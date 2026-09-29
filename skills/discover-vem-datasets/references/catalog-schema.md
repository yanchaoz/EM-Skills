# Catalog schema

The bundled `datasets.json` is a curated, machine-readable snapshot of task-relevant records from `yanchaoz/awesome-vem-datasets`. It is intentionally smaller than the upstream museum. Add a record only when it improves a realistic discovery or handoff request.

## Top-level fields

| Field | Meaning |
| --- | --- |
| `schema_version` | Catalog contract version. This Skill supports major version `1`. |
| `catalog_id` | Stable identifier for this snapshot family. |
| `snapshot` | Upstream repository, commit, capture date, scope, and catalog license. |
| `datasets` | Array of normalized dataset records. |

## Dataset record

Required fields:

- `id`: lowercase stable identifier using letters, digits, and hyphens;
- `name`: human-facing name;
- `aliases`, `species`, `tissues`, `modalities`: arrays of strings;
- `voxel_size_nm_zyx`: `[z, y, x]` in nanometres, or `null` when unresolved;
- `annotations`: controlled tags such as `neuron_instance`, `membrane`, `mitochondria_instance`, `mitochondria_semantic`, `synapse`, `skeleton`, or `unlabeled`;
- `tasks`: controlled tags such as `neuron_segmentation`, `mitochondria_segmentation`, `connectomics`, `pretraining`, or `visualization`;
- `raw_available`, `labels_available`: `yes`, `no`, or `unknown`;
- `access`: status, URLs, format, and dataset-specific license;
- `metadata_status`: `reported`, `partially_verified`, or `verified`;
- `last_verified`: date of the record-level check, or `null`;
- `sources`: at least one evidence URL;
- `notes`: concise caveats that change selection decisions.

## Access fields

`access.status` is one of:

- `open`: no approval is reported, though hosting terms may still apply;
- `registration`: account or click-through registration is reported;
- `request`: explicit access approval is reported;
- `restricted`: use is limited by stated conditions;
- `unknown`: current access was not established.

`access.dataset_license` refers to the dataset, not this repository or the upstream catalog. Use `unknown` rather than guessing. Each entry in `access.urls` contains a `role`, URL, and reported format.

## Evidence state

`reported` means the metadata was transcribed from the upstream curated catalog or a cited publication but was not independently probed in this Skill snapshot. `partially_verified` means at least one authoritative source or endpoint was checked but material fields remain unresolved. `verified` requires current authoritative evidence for the fields used by the intended task; it is not a permanent property.

Run:

```powershell
python scripts/vem_dataset_catalog.py validate
```

after every edit. Validation checks structure and invariants, not scientific truth or URL availability.
