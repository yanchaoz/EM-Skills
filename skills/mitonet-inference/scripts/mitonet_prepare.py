#!/usr/bin/env python3
"""Prepare a physically audited model-grid TIFF for MitoNet."""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path

import numpy as np


PIPELINE_PATH = Path(__file__).with_name("mitonet_pipeline.py")
SPEC = importlib.util.spec_from_file_location("mitonet_pipeline", PIPELINE_PATH)
pipeline = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(pipeline)


def load_volume(path: Path) -> np.ndarray:
    if path.suffix.lower() == ".npy":
        return np.load(path, mmap_mode="r")
    if path.suffix.lower() in {".tif", ".tiff"}:
        import tifffile
        return tifffile.imread(path)
    raise pipeline.SkillError("Bundled preparation supports local NPY and TIFF; use an external adapter for other formats")


def fit_shape(array: np.ndarray, shape: list[int]) -> np.ndarray:
    slices = tuple(slice(0, min(array.shape[i], shape[i])) for i in range(3))
    result = np.asarray(array[slices])
    padding = [(0, shape[i] - result.shape[i]) for i in range(3)]
    return np.pad(result, padding, mode="edge") if any(after for _, after in padding) else result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    args = parser.parse_args()
    config_path = args.config.resolve()
    config = pipeline.load_document(config_path)
    pipeline.audit_config(config, config_path)
    plan = pipeline.create_plan(config)
    source = pipeline.mapping(config, "source")
    source_path = pipeline.resolve_local(str(source["uri"]), config_path.parent)
    array = load_volume(source_path)
    axes = str(source["axis_order"]).lower()
    if array.ndim != 3:
        raise pipeline.SkillError(f"Expected a 3D source volume, got {array.shape}")
    array = np.transpose(array, [axes.index(axis) for axis in "zyx"])
    bbox = [int(value) for value in source.get("bbox_vox_zyx", [0, 0, 0, *array.shape])]
    selected = np.asarray(array[bbox[0]:bbox[3], bbox[1]:bbox[4], bbox[2]:bbox[5]])
    target_shape = [int(value) for value in plan["model_grid"]["shape_zyx"]]
    from scipy.ndimage import zoom
    factors = [target_shape[i] / selected.shape[i] for i in range(3)]
    prepared = fit_shape(zoom(selected.astype(np.float32), factors, order=1, mode="nearest", prefilter=False), target_shape)
    if np.issubdtype(array.dtype, np.integer):
        limits = np.iinfo(array.dtype)
        prepared = np.clip(np.rint(prepared), limits.min, limits.max).astype(array.dtype)
    root = pipeline.output_root(config, config_path)
    output = root / str(pipeline.mapping(config, "output").get("raw_model_grid_uri", "raw-model-grid.tif"))
    if output.exists() and not pipeline.mapping(config, "output").get("allow_overwrite", False):
        raise pipeline.SkillError(f"Refusing to overwrite {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    import tifffile
    tifffile.imwrite(output, prepared, metadata={"axes": "ZYX"})
    record = {
        "source": str(source_path), "output": str(output), "source_bbox_zyx": bbox,
        "source_shape_zyx": list(selected.shape), "model_shape_zyx": list(prepared.shape),
        "source_resolution_nm_zyx": source["resolution_nm_zyx"],
        "model_resolution_nm_zyx": pipeline.mapping(config, "model")["target_resolution_nm_zyx"],
        "interpolation": "linear intensity interpolation", "output_sha256": pipeline.sha256_file(output),
    }
    pipeline.write_json(root / "_mitonet_skill" / "preparation.json", record)
    print(json.dumps(record, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
