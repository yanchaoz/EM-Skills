#!/usr/bin/env python3
"""Create a spatial and UMAP embedding-domain annotation review figure."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np


def umap2(
    x: np.ndarray,
    n_neighbors: int = 25,
    min_dist: float = 0.12,
    metric: str = "euclidean",
    seed: int = 7,
) -> np.ndarray:
    if len(x) < 3:
        raise ValueError("UMAP visualization requires at least three embedding rows")
    if n_neighbors < 2:
        raise ValueError("UMAP n_neighbors must be at least 2")
    if min_dist < 0:
        raise ValueError("UMAP min_dist must be non-negative")
    try:
        import umap
    except ImportError as exc:
        raise RuntimeError("UMAP visualization requires the umap-learn package; no PCA fallback is used") from exc
    effective_neighbors = min(max(2, n_neighbors), len(x) - 1)
    reducer = umap.UMAP(
        n_components=2,
        n_neighbors=effective_neighbors,
        min_dist=min_dist,
        metric=metric,
        random_state=seed,
    )
    return reducer.fit_transform(x.astype(np.float32, copy=False))


def render(
    manifest_path: Path,
    selection_path: Path,
    embeddings_path: Path,
    out_path: Path,
    projection_out: Path | None = None,
    n_neighbors: int = 25,
    min_dist: float = 0.12,
    metric: str = "euclidean",
    seed: int = 7,
) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    selection = json.loads(selection_path.read_text(encoding="utf-8"))
    embeddings = np.load(embeddings_path, allow_pickle=False)
    if embeddings.ndim != 2 or embeddings.shape[0] != manifest["patch_count"]:
        raise ValueError("embedding shape does not match manifest")

    points = umap2(embeddings, n_neighbors=n_neighbors, min_dist=min_dist, metric=metric, seed=seed)
    if projection_out is not None:
        projection_out.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(
            projection_out,
            umap=points,
            n_neighbors=np.asarray(n_neighbors),
            min_dist=np.asarray(min_dist),
            metric=np.asarray(metric),
            seed=np.asarray(seed),
            embedding_rows=np.asarray(embeddings.shape[0]),
        )
    covered = np.asarray(selection["covered_patch_ids"], dtype=int)
    selected = np.asarray(selection["selected_patch_ids"], dtype=int)
    curve = selection["coverage_curve"]
    source_shape = manifest["source"]["shape_zyx"]

    fig = plt.figure(figsize=(14, 9), constrained_layout=True)
    grid = fig.add_gridspec(2, 2, height_ratios=[1.1, 0.9])
    ax_space = fig.add_subplot(grid[0, 0])
    ax_embed = fig.add_subplot(grid[0, 1])
    ax_curve = fig.add_subplot(grid[1, 0])
    ax_table = fig.add_subplot(grid[1, 1])

    ax_space.set_title("A  Spatial annotation suggestions (XY projection)", loc="left", fontweight="bold")
    ax_space.add_patch(Rectangle((0, 0), source_shape[2], source_shape[1], facecolor="#f3f5f7", edgecolor="#5d6772", linewidth=1.2))
    colors = plt.cm.tab10(np.linspace(0, 1, max(1, len(selection["selected_subvolumes"]))))
    for color, row in zip(colors, selection["selected_subvolumes"]):
        (z0, y0, x0), (z1, y1, x1) = row["bbox_zyx"]
        ax_space.add_patch(Rectangle((x0, y0), x1 - x0, y1 - y0, facecolor=color, edgecolor="black", alpha=0.42, linewidth=1.2))
        label_x = x0 + min(4, max(1, (x1 - x0) * 0.12))
        label_y = y0 + min(14, max(2, (y1 - y0) * 0.5))
        ax_space.text(label_x, label_y, f"#{row['rank']}", fontsize=9, fontweight="bold", color="black")
    ax_space.set_xlim(0, source_shape[2])
    ax_space.set_ylim(source_shape[1], 0)
    ax_space.set_aspect("equal", adjustable="box")
    ax_space.set_xlabel("x (voxel)")
    ax_space.set_ylabel("y (voxel)")
    ax_space.text(0.01, 0.01, "Boxes are projected across z; inspect every slice before acceptance.", transform=ax_space.transAxes, fontsize=8, color="#4d5660")

    ax_embed.set_title("B  Embedding coverage (UMAP for display only)", loc="left", fontweight="bold")
    ax_embed.scatter(points[:, 0], points[:, 1], s=9, c="#b8c0c8", alpha=0.45, label="all patches", linewidths=0)
    if covered.size:
        ax_embed.scatter(points[covered, 0], points[covered, 1], s=13, c="#f39c36", alpha=0.55, label="covered", linewidths=0)
    if selected.size:
        ax_embed.scatter(points[selected, 0], points[selected, 1], s=27, c="#d62728", marker="*", alpha=0.9, label="selected", linewidths=0)
    ax_embed.set_xlabel("UMAP 1")
    ax_embed.set_ylabel("UMAP 2")
    ax_embed.legend(frameon=False, fontsize=8)
    ax_embed.text(0.01, 0.01, f"UMAP n={n_neighbors}, min_dist={min_dist:g}, seed={seed}; diagnostic only.", transform=ax_embed.transAxes, fontsize=8, color="#4d5660")

    ax_curve.set_title("C  Constrained coverage rate", loc="left", fontweight="bold")
    ranks = [r["rank"] for r in curve]
    rates = [100 * r["coverage_rate"] for r in curve]
    ax_curve.plot(ranks, rates, color="#165d8c", marker="o", linewidth=2)
    ax_curve.fill_between(ranks, rates, alpha=0.14, color="#165d8c")
    ax_curve.set_xticks(ranks)
    ax_curve.set_ylim(0, max(100, max(rates, default=0) * 1.08))
    ax_curve.set_xlabel("selected subvolume rank")
    ax_curve.set_ylabel("covered patches (%)")
    ax_curve.grid(axis="y", color="#dfe3e6", linewidth=0.8)

    ax_table.set_title("D  Human review queue", loc="left", fontweight="bold")
    ax_table.axis("off")
    table_rows = []
    for row in selection["selected_subvolumes"]:
        box = row["bbox_zyx"]
        table_rows.append([
            f"#{row['rank']}",
            row["candidate_id"],
            f"{row.get('derived_shape_zyx', [box[1][i]-box[0][i] for i in range(3)])}",
            f"{box[0]}–{box[1]}",
            f"+{row['newly_covered_patch_count']}",
            row.get("review_status", "pending"),
        ])
    table = ax_table.table(
        cellText=table_rows,
        colLabels=["Rank", "ID", "Size zyx", "bbox zyx", "Gain", "Review"],
        colWidths=[0.07, 0.18, 0.15, 0.32, 0.10, 0.16],
        loc="center",
        cellLoc="left",
        colLoc="left",
    )
    table.auto_set_font_size(False)
    table.set_fontsize(8)
    table.scale(1, 1.45)
    for (r, _), cell in table.get_celld().items():
        cell.set_edgecolor("#dfe3e6")
        if r == 0:
            cell.set_facecolor("#e9eef2")
            cell.set_text_props(weight="bold")

    spent = selection.get("annotation_cost_voxels")
    budget = selection.get("annotation_budget_voxels")
    budget_text = f" • budget {spent:,}/{budget:,} voxels" if isinstance(spent, int) and isinstance(budget, int) else ""
    fig.suptitle(f"EM Annotation Advisor — {selection.get('project_id', 'project')}\nDRAFT • human review required{budget_text}", fontsize=15, fontweight="bold")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=220, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--selection", type=Path, required=True)
    parser.add_argument("--embeddings", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--projection-out", type=Path, help="optional compressed NPZ containing UMAP coordinates and parameters")
    parser.add_argument("--umap-neighbors", type=int, default=25)
    parser.add_argument("--umap-min-dist", type=float, default=0.12)
    parser.add_argument("--umap-metric", default="euclidean")
    parser.add_argument("--umap-seed", type=int, default=7)
    args = parser.parse_args()
    render(
        args.manifest,
        args.selection,
        args.embeddings,
        args.out,
        projection_out=args.projection_out,
        n_neighbors=args.umap_neighbors,
        min_dist=args.umap_min_dist,
        metric=args.umap_metric,
        seed=args.umap_seed,
    )
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
