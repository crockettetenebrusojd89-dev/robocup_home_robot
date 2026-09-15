#!/usr/bin/env python3
"""Run post-trial YOLO/geometry analysis on read-only P2 capture artifacts."""

from __future__ import annotations

import argparse
from collections import defaultdict
import json
import math
from pathlib import Path
import statistics
import sys
from typing import Any, Mapping

import cv2
import numpy as np
from ultralytics import YOLO


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            records.append(json.loads(line))
    return records


def _write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def _quaternion_matrix(rotation: Mapping[str, float]) -> np.ndarray:
    x = float(rotation["x"])
    y = float(rotation["y"])
    z = float(rotation["z"])
    w = float(rotation["w"])
    norm = math.sqrt(x * x + y * y + z * z + w * w)
    if norm == 0.0:
        raise ValueError("zero-length transform quaternion")
    x, y, z, w = x / norm, y / norm, z / norm, w / norm
    return np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
    ])


def project_map_point(
    point: Mapping[str, float],
    map_to_camera: Mapping[str, Any] | None,
    camera_info: Mapping[str, Any],
) -> dict[str, float] | None:
    """Project a map point with a recorded camera->map TF transform."""
    if not map_to_camera:
        return None
    translation = map_to_camera["translation"]
    camera_in_map = np.array([
        translation["x"], translation["y"], translation["z"]
    ], dtype=float)
    point_map = np.array([point["x"], point["y"], point["z"]], dtype=float)
    camera_to_map = _quaternion_matrix(map_to_camera["rotation"])
    point_camera = camera_to_map.T @ (point_map - camera_in_map)
    depth = float(point_camera[2])
    if depth <= 0.0:
        return {"u": math.nan, "v": math.nan, "depth_m": depth}
    k = camera_info["k"]
    return {
        "u": float(k[0] * point_camera[0] / depth + k[2]),
        "v": float(k[4] * point_camera[1] / depth + k[5]),
        "depth_m": depth,
    }


def _target_boxes(result, target: str) -> list[dict[str, Any]]:
    boxes = result.boxes
    if boxes is None:
        return []
    target_boxes = []
    for box in boxes:
        class_id = int(box.cls[0].item())
        class_name = str(result.names[class_id])
        if class_name != target:
            continue
        confidence = float(box.conf[0].item())
        x1, y1, x2, y2 = (float(value) for value in box.xyxy[0].tolist())
        candidate = {
            "confidence": confidence,
            "bbox_xyxy": [x1, y1, x2, y2],
            "bbox_width_px": x2 - x1,
            "bbox_height_px": y2 - y1,
            "bbox_area_px2": (x2 - x1) * (y2 - y1),
        }
        target_boxes.append(candidate)
    return sorted(target_boxes, key=lambda item: item["confidence"], reverse=True)


def _unique_raw_frames(manifest: list[dict[str, Any]]):
    frames: dict[int, dict[str, Any]] = {}
    priority = {"raw_periodic": 1, "runtime_raw": 2}
    for record in manifest:
        if record.get("kind") not in priority:
            continue
        stamp = int(record["stamp_ns"])
        current = frames.get(stamp)
        if current is None or priority[record["kind"]] > priority[current["kind"]]:
            frames[stamp] = dict(record)
    runtime_stamps = {
        int(record["stamp_ns"])
        for record in manifest
        if record.get("kind") == "runtime_annotated"
    }
    for stamp, record in frames.items():
        record["runtime_sampled"] = stamp in runtime_stamps
    return [frames[stamp] for stamp in sorted(frames)], runtime_stamps


def _fill_nearest_transforms(frames: list[dict[str, Any]]) -> None:
    """Fill occasional sidecar TF misses from a nearby frame in the same step."""
    for key in ("map_to_camera", "map_to_base"):
        available = [
            frame for frame in frames if frame.get(key) is not None
        ]
        for frame in frames:
            if frame.get(key) is not None:
                continue
            candidates = [
                other for other in available
                if other.get("step") == frame.get("step")
                and abs(int(other["stamp_ns"]) - int(frame["stamp_ns"]))
                <= 250_000_000
            ]
            if not candidates:
                continue
            nearest = min(
                candidates,
                key=lambda other: abs(
                    int(other["stamp_ns"]) - int(frame["stamp_ns"])
                ),
            )
            frame[key] = nearest[key]
            frame[f"{key}_imputed_from_stamp_ns"] = int(nearest["stamp_ns"])
            if key == "map_to_base" and nearest.get("robot_yaw_rad") is not None:
                frame["robot_yaw_rad"] = nearest["robot_yaw_rad"]


