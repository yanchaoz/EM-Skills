# Kidney local-field CloudVolume example

This example intentionally shows **local kidney fields only**, not a whole-kidney overview.

## Source and view contract

- Source family: kidney EM WSI CloudVolume/precomputed datasets.
- Display sampling: 20 nm/px local review images.
- Regions: cortex, corticomedullary junction, medulla, and renal papilla.
- Related segmentation layers used by the project include nuclei, mitochondria, basement membrane, and lysosome masks.
- Purpose: representative-field visual review and regional structure-density comparison, not segmentation-accuracy benchmarking.

![Four kidney local EM fields](four-local-fields-20nm.jpg)

![Local region density comparison](local-region-density-comparison.png)

The images demonstrate the local-field presentation policy used by `$cloudvolume-video`. They do not establish biological accuracy without reference annotations.

The kidney WSI source is a single-section presentation source, so it is **not** used as evidence for true 3D mesh reconstruction. Mesh support is separately exercised by automated tests with a real 3D label fixture: bounded ROI extraction, physical-coordinate conversion, PLY export, headless turntable rendering, distributed frame decoding, and hash verification.
