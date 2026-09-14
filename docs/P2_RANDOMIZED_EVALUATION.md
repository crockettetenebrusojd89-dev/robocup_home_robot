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
