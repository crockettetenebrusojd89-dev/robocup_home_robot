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

## Vision final-dedup V2 runtime verification

- The real Gazebo + YOLO + RGB-D + TF2 visual chain ran successfully without
  using Gazebo object ground truth.
- `go_to_living_room` succeeded, followed by the six-step
  `scan_living_room` and a successful `reinspect_far_object` run.
- Runtime startup confirmed the separate radii: online
  `deduplication_radius=0.05 m` and output-only
  `final_deduplication_radius=0.08 m`.
- Confirmed apple clusters `#26` and `#31` appeared during the run. At answer
  save they were 0.062 m apart with observation counts `3 + 98`.
- Final Dedup V2 merged that pair into one observation-count-weighted answer
  position while leaving both live tracking clusters unchanged.
- `/vision/save_answer` successfully wrote a legal answer JSON with finite
  coordinates. The deduplicated-marker topic was also observed publishing.
- The workspace-level `RUNBOOK.md` requires a later documentation fix: the
  current FR3-integrated startup also needs
  `source ~/franka_ros2_ws/install/setup.bash`. That outer-workspace document
  was deliberately not changed on this branch.

## Vision final-dedup V2 not yet verified

- Gazebo runtime behavior when two real same-class objects are simultaneously
  visible, are closer than 8 cm, and must be preserved by same-frame
  protection.
- Calibration of the 8 cm final radius against actual same-class object spacing
  in the competition environment.
- This runtime test did not use Gazebo ground truth, so it does not establish
  final TP / FP performance or competition scoring accuracy.
- RViz GUI markers were not manually inspected, although the marker topic was
  verified at the ROS-message level.

## Vision scoring-window hardening

- Feature branch: `work/vision-observation-window`.
- The latest pre-change real answer, group 100, scored 6/20 with the official
  scorer at an explicit 0.10 m threshold: apple TP=2 FP=3 and coke_can TP=1
  FP=4. Runtime logs showed those extra clusters were accumulated before the
  formal room scan, mainly while navigating.
- `scan_living_room` now requires `/vision/reset_tracking` and clears all live
  clusters, lineages, and same-frame protection state immediately before the
  scoring scan. It fails closed if the service cannot be called.
- The default full-circle scan now uses twelve 30-degree steps instead of six
  60-degree steps. A direct comparison found all three targets with the denser
  angular coverage after the six-step scan missed the distant apple.
- Online confirmation stays at three observations so a sparse distant target
  can trigger reinspection. Final output requires five aggregate observations
  after final deduplication, suppressing a four-observation transient that
  produced one verified FP in group 102.
- `/vision/final_object_markers` publishes the exact JSON snapshot as persistent
  transient-local markers after a successful save. RViz subscribes to this
  topic, so displayed final answers no longer disagree with output-only dedup.
- Group 101 scored 20/20 after the scan-window reset. Group 102 exposed the
  low-evidence reinspection FP and scored 18/20. The final group 103 flow used
  the denser scan and evidence filter and scored 20/20 at an explicit 0.10 m
  threshold, with three TPs, no FPs, and no FNs.
