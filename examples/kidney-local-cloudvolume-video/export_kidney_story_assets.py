#!/usr/bin/env python3
"""Export one kidney context ROI and seeded-random local detail ROIs.

The context is 1 x 1 mm. Four 200 x 112.5 um local fields are sampled inside
it with a recorded seed, tissue threshold, and minimum center separation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

import cv2
import numpy as np
from cloudvolume import CloudVolume


LAYERS = (
    ("nuclei", "EM-WSI-KIDNEY-NC", "Nuclei", [124, 124, 255]),
    ("mitochondria", "EM-WSI-KIDNEY-MITO", "Mitochondria", [0, 214, 95]),
    ("basement_membrane", "EM-WSI-KIDNEY-BM", "Basement membrane", [0, 225, 225]),
    ("lysosomes", "EM-WSI-KIDNEY-LY", "Lysosomes", [225, 0, 170]),
)
RAW_DATASET = "EM-WSI-KIDNEY"
DISPLAY_WINDOW = (60.0, 230.0)
CONTEXT_CENTER_NM = (1_375_000.0, 2_160_000.0)
CONTEXT_FOV_NM = (1_000_000.0, 1_000_000.0)
DETAIL_FOV_NM = (200_000.0, 112_500.0)


def find_mip(volume, resolution_nm):
    for mip in volume.available_mips:
        resolution = tuple(map(int, volume.mip_resolution(mip)))
        if resolution[:2] == (resolution_nm, resolution_nm):
            return int(mip)
    raise RuntimeError(f"{volume.cloudpath} has no {resolution_nm} nm XY mip")


def open_volume(root: Path, dataset: str):
    return CloudVolume("file://" + str(root / dataset), progress=False, fill_missing=True)


def info_sha256(root: Path, dataset: str):
    path = root / dataset / "info"
    return hashlib.sha256(path.read_bytes()).hexdigest()


def bounds_from_center(center_nm, fov_nm):
    cx, cy = center_nm
    fw, fh = fov_nm
    return [cx - fw / 2, cx + fw / 2, cy - fh / 2, cy + fh / 2]


def read_yx(root: Path, dataset: str, resolution_nm: int, bounds_nm):
    volume = open_volume(root, dataset)
    mip = find_mip(volume, resolution_nm)
    volume.mip = mip
    x0, x1, y0, y1 = bounds_nm
    ix0, ix1 = int(round(x0 / resolution_nm)), int(round(x1 / resolution_nm))
    iy0, iy1 = int(round(y0 / resolution_nm)), int(round(y1 / resolution_nm))
    bounds = volume.bounds
    if not (bounds.minpt[0] <= ix0 < ix1 <= bounds.maxpt[0] and
            bounds.minpt[1] <= iy0 < iy1 <= bounds.maxpt[1]):
        raise ValueError(f"{dataset} ROI {(ix0, ix1, iy0, iy1)} is outside {bounds}")
    array = np.asarray(volume[ix0:ix1, iy0:iy1, 0:1]).squeeze().T
    expected = (iy1 - iy0, ix1 - ix0)
    if array.shape != expected:
        raise RuntimeError(f"{dataset} returned {array.shape}, expected {expected}")
    return array, {"mip": mip, "pixel_bounds_xy": [ix0, ix1, iy0, iy1]}


def display_raw(raw):
    low, high = DISPLAY_WINDOW
    return np.clip((raw.astype(np.float32) - low) * 255.0 / (high - low), 0, 255).astype(np.uint8)


def aggregate_density(mask, valid, bin_px):
    height, width = mask.shape
    padded_h = int(math.ceil(height / bin_px) * bin_px)
    padded_w = int(math.ceil(width / bin_px) * bin_px)
    numerator = np.zeros((padded_h, padded_w), np.uint8)
    denominator = np.zeros((padded_h, padded_w), np.uint8)
    numerator[:height, :width] = (mask & valid).astype(np.uint8)
    denominator[:height, :width] = valid.astype(np.uint8)
    numerator = numerator.reshape(padded_h // bin_px, bin_px, padded_w // bin_px, bin_px).sum(axis=(1, 3))
    denominator = denominator.reshape(padded_h // bin_px, bin_px, padded_w // bin_px, bin_px).sum(axis=(1, 3))
    density = np.divide(100.0 * numerator, denominator, out=np.zeros_like(numerator, dtype=np.float32), where=denominator > 0)
    density = cv2.GaussianBlur(density, (0, 0), 0.8)
    return density.astype(np.float32), int(numerator.sum()), int(denominator.sum())


def export_roi(root, arrays, record, prefix, center_nm, fov_nm, resolution_nm, display_shape_yx):
    bounds_nm = bounds_from_center(center_nm, fov_nm)
    raw, raw_meta = read_yx(root, RAW_DATASET, resolution_nm, bounds_nm)
    valid = (raw > 0) & (raw < 250)
    target_h, target_w = display_shape_yx
    arrays[f"{prefix}_raw"] = cv2.resize(display_raw(raw), (target_w, target_h), interpolation=cv2.INTER_AREA)
    bin_px = 64
    layer_records = {}
    for key, dataset, label, color in LAYERS:
        label_array, label_meta = read_yx(root, dataset, resolution_nm, bounds_nm)
        mask = label_array > 0
        density, positive, valid_count = aggregate_density(mask, valid, bin_px)
        arrays[f"{prefix}_mask_{key}"] = cv2.resize(mask.astype(np.uint8), (target_w, target_h), interpolation=cv2.INTER_NEAREST)
        arrays[f"{prefix}_density_{key}"] = density
        values, counts = np.unique(label_array, return_counts=True)
        layer_records[key] = {
            "dataset": dataset, "label": label, "color_rgb": color,
            "mip": label_meta["mip"], "sample_values": [int(x) for x in values[:16]],
            "sample_counts": [int(x) for x in counts[:16]],
            "positive_pixels": positive, "valid_tissue_pixels": valid_count,
            "density_percent": 100.0 * positive / valid_count if valid_count else 0.0,
            "density_bin_um": bin_px * resolution_nm / 1000.0,
        }
    record.update({
        "center_nm_xy": list(center_nm), "fov_um_xy": [fov_nm[0] / 1000, fov_nm[1] / 1000],
        "bounds_um_xyxy": [x / 1000 for x in bounds_nm], "resolution_nm_xy": [resolution_nm, resolution_nm],
        "raw_mip": raw_meta["mip"], "source_shape_yx": list(map(int, raw.shape)),
        "display_shape_yx": list(display_shape_yx), "valid_tissue_pixels": int(valid.sum()),
        "layers": layer_records,
    })


def select_random_regions(root, seed, count, min_distance_um, min_tissue_fraction):
    rng = np.random.default_rng(seed)
    context = bounds_from_center(CONTEXT_CENTER_NM, CONTEXT_FOV_NM)
    min_x, max_x = context[0] + DETAIL_FOV_NM[0] / 2, context[1] - DETAIL_FOV_NM[0] / 2
    min_y, max_y = context[2] + DETAIL_FOV_NM[1] / 2, context[3] - DETAIL_FOV_NM[1] / 2
    selected = []
    for candidate_index in range(1, 2001):
        center = (float(rng.uniform(min_x, max_x)), float(rng.uniform(min_y, max_y)))
        if any(math.dist(center, item["center_nm_xy"]) < min_distance_um * 1000 for item in selected):
            continue
        raw, _ = read_yx(root, RAW_DATASET, 160, bounds_from_center(center, DETAIL_FOV_NM))
        tissue_fraction = float(np.mean((raw > 0) & (raw < 250)))
        if tissue_fraction < min_tissue_fraction:
            continue
        selected.append({
            "id": f"random-{len(selected) + 1:02d}",
            "label": f"Random local view {len(selected) + 1}",
            "center_nm_xy": list(center),
            "selection_candidate_index": candidate_index,
            "selection_tissue_fraction": tissue_fraction,
        })
        if len(selected) == count:
            return selected
    raise RuntimeError(f"Selected only {len(selected)}/{count} random local views")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=20260815)
    parser.add_argument("--random-count", type=int, default=4)
    parser.add_argument("--min-center-distance-um", type=float, default=220.0)
    parser.add_argument("--min-tissue-fraction", type=float, default=0.70)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)

    datasets = [RAW_DATASET] + [x[1] for x in LAYERS]
    sources = {}
    for dataset in datasets:
        volume = open_volume(args.source_root, dataset)
        sources[dataset] = {
            "info_sha256": info_sha256(args.source_root, dataset),
            "shape_xyzc": list(map(int, volume.shape)), "dtype": str(volume.dtype),
            "mips": [{"mip": int(m), "resolution_nm_xyz": list(map(int, volume.mip_resolution(m)))}
                     for m in volume.available_mips],
        }

    arrays = {}
    context = {"id": "kidney-1mm-context", "label": "Kidney 1 mm context"}
    export_roi(
        args.source_root, arrays, context, "context",
        center_nm=CONTEXT_CENTER_NM, fov_nm=CONTEXT_FOV_NM,
        resolution_nm=160, display_shape_yx=(2160, 2160),
    )
    regions = []
    selected = select_random_regions(
        args.source_root, args.seed, args.random_count,
        args.min_center_distance_um, args.min_tissue_fraction,
    )
    for record in selected:
        print(f"EXPORT {record['label']} center_nm={record['center_nm_xy']}", flush=True)
        key = record["id"]
        export_roi(
            args.source_root, arrays, record, f"detail_{key}",
            center_nm=record["center_nm_xy"], fov_nm=DETAIL_FOV_NM,
            resolution_nm=80, display_shape_yx=(1080, 1920),
        )
        regions.append(record)

    np.savez_compressed(args.output, **arrays)
    manifest = {
        "description": "Bounded kidney CloudVolume assets for mask, overlay, and local-density video.",
        "presentation_scope": "1 x 1 mm segmentation/density context followed by four seeded-random local views",
        "story_sequence": [
            "context.raw", "context.masks", "context.overlay",
            "context.density.nuclei", "context.density.mitochondria",
            "context.density.basement_membrane", "context.density.lysosomes",
            "four_local_camera_moves_with_locked_holds",
        ],
        "local_stop_selection": {
            "mode": "seeded_random", "seed": args.seed, "count": args.random_count,
            "min_center_distance_um": args.min_center_distance_um,
            "min_tissue_fraction": args.min_tissue_fraction,
            "bounded_by_context": True,
        },
        "axes": "yx", "raw_display_window": list(DISPLAY_WINDOW),
        "density_method": "positive structure pixels / valid tissue pixels; valid raw intensity 0 < I < 250; Gaussian sigma 0.8 bins for display",
        "sources": sources, "context": context, "regions": regions,
        "asset_npz": args.output.name,
    }
    manifest_path = args.output.with_suffix(".manifest.json")
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"npz": str(args.output), "bytes": args.output.stat().st_size,
                      "manifest": str(manifest_path), "regions": [x["id"] for x in regions]}, indent=2))


if __name__ == "__main__":
    main()
