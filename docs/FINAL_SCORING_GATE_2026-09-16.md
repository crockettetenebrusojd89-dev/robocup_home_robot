# Final Scoring Gate — 2026-09-16

## Scope and verdict

The frozen epoch31 runtime completed the full P1/P2 chain in all nine legal,
reproducible tabletop scenarios, but the vision chain is **not yet
competition-ready**. Navigation, scan sequencing, reset ownership, answer
writing, and the strict scorer boundary were reliable. Final-answer recall,
tracking fragmentation, and 10 cm localization were not.

Across 28 ground-truth objects, the official 10 cm scorer measured 13 TP,
7 FP, and 15 FN. Normal combinations scored 8, 20, and 10 out of 30. Dangerous
requested-pair combinations scored 18, 16, and 20. Banana combinations scored
10, 10, and 0; banana itself was 0 TP, 0 FP, and 3 FN and therefore lost the
full 10 class points in every tested combination.

This gate did not change the checkpoint, confidence, P1/P2, navigation, RGB-D,
TF, confirmation, or deduplication settings. It did not train a model.

## Frozen contract

- Checkpoint: `/home/hao/robocup_assets/training_runs/formal_objects_v2_yolo11n_finetune/weights/epoch30.pt`
- SHA256: `c16f5332221649fdb89c225f9aaec6f73db97e2590bc37734a6d0e0a5099564c`
- Confidence: 0.50
- P1: `(-3.485, -1.115, -0.532)`
- P2: `(0.265, -0.665, -2.638)`
- Online tracking radius: 0.05 m
- Final deduplication radius: 0.08 m
- Online confirmation threshold: 3 observations
- Final confirmation threshold: 5 observations
- Official match gate: strict distance `< 0.10 m`
- Evidence root: `~/robocup_assets/p2_eval/final_scoring_gate_20260916`

Before the gate, the installed localizer was found to predate the committed
early-whitelist source. The package was rebuilt without changing source or
parameters, and the installed/runtime script hash then matched the source hash
`d318b59f...cfed`. This prevented the gate from accidentally exercising the
old deployment.

## A. Runtime audit

All required runtime behaviors matched the formal contract:

- Early whitelist: **PASS**. `filter_target_detections()` runs immediately
  after detector decoding and before depth, TF, markers, and tracking. Its
  focused regression test passed, and every runtime launched with exactly the
  requested three target classes.
- Reset timing: **PASS**. Every one of the nine logs contains exactly one
  localizer reset at the first P1 scan and one explicit P2
  `preserving visual tracking` marker. There is no P1-to-P2 reset.
- Confirmations and dedup: **PASS as configuration**. Runtime logs show 3
  online confirmations, 5 final confirmations, 0.05 m online association, and
  0.08 m final deduplication. Their scoring quality is analyzed below.
- Answer writer: **PASS**. All nine answer files contain exactly the three
  judge targets and finite `x/y` values only.
- Scorer: **PASS**. Every run invoked the official one-to-one class matcher
  with `--match-threshold 0.10`. Extra same-class outputs after the first match
  were counted as FP.
- Full runner: **PASS operationally**. Nine of nine trials completed P1,
  scan, P2, scan, one fused answer save, and scoring. Runtime was 148.4--201.0
  seconds, with no navigation, timeout, depth-TF availability, or scorer-stage
  failure.

Validation also passed 14 formal-runtime, 9 final-dedup, and 20 P2 evaluator
tests.

## B. Normal combinations

| Targets | GT | TP | FP | FN | Per-class scores | Visual score |
|---|---:|---:|---:|---:|---|---:|
| apple / beer / coke_can | 4 | 2 | 2 | 2 | apple 8, beer 0, coke 0 | **8/30** |
| apple / bowl / mustard_bottle | 3 | 2 | 0 | 1 | apple 10, bowl 10, mustard 0 | **20/30** |
| beer / pudding_box / windex_bottle | 3 | 1 | 0 | 2 | beer 0, pudding 0, windex 10 | **10/30** |

The normal-combination range is 8--20/30, with a mean of 12.67/30. This is
not a high-scoring baseline.

Detailed final outputs:

- `apple / beer / coke_can`
  - apple prediction `(-1.901, -0.012)` -> GT `(-1.877, -0.014)`, 2.44 cm,
    19 observations, TP.
  - apple prediction `(0.518, -2.355)` -> GT `(0.570, -2.311)`, 6.78 cm,
    8 observations, duplicate FP.
  - apple prediction `(0.574, -2.263)` -> the same GT, 4.85 cm,
    34 observations, TP. The two outputs for this object are 10.80 cm apart.
  - coke prediction `(-3.319, -3.458)` -> GT `(-3.397, -3.526)`, 10.37 cm,
    23 observations, localization FP plus FN.
  - beer had one valid-depth/TF observation and did not reach final output.
