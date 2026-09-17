# Advanced Stage 2A — FR3 Visual Pre-Grasp

Date: 2026-09-17

Branch: `work/p2-randomized-eval`

Starting HEAD: `5b9460d`

## Verdict

**Stage 2A: PASS.** The complete mobile robot now reuses the teacher demo's
Gazebo `ros2_control`/MoveIt control chain. An automatically selected dining
target drives a collision-checked top-down pre-grasp. This work does not close
the gripper, attach an object, lift, or place.

The long Advanced-only table-exterior route and the final arm gate were also
tested separately to isolate Nav2 timing variance from manipulation safety.
The full route reached the manipulation pose in
`advanced_stage2a_full_route_2026-09-17.log`; after the final planning fixes,
the automatic visual-target-to-pre-grasp gate passed in
`advanced_stage2a_arm_focus3_2026-09-17.log`.

## FR3 Control

- Original integrated state: **A — static URDF model only**. It had no active
  `controller_manager`, trajectory action, SRDF, or MoveIt runtime.
- Gazebo hardware/plugin reused from the teacher chain:
  `franka_gazebo_hardware/FrankaGazeboHardwareInterface` through
  `gz_ros2_control`.
- Active arm controller: `fr3_arm_controller`,
  `joint_trajectory_controller/JointTrajectoryController`, effort command with
  position/velocity feedback, joints `fr3_joint1` through `fr3_joint7`.
- Controller update rate: 1000 Hz. Lower 100/500 Hz trials reached endpoint
  positions but produced unsafe multi-joint velocity limit cycles, so they
  were rejected by the stop-velocity gate.
- Hand controllers from the teacher demo are intentionally not spawned in
  Stage 2A. No gripper command is issued.
- MoveIt controller mapping: `fr3_arm_controller/follow_joint_trajectory`.
- Planning group: `fr3_arm`.
- Planning frame: `base_link` (fixed-root integrated robot model).
- End effector/TCP: `fr3_hand_tcp`.
- Navigation-stowed start:
  `[-0.68, 0.29, -0.26, -2.91, 0.75, 1.03, 2.00]` rad.
- Safe-motion gate: joint 7 target change `-0.05` rad; actual change
  `-0.0459` rad; MoveIt plan and controller execution both succeeded.

## TF

- Integrated static mount `base_link -> fr3_link0`:
  translation `[-0.090, 0.055, 0.425]` m, identity rotation.
- TCP: `fr3_hand_tcp`; no duplicate FR3 or second TF tree is spawned.
- The final target came from Stage 1, was transformed through `/map`, and was
  then transformed to both `base_link` and `fr3_link0` at the final base pose.
- Top-down orientation is the teacher demo's world/map quaternion
  `xyzw=[1,0,0,0]`. The complete pose is transformed from `/map` to
  `base_link`; the quaternion is not incorrectly reused as a base-frame
  quaternion.

## Target

Final focused acceptance selected automatically:

- class: `coke_can`
- confidence: `0.98`
- camera point: `[0.003, 0.120, 0.568]` m
- initial target in `base_link`: `[0.738, -0.003, 0.683]` m
- target in `/map`: `[1.851, 1.962, 0.683]` m
- target at manipulation pose in `base_link`: `[-0.596, 0.377, 0.683]` m
- target in `fr3_link0`: `[-0.506, 0.322, 0.258]` m

The observation pose target was explicitly rejected as manipulation-reachable
and logged as `OBSERVATION POSE NOT MANIPULATION REACHABLE`. The Advanced-only
approach uses exterior table waypoints and never modifies the frozen base-task
P1/P2 or Stage 1 observation pose.

## Planning Scene

The nearest actual dining-table top is inserted as a MoveIt collision box:

- object id: `dinning_table_1`
- world centre: `[1.500, 2.000, 0.765]` m
- size: `[0.5, 1.2, 0.03]` m
- yaw: `1.57` rad
- verified surface height: `0.780` m

The dimensions and pose come directly from the acceptance world. Robot-body
and FR3 collisions come from the integrated robot model and are not duplicated.

## Pre-Grasp

- Support-plane rule: the RGB-D visible-surface estimate was below the verified
  table surface, so only the safe pre-grasp Z was clamped to the support plane.
  Class and visual XY were unchanged.
- Offset: `0.180` m above the verified table surface.
- Final pose in `base_link`: `[-0.596, 0.377, 0.960]` m.
- Orientation: top-down `quaternion_map_xyzw=[1,0,0,0]`, transformed by TF2
  into the MoveIt planning frame.
- Conservative radial reach: `0.804` m (`0.95` m gate).
- Table Planning Scene: **APPLIED**.
- IK: **SUCCESS**.
- collision-checked OMPL plan: **SUCCESS**.
- trajectory execution: **SUCCESS**.
- final runtime marker: `STAGE2A_PASS`.
- Gripper close / grasp / lift / place: **NOT IMPLEMENTED and NOT EXECUTED**.

## Evidence

- Final automatic visual-to-pre-grasp log:
  `/home/hao/robocup_assets/evidence/advanced_stage2a_arm_focus3_2026-09-17.log`
- Full Advanced-only exterior-route log:
  `/home/hao/robocup_assets/evidence/advanced_stage2a_full_route_2026-09-17.log`
- Automatically annotated selected-target image:
  `/home/hao/robocup_assets/evidence/advanced_stage2a_target_focused_arm3_2026-09-17.png`

The accepted run was headless, so no separate Gazebo or RViz still image was
captured. Actual Gazebo motion is evidenced by the controller-accepted
trajectory, measured joint-state delta, successful trajectory result, and
final pre-grasp execution in the preserved log. RViz was observation-only and
was disabled for the resource-isolated acceptance run.

## Validation

- `ament_flake8`: passed for edited Python launch/scripts.
- `ament_uncrustify`: passed for `advanced_stage2a_pregrasp.cpp`.
- Focused regression set: **25 passed** (FR3 frames, pre-grasp geometry,
  target selector, dining navigation, and formal base runtime).
- `git diff --check`: passed in the repository.
- `colcon build --symlink-install --cmake-args
  -DCMAKE_BUILD_TYPE=Release -DBUILD_TESTS=OFF`: passed for both workspace
  packages; `robocup_home_robot` rebuilt successfully.
- Frozen base-task detector/checkpoint/confidence, P1/P2, Nav2 speed, tracking,
  deduplication, confirmations, and answer writer were not changed.
