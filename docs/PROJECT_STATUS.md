# Project Status

## Last Updated

2026-09-16

## Current Stage

The formal P1/P2 Final Scoring Gate is complete for the 70-point autonomous
navigation and visual counting task. Nine of nine legal tabletop trials
completed navigation, P1/P2 scanning, tracking, one fused answer save, and
official 10 cm scoring. Across 28 GT, the result was 13 TP, 7 FP, and 15 FN;
the nine visual scores totaled 112/270 and averaged 12.44/30. Normal
combinations averaged 12.67/30 and dangerous combinations averaged 18/30.
With the navigation 40 points included, the measured nine-run center is about
52/70. This is a record of the tested scenarios, not a competition forecast.

## Current Goal

The documented formal baseline is V2 epoch31 (`epoch30.pt`), confidence 0.50,
early target whitelisting, P1 `(-3.485, -1.115, -0.532)`, P2
`(0.265, -0.665, -2.638)`, 5 cm online association, 8 cm final deduplication,
five final confirmations, and the existing position estimator. Detector and
banana development is stopped. No audited low-confidence, tracking, dedup,
confirmation, viewpoint, or position-estimator change has replaced this
baseline.

## Open Problems

### P-001 — Unified detector is not robust across all official classes

- **Status:** OPEN
- **Priority:** CRITICAL
- **Problem:** The selected V2 checkpoint is still unreliable for banana and
  produces systematic target-confusion and lighting-dependent background FPs.
- **Key evidence:** At confidence 0.50 and frozen P1/P2, epoch31 achieved
  banana 2/15. Image size 960 reached only 3/15 and remained 0/9 on the
  difficult yaw group. Class-agnostic NMS and IoU-0.50 cross-class suppression
  reduced wrong boxes only 74 to 73 while losing a master TP. The one permitted
  465-image V2.1 repair run still achieved banana 2/15. It reduced master wrong
  boxes from 27 to 8 and lighting wrong boxes from 91 to 29, but polluted beer
  from zero to eight wrong boxes on seven placements. Full evidence is in
  `docs/FORMAL_MODEL_V2_1_REPAIR_2026-09-16.md`. The final runtime audit found
  tiled inference 1/15, low-confidence replay at most 1/15 after five distinct
  saved frames, and P1/P2 plus a close fallback only 4/15. Full evidence is in
  `docs/BANANA_RUNTIME_REPAIR_2026-09-16.md`. The final geometry-discriminating
  pose `(-2.085, -2.415, -2.691)` passed one Nav2 reachability/scan smoke, but
  epoch31 detected banana in 0/15 untouched placements and 0/9 difficult
  placements. P1/new/P2 therefore remained 2/15 and 0/9 while adding four
  wrong-class boxes on three placements. The prescribed stop rule is met. In
  the full Final Scoring Gate, banana then produced 0 TP, 0 FP, and 3 FN across
  three legal layouts, losing all 10 banana points every time. The subsequent
  low-confidence audit classified 4/11 detector FN as strong sub-threshold,
  1/11 as weak, and 6/11 as absent/non-actionable. In a depth-enabled replay,
  banana at confidence 0.10 or 0.15 produced 1 TP plus 3 FP; master produced
  only a spatially wrong FP and bowl remained outside 10 cm. V2.1, image size
  960, tiled inference, low-confidence/tabletop rescue, the old fallback
  viewpoint, and the new geometry viewpoint were all tested and rejected. Full
  evidence is in `docs/LOW_CONFIDENCE_DETECTOR_FN_AUDIT_2026-09-16.md`.
- **Recorded disposition:** P-001 remains an accepted HIGH competition risk.
  Formal confidence remains 0.50; no low-confidence rescue, tabletop ROI
  rescue, global threshold lowering, or extra banana viewpoint is enabled.

### P-002 — Competition-like full-chain reliability is not established

- **Status:** OPEN
- **Priority:** HIGH
- **Problem:** Ten different randomized layouts with temporary obstacles,
  occlusion, and the eight-minute cap have not been completed.
- **Key evidence:** The Final Scoring Gate completed the full runner and scorer
  in 9/9 legal tabletop trials, but only 13/28 GT became TP; totals were 7 FP
  and 15 FN. Normal combinations scored 8, 20, and 10/30; dangerous
  combinations 18, 16, and 20/30; banana combinations 10, 10, and 0/30.
  The visual total was 112/270, or 12.44/30 on average. Thirteen TPs had
  0.58 cm minimum, 6.08 cm median, and 8.98 cm maximum error; three were over
  8 cm and none was at or above 10 cm. Three additional correct-class outputs
  failed at 10.37, 11.11, and 11.90 cm, each producing FP+FN. Full evidence is
  in `docs/FINAL_SCORING_GATE_2026-09-16.md`.
- **Recorded disposition:** The full runner has 9/9 successful end-to-end
  executions in this gate. This does not close P-002 because the broader
  randomized-layout requirement remains unverified.

### P-003 — Judge target-name input contract is unknown

- **Status:** OPEN
- **Priority:** MEDIUM
- **Problem:** The spelling and formatting of the three English target names
  supplied on competition day have not been confirmed.
- **Key evidence:** The official model directories and the audited 18-class
  manifest match exactly, but those identifiers do not prove the judge input
  syntax. The alias file is intentionally empty.
- **Next step:** Obtain the official input contract or a representative judge
  input sample, then validate normalization and add only confirmed aliases.

