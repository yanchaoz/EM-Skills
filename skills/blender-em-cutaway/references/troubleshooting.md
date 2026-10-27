# Troubleshooting source-aligned EM cutaways

Diagnose before editing. A request to explain a dark region or missing corner does not authorize a repair. Freeze the approved image, camera, crop, display mapping and mesh while testing one suspected cause at a time. Keep the source read-only.

## A dark band, hole or apparent missing strip

Start with an EM-only pass and the original volume at the same coordinates. Then compare support, clipping and display effects:

| Candidate cause | Discriminating check | Safe response after authorization |
| --- | --- | --- |
| Source coverage is absent | Read native samples and the dataset's missing-data contract; inspect neighboring Z and the relevant XZ/YZ section | Keep missingness visible or choose a different complete cut plane; do not invent tissue |
| Signal exists but is dark | Report raw percentiles and positive/zero counts in the region and adjacent context | Use a documented global display rule or change the exposed plane; do not equate weak signal with no data |
| Cut geometry removed real tissue | Evaluate the exact keep/remove half-spaces and compare visibility with cuts disabled | Adjust the relevant plane or scope; verify added/removed visibility on every Z layer |
| A brightness threshold erased valid tissue | Compare raw support with the rendering support/opacity rule | Separate occupancy from tone; use the declared validity rule rather than a convenient gray cutoff |
| UV or coordinate mapping is wrong | Compare identifiable native features, physical bounds, mesh bounds and transformed axes | Correct the shared mapping; do not conceal the error with texture offsets or a local warp |
| Illumination or shading causes the band | Compare the source, mapped intensity, EM-only pass and combined pass with one effect disabled | Adjust display settings only; record gain bounds and unchanged source coordinates |
| A cache no longer contains newly exposed data | Compare cache coverage with the revised cut plus interpolation/ray support margin | Rebuild a sufficient source-derived cache; a missing cache sample is not evidence of missing acquisition |

Map the marked screen position back to a ray or an appropriate native section rather than choosing a visually similar patch. If a screen pixel integrates multiple samples, do not describe it as one uniquely identified raw voxel. Quantify only the region actually checked.

Zero can be a valid intensity. Do not use `raw > 0` universally: it is appropriate only when a documented source convention makes zero a missing-value sentinel. A no-zero ROI proves coverage under that rule, not correct segmentation, registration or tissue identity.

## The object looks upside down, stretched or detached

- List array axis order, voxel spacing in XYZ, origin/offset and mesh units. Shape alone cannot establish correspondence.
- Check known landmarks in native XY/XZ/YZ. Distinguish an in-plane camera rotation from a top/bottom reversal.
- For a requested Z reflection, apply the same physical pivot and transform to volume and mesh. A handedness-changing transform requires checking mesh winding and normals.
- Keep separate records for source axes, the local crop basis and screen axes. A cut parallel to the local block edge can be oblique to the original image X/Y axes.
- Check voxel-center versus voxel-edge conventions. An index difference times spacing is a center-to-center distance; it may not equal a displacement between differently defined clip boundaries.

Do not stretch one axis to imitate the visual thickness of a reference. Camera elevation, viewing direction and relative scale can explain perceived thickness without changing physical geometry. If actual registration is wrong, report it and request a separate registration task.

## The figure looks flat, too thick or over-cropped

First inspect the uncropped volume bounds and physical aspect ratio. Keep a fixed physical scale while testing camera elevation and azimuth. Showing a top face and two genuine side faces usually provides more depth cues than a top-only view. Retain sufficient peripheral EM around the target to make the full data context legible.

Use a small number of coherent steps rather than many thin terraces when the goal is a concise figure. Ensure cut planes belong to a named physical basis, not screen-space diagonal bands. A local cut need not remove an entire quadrant of the stack. Save the amount and location removed; “conservative” must be supported by an explicit mask or volume comparison.

Do not adjust camera, crop and material simultaneously when the user approved all but one. Render a comparison using the approved camera and mapping so a local correction can be evaluated independently.

## A restored side strip looks pasted on

