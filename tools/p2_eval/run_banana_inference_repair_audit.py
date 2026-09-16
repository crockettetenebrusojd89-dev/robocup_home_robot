#!/usr/bin/env python3
"""Replay banana external RGB for tiled inference and candidate tracking."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import time
from typing import Any, Mapping, Sequence

import cv2
from ultralytics import YOLO

from p2_eval_core import EvaluationConfigError
from run_18_class_robustness_audit import _all_boxes
from run_18_class_robustness_audit import _box_iou
from run_tabletop_robustness_gate import _associated
from run_tabletop_robustness_gate import _distribution
from run_tabletop_robustness_gate import _manifest_records


FORMAL_CONFIDENCE = 0.50
DIAGNOSTIC_CONFIDENCE = 0.001
IMAGE_SIZE = 640
NMS_IOU = 0.70
TILE_OVERLAP = 0.20
CANDIDATE_THRESHOLDS = (0.10, 0.15, 0.20)
MIN_CONFIRMATIONS = 3
FINAL_MIN_CONFIRMATIONS = 5
PROBLEM_DISTANCE_M = 1.98
VIEWPOINTS = ((-3.485, -1.115), (0.265, -0.665))


def sha256_file(path: Path) -> str:
    """Return the SHA256 identity of one checkpoint."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def tile_windows(
    width: int, height: int, overlap: float = TILE_OVERLAP
) -> tuple[tuple[int, int, int, int], ...]:
    """Return deterministic 2x2 crop windows with fractional overlap."""
    if width < 2 or height < 2:
        raise ValueError("image must be at least 2x2")
    if not 0.0 <= overlap < 1.0:
        raise ValueError("tile overlap must be in [0, 1)")
    tile_width = min(width, int(math.ceil(width / (2.0 - overlap))))
    tile_height = min(height, int(math.ceil(height / (2.0 - overlap))))
    x_starts = (0, width - tile_width)
    y_starts = (0, height - tile_height)
    return tuple(
        (x, y, x + tile_width, y + tile_height)
        for y in y_starts for x in x_starts
    )


def same_class_nms(
    boxes: Sequence[Mapping[str, Any]], threshold: float = NMS_IOU
) -> list[dict[str, Any]]:
    """Merge duplicate same-class boxes produced by overlapping tiles."""
    retained: list[dict[str, Any]] = []
    for box in sorted(boxes, key=lambda item: item["confidence"], reverse=True):
        if any(
            box["class_name"] == other["class_name"]
            and _box_iou(box, other) >= threshold
            for other in retained
        ):
            continue
        retained.append(dict(box))
    return retained


def map_tile_boxes(
    result, window: tuple[int, int, int, int]
) -> list[dict[str, Any]]:
    """Map one crop's boxes back into full-frame pixel coordinates."""
    offset_x, offset_y, _, _ = window
    mapped = []
    for box in _all_boxes(result):
        x1, y1, x2, y2 = box["bbox_xyxy"]
        x1 += offset_x
        x2 += offset_x
        y1 += offset_y
        y2 += offset_y
        mapped.append({
            **box,
            "bbox_xyxy": [x1, y1, x2, y2],
            "bbox_width_px": x2 - x1,
            "bbox_height_px": y2 - y1,
            "bbox_area_px2": (x2 - x1) * (y2 - y1),
        })
    return mapped


def nearest_viewpoint_distance(record: Mapping[str, Any]) -> float:
    """Return the frozen P1/P2 planar distance for one placement."""
    return min(
        math.hypot(record["world_x"] - x, record["world_y"] - y)
        for x, y in VIEWPOINTS
    )


def truth_box(record: Mapping[str, Any]) -> list[float] | None:
    """Return a visible truth box, used only after detector inference."""
    if not record["truth_visible"]:
        return None
    return [
        record["truth_x1"], record["truth_y1"],
        record["truth_x2"], record["truth_y2"],
    ]


def infer_full(model, image_path: str, device: str):
    """Run the unchanged full-frame epoch31 inference contract."""
    started = time.perf_counter()
    result = model.predict(
        source=image_path,
        conf=DIAGNOSTIC_CONFIDENCE,
        device=device,
        imgsz=IMAGE_SIZE,
        iou=NMS_IOU,
        verbose=False,
    )[0]
    return _all_boxes(result), (time.perf_counter() - started) * 1000.0


