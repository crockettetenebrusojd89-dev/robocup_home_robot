# Formal Model V2 Competition-Domain External Gate — 2026-09-16

## Scope and verdict

The human-epoch-31 V2 candidate does **not** pass the frozen external detector
gate and is not ready to replace V1 as a frozen competition checkpoint.
Correct-class detection improved substantially for corrected beer and
master_chef_can and remained strong for coke_can, pudding_box, and
tomato_soup_can. However, banana remained 2/15 in the historical tabletop
problem-yaw capture, cross-class detections were systematic, and the bounded
lighting test exposed profile-specific background false detections. No model,
runtime, confidence, viewpoint, camera, localization, deduplication, or
navigation parameter was changed. No training was run.

## Candidate and fixed runtime contract

- Checkpoint: `/home/hao/robocup_assets/training_runs/formal_objects_v2_yolo11n_finetune/weights/epoch30.pt`
- SHA256: `c16f5332221649fdb89c225f9aaec6f73db97e2590bc37734a6d0e0a5099564c`
- Formal confidence: 0.50
- P1: x=-3.485, y=-1.115, yaw=-0.532
- P2: x=0.265, y=-0.665, yaw=-2.638
- Camera: unchanged 640x480, 70-degree horizontal field of view
- Corrected official assets: `/home/hao/robocup_assets/official_models_v2`
- Competition room resources: `/home/hao/wpr_ros2_ws/src/wpr_simulation_ros2/models`

Spatial designs are deterministic grids, not random samples, so they have
scenario IDs but no RNG seed. The lighting design uses recorded protocol seed
20260915 and fixed mid, far, and edge/problem-yaw scenarios. Each spatial
placement is viewed from P1 and P2 through the existing full-yaw capture
protocol. Ground-truth labels are used only after RGB inference.

A placement succeeds when a confidence-at-least-0.50 box of the correct class
is spatially associated with the Gazebo truth box in any physically visible
frame. A detector miss is a physically visible placement with no such box.
A wrong-class detector FP is any other official-class box at confidence 0.50
or above; the evidence records whether it overlaps the target truth. A
same-frame duplicate is more than one associated correct-class box in one
frame. Invisible frames are never counted as detector misses.

## Targeted aggregate recall 0.870

The evaluator is correct. The 144-image targeted-positive subset contains the
six primary targeted classes plus five secondary classes: apple, bowl,
mustard_bottle, pitcher_base, and sugar_box. Ultralytics macro-averages all 11
classes present in the subset. One missed sugar_box instance and bowl recall
2/3 lower the macro recall to 0.8697 even though the six primary targeted
classes are near 0.95-1.00 recall. This definition does not change the external
gate conclusion.

## Spatial gate

Confidence and bbox columns are minimum / median / maximum over each
placement maximum. Bbox values are width x height in pixels.

| Class | Result | Confidence | Bbox | Wrong-class FP placements | Same-frame duplicate placements |
|---|---:|---:|---:|---:|---:|
| banana | 2/15 | .003 / .158 / .548 | 24.2/31.0/49.2 x 5.9/7.5/14.9 | 0/15 | 0/15 |
| corrected beer | 15/15 | .924 / .966 / .981 | 21.8/33.7/43.9 x 49.0/69.8/86.4 | 0/15 | 0/15 |
| master_chef_can | 15/15 | .527 / .967 / .983 | 22.6/32.7/41.3 x 32.6/42.2/51.8 | 13/15 | 0/15 |
| coke_can | 15/15 | .902 / .935 / .954 | 12.7/18.6/27.2 x 25.4/34.2/50.5 | 9/15 | 0/15 |
| pudding_box | 15/15 | .901 / .954 / .978 | 15.3/27.6/50.1 x 18.5/24.6/36.7 | 2/15 | 0/15 |
| tomato_soup_can | 15/15 | .911 / .946 / .963 | 12.3/19.3/27.8 x 20.5/26.6/38.3 | 2/15 | 0/15 |

