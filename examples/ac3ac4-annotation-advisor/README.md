# AC3AC4 real-data annotation-advisor pilot

This example is a real remote execution of `suggest-em-annotations` on:

```text
/opt/data/3_33/SCN/zhangyc/EMFoundataion/Code/Figure2-Exps/data/AC3AC4/0.tif
```

with the EMFoundation BASE checkpoint:

```text
/opt/data/3_33/SCN/zhangyc/EMFoundataion/Code/Pretraining_mito/models/BASE/learner.ckpt
```

## Audited inputs

- raw shape/dtype: `256 × 1024 × 1024`, `uint8`, axes `zyx`;
- recorded voxel size used for the pilot: `30 × 6 × 6 nm` (`zyx`); confirm this against authoritative dataset metadata before reuse;
- raw SHA-256: `3fe05531de1ceccc88f1f23aa66d19e938d3f73ea0473020dc159b5f4f5b3214`;
- checkpoint SHA-256: `86f7674b15f5967e8fe9624546da094416ffd91e81abfb6b662d7ebf0804af5a`;
- runtime: Python 3.10.14, PyTorch 2.1.1+cu118, NVIDIA GeForce RTX 4090.

The adapter matched all 74 encoder keys with no missing or unexpected keys and emitted `3375 × 512` finite embeddings. Patch/stride were `32 × 128 × 128 / 16 × 64 × 64` with end alignment.

## Variable-size selection

Candidate windows and source-voxel sizes were:

| Patch-grid window | Source shape zyx | Eligible boxes |
| --- | --- | ---: |
| `1 × 3 × 3` | `32 × 256 × 256` | 2,535 |
| `1 × 5 × 5` | `32 × 384 × 384` | 1,815 |
| `2 × 3 × 3` | `48 × 256 × 256` | 2,366 |
| `2 × 5 × 5` | `48 × 384 × 384` | 1,694 |

The budgeted selector used `k=30`, Euclidean distance, `cost_exponent=0.75`, a 24,000,000-voxel budget, and a maximum of six non-overlapping boxes. It selected six boxes using 22,806,528 voxels and covered 49.63% of the patch set in the chosen embedding. Five boxes were `48 × 256 × 256`; one was `48 × 384 × 384`.

The embedding panel uses deterministic UMAP—not PCA—with `n_neighbors=25`, `min_dist=0.12`, Euclidean metric, and `random_state=7`. The displayed coordinates and parameters are preserved in `selection-umap.npz`. UMAP is used only for visualization; coverage and selection still operate in the original 512-D embedding space.

![Selection overview](selection-overview.png)

![Raw EM review gallery](raw-subvolume-gallery.png)

The gallery shows only each box's center slice. Review the complete z extent before accepting any target.

## Included records

- `embedding-run.json`: real model/data provenance and embedding hashes;
- `project.json`: exact tiling, candidate sizes, budget, and model configuration;
- `audit.json`: geometry and scale audit;
- `draft-selection.json`: full ranked proposal queue;
- `selection-summary.json`: compact metrics and output hashes.
- `selection-umap.npz`: displayed UMAP coordinates and deterministic projection parameters.

Large source data, checkpoint files, embeddings, and the complete candidate manifest are intentionally not redistributed.

## Interpretation boundary

This run proves that the real source-to-embedding-to-variable-size-selection workflow executes and produces auditable coordinates. It is still a `DRAFT_REQUIRES_HUMAN_REVIEW`, has no accepted annotations, and is not evidence of improved downstream neuron segmentation. Matched-budget random/equispaced/fixed-size baselines plus held-out segmentation evaluation are required for that claim.
