# Low-confidence detector-FN audit — 2026-09-16

## Verdict

The 11 detector-evidence false negatives from the Final Scoring Gate contain
four strong correct-class sub-threshold cases, one weak case, and six absent
or non-actionable cases. This is enough signal to test a rescue path offline,
but not enough to enable one. In two representative depth-enabled replays, no
single threshold/confirmation setting added 4--5 TP with few or no FP.

The proposed rescue is therefore **rejected**. The formal checkpoint,
confidence 0.50, P1/P2, tracking, confirmation, deduplication, RGB-D, TF,
Nav2, and final answer path remain unchanged.

## Frozen boundary and evidence

- Checkpoint: epoch31 V2 (`epoch30.pt`), SHA256 `c16f5332...9564c`
- Formal confidence: 0.50
- P1: `(-3.485, -1.115, -0.532)`
- P2: `(0.265, -0.665, -2.638)`
- Original evidence:
  `~/robocup_assets/p2_eval/final_scoring_gate_20260916`
- Depth-enabled representative evidence:
  - `~/robocup_assets/p2_eval/low_conf_depth_audit_banana_coke_bowl_20260916`
  - `~/robocup_assets/p2_eval/low_conf_depth_audit_danger_master_tomato_apple_20260916`
- Reproducible counterfactual matrix:
  `~/robocup_assets/p2_eval/low_conf_depth_audit_20260916/low_confidence_rescue_audit.json`

The original gate inferred every saved RGB frame at diagnostic confidence
0.001, but it did not retain aligned depth or map positions for every
sub-threshold box. Consequently its per-FN table can establish 2D detector
signal, not whether that signal would survive depth, fixed-table ROI, and the
10 cm map gate. The representative replays add those missing observations.

## Per-FN audit

`P1/P2` is `visible frames / correct-class candidate frames (maximum
confidence)`. Confidence counts use all visible captured frames and are shown
for `>=.10/.15/.20/.30/.40/.50`. Bounding boxes are the maximum-confidence
GT-associated box in `x1,y1,x2,y2` pixels.

| Scenario / class | GT map xyz | P1 / P2 | Visible / candidate | Max / median | Counts .10/.15/.20/.30/.40/.50 | Max bbox | Depth / map evidence | Class |
|---|---|---|---:|---:|---|---|---|---|
| normal apple-beer-coke / beer | `(-2.911,-2.064,.780)` | `49/31 (.178)` / `43/0` | 92 / 31 | .178 / .001 | 2/1/0/0/0/0 | `(586,192,639,276)` | Original depth/map unavailable; visual review shows the strongest large edge box is background, not the tiny beer | C |
| normal apple-bowl-mustard / mustard | `(-3.467,-3.483,.780)` | `41/0` / `51/0` | 92 / 0 | 0 / 0 | 0/0/0/0/0/0 | — | No 2D candidate; depth/map not applicable | C |
| normal beer-pudding-windex / beer | `(-2.154,.041,.780)` | `40/0` / `48/0` | 88 / 0 | 0 / 0 | 0/0/0/0/0/0 | — | No 2D candidate; depth/map not applicable | C |
| normal beer-pudding-windex / pudding | `(.525,-2.852,.780)` | `59/16 (.033)` / `110/6 (.032)` | 169 / 22 | .033 / .003 | 0/0/0/0/0/0 | `(107,192,138,273)` | Signal never reaches .10; original depth/map unavailable | C |
| danger master-tomato-apple / master | `(-1.670,.087,.780)` | `42/2 (.317)` / `50/0` | 92 / 2 | .317 / .271 | 2/2/2/1/0/0 | `(498,196,523,229)` | Replay: 298/298 aligned depths; stable 8-frame cluster is 25.3 cm from GT, lone stronger candidate 11.7 cm | A, unsafe |
| banana-apple-beer / banana | `(-3.395,-3.316,.780)` | `37/37 (.392)` / `55/52 (.072)` | 92 / 89 | .392 / .046 | 34/30/8/3/0/0 | `(535,218,582,229)` | Original depth/map unavailable | A |
| banana-apple-beer / beer | `(.677,-2.523,.780)` | `48/0` / `180/0` | 228 / 0 | 0 / 0 | 0/0/0/0/0/0 | — | No 2D candidate; depth/map not applicable | C |
| banana-coke-bowl / banana | `(-2.348,-.096,.780)` | `35/35 (.535)` / `51/34 (.152)` | 86 / 69 | .535 / .129 | 44/33/18/15/1/1 | `(471,244,501,258)` | Replay: 283/287 aligned depths; true clusters 3.2--5.6 cm from GT, but extra true fragments and an 8-frame false banana cluster on the bowl table | A, unsafe |
| banana-coke-bowl / bowl | `(-3.575,-3.479,.780)` | `34/33 (.277)` / `257/0` | 291 / 33 | .277 / .131 | 18/3/2/0/0/0 | `(21,214,64,228)` | Replay candidate cluster has valid depth but is 15.1 cm from GT | B, non-scoring |
| banana-mustard-windex / banana | `(.626,-2.156,.780)` | `53/2 (.032)` / `143/57 (.480)` | 196 / 59 | .480 / .267 | 52/48/32/28/7/0 | `(133,254,188,274)` | Original depth/map unavailable | A |
| banana-mustard-windex / mustard | `(-1.979,.046,.780)` | `39/0` / `47/0` | 86 / 0 | 0 / 0 | 0/0/0/0/0/0 | — | No 2D candidate; depth/map not applicable | C |

