# Quality gates

## Pilot acceptance

- source/model-grid raw images align physically and contrast normalization is recorded;
- inference plane and scale are justified by identical-slice comparisons;
- foreground follows mitochondrial outer membranes without widespread ER/Golgi/vesicle leakage;
- elongated mitochondria are not systematically oversplit;
- closely apposed mitochondria are not systematically merged;
- objects remain coherent through z and do not form one-slice pancakes;
- border-touching objects and partial mitochondria are handled by an explicit policy;
- parameter profile, runtime, model, and transforms are frozen;
- a domain expert records approval.

## Automated integrity checks

- output shape, physical bounds, offset, dtype, and background ID match the contract;
- labels are nonnegative integers and non-background IDs are valid;
- nearest-neighbor restoration preserves the label set modulo documented removals;
- foreground fraction, object count, size distribution, z-span distribution, and border-touch fraction are finite and plausible enough for review;
- required logs, hashes, configuration, and figures exist.

These checks detect broken pipelines; they do not prove biological accuracy.

## Accuracy with ground truth

Report semantic and instance performance separately. Include the ground-truth provenance, annotated volume, sampling design, matching rule, IoU threshold, treatment of border objects, and confidence intervals or per-ROI variation where possible. Do not report a single pixel accuracy number as instance quality.

## Approval status

Use `approved`, `withheld`, or `failed`. `withheld` is appropriate when execution is technically valid but metadata, z extent, representative sampling, or ground truth is inadequate for scientific acceptance.
