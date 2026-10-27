"""Coordinate-safe primitives shared by the EM cutaway command line tools.

Arrays are always ZYX. Physical positions are global XYZ; VDB indices are XYZ.
All geometry distances are micrometres, while Blender object transforms use mm.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import numpy as np


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _vector(value, length, label, positive=False):
    a = np.asarray(value, dtype=float)
    if a.shape != (length,) or not np.isfinite(a).all():
        raise ValueError(f"{label} must contain {length} finite numbers")
    if positive and not (a > 0).all():
        raise ValueError(f"{label} must be positive")
    return a


def validate_config(cfg):
    if cfg.get("schema_version") != 1:
        raise ValueError("Only schema_version 1 is supported")
    src = cfg["source"]
    if src.get("axis_order") != "zyx":
        raise ValueError("source.axis_order must explicitly be 'zyx'")
    _vector(src["voxel_size_nm_xyz"], 3, "voxel_size_nm_xyz", True)
    _vector(src.get("offset_nm_xyz", [0, 0, 0]), 3, "source.offset_nm_xyz")
    if not isinstance(src.get("zero_is_missing"), bool):
        raise ValueError("source.zero_is_missing must be explicitly true or false")
    geom = cfg.get("geometry", {})
    if not isinstance(geom.get("reflect_z", False), bool):
        raise ValueError("geometry.reflect_z must be boolean")
    if not np.isfinite(float(geom.get("basis_rotation_deg", 0))):
        raise ValueError("basis_rotation_deg must be finite")
    if "outer_uv_bounds_um" in geom:
        bounds = np.asarray(geom["outer_uv_bounds_um"], float)
        if bounds.shape != (2, 2) or not np.isfinite(bounds).all() or not (bounds[1] > bounds[0]).all():
            raise ValueError("outer_uv_bounds_um must be [[low U,low V],[high U,high V]]")
    if "display_z_bounds_um" in geom:
        b = _vector(geom["display_z_bounds_um"], 2, "display_z_bounds_um")
        if b[1] <= b[0]:
            raise ValueError("display_z_bounds_um must increase")
    planes = list(geom.get("keep_planes", []))
    for region in geom.get("remove_regions", []):
        if not region.get("planes"):
            raise ValueError("Every remove region needs at least one plane")
        for plane in region["planes"]:
            if "only_below_v_um" in plane:
                raise ValueError("only_below_v_um applies to keep_planes only")
        planes.extend(region["planes"])
    for plane in planes:
        coeff = _vector(plane["coeff_uvz"], 3, "coeff_uvz")
        if not np.any(coeff):
            raise ValueError("Plane normal cannot be zero")
        if not np.isfinite(float(plane["threshold_um"])):
            raise ValueError("Plane threshold must be finite")
        if "only_below_v_um" in plane and not np.isfinite(float(plane["only_below_v_um"])):
            raise ValueError("Conditional V boundary must be finite")
    mesh = cfg.get("mesh")
    if mesh:
        if mesh.get("units") not in ("nm", "um", "mm"):
            raise ValueError("mesh.units must be nm, um or mm; mesh.offset_nm_xyz always uses nm")
        _vector(mesh.get("offset_nm_xyz", [0, 0, 0]), 3, "mesh.offset_nm_xyz")
    display = cfg.get("display", {})
    norm = display.get("normalization", {"mode": "none"})
    if norm.get("mode", "none") not in ("none", "per_slice_percentile"):
        raise ValueError("normalization.mode must be none or per_slice_percentile")
    if norm.get("mode") == "per_slice_percentile":
        pct = _vector(norm.get("percentiles", [1, 99]), 2, "normalization.percentiles")
        if not 0 <= pct[0] < pct[1] <= 100:
            raise ValueError("Normalization percentiles must satisfy 0 <= low < high <= 100")
    illum = display.get("illumination", {})
    if not isinstance(illum.get("enabled", False), bool):
        raise ValueError("illumination.enabled must be boolean")
    if illum.get("enabled", False):
        max_gain, target = float(illum.get("max_gain", 4.5)), float(illum.get("target_mean", 110))
        factor, sigma = float(illum.get("downsample", 8)), float(illum.get("sigma", 3))
        if not np.isfinite([max_gain, target, factor, sigma]).all():
            raise ValueError("Illumination parameters must be finite")
        if max_gain < 1 or target <= 0:
            raise ValueError("Illumination max_gain >= 1 and target_mean > 0 are required")
        if factor < 1 or factor != int(factor) or sigma < 0:
            raise ValueError("Illumination downsample must be an integer >= 1; sigma must be >= 0")
    if "output_dir" not in cfg:
        raise ValueError("output_dir is required")
    out = Path(cfg["output_dir"]).resolve()
    for item in (src, mesh):
        if item:
            p = Path(item["path"]).resolve()
            if p == out or p.is_relative_to(out):
                raise ValueError("Input source/mesh cannot be inside output_dir")


def load_config(path):
    path = Path(path).resolve()
    cfg = json.loads(path.read_text(encoding="utf-8-sig"))
    for section in ("source", "mesh"):
        if cfg.get(section):
            p = Path(cfg[section]["path"])
            cfg[section]["path"] = str((path.parent / p).resolve() if not p.is_absolute() else p.resolve())
    p = Path(cfg["output_dir"])
    cfg["output_dir"] = str((path.parent / p).resolve() if not p.is_absolute() else p.resolve())
    cfg["_config_path"] = str(path)
    validate_config(cfg)
    return cfg


def open_source(cfg):
    """Read uint8 3D NPY or TIFF; compressed TIFF may require full RAM decoding."""
    path = Path(cfg["source"]["path"])
    if path.suffix.lower() == ".npy":
        a = np.load(path, mmap_mode="r", allow_pickle=False)
    elif path.suffix.lower() in (".tif", ".tiff"):
        try:
            import tifffile
        except ImportError as exc:
            raise RuntimeError("TIFF input needs tifffile") from exc
        try:
            a = tifffile.memmap(path, mode="r")
        except ValueError:
            a = tifffile.imread(path)
    else:
        raise ValueError("Only .npy, .tif and .tiff inputs are supported")
    if a.ndim != 3 or a.dtype != np.uint8 or min(a.shape) < 1:
        raise ValueError(f"Expected uint8 ZYX volume, received {a.dtype} {a.shape}")
    a.flags.writeable = False
    return a


def source_metadata(cfg, array):
    src = cfg["source"]
    return dict(path=src["path"], sha256=sha256(src["path"]), shape_zyx=list(array.shape),
                dtype=str(array.dtype), axis_order="zyx", voxel_size_nm_xyz=src["voxel_size_nm_xyz"],
                offset_nm_xyz=src.get("offset_nm_xyz", [0, 0, 0]), zero_is_missing=src["zero_is_missing"])


def transform_metadata(cfg, shape_zyx):
    spacing = np.asarray(cfg["source"]["voxel_size_nm_xyz"], float)
    offset = np.asarray(cfg["source"].get("offset_nm_xyz", [0, 0, 0]), float)
    pivot = 2 * offset[2] + (shape_zyx[0] - 1) * spacing[2]
    location = offset.copy()
    scale = spacing.copy()
    reflect = cfg.get("geometry", {}).get("reflect_z", False)
    if reflect:
        location[2] = pivot - offset[2]
        scale[2] *= -1
    return dict(volume_scale_xyz=(scale / 1e6).tolist(), volume_location_mm=(location / 1e6).tolist(),
                reflect_z=reflect, reflection_pivot_nm=float(pivot))


def native_world_um(cfg, shape_zyx, x, y, z):
    t = transform_metadata(cfg, shape_zyx)
    return tuple(np.asarray(q) * s * 1000 + o * 1000
                 for q, s, o in zip((x, y, z), t["volume_scale_xyz"], t["volume_location_mm"]))


def world_to_uv(cfg, x, y):
    angle = np.deg2rad(cfg.get("geometry", {}).get("basis_rotation_deg", 0))
    c, s = np.cos(angle), np.sin(angle)
    return np.asarray(x) * c + np.asarray(y) * s, -np.asarray(x) * s + np.asarray(y) * c


def keep_mask(cfg, u, v, z):
    """Inclusive outer/keep bounds. Remove intersections use strictly > planes.

    Optional keep-plane V exception: apply the plane only where V < boundary.
    Native voxel centres are evaluated, not voxel bounding boxes.
    """
    u, v, z = np.broadcast_arrays(u, v, z)
    keep = np.ones(u.shape, dtype=bool)
    geom = cfg.get("geometry", {})
    if "outer_uv_bounds_um" in geom:
        (u0, v0), (u1, v1) = geom["outer_uv_bounds_um"]
        keep &= (u >= u0) & (u <= u1) & (v >= v0) & (v <= v1)
    if "display_z_bounds_um" in geom:
        z0, z1 = geom["display_z_bounds_um"]
        keep &= (z >= z0) & (z <= z1)
    def value(p):
        a, b, c = p["coeff_uvz"]
        return a * u + b * v + c * z
    for p in geom.get("keep_planes", []):
        passed = value(p) >= p["threshold_um"]
        if "only_below_v_um" in p:
            passed |= v >= p["only_below_v_um"]
        keep &= passed
    for region in geom.get("remove_regions", []):
        removed = np.ones(u.shape, dtype=bool)
        for p in region["planes"]:
            removed &= value(p) > p["threshold_um"]
        keep &= ~removed
    return keep


def source_support(cfg, layer):
    return layer != 0 if cfg["source"]["zero_is_missing"] else np.ones(layer.shape, bool)


def display_layer(cfg, layer):
    """Display-only gain/LUT; native EM values and locations remain untouched."""
    support = source_support(cfg, layer)
    corrected = layer.astype(np.float32)
    opts = cfg.get("display", {})
    illum = opts.get("illumination", {})
    gain_range = [1.0, 1.0]
    if illum.get("enabled", False):
        try:
            from scipy.ndimage import gaussian_filter, map_coordinates
        except ImportError as exc:
            raise RuntimeError("Illumination compensation requires scipy") from exc
        factor = int(illum.get("downsample", 8))
        h, w = layer.shape
        ys, xs = np.arange(0, h, factor), np.arange(0, w, factor)
        # Block sums avoid sampling holes as if they were real dark tissue.
        sums = np.add.reduceat(np.add.reduceat(corrected * support, ys, axis=0), xs, axis=1)
        counts = np.add.reduceat(np.add.reduceat(support.astype(np.float32), ys, axis=0), xs, axis=1)
        sigma = float(illum.get("sigma", 3))
        num = gaussian_filter(sums, sigma, mode="nearest")
        den = gaussian_filter(counts, sigma, mode="nearest")
        mean = np.divide(num, den, out=np.ones_like(num), where=den > 0)
        gain = np.clip(float(illum.get("target_mean", 110)) / np.maximum(mean, 1e-6), 1,
                       float(illum.get("max_gain", 4.5)))
        gain[den <= 0] = 1
        yy, xx = np.meshgrid((np.arange(h) + .5) / factor - .5,
                             (np.arange(w) + .5) / factor - .5, indexing="ij")
        full_gain = map_coordinates(gain, [yy, xx], order=1, mode="nearest")
        corrected = np.clip(corrected * full_gain, 0, 255)
        gain_range = [float(full_gain.min()), float(full_gain.max())]
    norm = opts.get("normalization", {})
    limits = [0.0, 255.0]
    if norm.get("mode", "none") == "per_slice_percentile" and np.any(support):
        limits = np.percentile(corrected[support], norm.get("percentiles", [1, 99])).tolist()
        if limits[1] > limits[0]:
            corrected = np.clip((corrected - limits[0]) / (limits[1] - limits[0]), 0, 1) * 255
        # Constant-intensity planes keep their original display value.
    srgb = corrected / 255.0
    linear = np.where(srgb <= .04045, srgb / 12.92, ((srgb + .055) / 1.055) ** 2.4)
    linear = np.asarray(linear * support, np.float32)
    return linear, support, dict(percentile_limits=limits, gain_range=gain_range,
                                support_voxels=int(support.sum()), raw_zero_voxels=int((layer == 0).sum()))


def write_json(path, payload):
    Path(path).write_text(json.dumps(payload, indent=2, allow_nan=False) + "\n", encoding="utf-8")
