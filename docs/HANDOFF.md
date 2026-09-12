# Handoff: FR3 V2 Static Stowed Integration

- Feature branch: `codex/fr3-v2-integration` (merged and retired).
- Integration commit: `cf93726b0c19ab55e47cb1e4e3983fb5585ac05d`.

## Main changes

- `CMakeLists.txt`
- `launch/spawn_robot.launch.py`
- `scripts/generate_spawn_sdf.py`
- `scripts/offset_joint_states.py`
- `urdf/mobile_manipulator.xacro`

The integration generates the spawn SDF with the navigation-stowed FR3 pose
and relays offset FR3 joint states for the robot-state-publisher TF chain.

## Actually passed

- Xacro parsing.
- `check_urdf`.
- `ign sdf -k`.
- Python compilation.
- `ament_flake8`.
- Package-only `colcon build`.
- Gazebo runtime spawn and static FR3 stowed posture.
- FR3 joint states and TF queries.
- LiDAR and RGB-D runtime checks.
- Differential-drive movement regression.
- Nav2 smoke test.

## Not established by this integration

- Long-duration static stability of the FR3.
- A complete `NavigateToPose` regression to the living room using this exact
  integrated revision.
- MoveIt2 or active FR3 control.
- Grasp execution.
