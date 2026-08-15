# EMFoundation BASE adapter

## Audited local reference

The adapter mirrors the model-loading path in:

```text
/opt/data/3_33/SCN/zhangyc/EMFoundataion/Code/Figure2-Exps-UMAP/extract_encoder_umap.py
```

That script loads:

```text
/opt/data/3_33/SCN/zhangyc/EMFoundataion/Code/Pretraining_mito/models/BASE/learner.ckpt
```

with `PNIv2_head.UNet_PNI(num_features=[32,64,128,256,512])`. It keeps checkpoint keys containing `encoder`, strips the `sp_cnn.` prefix, calls `hierarchical=True`, and uses adaptive-average-pooled center features. The resulting embedding dimension is 512.

This differs from the public SL-SSNS paper configuration, which reports an 80-dimensional selection encoder. Record which encoder produced every result; do not mix the two contracts.

## Data and preprocessing contract

- Input at the adapter boundary is a 3D z-y-x TIFF.
- Default patch and stride are `[32,128,128]` and `[16,64,64]`.
- `align_end` appends a final end-aligned patch on axes where the regular stride misses the boundary.
- The reference normalization converts to float32, divides by 255 when the patch maximum exceeds 1.5, then applies per-patch z-score normalization.
- Intensities above 255 fail closed because the reference transform has not been validated for high-dynamic-range data.

## Weight-load acceptance

A valid run must report a nonzero number of compatible encoder keys and a 512-column output. Preserve the complete matched-key list in `embedding_run.json`. Missing decoder or non-encoder keys are expected because this is an encoder-only load; zero matched encoder keys are a hard failure.

## Permission failure

If the input TIFF raises `PermissionError`, stop and report the exact path and Unix permission evidence. Do not use synthetic embeddings, an unrelated dataset, the instance mask, or a previously generated UMAP archive as a substitute.

## Provenance

Keep these together:

- source and checkpoint SHA-256;
- code path and revision note;
- Python, PyTorch, NumPy, tifffile, CUDA device;
- input shape, dtype, axes, voxel size;
- patch, stride, boundary mode and position hash;
- embedding shape and hash.

