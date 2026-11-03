---
name: register-serial-em
description: Register serial-section electron microscopy images with Google SOFIMA, the Popovych et al. Nature Communications metroEM/corgie pipeline (SEAMLeSS and ABCD), or Yuelong Wu's FEABAS. Use for backend selection, alignment pilots or comparisons, execution through official tools, transform and continuity QC, and lossless TIFF or XY-only CloudVolume delivery. Reuse existing transforms for export-only requests. Excludes cryo-EM particle alignment and cross-subject anatomical registration.
---

# Register Serial EM

Integrate three official workflows through shared data, provenance, comparison and
delivery contracts. They are alternative backends, not three deformations to apply
successively. Run only the stages the user requested.

## Route the task

| Request | Action | Read |
|---|---|---|
| Choose or compare methods | Use identical pilot sections and physical fields | [Backend selection](references/backends.md) |
| SOFIMA | JAX optical flow and elastic mesh; preserve map direction and origin | [SOFIMA recipe](references/sofima.md) |
| Princeton / Popovych Nat Commun | **metroEM + corgie**: SEAMLeSS pair alignment and ABCD block composition | [metroEM/corgie recipe](references/metroem-corgie.md) |
| Harvard / Yuelong Wu FEABAS | Section order, tile geometry, material masks and finite-element alignment | [FEABAS recipe](references/feabas.md) |
| Diagnose or compare existing results | Common valid pixels, XY/XZ/YZ views and native geometry | [QC](references/quality.md) |
| TIFF, precomputed or video | Reuse accepted aligned pixels and transforms | [Delivery](references/delivery.md) |

The Popovych reference is *Petascale pipeline for precise alignment of images from
serial section electron microscopy*, **Nature Communications 15, 289 (2024)**,
[DOI: 10.1038/s41467-023-44354-0](https://doi.org/10.1038/s41467-023-44354-0).
An unrelated block matcher is not a reproduction of its learned alignment method.

## Establish the data contract

Read [the project contract](references/project-contract.md). Record explicit section
order, independent-volume boundaries, axes/dtype, XYZ voxel size in nm, valid
regions, missing/damaged sections, and requested outputs. Multiple directories with
their own `layer1` sequences might be independent volumes, consecutive Z blocks or
XY tiles. Resolve that relationship before dependent work.

Use one ordered manifest per independent volume. Preserve source files. A derived
subdirectory beneath the raw root is valid when disjoint from the input files.
Never silently concatenate groups, compact missing Z positions, inpaint defects,
change contrast, or discard displaced borders.

Run the helper on the machine where the data reside:

```bash
python scripts/registration_workflow.py audit project.json --out audit.json
python scripts/registration_workflow.py plan project.json --backend sofima --group volume-a --stage pilot --out pilot-plan.json
python scripts/registration_workflow.py run project.json --backend sofima --group volume-a --stage pilot --execute
```

Start from [the example project](assets/project.example.json). Configure real argv
arrays using the selected recipe. `plan` launches nothing. `run` checks pinned
repositories, checkpoint hashes, run identity and declared outputs before invoking
commands without a shell. It is a native-command harness, not a replacement
implementation of the algorithms. Unconfigured stages are `needs_configuration`
and cannot execute. Preserve existing authorization; do not add another approval
gate to an already authorized run.

## Pilot and scale

Include ordinary pairs, large offsets, representative defects/low texture and block
boundaries in a bounded pilot. Use one physical reference; record rigid initialization.
Tune patch/mesh spacing in physical units. Verify forward/inverse direction using a
known shift. For comparisons, use separate backend outputs and report runtime,
memory, coverage, deformation and failures alongside continuity.

Scale up when the pilot supports the requested outcome and resources. Checkpoints
must match source, code, model and configuration identities. Changed parameters
require a new run or deliberate invalidation of affected outputs. Do not erase
native caches silently. Training a new SEAMLeSS model is a separate requested action.

## Preserve geometry and evidence

- Declare array axes, map components, spacing, origin, direction and units. SOFIMA
  relative XY offsets, FEABAS meshes and corgie fields need verified adapters.
- Estimate the transformed union canvas before native rendering. Retain negative
  offsets. A larger canvas does not change pixel size.
- Render original intensities once with final transforms where the backend permits;
  keep matching-only normalization separate from delivered data.
- Check finite coordinates, local orientation and numerical inverse consistency for
  continuous maps. For tears, evaluate native material/component geometry rather
  than a global smooth-map test across discontinuities.
- Preserve transforms, masks, rejected matches and defect notes. Metadata dimensions
  alone do not establish registration quality.

## Deliver and verify

Describe accepted output using [the result manifest](assets/result.example.json):

```bash
python scripts/export_aligned.py result.json --output exported --tiff
python scripts/export_aligned.py result.json --output exported-cv --cloudvolume --mips 6
```

TIFF and CloudVolume are separate deliverables. Keep original dtype and native XY
sampling. For XY-only pyramids, use `(2,2,1)` and verify Z count, spacing and offset
at every level. Read the delivery reference for grid alignment and odd dimensions.

Report what was executed, read back and visually inspected; include failures and
unevaluated backends. Integrity checks and correlation are not ground-truth accuracy
or human scientific approval. For video, read the written result, show before/after
and orthogonal views, and label display-only Z exaggeration. The sibling
`cloudvolume-video` skill can handle presentation when installed; audit and export
do not require it.

Run `python -m unittest discover -s tests -v` from this skill directory. Synthetic
tests validate contracts and utilities, not three-algorithm performance. Read
[validation status and forward-test cases](references/validation.md).
