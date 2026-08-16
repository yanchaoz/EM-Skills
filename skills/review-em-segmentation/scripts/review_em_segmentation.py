#!/usr/bin/env python3
"""Deterministic integrity, metric, and visual review for EM segmentations."""

from __future__ import annotations

import argparse
import colorsys
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np


def load_yaml(path: Path) -> dict[str, Any]:
    try:
        import yaml
    except ImportError as exc:
        raise RuntimeError("PyYAML is required to read the project configuration") from exc
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Configuration root must be a mapping")
    return data


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
        try:
            import tifffile
        except ImportError as exc:
            raise RuntimeError("tifffile is required for TIFF inputs") from exc
        return tifffile.imread(path)
    raise ValueError(f"Unsupported input format: {path}")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def resolve_path(base: Path, value: str) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else (base / path).resolve()


def require_keys(mapping: dict[str, Any], keys: tuple[str, ...], where: str) -> None:
    missing = [key for key in keys if key not in mapping]
    if missing:
        raise ValueError(f"Missing {where} field(s): {', '.join(missing)}")


def validate_labels(array: np.ndarray, name: str) -> np.ndarray:
    values = np.asarray(array)
    if not np.all(np.isfinite(values)):
        raise ValueError(f"{name} contains non-finite labels")
    if np.any(values < 0):
        raise ValueError(f"{name} contains negative labels")
    if not (np.issubdtype(values.dtype, np.integer) or values.dtype == np.bool_):
        if not np.all(values == np.floor(values)):
            raise ValueError(f"{name} contains non-integral labels")
    maximum = int(values.max()) if values.size else 0
    if maximum > np.iinfo(np.uint64).max:
        raise ValueError(f"{name} exceeds uint64 label capacity")
    return values.astype(np.uint64, copy=False)


def validate_offset(values: Any, axes_name: str) -> list[int]:
    offsets = [float(value) for value in values]
    if len(offsets) != len(axes_name) or any(value != int(value) for value in offsets):
        raise ValueError("raw.offset_vox must contain one integer value per declared axis")
    return [int(value) for value in offsets]


def robust01(image: np.ndarray) -> np.ndarray:
    values = np.asarray(image, dtype=np.float32)
    finite = values[np.isfinite(values)]
    if not finite.size:
        return np.zeros(values.shape, dtype=np.float32)
    low, high = np.percentile(finite, [1, 99])
    if high <= low:
        return np.zeros(values.shape, dtype=np.float32)
    scaled = np.where(np.isfinite(values), (values - low) / (high - low), 0)
    return np.clip(scaled, 0, 1)


def label_boundaries(labels: np.ndarray) -> np.ndarray:
    boundary = np.zeros(labels.shape, dtype=bool)
    boundary[1:, :] |= labels[1:, :] != labels[:-1, :]
    boundary[:, 1:] |= labels[:, 1:] != labels[:, :-1]
    return boundary & (labels != 0)


def label_colors(labels: np.ndarray) -> np.ndarray:
    rgb = np.zeros((*labels.shape, 3), dtype=np.float32)
    for value in np.unique(labels):
        if value:
            rgb[labels == value] = colorsys.hsv_to_rgb((int(value) * 0.61803398875) % 1, 0.72, 1)
    return rgb


def overlay(raw: np.ndarray, labels: np.ndarray, alpha: float = 0.48) -> np.ndarray:
    base = np.repeat(robust01(raw)[..., None], 3, axis=-1)
    tint = label_colors(labels)
    foreground = labels != 0
    base[foreground] = (1 - alpha) * base[foreground] + alpha * tint[foreground]
    base[label_boundaries(labels)] = 1
    return base


