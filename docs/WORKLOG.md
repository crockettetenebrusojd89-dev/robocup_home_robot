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

## 2026-09-16 — Banana runtime containment and final event-week decision

### Goal

Without training or changing the formal confidence and viewpoints, test early
target whitelisting, 2x2 tiled banana inference, low-confidence banana
candidate confirmation, and at most one fixed close-range fallback. Select the
smallest defensible event-week runtime repair.

### Done

- Re-audited the judge-target path and moved the existing validated three-class
  whitelist immediately after detector decoding, before depth, TF, markers,
  and tracking. The 18-class model and final answer boundary remain unchanged.
- Replayed all 720 untouched banana external RGB frames through full-frame 640
  and four 20%-overlapping 640-input tiles, with full-frame box remapping,
  same-class merge, latency, raw FP, whitelist FP, and duplicate accounting.
- Replayed banana-only candidate thresholds 0.10, 0.15, and 0.20 with strict
  distinct-scan-frame confirmation and a conservative real-dwell FP bound.
- Selected one fixed fallback pose from table geometry and the static map,
  captured all 15 original placements at the original object yaw, and ran one
  Nav2 reachability/scan/answer-save trial. No GT selected the pose.

### Results

- Full-frame remains 2/15 and 0/9 difficult placements at 8.109 ms median.
  Tiled inference falls to 1/15 and 0/9, increases latency to 14.975 ms, and
  produces 60 irrelevant-class boxes. It is rejected.
- At thresholds 0.10/0.15, eight placements have any target candidate, seven
  reach three distinct frames, but only one reaches five and none is in the
  difficult group. All 15 placements contain background banana candidates;
  the real two-second dwell can repeat one static FP to five confirmations.
  Threshold 0.20 is weaker. No candidate threshold is adopted.
- The fallback `(-3.300, -1.800, -1.723)` is Nav2 reachable without collision.
  Its scan run completes successfully, but fallback-only recall is 2/15 and
  P1/P2 plus fallback is only 4/15 and 1/9 difficult placements. It also adds
  one `coke_can` wrong box per placement and costs an estimated 75 seconds when
  appended after P2. It is rejected.
- Only the early whitelist is retained. It removes non-target upstream work but
  does not change existing final-answer semantics or solve requested-pair
  master/tomato and coke/tomato confusion.

### Problem Updates

- P-001 remains **OPEN**, with banana and requested-pair confusion explicitly
  accepted as HIGH event risk. Epoch31 is frozen as the competition checkpoint;
  no more detector/model development is authorized.
- P-002 changes from **BLOCKED** to **OPEN**. Schedule value now favors the
  formal `/map` 10 cm, final-FP, and `answer.json` gate over further detector
  experiments.
- P-010 is **SOLVED**: non-target classes are filtered before localization and
  tracking, with focused regression coverage.
- Other problem states are unchanged.

### Next

Stop this work. In a new task, run the formal `/map` 10 cm, final-FP, and
`answer.json` gate using epoch31, confidence 0.50, unchanged P1/P2, and the
early whitelist. Do not continue automatically into the full runner or FR3.

### Git / Validation

- Branch: `work/p2-randomized-eval`; starting HEAD `2ef23326`.
- Commit: the commit containing this entry.
- Validation: 20 focused P2, 14 formal-runtime, and 9 dedup tests passed; six
  edited Python files passed style checks and four executable scripts passed
  syntax compilation; the C++ worker compiled with strict warnings; Gazebo
  fallback capture had zero render-resource errors; and one Nav2 fallback trial
  completed successfully. Full evidence is in
  `docs/BANANA_RUNTIME_REPAIR_2026-09-16.md`.

## 2026-09-16 — Final banana geometry viewpoint gate

### Goal

Test exactly one fixed distance-plus-angle candidate at
`(-2.085, -2.415, -2.691)`: require a real Nav2 safety smoke before replaying
the untouched 15-placement banana external gate, then obey the declared recall
stop rule without searching another viewpoint.

### Done

- Ran one unchanged-map/footprint Nav2 navigation and 12-step scan smoke.
- Reused the original 15 banana positions and fixed yaw with epoch31 and
  confidence 0.50. Invalid missing-resource capture evidence was rejected;
  the accepted recapture had zero missing-resource signatures.
- Compared candidate-only detections with the frozen P1/P2 baseline and kept
  all detector, navigation, localization, tracking, and dedup settings frozen.

### Results

- Nav2 planned and reached the candidate without collision, recovery, or
  oscillation in 23.00 s. The accepted goal pose error was 0.323 m and 18.7
  degrees; the observed endpoint retained about 0.53 m map clearance. The scan
  completed in 44.46 s.
