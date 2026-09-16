# Worklog

Append new substantive-work entries at the end. Keep entries concise and
evidence-driven; detailed procedures belong in the relevant runbook or
experiment document.

## 2026-09-15 — Project workflow infrastructure

### Goal

Establish a discoverable repository workflow Skill and concise, evidence-driven
project status records without changing robot runtime behavior.

### Done

- Installed `robocup-project-workflow` in the Codex user Skill directory.
- Added the repo-level invocation rule and the authoritative project-status and
  append-only worklog files.
- Marked the previous project-state and handoff documents as frozen historical
  snapshots and updated README links.

### Results

- The official `skill-creator` validator reported `Skill is valid!`.
- Required status sections, stable Problem IDs, allowed states, and the repo
  invocation rule were found by focused checks.
- Git whitespace validation passed; no ROS2, Nav2, YOLO, model, or runtime file
  was changed.

### Problem Updates

- P-001 through P-008 were initialized from existing verified repository
  evidence. No robot-runtime problem changed state in this documentation-only
  task.

### Next

Use `$robocup-project-workflow` for the next substantive task and work on
P-001 only: targeted data correction, unified retraining, and unchanged
robustness re-audit.

### Git / Validation

- Branch: `work/p2-randomized-eval`
- Commit: none created; starting HEAD `92d16cb`
- Validation: official Skill quick validation passed; `git diff --check`
  passed; runtime tests not run because only workflow documentation changed.

## 2026-09-15 — Formal Model V2 auditable data pipeline

### Goal

Address P-001 at the data layer only: replace the invalid beer rendering domain,
add controlled hard-sample generation, prove the pipeline on a small smoke, and
stop before full generation or training.

### Done

- Added an isolated, hash-pinned V2 asset preparation path and installed the
  teacher's corrected PBR beer under
  `~/robocup_assets/official_models_v2` without changing V1 assets.
- Added deterministic per-class distance, yaw, placement, background, lighting,
  secondary-object, negative-sample, and split policies plus a per-image
  scenario manifest.
- Added V2 validation for asset identity, exact quotas, boxes, declared empty
  labels, beer visual anomalies, and four train/val leakage signatures.
- Added a 45-image smoke configuration and a reviewed but unexecuted 724-image
  formal targeted-supplement configuration.

### Results

- Smoke completed 45/45 captures: 30 train, 15 val, 39 positive, and 6 empty
  negatives. All configured per-class and domain quotas passed.
- Scene-group, exact-image, exact background/light-combination, and perceptual
  near-duplicate train/val overlap were all zero.
- Corrected beer was visibly textured in manual previews; across 12 primary
  boxes its near-black fraction was 22.12% median and 26.71% maximum, compared
  with 95.4% median in invalid V1 evidence. The formal plan rejects any beer
  crop whose near-black fraction exceeds 50%.
- V1 audit found 151 train and 33 val images containing old beer. Whole-image
  removal leaves 1,649 train and 327 val replay images. Adding the frozen
  570/154 targeted plan yields exactly 2,700 images after later composition.
- No full dataset generation, training, runtime parameter change, or merge to
  `main` was performed.

### Problem Updates

- P-001 remains **OPEN**. The V2 generator/validator and asset correction are
  proven at smoke scale; full targeted generation, clean replay composition,
  unified training, and the unchanged external robustness gate remain.
- P-002 through P-008 are unchanged.

### Next

After explicit approval, generate the 724-image targeted supplement, compose it
with all 1,976 clean V1 replay images, validate the unified dataset, then
fine-tune all layers from the V1 checkpoint and re-run the frozen P1/P2 gate at
confidence 0.50.

### Git / Validation

- Branch: `work/p2-randomized-eval`
- Implementation commit: `18facd1`
- Validation: V2 validator passed on the real smoke; 53 focused repository
  tests passed (11 dataset, 9 dedup, 14 P2, 6 world-loader, 13 runtime);
  C++ worker compiled with warnings enabled; `git diff --check` passed.

