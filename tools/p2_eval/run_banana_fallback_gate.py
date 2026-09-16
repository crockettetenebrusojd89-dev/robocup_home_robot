#!/usr/bin/env python3
"""Validate one fixed, truth-independent close-range banana fallback pose."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any, Mapping

from p2_eval_core import EvaluationConfigError
from run_18_class_robustness_audit import analyze
from run_tabletop_robustness_gate import _read_json
from run_tabletop_robustness_gate import _write_json
from run_tabletop_robustness_gate import capture
from run_tabletop_robustness_gate import create_gate_world


FALLBACK_POSE = {"index": 3, "x": -3.300, "y": -1.800, "yaw": -1.723}
YAW_SAMPLES = 24
FORMAL_CONFIDENCE = 0.50
PROBLEM_IDS = frozenset(f"banana_{index:02d}" for index in range(7, 16))


def write_capture_plan(path: Path, placements: list[Mapping[str, Any]]) -> None:
    """Write a fallback-only plan using the untouched external placements."""
    lines = [
        "WORLD robocup_home p2_gate_camera",
        f"YAW_SAMPLES {YAW_SAMPLES}",
        "VIEW {index} {x:.12f} {y:.12f} {yaw:.12f}".format(**FALLBACK_POSE),
        "HIDE p2_gate_banana",
        "HIDE p2_gate_coke_can",
    ]
    for item in placements:
        lines.append(
            "PLACEMENT {id} {class_name} {entity_name} {gazebo_label} "
            "{local_x:.12f} {local_y:.12f} {world_x:.12f} "
            "{world_y:.12f} {world_z:.12f} {world_yaw:.12f} {region}".format(
                **item
            )
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-world", required=True, type=Path)
    parser.add_argument("--source-design", required=True, type=Path)
    parser.add_argument("--class-manifest", required=True, type=Path)
    parser.add_argument("--model-resources", required=True, type=Path)
    parser.add_argument("--model", required=True, type=Path)
    parser.add_argument("--baseline-summary", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--device", default="0")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output = args.output.expanduser().resolve()
    if output.exists():
        raise EvaluationConfigError(f"output already exists: {output}")
    source_design = _read_json(args.source_design.expanduser().resolve())
    class_document = _read_json(args.class_manifest.expanduser().resolve())
    classes = [item["name"] for item in class_document["classes"]]
    labels = {
        item["name"]: int(item["gazebo_label"])
        for item in class_document["classes"]
    }
    placements = [
        item for item in source_design["placements"]
        if item["class_name"] == "banana"
    ]
    if len(placements) != 15:
        raise EvaluationConfigError("source design must have 15 banana placements")
    if len({round(item["world_yaw"], 9) for item in placements}) != 1:
        raise EvaluationConfigError("external banana yaw is not frozen")
    output.mkdir(parents=True)
    design = {
        "schema_version": 1,
        "selection_contract": (
            "One fixed pose chosen from known table geometry and static map; "
            "no object ground truth is used by the runtime condition."
        ),
        "fallback_pose": FALLBACK_POSE,
        "yaw_samples": YAW_SAMPLES,
        "formal_confidence": FORMAL_CONFIDENCE,
        "source_design": str(args.source_design.expanduser().resolve()),
        "placements": placements,
    }
    _write_json(output / "design.json", design)
    world = output / "fallback.world"
    create_gate_world(
        args.source_world.expanduser().resolve(), world, classes, labels
    )
    plan = output / "capture_plan.tsv"
    write_capture_plan(plan, placements)
    capture(
        world,
        plan,
        output,
        Path(__file__).with_name("tabletop_gate_capture_worker.cpp"),
        args.model_resources.expanduser().resolve(),
    )
    detector_output = output / "detector"
    detector_output.mkdir()
    fallback = analyze(
        output / "frames.tsv",
        args.model.expanduser().resolve(),
        args.device,
        detector_output,
        ["banana"],
    )["classes"]["banana"]
    baseline = _read_json(
        args.baseline_summary.expanduser().resolve()
    )["classes"]["banana"]
    baseline_ids = {
        item["placement_id"] for item in baseline["placements"]
        if item["detected"]
    }
    fallback_ids = {
        item["placement_id"] for item in fallback["placements"]
        if item["detected"]
    }
    combined_ids = baseline_ids | fallback_ids
    pose_x, pose_y = FALLBACK_POSE["x"], FALLBACK_POSE["y"]
    distances = [
        math.hypot(item["world_x"] - pose_x, item["world_y"] - pose_y)
        for item in placements
    ]
    summary = {
        "schema_version": 1,
        "fallback_pose": FALLBACK_POSE,
        "fallback_distance_m": {
            "minimum": min(distances),
            "median": sorted(distances)[len(distances) // 2],
            "maximum": max(distances),
        },
        "fallback_only_success": len(fallback_ids),
        "fallback_only_problem_success": len(fallback_ids & PROBLEM_IDS),
        "p1_p2_baseline_success": len(baseline_ids),
        "p1_p2_baseline_problem_success": len(baseline_ids & PROBLEM_IDS),
        "combined_success": len(combined_ids),
        "combined_problem_success": len(combined_ids & PROBLEM_IDS),
        "newly_recovered_placements": sorted(fallback_ids - baseline_ids),
        "fallback_detector_summary": str(detector_output / "summary.json"),
        "isolation": (
            "The fixed fallback pose was selected before capture from table "
            "geometry and the static occupancy map. External placement truth "
            "is used only after RGB inference for scoring."
        ),
    }
    _write_json(output / "summary.json", summary)
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, ValueError) as error:
        print(f"BANANA_FALLBACK_GATE_FAILED: {error}")
        raise SystemExit(1)
