#!/usr/bin/env python3
"""Optimize one/two living-room observation points from map/table geometry."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sys
from typing import Any, Mapping

import cv2
import numpy as np
import yaml


ROBOT_HALF_LENGTH_M = 0.27
ROBOT_HALF_WIDTH_M = 0.25
ROBOT_RADIUS_M = math.hypot(ROBOT_HALF_LENGTH_M, ROBOT_HALF_WIDTH_M)


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def _table_local_to_world(table: Mapping[str, Any], local_xy: np.ndarray):
    yaw = float(table["yaw_world_rad"])
    rotation = np.array([
        [math.cos(yaw), -math.sin(yaw)],
        [math.sin(yaw), math.cos(yaw)],
    ])
    center = np.asarray(table["center_world_m"], dtype=float)
    return local_xy @ rotation.T + center


def legal_surface_samples(
    config: Mapping[str, Any], spacing_m: float
) -> tuple[np.ndarray, list[str]]:
    """Sample every legal object-center rectangle without object ground truth."""
    policy = config["placement_policy"]
    inset = (
        float(policy["edge_margin_m"])
        + float(policy["object_footprint_radius_m"])
    )
    all_samples = []
    table_ids = []
    for table in config["tables"]:
        size_x, size_y = (float(value) for value in table["size_local_m"])
        half_x = size_x / 2.0 - inset
        half_y = size_y / 2.0 - inset
        if half_x <= 0.0 or half_y <= 0.0:
            raise ValueError(f"empty legal region for {table['table_id']}")
        count_x = max(2, math.ceil(2.0 * half_x / spacing_m) + 1)
        count_y = max(2, math.ceil(2.0 * half_y / spacing_m) + 1)
        xs = np.linspace(-half_x, half_x, count_x)
        ys = np.linspace(-half_y, half_y, count_y)
        local = np.array([(x, y) for x in xs for y in ys], dtype=float)
        world = _table_local_to_world(table, local)
        all_samples.append(world)
        table_ids.extend([str(table["table_id"])] * len(world))
    return np.vstack(all_samples), table_ids


def _world_to_pixel(x, y, origin, resolution, height):
    column = int(math.floor((x - origin[0]) / resolution))
    row_from_bottom = int(math.floor((y - origin[1]) / resolution))
    return column, height - 1 - row_from_bottom


def _pixel_to_world(column, row, origin, resolution, height):
    return np.array([
        origin[0] + (column + 0.5) * resolution,
        origin[1] + (height - row - 0.5) * resolution,
    ])


def _distance_to_table(point: np.ndarray, table: Mapping[str, Any]) -> float:
    center = np.asarray(table["center_world_m"], dtype=float)
    yaw = float(table["yaw_world_rad"])
    delta = point - center
    local = np.array([
        math.cos(yaw) * delta[0] + math.sin(yaw) * delta[1],
        -math.sin(yaw) * delta[0] + math.cos(yaw) * delta[1],
    ])
    half = np.asarray(table["size_local_m"], dtype=float) / 2.0
    outside = np.maximum(np.abs(local) - half, 0.0)
    return float(np.linalg.norm(outside))


def navigable_candidates(
    map_yaml_path: Path,
    tables: list[Mapping[str, Any]],
    start_xy: tuple[float, float],
    structural_clearance_m: float,
    table_clearance_m: float,
    grid_stride_cells: int,
) -> tuple[np.ndarray, dict[str, Any]]:
    map_config = yaml.safe_load(map_yaml_path.read_text(encoding="utf-8"))
    image_path = (map_yaml_path.parent / map_config["image"]).resolve()
    image = cv2.imread(str(image_path), cv2.IMREAD_GRAYSCALE)
    if image is None:
        raise OSError(f"could not load occupancy image: {image_path}")
    resolution = float(map_config["resolution"])
    origin = tuple(float(value) for value in map_config["origin"][:2])
    height, width = image.shape
    free = (image >= 250).astype(np.uint8)
    clearance = cv2.distanceTransform(free, cv2.DIST_L2, 5) * resolution
    connectivity_clearance = ROBOT_RADIUS_M + 0.02
    traversable = (clearance >= connectivity_clearance).astype(np.uint8)
    count, labels = cv2.connectedComponents(traversable, connectivity=8)
    if count <= 1:
        raise ValueError("eroded map has no traversable component")
    start_column, start_row = _world_to_pixel(
        start_xy[0], start_xy[1], origin, resolution, height
    )
    if not (0 <= start_column < width and 0 <= start_row < height):
        raise ValueError("start pose lies outside occupancy map")
    start_label = int(labels[start_row, start_column])
    if start_label == 0:
        rows, columns = np.where(labels > 0)
        distances = (columns - start_column) ** 2 + (rows - start_row) ** 2
        nearest_index = int(np.argmin(distances))
        start_label = int(labels[rows[nearest_index], columns[nearest_index]])
    rows, columns = np.where(
        (labels == start_label) & (clearance >= structural_clearance_m)
    )
    keep_stride = (
        (rows % grid_stride_cells == 0)
        & (columns % grid_stride_cells == 0)
    )
    rows = rows[keep_stride]
    columns = columns[keep_stride]
    points = np.vstack([
        _pixel_to_world(column, row, origin, resolution, height)
        for row, column in zip(rows, columns)
    ])
    table_centers = np.vstack([
        np.asarray(table["center_world_m"], dtype=float) for table in tables
    ])
    room_min = table_centers.min(axis=0) - np.array([1.35, 1.15])
    room_max = table_centers.max(axis=0) + np.array([1.35, 1.15])
    room_mask = np.all((points >= room_min) & (points <= room_max), axis=1)
    points = points[room_mask]
    rows = rows[room_mask]
    columns = columns[room_mask]
    table_mask = np.array([
        min(_distance_to_table(point, table) for table in tables)
        >= table_clearance_m
        for point in points
    ])
    points = points[table_mask]
    rows = rows[table_mask]
    columns = columns[table_mask]
    structural = clearance[rows, columns]
    table_clearances = np.array([
        min(_distance_to_table(point, table) for table in tables)
        for point in points
    ])
    return points, {
        "map_image": str(image_path),
        "resolution_m": resolution,
        "candidate_count": len(points),
        "robot_circumscribed_radius_m": ROBOT_RADIUS_M,
        "connectivity_clearance_m": connectivity_clearance,
        "minimum_structural_clearance_m": float(structural.min()),
        "minimum_table_clearance_m": float(table_clearances.min()),
        "structural_clearance_by_candidate_m": structural,
        "table_clearance_by_candidate_m": table_clearances,
    }


def _coverage_masks(distances: np.ndarray, radius: float) -> list[int]:
    masks = []
    for row in distances <= radius:
        packed = np.packbits(row, bitorder="little")
        masks.append(int.from_bytes(packed.tobytes(), "little"))
    return masks


def _find_cover_pair(masks: list[int], full_mask: int):
    for first, first_mask in enumerate(masks):
        missing = full_mask & ~first_mask
        if not missing:
            return first, first
        for second in range(first + 1, len(masks)):
            if masks[second] & missing == missing:
                return first, second
    return None


def optimize_k2(distances: np.ndarray, upper_bound: float):
    full_mask = (1 << distances.shape[1]) - 1
    lower = 0.0
    upper = upper_bound
    best_pair = None
    for _ in range(18):
        midpoint = (lower + upper) / 2.0
        pair = _find_cover_pair(_coverage_masks(distances, midpoint), full_mask)
        if pair is None:
            lower = midpoint
        else:
            upper = midpoint
            best_pair = pair
    masks = _coverage_masks(distances, upper + 1e-6)
    feasible_pairs = []
    for first, first_mask in enumerate(masks):
        missing = full_mask & ~first_mask
        for second in range(first + 1, len(masks)):
            if masks[second] & missing != missing:
                continue
            exact = float(np.minimum(distances[first], distances[second]).max())
            feasible_pairs.append((exact, first, second))
    if not feasible_pairs:
        if best_pair is None:
            raise ValueError("could not find a two-point cover")
        first, second = best_pair
        worst = float(np.minimum(distances[first], distances[second]).max())
        return worst, first, second
    return min(feasible_pairs)


def _point_report(
    point: np.ndarray,
    index: int,
    candidate_meta: Mapping[str, Any],
    table_centroid: np.ndarray,
) -> dict[str, Any]:
    return {
        "x": float(point[0]),
        "y": float(point[1]),
        "suggested_yaw_rad": float(math.atan2(
            table_centroid[1] - point[1], table_centroid[0] - point[0]
        )),
        "structural_clearance_m": float(
            candidate_meta["structural_clearance_by_candidate_m"][index]
        ),
        "table_clearance_m": float(
            candidate_meta["table_clearance_by_candidate_m"][index]
        ),
        "same_start_connected_component": True,
    }


def optimize(
    table_config_path: Path,
    map_yaml_path: Path,
    output_path: Path,
    sample_spacing_m: float,
    structural_clearance_m: float,
    table_clearance_m: float,
    grid_stride_cells: int,
) -> dict[str, Any]:
    config = _read_json(table_config_path)
    samples, table_ids = legal_surface_samples(config, sample_spacing_m)
    candidates, candidate_meta = navigable_candidates(
        map_yaml_path,
        config["tables"],
        (-4.828, -0.477),
        structural_clearance_m,
        table_clearance_m,
        grid_stride_cells,
    )
    distances = np.linalg.norm(
        candidates[:, np.newaxis, :] - samples[np.newaxis, :, :], axis=2
    )
    one_worst = distances.max(axis=1)
    one_index = int(np.argmin(one_worst))
    two_worst, two_first, two_second = optimize_k2(
        distances, float(one_worst[one_index])
    )
    baseline = np.array([
        float(config["scan_pose_map"]["x"]),
        float(config["scan_pose_map"]["y"]),
    ])
    baseline_distances = np.linalg.norm(samples - baseline, axis=1)
    centroid = samples.mean(axis=0)
    camera = config["camera"]
    horizontal_fov = float(camera["horizontal_fov_rad"])
    vertical_fov = 2.0 * math.atan(
        math.tan(horizontal_fov / 2.0)
        * 480.0 / float(camera["image_width_px"])
    )

    def table_worst(point_indices):
        nearest = np.min(distances[list(point_indices)], axis=0)
        result = {}
        for table_id in sorted(set(table_ids)):
            mask = np.array([value == table_id for value in table_ids])
            result[table_id] = float(nearest[mask].max())
        return result

    result = {
        "schema_version": 1,
        "inputs": {
            "table_config": str(table_config_path.resolve()),
            "map_yaml": str(map_yaml_path.resolve()),
            "old_viewpoint_file_read": False,
            "world_to_map_assumption": (
                "world XY is used as map XY because the same saved map/scenario "
                "already passed the official objects-only scorer; corners are not "
                "used or connected to runtime"
            ),
            "legal_surface_sample_spacing_m": sample_spacing_m,
            "legal_surface_sample_count": len(samples),
            "candidate_grid_spacing_m": (
                candidate_meta["resolution_m"] * grid_stride_cells
            ),
            "candidate_count": candidate_meta["candidate_count"],
            "robot_footprint_m": [0.54, 0.50],
            "robot_circumscribed_radius_m": ROBOT_RADIUS_M,
            "required_structural_clearance_m": structural_clearance_m,
            "required_table_clearance_m": table_clearance_m,
            "camera_horizontal_fov_deg": math.degrees(horizontal_fov),
            "camera_vertical_fov_deg": math.degrees(vertical_fov),
            "camera_depth_max_m": float(camera["depth_max_m"]),
            "scan_coverage": "12 x 30 degrees at every observation point",
        },
        "baseline": {
            "x": float(baseline[0]),
            "y": float(baseline[1]),
            "worst_legal_surface_distance_m": float(baseline_distances.max()),
        },
        "one_point": {
            "points": [
                _point_report(
                    candidates[one_index], one_index, candidate_meta, centroid
                )
            ],
            "worst_legal_surface_distance_m": float(one_worst[one_index]),
            "per_table_worst_distance_m": table_worst([one_index]),
        },
        "two_point": {
            "points": [
                _point_report(
                    candidates[index], index, candidate_meta, centroid
                )
                for index in (two_first, two_second)
            ],
            "worst_legal_surface_distance_m": float(two_worst),
            "per_table_worst_distance_m": table_worst(
                [two_first, two_second]
            ),
        },
    }
    _write_json(output_path, result)
    return result


def main(argv=None) -> int:
    package_root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--table-config",
        type=Path,
        default=package_root / "tools/p2_eval/tables.json",
    )
    parser.add_argument(
        "--map-yaml",
        type=Path,
        default=package_root / "maps/example_map_v1.yaml",
    )
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--sample-spacing-m", type=float, default=0.025)
    parser.add_argument("--structural-clearance-m", type=float, default=0.65)
    parser.add_argument("--table-clearance-m", type=float, default=0.70)
    parser.add_argument("--grid-stride-cells", type=int, default=2)
    args = parser.parse_args(argv)
    try:
        result = optimize(
            args.table_config,
            args.map_yaml,
            args.output,
            args.sample_spacing_m,
            args.structural_clearance_m,
            args.table_clearance_m,
            args.grid_stride_cells,
        )
        print(json.dumps(result, indent=2))
        return 0
    except (OSError, ValueError, json.JSONDecodeError, yaml.YAMLError) as error:
        print(f"viewpoint optimization failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
