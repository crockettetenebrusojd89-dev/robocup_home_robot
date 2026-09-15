#!/usr/bin/env python3
"""Measure fixed-viewpoint detector robustness over legal tabletop positions."""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
from pathlib import Path
import shlex
import signal
import subprocess
import sys
import tempfile
import time
from typing import Any, Mapping, Sequence
import xml.etree.ElementTree as ET

import numpy as np
from ultralytics import YOLO

from p2_eval_core import EvaluationConfigError
from p2_eval_core import legal_center_half_extents
from p2_eval_core import load_table_config


VIEWPOINTS = (
    {"index": 1, "x": -3.485, "y": -1.115, "yaw": -0.532},
    {"index": 2, "x": 0.265, "y": -0.665, "yaw": -2.638},
)
TARGET_TABLES = {
    "coke_can": "living_room_table_2",
    "banana": "living_room_table_3",
}
DIAGNOSTIC_CONFIDENCE = 0.001
FORMAL_CONFIDENCE = 0.50
YAW_SAMPLE_DEGREES = 15
RENDER_RESOURCE_ERROR_MARKERS = (
    "Unable to find file with URI",
    "Cannot load null mesh",
    "Failed to load geometry for visual",
)


def render_resource_failures(log_text: str) -> list[str]:
    """Return render-resource failures that invalidate visual evidence."""
    return [
        marker for marker in RENDER_RESOURCE_ERROR_MARKERS
        if marker in log_text
    ]


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def _local_to_world(table: Mapping[str, Any], x: float, y: float):
    center_x, center_y = table["center_world_m"]
    yaw = float(table["yaw_world_rad"])
    return (
        float(center_x) + math.cos(yaw) * x - math.sin(yaw) * y,
        float(center_y) + math.sin(yaw) * x + math.cos(yaw) * y,
    )


def representative_positions(
    table: Mapping[str, Any], policy: Mapping[str, Any]
) -> list[dict[str, Any]]:
    """Return a 3x5 grid spanning center, edges, ends, and all corners."""
    half_x, half_y = legal_center_half_extents(table, policy)
    x_values = (-half_x, 0.0, half_x)
    y_values = (-half_y, -half_y / 2.0, 0.0, half_y / 2.0, half_y)
    x_names = ("left_edge", "center_width", "right_edge")
    y_names = ("end_low", "mid_low", "center_length", "mid_high", "end_high")
    positions = []
    for y_index, local_y in enumerate(y_values):
        for x_index, local_x in enumerate(x_values):
            world_x, world_y = _local_to_world(table, local_x, local_y)
            positions.append({
                "local_x": local_x,
                "local_y": local_y,
                "world_x": world_x,
                "world_y": world_y,
                "region": f"{x_names[x_index]}_{y_names[y_index]}",
            })
    return positions


def _camera_model(world: ET.Element) -> None:
    model = ET.SubElement(world, "model", {"name": "p2_gate_camera"})
    ET.SubElement(model, "static").text = "true"
    ET.SubElement(model, "pose").text = "0 0 0.9 0 0.1745329252 0"
    link = ET.SubElement(model, "link", {"name": "link"})
    for name, sensor_type, topic in (
        ("rgb", "camera", "/p2_gate/rgb"),
        ("visible_boxes", "boundingbox_camera", "/p2_gate/boxes"),
    ):
        sensor = ET.SubElement(
            link, "sensor", {"name": name, "type": sensor_type}
        )
        ET.SubElement(sensor, "topic").text = topic
        camera = ET.SubElement(sensor, "camera")
        if sensor_type == "boundingbox_camera":
            ET.SubElement(camera, "box_type").text = "visible_2d"
        ET.SubElement(camera, "horizontal_fov").text = "1.2217304764"
        image = ET.SubElement(camera, "image")
        ET.SubElement(image, "width").text = "640"
        ET.SubElement(image, "height").text = "480"
        if sensor_type == "camera":
            ET.SubElement(image, "format").text = "R8G8B8"
        clip = ET.SubElement(camera, "clip")
        ET.SubElement(clip, "near").text = "0.20"
        ET.SubElement(clip, "far").text = "10.0"
        ET.SubElement(sensor, "always_on").text = "true"
        ET.SubElement(sensor, "update_rate").text = "15"
        ET.SubElement(sensor, "visualize").text = "false"


