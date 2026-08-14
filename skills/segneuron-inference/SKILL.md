---
name: segneuron-inference
description: Audit, plan, deploy, and verify SegNeuron-based 3D neuron instance segmentation for volume electron microscopy. Use for FIB-SEM, SBF-SEM, ATUM-SEM, ssTEM, CloudVolume/precomputed, Zarr, N5, TIFF, or NumPy volumes when the task includes physical-resolution adjustment, SegNeuron affinity inference, foreground-restricted instance postprocessing, blockwise execution, mapping labels back to the source grid, or segmentation quality control. Do not use for organelle segmentation, manual proofreading alone, or model training unless explicitly extended.
---

# SegNeuron Inference

Build a reproducible path from a source EM volume to affinity maps and globally coherent neuron instance labels. Treat metadata, a pilot ROI, beta selection, and final verification as approval gates—not optional reporting.

## Non-negotiable model contract

SegNeuron is an affinity-first pipeline. Keep these artifacts distinct:

```text
source raw -> model-grid raw -> affinity maps -> FRMC instances
           -> source-grid instances -> verified delivery
```

Never describe affinity output as final neuron instances. Never interpolate instance IDs with a continuous-image interpolator.

Manage three explicit grids:

- `source_grid`: native data resolution, offset, axes, and bounds;
- `model_grid`: data presented to the pinned SegNeuron checkpoint;
- `delivery_grid`: grid used for measurement or publication, normally the source grid.

Read [references/resolution-and-grids.md](references/resolution-and-grids.md) completely before choosing a target resolution or performing any resampling.

## Core workflow

1. Preserve the source. Write every derived artifact beneath a separate `output.root`.
2. Create a project configuration from `assets/project.example.yaml`. Read [references/config-schema.md](references/config-schema.md) completely for the field contract.
3. Run `audit`. Stop if voxel size, axis order, bounds, source identity, checkpoint identity, or output separation is unresolved.
4. Run `plan`. Review the source-to-model transform, output shape, tile count, overlap, disk estimate, and selected execution mode.
5. Run `pilot` on representative ROIs before any full-volume job. Include difficult membranes, dense neurites, a large profile, and low-contrast or artifact-prone regions where available.
6. Run `infer` to produce affinities. Use a pinned repository commit, checkpoint checksum, and command represented as an argument list. Generate job specifications first; add `--execute` only after reviewing them.
7. When `instance.beta_sweep` is configured, run `beta-sweep` to generate every candidate, create a comparison plate with `segneuron_visualize.py beta-sweep`, and ask the user to choose. Do not optimize or select beta silently.
8. Run `select-beta --beta VALUE` to record the human choice, then run `instance` with the frozen `{selected_beta}`.
9. If instances were generated per block, reconcile them into globally unique and continuous IDs. Do not finalize independent per-block IDs. Read [references/instance-stitching.md](references/instance-stitching.md) completely.
10. Run `restore` with nearest-neighbor label resampling or an explicit external restoration command. Preserve source resolution, offset, and physical bounds.
11. Run `verify`, inspect orthogonal overlays, and record split, merge, seam, fragment, dtype, bounds, and provenance checks.
12. Run `finalize` only after all required gates pass. Deliver configurations and evidence with the volumes.

## Commands

Use the bundled orchestrator from the skill directory:

```powershell
python scripts/segneuron_pipeline.py scaffold project.yaml
python scripts/segneuron_pipeline.py audit project.yaml
python scripts/segneuron_pipeline.py plan project.yaml
python scripts/segneuron_pipeline.py pilot project.yaml
python scripts/segneuron_pipeline.py infer project.yaml
python scripts/segneuron_pipeline.py infer project.yaml --execute
python scripts/segneuron_pipeline.py beta-sweep project.yaml
python scripts/segneuron_pipeline.py beta-sweep project.yaml --execute
python scripts/segneuron_pipeline.py select-beta project.yaml --beta 0.25
python scripts/segneuron_pipeline.py instance project.yaml --execute
python scripts/segneuron_pipeline.py restore project.yaml --execute
python scripts/segneuron_pipeline.py verify project.yaml
python scripts/segneuron_pipeline.py finalize project.yaml
```

`infer`, `beta-sweep`, `instance`, and `restore` are dry-run operations unless `--execute` is supplied. Dry-run writes rendered job specifications without invoking third-party code. `select-beta` accepts only a configured beta whose candidate outputs exist.

Create a four-panel raw/affinity/membrane/instance figure after postprocessing:

```powershell
python scripts/segneuron_visualize.py summary `
  --raw derived/raw-model-grid.tif `
  --affinities derived/affinities.npy `
  --membrane derived/boundaries.tif `
  --instances derived/instances-model-grid.npy `
  --resolution-nm-zyx 50 8 8 `
  --output-stem derived/qc/segneuron-summary
```

For beta comparison, repeat `--instance BETA=PATH` for every candidate and optionally mark the recorded selection with `--selected-beta`. The renderer exports PNG, SVG, and PDF by default, uses deterministic label colors, preserves physical aspect ratio, and adds calibrated scale bars.

