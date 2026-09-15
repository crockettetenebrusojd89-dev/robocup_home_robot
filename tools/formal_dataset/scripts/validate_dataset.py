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

from v2_common import (
    SCHEMA_VERSION as V2_SCHEMA_VERSION,
    V2ConfigError,
    load_v2_config,
    policy_expected_counts,
    sha256_file,
)


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


def _read_boxes(path: Path, valid_ids: set[int]) -> list[dict]:
    boxes = []
    seen_ids = set()
    for line_number, line in enumerate(path.read_text(encoding='utf-8').splitlines(), start=1):
        fields = line.split()
        if len(fields) != 5:
            raise ValueError(f'{path}:{line_number}: expected 5 fields')
        class_id = int(fields[0])
        if class_id not in valid_ids:
            raise ValueError(f'{path}:{line_number}: invalid class {class_id}')
        if class_id in seen_ids:
            raise ValueError(f'{path}:{line_number}: duplicate class in one image')
        seen_ids.add(class_id)
        values = [float(value) for value in fields[1:]]
        if not all(0.0 <= value <= 1.0 for value in values):
            raise ValueError(f'{path}:{line_number}: bbox outside [0, 1]')
        if values[2] <= 0.0 or values[3] <= 0.0:
            raise ValueError(f'{path}:{line_number}: empty bbox')
        boxes.append({
            'class_id': class_id,
            'center_x': values[0],
            'center_y': values[1],
            'width': values[2],
            'height': values[3],
        })
    return boxes


def _difference_hash(image: Image.Image) -> int:
    resampling = getattr(Image, 'Resampling', Image)
    gray = image.convert('L').resize((9, 8), resampling.LANCZOS)
    pixels = list(gray.getdata())
    value = 0
    for row in range(8):
        for column in range(8):
            value = (value << 1) | int(
                pixels[row * 9 + column] > pixels[row * 9 + column + 1]
            )
    return value


def _near_black_fraction(
    image: Image.Image,
    box: dict,
    threshold: int,
) -> float:
    width, height = image.size
    x1 = max(0, int(round((box['center_x'] - box['width'] / 2) * width)))
    y1 = max(0, int(round((box['center_y'] - box['height'] / 2) * height)))
    x2 = min(width, int(round((box['center_x'] + box['width'] / 2) * width)))
    y2 = min(height, int(round((box['center_y'] + box['height'] / 2) * height)))
    pixels = list(image.crop((x1, y1, x2, y2)).convert('RGB').getdata())
    if not pixels:
        raise ValueError('beer bbox produced an empty image crop')
    return sum(max(pixel) < threshold for pixel in pixels) / len(pixels)


def _normalized_yaw_key(value: float) -> str:
    rounded = round(float(value), 8)
    return str(int(rounded)) if rounded.is_integer() else str(rounded)


def _close_sequence(actual: object, expected: object, tolerance: float = 1e-9) -> bool:
    if not isinstance(actual, list) or not isinstance(expected, list):
        return False
    return len(actual) == len(expected) and all(
        abs(float(left) - float(right)) <= tolerance
        for left, right in zip(actual, expected)
    )


def _validate_lighting(sample_id: str, lighting: object, profiles: dict[str, dict]) -> tuple:
    """Check that recorded light values are inside the declared physical profile."""
    required = {
        'seed', 'profile_id', 'main_rgb', 'main_intensity', 'direction_xyz',
        'ambient_fill_rgb', 'ambient_fill_intensity',
    }
    if not isinstance(lighting, dict) or not required <= set(lighting):
        raise ValueError(f'{sample_id}: incomplete lighting metadata')
    profile_id = lighting['profile_id']
    if profile_id not in profiles:
        raise ValueError(f'{sample_id}: unknown lighting profile {profile_id}')
    profile = profiles[profile_id]
    if not isinstance(lighting['seed'], int):
        raise ValueError(f'{sample_id}: lighting seed is not an integer')
    if not _close_sequence(lighting['main_rgb'], profile['main_rgb']):
        raise ValueError(f'{sample_id}: main light color differs from its profile')
    if not _close_sequence(lighting['ambient_fill_rgb'], profile['ambient_fill_rgb']):
        raise ValueError(f'{sample_id}: ambient fill color differs from its profile')
    direction = [float(value) for value in profile['direction_xyz']]
    length = sum(value * value for value in direction) ** 0.5
    expected_direction = [value / length for value in direction]
    if not _close_sequence(lighting['direction_xyz'], expected_direction):
        raise ValueError(f'{sample_id}: light direction differs from its profile')
    main_intensity = float(lighting['main_intensity'])
    if not profile['main_intensity'][0] <= main_intensity <= profile['main_intensity'][1]:
        raise ValueError(f'{sample_id}: main light intensity is outside its profile')
    fill_intensity = float(lighting['ambient_fill_intensity'])
    if not profile['ambient_fill_intensity'][0] <= fill_intensity <= profile['ambient_fill_intensity'][1]:
        raise ValueError(f'{sample_id}: ambient fill intensity is outside its profile')
    return (
        profile_id,
        tuple(round(float(value), 9) for value in lighting['main_rgb']),
        round(main_intensity, 9),
        tuple(round(float(value), 9) for value in lighting['direction_xyz']),
        tuple(round(float(value), 9) for value in lighting['ambient_fill_rgb']),
        round(fill_intensity, 9),
    )


