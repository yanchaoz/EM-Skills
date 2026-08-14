---
name: suggest-em-annotations
description: Build auditable, human-reviewed annotation suggestion queues for volume electron microscopy (volume EM) by selecting representative spatially contiguous subvolumes with the SL-SSNS coverage-based greedy selection (CGS) principle. Use when planning one-shot neuron-segmentation annotation, choosing EM ROIs under a fixed budget, comparing random/equispaced/coverage-based sampling, visualizing selected and covered patches in spatial and embedding domains, or adapting the public SL-SSNS repository/Colab to a new dataset. Do not use this skill to generate ground-truth labels, silently crop a volume, or claim model uncertainty or biological class identity from an embedding alone.
---

# Suggest EM Annotations

## Outcome

Produce a provenance-rich draft queue of representative EM subvolumes, a spatial/embedding coverage figure, and a separately reviewed final annotation manifest. Treat every selected subvolume as a suggestion, never as ground truth.

## Workflow

1. Read `references/method-and-evidence.md` before interpreting SL-SSNS or CGS.
2. Read `references/config-schema.md` and fill a project config from `assets/project.example.json`.
3. Audit source identity, axes, voxel size, bounds, patch grid, derived subvolume size, annotation budget, exclusions, and train/validation separation.
4. Obtain patch embeddings using a pinned encoder. For the official implementation, read `references/sl-ssns-adapter.md`; do not install, clone, or execute it unless the user requests that action.
5. Generate the patch/candidate manifest, then run coverage-based selection.
6. Generate the spatial/embedding visualization and inspect duplicates, damaged tissue, borders, empty resin, artifacts, and holdout leakage.
7. Require a named reviewer to accept or reject every suggestion. Read `references/review-and-export.md` before finalization or export.
8. Report provenance, configuration, coverage, rejected regions, unresolved risks, and the exact final manifest path.

## Commands

Use a Python environment with NumPy. PyYAML is only needed for YAML configs; JSON is the portable default.

```powershell
python scripts/em_annotation_advisor.py audit --config assets/project.example.json
python scripts/em_annotation_advisor.py plan --config project.json --out work/candidates.json
python scripts/em_annotation_advisor.py select --config project.json --manifest work/candidates.json --embeddings work/embeddings.npy --out work/draft_selection.json
python scripts/visualize_annotation_advice.py --manifest work/candidates.json --selection work/draft_selection.json --embeddings work/embeddings.npy --out work/selection_overview.png
python scripts/em_annotation_advisor.py finalize --draft work/draft_selection.json --decisions work/review_decisions.json --out work/final_annotation_queue.json
```

Run commands from this skill directory, or use absolute paths. The embedding row order must exactly match `patches[*].patch_id` in the candidate manifest.

## Non-negotiable Quality Gates

- Fail when axes are not explicitly `zyx`, dimensions are non-positive, voxel size is missing, the embedding count/dimension differs from the manifest/config, or NaN/Inf values occur.
- Fail when a candidate intersects a configured holdout or exclusion box.
- Print the derived subvolume shape in voxels and nanometers. If `expected_subvolume_shape_zyx` is configured, require an exact match.
- Keep source identity, model repository, pinned commit, checkpoint SHA-256, config SHA-256, and embedding SHA-256 in outputs.
- Do not silently emulate the public script's first-100-z-slices truncation or fixed `cuda:3` device.
- Warn and stop before large exact all-pairs runs unless the user explicitly raises `max_exact_patches`; the implementation is memory-bounded but remains quadratic in time.
- Do not select from test/validation/holdout regions. Spatially adjacent leakage counts as leakage when the project's split policy says so.
- Do not call UMAP clusters biological classes without an expert audit or independent labels.
- Do not finalize until every proposed subvolume has an explicit accept/reject decision and reviewer identity.

## Selection Semantics

Match the paper's constrained coverage rate: every patch represents its `k_neighbors` nearest patches (including itself); the covered set is the union of those neighborhoods. Greedily add the non-overlapping contiguous candidate subvolume with the largest new coverage. Ties resolve by stable candidate ID.

The included selector computes exact neighbors in blocks, so peak distance-matrix memory is bounded. It does not change the O(N²) distance-computation cost. For very large volumes, shard by scientifically justified strata or use a validated approximate-nearest-neighbor backend, then disclose that deviation.

## Deliverables

- `candidates.json`: deterministic patch grid, candidate boxes, exclusions, physical coordinates, and configuration audit.
- `draft_selection.json`: ranked suggestions, coverage curve, selected/covered patch IDs, hashes, warnings, and `DRAFT_REQUIRES_HUMAN_REVIEW` status.
- `selection_overview.png`: spatial projection, embedding projection, coverage curve, and review queue.
- `review_decisions.json`: human decisions using the supplied schema.
- `final_annotation_queue.json`: accepted-only queue with reviewer and timestamp.

## Scope Boundary

This skill covers annotation planning and selection. It does not train IIC-Net, create neuron labels, assess annotator correctness, or prove downstream segmentation gains on a new dataset. Those require a separate experimental protocol with random/equispaced baselines and held-out evaluation.
