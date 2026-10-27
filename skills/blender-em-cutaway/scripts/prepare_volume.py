"""Build a full native-grid OpenVDB cache, without geometry pruning/resampling."""
from __future__ import annotations
import argparse
import importlib
import os
from pathlib import Path
import sys
import time
import numpy as np
from cutaway_core import (display_layer, load_config, open_source, sha256,
                          source_metadata, transform_metadata, write_json)

_DLL_HANDLES = []


def import_vdb():
    # Official Windows Blender archives put OpenVDB DLLs at the runtime root.
    # Discover relative to this interpreter; never encode a user's installation.
    if os.name == "nt" and hasattr(os, "add_dll_directory"):
        for parent in Path(sys.executable).resolve().parents:
            if (parent / "blender.exe").is_file():
                _DLL_HANDLES.append(os.add_dll_directory(str(parent)))
                break
    for module in ("openvdb", "pyopenvdb"):
        try:
            return importlib.import_module(module)
        except (ImportError, OSError):
            continue
    raise RuntimeError("OpenVDB Python bindings are required. Run with a Python interpreter "
                       "providing openvdb/pyopenvdb (for example Blender's bundled Python).")


def prepare(config_path, output=None, overwrite=False, sample_count=1024):
    start = time.time()
    cfg = load_config(config_path)
    out = Path(output).resolve() if output else Path(cfg["output_dir"]) / "prepared"
    for item in (cfg["source"], cfg.get("mesh")):
        if item and Path(item["path"]).is_relative_to(out):
            raise ValueError("Preparation output must not contain any input source/mesh")
    files = [out / "volume.vdb", out / "manifest.json", out / "volume.partial.vdb"]
    if Path(cfg["_config_path"]) in files:
        raise ValueError("Prepared output cannot overwrite the project configuration")
    if not overwrite and any(p.exists() for p in files):
        raise FileExistsError(f"Prepared output exists in {out}; choose a new directory or --overwrite")
    vdb = import_vdb()
    raw = open_source(cfg)
    src = source_metadata(cfg, raw)
    mesh = None
    if cfg.get("mesh"):
        mesh = dict(cfg["mesh"], sha256=sha256(cfg["mesh"]["path"]))
    grids = []
    for name in ("em_linear", "em_support"):
        grid = vdb.FloatGrid(background=0.0)
        grid.name = name
        grid.gridClass = vdb.GridClass.FOG_VOLUME
        grid.transform = vdb.createLinearTransform(voxelSize=1.0)
        grids.append(grid)
    counts = [0, 0]
    layer_qa = []
    for first in range(0, raw.shape[0], 8):
        stop = min(first + 8, raw.shape[0])
        values = np.empty((stop - first, *raw.shape[1:]), np.float32)
        supports = np.empty_like(values)
        for j, z in enumerate(range(first, stop)):
            values[j], supports[j], qa = display_layer(cfg, raw[z])
            layer_qa.append(dict(raw_z_index=z, **qa))
        for i, block in enumerate((values, supports)):
            counts[i] += int(np.count_nonzero(block))
            # A storage axis transpose, not a rotation or spatial interpolation.
            grids[i].copyFromArray(np.ascontiguousarray(block.transpose(2, 1, 0)),
                                   ijk=(0, 0, first), tolerance=0.0)
        print(f"Prepared native layers {stop}/{raw.shape[0]}", flush=True)
    for grid, count in zip(grids, counts):
        if int(grid.activeVoxelCount()) != count:
            raise RuntimeError(f"Unexpected active voxel count in {grid.name}")
    if sha256(src["path"]) != src["sha256"]:
        raise RuntimeError("Source changed during preparation; output is not verified")
    out.mkdir(parents=True, exist_ok=True)
    vdb.write(str(files[2]), grids, metadata={"schema_version": 1,
              "spatial_resampling": False, "geometry_pruned": False})
    # Read back serialized grids independently; verify native positions explicitly.
    readback = [vdb.read(str(files[2]), name) for name in ("em_linear", "em_support")]
    if any(not np.allclose(g.transform.voxelSize(), [1, 1, 1]) for g in readback):
        raise RuntimeError("Unexpected serialized VDB transform")
    if any(int(g.activeVoxelCount()) != n for g, n in zip(readback, counts)):
        raise RuntimeError("Serialized active voxel counts differ from source-derived counts")
    access = [g.getConstAccessor() for g in readback]
    rng = np.random.default_rng(20261027)
    samples = [tuple(int(i) for i in row) for row in rng.integers([0, 0, 0], raw.shape,
                                                                             size=(sample_count, 3))]
    samples += [(z, y, x) for z in (0, raw.shape[0]-1) for y in (0, raw.shape[1]-1)
                for x in (0, raw.shape[2]-1)]
    last_z, expected = -1, None
    for z, y, x in sorted(samples):
        if z != last_z:
            linear, support, _ = display_layer(cfg, raw[z])
            expected, last_z = (linear, support), z
        for a, values in zip(access, expected):
            if a.getValue((x, y, z)) != float(values[y, x]):
                raise RuntimeError(f"Serialized VDB mismatch at ZYX {(z, y, x)}")
    source_unchanged = sha256(src["path"]) == src["sha256"]
    mesh_unchanged = mesh is None or sha256(mesh["path"]) == mesh["sha256"]
    if not source_unchanged or not mesh_unchanged:
        raise RuntimeError("An input changed; refusing verified manifest")
    files[2].replace(files[0])
    manifest = dict(schema_version=1, source=src, mesh=mesh,
        vdb=dict(path=str(files[0]), sha256=sha256(files[0]), grids=[g.name for g in grids],
                 transform="native_index_unit_voxel", grid_voxel_size=[1, 1, 1],
                 geometry_pruned=False, active_voxels=dict(zip((g.name for g in grids), counts))),
        transform=transform_metadata(cfg, raw.shape), display=cfg.get("display", {}),
        verification=dict(status="passed", source_sha256_before_after_equal=source_unchanged,
             mesh_sha256_before_after_equal=mesh_unchanged, source_data_modified=False,
             spatial_resampling=False, zero_semantics=cfg["source"]["zero_is_missing"],
             independent_serialized_readback_samples=len(samples),
             scope="All slices processed and active counts checked; values checked at sampled native coordinates, not every voxel.",
             elapsed_seconds=time.time()-start), layer_qa=layer_qa)
    write_json(files[1], manifest)
    print(f"Verified manifest: {files[1]}", flush=True)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--output", help="Prepared directory (default: output_dir/prepared)")
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    prepare(args.config, args.output, args.overwrite)


if __name__ == "__main__":
    main()
