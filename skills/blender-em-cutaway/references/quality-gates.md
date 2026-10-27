# Quality gates

## Before rendering

- Native axis order and XYZ voxel sizes/offsets are explicit. The bundled adapter accepts uint8 ZYX TIFF/NPY; it fails rather than guessing channels, time or axes.
- Source and output paths cannot alias. Input hashes remain unchanged.
- Mesh units and offsets are known; raw data and mesh have overlapping physical bounds. Geometric overlap alone does not prove registration: inspect representative aligned sections.
- Camera and source transformations are separate. A display Z reflection uses the same pivot for both inputs and changes mesh winding, not anatomical shape.
- The support rule explicitly says whether zero represents missing data. A dark positive voxel is not automatically missing.

## Cut geometry

- A comparison evaluates old/new keep masks over the full requested native grid when making a full-grid claim; otherwise label its sampled scope.
- A local crop must not unexpectedly restore previously hidden tissue, touch the contour, change an internal terrace, or remove a protected rear edge.
- Inspect the exposed native planes. High nonzero coverage is an integrity observation, not an anatomical-quality score.
- For a conditional plane, inspect its activation boundary. Abruptly exempting the rear end can introduce a false protrusion even when every native slice is valid.
- If the requested repair needs a new shared plane, disclose the depth change and obtain agreement when it changes previously protected geometry.

## Rendering

- Same-camera before/after and EM-only views are available. Check continuity in the data, not only under a bright contour overlay.
- Preserve physical dimensions: adjust camera before considering nonphysical Z exaggeration, and only use exaggeration if explicitly requested and labeled.
- Mesh geometry and material changes are separate. Transparency, highlights and x-ray visibility must not be presented as new structural evidence.
- Check the complete frame and enlarged crop. Look for narrow raised strips, mismatched texture scale, bright interpolation fringes, new corners and black support thresholds.
- Preserve original missing-data boundaries. Do not silently inpaint or clone adjacent EM texture.

## Delivery and local pixel preservation

Retain raw renders, configuration, Blender scene, source/cache hashes and evidence scope. Include the unannotated figure; only add a scale bar when the camera/physical scale supports it. Orthographic bars use view span, image width/height and aspect ratio; a simple formula is not valid for arbitrary perspective cameras.

If a local edit must keep everything else identical, derive a same-camera mask from the changed geometry's projected footprint, with a justified antialiasing/denoising margin. It may be used to retain approved pixels outside that footprint. Verify substantial differences do not lie outside it, check the boundary, preserve both raw rerender and mask, and label the operation. Never use a preservation mask to hide a changed camera, a large data replacement or a failed continuity test.

The `verify_export.py preserve` command is deliberately strict: it requires an explicit rectangle and tolerance and rejects changed pixels exceeding that tolerance outside the rectangle. It does not infer whether the rectangle is scientifically justified. The agent must establish that before invoking it.

Publication is a separate authorized action. Exclude original patient/research data, private infrastructure, credentials and machine paths from public code. Synthetic smoke outputs test mechanics, not biological fidelity. An artifact passing automated checks still needs human visual approval when requested.