- `apple / bowl / mustard_bottle`
  - apple `(-3.613, -2.064)` -> GT `(-3.662, -2.139)`, 8.98 cm, TP.
  - bowl `(0.632, -2.920)` -> GT `(0.589, -2.983)`, 7.54 cm, TP.
  - mustard had zero detections and was an FN.
- `beer / pudding_box / windex_bottle`
  - windex `(-3.391, -2.949)` -> GT `(-3.452, -3.012)`, 8.75 cm, TP.
  - beer had two isolated one-observation clusters.
  - pudding had six detections, four valid-depth/TF points, and only
    one/two-observation clusters; neither class reached the five-observation
    final gate.

## C. Dangerous combinations

| Targets | GT | TP | FP | FN | Visual score |
|---|---:|---:|---:|---:|---:|
| master_chef_can / tomato_soup_can / apple | 3 | 2 | 1 | 1 | **18/30** |
| coke_can / tomato_soup_can / apple | 3 | 2 | 3 | 1 | **16/30** |
| master_chef_can / coke_can / tomato_soup_can | 3 | 2 | 0 | 1 | **20/30** |

### Master plus tomato

Master had zero detections. Tomato produced two final clusters:

- `(0.515, -3.029)` -> tomato GT `(0.530, -2.969)`, 6.16 cm,
  6 observations, TP.
- `(0.586, -2.898)` -> the same tomato GT, 9.02 cm,
  11 observations, duplicate FP.

The two tomato clusters are 14.86 cm apart and both are near the real tomato,
not the master GT at `(-1.670, 0.087)`. Therefore the measured final FP is a
tracking split of the real tomato, not a surviving master-to-tomato
cross-class error. No localized tomato track existed near the master.

### Coke plus tomato

- Coke `(-2.356, -0.007)` -> GT `(-2.374, 0.034)`, 4.44 cm,
  16 observations, TP.
- Coke `(-2.286, -0.098)` -> the same GT, 15.82 cm,
  6 observations, duplicate FP.
- Coke `(-2.223, -0.221)` -> the same GT, 29.57 cm,
  11 observations, duplicate FP.
- Tomato `(0.721, -2.815)` -> GT `(0.714, -2.829)`, 1.51 cm, TP.
- Apple `(-3.412, -2.847)` -> GT `(-3.489, -2.938)`, 11.90 cm,
  24 observations, localization FP plus FN.

The coke clusters are 11.48, 13.79, and 25.17 cm apart. No tomato output was
near the coke GT, so coke-to-tomato did not survive as a final cross-class FP
in this layout. The two coke FPs are tracking splits of the true coke.

### Master plus coke plus tomato

- Master `(-1.632, -0.051)` -> GT `(-1.676, -0.025)`, 5.17 cm, TP.
- Coke `(0.697, -2.972)` -> GT `(0.662, -3.024)`, 6.26 cm, TP.
- Tomato generated eight valid-depth/TF detections, but they split into five
  clusters with at most two observations, so none reached final output.

The final answer contained no FP. One 5-observation coke fragment was merged
into the 27-observation main track by final dedup, demonstrating that the
existing 8 cm merge can work when fragmentation remains inside its radius.

### Dangerous-pair conclusion

The prior raw detector evidence still justifies treating master/tomato and
coke/tomato as risks, but **none of these three final answers contained a
cross-class FP near another requested class's GT**. Raw requested-pair
confusion did not demonstrably survive depth, TF, tracking, confirmation, and
final dedup in these layouts. The observed dangerous-combination losses came
from a class miss, a confirmation failure, three same-object tracking-split
FPs, and one >10 cm localization failure.

## D. Banana combinations

| Targets | Banana TP/FP/FN | Other classes | Visual score |
|---|---:|---|---:|
| banana / apple / beer | 0 / 0 / 1 | apple 10, beer 0 | **10/30** |
| banana / coke_can / bowl | 0 / 0 / 1 | coke 10, bowl 0 | **10/30** |
| banana / mustard_bottle / windex_bottle | 0 / 0 / 1 | mustard 0, windex 0 | **0/30** |

Banana produced zero runtime detections, zero tracks, and zero final outputs in
all three layouts. Its class score was always 0. For the tested one-banana
ground truth, both typical and worst banana-attributable loss were **10
points**. Banana did not add an FP in this gate; its failure mode was pure FN.

The only final coordinates in the banana groups were:

- Apple `(-1.926, -0.009)` -> GT `(-1.927, -0.003)`, 0.58 cm, TP.
- Coke `(0.577, -2.815)` -> GT `(0.586, -2.875)`, 6.08 cm, TP.
- Windex `(-3.453, -3.481)` -> GT `(-3.547, -3.541)`, 11.11 cm,
  localization FP plus FN. Final dedup had merged two windex tracks 6.6 cm
  apart before producing this output.

