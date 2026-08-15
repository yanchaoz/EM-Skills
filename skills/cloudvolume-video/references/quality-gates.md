# Quality gates

Read this file completely before approving a storyboard, starting a formal render, or delivering results.

## Gate 0: optional precomputed preparation

- [ ] Source format, axes, shape, dtype, channel count, resolution, and offset are explicit.
- [ ] Converted datasets write to a separate bounded derived root, never the source array.
- [ ] Image versus segmentation layer type and encoding are correct.
- [ ] First, center, and last source/precomputed samples match exactly after axis mapping.
- [ ] Base-mip-only output or the explicit pyramid backend is recorded.
- [ ] Viewer state uses credential-free source URLs; the built-in server binds to loopback unless public exposure was explicitly reviewed.

## Gate 1: semantic, metadata, and mesh audit

- [ ] Raw and overlay paths exist.
- [ ] Native dimensions, resolution, physical field, dtype, and mips are recorded.
- [ ] Every abbreviation and label ID is supported by provenance or user confirmation.
- [ ] Explicit exclusions are recorded.
- [ ] Raw and overlays share the intended physical extent/origin.
- [ ] Requested scale bars are physically meaningful.
- [ ] Mesh source type, segment IDs, coordinate convention, bounds, and physical units are explicit.
- [ ] Label-derived mesh work uses a bounded 3D ROI and excludes background ID 0.

## Gate 2: storyboard approval

- [ ] Opening frame identifies the specimen or bounded context and its physical field of view.
- [ ] A requested 1 x 1 mm context is exactly that physical size and is not replaced by a whole-organ frame.
- [ ] Each isolated overlay uses the requested color and opacity.
- [ ] Each isolated overlay is immediately followed by its density map.
- [ ] Density is mask area divided by valid tissue area in physical bins.
- [ ] Combined view contains exactly the approved layers.
- [ ] Requested random fields use a recorded seed, stay inside the context ROI, meet tissue/margin rules, and retain random order.
- [ ] Random fields are not relabeled as anatomical or representative regions.
- [ ] Segmentation/density stages are not redundantly repeated at each random stop unless requested.
- [ ] Four requested camera moves are visible spatial motion rather than crossfades.
- [ ] Fine labels align with EM structures in every representative field.
- [ ] Coordinates and scale bars are readable at final 1920x1080 size.
- [ ] Camera entry, hold, and move keyframes stay within bounded source data.
- [ ] Pan/zoom uses one transform for the aligned raw-plus-label composite.
- [ ] Dynamic scale bars and coordinate captions match the instantaneous FOV.
- [ ] Easing has no visible start/stop jumps; transition zoom-out remains restrained.
- [ ] Source missing tiles are distinguished from rendering artifacts.
- [ ] Black background and hidden axis lines are correct.
- [ ] Mesh previews use stable camera/light settings and show non-zero extent on all three axes.
- [ ] Any display face sampling is declared and does not affect the complete exported mesh.

## Gate 3: formal render

- [ ] Storyboard/config version matches the renderer input.
- [ ] Output directory has adequate free space.
- [ ] Existing stale frame files cannot inflate the final count.
- [ ] MP4 writer codec opens successfully.
- [ ] Progress is logged during static and camera stages.
- [ ] Final writer is released before verification.

## Gate 4: automated verification

- [ ] MP4 opens.
- [ ] Width and height exactly match configuration.
- [ ] FPS matches configuration within decoder tolerance.
- [ ] Frame count matches the timeline calculation.
- [ ] PNG count equals MP4 frame count when PNG export is enabled.
- [ ] Samples from opening, overlays, densities, combined view, transitions, and holds decode.
- [ ] Camera entry, hold midpoint, move midpoint, and final hold samples decode without blank borders or alignment drift.
- [ ] Verification contact sheet has no unexpected blank/black frames.
- [ ] SHA-256 is written for every MP4.
- [ ] Mesh vertices are finite, face indices are valid, and exported mesh/video hashes are recorded.

## Gate 5: delivery

- [ ] Each 2D specimen has MP4, requested PNG frames, keyframes JSON, `tour.ngvideo`, storyboard, verification JSON, contact sheet, and hash file.
- [ ] Each mesh scene has PLY, render manifest, MP4 when requested, verification JSON, contact sheet, and hashes.
- [ ] Root delivery manifest lists all specimens, layers, label IDs, durations, frames, sizes, and hashes.
- [ ] Converted inputs include precomputed conversion/verification manifests, `info` hashes, viewer state, and handoff URL.
- [ ] Exact configuration and renderer are copied into the delivery.
- [ ] Output root and important files are clearly reported to the user.
