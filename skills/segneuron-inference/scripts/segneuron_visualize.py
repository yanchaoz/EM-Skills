#!/usr/bin/env python3
"""Publication-style visual checks for SegNeuron outputs and beta sweeps."""

from __future__ import annotations

import argparse
import colorsys
from pathlib import Path
from typing import Iterable

import matplotlib as mpl
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.offsetbox import AnchoredText
from mpl_toolkits.axes_grid1.anchored_artists import AnchoredSizeBar


DEFAULT_RASTER_DPI = 600

mpl.rcParams.update({
    "font.family": "sans-serif",
    "font.size": 7,
    "axes.titlesize": 8,
    "svg.fonttype": "none",
    "pdf.fonttype": 42,
    "savefig.facecolor": "white",
})


def load_array(path: Path) -> np.ndarray:
    suffix = path.suffix.lower()
    if suffix == ".npy":
        return np.load(path, mmap_mode="r")
    if suffix == ".npz":
        archive = np.load(path)
        if len(archive.files) != 1:
            raise ValueError(f"NPZ must contain exactly one array: {path}")
        return archive[archive.files[0]]
    if suffix in {".tif", ".tiff"}:
        import tifffile
        return tifffile.imread(path)
    raise ValueError(f"Unsupported array format: {path}")


def robust01(image: np.ndarray) -> np.ndarray:
    values = np.asarray(image, dtype=np.float32)
    finite = values[np.isfinite(values)]
    if not finite.size:
        return np.zeros(values.shape, dtype=np.float32)
    low, high = np.percentile(finite, [1, 99])
    if high <= low:
        return np.zeros(values.shape, dtype=np.float32)
    return np.clip((values - low) / (high - low), 0, 1)


def slice_zyx(volume: np.ndarray, axis: str, index: int | None) -> tuple[np.ndarray, int]:
    if volume.ndim != 3:
        raise ValueError(f"Expected a 3D zyx volume, got shape {volume.shape}")
    dim = {"xy": 0, "xz": 1, "yz": 2}[axis]
    chosen = volume.shape[dim] // 2 if index is None else index
    if not 0 <= chosen < volume.shape[dim]:
        raise ValueError(f"Slice index {chosen} is outside axis length {volume.shape[dim]}")
    if axis == "xy":
        return np.asarray(volume[chosen]), chosen
    if axis == "xz":
        return np.asarray(volume[:, chosen, :]), chosen
    return np.asarray(volume[:, :, chosen]), chosen


def affinity_slice(affinities: np.ndarray, axis: str, index: int | None) -> tuple[np.ndarray, int]:
    array = np.asarray(affinities)
    if array.ndim != 4:
        raise ValueError(f"Expected 4D affinities, got shape {array.shape}")
    if array.shape[0] not in {2, 3, 4} and array.shape[-1] in {2, 3, 4}:
        array = np.moveaxis(array, -1, 0)
    if array.shape[0] < 3:
        raise ValueError("Affinity array must provide at least three channels")
    channels = []
    chosen = 0
    for channel in array[:3]:
        image, chosen = slice_zyx(channel, axis, index)
        channels.append(robust01(image))
    return np.stack(channels, axis=-1), chosen


def label_boundaries(labels: np.ndarray) -> np.ndarray:
    labels = np.asarray(labels)
    boundary = np.zeros(labels.shape, dtype=bool)
    boundary[1:, :] |= labels[1:, :] != labels[:-1, :]
    boundary[:, 1:] |= labels[:, 1:] != labels[:, :-1]
    boundary &= labels != 0
    return boundary


def label_colors(labels: np.ndarray) -> np.ndarray:
    labels = np.asarray(labels, dtype=np.uint64)
    rgb = np.zeros((*labels.shape, 3), dtype=np.float32)
    for value in np.unique(labels):
        if value == 0:
            continue
        hue = ((int(value) * 0.618033988749895) % 1.0)
        rgb[labels == value] = colorsys.hsv_to_rgb(hue, 0.72, 1.0)
    return rgb


