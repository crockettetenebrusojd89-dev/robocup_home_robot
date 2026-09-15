#!/usr/bin/env python3
"""Screen all formal classes with fixed viewpoints and no runtime changes."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import sys
import time
from typing import Any, Mapping, Sequence
import xml.etree.ElementTree as ET

import numpy as np
from ultralytics import YOLO

from p2_eval_core import EvaluationConfigError
from p2_eval_core import legal_center_half_extents
from p2_eval_core import load_table_config
from run_tabletop_robustness_gate import _associated
from run_tabletop_robustness_gate import _camera_model
from run_tabletop_robustness_gate import _distribution
from run_tabletop_robustness_gate import _manifest_records
from run_tabletop_robustness_gate import _read_json
from run_tabletop_robustness_gate import _write_json
from run_tabletop_robustness_gate import capture
from run_tabletop_robustness_gate import representative_positions


VIEWPOINTS = (
    {"index": 1, "x": -3.485, "y": -1.115, "yaw": -0.532},
    {"index": 2, "x": 0.265, "y": -0.665, "yaw": -2.638},
)
FORMAL_CONFIDENCE = 0.50
DIAGNOSTIC_CONFIDENCE = 0.001
YAW_SAMPLES = 12
EXPANDED_TABLE = "living_room_table_3"


def _local_to_world(table: Mapping[str, Any], x: float, y: float):
    center_x, center_y = table["center_world_m"]
    yaw = float(table["yaw_world_rad"])
    return (
        float(center_x) + math.cos(yaw) * x - math.sin(yaw) * y,
        float(center_y) + math.sin(yaw) * x + math.cos(yaw) * y,
    )


def _nearest_viewpoint_distance(x: float, y: float) -> float:
    return min(
        math.hypot(x - float(viewpoint["x"]), y - float(viewpoint["y"]))
        for viewpoint in VIEWPOINTS
    )


def representative_specs(
    tables: Mapping[str, Mapping[str, Any]], policy: Mapping[str, Any]
) -> list[dict[str, Any]]:
    """Return five legal room-wide placements spanning distance and edges."""
    raw = (
        ("near", "living_room_table_1", 0.0, -1.0),
        ("middle", "living_room_table_0", 0.0, 0.0),
        ("far", "living_room_table_2", 0.0, 1.0),
        ("edge", "living_room_table_3", 1.0, 0.0),
        ("corner", "living_room_table_0", -1.0, 1.0),
    )
    specs = []
    for index, (region, table_id, x_scale, y_scale) in enumerate(raw):
        table = tables[table_id]
        half_x, half_y = legal_center_half_extents(table, policy)
        local_x = x_scale * half_x
        local_y = y_scale * half_y
        world_x, world_y = _local_to_world(table, local_x, local_y)
        specs.append({
            "region": region,
            "table_id": table_id,
            "local_x": local_x,
            "local_y": local_y,
            "world_x": world_x,
            "world_y": world_y,
            "world_z": float(table["surface_z_world_m"]),
            "world_yaw": index * math.pi / 4.0,
            "nearest_viewpoint_distance_m": _nearest_viewpoint_distance(
                world_x, world_y
            ),
        })
    return specs


def expanded_specs(
    table: Mapping[str, Any], policy: Mapping[str, Any]
) -> list[dict[str, Any]]:
    """Return the same 15-position legal tabletop grid used for banana."""
    specs = []
    for index, position in enumerate(representative_positions(table, policy)):
        specs.append({
            **position,
            "table_id": table["table_id"],
            "world_z": float(table["surface_z_world_m"]),
            "world_yaw": (index % 8) * math.pi / 4.0,
            "nearest_viewpoint_distance_m": _nearest_viewpoint_distance(
                position["world_x"], position["world_y"]
            ),
        })
    return specs


def create_audit_world(
    source_world: Path,
    destination: Path,
    official_classes: Sequence[str],
    gazebo_labels: Mapping[str, int],
) -> None:
    """Create an evaluation-only room with one movable entity per class."""
    tree = ET.parse(source_world)
    world = tree.getroot().find("world")
    if world is None:
        raise EvaluationConfigError("source world lacks a world element")
    official = set(official_classes)
    for include in list(world.findall("include")):
        model_name = (include.findtext("uri") or "").rsplit("/", 1)[-1]
        if model_name in official:
            world.remove(include)
    if not any(
        "sensors-system" in plugin.get("filename", "")
        for plugin in world.findall("plugin")
    ):
        sensor_plugin = ET.SubElement(
            world,
            "plugin",
            {
                "filename": "ignition-gazebo-sensors-system",
                "name": "ignition::gazebo::systems::Sensors",
            },
        )
        ET.SubElement(sensor_plugin, "render_engine").text = "ogre2"
    for class_name in official_classes:
        include = ET.SubElement(world, "include")
        ET.SubElement(include, "uri").text = f"model://{class_name}"
        ET.SubElement(include, "name").text = f"p2_audit_{class_name}"
        ET.SubElement(include, "static").text = "true"
        ET.SubElement(include, "pose").text = "0 0 -5 0 0 0"
        plugin = ET.SubElement(
            include,
            "plugin",
            {
                "filename": "ignition-gazebo-label-system",
                "name": "ignition::gazebo::systems::Label",
            },
        )
        ET.SubElement(plugin, "label").text = str(gazebo_labels[class_name])
    _camera_model(world)
    tree.write(destination, encoding="utf-8", xml_declaration=True)


def build_design(
    table_config: Mapping[str, Any],
    classes: Sequence[str],
    gazebo_labels: Mapping[str, int],
    phase: str,
) -> dict[str, Any]:
    """Build deterministic representative or expanded placements."""
    tables = {
        table["table_id"]: table for table in table_config["tables"]
    }
    if phase == "representative":
        specs = representative_specs(
            tables, table_config["placement_policy"]
        )
    else:
        specs = expanded_specs(
            tables[EXPANDED_TABLE], table_config["placement_policy"]
        )
    placements = []
    for class_name in classes:
        for index, spec in enumerate(specs, start=1):
            placements.append({
                "id": f"{class_name}_{index:02d}",
                "class_name": class_name,
                "entity_name": f"p2_audit_{class_name}",
                "gazebo_label": gazebo_labels[class_name],
                **spec,
            })
    return {
        "schema_version": 1,
        "phase": phase,
        "viewpoints": VIEWPOINTS,
        "yaw_samples_per_viewpoint": YAW_SAMPLES,
        "yaw_step_degrees": 360 / YAW_SAMPLES,
        "formal_confidence": FORMAL_CONFIDENCE,
        "diagnostic_confidence": DIAGNOSTIC_CONFIDENCE,
        "placements_per_class": len(specs),
        "classes": list(classes),
        "placements": placements,
    }


def write_capture_plan(path: Path, design: Mapping[str, Any]) -> None:
    lines = ["WORLD robocup_home p2_gate_camera", f"YAW_SAMPLES {YAW_SAMPLES}"]
    for viewpoint in design["viewpoints"]:
        lines.append(
            "VIEW {index} {x:.12f} {y:.12f} {yaw:.12f}".format(**viewpoint)
        )
    for class_name in design["classes"]:
        lines.append(f"HIDE p2_audit_{class_name}")
    for item in design["placements"]:
        lines.append(
            "PLACEMENT {id} {class_name} {entity_name} {gazebo_label} "
            "{local_x:.12f} {local_y:.12f} {world_x:.12f} "
            "{world_y:.12f} {world_z:.12f} {world_yaw:.12f} {region}".format(
                **item
            )
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def classify(success_rate: float) -> str:
    """Assign the predeclared screening band from position success rate."""
    if success_rate >= 1.0:
        return "stable"
    if success_rate >= 0.60:
        return "borderline"
    return "weak"


def _all_boxes(result) -> list[dict[str, Any]]:
    """Return every detector box with its official class identity."""
    values = []
    if result.boxes is None:
        return values
    for box in result.boxes:
        class_id = int(box.cls[0].item())
        x1, y1, x2, y2 = (float(value) for value in box.xyxy[0].tolist())
        values.append({
            "class_id": class_id,
            "class_name": str(result.names[class_id]),
            "confidence": float(box.conf[0].item()),
            "bbox_xyxy": [x1, y1, x2, y2],
            "bbox_width_px": x2 - x1,
            "bbox_height_px": y2 - y1,
            "bbox_area_px2": (x2 - x1) * (y2 - y1),
        })
    return values


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def analyze(
    manifest_path: Path,
    model_path: Path,
    device: str,
    output: Path,
    class_order: Sequence[str],
) -> dict[str, Any]:
    selected_names = set(class_order)
    records = [
        record for record in _manifest_records(manifest_path)
        if record["class_name"] in selected_names
    ]
    if not records:
        raise EvaluationConfigError("capture has no records for selected classes")
    model = YOLO(str(model_path))
    names = [str(model.names[index]) for index in range(len(model.names))]
    missing = sorted(set(class_order) - set(names))
    if missing:
        raise EvaluationConfigError(f"model lacks target classes: {missing}")

    per_placement: dict[str, dict[str, Any]] = {}
    for index, record in enumerate(records, start=1):
        result = model.predict(
            source=record["image"],
            conf=DIAGNOSTIC_CONFIDENCE,
            device=device,
            verbose=False,
        )[0]
        truth = (
            [record[name] for name in (
                "truth_x1", "truth_y1", "truth_x2", "truth_y2"
            )]
            if record["truth_visible"]
            else None
        )
        all_boxes = _all_boxes(result)
        boxes = _associated(
            [box for box in all_boxes if box["class_name"] == record["class_name"]],
            truth,
        )
        formal_boxes = [
            box for box in all_boxes
            if box["confidence"] >= FORMAL_CONFIDENCE
        ]
        associated_formal = _associated(formal_boxes, truth)
        correct_formal = [
            box for box in associated_formal
            if box["class_name"] == record["class_name"]
        ]
        wrong_formal = [
            box for box in formal_boxes
            if box["class_name"] != record["class_name"]
        ]
        associated_wrong = _associated(wrong_formal, truth)
        key = record["placement_id"]
        entry = per_placement.setdefault(key, {
            "placement_id": key,
            "class_name": record["class_name"],
            "region": record["region"],
            "local_position_m": {
                "x": record["local_x"], "y": record["local_y"]
            },
            "world_position_m": {
                "x": record["world_x"], "y": record["world_y"]
            },
            "frame_count": 0,
            "visible_frame_count": 0,
            "detection_count_ge_0_50": 0,
            "candidate_boxes": [],
            "wrong_class_detections": [],
            "wrong_class_detection_frame_count": 0,
            "duplicate_same_frame_count": 0,
        })
        entry["frame_count"] += 1
        entry["visible_frame_count"] += bool(record["truth_visible"])
        entry["detection_count_ge_0_50"] += len(correct_formal)
        if wrong_formal:
            entry["wrong_class_detection_frame_count"] += 1
            for box in wrong_formal:
                entry["wrong_class_detections"].append({
                    "image": record["image"],
                    "viewpoint": record["viewpoint"],
                    "yaw_index": record["yaw_index"],
                    "associated_with_target": box in associated_wrong,
                    **box,
                })
        if len(correct_formal) > 1:
            entry["duplicate_same_frame_count"] += 1
        if boxes:
            entry["candidate_boxes"].append({
                **boxes[0],
                "image": record["image"],
                "viewpoint": record["viewpoint"],
                "yaw_index": record["yaw_index"],
            })
        if index % 200 == 0 or index == len(records):
            print(f"INFERENCE {index}/{len(records)}", flush=True)

    placements = []
    for entry in per_placement.values():
        boxes = entry.pop("candidate_boxes")
        confidences = [box["confidence"] for box in boxes]
        best = max(boxes, key=lambda item: item["confidence"]) if boxes else None
        entry["maximum_confidence"] = max(confidences, default=0.0)
        entry["median_candidate_confidence"] = (
            float(np.median(confidences)) if confidences else 0.0
        )
        entry["best_bbox"] = best
        entry["detected"] = entry["detection_count_ge_0_50"] > 0
        entry["physically_visible"] = entry["visible_frame_count"] > 0
        entry["wrong_class_fp"] = bool(entry["wrong_class_detections"])
        entry["duplicate_same_frame_detection"] = (
            entry["duplicate_same_frame_count"] > 0
        )
        entry["approximate_distance_m"] = _nearest_viewpoint_distance(
            entry["world_position_m"]["x"], entry["world_position_m"]["y"]
        )
        placements.append(entry)

    classes = {}
    for class_name in class_order:
        selected = [
            item for item in placements if item["class_name"] == class_name
        ]
        maxima = [item["maximum_confidence"] for item in selected]
        detected = [item for item in selected if item["detected"]]
        best_boxes = [item["best_bbox"] for item in selected if item["best_bbox"]]
        success_rate = len(detected) / len(selected)
        worst = min(
            selected,
            key=lambda item: (
                item["maximum_confidence"],
                item["visible_frame_count"],
                item["placement_id"],
            ),
        )
        classes[class_name] = {
            "band": classify(success_rate),
            "placement_count": len(selected),
            "detected_placement_count": len(detected),
            "detection_success_rate": success_rate,
            "visible_frame_count": sum(
                item["visible_frame_count"] for item in selected
            ),
            "confidence_distribution_of_position_maxima": _distribution(maxima),
            "bbox_width_px_median": (
                float(np.median([box["bbox_width_px"] for box in best_boxes]))
                if best_boxes else 0.0
            ),
            "bbox_height_px_median": (
                float(np.median([box["bbox_height_px"] for box in best_boxes]))
                if best_boxes else 0.0
            ),
            "bbox_area_px2_median": (
                float(np.median([box["bbox_area_px2"] for box in best_boxes]))
                if best_boxes else 0.0
            ),
            "wrong_class_fp_placement_count": sum(
                item["wrong_class_fp"] for item in selected
            ),
            "wrong_class_detection_count": sum(
                len(item["wrong_class_detections"]) for item in selected
            ),
            "duplicate_same_frame_placement_count": sum(
                item["duplicate_same_frame_detection"] for item in selected
            ),
            "worst_position": worst,
            "placements": selected,
        }
    summary = {
        "schema_version": 1,
        "model_path": str(model_path.resolve()),
        "model_sha256": _sha256(model_path),
        "device": device,
        "formal_confidence": FORMAL_CONFIDENCE,
        "diagnostic_confidence": DIAGNOSTIC_CONFIDENCE,
        "frame_count": len(records),
        "classification_rule": {
            "stable": "position success rate = 1.00",
            "borderline": "0.60 <= position success rate < 1.00",
            "weak": "position success rate < 0.60",
        },
        "classes": classes,
        "bands": {
            band: [name for name in class_order if classes[name]["band"] == band]
            for band in ("stable", "borderline", "weak")
        },
        "wrong_class_fp_placement_count": sum(
            item["wrong_class_fp"] for item in placements
        ),
        "wrong_class_detection_count": sum(
            len(item["wrong_class_detections"]) for item in placements
        ),
        "duplicate_same_frame_placement_count": sum(
            item["duplicate_same_frame_detection"] for item in placements
        ),
        "isolation": (
            "YOLO received RGB image paths only. Gazebo labels and placement "
            "coordinates were used only after inference for offline association."
        ),
    }
    _write_json(output / "summary.json", summary)
    return summary


def main(argv=None) -> int:
    package_root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source-world",
        type=Path,
        default=Path(
            "/home/hao/robocup_assets/p2_eval/"
            "smoke_multitable_seed_20260914/scenario.world"
        ),
    )
    parser.add_argument(
        "--table-config",
        type=Path,
        default=package_root / "tools/p2_eval/tables.json",
    )
    parser.add_argument(
        "--class-manifest",
        type=Path,
        default=package_root / "tools/formal_dataset/classes.json",
    )
    parser.add_argument(
        "--model",
        type=Path,
        default=Path(
            "/home/hao/robocup_assets/training_runs/"
            "formal_objects_v1_yolo11n/weights/best.pt"
        ),
    )
    parser.add_argument("--model-resources", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument(
        "--phase", choices=("representative", "expanded"),
        default="representative",
    )
    parser.add_argument("--classes", nargs="*")
    parser.add_argument("--device", default="0")
    parser.add_argument("--analyze-only", action="store_true")
    parser.add_argument(
        "--reuse-capture-dir",
        type=Path,
        help=(
            "Analyze an immutable prior competition-domain capture into a new "
            "output directory without replacing its original summary."
        ),
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
        reuse_design = None
        if args.reuse_capture_dir:
            reuse_design = _read_json(args.reuse_capture_dir / "design.json")
            captured_classes = reuse_design.get("classes") or list(dict.fromkeys(
                item["class_name"] for item in reuse_design["placements"]
            ))
            selected_classes = args.classes or captured_classes
        else:
            selected_classes = args.classes or official_classes
        unknown = sorted(set(selected_classes) - set(official_classes))
        if unknown:
            raise EvaluationConfigError(f"unknown classes: {unknown}")
        if not args.reuse_capture_dir and args.phase == "expanded" and not args.classes:
            raise EvaluationConfigError("expanded phase requires --classes")
        if args.reuse_capture_dir and args.analyze_only:
            raise EvaluationConfigError(
                "--reuse-capture-dir and --analyze-only are mutually exclusive"
            )
        if args.reuse_capture_dir:
            if args.output_dir.exists():
                raise EvaluationConfigError(
                    f"output directory already exists: {args.output_dir}"
                )
            if not (args.reuse_capture_dir / "frames.tsv").is_file():
                raise EvaluationConfigError(
                    "--reuse-capture-dir requires a complete frames.tsv"
                )
            args.output_dir.mkdir(parents=True)
            _write_json(args.output_dir / "design.json", {
                **reuse_design,
                "capture_source": str(args.reuse_capture_dir.resolve()),
                "reanalyzed_classes": list(selected_classes),
            })
            manifest_path = args.reuse_capture_dir / "frames.tsv"
        elif args.analyze_only:
            if not (args.output_dir / "frames.tsv").is_file():
                raise EvaluationConfigError(
                    "--analyze-only requires an existing frames.tsv"
                )
        else:
            if args.output_dir.exists():
                raise EvaluationConfigError(
                    f"output directory already exists: {args.output_dir}"
                )
            args.output_dir.mkdir(parents=True)
            design = build_design(
                load_table_config(args.table_config),
                selected_classes,
                labels,
                args.phase,
            )
            _write_json(args.output_dir / "design.json", design)
            world = args.output_dir / "audit.world"
            create_audit_world(
                args.source_world,
                world,
                official_classes,
                labels,
            )
            plan = args.output_dir / "capture_plan.tsv"
            write_capture_plan(plan, design)
            capture(
                world,
                plan,
                args.output_dir,
                package_root / "tools/p2_eval/tabletop_gate_capture_worker.cpp",
                args.model_resources,
            )
            manifest_path = args.output_dir / "frames.tsv"
        if args.analyze_only:
            manifest_path = args.output_dir / "frames.tsv"
        design = _read_json(args.output_dir / "design.json")
        summary = analyze(
            manifest_path,
            args.model,
            args.device,
            args.output_dir,
            selected_classes,
        )
        summary["phase"] = design.get("phase", "reused_capture")
        summary["wall_seconds"] = time.monotonic() - started
        _write_json(args.output_dir / "summary.json", summary)
        print(json.dumps(summary, indent=2))
        return 0
    except (
        EvaluationConfigError,
        FileNotFoundError,
        OSError,
        RuntimeError,
        ValueError,
        ET.ParseError,
        json.JSONDecodeError,
    ) as error:
        print(f"CLASS_AUDIT_FAILED: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
