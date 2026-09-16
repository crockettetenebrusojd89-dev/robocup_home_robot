# RGB-D tabletop object proposal POC — 2026-09-16

## Verdict: FAIL

This is an isolated, offline, class-agnostic POC. It does not import YOLO or
ROS, publish a topic, call a service, modify an answer, or alter the formal
runtime. The stop rule is met: stable proposal recall is 0/6 (0%), and banana
is not stable at either P1 or P2. Crop inference was not run.

## Method and resource audit

- Four normal-height `living_room_table_*` models are eligible. Their fixed
  polygons come from `tools/p2_eval/tables.json`; every SDF surface is 0.78 m.
  Tea and dining tables are excluded.
- Existing topics are RGB, depth, CameraInfo, `camera_optical_frame`, and
  map-to-camera TF. The formal localizer has bbox-median depth only; there was
  no reusable point-cloud, plane-removal, DBSCAN, or clustering code.
- The Final Scoring Gate has no depth replay corpus. Two later low-confidence
  runs retain 16-bit depth, CameraInfo, per-frame TF, and GT for post-hoc score.

For 8 uniformly spaced rotation frames at P1 and P2 per run (32 frames), the
POC reconstructs valid depth points in `/map`, keeps only fixed tabletop
polygons, removes the fixed tabletop height band, then voxelizes at 1.5 cm and
uses 26-neighbour connected components. Components require 5 voxels, 18 points,
and no extent above 45 cm. The fixed centre estimator is coordinate-wise median.

A table-only geometry check found this simulator's RGB-D/TF map-Z convention
0.175 m below SDF table height. Plane removal therefore uses
`surface_z - 0.175 m`, retaining 1.2--45 cm above it. This is static geometry
calibration only, never class or GT tuning. Matching is formal strict map-XY
`<0.10 m`, applied only after proposal generation.

## Dataset and performance

The two retained scenes contain 6 GT: banana, coke_can, bowl, master_chef_can,
tomato_soup_can, and apple. They provide P1/P2 but not yaw, distance, or
close-pair coverage; the banana stop condition prevented further capture.

| Class | GT | stable | matched frames | median | max |
|---|---:|---:|---:|---:|---:|
| apple | 1 | 0 | 2 | 6.87 cm | 7.85 cm |
| banana | 1 | 0 | 2 | 8.39 cm | 9.24 cm |
| bowl | 1 | 0 | 2 | 6.74 cm | 7.76 cm |
| coke_can | 1 | 0 | 1 | 6.08 cm | 6.08 cm |
| master_chef_can | 1 | 0 | 1 | 8.96 cm | 8.96 cm |
| tomato_soup_can | 1 | 0 | 2 | 5.84 cm | 6.73 cm |

- Frame recall: 10 / (32 × 6) = **5.21%**; stable recall (≥5 matches) is
  **0/6 = 0%**.
- False proposals: **6**, or **0.19/frame**. Structural per-frame merge/split:
  **0/0**; absence rather than clean separation is the failure.
- The 10 isolated matches have 4.95 cm minimum, 7.14 cm median, and 9.24 cm
  maximum XY error; `<5/5--8/8--10/>=10 cm` is `1/7/2/0`. This sparse result
  does not beat the formal 6.08 cm median or establish a stable estimator.

## Banana and decision

Banana has one GT and only one `<10 cm` proposal at P1 (9.24 cm) and one at P2
(7.55 cm): 2/16 samples, below the required 5-frame stability threshold.
Banana stable recall, P1 stable recall, and P2 stable recall are all **0%**.

**FAIL.** Overall stable recall is below 90%, banana is not stable, and there
is no evidence of lower 10 cm risk. Do not do crop classification, further
proposal sweeps, or runtime integration.

## Reproduction boundary

`tools/tabletop_proposal_poc/tabletop_proposal_poc.py` replays the two saved
run directories using `tools/p2_eval/tables.json`. Its result JSON is
`~/robocup_assets/p2_eval/tabletop_proposal_poc_20260916/results.json`.
The formal detector, checkpoint, confidence, P1/P2, tracking, deduplication,
confirmations, position estimator, Nav2, TF, and answer writer are unchanged.
