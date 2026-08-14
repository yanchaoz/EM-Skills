# Project configuration

Use `assets/project.example.json` as the starting point. JSON is recommended for portability; YAML is accepted when PyYAML exists.

## Required sections

### `project`

- `id`: stable project identifier.
- `purpose`: human-readable annotation goal.

### `source`

- `uri`: immutable or resolvable source location. Prefer absolute paths, versioned object-store URIs, or CloudVolume URLs.
- `dataset_key`: HDF5/Zarr dataset key when applicable.
- `axes`: must be exactly `zyx` at the selector boundary.
- `shape_zyx`: source size in voxels.
- `voxel_size_nm_zyx`: physical voxel spacing in nanometers.
- `dtype`: expected raw type.
- `source_sha256`: strongly recommended for local immutable files. Replace placeholders before production.

### `embedding`

- `model_repository`, `model_commit`, `checkpoint_name`, `checkpoint_sha256`: immutable encoder provenance.
- `dimension`: embedding columns; 80 for the audited official checkpoint.
- `normalization`: record the exact intensity transform.

### `tiling`

- `patch_shape_zyx`, `stride_zyx`: must match embedding inference.
- `boundary_mode`:
  - `valid`: only full patches; safest default.
  - `align_end`: append an end-aligned patch; creates a nonuniform final stride.
  - `reflect`: reproduce a reflected padded grid only when inference used the identical padding.

### `selection`

- `budget_subvolumes`: number of draft suggestions.
- `window_patches_zyx`: contiguous patch-grid window per candidate.
- `expected_subvolume_shape_zyx`: optional hard check. Derived as `patch + stride × (window − 1)`.
- `k_neighbors`: CCR neighborhood size, including the query patch itself.
- `metric`: `euclidean` matches the main published method; `cosine` is a documented variant.
- `disallow_patch_overlap`: normally true.
- `max_exact_patches`: fail-closed scale gate for O(N²) exact neighbors.
- `max_working_memory_mib`: block-memory cap, not a time cap.

### `guards`

- `excluded_bboxes_zyx`: artifact, missing-tissue, already-labeled, or forbidden regions.
- `holdout_bboxes_zyx`: validation/test regions that may never enter the annotation queue.
- Bounding boxes are half-open `[[z0,y0,x0],[z1,y1,x1]]` in source voxel coordinates.
- `minimum_split_gap_voxels_zyx` is documentary in version 0.1; expand holdout boxes before planning when a gap is required.

## Embedding order contract

The selector assumes row `i` in `embeddings.npy` corresponds to `patches[i]` and that `patch_id == i`. Never sort or filter either side independently. If an adapter emits positions, join by exact `(z,y,x)` coordinates and verify one-to-one coverage before writing the NumPy array.