def validate_v2_dataset(root: Path, classes: list[dict]) -> None:
    config = load_v2_config(
        root / 'generation_config.json', [item['name'] for item in classes]
    )
    asset_manifest = json.loads(
        (root / 'asset_manifest.json').read_text(encoding='utf-8')
    )
    if asset_manifest.get('schema_version') != V2_SCHEMA_VERSION:
        raise ValueError('asset_manifest.json has the wrong schema version')
    beer_files = asset_manifest.get('classes', {}).get('beer', {}).get('files', {})
    contract = config['asset_contract']['beer']
    if beer_files.get('model.sdf') != contract['model_sdf_sha256']:
        raise ValueError('dataset beer model.sdf hash differs from its config')
    if beer_files.get('materials/textures/beer.png') != contract['texture_sha256']:
        raise ValueError('dataset beer texture hash differs from its config')
    provenance_path = Path(asset_manifest.get('provenance_file', ''))
    if not provenance_path.is_file():
        raise ValueError('recorded V2 asset provenance file is unavailable')
    if sha256_file(provenance_path) != asset_manifest.get('provenance_sha256'):
        raise ValueError('recorded V2 asset provenance hash changed')

    manifest_path = root / 'scenario_manifest.jsonl'
    records = []
    for line_number, line in enumerate(
        manifest_path.read_text(encoding='utf-8').splitlines(), start=1
    ):
        try:
            record = json.loads(line)
        except json.JSONDecodeError as error:
            raise ValueError(f'{manifest_path}:{line_number}: {error}') from error
        required = {
            'schema_version', 'sample_id', 'image_path', 'label_path', 'split',
            'scene_group_id', 'random_seed', 'negative', 'primary', 'secondary',
            'background', 'placement_category', 'camera', 'lighting', 'bboxes',
            'image_sha256',
        }
        if not isinstance(record, dict) or not required <= set(record):
            raise ValueError(f'{manifest_path}:{line_number}: incomplete V2 record')
        if record['schema_version'] != V2_SCHEMA_VERSION:
            raise ValueError(f'{manifest_path}:{line_number}: wrong schema version')
        records.append(record)
    if not records:
        raise ValueError('scenario_manifest.jsonl is empty')

    valid_ids = {item['yolo_id'] for item in classes}
    class_names = {item['yolo_id']: item['name'] for item in classes}
    seen_samples = set()
    split_groups = {'train': set(), 'val': set()}
    split_digests = {'train': set(), 'val': set()}
    split_phashes = {'train': [], 'val': []}
    split_lighting = {'train': set(), 'val': set()}
    primary_counts = {'train': Counter(), 'val': Counter()}
    quota_actual = {
        split: {
            name: {
                'distance_band': Counter(), 'yaw_bin': Counter(),
                'placement_category': Counter(), 'background_id': Counter(),
                'lighting_profile': Counter(),
            }
            for name in config['class_policies']
        }
        for split in ('train', 'val')
    }
    negative_counts = Counter()
    beer_dark = []

    expected_images = {'train': set(), 'val': set()}
    expected_labels = {'train': set(), 'val': set()}
    profiles = {item['id']: item for item in config['lighting_profiles']}
    for record in records:
        sample_id = record['sample_id']
        split = record['split']
        if sample_id in seen_samples:
            raise ValueError(f'duplicate manifest sample_id: {sample_id}')
        seen_samples.add(sample_id)
        if split not in split_groups:
            raise ValueError(f'{sample_id}: invalid split {split}')
        split_groups[split].add(record['scene_group_id'])
        image_path = root / record['image_path']
        label_path = root / record['label_path']
        expected_images[split].add(image_path.name)
        expected_labels[split].add(label_path.name)
        if image_path.parent != root / 'images' / split:
            raise ValueError(f'{sample_id}: image path is outside its split')
        if label_path.parent != root / 'labels' / split:
            raise ValueError(f'{sample_id}: label path is outside its split')
        if not image_path.is_file() or not label_path.is_file():
            raise ValueError(f'{sample_id}: image or label is missing')
        digest = sha256_file(image_path)
        if digest != record['image_sha256']:
            raise ValueError(f'{sample_id}: image hash differs from manifest')
        if digest in split_digests[split]:
            raise ValueError(f'{split}: duplicate image content at {image_path}')
        split_digests[split].add(digest)
        split_lighting[split].add(
            (record['background']['id'], _validate_lighting(sample_id, record['lighting'], profiles))
        )
        with Image.open(image_path) as image:
            if image.size != (640, 480):
                raise ValueError(f'{sample_id}: expected 640x480 image')
            phash = _difference_hash(image)
            boxes = _read_boxes(label_path, valid_ids)
            manifest_boxes = [
                {
                    'class_id': item['class_id'], 'center_x': item['center_x'],
                    'center_y': item['center_y'], 'width': item['width'],
                    'height': item['height'],
                }
                for item in record['bboxes']
            ]
            if boxes != manifest_boxes:
                raise ValueError(f'{sample_id}: manifest bboxes differ from label file')
            if record['negative']:
                negative_counts[split] += 1
                if record['primary'] is not None or record['secondary'] is not None or boxes:
                    raise ValueError(f'{sample_id}: negative sample contains an object')
            else:
                primary = record['primary']
                if not isinstance(primary, dict) or not boxes:
                    raise ValueError(f'{sample_id}: positive sample lacks primary object or bbox')
                class_id = primary['class_id']
                class_name = primary['class_name']
                if class_names.get(class_id) != class_name:
                    raise ValueError(f'{sample_id}: primary class mapping is invalid')
                if class_id not in {item['class_id'] for item in boxes}:
                    raise ValueError(f'{sample_id}: primary class is absent from labels')
                if primary['asset_tree_sha256'] != asset_manifest['classes'][class_name]['tree_sha256']:
                    raise ValueError(f'{sample_id}: primary asset hash is invalid')
                primary_counts[split][class_name] += 1
                actual = quota_actual[split][class_name]
                distance_band = record['camera']['distance_band']
                actual['distance_band'][distance_band] += 1
                actual['yaw_bin'][_normalized_yaw_key(primary['yaw_bin_deg'])] += 1
                actual['placement_category'][record['placement_category']] += 1
                actual['background_id'][record['background']['id']] += 1
                actual['lighting_profile'][record['lighting']['profile_id']] += 1
                distance = float(record['camera']['object_distance_m'])
                low, high = config['distance_bands_m'][distance_band]
                if not low <= distance <= high:
                    raise ValueError(f'{sample_id}: distance lies outside its declared band')
                if class_name == 'beer':
                    beer_box = next(item for item in boxes if item['class_id'] == class_id)
                    beer_dark.append(_near_black_fraction(
                        image,
                        beer_box,
                        int(config['beer_visual_check']['near_black_channel_threshold']),
                    ))
            split_phashes[split].append((sample_id, phash))

    if split_groups['train'] & split_groups['val']:
        raise ValueError('scene_group_id leakage exists between train and val')
    if split_digests['train'] & split_digests['val']:
        raise ValueError('exact image leakage exists between train and val')
    if split_lighting['train'] & split_lighting['val']:
        raise ValueError('exact background/lighting combination leakage exists between train and val')
    for train_id, train_hash in split_phashes['train']:
        for val_id, val_hash in split_phashes['val']:
            if (train_hash ^ val_hash).bit_count() <= 1:
                raise ValueError(f'perceptual near-duplicate leakage: {train_id} / {val_id}')

    for split in ('train', 'val'):
        actual_images = {path.name for path in (root / 'images' / split).glob('*.png')}
        actual_labels = {path.name for path in (root / 'labels' / split).glob('*.txt')}
        if actual_images != expected_images[split] or actual_labels != expected_labels[split]:
            raise ValueError(f'{split}: files differ from scenario manifest')
        if negative_counts[split] != config['negative_samples'][split]:
            raise ValueError(f'{split}: negative sample quota mismatch')
        for class_name, policy in config['class_policies'].items():
            expected_total = policy['samples'][split]
            if primary_counts[split][class_name] != expected_total:
                raise ValueError(f'{split}/{class_name}: primary sample quota mismatch')
            expected = policy_expected_counts(config, class_name, split)
            for field, counts in expected.items():
                if quota_actual[split][class_name][field] != counts:
                    raise ValueError(f'{split}/{class_name}: {field} quota mismatch')

    if not beer_dark:
        raise ValueError('V2 dataset contains no primary beer sample')
    max_dark = float(config['beer_visual_check']['max_near_black_fraction'])
    failures = sum(value > max_dark for value in beer_dark)
    if failures:
        raise ValueError(
            f'beer visual anomaly: {failures}/{len(beer_dark)} boxes exceed '
            f'near-black fraction {max_dark:.3f}'
        )
    print(
        f'VALID V2: images={len(records)} positives={len(records) - sum(negative_counts.values())} '
        f'negatives={sum(negative_counts.values())}'
    )
    print(
        'VALID scene_group leakage=0 exact_image leakage=0 '
        'background_lighting leakage=0 perceptual_near_duplicate=0'
    )
    print(
        f'VALID beer: samples={len(beer_dark)} near_black_max={max(beer_dark):.4f} '
        f'near_black_median={sorted(beer_dark)[len(beer_dark) // 2]:.4f}'
    )
    for split in ('train', 'val'):
        print(
            f'VALID {split}: images={len(expected_images[split])} '
            f'negatives={negative_counts[split]} primary={dict(sorted(primary_counts[split].items()))}'
        )


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

    if (root / 'scenario_manifest.jsonl').is_file():
        validate_v2_dataset(root, classes)
        return 0

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
    except (OSError, ValueError, V2ConfigError, json.JSONDecodeError) as error:
        print(f'INVALID: {error}', file=sys.stderr)
        raise SystemExit(1)
