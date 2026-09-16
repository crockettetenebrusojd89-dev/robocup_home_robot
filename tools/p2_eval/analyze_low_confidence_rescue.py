#!/usr/bin/env python3
"""Evaluate a disabled, tabletop-only low-confidence rescue path offline.

This tool consumes diagnostic detections captured by ``analyze_visibility.py``.
It never publishes ROS messages and never changes the formal runtime answer.
Ground truth is used only after clustering, to score the counterfactual result.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path


DEFAULT_THRESHOLDS = (0.10, 0.15, 0.20, 0.30)
DEFAULT_CONFIRMATIONS = (2, 3, 5)


def point_on_tabletop(
    point_xyz,
    tables,
    *,
    xy_margin_m=0.05,
    below_surface_m=0.33,
    above_surface_m=0.12,
):
    """Return the fixed-table ROI containing a map point, or ``None``."""
    x, y, z = (float(value) for value in point_xyz)
    for table in tables:
        surface_z = float(table["surface_z_world_m"])
        if not surface_z - below_surface_m <= z <= surface_z + above_surface_m:
            continue
        center_x, center_y = table["center_world_m"]
        size_x, size_y = table["size_local_m"]
        yaw = float(table["yaw_world_rad"])
        dx = x - float(center_x)
        dy = y - float(center_y)
        local_x = math.cos(yaw) * dx + math.sin(yaw) * dy
        local_y = -math.sin(yaw) * dx + math.cos(yaw) * dy
        if (
            abs(local_x) <= float(size_x) / 2.0 + xy_margin_m
            and abs(local_y) <= float(size_y) / 2.0 + xy_margin_m
        ):
            return table["table_id"]
    return None


def cluster_candidates(candidates, radius_m=0.10):
    """Greedily cluster map candidates, allowing at most one hit/frame/cluster."""
    ordered = sorted(
        candidates,
        key=lambda item: (int(item["stamp_ns"]), -float(item["confidence"])),
    )
    clusters = []
    for candidate in ordered:
        stamp_ns = int(candidate["stamp_ns"])
        x, y, z = (float(value) for value in candidate["map_xyz"])
        compatible = []
        for index, cluster in enumerate(clusters):
            if stamp_ns in cluster["stamp_set"]:
                continue
            distance = math.hypot(x - cluster["x"], y - cluster["y"])
            if distance <= radius_m:
                compatible.append((distance, index))
        if compatible:
            _, index = min(compatible)
            cluster = clusters[index]
            count = len(cluster["candidates"])
            cluster["candidates"].append(candidate)
            cluster["stamp_set"].add(stamp_ns)
            cluster["x"] = (cluster["x"] * count + x) / (count + 1)
            cluster["y"] = (cluster["y"] * count + y) / (count + 1)
            cluster["z"] = (cluster["z"] * count + z) / (count + 1)
        else:
            clusters.append(
                {
                    "x": x,
                    "y": y,
                    "z": z,
                    "candidates": [candidate],
                    "stamp_set": {stamp_ns},
                }
            )
    return sorted(clusters, key=lambda cluster: len(cluster["stamp_set"]), reverse=True)


def score_clusters(clusters, ground_truth_xy, match_threshold_m=0.10):
    """One-to-one score cluster centroids against same-class ground truth."""
    possible_matches = []
    for cluster_index, cluster in enumerate(clusters):
        for truth_index, (truth_x, truth_y) in enumerate(ground_truth_xy):
            distance = math.hypot(cluster["x"] - truth_x, cluster["y"] - truth_y)
            if distance < match_threshold_m:
                possible_matches.append((distance, cluster_index, truth_index))
    matched_clusters = set()
    matched_truth = set()
    matches = []
    for distance, cluster_index, truth_index in sorted(possible_matches):
        if cluster_index in matched_clusters or truth_index in matched_truth:
            continue
        matched_clusters.add(cluster_index)
        matched_truth.add(truth_index)
        matches.append(
            {
                "cluster_index": cluster_index,
                "ground_truth_index": truth_index,
                "distance_m": distance,
            }
        )
    return {
        "TP": len(matches),
        "FP": len(clusters) - len(matches),
        "FN": len(ground_truth_xy) - len(matches),
        "matches": matches,
    }


def _serializable_cluster(cluster):
    confidences = [float(item["confidence"]) for item in cluster["candidates"]]
    return {
        "distinct_frames": len(cluster["stamp_set"]),
        "candidate_count": len(cluster["candidates"]),
        "centroid_map_xyz": [cluster["x"], cluster["y"], cluster["z"]],
        "maximum_confidence": max(confidences),
        "table_ids": sorted({item["table_id"] for item in cluster["candidates"]}),
    }


def analyze_run(
    run_dir,
    tables,
    *,
    thresholds=DEFAULT_THRESHOLDS,
    confirmations=DEFAULT_CONFIRMATIONS,
    decision_threshold=0.50,
    cluster_radius_m=0.10,
    match_threshold_m=0.10,
):
    run_dir = Path(run_dir)
    summary = json.loads((run_dir / "summary.json").read_text())
    objects_by_class = {}
    for item in summary["objects"]:
        position = item["ground_truth_world_m"]
        objects_by_class.setdefault(item["class_name"], []).append(
            (float(position["x"]), float(position["y"]))
        )

    candidates_by_class = {class_name: [] for class_name in summary["classes"]}
    runtime_frame_count = 0
    localized_runtime_frame_count = 0
    with (run_dir / "offline" / "offline_frames.jsonl").open() as stream:
        for line in stream:
            frame = json.loads(line)
            if not frame.get("runtime_sampled"):
                continue
            runtime_frame_count += 1
            frame_had_localization = False
            for class_name, target in frame["targets"].items():
                for candidate in target.get("diagnostic_localizations", []):
                    confidence = float(candidate["confidence"])
                    if confidence >= decision_threshold or not candidate.get("map_valid"):
                        continue
                    table_id = point_on_tabletop(candidate["map_xyz"], tables)
                    if table_id is None:
                        continue
                    frame_had_localization = True
                    candidates_by_class[class_name].append(
                        {
                            "stamp_ns": int(frame["stamp_ns"]),
                            "confidence": confidence,
                            "bbox_xyxy": candidate["bbox_xyxy"],
                            "depth_m": candidate["depth_m"],
                            "map_xyz": candidate["map_xyz"],
                            "table_id": table_id,
                        }
                    )
            if frame_had_localization:
                localized_runtime_frame_count += 1

    class_results = {}
    for class_name, formal in summary["classes"].items():
        class_candidates = candidates_by_class.get(class_name, [])
        eligible = formal["FN"] > 0 and formal["submitted_count"] == 0
        result = {
            "formal_result": {
                key: formal[key]
                for key in ("ground_truth_count", "submitted_count", "TP", "FP", "FN")
            },
            "rescue_eligible": eligible,
            "eligibility_reason": (
                "formal output absent with at least one false negative"
                if eligible
                else "normal path already produced output or class has no false negative"
            ),
            "tabletop_candidate_count_below_decision_threshold": len(class_candidates),
            "tabletop_candidate_frame_count_below_decision_threshold": len(
                {item["stamp_ns"] for item in class_candidates}
            ),
            "matrix": {},
        }
        ground_truth = objects_by_class.get(class_name, [])
        for threshold in thresholds:
            selected = [
                item for item in class_candidates if item["confidence"] >= threshold
            ]
            clusters = cluster_candidates(selected, radius_m=cluster_radius_m)
            threshold_key = f"{threshold:.2f}"
            result["matrix"][threshold_key] = {
                "candidate_count": len(selected),
                "candidate_frame_count": len({item["stamp_ns"] for item in selected}),
                "all_clusters": [_serializable_cluster(cluster) for cluster in clusters],
                "confirmations": {},
            }
            for confirmation in confirmations:
                accepted = [
                    cluster
                    for cluster in clusters
                    if len(cluster["stamp_set"]) >= confirmation
                ]
                scored = score_clusters(
                    accepted, ground_truth, match_threshold_m=match_threshold_m
                )
                result["matrix"][threshold_key]["confirmations"][str(confirmation)] = {
                    "accepted_clusters": [
                        _serializable_cluster(cluster) for cluster in accepted
                    ],
                    "counterfactual": scored if eligible else None,
                }
        class_results[class_name] = result

    capture_summary = json.loads(
        (run_dir / "capture" / "capture_summary.json").read_text()
    )
    capture_counts = capture_summary.get("counts", {})
    return {
        "run_dir": str(run_dir),
        "trial_id": summary["trial_id"],
        "formal_score": summary["base_task_score"],
        "runtime_frame_count": runtime_frame_count,
        "runtime_depth_saved": capture_counts.get("runtime_depth_saved"),
        "runtime_depth_missing": capture_counts.get("runtime_depth_missing"),
        "runtime_frames_with_at_least_one_tabletop_localization": (
            localized_runtime_frame_count
        ),
        "classes": class_results,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", action="append", required=True, type=Path)
    parser.add_argument("--tables", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--cluster-radius-m", type=float, default=0.10)
    args = parser.parse_args(argv)
    tables_document = json.loads(args.tables.read_text())
    report = {
        "schema_version": 1,
        "analysis_boundary": (
            "offline observational counterfactual; no ROS publication and no "
            "formal answer mutation"
        ),
        "policy": {
            "decision_threshold": 0.50,
            "thresholds": list(DEFAULT_THRESHOLDS),
            "confirmations": list(DEFAULT_CONFIRMATIONS),
            "cluster_radius_m": args.cluster_radius_m,
            "match_threshold_m": 0.10,
            "table_xy_margin_m": 0.05,
            "table_z_window_m": [-0.33, 0.12],
            "eligibility": (
                "requested class has FN and the normal path submitted zero instances"
            ),
        },
        "runs": [
            analyze_run(
                run_dir,
                tables_document["tables"],
                cluster_radius_m=args.cluster_radius_m,
            )
            for run_dir in args.run_dir
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
