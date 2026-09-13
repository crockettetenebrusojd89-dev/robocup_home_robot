#!/usr/bin/env python3
"""Train and evaluate one reproducible unified YOLO model."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import platform
import subprocess
import sys

import torch
import ultralytics
from ultralytics import YOLO


TOOL_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASET = (
    Path.home() / 'robocup_assets' / 'datasets' / 'formal_objects_v1'
)
DEFAULT_MODEL = (
    Path.home() / 'wpr_ros2_ws' / 'src' / 'robocup_home_robot'
    / 'models' / 'yolo11n.pt'
)
DEFAULT_PROJECT = Path.home() / 'robocup_assets' / 'training_runs'


def parse_args() -> argparse.Namespace:
    """Parse explicit training inputs and bounded CPU defaults."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset', type=Path, default=DEFAULT_DATASET)
    parser.add_argument('--model', type=Path, default=DEFAULT_MODEL)
    parser.add_argument('--project', type=Path, default=DEFAULT_PROJECT)
    parser.add_argument('--name', default='formal_objects_v1_yolo11n')
    parser.add_argument('--epochs', type=int, default=30)
    parser.add_argument('--batch', type=int, default=8)
    parser.add_argument('--workers', type=int, default=4)
    parser.add_argument('--device', default='cpu')
    return parser.parse_args()


def require_positive(value: int, name: str) -> None:
    """Reject silently ineffective or nonsensical training sizes."""
    if isinstance(value, bool) or value <= 0:
        raise ValueError(f'{name} must be a positive integer')


def validate_inputs(args: argparse.Namespace) -> tuple[Path, Path, Path]:
    """Validate the dataset before allowing an expensive training run."""
    require_positive(args.epochs, '--epochs')
    require_positive(args.batch, '--batch')
    require_positive(args.workers, '--workers')
    dataset = args.dataset.expanduser().resolve()
    model = args.model.expanduser().resolve()
    project = args.project.expanduser().resolve()
    if not model.is_file():
        raise FileNotFoundError(model)
    if not args.name or Path(args.name).name != args.name:
        raise ValueError('--name must be one non-empty directory name')
    save_dir = project / args.name
    if save_dir.exists() and any(save_dir.iterdir()):
        raise FileExistsError(f'training output is not empty: {save_dir}')
    subprocess.run(
        [
            sys.executable,
            str(TOOL_ROOT / 'scripts' / 'validate_dataset.py'),
            str(dataset),
        ],
        check=True,
    )
    return dataset, model, project


def evaluation_document(metrics, weights: Path) -> dict:
    """Convert aggregate and per-class Ultralytics metrics to stable JSON."""
    box = metrics.box
    metric_index = {
        int(class_id): index
        for index, class_id in enumerate(metrics.ap_class_index)
    }
    per_class = []
    for class_id, class_name in sorted(metrics.names.items()):
        index = metric_index.get(class_id)
        if index is None:
            class_metrics = {
                'precision': None,
                'recall': None,
                'map50': None,
                'map50_95': None,
            }
        else:
            class_metrics = {
                'precision': float(box.p[index]),
                'recall': float(box.r[index]),
                'map50': float(box.ap50[index]),
                'map50_95': float(box.maps[index]),
            }
        per_class.append({
            'yolo_id': int(class_id),
            'name': class_name,
            'validation_instances': int(metrics.nt_per_class[class_id]),
            **class_metrics,
        })
    return {
        'weights': str(weights.resolve()),
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
        'aggregate': {
            'map50': float(box.map50),
            'map50_95': float(box.map),
            'map75': float(box.map75),
        },
        'per_class': per_class,
    }


def main() -> int:
    """Train, re-load best weights, evaluate, and persist exact metrics."""
    args = parse_args()
    dataset, model_path, project = validate_inputs(args)
    data_yaml = dataset / 'data.yaml'
    model = YOLO(str(model_path))
    results = model.train(
        data=str(data_yaml),
        epochs=args.epochs,
        batch=args.batch,
        imgsz=640,
        device=args.device,
        workers=args.workers,
        project=str(project),
        name=args.name,
        exist_ok=False,
        pretrained=True,
        seed=0,
        deterministic=True,
        plots=True,
    )
    save_dir = Path(results.save_dir).resolve()
    best_weights = save_dir / 'weights' / 'best.pt'
    if not best_weights.is_file():
        raise FileNotFoundError(best_weights)
    metrics = YOLO(str(best_weights)).val(
        data=str(data_yaml),
        device=args.device,
        workers=args.workers,
        plots=True,
        project=str(save_dir),
        name='evaluation',
        exist_ok=False,
    )
    document = evaluation_document(metrics, best_weights)
    report_path = save_dir / 'evaluation.json'
    report_path.write_text(
        json.dumps(document, indent=2) + '\n', encoding='utf-8'
    )
    print(f'MODEL_READY {best_weights}')
    print(f'EVALUATION_READY {report_path}')
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (
        FileNotFoundError,
        FileExistsError,
        ValueError,
        subprocess.CalledProcessError,
    ) as error:
        print(f'ERROR: {error}', file=sys.stderr)
        raise SystemExit(1)
