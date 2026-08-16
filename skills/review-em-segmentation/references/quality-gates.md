# Quality gates

## Integrity gate

Require all of the following before metric comparison:

- raw, candidates, and optional ground truth identify the same physical ROI;
- shape, axes, resolution, offset, and bounds are compatible;
- label meaning and background ID are declared;
- arrays are readable and labels are finite non-negative integers;
- source artifacts remain immutable and outputs are separate.

## Evidence gate

Classify the result explicitly:

| Evidence | Allowed claim |
| --- | --- |
| Integrity checks only | Files are structurally compatible |
| Descriptive QC without truth | Observed foreground, component, object-size, border, and z-span properties |
| Frozen independent ground truth | Accuracy on the declared evaluation sample using the reported metrics |
| Expert review plus representative evaluation | Approval for the expert's declared claim scope |

Do not generalize performance beyond the inspected dataset, structures, resolution, modality, or acquisition conditions.

## Visual gate

Inspect the same physical locations for every candidate. Review more than the automatically selected slice for final delivery, including difficult and low-contrast regions. For volumes, include orthogonal views when anisotropy and z extent permit.

Look for:

- foreground leakage into membranes, resin, nuclei, ER, vesicles, or other confounders;
- missed low-contrast structures;
- instance merges, splits, fragments, and duplicate IDs;
- truncated objects at ROI borders;
- pancakes, discontinuities, seams, and topology loss through z;
- display resampling that hides one-voxel structures or boundaries.

## Approval gate

The deterministic report always sets `scientific_approval: withheld`. Record `approved`, `rejected`, or `withheld` only after a named reviewer inspects the evidence. Store the review basis and claim scope. A VLM note, candidate rank, object count, or foreground fraction cannot authorize approval.

If severe unresolved errors remain, select `rejected` or `withheld`, state the blocking evidence, and return the result to the responsible upstream Skill.
