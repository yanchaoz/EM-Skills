---
name: review-em-segmentation
description: Audit, compare, visualize, and verify semantic or instance segmentations against electron microscopy images. Use when Codex needs to inspect existing EM masks or labels, compare model or parameter candidates, compute metrics with optional ground truth, identify integrity and continuity risks, prepare calibrated QC figures, or record an explicit human review decision. Supports 2D and 3D NumPy or TIFF artifacts. Do not use automated or vision-language scores as scientific approval, and do not rerun an upstream segmentation model when the request is review-only.
---

# Review EM Segmentation

Use this Skill as an independent review layer. Reuse supplied raw images, candidate labels, and ground truth. Do not silently rerun inference, change labels, or select an upstream model parameter.

## Route the request

| User intent | Action |
| --- | --- |
| Inspect one existing result | Run deterministic review for that candidate |
| Compare models, checkpoints, or parameters | Review all candidates at identical physical coordinates |
| Evaluate against labels | Add the frozen ground truth and report semantic plus applicable instance metrics |
| Make a figure only | Render from existing artifacts; do not require upstream execution |
| Approve or reject a result | Present the evidence, obtain an explicit human decision, then write an approval record |
| Diagnose poor segmentation | Report failure evidence and likely categories; do not alter the upstream pipeline unless asked |

For a complete review, use `review -> inspect report and figure -> finalize`. `finalize` records a human decision and never infers one.

## Preserve the review contract

- Keep raw data, candidate labels, and ground truth immutable.
- Require matching array shape and declared `yx` or `zyx` axes.
- Track physical voxel size in nanometres and render the same physical slice for every candidate.
- Treat `semantic` and `instance` labels differently. Never call a foreground mask an instance segmentation.
- Rank candidates only when frozen ground truth provides an objective score. Without ground truth, present descriptive QC side by side without a winner.
- Separate artifact integrity, descriptive QC, measured accuracy, and human scientific approval in every report.
- Treat an optional VLM assessment as a review note, not as ground truth or an approval gate.
- Preserve validation and test labels as evaluation-only data. Do not copy reviewed holdout examples into training or memory stores.

Read [artifact contract](references/artifact-contract.md) before adapting formats or label semantics. Read [quality gates](references/quality-gates.md) before final delivery.

## Run the deterministic reviewer

Start from `assets/review.example.yaml` and read [configuration schema](references/config-schema.md).

```powershell
python scripts/review_em_segmentation.py review project.yaml
```

The command writes:

- `review-report.json` with source identities, integrity findings, descriptive QC, and optional ground-truth metrics;
- `review-comparison.png` and `review-comparison.svg` with raw EM, ground truth when supplied, and candidate overlays at one physical location.

The report always leaves `scientific_approval` as `withheld`. After a human examines the evidence, record the decision separately:

```powershell
python scripts/review_em_segmentation.py finalize derived/review-report.json `
  --decision approved `
  --reviewer "Expert name or stable ID" `
  --basis "Reviewed raw-overlay alignment and frozen holdout metrics" `
  --claim-scope "Integrity and accuracy on the declared holdout only"
```

Use `--force` only after checking the exact approval-record target. Never overwrite a prior decision silently.

## Interpret evidence conservatively

- With ground truth, report foreground Dice, IoU, precision, and recall. For instance labels, additionally report IoU-thresholded one-to-one matching precision, recall, F1, and mean matched IoU.
- Without ground truth, report foreground fraction, object or component counts, object-size distribution, border contact, and z-span where applicable as descriptive QC only.
- Object count, foreground fraction, or a VLM score alone cannot establish accuracy.
- A 2D review cannot establish 3D continuity or topology.
- Slice-wise overlays can reveal errors but cannot prove the absence of errors elsewhere in a volume.
- When candidates use different grids, offsets, bounds, or label meanings, stop before comparison and request a physically aligned artifact.

## Compose with other EM Skills

Review outputs from `$segneuron-inference`, `$mitonet-inference`, `$bootstrap-em-segmentation`, or another pinned segmentation workflow after their artifact identities and physical grids are fixed. Return the review report, comparison figures, approval record if any, and blocking findings to the upstream Skill. Do not use this Skill to choose beta/profile values from object count alone or to convert draft annotations into final truth.

## Fail closed

Stop when axes, voxel size, label meaning, source identity, or ground-truth provenance is unresolved; arrays are physically misaligned; labels contain negative, non-finite, or non-integral values; a candidate and ground truth are not independent; or the requested claim exceeds the inspected evidence. A figure-only task may proceed with explicit limitations when physical scale is known and no scientific approval is implied.
