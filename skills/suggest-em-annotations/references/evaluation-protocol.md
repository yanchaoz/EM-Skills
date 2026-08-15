# Evaluation protocol

## What must be evaluated

Evaluate the selector at two levels:

1. **Selection mechanics:** determinism, no holdout leakage, exact position order, budget compliance, non-overlap, finite embeddings, monotonic coverage, and reproducible hashes.
2. **Scientific utility:** annotation time/volume, label quality, and downstream neuron-segmentation performance on a fixed held-out set.

## Matched-budget baselines

Compare all methods under the same total annotation voxel budget and the same allowed candidate sizes:

- random multi-scale boxes, repeated across at least five seeds;
- spatially equispaced boxes;
- fixed-size CCR using each individual size;
- variable-size budgeted CCR;
- optional expert manual selection.

Report distributional results for randomized baselines, not only the best seed.

## Downstream evaluation

Use the same annotation SOP, model architecture, training schedule, augmentation, seed policy, and held-out evaluation volume across selection methods. Appropriate neuron-instance metrics can include adapted Rand error and variation of information; define all metric conventions and foreground masks before evaluation.

Variable-size selection is successful only if it improves a decision-relevant outcome, such as held-out segmentation quality at equal annotation time/volume, or reduces annotation cost at equal quality. Higher embedding coverage alone is not sufficient.

## Ablations

At minimum test:

- candidate-size set;
- annotation budget;
- `cost_exponent`;
- `k_neighbors`;
- distance metric;
- overlap rule;
- exact versus approximate nearest neighbors, if ANN is introduced.

## Reporting

Report source/model hashes, split policy, number and physical size of accepted boxes, rejected-box reasons, actual annotation time, annotator identity/experience level, and uncertainty across training seeds. Treat a single AC3AC4 volume run as a pilot, not general validation.