### P-004 — Final tracking fragmentation causes scorer FP and FN

- **Status:** OPEN
- **Priority:** HIGH
- **Problem:** Viewpoint-dependent localized points can form multiple tracks
  for one real object or remain below final confirmation instead of producing
  one stable output.
- **Key evidence:** The Final Scoring Gate produced four duplicate FPs: apple
  split into two outputs 10.80 cm apart, tomato into two outputs 14.86 cm
  apart, and coke into three outputs 11.48--25.17 cm apart. The offline audit
  found scan-angle position drift within P1 as well as P1/P2 mode changes.
  The four duplicate FP were apple 1, tomato 1, and coke 2. Of 15 FN, 11 were
  detector-evidence failures, zero were caused by depth/TF, one was primarily
  tracking/confirmation, three were localization failures at or beyond 10 cm,
  and zero were lost only by final filtering/dedup. Tracking is therefore not
  the main FN source. Final confirmation 4 was identical to 5, while 3 added
  two FP and reduced the nine-run score sum from 112 to 108. A 7/8/10 cm
  global online radius did not remove the four duplicate FP in final-centroid
  sensitivity and incorrectly merged 10--12 cm same-class objects under 2 cm
  localization jitter. The raw runs did not retain ordered 3D observations,
  so frame-exact online replay is not possible from the current corpus. Full
  evidence is in
  `docs/TRACKING_FRAGMENTATION_OFFLINE_AUDIT_2026-09-16.md`.
- **Recorded disposition:** There is no validated safe tracking-parameter or
  position-estimator change. Online association remains 5 cm, final dedup 8 cm,
  final confirmations 5, and the position estimator remains unchanged.

## Deferred Problems

### P-005 — Corner-frame calibration is unverified

- **Status:** DEFERRED
- **Priority:** MEDIUM
- **Problem:** Manual C0-C3 capture and official-scorer A/B validation have not
  been performed.
- **Key evidence:** The code and history audit found no prior corner
  calibration. Objects-only identity scoring has passed 20/20 at an explicit
  0.10 m gate, so this is not currently enabled in runtime.
- **Next step:** Revisit only if randomized scoring shows a systematic map-frame
  offset or the official environment requires corner alignment.

### P-006 — FR3 active manipulation is not integrated

- **Status:** DEFERRED
- **Priority:** LOW
- **Problem:** The FR3 is statically integrated, but active control, MoveIt2 /
  MoveIt Task Constructor, and visual grasping are not established.
- **Key evidence:** Static spawn, stowed posture, joint states, TF, sensors,
  base motion, and a Nav2 smoke passed at commit `cf93726`.
- **Next step:** Resume only after the 70-point base task is stable.

## Recently Solved

### P-007 — Competition Gazebo/Nav2 startup ownership failure

- **Status:** SOLVED
- **Priority:** HIGH
- **Problem:** The initial fixed-seed gate failed at `nav2_map_tf` in 5/5
  attempts because Gazebo server ownership was duplicated.
- **Key evidence:** Commit `1037610` kept the server launch-owned; the repeated
  gate then reached Gazebo/Nav2 startup in 5/5 attempts.
- **Next step:** Treat any recurrence of the same startup signature as
  `REGRESSED` under P-007.

### P-008 — Gross camera coverage at the two candidate viewpoints

- **Status:** SOLVED
- **Priority:** HIGH
- **Problem:** It was unknown whether legal tabletop placements entered a
  camera view from the candidate P1/P2 viewpoints.
- **Key evidence:** All 30 tested coke_can and banana placements entered a
  view. Coke_can passed 15/15 while banana passed 2/15, isolating the remaining
  weakness to detection robustness rather than gross viewpoint coverage.
- **Next step:** Do not tune viewpoints again from this evidence alone; reopen
  as `REGRESSED` only if broader layouts demonstrate coverage failures.

### P-009 — External audit accepted scenes with missing render resources

- **Status:** SOLVED
- **Priority:** HIGH
- **Problem:** Older 18-class audit captures silently continued after Gazebo
  failed to load room table/furniture meshes, making their tabletop evidence
  invalid.
- **Key evidence:** Each affected log contained 60 missing-resource/geometry
  errors and manual images showed floating objects. Fresh valid capture logs
  contain zero such errors. The shared capture layer now rejects three Gazebo
  missing-resource signatures before producing a valid result; focused tests
  cover the fail-closed rule.
- **Next step:** Preserve the older trees as invalid evidence and require the
  resource-complete capture path for every future visual gate.

### P-010 — Non-target detector classes entered localization and tracking

- **Status:** SOLVED
- **Priority:** HIGH
- **Problem:** The 18-class detector's confidence-passing non-target boxes
  reached depth, TF, markers, and tracking even though the final answer emitted
  only the three judge targets.
- **Key evidence:** The runtime now filters decoded detections against the
  already validated three-target set before any depth work. Focused tests keep
  both classes when master/tomato are requested together and reject an
  unrequested coke detection. Final answer filtering and model class order are
  unchanged.
- **Next step:** Reopen as `REGRESSED` only if a non-target class reaches
  localization telemetry, tracking, markers, or `answer.json`.

## Next Step

This documentation synchronization establishes no new project action. The
current recorded state is the frozen epoch31/P1/P2 baseline above, with
low-confidence rescue, banana alternatives, and the audited tracking parameter
changes rejected. No safe runtime parameter modification is currently
validated.
