#!/usr/bin/env python3
"""Build a small, read-only runtime-like detector-FN audit from saved evidence.

This deliberately reuses the Final Scoring Gate's offline frame records.  It
does not launch Gazebo, alter runtime decisions, or generate/training data.
One low-threshold model inference is made only for the selected best-opportunity
frame of each already-audited detector-evidence FN, so a wrong-class box can be
distinguished from absence of a target-class box.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
import math
from pathlib import Path
import statistics
from typing import Any

import cv2
from ultralytics import YOLO


ROOT_NAME = "final_scoring_gate_20260916"
DEFAULT_EVIDENCE = Path("/home/hao/robocup_assets/p2_eval") / ROOT_NAME
DEFAULT_DATASET = Path("/home/hao/robocup_assets/datasets/formal_objects_v2")
DEFAULT_TARGETED_METADATA = Path(
    "/home/hao/robocup_assets/datasets/formal_objects_v2_targeted_20260915/"
    "scenario_manifest.jsonl"
)
DEFAULT_MODEL = Path(
    "/home/hao/robocup_assets/training_runs/"
    "formal_objects_v2_yolo11n_finetune/weights/epoch30.pt"
)

# These are exactly the 11 detector-evidence FNs established by the Final
# Scoring Gate and the low-confidence audit.  The prior class is evidence, not
# a newly inferred label: A/B have correct-class diagnostic signal, C did not.
DETECTOR_FNS = (
    ("normal_apple_beer_coke", "beer", "C", "TYPE 3"),
    ("normal_apple_bowl_mustard", "mustard_bottle", "C", "TYPE 3"),
    ("normal_beer_pudding_windex", "beer", "C", "TYPE 3"),
    ("normal_beer_pudding_windex", "pudding_box", "C", "TYPE 2"),
    ("danger_master_tomato_apple", "master_chef_can", "A", "TYPE 1"),
    ("banana_apple_beer", "banana", "A", "TYPE 1"),
    ("banana_apple_beer", "beer", "C", "TYPE 2"),
    ("banana_coke_bowl", "banana", "A", "TYPE 4"),
    ("banana_coke_bowl", "bowl", "B", "TYPE 1"),
    ("banana_mustard_windex", "banana", "A", "TYPE 1"),
    ("banana_mustard_windex", "mustard_bottle", "C", "TYPE 2"),
)
CONTROLS = ("apple", "coke_can", "tomato_soup_can", "windex_bottle")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()]


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_jsonl(path: Path, values: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as stream:
        for value in values:
            stream.write(json.dumps(value, sort_keys=True) + "\n")


def finite_projection(frame: dict[str, Any], target: str) -> bool:
    item = frame["targets"][target]
    projection = item.get("projection") or {}
    return bool(item.get("projected_center_in_frame") and all(
        math.isfinite(float(projection.get(key, math.nan)))
        for key in ("u", "v", "depth_m")
    ))


def association(box: dict[str, Any], projection: dict[str, Any] | None) -> bool:
    """Use the same projection association as analyze_visibility.py."""
    if projection is None:
        return False
    u, v = float(projection["u"]), float(projection["v"])
    if not (math.isfinite(u) and math.isfinite(v)):
        return False
    x1, y1, x2, y2 = (float(value) for value in box["bbox_xyxy"])
    width = x2 - x1
    height = y2 - y1
    return (
        x1 - max(30.0, 0.75 * width) <= u <= x2 + max(30.0, 0.75 * width)
        and y1 - max(60.0, 1.5 * height) <= v <= y2 + max(60.0, 1.5 * height)
    )


def box_record(class_name: str, confidence: float, xyxy: list[float]) -> dict[str, Any]:
    x1, y1, x2, y2 = (float(value) for value in xyxy)
    width, height = x2 - x1, y2 - y1
    return {
        "class_name": class_name,
        "confidence": float(confidence),
        "bbox_xyxy": [x1, y1, x2, y2],
        "bbox_width_px": width,
        "bbox_height_px": height,
        "bbox_area_px2": width * height,
    }


def result_frames(evidence: Path, source: str) -> list[dict[str, Any]]:
    path = evidence / f"result_{source}" / "run_01/offline/offline_frames.jsonl"
    if not path.is_file():
        raise FileNotFoundError(path)
    return read_jsonl(path)


def select_frame(frames: list[dict[str, Any]], target: str) -> dict[str, Any]:
    visible = [frame for frame in frames if finite_projection(frame, target)]
    if not visible:
        raise ValueError(f"no projected-in-frame opportunity for {target}")
    candidates = [frame for frame in visible if frame["targets"][target].get("best_box")]
    # The existing all-frame diagnostic maximum is the most informative raw
    # review image.  For absent cases select the nearest visible opportunity.
    if candidates:
        return max(candidates, key=lambda frame: float(
            frame["targets"][target]["best_box"]["confidence"]
        ))
    return min(visible, key=lambda frame: float(
        frame["targets"][target]["projection"]["depth_m"]
    ))


def raw_predictions(model: YOLO, frame: dict[str, Any], target: str) -> list[dict[str, Any]]:
    image = cv2.imread(frame["path"])
    if image is None:
        raise OSError(f"could not read {frame['path']}")
    result = model.predict(source=image, conf=0.001, device="cpu", verbose=False)[0]
    projection = frame["targets"][target].get("projection")
    values = []
    for box in result.boxes or []:
        class_id = int(box.cls[0].item())
        candidate = box_record(
            str(result.names[class_id]), float(box.conf[0].item()),
            [float(value) for value in box.xyxy[0].tolist()],
        )
        if association(candidate, projection):
            values.append(candidate)
    return sorted(values, key=lambda value: value["confidence"], reverse=True)


def stats(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"count": 0, "min": None, "median": None, "mean": None, "max": None}
    return {
        "count": len(values),
        "min": min(values),
        "median": statistics.median(values),
        "mean": statistics.fmean(values),
        "max": max(values),
    }


def quantile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return math.nan
    position = (len(ordered) - 1) * fraction
    low, high = math.floor(position), math.ceil(position)
    if low == high:
        return ordered[low]
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def synthetic_stats(dataset: Path, class_names: set[str]) -> dict[str, Any]:
    classes = read_json(dataset / "classes.json")
    if isinstance(classes, dict):
        entries = classes.get("classes")
        if isinstance(entries, list):
            id_to_name = {
                int(entry["yolo_id"]): str(entry["name"])
                for entry in entries
            }
        else:
            id_to_name = {int(key): str(value) for key, value in classes.items()}
    else:
        id_to_name = {index: str(name) for index, name in enumerate(classes)}
    output: dict[str, list[dict[str, float]]] = defaultdict(list)
    for item in read_jsonl(dataset / "dataset_composition_manifest.jsonl"):
        if item.get("split") != "val":
            continue
        image = cv2.imread(str(dataset / item["image_path"]))
        if image is None:
            raise OSError(item["image_path"])
        height, width = image.shape[:2]
        for line in (dataset / item["label_path"]).read_text(encoding="utf-8").splitlines():
            fields = line.split()
            if len(fields) != 5:
                continue
            class_name = id_to_name[int(fields[0])]
            if class_name not in class_names:
                continue
            box_width = float(fields[3]) * width
            box_height = float(fields[4]) * height
            output[class_name].append({
                "width_px": box_width,
                "height_px": box_height,
                "short_side_px": min(box_width, box_height),
                "area_px2": box_width * box_height,
                "aspect_ratio": max(box_width, box_height) / max(1e-9, min(box_width, box_height)),
            })
    return {
        name: {
            "instances": len(values),
            "width_px": stats([entry["width_px"] for entry in values]),
            "height_px": stats([entry["height_px"] for entry in values]),
            "short_side_px": stats([entry["short_side_px"] for entry in values]),
            "area_px2": stats([entry["area_px2"] for entry in values]),
            "aspect_ratio": stats([entry["aspect_ratio"] for entry in values]),
        }
        for name, values in sorted(output.items())
    }


def runtime_control_stats(evidence: Path) -> dict[str, Any]:
    """Summarize a few strong classes from saved, already-inferred frames."""
    observations: dict[str, list[dict[str, Any]]] = defaultdict(list)
    visible_counts: Counter[str] = Counter()
    formal_counts: Counter[str] = Counter()
    for offline_path in sorted(evidence.glob("result_*/run_01/offline/offline_frames.jsonl")):
        for frame in read_jsonl(offline_path):
            for target in CONTROLS:
                if target not in frame.get("targets", {}) or not finite_projection(frame, target):
                    continue
                visible_counts[target] += 1
                item = frame["targets"][target]
                if item.get("above_decision_threshold"):
                    formal_counts[target] += 1
                box = item.get("best_box")
                if box is None:
                    continue
                observations[target].append({
                    "short_side_px": min(float(box["bbox_width_px"]), float(box["bbox_height_px"])),
                    "confidence": float(box["confidence"]),
                    "depth_m": float(item["projection"]["depth_m"]),
                })
    return {
        target: {
            "visible_frames": visible_counts[target],
            "formal_above_050_frames": formal_counts[target],
            "formal_frame_recall": (
                formal_counts[target] / visible_counts[target]
                if visible_counts[target] else None
            ),
            "candidate_short_side_px": stats([
                entry["short_side_px"] for entry in observations[target]
            ]),
            "candidate_distance_m": stats([
                entry["depth_m"] for entry in observations[target]
            ]),
        }
        for target in CONTROLS
    }


def targeted_synthetic_metadata(
    manifest_path: Path, class_names: set[str]
) -> dict[str, Any]:
    """Expose the generated V2 targeted subset's known camera/yaw coverage."""
    collected: dict[str, dict[str, Any]] = {
        name: {"distances": [], "yaws": [], "short_sides": [], "backgrounds": Counter(),
               "lighting": Counter(), "object_counts": []}
        for name in class_names
    }
    for item in read_jsonl(manifest_path):
        if item.get("split") != "val":
            continue
        bbox_names = {str(box["class_name"]) for box in item.get("bboxes", [])}
        for class_name in bbox_names & class_names:
            record = collected[class_name]
            record["backgrounds"][str(item["background"]["id"])] += 1
            record["lighting"][str(item["lighting"]["profile_id"])] += 1
            record["object_counts"].append(len(item.get("bboxes", [])))
            for box in item.get("bboxes", []):
                if str(box["class_name"]) == class_name:
                    record["short_sides"].append(min(
                        float(box["width"]) * 640.0,
                        float(box["height"]) * 480.0,
                    ))
            primary = item.get("primary") or {}
            if str(primary.get("class_name")) == class_name:
                record["distances"].append(float(item["camera"]["object_distance_m"]))
                record["yaws"].append(float(primary["yaw_deg"]))
    return {
        name: {
            "samples": len(record["object_counts"]),
            "primary_distance_m": stats(record["distances"]),
            "primary_yaw_deg": stats(record["yaws"]),
            "label_short_side_px": stats(record["short_sides"]),
            "objects_per_image": stats(record["object_counts"]),
            "backgrounds": dict(sorted(record["backgrounds"].items())),
            "lighting_profiles": dict(sorted(record["lighting"].items())),
        }
        for name, record in sorted(collected.items())
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence", type=Path, default=DEFAULT_EVIDENCE)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--targeted-metadata", type=Path, default=DEFAULT_TARGETED_METADATA)
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.output_dir.exists():
        raise SystemExit(f"refusing to overwrite existing output: {args.output_dir}")
    if not args.model.is_file():
        raise SystemExit(f"missing model: {args.model}")
    args.output_dir.mkdir(parents=True)

    cache = {source: result_frames(args.evidence, source)
             for source, _, _, _ in DETECTOR_FNS}
    model = YOLO(str(args.model))
    selected = []
    all_candidate_observations: list[dict[str, Any]] = []
    for index, (source, target, prior, primary_taxonomy) in enumerate(
        DETECTOR_FNS, start=1
    ):
        frames = cache[source]
        visible = [frame for frame in frames if finite_projection(frame, target)]
        candidates = [frame for frame in visible if frame["targets"][target].get("best_box")]
        exact = [frame for frame in visible if frame["targets"][target].get("exact_best_box")]
        for frame in candidates:
            box = frame["targets"][target]["best_box"]
            all_candidate_observations.append({
                "target": target,
                "confidence": float(box["confidence"]),
                "short_side_px": min(float(box["bbox_width_px"]), float(box["bbox_height_px"])),
                "depth_m": float(frame["targets"][target]["projection"]["depth_m"]),
                "above_050": bool(frame["targets"][target]["above_decision_threshold"]),
            })
        frame = select_frame(frames, target)
        item = frame["targets"][target]
        predictions = raw_predictions(model, frame, target)
        max_target_confidence = max(
            [float(other["targets"][target]["best_box"]["confidence"])
             for other in candidates], default=0.0,
        )
        above_050_count = sum(int(other["targets"][target]["exact_detection_count"])
                              for other in exact)
        taxonomy_labels = {
            "TYPE 1": "correct class below 0.50",
            "TYPE 2": "wrong-class box at representative opportunity",
            "TYPE 3": "no meaningful detection",
            "TYPE 4": "one-or-more correct >=0.50 boxes, but temporally insufficient",
        }
        selected.append({
            "audit_id": f"fn_{index:02d}",
            "class_name": target,
            "source_run": source,
            "prior_low_confidence_audit_class": prior,
            "viewpoint": f"P{int(frame.get('viewpoint_index', 0))}",
            "scan_step": frame.get("step"),
            "camera_yaw_deg": round(math.degrees(float(frame["robot_yaw_rad"])), 3),
            "relative_object_yaw": "unavailable: world object yaw was not retained",
            "image_path": frame["path"],
            "projection": item["projection"],
            "visible_frame_count": len(visible),
            "correct_class_candidate_frame_count": len(candidates),
            "correct_class_above_050_box_count": above_050_count,
            "max_correct_class_confidence_all_visible_frames": max_target_confidence,
            "detector_proxy_bbox": item.get("best_box"),
            "gt_bbox": "unavailable: Final Gate retained point projection, not 2-D labels",
            "raw_associated_predictions_at_0.001": predictions,
            "taxonomy": f"{primary_taxonomy}: {taxonomy_labels[primary_taxonomy]}",
        })

    synthetic = synthetic_stats(
        args.dataset, {item[1] for item in DETECTOR_FNS} | set(CONTROLS)
    )
    targeted_metadata = targeted_synthetic_metadata(
        args.targeted_metadata, {item[1] for item in DETECTOR_FNS} | set(CONTROLS)
    )
    short_sides = [entry["short_side_px"] for entry in all_candidate_observations]
    q1, q2, q3 = (quantile(short_sides, fraction) for fraction in (0.25, 0.50, 0.75))
    bins = [
        ("very_small", -math.inf, q1), ("small", q1, q2),
        ("medium", q2, q3), ("large", q3, math.inf),
    ]
    pixel_bins = {}
    for name, low, high in bins:
        values = [entry for entry in all_candidate_observations
                  if low <= entry["short_side_px"] <= high]
        pixel_bins[name] = {
            "short_side_range_px": [low if math.isfinite(low) else None,
                                    high if math.isfinite(high) else None],
            "candidate_frames": len(values),
            "formal_above_050_frames": sum(entry["above_050"] for entry in values),
            "median_confidence": statistics.median([entry["confidence"] for entry in values]) if values else None,
            "median_distance_m": statistics.median([entry["depth_m"] for entry in values]) if values else None,
        }
    weak_runtime_by_class = {
        class_name: {
            "candidate_frames": sum(entry["target"] == class_name for entry in all_candidate_observations),
            "formal_above_050_frames": sum(
                entry["target"] == class_name and entry["above_050"]
                for entry in all_candidate_observations
            ),
            "candidate_short_side_px": stats([
                entry["short_side_px"] for entry in all_candidate_observations
                if entry["target"] == class_name
            ]),
            "candidate_distance_m": stats([
                entry["depth_m"] for entry in all_candidate_observations
                if entry["target"] == class_name
            ]),
            "candidate_confidence": stats([
                entry["confidence"] for entry in all_candidate_observations
                if entry["target"] == class_name
            ]),
        }
        for class_name in sorted({entry["target"] for entry in all_candidate_observations})
    }
    taxonomy_counts = Counter(item["taxonomy"].split(":", 1)[0] for item in selected)
    summary = {
        "scope": "11 Final-Scoring-Gate detector-evidence FN; no Gazebo rerun and no runtime edit",
        "model": str(args.model),
        "formal_confidence": 0.50,
        "raw_review_confidence": 0.001,
        "selected_fn_count": len(selected),
        "taxonomy_counts": dict(sorted(taxonomy_counts.items())),
        "per_class": {
            class_name: {
                "fn_instances": sum(item["class_name"] == class_name for item in selected),
                "correct_signal_instances": sum(
                    item["class_name"] == class_name
                    and item["max_correct_class_confidence_all_visible_frames"] > 0.001
                    for item in selected
                ),
                "formal_050_signal_instances": sum(
                    item["class_name"] == class_name
                    and item["correct_class_above_050_box_count"] > 0
                    for item in selected
                ),
                "max_confidence": stats([
                    item["max_correct_class_confidence_all_visible_frames"]
                    for item in selected if item["class_name"] == class_name
                ]),
            }
            for class_name in sorted({item["class_name"] for item in selected})
        },
        "runtime_candidate_proxy": {
            "note": "Only correct-class diagnostic boxes are measurable. No-box cases have no defensible 2-D size.",
            "short_side_px": stats(short_sides),
            "distance_m": stats([entry["depth_m"] for entry in all_candidate_observations]),
            "pixel_bins": pixel_bins,
        },
        "weak_runtime_by_class": weak_runtime_by_class,
        "runtime_controls": runtime_control_stats(args.evidence),
        "synthetic_validation_bbox_distribution": synthetic,
        "targeted_synthetic_metadata": targeted_metadata,
        "limitations": [
            "Runtime GT 2-D boxes and object yaw/occlusion labels were not retained.",
            "Wrong-class review is one selected maximum-opportunity frame per FN, not a new exhaustive inference sweep.",
            "Detector proxy boxes are model boxes, not GT silhouettes; no-box runtime pixel scale is unavailable.",
        ],
    }
    write_jsonl(args.output_dir / "weak_class_runtime_manifest.jsonl", selected)
    write_json(args.output_dir / "weak_class_runtime_summary.json", summary)
    print(json.dumps({
        "selected_fn_count": len(selected),
        "taxonomy_counts": summary["taxonomy_counts"],
        "output_dir": str(args.output_dir),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