Banana used the identical valid historical capture and object yaw 5.140 rad
(about 294.5 degrees) as the V1 2/15 baseline. V2 detected only placements 03
and 05 at about 1.53 m and 1.76 m. All nine placements from about 1.99 m to
2.45 m failed, and four of the six shorter placements also failed. Far boxes
were commonly only about 6-8 pixels high. This is a systematic scale plus
problem-yaw failure, not an isolated miss, and V2 did not improve the V1
banana baseline.

Corrected beer improved from V1 0/15 to 15/15 with no wrong-class box. Master
improved from V1 8/15 to 15/15, but 13 placements contained 27 target-overlap
wrong-class boxes: 23 tomato_soup_can, three sugar_box, and one pudding_box.
Coke retained 15/15 but nine placements contained 14 target-overlap
tomato_soup_can boxes. Pudding and tomato each reached 15/15, with two
target-confusion placements apiece. A correct target detection plus an
additional target-overlap wrong class is not treated as a clean pass for the
FP decision.

## Lighting robustness gate

The lighting gate contains exactly 48 trials: four classes, three fixed
external scenarios, and four profiles. The profile values are the midpoints
of the already validated V2 physical ranges. Object model, pose, yaw, table,
P1/P2, camera, checkpoint, confidence, and detector settings are identical
between profiles.

| Class | Result | Normal median | Bright median | Dim median | Warm-side median |
|---|---:|---:|---:|---:|---:|
| banana | 12/12 | .736 | .768 | .695 | .600 |
| corrected beer | 12/12 | .965 | .971 | .957 | .961 |
| master_chef_can | 12/12 | .962 | .814 | .966 | .932 |
| coke_can | 12/12 | .917 | .921 | .904 | .913 |

There was no correct-target confidence collapse to 0.50 or below. The largest
same-scene drops were banana edge/problem-yaw under warm-side, .799 to .600,
and master edge/problem-yaw under bright, .962 to .787. Banana warm-side far
was .555, so its detection passed but has narrow margin. Lighting is not the
cause of the historical banana 2/15 spatial failure.

The FP dimension did show systematic lighting sensitivity. All 48 trials had
at least one wrong-class detector box because the unchanged room background
produced repeatable false boxes: normal and bright produced sugar_box,
dim produced bleach_cleanser, and warm-side produced bleach_cleanser,
cracker_box, and sugar_box. These are repeated signatures at fixed background
locations, not 48 independent objects. In addition, master produced 19
target-overlap wrong-class boxes in 8/12 lighting trials: 16 tomato_soup_can,
two pudding_box, and one sugar_box. Thus correct-target lighting recall passes,
but the overall lighting-aware detector gate does not pass because FP behavior
is systematic and profile-dependent.

## Stable-12 regression screen

| Class | Result |
|---|---:|
| apple | 5/5 |
| bleach_cleanser | 5/5 |
| bowl | 5/5 |
| chips_can | 5/5 |
| cracker_box | 5/5 |
| gelatin_box | 5/5 |
| mustard_bottle | 5/5 |
| pitcher_base | 5/5 |
| potted_meat_can | 5/5 |
| sugar_box | 5/5 |
| tuna_fish_can | 4/5 |
| windex_bottle | 5/5 |

Tuna missed only the physically visible corner placement. It was near at
about 1.37 m with an approximately 38 x 16 px candidate box, but confidence
was only .125, so this is a yaw/background risk rather than a far-scale miss.
The other four tuna scenarios ranged from .679 to .914. Across the stable
screen, 22/60 placements had 29 target-overlap wrong-class detections and the
near windex placement had one same-frame duplicate. There is no broad
correct-class forgetting, but the tuna miss and cross-class boxes prevent a
clean stable regression verdict. The earlier V1 representative captures are
not a valid direct external comparison because they had missing room meshes;
the synthetic stable-12 comparison remains non-regressed.

## Backup A/B

The epoch-40 backup was tested only on the identical 15 banana scenarios, as
predeclared. Epoch31 achieved 2/15 with confidence min/median/max
.003/.158/.548. Epoch40 achieved 4/15 with .009/.249/.579. Both are a strong
failure, so the backup does not solve the external banana problem and no wider
backup run is justified. Epoch31 remains the better candidate of the two
because its prior synthetic coke recall is materially stronger, but neither
checkpoint is ready to freeze.

