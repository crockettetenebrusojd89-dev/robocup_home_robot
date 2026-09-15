#!/usr/bin/env python3
"""Build and validate the clean-replay plus targeted Formal V2 dataset."""

from __future__ import annotations

import argparse
from collections import Counter
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

from generate_dataset import load_manifest
from v2_common import sha256_file


TOOL_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = TOOL_ROOT / "classes.json"
EXPECTED_V1_IMAGES = {"train": 1800, "val": 360}
EXPECTED_REMOVED_BEER_IMAGES = {"train": 151, "val": 33}
EXPECTED_CLEAN_REPLAY = {"train": 1649, "val": 327}
EXPECTED_TARGETED = {"train": 570, "val": 154}
EXPECTED_FINAL = {"train": 2219, "val": 481}
COMPOSITION_SCHEMA_VERSION = 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--v1", type=Path, required=True)
    parser.add_argument("--targeted", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    return parser.parse_args()


def _read_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl(path: Path) -> list[dict]:
    records = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        try:
            record = json.loads(line)
        except json.JSONDecodeError as error:
            raise ValueError(f"{path}:{line_number}: {error}") from error
        if not isinstance(record, dict):
            raise ValueError(f"{path}:{line_number}: record must be an object")
        records.append(record)
    return records


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, records: list[dict]) -> None:
    path.write_text(
        "".join(
            json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n"
            for record in records
        ),
        encoding="utf-8",
    )


def _class_ids(label_path: Path, valid_ids: set[int]) -> list[int]:
    class_ids = []
    seen = set()
    for line_number, line in enumerate(label_path.read_text(encoding="utf-8").splitlines(), 1):
        fields = line.split()
        if len(fields) != 5:
            raise ValueError(f"{label_path}:{line_number}: expected five fields")
        class_id = int(fields[0])
        if class_id not in valid_ids:
            raise ValueError(f"{label_path}:{line_number}: invalid class {class_id}")
        if class_id in seen:
            raise ValueError(f"{label_path}:{line_number}: duplicate class")
        seen.add(class_id)
        values = [float(value) for value in fields[1:]]
        if not all(0.0 <= value <= 1.0 for value in values):
            raise ValueError(f"{label_path}:{line_number}: bbox outside [0, 1]")
        if values[2] <= 0.0 or values[3] <= 0.0:
            raise ValueError(f"{label_path}:{line_number}: empty bbox")
        class_ids.append(class_id)
    return class_ids


def _source_pairs(root: Path, split: str) -> list[tuple[Path, Path]]:
    image_dir = root / "images" / split
    label_dir = root / "labels" / split
    images = {path.stem: path for path in image_dir.glob("*.png")}
    labels = {path.stem: path for path in label_dir.glob("*.txt")}
    if set(images) != set(labels):
        raise ValueError(f"{root}/{split}: image/label pairing differs")
    return [(images[stem], labels[stem]) for stem in sorted(images)]


