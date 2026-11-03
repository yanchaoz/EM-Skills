# Evaluate continuity without inventing accuracy

Keep backend-specific outputs and immutable raw images. Register/render a raw
baseline into the same physical canvas before comparison; simple shape equality
does not establish equal physical coordinates.

Run:

```bash
python scripts/compare_alignment.py baseline.json sofima-result.json feabas-result.json --out comparison.json
```

Every manifest must share ordered IDs, dtype, XYZ resolution, XYZ offset and ZYX
shape. Each section requires a `valid_mask` path: nonzero means valid. Masks must
have the same YX shape. Explicit masks are required even for all-valid images;
zero-valued tissue is never excluded automatically. Mask polarity is separate from
FEABAS material masks.

The script uses the intersection across **all** results at each adjacent pair, so
NCC cannot increase merely by scoring a smaller area for one backend. It reports
the common coverage and null correlation for constant/insufficient pixels.
It processes two adjacent planes per result at a time. NCC is a continuity
indicator, not ground-truth accuracy and not a reason to declare a universal winner.
Save the masks, not just their coverage statistic.

Inspect before/after XY flips and fixed-location XZ/YZ views, including large
displacements, damaged slices, sparse texture, block joins and volume boundaries.
Record jumps, duplicated contours, tissue loss, border collapse and over-warping.
Measure matching residuals on held-out landmarks when available, preferably in nm.
Report median and tail errors, valid support, runtime, memory and failure counts.

For continuous displacement fields, record finite-coordinate checks, local
orientation/Jacobian, inverse consistency and displacement quantiles in declared
units. `bilinear_jacobian_stats` in compare_alignment.py checks all four corners
of each bilinear XY cell; this is stronger than checking just central differences.
It is a diagnostic for that interpolation model, not a certificate for a different
renderer. FEABAS tears need per-material native mesh checks, not a smooth-grid
test across disconnected pieces.

Make physical-scale orthogonal views and label any display-only Z exaggeration.
A smooth movie can conceal distorted dimensions. Compare image content and
geometry; metadata and successful process exit alone do not prove alignment.