- Candidate-only banana recall was 0/15 and 0/9 difficult placements. P1/new/P2
  remained 2/15 and 0/9, below both the old fallback's 4/15 and the mandatory
  stop threshold. The candidate also produced four wrong-class boxes on three
  placements: three beer and one pudding_box.
- Although nominal distance and relative viewing angle improved, the banana
  remained only about 4.6--7.6 pixels on its short side when a diagnostic
  candidate existed, and some views were partially blocked by room furniture.
  The pose does not justify its estimated roughly 53-second route-plus-scan
  cost.

### Problem Updates

- P-001 remains **OPEN** and is now an accepted competition risk with banana
  viewpoint development permanently stopped under the declared rule.
- P-002 remains **OPEN**. The next justified work is the formal `/map` 10 cm,
  final-FP, and `answer.json` gate.

### Next

Keep epoch31, confidence 0.50, and P1/P2 unchanged. Do not add the candidate or
test another viewpoint. Proceed to the Final Scoring Gate.

### Git / Validation

- Branch: `work/p2-randomized-eval`; starting HEAD `be55183b`.
- No runtime/code change and no commit. Checkpoint SHA256 remained
  `c16f5332...9564c`; one Nav2 smoke and one accepted 360-frame external
  capture completed. Evidence is under
  `~/robocup_assets/p2_eval/banana_geometry_candidate_nav_smoke_20260916` and
  `~/robocup_assets/p2_eval/v2_epoch31_banana_geometry_candidate_valid_20260916`.

## 2026-09-16 — Final P1/P2 official-scorer gate

### Goal

Measure the frozen epoch31 P1/P2 chain at the actual `answer.json` and strict
10 cm scorer boundary, including normal, dangerous requested-pair, and banana
combinations. Distinguish raw detections from final TP/FP/FN.

### Done

- Audited early whitelisting, reset ownership, confirmation/dedup settings,
  three-key answer writing, and the scorer's one-to-one `<0.10 m` contract.
- Found that the installed localizer predated the committed early whitelist;
  rebuilt only `robocup_home_robot` and verified the runtime/source hashes
  match before testing.
- Added nine reproducible legal tabletop scenarios and ran the unchanged full
  P1/scan/P2/scan/save/scorer chain once for every scenario.
- Preserved runtime telemetry, answers, GT, scorer details, raw captures, and
  offline detector evidence under
  `~/robocup_assets/p2_eval/final_scoring_gate_20260916`.

### Results

- Full runner/scorer completion was 9/9, but vision totaled 13 TP, 7 FP, and
  15 FN over 28 GT. Normal combinations scored 8/20/10, dangerous combinations
  18/16/20, and banana combinations 10/10/0 out of 30.
- Banana was 0 TP, 0 FP, 3 FN and lost all 10 class points in every layout.
  No tested dangerous pair produced a final cross-class FP near the other
  class GT; the observed extra outputs were same-object tracking splits.
- Four duplicate FPs affected apple, tomato, and coke. Three other
  correct-class outputs failed the position gate at 10.37--11.90 cm. The 13
  TPs had 0.58 cm minimum, 6.08 cm median, and 8.98 cm maximum error.
- Seven FN class instances had zero detections, five had detections/depth/TF
  but no five-observation final track, and three produced an output outside
  10 cm. Full evidence and verdict are in
  `docs/FINAL_SCORING_GATE_2026-09-16.md`.

### Problem Updates

- P-001 remains **OPEN** and frozen as accepted detector risk; the final gate
  measured banana's practical loss without reopening model work.
- P-002 remains **OPEN**: operational completion is established, but the
  0--20/30 score range rejects competition-readiness.
- P-004 changes from **DEFERRED** to **OPEN/HIGH** because tracking splits
  caused four scorer FPs and low-evidence fragmentation contributed to final
  FN. No radius or confirmation threshold changed.

### Next

Keep detector, confidence, P1/P2, navigation, TF, and RGB-D geometry frozen.
Address only P-004 with one controlled tracking-fragmentation and close-pair
safety A/B, then rerun the same official-scorer gate. Do not start broad
randomized readiness repeats or FR3 work yet.

### Git / Validation

- Branch: `work/p2-randomized-eval`; starting HEAD `be55183b`.
- Validation: 14 formal-runtime, 9 dedup, and 20 P2 tests passed; installed and
  source localizer SHA256 matched after rebuild; 9/9 Gazebo/ROS2/scorer trials
  completed successfully. Existing user edits in `README.md`, `AGENTS.md`,
  `docs/HANDOFF.md`, `docs/PROJECT_STATE.md`, `docs/PROJECT_STATUS.md`, and
  `docs/WORKLOG.md` were preserved and excluded from staging.