def create_gate_world(
    source_world: Path,
    destination: Path,
    official_classes: Sequence[str],
    gazebo_labels: Mapping[str, int],
) -> None:
    """Create an evaluation-only room with two movable labeled targets."""
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
    for class_name in TARGET_TABLES:
        include = ET.SubElement(world, "include")
        ET.SubElement(include, "uri").text = f"model://{class_name}"
        ET.SubElement(include, "name").text = f"p2_gate_{class_name}"
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
    scenario_metadata: Mapping[str, Any],
    gazebo_labels: Mapping[str, int],
) -> dict[str, Any]:
    """Build deterministic placements while keeping the seed object's yaw."""
    tables = {
        table["table_id"]: table for table in table_config["tables"]
    }
    seed_objects = {
        item["class_name"]: item for item in scenario_metadata["objects"]
    }
    placements = []
    for class_name, table_id in TARGET_TABLES.items():
        table = tables[table_id]
        for index, position in enumerate(
            representative_positions(table, table_config["placement_policy"]),
            start=1,
        ):
            placements.append({
                "id": f"{class_name}_{index:02d}",
                "class_name": class_name,
                "entity_name": f"p2_gate_{class_name}",
                "gazebo_label": gazebo_labels[class_name],
                "table_id": table_id,
                "world_z": float(table["surface_z_world_m"]),
                "world_yaw": float(seed_objects[class_name]["world_yaw_rad"]),
                **position,
            })
    return {
        "schema_version": 1,
        "seed": scenario_metadata["seed"],
        "viewpoints": VIEWPOINTS,
        "yaw_sample_degrees": YAW_SAMPLE_DEGREES,
        "formal_confidence": FORMAL_CONFIDENCE,
        "diagnostic_confidence": DIAGNOSTIC_CONFIDENCE,
        "positions_per_class": 15,
        "placements": placements,
    }


