# Deployment and recovery

## Reproducible runtime identity

Before a pilot, freeze:

- SegNeuron repository URL and commit;
- checkpoint filename, source, and SHA-256;
- Python/CUDA/framework environment lock or container digest;
- external postprocessing code revision;
- rendered argv, cwd, environment variable names, and hardware/backend identity.

Do not store credentials, access tokens, private keys, or passwords in the project configuration. Use the deployment platform's secret mechanism.

## Local runner

The bundled orchestrator executes only argument-list commands with `shell=False`. It writes the rendered job spec first and requires `--execute`. It refuses an existing expected output unless `output.allow_overwrite` is true.

Use a pinned environment interpreter explicitly in `argv` when system `python` is ambiguous.

## SSH adapter contract

For remote execution, create a small project-specific adapter outside the skill or extend the runner with these properties:

1. upload only configuration/job manifests, never embed credentials;
2. resolve remote paths separately from local paths;
3. record remote host alias, working directory, scheduler job ID, and commit;
4. stream or periodically retrieve logs;
5. use a remote completion record containing exit code and output checksums;
6. support reconnect without launching a duplicate job.

## Slurm contract

Generate an inspectable job script with explicit GPU, CPU, memory, wall-time, environment activation, working directory, and log paths. A submitted job is not a completed stage. Poll scheduler state and then validate outputs before updating state.

For block arrays, assign exactly one manifest tile per array index. Retrying an index must be idempotent. Never infer completion from the presence of a partially written directory.

## Recovery

Each tile/job should progress through:

```text
pending -> running -> completed
                \-> failed -> pending (explicit retry)
```

Write to a temporary sibling path, fsync/close where supported, validate shape and dtype, then atomically publish the completed artifact. Record a checksum or immutable object version. On restart, validate completed outputs and schedule only missing/invalid jobs.

## Resource estimation

Before full execution report:

- source and model-grid voxels;
- raw/model-grid temporary bytes;
- affinity bytes, normally channels × dtype bytes × voxels;
- instance and restored-label bytes;
- tile count and overlap overhead;
- free storage headroom;
- pilot throughput and extrapolated GPU time.

Estimates are planning evidence, not guarantees. Stop if projected output plus temporary space does not fit with a safety margin.
