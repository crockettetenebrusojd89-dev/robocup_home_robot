#!/usr/bin/env python3
"""Generate an auditable, targeted Formal 18-class Model V2 dataset."""

from __future__ import annotations

import argparse
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
import xml.etree.ElementTree as ET

from generate_dataset import load_manifest
from v2_common import (
    build_scenario_plan,
    load_v2_config,
    sha256_file,
    validate_asset_contract,
)


TOOL_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = TOOL_ROOT / "config" / "v2_smoke.json"
DEFAULT_MANIFEST = TOOL_ROOT / "classes.json"
DEFAULT_MODELS = Path.home() / "robocup_assets" / "official_models_v2"
DEFAULT_OUTPUT = Path.home() / "robocup_assets" / "datasets" / "formal_objects_v2_smoke"
WORLD = TOOL_ROOT / "worlds" / "formal_objects_dataset_v2.sdf"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--models", type=Path, default=DEFAULT_MODELS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def check_output(output: Path) -> None:
    if output.exists() and any(output.iterdir()):
        raise FileExistsError(f"output is not empty: {output}")


def check_world(classes: list[dict], config: dict) -> None:
    root = ET.parse(WORLD).getroot()
    world = root.find("world")
    if world is None or world.get("name") != "formal_objects_dataset_v2":
        raise ValueError("V2 training world name is invalid")
    mapping = []
    for include in world.findall("include"):
        label = include.findtext("plugin/label", "")
        uri = include.findtext("uri", "")
        if label and uri.startswith("model://"):
            mapping.append((include.findtext("name", ""), uri[8:], int(label)))
    expected = [(item["name"], item["name"], item["gazebo_label"]) for item in classes]
    if mapping != expected:
        raise ValueError("V2 world class mapping differs from classes.json")
    world_backgrounds = {
        model.get("name").removeprefix("background_")
        for model in world.findall("model")
        if model.get("name", "").startswith("background_")
    }
    config_backgrounds = {item["id"] for item in config["backgrounds"]}
    if world_backgrounds != config_backgrounds:
        raise ValueError("V2 world backgrounds differ from the config")


def compile_worker(build_dir: Path) -> Path:
    executable = build_dir / "capture_worker_v2"
    flags = subprocess.check_output(
        ["pkg-config", "--cflags", "--libs", "ignition-transport11", "ignition-msgs8", "opencv4"],
        text=True,
    )
    command = [
        "g++", "-std=c++17", "-O2", "-Wall", "-Wextra", "-Wpedantic",
        str(TOOL_ROOT / "scripts" / "capture_worker_v2.cpp"), "-o", str(executable),
        *shlex.split(flags),
    ]
    subprocess.run(command, check=True)
    return executable


def _runtime_row(record: dict) -> list[str]:
    primary = record["primary"]
    secondary = record["secondary"]
    if primary is None:
        primary_values = [-1, 0.0, 0.0, 0.0, 0.0]
    else:
        primary_values = [
            primary["class_id"], *primary["position_world_m"], math.radians(primary["yaw_deg"])
        ]
    if secondary is None:
        secondary_values = [-1, 0.0, 0.0, 0.0, 0.0]
    else:
        secondary_values = [
            secondary["class_id"], *secondary["position_world_m"], math.radians(secondary["yaw_deg"])
        ]
    camera = record["camera"]
    lighting = record["lighting"]
    return [
        record["sample_id"], record["split"],
        str(primary_values[0]), str(secondary_values[0]),
        *(f"{value:.12g}" for value in primary_values[1:]),
        *(f"{value:.12g}" for value in secondary_values[1:]),
        *(f"{value:.12g}" for value in camera["position_world_m"]),
        f"{camera['rpy_rad'][1]:.12g}", f"{camera['rpy_rad'][2]:.12g}",
        *(f"{value:.12g}" for value in lighting["main_rgb"]),
        f"{lighting['main_intensity']:.12g}",
        *(f"{value:.12g}" for value in lighting["direction_xyz"]),
        *(f"{value:.12g}" for value in lighting["ambient_fill_rgb"]),
        f"{lighting['ambient_fill_intensity']:.12g}",
    ]


