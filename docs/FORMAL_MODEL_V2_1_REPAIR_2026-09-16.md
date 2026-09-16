# Formal Model V2.1 Competition-Domain Repair Audit

Date: 2026-09-16

Branch: `work/p2-randomized-eval`

Starting HEAD: `8934c71858dd1e85944d31c6b7d0d4946bdd7de8`

Frozen confidence: `0.50`

Frozen viewpoints: P1 `(-3.485, -1.115, -0.532)`, P2
`(0.265, -0.665, -2.638)`

## Verdict

The low-cost inference and post-processing candidates do not repair the
competition-domain failure. The one permitted V2.1 repair fine-tune also does
not repair banana and introduces a beer wrong-class regression. Keep the
epoch-31 V2 checkpoint as the least-bad current checkpoint, but do not approve
or freeze the detector and do not advance to the formal `/map` 10 cm, final-FP,
or full-runner gate as if P-001 were solved.

Recommended current checkpoint:

```text
/home/hao/robocup_assets/training_runs/formal_objects_v2_yolo11n_finetune/weights/epoch30.pt
SHA256 c16f5332221649fdb89c225f9aaec6f73db97e2590bc37734a6d0e0a5099564c
```

The V2.1 candidate is retained only as negative experiment evidence:

```text
/home/hao/robocup_assets/training_runs/formal_objects_v2_1_repair_20260916/weights/best.pt
SHA256 eeb638f42be5026229998cd9757854df1948fd9e0999626ba9efe4b1cac13e90
```

## A. Target whitelist audit

### Runtime path

1. Judge target strings enter `launch/formal_base_task.launch.py` through
   `resolve_target_classes()` and are passed as `target_classes` to both the
   RGB-D localizer and the formal runner.
2. `scripts/rgbd_object_localizer.py` loads `target_classes`, but
   `_extract_detections()` currently filters only by confidence. All 18-class
   detections can therefore continue through depth, TF, localization, and
   `_update_clusters()`.
3. `_make_answer_snapshot()` creates only the three requested output keys and
   includes only clusters whose class is in that target set. Non-target classes
   cannot enter `answer.json`; they can still consume upstream tracking work.
4. A wrong prediction remains dangerous when its predicted class and the real
   object's class are both among the three judge targets.

### Offline 3-class enumeration

The original epoch-31 spatial evidence contains 150 placements and 74
wrong-class boxes, all target-overlap boxes, on 48 placements. Enumerating all
816 possible three-class target sets gives:

| Metric | Raw selected-object wrong boxes | After target whitelist |
|---|---:|---:|
| Minimum | 0 | 0 |
| Median | 8 | 0 |
| 90th percentile | 31 | 4 |
| Maximum | 46 | 38 |
| Mean | 12.33 | 1.45 |

The worst target set is `coke_can + master_chef_can + tomato_soup_can`: 43
raw selected-object wrong boxes and 38 surviving boxes. The important
per-object confusions are:

- `master_chef_can`: 27 wrong boxes: 23 `tomato_soup_can`, 3 `sugar_box`,
  and 1 `pudding_box`. The 23 tomato errors survive whenever tomato is also a
  requested target.
- `coke_can`: 14 wrong boxes, all `tomato_soup_can`; all survive when tomato
  is requested.
- `pudding_box`: 2 wrong boxes (`potted_meat_can`, `tomato_soup_can`).
- `tomato_soup_can`: 2 wrong boxes (`sugar_box`, `master_chef_can`).

Conclusion: the whitelist is required competition containment and should be
placed before depth/tracking in a separately authorized runtime change, while
the existing answer boundary must remain. It removes most irrelevant-class
FPs but cannot solve master/tomato or coke/tomato target-pair confusion. No
formal runtime was changed in this work.

## B. Overlap suppression / NMS A/B

The same saved external RGB evidence was replayed with current class-aware NMS,
Ultralytics class-agnostic NMS, and a simple IoU 0.50 cross-class rule that
keeps the higher-confidence box.

| Method | TP placements | Correct associated boxes | Wrong-class boxes | Wrong-class placements |
|---|---:|---:|---:|---:|
| Current NMS | 136/150 | 432 | 74 | 48 |
| Class-agnostic NMS | 135/150 | 429 | 73 | 47 |
| Cross-class IoU 0.50 | 135/150 | 429 | 73 | 47 |

