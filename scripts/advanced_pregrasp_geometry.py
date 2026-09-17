"""Pure geometry and validity checks for Advanced Stage 2A."""

import math


DINING_TABLES = (
    ('dinning_table_0', 1.5, 1.5),
    ('dinning_table_1', 1.5, 2.0),
    ('dinning_table_2', 2.7, 1.5),
    ('dinning_table_3', 2.7, 2.0),
)
TABLE_TOP_SIZE = (0.5, 1.2, 0.03)
TABLE_TOP_Z = 0.765
TABLE_YAW = 1.57
# The four real table tops form one contiguous 2.4 m x 1.0 m rectangle after
# their 90-degree world rotation. Approach only from an exterior edge; driving
# between individual table centres would put the chassis inside another table.
DINING_CLUSTER_BOUNDS = (0.9, 3.3, 1.25, 2.25)


def finite_xyz(point):
    """Return a finite xyz tuple or reject malformed target data."""
    values = (float(point[0]), float(point[1]), float(point[2]))
    if not all(math.isfinite(value) for value in values):
        raise ValueError('target point must contain only finite values')
    return values


def nearest_dining_table(target_map):
    """Select the actual world table whose centre is closest in map XY."""
    x, y, _ = finite_xyz(target_map)
    name, table_x, table_y = min(
        DINING_TABLES,
        key=lambda item: math.hypot(x - item[1], y - item[2]),
    )
    distance = math.hypot(x - table_x, y - table_y)
    if distance > 0.70:
        raise ValueError(
            f'target is {distance:.3f} m from the nearest dining table centre'
        )
    return name, table_x, table_y


def manipulation_pose(target_map, table_clearance=0.45, current_base=None):
    """Choose the exterior table edge that gives the strongest arm margin."""
    x, y, z = finite_xyz(target_map)
    table_clearance = float(table_clearance)
    if not math.isfinite(table_clearance) or not 0.25 <= table_clearance <= 0.45:
        raise ValueError('table clearance must be within [0.25, 0.45] m')
    x_min, x_max, y_min, y_max = DINING_CLUSTER_BOUNDS
    # The FR3 base is 90 mm aft and 55 mm left of base_link. Align that complete
    # 105 mm offset vector with the target direction. This maximizes usable arm
    # reach while keeping the chassis outside the 0.35 m inflated table cost.
    target_directions = {
        'west': 0.0,
        'east': math.pi,
        'south': math.pi / 2.0,
        'north': -math.pi / 2.0,
    }
    arm_offset_direction = math.atan2(0.055, -0.09)
    base_positions = {
        'west': (x_min - table_clearance, y),
        'east': (x_max + table_clearance, y),
        'south': (x, y_min - table_clearance),
        'north': (x, y_max + table_clearance),
    }
    candidates = []
    for side, direction in target_directions.items():
        base_x, base_y = base_positions[side]
        target_distance = math.hypot(x - base_x, y - base_y)
        horizontal_reach = max(0.0, target_distance - math.hypot(0.09, 0.055))
        vertical_reach = z + 0.18 - 0.425
        nominal_reach = math.hypot(horizontal_reach, vertical_reach)
        if nominal_reach > 0.95:
            continue
        yaw = math.atan2(
            math.sin(direction - arm_offset_direction),
            math.cos(direction - arm_offset_direction),
        )
        candidates.append((side, base_x, base_y, yaw, nominal_reach))
    if not candidates:
        raise ValueError('no manipulation pose clears the dining-table cluster')
    if current_base is None:
        chosen = min(candidates, key=lambda item: item[4])
    else:
        current_x, current_y, _ = finite_xyz(
            (current_base[0], current_base[1], 0.0)
        )
        chosen = min(candidates, key=lambda item: (
            item[4],
            math.hypot(item[1] - current_x, item[2] - current_y),
        ))
    return chosen[1], chosen[2], chosen[3]


def manipulation_route(current_base, goal):
    """Add exterior corner waypoints when a route must cross the table cluster."""
    current_x, current_y, _ = finite_xyz((current_base[0], current_base[1], 0.0))
    goal_x, goal_y, goal_yaw = (float(value) for value in goal)
    x_min, x_max, y_min, y_max = DINING_CLUSTER_BOUNDS
    clearance = 0.35
    crosses_south_to_north = (
        current_y < y_min - clearance and goal_y > y_max + 0.25
    )
    crosses_north_to_south = (
        current_y > y_max + clearance and goal_y < y_min - 0.25
    )
    if not (crosses_south_to_north or crosses_north_to_south):
        return [(goal_x, goal_y, goal_yaw)]
    corridors = (x_min - clearance, x_max + clearance)
    corridor_x = min(
        corridors,
        key=lambda candidate: abs(current_x - candidate) + abs(goal_x - candidate),
    )
    south_y = y_min - clearance
    north_y = y_max + clearance
    if crosses_south_to_north:
        first_y, second_y, travel_yaw = south_y, north_y, math.pi / 2.0
    else:
        first_y, second_y, travel_yaw = north_y, south_y, -math.pi / 2.0
    final_yaw = 0.0 if goal_x >= corridor_x else math.pi
    return [
        (corridor_x, first_y, travel_yaw),
        (corridor_x, second_y, final_yaw),
        (goal_x, goal_y, goal_yaw),
    ]


def pregrasp_position(target_planning, vertical_offset=0.18):
    """Generate the TCP point above a validated tabletop target."""
    x, y, z = finite_xyz(target_planning)
    vertical_offset = float(vertical_offset)
    if not math.isfinite(vertical_offset) or not 0.10 <= vertical_offset <= 0.25:
        raise ValueError('pre-grasp vertical offset must be within [0.10, 0.25] m')
    if not 0.45 <= z <= 1.10:
        raise ValueError(f'target height {z:.3f} m is not tabletop-like')
    return x, y, z + vertical_offset


def within_arm_workspace(target_planning, arm_base, maximum_distance=0.95):
    """Conservative radial reach check before invoking IK."""
    target = finite_xyz(target_planning)
    base = finite_xyz(arm_base)
    distance = math.sqrt(sum((a - b) ** 2 for a, b in zip(target, base)))
    return distance <= float(maximum_distance), distance
