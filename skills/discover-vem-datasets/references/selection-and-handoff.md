# Selection and handoff

## Interpret a shortlist

Use explicit user constraints as filters. Do not quietly relax a resolution, species, annotation, access, or license constraint to produce more results. If no record matches, report which constraint eliminated the final candidates and offer a clearly labeled exploratory query.

The CLI `readiness_score` measures catalog completeness and ease of access. It does not estimate image quality, reconstruction accuracy, domain similarity, or publication value. Explain scientific ranking in terms of the user's criteria.

## Verification checklist

Before acquisition or downstream execution, establish:

1. authoritative landing page and stable dataset/version identity;
2. dataset-specific license, terms, and citation requirements;
3. raw and label availability at the requested granularity;
4. array shape, axis order, voxel size, offset, and physical bounds;
5. label object and encoding: semantic, instance, skeleton, point, cleft, or partner;
6. train/validation/test ancestry and leakage risk;
7. format, credentials, expected transfer size, checksum, and resumability;
8. subset or ROI that is scientifically representative and operationally affordable.

Record observed values separately from assumptions. If a source reports several acquisition profiles, select one exact profile in the handoff.

## Downstream compatibility

| Downstream Skill | Minimum useful handoff |
| --- | --- |
| `segneuron-inference` | raw URI/path, zyx grid, voxel size, bounds; neuron instances only when scoring or training is requested |
| `mitonet-inference` | raw URI/path, zyx grid, voxel size; mitochondria label type and holdout when scoring is requested |
| `suggest-em-annotations` | immutable raw identity, candidate bounds, holdout exclusions, available coarse labels |
| `review-em-segmentation` | frozen raw and candidate/GT label identities, physical transforms, label semantics |
| `cloudvolume-video` | source layers, format, physical grid, bounded ROI, label/density semantics |

Compatibility in an exported manifest means "plausible candidate based on catalog metadata," not "execution approved." The receiving Skill must audit the actual source.

## Acquisition boundary

Discovery, comparison, source inspection, and manifest export are read-only. Downloading, converting, mirroring, or publishing data is a separate action. Before one of those actions, state the exact source and target, estimated data volume, credentials, license constraints, overwrite behavior, and stopping condition.
