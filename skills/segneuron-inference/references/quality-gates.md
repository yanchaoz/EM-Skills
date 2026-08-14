# Quality gates

## Gate 0: source and identity

- Source resolution, axes, offset, shape, and bounds are known.
- Source identity is immutable or checksummed.
- Source is read-only and output is separate.
- Repository commit and checkpoint checksum are pinned.

## Gate 1: plan

- Source/model/delivery grids are explicit.
- Physical end-bound residual is within tolerance.
- Patch, tile core, halo, padding, and overlap are distinguishable.
- Estimated storage/runtime fits the backend.
- Representative pilot ROIs are selected in source coordinates.

## Gate 2: pilot

Inspect XY, XZ, and YZ at full useful resolution. Check raw/model-grid alignment, affinity channels, neurite continuity, membrane leakage, false foreground, splits, merges, fragments, and edge behavior. Freeze accepted parameters. Set `verification.pilot_approved: true` only after review.

## Gate 3: affinity execution

- All planned blocks completed once or were explicitly retried.
- Output channel count, shape, dtype, numerical range, and finite-value checks pass.
- Overlap agreement and seam visualizations pass.
- Command, log, runtime, commit, checkpoint, and environment records exist.

## Gate 4: instances

- Background convention is correct.
- IDs fit label dtype and are globally unique.
- Per-block jobs have a reviewed global reconciliation artifact.
- Object-size distribution, singleton/small-fragment rate, largest components, and border-crossing continuity are inspected.
- Catastrophic merges, orphan blocks, and empty/unlabeled foreground are absent or documented.

## Gate 5: restoration and delivery

- Restored labels use nearest-neighbor mapping.
- Delivery shape, resolution, offset, and bounds match the contract.
- Orthogonal overlays remain aligned.
- Output opens in the intended viewer and representative IDs can be selected.
- Required artifacts and checksums/version identifiers are present.

## Accuracy evidence

With ground truth, report at least one split/merge-aware metric family and its evaluation mask, resolution, matching rules, and excluded regions. Recommended evidence includes adapted Rand error and variation of information separated into split and merge components.

Without ground truth, use stratified manual review across anatomy, contrast, artifacts, object size, and block seams. Record sampling procedure, reviewed physical volume, reviewer decisions, and uncertainty. Pixel/instance histograms are diagnostics, not accuracy measurements.

## Finalize blockers

Do not finalize when:

- `pilot_approved` is false;
- severe issue count is nonzero;
- a required artifact is missing;
- an executed command failed or expected output was not produced;
- global reconciliation is incomplete for per-block instances;
- delivery bounds/dtype/provenance checks are not explicitly true.
