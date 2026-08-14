# Project configuration schema

Paths are resolved relative to the configuration file unless they are explicit URIs.

## Required sections

### `project`

- `id`: filesystem-safe stable identifier.

### `source`

- `uri`, `format`, `axis_order`, `shape_zyx`, `resolution_nm_zyx`, `offset_vox_zyx`, and half-open `bbox_vox_zyx`.
- `read_only`: must be true.
- `identity`: immutable version or checksum.

### `model`

- `repository`: official source repository.
- `repo_path`: external pinned checkout.
- `repo_commit`: exact 40-character commit.
- `variant`: `MitoNet_v1` or `MitoNet_v1_mini`; record quantization separately when used.
- `model_config` and `model_config_sha256`.
- `checkpoint` and `checkpoint_sha256`.
- `target_resolution_nm_zyx`: model-grid sampling.
- `z_policy`: `preserve` or `explicit`; preserve is the default for anisotropic stack inference.

### `planning`

- `pilot_rois`: source-grid half-open bounding boxes.
- `max_end_error_nm`: allowed physical end-bound rounding discrepancy.

### `inference`

- `profiles`: two or more named parameter mappings when comparison is needed.
- `orthoplane_reviewed`: must be true before orthoplane profiles are accepted for strongly anisotropic data.

Each profile requires `mode`, `median_kernel`, `segmentation_confidence`, `center_confidence`, `center_min_distance`, `merge_iou`, `merge_ioa`, `pixel_vote`, `cluster_iou`, `allow_one_view`, `fine_boundaries`, `min_size_vox`, `min_span_slices`, `label_divisor`, and a power-of-two `downsample_factor`.

### `commands`

Each adapter contains `argv`, `cwd`, optional non-secret `env`, and `expected_outputs`. Commands are argument lists, never shell strings. Common placeholders are `{config_path}`, `{output_root}`, `{skill_path}`, `{repo_path}`, `{model_config}`, and `{checkpoint}`. Profile jobs additionally receive `{profile}` and `{profile_FIELD}`. Final inference receives `{selected_profile}`.

### `output`

- `root`: separate local derived-output directory.
- `raw_model_grid_uri`, `instance_model_grid_uri`, and `instance_source_grid_uri`.
- `allow_overwrite`: false by default.

### `verification`

- `required_artifacts`, `pilot_approved`, `severe_issue_count`, and declared boolean `checks`.

## State artifacts

The orchestrator writes beneath `output.root/_mitonet_skill/`: `audit.json`, `plan.json`, `pilot.json`, `profile-sweep.json`, `profile-selection.json`, rendered jobs, run logs, `verification.json`, `delivery-manifest.json`, and `state.json`.
