"""Audit native-data support and the voxel-centre effects of cutaway changes."""
from __future__ import annotations
import argparse
from pathlib import Path
import numpy as np
from cutaway_core import (keep_mask, load_config, native_world_um, open_source,
                          sha256, source_metadata, source_support, world_to_uv, write_json)


def frozen_settings(cfg):
    """Snapshot non-crop settings and the currently referenced mesh identity."""
    mesh = cfg.get("mesh")
    return dict(mesh=(dict(path=mesh["path"], sha256=sha256(mesh["path"]), units=mesh["units"],
                          offset_nm_xyz=mesh.get("offset_nm_xyz", [0, 0, 0])) if mesh else None),
                orientation=dict(reflect_z=cfg.get("geometry", {}).get("reflect_z", False)),
                **{key: cfg.get(key, {}) for key in ("camera", "contour", "display", "render")})


def changed_fields(before, after, prefix):
    if isinstance(before, dict) and isinstance(after, dict):
        result = []
        for key in sorted(set(before) | set(after)):
            field = f"{prefix}.{key}"
            if key not in before or key not in after:
                result.append(field)
            else:
                result.extend(changed_fields(before[key], after[key], field))
        return result
    if isinstance(before, list) and isinstance(after, list) and len(before) == len(after):
        return [field for i, (a, b) in enumerate(zip(before, after))
                for field in changed_fields(a, b, f"{prefix}[{i}]")]
    return [] if before == after else [prefix]


def compare_frozen_settings(before, after):
    sections = {}
    for key in before:
        fields = changed_fields(before[key], after[key], key)
        sections[key] = dict(unchanged=not fields, baseline=before[key], current=after[key],
                             changed_fields=fields)
    fields = [field for section in sections.values() for field in section["changed_fields"]]
    return dict(unchanged=not fields, changed_fields=fields, sections=sections,
                scope="Configuration values and currently referenced mesh files; not historical source identity or command-line render overrides.")


def audit(config_path, compare=None, slices=None):
    cfg = load_config(config_path)
    raw = open_source(cfg)
    meta = source_metadata(cfg, raw)
    baseline = load_config(compare) if compare else None
    settings_before, settings_after, settings_comparison = None, None, None
    if baseline:
        previous = open_source(baseline)
        prior = source_metadata(baseline, previous)
        for key in ("sha256", "shape_zyx", "voxel_size_nm_xyz", "offset_nm_xyz", "zero_is_missing"):
            if meta[key] != prior[key]:
                raise ValueError(f"Comparison requires identical source mapping: {key} differs")
        settings_before, settings_after = frozen_settings(baseline), frozen_settings(cfg)
        settings_comparison = compare_frozen_settings(settings_before, settings_after)
    selected = list(range(raw.shape[0])) if slices is None else sorted(set(slices))
    if not selected or min(selected) < 0 or max(selected) >= raw.shape[0]:
        raise ValueError("--slices must select valid native zero-based Z indices")
    yy, xx = np.mgrid[:raw.shape[1], :raw.shape[2]]
    xw, yw, _ = native_world_um(cfg, raw.shape, xx, yy, 0)
    u, v = world_to_uv(cfg, xw, yw)
    totals = dict(kept_valid_voxels=0, kept_missing_voxels=0, added_valid_voxels=0, removed_valid_voxels=0)
    details, changed = [], []
    for z in selected:
        _, _, zw = native_world_um(cfg, raw.shape, 0, 0, z)
        keep = keep_mask(cfg, u, v, zw)
        support = source_support(cfg, raw[z])
        valid = keep & support
        values = raw[z][valid]
        row = dict(raw_z_index=z, display_z_um=float(zw), geometry_selected_voxels=int(keep.sum()),
                   kept_valid_voxels=int(valid.sum()), kept_missing_voxels=int((keep & ~support).sum()),
                   raw_zero_voxels_in_keep=int((keep & (raw[z] == 0)).sum()),
                   intensity_p10_p50_p90=np.percentile(values, [10, 50, 90]).tolist() if values.size else None)
        if baseline:
            bx, by, bz = native_world_um(baseline, raw.shape, xx, yy, z)
            bu, bv = world_to_uv(baseline, bx, by)
            before = keep_mask(baseline, bu, bv, bz)
            added, removed = valid & ~before, before & support & ~keep
            row.update(added_valid_voxels=int(added.sum()), removed_valid_voxels=int(removed.sum()),
                       changed_geometry_voxels=int((before != keep).sum()))
            if row["changed_geometry_voxels"]:
                cy, cx = np.where(before != keep)
                row["changed_index_xy_bounds_inclusive"] = [[int(cx.min()), int(cy.min())], [int(cx.max()), int(cy.max())]]
                changed.append(z)
        for key in totals:
            totals[key] += row.get(key, 0)
        details.append(row)
    if sha256(meta["path"]) != meta["sha256"]:
        raise RuntimeError("Source changed during audit")
    if baseline:
        if sha256(prior["path"]) != prior["sha256"]:
            raise RuntimeError("Baseline source changed during audit")
        for settings in (settings_before, settings_after):
            mesh = settings["mesh"]
            if mesh and sha256(mesh["path"]) != mesh["sha256"]:
                raise RuntimeError("A referenced mesh changed during audit")
    return dict(schema_version=1, source=meta, config_path=cfg["_config_path"],
                compared_config=baseline["_config_path"] if baseline else None,
                frozen_settings_comparison=settings_comparison,
                scope="all native voxel centres" if len(selected) == raw.shape[0] else "selected slices only",
                sampled_or_selected_slices=selected, changed_raw_z_indices=changed, totals=totals, slices=details,
                source_sha256_before_after_equal=True,
                caveat="Geometric/data audit, not a biological label validation or rendered-pixel equivalence test.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--compare")
    parser.add_argument("--slices", type=int, nargs="+")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    cfg = load_config(args.config)
    dest = Path(args.out).resolve()
    forbidden = [Path(cfg["source"]["path"]), Path(args.config).resolve()]
    if cfg.get("mesh"):
        forbidden.append(Path(cfg["mesh"]["path"]))
    if args.compare:
        forbidden.append(Path(args.compare).resolve())
    if dest in forbidden:
        raise ValueError("Audit output cannot overwrite an input")
    result = audit(args.config, args.compare, args.slices)
    dest.parent.mkdir(parents=True, exist_ok=True)
    write_json(dest, result)
    print(f"Audit written: {dest}")


if __name__ == "__main__":
    main()
