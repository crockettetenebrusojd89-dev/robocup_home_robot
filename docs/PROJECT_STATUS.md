# Project Status

## Last Updated

2026-09-16

## Current Stage

P2 robustness work for the 70-point autonomous navigation and visual counting
task. The low-cost inference/post-processing audit and the only authorized
V2.1 repair fine-tune are complete. Both failed to close the external detector
gate, so detector replacement and freeze remain blocked.

## Current Goal

Preserve epoch31 as the least-bad current checkpoint and V2.1 as rejected
evidence. Do not run another model training or sweep. Treat banana and the
master/tomato and coke/tomato requested-pair confusions as explicit competition
blockers while deciding the narrowest event-week containment action.

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
  `docs/FORMAL_MODEL_V2_1_REPAIR_2026-09-16.md`.
- **Next step:** Keep epoch31 rather than V2.1, but do not freeze the detector
  or claim readiness for the formal `/map` 10 cm/final-FP/full-runner gate.
  No further training is authorized. If a runtime change is separately
  authorized, move the existing three-target whitelist before depth/tracking;
  this contains irrelevant-class FPs but cannot repair requested-pair
  confusion or missed banana detections.

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

Stop this completed repair work. P-001 remains OPEN after the low-cost audit
and the only authorized V2.1 run. Retain epoch31 as the least-bad fallback,
reject V2.1, and do not start another training run, checkpoint sweep, or formal
downstream gate. The only evidenced runtime containment candidate is an early
three-target whitelist; it requires separate authorization and does not solve
banana or requested-pair confusion.
