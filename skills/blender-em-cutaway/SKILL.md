---
name: blender-em-cutaway
description: Build or revise source-aligned Blender visualizations of EM volumes with contour meshes and conservative stepped cutaways. Use for full-volume scientific figures, native-data continuity checks, crop or orientation diagnostics, and narrowly scoped render changes; not segmentation inference or generative image repair.
---

# Blender EM cutaway

Render real EM voxels and an existing contour mesh in one physical coordinate frame. Deliver an editable scene, traceable display settings, and inspected figure exports. A visually plausible surface is not proof of source continuity or segmentation correctness.

## Start with the requested scope

- For a question about an artifact, inspect the source and render/crop rules first. Diagnosis alone does not authorize a repair.
- For an existing approved figure, freeze camera, physical scale, accepted crop, display mapping and contour material. Change only the requested subset. Preserve the approved files.
- For a new figure, confirm axis order, voxel size, offsets, mesh units, source alignment and which end of Z is intended at the top. Do not infer units from appearance or make a thin volume look thicker by stretching it.
- If source registration is wrong, report it; this skill does not silently register, warp, remesh or synthesize data.

Read [configuration](references/configuration.md) before constructing a project. Read [operations](references/operations.md) for commands and dependencies. For an existing defect, read [troubleshooting](references/troubleshooting.md). The [case record](references/case-study.zh-CN.md) explains the observed failures and accepted revisions of one project, not universal rendering defaults.

## Physical and scientific invariants

1. Keep the source read-only. Hash inputs; record native shape, axis order, physical sampling and offsets separately from display choices.
2. Reflect Z, when requested, on both volume and mesh around the same physical pivot. Reverse mesh winding when the transform changes handedness. Never independently transpose or scale the two sources.
3. Separate occupancy from brightness. Zero means missing only when the source contract declares it. Do not turn dark but valid tissue transparent or fill an acquisition gap to improve the figure.
4. Treat percentile normalization, low-frequency illumination gain, opacity and lighting as display transformations. Record them, retain unmodified source evidence, and avoid regional intensity switches or interpolation of missing tissue.
5. Express cutaways as physical planes, independent of the camera. Inspect native XY/XZ/YZ evidence and exposed slice indices. A true shared cut face samples one depth across adjacent regions, not a collection of independently elevated strips.
6. Preserve requested tissue context and the complete contour. Distinguish an x-ray contour overlay from ordinary depth occlusion; label the display mode. Do not imply a visible contour in an overlay is exposed EM tissue.

## Working sequence

Use the existing stages that match the task; do not rerun expensive work merely to follow a sequence.

1. **Audit.** Load source metadata and mesh coordinates; compare physical bounds. Use native-plane statistics to distinguish zero coverage, dark signal, cut geometry and rendering effects. Record uncertainty where coverage has only been sampled.
2. **Define a conservative cut.** Start from the approved geometry or requested reference. A small number of axis-aligned local steps often communicates depth better than many terraces. Choose exposed planes using source evidence and user intent, not fixed example slice numbers.
3. **Prepare a display cache.** Preserve native IJK sampling. Verify grid values against the source/display rule and keep intensity and support grids separate. A cache can be reused after a stricter cut only if it contains all newly visible/interpolated samples.
4. **Render a bounded preview.** Use Blender, not image generation, for geometry or EM changes. Inspect both EM-only and composite views. Check top/bottom direction, perimeter completeness, visible XZ/YZ depth, cut-face continuity and contour visibility.
5. **Iterate narrowly.** A geometry defect cannot be solved by painting a texture, and a material issue does not justify recropping the volume. Compare revisions at the same camera and display settings. Seek direction when the necessary change exceeds the requested scope.
6. **Verify and export.** Inspect the full image plus enlarged defect regions. Save source/cache identities, clip and camera settings, raw render passes, scene, final PNG and checks. If preserving unchanged pixels from an approved render, use a justified same-coordinate mask, verify the seam and disclose the composition; never represent it as a single untouched render.

The included tools support local uint8 ZYX TIFF/NPY inputs. Other storage formats require an explicitly verified adapter before use. They do not download data, install Blender, launch remote jobs, or authorize publication.

## Tools and acceptance

- `scripts/make_demo.py`: create a small, explicitly synthetic technical fixture, not biological evidence.
- `scripts/prepare_volume.py`: prepare native display/support VDB grids and source verification.
- `scripts/audit_cutaway.py`: inspect native planes or compare clipping masks.
- `scripts/render_blender.py`: construct a portable Blender scene from data/configuration, rather than depend on an old private `.blend`.
- `scripts/verify_export.py`: compare same-coordinate exports, preserve authorized local revisions, and write file manifests.
- `scripts/annotate_scale.py`: add an audited camera-plane scale bar from an actual orthographic render projection, preserving the raw image.

Run the focused tests and a small Blender smoke render before applying the workflow to a large new dataset. Inspect the rendered result; successful execution alone does not establish visual or scientific quality. Report which checks were full-volume, sampled, skipped, or unsupported. Read [quality gates](references/quality-gates.md) before delivery.