## 2026-09-15 — Formal Model V2 dataset completion

### Goal

Generate and validate the reviewed 724-image targeted supplement, remove every
V1 frame containing invalid old beer, compose the final unified dataset, and
stop before training.

### Done

- Completed 570 train and 154 val targeted captures with the corrected PBR beer,
  frozen per-class quotas, 40 negatives, manifests, previews, and asset hashes.
- Added a primary sight-corridor guard after a deterministic secondary-object
  occlusion stopped the first run at train sample 260; retained that partial run
  as failure evidence and added regression coverage for the exact geometry.
- Added an atomic dataset composer that removes whole old-beer image/label pairs,
  hard-links retained source bytes under collision-proof names, and records
  provenance and separate legacy, targeted-positive, and negative val lists.
- Extended the validator for the fixed composition contract, source hashes,
  old-beer exclusion, validation partitions, filename collisions, targeted
  quotas, and annotation-aware perceptual leakage.

### Results

- Targeted validation passed all 724 frames: zero scene-group, exact-image,
  exact background/light, or annotation-aware perceptual leakage. Corrected
  beer black-fraction was 19.86% median and 27.54% maximum across 225 boxes,
  with zero violations of the 50% gate.
- Removed 151 train and 33 val V1 frames containing old beer as whole pairs.
  The 1,649/327 clean replay plus 570/154 targeted frames produced exactly
  2,219 train and 481 val images; all 2,700 output images remain hard-linked to
  their recorded sources and old beer occurs in zero replay frames.
- Manual previews passed for beer distance/light/yaw, hard banana,
  master_chef_can, far borderline classes, and empty/background negatives.
  Ultralytics accepted the final 18-class `data.yaml` without training.

### Problem Updates

- P-001 remains **OPEN**. Its data-layer blocker is resolved, but unified model
  training and the frozen external P1/P2 robustness gate are still required.
- P-002 through P-008 are unchanged. No runtime, navigation, viewpoint,
  confidence, localization, or deduplication setting changed.

### Next

Wait for explicit approval. Then fine-tune one unified 18-class model from V1
`best.pt`, report overall and source-partitioned validation, and repeat the
unchanged confidence-0.50 P1/P2 audit. Do not start training automatically.

### Git / Validation

- Branch: `work/p2-randomized-eval`
- Implementation commit: `41d15a6`
- Validation: both real dataset validators passed; 55 focused repository tests
  passed (13 dataset, 9 dedup, 14 P2, 6 world-loader, 13 runtime); four edited
  Python files passed `ament_flake8` and syntax compilation; `git diff --check`
  passed.

## 2026-09-15 — Formal Model V2 fine-tune and candidate selection

### Goal

Address the synthetic-training portion of P-001 with one conservative V2
fine-tune, partitioned validation, and one main plus at most one backup
checkpoint; stop before the competition-domain Gazebo gate.

### Done

- Audited the existing CUDA training environment, V1 checkpoint identity and
  18-class order, final V2 composition, disk capacity, and GPU memory.
- Added explicit fine-tune controls and structured provenance to the existing
  trainer, plus a symlink-only data view that prevents loader cache writes to
  the composed source dataset.
- Added and regression-tested a minimal evaluator for overall, legacy,
  targeted-positive, and confidence-0.50 negative subsets.
- Passed one 1-epoch smoke and then completed the only formal 40-epoch AdamW
  fine-tune from V1. Evaluated V1 and human epochs 21, 31, 36, and 40.

### Results

- Formal training completed 40/40 epochs in 639.06 seconds without OOM; best
  was epoch 40. Train and validation losses declined together, with no obvious
  synthetic overfit signal.
- Human epoch 31 was selected over the default best: targeted weak-class
  recalls were .973/1.000/1.000 for banana/beer/master, all three borderline
  recalls were at least .949, targeted mAP50-95 was .908, and 10/10 negatives
  had zero detections at confidence 0.50.
