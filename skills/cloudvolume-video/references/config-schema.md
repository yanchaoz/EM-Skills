# Configuration schema

Read this file completely when creating or changing a project configuration.

## Top-level object

```json
{
  "project_name": "organ-wsi",
  "source_root": "/data/project/outputs",
  "output_root": "/data/project/video-output",
  "video": {},
  "neuroglancer": {},
  "specimens": [],
  "mesh_render": {},
  "mesh_scenes": []
}
```

- `project_name`: stable identifier used in manifests.
- `source_root`: directory containing precomputed dataset directories. Dataset paths may also be absolute.
- `output_root`: separate derived-output directory.
- `video`: common rendering settings.
- `neuroglancer`: `.ngvideo` state settings.
- `specimens`: one object per WSI/section/volume tour.
- `mesh_render`: common headless mesh-rendering settings.
- `mesh_scenes`: one object per mesh retrieval, extraction, or turntable task.

Mesh-only projects may omit `specimens`; 2D projects may omit `mesh_render` and `mesh_scenes`.

## Video settings

```json
{
  "width": 1920,
  "height": 1080,
  "fps": 30,
  "include_overview": true,
  "preview_resolution_nm": 640,
  "detail_resolution_nm": 160,
  "detail_fov_um": 200.0,
  "detail_scale_bar_um": 10.0,
  "overview_scale_bar_um": 1000.0,
  "density_bin_um": 10.24,
  "density_display_quantile": 0.99,
  "metadata_seconds": 3.0,
  "isolated_seconds": 2.5,
  "density_seconds": 2.5,
  "all_seconds": 3.0,
  "zoom_seconds": 4.0,
  "hold_seconds": 3.0,
  "move_seconds": 3.0,
  "camera": {
    "easing": "smootherstep",
    "entry_start_fov_multiplier": 1.40,
    "hold_pan_fraction": 0.035,
    "hold_zoom_fraction": 0.06,
    "transition_zoom_out_fraction": 0.16
  },
  "fade_frames": 15,
  "png_frames": true,
  "png_compression": 2,
  "codec": "mp4v",
  "bulk_missing_mip_max_gb": 64.0,
  "source_tile_max_pixels": 4096,
  "tissue": {"min_intensity": 1, "max_intensity": 249}
}
```

All times are seconds. Resolutions are isotropic XY nanometres per pixel. `density_bin_um` is a physical size, not a fixed pixel count. Set `include_overview: false` for a local-fields-only storyboard/video; overview assets may still be computed internally to locate and align the bounded fields, but they are not displayed. Set `bulk_missing_mip_max_gb` to `0` to force bounded tiled reading.

### Camera motion

`video.camera` controls a deterministic physical-coordinate trajectory:

- `easing`: `linear`, `smoothstep`, `smootherstep`, or `cosine`; use
  `smootherstep` for zero-slope starts and stops.
- `entry_start_fov_multiplier`: initial high-resolution FOV relative to
  `detail_fov_um` during the overview-to-detail entry zoom; must be at least 1.
- `hold_pan_fraction`: total pan amplitude as a fraction of detail FOV. Values
  above `0.08` are usually distracting for scientific review; maximum `0.20`.
- `hold_zoom_fraction`: slow hold push-in, expressed as the starting excess FOV
  over `detail_fov_um`; maximum `0.35`.
- `transition_zoom_out_fraction`: midpoint zoom-out used to preserve context
  while moving between stops; maximum `1.0`.

The renderer interpolates center and physical FOV, crops the aligned composite
once, and recalculates scale bars and coordinate ranges for every frame. Set the
three fractions to `0` for fixed-FOV motion. Motion blur and independent
raw/mask transforms are intentionally unsupported.

## Neuroglancer settings

```json
{
  "base_url": "http://127.0.0.1:1337",
  "viewer_url": "https://neuroglancer-demo.appspot.com/",
  "show_axis_lines": false,
  "show_scale_bar": true,
  "background": "#000000",
  "layout": "xy"
}
```

Do not put credentials in URLs.

Set `layout` to a supported Neuroglancer layout only when the handoff should open a 3D-capable view. Segmentation layers additionally use their `object_alpha`; objects appear only when the precomputed dataset has valid mesh metadata.

## Specimen object

```json
{
  "id": "lung",
  "label": "Lung",
  "raw": "EM-WSI-Lung",
  "layers": [],
  "stops_um": null,
  "excluded_layers": [{"dataset": "EM-WSI-Lung-Red", "reason": "RBC"}]
}
```