def instance_overlay(raw: np.ndarray, labels: np.ndarray, alpha: float = 0.48) -> np.ndarray:
    if raw.shape != labels.shape:
        raise ValueError(f"Raw slice {raw.shape} and instance slice {labels.shape} do not match")
    base = np.repeat(robust01(raw)[..., None], 3, axis=-1)
    colors = label_colors(labels)
    foreground = labels != 0
    output = base.copy()
    output[foreground] = (1 - alpha) * base[foreground] + alpha * colors[foreground]
    output[label_boundaries(labels)] = 1.0
    return output


def extent_and_bar(axis: str, shape: tuple[int, int], resolution_nm_zyx: Iterable[float]) -> tuple[list[float], float, str]:
    rz, ry, rx = [float(value) for value in resolution_nm_zyx]
    if axis == "xy":
        vertical, horizontal = ry, rx
    elif axis == "xz":
        vertical, horizontal = rz, rx
    else:
        vertical, horizontal = rz, ry
    extent = [0, shape[1] * horizontal / 1000, shape[0] * vertical / 1000, 0]
    width_um = extent[1]
    candidates = np.asarray([0.05, 0.1, 0.2, 0.5, 1, 2, 5, 10, 20, 50])
    allowed = candidates[candidates <= width_um * 0.28]
    bar = float(allowed[-1] if allowed.size else width_um * 0.2)
    label = f"{bar:g} µm" if bar >= 1 else f"{bar * 1000:g} nm"
    return extent, bar, label


def decorate_image_axis(ax: plt.Axes, axis: str, shape: tuple[int, int], resolution: list[float], panel: str, title: str) -> None:
    extent, bar, label = extent_and_bar(axis, shape, resolution)
    ax.set_facecolor("black")
    ax.set_xticks([])
    ax.set_yticks([])
    ax.set_title(title, color="#151515", pad=5)
    ax.add_artist(AnchoredText(panel, loc="upper left", prop={"weight": "bold", "size": 8, "color": "white"}, frameon=False, pad=0.2))
    ax.add_artist(AnchoredSizeBar(ax.transData, bar, label, "lower right", pad=0.25, color="white", frameon=False, size_vertical=max(abs(extent[2] - extent[3]) * 0.008, 0.002), fontproperties={"size": 6}))


def save_figure(fig: plt.Figure, output_stem: Path, formats: list[str], dpi: int) -> list[Path]:
    output_stem.parent.mkdir(parents=True, exist_ok=True)
    written = []
    suffixes = {"png": ".png", "svg": ".svg", "pdf": ".pdf", "tiff": ".tiff"}
    for fmt in formats:
        path = output_stem.with_suffix(suffixes[fmt])
        fig.savefig(path, dpi=dpi, bbox_inches="tight", pad_inches=0.04, metadata={"Creator": "SegNeuron inference skill"})
        written.append(path)
    return written


def draw_summary(args: argparse.Namespace) -> list[Path]:
    raw, _ = slice_zyx(load_array(args.raw), args.axis, args.index)
    affinities, chosen = affinity_slice(load_array(args.affinities), args.axis, args.index)
    membrane, _ = slice_zyx(load_array(args.membrane), args.axis, args.index)
    labels, _ = slice_zyx(load_array(args.instances), args.axis, args.index)
    if args.membrane_mode == "interior":
        membrane = 1 - robust01(membrane)
    else:
        membrane = robust01(membrane)
    shapes = {raw.shape, affinities.shape[:2], membrane.shape, labels.shape}
    if len(shapes) != 1:
        raise ValueError(f"All displayed slices must share a shape; found {sorted(shapes)}")
    extent, _, _ = extent_and_bar(args.axis, raw.shape, args.resolution_nm_zyx)
    fig, axes = plt.subplots(1, 4, figsize=(7.2, 2.05), constrained_layout=True)
    images = [robust01(raw), affinities, membrane, instance_overlay(raw, labels)]
    titles = ["Raw EM", "Affinity channels (z/y/x)", "Membrane evidence", f"Instance overlay (n_slice={np.unique(labels[labels > 0]).size})"]
    cmaps = ["gray", None, "magma", None]
    for i, (ax, image, title, cmap) in enumerate(zip(axes, images, titles, cmaps)):
        ax.imshow(image, cmap=cmap, extent=extent, interpolation="nearest", aspect="equal")
        decorate_image_axis(ax, args.axis, raw.shape, args.resolution_nm_zyx, chr(97 + i), title)
    fig.suptitle(f"SegNeuron pilot · {args.axis.upper()} slice {chosen}", x=0.01, ha="left", fontsize=8, weight="bold")
    written = save_figure(fig, args.output_stem, args.formats, args.dpi)
    plt.close(fig)
    return written


