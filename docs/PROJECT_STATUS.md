# Project Status

## Last Updated

2026-09-15

## Current Stage

P2 robustness work for the 70-point autonomous navigation and visual counting
task. One Formal Model V2 fine-tune and synthetic candidate selection are
complete; the unchanged competition-domain Gazebo gate is now the critical
next decision.

## Current Goal

Run the selected epoch-31 Formal Model V2 candidate through the unchanged P1/P2
Gazebo external gate, using the epoch-40 best checkpoint only as a backup and
without tuning the frozen competition runtime parameters.

## Open Problems

### P-001 — Unified detector is not robust across all official classes

- **Status:** OPEN
- **Priority:** CRITICAL
- **Problem:** The current checkpoint is unreliable for corrected beer,
  banana, and master_chef_can; three additional classes are borderline.
- **Key evidence:** The competition-like audit remains banana 2/15, corrected
  beer 0/15, and master_chef_can 8/15 for V1. One 40-epoch V2 fine-tune from V1
  completed on the validated 2,700-image dataset. The selected epoch-31
  checkpoint has targeted recalls .973/1.000/1.000 for banana/beer/master,
  1.000/.979/.949 for coke/pudding/tomato, targeted mAP50-95 .908, and zero
  detections on 10/10 negatives at confidence 0.50. Its stable-12 legacy macro
  recall/mAP50/mAP50-95 are .987/.989/.954 versus V1 .979/.987/.931, with no
  per-class decrease beyond 2 percentage points. Evidence and hashes are in
  `docs/FORMAL_MODEL_V2_TRAINING_2026-09-15.md`.
- **Next step:** Run
  `formal_objects_v2_yolo11n_finetune/weights/epoch30.pt` (human epoch 31,
  SHA256 `c16f5332...564c`) through the frozen P1/P2 external gate first. Use
  epoch-40 `best.pt` only if the main result is ambiguous or fails; do not
  retrain from `yolo11n.pt` automatically.

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

Work on P-001 only: run the selected epoch-31 V2 candidate through the
unchanged confidence-0.50 P1/P2 robustness audit. Do not alter
confidence 0.50, depth/TF, online or final deduplication, final confirmation,
Nav2, corner handling, FR3/MoveIt, or the candidate viewpoints as part of this
model correction.
