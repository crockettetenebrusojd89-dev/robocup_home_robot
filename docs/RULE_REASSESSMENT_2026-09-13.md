# Rule-first project reassessment - 2026-09-13

## Source priority

1. Teacher's latest group notices.
2. SEU 2026 school-competition rulebook v4.
3. Official scorer and JSON requirements.
4. Teacher-provided `models.zip`.
5. Repository and runtime evidence.
6. Historical project plans.

## Actual task structure

- Pre-competition: build and save a map and label room/area locations.
- Base task, 70 points: start at the marked entrance, autonomously navigate to
  the living room without collisions (40), then identify, localize, and count
  exactly three judge-announced English target categories (10 each). Print
  category names and counts, show `/map` RViz markers, and automatically save
  the strict answer JSON before the run ends.
- Advanced task, 30 points: after the base task, autonomously navigate through
  the dining-room door to the table (10), autonomously identify and visibly
  label one chosen target among four unannounced table objects (10), then grasp,
  clearly lift, and stably return it (10).

The four unannounced objects are the four dining-table objects in the advanced
task, not four additional base-task search objects. The available evidence does
not explicitly state that these four are guaranteed to be selected from the 18
directories in `models.zip`; confirm this with the teacher before freezing the
advanced-task classifier contract.

## Latest group clarifications

- A `.world` file will be issued on competition day and can be loaded directly.
- Base-task search objects are all on table surfaces and are not stacked.
- An object that can stand stably will not intentionally be laid down. An
  unstable object may be laid horizontally; `mustard_bottle` was the explicit
  example.
- Occlusion depends on viewpoint. A single view may be occluded, while a
  combination of multiple viewpoints can provide complete coverage; the robot
  must combine multi-view information.
- The four dining-table objects are not search objects. Their categories will
  not be announced because the robot must identify them autonomously.
- Temporary obstacles are not limited to the two positions suggested by a
  student, but they will not make the route completely impassable.

These notices clarify the rulebook rather than contradicting its scoring. The
only meaningful scope correction is that the four unknown categories belong to
advanced visual-grasping, not base-task target input.

## Current evidence and gaps

- A complete example-world run has demonstrated living-room navigation plus a
  real YOLO/RGB-D/TF2 chain scoring 20/20 for the two pilot categories. This is
  strong component evidence but not a formal three-category run.
- The unified 18-class model is trained but not integrated or scored through
  the competition runtime.
- The synthetic dataset randomizes object yaw and camera pose but keeps object
  roll and pitch at zero. It has no intentional lying-object coverage.
- Direct inference on the teacher's horizontal `mustard_bottle` screenshot did
  not produce a mustard detection even at confidence 0.01 and instead produced
  banana false positives. This justifies a later targeted pose dataset, not an
  immediate large retrain.
- Twelve 30-degree scan steps provide full azimuth and repeated observations,
  and map-frame clustering/deduplication can fuse detections across frames.
  However, rotating at one position does not create translational parallax, so
  it cannot guarantee recovery from object-on-object occlusion.
- The main launch hard-codes the packaged example world. This is the first
  formal-day blocker addressed by the current P0.

## New priority order

### P0 - direct formal-world launch and preflight

This gates every scored task. Accept the teacher-provided `.world` path without
copying, changing, or parsing object truth; fail closed on invalid inputs; keep
the example default; and verify Gazebo, robot, sensors, Nav2, and AMCL startup.

P0 is complete on branch `work/formal-world-loader`: absolute-path and default
launch modes reached active Nav2, the direct-path run exposed all required
sensor interfaces and autonomously reached the living room, and a missing path
failed before Gazebo startup. Final validation with the actual teacher-provided
competition file can only occur after that file is released.

### P1 - formal three-target base runtime

Integrate the explicit 18-class weights, exactly three judge inputs, strict
category-name handling, group number, automatic navigation/scan/save sequencing,
and official JSON validation. Unknown input formats remain a documented
normalization/alias boundary until the teacher publishes the interface.

### P2 - evidence-driven perception and run robustness

Add targeted lying-object evaluation/data only for physically unstable models,
then add multiple safe observation positions for parallax. Run randomized
object placement, temporary-obstacle, corner-calibration, duplicate, and
eight-minute end-to-end score regressions before tuning thresholds.

### Deferred

Defer dining-room unknown-four classification and FR3 grasp integration until
the base 70-point chain is repeatable. Keep the existing arm work intact.

## Open questions for the teacher

1. Are all four dining-table objects guaranteed to come from the 18 official
   `models.zip` directories?
2. What exact mechanism and spelling format will deliver the three base target
   names?
3. Will the formal file retain the Gazebo world name `robocup_home`?
4. Does the eight-minute limit end after the base-task outputs are saved, with
   advanced-task timing handled separately, or is there a total-run time cap?
