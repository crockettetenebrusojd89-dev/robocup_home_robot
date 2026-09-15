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

## Formal Model V2 targeted pipeline

V2 is an additive, offline-only pipeline. It leaves the V1 world, assets,
dataset, and checkpoint untouched. Its capture plan is completely determined
before Gazebo starts, so a failed or too-small bounding box stops the run
instead of silently resampling an easier pose.

First create the independent asset root. The command refuses an existing
non-empty output, replaces only `beer`, and records archive, per-file, and
per-model-tree SHA256 values in `asset_provenance.json`:

```bash
python3 scripts/prepare_v2_assets.py \
  --source ~/robocup_assets/official_models \
  --beer-zip ~/Downloads/beer.zip \
  --output ~/robocup_assets/official_models_v2
```

The checked teacher asset contract is:

- `beer.zip`: `d4a787f320432ab37a67b81e3b6c175c1863ae8315456c56b9094d26df7396fa`;
- PBR `beer/model.sdf`: `4282a7ae9a064337b1c6a788caa3135e958c93b279f84e6b02ea0e893e0dab4c`;
- `beer.png`: `8109bbef7fedb1adff19a22b16a18647871369ab74cfbfcbf4f5e45973bc5e06`.

Generate and validate the small V2 smoke before any formal run:

```bash
python3 scripts/generate_dataset_v2.py \
  --config config/v2_smoke.json \
  --models ~/robocup_assets/official_models_v2 \
  --output ~/robocup_assets/datasets/formal_objects_v2_smoke

python3 scripts/validate_dataset.py \
  ~/robocup_assets/datasets/formal_objects_v2_smoke

python3 scripts/visualize_labels.py \
  ~/robocup_assets/datasets/formal_objects_v2_smoke \
  --split train \
  --output ~/robocup_assets/datasets/formal_objects_v2_smoke/preview/train_contact_sheet.jpg
```

`v2_smoke.json` and `v2_formal.json` express independent per-class sample,
distance-band, yaw-bin, placement, background, lighting, and secondary-object
policies. The formal configuration is a reviewed 724-image targeted supplement
(570 train, 154 val), not a command to run automatically. It is intended to be
combined later with all V1 replay images that do not contain the legacy beer;
the whole V1 image must be excluded when any old beer label is present.

Each generated image has one `scenario_manifest.jsonl` record containing its
split, immutable scene-group ID, random seed, primary and optional secondary
class plus asset-tree hashes, object poses/yaws, camera pose and distance band,
placement category, background, complete Gazebo light parameters and seed,
YOLO boxes, and final image SHA256. Validation enforces exact configured
quotas, asset identity, class and box consistency, declared empty negatives,
and zero train/val overlap for scene groups, exact images, exact
background-light combinations, and perceptual near-duplicates. It also rejects
beer crops with the legacy near-black failure signature.

After explicit approval, the targeted formal supplement can be generated with:

```bash
python3 scripts/generate_dataset_v2.py \
  --config config/v2_formal.json \
  --models ~/robocup_assets/official_models_v2 \
  --output ~/robocup_assets/datasets/formal_objects_v2_targeted
```

Do not train directly on the targeted supplement: the cleaned 17-class V1
replay must first be composed into the final unified 18-class training dataset.
The unchanged P2 robustness scenes remain an external test gate and must never
be copied into either split.

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
