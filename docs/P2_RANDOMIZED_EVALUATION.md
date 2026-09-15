# P2 randomized evaluation

This is an evaluation-only layer around the frozen formal base-task runtime.
It does not alter navigation, scan, vision, depth, TF, clustering, deduplication,
or answer generation.

## Eligibility and geometry

`tools/p2_eval/tables.json` records the four normal-height models named
`living_room_table_0` through `living_room_table_3` from `example.world`.
Their tops are all 0.5 m by 1.2 m at world z=0.78 m. The low `tea_table`
(top about 0.42 m) is excluded, as are dining-room and kitchen tables. This is
an explicit interpretation of the documented base-task scope, not data exposed
to the robot.

Placement centers are sampled uniformly in table-local coordinates. A 0.03 m
edge margin and conservative 0.11 m circular object footprint are removed from
each table edge. Objects on the same table must have another 0.015 m gap. Table,
position, yaw, and seed are written to metadata so every world is reproducible.

## Fairness boundary

Scenario generation is allowed to read the world and table descriptions. It
creates four separate artifacts:

- `scenario.world`: visual/physical simulation presented to Gazebo;
- `ground_truth.json`: read only after the formal runtime exits;
- `scenario_metadata.json`: read only by post-run analysis;
- `runtime_inputs.json`: only the generated world path/name, three target
  strings, and group number.

The subprocess that runs `formal_base_task.launch.py` accepts only the last set
plus the already-required model, device, output directory, and timeout. Its API
rejects extra keys, including ground truth or coordinates. The official scorer
starts only after that subprocess has exited and always receives
`--match-threshold 0.10` explicitly.

## One smoke trial

From a sourced workspace, or directly with the environment paths used below:

```bash
python3 tools/p2_eval/run_trial.py \
  --scenario tools/p2_eval/scenarios/smoke_multitable.json \
  --output-dir /home/hao/robocup_assets/p2_eval/smoke_multitable_seed_20260914
```

The trial uses apple on table 0, coke_can on table 2, and banana on table 3.
The table-local positions and yaw are random under seed 20260914. This first run
validates the evaluation chain; a partial visual score is data, not a harness
failure.

## First ten high-information scenarios (proposal only)

Do not execute these as a bulk suite until the smoke chain is accepted.

1. Three targets concentrated on nearest table 0, with legal random positions.
2. Three targets concentrated on farthest table 2.
3. Targets near the far edge of table 2, random yaw within an edge band.
4. Small classes (`tuna_fish_can`, `pudding_box`, `gelatin_box`) on table 2.
5. Two same-class instances on one table at the minimum legal separation.
6. Two different classes close together without physical intersection.
7. Targets in corner bands on table 1 and table 3.
8. One legal line-of-sight partial-occlusion arrangement on table 3.
9. Three target classes distributed across three different tables.
10. Scenario 9 plus one competition-style temporary obstacle that preserves a
    valid route, exercising the full navigation and scan chain.

These cases should retain random legal coordinates and fixed seeds; their
constraints select risk regions rather than hand-tuning easy poses.

## Legacy reinspection status

`reinspect_far_object.py` remains disconnected. It requires an existing visual
cluster, chooses the farthest cluster for only one configured class, and then
uses obsolete fixed viewpoints. It cannot recover a complete first-pass miss.
It may improve range/localization for an already-detected object, but adds a
navigation leg and dwell (up to the existing 120 s navigation result timeout)
and can create association/duplicate-output risk. The old four viewpoints were
not read, tested, or reused by this P2 work.

## Frozen single-stand coverage audit

The fixed robot scan stand is x=-2.393 m, y=-0.882 m, yaw=0.724 rad. With the
configured legal center area (table half-size less 0.03 m edge margin and the
0.11 m conservative footprint), planar distance bounds are:

| Table | Center (m) | Size (m) | Nearest legal (m) | Farthest legal (m) |
|---|---:|---:|---:|---:|
| living_room_table_0 | (-2.10, 0.00) | 0.50 x 1.20 | 0.77 | 1.25 |
| living_room_table_1 | (-3.30, -2.10) | 0.50 x 1.20 | 1.20 | 1.91 |
| living_room_table_2 | (0.63, -2.60) | 0.50 x 1.20 | 3.17 | 3.82 |
| living_room_table_3 | (-3.50, -3.10) | 0.50 x 1.20 | 2.02 | 2.94 |

