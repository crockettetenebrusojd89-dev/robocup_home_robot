#!/usr/bin/env python3
"""Run the bounded four-class competition-room lighting detector gate."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sys
import time
from typing import Any, Mapping, Sequence
import xml.etree.ElementTree as ET

from p2_eval_core import EvaluationConfigError
from p2_eval_core import load_table_config
from run_18_class_robustness_audit import DIAGNOSTIC_CONFIDENCE
from run_18_class_robustness_audit import FORMAL_CONFIDENCE
from run_18_class_robustness_audit import VIEWPOINTS
from run_18_class_robustness_audit import _nearest_viewpoint_distance
from run_18_class_robustness_audit import analyze
from run_18_class_robustness_audit import create_audit_world
from run_18_class_robustness_audit import representative_specs
from run_18_class_robustness_audit import write_capture_plan
from run_tabletop_robustness_gate import _distribution
from run_tabletop_robustness_gate import _read_json
from run_tabletop_robustness_gate import _write_json
from run_tabletop_robustness_gate import capture


LIGHTING_CLASSES = (
    "banana", "beer", "master_chef_can", "coke_can",
)
PROFILE_ORDER = ("normal", "bright", "dim", "warm_side")
PROBLEM_YAWS_DEG = {
    "banana": 300.0,
    "beer": 315.0,
    "master_chef_can": 270.0,
    "coke_can": 270.0,
}
SEED = 20260915


def load_profiles(path: Path) -> dict[str, dict[str, Any]]:
    document = _read_json(path)
    profiles = {}
    for raw in document["lighting_profiles"]:
        profile_id = str(raw["id"])
        direction = [float(value) for value in raw["direction_xyz"]]
        length = math.sqrt(sum(value * value for value in direction))
        if length <= 0.0:
            raise EvaluationConfigError(
                f"lighting profile {profile_id} has zero direction"
            )
        profiles[profile_id] = {
            "profile_id": profile_id,
            "main_rgb": [float(value) for value in raw["main_rgb"]],
            "main_intensity": sum(raw["main_intensity"]) / 2.0,
            "direction_xyz": [value / length for value in direction],
            "ambient_fill_rgb": [
                float(value) for value in raw["ambient_fill_rgb"]
            ],
            "ambient_fill_intensity": (
                sum(raw["ambient_fill_intensity"]) / 2.0
            ),
        }
    if set(profiles) != set(PROFILE_ORDER):
        raise EvaluationConfigError(
            f"expected lighting profiles {PROFILE_ORDER}, got {tuple(profiles)}"
        )
    return profiles


def build_design(
    table_config: Mapping[str, Any],
    classes: Sequence[str],
    gazebo_labels: Mapping[str, int],
    profiles: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    tables = {table["table_id"]: table for table in table_config["tables"]}
    representatives = {
        item["region"]: item for item in representative_specs(
            tables, table_config["placement_policy"]
        )
    }
    scenario_specs = (
        ("A_mid", "middle"),
        ("B_far", "far"),
        ("C_edge_problem_yaw", "edge"),
    )
    placements = []
    for class_name in classes:
        for scenario_id, region in scenario_specs:
            spec = dict(representatives[region])
            if scenario_id == "C_edge_problem_yaw":
                spec["world_yaw"] = math.radians(PROBLEM_YAWS_DEG[class_name])
            placements.append({
                "id": f"{class_name}_{scenario_id}",
                "scenario_id": scenario_id,
                "class_name": class_name,
                "entity_name": f"p2_audit_{class_name}",
                "gazebo_label": int(gazebo_labels[class_name]),
                **spec,
            })
    return {
        "schema_version": 1,
        "protocol": "competition_room_four_profile_lighting_gate",
        "seed": SEED,
        "classes": list(classes),
        "profiles": [profiles[name] for name in PROFILE_ORDER],
        "viewpoints": VIEWPOINTS,
        "formal_confidence": FORMAL_CONFIDENCE,
        "diagnostic_confidence": DIAGNOSTIC_CONFIDENCE,
        "scenarios_per_class": 3,
        "trials_per_class": 12,
        "trial_count": len(classes) * 3 * len(PROFILE_ORDER),
        "placements": placements,
        "control_variables": (
            "Object model, pose, yaw, table, P1/P2, camera, checkpoint, "
            "confidence, and detector parameters are identical across profiles."
        ),
    }


def _add_directional_light(
    world: ET.Element,
    name: str,
    rgb: Sequence[float],
    intensity: float,
    direction: Sequence[float],
    shadows: bool,
) -> None:
    light = ET.SubElement(world, "light", {"type": "directional", "name": name})
    ET.SubElement(light, "pose").text = "0 0 8 0 0 0"
    ET.SubElement(light, "diffuse").text = (
        f"{rgb[0]:.9g} {rgb[1]:.9g} {rgb[2]:.9g} 1"
    )
    ET.SubElement(light, "specular").text = (
        f"{rgb[0] * 0.2:.9g} {rgb[1] * 0.2:.9g} {rgb[2] * 0.2:.9g} 1"
    )
    ET.SubElement(light, "direction").text = " ".join(
        f"{value:.12g}" for value in direction
    )
    ET.SubElement(light, "intensity").text = f"{intensity:.12g}"
    ET.SubElement(light, "cast_shadows").text = str(shadows).lower()


def apply_lighting_profile(
    world_path: Path, profile: Mapping[str, Any]
) -> None:
    tree = ET.parse(world_path)
    world = tree.getroot().find("world")
    if world is None:
        raise EvaluationConfigError("lighting world lacks a world element")
    for light in list(world.findall("light")):
        world.remove(light)
    scene = world.find("scene")
    if scene is None:
        scene = ET.SubElement(world, "scene")
    ambient = scene.find("ambient")
    if ambient is None:
        ambient = ET.SubElement(scene, "ambient")
    ambient.text = "0.18 0.18 0.18 1"
    shadows = scene.find("shadows")
    if shadows is None:
        shadows = ET.SubElement(scene, "shadows")
    shadows.text = "true"
    direction = profile["direction_xyz"]
    _add_directional_light(
        world,
        "sun",
        profile["main_rgb"],
        float(profile["main_intensity"]),
        direction,
        True,
    )
    _add_directional_light(
        world,
        "ambient_fill",
        profile["ambient_fill_rgb"],
        float(profile["ambient_fill_intensity"]),
        (-direction[0], -direction[1], direction[2]),
        False,
    )
    tree.write(world_path, encoding="utf-8", xml_declaration=True)


def consolidate(
    design: Mapping[str, Any],
    profile_summaries: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    placement_design = {
        item["id"]: item for item in design["placements"]
    }
    classes = {}
    for class_name in design["classes"]:
        profile_results = {}
        trials = []
        by_profile_and_scenario = {}
        for profile_id in PROFILE_ORDER:
            class_result = profile_summaries[profile_id]["classes"][class_name]
            selected = class_result["placements"]
            for result in selected:
                scenario = placement_design[result["placement_id"]]
                trial = {
                    "class_name": class_name,
                    "scenario_id": scenario["scenario_id"],
                    "lighting_profile": profile_id,
                    "table_id": scenario["table_id"],
                    "placement": scenario["region"],
                    "object_position_m": [
                        scenario["world_x"], scenario["world_y"],
                        scenario["world_z"],
                    ],
                    "object_yaw_rad": scenario["world_yaw"],
                    "approximate_distance_m": _nearest_viewpoint_distance(
                        scenario["world_x"], scenario["world_y"]
                    ),
                    "physically_visible": result["physically_visible"],
                    "success": result["detected"],
                    "maximum_confidence": result["maximum_confidence"],
                    "best_bbox": result["best_bbox"],
                    "wrong_class_fp": result["wrong_class_fp"],
                    "wrong_class_detections": result[
                        "wrong_class_detections"
                    ],
                    "duplicate_same_frame_detection": result[
                        "duplicate_same_frame_detection"
                    ],
                }
                trials.append(trial)
                by_profile_and_scenario[(profile_id, scenario["scenario_id"])] = trial
            confidences = [item["maximum_confidence"] for item in selected]
            profile_results[profile_id] = {
                "success_count": sum(item["detected"] for item in selected),
                "trial_count": len(selected),
                "confidence_distribution": _distribution(confidences),
                "scenario_confidences": {
                    placement_design[item["placement_id"]]["scenario_id"]:
                    item["maximum_confidence"] for item in selected
                },
            }
        comparisons = []
        collapse_profiles = set()
        for scenario_id, _ in (
            ("A_mid", "middle"), ("B_far", "far"),
            ("C_edge_problem_yaw", "edge"),
        ):
            normal = by_profile_and_scenario[("normal", scenario_id)]
            for profile_id in PROFILE_ORDER[1:]:
                changed = by_profile_and_scenario[(profile_id, scenario_id)]
                collapse = (
                    normal["maximum_confidence"] > 0.8
                    and changed["maximum_confidence"] <= 0.5
                )
                if collapse:
                    collapse_profiles.add(profile_id)
                comparisons.append({
                    "scenario_id": scenario_id,
                    "profile": profile_id,
                    "normal_confidence": normal["maximum_confidence"],
                    "profile_confidence": changed["maximum_confidence"],
                    "confidence_drop": (
                        normal["maximum_confidence"]
                        - changed["maximum_confidence"]
                    ),
                    "confidence_collapse": collapse,
                })
        classes[class_name] = {
            "success_count": sum(item["success"] for item in trials),
            "trial_count": len(trials),
            "gate_result": (
                "PASS" if sum(item["success"] for item in trials) >= 11
                else "RISK" if sum(item["success"] for item in trials) == 10
                else "FAIL"
            ),
            "profiles": profile_results,
            "systematic_confidence_collapse_profiles": sorted(collapse_profiles),
            "confidence_comparisons": comparisons,
            "wrong_class_fp_trial_count": sum(
                item["wrong_class_fp"] for item in trials
            ),
            "duplicate_trial_count": sum(
                item["duplicate_same_frame_detection"] for item in trials
            ),
            "trials": trials,
        }
    first = profile_summaries[PROFILE_ORDER[0]]
    return {
        "schema_version": 1,
        "protocol": design["protocol"],
        "seed": design["seed"],
        "model_path": first["model_path"],
        "model_sha256": first["model_sha256"],
        "formal_confidence": FORMAL_CONFIDENCE,
        "viewpoints": VIEWPOINTS,
        "lighting_profiles": design["profiles"],
        "classes": classes,
        "trial_count": sum(item["trial_count"] for item in classes.values()),
        "wrong_class_fp_trial_count": sum(
            item["wrong_class_fp_trial_count"] for item in classes.values()
        ),
        "duplicate_trial_count": sum(
            item["duplicate_trial_count"] for item in classes.values()
        ),
    }


def main(argv=None) -> int:
    package_root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source-world", type=Path,
        default=Path(
            "/home/hao/robocup_assets/p2_eval/"
            "smoke_multitable_seed_20260914/scenario.world"
        ),
    )
    parser.add_argument(
        "--table-config", type=Path,
        default=package_root / "tools/p2_eval/tables.json",
    )
    parser.add_argument(
        "--class-manifest", type=Path,
        default=package_root / "tools/formal_dataset/classes.json",
    )
    parser.add_argument(
        "--lighting-config", type=Path,
        default=package_root / "tools/formal_dataset/config/v2_formal.json",
    )
    parser.add_argument("--model", required=True, type=Path)
    parser.add_argument("--model-resources", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--device", default="0")
    parser.add_argument(
        "--analyze-only",
        action="store_true",
        help="Reanalyze the four completed profile captures in place.",
    )
    args = parser.parse_args(argv)
    started = time.monotonic()
    try:
        class_document = _read_json(args.class_manifest)
        official_classes = [
            item["name"] for item in class_document["classes"]
        ]
        labels = {
            item["name"]: int(item["gazebo_label"])
            for item in class_document["classes"]
        }
        profiles = load_profiles(args.lighting_config)
        if args.analyze_only:
            if not (args.output_dir / "design.json").is_file():
                raise EvaluationConfigError(
                    "--analyze-only requires a completed lighting design"
                )
            design = _read_json(args.output_dir / "design.json")
        else:
            if args.output_dir.exists():
                raise EvaluationConfigError(
                    f"output directory already exists: {args.output_dir}"
                )
            args.output_dir.mkdir(parents=True)
            design = build_design(
                load_table_config(args.table_config),
                LIGHTING_CLASSES,
                labels,
                profiles,
            )
            _write_json(args.output_dir / "design.json", design)
        summaries = {}
        for profile_id in PROFILE_ORDER:
            profile_output = args.output_dir / profile_id
            if args.analyze_only:
                if not (profile_output / "frames.tsv").is_file():
                    raise EvaluationConfigError(
                        f"profile capture is incomplete: {profile_id}"
                    )
            else:
                profile_output.mkdir()
                _write_json(profile_output / "design.json", {
                    **design,
                    "active_lighting_profile": profiles[profile_id],
                })
                world_path = profile_output / "lighting_gate.world"
                create_audit_world(
                    args.source_world, world_path, official_classes, labels
                )
                apply_lighting_profile(world_path, profiles[profile_id])
                plan_path = profile_output / "capture_plan.tsv"
                write_capture_plan(plan_path, design)
                capture(
                    world_path,
                    plan_path,
                    profile_output,
                    package_root /
                    "tools/p2_eval/tabletop_gate_capture_worker.cpp",
                    args.model_resources,
                )
            summaries[profile_id] = analyze(
                profile_output / "frames.tsv",
                args.model,
                args.device,
                profile_output,
                LIGHTING_CLASSES,
            )
        summary = consolidate(design, summaries)
        summary["wall_seconds"] = time.monotonic() - started
        _write_json(args.output_dir / "summary.json", summary)
        print(json.dumps(summary, indent=2))
        return 0
    except (
        EvaluationConfigError, FileExistsError, FileNotFoundError, OSError,
        RuntimeError, ValueError, ET.ParseError, json.JSONDecodeError,
    ) as error:
        print(f"LIGHTING_GATE_FAILED: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
