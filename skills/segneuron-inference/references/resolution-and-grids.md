# Resolution and grid contract

Read this file before selecting a model resolution or resampling any artifact.

## Axis convention

Configuration vectors use `zyx` order unless a field explicitly says otherwise. `source.axis_order` describes on-disk array axes and must contain each spatial axis exactly once. Convert metadata to canonical `zyx` before planning.

Store:

- `shape_zyx`: voxel counts;
- `resolution_nm_zyx`: voxel size in nm;
- `offset_vox_zyx`: voxel-space origin;
- `bbox_vox_zyx`: half-open `[z0,y0,x0,z1,y1,x1]` bounds.

Physical extent is `shape * resolution`. Planning computes the model shape by rounding physical extent divided by target resolution. Record residual end-bound error; do not silently crop a neuron to make a tile grid divide evenly.

## Choosing the model grid

The official SegNeuron repository describes generalization to unseen 3D EM data with approximately 5–10 nm x/y sampling. Its listed datasets contain substantially anisotropic z sampling. Treat that range as a model-profile clue, not a universal conversion command.

For each pinned checkpoint, record a profile containing:

- supported and validated x/y range;
- preferred x/y target, if known;
- z policy: preserve, bounded range, or explicit target;
- expected intensity polarity and normalization;
- inference patch and halo constraints;
- evidence source and date.

Default to `z_policy: preserve`. Any z resampling requires a model-profile instruction or pilot evidence.

## Interpolation

Raw EM intensity:

- downsampling: area/box or antialiased linear method;
- upsampling: linear or cubic only if validated;
- preserve intensity polarity and document clipping/normalization.

Affinities:

- keep native model-grid affinities whenever possible;
- use continuous interpolation only when a consumer explicitly requires another grid;
- preserve channel meaning and range.

Instance labels:

- nearest-neighbor only;
- never blur, average, or cast through floating point unnecessarily;
- compare nonzero ID sets before and after mapping;
- record IDs lost because an object is smaller than the delivery voxel.

## Tile and halo rules

Distinguish patch size, output core, and halo. A tile covers `core + 2*halo`; only the core is committed directly. At global boundaries, record padding. For affinities, blend overlapping predictions with deterministic weights. For instances, do not crop away all overlap before reconciliation.

Tile starts must be computed from the global model-grid origin, not independently per worker. Every tile manifest entry includes global half-open read bounds, core bounds, output URI, status, and checksum.

## Transform checks

Before execution:

1. Transform the eight bounding-box corners from source to model physical coordinates.
2. Verify monotonic axes and positive voxel sizes.
3. Compare source and model physical end bounds against `planning.max_end_error_nm`.
4. Round-trip representative coordinates and report maximum error.
5. Confirm the delivery volume restores the source resolution and offset when requested.

No affine with rotation or shear should be inferred from voxel sizes alone. If acquisition registration includes rotation/shear, require an explicit 4×4 physical transform and a resampler that supports it.
