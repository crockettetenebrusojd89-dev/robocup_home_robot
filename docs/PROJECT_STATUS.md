# Project Status

## Last Updated

2026-09-16

## Current Stage

P2 robustness work for the 70-point autonomous navigation and visual counting
task. The Formal Model V2 competition-domain external detector gate is
complete and failed; detector replacement and freeze remain blocked on
systematic banana misses and wrong-class FP behavior.

## Current Goal

Keep P-001 scoped to the smallest competition-domain correction for banana and
cross-class/background detector FPs. Do not start runtime integration, 3D
localization, deduplication tuning, a broad checkpoint sweep, or unrelated
competition work until the detector gate is rerun.

## Open Problems

### P-001 — Unified detector is not robust across all official classes

- **Status:** OPEN
- **Priority:** CRITICAL
- **Problem:** The selected V2 checkpoint is still unreliable for banana and
  produces systematic target-confusion and lighting-dependent background FPs.
- **Key evidence:** At confidence 0.50 and frozen P1/P2, epoch31 achieved
  banana 2/15, corrected beer 15/15, master_chef_can 15/15, and all three
  borderline classes 15/15. Stable classes were 5/5 except tuna_fish_can 4/5.
  All four lighting focus classes were 12/12 with no confidence collapse, but
  every lighting trial had a repeatable background wrong-class box and master
  had target-overlap confusion in 8/12 trials. Epoch40 reached only banana
  4/15 in the identical A/B. Full evidence is in
  `docs/FORMAL_MODEL_V2_EXTERNAL_GATE_2026-09-16.md`.
- **Next step:** Do not freeze or integrate either V2 checkpoint. Use the
  preserved competition-domain failures to define one bounded banana and
  wrong-class-FP correction, then rerun the identical spatial, lighting, and
  stable gates without changing confidence or viewpoints.

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

## Next Step

Stop this completed gate work. P-001 remains the only next model task: plan one
bounded competition-domain correction for the systematic banana and FP
failures, then rerun the same confidence-0.50 P1/P2 and lighting evidence. Do
not start V2 runtime integration, depth/TF, deduplication, Nav2, FR3/MoveIt, or
a broad retraining/checkpoint sweep before that decision.