## Resolution rules

- Require physical voxel size in nanometres; never infer it from array shape.
- Select `target_resolution_nm` from the pinned model profile and pilot evidence, not from a universal hard-coded number.
- Preserve z anisotropy by default. Changing z requires an explicit profile rule and recorded rationale.
- Compute shapes from physical extents. Report rounding and end-bound differences.
- Use continuous interpolation only for raw intensities or affinities.
- Use nearest-neighbor interpolation for labels and validate the set of IDs after restoration.
- Record source-to-model and model-to-delivery transforms in the plan artifact.

## Deployment rules

Read [references/deployment.md](references/deployment.md) completely before running a remote, scheduled, or full-volume job.

- Pin the SegNeuron repository commit, checkpoint path, checkpoint SHA-256, and runtime identity.
- Keep weights, environments, credentials, and datasets outside the skill package.
- Prefer argument-list commands such as `["python", "inference.py", "--config", "{config_path}"]`; do not use shell strings.
- Keep command working directories explicit.
- Make jobs resumable and idempotent. A completed artifact must not be silently overwritten.
- Store logs, rendered commands, timestamps, host/backend identity, exit code, and checksums under `output.root`.
- The bundled runner implements local execution. For SSH or Slurm, generate a reviewed adapter/job script from the documented contract rather than embedding credentials.

## Pilot gate

A pilot passes only when all required items are documented:

- source and model-grid orthogonal views align physically;
- affinity channels have plausible membrane/adjacency signal and no gross seams;
- instances follow neurites through z, rather than merely looking plausible in XY;
- obvious merge, split, fragment, and foreground leakage cases are reviewed;
- parameters are frozen in the project configuration before full execution;
- estimated storage and runtime fit the selected backend.

If a pilot fails, revise the resolution/normalization/model profile or stop. Do not hide failure through more aggressive instance merging.

## Instance scope

Use `instance.scope: whole-volume` for a pilot or a volume whose complete affinities fit the postprocessor. Use `per-block` only with:

- overlap/halo retained through postprocessing;
- a configured global reconciliation step;
- deterministic global ID assignment;
- seam-focused verification.

The orchestrator marks per-block output as non-final until `instance.global_reconciliation.completed` is true and its artifact exists.

## Beta selection gate

Configure at least two unique values strictly between 0 and 1 under `instance.beta_sweep.values`. The external `commands.beta_sweep` adapter must write separate candidate outputs using `{beta}` and `{beta_tag}` placeholders. Review the same physical slices across candidates and consider merges, splits, fragments, neurite continuity through z, and foreground leakage. The selected beta is a dataset- and checkpoint-specific postprocessing parameter, not a transferable accuracy claim.

`select-beta` writes `_segneuron_skill/beta-selection.json` with the configuration digest and selected candidate. If the configuration changes, the selection becomes invalid and the comparison must be repeated. The final `commands.instance` adapter receives `{selected_beta}` and `{selected_beta_tag}`.

## Verification and delivery

Read [references/quality-gates.md](references/quality-gates.md) completely before approving or delivering a result.

Minimum delivery:

- source identity and metadata snapshot;
- frozen project configuration;
- resolution and tiling plan;
- pilot record;
- affinity volume or durable reference to it;
- model-grid instance volume;
- source-grid/delivery instance volume;
- model commit, checkpoint checksum, environment identity, and command logs;
- automated verification report and orthogonal-view contact sheet;
- known limitations and sampled manual-review decisions.

When ground truth is available, report split and merge components separately using an adapted Rand/VI-style evaluation. When it is absent, use documented stratified ROI review and do not substitute instance-size histograms for segmentation accuracy.

## Stop conditions

Stop and report the blocker when any of these is true:

- resolution, axis order, offset, or bounds are missing or contradictory;
- a checkpoint or repository revision is mutable or unidentified;
- source and output paths overlap;
- target resolution lies outside the documented model profile without an explicit pilot decision;
- expected instance count can overflow the configured label dtype;
- a transform changes physical bounds beyond configured tolerance;
- per-block instances lack a global reconciliation artifact;
- verification finds unresolved severe seams, catastrophic merges, or topology loss.

## Bundled resources

- `scripts/segneuron_pipeline.py`: configuration validation, grid planning, dry-run/execute adapters, state gates, verification, and delivery manifest.
- `scripts/segneuron_visualize.py`: professional raw/affinity/membrane/instance plates and beta-sweep overlays.
- `assets/project.example.yaml`: starter project configuration.
- `references/config-schema.md`: complete configuration contract.
- `references/resolution-and-grids.md`: physical-grid and interpolation rules.
- `references/deployment.md`: pinned environments, job generation, remote adapters, and recovery.
- `references/segneuron-adapter.md`: safe integration contract for the current research-code entry points.
- `references/instance-stitching.md`: blockwise instance reconciliation contract.
- `references/quality-gates.md`: pilot, full-run, and delivery acceptance checklist.
