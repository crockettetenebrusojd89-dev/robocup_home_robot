#!/usr/bin/env python3
"""Evaluate one checkpoint on overall, legacy, targeted, and negative V2 val."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import platform
import time

import torch
import ultralytics
from ultralytics import YOLO

from evaluation_core import load_class_names
from evaluation_core import load_subset_images
from evaluation_core import metrics_document
from evaluation_core import negative_detection_document
from evaluation_core import require_model_contract
from evaluation_core import write_subset_yaml


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--weights', type=Path, required=True)
    parser.add_argument('--dataset', type=Path, required=True)
    parser.add_argument('--data-view', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--device', default='0')
    parser.add_argument('--workers', type=int, default=4)
    parser.add_argument('--batch', type=int, default=8)
    parser.add_argument('--imgsz', type=int, default=640)
    parser.add_argument('--negative-conf', type=float, default=0.50)
    return parser.parse_args()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    args = parse_args()
    weights = args.weights.expanduser().resolve()
    dataset = args.dataset.expanduser().resolve()
    data_view = args.data_view.expanduser().resolve()
    output = args.output.expanduser().resolve()
    if not weights.is_file():
        raise FileNotFoundError(weights)
    if output.exists() and any(output.iterdir()):
        raise FileExistsError(f'evaluation output is not empty: {output}')
    output.mkdir(parents=True, exist_ok=True)

    names = load_class_names(dataset)
    model = YOLO(str(weights))
    require_model_contract(model.names, names)
    subset_root = dataset / 'metadata' / 'validation_subsets'
    subset_inputs = {
        'legacy': load_subset_images(
            dataset, subset_root / 'legacy_val.txt', data_view
        ),
        'targeted': load_subset_images(
            dataset, subset_root / 'targeted_val.txt', data_view
        ),
        'negative': load_subset_images(
            dataset, subset_root / 'negative_val.txt', data_view
        ),
    }
    data_yamls = {'overall': data_view / 'data.yaml'}
    for subset in ('legacy', 'targeted'):
        data_yamls[subset] = write_subset_yaml(
            output / 'inputs' / subset,
            data_view,
            subset_inputs[subset],
            names,
        )

    report = {
        'schema_version': 1,
        'weights': str(weights),
        'weights_sha256': sha256_file(weights),
        'dataset': str(dataset),
        'data_view': str(data_view),
        'environment': {
            'python': platform.python_version(),
            'torch': torch.__version__,
            'ultralytics': ultralytics.__version__,
            'cuda_build': torch.version.cuda,
            'cuda_available': torch.cuda.is_available(),
            'gpu': (
                torch.cuda.get_device_name(0)
                if torch.cuda.is_available() else None
            ),
        },
        'negative_confidence': args.negative_conf,
        'subsets': {},
    }
    counts = {
        'overall': sum(1 for path in (data_view / 'images' / 'val').iterdir()
                       if path.is_file()),
        'legacy': len(subset_inputs['legacy']),
        'targeted': len(subset_inputs['targeted']),
    }
    for subset in ('overall', 'legacy', 'targeted'):
        started = time.monotonic()
        metrics = model.val(
            data=str(data_yamls[subset]),
            device=args.device,
            workers=args.workers,
            batch=args.batch,
            imgsz=args.imgsz,
            plots=False,
            project=str(output / 'runs'),
            name=f'{subset}_val',
            exist_ok=False,
        )
        report['subsets'][subset] = {
            **metrics_document(metrics, counts[subset]),
            'runtime_seconds': time.monotonic() - started,
        }

    started = time.monotonic()
    results = model.predict(
        source=[str(path) for path in subset_inputs['negative']],
        device=args.device,
        batch=args.batch,
        imgsz=args.imgsz,
        conf=args.negative_conf,
        save=False,
        verbose=False,
        stream=True,
    )
    report['subsets']['negative'] = {
        **negative_detection_document(
            results, model.names, len(subset_inputs['negative'])
        ),
        'runtime_seconds': time.monotonic() - started,
    }
    report_path = output / 'evaluation.json'
    report_path.write_text(
        json.dumps(report, indent=2) + '\n', encoding='utf-8'
    )
    print(f'EVALUATION_READY {report_path}')
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (FileNotFoundError, FileExistsError, ValueError) as error:
        print(f'ERROR: {error}')
        raise SystemExit(1)
