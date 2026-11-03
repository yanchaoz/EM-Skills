# Project, job and result contracts

Helpers require Python 3.10+ and NumPy. Install Pillow for BMP/PNG, tifffile for TIFF,
and cloud-volume for precomputed delivery in an isolated environment. Backend
environments are separate. See validation.md for tested utility versions.

## Project

Start from ../assets/project.example.json. Paths are relative to the project JSON
unless absolute; the helper never guesses section order from filenames.
`axes: yx` describes each scalar image; physical metadata are XYZ in nanometres.
`group_relationship: independent` must reflect the user's actual grouping.
Every group's explicit sections have unique IDs and contiguous zero-based z_index.
The helper rejects missing indices: represent missing planes with a separately
documented validity mask on a regular grid, or use a backend-specific sparse-Z
adapter. Do not invent biological images or compact the Z axis.

Full input audit decodes every plane, checks shape/dtype and hashes each file.
This costs IO but does not upload or change sources. RGB, nonlinear palettes,
multipage TIFF and nonfinite pixels need an explicit conversion adapter. Scalar
TIFF pages and scalar BMP/PNG/NPY sections are supported. Masks and image intensity
must stay separate. Zero intensity is not automatically invalid.

For very large tiled sections, build a native tile/CloudVolume adapter and manifest
instead of pretending these whole-plane utilities are out-of-core tile engines.
The exporter holds one plane and pyramid working arrays; audit and comparison also
need whole planes in RAM. Estimate this before running.

## Native jobs

A backend contains repository names, local paths and exact 40-character commits,
a Python executable, model file SHA256 entries where applicable, and pilot/full
stage arrays. Each job is:

```json
{
  "argv": ["{python}", "/code/my_sofima_driver.py", "--project", "{project}", "--group", "{group}", "--output", "{run_dir}/native"],
  "cwd": "{run_dir}",
  "expected_outputs": ["{run_dir}/native/result.json"]
}
```

Only project, group, run_dir and python tokens expand. JSON processor arguments
remain single argv entries. No shell interpolation, pipes or shell strings.
Use absolute executable/script paths or a documented PATH.
Expected outputs must be descendants of that group's backend/stage directory.
Commands are trusted code: this validation is not a sandbox and cannot prevent an
incorrect custom driver from writing elsewhere. Review paths before execution.

The helper validates repository HEAD and tracked cleanliness, model hashes, source
hashes, project JSON and external file arguments. It saves ordered-sections.json,
run-identity.json, per-command logs and execution.json. Configuration referenced
indirectly by a driver must be included as an explicit file argument or its
checksum embedded in the project. It does not hash entire runtime environments or
untracked repository files. Record those separately; prefer clean checkouts.
Generated files within run_dir are excluded from command-argument hashing so a
successful run can be resumed. Unchanged identity permits native cache reuse;
changed identity fails. Native commands completed is not scientific acceptance.
Run one writer per run_dir; no distributed lock is provided.

## Result

../assets/result.example.json describes already rendered original intensities.
List all sections in canonical order, shape_zyx, dtype, voxel_size_nm_xyz and
integer voxel_offset_xyz. Each section has a path (relative to the result JSON)
or the manifest has a CloudVolume URL with section IDs/indices. Optional
sha256_pixels uses row-major array bytes, not TIFF-file bytes.
For nonzero offsets, physical voxel centres use the backend's declared centre
convention; the manifest records the grid origin as offset * resolution.

Record native transforms separately with format, direction (source-to-output or
output-to-source), array/component axes, units, map spacing/origin, reference
section and canvas bounds. The generic exporter does not interpret native fields
or meshes, and cannot certify that a result was actually registered. Preserve
backend provenance and human/quantitative QC alongside it.
