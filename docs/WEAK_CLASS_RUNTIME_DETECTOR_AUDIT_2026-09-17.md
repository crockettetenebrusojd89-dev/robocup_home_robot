# Runtime-like weak-class detector audit — 2026-09-17

## Detector Repair Verdict

**NO LOW-RISK DETECTOR REPAIR.**

The evidence does not support a confidence/calibration change, a global
scale/distance explanation, or a single P1/P2 coverage fix.  There is a real
synthetic-to-runtime context and long-distance-tail mismatch, but the 11 FN
are too heterogeneous for a narrowly-scoped retrain to have a defensible,
low-risk score payoff.  In particular, several failures occur at ordinary
range and at synthetic-covered scale, and four representative frames already
prefer another class.  No model, training data, detector setting, runtime,
P1/P2, Nav2, RGB-D, tracking, or deduplication setting was changed.

## Scope and evidence

This audit examines exactly the **11 detector-evidence FN** from the 2026-09-16
Final Scoring Gate, not the separate one tracking/confirmation FN or three
`>=10 cm` localization FN.  It reuses only saved artifacts:

- Final Gate: `~/robocup_assets/p2_eval/final_scoring_gate_20260916`;
- existing low-confidence/depth audit;
- saved `offline_frames.jsonl` projection, P1/P2 step/yaw, and diagnostic
  inference records;
- V2 validation labels and targeted-generator metadata;
- unchanged `epoch30.pt`, once at `conf=0.001` for each FN's selected
  best-opportunity frame.

There was no Gazebo rerun.  The reproducible audit tool is
`tools/weak_class_detector_audit.py`; its generated manifest and summary are
read-only `/tmp` artifacts.  The raw low-threshold review is diagnostic only
and never enters the formal runtime.

## Weak-class runtime-like eval set

Each row has a projected-in-frame GT center.  `depth` is optical-axis distance
from saved TF/projection.  Exact 2-D GT boxes, object yaw, and occlusion masks
were not retained, so detector proxy boxes are explicitly not treated as GT
boxes.

| ID | Class | Source | View / step / camera yaw | Depth m | Max correct conf. | Primary taxonomy |
|---|---|---|---|---:|---:|---|
| 01 | beer | normal apple-beer-coke | P1 / 1 / -26.0° | 0.97 | n/a meaningful | Type 3 |
| 02 | mustard | normal apple-bowl-mustard | P1 / 9 / -115.1° | 2.13 | 0 | Type 3 |
| 03 | beer | normal beer-pudding-windex | P1 / 1 / 2.0° | 1.37 | 0 | Type 3 |
| 04 | pudding | normal beer-pudding-windex | P1 / 11 / -50.1° | 4.06 | .033 | Type 2 |
| 05 | master | danger master-tomato-apple | P1 / 3 / 47.6° | 1.88 | .317 | Type 1 |
| 06 | banana | banana-apple-beer | P1 / 12 / -55.3° | 1.98 | .392 | Type 1 |
| 07 | beer | banana-apple-beer | P2 / 12 / -102.5° | 1.30 | 0 | Type 2 |
| 08 | banana | banana-coke-bowl | P1 / 3 / 51.4° | 1.29 | .535 once | Type 4 |
| 09 | bowl | banana-coke-bowl | P1 / 10 / -117.6° | 1.96 | .277 | Type 1 |
| 10 | banana | banana-mustard-windex | P2 / 12 / -86.1° | 1.23 | .480 | Type 1 |
| 11 | mustard | banana-mustard-windex | P1 / 1 / -0.7° | 1.48 | 0 | Type 2 |

The first beer's `.178` large edge box is deliberately classified Type 3: the
previous visual audit established that it is background rather than the tiny
beer target.  It is retained in the manifest for traceability but excluded
from claims about true beer scale.

## Per-class detector evidence

| Weak class | FN opportunities | Meaningful correct signal | Any associated `>=.50` box | Finding |
|---|---:|---:|---:|---|
| banana | 3 | 3 | 1 | All three have signal, but two peak at .392/.480 and one has only one `.535` box. |
| beer | 3 | 0 | 0 | Two no-meaningful-detection cases and one high-confidence sugar confusion. |
| mustard_bottle | 2 | 0 | 0 | One no-detection and one wrong-class representative frame. |
| master_chef_can | 1 | 1 | 0 | `.317` master is nearly tied by `.319` pudding. |
| bowl | 1 | 1 | 0 | `.277` bowl, with a competing banana `.029`. |
| pudding_box | 1 | weak `.033` | 0 | A `.063` sugar box outranks the pudding box. |

The small controls are intentionally not used as final-score labels; their
saved detector-frame evidence shows that comparable scale/range can be
detected: apple median short-side 18.6 px at median 1.64 m, coke 14.5 px at
2.15 m, tomato 12.1 px at 2.32 m, and windex 18.1 px at 2.41 m.

## Confidence taxonomy

| Type | Count | Evidence |
|---|---:|---|
| Type 1 — correct class below .50 | 4 | master, two banana layouts, bowl |
| Type 2 — wrong-class box at representative opportunity | 3 | beer→sugar, pudding→sugar, mustard→cracker/chips |
| Type 3 — no meaningful detector signal | 3 | beer edge/background, beer low `.002` cracker, mustard no-box case |
| Type 4 — a correct `.50` box but temporally insufficient | 1 | banana-coke-bowl: one `.535` observation only |