def choose_slice(labels: list[np.ndarray], axis: str, requested: int | None) -> int | None:
    if labels[0].ndim == 2:
        if axis != "xy":
            raise ValueError("2D yx inputs support only the xy view")
        if requested not in (None, 0):
            raise ValueError("2D inputs have only index 0")
        return None
    dim = {"xy": 0, "xz": 1, "yz": 2}[axis]
    if requested is not None:
        if not 0 <= requested < labels[0].shape[dim]:
            raise ValueError(f"Slice index {requested} is outside axis length {labels[0].shape[dim]}")
        return requested
    foreground = np.zeros(labels[0].shape, dtype=bool)
    for label in labels:
        foreground |= label > 0
    reduction = tuple(index for index in range(3) if index != dim)
    counts = np.count_nonzero(foreground, axis=reduction)
    return int(np.argmax(counts)) if np.any(counts) else labels[0].shape[dim] // 2


def take_view(array: np.ndarray, axis: str, index: int | None) -> np.ndarray:
    if array.ndim == 2:
        return np.asarray(array)
    assert index is not None
    if axis == "xy":
        return np.asarray(array[index])
    if axis == "xz":
        return np.asarray(array[:, index, :])
    return np.asarray(array[:, :, index])


def foreground_metrics(prediction: np.ndarray, truth: np.ndarray) -> dict[str, float]:
    pred = prediction > 0
    true = truth > 0
    tp = int(np.count_nonzero(pred & true))
    fp = int(np.count_nonzero(pred & ~true))
    fn = int(np.count_nonzero(~pred & true))
    denominator_dice = 2 * tp + fp + fn
    denominator_iou = tp + fp + fn
    return {
        "dice": float(2 * tp / denominator_dice) if denominator_dice else 1.0,
        "iou": float(tp / denominator_iou) if denominator_iou else 1.0,
        "precision": float(tp / (tp + fp)) if tp + fp else float(true.sum() == 0),
        "recall": float(tp / (tp + fn)) if tp + fn else 1.0,
    }


def instance_matching(prediction: np.ndarray, truth: np.ndarray, threshold: float) -> dict[str, Any]:
    pred_ids, pred_counts = np.unique(prediction[prediction > 0], return_counts=True)
    true_ids, true_counts = np.unique(truth[truth > 0], return_counts=True)
    pred_size = {int(label): int(count) for label, count in zip(pred_ids, pred_counts)}
    true_size = {int(label): int(count) for label, count in zip(true_ids, true_counts)}
    overlap_mask = (prediction > 0) & (truth > 0)
    pairs: list[tuple[float, int, int]] = []
    if np.any(overlap_mask):
        pair_values, intersections = np.unique(
            np.stack((prediction[overlap_mask], truth[overlap_mask]), axis=1), axis=0, return_counts=True
        )
        for (pred_id, true_id), intersection in zip(pair_values, intersections):
            union = pred_size[int(pred_id)] + true_size[int(true_id)] - int(intersection)
            iou = float(intersection / union)
            if iou >= threshold:
                pairs.append((iou, int(pred_id), int(true_id)))
    matched_pred: set[int] = set()
    matched_true: set[int] = set()
    matched_ious: list[float] = []
    for iou, pred_id, true_id in sorted(pairs, reverse=True):
        if pred_id not in matched_pred and true_id not in matched_true:
            matched_pred.add(pred_id)
            matched_true.add(true_id)
            matched_ious.append(iou)
    tp = len(matched_ious)
    fp = len(pred_ids) - tp
    fn = len(true_ids) - tp
    precision = tp / (tp + fp) if tp + fp else float(len(true_ids) == 0)
    recall = tp / (tp + fn) if tp + fn else 1.0
    return {
        "iou_threshold": threshold,
        "matched_instances": tp,
        "false_positive_instances": fp,
        "false_negative_instances": fn,
        "precision": float(precision),
        "recall": float(recall),
        "f1": float(2 * precision * recall / (precision + recall)) if precision + recall else 0.0,
        "mean_matched_iou": float(np.mean(matched_ious)) if matched_ious else None,
    }


def connected_component_count(foreground: np.ndarray) -> int | None:
    try:
        from scipy import ndimage
    except ImportError:
        return None
    _, count = ndimage.label(foreground)
    return int(count)


