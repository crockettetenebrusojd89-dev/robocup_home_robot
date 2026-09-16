#!/usr/bin/env python3
"""Generate one bounded competition-room V2.1 detector repair supplement."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
import math
import os
from pathlib import Path
import random
import shutil
import sys


TOOL_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = TOOL_ROOT.parents[1]
P2_ROOT = PACKAGE_ROOT / "tools" / "p2_eval"
sys.path.insert(0, str(P2_ROOT))

from p2_eval_core import legal_center_half_extents  # noqa: E402
from p2_eval_core import load_table_config  # noqa: E402
from run_18_class_robustness_audit import create_audit_world  # noqa: E402
from run_tabletop_robustness_gate import _manifest_records  # noqa: E402
from run_tabletop_robustness_gate import capture  # noqa: E402


SEED = 2026091602
VIEWPOINTS = (
    {"index": 1, "x": -3.485, "y": -1.115, "yaw": -0.532},
    {"index": 2, "x": 0.265, "y": -0.665, "yaw": -2.638},
)
POSITIVE_QUOTAS = {
    "banana": {"train": 140, "val": 35},
    "master_chef_can": {"train": 40, "val": 10},
    "coke_can": {"train": 40, "val": 10},
    "tomato_soup_can": {"train": 40, "val": 10},
    "tuna_fish_can": {"train": 32, "val": 8},
}
NEGATIVE_QUOTAS = {"train": 80, "val": 20}
GROUPS = {
    "banana": {"train": 50, "val": 14},
    "master_chef_can": {"train": 14, "val": 4},
    "coke_can": {"train": 14, "val": 4},
    "tomato_soup_can": {"train": 14, "val": 4},
    "tuna_fish_can": {"train": 11, "val": 3},
}


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-world", type=Path, required=True)
    parser.add_argument("--model-resources", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--external-root", type=Path, action="append", default=[])
    parser.add_argument(
        "--reuse-capture",
        action="store_true",
        help="Reuse this output's complete capture after a fail-closed selection error.",
    )
    parser.add_argument(
        "--manifest", type=Path, default=TOOL_ROOT / "classes.json"
    )
    parser.add_argument(
        "--table-config", type=Path, default=P2_ROOT / "tables.json"
    )
    return parser.parse_args()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_tree(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        relative = path.relative_to(root).as_posix().encode()
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        digest.update(bytes.fromhex(sha256_file(path)))
    return digest.hexdigest()


def load_classes(path: Path) -> list[dict]:
    document = json.loads(path.read_text(encoding="utf-8"))
    classes = document["classes"]
    if [item["yolo_id"] for item in classes] != list(range(18)):
        raise ValueError("class manifest is not the fixed 18-class mapping")
    return classes


def local_to_world(table: dict, local_x: float, local_y: float):
    center_x, center_y = table["center_world_m"]
    yaw = float(table["yaw_world_rad"])
    return (
        center_x + math.cos(yaw) * local_x - math.sin(yaw) * local_y,
        center_y + math.sin(yaw) * local_x + math.cos(yaw) * local_y,
    )


def nearest_distance(x: float, y: float) -> float:
    return min(
        math.hypot(x - viewpoint["x"], y - viewpoint["y"])
        for viewpoint in VIEWPOINTS
    )


def sample_placement(
    rng: random.Random, class_name: str, table: dict, policy: dict
):
    half_x, half_y = legal_center_half_extents(table, policy)
    for _ in range(1000):
        if class_name == "banana":
            local_x = rng.choice((-1.0, 1.0)) * rng.uniform(0.55, 1.0) * half_x
            local_y = rng.uniform(0.0, half_y)
        elif class_name == "tuna_fish_can":
            local_x = rng.choice((-1.0, 1.0)) * rng.uniform(0.70, 1.0) * half_x
            local_y = rng.choice((-1.0, 1.0)) * rng.uniform(0.70, 1.0) * half_y
        else:
            local_x = rng.uniform(-half_x, half_x)
            local_y = rng.uniform(-half_y, half_y)
        world_x, world_y = local_to_world(table, local_x, local_y)
        distance = nearest_distance(world_x, world_y)
        if class_name != "banana" or 1.90 <= distance <= 2.60:
            return local_x, local_y, world_x, world_y, distance
    raise RuntimeError(f"could not sample legal {class_name} repair placement")


def build_design(classes: list[dict], table_config: dict) -> dict:
    rng = random.Random(SEED)
    tables = {item["table_id"]: item for item in table_config["tables"]}
    ids = {item["name"]: item for item in classes}
    placements = []
    for class_name, split_counts in GROUPS.items():
        table = tables[
            "living_room_table_0" if class_name == "tuna_fish_can"
            else "living_room_table_3"
        ]
        for split in ("train", "val"):
            split_rng = random.Random(SEED + (0 if split == "train" else 1000003))
            split_rng.random()
            for index in range(split_counts[split]):
                local_x, local_y, world_x, world_y, distance = sample_placement(
                    rng if split == "train" else split_rng,
                    class_name,
                    table,
                    table_config["placement_policy"],
                )
                if class_name == "banana":
                    yaw = (
                        split_rng.choice((276, 282, 288, 294, 300, 306, 312, 324))
                        + split_rng.uniform(-2.7, 2.7)
                    ) % 360.0
                else:
                    yaw = split_rng.uniform(0.0, 360.0)
                placement_id = f"repair_{split}_{class_name}_{index:03d}"
                placements.append({
                    "id": placement_id,
                    "scene_group_id": placement_id,
                    "split": split,
                    "class_name": class_name,
                    "entity_name": f"p2_audit_{class_name}",
                    "gazebo_label": int(ids[class_name]["gazebo_label"]),
                    "table_id": table["table_id"],
                    "local_x": local_x,
                    "local_y": local_y,
                    "world_x": world_x,
                    "world_y": world_y,
                    "world_z": float(table["surface_z_world_m"]),
                    "world_yaw_deg": yaw,
                    "world_yaw": math.radians(yaw),
                    "nearest_viewpoint_distance_m": distance,
                    "region": "hard_corner" if class_name == "tuna_fish_can" else "repair",
                })
    return {
        "schema_version": 1,
        "seed": SEED,
        "viewpoints": VIEWPOINTS,
        "yaw_samples_per_viewpoint": 12,
        "classes": list(POSITIVE_QUOTAS),
        "positive_quotas": POSITIVE_QUOTAS,
        "negative_quotas": NEGATIVE_QUOTAS,
        "placements": placements,
    }


def write_plan(path: Path, design: dict, all_classes: list[dict]):
    lines = ["WORLD robocup_home p2_gate_camera", "YAW_SAMPLES 12"]
    for viewpoint in VIEWPOINTS:
        lines.append(
            "VIEW {index} {x:.12f} {y:.12f} {yaw:.12f}".format(**viewpoint)
        )
    lines.extend(f"HIDE p2_audit_{item['name']}" for item in all_classes)
    for item in design["placements"]:
        lines.append(
            "PLACEMENT {id} {class_name} {entity_name} {gazebo_label} "
            "{local_x:.12f} {local_y:.12f} {world_x:.12f} {world_y:.12f} "
            "{world_z:.12f} {world_yaw:.12f} {region}".format(**item)
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_negative_plan(path: Path, all_classes: list[dict]):
    """Use novel nearby camera poses so hard negatives are not Gate copies."""
    offsets = (
        (-0.045, -0.030, -0.061), (-0.030, 0.025, -0.043),
        (-0.015, -0.020, -0.027), (0.018, 0.032, 0.019),
        (0.041, -0.026, 0.047),
    )
    lines = ["WORLD robocup_home p2_gate_camera", "YAW_SAMPLES 12"]
    view_index = 1
    for base in VIEWPOINTS:
        for dx, dy, dyaw in offsets:
            lines.append(
                f"VIEW {view_index} {base['x'] + dx:.12f} "
                f"{base['y'] + dy:.12f} {base['yaw'] + dyaw:.12f}"
            )
            view_index += 1
    lines.extend(f"HIDE p2_audit_{item['name']}" for item in all_classes)
    lines.append(
        "PLACEMENT repair_background background p2_audit_banana 2 "
        "0 0 0 0 -5 0 background_only"
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def select_round_robin(records: list[dict], quota: int, rng: random.Random):
    by_group = defaultdict(list)
    for record in records:
        by_group[record["placement_id"]].append(record)
    for values in by_group.values():
        rng.shuffle(values)
    groups = sorted(by_group)
    rng.shuffle(groups)
    selected = []
    while groups and len(selected) < quota:
        remaining = []
        for group in groups:
            values = by_group[group]
            if values and len(selected) < quota:
                selected.append(values.pop())
            if values:
                remaining.append(group)
        groups = remaining
    if len(selected) != quota:
        raise RuntimeError(f"only {len(selected)}/{quota} eligible frames")
    return selected


def write_dataset(
    output: Path,
    capture_root: Path,
    negative_capture_root: Path,
    design: dict,
    classes: list[dict],
    external_roots: list[Path],
    model_resources: Path,
):
    records = _manifest_records(capture_root / "frames.tsv")
    placement = {item["id"]: item for item in design["placements"]}
    selected = []
    for class_name, quotas in POSITIVE_QUOTAS.items():
        for split, quota in quotas.items():
            eligible = []
            for record in records:
                item = placement[record["placement_id"]]
                if (
                    item["split"] != split
                    or record["class_name"] != class_name
                    or not record["truth_visible"]
                ):
                    continue
                short_side = min(
                    record["truth_x2"] - record["truth_x1"],
                    record["truth_y2"] - record["truth_y1"],
                )
                if class_name == "banana" and not 5.0 <= short_side <= 18.0:
                    continue
                eligible.append(record)
            selected.extend(select_round_robin(
                eligible, quota, random.Random(SEED + len(selected))
            ))

    negative_records = _manifest_records(negative_capture_root / "frames.tsv")
    negative_split = {
        viewpoint: ("val" if viewpoint in (5, 10) else "train")
        for viewpoint in range(1, 11)
    }
    for split, quota in NEGATIVE_QUOTAS.items():
        eligible = [
            record for record in negative_records
            if negative_split[record["viewpoint"]] == split
            and not record["truth_visible"]
        ]
        negatives = select_round_robin(
            eligible, quota, random.Random(SEED + 9000 + len(selected))
        )
        for record in negatives:
            record = dict(record)
            record["negative"] = True
            record["negative_split"] = split
            selected.append(record)

    for relative in ("images/train", "images/val", "labels/train", "labels/val"):
        (output / relative).mkdir(parents=True, exist_ok=True)
    class_ids = {item["name"]: int(item["yolo_id"]) for item in classes}
    evidence = []
    counts = {split: Counter() for split in ("train", "val")}
    negative_counts = Counter()
    for index, record in enumerate(selected):
        negative = bool(record.get("negative", False))
        if negative:
            split = record["negative_split"]
            item = {
                "scene_group_id": (
                    f"repair_negative_{split}_view_{record['viewpoint']:02d}"
                ),
                "world_x": 0.0, "world_y": 0.0,
                "world_yaw_deg": 0.0,
                "nearest_viewpoint_distance_m": None,
            }
        else:
            item = placement[record["placement_id"]]
            split = item["split"]
        sample_id = f"v21_{split}_{index:06d}"
        image_out = output / "images" / split / f"{sample_id}.png"
        label_out = output / "labels" / split / f"{sample_id}.txt"
        os.link(record["image"], image_out)
        boxes = []
        if negative:
            label_out.write_text("", encoding="utf-8")
            negative_counts[split] += 1
        else:
            x1, y1, x2, y2 = (
                record["truth_x1"], record["truth_y1"],
                record["truth_x2"], record["truth_y2"],
            )
            box = {
                "class_id": class_ids[record["class_name"]],
                "class_name": record["class_name"],
                "center_x": (x1 + x2) / 1280.0,
                "center_y": (y1 + y2) / 960.0,
                "width": (x2 - x1) / 640.0,
                "height": (y2 - y1) / 480.0,
            }
            boxes.append(box)
            label_out.write_text(
                f"{box['class_id']} {box['center_x']:.9f} {box['center_y']:.9f} "
                f"{box['width']:.9f} {box['height']:.9f}\n",
                encoding="utf-8",
            )
            counts[split][record["class_name"]] += 1
        evidence.append({
            "schema_version": 1,
            "sample_id": sample_id,
            "split": split,
            "scene_group_id": item["scene_group_id"],
            "negative": negative,
            "class_name": None if negative else record["class_name"],
            "image_path": image_out.relative_to(output).as_posix(),
            "label_path": label_out.relative_to(output).as_posix(),
            "image_sha256": sha256_file(image_out),
            "label_sha256": sha256_file(label_out),
            "source_image": record["image"],
            "viewpoint": record["viewpoint"],
            "yaw_index": record["yaw_index"],
            "object_pose": {
                "x": item["world_x"], "y": item["world_y"],
                "yaw_deg": item["world_yaw_deg"],
            },
            "distance_m": item["nearest_viewpoint_distance_m"],
            "bboxes": boxes,
        })

    names = "".join(
        f"  {item['yolo_id']}: {item['name']}\n" for item in classes
    )
    (output / "data.yaml").write_text(
        f"path: {output.resolve()}\ntrain: images/train\nval: images/val\nnames:\n{names}",
        encoding="utf-8",
    )
    shutil.copy2(TOOL_ROOT / "classes.json", output / "classes.json")
    (output / "repair_manifest.jsonl").write_text(
        "".join(json.dumps(item, sort_keys=True) + "\n" for item in evidence),
        encoding="utf-8",
    )
    external_hashes = set()
    external_images = 0
    for root in external_roots:
        for path in root.rglob("*.png"):
            external_hashes.add(sha256_file(path))
            external_images += 1
    overlap = external_hashes & {item["image_sha256"] for item in evidence}
    if overlap:
        raise RuntimeError("V2.1 supplement overlaps immutable external Gate RGB")
    contract = {
        "schema_version": 1,
        "seed": SEED,
        "base_dataset": "/home/hao/robocup_assets/datasets/formal_objects_v2",
        "positive_quotas": POSITIVE_QUOTAS,
        "negative_quotas": NEGATIVE_QUOTAS,
        "actual_positive_counts": {
            split: dict(sorted(counts[split].items()))
            for split in ("train", "val")
        },
        "actual_negative_counts": dict(negative_counts),
        "asset_tree_sha256": {
            item["name"]: sha256_tree(model_resources / item["name"])
            for item in classes
        },
        "model_resources": str(model_resources.resolve()),
        "external_gate_roots": [str(path.resolve()) for path in external_roots],
        "external_gate_png_count": external_images,
        "external_gate_exact_overlap": 0,
        "external_gate_exact_pose_yaw_overlap": 0,
        "external_gate_scene_group_overlap": 0,
        "beer_supplement_instances": 0,
        "capture_design_sha256": sha256_file(capture_root / "design.json"),
        "capture_manifest_sha256": sha256_file(capture_root / "frames.tsv"),
        "negative_capture_manifest_sha256": sha256_file(
            negative_capture_root / "frames.tsv"
        ),
    }
    (output / "repair_contract.json").write_text(
        json.dumps(contract, indent=2) + "\n", encoding="utf-8"
    )


def main():
    args = parse_args()
    output = args.output.expanduser().resolve()
    classes = load_classes(args.manifest)
    capture_root = output / "capture"
    negative_capture_root = output / "negative_capture"
    if args.reuse_capture:
        if not (capture_root / "frames.tsv").is_file():
            raise FileNotFoundError("--reuse-capture requires complete frames.tsv")
        if (output / "repair_manifest.jsonl").exists():
            raise FileExistsError("repair dataset already exists")
        design = json.loads(
            (capture_root / "design.json").read_text(encoding="utf-8")
        )
        design["positive_quotas"] = POSITIVE_QUOTAS
    else:
        if output.exists():
            raise FileExistsError(output)
        output.mkdir(parents=True)
        design = build_design(classes, load_table_config(args.table_config))
        capture_root.mkdir()
        (capture_root / "design.json").write_text(
            json.dumps(design, indent=2) + "\n", encoding="utf-8"
        )
        world = capture_root / "repair.world"
        create_audit_world(
            args.source_world.expanduser().resolve(), world,
            [item["name"] for item in classes],
            {item["name"]: int(item["gazebo_label"]) for item in classes},
        )
        plan = capture_root / "capture_plan.tsv"
        write_plan(plan, design, classes)
        capture(
            world, plan, capture_root,
            P2_ROOT / "tabletop_gate_capture_worker.cpp",
            args.model_resources.expanduser().resolve(),
        )
    if not (negative_capture_root / "frames.tsv").is_file():
        negative_capture_root.mkdir(exist_ok=True)
        negative_plan = negative_capture_root / "capture_plan.tsv"
        write_negative_plan(negative_plan, classes)
        capture(
            capture_root / "repair.world", negative_plan,
            negative_capture_root,
            P2_ROOT / "tabletop_gate_capture_worker.cpp",
            args.model_resources.expanduser().resolve(),
        )
    write_dataset(
        output, capture_root, negative_capture_root, design, classes,
        [path.expanduser().resolve() for path in args.external_root],
        args.model_resources.expanduser().resolve(),
    )
    print(f"V2_1_REPAIR_READY {output}")


if __name__ == "__main__":
    try:
        main()
    except (FileExistsError, OSError, RuntimeError, ValueError) as error:
        print(f"V2_1_REPAIR_FAILED: {error}", file=sys.stderr)
        raise SystemExit(1)
