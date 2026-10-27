# Operations

## Runtime

Use an existing Python environment with NumPy, Pillow, tifffile and (for illumination correction) SciPy. VDB preparation additionally requires an OpenVDB Python module compatible with that Python interpreter; Blender rendering requires Blender and its `bpy` runtime. Do not assume that a system Python, Blender Python and an OpenVDB binary have interchangeable ABIs.

The pipeline was developed from a Blender 4.5 workflow. Record the version actually tested in your environment. No runtime, private scene, datasets or native binaries are bundled. Check existing runtimes first; dependency installation or remote execution is outside an ordinary figure edit unless authorized. If OpenVDB is unavailable, report the prerequisite instead of substituting a stack of textured planes and claiming it is equivalent native volume rendering.

Commands below run from the skill directory. Replace `python` and `blender` with verified executables. Use a new output directory for each revision. Put large caches and renders in the project's designated data storage.

## Small synthetic smoke test

```bash
python scripts/make_demo.py --out /work/cutaway-demo
python scripts/audit_cutaway.py --config /work/cutaway-demo/project.json --out /work/cutaway-demo/audit.json
python scripts/prepare_volume.py --config /work/cutaway-demo/project.json --output /work/cutaway-demo/prepared
blender --background --python-exit-code 1 --python scripts/render_blender.py -- --config /work/cutaway-demo/project.json --cache /work/cutaway-demo/prepared/volume.vdb --output /work/cutaway-demo/render --size 256 --samples 4 --device CPU --save-blend
```

Inspect the resulting EM-only, contour and composite views, not only the exit code. The fixture is a technical coordinate/volume test, not an EM specimen or biological validation. Do not upload private project data to replace the synthetic fixture.

## Real project

1. Copy the example JSON and replace source, units, offsets, camera and crop values using actual metadata. Establish zero-value semantics and alignment before preparation.
2. Run native-plane audit on candidate slice indices. For a crop revision, compare the new configuration against the approved one. Inspect full-grid versus sampled scope in the report.
3. Prepare a cache or verify an existing cache's source/display/grid identity. Do not overwrite original data.
4. Render a small preview first. Preserve the accepted camera and material for geometry-only revisions. Use the requested CPU/GPU device; on a small Windows GPU reduce tiles/samples before escalating compute or changing data resolution.
5. Inspect the full frame and local regions. Export high resolution only after resolving actual continuity/geometry issues.

Example native slice audit and configuration comparison:

```bash
python scripts/audit_cutaway.py --config project.json --slices 24 138 245 --out native-plane-audit.json
python scripts/audit_cutaway.py --config revised.json --compare approved.json --out geometry-delta.json
```

The slice indices above are illustrative, not defaults for another volume.

`--compare` reports native geometry deltas and separately lists changes to the Z display direction, camera, contour, display, mesh mapping and render settings. A zero geometry delta alone does not mean the figure is unchanged. Review every field expected to stay frozen, including command-line render overrides in the actual render manifest. The bundled audit reports whole selected XY planes; specific ROIs, XZ/YZ evidence and mesh-bound plots require additional read-only diagnostics appropriate to the source.

The renderer explicitly uses world-space volume sampling so native-grid object scaling does not scale physical step size/density twice. Inspect `volume_sampling_space`, `actual_step_mm` and `camera_projection` in the completed render manifest. Always check `status: complete`, expected files and the process exit code; use Blender's `--python-exit-code 1` for script failures.

## Calibrated scale bar

```bash
python scripts/annotate_scale.py --image render/render.png --render-manifest render/render_manifest.json --length-um 10 --out annotated
```

Choose a meaningful length for the actual data, not the example's 10 um. The tool uses Blender's actual orthographic camera frame, supports non-square images, verifies the image hash/dimensions, and records pixel rounding. It does not accept resized, cropped or otherwise changed render inputs. This is a camera-plane scale, not a foreshortened X/Y/Z ruler. Inspect placement for overlap; keep the original unannotated render. Pillow >= 10.1 provides the built-in scalable font; otherwise pass an explicit TrueType `--font`.

## Pixel comparison and narrow revisions

```bash
python scripts/verify_export.py compare --before approved.png --after rerender.png --out comparison.json
python scripts/verify_export.py preserve --before approved.png --after rerender.png --rectangle 850 316 1008 597 --tolerance 2 --out local-delivery
python scripts/verify_export.py manifest --files project.json render.png scene.blend --out delivery-manifest.json
```

`preserve` is optional and requires a justified same-coordinate region. The rectangle must come from the changed geometry's projection plus a documented margin, not from a desire to conceal unrelated changes. It writes `preserved.png`, `mask.png` and a verification report, rejects substantial changes outside/boundary, and keeps both inputs untouched. Keep the raw full rerender as well. A composed image must be disclosed as such.

## Tests and practical limits

```bash
python -m unittest discover -s tests -v
```

Unit tests do not replace the Blender smoke render. Optional dependency skips must be reported as skips. The real source-case audit is separate from the synthetic tool tests; do not extrapolate its slice counts, offsets or geometry thresholds to another dataset. Do not report successful VDB preparation alone as successful rendering.

See the [validation record](validation.md) for the tested runtime and explicit coverage limits.

For export, preserve editable `.blend`, configuration, VDB/mesh dependencies or their verified locations, original render passes, final figure, source identities and review notes. A final PNG is raster even if embedded inside an SVG. Do not describe embedded microscopy as vector-resolution imagery.
