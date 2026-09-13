# Base-task gap analysis — 2026-09-13

## Decision basis

This assessment uses the SEU 2026 school-competition rulebook v4, the supplied
visual-technology recommendation, the teacher's formally released `models.zip`,
the official scorer, repository state, and prior runtime evidence. The reviewed
baseline is clean `main` at commit
`36e6da74aabc31d2f239687b28d8c34f54f94deb`.

The base task is worth 70 points: 40 for autonomous navigation and 10 for each
of three judge-selected object classes. A visual answer is correct only when
the class is correct and its `/map` position is strictly within 0.10 m of the
real object center. Extra and duplicate answers are false positives. The robot
must finish the base task within eight minutes without keyboard, mouse, RViz,
or other manual control after leaving the start.

The teacher's latest clarification adds an optional coordinate-calibration
mode. If the team's `/map` frame does not coincide with Gazebo world, the
answer must include the four designated living-room wall corners `C_0` through
`C_3`, measured manually in `/map` with the permitted RViz Publish Point tool.
The official scorer fits a 2D rigid `/map` -> world transform from `C_0`, `C_1`
and `C_2`, independently validates it with `C_3`, then transforms submitted
objects before matching. If the frames already coincide, an objects-only
answer remains valid. Runtime code must not inspect the world/SDF or simulator
ground truth to obtain corners or object positions.

## Verified baseline

- Autonomous navigation to the living room and temporary-obstacle avoidance
  have passed previously.
- The real YOLO + RGB-D + TF2 + spatial deduplication chain has passed the
  official scorer for the two pilot classes (`apple`, `coke_can`): 20/20 with
  three true positives, no false positives, and maximum error 0.0746 m.
- A fresh observation window, denser full-circle scan, final evidence filter,
  exact answer JSON, and persistent final RViz markers are implemented.
- The default model still contains only two classes, while a formal run asks
  for three classes. The current workflow also still needs manual staged
  commands and has not passed randomized, no-intervention, eight-minute trials.

Estimated base-task readiness is 55–65%. The navigation and two-class geometry
chain are strong, but the current system is not a complete competition
deliverable.

That estimate describes the clean-`main` runtime baseline. Confirmation of the
official 18-class asset set removes the P0 class-universe uncertainty and raises
confidence in the trained model's scope, but it does not by itself raise
end-to-end run readiness because the model is not yet integrated and P1/P2 are
still open.

## Map/world and corners audit

The project has **not previously completed corner calibration**. There is no
saved `C_0`-`C_3` configuration, no corner transform in the runtime, and the
current answer writer emits exactly `{"objects": ...}`. Earlier project state
only listed direct corner validation as unverified.

The current frames are deliberately close, but are not proven identical:

- `example_map_v1.yaml` has occupancy-grid origin `[-5.06, -4.04, 0]`. This
  locates the raster in `/map`; it does not prove `/map == world`.
- Gazebo spawns the robot at world pose
  `(-4.852336, -0.532520, 0.014067 rad)`.
- AMCL seeds the same start in `/map` at
  `(-4.828, -0.477, 0.010 rad)`.
- A live read-only check showed Gazebo DiffDrive odometry starts at zero and
  AMCL publishes `map -> odom` from that configured map start. The two start
  anchors differ by 0.0606 m and 0.00407 rad (0.233 degrees).
- Interpreting those configured anchors as the same physical start implies an
  approximate `map -> world` transform with rotation `0.004067 rad` and
  translation `(-0.0263, -0.0359) m`. This is diagnostic evidence of near
  alignment, not a replacement for the teacher-defined corner calibration.

Objects-only scoring works because omission of `corners` makes the scorer use
the identity transform, and the combined frame offset plus perception error
has remained inside the strict 0.10 m gate. Replaying the previously saved
answers with the supplied scorer and an explicit `--match-threshold 0.10`
again produced 20/20 for runs 101 and 103. Run 103's three matched distances
were 0.0746 m, 0.0235 m and 0.0160 m; no false positives were present. Thus
20/20 proves that the identity approximation was adequate for that layout and
those detections, not that the frames are mathematically identical.

The supplied scorer currently defaults its object gate to 0.15 m, while the
teacher's formal scoring requirement and project acceptance criterion are
0.10 m. All project validation therefore continues to pass
`--match-threshold 0.10` explicitly unless the teacher publishes a different
official invocation.

Corners could remove a systematic translation/rotation and increase margin
for detections near 0.10 m, especially after a map, spawn, or competition-world
change. They also introduce risk: a wrong wall intersection, wall-thickness
ambiguity, or inconsistent manual click can rotate every otherwise-correct
object, and the scorer rejects the submission if the fit residual or held-out
`C_3` residual exceeds its corner threshold. Corners are therefore not enabled
from inference alone.

## Priority gaps

### P0 — unified official-model closed-set detector

The current two-class model cannot represent three distinct judge-selected
classes. This is a structural scoring ceiling, not a threshold-tuning problem.
The teacher's formally released `models.zip` contains exactly 18 object model
directories, and the existing two-class synthetic-data pilot already proves
the lowest-risk technical route.

Success gates:

