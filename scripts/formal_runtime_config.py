#!/usr/bin/env python3
"""Pure validation helpers for the formal base-task runtime."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Mapping, Sequence


def _load_json(path: Path) -> Any:
    def reject_duplicate_keys(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f'duplicate JSON key: {key!r}')
            result[key] = value
        return result

    try:
        with path.open('r', encoding='utf-8') as stream:
            return json.load(stream, object_pairs_hook=reject_duplicate_keys)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
        raise ValueError(f'Could not read JSON {path}: {error}') from error


def load_class_manifest(path: str | Path) -> tuple[str, ...]:
    """Return the exact sequential class names from the official manifest."""
    path = Path(path).expanduser()
    document = _load_json(path)
    if not isinstance(document, dict) or set(document) != {'classes'}:
        raise ValueError('Class manifest must contain exactly the classes key.')
    entries = document['classes']
    if not isinstance(entries, list) or not entries:
        raise ValueError('Class manifest classes must be a non-empty array.')

    names = []
    for expected_id, entry in enumerate(entries):
        location = f'classes[{expected_id}]'
        if not isinstance(entry, dict):
            raise ValueError(f'{location} must be an object.')
        if set(entry) != {'yolo_id', 'name', 'gazebo_label'}:
            raise ValueError(f'{location} has unexpected or missing keys.')
        if entry['yolo_id'] != expected_id:
            raise ValueError(f'{location}.yolo_id must be {expected_id}.')
        name = entry['name']
        if not isinstance(name, str) or not name:
            raise ValueError(f'{location}.name must be a non-empty string.')
        names.append(name)

    if len(set(names)) != len(names):
        raise ValueError('Class manifest contains duplicate names.')
    return tuple(names)


def load_aliases(
    path: str | Path,
    canonical_classes: Sequence[str],
) -> dict[str, str]:
    """Load an explicit raw-input to canonical-class alias map."""
    path = Path(path).expanduser()
    document = _load_json(path)
    if not isinstance(document, dict):
        raise ValueError('Alias configuration must be an object.')
    if set(document) != {'schema_version', 'aliases'}:
        raise ValueError(
            'Alias configuration must contain schema_version and aliases.'
        )
    if document['schema_version'] != 1:
        raise ValueError('Unsupported alias schema_version.')
    aliases = document['aliases']
    if not isinstance(aliases, dict):
        raise ValueError('aliases must be an object.')

    canonical = set(canonical_classes)
    validated = {}
    for raw_name, canonical_name in aliases.items():
        if not isinstance(raw_name, str) or not raw_name:
            raise ValueError('Alias keys must be non-empty strings.')
        if raw_name != raw_name.strip():
            raise ValueError(f'Alias key has surrounding whitespace: {raw_name!r}.')
        if raw_name in canonical:
            raise ValueError(f'Alias shadows canonical class {raw_name!r}.')
        if canonical_name not in canonical:
            raise ValueError(
                f'Alias {raw_name!r} maps to unknown class {canonical_name!r}.'
            )
        validated[raw_name] = canonical_name
    return validated


def resolve_target_classes(
    raw_targets: Sequence[str],
    canonical_classes: Sequence[str],
    aliases: Mapping[str, str],
) -> tuple[str, str, str]:
    """Resolve exactly three judge strings through an auditable boundary."""
    if len(raw_targets) != 3:
        raise ValueError('Exactly three judge target strings are required.')
    canonical = set(canonical_classes)
    resolved = []
    for index, raw_target in enumerate(raw_targets, start=1):
        if not isinstance(raw_target, str):
            raise ValueError(f'Target {index} must be a string.')
        normalized = raw_target.strip()
        if not normalized:
            raise ValueError(f'Target {index} must not be empty.')
        if normalized in canonical:
            resolved.append(normalized)
        elif normalized in aliases:
            resolved.append(aliases[normalized])
        else:
            raise ValueError(
                f'Unknown judge target {raw_target!r}; add an explicitly '
                'teacher-confirmed alias before competition.'
            )
    if len(set(resolved)) != 3:
        raise ValueError(
            'Judge targets must resolve to three distinct canonical classes.'
        )
    return tuple(resolved)


def filter_target_detections(
    detections: Sequence[Sequence[Any]],
    target_classes: Sequence[str],
) -> list[Sequence[Any]]:
    """Keep only detections whose first field is a requested target class."""
    targets = frozenset(target_classes)
    return [
        detection for detection in detections
        if detection and detection[0] in targets
    ]


def parse_group_number(raw_value: str | int) -> int:
    """Return one positive submission group number without bool coercion."""
    if isinstance(raw_value, bool):
        raise ValueError('group_number must be a positive integer.')
    if isinstance(raw_value, int):
        group_number = raw_value
    elif isinstance(raw_value, str) and raw_value.strip().isdigit():
        group_number = int(raw_value.strip())
    else:
        raise ValueError('group_number must be a positive integer.')
    if group_number <= 0:
        raise ValueError('group_number must be a positive integer.')
    return group_number


def ordered_model_names(model_names: Any) -> tuple[str, ...]:
    """Normalize Ultralytics list/dict names without changing their order."""
    if isinstance(model_names, dict):
        try:
            keys = sorted(model_names)
        except TypeError as error:
            raise ValueError('Model class IDs must be consistently typed.') from error
        if keys != list(range(len(keys))):
            raise ValueError('Model class IDs must be sequential from zero.')
        names = tuple(model_names[index] for index in keys)
    elif isinstance(model_names, (list, tuple)):
        names = tuple(model_names)
    else:
        raise ValueError('Model names must be a list, tuple, or ID mapping.')
    if any(not isinstance(name, str) or not name for name in names):
        raise ValueError('Model class names must be non-empty strings.')
    return names


def validate_model_contract(
    model_names: Any,
    expected_classes: Sequence[str],
    target_classes: Sequence[str],
) -> tuple[str, ...]:
    """Require the exact formal model class order and requested subset."""
    names = ordered_model_names(model_names)
    expected = tuple(expected_classes)
    if expected and names != expected:
        raise ValueError(
            'YOLO model classes do not exactly match the official manifest.'
        )
    missing = sorted(set(target_classes) - set(names))
    if missing:
        raise ValueError(f'YOLO model is missing target classes: {missing}.')
    return names


def validate_answer_document(
    document: Any,
    target_classes: Sequence[str],
) -> dict[str, int]:
    """Validate the saved objects-only answer and return per-class counts."""
    if not isinstance(document, dict) or set(document) != {'objects'}:
        raise ValueError('Answer must contain exactly the objects key.')
    objects = document['objects']
    if not isinstance(objects, dict) or set(objects) != set(target_classes):
        raise ValueError('Answer object keys must exactly match judge targets.')

    counts = {}
    for class_name in target_classes:
        instances = objects[class_name]
        if not isinstance(instances, list):
            raise ValueError(f'objects.{class_name} must be an array.')
        for index, point in enumerate(instances):
            if not isinstance(point, dict) or set(point) != {'x', 'y'}:
                raise ValueError(
                    f'objects.{class_name}[{index}] must contain x and y.'
                )
            for axis in ('x', 'y'):
                value = point[axis]
                if (
                    isinstance(value, bool)
                    or not isinstance(value, (int, float))
                    or not math.isfinite(float(value))
                ):
                    raise ValueError(
                        f'objects.{class_name}[{index}].{axis} '
                        'must be finite.'
                    )
        counts[class_name] = len(instances)
    return counts
