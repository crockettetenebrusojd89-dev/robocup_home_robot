# Banana Runtime Repair Audit

Date: 2026-09-16

Branch: `work/p2-randomized-eval`

Starting HEAD: `2ef23326bfce29162a43e1fde7a01814f37e978a`

## Verdict

Keep V2 epoch31, confidence 0.50, and P1/P2 unchanged. Move the existing
three-target whitelist immediately after detector decoding and before depth,
TF, markers, and tracking. Reject tiled inference, low-confidence banana
candidates, and the close-range fallback pose. Stop detector/model development
for the event and proceed next to the formal `/map` 10 cm and `answer.json`
gate with banana recorded as a high competition risk.

Checkpoint:

```text
/home/hao/robocup_assets/training_runs/formal_objects_v2_yolo11n_finetune/weights/epoch30.pt
SHA256 c16f5332221649fdb89c225f9aaec6f73db97e2590bc37734a6d0e0a5099564c
```

No training was run. No P1/P2, global confidence, Nav2, AMCL, TF, RGB-D,
deduplication radius, or confirmation threshold changed.

## A. Early target whitelist

`formal_base_task.launch.py` resolves exactly three judge target classes and
passes them to the localizer. Before this change, `_extract_detections()` kept
all confidence-0.50 18-class detections. Non-target detections therefore passed
through depth, TF, markers, and tracking. `_make_answer_snapshot()` filtered to
the three requested classes only at save time.

The minimal runtime change now applies the same resolved target set at the end
of `_extract_detections()`. The model remains an 18-class model and still runs
one ordinary inference. Only detections whose decoded class is requested enter
the downstream chain.

Consequences:

- Non-target raw boxes no longer consume depth, TF, marker, and tracking work.
- Target markers and answer contents keep the same intended competition scope.
- Current final `answer.json` semantics do not change: the final snapshot
  already rejected non-target classes. Moving the whitelist earlier is
  containment and efficiency, not a claimed direct reduction of existing
  final-output FP counts.
- A wrong class still survives when both the real class and the predicted class
  are judge targets. In particular, master/tomato and coke/tomato remain high
  risk.

From the prior 150-placement audit there were 74 wrong-class boxes on 48
placements. Across all 816 possible three-target sets, the whitelist changes
median wrong boxes from 8 to 0 and the 90th percentile from 31 to 4, but the
worst `coke_can + master_chef_can + tomato_soup_can` set retains 38 boxes.

## B. Full-frame versus 2x2 tiled inference

The untouched 720 RGB frames from the same 15 banana external placements were
replayed with epoch31. The tiled mode used four 20%-overlapping crops, resized
each crop to 640, mapped boxes back to full-frame coordinates, and applied
same-class IoU-0.70 merge.

| Mode | Success | Problem group | Median wall latency | Raw FP boxes | FP after banana whitelist | Duplicate frames |
|---|---:|---:|---:|---:|---:|---:|
| Full frame 640 | 2/15 | 0/9 | 8.109 ms | 0 | 0 | 0 |
| 2x2 tiled 640 | 1/15 | 0/9 | 14.975 ms | 60 | 0 | 0 |

Tiling reduced recall, did not recover any problem placement, increased median
latency by about 85%, and produced four irrelevant-class boxes per placement.
The early whitelist removes those tiled raw boxes when only banana is relevant,
but cannot make the lost recall acceptable. Tiled inference is rejected and
was not integrated into runtime.

Evidence:

```text
/home/hao/robocup_assets/p2_eval/v2_epoch31_banana_runtime_repair_audit_20260916/summary.json
```

## C. Low-confidence banana candidate replay

Only banana candidates were admitted in this replay; the global formal
confidence remains 0.50. A target placement was associated using its truth box
only after inference. Strict confirmation counts use distinct saved scan-yaw
frames: three frames for a confirmed proxy and five for a final-output proxy.

