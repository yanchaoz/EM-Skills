# Popovych et al.: metroEM + corgie / SEAMLeSS + ABCD

Reference: *Petascale pipeline for precise alignment of images from serial section
electron microscopy*, Nature Communications **15, 289 (2024)**,
[DOI 10.1038/s41467-023-44354-0](https://doi.org/10.1038/s41467-023-44354-0).

Official [metroEM](https://github.com/seung-lab/metroem) handles learned multiscale
alignment/training; [corgie](https://github.com/seung-lab/corgie) orchestrates block
alignment, multiple-reference voting and **Alignment of Blocks and Composition with
Decay (ABCD)**. Pin both. Their LICENSE files specify Apache-2.0 (the old corgie
README's license sentence is inconsistent). Do not relabel unrelated block matching
as this method.

## Environment and model gate

Corgie's documented stack is older (Python 3.7–3.9, PyTorch >=1.8, Click <8 in the
inspected setup.py). Use a dedicated compatible environment and confirm
`corgie --help`, `corgie align-block --help`, `corgie align --help`.
The common harness can run under a newer Python and invoke this separate executable.

Require the model's acquisition domain, expected physical XY scale, preprocessing
and complete local checkpoint-file SHA256 manifest. Checkpoint URLs alone are
mutable. Match each processor_mip to physical voxel size at that level; mip index
alone is insufficient across datasets.

The official MICrONS example model is named for **512/1024 nm**:
`https://storage.googleapis.com/corgie_package/models/aligners/MICrONS_aligner_512_1024nm`.
It is a demonstration, not evidence of fine registration at native 5 nm.
Download only if authorized by the task and compatible; hash all required files.
Missing/incompatible weights mean needs_configuration, not silently running a
different algorithm. Training requires separately specified data, compute and scope.

## Bounded native pilot

Follow the [official SEAMLeSS walkthrough](https://github.com/seung-lab/corgie/blob/5307f8047287824a3f6eb3113e83e3f098d2d7f6/docs/source/walkthrough/align_seamless.rst).
After preparing physically consistent normalized matching precomputed layers:

```bash
corgie align-block \
  --src_layer_spec '{"path":"/data/matching/img_norm"}' \
  --dst_folder /data/run/volume-a/metroem-corgie/pilot/native \
  --start_coord "100000, 100000, 17000" \
  --end_coord "150000, 150000, 17010" \
  --render_chunk_xy 2048 --chunk_xy 1024 \
  --processor_spec '{"ApplyModel":{"params":{"path":"/models/validated-aligner"}}}' \
  --processor_mip 7 --device cuda --suffix pilot
```

These coordinates/mip are illustrative. Replace them with the audited physical ROI
and compatible model. In project JSON every flag/value is a separate argv element
and each JSON processor spec is one string. Declare actual emitted field/layer
metadata as expected outputs, not a guessed filename. Check the pinned CLI's global
scheduler options; run locally unless distributed services were requested.

## Full workflow and native rendering

`corgie align` adds block stitching/composition to pair/block alignment. Configure
`--block_size`, `--stitch_size`, `--vote_dist`, `--decay_dist` and
`--blur_rate`; processor_spec and processor_mip accept repeated corresponding
entries. Inspect block boundaries and long-range morphology. The stages are
align_blocks, compute_stitch_fields, compose_fields and final_render; restart_stage
and restart_suffix must refer to the same pinned run, not stale fields.

The inspected align implementation renders at `processor_mip[-1]`. A successful
coarse model run is therefore **not native-resolution delivery**. Use the final
composed fields with a verified native renderer and scale conversion against original
intensities, establishing field units, direction, offsets and boundary behavior with
a known translation first. Keep normalized images for matching only.
Do not claim full ABCD reproduction from an align-block-only pilot.
