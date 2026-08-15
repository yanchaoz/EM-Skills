---
name: cloudvolume-video
description: Create reproducible scientific videos and review figures from CloudVolume or Neuroglancer precomputed EM datasets. Use for metadata and physical-alignment audits; bounded local-field raw/segmentation overlays; structure-density maps; representative-field camera tours; existing precomputed mesh retrieval; bounded 3D label-to-mesh extraction; headless mesh turntables; Neuroglancer handoff; or delivery verification. Supports one requested stage or an end-to-end presentation package. Do not use to infer biological labels or to turn a single 2D section into a claimed 3D mesh.
---

# CloudVolume Video

Treat this Skill as a set of presentation and verification capabilities. Route the request to the smallest valid stage, reuse supplied artifacts, and keep raw data immutable.

## Route the request

| User intent | Capability | Script |
| --- | --- | --- |
| Inspect datasets, scales, bounds, alignment, or mesh availability | `audit` or `mesh audit` | `cloudvolume_video.py`, `cloudvolume_mesh.py` |
| Plan a local-field story before rendering | `storyboard` | `cloudvolume_video.py` |
| Render raw/segmentation overlays, density maps, and a local camera tour | `render` | `cloudvolume_video.py` |
| Retrieve an existing mesh or extract one from a bounded 3D label ROI | `mesh export` | `cloudvolume_mesh.py` |
| Preview a mesh from four angles or make a headless turntable | `mesh storyboard` or `mesh render` | `cloudvolume_mesh.py` |
| Check video decoding, frame metadata, contact sheets, and hashes | `verify` | the corresponding script |
| Package an approved 2D delivery | `finalize` | `cloudvolume_video.py` |

For an end-to-end 2D request, use `audit → storyboard → render → verify → finalize`. For mesh, use `mesh audit → mesh storyboard → mesh render → mesh verify`. Do not impose either full sequence on a figure-only, audit-only, export-only, or verification-only request.

## Preserve the data contract

- Record source URI, mip, bounds, resolution, voxel offset, axes, segment IDs, requested ROI, and output identity.
- Align categorical labels in physical coordinates with nearest-neighbor sampling. Never interpolate instance IDs continuously.
- Default to bounded local fields. Whole-section density maps are optional analytical context, not the default example view.
- Use an existing precomputed mesh when present. Otherwise run marching cubes only on an explicit, bounded 3D label ROI.
- Treat precomputed mesh coordinates as physical nm unless the source contract explicitly says voxel coordinates.
- Never extrude a single z section and call it a biological 3D mesh.
- If display face sampling is needed, record it as a rendering optimization; the exported PLY remains complete.

Stop before dependent work when coordinate units, voxel size, label identity, mesh coordinate space, or raw/segmentation physical alignment is unresolved.

## Use the scripts

Start from [the example configuration](assets/project.example.json) and read the [configuration schema](references/config-schema.md).

```powershell
python scripts/scaffold_config.py project.json
python scripts/cloudvolume_video.py audit project.json
python scripts/cloudvolume_video.py storyboard project.json
python scripts/cloudvolume_video.py render project.json
python scripts/cloudvolume_video.py verify project.json
python scripts/cloudvolume_video.py finalize project.json

python scripts/cloudvolume_mesh.py audit project.json --scene local-mesh
python scripts/cloudvolume_mesh.py export project.json --scene local-mesh
python scripts/cloudvolume_mesh.py storyboard project.json --scene local-mesh
python scripts/cloudvolume_mesh.py render project.json --scene local-mesh
python scripts/cloudvolume_mesh.py verify project.json --scene local-mesh
```

The mesh source may be `precomputed`, `labels`, or `file`. `labels` requires a `zyx` volume, physical resolution, non-background segment IDs, and `roi_zyx`. Mesh-only projects may omit `specimens`; 2D projects may omit `mesh_scenes`.

Mesh export/storyboard/render commands refuse to overwrite existing artifacts. Use `--force` only after reviewing the target.

## Design a local-field presentation

Choose fields that answer the scientific question and declare their physical field of view. For multi-region tissue, compare matched local windows rather than scaling an entire organ to fit a frame. Preserve scale bars, segment colors, opacity, selected label IDs, and any excluded layers.

Set `video.include_overview: false` when the requested delivery must contain local fields only. The pipeline may still compute overview assets internally for alignment and stop selection, but it excludes them from the storyboard, MP4 timeline, and `.ngvideo` handoff.

A useful local sequence is:

```text
region identity → raw EM → one structure overlay → density or occupancy → all overlays → local detail stops
```

For mesh, use a neutral background, stable lighting, the same camera elevation across comparisons, and a full orbit only when 3D shape is the subject.

## Verify and report honestly

- Inspect a storyboard before expensive rendering.
- Decode samples across every output video; verify dimensions, FPS, frame count, duration, and contact sheet.
- Confirm raw/label alignment at edges and small structures in more than one field.
- For mesh, verify finite vertices, valid face indices, non-zero physical extent, requested segment IDs, ROI, and export hash.
- Separate execution success and visual QC from biological accuracy. This Skill visualizes supplied labels; it does not validate their scientific correctness without reference annotations.
- Read [quality gates](references/quality-gates.md) before final delivery and [mesh contract](references/mesh-contract.md) for 3D work.

## Compose with other EM Skills

This Skill is a downstream presentation layer. It may visualize coarse or approved results from `$segneuron-inference`, `$mitonet-inference`, or a `$bootstrap-em-segmentation` run after their artifact grids and identities are fixed. It must not silently rerun inference, choose beta/profile parameters, or convert draft annotation suggestions into final labels.
