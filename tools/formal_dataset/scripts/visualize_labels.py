#!/usr/bin/env python3
"""Render a contact sheet with YOLO boxes for human dataset inspection."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


COLORS = (
    '#e6194b', '#3cb44b', '#ffe119', '#4363d8', '#f58231', '#911eb4',
    '#46f0f0', '#f032e6', '#bcf60c', '#fabebe', '#008080', '#e6beff',
    '#9a6324', '#fffac8', '#800000', '#aaffc3', '#808000', '#000075',
)


def parse_args() -> argparse.Namespace:
    """Parse a dataset path and compact contact-sheet options."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('dataset', type=Path)
    parser.add_argument('--split', choices=('train', 'val'), default='val')
    parser.add_argument('--output', type=Path, default=Path('/tmp/formal_labels.png'))
    parser.add_argument('--max-images', type=int, default=18)
    return parser.parse_args()


def load_names(dataset: Path) -> list[str]:
    """Load class names from the immutable dataset metadata copy."""
    path = dataset / 'classes.json'
    with path.open(encoding='utf-8') as stream:
        document = json.load(stream)
    classes = document.get('classes') if isinstance(document, dict) else None
    if not isinstance(classes, list) or not classes:
        raise ValueError(f'invalid classes metadata: {path}')
    names = []
    for index, item in enumerate(classes):
        if not isinstance(item, dict) or item.get('yolo_id') != index:
            raise ValueError(f'invalid class mapping at index {index}')
        name = item.get('name')
        if not isinstance(name, str) or not name:
            raise ValueError(f'invalid class name at index {index}')
        names.append(name)
    return names


def draw_sample(image_path: Path, label_path: Path, names: list[str]) -> Image.Image:
    """Draw the normalized labels for one source image."""
    image = Image.open(image_path).convert('RGB')
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default()
    width, height = image.size
    for line in label_path.read_text(encoding='utf-8').splitlines():
        class_text, center_x, center_y, box_width, box_height = line.split()
        class_id = int(class_text)
        if class_id < 0 or class_id >= len(names):
            raise ValueError(f'{label_path}: invalid class ID {class_id}')
        center_x = float(center_x) * width
        center_y = float(center_y) * height
        box_width = float(box_width) * width
        box_height = float(box_height) * height
        bounds = (
            center_x - box_width / 2,
            center_y - box_height / 2,
            center_x + box_width / 2,
            center_y + box_height / 2,
        )
        color = COLORS[class_id % len(COLORS)]
        draw.rectangle(bounds, outline=color, width=3)
        label = names[class_id]
        text_width = len(label) * 6
        text_height = 11
        text_x = max(0, int(bounds[0]))
        text_y = max(0, int(bounds[1]) - text_height - 5)
        draw.rectangle(
            (text_x, text_y, text_x + text_width + 6, text_y + text_height + 4),
            fill='black',
        )
        draw.text(
            (text_x + 3, text_y + 2), label, fill=color, font=font,
        )
    return image


def main() -> int:
    """Build a deterministic contact sheet from one dataset split."""
    args = parse_args()
    dataset = args.dataset.expanduser().resolve()
    if args.max_images <= 0:
        raise ValueError('--max-images must be positive')
    names = load_names(dataset)
    image_paths = sorted((dataset / 'images' / args.split).glob('*.png'))
    image_paths = image_paths[:args.max_images]
    if not image_paths:
        raise ValueError(f'no {args.split} images in {dataset}')

    columns = min(3, len(image_paths))
    rows = math.ceil(len(image_paths) / columns)
    tile_width = 640
    tile_height = 510
    sheet = Image.new('RGB', (columns * tile_width, rows * tile_height), 'white')
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.load_default()
    for index, image_path in enumerate(image_paths):
        label_path = dataset / 'labels' / args.split / f'{image_path.stem}.txt'
        sample = draw_sample(image_path, label_path, names)
        x = (index % columns) * tile_width
        y = (index // columns) * tile_height
        sheet.paste(sample, (x, y))
        draw.text((x + 5, y + 486), image_path.stem, fill='black', font=font)

    output = args.output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output)
    print(f'PREVIEW_READY {output} images={len(image_paths)}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