def write_capture_plan(path: Path, design: Mapping[str, Any]) -> None:
    lines = ["WORLD robocup_home p2_gate_camera"]
    for viewpoint in design["viewpoints"]:
        lines.append(
            "VIEW {index} {x:.12f} {y:.12f} {yaw:.12f}".format(**viewpoint)
        )
    for class_name in TARGET_TABLES:
        lines.append(f"HIDE p2_gate_{class_name}")
    for item in design["placements"]:
        lines.append(
            "PLACEMENT {id} {class_name} {entity_name} {gazebo_label} "
            "{local_x:.12f} {local_y:.12f} {world_x:.12f} "
            "{world_y:.12f} {world_z:.12f} {world_yaw:.12f} {region}".format(
                **item
            )
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def compile_worker(source: Path, destination: Path) -> None:
    flags = subprocess.check_output(
        [
            "pkg-config",
            "--cflags",
            "--libs",
            "ignition-transport11",
            "ignition-msgs8",
            "opencv4",
        ],
        text=True,
    )
    command = [
        "g++", "-std=c++17", "-O2", "-Wall", "-Wextra", "-Wpedantic",
        str(source), "-o", str(destination), *shlex.split(flags),
    ]
    subprocess.run(command, check=True)


def stop_process(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    os.killpg(process.pid, signal.SIGINT)
    try:
        process.wait(timeout=10.0)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=5.0)


def capture(
    world: Path,
    plan: Path,
    output: Path,
    worker_source: Path,
    model_resources: Path,
) -> None:
    with tempfile.TemporaryDirectory(prefix="p2_tabletop_gate_") as temporary:
        temporary_path = Path(temporary)
        worker = temporary_path / "capture_worker"
        compile_worker(worker_source, worker)
        environment = os.environ.copy()
        environment["IGN_PARTITION"] = f"p2_tabletop_gate_{os.getpid()}"
        environment["IGN_HOMEDIR"] = str(temporary_path / "ign_home")
        old_resources = environment.get("IGN_GAZEBO_RESOURCE_PATH", "")
        environment["IGN_GAZEBO_RESOURCE_PATH"] = (
            str(model_resources) if not old_resources
            else f"{model_resources}:{old_resources}"
        )
        with (output / "gazebo.log").open("w", encoding="utf-8") as log:
            gazebo = subprocess.Popen(
                [
                    "ign", "gazebo", "-s", "--headless-rendering", "-r",
                    str(world), "-v", "2",
                ],
                env=environment,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
                text=True,
            )
            try:
                with (output / "capture_worker.log").open(
                    "w", encoding="utf-8"
                ) as worker_log:
                    completed = subprocess.run(
                        [str(worker), str(output), str(plan)],
                        env=environment,
                        stdout=worker_log,
                        stderr=subprocess.STDOUT,
                        timeout=600.0,
                        check=False,
                        text=True,
                    )
                if completed.returncode != 0:
                    worker_tail = (output / "capture_worker.log").read_text(
                        encoding="utf-8", errors="replace"
                    )[-6000:]
                    gazebo_tail = (output / "gazebo.log").read_text(
                        encoding="utf-8", errors="replace"
                    )[-6000:]
                    raise RuntimeError(
                        f"capture worker failed ({completed.returncode})\n"
                        f"{worker_tail}\nGazebo:\n{gazebo_tail}"
                    )
            finally:
                stop_process(gazebo)
        gazebo_log = (output / "gazebo.log").read_text(
            encoding="utf-8", errors="replace"
        )
        failures = render_resource_failures(gazebo_log)
        if failures:
            raise RuntimeError(
                "Gazebo visual evidence is invalid because rendering resources "
                f"were missing: {failures}"
            )


def _boxes(result, class_name: str):
    values = []
    if result.boxes is None:
        return values
    for box in result.boxes:
        class_id = int(box.cls[0].item())
        if str(result.names[class_id]) != class_name:
            continue
        x1, y1, x2, y2 = (float(value) for value in box.xyxy[0].tolist())
        values.append({
            "confidence": float(box.conf[0].item()),
            "bbox_xyxy": [x1, y1, x2, y2],
            "bbox_width_px": x2 - x1,
            "bbox_height_px": y2 - y1,
            "bbox_area_px2": (x2 - x1) * (y2 - y1),
        })
    return values


def _associated(boxes, truth):
    if truth is None:
        return []
    tx1, ty1, tx2, ty2 = truth
    margin = 8.0
    associated = []
    for box in boxes:
        x1, y1, x2, y2 = box["bbox_xyxy"]
        center_x = (x1 + x2) / 2.0
        center_y = (y1 + y2) / 2.0
        overlap_x = max(0.0, min(x2, tx2) - max(x1, tx1))
        overlap_y = max(0.0, min(y2, ty2) - max(y1, ty1))
        if (
            overlap_x * overlap_y > 0.0
            or tx1 - margin <= center_x <= tx2 + margin
            and ty1 - margin <= center_y <= ty2 + margin
        ):
            associated.append(box)
    return sorted(
        associated, key=lambda item: item["confidence"], reverse=True
    )


def _manifest_records(path: Path):
    with path.open(encoding="utf-8", newline="") as stream:
        records = list(csv.DictReader(stream, delimiter="\t"))
    numeric = (
        "local_x", "local_y", "world_x", "world_y", "camera_base_x",
        "camera_base_y", "camera_yaw", "truth_x1", "truth_y1",
        "truth_x2", "truth_y2",
    )
    for record in records:
        for name in numeric:
            record[name] = float(record[name])
        for name in ("viewpoint", "yaw_index", "truth_visible"):
            record[name] = int(record[name])
    return records


def _distribution(values: Sequence[float]) -> dict[str, float]:
    array = np.asarray(values, dtype=float)
    return {
        "minimum": float(array.min()),
        "p10": float(np.percentile(array, 10)),
        "q1": float(np.percentile(array, 25)),
        "median": float(np.median(array)),
        "mean": float(array.mean()),
        "q3": float(np.percentile(array, 75)),
        "p90": float(np.percentile(array, 90)),
        "maximum": float(array.max()),
    }


def analyze(
    manifest_path: Path,
    model_path: Path,
    device: str,
    output: Path,
) -> dict[str, Any]:
    records = _manifest_records(manifest_path)
    model = YOLO(str(model_path))
    model_names = [str(model.names[index]) for index in range(len(model.names))]
    missing = sorted(set(TARGET_TABLES) - set(model_names))
    if missing:
        raise EvaluationConfigError(f"model lacks target classes: {missing}")

    def run_pass(confidence):
        collected = []
        for index, record in enumerate(records, start=1):
            result = model.predict(
                source=record["image"],
                conf=confidence,
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
            collected.append(
                _associated(_boxes(result, record["class_name"]), truth)
            )
            if index % 100 == 0 or index == len(records):
                print(
                    f"INFERENCE conf={confidence:.3f} {index}/{len(records)}",
                    flush=True,
                )
        return collected

    diagnostic = run_pass(DIAGNOSTIC_CONFIDENCE)
    exact = run_pass(FORMAL_CONFIDENCE)
    per_placement: dict[str, dict[str, Any]] = {}
    for record, diagnostic_boxes, exact_boxes in zip(records, diagnostic, exact):
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
            "truth_visible_frame_count": 0,
            "detection_count_ge_0_50": 0,
            "candidate_boxes": [],
        })
        entry["frame_count"] += 1
        entry["truth_visible_frame_count"] += bool(record["truth_visible"])
        entry["detection_count_ge_0_50"] += len(exact_boxes)
        if diagnostic_boxes:
            entry["candidate_boxes"].append(diagnostic_boxes[0])

    placement_results = []
    for entry in per_placement.values():
        boxes = entry.pop("candidate_boxes")
        best = max(boxes, key=lambda item: item["confidence"]) if boxes else None
        entry["maximum_confidence"] = (
            float(best["confidence"]) if best else 0.0
        )
        entry["best_bbox"] = best
        entry["detected"] = entry["detection_count_ge_0_50"] > 0
        placement_results.append(entry)

    classes = {}
    for class_name in TARGET_TABLES:
        selected = [
            item for item in placement_results
            if item["class_name"] == class_name
        ]
        maxima = [item["maximum_confidence"] for item in selected]
        detected = [item for item in selected if item["detected"]]
        worst = min(
            selected,
            key=lambda item: (
                item["maximum_confidence"],
                item["truth_visible_frame_count"],
                item["placement_id"],
            ),
        )
        classes[class_name] = {
            "placement_count": len(selected),
            "detected_placement_count": len(detected),
            "detection_success_rate": len(detected) / len(selected),
            "confidence_distribution": _distribution(maxima),
            "worst_position": worst,
            "placements": selected,
        }
    summary = {
        "schema_version": 1,
        "model_path": str(model_path.resolve()),
        "device": device,
        "formal_confidence": FORMAL_CONFIDENCE,
        "diagnostic_confidence": DIAGNOSTIC_CONFIDENCE,
        "frame_count": len(records),
        "classes": classes,
        "isolation": (
            "YOLO received image paths only. Gazebo label boxes and placement "
            "coordinates were used solely afterward to associate and aggregate "
            "evaluation results."
        ),
    }
    _write_json(output / "summary.json", summary)
    return summary


