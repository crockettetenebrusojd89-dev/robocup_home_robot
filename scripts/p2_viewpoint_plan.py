#!/usr/bin/env python3
"""Pure validation for a small, truth-independent observation plan."""

from __future__ import annotations

import json
import math


def parse_observation_plan(raw_value: str):
    """Validate a one-to-three-point plan supplied by the geometry optimizer."""
    try:
        document = json.loads(raw_value)
    except json.JSONDecodeError as error:
        raise ValueError(f"invalid observation plan JSON: {error}") from error
    if not isinstance(document, list) or not 1 <= len(document) <= 3:
        raise ValueError("observation plan must contain one to three points")
    plan = []
    for index, item in enumerate(document, start=1):
        if not isinstance(item, dict) or set(item) != {"x", "y", "yaw"}:
            raise ValueError(
                f"observation point {index} must contain exactly x, y, yaw"
            )
        point = {name: float(item[name]) for name in ("x", "y", "yaw")}
        if any(not math.isfinite(value) for value in point.values()):
            raise ValueError(f"observation point {index} must be finite")
        plan.append(point)
    return tuple(plan)
