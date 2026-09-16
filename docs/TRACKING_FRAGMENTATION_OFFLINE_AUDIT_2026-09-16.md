# Tracking Fragmentation Offline Audit — 2026-09-16

## Scope and evidence verdict

This audit used the unchanged nine-run Final Scoring Gate evidence under
`~/robocup_assets/p2_eval/final_scoring_gate_20260916`. It did not run YOLO,
Gazebo, navigation, or training, and it did not change the checkpoint,
confidence, P1/P2, TF, RGB-D geometry, tracking parameters, or final dedup.

The saved evidence is sufficient for exact FN decomposition, final-track
analysis, final-confirmation A/B, and official rescoring. It is **not** a full
observation replay corpus: `vision_telemetry.json` stores only final track
centroids and counts, `ObjectCluster` does not retain observations, RGB-D map
positions are logged only once per second, and the capture contains RGB but no
depth images or rosbag. Per-observation map positions, timestamps, association
decisions, same-frame pair history, and track lineage are therefore missing.

Consequently, 7/8/10 cm results below are explicitly a final-track-centroid
sensitivity bound, not a claimed frame-exact online replay. Inventing repeated
observations at each final centroid would reproduce the baseline while
silently discarding the centroid motion that caused the problem.

## A. FN decomposition

Track entries are `id:observations@distance-to-nearest-GT-cm`. Detection and
valid-3D counts are exact runtime telemetry counts.

| Scenario / FN class | Detections | Valid 3D | Tracks | Final output | Scorer | Root cause |
|---|---:|---:|---|---|---|---|
| normal apple/beer/coke — beer | 1 | 1 | `4:1@93.2` | none | FN | A: no sufficient correct detector observation |
| normal apple/beer/coke — coke_can | 24 | 24 | `3:23@10.37`, `11:1@1.62` | one, 10.37 cm | FP+FN | F: representative output outside 10 cm |
| normal apple/bowl/mustard — mustard_bottle | 0 | 0 | none | none | FN | A: detector miss |
| normal beer/pudding/windex — beer | 2 | 2 | `1:1@304.6`, `2:1@376.5` | none | FN | A: detections were not the GT object |
| normal beer/pudding/windex — pudding_box | 6 | 4 | `3:2@426.2`, `5:1@459.7`, `7:1@387.4` | none | FN | A: no correct detector/localized observation; two depth rejects did not cause the GT miss |
| danger master/tomato/apple — master_chef_can | 0 | 0 | none | none | FN | A: detector miss |
| danger coke/tomato/apple — apple | 24 | 24 | `6:24@11.90` | one, 11.90 cm | FP+FN | F: representative output outside 10 cm |
| danger master/coke/tomato — tomato_soup_can | 8 | 8 | correct `1:2@11.20`, `2:2@5.35`; four other observations were 395–441 cm away | none | FN | D primary, C contributing: only four correct observations, split 2+2; no track reached online confirmation 3 or final 5 |
| banana/apple/beer — banana | 0 | 0 | none | none | FN | A: detector miss |
| banana/apple/beer — beer | 1 | 1 | `2:1@170.9` | none | FN | A: detection was not the GT object |
| banana/coke/bowl — banana | 0 | 0 | none | none | FN | A: detector miss |
| banana/coke/bowl — bowl | 0 | 0 | none | none | FN | A: detector miss |
| banana/mustard/windex — banana | 0 | 0 | none | none | FN | A: detector miss |
| banana/mustard/windex — mustard_bottle | 0 | 0 | none | none | FN | A: detector miss |
| banana/mustard/windex — windex_bottle | 26 | 26 | `0:12@8.00`, `1:13@14.13`, `2:1@397.9` | merged output, 11.11 cm | FP+FN | F: representative output outside 10 cm |

Primary-cause totals:

| Cause | FN | Share |
|---|---:|---:|
| Detector miss or insufficient correct observations (A) | 11 | 73.3% |
| Depth/TF failure (B) | 0 | 0.0% |
| Fragmentation alone (C) | 0 | 0.0% |
| Insufficient confirmation, with fragmentation contributing (D) | 1 | 6.7% |
| Lost only by final filtering/dedup (E) | 0 | 0.0% |
| Correct-class output at or beyond 10 cm (F) | 3 | 20.0% |
| Other (G) | 0 | 0.0% |