The camera is 640 px wide with 70 degree horizontal FOV, giving about 457 px
focal length. At the far edge of table 2, a 5 cm projected width is only about
6 px and a 10 cm width about 12 px. The configured 5 m depth limit covers all
four regions geometrically, but this alone does not prove reliable detection or
depth on small or occluded objects.

## Smoke evidence, 2026-09-14

The canonical retry completed navigation, tracking reset, all 12 scan steps,
answer save, and official scoring in 137.31 s. The explicit 0.10 m score was:

- apple on table 0 at 0.88 m: TP, 0.09685 m error;
- coke_can on table 2 at 3.62 m: FN, no post-reset localized cluster;
- banana on table 3 at 2.61 m: FN, no post-reset localized cluster;
- aggregate TP=1, FP=0, FN=2, vision=10/30, navigation=40/40,
  base-task result=50/70.

An initial infrastructure attempt was retained separately after AMCL lifecycle
configuration failed to complete. The identical retry passed that point without
any runtime or parameter change, so this is currently a startup-repeatability
risk, not a table-coverage measurement.

The frozen runtime only logs detections that also obtained valid depth and TF.
For a missed class the evaluation cannot yet distinguish raw YOLO miss, invalid
depth, or TF failure; the summary records those individual fields as null and
records the observable end-to-end localization pipeline result as false.

The 12 MB runtime log is dominated by repeated `TF_OLD_DATA` and RViz message
filter or shutdown messages. They did not prevent the canonical run from
finishing, so they are non-blocking noise for this smoke and are deliberately
not repaired in P2. They can still obscure useful evidence and should not be
generalized as harmless without more trials.

## Fixed-seed repeatability gate and startup correction, 2026-09-14/15

Commit `1b951f7` added the repeatability harness. The first five-run gate kept
seed `20260914`, the generated world, object
poses/yaws, targets, checkpoint, formal parameters, fixed scan pose, and
explicit scorer threshold `0.10 m` unchanged. All five attempts failed at
`nav2_map_tf`; startup and complete-runtime success were both 0/5. Wall time
was tightly grouped from 126.77 s to 128.45 s. This established a deterministic
startup defect rather than a visual repeatability result.

Commit `1037610` corrected ownership of the competition Gazebo server so that
the formal world loader remains the only launcher. That correction entered
`main` before it was merged back into this P2 branch. It did not change Nav2,
vision, scan, depth, TF, clustering, or deduplication parameters.

The fixed-seed gate was then repeated with read-only telemetry:

- Gazebo and Nav2 startup succeeded in 5/5 runs;
- four runs completed and one failed during navigation, for 4/5 complete-task
  success;
- scores were 50, 50, 50, 0, and 48 out of 70;
- wall times were 92.68, 148.16, 112.23, 84.14, and 86.33 s;
- apple reached detection, valid depth, successful TF, a cluster, and the final
  answer in every visually evaluable run; its four TP errors were 3.05, 2.59,
  0.52, and 5.59 cm, with one additional FP in run 5;
- coke_can was not detected in any of the four visually evaluable runs;
- banana was detected, depth-valid, transformed, and clustered in only one of
  four visually evaluable runs, but never passed the final-answer gate.

Evidence is under
`~/robocup_assets/p2_eval/repeatability_telemetry_seed_20260914_20260915`.
The older all-startup-failure evidence remains under
`~/robocup_assets/p2_eval/repeatability_smoke_multitable_seed_20260914`.

## Read-only pipeline telemetry

Commit `0dded44` added post-reset counters that expose raw target detection,
valid depth, TF success, cluster formation, and final-answer presence. The
counters are read by the P2 harness only after a trial. They do not feed any
detector, localizer, confirmation, clustering, filtering, or answer decision.
This closed the original diagnostic gap while preserving formal behavior.

## Visibility-versus-detector gate

