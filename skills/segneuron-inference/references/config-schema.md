# Project configuration schema

The orchestrator accepts YAML when PyYAML is available and JSON everywhere. Paths are resolved relative to the configuration file unless documented as a URI.

## Required top-level sections

### `project`

- `id`: stable, filesystem-safe project identifier.
- `description`: optional human context.

### `source`

- `uri`: local path or remote dataset URI. Local paths are checked during audit.
- `format`: `tiff`, `npy`, `zarr`, `n5`, `cloudvolume-precomputed`, or `other`.
- `axis_order`: on-disk spatial axis order, normally `zyx` or `xyz`.
- `shape_zyx`: positive integers.
- `resolution_nm_zyx`: positive physical voxel sizes.
- `offset_vox_zyx`: integer origin; defaults to `[0,0,0]`.
- `bbox_vox_zyx`: optional half-open bounds; defaults to the complete shape.
- `read_only`: must be true.
- `identity`: immutable identifier such as dataset version, object generation, or source checksum.

### `model`

- `repository`: normally `yanchaoz/SegNeuron`.
- `repo_path`: local checkout used by the external command.
- `repo_commit`: pinned full or unambiguous commit.
- `checkpoint`: path to weights.
- `checkpoint_sha256`: expected 64-character checksum.
- `profile.target_resolution_nm_zyx`: target model-grid voxel size.
- `profile.validated_xy_nm`: inclusive `[minimum, maximum]` range.
- `profile.z_policy`: `preserve` or `explicit`.
- `profile.normalization`: documented normalization name or mapping.
- `profile.patch_zyx`: inference patch from the pinned runtime configuration.
- `profile.halo_zyx`: nonnegative halo.

### `planning`

- `tile_core_zyx`: positive core size written per tile.
- `max_end_error_nm`: allowed physical end-bound discrepancy.
- `pilot_rois`: list of source-grid half-open bboxes.
- `estimated_bytes_per_affinity_voxel`: default 12 for three float32 channels.
- `estimated_bytes_per_instance_voxel`: default 8 for uint64 labels.

### `commands`

Each operation contains:

- `argv`: argument list, never a shell command string;
- `cwd`: explicit working directory;
- `env`: optional non-secret environment mapping;
- `expected_outputs`: files or directories required after success.

Supported placeholders include `{config_path}`, `{output_root}`, `{plan_path}`, `{source_uri}`, `{checkpoint}`, and `{repo_path}`. `commands.beta_sweep` additionally receives `{beta}` and filesystem-safe `{beta_tag}`; `commands.instance` receives `{selected_beta}` and `{selected_beta_tag}` when a sweep is configured. Unknown placeholders fail before execution.

Operations are `infer`, `beta_sweep`, `instance`, `reconcile`, and `restore`. An empty operation remains a documented manual gate and cannot be executed by the bundled runner.

### `instance`

- `method`: normally `frmc` for the official repository postprocessor.
- `scope`: `whole-volume` or `per-block`.
- `label_dtype`: `uint32` or `uint64`.
- `background_id`: must normally be 0.
- `beta_sweep.values`: optional list of at least two unique values strictly between 0 and 1. Each value creates a separate candidate; the orchestrator never chooses automatically.
- `global_reconciliation.required`: true for `per-block`.
- `global_reconciliation.completed`: false until a reconciliation job succeeds.
- `global_reconciliation.artifact`: global label volume or reconciliation manifest.

### `output`

- `root`: derived output directory; must not be equal to or inside a local source directory.
- `affinity_uri`: expected affinity location.
- `instance_model_grid_uri`: model-grid instance output.
- `instance_source_grid_uri`: restored delivery output.
- `allow_overwrite`: defaults to false.

### `verification`

- `required_artifacts`: paths required by `verify`.
- `ground_truth_uri`: optional reference labels.
- `manual_sample_count`: positive count when ground truth is absent.
- `severe_issue_count`: updated by review; must be zero to finalize.
- `pilot_approved`: explicit approval recorded after pilot review.
- `checks`: mappings for bounds, dtype, seams, IDs, and provenance.

## State artifacts

The orchestrator writes under `output.root/_segneuron_skill/`:

- `audit.json`
- `plan.json`
- `pilot.json`
- `beta-sweep.json`
- `beta-selection.json`
- `jobs/*.json`
- `runs/*.json`
- `verification.json`
- `delivery-manifest.json`
- `state.json`

These are derived records. Do not edit them to bypass a gate; update the source configuration and rerun the relevant stage.
