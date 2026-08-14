#!/usr/bin/env python3
"""Publication-style MitoNet raw, foreground, instance, and continuity QC."""

from __future__ import annotations

import argparse
import colorsys
import json
from pathlib import Path

import matplotlib as mpl
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.offsetbox import AnchoredText
from mpl_toolkits.axes_grid1.anchored_artists import AnchoredSizeBar


DEFAULT_RASTER_DPI = 600
mpl.rcParams.update({"font.family": "sans-serif", "font.size": 7, "axes.titlesize": 8, "svg.fonttype": "none", "pdf.fonttype": 42})


def load(path: Path) -> np.ndarray:
    if path.suffix.lower() == ".npy":
        return np.load(path, mmap_mode="r")
    if path.suffix.lower() in {".tif", ".tiff"}:
        import tifffile
        return tifffile.imread(path)
    raise ValueError(f"Unsupported input: {path}")


def robust01(image: np.ndarray) -> np.ndarray:
    values = np.asarray(image, np.float32)
    finite = values[np.isfinite(values)]
    if not finite.size:
        return np.zeros(values.shape, np.float32)
    low, high = np.percentile(finite, [1, 99])
    return np.clip((values - low) / (high - low), 0, 1) if high > low else np.zeros(values.shape, np.float32)


def boundaries(labels: np.ndarray) -> np.ndarray:
    result = np.zeros(labels.shape, bool)
    result[1:] |= labels[1:] != labels[:-1]
    result[:, 1:] |= labels[:, 1:] != labels[:, :-1]
    return result & (labels != 0)


def colors(labels: np.ndarray) -> np.ndarray:
    result = np.zeros((*labels.shape, 3), np.float32)
    for value in np.unique(labels):
        if value:
            result[labels == value] = colorsys.hsv_to_rgb((int(value) * 0.61803398875) % 1, 0.72, 1)
    return result


def overlay(raw: np.ndarray, labels: np.ndarray, alpha: float = 0.5) -> np.ndarray:
    base = np.repeat(robust01(raw)[..., None], 3, axis=-1)
    tint = colors(labels)
    mask = labels != 0
    base[mask] = (1 - alpha) * base[mask] + alpha * tint[mask]
    base[boundaries(labels)] = 1
    return base


def extent(axis: str, shape: tuple[int, int], resolution: list[float]) -> tuple[list[float], float, str]:
    rz, ry, rx = resolution
    vertical, horizontal = {"xy": (ry, rx), "xz": (rz, rx), "yz": (rz, ry)}[axis]
    values = [0, shape[1] * horizontal / 1000, shape[0] * vertical / 1000, 0]
    candidates = np.asarray([0.05, 0.1, 0.2, 0.5, 1, 2, 5, 10, 20])
    available = candidates[candidates <= values[1] * 0.28]
    bar = float(available[-1] if available.size else values[1] * 0.2)
    label = f"{bar:g} µm" if bar >= 1 else f"{bar * 1000:g} nm"
    return values, bar, label


def decorate(ax: plt.Axes, panel: str, title: str, axis: str, shape: tuple[int, int], resolution: list[float]) -> None:
    values, bar, label = extent(axis, shape, resolution)
    ax.set_facecolor("black"); ax.set_xticks([]); ax.set_yticks([]); ax.set_title(title, pad=5)
    ax.add_artist(AnchoredText(panel, loc="upper left", prop={"size": 8, "weight": "bold", "color": "white"}, frameon=False, pad=0.2))
    ax.add_artist(AnchoredSizeBar(ax.transData, bar, label, "lower right", color="white", frameon=False, pad=0.25, size_vertical=max(abs(values[2] - values[3]) * 0.008, 0.002), fontproperties={"size": 6}))


