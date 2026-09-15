#!/usr/bin/env python3
"""Train and evaluate one reproducible unified YOLO model."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import sys
import time

import torch
import ultralytics
from ultralytics import YOLO

from evaluation_core import create_dataset_view
from evaluation_core import load_class_names
from evaluation_core import require_model_contract


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
    parser.add_argument('--data-view', type=Path)
    parser.add_argument('--epochs', type=int, default=30)
    parser.add_argument('--batch', type=int, default=8)
    parser.add_argument('--workers', type=int, default=4)
    parser.add_argument('--device', default='cpu')
    parser.add_argument('--imgsz', type=int, default=640)
    parser.add_argument('--patience', type=int, default=10)
    parser.add_argument('--optimizer', default='AdamW')
    parser.add_argument('--lr0', type=float, default=0.0005)
    parser.add_argument('--lrf', type=float, default=0.1)
    parser.add_argument('--weight-decay', type=float, default=0.0005)
    parser.add_argument('--warmup-epochs', type=float, default=2.0)
    parser.add_argument('--cos-lr', action=argparse.BooleanOptionalAction,
                        default=True)
    parser.add_argument('--hsv-h', type=float, default=0.01)
    parser.add_argument('--hsv-s', type=float, default=0.4)
    parser.add_argument('--hsv-v', type=float, default=0.3)
    parser.add_argument('--translate', type=float, default=0.1)
    parser.add_argument('--scale', type=float, default=0.25)
    parser.add_argument('--mosaic', type=float, default=0.5)
    parser.add_argument('--close-mosaic', type=int, default=5)
    parser.add_argument('--fliplr', type=float, default=0.0)
    parser.add_argument('--multi-scale', action=argparse.BooleanOptionalAction,
                        default=False)
    parser.add_argument('--save-period', type=int, default=5)
    parser.add_argument('--seed', type=int, default=0)
    parser.add_argument('--deterministic',
                        action=argparse.BooleanOptionalAction, default=True)
    return parser.parse_args()


def require_positive(value: int, name: str) -> None:
    """Reject silently ineffective or nonsensical training sizes."""
    if isinstance(value, bool) or value <= 0:
        raise ValueError(f'{name} must be a positive integer')


def validate_inputs(args: argparse.Namespace) -> tuple[Path, Path, Path, Path]:
    """Validate the dataset before allowing an expensive training run."""
    require_positive(args.epochs, '--epochs')
    require_positive(args.batch, '--batch')
    require_positive(args.workers, '--workers')
    require_positive(args.imgsz, '--imgsz')
    require_positive(args.patience, '--patience')
    require_positive(args.save_period, '--save-period')
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
    data_yaml = dataset / 'data.yaml'
    if args.data_view is not None:
        data_view = args.data_view.expanduser().resolve()
        data_yaml = create_dataset_view(dataset, data_view)
    return dataset, model, project, data_yaml


def sha256_file(path: Path) -> str:
    """Return a stable identity for an input or output artifact."""
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def best_epoch(results_csv: Path) -> int | None:
    """Return the one-based epoch with the highest validation mAP50-95."""
    if not results_csv.is_file():
        return None
    with results_csv.open(encoding='utf-8', newline='') as stream:
        rows = list(csv.DictReader(stream))
    key = 'metrics/mAP50-95(B)'
    if not rows or key not in rows[0]:
        return None
    row = max(rows, key=lambda item: float(item[key]))
    return int(row['epoch'])


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
                'map50_95': float(box.maps[class_id]),
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
            'precision': float(box.mp),
            'recall': float(box.mr),
            'map50': float(box.map50),
            'map50_95': float(box.map),
            'map75': float(box.map75),
        },
        'per_class': per_class,
    }


def main() -> int:
    """Train, re-load best weights, evaluate, and persist exact metrics."""
    args = parse_args()
    dataset, model_path, project, data_yaml = validate_inputs(args)
    model = YOLO(str(model_path))
    class_names = load_class_names(dataset)
    require_model_contract(model.names, class_names)
    if torch.cuda.is_available():
        torch.cuda.reset_peak_memory_stats()
    started = time.monotonic()
    results = model.train(
        data=str(data_yaml),
        epochs=args.epochs,
        batch=args.batch,
        imgsz=args.imgsz,
        device=args.device,
        workers=args.workers,
        project=str(project),
        name=args.name,
        exist_ok=False,
        pretrained=True,
        seed=args.seed,
        deterministic=args.deterministic,
        patience=args.patience,
        optimizer=args.optimizer,
        lr0=args.lr0,
        lrf=args.lrf,
        weight_decay=args.weight_decay,
        warmup_epochs=args.warmup_epochs,
        cos_lr=args.cos_lr,
        hsv_h=args.hsv_h,
        hsv_s=args.hsv_s,
        hsv_v=args.hsv_v,
        translate=args.translate,
        scale=args.scale,
        mosaic=args.mosaic,
        close_mosaic=args.close_mosaic,
        fliplr=args.fliplr,
        flipud=0.0,
        multi_scale=args.multi_scale,
        save_period=args.save_period,
        cache=False,
        plots=True,
    )
    training_seconds = time.monotonic() - started
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
    arguments = {
        key: str(value) if isinstance(value, Path) else value
        for key, value in vars(args).items()
    }
    provenance = {
        'schema_version': 1,
        'dataset': str(dataset),
        'training_data_yaml': str(data_yaml),
        'dataset_evidence_sha256': {
            name: sha256_file(dataset / name)
            for name in (
                'data.yaml', 'classes.json', 'dataset_composition.json',
                'dataset_composition_manifest.jsonl',
            )
        },
        'starting_checkpoint': str(model_path),
        'starting_checkpoint_sha256': sha256_file(model_path),
        'arguments': arguments,
        'environment': document['environment'],
        'gpu_vram_bytes': (
            torch.cuda.get_device_properties(0).total_memory
            if torch.cuda.is_available() else None
        ),
        'training_seconds': training_seconds,
        'best_epoch': best_epoch(save_dir / 'results.csv'),
        'completed_epochs': sum(
            1 for _ in (save_dir / 'results.csv').open(encoding='utf-8')
        ) - 1,
        'best_checkpoint': str(best_weights),
        'best_checkpoint_sha256': sha256_file(best_weights),
        'last_checkpoint': str(save_dir / 'weights' / 'last.pt'),
        'last_checkpoint_sha256': sha256_file(
            save_dir / 'weights' / 'last.pt'
        ),
        'peak_gpu_memory_allocated_bytes': (
            torch.cuda.max_memory_allocated() if torch.cuda.is_available()
            else None
        ),
        'peak_gpu_memory_reserved_bytes': (
            torch.cuda.max_memory_reserved() if torch.cuda.is_available()
            else None
        ),
    }
    provenance_path = save_dir / 'training_provenance.json'
    provenance_path.write_text(
        json.dumps(provenance, indent=2) + '\n', encoding='utf-8'
    )
    print(f'MODEL_READY {best_weights}')
    print(f'EVALUATION_READY {report_path}')
    print(f'PROVENANCE_READY {provenance_path}')
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
