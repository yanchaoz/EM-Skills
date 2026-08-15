#!/usr/bin/env python3
"""Extract deterministic patch embeddings with the EMFoundation BASE encoder.

This adapter reproduces the model-loading and patch-normalization contract in
Figure2-Exps-UMAP/extract_encoder_umap.py without requiring UMAP.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import sys
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np


ADAPTER_VERSION = "0.2.0"


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def sha256(path: Path, block_size: int = 8 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(block_size), b""):
            digest.update(block)
    return digest.hexdigest()


def array_sha256(value: np.ndarray) -> str:
    array = np.ascontiguousarray(value)
    digest = hashlib.sha256()
    digest.update(str(array.dtype).encode())
    digest.update(json.dumps(list(array.shape)).encode())
    digest.update(memoryview(array).cast("B"))
    return digest.hexdigest()


def triplet(text: str) -> tuple[int, int, int]:
    values = tuple(int(v) for v in text.split(","))
    if len(values) != 3 or any(v <= 0 for v in values):
        raise argparse.ArgumentTypeError("expected three positive integers: z,y,x")
    return values


def float_triplet(text: str) -> tuple[float, float, float]:
    values = tuple(float(v) for v in text.split(","))
    if len(values) != 3 or any(v <= 0 for v in values):
        raise argparse.ArgumentTypeError("expected three positive numbers: z,y,x")
    return values


def grid_starts(length: int, patch: int, stride: int, boundary: str) -> list[int]:
    if length < patch:
        raise ValueError(f"axis length {length} is smaller than patch {patch}")
    starts = list(range(0, length - patch + 1, stride))
    if boundary == "align_end" and starts[-1] != length - patch:
        starts.append(length - patch)
    return starts


def normalize_patch(patch: np.ndarray) -> np.ndarray:
    patch = patch.astype(np.float32, copy=False)
    if float(patch.max()) > 255.0:
        raise ValueError("reference normalization only supports intensities <=255; configure a validated transform for this source")
    if float(patch.max()) > 1.5:
        patch = patch / 255.0
    mean = float(patch.mean())
    std = float(patch.std())
    return (patch - mean) / (std + 1e-6)


def load_volume(path: Path, axes: str) -> np.ndarray:
    import tifffile

    volume = tifffile.imread(path)
    if volume.ndim != 3:
        raise ValueError(f"expected a 3D TIFF, got shape={volume.shape}")
    axes = axes.lower()
    if sorted(axes) != ["x", "y", "z"]:
        raise ValueError("--input-axes must be a permutation of zyx")
    if axes != "zyx":
        volume = np.transpose(volume, tuple(axes.index(axis) for axis in "zyx"))
    return volume


def build_model(pretrain_dir: Path, checkpoint: Path, device: str) -> tuple[Any, dict[str, Any]]:
    import torch

    sys.path.insert(0, str(pretrain_dir))
    from PNIv2_head import UNet_PNI

    model = UNet_PNI(num_features=[32, 64, 128, 256, 512])
    saved = torch.load(checkpoint, map_location="cpu")
    if not isinstance(saved, dict) or "model_weights" not in saved:
        raise ValueError("checkpoint must contain model_weights")
    pretrained = saved["model_weights"]
    raw_encoder = OrderedDict()
    for old_key, value in pretrained.items():
        if "encoder" in old_key:
            raw_encoder[old_key.split("sp_cnn.")[-1]] = value

    model_state = model.state_dict()
    compatible = OrderedDict(
        (key, value)
        for key, value in raw_encoder.items()
        if key in model_state and tuple(model_state[key].shape) == tuple(value.shape)
    )
    result = model.load_state_dict(compatible, strict=False)
    if not compatible:
        raise ValueError("no compatible encoder weights matched the PNIv2 model")
    report = {
        "checkpoint_model_weight_keys": len(pretrained),
        "raw_encoder_weight_keys": len(raw_encoder),
        "matched_encoder_weight_keys": len(compatible),
        "missing_key_count": len(result.missing_keys),
        "unexpected_key_count": len(result.unexpected_keys),
        "matched_keys": list(compatible),
    }
    model = model.to(torch.device(device))
    model.eval()
    return model, report


def extract(
    model: Any,
    volume: np.ndarray,
    patch_size: tuple[int, int, int],
    stride: tuple[int, int, int],
    boundary: str,
    batch_size: int,
    device: str,
) -> tuple[np.ndarray, np.ndarray]:
    import torch

    starts = [grid_starts(volume.shape[i], patch_size[i], stride[i], boundary) for i in range(3)]
    positions = np.asarray([(z, y, x) for z in starts[0] for y in starts[1] for x in starts[2]], dtype=np.int32)
    chunks: list[np.ndarray] = []
    with torch.inference_mode():
        for first in range(0, len(positions), batch_size):
            batch_positions = positions[first : first + batch_size]
            batch = []
            for z, y, x in batch_positions:
                patch = volume[z : z + patch_size[0], y : y + patch_size[1], x : x + patch_size[2]]
                if patch.shape != patch_size:
                    raise RuntimeError(f"internal patch geometry mismatch at {(int(z), int(y), int(x))}: {patch.shape}")
                batch.append(normalize_patch(patch)[None, None])
            tensor = torch.from_numpy(np.concatenate(batch, axis=0)).to(device)
            _, pooled = model(tensor, hierarchical=True)
            chunks.append(pooled.detach().cpu().numpy().astype(np.float32, copy=False))
    embeddings = np.concatenate(chunks, axis=0)
    if embeddings.shape[0] != positions.shape[0] or embeddings.ndim != 2:
        raise RuntimeError(f"unexpected embedding shape {embeddings.shape} for {positions.shape[0]} positions")
    if embeddings.shape[1] != 512:
        raise RuntimeError(f"expected 512-dimensional BASE embeddings, got {embeddings.shape[1]}")
    if not np.isfinite(embeddings).all():
        raise RuntimeError("embeddings contain NaN or Inf")
    return embeddings, positions


def generated_config(
    args: argparse.Namespace,
    volume: np.ndarray,
    checkpoint_hash: str,
    source_hash: str,
) -> dict[str, Any]:
    windows = [list(value) for value in args.candidate_window]
    derived = [
        [args.patch_size[i] + args.stride[i] * (window[i] - 1) for i in range(3)]
        for window in windows
    ]
    default_budget = args.annotation_budget_voxels
    if default_budget is None:
        default_budget = args.max_subvolumes * max(np.prod(shape) for shape in derived)
    return {
        "project": {"id": args.project_id, "purpose": "Embedding-guided variable-size EM subvolume annotation planning"},
        "source": {
            "uri": str(args.input.resolve()),
            "axes": "zyx",
            "shape_zyx": list(volume.shape),
            "voxel_size_nm_zyx": list(args.voxel_size_nm),
            "dtype": str(volume.dtype),
            "source_sha256": source_hash,
        },
        "embedding": {
            "model_repository": str(args.pretrain_dir.resolve()),
            "model_commit": args.model_revision,
            "checkpoint_name": str(args.checkpoint.resolve()),
            "checkpoint_sha256": checkpoint_hash,
            "dimension": 512,
            "normalization": "if max>1.5 divide by 255, then per-patch z-score (Figure2-Exps-UMAP reference)",
        },
        "tiling": {
            "patch_shape_zyx": list(args.patch_size),
            "stride_zyx": list(args.stride),
            "boundary_mode": args.boundary,
        },
        "selection": {
            "max_subvolumes": args.max_subvolumes,
            "annotation_budget_voxels": int(default_budget),
            "candidate_windows_patches_zyx": windows,
            "expected_subvolume_shapes_zyx": derived,
            "k_neighbors": args.k_neighbors,
            "metric": args.metric,
            "cost_exponent": args.cost_exponent,
            "disallow_patch_overlap": True,
            "max_exact_patches": args.max_exact_patches,
            "max_working_memory_mib": args.max_working_memory_mib,
        },
        "guards": {"excluded_bboxes_zyx": [], "holdout_bboxes_zyx": []},
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--input-axes", default="zyx")
    parser.add_argument("--pretrain-dir", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--project-id", default="emfoundation-annotation-plan")
    parser.add_argument("--model-revision", default="local-Figure2-reference")
    parser.add_argument("--patch-size", type=triplet, default=(32, 128, 128))
    parser.add_argument("--stride", type=triplet, default=(16, 64, 64))
    parser.add_argument("--boundary", choices=("valid", "align_end"), default="align_end")
    parser.add_argument("--voxel-size-nm", type=float_triplet, required=True)
    parser.add_argument("--candidate-window", action="append", type=triplet, default=None)
    parser.add_argument("--max-subvolumes", type=int, default=6)
    parser.add_argument("--annotation-budget-voxels", type=int)
    parser.add_argument("--k-neighbors", type=int, default=30)
    parser.add_argument("--metric", choices=("euclidean", "cosine"), default="euclidean")
    parser.add_argument("--cost-exponent", type=float, default=0.75)
    parser.add_argument("--max-exact-patches", type=int, default=20000)
    parser.add_argument("--max-working-memory-mib", type=int, default=512)
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--device", default="cuda:0")
    args = parser.parse_args()
    if args.candidate_window is None:
        args.candidate_window = [(1, 3, 3), (1, 5, 5), (2, 3, 3), (2, 5, 5)]
    if args.max_subvolumes <= 0 or args.batch_size <= 0:
        parser.error("--max-subvolumes and --batch-size must be positive")
    return args


def main() -> int:
    args = parse_args()
    try:
        import torch
        import tifffile

        if not args.input.is_file():
            raise FileNotFoundError(f"input TIFF is not readable: {args.input}")
        if not args.checkpoint.is_file():
            raise FileNotFoundError(f"checkpoint is not readable: {args.checkpoint}")
        if args.device.startswith("cuda") and not torch.cuda.is_available():
            raise RuntimeError(f"requested {args.device}, but CUDA is unavailable")
        args.out_dir.mkdir(parents=True, exist_ok=True)
        volume = load_volume(args.input, args.input_axes)
        source_hash = sha256(args.input)
        checkpoint_hash = sha256(args.checkpoint)
        model, load_report = build_model(args.pretrain_dir, args.checkpoint, args.device)
        embeddings, positions = extract(
            model, volume, args.patch_size, args.stride, args.boundary, args.batch_size, args.device
        )
        np.save(args.out_dir / "embeddings.npy", embeddings)
        np.save(args.out_dir / "positions_zyx.npy", positions)
        config = generated_config(args, volume, checkpoint_hash, source_hash)
        (args.out_dir / "project.json").write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
        report = {
            "status": "PASS",
            "adapter_version": ADAPTER_VERSION,
            "created_at": utc_now(),
            "input": str(args.input.resolve()),
            "input_sha256": source_hash,
            "input_shape_zyx": list(volume.shape),
            "input_dtype": str(volume.dtype),
            "checkpoint": str(args.checkpoint.resolve()),
            "checkpoint_sha256": checkpoint_hash,
            "pretrain_dir": str(args.pretrain_dir.resolve()),
            "device": args.device,
            "gpu": torch.cuda.get_device_name(torch.device(args.device)) if args.device.startswith("cuda") else None,
            "python": sys.version,
            "platform": platform.platform(),
            "torch": torch.__version__,
            "numpy": np.__version__,
            "tifffile": tifffile.__version__,
            "patch_size_zyx": list(args.patch_size),
            "stride_zyx": list(args.stride),
            "boundary": args.boundary,
            "embedding_shape": list(embeddings.shape),
            "embedding_sha256": array_sha256(embeddings),
            "positions_sha256": array_sha256(positions),
            "model_load_report": load_report,
            "outputs": ["embeddings.npy", "positions_zyx.npy", "project.json", "embedding_run.json"],
        }
        (args.out_dir / "embedding_run.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report, indent=2))
        return 0
    except Exception as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
