#!/usr/bin/env python3
"""
Deterministic, evaluation-only P2 scenario generation helpers.

This module is intentionally independent of ROS and the competition runtime.
It may read table geometry and create ground truth, but none of those values are
passed to the formal runtime.
"""

from __future__ import annotations

from copy import deepcopy
import json
import math
from pathlib import Path
import random
from typing import Any, Dict, Iterable, Mapping, Sequence
import xml.etree.ElementTree as ET


SCHEMA_VERSION = 1


class EvaluationConfigError(ValueError):
    """An evaluation input is malformed or unsafe."""


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise EvaluationConfigError(f"cannot read JSON {path}: {error}") from error


def _require_keys(value: Any, expected: Iterable[str], location: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise EvaluationConfigError(f"{location} must be a JSON object")
    expected_set = set(expected)
    actual = set(value)
    if actual != expected_set:
        raise EvaluationConfigError(
            f"{location} keys must be {sorted(expected_set)}; got {sorted(actual)}"
        )
    return value


def _finite_number(value: Any, location: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise EvaluationConfigError(f"{location} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise EvaluationConfigError(f"{location} must be finite")
    return result


def load_table_config(path: Path) -> Dict[str, Any]:
    document = _require_keys(
        _load_json(path),
        (
            "schema_version",
            "source_world",
            "eligibility_note",
            "scan_pose_map",
            "camera",
            "placement_policy",
            "tables",
        ),
        "table config",
    )
    if document["schema_version"] != SCHEMA_VERSION:
        raise EvaluationConfigError("unsupported table config schema_version")

    scan = _require_keys(document["scan_pose_map"], ("x", "y", "yaw"), "scan_pose_map")
    for name in scan:
        _finite_number(scan[name], f"scan_pose_map.{name}")

    camera = _require_keys(
        document["camera"],
        ("base_xyz_m", "pitch_rad", "horizontal_fov_rad", "image_width_px", "depth_max_m"),
        "camera",
    )
    if not isinstance(camera["base_xyz_m"], list) or len(camera["base_xyz_m"]) != 3:
        raise EvaluationConfigError("camera.base_xyz_m must contain three numbers")
    for index, value in enumerate(camera["base_xyz_m"]):
        _finite_number(value, f"camera.base_xyz_m[{index}]")
    for name in ("pitch_rad", "horizontal_fov_rad", "image_width_px", "depth_max_m"):
        _finite_number(camera[name], f"camera.{name}")

    policy = _require_keys(
        document["placement_policy"],
        ("edge_margin_m", "object_footprint_radius_m", "minimum_object_gap_m", "max_attempts"),
        "placement_policy",
    )
    for name in ("edge_margin_m", "object_footprint_radius_m", "minimum_object_gap_m"):
        value = _finite_number(policy[name], f"placement_policy.{name}")
        if value < 0.0:
            raise EvaluationConfigError(f"placement_policy.{name} must be non-negative")
    if isinstance(policy["max_attempts"], bool) or not isinstance(policy["max_attempts"], int):
        raise EvaluationConfigError("placement_policy.max_attempts must be an integer")
    if policy["max_attempts"] < 1:
        raise EvaluationConfigError("placement_policy.max_attempts must be positive")

    tables = document["tables"]
    if not isinstance(tables, list) or not tables:
        raise EvaluationConfigError("tables must be a non-empty array")
    seen = set()
    for index, table in enumerate(tables):
        location = f"tables[{index}]"
        table = _require_keys(
            table,
            (
                "table_id",
                "center_world_m",
                "size_local_m",
                "surface_z_world_m",
                "yaw_world_rad",
            ),
            location,
        )
        table_id = table["table_id"]
        if not isinstance(table_id, str) or not table_id:
            raise EvaluationConfigError(f"{location}.table_id must be non-empty")
        if table_id in seen:
            raise EvaluationConfigError(f"duplicate table_id: {table_id}")
        seen.add(table_id)
        for field, length in (("center_world_m", 2), ("size_local_m", 2)):
            values = table[field]
            if not isinstance(values, list) or len(values) != length:
                raise EvaluationConfigError(
                    f"{location}.{field} must have {length} numbers"
                )
            for component, value in enumerate(values):
                parsed = _finite_number(
                    value,
                    f"{location}.{field}[{component}]",
                )
                if parsed <= 0.0 and field == "size_local_m":
                    raise EvaluationConfigError(f"{location}.{field} must be positive")
        _finite_number(table["surface_z_world_m"], f"{location}.surface_z_world_m")
        _finite_number(table["yaw_world_rad"], f"{location}.yaw_world_rad")
    return deepcopy(dict(document))


def load_scenario_spec(
    path: Path,
    official_classes: Sequence[str],
) -> Dict[str, Any]:
    document = _require_keys(
        _load_json(path),
        (
            "schema_version",
            "scenario_id",
            "seed",
            "group_number",
            "targets",
            "placements",
        ),
        "scenario spec",
    )
    if document["schema_version"] != SCHEMA_VERSION:
        raise EvaluationConfigError("unsupported scenario schema_version")
    if not isinstance(document["scenario_id"], str) or not document["scenario_id"]:
        raise EvaluationConfigError("scenario_id must be a non-empty string")
    if isinstance(document["seed"], bool) or not isinstance(document["seed"], int):
        raise EvaluationConfigError("seed must be an integer")
    if (
        isinstance(document["group_number"], bool)
        or not isinstance(document["group_number"], int)
        or document["group_number"] <= 0
    ):
        raise EvaluationConfigError("group_number must be a positive integer")
    targets = document["targets"]
    if not isinstance(targets, list) or len(targets) != 3 or len(set(targets)) != 3:
        raise EvaluationConfigError("targets must contain exactly three distinct classes")
    unknown = sorted(set(targets) - set(official_classes))
    if unknown:
        raise EvaluationConfigError(f"targets are not official classes: {unknown}")
    placements = document["placements"]
    if not isinstance(placements, list) or not placements:
        raise EvaluationConfigError("placements must be a non-empty array")
    present = set()
    for index, placement in enumerate(placements):
        placement = _require_keys(
            placement,
            ("class_name", "table_id"),
            f"placements[{index}]",
        )
        if placement["class_name"] not in targets:
            raise EvaluationConfigError(f"placements[{index}] class must be one of the targets")
        if not isinstance(placement["table_id"], str) or not placement["table_id"]:
            raise EvaluationConfigError(f"placements[{index}].table_id must be non-empty")
        present.add(placement["class_name"])
    missing = sorted(set(targets) - present)
    if missing:
        raise EvaluationConfigError(f"every target needs ground truth; missing {missing}")
    return deepcopy(dict(document))


def _local_to_world(
    table: Mapping[str, Any],
    local_x: float,
    local_y: float,
) -> tuple[float, float]:
    center_x, center_y = table["center_world_m"]
    yaw = float(table["yaw_world_rad"])
    cosine = math.cos(yaw)
    sine = math.sin(yaw)
    return (
        float(center_x) + cosine * local_x - sine * local_y,
        float(center_y) + sine * local_x + cosine * local_y,
    )


def legal_center_half_extents(
    table: Mapping[str, Any],
    policy: Mapping[str, Any],
) -> tuple[float, float]:
    inset = float(policy["edge_margin_m"]) + float(
        policy["object_footprint_radius_m"]
    )
    half_x = float(table["size_local_m"][0]) * 0.5 - inset
    half_y = float(table["size_local_m"][1]) * 0.5 - inset
    if half_x <= 0.0 or half_y <= 0.0:
        raise EvaluationConfigError(f"table {table['table_id']} has no legal placement area")
    return half_x, half_y


def table_distance_bounds(
    table: Mapping[str, Any],
    policy: Mapping[str, Any],
    scan_xy: tuple[float, float],
) -> tuple[float, float]:
    half_x, half_y = legal_center_half_extents(table, policy)
    center_x, center_y = (float(value) for value in table["center_world_m"])
    yaw = float(table["yaw_world_rad"])
    dx = scan_xy[0] - center_x
    dy = scan_xy[1] - center_y
    local_scan_x = math.cos(yaw) * dx + math.sin(yaw) * dy
    local_scan_y = -math.sin(yaw) * dx + math.cos(yaw) * dy
    closest_x = max(-half_x, min(half_x, local_scan_x))
    closest_y = max(-half_y, min(half_y, local_scan_y))
    nearest_world = _local_to_world(table, closest_x, closest_y)
    nearest = math.hypot(
        nearest_world[0] - scan_xy[0],
        nearest_world[1] - scan_xy[1],
    )
    farthest = max(
        math.hypot(world_x - scan_xy[0], world_y - scan_xy[1])
        for local_x in (-half_x, half_x)
        for local_y in (-half_y, half_y)
        for world_x, world_y in (_local_to_world(table, local_x, local_y),)
    )
    return nearest, farthest


def _place_objects(spec: Mapping[str, Any], config: Mapping[str, Any]) -> list[Dict[str, Any]]:
    randomizer = random.Random(spec["seed"])
    policy = config["placement_policy"]
    tables = {table["table_id"]: table for table in config["tables"]}
    scan_xy = (float(config["scan_pose_map"]["x"]), float(config["scan_pose_map"]["y"]))
    radius = float(policy["object_footprint_radius_m"])
    separation = radius * 2.0 + float(policy["minimum_object_gap_m"])
    accepted_by_table: Dict[str, list[tuple[float, float]]] = {name: [] for name in tables}
    class_counts: Dict[str, int] = {}
    generated = []

    for index, requested in enumerate(spec["placements"]):
        table_id = requested["table_id"]
        if table_id not in tables:
            raise EvaluationConfigError(f"unknown table_id in placement: {table_id}")
        table = tables[table_id]
        half_x, half_y = legal_center_half_extents(table, policy)
        for _attempt in range(int(policy["max_attempts"])):
            local_x = randomizer.uniform(-half_x, half_x)
            local_y = randomizer.uniform(-half_y, half_y)
            if all(
                math.hypot(local_x - prior_x, local_y - prior_y) >= separation
                for prior_x, prior_y in accepted_by_table[table_id]
            ):
                break
        else:
            raise EvaluationConfigError(
                f"could not place object {index} on {table_id} without overlap"
            )
        accepted_by_table[table_id].append((local_x, local_y))
        world_x, world_y = _local_to_world(table, local_x, local_y)
        class_name = requested["class_name"]
        class_index = class_counts.get(class_name, 0)
        class_counts[class_name] = class_index + 1
        local_yaw = randomizer.uniform(-math.pi, math.pi)
        world_yaw = float(table["yaw_world_rad"]) + local_yaw
        generated.append({
            "instance_name": f"p2_{class_name}_{class_index}",
            "class_name": class_name,
            "table_id": table_id,
            "table_local_position_m": {"x": local_x, "y": local_y},
            "world_position_m": {
                "x": world_x,
                "y": world_y,
                "z": float(table["surface_z_world_m"]),
            },
            "local_yaw_rad": local_yaw,
            "world_yaw_rad": world_yaw,
            "scan_stand_distance_m": math.hypot(world_x - scan_xy[0], world_y - scan_xy[1]),
        })
    return generated


def _world_tree(path: Path) -> ET.ElementTree:
    if path.suffix != ".world" or not path.is_file():
        raise EvaluationConfigError(f"base world must be an existing .world file: {path}")
    try:
        parser = ET.XMLParser(target=ET.TreeBuilder(insert_comments=True))
        return ET.parse(path, parser=parser)
    except (OSError, ET.ParseError) as error:
        raise EvaluationConfigError(f"cannot parse base world {path}: {error}") from error


def generate_trial(
    base_world: Path,
    table_config_path: Path,
    scenario_spec_path: Path,
    class_manifest_path: Path,
    output_directory: Path,
) -> Dict[str, Path]:
    """Generate world, truth, metadata, and truth-free runtime inputs."""
    if output_directory.exists():
        raise EvaluationConfigError(f"refusing to overwrite trial directory: {output_directory}")
    manifest = _require_keys(_load_json(class_manifest_path), ("classes",), "class manifest")
    raw_classes = manifest["classes"]
    if not isinstance(raw_classes, list) or len(raw_classes) != 18:
        raise EvaluationConfigError("official class manifest must contain 18 classes")
    official_classes = []
    for index, item in enumerate(raw_classes):
        item = _require_keys(item, ("yolo_id", "name", "gazebo_label"), f"classes[{index}]")
        if item["yolo_id"] != index or not isinstance(item["name"], str) or not item["name"]:
            raise EvaluationConfigError("official class manifest order/name is invalid")
        official_classes.append(item["name"])
    config = load_table_config(table_config_path)
    spec = load_scenario_spec(scenario_spec_path, official_classes)
    generated = _place_objects(spec, config)

    tree = _world_tree(base_world)
    root = tree.getroot()
    world = root.find("world")
    if world is None:
        raise EvaluationConfigError("base world does not contain one top-level world")
    official_set = set(official_classes)
    removed = []
    for include in list(world.findall("include")):
        uri = (include.findtext("uri") or "").strip()
        model_name = uri.rsplit("/", 1)[-1]
        if model_name in official_set:
            removed.append((include.findtext("name") or model_name).strip())
            world.remove(include)

    for item in generated:
        include = ET.SubElement(world, "include")
        ET.SubElement(include, "uri").text = f"model://{item['class_name']}"
        ET.SubElement(include, "name").text = item["instance_name"]
        position = item["world_position_m"]
        ET.SubElement(include, "pose").text = (
            f"{position['x']:.9f} {position['y']:.9f} {position['z']:.9f} "
            f"0 0 {item['world_yaw_rad']:.9f}"
        )

    output_directory.mkdir(parents=True)
    world_path = output_directory / "scenario.world"
    tree.write(world_path, encoding="utf-8", xml_declaration=True)
    ground_truth = {"objects": {name: [] for name in spec["targets"]}}
    for item in generated:
        position = item["world_position_m"]
        ground_truth["objects"][item["class_name"]].append({
            "x": position["x"],
            "y": position["y"],
        })
    ground_truth_path = output_directory / "ground_truth.json"
    ground_truth_path.write_text(json.dumps(ground_truth, indent=2) + "\n", encoding="utf-8")

    metadata = {
        "schema_version": SCHEMA_VERSION,
        "trial_id": spec["scenario_id"],
        "seed": spec["seed"],
        "base_world": str(base_world.resolve()),
        "generated_world": str(world_path.resolve()),
        "removed_official_object_instances": removed,
        "targets": spec["targets"],
        "group_number": spec["group_number"],
        "scan_pose_map": config["scan_pose_map"],
        "placement_policy": config["placement_policy"],
        "objects": generated,
    }
    metadata_path = output_directory / "scenario_metadata.json"
    metadata_path.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")

    runtime_inputs = {
        "world_file": str(world_path.resolve()),
        "world_name": world.get("name", "robocup_home"),
        "target_1": spec["targets"][0],
        "target_2": spec["targets"][1],
        "target_3": spec["targets"][2],
        "group_number": spec["group_number"],
    }
    runtime_inputs_path = output_directory / "runtime_inputs.json"
    runtime_inputs_path.write_text(json.dumps(runtime_inputs, indent=2) + "\n", encoding="utf-8")
    return {
        "world": world_path,
        "ground_truth": ground_truth_path,
        "metadata": metadata_path,
        "runtime_inputs": runtime_inputs_path,
    }
