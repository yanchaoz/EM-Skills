---
name: discover-vem-datasets
description: Discover, compare, and audit public volume electron microscopy datasets for a biological target, imaging modality, physical resolution, annotation type, access constraint, or downstream EM task. Use when selecting benchmark, pretraining, fine-tuning, evaluation, visualization, or proofreading data and when exporting a dataset handoff for another EM Skill. Do not use to run segmentation models or silently download large datasets.
---

# Discover vEM Datasets

Turn a scientific data requirement into a traceable shortlist or a machine-readable handoff. Treat the bundled catalog as a curated index derived from [awesome-vem-datasets](https://github.com/yanchaoz/awesome-vem-datasets), not as proof that every upstream field or URL remains current.

## Route the request

| User intent | Capability | Result |
| --- | --- | --- |
| Find data matching biological or technical constraints | `query` | strict filtered shortlist with unresolved fields |
| Compare known candidates | `query`, then evidence review | criterion-by-criterion comparison without invented metadata |
| Check whether one dataset is usable | catalog record plus authoritative source audit | access, license, format, axes, resolution, and label-semantic findings |
| Prepare another EM Skill | `manifest` | dataset identity, physical metadata, access plan, risks, and required checks |
| Add or update a catalog record | schema validation | normalized record with source and verification state |

Use the smallest capability that answers the request. A simple question about one known dataset does not require a full catalog export.

## Separate reported metadata from verified facts

- Preserve `reported`, `partially_verified`, and `verified` states. A row in the source catalog is reported metadata until its authoritative landing page or data endpoint is checked.
- Do not inherit the catalog repository's MIT license as the dataset license. Keep `dataset_license: unknown` until the dataset's own terms are found.
- Do not infer axis order, label semantics, download size, format, checksum, or public availability from a paper title or repository name.
- When the user asks for current availability, licensing, or exact acquisition instructions, inspect the authoritative source at execution time and record the check date.
- Unknown fields fail strict filters by default. Include them only when the user explicitly wants exploratory candidates.

## Query the bundled snapshot

Run from the Skill directory:

```powershell
python scripts/vem_dataset_catalog.py validate
python scripts/vem_dataset_catalog.py query --species mouse --tissue cortex --max-xy-nm 10 --annotation neuron_instance --require-labels
python scripts/vem_dataset_catalog.py query --annotation mitochondria_instance --access-status open --format json --output shortlist.json
python scripts/vem_dataset_catalog.py manifest --id snemi3d-ac3-ac4 --downstream segneuron-inference --output dataset-manifest.json
```

The script uses only the Python standard library. Read [catalog schema](references/catalog-schema.md) when editing records or interpreting fields. Read [selection and handoff](references/selection-and-handoff.md) when ranking candidates or preparing another Skill.

The bundled snapshot is deliberately focused rather than exhaustive. If it yields no match, the user asks for a comprehensive or current survey, or the requested organ/taxon is outside the snapshot, search the current upstream `README.md` and `DATASET.md`, then verify promising records at their authoritative sources. Label live-only findings as such; do not silently append them to the maintained snapshot during an unrelated task.

## Select on scientific fit before convenience

Apply user constraints as hard filters when they are explicit. Among remaining candidates, compare:

1. biological fit: species, tissue, developmental state, pathology, and preparation;
2. imaging fit: modality, voxel size, anisotropy, contrast, and artifact regime;
3. supervision fit: object type, semantic versus instance labels, dense versus sparse coverage, and proofreading status;
4. operational fit: access conditions, format, volume size, license, version, and storage/compute cost;
5. evaluation fit: independence from training data, frozen split availability, and leakage risk.

Do not collapse these into a single unexplained score. The script's readiness score reflects metadata completeness and access convenience, not scientific performance.

## Audit before acquisition or claims

Before recommending a dataset as ready to use, verify the fields that affect the requested task. At minimum check the authoritative landing page, dataset-specific license or terms, exact raw/label availability, axes and voxel size, label semantics, version identity, and expected transfer size. For CloudVolume/precomputed, Zarr, N5, or TIFF endpoints, inspect actual metadata when access is available.

Never start a large download merely because a candidate was selected. First report the proposed source, subset or ROI, estimated bytes, destination, expected credentials, and whether the action is resumable; then obtain authorization.

## Hand off to other EM Skills

Export a manifest rather than copying an informal URL:

- `$segneuron-inference`: raw volume identity, axes, `voxel_size_nm_zyx`, bounds, and neuron-label availability if evaluation or fine-tuning is planned.
- `$mitonet-inference`: raw identity, physical grid, mitochondria label semantics, and evaluation split.
- `$suggest-em-annotations`: immutable source identity, usable bounds, exclusion/holdout regions, and annotation budget context.
- `$review-em-segmentation`: frozen raw/label identities, label semantics, transforms, and evaluation scope.
- `$cloudvolume-video`: source URI or local path, format, axes, physical grid, layers, and bounded presentation ROI.

The generated manifest is a candidate handoff. The receiving Skill must still verify the actual arrays and physical metadata before inference, training, evaluation, or visualization.

## Fail closed

Do not call a dataset task-ready when its access terms, dataset license, physical grid, label meaning, or source identity is unresolved and material to the requested use. Return the best available candidates with explicit gaps and the next verification action instead.
