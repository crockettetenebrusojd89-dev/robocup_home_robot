# Formal competition world runbook

The teacher's latest group notice says the competition `.world` file will be
issued on the day and may be loaded directly. The rulebook says its overall
layout, room partition, and table positions remain the same as the preview
environment, so the saved map remains the intended navigation map and a new
SLAM run is not required. Temporary obstacles and object placements will
change.

## Before competition day

Verify the direct-file path with the supplied `example.world`:

```bash
ros2 launch robocup_home_robot base_system.launch.py \
  world_file:=$HOME/wpr_ros2_ws/src/wpr_simulation_ros2/worlds/example.world
```

An empty `world_file` keeps the existing packaged-example behavior. The launch
fails before Gazebo starts when the path is missing or does not end in
`.world`.

## Competition-day command

Use an absolute path to the teacher-provided file:

```bash
ros2 launch robocup_home_robot base_system.launch.py \
  world_file:=/absolute/path/to/teacher_provided.world
```

The expected Gazebo world name is `robocup_home`. If the teacher explicitly
provides a different world name, pass it without editing the scene file:

```bash
ros2 launch robocup_home_robot base_system.launch.py \
  world_file:=/absolute/path/to/teacher_provided.world \
  world_name:=documented_world_name
```

Do not inspect or parse the world to obtain object names or poses. This launch
only checks the filesystem path and passes the file to Gazebo. Robot spawning,
world readiness, and sensor-system services all use the same `world_name`.

## Success checks

1. Gazebo displays the supplied environment.
2. The terminal reports the matching `/world/<world_name>/create` service.
3. The robot appears once at the official start.
4. `/scan`, `/odom`, `/imu`, RGB, depth, and camera-info topics publish.
5. Nav2 lifecycle nodes become active and AMCL uses `example_map_v1.yaml`.
6. No new SLAM or manual RViz pose/goal operation is performed after timing
   starts.

If the launch times out waiting for the world service, first ask the teacher
for the file's Gazebo world name. Do not open the scene to extract object truth.

## Verification record

On 2026-09-13, the absolute-path mode was exercised with the existing
`example.world`. Gazebo loaded that exact path, the robot spawned once, all
LiDAR/odometry/IMU/RGB/depth/camera-info interfaces appeared, Nav2 reached the
active state, AMCL loaded the saved map, and autonomous navigation from the
start to the living room succeeded. The empty-path default also reached active
Nav2. A nonexistent path failed before Gazebo started.

On 2026-09-14, the combined formal base-task launch loaded the same
`example.world` by absolute path and completed navigation, twelve-view scanning,
RGB-D localization, deduplication, and automatic JSON save without intervention
in 93.26 seconds. The launch only forwarded the path and world name; it did not
read scene contents.
