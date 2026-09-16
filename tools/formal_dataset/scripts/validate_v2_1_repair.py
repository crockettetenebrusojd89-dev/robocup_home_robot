#!/usr/bin/env python3
"""Validate the bounded V2.1 repair supplement and all leakage contracts."""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys

from PIL import Image


TOOL_ROOT = Path(__file__).resolve().parents[1]


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


def load_jsonl(path: Path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def parse_label(path: Path):
    boxes = []
    for line in path.read_text(encoding="utf-8").splitlines():
        fields = line.split()
        if len(fields) != 5:
            raise ValueError(f"invalid label row: {path}")
        class_id = int(fields[0])
        values = [float(item) for item in fields[1:]]
        if not 0 <= class_id < 18 or not all(0.0 <= item <= 1.0 for item in values):
            raise ValueError(f"invalid label value: {path}")
        if values[2] <= 0.0 or values[3] <= 0.0:
            raise ValueError(f"empty bbox: {path}")
        boxes.append((class_id, *values))
    return boxes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", type=Path)
    args = parser.parse_args()
    root = args.dataset.expanduser().resolve()
    classes = json.loads((root / "classes.json").read_text(encoding="utf-8"))["classes"]
    canonical = json.loads((TOOL_ROOT / "classes.json").read_text(encoding="utf-8"))["classes"]
    if classes != canonical:
        raise ValueError("class mapping differs from the official manifest")
    names = {int(item["yolo_id"]): item["name"] for item in classes}
    contract = json.loads((root / "repair_contract.json").read_text(encoding="utf-8"))
    records = load_jsonl(root / "repair_manifest.jsonl")
    seen_ids = set()
    split_groups = {"train": set(), "val": set()}
    split_hashes = {"train": set(), "val": set()}
    counts = {"train": Counter(), "val": Counter()}
    negatives = Counter()
    expected_files = {"train": set(), "val": set()}
    for record in records:
        sample_id = record["sample_id"]
        split = record["split"]
        if sample_id in seen_ids or split not in split_groups:
            raise ValueError(f"duplicate sample or invalid split: {sample_id}")
        seen_ids.add(sample_id)
        split_groups[split].add(record["scene_group_id"])
        image = root / record["image_path"]
        label = root / record["label_path"]
        if not image.is_file() or not label.is_file():
            raise ValueError(f"missing pair: {sample_id}")
        expected_files[split].add(sample_id)
        if sha256_file(image) != record["image_sha256"]:
            raise ValueError(f"image hash differs: {sample_id}")
        if sha256_file(label) != record["label_sha256"]:
            raise ValueError(f"label hash differs: {sample_id}")
        if record["image_sha256"] in split_hashes[split]:
            raise ValueError(f"duplicate image content: {sample_id}")
        split_hashes[split].add(record["image_sha256"])
        with Image.open(image) as opened:
            if opened.size != (640, 480):
                raise ValueError(f"wrong image size: {sample_id}")
            opened.verify()
        boxes = parse_label(label)
        if record["negative"]:
            if boxes or record["bboxes"] or record["class_name"] is not None:
                raise ValueError(f"negative sample has an object: {sample_id}")
            negatives[split] += 1
        else:
            if len(boxes) != 1 or len(record["bboxes"]) != 1:
                raise ValueError(f"positive sample is not single-object: {sample_id}")
            class_id = boxes[0][0]
            if names[class_id] != record["class_name"]:
                raise ValueError(f"class mapping differs: {sample_id}")
            counts[split][record["class_name"]] += 1

    if split_groups["train"] & split_groups["val"]:
        raise ValueError("scene-group leakage exists")
    if split_hashes["train"] & split_hashes["val"]:
        raise ValueError("exact train/val image leakage exists")
    expected_positive = contract["positive_quotas"]
    for class_name, quotas in expected_positive.items():
        for split, expected in quotas.items():
            if counts[split][class_name] != expected:
                raise ValueError(f"{split}/{class_name} count differs")
    if dict(negatives) != contract["negative_quotas"]:
        raise ValueError("negative counts differ")
    if counts["train"]["beer"] or counts["val"]["beer"]:
        raise ValueError("repair supplement polluted beer")
    for split in ("train", "val"):
        image_stems = {path.stem for path in (root / "images" / split).glob("*.png")}
        label_stems = {path.stem for path in (root / "labels" / split).glob("*.txt")}
        if image_stems != expected_files[split] or label_stems != expected_files[split]:
            raise ValueError(f"{split} pairing differs from manifest")

    base = Path(contract["base_dataset"])
    base_hashes = {
        sha256_file(path) for split in ("train", "val")
        for path in (base / "images" / split).glob("*.png")
    }
    if base_hashes & (split_hashes["train"] | split_hashes["val"]):
        raise ValueError("repair has exact overlap with Formal V2")
    external_hashes = {
        sha256_file(path)
        for raw_root in contract["external_gate_roots"]
        for path in Path(raw_root).rglob("*.png")
    }
    if external_hashes & (split_hashes["train"] | split_hashes["val"]):
        raise ValueError("repair has exact overlap with external Gate")
    if contract["external_gate_exact_overlap"] != 0:
        raise ValueError("recorded external overlap is not zero")
    design = json.loads(
        (root / "capture" / "design.json").read_text(encoding="utf-8")
    )
    repair_poses = {
        (
            item["class_name"], round(float(item["world_x"]), 9),
            round(float(item["world_y"]), 9),
            round(float(item["world_yaw"]), 9),
        )
        for item in design["placements"]
    }
    repair_groups = {item["scene_group_id"] for item in design["placements"]}
    external_poses = set()
    external_groups = set()
    for raw_root in contract["external_gate_roots"]:
        for design_path in Path(raw_root).rglob("design.json"):
            external_design = json.loads(design_path.read_text(encoding="utf-8"))
            for item in external_design.get("placements", []):
                if all(key in item for key in ("class_name", "world_x", "world_y", "world_yaw")):
                    external_poses.add((
                        item["class_name"], round(float(item["world_x"]), 9),
                        round(float(item["world_y"]), 9),
                        round(float(item["world_yaw"]), 9),
                    ))
                external_groups.add(item.get("scene_group_id", item.get("id")))
    if repair_poses & external_poses:
        raise ValueError("repair has exact position/yaw overlap with external Gate")
    if repair_groups & external_groups:
        raise ValueError("repair has scene-group overlap with external Gate")
    if (
        contract["external_gate_exact_pose_yaw_overlap"] != 0
        or contract["external_gate_scene_group_overlap"] != 0
    ):
        raise ValueError("recorded external scenario overlap is not zero")
    model_resources = Path(contract["model_resources"])
    for class_name, expected_hash in contract["asset_tree_sha256"].items():
        if sha256_tree(model_resources / class_name) != expected_hash:
            raise ValueError(f"asset tree changed: {class_name}")
    print(
        "VALID V2.1 repair: "
        f"train={len(expected_files['train'])} val={len(expected_files['val'])} "
        f"negatives={dict(negatives)} beer=0"
    )
    print(
        "VALID leakage: scene_group=0 train_val_exact=0 V2_exact=0 "
        "external_gate_exact=0 external_pose_yaw=0 external_scene_group=0"
    )
    print(f"VALID classes: train={dict(counts['train'])} val={dict(counts['val'])}")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"INVALID V2.1 REPAIR: {error}", file=sys.stderr)
        raise SystemExit(1)
