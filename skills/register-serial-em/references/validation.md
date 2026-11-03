# Validation scope

Validated on 2026-11-03 with Windows, Python 3.12.14, NumPy 2.3.5,
tifffile 2026.3.3 and cloud-volume 12.15.2 in an isolated utility environment.

From the skill directory:

```bash
python -m unittest discover -s tests -v
python -m compileall -q scripts tests
```

Install NumPy, Pillow, tifffile and cloud-volume in that utility environment.
Git must be on PATH for the pinned-source execution test. Optional TIFF/CloudVolume
tests explicitly skip when their libraries are absent; a skipped test is not a pass
for that integration. The recorded run had **13 passing tests, zero skips**.

Coverage includes explicit nonlexical order, independent volume isolation, missing
section/group rejection, output/source separation, dry-run behavior, SEAMLeSS model
requirements, argv JSON preservation, actual subprocess execution against a
temporary pinned Git fixture, unchanged resume and changed-config refusal, pixel
tamper detection, common-mask NCC, undefined constant-image correlation, and a
known-translation/fold geometry fixture.

IO tests write and read complete uint8/uint16/float32 TIFF and precomputed data,
including negative XY offsets, nonzero Z offset, three XY-only levels and export
from CloudVolume back to TIFF. Coarse-grid misalignment and odd-sized averaging
fail explicitly. The test fixtures are generated at runtime and contain no
biological images, credentials or private infrastructure.

The skill-creator frontmatter/scaffold validator also passed. This is distinct
from scientific validation.

An independent forward pass exercised two realistic requests: (1) the public CLI
exported a 3x8x8 uint16 fixture with offset [-4,0,7] to lossless TIFF and three
precomputed levels; separate pixel/metadata checks confirmed all levels, negative
XY origins, constant 100 nm Z sampling and unchanged source hashes; (2) two
independent 100-section symbolic manifests produced separate pilot/full plans for
metroEM/corgie, and missing checkpoints blocked execution before output creation.
These were synthetic utility/decision checks, not backend performance measurements.

## What remains application-specific

No real SOFIMA, metroEM/corgie or FEABAS dataset registration was run as part of
this public skill's test suite. Upstream source/CLI/configuration recipes were
inspected at the commits in upstreams.json. Actual backend installations, learned
checkpoint compatibility, native transform adapters, field inversion/rendering,
large-volume throughput and biological accuracy still require a representative
pilot on the intended acquisition.

The included native-command harness does not replace those libraries, train models,
or transform all native mesh/field formats automatically. Its passing fixture proves
execution/provenance controls, not any registration algorithm.

The scenarios in ../evals/evals.json are behavioral evaluation prompts, not an
automatically measured pass-rate benchmark. Keep future test outcomes tied to
actual artifacts and state their scope.