## 2026-09-16 — P-004 tracking-fragmentation offline audit

### Goal

Use only the saved Final Scoring Gate evidence to decompose all 15 FN, audit
the four duplicate FP, test association and final-confirmation sensitivity,
protect close same-class objects, and check simple position estimators before
changing runtime parameters.

### Done

- Classified every FN from runtime telemetry, final tracks, answers, GT, and
  official scorer details.
- Reconstructed the observable duplicate-track history from final telemetry
  and periodic track snapshots, and distinguished P1-internal scan drift from
  P1/P2 mode changes.
- Ran final-track-centroid sensitivity at 5/7/8/10 cm, exact final-confirmation
  rescoring at 5/4/3, a deterministic 10--20 cm close-pair safety case, and a
  bounded estimator audit from post-reset logged map samples.
- Audited evidence completeness before replay. No detector, Gazebo, navigation,
  training, formal parameter, or runtime code change was made.

### Results

- Of 15 FN, 11 (73.3%) lacked sufficient correct detector evidence, one (6.7%)
  had four correct observations split 2+2 below confirmation, and three (20%)
  had outputs outside 10 cm. Depth/TF caused no GT miss.
- Apple split within P1 before P2, tomato split across P1/P2, and coke split
  both within P1 and again at P2. The common mechanism is scan-angle/viewpoint
  position drift, not confidence or TF failure.
- Final confirmation 4 was identical to 5. Threshold 3 added two scorer FP and
  reduced the aggregate score from 112 to 108/270.
- The 7/8/10 cm centroid sensitivity did not remove the four duplicate FP. A
  10 cm radius showed one unsupported boundary-localization gain, but 7/8/10
  cm incorrectly merged 10--12 cm same-class objects under 2 cm jitter.
- The corpus lacks ordered per-observation map positions and association
  decisions, so a frame-exact online-radius replay and full estimator A/B
  cannot be honestly computed. Full results are in
  `docs/TRACKING_FRAGMENTATION_OFFLINE_AUDIT_2026-09-16.md`.

### Problem Updates

- P-004 remains **OPEN/HIGH**. Its duplicate mechanism is confirmed, but the
  requested global-radius and confirmation changes are rejected by score and
  close-pair safety evidence.
- P-001 and P-002 remain **OPEN**. The FN decomposition shows detector recall
  and localization margin dominate recoverable score more than final
  confirmation tuning.

### Next

Keep online association 5 cm, final confirmations 5, and final dedup 8 cm.
Before another A/B, add bounded observational-only retention and deterministic
ordered replay, then collect an unchanged replayable corpus. Do not rerun the
nine Gazebo scenarios until a safe candidate exists.

### Git / Validation

- Branch: `work/p2-randomized-eval`; HEAD `1b90b24`; remote divergence 0/0
  after fetch.
- Validation used all nine telemetry/GT/answer/scorer bundles, exact scorer
  recomputation for final-confirmation 5/4/3, final-centroid sensitivity for
  5/7/8/10 cm, deterministic close-pair sequences at 10/12/15/20 cm, and 16
  output-bearing GT groups from throttled localization logs. No commit.

## 2026-09-16 — Detector-FN low-confidence audit

### Goal

Determine whether the 11 detector-evidence FN contain enough correct-class
signal below confidence 0.50 to justify a conservative tabletop-only rescue,
without changing the frozen runtime.

### Done

- Audited every detector FN by scenario, class, GT, P1/P2 visibility,
  candidate frames, confidence distribution, threshold counts, and strongest
  bbox.
- Added observational-only aligned depth retention and offline localization of
  every requested-class diagnostic box; formal inference and answers are
  untouched.
- Replayed only banana/coke/bowl and master/tomato/apple, covering an ordinary
  FN, banana, a dangerous pair, and stable controls.
- Added a reproducible fixed-table ROI counterfactual for thresholds
  .10/.15/.20/.30 and 2/3/5 distinct-frame confirmations.

### Results

- The 11 FN classify as A=4 strong, B=1 weak, C=6 absent/non-actionable, D=0.
- Depth coverage was 283/287 and 298/298 runtime frames in the two replays.
- Banana at .10/.15 yielded 1 TP plus 3 FP; bowl and master yielded no TP;
  tomato could add one isolated TP in its single replay. No policy met the
  required +4--5 TP with few or no FP.
- The rescue path is rejected and confidence remains 0.50. Full evidence is
  in `docs/LOW_CONFIDENCE_DETECTOR_FN_AUDIT_2026-09-16.md`.