The group-level 0--10 range is worse than banana's fixed 10-point loss because
the companion classes also failed in these particular legal placements.

## E. Localization

For the 13 official TPs:

- Minimum error: **0.58 cm**
- Median error: **6.08 cm**
- Maximum error: **8.98 cm**
- TP samples over 8 cm: **3**
- TP samples at or above 10 cm: **0**

Three additional correct-class outputs failed the strict gate:

| Class | Prediction | GT | Error | Scorer effect |
|---|---|---|---:|---|
| coke_can | `(-3.319, -3.458)` | `(-3.397, -3.526)` | 10.37 cm | FP + FN |
| windex_bottle | `(-3.453, -3.481)` | `(-3.547, -3.541)` | 11.11 cm | FP + FN |
| apple | `(-3.412, -2.847)` | `(-3.489, -2.938)` | 11.90 cm | FP + FN |

All observations feeding these outputs had valid depth and successful TF; the
nine trials recorded no TF failure. Thirteen other TPs remained below 9 cm,
which argues against a single gross AMCL/map or TF offset. The strongest
current evidence is viewpoint-dependent visible-surface/bbox representative
points followed by tracking-centroid aggregation. This is a root-cause
hypothesis supported by the class/layout dependence and cluster drift, not a
license to change RGB-D geometry, TF, AMCL, or Nav2 without a controlled A/B.

## F. Duplicate final FP

The scorer counted **four duplicate FPs** affecting three classes:

| Class/layout | Output clusters for one GT | Pairwise separation | Observations | Result |
|---|---:|---:|---|---|
| apple, normal 1 | 2 | 10.80 cm | 8 and 34 | 1 TP + 1 FP |
| tomato, danger A | 2 | 14.86 cm | 6 and 11 | 1 TP + 1 FP |
| coke, danger B | 3 | 11.48--25.17 cm | 6, 11, 16 | 1 TP + 2 FP |

These are tracking splits first: the online 5 cm association produced distinct
tracks for one physical object. They then remained too far apart for the 8 cm
final merge. The evidence now proves duplicate output is a formal scoring
blocker, but no radius was changed in this work. A radius change still needs a
controlled close-pair A/B so two real nearby same-class objects are not merged.

## G. Final score risks

- **HIGH — final-answer recall:** 15/28 GT were FN. Seven class instances had
  zero runtime detections; five had detections/depth/TF but no track reached
  final output; three had final outputs outside 10 cm.
- **HIGH — banana FN:** 0/3, with a repeatable 10-point class loss.
- **HIGH — tracking/confirmation:** five class instances produced detections
  but no final answer, and track fragmentation created four duplicate FPs.
- **HIGH — localization margin:** three outputs failed at 10.37--11.90 cm and
  three additional TPs were already over 8 cm.
- **HIGH — duplicate:** four of seven total FPs were same-object duplicates.
- **MEDIUM — master/tomato final confusion:** historical raw confusion remains,
  but no final cross-class track was observed here. Master recall itself was
  inconsistent across the two relevant layouts.
- **LOW-to-MEDIUM — coke/tomato final confusion:** no final cross-class FP was
  observed, although coke track fragmentation was severe in one layout.

## H. Final verdict

1. **Competition usability:** No. The runner is operationally reliable, but
   the complete vision chain is not reliably scoring.
2. **Normal combinations:** 8--20/30, mean 12.67/30 in this gate.
3. **Dangerous combinations:** 16--20/30, mean 18/30. Historical cross-class
   risk did not become a final cross-class FP here; other failures dominated.
4. **Banana impact:** banana consistently lost 10/10 class points; tested group
   scores were 0--10/30, mean 6.67/30.
5. **Largest score blocker:** failure to produce a correct final answer for the
   GT object: 15 FN versus 13 TP. Under the frozen-detector rule, the narrowly
   actionable portion is the five detected/depth/TF-success classes that still
   failed track formation or final confirmation. Duplicate track fragmentation
   is the largest final-FP mechanism.
6. **Continue visual work:** Yes, but only on this evidenced final-output
   track/confirmation blocker. Do not resume training, banana viewpoints,
   confidence sweeps, or unrelated geometry changes.
7. **Proceed to broad randomized repeats:** Not as a readiness campaign yet.
   The formal P1/P2 runner itself passed 9/9 and is ready to use, but broad
   repeats would mainly reconfirm the current low score. First isolate the
   detected-but-not-final track/confirmation failures with one controlled
   variable; then rerun this same scorer gate before broader competition
   repeats.