def _box_matches_projection(
    box: Mapping[str, Any], projection: Mapping[str, float] | None
) -> bool:
    """Associate one class box with the one known post-trial target instance."""
    if (
        not projection
        or not math.isfinite(projection["u"])
        or not math.isfinite(projection["v"])
    ):
        return False
    x1, y1, x2, y2 = box["bbox_xyxy"]
    # Metadata z is the spawned model origin, not a semantic bbox center.
    # Keep horizontal association tighter while allowing the projected origin
    # to sit vertically outside a small object's 2-D box.
    margin_x = max(30.0, 0.75 * float(box["bbox_width_px"]))
    margin_y = max(60.0, 1.5 * float(box["bbox_height_px"]))
    return (
        x1 - margin_x <= projection["u"] <= x2 + margin_x
        and y1 - margin_y <= projection["v"] <= y2 + margin_y
    )


def _confidence_stats(values: list[float]) -> dict[str, Any]:
    return {
        "candidate_frame_count": len(values),
        "maximum": max(values) if values else None,
        "mean_over_candidate_frames": statistics.fmean(values) if values else None,
    }


def _bbox_stats(boxes: list[Mapping[str, Any]]) -> dict[str, Any]:
    if not boxes:
        return {
            "count": 0,
            "width_px_min_mean_max": None,
            "height_px_min_mean_max": None,
            "area_px2_min_mean_max": None,
        }

    def stats(key):
        values = [float(box[key]) for box in boxes]
        return [min(values), statistics.fmean(values), max(values)]
    return {
        "count": len(boxes),
        "width_px_min_mean_max": stats("bbox_width_px"),
        "height_px_min_mean_max": stats("bbox_height_px"),
        "area_px2_min_mean_max": stats("bbox_area_px2"),
    }


