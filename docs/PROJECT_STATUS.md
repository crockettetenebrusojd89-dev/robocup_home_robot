# Project Status

## Last Updated

2026-09-15

## Current Stage

P2 robustness work for the 70-point autonomous navigation and visual counting
task. One full formal-model run is integrated, and randomized evaluation has
identified model generalization as the immediate blocker.

## Current Goal

Train and re-audit one unified 18-class Formal Model V2 checkpoint from the
completed, validated 2,700-image dataset, but only after explicit approval and
without changing the frozen competition runtime parameters.

## Open Problems

### P-001 — Unified detector is not robust across all official classes

- **Status:** OPEN
- **Priority:** CRITICAL
- **Problem:** The current checkpoint is unreliable for corrected beer,
  banana, and master_chef_can; three additional classes are borderline.
- **Key evidence:** At confidence 0.50, the expanded audit produced banana
  2/15, corrected beer 0/15, and master_chef_can 8/15. Coke_can,
  pudding_box, and tomato_soup_can each passed 4/5. In the existing beer
  training set, 183/184 labelled boxes are majority near-black, unlike the
  corrected rendered asset. The completed 724-image targeted supplement passed
  all quota, asset, empty-negative, and leakage gates; all 225 corrected beer
  crops passed the 50% black-fraction gate (19.86% median, 27.54% maximum).
  Removing all 184 V1 frames containing old beer and composing the remaining
  1,976 replay frames produced a validated 2,700-image dataset (2,219 train,
  481 val) with zero old-beer replay frames.
- **Next step:** After explicit approval, fine-tune all 18 classes from V1
  `best.pt`, report overall, legacy, targeted, and negative validation results
  separately, then repeat the unchanged P1/P2 robustness audit.

### P-002 — Competition-like full-chain reliability is not established

- **Status:** BLOCKED
- **Priority:** HIGH
- **Problem:** Ten different randomized layouts with temporary obstacles,
  occlusion, and the eight-minute cap have not been completed.
- **Key evidence:** After the startup correction, the fixed-seed gate achieved
  Gazebo/Nav2 startup 5/5 but complete-task success 4/5; scores were 50, 50,
  50, 0, and 48 out of 70. Existing broader evidence covers only one seed.
- **Next step:** After P-001 passes its model gate, run the different-seed
  randomized full-chain evaluation and classify failures by navigation,
  detection, localization, deduplication, and timing stage.

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

## Deferred Problems

### P-004 — Close same-class final deduplication needs competition calibration

- **Status:** DEFERRED
- **Priority:** MEDIUM
- **Problem:** Same-frame protection for two real same-class objects closer
  than 8 cm and the 8 cm final-deduplication radius are not runtime-calibrated
  against official layouts.
- **Key evidence:** Deterministic tests and one real split-cluster merge passed,
  but no close-pair Gazebo ground-truth trial has established TP/FP behavior.
- **Next step:** After P-001 and the main randomized gate, run controlled
  close-pair layouts and score them at the official 10 cm position threshold.

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

## Next Step

Work on P-001 only: after explicit approval, train one unified 18-class model
from the completed Formal V2 dataset and re-run the unchanged robustness audit.
Do not alter
confidence 0.50, depth/TF, online or final deduplication, final confirmation,
Nav2, corner handling, FR3/MoveIt, or the candidate viewpoints as part of this
model correction.