Commit `3e593e1` added an evaluation-only RGB capture and offline inference
path. Gazebo labels and object poses are used only after inference to associate
evidence; the detector receives RGB images only. Three identical fixed-point
trials all completed navigation and scoring. For every run:

- apple was detected and scored TP;
- coke_can's offline maximum confidence was 0.060, 0.254, and 0.214;
- banana's offline maximum confidence was 0.065, 0.172, and 0.309;
- neither remote class produced any frame at the formal 0.50 threshold.

This separated the remote FNs from depth, TF, clustering, and final filtering:
they were raw detector misses at the original single scan stand. Evidence is
under `~/robocup_assets/p2_eval/visibility_gate_seed_20260914_20260915`.

## Geometry-based observation-point evaluation

Commit `21d7789` sampled all legal object-center areas on the four living-room
tables against the saved occupancy map, robot footprint, structural clearance,
table clearance, 70-degree camera FOV, and 5 m depth limit. It did not read the
obsolete four-point YAML and did not connect corners to runtime.

The safety-adjusted one-point trial used
`(-1.685, -1.215, yaw=-2.051)` with a 3.047 m worst legal-table distance. It
completed in 100.20 s and scored 60/70: apple and coke_can TP, banana FN.

The current two-point candidate is:

- P1 `(-3.485, -1.115, yaw=-0.532)`;
- P2 `(0.265, -0.665, yaw=-2.638)`.

Its sampled worst legal-table distance is 2.448 m. Both points were reached by
Nav2 in the fixed-seed trial. That run completed in 157.34 s and scored 60/70:
apple TP, coke_can TP at maximum confidence 0.973, and banana FN at maximum
confidence 0.456. The two points remain candidates, not frozen formal-runtime
defaults.

## Two-point tabletop-position robustness gate

Commit `315154c` evaluated the fixed P1/P2 pair without changing the formal
runner. For each placement it captured both observation points through a full
rotation, ran the formal checkpoint at confidence 0.50, and used Gazebo labels
only afterward for offline association.

- all 30 tested placements entered the camera view;
- coke_can was detected at 15/15 legal positions; per-position maximum
  confidence ranged from 0.804 to 0.986, with median 0.944;
- banana was detected at only 2/15 legal positions; per-position maximum
  confidence ranged from 0.008 to 0.505, with median 0.092;
- banana's worst associated box was about 31 x 8 px.

The geometry therefore covers the tested tables, while banana is an object
scale/appearance robustness problem. Observation points must not be adjusted
again solely from this evidence. Evidence is under
`~/robocup_assets/p2_eval/tabletop_robustness_gate_two_points_20260915`.

## Corrected beer asset audit

The teacher's corrected `beer.zip` was inspected without modifying the
archive. Neither old nor new beer uses a mesh: both visual and collision shapes
are cylinders of radius 0.055 m and length 0.230 m. Mass, inertia, link pose,
collision, texture bytes, and the legacy SDF 1.4 file are unchanged.

The active SDF changed from the legacy `Beer/Diffuse` script to an SDF 1.6 PBR
material that directly uses `beer.png`, ambient/diffuse `1 1 1 1`, metalness
0.0, and roughness 0.7. The material script also corrects `anistropic` to
`anisotropic`. A private Gazebo Fortress/OGRE2 smoke rendered the complete can
texture rather than a black cylinder, confirming this is a rendering
compatibility repair with no geometry or physics change.

The original unified training dataset is affected: it contains 184 beer
instances, 183 of which have a majority of near-black pixels inside the label
box. The median dark-pixel fraction is 95.4%, and median RGB is approximately
(8, 7, 7). Do not treat the existing beer metrics as evidence for the corrected
official appearance.

## Unified 18-class robustness audit, 2026-09-15

Commit `6eb7a60` added a P2-only audit using the formal `best.pt`, confidence
0.50, the candidate P1/P2 positions, and 12 x 30-degree scans. Every class was
first screened at five representative legal placements spanning near, middle,
far, edge, corner, and multiple object yaws. Clearly weak classes were expanded
to 15 positions. Corrected beer was loaded through an evaluation-only model
resource path. Ground truth was never passed to YOLO or formal runtime.

