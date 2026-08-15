#!/usr/bin/env python3
"""Prepare, verify, hand off, and locally serve Neuroglancer precomputed EM data.

Conversion supports single-channel NPY, TIFF, and Zarr arrays.  It writes a
base mip in bounded chunks and never mutates the source array.  Optional mip
pyramids remain an explicit external backend decision.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote, urlparse


SUPPORTED_AXES = {"yx", "xy", "zyx", "xyz", "zyxc", "xyzc"}


def require_numpy():
    try:
        import numpy as np
    except ImportError as exc:
        raise SystemExit(f"NumPy is required: {exc}")
    return np


def require_cloudvolume():
    try:
        from cloudvolume import CloudVolume
    except ImportError as exc:
        raise SystemExit(
            "CloudVolume is required for convert/verify. Use an existing server "
            f"environment; this script does not install dependencies: {exc}"
        )
    return CloudVolume


def resolve_from(base, value):
    path = Path(value)
    return path.resolve() if path.is_absolute() else (base / path).resolve()


def is_within(path, root):
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def validate_url(url, field):
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"{field} must be an http(s) URL")
    if parsed.username or parsed.password or parsed.query:
        raise ValueError(f"{field} must not contain credentials or query secrets")
    return url.rstrip("/")


def load_config(path):
    cfg_path = Path(path).resolve()
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    block = cfg.get("precomputed")
    if not isinstance(block, dict):
        raise ValueError("Missing top-level precomputed object")
    root = resolve_from(cfg_path.parent, block.get("root", "derived/precomputed"))
    datasets = block.get("datasets")
    if not isinstance(datasets, list) or not datasets:
        raise ValueError("precomputed.datasets must be a non-empty list")
    ids = [item.get("id") for item in datasets]
    if any(not value for value in ids) or len(ids) != len(set(ids)):
        raise ValueError("precomputed dataset ids must be present and unique")
    outputs = []
    for item in datasets:
        output = Path(item.get("output", ""))
        if not str(output) or output.is_absolute() or ".." in output.parts:
            raise ValueError(f"{item['id']}.output must be a safe path relative to precomputed.root")
        target = (root / output).resolve()
        if not is_within(target, root) or target == root:
            raise ValueError(f"Unsafe output for {item['id']}: {target}")
        item["_target"] = str(target)
        outputs.append(str(target).casefold())
        if item.get("source") is not None:
            source = item["source"]
            if not isinstance(source, dict) or not source.get("path"):
                raise ValueError(f"{item['id']}.source.path is required")
            axes = str(source.get("axes", "")).lower()
            if axes not in SUPPORTED_AXES:
                raise ValueError(f"Unsupported axes for {item['id']}: {axes}")
            source_path = resolve_from(cfg_path.parent, source["path"])
            if target == source_path or is_within(target, source_path):
                raise ValueError(
                    f"{item['id']}.output must not overwrite or be nested inside its source"
                )
            item["_source"] = str(source_path)
        layer_type = item.get("layer_type", "image")
        if layer_type not in {"image", "segmentation"}:
            raise ValueError(f"{item['id']}.layer_type must be image or segmentation")
        for key, default in (("resolution_nm_xyz", None), ("voxel_offset_xyz", [0, 0, 0]),
                             ("chunk_size_xyz", [256, 256, 1])):
            value = item.get(key, default)
            if not (isinstance(value, list) and len(value) == 3 and
                    all(isinstance(x, (int, float)) and x > 0 for x in value)):
                if key == "voxel_offset_xyz" and isinstance(value, list) and len(value) == 3 and all(
                        isinstance(x, (int, float)) for x in value):
                    continue
                raise ValueError(f"{item['id']}.{key} must contain three positive numbers")
        item.setdefault("voxel_offset_xyz", [0, 0, 0])
        item.setdefault("chunk_size_xyz", [256, 256, 1])
        item.setdefault("encoding", "raw")
        if item["encoding"] not in {"raw", "jpeg", "compressed_segmentation"}:
            raise ValueError(f"Unsupported encoding for {item['id']}: {item['encoding']}")
        if layer_type == "segmentation" and item["encoding"] == "jpeg":
            raise ValueError("JPEG is not valid for categorical segmentation")
    if len(outputs) != len(set(outputs)):
        raise ValueError("precomputed dataset outputs must be unique")
    block["_root"] = str(root)
    block.setdefault("hash_source", False)
    cfg["_config_path"] = str(cfg_path)
    return cfg


def select_datasets(cfg, selected):
    wanted = set(selected or [])
    datasets = [item for item in cfg["precomputed"]["datasets"] if not wanted or item["id"] in wanted]
    missing = wanted - {item["id"] for item in datasets}
    if missing:
        raise ValueError(f"Unknown precomputed dataset ids: {sorted(missing)}")
    return datasets


def infer_format(path, explicit=None):
    if explicit:
        return str(explicit).lower()
    suffix = path.suffix.lower()
    if suffix == ".npy":
        return "npy"
    if suffix in {".tif", ".tiff"}:
        return "tiff"
    if suffix in {".zarr", ".n5"} or path.is_dir():
        return "zarr"
    raise ValueError(f"Cannot infer source format from {path}")


def open_source(item):
    np = require_numpy()
    source_cfg = item.get("source")
    if source_cfg is None:
        raise ValueError(f"{item['id']} has no source; it is existing-precomputed only")
    path = Path(item["_source"])
    if not path.exists():
        raise FileNotFoundError(path)
    kind = infer_format(path, source_cfg.get("format"))
    mode = None
    if kind == "npy":
        array = np.load(path, mmap_mode="r", allow_pickle=False)
        mode = "numpy-memmap"
    elif kind == "tiff":
        try:
            import tifffile
        except ImportError as exc:
            raise SystemExit(f"tifffile is required for TIFF input: {exc}")
        try:
            array = tifffile.memmap(path)
            mode = "tiff-memmap"
        except Exception:
            array = tifffile.imread(path)
            mode = "tiff-loaded"
    elif kind in {"zarr", "n5"}:
        try:
            import zarr
        except ImportError as exc:
            raise SystemExit(f"zarr is required for Zarr/N5 input: {exc}")
        if kind == "n5" or path.suffix.lower() == ".n5":
            try:
                from zarr.storage import N5Store
            except ImportError as exc:
                raise SystemExit(
                    "This zarr runtime has no N5Store; use an existing environment "
                    f"with Zarr v2 N5 support or convert N5 to Zarr first: {exc}"
                )
            store = zarr.open(store=N5Store(str(path)), mode="r")
        else:
            store = zarr.open(str(path), mode="r")
        key = source_cfg.get("array_path")
        array = store[key] if key else store
        if not hasattr(array, "shape"):
            raise ValueError(f"{item['id']} Zarr source is a group; set source.array_path")
        mode = "zarr"
    else:
        raise AssertionError(kind)
    axes = str(source_cfg["axes"]).lower()
    shape = tuple(map(int, array.shape))
    if len(shape) != len(axes):
        raise ValueError(f"{item['id']} axes {axes} do not match source shape {shape}")
    if "c" in axes and shape[axes.index("c")] != 1:
        raise ValueError(f"{item['id']} must be single-channel; got shape {shape}")
    return array, axes, {"format": kind, "access_mode": mode, "shape": list(shape),
                         "dtype": str(array.dtype), "path": str(path)}


def shape_xyz(shape, axes):
    result = [shape[axes.index(axis)] if axis in axes else 1 for axis in "xyz"]
    return tuple(map(int, result))


def read_xyz(array, axes, bounds):
    np = require_numpy()
    x0, x1, y0, y1, z0, z1 = bounds
    ranges = {"x": slice(x0, x1), "y": slice(y0, y1), "z": slice(z0, z1), "c": slice(0, 1)}
    block = np.asarray(array[tuple(ranges[axis] for axis in axes)])
    active_axes = axes
    if "c" in active_axes:
        block = np.squeeze(block, axis=active_axes.index("c"))
        active_axes = active_axes.replace("c", "")
    if "z" not in active_axes:
        block = np.transpose(block, [active_axes.index("x"), active_axes.index("y")])[..., None]
    else:
        block = np.transpose(block, [active_axes.index(axis) for axis in "xyz"])
    return np.ascontiguousarray(block)


def iter_bounds(size_xyz, chunk_xyz):
    sx, sy, sz = map(int, size_xyz)
    cx, cy, cz = map(int, chunk_xyz)
    for z0 in range(0, sz, cz):
        for y0 in range(0, sy, cy):
            for x0 in range(0, sx, cx):
                yield (x0, min(sx, x0 + cx), y0, min(sy, y0 + cy), z0, min(sz, z0 + cz))


def file_identity(path, full_hash=False):
    path = Path(path)
    if path.is_file():
        stat = path.stat()
        record = {"bytes": stat.st_size, "mtime_ns": stat.st_mtime_ns}
        if full_hash:
            digest = hashlib.sha256()
            with path.open("rb") as handle:
                for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
                    digest.update(block)
            record["sha256"] = digest.hexdigest()
        return record
    metadata = []
    for name in (".zarray", ".zattrs", "zarr.json", "attributes.json"):
        for candidate in sorted(path.rglob(name)):
            metadata.append((str(candidate.relative_to(path)), hashlib.sha256(candidate.read_bytes()).hexdigest()))
    return {"metadata_sha256": hashlib.sha256(json.dumps(metadata).encode()).hexdigest(),
            "metadata_files": len(metadata), "full_data_hash": False}


def info_sha256(target):
    return hashlib.sha256((Path(target) / "info").read_bytes()).hexdigest()


def manifest_path(cfg, item, suffix):
    root = Path(cfg["precomputed"]["_root"])
    path = root / "_manifests" / f"{item['id']}.{suffix}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def inspect_dataset(cfg, item):
    target = Path(item["_target"])
    record = {"id": item["id"], "target": str(target), "layer_type": item.get("layer_type", "image"),
              "target_exists": (target / "info").is_file()}
    if item.get("source") is not None:
        array, axes, source_meta = open_source(item)
        size = shape_xyz(array.shape, axes)
        record.update({"source": source_meta, "axes": axes, "size_xyz": list(size),
                       "estimated_uncompressed_bytes": int(math.prod(size) * array.dtype.itemsize),
                       "resolution_nm_xyz": item["resolution_nm_xyz"],
                       "voxel_offset_xyz": item["voxel_offset_xyz"],
                       "chunk_size_xyz": item["chunk_size_xyz"]})
    elif record["target_exists"]:
        record["info"] = json.loads((target / "info").read_text(encoding="utf-8"))
    else:
        raise FileNotFoundError(f"No source and no existing precomputed info for {item['id']}")
    return record


def expected_info(CloudVolume, item, array, axes):
    size = list(shape_xyz(array.shape, axes))
    kwargs = {}
    if item["encoding"] == "jpeg" and str(array.dtype) != "uint8":
        raise ValueError(f"{item['id']} JPEG encoding requires uint8 image data")
    if item["encoding"] == "compressed_segmentation":
        kwargs["compressed_segmentation_block_size"] = [
            max(value for value in range(1, min(8, int(chunk)) + 1) if int(chunk) % value == 0)
            for chunk in item["chunk_size_xyz"]
        ]
    info = CloudVolume.create_new_info(
        num_channels=1, layer_type=item.get("layer_type", "image"),
        data_type=str(array.dtype), encoding=item["encoding"],
        resolution=list(map(int, item["resolution_nm_xyz"])),
        voxel_offset=list(map(int, item["voxel_offset_xyz"])),
        chunk_size=list(map(int, item["chunk_size_xyz"])), volume_size=size, **kwargs,
    )
    if item.get("segment_properties"):
        info["segment_properties"] = "segment_properties"
    return info


def write_segment_properties(target, properties):
    if not properties:
        return
    ids = sorted((str(key) for key in properties), key=lambda value: int(value))
    values = [str(properties[value] if value in properties else properties[int(value)]) for value in ids]
    payload = {"@type": "neuroglancer_segment_properties", "inline": {"ids": ids,
               "properties": [{"id": "label", "type": "label", "values": values}]}}
    path = Path(target) / "segment_properties" / "info"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def convert_dataset(cfg, item, force=False):
    CloudVolume = require_cloudvolume()
    array, axes, source_meta = open_source(item)
    target = Path(item["_target"])
    info = expected_info(CloudVolume, item, array, axes)
    if (target / "info").exists() and not force:
        raise FileExistsError(f"{target}/info exists; use --force only to rewrite the same declared grid")
    if (target / "info").exists() and force:
        existing = json.loads((target / "info").read_text(encoding="utf-8"))
        keys = ("type", "data_type", "num_channels")
        if any(existing.get(key) != info.get(key) for key in keys) or existing["scales"][0] != info["scales"][0]:
            raise ValueError(f"Refusing --force because existing info grid differs for {item['id']}")
    target.parent.mkdir(parents=True, exist_ok=True)
    volume = CloudVolume("file://" + str(target), info=info, compress=True, progress=False)
    volume.commit_info()
    write_segment_properties(target, item.get("segment_properties"))
    size = shape_xyz(array.shape, axes)
    bounds = list(iter_bounds(size, item["chunk_size_xyz"]))
    ox, oy, oz = map(int, item["voxel_offset_xyz"])
    for index, bound in enumerate(bounds, 1):
        x0, x1, y0, y1, z0, z1 = bound
        volume[ox + x0:ox + x1, oy + y0:oy + y1, oz + z0:oz + z1] = read_xyz(
            array, axes, bound
        )[..., None]
        if index == 1 or index == len(bounds) or index % max(1, len(bounds) // 20) == 0:
            print(f"CONVERT {item['id']} chunks={index}/{len(bounds)}", flush=True)
    record = {
        "id": item["id"], "source": source_meta,
        "source_identity": file_identity(item["_source"], cfg["precomputed"].get("hash_source", False)),
        "target": str(target), "size_xyz": list(size), "dtype": str(array.dtype),
        "layer_type": item.get("layer_type", "image"), "encoding": item["encoding"],
        "resolution_nm_xyz": item["resolution_nm_xyz"], "voxel_offset_xyz": item["voxel_offset_xyz"],
        "chunk_size_xyz": item["chunk_size_xyz"], "info_sha256": info_sha256(target),
        "pyramid": "base mip only; additional mips require an explicit recorded backend",
    }
    manifest_path(cfg, item, "convert").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return record


def sample_bounds(size, chunk):
    sx, sy, sz = size
    cx, cy, cz = [min(int(chunk[i]), int(size[i])) for i in range(3)]
    starts = [(0, 0, 0), ((sx - cx) // 2, (sy - cy) // 2, (sz - cz) // 2),
              (sx - cx, sy - cy, sz - cz)]
    unique = []
    for x0, y0, z0 in starts:
        bound = (x0, x0 + cx, y0, y0 + cy, z0, z0 + cz)
        if bound not in unique:
            unique.append(bound)
    return unique


def verify_dataset(cfg, item):
    np = require_numpy()
    CloudVolume = require_cloudvolume()
    target = Path(item["_target"])
    if not (target / "info").is_file():
        raise FileNotFoundError(target / "info")
    volume = CloudVolume("file://" + str(target), progress=False, fill_missing=False)
    info = json.loads((target / "info").read_text(encoding="utf-8"))
    scale = info["scales"][0]
    ox, oy, oz = map(int, scale["voxel_offset"])
    checks = {"layer_type": info["type"] == item.get("layer_type", "image"),
              "num_channels": int(info["num_channels"]) == 1,
              "encoding": scale["encoding"] == item["encoding"],
              "chunk_size": list(map(int, scale["chunk_sizes"][0])) == list(map(int, item["chunk_size_xyz"])),
              "resolution": list(map(int, scale["resolution"])) == list(map(int, item["resolution_nm_xyz"])),
              "voxel_offset": list(map(int, scale["voxel_offset"])) == list(map(int, item["voxel_offset_xyz"]))}
    samples = []
    if item.get("source") is not None:
        array, axes, _ = open_source(item)
        size = shape_xyz(array.shape, axes)
        checks["size"] = list(map(int, scale["size"])) == list(size)
        checks["dtype"] = str(info["data_type"]) == str(array.dtype)
        for bound in sample_bounds(size, item["chunk_size_xyz"]):
            x0, x1, y0, y1, z0, z1 = bound
            expected = read_xyz(array, axes, bound)
            observed = np.asarray(
                volume[ox + x0:ox + x1, oy + y0:oy + y1, oz + z0:oz + z1]
            ).squeeze(-1)
            equal = bool(np.array_equal(expected, observed))
            samples.append({"bounds_xyzxyz": list(bound), "exact_equal": equal,
                            "expected_sha256": hashlib.sha256(expected.tobytes()).hexdigest(),
                            "observed_sha256": hashlib.sha256(observed.tobytes()).hexdigest()})
        checks["sample_readback"] = all(sample["exact_equal"] for sample in samples)
    else:
        size = tuple(map(int, scale["size"]))
        bound = sample_bounds(size, scale["chunk_sizes"][0])[0]
        x0, x1, y0, y1, z0, z1 = bound
        observed = np.asarray(volume[ox + x0:ox + x1, oy + y0:oy + y1, oz + z0:oz + z1])
        checks["sample_read"] = observed.size > 0
    record = {"id": item["id"], "target": str(target), "checks": checks,
              "samples": samples, "info_sha256": info_sha256(target), "ok": all(checks.values())}
    manifest_path(cfg, item, "verify").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    if not record["ok"]:
        raise RuntimeError(f"Precomputed verification failed for {item['id']}: {checks}")
    return record


def build_neuroglancer_state(cfg, datasets):
    ng = cfg.get("neuroglancer", {})
    base_url = validate_url(ng.get("base_url", "http://127.0.0.1:1337"), "neuroglancer.base_url")
    layers = []
    first_scale = None
    for item in datasets:
        info = json.loads((Path(item["_target"]) / "info").read_text(encoding="utf-8"))
        scale = info["scales"][0]
        first_scale = first_scale or scale
        relative = Path(item["_target"]).relative_to(Path(cfg["precomputed"]["_root"])).as_posix()
        layer = {"type": info["type"], "source": f"precomputed://{base_url}/{quote(relative, safe='/')}",
                 "name": item.get("label", item["id"])}
        if info["type"] == "segmentation" and item.get("segment_properties"):
            layer["segments"] = sorted(str(value) for value in item["segment_properties"])
        layers.append(layer)
    resolution = first_scale["resolution"]
    offset, size = first_scale["voxel_offset"], first_scale["size"]
    state = {
        "dimensions": {axis: [float(resolution[index]) * 1e-9, "m"] for index, axis in enumerate("xyz")},
        "position": [float(offset[index]) + float(size[index]) / 2.0 for index in range(3)],
        "crossSectionScale": float(ng.get("cross_section_scale", 1.0)),
        "projectionScale": float(ng.get("projection_scale", 1024.0)),
        "layers": layers,
        "layout": ng.get("layout", "xy"),
        "showAxisLines": bool(ng.get("show_axis_lines", False)),
        "showScaleBar": bool(ng.get("show_scale_bar", True)),
    }
    return state


def write_handoff(cfg, datasets):
    state = build_neuroglancer_state(cfg, datasets)
    root = Path(cfg["precomputed"]["_root"])
    root.mkdir(parents=True, exist_ok=True)
    state_path = root / "neuroglancer-state.json"
    state_path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    viewer = validate_url(cfg.get("neuroglancer", {}).get(
        "viewer_url", "https://neuroglancer-demo.appspot.com/"), "neuroglancer.viewer_url")
    viewer_url = viewer + "/#!" + quote(json.dumps(state, separators=(",", ":")), safe="")
    (root / "neuroglancer-viewer-url.txt").write_text(viewer_url + "\n", encoding="utf-8")
    return {"state": str(state_path), "viewer_url": viewer_url, "layers": len(state["layers"])}


def validate_serve_host(host, allow_public=False):
    if host not in {"127.0.0.1", "localhost", "::1"} and not allow_public:
        raise ValueError("Refusing a non-loopback server; pass --allow-public only after network review")
    return host


def serve(cfg, host, port, allow_public=False):
    host = validate_serve_host(host, allow_public)
    root = Path(cfg["precomputed"]["_root"])
    if not root.is_dir():
        raise FileNotFoundError(root)

    class CorsHandler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(root), **kwargs)

        def end_headers(self):
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, HEAD, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Range")
            super().end_headers()

        def do_OPTIONS(self):
            self.send_response(204)
            self.end_headers()

    print(f"SERVE root={root} url=http://{host}:{port}", flush=True)
    ThreadingHTTPServer((host, int(port)), CorsHandler).serve_forever()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("inspect", "convert", "verify", "handoff", "prepare", "serve"))
    parser.add_argument("config", type=Path)
    parser.add_argument("--dataset", action="append", default=[])
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=1337)
    parser.add_argument("--allow-public", action="store_true")
    args = parser.parse_args()
    cfg = load_config(args.config)
    datasets = select_datasets(cfg, args.dataset)
    if args.command == "inspect":
        result = [inspect_dataset(cfg, item) for item in datasets]
    elif args.command == "convert":
        result = [convert_dataset(cfg, item, args.force) for item in datasets if item.get("source") is not None]
    elif args.command == "verify":
        result = [verify_dataset(cfg, item) for item in datasets]
    elif args.command == "handoff":
        result = write_handoff(cfg, datasets)
    elif args.command == "prepare":
        converted = [convert_dataset(cfg, item, args.force) for item in datasets if item.get("source") is not None]
        verified = [verify_dataset(cfg, item) for item in datasets]
        result = {"converted": converted, "verified": verified, "handoff": write_handoff(cfg, datasets)}
    else:
        serve(cfg, args.host, args.port, args.allow_public)
        return
    print(json.dumps(result, indent=2), flush=True)


if __name__ == "__main__":
    main()