1. One explicit, sequential class manifest maps all 18 asset directory names
   to YOLO IDs and Gazebo labels.
2. One configurable generator produces a validated unified dataset, with every
   class in train and validation splits and no duplicate-image leakage.
3. Human contact-sheet inspection confirms that rendered objects, class names,
   and boxes agree.
4. One unified YOLO model is trained and independently re-evaluated, with
   aggregate and per-class metrics recorded from the best checkpoint.
5. Model names match the manifest and the existing RGB-D runtime can filter any
   requested class subset without using simulator truth.

The rulebook itself does not contain a complete class manifest, but the
teacher's formally released `models.zip` has now been checked directory by
directory against `tools/formal_dataset/classes.json`: missing 0, extra 0, and
naming differences 0. The current 18-class set is therefore the complete
official model asset set.

This confirms the **official model directory identifiers**, not the syntax of
the **judge input strings on competition day**. Until the input interface is
specified, no assumption is made about case, spaces versus underscores,
punctuation, singular/plural forms, or aliases. P1 must introduce an explicit,
auditable normalization/alias boundary that maps only documented or configured
input forms to the canonical 18 directory identifiers and fails closed on an
unknown or ambiguous name.

### P1 — zero-intervention competition runner

Provide one bounded runner that accepts exactly three judge target strings and
a positive group number, resolves each target through an explicit
normalization/alias map to a distinct canonical class, navigates, resets the
observation window, scans, performs only evidence-driven reinspection, saves
once, and exits within the base-task time budget. Reject unknown, ambiguous, or
duplicate-after-normalization targets and fail closed when any stage fails.

### P2 — high-information scenario matrix

Run the complete chain against randomized placements, target triples, nearby
same-class objects, occlusion, table corners, and temporary obstacles. Record
official-score TP/FP/FN, maximum localization error, completion time, and
failure stage. Use failures to change one justified parameter or component at
a time.

The first coordinate-calibration item inside P2 is a non-runtime A/B test:

1. With the saved `example_map_v1` loaded, manually capture the teacher-defined
   `C_0`-`C_3` wall intersections in `/map` using RViz Publish Point. Repeat the
   capture independently to measure click stability; do not read the world or
   SDF.
2. Duplicate one unchanged, real perception answer into objects-only and
   corners-plus-objects variants.
3. Run both through the same official scorer with an explicit 0.10 m object
   gate. Compare validity, fitted rotation/translation, all fit residuals,
   held-out `C_3` residual, each TP distance, FP/FN and total score.
4. Keep objects-only unless repeated corner captures remain stable, `C_3` has
   comfortable margin below the official corner threshold, and the calibrated
   variant preserves the score while consistently reducing systematic or
   maximum object error across more than one layout.

This work must not preempt P1. It becomes urgent before formal submission if a
new map or spawn pose is introduced, the teacher's formal world moves the
shared start/layout frame, repeated objects-only errors show a consistent
direction, any correct-class detection approaches or crosses 0.10 m, or the
official scorer invocation makes calibration mandatory.

### Deferred

- Active FR3 / MoveIt2 work until the 70-point base chain is repeatable.
- Blind confidence, depth, or deduplication-radius tuning without failure data.
- Any calibration fitted to one hidden ground-truth layout.

## P0 implementation evidence

The feature branch `work/formal-object-dataset` adds an offline-only pipeline
under `tools/formal_dataset`. It leaves the existing pilot weights and runtime
model selection unchanged.

- Smoke dataset: 18 train images, 18 validation images, 54 total instances;
  every class occurs in both splits and the contact sheet passed human review.
- First-pass dataset: 1,800 train images, 360 validation images, 3,266 total
  instances; per-class train counts are 135–166 and validation counts are
  25–36. Structural validation and duplicate-image leakage checks passed.
- Dataset path:
  `~/robocup_assets/datasets/formal_objects_v1` (generated artifact, not Git).
- Unified YOLO11n model: 20 epochs on the RTX 4060, with the best checkpoint at
  epoch 20. Independent validation produced precision 0.977, recall 0.965,
  mAP50 0.981, and mAP50-95 0.926. All 18 classes have recorded metrics; the
  lowest per-class recall is 0.872 and the lowest per-class mAP50 is 0.942,
  both for `chips_can`.
- Best weights:
  `~/robocup_assets/training_runs/formal_objects_v1_yolo11n/weights/best.pt`.
  The original CPU runtime environment loaded these GPU-trained weights,
  preserved the exact 18-name manifest order, and completed inference, so no
  runtime framework replacement is required.

All five P0 success gates are complete for the synthetic first pass, and the
canonical class set is now confirmed against the official `models.zip`. This
is a model-development result, not evidence that all 18 classes will score
equally well in the full competition world. Judge-input normalization remains
a P1 interface task; P1 runner integration and P2 randomized end-to-end scoring
remain required before this model replaces the pilot default.

## Fair-play boundary

Gazebo labels and model poses are used only inside the offline dataset generator
to produce training annotations. Competition perception and answer generation
must continue to use camera images, depth, camera calibration, TF2, and online
robot state only. No label topic, object entity pose, known answer coordinate,
or simulator ground-truth hook may enter the runtime chain.
