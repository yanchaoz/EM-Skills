"""Shared contracts: image arrays are YX; physical metadata are XYZ."""
from __future__ import annotations
import hashlib
import json
import math
import os
from pathlib import Path


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    tmp.replace(path)


def digest_file(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def identity(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def resolve(base, path):
    p = Path(path).expanduser()
    return (p if p.is_absolute() else Path(base) / p).resolve()


def positive_xyz(value, name="voxel_size_nm_xyz"):
    if not isinstance(value, list) or len(value) != 3 or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or v <= 0 for v in value):
        raise ValueError(f"{name} must contain three positive finite XYZ values")
    return value


def read_plane(path, allow_bool=False):
    import numpy as np
    p = Path(path)
    if p.suffix.lower() == ".npy":
        a = np.load(p, mmap_mode="r", allow_pickle=False)
    elif p.suffix.lower() in (".tif", ".tiff"):
        import tifffile
        with tifffile.TiffFile(p) as tif:
            if len(tif.pages) != 1:
                raise ValueError(f"Expected one YX plane per file, found multipage TIFF: {p}")
            a = tif.asarray()
    else:
        from PIL import Image
        with Image.open(p) as im:
            if im.mode == "P":
                palette = im.getpalette()
                linear = [v for i in range(256) for v in (i, i, i)]
                if palette is None or palette[:768] != linear:
                    raise ValueError(f"Nonlinear/color palette needs explicit conversion: {p}")
            a = np.asarray(im).copy()
    if a.ndim != 2 or a.dtype.kind not in ("uifb" if allow_bool else "uif") or not np.isfinite(a).all():
        raise ValueError(f"Expected finite scalar YX image: {p}")
    return a


def pixel_hash(a):
    return hashlib.sha256(a.tobytes(order="C")).hexdigest()


def validate_sections(sections):
    if not isinstance(sections, list) or not sections:
        raise ValueError("An explicit nonempty ordered sections list is required")
    ids = [s["id"] for s in sections]
    if any(not isinstance(s, str) or not s for s in ids) or len(set(ids)) != len(ids):
        raise ValueError("Section IDs must be nonempty and unique within each group")
    if [s["z_index"] for s in sections] != list(range(len(sections))):
        raise ValueError("Declare contiguous z_index values; do not compact missing sections")


def load_project(path):
    path = Path(path).resolve()
    cfg = read_json(path)
    if cfg.get("schema_version") != 1 or cfg.get("axes") != "yx":
        raise ValueError("Expected schema_version=1 and axes=yx for per-section files")
    positive_xyz(cfg["voxel_size_nm_xyz"])
    groups = cfg["groups"]
    if not groups or cfg.get("group_relationship") != "independent":
        raise ValueError("Resolve groups into explicitly independent volumes before planning")
    ids = [g["id"] for g in groups]
    if len(set(ids)) != len(ids) or any(not isinstance(i, str) or not i or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for c in i) for i in ids):
        raise ValueError("Group IDs must be unique path-safe names")
    output = resolve(path.parent, cfg["output_root"])
    all_paths = set()
    for group in groups:
        validate_sections(group["sections"])
        for section in group["sections"]:
            p = resolve(path.parent, section["path"])
            if p in all_paths:
                raise ValueError(f"Repeated source path: {p}")
            all_paths.add(p)
            if p == output or output in p.parents:
                raise ValueError("Output root would contain protected source files")
    return path, cfg, output


def load_result(path):
    path = Path(path).resolve()
    cfg = read_json(path)
    if cfg.get("schema_version") != 1 or cfg.get("axes") != "zyx":
        raise ValueError("Result requires schema_version=1 and axes=zyx")
    positive_xyz(cfg["voxel_size_nm_xyz"])
    offset = cfg["voxel_offset_xyz"]
    if len(offset) != 3 or any(isinstance(v, bool) or not isinstance(v, int) for v in offset):
        raise ValueError("voxel_offset_xyz must contain three integers")
    validate_sections(cfg["sections"])
    shape = cfg["shape_zyx"]
    if len(shape) != 3 or any(isinstance(v, bool) or not isinstance(v, int) or v <= 0 for v in shape) or shape[0] != len(cfg["sections"]):
        raise ValueError("Result shape/count mismatch")
    if cfg.get("artifact_kind") != "aligned_intensity":
        raise ValueError("Export requires aligned intensities, not fields, meshes or matching images")
    return path, cfg


def iter_result(path):
    path, cfg = load_result(path)
    cv = None
    if cfg.get("cloudvolume"):
        from cloudvolume import CloudVolume
        cv = CloudVolume(cfg["cloudvolume"], mip=0, fill_missing=False, progress=False, parallel=1)
        if cv.info.get("num_channels") != 1 or cv.info.get("type") != "image":
            raise ValueError("Expected a single-channel intensity CloudVolume")
        scale = cv.info["scales"][0]
        if list(scale["size"]) != cfg["shape_zyx"][::-1] or list(scale["voxel_offset"]) != cfg["voxel_offset_xyz"] or list(scale["resolution"]) != cfg["voxel_size_nm_xyz"]:
            raise ValueError("CloudVolume grid differs from result manifest")
    for section in cfg["sections"]:
        if cv is None:
            p = resolve(path.parent, section["path"])
            a = read_plane(p)
        else:
            import numpy as np
            p = cfg["cloudvolume"]
            z = cfg["voxel_offset_xyz"][2] + section["z_index"]
            a = np.asarray(cv[:, :, z:z + 1])[:, :, 0, 0].T
        if list(a.shape) != cfg["shape_zyx"][1:] or str(a.dtype) != cfg["dtype"]:
            raise ValueError(f"Result geometry/dtype mismatch: {p}")
        if section.get("sha256_pixels") and pixel_hash(a) != section["sha256_pixels"]:
            raise ValueError(f"Result pixels changed: {p}")
        yield section, a
