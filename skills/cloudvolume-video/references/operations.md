# Operations playbook

Read this file completely for remote data, missing mips, large arrays, batch rendering, or restarts.

## Preflight

1. Confirm the source and output roots resolve to different directories.
2. Enumerate datasets with `rg`, `find`, or directory listings before opening large arrays.
3. Run `audit`; compare native physical extents of raw and segmentation layers.
4. Check `free -h`, `df -h`, CPU count, OpenCV codec availability, and Python imports.
5. Estimate frames from the configured timeline. PNG frames usually dominate storage.

## SSH execution

- Prefer a server-side Python environment that already has CloudVolume, NumPy, and OpenCV. Label-to-mesh extraction additionally needs scikit-image; non-NPZ mesh files need trimesh.
- Transfer the renderer and JSON config, then run them on the server where the precomputed files are mounted.
- Put passwords/tokens in an approved secret channel or environment variable. Never write them into scripts.
- Use one log and PID file per specimen. Include stage/progress messages in logs.
- Poll processes, logs, output counts, memory, and disk. An empty log is not proof of failure if the process is CPU/I/O active, but long reads should emit progress in this pipeline.

## Missing mip strategy

For a requested target grid:

1. Use the exact mip when present.
2. Otherwise select a finer source mip and map target pixel bounds to physical nanometres.
3. For detail strips, read bounded source tiles and nearest-resample categorical labels.
4. For a global overview, permit a bulk read only when:
   - estimated source bytes plus temporary arrays remain comfortably below available RAM;
   - the read is sequential and one-off;
   - the result is cached/approved so final rendering can reuse it.
5. Never use linear interpolation for label IDs.

If repeated use justifies a derived pyramid, create it under the output root and document it. Do not add scales to the source without explicit authorization.

## Alignment

- Treat every coordinate as physical XY nanometres.
- Account for mip resolution and volume bounds for each layer independently.
- Do not infer alignment from equal array shapes alone.
- Validate with at least four high-resolution fields spanning the specimen.
- A transpose/origin error often looks plausible globally; inspect nuclei or membrane boundaries locally.

## Representative fields

Automatic stops should be ordered left-to-right and maximize local tissue coverage plus texture within four X bands. Use manual `stops_um` when anatomical regions matter. Record X/Y ranges and the FOV on each hold.

## Mesh operations

- Query existing precomputed mesh metadata before generating a new surface.
- Retrieve only the requested segment IDs.
- Run marching cubes only on an explicit ROI whose memory cost has been estimated.
- Use the headless renderer for deterministic preview/turntable delivery; it does not require EGL or an interactive desktop.
- Keep the complete PLY even when `max_render_faces` causes preview sampling.
- Render each mesh scene in a separate output directory to make restart and verification idempotent.

## Parallelism

- Parallelize independent specimens after the storyboard stage.
- Keep only one or a small number of huge missing-mip bulk reads active.
- Separate storyboards and formal renders into independent PID/log files.
- Do not launch duplicate jobs against the same output directory.
- Preserve completed outputs on restart; use approved-asset reuse for final rendering.

## Failure handling

- MP4 opens but decodes no frames: verify codec and close/release the writer.
- MP4 exists with wrong FPS/size: reject it; do not rely on filename or writer parameters.
- PNG count differs from MP4 frames: reject delivery and inspect interrupted/repeated render state.
- Black rectangles at the same physical location across source and output: document source missing tiles.
- Black rectangles only during motion: enlarge the detail strip margin or fix coordinate mapping.
- Density heatmap covers padding: tighten the tissue-validity rule.
- Multiclass overlay covers implausible anatomy: re-audit label IDs; do not recolor around a semantic error.
- Memory spikes on missing mip: lower `bulk_missing_mip_max_gb` or force tiled reading.
- Marching cubes uses excessive memory: shrink or partition the declared ROI; do not silently process the full label volume.
- Precomputed mesh retrieval is empty: verify mesh metadata, segment IDs, and source URI before falling back to label extraction.
- Job appears idle: inspect CPU, RSS, `/proc/PID/io`, and logs before terminating it.

## Reproducibility

Copy into delivery:

- exact JSON config;
- exact renderer script;
- asset and keyframe manifests;
- exclusion and label mapping records;
- verification JSON and hashes;
- storyboards/contact sheets.
