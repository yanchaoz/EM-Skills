# Configuration schema

## Top-level fields

| Field | Required | Contract |
| --- | --- | --- |
| `project_id` | yes | Stable identifier for this review |
| `raw` | yes | Source EM array and physical metadata |
| `candidates` | yes | One or more segmentation artifacts |
| `ground_truth` | no | Frozen independent reference labels |
| `review` | yes | Display, matching, and output settings |

Paths are resolved relative to the YAML file unless absolute.

## Raw

```yaml
raw:
  path: data/raw.npy
  source_id: dataset-name:roi-name:immutable-version
  grid_id: source-grid-v1
  axes: zyx
  resolution_nm: [40, 8, 8]
  offset_vox: [0, 0, 0]
```

Use `yx` for a 2D image and `zyx` for a volume. Supply one positive nanometre value and one integer voxel offset per axis in the same order. `source_id` identifies the immutable dataset ROI; `grid_id` names its exact sampling grid. The deterministic reviewer accepts single-array NPY, single-array NPZ, TIFF, and TIFF stacks.

## Candidates

```yaml
candidates:
  - name: model-a
    path: data/model-a.tif
    kind: semantic
    grid_id: source-grid-v1
    provenance: "Model, checkpoint, configuration, and command identities"
  - name: model-b
    path: data/model-b.npy
    kind: instance
    grid_id: source-grid-v1
    provenance: "Model, checkpoint, configuration, and command identities"
```

Names must be unique. Use `semantic` for foreground/background labels and `instance` when each object has a stable non-zero ID. Every candidate must declare the same `grid_id` as raw and include non-empty provenance. All candidates must match the raw array shape. Labels must be finite, non-negative integers; background is ID `0`.

All candidates in one comparison must use the same label meaning. Do not mix semantic and instance candidates in a single objective ranking.

## Ground truth

```yaml
ground_truth:
  path: data/holdout-labels.npy
  kind: instance
  grid_id: source-grid-v1
  provenance: "Expert consensus labels from frozen holdout v2"
```

Declare provenance and verify that the labels were not used for training, prompt construction, candidate selection, or threshold tuning. Omit the entire block when no valid ground truth exists. The reviewer will then suppress ranking and mark the evidence as descriptive QC only.

## Review

```yaml
review:
  output_root: derived/review
  axis: xy
  index: null
  instance_iou_threshold: 0.5
  force: false
```

- `axis`: `xy`, `xz`, or `yz`; 2D inputs allow only `xy`.
- `index`: explicit array index or `null` to select the slice with maximum union foreground across candidates and ground truth.
- `instance_iou_threshold`: one-to-one instance matching threshold in `(0, 1]`.
- `force`: permit replacement of deterministic report and figure outputs. Leave false unless the exact targets were reviewed.
