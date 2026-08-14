# Human review and export

## Review every suggestion

Inspect the complete z extent, not only a center slice. For each candidate record:

- tissue present versus empty resin;
- section loss, folds, tears, charging, streaks, blur, misalignment, or intensity discontinuities;
- already-labeled overlap or duplicated morphology;
- neuron continuity and boundary complexity relevant to the intended task;
- large non-neuronal structures such as myelin, blood vessels, soma, or glia that may dominate the field;
- proximity to train/validation/test boundaries;
- whether the requested physical annotation size is practical for the annotation tool.

Rejecting a suggestion requires a reason. When a rejection reduces the accepted budget, rerun selection with the rejected box added to `excluded_bboxes_zyx`; do not silently take the next rank from a stale run.

## Decision schema

Use `assets/review_decisions.example.json`. Every draft candidate ID must appear exactly once with `accept` or `reject`. Include reviewer identity and an ISO-8601 timestamp. Finalization fails closed when a decision is missing, duplicated, or refers to an unknown candidate.

## Export contract

The final JSON contains half-open source voxel bounding boxes and nanometer coordinates. Convert to a tool-specific format only after confirming that tool's axis order, indexing convention, resolution level, and inclusive/exclusive stop semantics.

For proofreading or annotation platforms, export at minimum:

- stable candidate ID and rank;
- source URI/version and source hash;
- source resolution and axes;
- half-open bbox in source voxels;
- bbox in physical units;
- accepted reviewer, timestamp, and notes;
- target label ontology and annotation SOP version, maintained outside this selector.

Never write selected patches into a test set, and never describe the queue as completed annotation.
