---
name: cloudvolume-video
description: Prepare and verify Neuroglancer precomputed EM data, then create reproducible scientific videos and review figures from CloudVolume datasets. Use for NPY/TIFF/Zarr-to-precomputed conversion; bounded 1 mm context views; segmentation and structure-density presentation; seeded-random or representative local-field camera tours; localhost Neuroglancer handoff; existing or bounded label-derived meshes; and delivery verification. Supports one requested stage or an end-to-end package. Do not invent anatomical region names, infer biological labels, or turn a single 2D section into claimed 3D geometry.
---

# CloudVolume Video

Treat this Skill as a set of presentation and verification capabilities. Route the request to the smallest valid stage, reuse supplied artifacts, and keep raw data immutable.

## Route the request

| User intent | Capability | Script |
| --- | --- | --- |
| Convert NPY/TIFF/Zarr arrays or verify an existing precomputed source | `precomputed inspect`, `prepare`, or `verify` | `neuroglancer_precomputed.py` |
| Generate a viewer state/URL or safely serve local precomputed data | `precomputed handoff` or `serve` | `neuroglancer_precomputed.py` |
| Inspect datasets, scales, bounds, alignment, or mesh availability | `audit` or `mesh audit` | `cloudvolume_video.py`, `cloudvolume_mesh.py` |
| Plan a local-field story before rendering | `storyboard` | `cloudvolume_video.py` |
| Render raw/segmentation overlays, density maps, and a smooth local camera tour | `render` | `cloudvolume_video.py` |
| Retrieve an existing mesh or extract one from a bounded 3D label ROI | `mesh export` | `cloudvolume_mesh.py` |
| Preview a mesh from four angles or make a headless turntable | `mesh storyboard` or `mesh render` | `cloudvolume_mesh.py` |
| Check video decoding, frame metadata, contact sheets, and hashes | `verify` | the corresponding script |
| Package an approved 2D delivery | `finalize` | `cloudvolume_video.py` |

If inputs are arrays rather than precomputed, use `precomputed inspect → prepare`
before the presentation stages. Existing precomputed users skip preparation.
For an end-to-end 2D request, use `audit → storyboard → render → verify →
finalize`. For mesh, use `mesh audit → mesh storyboard → mesh render → mesh
verify`. Do not impose either full sequence on a figure-only, audit-only,
handoff-only, export-only, or verification-only request.

## Preserve the data contract

- Record source URI, mip, bounds, resolution, voxel offset, axes, segment IDs, requested ROI, and output identity.
- Keep source arrays immutable and write converted precomputed datasets only under a declared derived root.
- Align categorical labels in physical coordinates with nearest-neighbor sampling. Never interpolate instance IDs continuously.
- Use an explicitly bounded context ROI when the user asks for a large local field such as 1 x 1 mm. Do not substitute a whole-organ frame.
- Use an existing precomputed mesh when present. Otherwise run marching cubes only on an explicit, bounded 3D label ROI.
- Treat precomputed mesh coordinates as physical nm unless the source contract explicitly says voxel coordinates.
- Never extrude a single z section and call it a biological 3D mesh.
- If display face sampling is needed, record it as a rendering optimization; the exported PLY remains complete.

Stop before dependent work when coordinate units, voxel size, label identity, mesh coordinate space, or raw/segmentation physical alignment is unresolved.

## Use the scripts

Start from [the example configuration](assets/project.example.json) and read the [configuration schema](references/config-schema.md).

```powershell
python scripts/scaffold_config.py project.json
python scripts/neuroglancer_precomputed.py inspect project.json
python scripts/neuroglancer_precomputed.py prepare project.json
python scripts/neuroglancer_precomputed.py handoff project.json
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

The precomputed converter supports single-channel NPY, TIFF, and Zarr/N5 input
and writes a base mip in bounded chunks. Read the [precomputed contract](references/precomputed-contract.md)
before conversion or serving. Generate large interactive mip pyramids only
through an explicit pinned backend; never average categorical instance IDs.

Mesh export/storyboard/render commands refuse to overwrite existing artifacts. Use `--force` only after reviewing the target.

## Design a local-field presentation

Choose fields that answer the scientific question and declare their physical field of view. Preserve scale bars, segment colors, opacity, selected label IDs, and any excluded layers.

When the request says “show a 1 mm large field, then move to four random local
fields,” implement this exact story contract:

```text
bounded 1 x 1 mm raw context
  → segmentation results at the same context coordinates
  → one full-size density map per structure at the same context coordinates
  → visible camera move to seeded-random local view 1 → overlay hold
  → visible moves and overlay holds for local views 2–4
```

- Put `story.context_roi_um_xyxy` and `story.local_stops` in the specimen config.
- Use `local_stops.mode: seeded_random`, record the integer seed, screen by
  tissue fraction, enforce physical margins and minimum center separation, and
  keep every local FOV inside the context ROI.
- Label the stops `Random local view 1–4`. Do not rename them cortex, medulla,
  papilla, or other anatomical regions unless those identities were supplied.
- Show every requested density map as its own readable context-scale hold; do
  not compress multiple maps into a montage when the user asks to show them
  one by one.
- Show segmentation/density at the context scale once. Do not repeat raw,
  masks, overlay, and density at every local stop unless explicitly requested.
- Make the movement itself visible; a crossfade between unrelated fields is
  not a camera tour.

Use `local_stops.mode: representative` only when the user asks for
representative or tissue-rich fields. Use manual `stops_um` only for supplied
coordinates or approved named anatomy. “Random” never means representative.

Set `video.include_overview: false` when the requested delivery must contain local fields only. The pipeline may still compute overview assets internally for alignment and stop selection, but it excludes them from the storyboard, MP4 timeline, and `.ngvideo` handoff.

Use the `video.camera` block for restrained scientific camera motion. Freeze
global result frames and local review holds by default
(`hold_pan_fraction: 0`, `hold_zoom_fraction: 0`); motion belongs only to entry
and inter-field transitions unless the user explicitly asks otherwise. Prefer
`smootherstep` easing and a small zoom-out while moving between distant stops.
Keep the physical FOV within the configured bounds and update scale bars and
coordinate captions from every rendered pose. Apply one transform to the
already aligned raw-plus-label composite; never animate raw and masks
independently. Review entry, midpoint, and exit poses in the storyboard or
motion-contact sheet. Do not add motion blur, fake parallax, or depth effects
that can hide boundaries.

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
