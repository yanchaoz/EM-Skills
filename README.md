# EM-Skills

**Reusable Agent Skills for Electron Microscopy (EM / Volume EM)**

English | [简体中文](README.zh-CN.md)

EM-Skills is a collection of reusable Agent Skills for professional electron microscopy analysis.

Instead of treating EM analysis as a single model inference step, each skill organizes the complete workflow required for reliable scientific use, including data inspection, physical-resolution planning, pilot validation, model inference, parameter comparison, human review, output restoration, visualization, and quality control.

The goal is simple:

> Turn specialized EM analysis pipelines into reproducible workflows that AI Agents can execute, inspect, and verify.

---

## Available Skills

| Skill                                                        | Purpose                                                       |
| ------------------------------------------------------------ | ------------------------------------------------------------- |
| [`segneuron-inference`](skills/segneuron-inference/SKILL.md) | SegNeuron-based 3D neuron instance segmentation for Volume EM |
| [`mitonet-inference`](skills/mitonet-inference/SKILL.md) | MitoNet/Empanada mitochondrial semantic and 3D instance segmentation |

`segneuron-inference` is designed for datasets such as:

* FIB-SEM
* SBF-SEM
* ATUM-SEM
* ssTEM
* other serial-section or volume electron microscopy datasets

---

## Installation

In Codex, simply ask:

```text
Install skills/segneuron-inference from the GitHub repository yanchaoz/EM-Skills.
Install skills/mitonet-inference from the GitHub repository yanchaoz/EM-Skills.
```

Install the complete skill directory rather than copying only `SKILL.md`.

After installation, start a new Codex task so the skill can be discovered.

---

## How to Use

The skill can be invoked directly with natural language.

For example:

```text
Use the segneuron-inference skill on this zyx Volume EM dataset.

First inspect the dataset shape, axis order, and physical voxel resolution.
Plan the appropriate SegNeuron model grid based on the real physical resolution.

Run a representative pilot before processing the full volume.

Then perform affinity inference and generate several instance-segmentation candidates
for beta = [0.10, 0.25, 0.50, 0.75].

Create comparison figures at identical physical locations so I can inspect
merge errors, split errors, fragmentation, foreground leakage, and z continuity.

Wait for my beta selection before generating the final 3D instance segmentation.

Finally restore the labels to the target resolution, verify the outputs,
and generate quality-control visualizations.
```

A shorter instruction also works:

```text
Use segneuron-inference on this Volume EM dataset.
Run a pilot first, compare multiple beta values,
wait for my selection, and then generate the final neuron instances.
```

### MitoNet example

```text
Use the mitonet-inference skill on this zyx Volume EM dataset.
Audit axis order and physical voxel resolution, then run a representative pilot.
Compare named MitoNet profiles across plausible xy scales and thresholds.
Render raw EM, mitochondrial foreground, instance overlays, and XZ continuity.
Wait for my profile selection before full-volume inference and label restoration.
```

The MitoNet workflow keeps semantic foreground, per-plane panoptic instances, 3D stack matching, source-grid restoration, and scientific approval as separate gates.

---

## Standard Workflow

The recommended workflow is:

```text
Source Volume EM
        ↓
Data & Metadata Audit
        ↓
Physical Resolution Planning
        ↓
Representative Pilot
        ↓
SegNeuron Affinity Inference
        ↓
Multi-Beta Instance Candidates
        ↓
Visual Comparison
        ↓
Human Beta Selection
        ↓
Final 3D Instance Segmentation
        ↓
Label Restoration
        ↓
Verification & Quality Control
        ↓
Final Output
```

### 1. Data audit

The skill first checks essential dataset information, including:

* volume dimensions;
* axis order;
* voxel resolution;
* physical units;
* image characteristics;
* compatibility with the model input grid.

Physical metadata is treated as part of the scientific workflow rather than an optional implementation detail.

---

### 2. Physical-resolution planning

Volume EM datasets often have different voxel sizes and substantial z anisotropy.

The skill therefore plans model input according to **physical resolution**, rather than simply resizing arrays based on image dimensions.

This helps maintain consistent biological scale across datasets acquired with different microscopes or imaging protocols.

---

### 3. Pilot before full-volume processing

A small representative region is processed first.

The pilot is used to verify:

* orientation;
* resolution handling;
* model compatibility;
* affinity predictions;
* segmentation behavior;
* visualization;
* downstream postprocessing.

Only after the pilot is considered technically reasonable should the workflow proceed to larger-scale processing.

---

### 4. Affinity inference

SegNeuron predicts affinity information describing local neuronal connectivity.

The affinity output is then used as the basis for instance-level reconstruction.

Inference and instance reconstruction are treated as separate stages so that failures can be diagnosed more clearly.

---

### 5. Multi-beta comparison

Instance reconstruction can change substantially with the postprocessing parameter `beta`.

Instead of silently using one predefined value, the skill can generate several candidates, for example:

```text
beta = 0.10
beta = 0.25
beta = 0.50
beta = 0.75
```

All candidates are compared at the same physical locations.

Important failure modes include:

* merged neurites;
* over-segmentation;
* fragmented processes;
* incorrect foreground expansion;
* poor z continuity;
* local topology errors.

The workflow does **not** automatically select beta from the number of reconstructed objects.

---

### 6. Human selection

The user reviews the candidate segmentations and explicitly chooses the preferred beta.

