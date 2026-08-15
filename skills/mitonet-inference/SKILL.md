---
name: mitonet-inference
description: Work with MitoNet/Empanada for mitochondrial semantic and 3D instance segmentation in electron microscopy. Use when a task involves auditing EM metadata, planning or preparing the model grid, running MitoNet or MitoNet-mini, comparing inference profiles, inspecting semantic foreground or instance outputs, stack matching or orthoplane consensus, restoring labels to the source grid, creating mitochondrial overlays and continuity figures, or verifying a MitoNet result. Supports a single requested stage as well as end-to-end pilot and inference runs. Do not use for fluorescence MitoSegNet, neuron segmentation, classification, or model training.
---

# MitoNet Inference

Use this Skill as a task-routed capability pack. Execute only the stages required for the requested outcome and reuse existing raw, semantic, instance, configuration, or QC artifacts when available.

## Route the request

| User intent | Use this capability | Load when needed |
| --- | --- | --- |
| Inspect data or metadata | `audit` | [config schema](references/config-schema.md) |
| Select scale, plane, or estimate a run | `plan` | [model contract](references/model-contract.md) |
| Resample raw data for the model | `prepare` | [model contract](references/model-contract.md) |
| Test or run MitoNet | `pilot` or `infer` | [deployment](references/deployment.md), [model contract](references/model-contract.md) |
| Compare scales, thresholds, or matching settings | `profile-sweep`; select only after review | [quality gates](references/quality-gates.md) |
| Inspect an existing mask or segmentation | visualization and relevant verification only | [quality gates](references/quality-gates.md) |
| Restore or package labels | `restore`, `verify`, or `finalize` as requested | [quality gates](references/quality-gates.md) |

For an end-to-end segmentation request, use `audit → plan → prepare → pilot/profile-sweep → select-profile → infer → restore → verify → finalize`. Pause at profile selection unless the user already supplied a profile. Do not require the full chain for visualization, auditing, or diagnosis.

## Preserve the model contract

Keep these artifacts distinct:

```text
source raw -> model-grid raw -> semantic/center/offset predictions
           -> per-plane instances -> 3D stack matching or orthoplane consensus
           -> source-grid labels -> QC/proofreading
```

- Use the MitoNet model distributed through Empanada; do not confuse it with similarly named fluorescence or connectomics projects.
- MitoNet is a 2D panoptic model. Describe 3D instances as the result of slice matching and, when used, orthoplane consensus.
- Never call a semantic foreground mask an instance segmentation.
- Track axes, voxel size, offset, physical bounds, source identity, model revision, checkpoint checksum, and runtime.
- Use continuous interpolation for raw intensities and nearest-neighbor interpolation for labels.
- Preserve source data and write derived artifacts beneath a separate `output.root`.

Read [model contract](references/model-contract.md) before choosing MitoNet versus MitoNet-mini, target pixel size, inference plane, or postprocessing parameters.

## Use the orchestrator

Run commands from the Skill directory:

```powershell
python scripts/mitonet_pipeline.py scaffold project.yaml
python scripts/mitonet_pipeline.py audit project.yaml
python scripts/mitonet_pipeline.py plan project.yaml
python scripts/mitonet_pipeline.py prepare project.yaml
python scripts/mitonet_pipeline.py pilot project.yaml
python scripts/mitonet_pipeline.py profile-sweep project.yaml
python scripts/mitonet_pipeline.py select-profile project.yaml --profile stack-balanced
python scripts/mitonet_pipeline.py infer project.yaml
python scripts/mitonet_pipeline.py restore project.yaml
python scripts/mitonet_pipeline.py verify project.yaml
python scripts/mitonet_pipeline.py finalize project.yaml
```

`prepare`, `pilot`, `profile-sweep`, `infer`, and `restore` are dry runs unless `--execute` is supplied. Review generated arguments, working directory, source/output separation, expected artifacts, and pinned model identity before execution.

Start new projects from `assets/project.example.yaml`. Read [config schema](references/config-schema.md) before changing fields or command templates. Use `scripts/mitonet_adapter.py` to invoke the pinned official `scripts/pdl_inference3d.py`; do not reimplement MitoNet inside the Skill.

## Compare profiles

Use named profiles to freeze scale, model variant, inference mode, thresholds, matching, consensus, and object filters. Write each candidate to a separate path. Compare the same XY slices plus XZ/YZ continuity when z extent permits.

Inspect false positives on ER/Golgi/vesicles, missed low-contrast mitochondria, merges between apposed objects, elongated-object oversplits, pancakes, boundary truncation, and topology through z. Do not rank candidates from object count or foreground fraction alone.

Ask the user to choose unless they delegated selection under explicit criteria or supplied a profile. `select-profile` records the configuration digest; changing the configuration invalidates the selection.

## Visualize existing or new results

```powershell
python scripts/mitonet_visualize.py `
  --raw derived/raw-model-grid.tif `
  --instances derived/instances-model-grid.tif `
  --resolution-nm-zyx 50 16 16 `
  --output-stem derived/qc/mitonet-summary
```

The renderer creates raw, semantic foreground, instance overlay, and orthogonal-continuity panels plus JSON metrics. Do not rerun inference when the user only requests a figure from existing artifacts.

## Verify in proportion to the request

- For a pilot, cover difficult mitochondria, crowded regions, similar-texture membranes, low contrast, artifacts, and enough z extent to judge continuity.
- For orthoplane consensus, inspect each plane before trusting the consensus, especially with strong anisotropy.
- For restored labels, verify shape, dtype, label set, voxel size, offset, and physical bounds.
- For final delivery, read [quality gates](references/quality-gates.md) and include the frozen configuration, provenance, executed commands, QC figures, limitations, and relevant intermediate artifacts.
- With ground truth, report semantic and instance metrics separately at declared thresholds. Without ground truth, report integrity and manual-review evidence, not accuracy.

## Fail closed for scientific claims

Stop a dependent stage when axes, voxel size, bounds, source identity, model revision, or checkpoint checksum is unresolved; source and output overlap; a chosen scale/plane lacks pilot evidence; label capacity may overflow; restoration changes physical bounds; or severe false positives, merges, topology loss, or seams remain. A display-only task may proceed if its limitations are stated and no missing metadata are fabricated.