def _link(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    os.link(source, destination)


def _metadata_hashes(root: Path, names: tuple[str, ...]) -> dict[str, str]:
    return {name: sha256_file(root / name) for name in names}


def _data_yaml(root: Path, classes: list[dict]) -> str:
    names = "".join(f"  {item['yolo_id']}: {item['name']}\n" for item in classes)
    return (
        f"path: {root.resolve()}\n"
        "train: images/train\n"
        "val: images/val\n"
        "names:\n"
        f"{names}"
    )


def compose(v1: Path, targeted: Path, output: Path, manifest_path: Path) -> dict:
    """Create one immutable hard-linked training tree and its provenance."""
    v1 = v1.expanduser().resolve()
    targeted = targeted.expanduser().resolve()
    output = output.expanduser().resolve()
    manifest_path = manifest_path.expanduser().resolve()
    if output.exists():
        raise FileExistsError(f"output already exists: {output}")
    if v1 == targeted or output in {v1, targeted}:
        raise ValueError("source and output dataset paths must be distinct")
    classes = load_manifest(manifest_path)
    class_names = {item["yolo_id"]: item["name"] for item in classes}
    valid_ids = set(class_names)
    beer_id = next(item["yolo_id"] for item in classes if item["name"] == "beer")
    for source in (v1, targeted):
        if load_manifest(source / "classes.json") != classes:
            raise ValueError(f"class mapping differs: {source}")
        subprocess.run(
            [
                sys.executable,
                str(TOOL_ROOT / "scripts" / "validate_dataset.py"),
                str(source),
                "--manifest",
                str(manifest_path),
            ],
            check=True,
        )

    targeted_scenarios = _read_jsonl(targeted / "scenario_manifest.jsonl")
    scenarios_by_sample = {record["sample_id"]: record for record in targeted_scenarios}
    if len(scenarios_by_sample) != len(targeted_scenarios):
        raise ValueError("targeted scenario manifest contains duplicate sample IDs")

    composition_records: list[dict] = []
    excluded_records: list[dict] = []
    final_counts = Counter()
    source_counts = Counter()
    class_counts = {split: Counter() for split in ("train", "val")}
    validation_lists = {"legacy_val": [], "targeted_val": [], "negative_val": []}

    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=f".{output.name}.building-", dir=output.parent
    ) as temporary:
        staging = Path(temporary)
        for relative in (
            "images/train", "images/val", "labels/train", "labels/val",
            "metadata", "metadata/validation_subsets", "preview",
        ):
            (staging / relative).mkdir(parents=True, exist_ok=True)

        for split in ("train", "val"):
            pairs = _source_pairs(v1, split)
            if len(pairs) != EXPECTED_V1_IMAGES[split]:
                raise ValueError(f"V1 {split} image count changed: {len(pairs)}")
            removed = 0
            for image_path, label_path in pairs:
                ids = _class_ids(label_path, valid_ids)
                if beer_id in ids:
                    removed += 1
                    excluded_records.append({
                        "split": split,
                        "reason": "contains_legacy_beer",
                        "source_image": str(image_path),
                        "source_label": str(label_path),
                        "image_sha256": sha256_file(image_path),
                        "label_sha256": sha256_file(label_path),
                        "class_ids": ids,
                    })
                    continue
                stem = f"legacy_v1_{split}_{image_path.stem}"
                relative_image = Path("images") / split / f"{stem}.png"
                relative_label = Path("labels") / split / f"{stem}.txt"
                _link(image_path, staging / relative_image)
                _link(label_path, staging / relative_label)
                record = {
                    "schema_version": COMPOSITION_SCHEMA_VERSION,
                    "sample_id": stem,
                    "split": split,
                    "source": "legacy_v1_replay",
                    "validation_subset": f"legacy_{split}",
                    "source_sample_id": image_path.stem,
                    "source_image": str(image_path),
                    "source_label": str(label_path),
                    "image_path": relative_image.as_posix(),
                    "label_path": relative_label.as_posix(),
                    "image_sha256": sha256_file(image_path),
                    "label_sha256": sha256_file(label_path),
                    "negative": False,
                    "class_ids": ids,
                    "class_names": [class_names[class_id] for class_id in ids],
                    "scene_group_id": None,
                }
                composition_records.append(record)
                final_counts[split] += 1
                source_counts[("legacy_v1_replay", split)] += 1
                class_counts[split].update(ids)
                if split == "val":
                    validation_lists["legacy_val"].append(relative_image.as_posix())
            if removed != EXPECTED_REMOVED_BEER_IMAGES[split]:
                raise ValueError(f"V1 {split} legacy beer count changed: {removed}")

        for split in ("train", "val"):
            pairs = _source_pairs(targeted, split)
            if len(pairs) != EXPECTED_TARGETED[split]:
                raise ValueError(f"targeted {split} image count changed: {len(pairs)}")
            for image_path, label_path in pairs:
                ids = _class_ids(label_path, valid_ids)
                scenario = scenarios_by_sample.get(image_path.stem)
                if scenario is None or scenario.get("split") != split:
                    raise ValueError(
                        "targeted scenario is missing or misplaced: "
                        f"{image_path.stem}"
                    )
                negative = bool(scenario.get("negative"))
                if negative != (not ids):
                    raise ValueError(
                        "targeted negative declaration differs from label: "
                        f"{image_path.stem}"
                    )
                stem = f"v2_targeted_{split}_{image_path.stem}"
                relative_image = Path("images") / split / f"{stem}.png"
                relative_label = Path("labels") / split / f"{stem}.txt"
                _link(image_path, staging / relative_image)
                _link(label_path, staging / relative_label)
                subset = f"negative_{split}" if negative else f"targeted_{split}"
                record = {
                    "schema_version": COMPOSITION_SCHEMA_VERSION,
                    "sample_id": stem,
                    "split": split,
                    "source": "v2_targeted",
                    "validation_subset": subset,
                    "source_sample_id": image_path.stem,
                    "source_image": str(image_path),
                    "source_label": str(label_path),
                    "image_path": relative_image.as_posix(),
                    "label_path": relative_label.as_posix(),
                    "image_sha256": sha256_file(image_path),
                    "label_sha256": sha256_file(label_path),
                    "negative": negative,
                    "class_ids": ids,
                    "class_names": [class_names[class_id] for class_id in ids],
                    "scene_group_id": scenario["scene_group_id"],
                }
                composition_records.append(record)
                final_counts[split] += 1
                source_counts[("v2_targeted", split)] += 1
                class_counts[split].update(ids)
                if split == "val":
                    validation_lists[subset].append(relative_image.as_posix())

        if dict(final_counts) != EXPECTED_FINAL:
            raise ValueError(f"final image counts differ: {dict(final_counts)}")
        unique_sample_ids = {
            record["sample_id"] for record in composition_records
        }
        if len(unique_sample_ids) != len(composition_records):
            raise ValueError("composed filename collision")

        (staging / "classes.json").write_text(
            json.dumps({"classes": classes}, indent=2) + "\n", encoding="utf-8"
        )
        _write_jsonl(staging / "dataset_composition_manifest.jsonl", composition_records)
        _write_jsonl(staging / "metadata" / "excluded_legacy_beer.jsonl", excluded_records)
        evidence_files = (
            "generation_config.json", "asset_manifest.json", "scenario_manifest.jsonl",
            "capture_plan.tsv",
        )
        for name in evidence_files:
            _link(targeted / name, staging / "metadata" / f"targeted_{name}")
        for name in ("generation_config.json",):
            _link(v1 / name, staging / "metadata" / f"legacy_v1_{name}")
        for subset, paths in validation_lists.items():
            (staging / "metadata" / "validation_subsets" / f"{subset}.txt").write_text(
                "".join(f"{path}\n" for path in sorted(paths)), encoding="utf-8"
            )
        summary = {
            "schema_version": COMPOSITION_SCHEMA_VERSION,
            "output": str(output),
            "link_mode": "hardlink",
            "sources": {
                "legacy_v1_replay": str(v1),
                "v2_targeted": str(targeted),
            },
            "expected": {
                "v1_images": EXPECTED_V1_IMAGES,
                "removed_legacy_beer_images": EXPECTED_REMOVED_BEER_IMAGES,
                "clean_replay": EXPECTED_CLEAN_REPLAY,
                "targeted": EXPECTED_TARGETED,
                "final": EXPECTED_FINAL,
            },
            "actual": {
                "removed_legacy_beer_images": dict(Counter(
                    record["split"] for record in excluded_records
                )),
                "source_images": {
                    source: {split: source_counts[(source, split)] for split in ("train", "val")}
                    for source in ("legacy_v1_replay", "v2_targeted")
                },
                "final_images": dict(final_counts),
                "class_instances": {
                    split: {
                        class_names[class_id]: class_counts[split][class_id]
                        for class_id in sorted(valid_ids)
                    }
                    for split in ("train", "val")
                },
            },
            "source_metadata_sha256": {
                "legacy_v1": _metadata_hashes(v1, ("classes.json", "generation_config.json")),
                "v2_targeted": _metadata_hashes(targeted, ("classes.json", *evidence_files)),
            },
            "validation_subsets": {
                key: f"metadata/validation_subsets/{key}.txt" for key in sorted(validation_lists)
            },
        }
        _write_json(staging / "dataset_composition.json", summary)
        (staging / "data.yaml").write_text(_data_yaml(output, classes), encoding="utf-8")
        staging.rename(output)

    subprocess.run(
        [
            sys.executable,
            str(TOOL_ROOT / "scripts" / "validate_dataset.py"),
            str(output),
            "--manifest",
            str(manifest_path),
        ],
        check=True,
    )
    return summary


def main() -> int:
    args = parse_args()
    summary = compose(args.v1, args.targeted, args.output, args.manifest)
    print(
        "DATASET_V2_COMPOSED "
        f"{Path(summary['output'])} train={summary['actual']['final_images']['train']} "
        f"val={summary['actual']['final_images']['val']}"
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (
        FileNotFoundError, FileExistsError, ValueError, OSError,
        subprocess.CalledProcessError,
    ) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(1)
