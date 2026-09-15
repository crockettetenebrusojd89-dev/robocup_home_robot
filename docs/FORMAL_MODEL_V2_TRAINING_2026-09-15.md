# Formal Model V2 Training and Candidate Selection — 2026-09-15

## Scope and verdict

One and only one formal 18-class V2 fine-tune was run from the V1 `best.pt`.
The unchanged competition runtime and the P1/P2 Gazebo external gate were not
touched. Synthetic evidence supports advancing the checkpoint saved after
human epoch 31 (`epoch30.pt`, whose internal epoch field is zero-based) to the
external gate first. The epoch-40 Ultralytics `best.pt` is the only backup.

## Inputs and environment

- Dataset: `~/robocup_assets/datasets/formal_objects_v2` (2,219 train, 481 val)
- Validation partitions: 327 legacy, 144 targeted-positive, 10 negative
- Dataset validation: all composition, leakage, old-beer, corrected-beer,
  quota, pairing, and empty-negative gates passed immediately before training
- Starting checkpoint:
  `~/robocup_assets/training_runs/formal_objects_v1_yolo11n/weights/best.pt`
- Starting SHA256:
  `d9f73d0a2037212bafca6adf818e0cf82921f6112bdb92b930633d6ba034d69f`
- Python 3.10.12; torch 2.14.0+cu130; torchvision 0.29.0+cu130;
  CUDA build 13.0; Ultralytics 8.4.142
- GPU: NVIDIA GeForce RTX 4060 Laptop GPU, 8,188 MiB total VRAM; driver
  580.178.04
- Free disk before training: 337 GiB
- Training script: `tools/formal_dataset/scripts/train_model.py` in the commit
  containing this report

The loader used a symlink-only view under `~/robocup_assets/training_views`, so
Ultralytics cache files were not written into the immutable composed dataset.
No package, CUDA, PyTorch, or Ultralytics upgrade was performed.

## Training smoke

- Output: `~/robocup_assets/training_runs/formal_objects_v2_yolo11n_finetune_smoke`
- Duration recorded by the trainer: 36.80 seconds
- Parameters: the formal configuration below, except `epochs=1`
- Peak allocated/reserved GPU memory: 1,187,301,888 / 1,514,143,744 bytes;
  trainer display peaked near 1.25 GiB
- Result: PASS; all train/val images, empty negative labels, four workers,
  CUDA, checkpoint output, and provenance output worked without OOM

Ultralytics performed a one-time AMP compatibility check that downloaded a
5.3 MB `yolo26n.pt`; it was not used as initialization or training input, and
the duplicate created by this work was removed. The only other warning was a
future Pillow `getdata()` deprecation in the dataset validator.

## Formal configuration

| Parameter | Value |
|---|---:|
| model | V1 `best.pt` |
| epochs / patience | 40 / 10 |
| batch / workers / device | 8 / 4 / 0 |
| image size | 640 |
| optimizer | AdamW |
| lr0 / lrf | 0.0005 / 0.1 |
| schedule | cosine |
| weight decay | 0.0005 |
| warmup | 2.0 epochs |
| HSV h/s/v | 0.01 / 0.4 / 0.3 |
| translate / scale | 0.1 / 0.25 |
| mosaic / close mosaic | 0.5 / final 5 epochs |
| horizontal / vertical flip | 0.0 / 0.0 |
| multi-scale | false |
| save period | 5 |
| seed / deterministic | 0 / true |
| explicit freeze | none |

The 0.0005 initial learning rate is deliberately conservative for an AdamW
fine-tune from a strong V1 checkpoint with replay data. Mild augmentation adds
variation without duplicating the strong Gazebo-side domain randomization or
mirroring object text. Batch 8 retains the already proven V1 memory margin.

Ultralytics reports one frozen parameter,
`model.23.dfl.conv.weight`. Version 8.4.142 unconditionally freezes this fixed
DFL integral projection, which is initialized to `[0..15]` with
`requires_grad_(False)`; no backbone, classification/regression convolution,
or learned detection-head parameter was explicitly frozen. The model reported
2,593,334 gradients out of 2,593,350 parameters.

## Training result

- Output: `~/robocup_assets/training_runs/formal_objects_v2_yolo11n_finetune`
- Training duration: 639.06 seconds (10 minutes 39 seconds)
- Completed epochs: 40; best epoch: 40
- Best: `weights/best.pt`; last: `weights/last.pt`
- `best.pt` and `last.pt` contain identical values for all 499 model tensors
- Periodic files: `epoch0.pt`, `epoch5.pt`, `epoch10.pt`, `epoch15.pt`,
  `epoch20.pt`, `epoch25.pt`, `epoch30.pt`, and `epoch35.pt`. Ultralytics uses
  zero-based filenames/metadata, so these follow human epochs 1, 6, 11, 16,
  21, 26, 31, and 36.
- Train box/class/DFL loss moved from 0.4891/0.6292/0.8071 to
  0.2844/0.2400/0.7671. Validation box/class/DFL moved from
  0.4711/0.5355/0.8014 to 0.3159/0.2674/0.7771.
- Train and validation losses declined together while mAP50-95 continued to
  improve through epoch 40. There is no obvious synthetic overfit signal.

The exact args, input hashes, runtime, GPU memory, and output hashes are in
`training_provenance.json`; `results.csv` and `results.png` contain the full
curve.

## Corrected subset evaluation

