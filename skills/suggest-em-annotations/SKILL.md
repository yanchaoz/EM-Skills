---
name: suggest-em-annotations
description: Select and review embedding-guided, variable-size Volume EM subvolumes for human annotation. Use when a task involves extracting EMFoundation BASE embeddings, auditing an embedding run, building multi-scale contiguous candidates, selecting regions under an annotation-volume budget, comparing coverage with baselines, visualizing spatial or UMAP coverage, reviewing proposed boxes, or exporting a reviewer-approved annotation manifest. Supports individual stages and complete annotation-planning runs. Never use it to create ground-truth labels automatically.
---

# Suggest EM Annotations

Use this Skill to decide **where a human should annotate**, not to create labels. Execute the smallest capability that satisfies the request and reuse existing embeddings, candidate manifests, selections, or review decisions when supplied.

## Route the request

| User intent | Use this capability | Load when needed |
| --- | --- | --- |
| Embed a real EM volume | `extract_emfoundation_embeddings.py` | [EMFoundation adapter](references/emfoundation-adapter.md) |
| Audit source, model, axes, scale, or holdouts | `audit` | [config schema](references/config-schema.md) |
| Inspect candidate sizes and cost | `plan` | [config schema](references/config-schema.md), [method and evidence](references/method-and-evidence.md) |
| Select variable-size subvolumes | `select` | [method and evidence](references/method-and-evidence.md) |
| Plot spatial or embedding coverage | visualization scripts; do not re-extract embeddings | None unless provenance is unclear |
| Evaluate the selection strategy | matched-budget baselines and held-out evaluation | [evaluation protocol](references/evaluation-protocol.md) |
| Accept/reject boxes or export a queue | `finalize` after complete named review | [review and export](references/review-and-export.md) |

For a complete annotation-planning request, use `extract → audit → plan → select → visualize → review → finalize`. Evaluation is a separate capability and is required only before claiming improved annotation efficiency.

## Preserve the model and data contract

- Use real embeddings when a real source/model run is requested. Never replace an unreadable source or failed checkpoint with random or synthetic features.
- Record source hash, axes, shape, dtype, voxel size, holdout bounds, model/checkpoint identity, embedding shape, and output hashes.
- Keep validation, test, and holdout regions outside embedding selection and annotation output.
- Keep `positions_zyx.npy`, `embeddings.npy`, `embedding_run.json`, and `project.json` aligned and together.
- Require finite 512-D features for the documented EMFoundation BASE adapter. Read [EMFoundation adapter](references/emfoundation-adapter.md) before loading the checkpoint or changing normalization.
- Treat annotation volume as a configurable human-time proxy, not a universal cost measurement.

Stop a dependent stage on axis ambiguity, missing voxel size, permission errors, source/model mismatch, non-finite embeddings, row misalignment, checkpoint mismatch, or holdout leakage. Visualization of already generated artifacts may proceed when it can be labeled honestly.

## Extract embeddings

Run `scripts/extract_emfoundation_embeddings.py` in the environment containing the pinned EMFoundation code and dependencies. Inspect its help and use the dataset-specific paths, axes, voxel size, patch size, stride, candidate windows, budget, and device. The checkpoint file is normally `learner.ckpt`, even when described informally as `learner`.

The repository's real AC3/AC4 example and exact remote invocation are documented in `examples/ac3ac4-annotation-advisor/README.md`; do not treat its `30,6,6 nm` metadata or candidate sizes as universal defaults.

## Plan and select

```bash
python scripts/em_annotation_advisor.py audit --config work/project.json --out work/audit.json
python scripts/em_annotation_advisor.py plan --config work/project.json --out work/candidates.json
python scripts/em_annotation_advisor.py select --config work/project.json --manifest work/candidates.json --embeddings work/embeddings.npy --positions work/positions_zyx.npy --out work/draft_selection.json
```

Each configured window is a contiguous box on the patch grid. The selector greedily maximizes newly covered embedding neighborhoods relative to annotation cost, subject to budget, number-of-boxes, overlap, holdout, and marginal-gain constraints. Report window sizes, `k_neighbors`, metric, budget, and `cost_exponent`; do not present this multi-scale extension as an experiment performed in the original SL-SSNS paper.

## Visualize and review

```bash
python scripts/visualize_annotation_advice.py --manifest work/candidates.json --selection work/draft_selection.json --embeddings work/embeddings.npy --projection-out work/selection_umap.npz --out work/selection_overview.png
python scripts/visualize_subvolume_gallery.py --raw /absolute/path/raw.tif --selection work/draft_selection.json --axes zyx --out work/raw_subvolume_gallery.png
```

- Use deterministic UMAP for embedding display and record neighbors, minimum distance, metric, and seed. Fail if `umap-learn` is unavailable; do not silently substitute PCA.
- Do not interpret UMAP clusters as biological classes without independent labels and expert audit.
- Inspect every proposed box in the raw volume for artifacts, empty resin, borders, damaged sections, duplicate morphology, and holdout leakage. A center-slice gallery does not replace full-z review.
- Keep the selection status `DRAFT_REQUIRES_HUMAN_REVIEW` until a named reviewer accepts or rejects every proposal.

Finalize only after review is complete:

```bash
python scripts/em_annotation_advisor.py finalize --draft work/draft_selection.json --decisions work/review_decisions.json --out work/final_annotation_queue.json
```

## Evaluate only when making an efficiency claim

Compare against random and equispaced selections under the same annotation-volume budget. Use repeated seeds and report coverage uncertainty. To claim annotation efficiency, train or fine-tune the same downstream segmentation method with matched labeling/training budgets and evaluate on an untouched held-out set. Coverage, UMAP separation, and morphology distributions are selection diagnostics—not segmentation accuracy.

## Expected outputs

- Embedding provenance: `embedding_run.json`, `project.json`, `positions_zyx.npy`, `embeddings.npy`.
- Candidate and draft artifacts: `candidates.json`, `draft_selection.json`.
- Review evidence: `selection_overview.png`, `selection_umap.npz`, `raw_subvolume_gallery.png`.
- Final artifact: `final_annotation_queue.json`, containing accepted targets only.

This Skill does not create neuron labels, train IIC-Net, automatically measure annotation time, or prove downstream gains. Treat those as separate labeling, training, and evaluation tasks.
