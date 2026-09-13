# Formal base-task runtime

This launch is the single entry point for the 70-point base-task workflow:

1. validate the official 18-class model and the three judge-specified classes;
2. start the existing navigation stack and drive to the living room;
3. reset the observation window and run the 12-by-30-degree scan;
4. fuse RGB-D detections in `/map`, cluster duplicates, and count objects;
5. save `<group_number>_answer.json` automatically and shut down.

## Build

```bash
cd ~/wpr_ros2_ws
source /opt/ros/humble/setup.bash
source ~/franka_ros2_ws/install/setup.bash
colcon build --symlink-install --packages-select robocup_home_robot
```

## Run

Use the judge's three names exactly as published. The default alias map is
empty, so spelling and case differences are rejected rather than guessed.

```bash
cd ~/wpr_ros2_ws
source /opt/ros/humble/setup.bash
source ~/franka_ros2_ws/install/setup.bash
source ~/robocup_vision_venv/bin/activate
source install/setup.bash

ros2 launch robocup_home_robot formal_base_task.launch.py \
  target_1:=apple \
  target_2:=coke_can \
  target_3:=banana \
  group_number:=104 \
  model_path:="$HOME/robocup_assets/training_runs/formal_objects_v1_yolo11n/weights/best.pt"
```

Replace the three example targets and `104` before a scored run. The group
number must be a positive integer. The model must expose all 18 official
classes in the exact order recorded by the repository manifest.

By default the answer is written to:

```text
~/robocup_assets/submissions/<group_number>_answer.json
```

The launcher refuses to overwrite an existing answer. Move the earlier file
out of the submissions directory or choose the correct unused group number
before retrying.

## Success criteria

A successful run prints all three English class names and counts, reports the
answer path, and exits without operator input. The saved JSON has exactly one
top-level `objects` field and exactly the three requested class keys. Empty
classes remain present as empty arrays.

The current launch uses the repository's existing pre-release `example.world`
navigation path. Loading a competition-day absolute `.world` path is tracked
separately and must be integrated only after that feature branch is reviewed.

## Optional parameters

- `answer_output_dir`: output directory for the answer JSON.
- `device`: inference device; defaults to `cpu`.
- `max_runtime_seconds`: hard timeout for the unattended run; defaults to 450.
- `class_aliases`: explicit alias JSON. Keep it empty until the judge's input
  string format is confirmed.