def _draw_frame(
    frame: Mapping[str, Any], target: str, threshold: float, size=(320, 240)
):
    image = cv2.imread(frame["path"])
    if image is None:
        return None
    projection = frame["targets"][target].get("projection")
    box = frame["targets"][target].get("best_box")
    if projection and math.isfinite(projection["u"]) and math.isfinite(projection["v"]):
        center = (int(round(projection["u"])), int(round(projection["v"])))
        cv2.drawMarker(image, center, (255, 0, 255), cv2.MARKER_CROSS, 24, 2)
    if box:
        x1, y1, x2, y2 = (int(round(value)) for value in box["bbox_xyxy"])
        color = (0, 220, 0) if box["confidence"] >= threshold else (0, 165, 255)
        cv2.rectangle(image, (x1, y1), (x2, y2), color, 2)
        cv2.putText(
            image,
            f"{target} {box['confidence']:.3f}",
            (max(0, x1), max(18, y1 - 4)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.52,
            color,
            2,
            cv2.LINE_AA,
        )
    yaw = frame.get("robot_yaw_rad")
    yaw_text = "?" if yaw is None else f"{math.degrees(yaw):.1f}deg"
    label = (
        f"step {frame.get('step')} {frame.get('phase')} yaw={yaw_text} "
        f"runtime={'Y' if frame.get('runtime_sampled') else 'N'}"
    )
    cv2.rectangle(image, (0, 0), (image.shape[1], 28), (0, 0, 0), -1)
    cv2.putText(
        image, label, (6, 19), cv2.FONT_HERSHEY_SIMPLEX, 0.48,
        (255, 255, 255), 1, cv2.LINE_AA,
    )
    return cv2.resize(image, size, interpolation=cv2.INTER_AREA)


def _contact_sheet(
    frames: list[dict[str, Any]],
    target: str,
    threshold: float,
    output_path: Path,
) -> None:
    selected = []
    by_step: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for frame in frames:
        step = int(frame.get("step", 0))
        if 1 <= step <= 12:
            by_step[step].append(frame)
    for step in range(1, 13):
        candidates = by_step.get(step, [])
        dwell = [item for item in candidates if item.get("phase") == "dwell"]
        pool = dwell or candidates
        if pool:
            selected.append(pool[len(pool) // 2])
    tiles = [
        tile for tile in (
            _draw_frame(frame, target, threshold) for frame in selected
        ) if tile is not None
    ]
    if not tiles:
        return
    columns = 4
    rows = math.ceil(len(tiles) / columns)
    blank = np.zeros_like(tiles[0])
    tiles.extend([blank] * (columns * rows - len(tiles)))
    sheet_rows = [
        np.hstack(tiles[index:index + columns])
        for index in range(0, len(tiles), columns)
    ]
    cv2.imwrite(str(output_path), np.vstack(sheet_rows))


def analyze_capture(
    capture_dir: Path,
    metadata_path: Path,
    model_path: Path,
    output_dir: Path,
    device: str = "cpu",
    decision_threshold: float = 0.50,
    confidence_floor: float = 0.001,
    model: YOLO | None = None,
) -> dict[str, Any]:
    """Analyze only after runtime exit; metadata is never read by capture/runtime."""
    output_dir.mkdir(parents=True, exist_ok=True)
    metadata = _read_json(metadata_path)
    camera_info = _read_json(capture_dir / "camera_info.json")
    manifest = _read_jsonl(capture_dir / "frames.jsonl")
    frames, runtime_stamps = _unique_raw_frames(manifest)
    _fill_nearest_transforms(frames)
    if model is None:
        model = YOLO(str(model_path))
    model_names = {int(key): str(value) for key, value in model.names.items()}
    targets = list(metadata["targets"])
    missing = [target for target in targets if target not in model_names.values()]
    if missing:
        raise ValueError(f"model lacks target classes: {missing}")
    truth_by_target = {
        item["class_name"]: item["world_position_m"]
        for item in metadata["objects"]
    }

    analyzed_frames = []
    for index, frame in enumerate(frames, start=1):
        image = cv2.imread(frame["path"])
        if image is None:
            raise OSError(f"could not read captured frame: {frame['path']}")
        exact_result = model.predict(
            source=image,
            conf=decision_threshold,
            device=device,
            verbose=False,
        )[0]
        diagnostic_result = model.predict(
            source=image,
            conf=confidence_floor,
            device=device,
            verbose=False,
        )[0]
        frame = dict(frame)
        frame["targets"] = {}
        for target in targets:
            projection = project_map_point(
                truth_by_target[target], frame.get("map_to_camera"), camera_info
            )
            projected_in_frame = bool(
                projection
                and projection["depth_m"] > 0.0
                and 0.0 <= projection["u"] < camera_info["width"]
                and 0.0 <= projection["v"] < camera_info["height"]
            )
            exact_class_boxes = _target_boxes(exact_result, target)
            diagnostic_class_boxes = _target_boxes(diagnostic_result, target)
            exact_boxes = [
                box for box in exact_class_boxes
                if _box_matches_projection(box, projection)
            ]
            diagnostic_boxes = [
                box for box in diagnostic_class_boxes
                if _box_matches_projection(box, projection)
            ]
            best = diagnostic_boxes[0] if diagnostic_boxes else None
            frame["targets"][target] = {
                "projection": projection,
                "projected_center_in_frame": projected_in_frame,
                "best_box": best,
                "exact_best_box": exact_boxes[0] if exact_boxes else None,
                "exact_detection_count": len(exact_boxes),
                "exact_class_detection_count": len(exact_class_boxes),
                "unassociated_exact_class_detection_count": (
                    len(exact_class_boxes) - len(exact_boxes)
                ),
                "above_decision_threshold": bool(exact_boxes),
            }
        analyzed_frames.append(frame)
        if index % 50 == 0 or index == len(frames):
            print(
                f"Offline inference {index}/{len(frames)} frames in {capture_dir}",
                flush=True,
            )

    frame_path = output_dir / "offline_frames.jsonl"
    with frame_path.open("w", encoding="utf-8") as stream:
        for frame in analyzed_frames:
            stream.write(json.dumps(frame, separators=(",", ":")) + "\n")

    telemetry_path = capture_dir.parent / "vision_telemetry.json"
    telemetry = _read_json(telemetry_path) if telemetry_path.is_file() else {}
    classes = {}
    for target in targets:
        all_boxes = [
            frame["targets"][target]["best_box"]
            for frame in analyzed_frames
            if frame["targets"][target]["best_box"] is not None
        ]
        sampled_frames = [
            frame for frame in analyzed_frames if frame["runtime_sampled"]
        ]
        sampled_boxes = [
            frame["targets"][target]["best_box"]
            for frame in sampled_frames
            if frame["targets"][target]["best_box"] is not None
        ]
        above = [
            frame for frame in analyzed_frames
            if frame["targets"][target]["above_decision_threshold"]
        ]
        sampled_above = [
            frame for frame in sampled_frames
            if frame["targets"][target]["above_decision_threshold"]
        ]
        projected = [
            frame for frame in analyzed_frames
            if frame["targets"][target]["projected_center_in_frame"]
        ]
        target_telemetry = telemetry.get("classes", {}).get(target, {})
        classes[target] = {
            "captured_frame_count": len(analyzed_frames),
            "runtime_sampled_frame_count": len(sampled_frames),
            "projected_center_in_frame_count": len(projected),
            "projected_center_steps": sorted({
                int(frame["step"]) for frame in projected
            }),
            "candidate_confidence_all_frames": _confidence_stats([
                float(box["confidence"]) for box in all_boxes
            ]),
            "candidate_confidence_runtime_frames": _confidence_stats([
                float(box["confidence"]) for box in sampled_boxes
            ]),
            "above_threshold_frame_count_all": len(above),
            "above_threshold_steps_all": sorted({
                int(frame["step"]) for frame in above
            }),
            "above_threshold_frame_count_runtime": len(sampled_above),
            "above_threshold_steps_runtime": sorted({
                int(frame["step"]) for frame in sampled_above
            }),
            "bbox_stats_all_candidate_frames": _bbox_stats(all_boxes),
            "bbox_stats_runtime_candidate_frames": _bbox_stats(sampled_boxes),
            "runtime_telemetry_detection_count": int(
                target_telemetry.get("detection_count", 0)
            ),
            "offline_above_threshold_boxes_on_runtime_frames": sum(
                frame["targets"][target]["exact_detection_count"]
                for frame in sampled_frames
            ),
            "offline_exact_class_boxes_on_runtime_frames": sum(
                frame["targets"][target]["exact_class_detection_count"]
                for frame in sampled_frames
            ),
            "offline_unassociated_exact_boxes_all_frames": sum(
                frame["targets"][target][
                    "unassociated_exact_class_detection_count"
                ]
                for frame in analyzed_frames
            ),
            "runtime_vs_offline_detection_consistent": (
                int(target_telemetry.get("detection_count", 0))
                == sum(
                    frame["targets"][target]["exact_class_detection_count"]
                    for frame in sampled_frames
                )
            ),
            "candidate_steps_all": sorted({
                int(frame["step"])
                for frame in analyzed_frames
                if frame["targets"][target]["best_box"] is not None
            }),
            "candidate_yaws_deg_all": sorted({
                round(math.degrees(float(frame["robot_yaw_rad"])), 1)
                for frame in analyzed_frames
                if frame.get("robot_yaw_rad") is not None
                and frame["targets"][target]["best_box"] is not None
            }),
        }
        _contact_sheet(
            analyzed_frames,
            target,
            decision_threshold,
            output_dir / f"contact_sheet_{target}.jpg",
        )

    summary = {
        "schema_version": 1,
        "analysis_boundary": (
            "scenario metadata and ground truth were opened only after the formal "
            "runtime and read-only capture process had exited"
        ),
        "world_to_map_projection_assumption": (
            "For visibility visualization only, scenario world points are treated "
            "as map points because this fixed scenario already scored in objects-only "
            "mode. Projection is supporting evidence, not scorer input."
        ),
        "model_path": str(model_path.resolve()),
        "model_names": model_names,
        "device": device,
        "decision_threshold": decision_threshold,
        "diagnostic_confidence_floor": confidence_floor,
        "confidence_note": (
            "Every frame is inferred once with the formal 0.50 confidence and "
            "again at a lower diagnostic floor. The latter exposes sub-threshold "
            "candidates but never affects runtime decisions."
        ),
        "captured_unique_raw_frames": len(analyzed_frames),
        "runtime_annotated_stamp_count": len(runtime_stamps),
        "runtime_raw_stamp_count": sum(
            bool(frame["runtime_sampled"]) for frame in analyzed_frames
        ),
        "runtime_raw_coverage": (
            sum(bool(frame["runtime_sampled"]) for frame in analyzed_frames)
            / len(runtime_stamps)
            if runtime_stamps else None
        ),
        "classes": classes,
        "artifacts": {
            "per_frame": str(frame_path.resolve()),
            "contact_sheets": {
                target: str((output_dir / f"contact_sheet_{target}.jpg").resolve())
                for target in targets
            },
        },
    }
    _write_json(output_dir / "offline_summary.json", summary)
    return summary


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture-dir", required=True, type=Path)
    parser.add_argument("--metadata", required=True, type=Path)
    parser.add_argument("--model", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--decision-threshold", type=float, default=0.50)
    parser.add_argument("--confidence-floor", type=float, default=0.001)
    args = parser.parse_args(argv)
    try:
        summary = analyze_capture(
            args.capture_dir,
            args.metadata,
            args.model,
            args.output_dir,
            args.device,
            args.decision_threshold,
            args.confidence_floor,
        )
        print(json.dumps(summary, indent=2))
        return 0
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"P2 visibility analysis failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
