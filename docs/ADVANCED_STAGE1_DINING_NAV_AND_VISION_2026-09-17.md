# Advanced Stage 1 dining navigation and vision validation — 2026-09-17

## Scope

P-013 only. This run does not change the frozen base-task launch, P1/P2
poses, Nav2 parameters, detector checkpoint, confidence, or manipulation
stack.

## Disposable validation scene

`/home/hao/robocup_assets/evidence/advanced_stage1_dining_2026-09-17.world`
was generated from packaged `example.world`; its source was not edited. It
places the following four legal-manifest objects on the 0.78 m dining-table
surface, in separate normal quadrants:

| Class | World pose `(x, y, z, yaw)` |
| --- | --- |
| `apple` | `(1.450, 1.550, 0.780, 0.350)` |
| `coke_can` | `(1.850, 1.930, 0.780, -0.450)` |
| `mustard_bottle` | `(2.500, 1.550, 0.780, 0.200)` |
| `master_chef_can` | `(2.950, 1.930, 0.780, -0.700)` |

## Direct-route failure diagnosis

The first resource-complete run reached frozen P2 but then sent one direct
goal to `(2.100, 0.450, 1.571)`. The global planner produced a path and the
controller accepted it, but the route skimmed the dining-entry wall corner
around map `(0.95, -0.55)`, as visible in the RViz collision screenshot.
Static-map sampling gives only about **0.14 m** clearance there. The frozen
footprint has half extents `0.27 m` and `0.25 m` (circumscribed radius about
`0.368 m`), so the direct route was not physically safe although planner and
costmaps remained active.

The direct run emitted six `Failed to make progress` events and two `Collision
Ahead` recoveries (Spin and DriveOnHeading) in that corner zone. Its old log
does not preserve timestamped AMCL poses, so this records the observed zone
rather than inventing centimetre-level collision coordinates. The successful
route below proves the observation pose is reachable; the defect was route
geometry, not the goal pose.

## Corrected real acceptance run

The final isolated run used frozen `epoch30.pt` and an Advanced-only two-leg
handoff via `dining_entry_waypoint=(0.450, 0.250, 1.571)`. No base-task
waypoint or Nav2 setting changed.

| Leg | Goal / result | Latest AMCL and XY error |
| --- | --- | --- |
| Normal start → frozen P2 | `(0.265, -0.665, -2.638)`; succeeded | `(0.049, -0.729)`; `0.225 m` |
| P2 → entry waypoint | `(0.450, 0.250, 1.571)`; succeeded | `(0.215, 0.118)`; `0.270 m` |
| Entry waypoint → observation | `(2.100, 0.450, 1.571)`; succeeded | `(1.878, 0.420)`; **`0.224 m`** |

The two dining legs took `13.472 s` and `15.573 s` of simulation time; P2
through observation arrival took `29.045 s`. Normal start through observation
arrival took `74.914 s`; target selection followed `1.239 s` later. The final
run had zero `Failed to make progress`, zero `Collision Ahead`, zero backup,
and zero DriveOnHeading recoveries. Nav2 performed one routine Spin, but no
collision or continuous failure occurred.

## Visual and 3D acceptance

Automatic target selection chose the placed `coke_can`.

| Field | Acceptance value |
| --- | --- |
| Confidence | `0.958` |
| Bbox | `[160.7, 224.6, 186.5, 272.7]` pixels |
| Depth / camera point | valid positive depth `1.159 m`; `[-0.371, 0.022, 1.159] m` |
| `base_link` point | `[1.338, 0.371, 0.677] m` |

Depth is finite and at the expected table range. In `base_link` the target is
in front of the robot (`x=1.338 m`) and at table height (`z=0.677 m`). The
saved image visibly shows the dining table, left-side real coke can, purple
selected bbox, and class label.

## Evidence and result

- Generated world: `/home/hao/robocup_assets/evidence/advanced_stage1_dining_2026-09-17.world`
- Verified `/advanced/target_image` evidence:
  `/home/hao/robocup_assets/evidence/advanced_stage1_target_2026-09-17.png`
- Direct-route log: `/tmp/p013_stage1.log`
- Final acceptance log: `/tmp/p013a_final.log`
- No additional layouts: the first normal layout passed, so the requested stop
  rule applies.

**Stage 1: PASS**

**P-013: SOLVED**

All acceptance conditions are met: collision-free P2 handoff, four legal
objects, correct selected class/bbox, valid depth and camera/base points,
observation error within `0.25 m`, and a verified target image. The frozen
base task is unchanged. No FR3, MoveIt, MTC, grasp, confidence, P1/P2, or
Nav2-speed work was performed.