Confidence columns below are distributions of the per-position maximum. For
banana, beer, and master_chef_can the stronger 15-position result replaces the
five-position screen.

| Class | Success | Visible frames | Median bbox (px) | Median / max confidence | Band |
|---|---:|---:|---:|---:|---|
| apple | 5/5 | 21 | 22 x 21 | 0.954 / 0.969 | stable |
| banana | 2/15 | 138 | 36 x 12 | 0.092 / 0.505 | weak |
| beer (corrected) | 0/15 | 77 | no detection | 0.000 / 0.000 | weak |
| bleach_cleanser | 5/5 | 21 | 33 x 76 | 0.981 / 0.992 | stable |
| bowl | 5/5 | 22 | 54 x 19 | 0.982 / 0.985 | stable |
| chips_can | 5/5 | 21 | 25 x 74 | 0.984 / 0.991 | stable |
| coke_can | 4/5 | 21 | 23 x 38 | 0.929 / 0.983 | borderline |
| cracker_box | 5/5 | 22 | 59 x 68 | 0.992 / 0.996 | stable |
| gelatin_box | 5/5 | 21 | 28 x 22 | 0.981 / 0.993 | stable |
| master_chef_can | 8/15 | 76 | 36 x 43 | 0.516 / 0.927 | weak |
| mustard_bottle | 5/5 | 21 | 29 x 57 | 0.985 / 0.994 | stable |
| pitcher_base | 5/5 | 22 | 48 x 74 | 0.982 / 0.994 | stable |
| potted_meat_can | 5/5 | 20 | 31 x 26 | 0.964 / 0.969 | stable |
| pudding_box | 4/5 | 21 | 24 x 29 | 0.946 / 0.982 | borderline |
| sugar_box | 5/5 | 21 | 29 x 54 | 0.958 / 0.993 | stable |
| tomato_soup_can | 4/5 | 23 | 25 x 32 | 0.947 / 0.977 | borderline |
| tuna_fish_can | 5/5 | 21 | 27 x 11 | 0.936 / 0.977 | stable |
| windex_bottle | 5/5 | 21 | 34 x 85 | 0.990 / 0.992 | stable |

The consolidated bands are:

- stable: apple, bleach_cleanser, bowl, chips_can, cracker_box, gelatin_box,
  mustard_bottle, pitcher_base, potted_meat_can, sugar_box, tuna_fish_can, and
  windex_bottle;
- borderline: coke_can, pudding_box, and tomato_soup_can;
- weak: banana, corrected beer, and master_chef_can.

Banana is primarily small-scale and problem-yaw sensitive. Beer is a confirmed
material/training-domain mismatch. Master_chef_can has a distance/yaw/background
domain gap that cannot be explained by tiny bbox size alone. The next dataset
work should target corrected beer first, then far/small/problem-yaw banana,
then mid/far multi-yaw master_chef_can, with smaller supplements for the three
borderline classes. A unified 18-class retrain is justified after those data
changes; no retraining was started by this audit.

Evidence directories are:

- `~/robocup_assets/p2_eval/formal_18_class_representative_audit_20260915`;
- `~/robocup_assets/p2_eval/formal_18_class_expanded_weak_audit_20260915`;
- `~/robocup_assets/p2_eval/formal_18_class_expanded_master_chef_can_20260915`.

## Formal Model V2 pipeline smoke, 2026-09-15

The V2 offline generator now uses an isolated asset root, a precomputed
per-class scenario plan, four table/background islands, and four bounded
Gazebo lighting profiles. It records object/camera geometry, yaw bin, distance
band, placement, asset hashes, light parameters, split, seed, scene group, and
final boxes and image hashes for every frame. A rejected box stops the run;
there is no V1-style retry that can bias the recorded quota toward easy poses.

The smoke at
`~/robocup_assets/datasets/formal_objects_v2_smoke_20260915` completed all 45
captures: 30 train and 15 val, including 6 declared empty/background negatives.
Primary counts were beer 8/4, banana 6/3, master_chef_can 6/3, and each
borderline class 2/1 for train/val. Train/val scene groups, exact image hashes,
exact background-light parameter combinations, and perceptual near-duplicates
all had zero overlap.

