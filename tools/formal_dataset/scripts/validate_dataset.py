#!/usr/bin/env python3
"""Validate class identity, image-label pairing, and YOLO boxes."""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys

from PIL import Image


TOOL_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = TOOL_ROOT / 'classes.json'


def parse_args() -> argparse.Namespace:
    """Parse a generated dataset and its authoritative manifest."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('dataset', type=Path)
    parser.add_argument('--manifest', type=Path, default=DEFAULT_MANIFEST)
    return parser.parse_args()


def load_classes(path: Path) -> list[dict]:
    """Read a manifest already structurally checked by the generator."""
    with path.open(encoding='utf-8') as stream:
        document = json.load(stream)
    classes = document.get('classes') if isinstance(document, dict) else None
    if not isinstance(classes, list) or not classes:
        raise ValueError(f'invalid class manifest: {path}')
    for index, item in enumerate(classes):
        if not isinstance(item, dict) or set(item) != {
            'yolo_id', 'name', 'gazebo_label'
        }:
            raise ValueError(f'invalid class entry at index {index}')
        name = item['name']
        if not isinstance(name, str) or not name:
            raise ValueError(f'invalid class name at index {index}')
        if item != {
            'yolo_id': index,
            'name': name,
            'gazebo_label': index + 1,
        }:
            raise ValueError(f'invalid class mapping at index {index}')
    return classes


def expected_data_yaml(root: Path, classes: list[dict]) -> str:
    """Return the only accepted data.yaml representation."""
    names = ''.join(
        f"  {item['yolo_id']}: {item['name']}\n" for item in classes
    )
    return (
        f'path: {root.resolve()}\n'
        'train: images/train\n'
        'val: images/val\n'
        'names:\n'
        f'{names}'
    )


def validate_split(
    root: Path,
    split: str,
    valid_ids: set[int],
) -> tuple[int, Counter, set[str]]:
    """Validate every image, matching label file, and normalized box."""
    image_dir = root / 'images' / split
    label_dir = root / 'labels' / split
    images = sorted(image_dir.glob('*.png'))
    labels = sorted(label_dir.glob('*.txt'))
    image_stems = {path.stem for path in images}
    label_stems = {path.stem for path in labels}
    if not images:
        raise ValueError(f'{split}: no images')
    if image_stems != label_stems:
        raise ValueError(
            f'{split}: image/label stems differ: '
            f'images_only={sorted(image_stems - label_stems)}, '
            f'labels_only={sorted(label_stems - image_stems)}'
        )

    counts = Counter()
    image_digests = set()
    for image_path in images:
        digest = hashlib.sha256(image_path.read_bytes()).hexdigest()
        if digest in image_digests:
            raise ValueError(f'{split}: duplicate image content at {image_path}')
        image_digests.add(digest)
        with Image.open(image_path) as image:
            if image.size != (640, 480):
                raise ValueError(
                    f'{image_path}: expected 640x480, got {image.size}'
                )
            image.verify()
        label_path = label_dir / f'{image_path.stem}.txt'
        lines = label_path.read_text(encoding='utf-8').splitlines()
        if not lines:
            raise ValueError(f'{label_path}: no object labels')
        seen_ids = set()
        for line_number, line in enumerate(lines, start=1):
            fields = line.split()
            if len(fields) != 5:
                raise ValueError(f'{label_path}:{line_number}: expected 5 fields')
            class_id = int(fields[0])
            if class_id not in valid_ids:
                raise ValueError(
                    f'{label_path}:{line_number}: invalid class {class_id}'
                )
            if class_id in seen_ids:
                raise ValueError(
                    f'{label_path}:{line_number}: duplicate class in one image'
                )
            seen_ids.add(class_id)
            values = [float(value) for value in fields[1:]]
            if not all(0.0 <= value <= 1.0 for value in values):
                raise ValueError(
                    f'{label_path}:{line_number}: bbox outside [0, 1]'
                )
            if values[2] <= 0.0 or values[3] <= 0.0:
                raise ValueError(f'{label_path}:{line_number}: empty bbox')
            counts[class_id] += 1
    return len(images), counts, image_digests


def main() -> int:
    """Validate a generated dataset and report per-class evidence."""
    args = parse_args()
    root = args.dataset.expanduser().resolve()
    manifest_path = args.manifest.expanduser().resolve()
    classes = load_classes(manifest_path)
    dataset_classes = load_classes(root / 'classes.json')
    if dataset_classes != classes:
        raise ValueError('dataset classes.json differs from the manifest')
    actual_yaml = (root / 'data.yaml').read_text(encoding='utf-8')
    if actual_yaml != expected_data_yaml(root, classes):
        raise ValueError('data.yaml does not exactly match the class manifest')

    valid_ids = {item['yolo_id'] for item in classes}
    totals = Counter()
    split_counts = {}
    split_digests = {}
    for split in ('train', 'val'):
        image_count, counts, digests = validate_split(root, split, valid_ids)
        split_counts[split] = counts
        split_digests[split] = digests
        totals.update(counts)
        print(f'VALID {split}: images={image_count} instances={sum(counts.values())}')

    overlap = split_digests['train'] & split_digests['val']
    if overlap:
        raise ValueError(f'train/val contain {len(overlap)} identical images')

    for item in classes:
        class_id = item['yolo_id']
        name = item['name']
        train_count = split_counts['train'][class_id]
        val_count = split_counts['val'][class_id]
        if train_count == 0 or val_count == 0:
            raise ValueError(
                f'class {name} must appear in both train and val splits'
            )
        print(
            f'CLASS {class_id:02d} {name}: '
            f'train={train_count} val={val_count} total={totals[class_id]}'
        )
    print(
        f'VALID total: classes={len(classes)} '
        f'instances={sum(totals.values())}'
    )
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f'INVALID: {error}', file=sys.stderr)
        raise SystemExit(1)