| Candidate threshold | Any target candidate | >=3 distinct frames | >=5 distinct frames | Problem >=5 | Raw banana FP boxes | FP frames | FP placements |
|---|---:|---:|---:|---:|---:|---:|---:|
| 0.10 | 8/15 | 7/15 | 1/15 | 0/9 | 105 | 60 | 15/15 |
| 0.15 | 8/15 | 7/15 | 1/15 | 0/9 | 90 | 60 | 15/15 |
| 0.20 | 7/15 | 5/15 | 0/15 | 0/9 | 60 | 45 | 15/15 |

At 0.10 and 0.15, every placement has a background banana candidate in four
distinct saved scan frames. At 0.20 every placement has one in three frames.
Thus all thresholds already create confirmed-track risk at the three-frame
stage. None of those FP signatures appears in five distinct saved yaw frames,
but that is not sufficient safety evidence: the real scan dwells for two
seconds and the localizer can infer at 5 Hz, so one repeatable static FP can
accumulate the unchanged five final confirmations during one dwell.

The saved gate contains RGB but not depth images, so a faithful 3D track replay
is impossible without recapturing the test. The strict and dwell-amplified
bounds are both reported rather than assuming unavailable depth would remove
the FPs. Threshold 0.15 dominates 0.10 slightly on raw FP count, but neither
recovers the difficult group and neither is safe enough to adopt. No candidate
threshold is recommended.

## D. Conditional close-range fallback

After both inference-only approaches failed, one fixed pose was selected from
the known geometry of `living_room_table_3` and the static occupancy map:

```text
x=-3.300, y=-1.800, yaw=-1.723
```

The pose faces the fixed table center near `(-3.5, -3.1)` and has approximately
0.56 m of free-map clearance to the nearest occupied cell. It was selected
before capture and does not depend on object position, class output, Gazebo GT,
or the original external placement truth. P1/P2 remain unchanged.

At this pose, object distance across the 15 placements falls to
0.845--1.787 m, and the median detected candidate bbox is approximately
52.8 x 10.2 px. Nevertheless:

| Gate | All placements | Problem group |
|---|---:|---:|
| P1/P2 baseline | 2/15 | 0/9 |
| Fallback only | 2/15 | 1/9 |
| P1/P2 plus fallback | 4/15 | 1/9 |

Only `banana_04` and `banana_07` are newly recovered. The fallback also
produces 15 confidence-0.50 wrong-class `coke_can` boxes, one per placement;
those boxes remain dangerous when banana and coke are both requested.

Nav2 reachability was verified in one fixed smoke run. Navigation completed
without collision, the 12-step scan completed, answer save succeeded, and the
run ended with `failure_stage=success` in 87.87 seconds total wall time. From
the runtime log, navigation after Nav2 activation took 13.14 seconds and the
scan took 44.11 seconds.

For the actual conditional P2-to-fallback segment, straight-line distance is
3.741 m. This is almost identical to the already measured P1-to-P2 distance of
3.777 m; that segment required 30.57 seconds of navigation plus a 44.15-second
scan. Therefore the evidence-based expected incremental cost is about 75
seconds, with a kinematic lower bound of about 63 seconds. Because combined
banana recall remains only 4/15, this cost is not justified and the fallback
is rejected.

Evidence:

```text
/home/hao/robocup_assets/p2_eval/v2_epoch31_banana_close_fallback_20260916
/home/hao/robocup_assets/p2_eval/banana_fallback_nav_reachability_20260916
/home/hao/robocup_assets/p2_eval/viewpoint_eval_seed_20260914_two_safe_20260915
```

## Final competition decision

The minimum event-week runtime repair is only the early target whitelist.
Do not integrate tiled inference, a lower banana threshold, or a third
viewpoint. Freeze checkpoint selection on epoch31 and stop visual model R&D.

This is a schedule/risk decision, not a claim that P-001 is solved: banana
remains a high-risk 2/15 detector limitation and requested-pair cross-class
confusion remains. The next project task may proceed to the `/map` 10 cm,
final-FP, and `answer.json` gate so the remaining time targets end-to-end score,
while preserving these known detector risks in the verdict.