Classification totals: **A = 4, B = 1, C = 6, D = 0**. A/B therefore
exceeds the three-instance early-stop threshold and justified the bounded
depth-enabled replay. “A” means strong 2D evidence, not a safe final output;
the map checks above show why that distinction matters.

## Observational telemetry added

The evaluation capture now saves timestamp-aligned 16-bit depth images for
runtime-sampled RGB frames. Offline analysis records every requested-class
diagnostic box, its bbox-center median depth, and its camera-to-map point.
This is read-only evaluation telemetry: it publishes nothing, calls no
service, and cannot affect the formal detector or answer.

Representative depth coverage was 283/287 frames (98.6%) for
banana/coke/bowl and 298/298 frames (100%) for master/tomato/apple. The two
scenes cover the requested ordinary FN, banana FN, dangerous similar-class
pair, and stable controls (coke and apple); the remaining seven full scenes
were not unnecessarily rerun.

## Offline tabletop rescue

The disabled counterfactual used only fixed table geometry from
`tools/p2_eval/tables.json`, never GT, to admit a candidate:

- XY inside any official living-room tabletop plus 5 cm margin;
- Z from 33 cm below to 12 cm above the known table surface;
- requested class only, formal output absent, and confidence below 0.50;
- thresholds 0.10/0.15/0.20/0.30;
- 10 cm exploratory spatial clustering;
- 2/3/5 distinct-frame confirmations.

GT enters only after clustering to score the counterfactual with the official
strict `<10 cm` one-to-one rule.

### TP/FP/FN matrix highlights

| Missing class | Threshold | Confirm 2 | Confirm 3 | Confirm 5 | Interpretation |
|---|---:|---:|---:|---:|---|
| banana | .10 | 1/3/0 | 1/3/0 | 1/3/0 | One TP, but fragmentation plus bowl→banana confusion creates three FP |
| banana | .15 | 1/3/0 | 1/3/0 | 1/3/0 | Same unsafe result |
| banana | .20 | 0/2/1 | 0/2/1 | 0/2/1 | Only wrong/non-scoring clusters remain |
| bowl | .10/.15 | 0/1/1 | 0/1/1 | 0/0/1 | Repeated evidence still lies outside 10 cm |
| master | .10/.15 | 0/1/1 | 0/1/1 | 0/1/1 | Stable low-confidence evidence is spatially wrong |
| tomato | .10 | 1/2/0 | 1/1/0 | 1/0/0 | High confirmation can isolate one TP in this replay only |
| tomato | .30 | 1/0/0 | 1/0/0 | 1/0/0 | Best single replay result, only +1 TP |

No shared policy approaches the required +4--5 TP with few or no FP. The
banana result is particularly disqualifying under the competition formula:
one recovered TP with three FP scores only 4 points for that class and risks
new false outputs on another real object. The isolated tomato gain is too
narrow to justify a second production decision path.

## Decision and next action

1. Do not implement or enable low-confidence rescue.
2. Keep formal confidence 0.50 and all frozen runtime parameters.
3. Preserve the new telemetry and offline analyzer for future diagnostics.
4. Return focus to the already identified ordered tracking-observation replay
   gap under P-004; do not train, add viewpoints, or rerun all nine scenes.

## Validation

- 25 focused P2 evaluator tests pass, including aligned depth localization,
  oriented tabletop ROI, distinct-frame clustering, and duplicate-FP scoring.
- `robocup_home_robot` rebuilt successfully after the telemetry change.
- Both representative Gazebo/ROS2/scorer runs completed normally.
- `git diff --check` passes.