Both alternatives removed only one wrong box and also removed the only correct
box at `master_chef_can_03`, changing master recall from 15/15 to 14/15. The
higher-confidence sugar/tomato wrong boxes at that placement survived. Coke's
14 wrong boxes and master's 27 wrong boxes were otherwise unchanged.

Multi-object safety was screened on all 177 two-object Formal V2 held-out
validation frames (354 ground-truth objects):

| Method | GT objects detected | Frames retaining both objects | Output boxes |
|---|---:|---:|---:|
| Current NMS | 343/354 | 166/177 | 353 |
| Class-agnostic NMS | 343/354 | 166/177 | 351 |
| Cross-class IoU 0.50 | 343/354 | 166/177 | 351 |

The synthetic adjacent-object screen shows no extra object-level loss, but the
external competition-domain replay loses a real master TP for negligible FP
benefit. Neither suppression variant is recommended.

Replay summaries are preserved under:

```text
/home/hao/robocup_assets/p2_eval/v2_epoch31_repair_audit_nms_agnostic_*_20260916
/home/hao/robocup_assets/p2_eval/v2_epoch31_repair_audit_overlap050_*_20260916
```

## C. Banana inference-resolution A/B

The identical 720 saved RGB frames covering the 15 banana placements were
replayed with epoch31 and confidence 0.50.

| Image size | Success | Problem-yaw group | Position-max confidence min / median / max | Median preprocess / inference / post / wall latency |
|---|---:|---:|---|---|
| 640 | 2/15 | 0/9 | .0025 / .1583 / .5478 | .531 / 3.822 / .776 / 7.772 ms |
| 960 | 3/15 | 0/9 | .0332 / .0836 / .7243 | 1.639 / 4.044 / .803 / 8.869 ms |

At 960, the audit also produced 15 fixed-background `pudding_box` wrong boxes,
one per placement. Because success remained only 3/15 and the systematic
problem-yaw group remained 0/9, the prescribed stop rule was reached and 1280
was not tested. Higher resolution is not recommended.

Evidence:

```text
/home/hao/robocup_assets/p2_eval/v2_epoch31_repair_audit_banana_640_20260916
/home/hao/robocup_assets/p2_eval/v2_epoch31_repair_audit_banana_960_20260916
```

## D. Decision gate

Whitelist containment is valuable, but it does not remove cross-confusion when
both classes are requested. NMS/overlap suppression loses a master TP for one
wrong-box improvement. Resolution 960 reaches only 3/15 banana and leaves all
nine difficult placements undetected. Low-cost repair is therefore
insufficient, and the single authorized V2.1 repair fine-tune was performed.

## E. V2.1 repair

### Dataset

The independent supplement is stored at:

```text
/home/hao/robocup_assets/datasets/formal_objects_v2_1_repair_20260916
```

| Content | Train | Val | Total |
|---|---:|---:|---:|
| Banana hard positives | 140 | 35 | 175 |
| Master/coke/tomato confusion positives | 120 | 30 | 150 |
| Competition-room hard negatives | 80 | 20 | 100 |
| Tuna corner/yaw positives | 32 | 8 | 40 |
| Beer supplement | 0 | 0 | 0 |
| Total | 372 | 93 | 465 |

Banana samples cover 1.9--2.6 m, yaw 270--330 degrees with emphasis on
285--305 degrees, edge/corner placements, and 5--18 px short-side targets.
The generator used new seeds, exact positions, yaws, and scene groups. The
validator confirmed zero train/val scene-group leakage, zero exact leakage
against V2, zero exact or pose/yaw overlap against the untouched external Gate,
valid class mapping, empty negative labels, valid asset hashes, and zero beer
supplement instances. It scanned 5,472 original Gate PNGs and found zero exact
image overlap.

### Training

Exactly one formal repair run was made, starting from epoch31 rather than V1
or an original pretrained model:

- 10 epochs, batch 8, image size 640, full-layer AdamW fine-tune;
- `lr0=0.0002`, `lrf=0.2`, weight decay 0.0005, one warmup epoch, cosine LR;
- seed 0, deterministic, no flips, no multiscale;
- mild HSV, translate 0.05, scale 0.15, mosaic 0.2, close mosaic at epoch 3.

