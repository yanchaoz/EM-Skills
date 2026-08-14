# Official SL-SSNS adapter

Use this route only when the user asks to run the official encoder or already has a compatible environment. Do not install dependencies or execute remote code by default.

## Pin and verify

1. Clone `https://github.com/yanchaoz/SL-SSNS` into an isolated environment.
2. Checkout the recorded commit. The version audited for this skill is `caa0ae6157be79fa1e39b047c10500c3c6f62cc0`.
3. Verify `CGS/selection_model.ckpt` SHA-256. At the audited commit it is `fd430e366feb335fc4d6aea50ee0093601855f61faab4925ec39fc4f6f344908`.
4. Record Python, PyTorch, CUDA, GPU, NumPy, h5py/imageio, UMAP, and YAML package versions.

## Required safe adaptations

- Replace the fixed `cuda:3` choice with an explicit device argument.
- Remove or explicitly configure the `[:100]` z truncation.
- Confirm data axes are z-y-x and intensity normalization is `float32 / 255` only for uint8-compatible input.
- Emit patch positions and embeddings in deterministic order; do not shuffle the inference loader.
- Do not use the public dense pairwise matrix for large volumes. Feed the embeddings to `em_annotation_advisor.py select` or a separately validated ANN implementation.
- Run without the blocking `plt.show(block=True)` call on remote/headless systems.
- Treat reflected padding as part of the model-input contract and keep source-coordinate clipping explicit.

## Compatibility check

Before selection, verify all of the following:

- model output is `[N, 80]` for the audited checkpoint;
- embedding row count equals manifest patch count;
- every recorded position exactly matches the manifest position;
- no NaN/Inf or zero-norm vector exists when cosine distance is requested;
- source hash, checkpoint hash, commit, configuration, and position-order hash are saved.

The included Skill does not redistribute the checkpoint. Its license and citation remain those of the upstream repository and paper.
