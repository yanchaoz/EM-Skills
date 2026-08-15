# Method and evidence

## Verified sources

- Published article: Yanchao Zhang, Hao Zhai, Jinyue Guo, Jing Liu, Qiwei Xie, and Hua Han, “A distribution-aware semi-supervised pipeline for cost-effective neuron segmentation,” *iScience* 29(1), article 114507. DOI: https://doi.org/10.1016/j.isci.2025.114507. It was first published online on 2025-12-19; the issue year is 2026.
- Open full text: https://pmc.ncbi.nlm.nih.gov/articles/PMC12805337/ (PMCID PMC12805337; PMID 41550775).
- Official code: https://github.com/yanchaoz/SL-SSNS, audited at commit `caa0ae6157be79fa1e39b047c10500c3c6f62cc0` on 2026-08-14. Repository license: MIT.
- Public Colab linked by the repository: https://colab.research.google.com/drive/1vPYYeaycpdQjDiu_TQD4LqQbjezf40yc?usp=sharing. The notebook describes visualization in spatial and embedding domains and states that selected subvolumes are subsequently manually or semi-automatically labeled.
- Earlier preprint: https://doi.org/10.1101/2024.05.26.595303. Prefer the published article for method claims.

## What CGS does

1. Train a 3D EM patch encoder by SimSiam-style self-supervision across fly, mouse, and human EM data.
2. Partition unlabeled volumes into patches and map every patch to an embedding vector.
3. Bind spatially adjacent patch vectors into candidate subvolumes.
4. Let each patch cover its K nearest embedding neighbors. The constrained coverage rate (CCR) is the fraction of the universal patch set covered by at least one selected vector.
5. Greedily select the spatially valid candidate that gives the greatest increase in CCR, then repeat until the annotation budget is exhausted.

The paper reports 18×160×160 input patches, 8×40×40 sliding stride, 80-dimensional embeddings, and K=30. It evaluates dataset-specific subvolume sizes because anatomical scales and voxel sizes differ.

## Evidence boundary

The publication supports CGS as a one-shot representative-selection heuristic and reports downstream improvements on its evaluated datasets. It does not establish that a chosen region is uncertain, biologically rare, correctly segmented, artifact-free, or optimal for every new dataset. A new dataset needs held-out evaluation and random/equispaced baselines before making efficiency claims.

## Local EMFoundation BASE evidence

The audited Figure2 UMAP script uses a different operational encoder contract from the public 80-D CGS checkpoint: `PNIv2_head.UNet_PNI([32,64,128,256,512])`, patch `32×128×128`, stride `16×64×64`, and a 512-D pooled center feature loaded from `Pretraining_mito/models/BASE/learner.ckpt`. The Skill's EMFoundation adapter reproduces that local contract because it is the model requested for AC3AC4 testing. It does not claim that this 512-D representation is identical to the paper's 80-D selection encoder.

Variable-size selection is a new budgeted extension implemented by this Skill. The paper motivates contiguous embedding-coverage selection and dataset-dependent subvolume sizes, but does not validate the exact multi-scale knapsack heuristic used here.

## Audited implementation discrepancies and risks

- `CGS/CGS_tools.py` slices loaded volumes with `[:100]`; this silently discards later z slices for larger inputs.
- `CGS/CGS.py` selects `cuda:3` whenever CUDA exists instead of accepting a device parameter.
- The implementation constructs a dense N×N distance matrix, causing O(N²) memory and time.
- The public config uses patch 18×160×160, stride 8×40×40, and window 1×9×9. Its extraction formula therefore yields 18×480×480, whereas the paper lists examples such as 18×380×380 on AC3/AC4. Treat paper datasets and repository demo config as distinct configurations.
- README pretraining paths (`Pretraining/pretraining.py`) differ from the repository tree (`Pretrain/pretrain.py`).
- UMAP is a visualization only. Apparent clusters must not be labeled as biological classes without independent evidence.

## Decision record

- Implement only the annotation-selection component, because the requested outcome is annotation advice rather than full IIC-Net training.
- Preserve CCR neighborhood coverage, but expose a separate multi-scale, cost-aware greedy objective for variable-size boxes.
- Use the locally audited 512-D EMFoundation BASE adapter for the specified AC3AC4 workflow; retain the public 80-D CGS adapter only as a separate legacy/reference route.
- Use blocked exact KNN to bound working memory while disclosing quadratic time.
- Require explicit geometry, provenance, holdout guards, and human review.
- Avoid embedding the SL-SSNS checkpoint or repository code in this skill; use a pinned external adapter when requested.
