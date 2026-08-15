#!/usr/bin/env python3
"""Auditable coverage-guided annotation suggestions for volume EM.

This is a clean, dependency-light implementation of the coverage objective
described by Zhang et al. It intentionally separates selection from human
review and does not create labels.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import numpy as np


SCHEMA_VERSION = "2.0"
TOOL_VERSION = "0.2.0"


class AdviceError(ValueError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def file_sha256(path: Path, block_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            block = handle.read(block_size)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def json_sha256(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def load_config(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json":
        value = json.loads(text)
    else:
        try:
            import yaml  # type: ignore
        except ImportError as exc:
            raise AdviceError("YAML config requires PyYAML; use JSON or install PyYAML in the execution environment") from exc
        value = yaml.safe_load(text)
    if not isinstance(value, dict):
        raise AdviceError("config root must be an object")
    return value


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _triplet(value: Any, field: str, cast: type = int) -> list[Any]:
    if not isinstance(value, list) or len(value) != 3:
        raise AdviceError(f"{field} must be a three-element [z, y, x] list")
    try:
        result = [cast(v) for v in value]
    except (TypeError, ValueError) as exc:
        raise AdviceError(f"{field} contains an invalid value") from exc
    if any(v <= 0 for v in result):
        raise AdviceError(f"{field} values must be positive")
    return result


def _bbox(value: Any, field: str) -> list[list[int]]:
    if not isinstance(value, list) or len(value) != 2:
        raise AdviceError(f"{field} must be [[z0,y0,x0],[z1,y1,x1]]")
    if not isinstance(value[0], list) or len(value[0]) != 3:
        raise AdviceError(f"{field}[0] must be a three-element [z, y, x] list")
    try:
        start = [int(v) for v in value[0]]
    except (TypeError, ValueError) as exc:
        raise AdviceError(f"{field}[0] contains an invalid value") from exc
    if any(v < 0 for v in start):
        raise AdviceError(f"{field}[0] values must be non-negative")
    stop = _triplet(value[1], field + "[1]")
    if any(a >= b for a, b in zip(start, stop)):
        raise AdviceError(f"{field} must have start < stop on every axis")
    return [start, stop]


def bbox_intersects(a: list[list[int]], b: list[list[int]]) -> bool:
    return all(a[0][i] < b[1][i] and b[0][i] < a[1][i] for i in range(3))


def bbox_physical_nm(bbox: list[list[int]], voxel_nm: list[float]) -> list[list[float]]:
    return [[round(bbox[j][i] * voxel_nm[i], 6) for i in range(3)] for j in range(2)]


def validate_config(cfg: dict[str, Any]) -> dict[str, Any]:
    required_sections = ("project", "source", "embedding", "tiling", "selection")
    for section in required_sections:
        if not isinstance(cfg.get(section), dict):
            raise AdviceError(f"missing object section: {section}")

    source = cfg["source"]
    if source.get("axes") != "zyx":
        raise AdviceError("source.axes must be explicitly 'zyx'; reorder the data before embedding if necessary")
    shape = _triplet(source.get("shape_zyx"), "source.shape_zyx")
    voxel_nm = _triplet(source.get("voxel_size_nm_zyx"), "source.voxel_size_nm_zyx", float)
    if not source.get("uri"):
        raise AdviceError("source.uri is required")

    tiling = cfg["tiling"]
    patch = _triplet(tiling.get("patch_shape_zyx"), "tiling.patch_shape_zyx")
    stride = _triplet(tiling.get("stride_zyx"), "tiling.stride_zyx")
    boundary = tiling.get("boundary_mode", "valid")
    if boundary not in {"valid", "align_end", "reflect"}:
        raise AdviceError("tiling.boundary_mode must be valid, align_end, or reflect")
    if boundary == "valid" and any(p > s for p, s in zip(patch, shape)):
        raise AdviceError("patch shape exceeds source shape under valid boundary mode")

    embedding = cfg["embedding"]
    dimension = int(embedding.get("dimension", 0))
    if dimension <= 0:
        raise AdviceError("embedding.dimension must be positive")
    for key in ("model_repository", "model_commit", "checkpoint_sha256"):
        if not embedding.get(key):
            raise AdviceError(f"embedding.{key} is required for provenance")
    checkpoint_hash = str(embedding["checkpoint_sha256"]).lower()
    if len(checkpoint_hash) != 64 or any(ch not in "0123456789abcdef" for ch in checkpoint_hash):
        raise AdviceError("embedding.checkpoint_sha256 must be a 64-character hexadecimal SHA-256")

    selection = cfg["selection"]
    raw_windows = selection.get("candidate_windows_patches_zyx")
    if raw_windows is None:
        legacy = selection.get("window_patches_zyx")
        raw_windows = [legacy] if legacy is not None else None
    if not isinstance(raw_windows, list) or not raw_windows:
        raise AdviceError("selection.candidate_windows_patches_zyx must be a non-empty list of [z,y,x] windows")
    windows = [_triplet(value, f"selection.candidate_windows_patches_zyx[{i}]") for i, value in enumerate(raw_windows)]
    if len({tuple(v) for v in windows}) != len(windows):
        raise AdviceError("selection.candidate_windows_patches_zyx contains duplicates")
    max_items = int(selection.get("max_subvolumes", selection.get("budget_subvolumes", 0)))
    budget_voxels = int(selection.get("annotation_budget_voxels", 0))
    k = int(selection.get("k_neighbors", 0))
    if max_items <= 0:
        raise AdviceError("selection.max_subvolumes must be positive")
    if budget_voxels <= 0:
        legacy_budget = int(selection.get("budget_subvolumes", 0))
        if legacy_budget > 0 and len(windows) == 1:
            derived = [patch[i] + stride[i] * (windows[0][i] - 1) for i in range(3)]
            budget_voxels = legacy_budget * math.prod(derived)
        else:
            raise AdviceError("selection.annotation_budget_voxels must be positive for variable-size selection")
    if k <= 0:
        raise AdviceError("selection.k_neighbors must be positive")
    if selection.get("metric", "euclidean") not in {"euclidean", "cosine"}:
        raise AdviceError("selection.metric must be euclidean or cosine")
    cost_exponent = float(selection.get("cost_exponent", 1.0))
    if not 0.0 <= cost_exponent <= 1.0:
        raise AdviceError("selection.cost_exponent must be between 0 and 1")

    derived_shapes = [[patch[i] + stride[i] * (window[i] - 1) for i in range(3)] for window in windows]
    expected = selection.get("expected_subvolume_shapes_zyx")
    if expected is not None:
        if not isinstance(expected, list) or len(expected) != len(derived_shapes):
            raise AdviceError("selection.expected_subvolume_shapes_zyx must match the candidate-window list length")
        checked = [_triplet(value, f"selection.expected_subvolume_shapes_zyx[{i}]") for i, value in enumerate(expected)]
        if checked != derived_shapes:
            raise AdviceError(f"expected_subvolume_shapes_zyx={checked} differs from derived={derived_shapes}")

    excluded = [_bbox(v, f"guards.excluded_bboxes_zyx[{i}]") for i, v in enumerate(cfg.get("guards", {}).get("excluded_bboxes_zyx", []))]
    holdouts = [_bbox(v, f"guards.holdout_bboxes_zyx[{i}]") for i, v in enumerate(cfg.get("guards", {}).get("holdout_bboxes_zyx", []))]
    full = [[0, 0, 0], shape]
    for kind, boxes in (("excluded", excluded), ("holdout", holdouts)):
        for box in boxes:
            if any(box[0][i] < 0 or box[1][i] > shape[i] for i in range(3)):
                raise AdviceError(f"{kind} bbox {box} lies outside source bounds {full}")

    return {
        "shape": shape,
        "voxel_nm": voxel_nm,
        "patch": patch,
        "stride": stride,
        "boundary": boundary,
        "windows": windows,
        "derived_shapes": derived_shapes,
        "derived_nm": [[round(shape[i] * voxel_nm[i], 6) for i in range(3)] for shape in derived_shapes],
        "budget_voxels": budget_voxels,
        "max_items": max_items,
        "cost_exponent": cost_exponent,
        "k": k,
        "excluded": excluded,
        "holdouts": holdouts,
    }


def axis_starts(size: int, patch: int, stride: int, boundary: str) -> list[int]:
    if boundary == "reflect":
        count = math.ceil((size - patch) / stride) + 1 if size > patch else 1
        return [i * stride for i in range(count)]
    if size < patch:
        return []
    starts = list(range(0, size - patch + 1, stride))
    if boundary == "align_end" and starts[-1] != size - patch:
        starts.append(size - patch)
    return starts


def build_manifest(cfg: dict[str, Any], config_path: Path | None = None) -> dict[str, Any]:
    audit = validate_config(cfg)
    starts = [
        axis_starts(audit["shape"][i], audit["patch"][i], audit["stride"][i], audit["boundary"])
        for i in range(3)
    ]
    grid_shape = [len(v) for v in starts]
    for window in audit["windows"]:
        if any(grid_shape[i] < window[i] for i in range(3)):
            raise AdviceError(f"candidate window {window} exceeds patch grid {grid_shape}")

    patches: list[dict[str, Any]] = []
    grid_to_patch: dict[tuple[int, int, int], int] = {}
    for gz, z in enumerate(starts[0]):
        for gy, y in enumerate(starts[1]):
            for gx, x in enumerate(starts[2]):
                pid = len(patches)
                grid_to_patch[(gz, gy, gx)] = pid
                stop = [min(z + audit["patch"][0], audit["shape"][0]), min(y + audit["patch"][1], audit["shape"][1]), min(x + audit["patch"][2], audit["shape"][2])]
                box = [[z, y, x], stop]
                patches.append({
                    "patch_id": pid,
                    "grid_zyx": [gz, gy, gx],
                    "bbox_zyx": box,
                    "bbox_nm_zyx": bbox_physical_nm(box, audit["voxel_nm"]),
                })

    candidates: list[dict[str, Any]] = []
    rejected_guard_count = 0
    counts_by_size: dict[str, int] = {}
    for size_index, (window, derived_shape) in enumerate(zip(audit["windows"], audit["derived_shapes"])):
        wz, wy, wx = window
        size_id = f"s{size_index:02d}-{wz}x{wy}x{wx}"
        counts_by_size[size_id] = 0
        for gz in range(grid_shape[0] - wz + 1):
            for gy in range(grid_shape[1] - wy + 1):
                for gx in range(grid_shape[2] - wx + 1):
                    patch_ids = [
                        grid_to_patch[(iz, iy, ix)]
                        for iz in range(gz, gz + wz)
                        for iy in range(gy, gy + wy)
                        for ix in range(gx, gx + wx)
                    ]
                    first = patches[patch_ids[0]]["bbox_zyx"][0]
                    last = patches[patch_ids[-1]]["bbox_zyx"][1]
                    box = [first, last]
                    if any(bbox_intersects(box, guard) for guard in audit["excluded"] + audit["holdouts"]):
                        rejected_guard_count += 1
                        continue
                    cid = f"sv-{size_id}-{gz:04d}-{gy:04d}-{gx:04d}"
                    cost_voxels = math.prod(last[i] - first[i] for i in range(3))
                    candidates.append({
                        "candidate_id": cid,
                        "size_id": size_id,
                        "window_patches_zyx": window,
                        "derived_shape_zyx": derived_shape,
                        "grid_start_zyx": [gz, gy, gx],
                        "patch_ids": patch_ids,
                        "bbox_zyx": box,
                        "bbox_nm_zyx": bbox_physical_nm(box, audit["voxel_nm"]),
                        "annotation_cost_voxels": cost_voxels,
                    })
                    counts_by_size[size_id] += 1

    if not candidates:
        raise AdviceError("no eligible candidates remain after guards")
    min_cost = min(row["annotation_cost_voxels"] for row in candidates)
    if min_cost > audit["budget_voxels"]:
        raise AdviceError(f"annotation budget {audit['budget_voxels']} voxels is below the smallest candidate cost {min_cost}")

    warnings: list[str] = []
    if audit["boundary"] == "reflect":
        warnings.append("reflect mode requires embeddings from the same reflected patch grid; clipped boxes do not imply unpadded inference")
    if len(audit["windows"]) == 1:
        warnings.append("only one candidate window is configured; selection is fixed-size rather than variable-size")

    return {
        "schema_version": SCHEMA_VERSION,
        "tool_version": TOOL_VERSION,
        "created_at": utc_now(),
        "kind": "em_annotation_candidate_manifest",
        "project_id": cfg["project"].get("id"),
        "source": cfg["source"],
        "embedding_provenance": cfg["embedding"],
        "config_sha256": file_sha256(config_path) if config_path else json_sha256(cfg),
        "axes": "zyx",
        "patch_grid_shape_zyx": grid_shape,
        "patch_count": len(patches),
        "candidate_count": len(candidates),
        "guard_rejected_candidate_count": rejected_guard_count,
        "candidate_windows_patches_zyx": audit["windows"],
        "derived_subvolume_shapes_zyx": audit["derived_shapes"],
        "derived_subvolume_sizes_nm_zyx": audit["derived_nm"],
        "candidate_count_by_size": counts_by_size,
        "annotation_budget_voxels": audit["budget_voxels"],
        "patches": patches,
        "candidates": candidates,
        "warnings": warnings,
    }


def exact_knn(embeddings: np.ndarray, k: int, metric: str, max_working_mib: int) -> np.ndarray:
    n = embeddings.shape[0]
    if k > n:
        raise AdviceError(f"k_neighbors={k} exceeds patch count={n}")
    x = embeddings.astype(np.float32, copy=False)
    if metric == "cosine":
        norms = np.linalg.norm(x, axis=1, keepdims=True)
        if np.any(norms == 0):
            raise AdviceError("cosine metric cannot be used with zero-norm embeddings")
        x = x / norms
    bytes_per_row = max(1, n * np.dtype(np.float32).itemsize)
    block = max(1, min(n, (max_working_mib * 1024 * 1024) // bytes_per_row))
    neighbors = np.empty((n, k), dtype=np.int64)
    x_norm = np.sum(x * x, axis=1)
    for start in range(0, n, block):
        stop = min(n, start + block)
        q = x[start:stop]
        if metric == "euclidean":
            distances = np.sum(q * q, axis=1, keepdims=True) + x_norm[None, :] - 2.0 * (q @ x.T)
            np.maximum(distances, 0.0, out=distances)
        else:
            distances = 1.0 - q @ x.T
        local = np.argpartition(distances, kth=k - 1, axis=1)[:, :k]
        local_dist = np.take_along_axis(distances, local, axis=1)
        order = np.argsort(local_dist, axis=1, kind="stable")
        neighbors[start:stop] = np.take_along_axis(local, order, axis=1)
    return neighbors


def _candidate_patch_set(candidate: dict[str, Any]) -> set[int]:
    return set(int(v) for v in candidate["patch_ids"])


def select_candidates(
    cfg: dict[str, Any],
    manifest: dict[str, Any],
    embeddings_path: Path,
    positions_path: Path | None = None,
) -> dict[str, Any]:
    audit = validate_config(cfg)
    embeddings = np.load(embeddings_path, allow_pickle=False)
    if embeddings.ndim != 2:
        raise AdviceError("embeddings must be a 2D [patch, dimension] NumPy array")
    if embeddings.shape[0] != manifest.get("patch_count"):
        raise AdviceError(f"embedding rows {embeddings.shape[0]} != manifest patch_count {manifest.get('patch_count')}")
    if embeddings.shape[1] != int(cfg["embedding"]["dimension"]):
        raise AdviceError(f"embedding dimension {embeddings.shape[1]} != configured {cfg['embedding']['dimension']}")
    if not np.isfinite(embeddings).all():
        raise AdviceError("embeddings contain NaN or Inf")
    positions_hash = None
    if positions_path is not None:
        positions = np.load(positions_path, allow_pickle=False)
        expected = np.asarray([row["bbox_zyx"][0] for row in manifest["patches"]], dtype=np.int64)
        if positions.shape != expected.shape or not np.array_equal(positions.astype(np.int64, copy=False), expected):
            raise AdviceError("positions_zyx does not exactly match manifest patch order")
        positions_hash = file_sha256(positions_path)

    limit = int(cfg["selection"].get("max_exact_patches", 20000))
    if embeddings.shape[0] > limit:
        raise AdviceError(
            f"exact KNN stopped at {embeddings.shape[0]} patches (max_exact_patches={limit}); "
            "raise the limit explicitly or use a validated ANN adapter"
        )
    memory_mib = int(cfg["selection"].get("max_working_memory_mib", 512))
    neighbors = exact_knn(embeddings, audit["k"], cfg["selection"].get("metric", "euclidean"), memory_mib)

    candidates = manifest["candidates"]
    patch_sets = [_candidate_patch_set(c) for c in candidates]
    candidate_cover_ids = [
        np.unique(neighbors[np.asarray(candidate["patch_ids"], dtype=np.int64)].reshape(-1))
        for candidate in candidates
    ]
    selected_indices: list[int] = []
    selected_patches: set[int] = set()
    covered = np.zeros(embeddings.shape[0], dtype=bool)
    curve: list[dict[str, Any]] = []
    selected_records: list[dict[str, Any]] = []
    disallow_overlap = bool(cfg["selection"].get("disallow_patch_overlap", True))
    consumed_voxels = 0

    for rank in range(1, audit["max_items"] + 1):
        best_idx: int | None = None
        best_key: tuple[float, int, int] | None = None
        best_gain = 0
        best_cover_ids: np.ndarray | None = None
        for idx, candidate in enumerate(candidates):
            if idx in selected_indices:
                continue
            if disallow_overlap and patch_sets[idx] & selected_patches:
                continue
            cost = int(candidate["annotation_cost_voxels"])
            if consumed_voxels + cost > audit["budget_voxels"]:
                continue
            candidate_neighbors = candidate_cover_ids[idx]
            gain = int(np.count_nonzero(~covered[candidate_neighbors]))
            if gain <= 0:
                continue
            score = gain / (cost ** audit["cost_exponent"])
            key = (score, gain, -cost)
            if best_key is None or key > best_key:
                best_idx = idx
                best_key = key
                best_gain = gain
                best_cover_ids = candidate_neighbors
        if best_idx is None or best_cover_ids is None:
            break
        selected_indices.append(best_idx)
        selected_patches.update(patch_sets[best_idx])
        covered[best_cover_ids] = True
        record = dict(candidates[best_idx])
        consumed_voxels += int(record["annotation_cost_voxels"])
        record.update({
            "rank": rank,
            "newly_covered_patch_count": best_gain,
            "marginal_coverage_per_cost": round(float(best_key[0]), 12),
            "cumulative_annotation_cost_voxels": consumed_voxels,
            "remaining_annotation_budget_voxels": audit["budget_voxels"] - consumed_voxels,
            "cumulative_covered_patch_count": int(covered.sum()),
            "cumulative_coverage_rate": round(float(covered.mean()), 8),
            "review_status": "pending",
        })
        selected_records.append(record)
        curve.append({
            "rank": rank,
            "candidate_id": record["candidate_id"],
            "newly_covered_patch_count": best_gain,
            "selected_shape_zyx": record["derived_shape_zyx"],
            "annotation_cost_voxels": record["annotation_cost_voxels"],
            "cumulative_annotation_cost_voxels": consumed_voxels,
            "covered_patch_count": int(covered.sum()),
            "coverage_rate": round(float(covered.mean()), 8),
        })

    if not selected_records:
        raise AdviceError("no candidate could be selected within the annotation budget and overlap constraints")

    return {
        "schema_version": SCHEMA_VERSION,
        "tool_version": TOOL_VERSION,
        "created_at": utc_now(),
        "kind": "em_annotation_suggestion_draft",
        "status": "DRAFT_REQUIRES_HUMAN_REVIEW",
        "project_id": manifest.get("project_id"),
        "source": manifest.get("source"),
        "embedding_provenance": manifest.get("embedding_provenance"),
        "config_sha256": manifest.get("config_sha256"),
        "candidate_manifest_sha256": json_sha256(manifest),
        "embedding_file": str(embeddings_path.resolve()),
        "embedding_sha256": file_sha256(embeddings_path),
        "positions_file": str(positions_path.resolve()) if positions_path else None,
        "positions_sha256": positions_hash,
        "method": {
            "name": "multi-scale budgeted coverage greedy selection",
            "paper_name": "CCR-inspired budgeted maximum coverage",
            "metric": cfg["selection"].get("metric", "euclidean"),
            "k_neighbors_including_self": audit["k"],
            "exact_knn": True,
            "cost_exponent": audit["cost_exponent"],
            "objective": "marginal newly covered patches / annotation_cost_voxels^cost_exponent",
            "tie_break": "score, gain, lower cost, stable manifest order",
            "disallow_patch_overlap": disallow_overlap,
        },
        "annotation_budget_voxels": audit["budget_voxels"],
        "annotation_cost_voxels": consumed_voxels,
        "remaining_annotation_budget_voxels": audit["budget_voxels"] - consumed_voxels,
        "patch_count": manifest["patch_count"],
        "candidate_count": manifest["candidate_count"],
        "selected_subvolumes": selected_records,
        "selected_patch_ids": sorted(selected_patches),
        "covered_patch_ids": np.flatnonzero(covered).astype(int).tolist(),
        "coverage_curve": curve,
        "warnings": list(manifest.get("warnings", [])) + [
            "coverage is representativeness in the chosen embedding, not uncertainty, biological correctness, or label quality",
            "all suggestions require raw-volume inspection and explicit human review",
        ],
    }


def finalize(draft: dict[str, Any], decisions: dict[str, Any]) -> dict[str, Any]:
    if draft.get("status") != "DRAFT_REQUIRES_HUMAN_REVIEW":
        raise AdviceError("input is not a reviewable draft")
    reviewer = str(decisions.get("reviewer", "")).strip()
    reviewed_at = str(decisions.get("reviewed_at", "")).strip()
    if not reviewer or not reviewed_at:
        raise AdviceError("decisions require reviewer and reviewed_at")
    rows = decisions.get("decisions")
    if not isinstance(rows, list):
        raise AdviceError("decisions.decisions must be a list")
    by_id: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict) or row.get("decision") not in {"accept", "reject"}:
            raise AdviceError("every decision must be an object with decision=accept or reject")
        cid = str(row.get("candidate_id", ""))
        if not cid or cid in by_id:
            raise AdviceError("candidate_id is missing or duplicated in decisions")
        if row["decision"] == "reject" and not str(row.get("reason", "")).strip():
            raise AdviceError(f"rejected candidate {cid} requires a reason")
        by_id[cid] = row
    proposed = {row["candidate_id"] for row in draft["selected_subvolumes"]}
    if set(by_id) != proposed:
        missing = sorted(proposed - set(by_id))
        extra = sorted(set(by_id) - proposed)
        raise AdviceError(f"review must cover every proposal exactly; missing={missing}, extra={extra}")

    accepted, rejected = [], []
    for proposal in draft["selected_subvolumes"]:
        decision = by_id[proposal["candidate_id"]]
        row = dict(proposal)
        row["review_status"] = decision["decision"]
        row["review_reason"] = decision.get("reason", "")
        (accepted if decision["decision"] == "accept" else rejected).append(row)
    return {
        "schema_version": SCHEMA_VERSION,
        "tool_version": TOOL_VERSION,
        "created_at": utc_now(),
        "kind": "em_annotation_final_queue",
        "status": "FINAL_HUMAN_REVIEWED",
        "project_id": draft.get("project_id"),
        "source": draft.get("source"),
        "embedding_provenance": draft.get("embedding_provenance"),
        "draft_sha256": json_sha256(draft),
        "review": {"reviewer": reviewer, "reviewed_at": reviewed_at, "notes": decisions.get("notes", "")},
        "accepted_subvolumes": accepted,
        "rejected_subvolumes": rejected,
        "accepted_count": len(accepted),
        "rejected_count": len(rejected),
        "warning": "accepted entries are annotation targets, not ground-truth labels",
    }


def audit_report(cfg: dict[str, Any]) -> dict[str, Any]:
    audit = validate_config(cfg)
    starts = [axis_starts(audit["shape"][i], audit["patch"][i], audit["stride"][i], audit["boundary"]) for i in range(3)]
    grid = [len(s) for s in starts]
    patch_count = math.prod(grid)
    candidate_grids = [[grid[i] - window[i] + 1 for i in range(3)] for window in audit["windows"]]
    counts = [math.prod(candidate_grid) if all(v > 0 for v in candidate_grid) else 0 for candidate_grid in candidate_grids]
    return {
        "status": "PASS",
        "axes": "zyx",
        "source_shape_zyx": audit["shape"],
        "voxel_size_nm_zyx": audit["voxel_nm"],
        "patch_grid_shape_zyx": grid,
        "patch_count": patch_count,
        "candidate_windows_patches_zyx": audit["windows"],
        "candidate_grid_shapes_zyx": candidate_grids,
        "candidate_count_before_guards_by_size": counts,
        "candidate_count_before_guards": sum(counts),
        "derived_subvolume_shapes_zyx": audit["derived_shapes"],
        "derived_subvolume_sizes_nm_zyx": audit["derived_nm"],
        "estimated_dense_pairwise_gib_float32": round(patch_count * patch_count * 4 / 1024**3, 4),
        "exact_knn_time_complexity": "O(N^2)",
        "annotation_budget_voxels": audit["budget_voxels"],
        "max_subvolumes": audit["max_items"],
        "cost_exponent": audit["cost_exponent"],
        "k_neighbors_including_self": audit["k"],
        "holdout_box_count": len(audit["holdouts"]),
        "excluded_box_count": len(audit["excluded"]),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    audit_p = sub.add_parser("audit", help="validate config and print scale/geometry audit")
    audit_p.add_argument("--config", type=Path, required=True)
    audit_p.add_argument("--out", type=Path)
    plan_p = sub.add_parser("plan", help="create deterministic patch and candidate manifest")
    plan_p.add_argument("--config", type=Path, required=True)
    plan_p.add_argument("--out", type=Path, required=True)
    select_p = sub.add_parser("select", help="run exact coverage-guided selection")
    select_p.add_argument("--config", type=Path, required=True)
    select_p.add_argument("--manifest", type=Path, required=True)
    select_p.add_argument("--embeddings", type=Path, required=True)
    select_p.add_argument("--positions", type=Path, help="optional positions_zyx.npy; exact row-order verification is strongly recommended")
    select_p.add_argument("--out", type=Path, required=True)
    final_p = sub.add_parser("finalize", help="apply complete human review decisions")
    final_p.add_argument("--draft", type=Path, required=True)
    final_p.add_argument("--decisions", type=Path, required=True)
    final_p.add_argument("--out", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        if args.command == "audit":
            report = audit_report(load_config(args.config))
            if args.out:
                write_json(args.out, report)
            print(json.dumps(report, indent=2, ensure_ascii=False))
        elif args.command == "plan":
            manifest = build_manifest(load_config(args.config), args.config)
            write_json(args.out, manifest)
            print(f"wrote {manifest['patch_count']} patches and {manifest['candidate_count']} eligible candidates to {args.out}")
        elif args.command == "select":
            cfg = load_config(args.config)
            manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
            draft = select_candidates(cfg, manifest, args.embeddings, args.positions)
            write_json(args.out, draft)
            print(f"wrote {len(draft['selected_subvolumes'])} review-required suggestions to {args.out}")
        elif args.command == "finalize":
            draft = json.loads(args.draft.read_text(encoding="utf-8"))
            decisions = json.loads(args.decisions.read_text(encoding="utf-8"))
            result = finalize(draft, decisions)
            write_json(args.out, result)
            print(f"wrote {result['accepted_count']} accepted annotation targets to {args.out}")
        return 0
    except (AdviceError, OSError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
