# Blockwise instance reconciliation

Independent block labels are not a final neuron segmentation. The same neuron may receive different IDs in adjacent blocks, and unrelated objects may reuse identical local IDs.

## Required inputs

For every block retain:

- global model-grid read bbox and committed core bbox;
- halo/overlap labels, not only the cropped core;
- corresponding affinities or boundary evidence;
- local instance volume;
- postprocessing parameters and checksum.

## Reconciliation graph

1. Namespace local IDs by block: `(block_id, local_id)`.
2. For every overlapping block pair, count voxel intersections for nonzero label pairs.
3. Compute symmetric evidence such as IoU and directional containment.
4. Optionally add boundary affinity evidence and skeleton continuity.
5. Add a merge edge only when the frozen rule passes.
6. Resolve connected components with deterministic ordering.
7. Assign contiguous or stable uint64 global IDs.
8. Write only block cores into the global volume; use the overlap for decisions.

Do not merge solely because two objects touch a block face. Do not use a one-sided overlap fraction without guarding against a tiny fragment attaching to a large neighboring neuron.

## Ambiguity handling

Flag rather than auto-merge when:

- one object maps strongly to multiple objects across a seam;
- the best and second-best matches are close;
- overlap contains mostly padding or missing data;
- the candidate merge creates an implausibly large component;
- affinity and geometric evidence disagree.

Persist an ambiguity table for targeted proofreading.

## Completion artifact

Global reconciliation is complete only when its artifact records:

- tile manifest checksum;
- rule and thresholds;
- local-to-global mapping checksum;
- global output path, shape, resolution, offset, dtype, and checksum/version;
- ambiguous and rejected edge counts;
- seam verification result.

Set `instance.global_reconciliation.completed: true` in the frozen delivery configuration only after this artifact is reviewed. The orchestrator still verifies that the artifact exists.
