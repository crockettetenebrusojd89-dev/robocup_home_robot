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
- The formal base-task integration requires exactly three distinct
  judge targets and a positive group number, validates the checkpoint against
  the exact 18-class manifest, and rejects unknown names by default. An
  explicit alias file is available but intentionally empty until the judge
  input syntax is confirmed.
- One unattended `example.world` smoke run navigated to the living room, ran
  the twelve-view scan, deduplicated observations, saved the three-key answer,
  and exited cleanly. The recorded result was `apple=1`, `coke_can=1`, and
  `banana=0` in 96 seconds from launch acceptance to runner completion.
- The combined `work/base-task-integration` launch forwards `world_file` and
  `world_name` to the verified world loader, waits for the Nav2 lifecycle stack
  to become active, and then starts the existing navigation/scan/save sequence.
  An absolute-path `example.world` unattended run completed successfully in
  93.26 seconds and produced `apple=1`, `coke_can=1`, and `banana=0`.

This establishes the formal model's runtime contract and one complete
integration pass, not full competition generalization. The generic localizer's
pilot defaults remain unchanged; the formal launch selects the 18-class model
explicitly.

The official directory identifiers do not establish the spelling or formatting
of judge input strings. Until that interface is published, the runner must keep
normalization and aliases explicit and configurable, avoid assuming case or
underscore conventions, and reject unknown or ambiguous inputs.

## P2 randomized evaluation — latest verified evidence

- The initial fixed-seed five-run repeatability gate reproduced a
  `nav2_map_tf` startup failure in 5/5 attempts. Commit `1037610`, now in
  `main` and this branch, kept the competition Gazebo server launch-owned.
- After that correction, Gazebo/Nav2 startup passed 5/5 times. Four complete
  tasks succeeded; one later failed in navigation. Scores were 50, 50, 50, 0,
  and 48 out of 70.
- Read-only post-reset telemetry now distinguishes target detection, valid
  depth, TF success, cluster formation, and final-answer presence without
  participating in any decision.
- Three visibility-versus-detector trials showed the original single stand's
  coke_can and banana FNs occurred before depth and TF: their offline maximum
  confidences remained below the formal 0.50 threshold in every run.
- Geometry optimization did not read the obsolete four-point YAML. The current
  two-point candidate is P1 `(-3.485, -1.115, yaw=-0.532)` and P2
  `(0.265, -0.665, yaw=-2.638)`, with a sampled worst legal-table distance of
  2.448 m. Both points were Nav2-reachable in the fixed-seed trial, which
  scored 60/70 in 157.34 s.
- A 30-placement gate proved all tested coke_can and banana placements entered
  a camera view. Coke_can passed 15/15, while banana passed only 2/15 at
  confidence 0.50. The current blocker is therefore class robustness rather
  than gross two-point geometric coverage.

## Official visual assets and 18-class robustness — latest audit

- The teacher's corrected beer preserves geometry, mass, inertia, collision,
  pose, and the exact `beer.png`; it replaces the incompatible legacy material
  reference with an SDF 1.6 PBR albedo map. It rendered correctly in a private
  Fortress/OGRE2 smoke.
- The existing formal training set's beer images are invalid for that corrected
  appearance: 183/184 beer boxes contain a majority of near-black pixels, with
  a 95.4% median dark-pixel fraction.
- At the formal 0.50 threshold, the current consolidated class bands are:

  - stable: apple, bleach_cleanser, bowl, chips_can, cracker_box, gelatin_box,
    mustard_bottle, pitcher_base, potted_meat_can, sugar_box, tuna_fish_can,
    windex_bottle;
  - borderline: coke_can, pudding_box, tomato_soup_can;
  - weak: banana (2/15), corrected beer (0/15), master_chef_can (8/15).

- A targeted data correction followed by a new unified 18-class training run
  is justified. No threshold change, observation-point change, class-specific
  detector, or retraining has been performed.

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
- Ten different randomized layouts and temporary-obstacle trials have not been
  started. Existing repeatability evidence covers one fixed seed only.
- Manual C0-C3 capture and official-scorer A/B validation. The code/history
  audit found no prior corner configuration or runtime calibration. Current
  spawn and AMCL start anchors imply only near alignment (about 6.1 cm anchor
  separation and 0.233 degrees yaw difference), while objects-only identity
  scoring has passed 20/20 at an explicit 0.10 m gate. Corners remain a P2
  validation item, not an enabled runtime feature.
- Manual RViz GUI inspection of the final-answer markers. Their ROS messages
  and exact equality with the saved JSON were verified.

## Current priority

1. Correct the beer training domain and add targeted banana and
   master_chef_can evidence, plus small far-view supplements for coke_can,
   pudding_box, and tomato_soup_can.
2. Retrain and re-audit one unified 18-class checkpoint while keeping formal
   confidence 0.50 and all frozen runtime parameters unchanged.
3. After the model gate passes, resume different-seed randomized full-chain
   scoring, including temporary obstacles, occlusion, and the eight-minute cap.
4. Manipulation and grasping afterwards.
