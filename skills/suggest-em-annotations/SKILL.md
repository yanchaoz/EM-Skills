---
name: suggest-em-annotations
description: Build an auditable, embedding-guided queue of variable-size Volume EM subvolumes for human annotation. Use for running the EMFoundation BASE PNIv2 encoder, selecting multi-scale contiguous regions under an annotation-volume budget, comparing coverage against baselines, visualizing spatial and embedding coverage, or finalizing a reviewer-approved annotation manifest. Never use it to create ground-truth labels automatically.
---

# Suggest EM Annotations

## Outcome

Produce real model embeddings, a multi-scale candidate manifest, a budgeted draft annotation queue, a QC figure, and a separately human-reviewed final manifest. Selected boxes are annotation suggestions, not labels.

## Required Workflow

1. Read `references/emfoundation-adapter.md` before loading the BASE checkpoint.
2. Audit source readability, SHA-256, axes, shape, dtype, voxel size, and holdout bounds. Stop on a permission error; never substitute synthetic embeddings for a requested real-data run.
3. Extract deterministic 512-D patch embeddings with `scripts/extract_emfoundation_embeddings.py`. Preserve its `positions_zyx.npy`, `embedding_run.json`, and generated `project.json` together.
4. Read `references/config-schema.md`. Review the multi-scale candidate windows and the annotation budget in voxels. Treat these as a human-time proxy, not a universal measure of difficulty.
5. Run `plan`, then `select`. The selector solves a CCR-inspired budgeted maximum-coverage problem across variable-size contiguous windows.
6. Render the review figure. Inspect raw tissue in every proposed box for artifacts, empty resin, borders, damaged sections, duplicate morphology, and holdout leakage.
7. Compare against random and equispaced selections with the same annotation-volume budget before claiming improvement. Read `references/evaluation-protocol.md`.
8. Require a named expert to accept or reject every proposal. Read `references/review-and-export.md` before finalization.

## EMFoundation BASE Example

Run in the environment that already contains PyTorch, tifffile, NumPy, and the repository dependencies. The checkpoint filename is `learner.ckpt`, even when it is referred to informally as `learner`.

```bash
python scripts/extract_emfoundation_embeddings.py \
  --input /opt/data/3_33/SCN/zhangyc/EMFoundataion/Code/Figure2-Exps/data/AC3AC4/0.tif \
  --input-axes zyx \
  --pretrain-dir /opt/data/3_33/SCN/zhangyc/EMFoundataion/Code/Pretraining_mito \
  --checkpoint /opt/data/3_33/SCN/zhangyc/EMFoundataion/Code/Pretraining_mito/models/BASE/learner.ckpt \
  --voxel-size-nm 30,6,6 \
  --patch-size 32,128,128 \
  --stride 16,64,64 \
  --boundary align_end \
  --candidate-window 1,3,3 \
  --candidate-window 1,5,5 \
  --candidate-window 2,3,3 \
  --candidate-window 2,5,5 \
  --max-subvolumes 6 \
  --annotation-budget-voxels 24000000 \
  --device cuda:0 \
  --out-dir work/ac3ac4-0
```

Confirm `30,6,6 nm` from dataset metadata before execution. Do not infer resolution only from a filename.

Then run:

```bash
python scripts/em_annotation_advisor.py audit --config work/ac3ac4-0/project.json --out work/ac3ac4-0/audit.json
python scripts/em_annotation_advisor.py plan --config work/ac3ac4-0/project.json --out work/ac3ac4-0/candidates.json
python scripts/em_annotation_advisor.py select --config work/ac3ac4-0/project.json --manifest work/ac3ac4-0/candidates.json --embeddings work/ac3ac4-0/embeddings.npy --positions work/ac3ac4-0/positions_zyx.npy --out work/ac3ac4-0/draft_selection.json
python scripts/visualize_annotation_advice.py --manifest work/ac3ac4-0/candidates.json --selection work/ac3ac4-0/draft_selection.json --embeddings work/ac3ac4-0/embeddings.npy --umap-neighbors 25 --umap-min-dist 0.12 --umap-metric euclidean --umap-seed 7 --projection-out work/ac3ac4-0/selection_umap.npz --out work/ac3ac4-0/selection_overview.png
python scripts/visualize_subvolume_gallery.py --raw /absolute/path/0.tif --selection work/ac3ac4-0/draft_selection.json --axes zyx --out work/ac3ac4-0/raw_subvolume_gallery.png
python scripts/em_annotation_advisor.py finalize --draft work/ac3ac4-0/draft_selection.json --decisions work/ac3ac4-0/review_decisions.json --out work/ac3ac4-0/final_annotation_queue.json
```