def descriptive_metrics(labels: np.ndarray, kind: str) -> dict[str, Any]:
    foreground = labels > 0
    ids, counts = np.unique(labels[foreground], return_counts=True)
    border_ids = set()
    if labels.size:
        for face in [labels[0], labels[-1], labels[..., 0], labels[..., -1]]:
            border_ids.update(int(value) for value in np.unique(face) if value)
        if labels.ndim == 3:
            for face in [labels[:, 0, :], labels[:, -1, :]]:
                border_ids.update(int(value) for value in np.unique(face) if value)
    result: dict[str, Any] = {
        "kind": kind,
        "foreground_fraction": float(np.count_nonzero(foreground) / labels.size) if labels.size else 0.0,
        "label_count": int(ids.size),
        "foreground_component_count": connected_component_count(foreground),
        "border_touch_label_count": len(border_ids),
        "label_size_voxels": {
            "min": int(counts.min()) if counts.size else 0,
            "median": float(np.median(counts)) if counts.size else 0.0,
            "max": int(counts.max()) if counts.size else 0,
        },
    }
    if labels.ndim == 3 and ids.size:
        z_bounds: dict[int, list[int]] = {}
        for z_index, section in enumerate(labels):
            for value in np.unique(section):
                if value:
                    z_bounds.setdefault(int(value), [z_index, z_index])[1] = z_index
        spans = [maximum - minimum + 1 for minimum, maximum in z_bounds.values()]
        result["z_span_slices"] = {
            "min": min(spans), "median": float(np.median(spans)), "max": max(spans)
        }
    return result


def extent(axis: str, shape: tuple[int, int], axes: str, resolution_nm: list[float]) -> list[float]:
    mapping = dict(zip(axes, resolution_nm))
    vertical_name, horizontal_name = {"xy": ("y", "x"), "xz": ("z", "x"), "yz": ("z", "y")}[axis]
    vertical = mapping[vertical_name]
    horizontal = mapping[horizontal_name]
    return [0, shape[1] * horizontal / 1000, shape[0] * vertical / 1000, 0]


def scale_bar_um(width_um: float) -> float:
    candidates = np.asarray([0.02, 0.05, 0.1, 0.2, 0.5, 1, 2, 5, 10, 20, 50, 100])
    allowed = candidates[candidates <= width_um * 0.28]
    return float(allowed[-1] if allowed.size else width_um * 0.2)


def render_comparison(
    raw: np.ndarray,
    candidates: list[dict[str, Any]],
    truth: dict[str, Any] | None,
    axis: str,
    index: int | None,
    axes_name: str,
    resolution_nm: list[float],
    output_root: Path,
) -> list[Path]:
    import matplotlib as mpl
    import matplotlib.pyplot as plt
    from mpl_toolkits.axes_grid1.anchored_artists import AnchoredSizeBar

    mpl.rcParams.update({"font.family": "sans-serif", "font.size": 7, "svg.fonttype": "none"})
    panels: list[tuple[str, np.ndarray, str | None]] = [("Raw EM", robust01(take_view(raw, axis, index)), "gray")]
    if truth is not None:
        panels.append(("Ground truth", overlay(take_view(raw, axis, index), take_view(truth["array"], axis, index)), None))
    for candidate in candidates:
        title = candidate["name"]
        if candidate.get("objective_score") is not None:
            title += f" · {candidate['objective_metric']}={candidate['objective_score']:.3f}"
        panels.append((title, overlay(take_view(raw, axis, index), take_view(candidate["array"], axis, index)), None))
    fig, plot_axes = plt.subplots(1, len(panels), figsize=(1.9 * len(panels), 2.15), constrained_layout=True)
    plot_axes = np.atleast_1d(plot_axes)
    for panel, (title, image, cmap) in zip(plot_axes, panels):
        physical_extent = extent(axis, image.shape[:2], axes_name, resolution_nm)
        panel.imshow(image, cmap=cmap, extent=physical_extent, interpolation="nearest", aspect="equal")
        panel.set_title(title)
        panel.set_xticks([])
        panel.set_yticks([])
        bar = scale_bar_um(physical_extent[1])
        bar_label = f"{bar:g} µm" if bar >= 1 else f"{bar * 1000:g} nm"
        panel.add_artist(AnchoredSizeBar(
            panel.transData,
            bar,
            bar_label,
            "lower right",
            color="white",
            frameon=False,
            pad=0.25,
            size_vertical=max(abs(physical_extent[2] - physical_extent[3]) * 0.008, 0.002),
            fontproperties={"size": 6},
        ))
    location = "2D" if index is None else f"{axis.upper()} index {index}"
    fig.suptitle(f"EM segmentation review · {location}", x=0.01, ha="left", fontsize=8, weight="bold")
    output_root.mkdir(parents=True, exist_ok=True)
    paths = [output_root / "review-comparison.png", output_root / "review-comparison.svg"]
    fig.savefig(paths[0], dpi=300, bbox_inches="tight", pad_inches=0.04, metadata={"Creator": "review-em-segmentation"})
    fig.savefig(paths[1], bbox_inches="tight", pad_inches=0.04, metadata={"Creator": "review-em-segmentation"})
    plt.close(fig)
    return paths