Official evidence root:
`~/robocup_assets/training_runs/formal_objects_v2_checkpoint_evaluations_corrected`

An initial evaluator result tree is retained with suffix
`_invalid_map_index`. It is not valid evidence: a missing-class subset exposed
that Ultralytics uses compact indices for P/R/mAP50 but full class IDs for
mAP50-95. The mapping was corrected, regression-tested, and every checkpoint
below was re-evaluated from scratch.

### Aggregate comparison

| Checkpoint | Human epoch | Overall P/R/mAP50/mAP50-95 | Legacy P/R/mAP50/mAP50-95 | Targeted P/R/mAP50/mAP50-95 | Negative FP |
|---|---:|---|---|---|---:|
| V1 best | 20 | .910/.878/.915/.848 | .979/.971/.982/.927 | .732/.729/.713/.594 | 0 |
| `epoch20.pt` | 21 | .983/.974/.985/.930 | .984/.973/.985/.937 | .955/.863/.917/.839 | 0 |
| `epoch30.pt` | 31 | .982/.980/.987/.945 | .989/.979/.986/.951 | .952/.870/.965/.908 | 0 |
| `epoch35.pt` | 36 | .987/.980/.987/.942 | .993/.977/.985/.950 | .966/.865/.965/.884 | 0 |
| V2 `best.pt` | 40 | .988/.979/.986/.943 | .991/.981/.984/.950 | .965/.857/.965/.895 | 0 |

### Targeted key classes

| Checkpoint / class | Precision | Recall | mAP50 | mAP50-95 |
|---|---:|---:|---:|---:|
| V1 / banana | .996 | .917 | .983 | .716 |
| V1 / beer | 1.000 | .000 | .013 | .005 |
| V1 / master_chef_can | .928 | .630 | .896 | .778 |
| Main epoch 31 / banana | 1.000 | .973 | .995 | .826 |
| Main epoch 31 / beer | .995 | 1.000 | .995 | .975 |
| Main epoch 31 / master_chef_can | .928 | 1.000 | .995 | .959 |
| Main epoch 31 / coke_can | .995 | 1.000 | .995 | .837 |
| Main epoch 31 / pudding_box | 1.000 | .979 | .995 | .902 |
| Main epoch 31 / tomato_soup_can | 1.000 | .949 | .995 | .878 |
| Backup epoch 40 / banana | 1.000 | .976 | .995 | .828 |
| Backup epoch 40 / beer | .997 | 1.000 | .995 | .957 |
| Backup epoch 40 / master_chef_can | .934 | 1.000 | .995 | .943 |
| Backup epoch 40 / coke_can | 1.000 | .900 | .995 | .828 |
| Backup epoch 40 / pudding_box | 1.000 | .964 | .995 | .903 |
| Backup epoch 40 / tomato_soup_can | 1.000 | .923 | .995 | .876 |

### Stable-class regression and negatives

Across the 12 stable classes on legacy val, the class-macro averages were:

| Checkpoint | Precision | Recall | mAP50 | mAP50-95 |
|---|---:|---:|---:|---:|
| V1 best | .986 | .979 | .987 | .931 |
| Main epoch 31 | .989 | .987 | .989 | .954 |
| Backup epoch 40 | .989 | .987 | .988 | .955 |

For the main candidate, every stable-class recall was equal to or above V1;
the largest mAP50 decrease was chips_can at -1.02 percentage points and the
largest mAP50-95 decrease was cracker_box at -0.43 points. For the backup,
every stable recall and mAP50-95 was equal or improved; chips_can mAP50 was
-1.98 points. No stable-class metric crossed the -2 percentage-point warning
line.

At the fixed runtime confidence 0.50, V1 and all four V2 checkpoints produced
zero detections on all 10 negative images: detection count 0, FP image count 0,
no FP classes, and no FP confidences.

## Candidates

### Main — human epoch 31

- Path:
  `~/robocup_assets/training_runs/formal_objects_v2_yolo11n_finetune/weights/epoch30.pt`
- SHA256:
  `c16f5332221649fdb89c225f9aaec6f73db97e2590bc37734a6d0e0a5099564c`
- Not Ultralytics `best.pt`; saved after human epoch 31
- Rationale: all weak-class recalls are at least .973, beer and master are
  1.000, all three borderline recalls are at least .949, targeted mAP50-95 is
  the best evaluated value (.908), negative FP is zero, and stable classes show
  no >2-point regression.

### Backup — human epoch 40

- Path:
  `~/robocup_assets/training_runs/formal_objects_v2_yolo11n_finetune/weights/best.pt`
- SHA256:
  `0aa4fc5032f5543d72c8c75fcde5034925f209fad5c2c31a6a827cf816d1906a`
- Ultralytics `best.pt`; human epoch 40
- Rationale: comparable aggregate and weak-class evidence, slightly higher
  banana recall, zero negative FP, and no stable regression. It is kept only as
  a fallback because targeted coke_can recall (.900) is materially below the
  main candidate (1.000).

## Competition decision

V2 is clearly better than V1 on this synthetic evidence, especially corrected
beer and master_chef_can. The weak classes justify external testing, stable
classes show no material forgetting, and the fixed-confidence negative gate is
clean. No second training run is justified. The next work should run the main
epoch-31 checkpoint through the unchanged P1/P2 competition-domain Gazebo gate
first; evaluate the epoch-40 backup there only if the main result is ambiguous
or fails. Synthetic evidence alone does not close P-001.
