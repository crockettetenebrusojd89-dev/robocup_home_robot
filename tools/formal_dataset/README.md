# Formal object dataset pipeline

This offline-only tool generates one closed-set YOLO detection dataset from
the 18 object models distributed with the SEU RoboCup@Home 2026 simulation.
It does not import the robot package and must never be used by competition
runtime perception or answer generation.

The class order is fixed in `classes.json`. Gazebo labels and object poses are
used only to create offline annotations. Generated datasets and trained weights
belong under `~/robocup_assets`; they are intentionally not committed here.

The 18 identifiers have been checked directory by directory against the
teacher's formally released `models.zip`: missing 0, extra 0, and naming
differences 0. They are the official model directory identifiers. This does not
define how the judge input strings will be formatted on competition day.
Runtime integration must keep a separate, explicit normalization/alias mapping
and must not silently assume case, spaces versus underscores, or alternate
names.

## Smoke test

The smoke configuration produces one primary example per class in both train
and validation splits. Run it before a full dataset:

```bash
cd ~/wpr_ros2_ws/src/robocup_home_robot/tools/formal_dataset
python3 scripts/generate_dataset.py \
  --config config/smoke.json \
  --output ~/robocup_assets/datasets/formal_objects_smoke
python3 scripts/validate_dataset.py \
  ~/robocup_assets/datasets/formal_objects_smoke
python3 scripts/visualize_labels.py \
  ~/robocup_assets/datasets/formal_objects_smoke \
  --split val --output /tmp/formal_objects_smoke_val.png
```

The generator refuses to overwrite a non-empty directory. It compiles the
small Ignition Transport capture worker locally, starts a private headless
Gazebo Fortress world, randomizes table objects and camera poses, and writes
YOLO labels from Gazebo's visible-2D bounding-box camera.
The contact sheet is a required human check that the rendered model and box
identity agree; the numeric validator cannot detect a visually wrong model.

## Full first-pass dataset

```bash
python3 scripts/generate_dataset.py \
  --config config/formal.json \
  --output ~/robocup_assets/datasets/formal_objects_v1
```

The first-pass configuration creates 1,800 training images and 360 validation
images. Every class is the primary subject equally often; half the samples add
a second, different class to exercise multi-object scenes.

Train and independently re-evaluate the first unified model with the dedicated
vision environment:

```bash
~/robocup_training_cuda_venv/bin/python scripts/train_model.py \
  --dataset ~/robocup_assets/datasets/formal_objects_v1 \
  --name formal_objects_v1_yolo11n \
  --device 0
```

The training script refuses to reuse a non-empty run directory and writes
`evaluation.json` with aggregate and per-class precision, recall, mAP50 and
mAP50-95 from the best checkpoint, plus the exact Python, PyTorch, Ultralytics,
CUDA, and GPU identity used. The CUDA training environment is intentionally
separate from `~/robocup_vision_venv`; this offline operation does not mutate
the known-good runtime environment or change the runtime model path.

## Safety boundary

This tool may use Gazebo labels and model poses because it is an offline
training-data generator. Do not copy its label subscriptions, set-pose calls,
world entity names, or class locations into `rgbd_object_localizer` or any
competition runtime node.