This creates a deliberate human-in-the-loop checkpoint before final whole-volume reconstruction.

A previously selected beta is not assumed to remain valid when the relevant configuration or data-processing settings change.

---

### 7. Final reconstruction

After the user selects beta, the final 3D neuron instances are generated.

The resulting segmentation can then be restored from the model grid to the desired output grid while preserving discrete instance identities.

---

### 8. Verification and quality control

A completed run is not automatically considered scientifically validated.

The workflow also checks whether outputs are internally consistent and whether the available evidence is sufficient for downstream use.

A result may therefore be:

* technically completed;
* structurally valid;
* but still withheld from scientific approval.

This distinction is intentional.

---

## Result Visualization

The skill provides standardized scientific visualizations for inspecting the complete SegNeuron workflow.

A typical summary includes:

1. raw EM;
2. SegNeuron affinity prediction;
3. membrane or boundary evidence;
4. neuron instance overlay.

Example:

![syn178 SegNeuron summary](examples/syn178-pilot/segneuron-summary.png)

The overlay uses deterministic instance colors so that the same instance can be followed consistently across slices and comparisons.

Physical voxel resolution is also used when generating scale bars and orthogonal views.

---

## Beta Comparison

The same affinity prediction can be reconstructed with multiple beta values and displayed side by side.

Example:

![syn178 beta sweep](examples/syn178-pilot/beta-sweep.png)

This allows direct inspection of how instance topology changes as postprocessing becomes more or less aggressive.

The selected beta should be based on segmentation quality rather than on object count alone.

---

## syn178 Pilot Example

The repository includes a small pilot example based on:

```text
syn178/raw[:18, :256, :256]
```

Under the recorded metadata assumption:

```text
source grid: 50 × 4 × 4 nm
model grid:  50 × 8 × 8 nm
```

the pilot produced a three-channel SegNeuron affinity volume and corresponding 3D neuron-instance candidates.

Using the recorded pilot configuration at:

```text
beta = 0.25
```

the official SegNeuron FRMC postprocessor produced 35 non-background 3D instances.

The example demonstrates that the complete workflow can be executed end to end.

It does **not** claim production-level segmentation accuracy.

---

## Why the Pilot Is Not Considered Scientific Validation

The syn178 example is intentionally treated as a workflow demonstration rather than a benchmark.

Scientific approval remains withheld because:

* only 18 z slices are included;
* the dataset is strongly anisotropic;
* the physical resolution is based on metadata that still requires confirmation;
* the z extent is limited for evaluating long-range neuronal continuity;
* neuron-instance ground truth is unavailable.

In other words:

> A workflow that runs successfully is not automatically a scientifically validated reconstruction.

---

## MitoNet syn178 Pilot

The repository includes a remote MitoNet-mini workflow demonstration on `syn178/raw[:18, :256, :256]`. The 8 nm and 16 nm profiles detected the same mitochondrial candidate with binary-mask Dice `0.8710`; the 8 nm result retained a slightly larger boundary and one additional z slice.

![syn178 MitoNet 8 nm QC](examples/syn178-mitonet-pilot/qc-scale-8nm.png)

![syn178 MitoNet 16 nm QC](examples/syn178-mitonet-pilot/qc-scale-16nm.png)

See the [MitoNet pilot record](examples/syn178-mitonet-pilot/README.md) for parameters, hashes, limitations, and vector figures. This is an execution and QC demonstration, not a ground-truth benchmark.

---

## Design Principles

EM-Skills follows several principles for scientific EM analysis.

### Physical scale matters

Model deployment should respect real voxel size and biological scale rather than relying only on array dimensions.

### Pilot before scale

A representative test volume should be processed before expensive whole-volume inference.

### Separate prediction from reconstruction

Affinity inference and neuron-instance reconstruction are different stages and should be inspected separately.

### Human review for topology-sensitive decisions

Some reconstruction parameters cannot be selected reliably from a single scalar statistic.

### Preserve reproducibility

Important model, data, physical-resolution, and postprocessing decisions should remain traceable.

### Fail closed

Missing metadata, incomplete outputs, or insufficient evidence should be reported rather than silently accepted.

---

## Intended Use

EM-Skills is designed for research workflows involving:

* connectomics;
* neuronal reconstruction;
* neuron instance segmentation;
* organelle segmentation;
* ultrastructural analysis;
* large-scale Volume EM;
* AI-assisted electron microscopy;
* scientific EM quality control.

The repository is intended to gradually expand into a broader collection of reusable EM-specific Agent Skills.

---

## Documentation

For the full technical specification of the current skill, see:

* [SegNeuron Inference Skill](skills/segneuron-inference/SKILL.md)
* [Configuration Reference](skills/segneuron-inference/references/config-schema.md)
* [Deployment Guide](skills/segneuron-inference/references/deployment.md)
* [MitoNet Inference Skill](skills/mitonet-inference/SKILL.md)
* [MitoNet Configuration Reference](skills/mitonet-inference/references/config-schema.md)

---

## Repository Philosophy

EM-Skills is not intended to be a repository of isolated inference scripts.

It aims to package expert EM workflows into reusable Agent Skills that combine:

```text
Domain knowledge
      +
Model execution
      +
Physical-scale reasoning
      +
Human review
      +
Quality control
      +
Reproducibility
```

so that AI Agents can assist with EM reconstruction in a structured and scientifically responsible way.

---

## License

See the repository license for usage and redistribution terms.