## Model Contract

- Architecture: `PNIv2_head.UNet_PNI(num_features=[32,64,128,256,512])`.
- Checkpoint: load `model_weights`, retain keys containing `encoder`, and strip the `sp_cnn.` prefix exactly as the Figure2 UMAP reference does.
- Feature: call `model(tensor, hierarchical=True)` and use the adaptive-average-pooled center feature.
- Embedding dimension: 512. Fail if any other dimension appears.
- Reference patch/stride: `32×128×128 / 16×64×64` in z-y-x order.
- Reference normalization: if the patch maximum is greater than 1.5, divide by 255, then per-patch z-score. Fail for intensities above 255 until a validated transform is configured.

## Variable-Size Selection

Each configured window is a contiguous box on the patch grid. For each candidate, the covered set is the union of the `k_neighbors` nearest embedding patches represented by that box. At each step choose the eligible candidate maximizing:

```text
marginal newly covered patches / annotation_cost_voxels ^ cost_exponent
```

Selection stops when the voxel budget, maximum number of boxes, overlap rule, or marginal-gain condition prevents another choice. `cost_exponent=1` emphasizes coverage per voxel; smaller values allow a larger box when its absolute coverage gain is valuable. Report the chosen value.

This is a multi-scale, budgeted extension of CCR—not an assertion that variable-size boxes were evaluated in the original paper.

## Non-negotiable Gates

- Never report a real-data test as passed unless the source TIFF was readable and its hash, shape, dtype, model-load report, embedding shape, and output hashes were recorded.
- Never fall back to random or synthetic embeddings after a real source/model was requested.
- Fail on axis ambiguity, missing voxel size, source/model permission errors, shape/order mismatch, non-finite embeddings, or checkpoint mismatch.
- Keep validation/test/holdout regions outside both embedding selection and annotation output.
- A generated queue remains `DRAFT_REQUIRES_HUMAN_REVIEW` until every proposal is accepted or rejected by a named reviewer.
- Do not interpret UMAP clusters as biological classes without independent labels and expert audit.
- Display embedding vectors with deterministic UMAP, record its neighbors, minimum distance, metric, and seed, and fail if `umap-learn` is unavailable. Do not silently substitute PCA.
- Do not claim annotation efficiency until matched-budget random/equispaced baselines and held-out downstream segmentation evaluation are complete.

## Deliverables

- `embedding_run.json`: runtime, model load, source/model hashes, embedding and position hashes.
- `project.json`: exact source, model, tiling, candidate-size, budget, and guard configuration.
- `positions_zyx.npy` and `embeddings.npy`: row-aligned patch coordinates and features.
- `candidates.json`: deterministic multi-scale candidate geometry and per-box annotation cost.
- `draft_selection.json`: ranked budgeted suggestions, coverage curve, size and cost of each box.
- `selection_overview.png`: spatial boxes, embedding coverage, coverage curve, and review queue.
- `selection_umap.npz`: displayed UMAP coordinates and reproducibility parameters.
- `raw_subvolume_gallery.png`: center-slice raw EM previews with physical scale bars; full-z review is still required.
- `final_annotation_queue.json`: expert-approved targets only.

## Scope Boundary

This Skill selects where experts should annotate. It does not create neuron labels, train IIC-Net, measure annotation time automatically, or prove downstream segmentation gains. Those are separate human-labeling and evaluation stages.