## Evaluation tooling correction

Manual image review found that the three older `formal_18_class_*` capture
trees logged 60 missing-mesh errors each and rendered tabletop objects without
the intended table geometry. Reanalyses of those captures are retained but
are invalid evidence and are excluded from every verdict above. Banana/coke
historical tabletop evidence had zero such errors. Fresh beer/master,
pudding/tomato, stable-12, and lighting captures explicitly included both the
corrected official object root and the competition room resource root; all
their Gazebo logs have zero missing-resource or missing-geometry errors.

The shared capture layer now fails closed when Gazebo logs `Unable to find file
with URI`, `Cannot load null mesh`, or `Failed to load geometry for visual`.
It also records every formal wrong-class box, target association, and
same-frame duplicate. This prevents incomplete scenes from silently producing
a detector verdict.

## Evidence and representative images

Valid evidence roots:

- `~/robocup_assets/p2_eval/v2_epoch31_tabletop_banana_coke_final_20260916`
- `~/robocup_assets/p2_eval/v2_epoch31_expanded_beer_master_correct_resources_20260916`
- `~/robocup_assets/p2_eval/v2_epoch31_expanded_pudding_tomato_20260916`
- `~/robocup_assets/p2_eval/v2_epoch31_stable12_representative_correct_resources_20260916`
- `~/robocup_assets/p2_eval/v2_epoch31_lighting_gate_20260916`
- `~/robocup_assets/p2_eval/v2_epoch40_backup_banana_tabletop_20260916`

Representative raw images retained for manual review include:

- banana far/problem-yaw failure: `tabletop_robustness_gate_two_points_20260915/frames/banana_13_v1_y22.png`
- corrected beer far success: `v2_epoch31_expanded_beer_master_correct_resources_20260916/frames/beer_14_v1_y11.png`
- master far success/confusion case: `v2_epoch31_expanded_beer_master_correct_resources_20260916/frames/master_chef_can_14_v1_y09.png`
- pudding far success: `v2_epoch31_expanded_pudding_tomato_20260916/frames/pudding_box_14_v1_y10.png`
- tomato far success: `v2_epoch31_expanded_pudding_tomato_20260916/frames/tomato_soup_can_14_v1_y10.png`
- tuna corner failure: `v2_epoch31_stable12_representative_correct_resources_20260916/frames/tuna_fish_can_05_v1_y02.png`
- banana edge/problem-yaw normal/bright/dim/warm-side: the corresponding `banana_C_edge_problem_yaw` best frames under each lighting profile
- warm-side background cracker_box FP: `v2_epoch31_lighting_gate_20260916/warm_side/frames/coke_can_A_mid_v2_y01.png`

## Final decision

1. Epoch31 external detector Gate: **FAIL**.
2. External comparison with V1: clearly better for beer and master, unchanged
   for banana, and clean correct-class performance for the three borderline
   classes; not sufficient for formal replacement.
3. Correct-target lighting recall: **PASS**, 12/12 for every focus class.
4. Lighting risk: no confidence collapse, but banana has a narrow warm-side
   margin and background FP signatures are profile-dependent.
5. Epoch40: targeted banana A/B completed; it also fails and should not replace
   epoch31.
6. Retraining: no blind V3 or broad retraining is justified in this work, but
   the evidence is systematic enough that a bounded banana and cross-class-FP
   correction is required before freezing.
7. Detector freeze: **NO**.
8. Competition checkpoint: epoch31 remains the preferred candidate over
   epoch40, but there is no approved frozen replacement checkpoint yet.

P-001 stays OPEN. V2 runtime integration, `/map` 10 cm, duplicate tuning,
formal P1/P2 runner, full randomized regression, and FR3 work were not started.
The next work must first decide and execute the smallest competition-domain
correction for banana and target/background class confusion, then rerun these
same frozen gates.
