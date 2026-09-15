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

Start here: [`docs/STARTUP_GUIDE.md`](docs/STARTUP_GUIDE.md) contains the
repository-local Chinese guide for building, mapping, navigation, vision,
formal competition-world loading, verification, and shutdown. It is intended
to remain usable without the workspace-level notes.

Documentation maintenance rule: every change that modifies dependencies,
launch commands, launch arguments, runtime order, expected topics, or success
criteria must update the startup guide in the same branch or pull request.
Every completed feature or evaluation branch must also update the relevant
experiment/runbook document plus `docs/PROJECT_STATE.md` and `docs/HANDOFF.md`
with its verified result, unresolved failures, evidence location, frozen
parameters, and next decision. Git commits remain the exact change history;
the Markdown files are the human-readable project and risk record.

For verified capability boundaries and the latest handoff, see
[`docs/PROJECT_STATE.md`](docs/PROJECT_STATE.md) and
[`docs/HANDOFF.md`](docs/HANDOFF.md).

## Formal base-task runtime

The unattended navigation, three-class search, counting, and answer-JSON
workflow is documented in
[`docs/FORMAL_BASE_RUNTIME.md`](docs/FORMAL_BASE_RUNTIME.md).