### Next

Keep the detector and decision path frozen. Preserve the diagnostic tooling,
then return to P-004's ordered tracking-observation retention and replay gap.
Do not rerun all nine scenes without a supported runtime candidate.

### Git / Validation

- Branch `work/p2-randomized-eval`, starting HEAD `1b90b24`, remote divergence
  0/0 before this task.
- 25 P2 evaluator tests pass, the package rebuild passes, both representative
  full-chain runs complete, and `git diff --check` passes.

## 2026-09-16 — Current-state documentation synchronization

### Goal

Synchronize the concise project status with the completed Final Scoring Gate,
tracking-fragmentation audit, low-confidence detector-FN audit, and stopped
banana work, without changing runtime behavior or creating new technical work.

### Done

- Reconciled `docs/PROJECT_STATUS.md` against the three evidence reports.
- Recorded the complete frozen runtime configuration and separated it from all
  tested-but-rejected detector, viewpoint, rescue, and tracking alternatives.
- Preserved the existing historical worklog entries and the user's local
  README, HANDOFF, PROJECT_STATE, and AGENTS changes.

### Results

- The Final Scoring Gate record is 9/9 complete runner executions, 28 GT,
  13 TP, 7 FP, 15 FN, and 112/270 visual points, averaging 12.44/30. The
  measured base-task center with 40 navigation points is about 52/70.
- Localization for the 13 TP is 0.58 cm minimum, 6.08 cm median, and 8.98 cm
  maximum; three other correct-class outputs at 10.37, 11.11, and 11.90 cm
  each became FP+FN.
- FN decomposition remains 11 detector-evidence, 0 depth/TF, 1
  tracking/confirmation, 3 localization, and 0 final-filter/dedup. Duplicate FP
  remain apple 1, tomato 1, and coke 2.
- The low-confidence audit remains A=4, B=1, C=6, D=0. Banana at 0.10/0.15
  added at most 1 TP with 3 FP; bowl and master candidates were about 15.1 cm
  and 25.3 cm from GT; tomato added at most one limited TP.
- Banana V2.1, image size 960, tiled inference, low-confidence rescue, old
  fallback viewpoint, and new geometry viewpoint were all rejected. The new
  viewpoint remained 0/15 alone and P1/new/P2 remained 2/15, with 0/9 problem
  scenarios and about 53 seconds estimated added time.

### Problem Updates

- P-001 remains **OPEN/CRITICAL** with detector and banana development stopped.
- P-002 remains **OPEN/HIGH**; the 9/9 gate is recorded full-runner evidence,
  not completion of the broader randomized-layout requirement.
- P-004 remains **OPEN/HIGH**, but tracking is not the main FN source and no
  safe parameter or position-estimator change was validated.

### Next

No new action, experiment, parameter change, or project plan was established
by this documentation-only synchronization.

### Git / Validation

- Branch: `work/p2-randomized-eval`; starting HEAD `ac4e68b`; remote divergence
  was 0/0 after `git fetch --all --prune`.
- Documentation-only diff review; no code, model, configuration, or new Gazebo
  experiment was involved.

## 2026-09-16 — RGB-D tabletop object proposal POC

### Goal

Determine, without YOLO or object-position input, whether fixed tabletop
geometry plus saved RGB-D can form stable 3-D object proposals that justify a
future crop-classification design.

### Done

- Audited the four eligible living-room table polygons, current RGB-D/TF path,
  and replay evidence; added a standalone offline replayer and focused tests.
- Replayed two depth/TF-complete audit runs over eight fixed rotation frames at
  each P1/P2 viewpoint. GT was used only for post-hoc one-to-one scoring.

### Results

- Stable proposal recall was 0/6; frame recall was 10/192 and there were six
  false proposals. Banana matched only 2/16 frames and was not stable.
- The fixed rule is therefore FAIL. No close-pair expansion, crop inference,
  classifier, runtime edit, model training, or formal parameter change was run.
  Full evidence is in `docs/TABLETOP_RGBD_PROPOSAL_POC_2026-09-16.md`.

### Problem Updates

- P-011 is **SOLVED** with verdict **FAIL**: the proposed bypass does not meet
  its stable-recall or banana gate. P-001, P-002, and P-004 are unchanged.

### Next

Stop this route. Preserve the frozen formal runtime; do not integrate tabletop
proposals or continue into crop inference without new authorization.

### Git / Validation

- Branch: `work/p2-randomized-eval`; starting and remote HEAD `fa3107b`.
- Validation: standalone Python syntax check, two focused POC tests, offline
  replay of two saved depth/TF corpora, and `git diff --check`.
