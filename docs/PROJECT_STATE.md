# Project State

This document records verified capabilities of the current development
baseline. It distinguishes earlier full-system verification, the FR3 V2 smoke
test, and work that remains unverified.

## Mobile robot — verified

- Differential-drive command and odometry interfaces: `/cmd_vel`, `/odom`.
- 2D LiDAR and LaserScan interface: `/scan`.
- IMU interface: `/imu`.
- RGB-D camera, color image, depth image, and CameraInfo interfaces.
- TF chain for the base, LiDAR, IMU, and camera frames.

## SLAM — previously verified

- `slam_toolbox` mapping succeeded.
- The saved map `example_map_v1` is available in this package.

## Navigation — previously verified

- AMCL with the static map has been verified.
- A complete autonomous navigation run from the formal start position to the
  living room has previously succeeded.
- Navigation around temporary obstacles has previously been verified.

## Vision — V2 runtime-verified chain (not scoring-verified)

- The YOLO pilot detects `apple` and `coke_can`.
- RGB-D back-projection and TF2 transformation produce object locations in
  `/map`.
- Per-class spatial clustering, deduplication, and counting are implemented.
- RViz markers and the answer-JSON generation main chain are present.
- Vision Final Dedup V2 code and deterministic tests passed, and the real
  Gazebo + YOLO + RGB-D + TF2 chain was exercised successfully.
- The documented `go_to_living_room`, six-step `scan_living_room`, and
  `reinspect_far_object` flows succeeded in that runtime session.
- Online tracking retained `deduplication_radius=0.05 m`; output-only final
  deduplication used `final_deduplication_radius=0.08 m`.
- Confirmed apple clusters `#26` and `#31` were 0.062 m apart at answer save.
  They were merged into one observation-count-weighted final answer location
  with observations `3 + 98`, without modifying live tracking clusters.
- `/vision/save_answer` successfully produced a valid JSON with finite
  coordinates, and the deduplicated-marker topic published during the run.

## FR3 V2 static integration — verified in commit `cf93726`

- The navigation-stowed joint reference is
  `[-0.68, 0.29, -0.26, -2.91, 0.75, 1.03, 2.00]`.
- Gazebo runtime spawning, FR3 stowed posture, `/joint_states`, and FR3 TF
  frames were verified.
- LiDAR and RGB-D were not observably obscured by the FR3 or its enclosure.
- Differential-drive motion regression and a Nav2 smoke test passed with the
  integrated model.

FR3 V2 is currently a **static whole-robot integration** only. It does not
establish arm control, MoveIt2 planning, or visual grasping.

## Not yet verified

- Long-duration FR3 static stability under extended simulation runs.
- A complete `NavigateToPose` run to the living room using the FR3 V2 revision
  specifically; only its Nav2 smoke test was performed for this revision.
- FR3 active control, MoveIt2 / MoveIt Task Constructor integration, and
  grasping.
- A complete competition run with no manual intervention.
- Same-frame protection in Gazebo when two real same-class objects are
  simultaneously visible and closer than 8 cm.
- Calibration of the 8 cm final-dedup radius against official competition
  object spacing.
- TP / FP and competition scoring accuracy. This runtime verification used no
  Gazebo object ground truth.
- Manual RViz GUI inspection of the final deduplicated markers.

## Current priority

1. Base-task stability.
2. Reliable visual localization and deduplication.
3. Multi-view search.
4. A complete no-intervention competition run.
5. Manipulation and grasping afterwards.