Training completed in 200.7 seconds. The V2.1 hard validation had banana 35/35,
coke 10/10, tuna 8/8, master recall .818, tomato recall .800, and zero
detections on 20/20 negative images. Original V2 validation showed no
catastrophic stable-12 regression, but synthetic results were not used as the
final verdict.

### Untouched external replay

| Class / gate | Epoch31 | V2.1 | Verdict |
|---|---:|---:|---|
| Banana spatial | 2/15, problem yaw 0/9 | 2/15, problem yaw 0/9 | No repair |
| Master spatial | 15/15, 27 wrong boxes | 15/15, 8 wrong boxes | Improved FP |
| Coke spatial | 15/15, 14 wrong boxes | 15/15, 13 wrong boxes | Negligible change |
| Beer spatial | 15/15, 0 wrong boxes | 15/15, 8 wrong boxes on 7 placements | Regression |

The V2.1 lighting spot-check kept banana, beer, master, and coke at 12/12 in
each of four profiles. Aggregate wrong boxes fell from 91 to 29, so the hard
negatives helped lighting backgrounds. This benefit does not outweigh unchanged
banana failure and newly polluted beer spatial evidence. V2.1 is rejected.

Evidence:

```text
/home/hao/robocup_assets/p2_eval/v2_1_external_banana_coke_20260916
/home/hao/robocup_assets/p2_eval/v2_1_external_beer_master_20260916
/home/hao/robocup_assets/p2_eval/v2_1_lighting_spot_20260916
/home/hao/robocup_assets/training_runs/formal_objects_v2_1_repair_quick_validation_20260916/evaluation.json
```

## F. Competition risk after the full runtime chain

### HIGH

- **Banana:** epoch31 and V2.1 are both 2/15; all nine difficult far/problem-yaw
  placements remain failures. Whitelist, tracking, confirmation, and dedup
  cannot recover a target that is never detected at confidence 0.50.
- **Cross-class confusion:** master/tomato and coke/tomato survive the whitelist
  whenever both classes are judge targets. Multi-frame confirmation may retain
  these repeatable errors rather than reject them, and they can enter
  `answer.json` as real FP clusters.

### MEDIUM

- **Background FP:** most irrelevant classes disappear at the answer whitelist,
  and nonpersistent boxes may fail multi-frame confirmation. A repeatable
  background box whose class is requested can still form a track and survive.
- **Tuna:** the original spatial Gate is 4/5. V2.1 synthetic tuna validation is
  improved, but the rejected checkpoint was not promoted and does not close the
  untouched external gap.

### LOW

- **Lighting confidence:** all four focus classes stayed 12/12 under all four
  profiles for both candidates, with no confidence collapse. Lighting still
  changes background-FP identity and count, but the target-recall evidence is
  stable.
- **Non-target raw boxes:** boxes whose predicted class is outside the three
  judge targets cannot enter the current answer snapshot, although filtering
  them earlier would reduce upstream work.

## G. Final answers

1. **Checkpoint:** retain epoch31 V2 (`epoch30.pt`, SHA256 `c16f5332...564c`)
   as the least-bad fallback; do not deploy V2.1.
2. **Target whitelist:** yes. Keep the final answer whitelist and add the same
   filter before depth/tracking in a separately reviewed runtime change.
3. **Class-agnostic NMS / overlap suppression:** no; both lose a master TP and
   barely reduce FP.
4. **Higher image size:** no; 960 is 3/15 with problem yaw 0/9, so 1280 was
   correctly skipped.
5. **V2.1:** yes, exactly one short fine-tune was performed; it is rejected.
6. **Freeze detector:** no. The external detector Gate still fails P-001.
7. **Advance to `/map` 10 cm + final FP + full runner:** no formal advancement
   yet. The detector remains the blocking evidence item; downstream work must
   not be reported as a passed competition gate.

No P1/P2, confidence, Nav2, AMCL, TF, RGB-D, localization, online/final dedup,
`final_min_confirmations`, corners, FR3, or MoveIt/MTC setting was changed.
