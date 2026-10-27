# Validation record

Validation performed on 2026-10-27 using generated synthetic inputs only. No private microscopy, meshes, source paths or credentials are included in this package.

## Automated coverage

- 27 test cases cover coordinates, offsets, anisotropic spacing, Z reflection/winding, zero-value semantics, clip boundaries, renderer/auditor agreement, cache identity, output protection, frozen-setting changes (including Z direction), exact local pixel preservation and orthographic scale bars.
- General Python ran 26 cases successfully and skipped the one real OpenVDB round-trip test because that interpreter had no OpenVDB module.
- Blender's compatible Python separately ran both preparation tests successfully, including the actual OpenVDB write/read test. This was not a mocked serialization test.
- The real VDB check processes all layers and compares active-voxel counts, then checks sampled native values. This is not an exhaustive per-voxel value-equality proof.
- The skill-creator frontmatter validation passed. Independent forward-testing exercised documented audit and local-preservation commands without private inputs.

## Runtime rendering

Blender 4.5.14 LTS / Cycles CPU was exercised with a 32 x 72 x 48 synthetic volume and an analytic ellipsoid, at 256 x 256 and four samples. The test creates a new scene and outputs the composite, EM-only, contour-only, transparent image, editable scene and completed manifest. The scene uses physical world-space volume sampling; a control that removes all data produces a white EM-only output, and a half-height cut changes the visible thickness as expected.

These tests validate pipeline execution and coordinate/crop behavior, not biological realism, publication quality or segmentation accuracy. A larger real-data render still requires native-section review, meaningful exposure/camera choices, adequate sampling and full-image plus local visual QA. CPU timings on this tiny fixture do not predict full-volume runtime.

## Portability limits

The tested runtime was Windows. Linux/macOS and other Blender versions have not been runtime-tested here. Local uint8 ZYX NPY/TIFF and an existing OBJ are the implemented input adapters; no cloud credentials, downloads, registration, segmentation, mesh repair or dependency installers are supplied. Blender/OpenVDB Python ABI compatibility remains an environment prerequisite. Rendering rejects pruned caches.

The documented historical specimen provides decision context. The reusable pipeline is newly parameterized and does not claim pixel-identical reproduction of its private LUT, runtime or original figure.