def metrics(labels: np.ndarray) -> dict[str, object]:
    ids, counts = np.unique(labels[labels > 0], return_counts=True)
    spans = []
    border = 0
    for value in ids:
        positions = np.where(labels == value)
        spans.append(int(positions[0].max() - positions[0].min() + 1))
        if any(np.any(axis == 0) or np.any(axis == labels.shape[index] - 1) for index, axis in enumerate(positions)):
            border += 1
    return {
        "shape_zyx": list(labels.shape), "dtype": str(labels.dtype), "object_count": int(ids.size),
        "foreground_fraction": float(np.count_nonzero(labels) / labels.size),
        "object_size_vox": {"min": int(counts.min()) if counts.size else 0, "median": float(np.median(counts)) if counts.size else 0, "max": int(counts.max()) if counts.size else 0},
        "z_span_slices": {"min": min(spans) if spans else 0, "median": float(np.median(spans)) if spans else 0, "max": max(spans) if spans else 0},
        "border_touch_count": border,
    }


def select_display_indices(labels: np.ndarray, xy_index: int | None, xz_index: int | None) -> tuple[int, int]:
    foreground = labels > 0
    if xy_index is None:
        per_z = np.count_nonzero(foreground, axis=(1, 2))
        zi = int(np.argmax(per_z)) if np.any(per_z) else labels.shape[0] // 2
    else:
        zi = xy_index
    if xz_index is None:
        per_y = np.count_nonzero(foreground, axis=(0, 2))
        yi = int(np.argmax(per_y)) if np.any(per_y) else labels.shape[1] // 2
    else:
        yi = xz_index
    return zi, yi


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw", type=Path, required=True); parser.add_argument("--instances", type=Path, required=True)
    parser.add_argument("--resolution-nm-zyx", nargs=3, type=float, required=True)
    parser.add_argument("--xy-index", type=int); parser.add_argument("--xz-index", type=int)
    parser.add_argument("--output-stem", type=Path, required=True)
    parser.add_argument("--formats", nargs="+", choices=("png", "svg", "pdf", "tiff"), default=["png", "svg", "pdf"])
    parser.add_argument("--dpi", type=int, default=DEFAULT_RASTER_DPI)
    args = parser.parse_args()
    raw, labels = np.asarray(load(args.raw)), np.asarray(load(args.instances))
    if raw.shape != labels.shape or raw.ndim != 3:
        raise ValueError(f"Raw and instances must be matching zyx volumes: {raw.shape}, {labels.shape}")
    zi, yi = select_display_indices(labels, args.xy_index, args.xz_index)
    raw_xy, labels_xy = raw[zi], labels[zi]
    raw_xz, labels_xz = raw[:, yi], labels[:, yi]
    data = metrics(labels)
    data["display_indices"] = {
        "xy_z": zi,
        "xz_y": yi,
        "selection": "manual" if args.xy_index is not None or args.xz_index is not None else "max_foreground",
    }
    views = [robust01(raw_xy), labels_xy > 0, overlay(raw_xy, labels_xy), overlay(raw_xz, labels_xz)]
    titles = ["Raw EM", f"Mito foreground ({data['foreground_fraction']:.1%})", f"Instance overlay (n={data['object_count']})", "XZ continuity"]
    axes_names = ["xy", "xy", "xy", "xz"]
    cmaps = ["gray", "magma", None, None]
    fig, axes = plt.subplots(1, 4, figsize=(7.2, 2.05), constrained_layout=True)
    for index, (ax, image, title, axis, cmap) in enumerate(zip(axes, views, titles, axes_names, cmaps)):
        values, _, _ = extent(axis, image.shape[:2], args.resolution_nm_zyx)
        ax.imshow(image, cmap=cmap, extent=values, interpolation="nearest", aspect="equal")
        decorate(ax, chr(97 + index), title, axis, image.shape[:2], args.resolution_nm_zyx)
    fig.suptitle("MitoNet pilot · integrity and continuity QC", x=0.01, ha="left", fontsize=8, weight="bold")
    args.output_stem.parent.mkdir(parents=True, exist_ok=True)
    suffixes = {"png": ".png", "svg": ".svg", "pdf": ".pdf", "tiff": ".tiff"}
    for fmt in args.formats:
        fig.savefig(args.output_stem.with_suffix(suffixes[fmt]), dpi=args.dpi, bbox_inches="tight", pad_inches=0.04, metadata={"Creator": "MitoNet inference skill"})
    plt.close(fig)
    metrics_path = args.output_stem.with_suffix(".metrics.json")
    metrics_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(data, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