- Stable-12 legacy macro recall/mAP50/mAP50-95 improved from
  .979/.987/.931 (V1) to .987/.989/.954; no stable per-class metric crossed the
  -2 percentage-point regression line.
- Main SHA256 is `c16f5332...564c` (`epoch30.pt`, human epoch 31). Epoch-40
  `best.pt`, SHA256 `0aa4fc50...906a`, is the only backup. Full evidence is in
  `docs/FORMAL_MODEL_V2_TRAINING_2026-09-15.md` and the external corrected
  evaluation tree recorded there.

### Problem Updates

- P-001 remains **OPEN**. Synthetic model evidence is strong enough to advance,
  but the unchanged P1/P2 competition-domain gate must confirm V2 can replace
  V1.
- P-002 through P-008 are unchanged. No runtime, confidence, navigation,
  viewpoint, localization, deduplication, FR3, or MoveIt setting changed.

### Next

Run the epoch-31 main candidate through the frozen P1/P2 external gate. Use the
epoch-40 backup only if needed. Do not start a second training run.

### Git / Validation

- Branch: `work/p2-randomized-eval`
- Commit: the commit containing this entry; starting HEAD `604bf75`
- Validation: final V2 validator passed; 17 focused dataset/evaluator tests
  passed; three training/evaluation scripts passed syntax compilation; four
  edited Python files passed `ament_flake8`; `git diff --check` passed. One
  initial subset report exposed and preserved an mAP50-95 class-index bug; the
  corrected implementation has a missing-class regression test and all five
  checkpoint reports were regenerated.

## 2026-09-16 — Formal Model V2 competition-domain external detector gate

### Goal

Decide whether human epoch 31 can replace V1 and be frozen, using the fixed
confidence-0.50 P1/P2 spatial, lighting, stable-class, and FP gates. Stop
before runtime integration or any further training.

### Done

- Verified branch, remote, candidate/backup hashes, frozen viewpoints, and the
  targeted aggregate definition.
- Added checkpoint-preserving capture reuse, full wrong-class/duplicate
  evidence, a 48-trial four-profile lighting gate, and fail-closed Gazebo
  render-resource validation.
- Ran all required main-candidate spatial, lighting, and stable gates plus the
  permitted banana-only epoch40 A/B. Repeated invalid older 18-class captures
  with complete resources after manual review found missing table meshes.

### Results

- Epoch31 spatial results were banana 2/15, beer 15/15, master 15/15, coke
  15/15, pudding 15/15, and tomato 15/15. Banana remained equal to its V1
  baseline; beer and master improved strongly.
- Lighting correct-target detection was 12/12 for banana, beer, master, and
  coke with no confidence collapse, but background FP signatures were
  profile-dependent and master target confusion persisted.
- Stable-12 was 5/5 except tuna 4/5. Epoch40 improved banana only to 4/15 and
  also failed. Epoch31 therefore failed the external detector gate and is not
  approved for replacement or freeze.

### Problem Updates

- P-001 remains **OPEN**: systematic banana misses and wrong-class FP behavior
  block detector freeze and downstream integration.
- P-009 is **SOLVED**: incomplete render-resource scenes now fail closed and
  all verdict evidence uses fresh zero-error Gazebo captures.
- P-002 through P-008 are otherwise unchanged.

### Next

Stop this work. Before downstream integration, authorize and define one bounded
competition-domain correction for banana and cross-class/background FP, then
rerun the identical gate. Do not start a blind V3, broad checkpoint sweep, or
unrelated runtime work.

### Git / Validation

- Branch: `work/p2-randomized-eval`; starting HEAD `d004b99`.
- Commit: the commit containing this entry.
- Validation: 17 focused P2 tests passed; four edited Python files passed
  `ament_flake8`; `git diff --check` passed; all accepted Gazebo evidence logs
  had zero missing-resource/geometry errors. Full evidence is in
  `docs/FORMAL_MODEL_V2_EXTERNAL_GATE_2026-09-16.md`.

## 2026-09-16 — Competition-domain low-cost audit and V2.1 repair

### Goal

