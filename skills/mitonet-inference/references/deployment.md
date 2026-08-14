# Deployment contract

## Reproducible runtime

Record the host/backend, OS, Python, CUDA, PyTorch, Empanada commit, adapter hash, model variant, checkpoint SHA-256, model config hash, command arguments, start/end times, and exit status. Keep source data read-only and outputs separate.

Use an isolated environment. Do not modify a shared base environment. For an air-gapped host, stage a reviewed wheelhouse, the pinned repository archive/checkout, the model file, and their checksums from a networked machine. Install only inside the project environment with `--no-index --find-links` and preserve the wheel manifest.

Do not put SSH passwords, tokens, private keys, or signed URLs in project YAML, scripts, logs, or the skill. Supply credentials through the execution platform.

## Remote workflow

1. Run local metadata audit and planning.
2. Create a remote project directory owned by the user.
3. Stage the selected ROI first; never begin with the full volume.
4. Verify every uploaded checksum.
5. Render and review commands before execution.
6. Run 2D parameter checks before 3D inference.
7. Retrieve QC figures, metrics, provenance, and logs; large arrays may remain remote with immutable references.
8. Clean up only after the user accepts the deliverables; prefer recoverable moves over deletion.

## Official entrypoint

The bundled adapter calls `scripts/pdl_inference3d.py` from the pinned `volume-em/empanada` checkout. Because the upstream repository is active, verify the entrypoint and arguments at the recorded commit. If they change, stop and update the adapter rather than silently targeting `main`.

Empanada v0.1.7 commit `01c6e7aa3ad0e3c3334df8b129b0122724b6ad2e` contains one internal signature mismatch in the generic 3D script: it passes two parameters that the same commit's `update_trackers` helper no longer accepts. For this exact commit only, the adapter stages a temporary copy and changes that one call to the three-argument form already used by the repository's MitoNet `evaluate3d.py`. The original source is untouched, source and executed hashes are recorded, and an unexpected source line causes a fail-closed error.

## Scaling

Use zarr for large volumes and TIFF for bounded pilots. Estimate input, intermediate per-plane stacks, consensus, and label volumes before execution. Multi-GPU overhead can dominate small volumes; use it only after measurement. Keep label divisor and dtype headroom above the expected number of objects.
