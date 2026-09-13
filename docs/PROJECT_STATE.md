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

## Vision — official-scorer and runtime verified

- The YOLO pilot detects `apple` and `coke_can`.
- RGB-D back-projection and TF2 transformation produce object locations in
  `/map`.
- Per-class spatial clustering, deduplication, and counting are implemented.
- RViz markers and the answer-JSON generation main chain are present.
- Vision Final Dedup V2 and final-evidence filtering have deterministic test
  coverage, and the real Gazebo + YOLO + RGB-D + TF2 chain was exercised.
- `scan_living_room` opens a fresh scoring observation window through
  `/vision/reset_tracking`, excluding detections collected at startup and while
  navigating to the room.
- The default scan uses twelve 30-degree steps with a two-second dwell. This
  keeps one full revolution while adding angular overlap for distant targets.
- Online tracking retained `deduplication_radius=0.05 m`; output-only final
  deduplication used `final_deduplication_radius=0.08 m`.
- Final output requires five aggregate observations after final deduplication;
  the three-observation online threshold remains available to far-object
  reinspection.
- `/vision/save_answer` successfully produced a valid JSON with finite
  coordinates. `/vision/final_object_markers` publishes the exact saved
  snapshot with transient-local durability, and RViz is configured to show it.
- Group 103 completed navigation, scan, far-object reinspection, answer save,
  and official scoring. With the scorer explicitly set to a strict 0.10 m
  match threshold, it scored 20/20: apple TP=2 FP=0 FN=0 and coke_can TP=1
  FP=0 FN=0. Match distances were 0.0746 m, 0.0235 m, and 0.0160 m.

## Unified official-model detector — runtime integration verified

- The teacher's formally released `models.zip` contains exactly the same 18
  directory identifiers as `tools/formal_dataset/classes.json`: missing 0,
  extra 0, and naming differences 0. This is the complete official model asset
  set.
- `tools/formal_dataset` defines one audited 18-class manifest and an
  offline-only Gazebo data-generation, validation, preview, training, and
  per-class evaluation pipeline.
- The first dataset contains 1,800 training images, 360 validation images, and
  3,266 instances. Every class occurs in both splits; structure, image-label
  pairing, box ranges, class identity, duplicate images, and train/validation
  leakage checks passed.
- The unified YOLO11n best checkpoint scored precision 0.977, recall 0.965,
  mAP50 0.981, and mAP50-95 0.926 on its independent synthetic validation
  split. Per-class results are stored beside the generated weights.
- The existing CPU competition vision environment successfully loaded the
  CUDA-trained weights, verified all 18 class names in manifest order, and ran
  inference. The known-good runtime environment was not modified.
- The `work/formal-base-runtime` integration requires exactly three distinct
  judge targets and a positive group number, validates the checkpoint against
  the exact 18-class manifest, and rejects unknown names by default. An
  explicit alias file is available but intentionally empty until the judge
  input syntax is confirmed.
- One unattended `example.world` smoke run navigated to the living room, ran
  the twelve-view scan, deduplicated observations, saved the three-key answer,
  and exited cleanly. The recorded result was `apple=1`, `coke_can=1`, and
  `banana=0` in 96 seconds from launch acceptance to runner completion.

This establishes the formal model's runtime contract and one complete
integration pass, not full competition generalization. The generic localizer's
pilot defaults remain unchanged; the formal launch selects the 18-class model
explicitly.

The official directory identifiers do not establish the spelling or formatting
of judge input strings. Until that interface is published, the runner must keep
normalization and aliases explicit and configurable, avoid assuming case or
underscore conventions, and reject unknown or ambiguous inputs.

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
- A complete competition-day `.world` run with no manual intervention.
- Same-frame protection in Gazebo when two real same-class objects are
  simultaneously visible and closer than 8 cm.
- Calibration of the 8 cm final-dedup radius against official competition
  object spacing and randomized layouts beyond the provided scoring example.
- Repeat trials with randomized object placement and temporary obstacles.
- Direct corner-based validation of map/world calibration modes C0-C3.
- Manual RViz GUI inspection of the final-answer markers. Their ROS messages
  and exact equality with the saved JSON were verified.

## Current priority

1. Review the completed `work/formal-base-runtime` integration and retain its
   successful smoke evidence before merging.
2. Combine it with the separately reviewed formal-world loader, then run
   randomized full-chain official scoring, including nearby same-class
   objects, temporary obstacles, occlusion, corners, and the eight-minute cap.
3. Use those failures to improve model generalization, localization, search,
   or deduplication one justified change at a time.
4. Manipulation and grasping afterwards.