def review(config_path: Path) -> dict[str, Any]:
    config_path = config_path.resolve()
    config = load_yaml(config_path)
    require_keys(config, ("project_id", "raw", "candidates", "review"), "configuration")
    base = config_path.parent
    raw_cfg = config["raw"]
    review_cfg = config["review"]
    require_keys(raw_cfg, ("path", "source_id", "grid_id", "axes", "resolution_nm", "offset_vox"), "raw")
    require_keys(review_cfg, ("output_root",), "review")
    axes_name = str(raw_cfg["axes"]).lower()
    if axes_name not in {"yx", "zyx"}:
        raise ValueError("raw.axes must be yx or zyx")
    resolution_nm = [float(value) for value in raw_cfg["resolution_nm"]]
    if len(resolution_nm) != len(axes_name) or any(value <= 0 for value in resolution_nm):
        raise ValueError("raw.resolution_nm must contain one positive value per declared axis")
    offset_vox = validate_offset(raw_cfg["offset_vox"], axes_name)
    grid_id = str(raw_cfg["grid_id"]).strip()
    source_id = str(raw_cfg["source_id"]).strip()
    if not grid_id or not source_id:
        raise ValueError("raw.source_id and raw.grid_id must be non-empty")
    raw_path = resolve_path(base, raw_cfg["path"])
    raw = np.asarray(load_array(raw_path))
    if raw.ndim != len(axes_name):
        raise ValueError(f"Raw shape {raw.shape} does not match axes {axes_name}")
    if not np.any(np.isfinite(raw)):
        raise ValueError("Raw image contains no finite values")

    candidate_cfgs = config["candidates"]
    if not isinstance(candidate_cfgs, list) or not candidate_cfgs:
        raise ValueError("candidates must be a non-empty list")
    names: set[str] = set()
    candidates: list[dict[str, Any]] = []
    for item in candidate_cfgs:
        if not isinstance(item, dict):
            raise ValueError("Each candidate must be a mapping")
        require_keys(item, ("name", "path", "kind", "grid_id", "provenance"), "candidate")
        name = str(item["name"])
        kind = str(item["kind"]).lower()
        if not name.strip():
            raise ValueError("Candidate name must be non-empty")
        if name in names:
            raise ValueError(f"Duplicate candidate name: {name}")
        if kind not in {"semantic", "instance"}:
            raise ValueError(f"Candidate {name} kind must be semantic or instance")
        if str(item["grid_id"]) != grid_id:
            raise ValueError(f"Candidate {name} grid_id does not match raw grid_id {grid_id}")
        if not str(item["provenance"]).strip():
            raise ValueError(f"Candidate {name} provenance must be non-empty")
        names.add(name)
        path = resolve_path(base, item["path"])
        labels = validate_labels(load_array(path), name)
        if kind == "semantic" and np.unique(labels[labels > 0]).size > 1:
            raise ValueError(f"Candidate {name} semantic labels must use one non-zero foreground value")
        if labels.shape != raw.shape:
            raise ValueError(f"Candidate {name} shape {labels.shape} does not match raw {raw.shape}")
        candidates.append({
            "name": name,
            "kind": kind,
            "path": path,
            "array": labels,
            "grid_id": grid_id,
            "provenance": str(item["provenance"]),
        })

    candidate_kinds = {candidate["kind"] for candidate in candidates}
    if len(candidate_kinds) > 1:
        raise ValueError("All candidates in one comparison must share semantic or instance label meaning")

    truth = None
    if config.get("ground_truth") is not None:
        truth_cfg = config["ground_truth"]
        require_keys(truth_cfg, ("path", "kind", "grid_id", "provenance"), "ground_truth")
        truth_kind = str(truth_cfg["kind"]).lower()
        if truth_kind not in {"semantic", "instance"}:
            raise ValueError("ground_truth.kind must be semantic or instance")
        if str(truth_cfg["grid_id"]) != grid_id:
            raise ValueError(f"Ground truth grid_id does not match raw grid_id {grid_id}")
        truth_path = resolve_path(base, truth_cfg["path"])
        truth_labels = validate_labels(load_array(truth_path), "ground truth")
        if truth_kind == "semantic" and np.unique(truth_labels[truth_labels > 0]).size > 1:
            raise ValueError("Ground-truth semantic labels must use one non-zero foreground value")
        if truth_labels.shape != raw.shape:
            raise ValueError(f"Ground truth shape {truth_labels.shape} does not match raw {raw.shape}")
        if not str(truth_cfg["provenance"]).strip():
            raise ValueError("Ground-truth provenance must be non-empty")
        truth = {"kind": truth_kind, "path": truth_path, "array": truth_labels, "provenance": str(truth_cfg["provenance"])}

    threshold = float(review_cfg.get("instance_iou_threshold", 0.5))
    if not 0 < threshold <= 1:
        raise ValueError("review.instance_iou_threshold must be in (0, 1]")
    axis = str(review_cfg.get("axis", "xy")).lower()
    if axis not in {"xy", "xz", "yz"}:
        raise ValueError("review.axis must be xy, xz, or yz")
    requested_index = review_cfg.get("index")
    if requested_index is not None:
        requested_index = int(requested_index)
    selection_arrays = [item["array"] for item in candidates]
    if truth is not None:
        selection_arrays.append(truth["array"])
    index = choose_slice(selection_arrays, axis, requested_index)
    output_root = resolve_path(base, review_cfg["output_root"])
    report_path = output_root / "review-report.json"
    if report_path.exists() and not bool(review_cfg.get("force", False)):
        raise FileExistsError(f"Refusing to overwrite existing report: {report_path}")

    warnings = []
    if truth is None:
        warnings.append("No ground truth was supplied; descriptive QC cannot establish accuracy or rank candidates.")
    if raw.ndim == 2:
        warnings.append("The review is 2D and cannot establish 3D continuity or topology.")
    if not np.all(np.isfinite(raw)):
        warnings.append("Raw image contains non-finite pixels; visualization uses finite values only.")

    candidate_reports = []
    for candidate in candidates:
        item_report: dict[str, Any] = {
            "name": candidate["name"],
            "kind": candidate["kind"],
            "grid_id": candidate["grid_id"],
            "provenance": candidate["provenance"],
            "artifact": {"path": str(candidate["path"]), "sha256": sha256(candidate["path"])},
            "descriptive_qc": descriptive_metrics(candidate["array"], candidate["kind"]),
            "ground_truth_metrics": None,
            "objective_score": None,
            "objective_metric": None,
        }
        if item_report["descriptive_qc"]["foreground_fraction"] in {0.0, 1.0}:
            warnings.append(f"Candidate {candidate['name']} has an empty or full foreground mask.")
        if truth is not None:
            fg = foreground_metrics(candidate["array"], truth["array"])
            metrics: dict[str, Any] = {"foreground": fg}
            score = fg["dice"]
            metric_name = "foreground_dice"
            if candidate["kind"] == "instance" and truth["kind"] == "instance":
                matched = instance_matching(candidate["array"], truth["array"], threshold)
                metrics["instance_matching"] = matched
                score = matched["f1"]
                metric_name = "instance_f1"
            item_report["ground_truth_metrics"] = metrics
            item_report["objective_score"] = float(score)
            item_report["objective_metric"] = metric_name
            candidate["objective_score"] = float(score)
            candidate["objective_metric"] = metric_name.replace("_", " ")
        candidate_reports.append(item_report)

    ranking = None
    if truth is not None:
        ranking = [
            {
                "rank": rank,
                "name": item["name"],
                "objective_metric": item["objective_metric"],
                "objective_score": item["objective_score"],
            }
            for rank, item in enumerate(sorted(candidate_reports, key=lambda value: (-value["objective_score"], value["name"])), start=1)
        ]

    figure_paths = render_comparison(raw, candidates, truth, axis, index, axes_name, resolution_nm, output_root)
    report = {
        "schema_version": 1,
        "project_id": str(config["project_id"]),
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "review_scope": {
            "axes": axes_name,
            "resolution_nm": resolution_nm,
            "offset_vox": offset_vox,
            "grid_id": grid_id,
            "view_axis": axis,
            "view_index": index,
            "slice_selection": "manual" if requested_index is not None else "maximum union foreground",
        },
        "raw": {
            "path": str(raw_path),
            "sha256": sha256(raw_path),
            "source_id": source_id,
            "grid_id": grid_id,
            "shape": list(raw.shape),
            "dtype": str(raw.dtype),
        },
        "ground_truth": None if truth is None else {
            "path": str(truth["path"]), "sha256": sha256(truth["path"]), "kind": truth["kind"], "grid_id": grid_id, "provenance": truth["provenance"]
        },
        "candidates": candidate_reports,
        "ranking": ranking,
        "warnings": sorted(set(warnings)),
        "evidence_state": "measured_accuracy_on_declared_ground_truth" if truth is not None else "descriptive_qc_only",
        "scientific_approval": "withheld",
        "approval_reason": "An explicit human review decision is required after inspecting the report and source-aligned figures.",
        "figures": [str(path) for path in figure_paths],
    }
    output_root.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"report": str(report_path), "figures": report["figures"], "ranking": ranking}, ensure_ascii=False, indent=2))
    return report