A strip can use genuine source voxels and still be discontinuous: elevating it beside a deeper floor introduces a new vertical wall. Widening the strip only moves that wall. Changing brightness cannot restore geometric continuity.

If a shared continuous face is required, choose one native depth across the neighboring core and context region, subject to source coverage and user intent. Keep valid original coordinates everywhere. This changes cut geometry and may require permission to alter the previously approved floor or boundary. Do not hide the depth change behind feathering, blending unrelated slices or synthetic inpainting.

Validate the entire proposed exposed ROI, not just a few attractive patches. Inspect neighboring slices because volume interpolation/ray integration may use them. Preserve the distinction between the full-plane coverage audit and sampled cache-value checks.

## A small corner or wedge protrudes from the outer edge

Inspect conditional geometry. A keep plane that applies only below a local coordinate threshold creates a transition edge where its exemption begins. The resulting corner can resemble missing or damaged acquisition even when native data exist.

Compare the old and proposed half-spaces at every native Z. If extending the same plane is the intended correction, verify that the change only removes the authorized wedge, adds no tissue, preserves the rear frame and leaves internal steps unchanged. Report the removed positive-voxel count and its denominator. Removing tissue from display is not modifying the source, but it is still a meaningful crop that must be disclosed.

Do not diagnose such a corner solely from a white-background screenshot. A raw acquisition gap, source-support threshold and conditional clip boundary require different treatments.

## The complete white contour is unclear

First determine whether the requested display is ordinary depth occlusion, hidden-edge lines, or a complete x-ray contour overlay. These are different visual claims. In x-ray mode, the visible contour may include geometry behind opaque EM.

Inspect a contour-only pass and check normals before changing opacity. Modest view-dependent opacity, surface roughness and soft directional illumination can strengthen shape without black outlines or changing geometry. Avoid saturation that erases internal texture. Keep complete mesh coordinates and the EM pass fixed when the request is material-only. Do not silently adopt preview variants that the user paused or rejected.

## GPU failure or Windows CUDA timeout

A large volume with long per-tile kernels can exceed the display-driver watchdog interval even when total VRAM seems adequate. Confirm the actual error and whether Blender is still running before launching another GPU render. Avoid concurrent preview renders on a small GPU.

Use a bounded fallback sequence:

1. Preserve the last valid output and the error log; do not call a partially written file complete.
2. Retry one small preview with a smaller render tile and unchanged scientific geometry.
3. Reduce preview resolution/samples or explicitly select CPU rendering; restore the documented final settings once stable. Do not silently switch the compute device.
4. A source-derived visibility cache with verified interpolation margin is a possible advanced extension, but is **not supported by this bundled pipeline**: preparation produces a full native cache and rendering rejects pruned caches. Do not set `geometry_pruned=false` to bypass this safeguard.

In the motivating case a 4 GB GPU failed with a large uncut cache and 256-pixel tiles; smaller tiles and a verified bounded cache worked. These observations are not hardware-independent defaults. Do not change OS watchdog/security settings, install drivers or kill unrelated processes merely to complete a render.

## Verification language and exact local revisions

- Say whether checks are full-volume, full-ROI, per-layer geometry comparisons, or sampled. Do not convert “no error found in a sample” into “all voxels verified.”
- Save input hashes, the effective display/crop configuration, cache identity, camera, passes, raw render and output manifest. A hash establishes identity, not biological correctness.
- Compare all supposedly frozen settings programmatically. Check EM-only and contour-only passes as well as the composite.
- Independent renders can differ outside a changed region because of stochastic sampling or denoising. If the requirement is exact unchanged pixels, use only a justified same-coordinate preservation mask and check its seam. Keep the full rerender and the mask, and disclose the final as a local composition.
- Never use preservation masks to disguise an inadequate rerender, crop that exceeds scope, offset texture paste, new anatomical content or missing-data fill. Avoid calling a composed delivery an untouched single render.
- Successful rendering is not visual QA. Inspect the whole frame, changed boundary and neighboring texture at useful magnification before delivery.

See the [case record](case-study.zh-CN.md) for one evidence-backed revision sequence and the [quality gates](quality-gates.md) for delivery checks.
