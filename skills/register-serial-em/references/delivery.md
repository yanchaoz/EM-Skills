# TIFF, precomputed and video

Use accepted **rendered original intensities** and a result manifest; export-only
requests do not rerun alignment. Record transformations, canvas bounds, masks,
source identities and QC separately from intensity products.

```bash
python scripts/export_aligned.py result.json --output /data/export-tiff --tiff
python scripts/export_aligned.py result.json --output /data/export-all --tiff --cloudvolume --mips 4
```

Each invocation needs a fresh empty directory; partial exports retain status/check
files for diagnosis, and this version does not resume them automatically. No source
file is overwritten. The whole-plane implementation supports uint8, uint16 and
float32. Final registration interpolation can change pixels relative to raw images;
this exporter verifies equality to the **provided aligned** pixels.

TIFF uses one scalar, losslessly deflated plane per file, stable zero-padded names,
original dtype, X/Y resolution tags and JSON description containing XYZ sampling,
offset and section ID. Standard TIFF X/Y tags alone cannot convey Z spacing;
preserve verification.json and the result manifest. Export verification hashes every
decoded plane and every completed TIFF file.

CloudVolume uses raw encoding with gzip, one image channel, XYZ metadata and
512x512x1 chunks. Helpers transpose YX arrays to CloudVolume's XYZC interface.
The native level is mip0. Each subsequent level averages 2x2 XY pixels (integer
results rounded half up); Z resolution/count/offset remain unchanged. Every
complete written plane at every mip is read back and hashed against its computed
array. This checks conversion, not registration accuracy.

For K levels, XY size and XY voxel offset must be divisible by 2**(K-1).
Odd shapes or incompatible negative origins require an explicitly padded **derived**
canvas with recorded bounds, or fewer mips. The exporter fails instead of silently
cropping or shifting. Padding must preserve source-to-world mapping and include a
validity mask. Z count need not be divisible by any factor.

A result can reference an existing single-channel CloudVolume via `cloudvolume`
and ordered section IDs, omitting per-section paths. Its mip0 metadata must match
the declared grid. Missing chunks fail; they are not silently filled with black.
Use separate read and write locations.

For video, read the delivered TIFF/precomputed data, retain slice number and physical
scale, show raw/aligned and orthogonal comparisons, and record display contrast and
any Z exaggeration. Use the sibling cloudvolume-video skill when available; do not
render synthetic microscopy or claim a movie proves anatomical accuracy.