def infer_tiled(model, image_path: str, device: str):
    """Run four overlapping crops at 640 and merge in full-frame space."""
    started = time.perf_counter()
    image = cv2.imread(image_path, cv2.IMREAD_COLOR)
    if image is None:
        raise EvaluationConfigError(f"could not read RGB frame: {image_path}")
    height, width = image.shape[:2]
    windows = tile_windows(width, height)
    crops = [image[y1:y2, x1:x2] for x1, y1, x2, y2 in windows]
    results = model.predict(
        source=crops,
        conf=DIAGNOSTIC_CONFIDENCE,
        device=device,
        imgsz=IMAGE_SIZE,
        iou=NMS_IOU,
        verbose=False,
    )
    boxes = []
    for result, window in zip(results, windows):
        boxes.extend(map_tile_boxes(result, window))
    return same_class_nms(boxes), (time.perf_counter() - started) * 1000.0


def summarize_detector_mode(
    frame_results: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Score formal recall and raw/whitelisted FP for one inference mode."""
    placements: dict[str, dict[str, Any]] = {}
    latency = []
    for item in frame_results:
        record = item["record"]
        boxes = item["boxes"]
        truth = truth_box(record)
        formal = [
            box for box in boxes if box["confidence"] >= FORMAL_CONFIDENCE
        ]
        associated = _associated(formal, truth)
        correct = [
            box for box in associated if box["class_name"] == "banana"
        ]
        raw_fp = [box for box in formal if box not in correct]
        whitelist_fp = [
            box for box in raw_fp if box["class_name"] == "banana"
        ]
        entry = placements.setdefault(record["placement_id"], {
            "placement_id": record["placement_id"],
            "distance_m": nearest_viewpoint_distance(record),
            "correct_boxes": 0,
            "raw_fp_boxes": 0,
            "whitelist_fp_boxes": 0,
            "duplicate_frames": 0,
        })
        entry["correct_boxes"] += len(correct)
        entry["raw_fp_boxes"] += len(raw_fp)
        entry["whitelist_fp_boxes"] += len(whitelist_fp)
        entry["duplicate_frames"] += len(correct) > 1
        latency.append(item["latency_ms"])
    values = list(placements.values())
    detected = [item for item in values if item["correct_boxes"]]
    problem = [item for item in values if item["distance_m"] >= PROBLEM_DISTANCE_M]
    problem_detected = [item for item in problem if item["correct_boxes"]]
    return {
        "success_placements": len(detected),
        "placement_count": len(values),
        "problem_success_placements": len(problem_detected),
        "problem_placement_count": len(problem),
        "raw_fp_boxes": sum(item["raw_fp_boxes"] for item in values),
        "raw_fp_placements": sum(bool(item["raw_fp_boxes"]) for item in values),
        "whitelist_surviving_fp_boxes": sum(
            item["whitelist_fp_boxes"] for item in values
        ),
        "whitelist_surviving_fp_placements": sum(
            bool(item["whitelist_fp_boxes"]) for item in values
        ),
        "duplicate_box_frames": sum(item["duplicate_frames"] for item in values),
        "latency_ms_per_rgb_frame": _distribution(latency),
        "placements": values,
    }


def _candidate_replay(
    frame_results: Sequence[Mapping[str, Any]], threshold: float
) -> dict[str, Any]:
    """Replay target-only candidates using distinct saved scan frames."""
    placements: dict[str, dict[str, Any]] = {}
    for item in frame_results:
        record = item["record"]
        candidates = [
            box for box in item["boxes"]
            if box["class_name"] == "banana"
            and box["confidence"] >= threshold
        ]
        associated = _associated(candidates, truth_box(record))
        false_candidates = [box for box in candidates if box not in associated]
        entry = placements.setdefault(record["placement_id"], {
            "placement_id": record["placement_id"],
            "distance_m": nearest_viewpoint_distance(record),
            "target_candidate_frames": 0,
            "raw_candidate_fp_boxes": 0,
            "raw_candidate_fp_frames": 0,
        })
        entry["target_candidate_frames"] += bool(associated)
        entry["raw_candidate_fp_boxes"] += len(false_candidates)
        entry["raw_candidate_fp_frames"] += bool(false_candidates)
    values = list(placements.values())
    candidate = [item for item in values if item["target_candidate_frames"]]
    confirmed = [
        item for item in values
        if item["target_candidate_frames"] >= MIN_CONFIRMATIONS
    ]
    final = [
        item for item in values
        if item["target_candidate_frames"] >= FINAL_MIN_CONFIRMATIONS
    ]
    problem_final = [
        item for item in final if item["distance_m"] >= PROBLEM_DISTANCE_M
    ]
    fp_frames = sum(item["raw_candidate_fp_frames"] for item in values)
    fp_placements = sum(bool(item["raw_candidate_fp_boxes"]) for item in values)
    return {
        "threshold": threshold,
        "candidate_detected_placements": len(candidate),
        "confirmed_track_placements_at_3_distinct_frames": len(confirmed),
        "final_track_placements_at_5_distinct_frames": len(final),
        "problem_final_track_placements": len(problem_final),
        "problem_placement_count": sum(
            item["distance_m"] >= PROBLEM_DISTANCE_M for item in values
        ),
        "raw_candidate_fp_boxes": sum(
            item["raw_candidate_fp_boxes"] for item in values
        ),
        "raw_candidate_fp_frames": fp_frames,
        "raw_candidate_fp_placements": fp_placements,
        "strict_confirmed_fp_placements": sum(
            item["raw_candidate_fp_frames"] >= MIN_CONFIRMATIONS
            for item in values
        ),
        "strict_final_fp_placements": sum(
            item["raw_candidate_fp_frames"] >= FINAL_MIN_CONFIRMATIONS
            for item in values
        ),
        "dwell_amplified_final_fp_risk_placements": fp_placements,
        "replay_limit": (
            "Saved evidence has one RGB frame per scan yaw and no depth image. "
            "Distinct-frame counts are a strict temporal proxy. During the "
            "real 2 s dwell, one repeatable FP can be inferred about ten times, "
            "so every placement with a raw candidate FP is also reported as a "
            "conservative possible final-output risk."
        ),
        "placements": values,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--model", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--device", default="0")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    manifest = args.manifest.expanduser().resolve()
    model_path = args.model.expanduser().resolve()
    output = args.output.expanduser().resolve()
    if output.exists():
        raise EvaluationConfigError(f"output already exists: {output}")
    if not manifest.is_file() or not model_path.is_file():
        raise EvaluationConfigError("manifest and model must exist")
    records = [
        record for record in _manifest_records(manifest)
        if record["class_name"] == "banana"
    ]
    if len({record["placement_id"] for record in records}) != 15:
        raise EvaluationConfigError("expected exactly 15 banana placements")
    output.mkdir(parents=True)
    model = YOLO(str(model_path))
    full_results = []
    tiled_results = []
    for index, record in enumerate(records, start=1):
        boxes, latency = infer_full(model, record["image"], args.device)
        full_results.append({
            "record": record, "boxes": boxes, "latency_ms": latency,
        })
        boxes, latency = infer_tiled(model, record["image"], args.device)
        tiled_results.append({
            "record": record, "boxes": boxes, "latency_ms": latency,
        })
        if index % 100 == 0 or index == len(records):
            print(f"BANANA_REPLAY {index}/{len(records)}", flush=True)
    summary = {
        "schema_version": 1,
        "manifest": str(manifest),
        "model": str(model_path),
        "model_sha256": sha256_file(model_path),
        "formal_confidence": FORMAL_CONFIDENCE,
        "diagnostic_confidence": DIAGNOSTIC_CONFIDENCE,
        "image_size": IMAGE_SIZE,
        "tile_configuration": {
            "grid": "2x2",
            "overlap_fraction": TILE_OVERLAP,
            "same_class_merge_iou": NMS_IOU,
        },
        "full_frame": summarize_detector_mode(full_results),
        "tiled_2x2": summarize_detector_mode(tiled_results),
        "full_frame_candidate_replay": [
            _candidate_replay(full_results, threshold)
            for threshold in CANDIDATE_THRESHOLDS
        ],
        "isolation": (
            "YOLO saw only unchanged saved RGB frames. Truth boxes and world "
            "positions were read after inference for offline scoring only."
        ),
    }
    (output / "summary.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, ValueError) as error:
        print(f"BANANA_REPAIR_AUDIT_FAILED: {error}")
        raise SystemExit(1)