The earlier coarse statement that five FN classes had detection/depth/TF but
no final track is true as pipeline staging, but it does not mean five correct
objects can be recovered by tracking parameters. Four of those five classes
had only wrong-object detections/localizations. Tomato is the only FN with
localized evidence near its GT, and its total correct evidence is four.

## B. Duplicate root cause

The saved final states and two-second cluster snapshots establish the
following histories. Exact per-frame association decisions cannot be recovered
because they were not saved.

### Apple — normal apple/beer/coke

- The second apple produced output tracks `#5` (8 observations,
  `(0.518, -2.355)`) and `#10` (34 observations, `(0.574, -2.263)`).
- They ended 10.80 cm apart. `#5` had already stabilized at eight observations
  before P2. `#10` also existed before the P1-to-P2 transition and then grew
  from 7 to 34 observations during P2.
- Low-evidence tracks `#7/#8/#9` lay between/around these modes. One 5 cm
  online merge occurred (`#6` into `#5`), but it did not connect the two main
  modes.
- Root cause: scan-angle-dependent visible-surface/bbox position drift already
  split the object within P1; P2 reinforced a different mode. This is not
  solely a viewpoint-switch failure.

### Tomato — danger master/tomato/apple

- P1 track `#2` ended with 6 observations at `(0.515, -3.029)`.
- After the P2 transition, `#5` was created and grew to 11 observations at
  `(0.586, -2.898)`. The final centroids are 14.86 cm apart.
- Root cause: viewpoint switch plus representative-point drift. The 5 cm
  radius could not associate the new P2 mode, and final 8 cm dedup could not
  merge it.

### Coke — danger coke/tomato/apple

- P1 already produced `#3` (11 observations, `(-2.223, -0.221)`) and `#5`
  (6 observations, `(-2.286, -0.098)`).
- P2 then created `#9`, which grew to 16 observations at
  `(-2.356, -0.007)` and became the closest output to GT.
- Final separations were 11.48, 13.79, and 25.17 cm.
- Root cause: a large, smooth scan-angle/viewpoint-dependent position sweep,
  not class confidence or a transient depth/TF failure. All 40 detections had
  valid depth and successful TF.

Across all three classes, the dominant mechanism is observation-position
jitter/drift caused by scan angle and visible-surface representation. P1/P2
switching contributes to tomato and coke but cannot explain the P1-internal
apple and coke splits. The running mean then stabilizes separated modes;
centroid drift is a consequence, while class confidence is not the gating
factor.

## C. Association-radius sensitivity

The 5 cm row is the exact official result. The other rows merge the saved final
5 cm tracks using the runtime's count-weighted centroid rule, then apply the
unchanged 8 cm final dedup and confirmation 5. They are useful sensitivity
bounds only; they are not frame-exact online replay results.

| Online radius | TP | FP | FN | Duplicate FP | Tracks after centroid coalescence | Fragmented GT objects | Close-pair wrong merge | Visual score sum |
|---:|---:|---:|---:|---:|---:|---:|---|---:|
| 5 cm exact baseline | 13 | 7 | 15 | 4 | 63 | 3 | no observed close-pair case | 112/270 |
| 7 cm sensitivity | 13 | 7 | 15 | 4 | 55 | 3 | yes in 10 cm + 2 cm-jitter safety case | 112/270 |
| 8 cm sensitivity | 13 | 7 | 15 | 4 | 53 | 3 | yes in 10–12 cm jitter safety cases | 112/270 |
| 10 cm sensitivity | 14 | 6 | 14 | 4 | 49 | 3 | yes at 10 cm even without added jitter | 122/270 |

The apparent 10-point gain at 10 cm comes from merging the 23-observation
biased coke track with one accurate observation, moving its centroid barely
inside the scorer gate. It does not remove any of the four duplicate FPs and
fails the requested same-class safety criterion. It is not a safe runtime
recommendation.

## D. Final-confirmation A/B

This A/B is exact at the saved final-track boundary. Online confirmation stays
3, online association stays 5 cm, and final dedup stays 8 cm.

| Final confirmations | TP | FP | FN | Duplicate/extra same-object FP | Newly admitted false final tracks | Visual score sum |
|---:|---:|---:|---:|---:|---:|---:|
| 5 | 13 | 7 | 15 | 4 | 0 | 112/270 |
| 4 | 13 | 7 | 15 | 4 | 0 | 112/270 |
| 3 | 13 | 9 | 15 | 6 | 2 | 108/270 |

