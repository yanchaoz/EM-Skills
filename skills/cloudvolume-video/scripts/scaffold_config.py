#!/usr/bin/env python3
"""Create a safe, documented starter config for cloudvolume_video.py."""
import argparse
import json
from pathlib import Path


TEMPLATE = {
    "project_name": "cloudvolume-video-project",
    "precomputed": {
        "root": "/path/to/derived-precomputed-datasets", "hash_source": False,
        "datasets": [{
            "id": "raw-em", "label": "Raw EM",
            "source": {"path": "/path/to/raw-em.npy", "axes": "zyx"},
            "output": "EM-WSI-Example", "layer_type": "image", "encoding": "raw",
            "resolution_nm_xyz": [8, 8, 40], "voxel_offset_xyz": [0, 0, 0],
            "chunk_size_xyz": [256, 256, 1]
        }]
    },
    "source_root": "/path/to/derived-precomputed-datasets",
    "output_root": "/path/to/derived-video-output",
    "video": {
        "width": 1920, "height": 1080, "fps": 30, "include_overview": True,
        "preview_resolution_nm": 640, "detail_resolution_nm": 160,
        "detail_fov_um": 200.0, "detail_scale_bar_um": 10.0,
        "overview_scale_bar_um": 1000.0, "density_bin_um": 10.24,
        "density_display_quantile": 0.99,
        "metadata_seconds": 3.0, "isolated_seconds": 2.5,
        "density_seconds": 2.5, "all_seconds": 3.0,
        "zoom_seconds": 4.0, "hold_seconds": 3.0, "move_seconds": 3.0,
        "camera": {
            "easing": "smootherstep", "entry_start_fov_multiplier": 5.0,
            "hold_pan_fraction": 0.035, "hold_zoom_fraction": 0.06,
            "transition_zoom_out_fraction": 0.16
        },
        "fade_frames": 15, "png_frames": True, "png_compression": 2,
        "codec": "mp4v", "bulk_missing_mip_max_gb": 64.0,
        "source_tile_max_pixels": 4096,
        "tissue": {"min_intensity": 1, "max_intensity": 249}
    },
    "neuroglancer": {
        "base_url": "http://127.0.0.1:1337",
        "viewer_url": "https://neuroglancer-demo.appspot.com/",
        "show_axis_lines": False, "show_scale_bar": True,
        "background": "#000000"
    },
    "mesh_render": {
        "width": 1280, "height": 720, "fps": 24, "seconds": 8,
        "elevation_deg": 22, "orbit_degrees": 360,
        "mesh_color_rgb": [74, 190, 167], "background_rgb": [9, 14, 23],
        "max_render_faces": 120000, "allow_face_sampling": False,
        "smooth_shading": True, "png_frames": False, "codec": "mp4v"
    },
    "mesh_scenes": [{
        "id": "local-mesh",
        "source": {"type": "precomputed", "uri": "precomputed:///path/to/segmentation",
                   "segment_ids": [42], "mip": 0, "coordinates": "nm"},
        "render": {"title": "Segment 42 - bounded local field"}
    }],
    "specimens": [{
        "id": "example", "label": "Example specimen", "raw": "EM-WSI-Example",
        "story": {
            "context_roi_um_xyxy": [0, 1000, 0, 1000],
            "local_stops": {
                "mode": "seeded_random", "seed": 20260815, "count": 4,
                "min_tissue_fraction": 0.70, "min_center_distance_um": 220
            }
        },
        "layers": [
            {"id": "mitochondria", "label": "Mitochondria",
             "dataset": "EM-WSI-Example-Mito", "label_value": None,
             "segment_ids": [1], "color_rgb": [0, 145, 20], "opacity": 0.54,
             "object_alpha": 0.7},
            {"id": "nucleus", "label": "Nucleus",
             "dataset": "EM-WSI-Example-Mask", "label_value": 1,
             "segment_ids": [1], "color_rgb": [124, 124, 255], "opacity": 0.60}
        ],
        "stops_um": None,
        "excluded_layers": []
    }]
}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("output", type=Path)
    p.add_argument("--force", action="store_true")
    a = p.parse_args()
    if a.output.exists() and not a.force:
        raise SystemExit(f"Refusing to overwrite {a.output}; use --force")
    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_text(json.dumps(TEMPLATE, indent=2) + "\n", encoding="utf-8")
    print(a.output.resolve())


if __name__ == "__main__":
    main()
