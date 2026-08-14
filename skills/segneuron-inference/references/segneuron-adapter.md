# SegNeuron research-code adapter

Read this file before filling any `commands.*.argv` entry.

## Why an adapter is required

The current official research repository separates affinity inference and FRMC postprocessing, but its checked-in scripts are examples rather than a stable deployment CLI:

- `Train_and_Inference/inference.py` is the affinity entry point;
- `Train_and_Inference/inference_provider.py` contains dataset-specific branches and fixed crop/stride behavior in the current source;
- `Postprocess/FRMC_post.py` contains placeholder filesystem paths in its `__main__` block;
- `FRMC_post.py` exposes `post_mc(affs, beta=0.25)`, which can be imported by a wrapper after dependencies are pinned.

Therefore do not invent arguments such as `--input` or `--output` for the upstream scripts. Pin either:

1. a reviewed project fork that exposes a real CLI; or
2. a small external wrapper that imports the pinned upstream functions and implements the contract below.

Keep that fork/wrapper outside this skill and identify its commit/checksum in provenance.

## Affinity wrapper contract

The adapter must accept or resolve:

- model-grid raw volume URI;
- canonical zyx axes and voxel metadata;
- model configuration and checkpoint;
- output affinity URI;
- optional model-grid bbox or tile manifest;
- device, batch size, and resume policy.

It must emit:

- three documented affinity channels in a declared channel order;
- shape and dtype metadata;
- completed tile manifest when blockwise;
- checkpoint/config/commit identities;
- nonzero exit code on incomplete output.

Validate whether the pinned provider swaps x/y indexing internally before using non-square data. Do not rely on visual plausibility alone.

## FRMC wrapper contract

The adapter should import the pinned `post_mc` implementation or an audited equivalent. It must accept affinity input, optional foreground/boundary restriction, beta and watershed parameters, output path, and label dtype.

The current example code constructs a boundary input, performs slice-wise distance-transform watershed, builds a region adjacency graph, transforms affinity probabilities to multicut costs, runs multicut, and projects node labels to pixels. Record all parameters whose defaults are inherited from the pinned source.

For production inference, ground-truth paths and metric calculation must be optional and separate from segmentation. Never require labels merely to run FRMC.

## Example reviewed command shape

Use the actual arguments exposed by your wrapper, for example:

```yaml
commands:
  infer:
    argv:
      - D:/envs/segneuron/python.exe
      - D:/adapters/run_segneuron_affinity.py
      - --project
      - "{config_path}"
      - --plan
      - "{plan_path}"
    cwd: "{repo_path}"
    env: {}
    expected_outputs: [affinities]
```

This is a contract example for a user-created adapter, not a claim about upstream CLI flags.

## Preflight probes

Before a pilot:

1. hash the wrapper, upstream commit, checkpoint, and model config;
2. import the model and FRMC dependencies in the selected environment;
3. load one patch and confirm zyx/channel conventions;
4. run one forward pass and validate finite affinity values;
5. run FRMC on that result and confirm background/label dtype;
6. map a synthetic coordinate marker through source, model, and delivery grids.
