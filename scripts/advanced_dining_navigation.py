#!/usr/bin/env python3
"""Fixed, map-checked high-level handoff pose for Advanced Stage 1."""

import math


# This point passes the west side of the dining-entry wall corner.  It is not
# a base-task waypoint and is used only by the isolated Advanced Stage 1 run.
DEFAULT_DINING_ENTRY_WAYPOINT = (0.45, 0.25, math.pi / 2.0)


def dining_entry_waypoint(x, y, yaw):
    """Return a finite waypoint tuple, rejecting malformed launch values."""
    values = (float(x), float(y), float(yaw))
    if not all(math.isfinite(value) for value in values):
        raise ValueError('dining entry waypoint must contain only finite values')
    return values
