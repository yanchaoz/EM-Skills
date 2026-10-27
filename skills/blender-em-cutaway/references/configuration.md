# Project configuration

Use JSON with `schema_version: 1`. Relative paths resolve against the configuration file, not the current working directory. Do not include machine credentials or remote-access details. The bundled source adapter is deliberately limited to local, three-dimensional uint8 TIFF/NPY in explicit ZYX order. Convert other formats only through a separately verified adapter.

The numerical geometry/camera case template is in `assets/project.example.json`. Its crop numbers belong to one example volume and must be replaced for unrelated data. Its explicit display defaults do not reproduce the historical private LUT. For a runnable non-private example, use `make_demo.py` instead.

## Fields

| Section | Fields and meaning |
| --- | --- |
| `source` | `path`, `axis_order: "zyx"`, positive `voxel_size_nm_xyz`, `offset_nm_xyz`, explicit boolean `zero_is_missing` |
| `mesh` | `path` to an existing OBJ, declared `units` (`nm`, `um`, `mm`), `offset_nm_xyz`; mesh coordinates plus offset are global source coordinates |
| `geometry` | `reflect_z`, `basis_rotation_deg`, `outer_uv_bounds_um`, `display_z_bounds_um`, `keep_planes`, `remove_regions` |
| `display` | `normalization`, optional `illumination`, `linear_white_mix`, `emission_power`; these are display-only transforms |
| `camera` | world `location_mm`, XYZ Euler `rotation_euler_rad`, Blender orthographic scale `ortho_scale_mm`; its projected horizontal/vertical span depends on aspect ratio and camera fit |
| `contour` | `mode` (`xray` or `occluded`), `gray_linear`, `alpha_center`, `alpha_edge`, `roughness`, `emission` |
| `render` | `[width,height]` `resolution`, `samples`, `device`, `tile_size`, `density_per_mm`, `step_um` |
| `output_dir` | derived output root; must not alias or contain input source/mesh files; explicit preparation outputs have the same restriction |

## Coordinate contract

For source indices `(x,y,z)` and physical offsets `o` and voxel sizes `s` in nm:

```text
X = ox + x*sx
Y = oy + y*sy
Z = oz + z*sz
pivotZ = 2*oz + (nz-1)*sz
Z_display = pivotZ - Z       # only when reflect_z is true
```

No axis is stretched. The VDB stores unit-grid IJK values, with a single array-order change from ZYX to XYZ for the VDB API. The Blender volume object supplies the declared anisotropic scale and physical offset. An OBJ is converted from its declared unit to global nm, then reflected around the identical pivot; reflection reverses face winding.

Clip coordinates use **display-space global micrometers**. Given `theta = basis_rotation_deg`:

```text
U = cos(theta)*X_um + sin(theta)*Y_um
V = -sin(theta)*X_um + cos(theta)*Y_um
```

UV rotation defines a local crop frame; it does not rotate or resample EM voxels. A plane `{ "coeff_uvz": [a,b,c], "threshold_um": t }` evaluates `a*U+b*V+c*Z_display`.

- A `keep_plane` retains values `>= t`.
- All planes within one `remove_regions` entry must be `> t` to remove a voxel. Multiple regions form a union of cuts.
- `only_below_v_um`, when present on a keep plane, exempts points at or beyond that V. This can create a discontinuity at the exemption boundary; use only intentionally and inspect the seam.
- The outer UV and display-Z limits apply in addition to the planes.

Two cuts generally produce three exposed height levels. A floor is a physical plane, not an ordinal slice guessed from an image. If using a native slice center, derive the floor from its index and the physical transform above. Array bounds and camera geometry must be checked before interpreting scale bars.

## Display and missing data

`normalization.mode` is `none` or `per_slice_percentile`; percentile mapping uses the declared valid support. The preparation manifest records the actual mapping and validation scope. Optional bounded illumination correction estimates a low-frequency field and clips its gain; it is not spatial interpolation or inpainting of EM structures. Preserve original samples for audit.

The support grid is distinct from intensity. If `zero_is_missing: true`, original zero samples remain unsupported. If false, zero is a valid black intensity and must not be deleted. Dark positive values remain supported in either case. Setting a white-mix display floor does not grant permission to change support.

## Cache identity

Preparation writes `volume.vdb` and `manifest.json`. The manifest binds source/mesh hashes, shape, physical sampling, display transformation, transform convention and VDB identity. A render must reject a mismatched cache. The manifest's `transform` records preparation-time provenance; a new render computes its transform from the current explicitly selected Z direction. The full native cache is independent of clipping and reflection, so these can change without rebuilding it. The included renderer rejects pruned caches. Do not infer compatibility from filenames alone.
