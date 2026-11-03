# Google SOFIMA

Official [repository](https://github.com/google-research/sofima) and
[EM alignment notebook](https://github.com/google-research/sofima/blob/c8b5e254a9b031a9c00f3d399e47bafda3c96a22/notebooks/em_alignment.ipynb).
Software citation: Januszewski, Blakely and Lueckmann (2024),
[DOI 10.5281/zenodo.10534541](https://doi.org/10.5281/zenodo.10534541).
License: Apache-2.0. Pin the revision in upstreams.json.

SOFIMA exposes Python APIs; this skill does not invent a universal SOFIMA CLI.
Adapt the official notebook into a dataset driver and pass its argv to the harness.
Install the pinned checkout in a JAX-compatible environment; verify device
availability and log package versions before choosing batch size.

## Native pipeline

1. Read the ordered sections for one group. Retain native images and separate
   matching images/masks. Estimate reliable translation/rotation or affine
   initialization when displacement exceeds the local matcher search range.
2. Use `flow_field.JAXMaskedXCorrWithStatsCalculator().flow_field(prev, curr,
   (patch, patch), (stride, stride), batch_size=...)`. Choose patch and stride
   in pixels at the matching level, and record their physical sizes.
3. Preserve peak statistics and apply `flow_utils.clean_flow` and
   `flow_utils.reconcile_flows` as appropriate. Track valid coverage and rejected
   vectors; filling every missing vector without evidence can deform blank regions.
4. Construct a mesh with `mesh.IntegrationConfig`; compose maps using
   `map_utils.compose_maps_fast` and relax with `mesh.relax_mesh`.
   Save maps, energies, iteration counts and convergence criteria.
5. Invert when required with `map_utils.invert_map`, then render through
   `warp.warp_subvolume` using the composed map and original intensities.

The notebook's settings (for example patch 160, stride 40, peak thresholds and
integration coefficients) are examples, not a validated native-resolution preset.
Inspect the exact notebook and installed function signatures before implementing
the driver; do not assume this API sketch is a complete stack script.

## Coordinates and boundaries

SOFIMA maps use relative coordinate offsets. Record component order, array axes,
map-grid spacing and map origin independently of image shape. A transpose between
channels/Z/Y/X and Y/X is not a physical coordinate transform.
Use a synthetic known translation to establish direction and sign before applying
a map to an expensive volume.

The patch grid does not reach all source edges. Padding absolute coordinates with
clamped edge values can collapse borders. If using an affine continuation outside
the reliable grid, document it and initialize the mesh consistently. Such
extrapolation is a model assumption, not measured correspondence.

Estimate transformed bounds, preserve negative origin, test local orientation,
inverse consistency and displaced-border coverage, then render once into the
common union canvas. Do not repeatedly resample each intermediate registration.
Reject nonconverged or folded regions rather than calling them successful solely
because the solver returned. See quality.md.