The corrected beer was present in 12 primary frames spanning all distance and
lighting bands represented by the smoke. Its maximum near-black fraction was
26.71% and median was 22.12%, versus the invalid V1 median of 95.4%. Manual
inspection of both contact sheets and the numerically darkest beer frame
confirmed a visible colored label and aligned box. Far/problem-yaw banana,
mid/far multi-yaw master_chef_can, edge/corner placement, lighting variants,
and empty tables were also visually present with aligned labels.

At the time of the smoke gate, the reviewed formal plan contained 724 new
frames and had not yet been run: 570 train
and 154 val, comprising corrected beer 180/45, banana 144/36,
master_chef_can 108/27, each borderline class 36/12, plus 30/10 negatives.
Removing every V1 image containing old beer leaves 1,649 train and 327 val
replay images. The eventual composition would therefore contain exactly 2,700
images while retaining clean replay from all 17 non-beer classes. Dataset
composition and unified training were still separate, unstarted steps. The
following section records their later data-only completion; unified training
remains unstarted.

## Formal Model V2 dataset completion, 2026-09-15

The formal targeted run is complete at
`~/robocup_assets/datasets/formal_objects_v2_targeted_20260915`: 570 train and
154 val frames, including 30/10 declared empty negatives. The first attempt was
stopped at train sample 260 because a secondary pitcher geometrically occluded
the primary beer. The partial run was retained as evidence under the suffixed
`failed_train000260` directory. A deterministic primary sight-corridor guard
was added, including a regression test for that exact camera/object geometry;
the fresh run then completed all 724 captures.

Actual primary distributions match the reviewed plan. Corrected beer has 225
frames with near/mid/far and center/edge/corner each 75, all twelve 30-degree
yaw bins at 18 or 19 frames, and four backgrounds and light profiles at 56 or
57 frames each. Banana has 26/51/103 near/mid/far frames, 25/77/78
center/edge/corner frames, and 34 frames in each problem-yaw bin at 270, 300,
and 330 degrees; its smallest primary box is 66 pixels. Master_chef_can has
16/51/68 near/mid/far and 27/54/54 center/edge/corner frames with all eight yaw
bins covered. Coke_can, pudding_box, and tomato_soup_can each have 48 frames,
39 far and 9 mid, with balanced cardinal yaws and all backgrounds/lights.

The targeted validator reports zero scene-group, exact-image, exact
background-light, and annotation-aware perceptual train/val overlap. All 225
corrected beer boxes pass the 50% near-black gate: median 19.86%, maximum
27.54%. Manual contact-sheet inspection covered beer distance/light/yaw,
far/problem-yaw/small banana, mid/far/multi-yaw master_chef_can, the three
borderline far classes, and negatives. Targets and boxes were aligned, beer
texture remained visible, lighting remained competition-like, and no systematic
cutoff or rendering defect was found.

The final composed dataset is
`~/robocup_assets/datasets/formal_objects_v2`. It removes the entire image and
label pair for 151 V1 train and 33 V1 val frames containing old beer, preserving
1,649/327 clean V1 replay frames and adding the unchanged 570/154 targeted
splits. The result is exactly 2,219 train and 481 val images. Every retained
image is hard-linked to its source without re-encoding, and source/split
prefixes prevent name collisions.

`dataset_composition_manifest.jsonl` records source paths, hashes, class IDs,
negative state, split, validation subset, and targeted scene group for all
2,700 frames. Separate validation lists preserve 327 legacy val, 144 targeted
positive val, and 10 targeted negative val frames. The composed validator
confirmed zero old-beer replay frames, zero filename collisions, valid empty
labels, the exact 18-class mapping, corrected beer asset and black-fraction
gates, targeted quotas, and zero exact, annotation-aware perceptual, or targeted
scene-group train/val leakage. Ultralytics accepted `data.yaml` with 18 classes
and the expected train/val roots. No checkpoint was loaded and no training or
runtime change was performed.