Use the preserved external Gate evidence to test target-whitelist containment,
overlap suppression, and higher banana inference resolution before permitting
exactly one bounded V2.1 repair fine-tune. Keep P1/P2, confidence 0.50, and all
navigation/localization/deduplication settings unchanged.

### Done

- Audited the judge-target data path. All 18 classes currently reach
  localization and tracking, while the final answer snapshot admits only the
  three requested classes.
- Enumerated every possible three-target whitelist over the untouched epoch31
  spatial evidence and replayed current, class-agnostic, and IoU-0.50
  cross-class suppression on the same RGB frames.
- Replayed the same 15 banana placements at image sizes 640 and 960 with
  per-stage latency measurement. Stopped without 1280 when 960 remained below
  the prescribed decision threshold.
- Generated and validated an independent 465-image V2.1 supplement containing
  banana hard positives, master/coke/tomato confusion positives, competition
  room hard negatives, and tuna corner/yaw positives. The original external
  Gate remained untouched and had zero exact, pose/yaw, or scene-group overlap.
- Performed the only authorized short V2.1 fine-tune from epoch31, then replayed
  untouched banana, coke, master, beer, and lighting evidence.

### Results

- The original evidence has 74 target-overlap wrong-class boxes on 48/150
  placements. Across 816 three-target sets, the whitelist changes median wrong
  boxes from 8 to 0 and the 90th percentile from 31 to 4. The worst set,
  `coke_can + master_chef_can + tomato_soup_can`, still retains 38 boxes.
- Class-agnostic NMS and IoU-0.50 cross-class suppression both change 136/150
  TP placements and 74 wrong boxes to 135/150 and 73. Both lose the only
  correct box at `master_chef_can_03`; neither is recommended.
- Banana is 2/15 at 640 and 3/15 at 960, with the difficult-yaw group 0/9 at
  both sizes. Median wall latency rises from 7.772 to 8.869 ms, and 960 adds 15
  fixed-background pudding FPs. Higher resolution is rejected.
- V2.1 training used 10 epochs, batch 8, image size 640, AdamW, `lr0=0.0002`,
  seed 0, deterministic full-layer fine-tuning. Its checkpoint SHA256 is
  `eeb638f4...3e90`.
- V2.1 still scores banana 2/15 and difficult yaw 0/9. Master wrong boxes fall
  27 to 8 and lighting wrong boxes 91 to 29, but beer regresses from zero to
  eight target-overlap wrong boxes on seven placements. V2.1 is rejected;
  epoch31 remains the least-bad fallback but is not approved or frozen.

### Problem Updates

- P-001 remains **OPEN**. Neither inference-only repair nor the one permitted
  V2.1 run closes the competition-domain detector gate.
- P-002 remains **BLOCKED**. The formal `/map` 10 cm, final-FP, and full-runner
  gate must not be reported as ready while the detector remains unfrozen.
- P-003 through P-009 are unchanged. No P1/P2, confidence, Nav2, AMCL, TF,
  RGB-D, localization, deduplication, corner, FR3, or MoveIt setting changed.

### Next

Stop model work and do not train or sweep again. Keep epoch31, reject V2.1,
and treat banana plus requested-pair master/tomato and coke/tomato confusion as
explicit competition risk. An early three-target whitelist is the only
evidenced runtime containment candidate, but it requires separate authorization
and cannot recover missed banana detections.

### Git / Validation

- Branch: `work/p2-randomized-eval`; starting HEAD `8934c718`.
- Commit: the commit containing this entry.
- Validation: V2.1 validator passed with 372 train and 93 val images and zero
  leakage; 18 focused P2 and 18 formal-dataset tests passed; seven edited
  Python files passed `ament_flake8`, and the five executable scripts passed
  syntax compilation; the edited C++ capture worker compiled with
  `-Wall -Wextra -Wpedantic`; `git diff --check` passed. Full evidence is in
  `docs/FORMAL_MODEL_V2_1_REPAIR_2026-09-16.md`.
