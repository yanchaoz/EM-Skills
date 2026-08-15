---
name: bootstrap-em-segmentation
description: Coordinate adaptation of neuron segmentation to a new or unseen 3D volume EM dataset by composing SegNeuron coarse reconstruction, embedding-guided variable-size annotation selection, expert connectivity correction, training-data handoff, and held-out post-adaptation evaluation. Use when a request spans two or more of these stages, especially for datasets with approximately 5–10 nm xy sampling that need coarse labels converted into efficient expert corrections for SegNeuron fine-tuning or lightweight-model training. Use the child Skills directly for a single inference, visualization, or selection task.
---

# Bootstrap EM Segmentation

Coordinate a closed adaptation loop across specialized Skills. Do not replace the child Skills or reimplement their methods. Use the smallest requested portion of the loop and preserve every artifact handoff.

## Route across Skills

| Stage | Delegate to | Result |
| --- | --- | --- |
| Audit a new volume and produce coarse neuron instances | `$segneuron-inference` | source/model-grid metadata, affinities, beta decision, coarse instances, QC |
| Choose what experts should correct | `$suggest-em-annotations` | variable-size draft subvolumes, UMAP/spatial review, approved annotation queue |
| Correct connectivity and labels | named human expert in an annotation/proofreading tool | corrected labels plus review provenance |
| Fine-tune SegNeuron or train a lightweight model | supplied training repository or future training Skill | pinned checkpoint and training record |
| Compare zero-shot and adapted reconstruction | `$segneuron-inference` plus declared evaluation code | paired holdout metrics, topology review, decision |

For requests confined to one row, invoke that child Skill directly. Trigger this coordinator when identities, splits, physical grids, budgets, or acceptance decisions must remain consistent across rows.

## Compose the adaptation loop

1. **Freeze the evaluation split first.** Record source identity, axes, voxel size, train/selection bounds, and untouched holdout bounds. Never embed, select, correct, or train on the holdout.
2. **Generate the coarse reconstruction.** Use `$segneuron-inference` to audit the volume, run a representative pilot, choose beta, and produce source-grid coarse instances with provenance.
3. **Select correction regions.** Use `$suggest-em-annotations` on the same source volume and holdout guard. Select variable-size subvolumes under a declared annotation budget. Pair every proposal with raw EM and the matching coarse-instance overlay so experts can judge connectivity errors.
4. **Collect expert corrections.** Require a named expert to accept/reject each proposed box and correct merges, splits, missing processes, false foreground, and broken continuity. Preserve coarse and corrected labels; never overwrite the coarse baseline.
5. **Create the training handoff.** Export approved raw/label pairs, physical coordinates, transforms, split membership, reviewer provenance, correction categories, and checksums. Read [composition contract](references/composition-contract.md) before training or export.
6. **Run adaptation only through a real adapter.** Fine-tune SegNeuron or train a lightweight model only when a pinned training repository, configuration, initialization checkpoint, runtime, and expected outputs are available. Otherwise stop at a validated training-data handoff.
7. **Evaluate on the frozen holdout.** Reinvoke `$segneuron-inference` with the adapted checkpoint and compare against the zero-shot baseline on identical source-grid regions. Report split and merge behavior, topology/connectivity evidence, and compute/runtime tradeoffs separately.
8. **Iterate only from training-side evidence.** A new selection round may use unselected training regions; never use holdout errors to choose training boxes.

## Treat 5–10 nm as eligibility, not proof

The general-purpose checkpoint is intended to support zero-shot coarse reconstruction on unseen 3D EM datasets whose xy sampling lies within a validated model profile, commonly around **5–10 nm**. Verify axes, z anisotropy, tissue/domain shift, contrast, and checkpoint profile with a pilot.

Do not claim “outstanding reconstruction performance” from resolution alone. Make that claim only when dataset-specific holdout evidence supports it. Otherwise describe the output as a coarse reconstruction suitable for expert review and potential adaptation.

## Make selective correction a real Skill handoff

`$suggest-em-annotations` chooses where experts work; it does not create labels. Require its final approved queue rather than manually choosing convenient ROIs. Join each selected `bbox_zyx` to the corresponding raw and coarse-instance crop using source-grid coordinates and nearest-neighbor label extraction.

Measure the annotation budget consistently across rounds. Record proposed, accepted, rejected, and corrected volumes separately. Do not treat the number of boxes as annotation cost when box sizes vary.

## Keep training outside unsupported boundaries

This coordinator defines the training contract but does not invent a SegNeuron fine-tuning CLI or lightweight architecture. If the user supplies training code, inspect and pin its real entry points before execution. If no adapter exists, deliver the corrected dataset and a machine-readable handoff manifest, then state that training remains pending.

After training, record model initialization, final checkpoint hash, code revision, configuration, train/validation curves, stopped epoch, and hardware/runtime. Never describe a corrected coarse segmentation as an independently annotated ground truth without documenting the correction protocol.

## Required decision record

Maintain one run record containing:

- source and model identities;
- physical grids and transforms;
- frozen spatial splits and holdout guards;
- SegNeuron coarse-run and beta-selection artifacts;
- annotation-advisor project, budget, UMAP, draft, and final queue;
- expert correction manifest and label hashes;
- training adapter/configuration or explicit pending status;
- zero-shot versus adapted holdout evaluation;
- decision to deploy, iterate, or stop.

Fail closed when identities, coordinate mappings, split isolation, reviewer provenance, or checkpoint provenance cannot be reconciled across Skills.