def parse_instance_spec(value: str) -> tuple[float, Path]:
    beta_text, separator, path_text = value.partition("=")
    if not separator:
        raise argparse.ArgumentTypeError("Use BETA=PATH")
    try:
        beta = float(beta_text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"Invalid beta: {beta_text}") from exc
    return beta, Path(path_text)


def draw_beta_sweep(args: argparse.Namespace) -> list[Path]:
    raw, chosen = slice_zyx(load_array(args.raw), args.axis, args.index)
    candidates = sorted(args.instance, key=lambda item: item[0])
    extent, _, _ = extent_and_bar(args.axis, raw.shape, args.resolution_nm_zyx)
    fig, axes = plt.subplots(1, len(candidates) + 1, figsize=(1.8 * (len(candidates) + 1), 2.12), constrained_layout=True)
    axes = np.atleast_1d(axes)
    axes[0].imshow(robust01(raw), cmap="gray", extent=extent, interpolation="nearest", aspect="equal")
    decorate_image_axis(axes[0], args.axis, raw.shape, args.resolution_nm_zyx, "a", "Raw EM")
    for index, ((beta, path), ax) in enumerate(zip(candidates, axes[1:]), start=1):
        labels, _ = slice_zyx(load_array(path), args.axis, args.index)
        if labels.shape != raw.shape:
            raise ValueError(f"Instance {path} slice shape {labels.shape} does not match raw {raw.shape}")
        count = np.unique(labels[labels > 0]).size
        selected = args.selected_beta is not None and np.isclose(beta, args.selected_beta, rtol=0, atol=1e-12)
        ax.imshow(instance_overlay(raw, labels), extent=extent, interpolation="nearest", aspect="equal")
        decorate_image_axis(ax, args.axis, raw.shape, args.resolution_nm_zyx, chr(97 + index), f"β={beta:g} · n_slice={count}" + (" · selected" if selected else ""))
        for spine in ax.spines.values():
            spine.set_visible(selected)
            spine.set_color("#00A6D6")
            spine.set_linewidth(2.2)
    fig.suptitle(f"Instance beta sweep · user selection required · {args.axis.upper()} slice {chosen}", x=0.01, ha="left", fontsize=8, weight="bold")
    written = save_figure(fig, args.output_stem, args.formats, args.dpi)
    plt.close(fig)
    return written


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    sub = root.add_subparsers(dest="command", required=True)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--raw", type=Path, required=True)
    common.add_argument("--axis", choices=("xy", "xz", "yz"), default="xy")
    common.add_argument("--index", type=int)
    common.add_argument("--resolution-nm-zyx", nargs=3, type=float, required=True)
    common.add_argument("--output-stem", type=Path, required=True)
    common.add_argument("--formats", nargs="+", choices=("png", "svg", "pdf", "tiff"), default=["png", "svg", "pdf"])
    common.add_argument("--dpi", type=int, default=DEFAULT_RASTER_DPI)
    summary = sub.add_parser("summary", parents=[common])
    summary.add_argument("--affinities", type=Path, required=True)
    summary.add_argument("--membrane", type=Path, required=True)
    summary.add_argument("--membrane-mode", choices=("boundary", "interior"), default="boundary")
    summary.add_argument("--instances", type=Path, required=True)
    sweep = sub.add_parser("beta-sweep", parents=[common])
    sweep.add_argument("--instance", action="append", type=parse_instance_spec, required=True, metavar="BETA=PATH")
    sweep.add_argument("--selected-beta", type=float)
    return root


def main() -> int:
    args = parser().parse_args()
    written = draw_summary(args) if args.command == "summary" else draw_beta_sweep(args)
    print("\n".join(str(path) for path in written))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
