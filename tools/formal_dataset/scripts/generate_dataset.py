#!/usr/bin/env python3
"""Generate a configurable 18-class Gazebo Fortress YOLO dataset."""

from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import re
import shlex
import signal
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET


TOOL_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = TOOL_ROOT / 'config' / 'smoke.json'
DEFAULT_MANIFEST = TOOL_ROOT / 'classes.json'
DEFAULT_MODELS = Path.home() / 'robocup_assets' / 'official_models'
DEFAULT_OUTPUT = Path.home() / 'robocup_assets' / 'datasets' / 'formal_objects_smoke'
WORLD = TOOL_ROOT / 'worlds' / 'formal_objects_dataset.sdf'
CLASS_NAME_PATTERN = re.compile(r'^[a-z][a-z0-9_]*$')


def parse_args() -> argparse.Namespace:
    """Parse paths without downloading or installing anything."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=DEFAULT_CONFIG)
    parser.add_argument('--manifest', type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument('--models', type=Path, default=DEFAULT_MODELS)
    parser.add_argument('--output', type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def load_manifest(path: Path) -> list[dict]:
    """Load and strictly validate the fixed class identity mapping."""
    with path.open(encoding='utf-8') as stream:
        document = json.load(stream)
    if not isinstance(document, dict) or set(document) != {'classes'}:
        raise ValueError('manifest must contain only the classes key')
    classes = document['classes']
    if not isinstance(classes, list) or not classes:
        raise ValueError('manifest classes must be a non-empty list')

    expected_keys = {'yolo_id', 'name', 'gazebo_label'}
    names = set()
    for index, class_info in enumerate(classes):
        if not isinstance(class_info, dict) or set(class_info) != expected_keys:
            raise ValueError(f'classes[{index}] has invalid keys')
        if class_info['yolo_id'] != index:
            raise ValueError('YOLO IDs must be contiguous and match list order')
        if class_info['gazebo_label'] != index + 1:
            raise ValueError('Gazebo labels must be contiguous and one-based')
        name = class_info['name']
        if not isinstance(name, str) or not CLASS_NAME_PATTERN.fullmatch(name):
            raise ValueError(f'classes[{index}].name is not snake_case')
        if name in names:
            raise ValueError(f'duplicate class name: {name}')
        names.add(name)
    return classes


def _finite_range(config: dict, name: str) -> tuple[float, float]:
    """Validate one finite ascending two-number range."""
    value = config.get(name)
    if (
        not isinstance(value, list)
        or len(value) != 2
        or isinstance(value[0], bool)
        or isinstance(value[1], bool)
        or not all(isinstance(item, (int, float)) for item in value)
    ):
        raise ValueError(f'{name} must be a two-number list')
    low, high = (float(item) for item in value)
    if not all(math.isfinite(item) for item in (low, high)) or low > high:
        raise ValueError(f'{name} must be finite and ascending')
    return low, high


def load_config(path: Path, class_count: int) -> dict:
    """Load and validate dataset sizing and randomization parameters."""
    with path.open(encoding='utf-8') as stream:
        config = json.load(stream)
    required = {
        'seed',
        'train_images',
        'val_images',
        'secondary_object_fraction',
        'image',
        'randomization',
        'minimum_bbox_area_px',
    }
    if not isinstance(config, dict) or set(config) != required:
        raise ValueError('dataset config has missing or unexpected keys')
    for name in ('train_images', 'val_images'):
        count = config[name]
        if isinstance(count, bool) or not isinstance(count, int) or count < class_count:
            raise ValueError(f'{name} must be an integer >= class count')
        if count % class_count != 0:
            raise ValueError(f'{name} must be divisible by class count')
    if isinstance(config['seed'], bool) or not isinstance(config['seed'], int):
        raise ValueError('seed must be an integer')
    secondary_fraction = config['secondary_object_fraction']
    if (
        isinstance(secondary_fraction, bool)
        or not isinstance(secondary_fraction, (int, float))
        or not 0.0 <= float(secondary_fraction) <= 1.0
    ):
        raise ValueError('secondary_object_fraction must be in [0, 1]')
    minimum_area = config['minimum_bbox_area_px']
    if (
        isinstance(minimum_area, bool)
        or not isinstance(minimum_area, (int, float))
        or not math.isfinite(float(minimum_area))
        or minimum_area <= 0
    ):
        raise ValueError('minimum_bbox_area_px must be positive and finite')

    image = config['image']
    expected_image = {
        'width': 640,
        'height': 480,
        'horizontal_fov_rad': 1.2217304764,
        'near_clip_m': 0.2,
        'far_clip_m': 10.0,
    }
    if image != expected_image:
        raise ValueError('image settings must match the fixed Gazebo sensors')

    randomization = config['randomization']
    expected_ranges = {
        'object_x_m',
        'object_y_m',
        'object_yaw_rad',
        'camera_distance_m',
        'camera_height_m',
        'camera_lateral_offset_m',
        'camera_yaw_jitter_rad',
        'camera_pitch_jitter_rad',
    }
    if not isinstance(randomization, dict):
        raise ValueError('randomization must be an object')
    if set(randomization) != expected_ranges | {'minimum_object_spacing_m'}:
        raise ValueError('randomization has missing or unexpected keys')
    for name in expected_ranges:
        _finite_range(randomization, name)
    spacing = randomization['minimum_object_spacing_m']
    if (
        isinstance(spacing, bool)
        or not isinstance(spacing, (int, float))
        or not math.isfinite(float(spacing))
        or spacing <= 0
    ):
        raise ValueError('minimum_object_spacing_m must be positive and finite')
    return config


def check_world_and_models(classes: list[dict], models: Path) -> None:
    """Require every official model and exact world label mapping."""
    if not WORLD.is_file():
        raise FileNotFoundError(WORLD)
    root = ET.parse(WORLD).getroot()
    world = root.find('world')
    if world is None or world.get('name') != 'formal_objects_dataset':
        raise ValueError('training world name is invalid')

    world_mapping = []
    for include in world.findall('include'):
        uri = include.findtext('uri', '')
        name = include.findtext('name', '')
        label_text = include.findtext('plugin/label', '')
        if uri.startswith('model://') and label_text:
            world_mapping.append((name, uri.removeprefix('model://'), int(label_text)))
    expected_mapping = [
        (item['name'], item['name'], item['gazebo_label']) for item in classes
    ]
    if world_mapping != expected_mapping:
        raise ValueError('training world does not match classes.json exactly')

    for class_info in classes:
        model = models / class_info['name']
        for required in (model / 'model.config', model / 'model.sdf'):
            if not required.is_file():
                raise FileNotFoundError(f'missing official model: {required}')


def check_output(output: Path) -> None:
    """Refuse to overwrite any prior dataset evidence."""
    if output.exists() and any(output.iterdir()):
        raise FileExistsError(f'output is not empty: {output}')


def compile_worker(build_dir: Path) -> Path:
    """Compile the small local capture client against installed libraries."""
    source = TOOL_ROOT / 'scripts' / 'capture_worker.cpp'
    executable = build_dir / 'capture_worker'
    flags = subprocess.check_output(
        [
            'pkg-config',
            '--cflags',
            '--libs',
            'ignition-transport11',
            'ignition-msgs8',
            'opencv4',
        ],
        text=True,
    )
    command = [
        'g++', '-std=c++17', '-O2', '-Wall', '-Wextra', '-Wpedantic',
        str(source), '-o', str(executable),
    ]
    command.extend(shlex.split(flags))
    subprocess.run(command, check=True)
    return executable


def worker_command(
    executable: Path,
    output: Path,
    config: dict,
    classes: list[dict],
) -> list[str]:
    """Build the stable positional interface used by the C++ worker."""
    randomization = config['randomization']
    values = [
        output,
        config['train_images'],
        config['val_images'],
        config['seed'],
        config['minimum_bbox_area_px'],
        config['secondary_object_fraction'],
        *randomization['object_x_m'],
        *randomization['object_y_m'],
        *randomization['object_yaw_rad'],
        randomization['minimum_object_spacing_m'],
        *randomization['camera_distance_m'],
        *randomization['camera_height_m'],
        *randomization['camera_lateral_offset_m'],
        *randomization['camera_yaw_jitter_rad'],
        *randomization['camera_pitch_jitter_rad'],
        len(classes),
        *(item['name'] for item in classes),
    ]
    return [str(executable), *(str(value) for value in values)]


def write_metadata(output: Path, config: dict, classes: list[dict]) -> None:
    """Write exact class order and reproducibility inputs beside the dataset."""
    names = ''.join(
        f"  {item['yolo_id']}: {item['name']}\n" for item in classes
    )
    data_yaml = (
        f'path: {output.resolve()}\n'
        'train: images/train\n'
        'val: images/val\n'
        'names:\n'
        f'{names}'
    )
    (output / 'data.yaml').write_text(data_yaml, encoding='utf-8')
    (output / 'classes.json').write_text(
        json.dumps({'classes': classes}, indent=2) + '\n',
        encoding='utf-8',
    )
    (output / 'generation_config.json').write_text(
        json.dumps(config, indent=2) + '\n',
        encoding='utf-8',
    )


def stop_process(process: subprocess.Popen) -> None:
    """Stop the private Gazebo process without affecting competition Gazebo."""
    if process.poll() is not None:
        return
    os.killpg(process.pid, signal.SIGINT)
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=5)


def main() -> int:
    """Generate, annotate, and validate one dataset directory."""
    args = parse_args()
    manifest_path = args.manifest.expanduser().resolve()
    config_path = args.config.expanduser().resolve()
    models = args.models.expanduser().resolve()
    output = args.output.expanduser().resolve()
    classes = load_manifest(manifest_path)
    config = load_config(config_path, len(classes))
    check_world_and_models(classes, models)
    check_output(output)
    for relative in ('images/train', 'images/val', 'labels/train', 'labels/val'):
        (output / relative).mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix='formal_objects_dataset_') as temporary:
        temporary_path = Path(temporary)
        executable = compile_worker(temporary_path)
        environment = os.environ.copy()
        environment['IGN_PARTITION'] = (
            f"formal_objects_{os.getpid()}_{config['seed']}"
        )
        environment['IGN_HOMEDIR'] = str(temporary_path / 'ign_home')
        old_resources = environment.get('IGN_GAZEBO_RESOURCE_PATH', '')
        environment['IGN_GAZEBO_RESOURCE_PATH'] = (
            str(models) if not old_resources else f'{models}:{old_resources}'
        )
        log_path = temporary_path / 'gazebo.log'
        with log_path.open('w', encoding='utf-8') as gazebo_log:
            gazebo = subprocess.Popen(
                [
                    'ign', 'gazebo', '-s', '--headless-rendering', '-r',
                    str(WORLD), '-v', '2',
                ],
                env=environment,
                stdout=gazebo_log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
                text=True,
            )
            try:
                result = subprocess.run(
                    worker_command(executable, output, config, classes),
                    env=environment,
                    text=True,
                    check=False,
                )
                if result.returncode != 0:
                    time.sleep(0.5)
                    details = log_path.read_text(
                        encoding='utf-8', errors='replace'
                    )
                    raise RuntimeError(
                        f'capture worker failed with code {result.returncode}\n'
                        f'Gazebo log:\n{details[-8000:]}'
                    )
            finally:
                stop_process(gazebo)

    write_metadata(output, config, classes)
    subprocess.run(
        [
            sys.executable,
            str(TOOL_ROOT / 'scripts' / 'validate_dataset.py'),
            str(output),
            '--manifest',
            str(manifest_path),
        ],
        check=True,
    )
    print(f'DATASET_READY {output}')
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (
        FileNotFoundError,
        FileExistsError,
        ValueError,
        RuntimeError,
        subprocess.CalledProcessError,
    ) as error:
        print(f'ERROR: {error}', file=sys.stderr)
        raise SystemExit(1)
