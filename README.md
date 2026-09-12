# SEU RoboCup@Home 2026

`robocup_home_robot` is the team-maintained robot package for the SEU
RoboCup@Home 2026 competition project.

## Environment

- Ubuntu 22.04
- ROS 2 Humble
- Gazebo Fortress / Gazebo Sim

## Robot

The current robot combines a differential-drive mobile base with a 2D LiDAR,
IMU, RGB-D camera, and a statically integrated Franka FR3 arm and Hand.

`main` is the stable development baseline. The FR3 V2 static stowed
integration was merged in commit `cf93726b0c19ab55e47cb1e4e3983fb5585ac05d`.

Detailed startup and operational instructions remain in the workspace-level
[`RUNBOOK.md`](../../RUNBOOK.md). This repository intentionally does not copy
that runbook.

For verified capability boundaries and the latest handoff, see
[`docs/PROJECT_STATE.md`](docs/PROJECT_STATE.md) and
[`docs/HANDOFF.md`](docs/HANDOFF.md).
