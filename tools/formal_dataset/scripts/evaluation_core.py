#!/usr/bin/env python3
"""Pure helpers for read-only Formal Model checkpoint evaluation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable, Mapping, Sequence


def load_class_names(dataset: Path) -> list[str]:
    """Load the canonical class order from a composed dataset."""
    document = json.loads((dataset / 'classes.json').read_text(encoding='utf-8'))
    classes = sorted(document['classes'], key=lambda item: item['yolo_id'])
    return [item['name'] for item in classes]


def ordered_model_names(model_names: Mapping | Sequence) -> list[str]:
    """Normalize Ultralytics dict/list class names into ID order."""
    if isinstance(model_names, Mapping):
        return [model_names[index] for index in sorted(model_names)]
    return list(model_names)


def require_model_contract(model_names: Mapping | Sequence,
                           expected_names: Sequence[str]) -> None:
    """Fail closed if a checkpoint changes the official class contract."""
    actual = ordered_model_names(model_names)
    if actual != list(expected_names):
        raise ValueError(
            f'checkpoint class order differs: expected={list(expected_names)} '
            f'actual={actual}'
        )


def create_dataset_view(dataset: Path, output: Path) -> Path:
    """Create a symlink-only loader view so cache files cannot touch source."""
    dataset = dataset.resolve()
    output = output.resolve()
    if output.exists() and any(output.iterdir()):
        raise FileExistsError(f'dataset view is not empty: {output}')
    names = load_class_names(dataset)
    for kind in ('images', 'labels'):
        for split in ('train', 'val'):
            source = dataset / kind / split
            destination = output / kind / split
            destination.mkdir(parents=True, exist_ok=True)
            for path in sorted(source.iterdir()):
                if path.is_file():
                    (destination / path.name).symlink_to(path.resolve())
    document = {
        'path': str(output),
        'train': 'images/train',
        'val': 'images/val',
        'names': {index: name for index, name in enumerate(names)},
    }
    data_yaml = output / 'data.yaml'
    data_yaml.write_text(json.dumps(document, indent=2) + '\n', encoding='utf-8')
    return data_yaml


def load_subset_images(dataset: Path, subset_file: Path,
                       data_root: Path | None = None) -> list[Path]:
    """Resolve a validated subset list against source or loader-view data."""
    dataset = dataset.resolve()
    data_root = dataset if data_root is None else data_root.resolve()
    paths = []
    seen = set()
    for raw_line in subset_file.read_text(encoding='utf-8').splitlines():
        relative = Path(raw_line.strip())
        if not raw_line.strip():
            continue
        if relative.is_absolute() or '..' in relative.parts:
            raise ValueError(f'unsafe subset path: {raw_line}')
        source_path = (dataset / relative).resolve()
        try:
            source_path.relative_to(dataset)
        except ValueError as error:
            raise ValueError(f'subset path escapes dataset: {raw_line}') from error
        if not source_path.is_file():
            raise FileNotFoundError(source_path)
        # Keep the view path itself rather than resolving its final symlink.
        # Ultralytics derives label/cache paths from this spelling, so resolving
        # here would accidentally direct cache files back into the source tree.
        target_path = data_root / relative
        if not target_path.is_file():
            raise FileNotFoundError(target_path)
        if target_path in seen:
            raise ValueError(f'duplicate subset path: {raw_line}')
        seen.add(target_path)
        paths.append(target_path)
    return paths


def write_subset_yaml(output: Path, data_root: Path, images: Sequence[Path],
                      names: Sequence[str]) -> Path:
    """Write an absolute image list and minimal Ultralytics subset YAML."""
    output.mkdir(parents=True, exist_ok=False)
    image_list = output / 'images.txt'
    image_list.write_text(
        ''.join(f'{path.absolute()}\n' for path in images), encoding='utf-8'
    )
    document = {
        'path': str(data_root.resolve()),
        'train': 'images/train',
        'val': str(image_list.resolve()),
        'names': {index: name for index, name in enumerate(names)},
    }
    data_yaml = output / 'data.yaml'
    data_yaml.write_text(json.dumps(document, indent=2) + '\n', encoding='utf-8')
    return data_yaml


def metrics_document(metrics, image_count: int) -> dict:
    """Convert aggregate and per-class Ultralytics metrics to stable JSON."""
    box = metrics.box
    metric_index = {
        int(class_id): index
        for index, class_id in enumerate(metrics.ap_class_index)
    }
    per_class = []
    for class_id, class_name in sorted(metrics.names.items()):
        index = metric_index.get(int(class_id))
        values = {
            'precision': None,
            'recall': None,
            'map50': None,
            'map50_95': None,
        }
        if index is not None:
            values = {
                'precision': float(box.p[index]),
                'recall': float(box.r[index]),
                'map50': float(box.ap50[index]),
                # maps is class-ID indexed even when p/r/ap50 are compacted to
                # only classes present in this validation subset.
                'map50_95': float(box.maps[int(class_id)]),
            }
        per_class.append({
            'yolo_id': int(class_id),
            'name': class_name,
            'validation_instances': int(metrics.nt_per_class[int(class_id)]),
            **values,
        })
    return {
        'image_count': image_count,
        'aggregate': {
            'precision': float(box.mp),
            'recall': float(box.mr),
            'map50': float(box.map50),
            'map50_95': float(box.map),
        },
        'per_class': per_class,
    }


def negative_detection_document(results: Iterable, names: Mapping[int, str],
                                image_count: int) -> dict:
    """Record every confidence-thresholded detection on negative images."""
    detections = []
    images_with_detections = set()
    for result in results:
        boxes = result.boxes
        if boxes is None:
            continue
        classes = boxes.cls.tolist()
        confidences = boxes.conf.tolist()
        for class_id, confidence in zip(classes, confidences):
            class_id = int(class_id)
            image = str(Path(result.path).resolve())
            images_with_detections.add(image)
            detections.append({
                'image': image,
                'class_id': class_id,
                'class_name': names[class_id],
                'confidence': float(confidence),
            })
    return {
        'image_count': image_count,
        'detection_count': len(detections),
        'images_with_detections': len(images_with_detections),
        'detections': detections,
    }
