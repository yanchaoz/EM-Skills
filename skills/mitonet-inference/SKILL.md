---
name: mitonet-inference
description: Audit, plan, deploy, visualize, and verify MitoNet/Empanada mitochondrial semantic and 3D instance segmentation for electron microscopy. Use for FIB-SEM, SBF-SEM, ATUM-SEM, ssTEM, TIFF, NumPy, Zarr, or CloudVolume data when the task includes physical-resolution adjustment, MitoNet or MitoNet-mini inference, stack or orthoplane consensus, threshold/profile comparison, source-grid label restoration, remote or air-gapped GPU execution, proofreading preparation, or mitochondrial segmentation QC. Do not use for fluorescence MitoSegNet, mitochondrial classification, neuron segmentation, or model training unless explicitly extended.
---

# MitoNet Inference

Build a fail-closed path from volume EM to mitochondrial semantic masks and globally coherent 3D instances. Use the MitoNet model distributed through Empanada; do not confuse it with similarly named fluorescence or PyTorch-Connectomics projects.

## Model contract

Keep the stages and artifacts distinct:

```text
source raw -> model-grid raw -> 2D semantic/center/offset predictions
           -> per-plane 2D instances -> stack matching or orthoplane consensus
           -> source-grid labels -> QC/proofreading -> verified delivery
```

MitoNet is a 2D panoptic model. A 3D result is produced by Empanada's slice matching and, optionally, consensus across `xy`, `xz`, and `yz`. Never describe a semantic foreground mask as an instance segmentation.

Read [references/model-contract.md](references/model-contract.md) before selecting MitoNet versus MitoNet-mini, a target pixel size, an inference mode, or postprocessing parameters. Read [references/config-schema.md](references/config-schema.md) before editing a project configuration.

## Workflow

1. Preserve the source and write all derivatives beneath a separate `output.root`.
2. Scaffold a project, then record source axes, shape, voxel size, offset, bounds, and immutable identity.
3. Pin the official Empanada repository commit, model variant, model file, and SHA-256. Keep code, weights, environments, data, and credentials outside the skill.
4. Run `audit` and stop on missing or contradictory metadata.
5. Run `plan`; review physical extents and the source-to-model transform. Do not assume one universal MitoNet pixel size.
6. Run `prepare` to create model-grid raw data using continuous interpolation. Preserve z by default for anisotropic stack inference.
7. Run a representative pilot. Test difficult mitochondria, crowded regions, membranes with similar texture, low contrast, and artifacts.
8. Configure two or more named inference profiles when parameters are uncertain. Run `profile-sweep`, render identical slices, and ask the user to select a profile. Do not select from object count alone.
9. Run `select-profile --profile NAME`, then `infer`. Use stack inference for strongly anisotropic data unless orthogonal views are demonstrably useful; use orthoplane consensus only after plane-wise review.
10. Restore labels with nearest-neighbor interpolation, generate QC figures, and record semantic and instance checks separately.
11. Run `verify` and `finalize` only after human review and all required gates pass.

## Commands

```powershell
python scripts/mitonet_pipeline.py scaffold project.yaml
python scripts/mitonet_pipeline.py audit project.yaml
python scripts/mitonet_pipeline.py plan project.yaml
python scripts/mitonet_pipeline.py prepare project.yaml
python scripts/mitonet_pipeline.py prepare project.yaml --execute
python scripts/mitonet_pipeline.py pilot project.yaml
python scripts/mitonet_pipeline.py profile-sweep project.yaml
python scripts/mitonet_pipeline.py profile-sweep project.yaml --execute
python scripts/mitonet_pipeline.py select-profile project.yaml --profile stack-balanced
python scripts/mitonet_pipeline.py infer project.yaml --execute
python scripts/mitonet_pipeline.py restore project.yaml --execute
python scripts/mitonet_pipeline.py verify project.yaml
python scripts/mitonet_pipeline.py finalize project.yaml
```

`prepare`, `pilot`, `profile-sweep`, `infer`, and `restore` are dry-run unless `--execute` is supplied. The runner executes argument lists without a shell and records rendered commands, logs, expected outputs, timestamps, and configuration hashes.

Use the official-code adapter after reviewing its generated job:

```powershell
python scripts/mitonet_adapter.py `
  --repo external/empanada `
  --model-config external/MitoNet_v1.yaml `
  --checkpoint external/MitoNet_v1.pth `
  --input derived/raw-model-grid.tif `
  --output derived/instances-model-grid.tif `
  --mode stack --median-kernel 3 --seg-thr 0.3 `
  --center-thr 0.1 --center-min-distance 3 `
  --merge-iou 0.25 --merge-ioa 0.25 `
  --min-size 500 --min-span 4
```

The adapter invokes the pinned official `scripts/pdl_inference3d.py`; it does not reimplement MitoNet.

## Profile selection gate

Each `inference.profiles` entry freezes the model grid, model variant, inference mode, thresholds, matching, consensus, and object filters. Profile candidates must use separate output paths via `{profile}`. Review raw overlays on the same XY slices and, for 3D data, XZ/YZ continuity. Selection writes `_mitonet_skill/profile-selection.json` with the configuration digest. A configuration change invalidates the selection.

Do not interpret “more instances” or “larger foreground fraction” as better. Inspect false positives on ER/Golgi/vesicles, missed low-contrast mitochondria, merges between apposed mitochondria, oversplits of elongated mitochondria, pancakes, boundary truncation, and topology through z.

## Visualization and QC

```powershell
python scripts/mitonet_visualize.py `
  --raw derived/raw-model-grid.tif `
  --instances derived/instances-model-grid.tif `
  --resolution-nm-zyx 50 16 16 `
  --output-stem derived/qc/mitonet-summary
```

The renderer produces a raw/foreground/instance-overlay/orthogonal-continuity plate plus JSON metrics. When ground truth exists, evaluate semantic IoU/Dice and instance precision/recall or F1 at declared IoU thresholds separately. Without ground truth, report only integrity and manual-review evidence; morphology distributions are not accuracy metrics.

Read [references/quality-gates.md](references/quality-gates.md) before approving a pilot or delivery. Read [references/deployment.md](references/deployment.md) before remote, scheduled, or air-gapped execution.

## Stop conditions

Stop and report the blocker when:

- voxel size, axis order, bounds, source identity, repository commit, or model checksum is unresolved;
- target pixel size or inference plane is chosen without pilot evidence;
- source and output paths overlap;
- orthoplane inference is requested for strongly anisotropic data without plane-wise review;
- the maximum label count can exceed the configured dtype or label divisor;
- restoration changes physical bounds or interpolates IDs continuously;
- a profile has not been explicitly selected;
- severe false positives, catastrophic merges, topology loss, or unresolved seams remain;
- the pilot lacks enough z extent to assess 3D continuity.

## Bundled resources

- `scripts/mitonet_pipeline.py`: audit, grid plan, dry-run/execute jobs, profile selection, verification, and delivery manifest.
- `scripts/mitonet_adapter.py`: pinned official Empanada CLI adapter and provenance recorder.
- `scripts/mitonet_visualize.py`: calibrated raw/mask/instance/orthogonal QC plate.
- `assets/project.example.yaml`: starter configuration.
- `references/model-contract.md`: official MitoNet/Empanada evidence and parameter semantics.
- `references/config-schema.md`: complete project field contract.
- `references/deployment.md`: remote and air-gapped execution contract.
- `references/quality-gates.md`: pilot and delivery acceptance checklist.
