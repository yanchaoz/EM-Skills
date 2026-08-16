# Artifact contract

## Accepted meanings

Keep these artifact types distinct:

```text
raw EM intensity
semantic foreground mask
instance label image
affinity or probability prediction
ground-truth label image
```

The deterministic reviewer accepts raw EM plus semantic or instance labels. Convert probabilities or affinities through the upstream method's declared postprocessing; do not threshold them implicitly inside a review and call the result an existing candidate.

## Coordinate identity

Before comparing arrays, establish:

- axis order;
- shape and physical voxel size;
- voxel offset and physical bounds when data were cropped or resampled;
- source dataset and ROI identity;
- whether labels are on source, model, or delivery grid.

Matching array shape is necessary but not sufficient to prove physical alignment. If offsets or bounds differ, restore or crop through a documented upstream operation before review. Interpolate categorical labels only with nearest-neighbour methods.

## Identity and provenance

Record file SHA-256, generating model and checkpoint, configuration identity, executed command, and any human edits. A ground-truth artifact must also state annotator or consensus provenance and data-split role.

Do not compare a candidate against labels that influenced the same candidate and describe the result as independent evaluation. Do not promote reviewed holdout labels into training or long-term memory.

## Scale and label capacity

Record resolution in nanometres in the declared axis order. Preserve non-zero instance IDs exactly; use an integer dtype with sufficient capacity. Reject negative, non-finite, or fractional label values.
