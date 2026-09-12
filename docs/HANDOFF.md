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

## Vision final-dedup V2

- Feature branch: `codex/vision-dedup-v2`.
- The existing 5 cm online `deduplication_radius` remains unchanged for
  association and online cluster consolidation.
- `rgbd_object_localizer` now has a separate 8 cm
  `final_deduplication_radius`, used only on a temporary final-answer snapshot.
- Same-class clusters observed as separate detections in one frame are recorded
  as protected pairs. Online cluster lineage preserves that protection after a
  5 cm online consolidation removes a cluster ID.
- Final deduplication considers only confirmed target clusters, never mutates
  live tracking state, and uses observation-count-weighted centroids.
- Candidate final merges are selected as disjoint nearest pairs; no cluster can
  participate twice, preventing A-B-C single-linkage chain merging.

## Vision final-dedup V2 verification

- Python syntax compilation passed.
- Seven deterministic final-dedup tests passed, including the known 7.16 cm
  apple split, same-frame protection, lineage preservation, class separation,
  radius rejection, chain protection, and confirmation filtering.
- `ament_flake8` and `ament_pep257` passed.
- Package-only `colcon build --symlink-install --packages-select
  robocup_home_robot` passed.
- Package CTest passed: 26 tests, 0 errors, 0 failures.

## Vision final-dedup V2 not yet verified

- Gazebo / RViz runtime behavior with live RGB-D and TF data.
- Final JSON behavior during a full visual scan or competition-runner flow.
- Calibration of the 8 cm final radius against actual same-class object spacing
  in the competition environment.
