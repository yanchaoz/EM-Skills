---
name: segneuron-inference
description: Work with SegNeuron outputs and pipelines for 3D neuron instance segmentation in volume electron microscopy. Use when a task involves auditing EM volume metadata, planning a physical-resolution transform, generating or inspecting SegNeuron affinities, reconstructing instances with FRMC, comparing beta candidates, stitching blockwise labels, restoring labels to the source grid, producing raw/affinity/membrane/instance visualizations, or verifying a SegNeuron result. Supports both a single requested stage and an end-to-end pilot or inference run. Do not use for organelle segmentation or model training.
---

# SegNeuron Inference

Treat this Skill as a set of SegNeuron capabilities, not as a requirement to run a fixed pipeline. Identify the user's requested outcome and execute the smallest valid set of stages. Reuse existing configurations and artifacts when they are supplied.

## Route the request

| User intent | Use this capability | Load when needed |
| --- | --- | --- |
| Inspect a dataset or diagnose metadata | `audit` | [config schema](references/config-schema.md), [resolution and grids](references/resolution-and-grids.md) |
| Choose the model grid or estimate a run | `plan` | [resolution and grids](references/resolution-and-grids.md) |
| Test a checkpoint on a small ROI | `pilot`, then requested inference/QC stages | [deployment](references/deployment.md), [adapter](references/segneuron-adapter.md) |
| Generate affinities | `infer` | [deployment](references/deployment.md), [adapter](references/segneuron-adapter.md) |
| Compare reconstruction parameters | `beta-sweep`, visualization, `select-beta` only after a user choice | [quality gates](references/quality-gates.md) |
| Generate or repair instances | `instance`; add reconciliation only for blockwise outputs | [instance stitching](references/instance-stitching.md) |
| Make a figure from existing arrays | `segneuron_visualize.py`; do not rerun inference | None unless metadata are unclear |
| Restore, verify, or package a result | `restore`, `verify`, or `finalize` as requested | [quality gates](references/quality-gates.md) |

For an end-to-end segmentation request, use `audit → plan → pilot → infer → beta-sweep → select-beta → instance → restore → verify → finalize`, inserting `reconcile` before `restore` for blockwise instances. Pause at beta selection unless the user already supplied a beta. Do not impose this complete sequence on a narrower request.

## Preserve the model contract

Keep artifacts and grids explicit:

```text
source raw -> model-grid raw -> affinities -> FRMC instances
           -> reconciled instances -> source/delivery-grid instances
```

- Never call affinities final neuron instances.
- Track `source_grid`, `model_grid`, and `delivery_grid` with axes, voxel size, offset, shape, and physical bounds.
- Use continuous interpolation for raw intensities and affinities; use nearest-neighbor interpolation for instance IDs.
- Preserve source data. Write derived artifacts beneath a separate `output.root`.
- Pin the SegNeuron revision, checkpoint identity and SHA-256, runtime, and command arguments for executed inference.
- Treat independent per-block IDs as non-final until deterministic global reconciliation completes.

Stop before a dependent stage when required metadata, model identity, artifact identity, or physical-grid consistency is unresolved. A visualization-only request may still proceed if the provided arrays can be displayed honestly without inventing missing physical metadata.

## Use the orchestrator

Run commands from the Skill directory:

```powershell
python scripts/segneuron_pipeline.py scaffold project.yaml
python scripts/segneuron_pipeline.py audit project.yaml
python scripts/segneuron_pipeline.py plan project.yaml
python scripts/segneuron_pipeline.py pilot project.yaml
python scripts/segneuron_pipeline.py infer project.yaml
python scripts/segneuron_pipeline.py beta-sweep project.yaml
python scripts/segneuron_pipeline.py select-beta project.yaml --beta 0.25
python scripts/segneuron_pipeline.py instance project.yaml
python scripts/segneuron_pipeline.py reconcile project.yaml
python scripts/segneuron_pipeline.py restore project.yaml
python scripts/segneuron_pipeline.py verify project.yaml
python scripts/segneuron_pipeline.py finalize project.yaml
```

`pilot`, `infer`, `beta-sweep`, `instance`, `reconcile`, and `restore` generate reviewed job specifications by default. Add `--execute` only when the user requested execution and the inputs, outputs, and command have been checked. Do not overwrite a completed artifact silently.

Start new projects from `assets/project.example.yaml`. Read [config schema](references/config-schema.md) before changing fields or templated commands.

## Compare beta candidates

Configure at least two unique beta values between 0 and 1. Generate each candidate at a separate path and compare identical physical slices, including z continuity. Show merge, split, fragmentation, foreground leakage, seam, and topology evidence; never select beta from instance count alone.

Ask the user to choose unless they delegated selection under a stated criterion or supplied a beta. Record the choice with `select-beta`; a configuration change invalidates the recorded choice.

## Visualize existing or new results

Create a calibrated four-panel plate:

```powershell
python scripts/segneuron_visualize.py summary `
  --raw derived/raw-model-grid.tif `
  --affinities derived/affinities.npy `
  --membrane derived/boundaries.tif `
  --instances derived/instances-model-grid.npy `
  --resolution-nm-zyx 50 8 8 `
  --output-stem derived/qc/segneuron-summary
```

Use `segneuron_visualize.py beta-sweep` with repeated `--instance BETA=PATH` arguments for beta comparison. Preserve physical aspect ratio and report when resolution or axes are assumed rather than verified.

## Verify in proportion to the request

- For a pilot, inspect orthogonal alignment, affinity plausibility, neurite continuity through z, representative failure modes, seams, storage, and runtime before scaling up.
- For blockwise instances, verify overlap handling, global ID uniqueness, reconciliation evidence, and seams.
- For restored labels, verify shape, dtype, ID set, voxel size, offset, and physical bounds.
- For a final delivery, read [quality gates](references/quality-gates.md) and include configuration, provenance, logs, QC figures, known limitations, and the relevant intermediate artifacts.
- With ground truth, report split and merge components separately using declared metrics. Without it, report stratified manual review as QC, not accuracy.

## Fail closed for scientific claims

Do not approve or finalize a result when physical metadata are contradictory, model/checkpoint identity is mutable, source and output overlap, label dtype may overflow, physical bounds drift beyond tolerance, blockwise labels are unreconciled, or severe seams/merges/topology loss remain. Report the blocking evidence and the next safe action.
