# Base-task gap analysis — 2026-09-13

## Decision basis

This assessment uses the SEU 2026 school-competition rulebook v4, the supplied
visual-technology recommendation, the teacher's formally released `models.zip`,
the official scorer, repository state, and prior runtime evidence. The reviewed
baseline for the P1 branch was clean `main` at commit
`36e6da74aabc31d2f239687b28d8c34f54f94deb`.

The base task is worth 70 points: 40 for autonomous navigation and 10 for each
of three judge-selected object classes. A visual answer is correct only when
the class is correct and its `/map` position is strictly within 0.10 m of the
real object center. Extra and duplicate answers are false positives. The robot
must finish the base task within eight minutes without keyboard, mouse, RViz,
or other manual control after leaving the start.

## Verified baseline

- Autonomous navigation to the living room and temporary-obstacle avoidance
  have passed previously.
- The real YOLO + RGB-D + TF2 + spatial deduplication chain has passed the
  official scorer for the two pilot classes (`apple`, `coke_can`): 20/20 with
  three true positives, no false positives, and maximum error 0.0746 m.
- A fresh observation window, denser full-circle scan, final evidence filter,
  exact answer JSON, and persistent final RViz markers are implemented.
- The generic localizer default still names the two pilot classes, while the
  dedicated formal launch now requires an explicit 18-class checkpoint and
  exactly three targets. Randomized, official-world, eight-minute trials have
  not yet passed.

Estimated base-task readiness is 70–80%. One complete formal-model runtime has
now passed, but one known layout is not yet a repeatable competition
deliverable.

That estimate describes the clean-`main` runtime baseline. Confirmation of the
official 18-class asset set removes the P0 class-universe uncertainty and raises
confidence in the trained model's scope, but it does not by itself raise
end-to-end run readiness because the model is not yet integrated and P1/P2 are
still open.

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
observation window, scans, saves once, and exits within the base-task time
budget. Reject unknown, ambiguous, or duplicate-after-normalization targets
and fail closed when any stage fails. Reinspection remains a later,
evidence-driven addition rather than a mandatory first closure step.

### P2 — high-information scenario matrix

Run the complete chain against randomized placements, target triples, nearby
same-class objects, occlusion, table corners, and temporary obstacles. Record
official-score TP/FP/FN, maximum localization error, completion time, and
failure stage. Use failures to change one justified parameter or component at
a time.

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
equally well in the full competition world.

## P1 implementation evidence

The `work/formal-base-runtime` branch now provides a fail-closed launch that
requires the formal model path, exactly three distinct canonical or explicitly
aliased target names, and a positive group number. It validates the model's
class names and order against the official 18-class manifest before accepting
detections, refuses to overwrite an existing answer, and verifies the saved
objects-only JSON before reporting success.

One full `example.world` run completed navigation, a fresh twelve-view scan,
RGB-D localization, spatial deduplication, counting, and automatic answer save
without operator input. The runner completed in 96 seconds and produced a
strict three-key answer with `apple=1`, `coke_can=1`, and `banana=0`. This closes
the requested P1 control-flow integration; P2 randomized official scoring is
still required to establish repeatability and all-class competition accuracy.

## Fair-play boundary

Gazebo labels and model poses are used only inside the offline dataset generator
to produce training annotations. Competition perception and answer generation
must continue to use camera images, depth, camera calibration, TF2, and online
robot state only. No label topic, object entity pose, known answer coordinate,
or simulator ground-truth hook may enter the runtime chain.
