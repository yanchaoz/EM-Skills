#!/usr/bin/env python3
"""Render raw-EM center-slice thumbnails for proposed annotation subvolumes."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np


def robust_display(image: np.ndarray) -> np.ndarray:
    image = image.astype(np.float32, copy=False)
    low, high = np.percentile(image, [1.0, 99.0])
    if high <= low:
        return np.zeros_like(image, dtype=np.float32)
    return np.clip((image - low) / (high - low), 0.0, 1.0)


def nice_scale_bar_nm(width_nm: float) -> float:
    target = max(1.0, width_nm * 0.22)
    exponent = 10 ** math.floor(math.log10(target))
    for multiplier in (5, 2, 1):
        value = multiplier * exponent
        if value <= target:
            return value
    return exponent


def render(raw_path: Path, selection_path: Path, out_path: Path, axes: str = "zyx") -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import tifffile

    selection = json.loads(selection_path.read_text(encoding="utf-8"))
    rows = selection.get("selected_subvolumes", [])
    if not rows:
        raise ValueError("selection contains no proposed subvolumes")
    volume = tifffile.imread(raw_path)
    if volume.ndim != 3:
        raise ValueError(f"expected 3D raw TIFF, got {volume.shape}")
    axes = axes.lower()
    if sorted(axes) != ["x", "y", "z"]:
        raise ValueError("axes must be a permutation of zyx")
    if axes != "zyx":
        volume = np.transpose(volume, tuple(axes.index(axis) for axis in "zyx"))

    voxel_nm = selection.get("source", {}).get("voxel_size_nm_zyx", [1.0, 1.0, 1.0])
    cols = 3 if len(rows) > 2 else len(rows)
    grid_rows = math.ceil(len(rows) / cols)
    fig, axes_grid = plt.subplots(grid_rows, cols, figsize=(5.2 * cols, 4.6 * grid_rows), squeeze=False)
    colors = plt.cm.tab10(np.linspace(0, 1, len(rows)))
    for ax, color, row in zip(axes_grid.flat, colors, rows):
        (z0, y0, x0), (z1, y1, x1) = row["bbox_zyx"]
        z = min(volume.shape[0] - 1, (z0 + z1 - 1) // 2)
        crop = volume[z, y0:y1, x0:x1]
        ax.imshow(robust_display(crop), cmap="gray", interpolation="nearest")
        for spine in ax.spines.values():
            spine.set_color(color)
            spine.set_linewidth(4)
        width_nm = (x1 - x0) * float(voxel_nm[2])
        bar_nm = nice_scale_bar_nm(width_nm)
        bar_px = bar_nm / float(voxel_nm[2])
        margin_x = max(8, int(crop.shape[1] * 0.06))
        margin_y = max(8, int(crop.shape[0] * 0.08))
        y_bar = crop.shape[0] - margin_y
        ax.plot([margin_x, margin_x + bar_px], [y_bar, y_bar], color="white", linewidth=5, solid_capstyle="butt")
        ax.text(margin_x, y_bar - max(5, crop.shape[0] * 0.025), f"{bar_nm:g} nm", color="white", fontsize=9, weight="bold")
        shape = row.get("derived_shape_zyx", [z1-z0, y1-y0, x1-x0])
        ax.set_title(
            f"#{row['rank']}  z={z}  size={shape}\n"
            f"gain +{row['newly_covered_patch_count']}  coverage {100*row['cumulative_coverage_rate']:.1f}%",
            loc="left", fontsize=11, weight="bold", color="#18212a",
        )
        ax.set_xticks([])
        ax.set_yticks([])
    for ax in axes_grid.flat[len(rows):]:
        ax.axis("off")
    fig.suptitle(
        f"Raw EM review gallery — {selection.get('project_id', 'project')}\n"
        "Center slice only • inspect the full z extent before acceptance",
        fontsize=16, weight="bold",
    )
    fig.tight_layout(rect=(0, 0, 1, 0.94))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=220, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw", type=Path, required=True)
    parser.add_argument("--selection", type=Path, required=True)
    parser.add_argument("--axes", default="zyx")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    render(args.raw, args.selection, args.out, args.axes)
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