def finalize(args: argparse.Namespace) -> dict[str, Any]:
    report_path = args.report.resolve()
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if report.get("scientific_approval") != "withheld":
        raise ValueError("Input report is not an unapproved deterministic review report")
    output = args.output.resolve() if args.output else report_path.with_name("approval-record.json")
    if output.exists() and not args.force:
        raise FileExistsError(f"Refusing to overwrite existing approval record: {output}")
    record = {
        "schema_version": 1,
        "report": {"path": str(report_path), "sha256": sha256(report_path)},
        "decision": args.decision,
        "reviewer": args.reviewer.strip(),
        "basis": args.basis.strip(),
        "claim_scope": args.claim_scope.strip(),
        "decided_utc": datetime.now(timezone.utc).isoformat(),
        "automated_selection": False,
    }
    if not all(record[key] for key in ("reviewer", "basis", "claim_scope")):
        raise ValueError("reviewer, basis, and claim-scope must be non-empty")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(record, ensure_ascii=False, indent=2))
    return record


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    sub = root.add_subparsers(dest="command", required=True)
    review_parser = sub.add_parser("review", help="Run deterministic review from a YAML project configuration")
    review_parser.add_argument("config", type=Path)
    final_parser = sub.add_parser("finalize", help="Record an explicit human decision for an existing report")
    final_parser.add_argument("report", type=Path)
    final_parser.add_argument("--decision", choices=("approved", "rejected", "withheld"), required=True)
    final_parser.add_argument("--reviewer", required=True)
    final_parser.add_argument("--basis", required=True)
    final_parser.add_argument("--claim-scope", required=True)
    final_parser.add_argument("--output", type=Path)
    final_parser.add_argument("--force", action="store_true")
    return root


def main() -> int:
    args = parser().parse_args()
    if args.command == "review":
        review(args.config)
    else:
        finalize(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
