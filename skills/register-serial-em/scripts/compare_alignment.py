"""Compare adjacent-section continuity on identical physical grids and support."""
from __future__ import annotations
import argparse
import numpy as np
from registration_common import iter_result, load_result, read_plane, resolve, write_json


def correlation(a, b, valid):
    x, y = np.asarray(a[valid], dtype=np.float64), np.asarray(b[valid], dtype=np.float64)
    if x.size < 2:
        return None
    x -= x.mean()
    y -= y.mean()
    scale = np.linalg.norm(x) * np.linalg.norm(y)
    return float(np.clip(np.dot(x, y) / scale, -1, 1)) if scale > 0 else None


def bilinear_jacobian_stats(displacement_xy, spacing_xy=(1, 1)):
    """Relative XY offsets in image pixels, sampled on a regular YX grid."""
    d = np.asarray(displacement_xy, dtype=np.float64)
    spacing = np.asarray(spacing_xy, dtype=float)
    if d.ndim != 3 or d.shape[0] != 2 or min(d.shape[1:]) < 2 or spacing.shape != (2,) or not np.isfinite(spacing).all() or (spacing <= 0).any():
        raise ValueError("Expected displacement [2,Y,X] and positive XY spacing")
    if not np.isfinite(d).all():
        raise ValueError("Nonfinite displacement field")
    yy, xx = np.indices(d.shape[1:])
    q = d + np.stack([xx * spacing[0], yy * spacing[1]])
    top = (q[:, :-1, 1:] - q[:, :-1, :-1]) / spacing[0]
    bottom = (q[:, 1:, 1:] - q[:, 1:, :-1]) / spacing[0]
    left = (q[:, 1:, :-1] - q[:, :-1, :-1]) / spacing[1]
    right = (q[:, 1:, 1:] - q[:, :-1, 1:]) / spacing[1]
    dets = np.stack([dx[0] * dy[1] - dx[1] * dy[0]
                     for dx, dy in ((top, left), (top, right), (bottom, left), (bottom, right))])
    return {"cells": int(dets.shape[1] * dets.shape[2]),
            "nonpositive_cells": int(np.any(dets <= 0, axis=0).sum()),
            "minimum_corner_jacobian": float(dets.min()),
            "maximum_corner_jacobian": float(dets.max())}


def compare(manifests):
    if len(manifests) < 2:
        raise ValueError("Provide a baseline and at least one candidate")
    loaded = [load_result(p) for p in manifests]
    paths, configs = zip(*loaded)
    reference = configs[0]
    for cfg in configs[1:]:
        for key in ("shape_zyx", "dtype", "voxel_size_nm_xyz", "voxel_offset_xyz"):
            if cfg[key] != reference[key]:
                raise ValueError(f"Common physical grid required: {key}")
        if [s["id"] for s in cfg["sections"]] != [s["id"] for s in reference["sections"]]:
            raise ValueError("Section correspondence differs")
    if reference["shape_zyx"][0] < 2:
        raise ValueError("Need at least two sections for continuity")
    streams = [iter_result(p) for p in paths]
    previous = previous_valid = None
    pairs = []
    for z in range(reference["shape_zyx"][0]):
        current, masks = [], []
        for path, stream in zip(paths, streams):
            section, plane = next(stream)
            if not section.get("valid_mask"):
                raise ValueError("Explicit valid_mask required; zero intensity is not a validity mask")
            mask = read_plane(resolve(path.parent, section["valid_mask"]), allow_bool=True)
            if mask.shape != plane.shape:
                raise ValueError("Validity mask shape mismatch")
            current.append(plane)
            masks.append(mask != 0)
        current_valid = np.logical_and.reduce(masks)
        if previous is not None:
            valid = previous_valid & current_valid
            pairs.append({"z_pair": [z - 1, z], "common_pixels": int(valid.sum()),
                          "common_fraction": float(valid.mean()),
                          "ncc": [correlation(a, b, valid) for a, b in zip(previous, current)]})
        previous, previous_valid = current, current_valid
    return {"status": "computed", "manifests": [str(p) for p in paths],
            "metric": "adjacent-section NCC on common valid support",
            "scope": "Continuity proxy, not ground-truth accuracy or a backend ranking",
            "pairs": pairs}


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("manifests", nargs="+")
    p.add_argument("--out", required=True)
    a = p.parse_args()
    report = compare(a.manifests)
    write_json(a.out, report)
    print(f"Compared {len(report['pairs'])} adjacent pairs on common support")
