# Cross-Skill Composition Contract

Read this reference before exporting expert corrections to training or comparing an adapted model with the zero-shot baseline.

## Shared identity

Use one immutable `source_id` across all stages. Derive it from the source URI/path plus a content hash or an immutable dataset version. Every artifact must also record:

- `axes` and array shape;
- `voxel_size_nm_zyx`, offset, and physical bounds;
- source-to-model and model-to-source transforms;
- training/selection/validation/test bounding boxes;
- generating Skill, configuration digest, and timestamp.

Reject an artifact join when source identity or physical bounds disagree.

## Coarse reconstruction handoff

The SegNeuron stage should provide:

- source-grid coarse instance labels;
- model-grid affinities or durable reference;
- selected beta and comparison evidence;
- checkpoint and code revision hashes;
- known merge, split, fragmentation, seam, and foreground-leakage findings;
- QC slices or volumes sufficient to inspect selected boxes.

The coarse labels remain an immutable baseline.

## Selective annotation handoff

The annotation-advisor stage should provide:

- final approved `bbox_zyx` regions in source-grid coordinates;
- physical bounds and annotation cost per region;
- embedding/model/configuration provenance;
- proposed, accepted, and rejected region records;
- UMAP/spatial figures used for review;
- an explicit holdout-exclusion audit.

Selection is based on raw-volume embeddings and budgeted coverage. Coarse labels are paired with selected boxes for expert review; do not claim the current selector automatically detects segmentation errors unless a validated error-aware objective is added.

## Expert correction manifest

Record one entry per accepted region:

```json
{
  "source_id": "sha256:...",
  "region_id": "sv-...",
  "bbox_zyx": [[0, 0, 0], [32, 512, 512]],
  "voxel_size_nm_zyx": [30, 8, 8],
  "raw_path": "...",
  "coarse_labels_path": "...",
  "corrected_labels_path": "...",
  "correction_types": ["merge", "broken-continuity"],
  "reviewer": "named expert",
  "reviewed_at": "RFC-3339 timestamp",
  "coarse_sha256": "...",
  "corrected_sha256": "..."
}
```

Use nearest-neighbor extraction for labels. Preserve background and ignore-label conventions. Verify label dtype and local/global ID semantics before training.

## Training handoff

Export a manifest containing the accepted correction entries plus:

- deterministic train/validation assignment with no spatial overlap;
- crop/augmentation and normalization configuration;
- target representation, such as affinities, membranes, or instances;
- initialization checkpoint and checksum;
- training repository revision and real entry point;
- expected checkpoint, logs, metrics, and failure artifacts.

If training new lightweight models, record architecture, parameter count, input resolution, receptive field, and inference cost. Do not compare compute efficiency without the same hardware and measurement protocol.

## Paired evaluation

Evaluate zero-shot and adapted checkpoints on the same untouched holdout and source grid. At minimum report:

- adapted Rand or variation-of-information split and merge components when ground truth exists;
- connectivity/topology review on predefined structures;
- false foreground and fragmentation;
- inference runtime, peak memory, and model size when comparing a lightweight model;
- confidence intervals or per-volume results across multiple holdouts when available.

Without ground truth, report blinded expert review and correction counts as QC evidence, not a universal accuracy claim.