Threshold 4 changes nothing because there is no post-dedup four-observation
cluster. Threshold 3 admits two low-evidence coke fragments and creates two
additional scorer FPs. It cannot rescue tomato's 2+2 observations because the
unchanged online confirmation gate of 3 excludes both tracks before final
deduplication.

## E. Same-class close-object safety

The nine formal scenarios contain no 10–20 cm same-class pair. Their nearest
same-class GT pair is the two apples in the normal scenario, about 3.37 m
apart. A deterministic offline safety sequence therefore used two same-class
objects at 10, 12, 15, and 20 cm, six same-frame observations per object, and
both exact and alternating 2 cm inward localization jitter. It reproduced the
current online nearest-centroid association and consolidation semantics; no
formal runtime code was changed.

| True separation | 5 cm | 7 cm | 8 cm | 10 cm |
|---:|---|---|---|---|
| 10 cm, exact | 2 tracks | 2 tracks | 2 tracks | **1 track** |
| 10 cm, 2 cm jitter | 2 tracks | **1 track** | **1 track** | **1 track** |
| 12 cm, 2 cm jitter | 2 tracks | 2 tracks | **1 track** | **1 track** |
| 15 cm, 2 cm jitter | 2 tracks | 2 tracks | 2 tracks | 2 tracks |
| 20 cm, 2 cm jitter | 2 tracks | 2 tracks | 2 tracks | 2 tracks |

The current online tracker does not use same-frame-separate protection during
association or consolidation; that protection exists only in final dedup.
Therefore the maximum tested radius that preserves the full requested
10–20 cm safety range under this small jitter is **5 cm**. A larger global
online radius is unsafe without changing the association design.

## F. Position-estimator quick audit

Full mean/median/trimmed-mean replay is impossible because raw observations
were not retained. As a bounded diagnostic, the post-reset, one-second-throttled
map positions in runtime logs were grouped by nearest GT (within 30 cm). This
covered the 16 GT objects that had a correct-class final output, but it is a
sampled audit and sometimes pools multiple tracks for one GT.

| Estimator on logged samples | Median error | Max error | Samples at/above 10 cm |
|---|---:|---:|---:|
| Arithmetic mean | 6.66 cm | 12.29 cm | 3/16 |
| Coordinate-wise median | 6.78 cm | 12.25 cm | 2/16 |
| 10% coordinate-wise trimmed mean | 6.66 cm | 12.29 cm | 2/16 |

For the three boundary failures:

| Class | Runtime output | Sample mean | Sample median | Sample trimmed mean |
|---|---:|---:|---:|---:|
| coke_can | 10.37 cm | 9.14 cm | 10.10 cm | 9.14 cm |
| windex_bottle | 11.11 cm | 10.76 cm | 8.70 cm | 10.76 cm |
| apple | 11.90 cm | 12.29 cm | 12.25 cm | 12.29 cm |

No estimator wins consistently: mean/trimmed mean help coke, median helps
windex, and none rescues apple. The sampled evidence does not justify changing
the runtime estimator.

## G. Decision

1. P-004's duplicate mechanism is position drift across scan angles and
   viewpoints followed by nearest-centroid fragmentation. It is real, but it
   is not the primary cause of the 15 FN: 11 are detector-evidence failures and
   three are localization-gate failures.
2. Do **not** change online association radius from 5 cm on this evidence.
3. Recommended online radius remains **5 cm**. Radii 7/8/10 do not remove the
   four duplicate FPs in the centroid sensitivity bound and fail close-pair
   safety.
4. Do **not** reduce `final_min_confirmations` from 5.
5. Recommended final confirmations remain **5**. Four has no effect; three
   adds two FP and loses four aggregate score points.
6. Keep final dedup at **8 cm**. It safely merged known 5.2/6.6 cm fragments;
   this audit provides no safe evidence for increasing it.
7. Do **not** change the position estimator yet. Median is a candidate only
   after full observation retention and replay.
8. Expected Final Scoring Gate improvement from the supported parameter set
   is **zero**, because the recommendation preserves current parameters. The
   unsupported 10 cm centroid sensitivity bound is +1 TP, -1 FP, -1 FN, and
   +10 aggregate points, but fails the safety gate and does not reduce
   duplicates.
9. Do **not** rerun the same nine Gazebo scenarios yet: there is no supported
   runtime fix to validate. First add bounded, observational-only retention of
   every accepted 3D observation and association decision, then collect a
   replayable corpus with unchanged behavior. The next A/B must replay those
   exact ordered observations and include same-frame close-pair protection
   before any runtime parameter change.
