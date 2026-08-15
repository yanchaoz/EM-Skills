# Neuroglancer precomputed contract

Read this file completely before converting arrays, generating a Neuroglancer
handoff, or starting a data server.

## Capability boundary

Use `scripts/neuroglancer_precomputed.py` to:

- inspect single-channel NPY, TIFF, or Zarr/N5 image and segmentation arrays;
- convert them to a base-mip Neuroglancer precomputed directory in bounded
  chunks;
- copy optional segmentation label names into segment properties;
- compare source and precomputed samples by exact readback;
- generate `neuroglancer-state.json` and a viewer URL;
- serve a precomputed root with Range/CORS headers on loopback.

If the requested datasets are already valid precomputed sources, omit `source`
from their dataset entries and run `verify` or `handoff` directly. Do not force
conversion into every video request.

## Configuration

```json
{
  "precomputed": {
    "root": "derived/precomputed",
    "hash_source": false,
    "datasets": [
      {
        "id": "raw-em",
        "label": "Raw EM",
        "source": {"path": "data/raw.tif", "axes": "zyx"},
        "output": "raw-em",
        "layer_type": "image",
        "encoding": "raw",
        "resolution_nm_xyz": [8, 8, 40],
        "voxel_offset_xyz": [0, 0, 0],
        "chunk_size_xyz": [256, 256, 1]
      },
      {
        "id": "instances",
        "label": "Neuron instances",
        "source": {"path": "data/instances.zarr", "axes": "zyx"},
        "output": "instances",
        "layer_type": "segmentation",
        "encoding": "compressed_segmentation",
        "resolution_nm_xyz": [8, 8, 40],
        "voxel_offset_xyz": [0, 0, 0],
        "chunk_size_xyz": [128, 128, 16],
        "segment_properties": {"1": "Neuron 1", "2": "Neuron 2"}
      }
    ]
  }
}
```

- `precomputed.root` is derived output. Keep it separate from the original
  arrays. All dataset `output` paths must remain inside this root.
- `source.axes` describes the source array, not the output. Supported forms are
  `yx`, `xy`, `zyx`, `xyz`, `zyxc`, and `xyzc`; a channel axis must have size 1.
- `resolution_nm_xyz` and `voxel_offset_xyz` use Neuroglancer/CloudVolume XYZ
  order even when the source array is ZYX.
- `chunk_size_xyz` is the write/read chunk contract, not the display FOV.
- Use `raw` for lossless image or segmentation storage. JPEG is permitted only
  for image layers. Use `compressed_segmentation` only for categorical labels.
- `hash_source: true` computes a full hash for file sources and may be expensive.
  The default records file size/mtime or Zarr metadata identity.
- For a Zarr group, set `source.array_path` to the array inside the group.

## Commands

```powershell
python scripts/neuroglancer_precomputed.py inspect project.json
python scripts/neuroglancer_precomputed.py prepare project.json
python scripts/neuroglancer_precomputed.py verify project.json
python scripts/neuroglancer_precomputed.py handoff project.json
python scripts/neuroglancer_precomputed.py serve project.json
```

Use `--dataset ID` repeatedly to limit work. `prepare` performs conversion,
exact sampled readback, and handoff generation; it does not start the blocking
server. Existing outputs are protected. `--force` rewrites chunks only when the
declared grid matches the existing `info`; it refuses an incompatible grid.

## Mip policy

The bundled converter writes a verified base mip only. This keeps the core
operation deterministic and avoids silently averaging labels. For interactive
large-volume navigation, build additional mips with an explicitly selected,
pinned backend such as an existing Igneous deployment:

- average or area-filter image data according to the acquisition contract;
- use a categorical-safe strategy for segmentation labels;
- write derived scales under the declared precomputed output, never the source
  array;
- rerun metadata, sample-read, and raw/label alignment checks after pyramid
  generation;
- record backend version, task specification, and mip identities.

The video pipeline can consume a base-only source and resample bounded fields,
but this is not a substitute for an efficient interactive pyramid.

## Handoff and server safety

`handoff` writes:

- `neuroglancer-state.json` with image/segmentation layers, physical
  dimensions, center position, layout, scale-bar, and axis settings;
- `neuroglancer-viewer-url.txt` containing the URL-encoded state.

The configured `neuroglancer.base_url` must be an HTTP(S) URL without embedded
credentials or query tokens. Default serving binds to `127.0.0.1:1337` and adds
CORS/Range headers. A non-loopback host is refused unless the operator passes
`--allow-public` after reviewing firewall, authentication, and data policy.
The built-in server provides no authentication or TLS and is not a production
data service.

## Verification and provenance

Require all of the following before using converted data in a video:

- source axes and output XYZ size agree;
- dtype, layer type, resolution, offset, chunk size, and encoding are recorded;
- first, center, and last samples exactly match source data after axis mapping;
- `info` SHA-256 and conversion/verification manifests exist;
- raw and label precomputed layers align at multiple physical locations;
- segment IDs and names are confirmed rather than inferred.

Precomputed preparation does not generate meshes. After verification, use
`cloudvolume_mesh.py` to retrieve existing Neuroglancer mesh metadata or to
extract a mesh from an explicit bounded 3D label ROI.