def write_capture_plan(path: Path, records: list[dict]) -> None:
    header = [
        "sample_id", "split", "primary_id", "secondary_id",
        "primary_x", "primary_y", "primary_z", "primary_yaw",
        "secondary_x", "secondary_y", "secondary_z", "secondary_yaw",
        "camera_x", "camera_y", "camera_z", "camera_pitch", "camera_yaw",
        "main_r", "main_g", "main_b", "main_intensity",
        "main_dx", "main_dy", "main_dz",
        "fill_r", "fill_g", "fill_b", "fill_intensity",
    ]
    lines = ["\t".join(header)]
    lines.extend("\t".join(_runtime_row(record)) for record in records)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_dataset_metadata(
    output: Path,
    config: dict,
    classes: list[dict],
    asset_manifest: dict,
    records: list[dict],
) -> None:
    names = "".join(f"  {item['yolo_id']}: {item['name']}\n" for item in classes)
    (output / "data.yaml").write_text(
        f"path: {output.resolve()}\ntrain: images/train\nval: images/val\nnames:\n{names}",
        encoding="utf-8",
    )
    (output / "classes.json").write_text(
        json.dumps({"classes": classes}, indent=2) + "\n", encoding="utf-8"
    )
    (output / "generation_config.json").write_text(
        json.dumps(config, indent=2) + "\n", encoding="utf-8"
    )
    (output / "asset_manifest.json").write_text(
        json.dumps(asset_manifest, indent=2) + "\n", encoding="utf-8"
    )
    write_capture_plan(output / "capture_plan.tsv", records)


def finalize_manifest(output: Path, records: list[dict], classes: list[dict]) -> None:
    names = {item["yolo_id"]: item["name"] for item in classes}
    lines = []
    for record in records:
        image_path = output / record["image_path"]
        label_path = output / record["label_path"]
        bboxes = []
        for line in label_path.read_text(encoding="utf-8").splitlines():
            class_text, center_x, center_y, width, height = line.split()
            class_id = int(class_text)
            bboxes.append({
                "class_id": class_id,
                "class_name": names[class_id],
                "center_x": float(center_x),
                "center_y": float(center_y),
                "width": float(width),
                "height": float(height),
            })
        record["bboxes"] = bboxes
        record["image_sha256"] = sha256_file(image_path)
        lines.append(json.dumps(record, sort_keys=True, separators=(",", ":")))
    (output / "scenario_manifest.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")


def stop_process(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    os.killpg(process.pid, signal.SIGINT)
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=5)


def main() -> int:
    args = parse_args()
    config_path = args.config.expanduser().resolve()
    manifest_path = args.manifest.expanduser().resolve()
    models = args.models.expanduser().resolve()
    output = args.output.expanduser().resolve()
    classes = load_manifest(manifest_path)
    config = load_v2_config(config_path, [item["name"] for item in classes])
    check_world(classes, config)
    asset_manifest = validate_asset_contract(models, config, [item["name"] for item in classes])
    check_output(output)
    for relative in ("images/train", "images/val", "labels/train", "labels/val", "preview"):
        (output / relative).mkdir(parents=True, exist_ok=True)
    records = build_scenario_plan(config, classes, asset_manifest)
    write_dataset_metadata(output, config, classes, asset_manifest, records)

    with tempfile.TemporaryDirectory(prefix="formal_objects_v2_") as temporary:
        temporary_path = Path(temporary)
        worker = compile_worker(temporary_path)
        environment = os.environ.copy()
        environment["IGN_PARTITION"] = f"formal_objects_v2_{os.getpid()}_{config['seed']}"
        environment["IGN_HOMEDIR"] = str(temporary_path / "ign_home")
        old_resources = environment.get("IGN_GAZEBO_RESOURCE_PATH", "")
        environment["IGN_GAZEBO_RESOURCE_PATH"] = str(models) if not old_resources else f"{models}:{old_resources}"
        log_path = output / "gazebo.log"
        with log_path.open("w", encoding="utf-8") as gazebo_log:
            gazebo = subprocess.Popen(
                ["ign", "gazebo", "-s", "--headless-rendering", "-r", str(WORLD), "-v", "2"],
                env=environment,
                stdout=gazebo_log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
                text=True,
            )
            try:
                result = subprocess.run(
                    [
                        str(worker), str(output / "capture_plan.tsv"), str(output),
                        str(config["world"]["minimum_bbox_area_px"]), str(len(classes)),
                        *(item["name"] for item in classes),
                    ],
                    env=environment,
                    text=True,
                    check=False,
                )
                if result.returncode != 0:
                    time.sleep(0.5)
                    details = log_path.read_text(encoding="utf-8", errors="replace")
                    raise RuntimeError(
                        f"V2 capture worker failed with code {result.returncode}\nGazebo log:\n{details[-8000:]}"
                    )
            finally:
                stop_process(gazebo)

    finalize_manifest(output, records, classes)
    subprocess.run(
        [sys.executable, str(TOOL_ROOT / "scripts" / "validate_dataset.py"), str(output), "--manifest", str(manifest_path)],
        check=True,
    )
    print(f"DATASET_V2_READY {output}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (
        FileNotFoundError, FileExistsError, ValueError, RuntimeError,
        subprocess.CalledProcessError, ET.ParseError,
    ) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(1)