Thus only 4/11 are threshold-like, and even those are not clean calibration
cases: master has nearly equal pudding confidence and the banana/bowl
low-confidence counterfactual previously created unsafe outputs.  Type 4 is
not counted as a threshold miss: lowering the threshold cannot repair an
already-above-threshold single observation under the frozen confirmation rule.

## Pixel size and distance

Across the 305 diagnostic correct-class candidate frames for these FN, the
model-box short-side distribution is 3.4--98.6 px (median 14.2 px), and saved
optical-axis distance is 0.97--4.48 m (median 2.04 m).  These are detector
proxies, not GT silhouettes; no-box cases have no defensible pixel-size value.
Data-dependent short-side quartiles were `<=9.76`, `9.76--14.23`,
`14.23--16.25`, and `>=16.25` px.  Only one candidate frame in all four bins
was formally associated at `.50`; even the large bin had no formal success.
Scale alone therefore does not explain the misses.

The more useful class comparison is below.  V2 validation values use labels;
runtime values use correct-class diagnostic proxies and are unavailable when
there was no meaningful target box.

| Class | V2 val median short side px | Targeted-val median short side px | Runtime candidate median short side px | Targeted primary distance median m | Runtime candidate distance median m |
|---|---:|---:|---:|---:|---:|
| banana | 12.0 | 9.0 | 13.1 | 2.14 | 2.04 |
| master | 27.0 | 22.0 | 26.4 | 2.09 | 1.80 |
| bowl | 26.5 | 14.0 | 14.2 | unavailable (secondary-only) | 2.07 |
| pudding | 26.0 | 13.0 | 25.9 | 2.17 | 4.24 |
| beer | 27.0 | 27.0 | unavailable meaningful box | 1.76 | unavailable |
| mustard | 28.5 | 16.0 | unavailable | unavailable (secondary-only) | unavailable |

**Pixel size is not the primary general factor.** Banana and master match or
exceed their synthetic median scale while failing; tomato and coke controls
are often detected at the same or smaller scale. Bowl has one small-scale
case, so scale is a secondary contributor there.

**Distance is not the primary general factor.** Several misses are at
0.97--1.98 m, whereas controls remain detectable to 2.3--2.4 m median.
There is nevertheless a real long-tail gap: targeted generation defines
`far = 2.05--2.60 m`, while runtime evidence reaches 4.48 m and the pudding
case is 4.06 m.  This explains a subset risk, not the entire weak-class set.

## View / scan coverage

All three banana GT had many projected-in-frame opportunities (92, 86, and
196).  Their strongest signal swaps by layout rather than identifying one bad
viewpoint:

- banana-apple-beer: P1 `.392`, P2 `.072`;
- banana-coke-bowl: P1 `.535`, P2 `.152`;
- banana-mustard-windex: P1 `.032`, P2 `.480`.

Therefore view angle affects confidence, but neither P1 nor P2, nor a single
scan yaw, is a universal blind spot.  The synthetic targeted primary yaw
metadata also spans broad nominal ranges (banana 12.6--348.6°, beer
11.9--347.5°, master 14.2--332.4°).  Runtime object yaw itself was not
retained, so a more precise relative-yaw comparison is unavailable.

## Synthetic versus runtime distribution

There is an evidenced **context/domain and long-distance-tail gap**, but not a
single sufficient retraining prescription:

- targeted synthetic primary samples have one labeled target per image for
  banana, beer, master, and pudding; runtime scenes have three judge targets
  plus room furniture and table context;
- targeted generation uses four wood backgrounds and four fixed lighting
  profiles, with camera bearing limited to ±12°; runtime lighting/material
  metadata was not retained, so a numerical lighting-distance test is not
  available;
- the long-distance tail above 2.60 m is absent from targeted generation;
- wrong-class evidence is concrete: pudding→sugar, beer→sugar,
  mustard→cracker/chips, and master nearly ties pudding.

This supports a domain/context hypothesis, especially for Type 2/3 errors,
but it does not establish that a small data patch will safely improve the
final scorer.  V2.1 already demonstrated that a focused repair can exchange
one confusion for another, and this audit adds no single class/view/scale
slice that dominates the 11 FN.

## Detector-FN root-cause taxonomy

| Primary cause | Count | Secondary / qualifier |
|---|---:|---|
| Correct class below formal confidence | 4 | view-sensitive signal; master also confused with pudding |
| Wrong-class preference | 3 | texture/context/class discrimination, not a threshold-only issue |
| No meaningful target evidence | 3 | includes a close-range case; scale cannot explain it |
| One formal detection but insufficient temporal evidence | 1 | banana; not repairable by lowering confidence |

The leading causes are therefore: (1) class discrimination/context mismatch,
(2) view-sensitive low confidence for a subset, and (3) a real but non-dominant
long-distance tail.  Occlusion fraction and exact GT box extent remain
unavailable, so neither is assigned as a primary cause.

## Decision

No data patch specification is proposed because **TARGETED RETRAIN WORTHWHILE**
is not justified by the present evidence.  Do not start data generation,
training, hyperparameter search, confidence rescue, new viewpoints, or runtime
integration from this audit.  Keep the frozen base-task detector path and move
to the separately authorized FR3/high-score work only after user confirmation.

## Validation

- `python3 -m py_compile tools/weak_class_detector_audit.py` passed.
- The audit completed with 11 selected FN; taxonomy totals are
  Type 1=4, Type 2=3, Type 3=3, Type 4=1.
- No source runtime file, launch file, model, Nav2 file, viewpoint, tracker,
  deduplication, or confirmation configuration was modified.
