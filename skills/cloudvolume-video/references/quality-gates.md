# Quality gates

Read this file completely before approving a storyboard, starting a formal render, or delivering results.

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

- [ ] Opening frame identifies the specimen or local anatomical region and its physical field of view.
- [ ] Each isolated overlay uses the requested color and opacity.
- [ ] Each isolated overlay is immediately followed by its density map.
- [ ] Density is mask area divided by valid tissue area in physical bins.
- [ ] Combined view contains exactly the approved layers.
- [ ] Four representative fields are tissue-rich and ordered along the intended path.
- [ ] Fine labels align with EM structures in every representative field.
- [ ] Coordinates and scale bars are readable at final 1920x1080 size.
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
- [ ] Verification contact sheet has no unexpected blank/black frames.
- [ ] SHA-256 is written for every MP4.
- [ ] Mesh vertices are finite, face indices are valid, and exported mesh/video hashes are recorded.

## Gate 5: delivery

- [ ] Each 2D specimen has MP4, requested PNG frames, keyframes JSON, `tour.ngvideo`, storyboard, verification JSON, contact sheet, and hash file.
- [ ] Each mesh scene has PLY, render manifest, MP4 when requested, verification JSON, contact sheet, and hashes.
- [ ] Root delivery manifest lists all specimens, layers, label IDs, durations, frames, sizes, and hashes.
- [ ] Exact configuration and renderer are copied into the delivery.
- [ ] Output root and important files are clearly reported to the user.
