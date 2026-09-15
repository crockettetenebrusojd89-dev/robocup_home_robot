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