- `id`: lowercase output directory name.
- `label`: title shown in video.
- `raw`: image dataset path relative to `source_root`, or absolute path.
- `layers`: ordered overlays.
- `stops_um`: `null` for four automatic tissue-rich X-ordered fields, or `[[x_um,y_um], ...]` for manual centers.
- `excluded_layers`: provenance-only list written into manifests.

## Layer object

```json
{
  "id": "lamellar-bodies",
  "label": "Lamellar bodies",
  "dataset": "EM-WSI-Lung-Mask",
  "label_value": 3,
  "segment_ids": [3],
  "color_rgb": [128, 64, 0],
  "opacity": 0.74,
  "object_alpha": 0.7
}
```

- `id`: stable lowercase identifier.
- `dataset`: segmentation dataset path.
- `label_value`: integer, list of integers, or `null` meaning any nonzero voxel.
- `segment_ids`: IDs displayed in Neuroglancer. Required when a nonzero binary dataset does not use segment `1`.
- `color_rgb`: three integers in RGB order.
- `opacity`: `0..1`.
- `object_alpha`: optional `0..1` Neuroglancer 3D mesh opacity; default `0`.

For one multiclass dataset, repeat the dataset with different `label_value` entries. Example:

```json
[
  {"id":"nucleus","label":"Nucleus","dataset":"EM-WSI-Lung-Mask","label_value":1,"segment_ids":[1],"color_rgb":[124,124,255],"opacity":0.60},
  {"id":"mitochondria","label":"Mitochondria","dataset":"EM-WSI-Lung-Mask","label_value":2,"segment_ids":[2],"color_rgb":[0,145,20],"opacity":0.54},
  {"id":"lamellar-bodies","label":"Lamellar bodies","dataset":"EM-WSI-Lung-Mask","label_value":3,"segment_ids":[3],"color_rgb":[128,64,0],"opacity":0.74}
]
```

## Recommended color vocabulary

These are defaults, not semantic truth:

| Structure | RGB |
|---|---|
| Mitochondria | `[0,145,20]` |
| Nucleus | `[124,124,255]` |
| Basement membrane | `[0,225,225]` |
| Endoplasmic reticulum | `[255,0,0]` |
| Transverse tubule | `[130,0,255]` |
| Lipid droplets | `[255,115,55]` |
| Lamellar bodies | `[128,64,0]` |
| Zymogen granules | `[205,205,0]` |
| Lysosomes | `[225,0,170]` |

## Mesh render settings

```json
{
  "width": 1280,
  "height": 720,
  "fps": 24,
  "seconds": 8,
  "elevation_deg": 22,
  "orbit_degrees": 360,
  "mesh_color_rgb": [74,190,167],
  "background_rgb": [9,14,23],
  "max_render_faces": 120000,
  "allow_face_sampling": false,
  "smooth_shading": true,
  "png_frames": false,
  "codec": "mp4v"
}
```

`max_render_faces` is a safety limit for the headless preview. Above it, provide a display LOD/decimated mesh. `allow_face_sampling: true` is an explicit last-resort preview mode that may create holes; it never changes the exported PLY. Smooth shading changes lighting only, not geometry. Set `backface_culling` only after inspecting a storyboard.

## Mesh scene objects

Existing precomputed mesh:

```json
{
  "id": "segment-42",
  "source": {
    "type": "precomputed",
    "uri": "precomputed:///data/segmentation",
    "segment_ids": [42],
    "mip": 0,
    "coordinates": "nm"
  },
  "render": {"title": "Segment 42 — local field"}
}
```

Bounded marching cubes from a 3D label volume:

```json
{
  "id": "label-7-roi",
  "source": {
    "type": "labels",
    "path": "labels.npy",
    "axes": "zyx",
    "segment_ids": [7],
    "roi_zyx": [4,68,100,612,200,712],
    "resolution_nm_zyx": [40,8,8],
    "voxel_offset_zyx": [0,0,0]
  }
}
```

`roi_zyx` is mandatory for label sources. Read [mesh contract](mesh-contract.md) before changing coordinate conventions.

## Example commands

```bash
python cloudvolume_video.py audit project.json --specimen lung
python cloudvolume_video.py storyboard project.json --specimen lung
python cloudvolume_video.py render project.json --specimen lung --reuse-assets
python cloudvolume_video.py verify project.json --specimen lung
python cloudvolume_video.py finalize project.json
python cloudvolume_mesh.py audit project.json --scene segment-42
python cloudvolume_mesh.py storyboard project.json --scene segment-42
python cloudvolume_mesh.py render project.json --scene segment-42
python cloudvolume_mesh.py verify project.json --scene segment-42
```