def main(argv=None) -> int:
    package_root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source-trial-dir",
        type=Path,
        default=Path(
            "/home/hao/robocup_assets/p2_eval/"
            "smoke_multitable_seed_20260914"
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
    parser.add_argument(
        "--model-resources",
        type=Path,
        default=Path(
            "/home/hao/wpr_ros2_ws/src/wpr_simulation_ros2/models"
        ),
    )
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--device", default="cpu")
    parser.add_argument(
        "--analyze-only",
        action="store_true",
        help="Resume analysis from an already complete frames.tsv capture.",
    )
    args = parser.parse_args(argv)
    started = time.monotonic()
    try:
        if args.analyze_only:
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
            class_document = _read_json(args.class_manifest)
            official_classes = [
                item["name"] for item in class_document["classes"]
            ]
            labels = {
                item["name"]: int(item["gazebo_label"])
                for item in class_document["classes"]
            }
            table_config = load_table_config(args.table_config)
            metadata = _read_json(
                args.source_trial_dir / "scenario_metadata.json"
            )
            design = build_design(table_config, metadata, labels)
            _write_json(args.output_dir / "design.json", design)
            world = args.output_dir / "tabletop_gate.world"
            create_gate_world(
                args.source_trial_dir / "scenario.world",
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
                package_root /
                "tools/p2_eval/tabletop_gate_capture_worker.cpp",
                args.model_resources,
            )
        summary = analyze(
            args.output_dir / "frames.tsv",
            args.model,
            args.device,
            args.output_dir,
        )
        summary["wall_seconds"] = time.monotonic() - started
        _write_json(args.output_dir / "summary.json", summary)
        print(json.dumps(summary, indent=2))
        return 0
    except (
        EvaluationConfigError,
        FileNotFoundError,
        OSError,
        RuntimeError,
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
        ET.ParseError,
        json.JSONDecodeError,
    ) as error:
        print(f"TABLETOP_GATE_FAILED: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
