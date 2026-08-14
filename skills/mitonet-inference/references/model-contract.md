# MitoNet and Empanada model contract

## Identity

This skill targets the MitoNet model described by Conrad and Narayan, *Cell Systems* 14(1), 58?71.e5 (2023), DOI `10.1016/j.cels.2022.12.006`, and its official software repositories:

- `volume-em/empanada`: core algorithms; GPL-2.0 repository license.
- `volume-em/empanada-napari`: deployment/plugin layer; BSD-3-Clause repository license.
- MitoNet TorchScript model files: Zenodo DOI `10.5281/zenodo.6861565`.

Pin exact commits and model checksums per project. The repositories are active and may contain breaking changes.

## Outputs

The model accepts a grayscale 2D EM image and predicts semantic class scores, vertical/horizontal offsets, and object-center heatmaps. Panoptic postprocessing creates 2D instances. Empanada creates 3D labels by matching objects across adjacent slices; orthoplane mode additionally combines XY/XZ/YZ stacks through consensus.

Use stack mode for strongly anisotropic data unless pilot evidence shows other planes are reliable. Orthoplane inference is most defensible for near-isotropic data or data resampled with an explicitly audited transform.

## Model variants

- `MitoNet_v1`: Panoptic DeepLab, larger and generally preferred when memory permits.
- `MitoNet_v1_mini`: Panoptic BiFPN, lower memory and faster; the paper reports a tradeoff in instance accuracy.
- Quantized variants: CPU-only deployment artifacts. Record quantization explicitly and do not compare their output to full-precision results as though the runtime were identical.

## Resolution and scaling

MitoNet output is resolution-sensitive. Treat the target xy pixel size or Empanada image-downsampling factor as a pilot parameter, not a universal constant. Preserve physical extent when preparing a model grid and preserve z by default for anisotropic stack inference.

Published applications and benchmarks often standardize near-isotropic volume EM near 16 nm/pixel, but this is evidence for a candidate profile, not a guarantee for every modality. Test at least two plausible scales when native sampling differs materially.

## Parameter semantics

- segmentation confidence: foreground probability threshold; changes semantic extent.
- center confidence and center minimum distance: control 2D instance centers and therefore splitting.
- fine boundaries: higher-resolution postprocessing with increased memory cost.
- median kernel: smooths semantic predictions through a stack; its physical span depends on voxel size.
- merge IoU / IoA: match or merge instances between adjacent slices.
- pixel vote and cluster IoU: govern orthoplane consensus.
- minimum size and minimum span: remove small objects and thin ?pancakes?; convert their voxel units to physical interpretation before freezing.

## Known error modes

The source paper documents missed small or low-contrast mitochondria, confusion with other membranous organelles, difficulty with closely apposed mitochondria, and both overmerge and oversplit errors. Generalist performance varies by dataset; finetuning and proofreading remain valid outcomes when the zero-shot pilot fails.
