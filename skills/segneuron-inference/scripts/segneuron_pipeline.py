#!/usr/bin/env python3
"""Reproducible orchestration and gates for external SegNeuron inference.

This script does not vendor SegNeuron or model weights. It validates project
metadata, plans physical grids and tiles, renders reviewed argument-list jobs,
executes local adapters only when explicitly requested, and records evidence.
"""

from __future__ import annotations

import argparse
import copy
import datetime as dt
import hashlib
import itertools
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from typing import Any, Iterable, Mapping


VERSION = "0.2.0"
STAGES = ("audit", "plan", "pilot", "infer", "beta-sweep", "select-beta", "instance", "reconcile", "restore", "verify", "finalize")
REMOTE_SCHEMES = ("precomputed://", "gs://", "s3://", "http://", "https://", "zarr://", "n5://")
HEX64 = re.compile(r"^[0-9a-fA-F]{64}$")
MUTABLE_REVISIONS = {"main", "master", "latest", "head", "develop", "dev"}
SECRET_KEY = re.compile(r"(?:TOKEN|PASSWORD|PASSWD|SECRET|PRIVATE_KEY|ACCESS_KEY)", re.I)


class SkillError(RuntimeError):
    pass


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path, block_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            block = handle.read(block_size)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def load_document(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise SkillError(f"Configuration not found: {path}")
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json":
        data = json.loads(text)
    else:
        try:
            import yaml  # type: ignore
        except ImportError as exc:
            raise SkillError("YAML configuration requires PyYAML; use the bundled JSON example instead.") from exc
        data = yaml.safe_load(text)
    if not isinstance(data, dict):
        raise SkillError("Configuration root must be a mapping.")
    return data


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def require_mapping(root: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = root.get(key)
    if not isinstance(value, Mapping):
        raise SkillError(f"Missing or invalid mapping: {key}")
    return value


def require_text(root: Mapping[str, Any], key: str, context: str) -> str:
    value = root.get(key)
    if not isinstance(value, str) or not value.strip():
        raise SkillError(f"Missing or invalid {context}.{key}")
    return value.strip()


def number_vector(value: Any, length: int, context: str, *, integer: bool = False, positive: bool = False) -> list[float] | list[int]:
    if not isinstance(value, list) or len(value) != length:
        raise SkillError(f"{context} must be a list of length {length}")
    result: list[float] | list[int] = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            raise SkillError(f"{context} must contain numbers")
        converted: float | int = int(item) if integer else float(item)
        if integer and float(item) != converted:
            raise SkillError(f"{context} must contain integers")
        if positive and converted <= 0:
            raise SkillError(f"{context} must contain positive values")
        result.append(converted)
    return result


def is_remote(value: str) -> bool:
    return value.lower().startswith(REMOTE_SCHEMES)


def resolve_local(value: str, base: Path) -> Path:
    expanded = Path(os.path.expandvars(value)).expanduser()
    return (base / expanded).resolve() if not expanded.is_absolute() else expanded.resolve()


def resolve_output_root(config: Mapping[str, Any], config_path: Path) -> Path:
    output = require_mapping(config, "output")
    value = require_text(output, "root", "output")
    if is_remote(value):
        raise SkillError("output.root must be a local path because state records are written there")
    return resolve_local(value, config_path.parent)


def state_dir(config: Mapping[str, Any], config_path: Path) -> Path:
    return resolve_output_root(config, config_path) / "_segneuron_skill"


def config_digest(config: Mapping[str, Any]) -> str:
    return sha256_bytes(canonical_json(config).encode("utf-8"))


def read_state(config: Mapping[str, Any], config_path: Path) -> dict[str, Any]:
    path = state_dir(config, config_path) / "state.json"
    if path.exists():
        loaded = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            return loaded
    return {"pipeline_version": VERSION, "project_id": config.get("project", {}).get("id"), "stages": {}}


def update_state(config: Mapping[str, Any], config_path: Path, stage: str, status: str, artifact: Path | None = None, details: Mapping[str, Any] | None = None) -> None:
    state = read_state(config, config_path)
    state["pipeline_version"] = VERSION
    state["config_sha256"] = config_digest(config)
    state.setdefault("stages", {})[stage] = {
        "status": status,
        "updated_at": now_iso(),
        "artifact": str(artifact) if artifact else None,
        "details": dict(details or {}),
    }
    write_json(state_dir(config, config_path) / "state.json", state)


def require_stage(config: Mapping[str, Any], config_path: Path, stage: str, statuses: Iterable[str] = ("completed",)) -> None:
    state = read_state(config, config_path)
    actual = state.get("stages", {}).get(stage, {}).get("status")
    if actual not in set(statuses):
        raise SkillError(f"Stage '{stage}' must be {sorted(set(statuses))}; current status is {actual!r}")


def validate_bbox(bbox: list[int], shape: list[int], context: str) -> None:
    starts, ends = bbox[:3], bbox[3:]
    for axis, (start, end, maximum) in enumerate(zip(starts, ends, shape)):
        if start < 0 or end <= start or end > maximum:
            raise SkillError(f"Invalid {context} on zyx axis {axis}: [{start}, {end}) outside [0, {maximum})")


def audit_config(config: Mapping[str, Any], config_path: Path) -> dict[str, Any]:
    project = require_mapping(config, "project")
    project_id = require_text(project, "id", "project")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", project_id):
        raise SkillError("project.id must be filesystem-safe")

    source = require_mapping(config, "source")
    source_uri = require_text(source, "uri", "source")
    require_text(source, "format", "source")
    axes = require_text(source, "axis_order", "source").lower()
    if sorted(axes) != ["x", "y", "z"]:
        raise SkillError("source.axis_order must contain x, y, and z exactly once")
    shape = number_vector(source.get("shape_zyx"), 3, "source.shape_zyx", integer=True, positive=True)
    resolution = number_vector(source.get("resolution_nm_zyx"), 3, "source.resolution_nm_zyx", positive=True)
    offset = number_vector(source.get("offset_vox_zyx", [0, 0, 0]), 3, "source.offset_vox_zyx", integer=True)
    bbox = number_vector(source.get("bbox_vox_zyx", [0, 0, 0, *shape]), 6, "source.bbox_vox_zyx", integer=True)
    validate_bbox(bbox, shape, "source.bbox_vox_zyx")
    if source.get("read_only") is not True:
        raise SkillError("source.read_only must be true")
    require_text(source, "identity", "source")

    local_source: Path | None = None
    if not is_remote(source_uri):
        local_source = resolve_local(source_uri, config_path.parent)
        if not local_source.exists():
            raise SkillError(f"Local source does not exist: {local_source}")

    model = require_mapping(config, "model")
    require_text(model, "repository", "model")
    revision = require_text(model, "repo_commit", "model")
    if revision.lower() in MUTABLE_REVISIONS or not re.fullmatch(r"[0-9a-fA-F]{7,40}", revision):
        raise SkillError("model.repo_commit must be a pinned commit, not a mutable branch/tag")
    checkpoint = require_text(model, "checkpoint", "model")
    expected_checkpoint_hash = require_text(model, "checkpoint_sha256", "model")
    if not HEX64.fullmatch(expected_checkpoint_hash):
        raise SkillError("model.checkpoint_sha256 must contain 64 hexadecimal characters")
    checkpoint_actual: str | None = None
    if not is_remote(checkpoint):
        checkpoint_path = resolve_local(checkpoint, config_path.parent)
        if checkpoint_path.exists() and checkpoint_path.is_file():
            checkpoint_actual = sha256_file(checkpoint_path)
            if checkpoint_actual.lower() != expected_checkpoint_hash.lower():
                raise SkillError("Checkpoint SHA-256 does not match model.checkpoint_sha256")

    profile = require_mapping(model, "profile")
    target = number_vector(profile.get("target_resolution_nm_zyx"), 3, "model.profile.target_resolution_nm_zyx", positive=True)
    xy_range = number_vector(profile.get("validated_xy_nm"), 2, "model.profile.validated_xy_nm", positive=True)
    if xy_range[0] > xy_range[1]:
        raise SkillError("model.profile.validated_xy_nm minimum exceeds maximum")
    for name, value in (("y", target[1]), ("x", target[2])):
        if not xy_range[0] <= value <= xy_range[1]:
            raise SkillError(f"Target {name} resolution {value} nm is outside the model profile range {xy_range}")
    z_policy = require_text(profile, "z_policy", "model.profile").lower()
    if z_policy not in {"preserve", "explicit"}:
        raise SkillError("model.profile.z_policy must be preserve or explicit")
    if z_policy == "preserve" and not math.isclose(target[0], resolution[0], rel_tol=0, abs_tol=1e-9):
        raise SkillError("z_policy is preserve but target z resolution differs from source z resolution")
    require_text(profile, "normalization", "model.profile")
    patch = number_vector(profile.get("patch_zyx"), 3, "model.profile.patch_zyx", integer=True, positive=True)
    halo = number_vector(profile.get("halo_zyx"), 3, "model.profile.halo_zyx", integer=True)
    if any(item < 0 for item in halo):
        raise SkillError("model.profile.halo_zyx cannot be negative")
    if any(2 * h >= p for h, p in zip(halo, patch)):
        raise SkillError("Each halo must be less than half the corresponding patch size")

    planning = require_mapping(config, "planning")
    core = number_vector(planning.get("tile_core_zyx"), 3, "planning.tile_core_zyx", integer=True, positive=True)
    if any(c > p for c, p in zip(core, patch)):
        raise SkillError("planning.tile_core_zyx cannot exceed model.profile.patch_zyx")
    max_end_error = planning.get("max_end_error_nm", 0.51 * max(target))
    if isinstance(max_end_error, bool) or not isinstance(max_end_error, (int, float)) or max_end_error < 0:
        raise SkillError("planning.max_end_error_nm must be nonnegative")
    pilot_rois = planning.get("pilot_rois", [])
    if not isinstance(pilot_rois, list) or not pilot_rois:
        raise SkillError("planning.pilot_rois must contain at least one source-grid ROI")
    for index, roi in enumerate(pilot_rois):
        candidate = number_vector(roi, 6, f"planning.pilot_rois[{index}]", integer=True)
        validate_bbox(candidate, shape, f"planning.pilot_rois[{index}]")

    instance = require_mapping(config, "instance")
    scope = require_text(instance, "scope", "instance")
    if scope not in {"whole-volume", "per-block"}:
        raise SkillError("instance.scope must be whole-volume or per-block")
    if instance.get("label_dtype") not in {"uint32", "uint64"}:
        raise SkillError("instance.label_dtype must be uint32 or uint64")
    if instance.get("background_id", 0) != 0:
        raise SkillError("The bundled contract requires instance.background_id to be 0")
    reconciliation = require_mapping(instance, "global_reconciliation")
    if scope == "per-block" and reconciliation.get("required") is not True:
        raise SkillError("per-block instances require global reconciliation")

    beta_sweep = instance.get("beta_sweep")
    if beta_sweep is not None:
        if not isinstance(beta_sweep, Mapping):
            raise SkillError("instance.beta_sweep must be a mapping")
        values = beta_sweep.get("values")
        if not isinstance(values, list) or len(values) < 2:
            raise SkillError("instance.beta_sweep.values must contain at least two beta values")
        normalized: list[float] = []
        for value in values:
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise SkillError("instance.beta_sweep.values must contain numbers")
            beta = float(value)
            if not 0.0 < beta < 1.0:
                raise SkillError("Every beta value must be strictly between 0 and 1")
            normalized.append(beta)
        if len(set(normalized)) != len(normalized):
            raise SkillError("instance.beta_sweep.values must be unique")

    output = require_mapping(config, "output")
    output_root = resolve_output_root(config, config_path)
    if local_source is not None:
        source_guard = local_source
        overlaps = output_root == source_guard or (source_guard.is_dir() and source_guard in output_root.parents)
        if overlaps:
            raise SkillError("output.root must not equal or be nested inside the local source directory")

    commands = config.get("commands", {})
    if not isinstance(commands, Mapping):
        raise SkillError("commands must be a mapping")
    for name, command in commands.items():
        if not isinstance(command, Mapping):
            raise SkillError(f"commands.{name} must be a mapping")
        argv = command.get("argv", [])
        if argv and (not isinstance(argv, list) or not all(isinstance(item, str) and item for item in argv)):
            raise SkillError(f"commands.{name}.argv must be a list of nonempty strings")
        env = command.get("env", {})
        if not isinstance(env, Mapping):
            raise SkillError(f"commands.{name}.env must be a mapping")
        forbidden = [key for key in env if SECRET_KEY.search(str(key))]
        if forbidden:
            raise SkillError(f"Do not store secrets in commands.{name}.env: {forbidden}")
    if beta_sweep is not None:
        sweep_command = commands.get("beta_sweep")
        final_command = commands.get("instance")
        if not isinstance(sweep_command, Mapping):
            raise SkillError("instance.beta_sweep requires commands.beta_sweep")
        sweep_argv = sweep_command.get("argv", [])
        sweep_outputs = sweep_command.get("expected_outputs", [])
        if "{beta}" not in "\n".join(str(item) for item in sweep_argv):
            raise SkillError("commands.beta_sweep.argv must use the {beta} placeholder")
        if "{beta_tag}" not in "\n".join(str(item) for item in sweep_outputs):
            raise SkillError("commands.beta_sweep.expected_outputs must use {beta_tag} to keep candidates separate")
        if not isinstance(final_command, Mapping) or "{selected_beta}" not in "\n".join(str(item) for item in final_command.get("argv", [])):
            raise SkillError("commands.instance.argv must use {selected_beta} when beta_sweep is configured")

    return {
        "pipeline_version": VERSION,
        "audited_at": now_iso(),
        "config_path": str(config_path),
        "config_sha256": config_digest(config),
        "project_id": project_id,
        "source": {
            "uri": source_uri,
            "resolved_local_path": str(local_source) if local_source else None,
            "shape_zyx": shape,
            "resolution_nm_zyx": resolution,
            "offset_vox_zyx": offset,
            "bbox_vox_zyx": bbox,
        },
        "model": {
            "repo_commit": revision,
            "checkpoint": checkpoint,
            "checkpoint_sha256_expected": expected_checkpoint_hash.lower(),
            "checkpoint_sha256_actual": checkpoint_actual,
            "target_resolution_nm_zyx": target,
        },
        "output_root": str(output_root),
        "status": "passed",
    }


def ceil_div(a: int, b: int) -> int:
    return (a + b - 1) // b


def map_bbox_between_grids(bbox: list[int], source_resolution: list[float], target_resolution: list[float]) -> list[int]:
    starts = [math.floor(bbox[i] * source_resolution[i] / target_resolution[i]) for i in range(3)]
    ends = [math.ceil(bbox[i + 3] * source_resolution[i] / target_resolution[i]) for i in range(3)]
    return starts + ends


def create_plan(config: Mapping[str, Any], config_path: Path) -> dict[str, Any]:
    source = require_mapping(config, "source")
    profile = require_mapping(require_mapping(config, "model"), "profile")
    planning = require_mapping(config, "planning")
    source_shape = [int(v) for v in source["shape_zyx"]]
    source_resolution = [float(v) for v in source["resolution_nm_zyx"]]
    source_offset = [int(v) for v in source.get("offset_vox_zyx", [0, 0, 0])]
    source_bbox = [int(v) for v in source.get("bbox_vox_zyx", [0, 0, 0, *source_shape])]
    selected_shape = [source_bbox[i + 3] - source_bbox[i] for i in range(3)]
    target = [float(v) for v in profile["target_resolution_nm_zyx"]]
    physical_extent = [selected_shape[i] * source_resolution[i] for i in range(3)]
    model_shape = [max(1, round(physical_extent[i] / target[i])) for i in range(3)]
    model_extent = [model_shape[i] * target[i] for i in range(3)]
    end_error = [model_extent[i] - physical_extent[i] for i in range(3)]
    maximum_allowed = float(planning.get("max_end_error_nm", 0.51 * max(target)))
    if max(abs(item) for item in end_error) > maximum_allowed:
        raise SkillError(f"Model-grid end error {end_error} nm exceeds planning.max_end_error_nm={maximum_allowed}")

    core = [int(v) for v in planning["tile_core_zyx"]]
    halo = [int(v) for v in profile["halo_zyx"]]
    counts = [ceil_div(model_shape[i], core[i]) for i in range(3)]
    tiles: list[dict[str, Any]] = []
    for iz, iy, ix in itertools.product(range(counts[0]), range(counts[1]), range(counts[2])):
        index = [iz, iy, ix]
        core_start = [index[i] * core[i] for i in range(3)]
        core_end = [min(core_start[i] + core[i], model_shape[i]) for i in range(3)]
        read_start = [max(0, core_start[i] - halo[i]) for i in range(3)]
        read_end = [min(model_shape[i], core_end[i] + halo[i]) for i in range(3)]
        tiles.append({
            "id": f"z{iz:05d}_y{iy:05d}_x{ix:05d}",
            "index_zyx": index,
            "read_bbox_model_zyx": read_start + read_end,
            "core_bbox_model_zyx": core_start + core_end,
            "status": "pending",
        })

    model_pilot_rois = [
        map_bbox_between_grids([int(v) for v in roi], source_resolution, target)
        for roi in planning["pilot_rois"]
    ]
    voxels = math.prod(model_shape)
    affinity_bytes = voxels * int(planning.get("estimated_bytes_per_affinity_voxel", 12))
    instance_bytes = voxels * int(planning.get("estimated_bytes_per_instance_voxel", 8))
    physical_origin = [(source_offset[i] + source_bbox[i]) * source_resolution[i] for i in range(3)]
    return {
        "pipeline_version": VERSION,
        "planned_at": now_iso(),
        "config_sha256": config_digest(config),
        "canonical_axis_order": "zyx",
        "source_grid": {
            "shape_zyx": selected_shape,
            "resolution_nm_zyx": source_resolution,
            "offset_vox_zyx": [source_offset[i] + source_bbox[i] for i in range(3)],
            "physical_origin_nm_zyx": physical_origin,
            "physical_extent_nm_zyx": physical_extent,
        },
        "model_grid": {
            "shape_zyx": model_shape,
            "resolution_nm_zyx": target,
            "physical_origin_nm_zyx": physical_origin,
            "physical_extent_nm_zyx": model_extent,
            "end_error_nm_zyx": end_error,
        },
        "source_to_model_scale_zyx": [source_resolution[i] / target[i] for i in range(3)],
        "model_to_source_scale_zyx": [target[i] / source_resolution[i] for i in range(3)],
        "tiling": {
            "core_zyx": core,
            "halo_zyx": halo,
            "count_zyx": counts,
            "tile_count": len(tiles),
            "tiles": tiles,
        },
        "pilot": {
            "source_bboxes_zyx": planning["pilot_rois"],
            "model_bboxes_zyx": model_pilot_rois,
        },
        "estimates": {
            "model_voxels": voxels,
            "affinity_bytes": affinity_bytes,
            "instance_bytes": instance_bytes,
            "affinity_plus_instance_bytes": affinity_bytes + instance_bytes,
        },
        "status": "planned",
    }


class StrictFormat(dict[str, Any]):
    def __missing__(self, key: str) -> Any:
        raise SkillError(f"Unknown command placeholder: {{{key}}}")


def command_context(config: Mapping[str, Any], config_path: Path) -> dict[str, str]:
    model = require_mapping(config, "model")
    source = require_mapping(config, "source")
    root = resolve_output_root(config, config_path)
    return {
        "config_path": str(config_path),
        "output_root": str(root),
        "plan_path": str(state_dir(config, config_path) / "plan.json"),
        "pilot_path": str(state_dir(config, config_path) / "pilot.json"),
        "source_uri": str(source["uri"]),
        "checkpoint": str(model["checkpoint"]),
        "repo_path": str(model.get("repo_path", "")),
    }


def beta_values(config: Mapping[str, Any]) -> list[float]:
    instance = require_mapping(config, "instance")
    sweep = instance.get("beta_sweep")
    if not isinstance(sweep, Mapping):
        return []
    values = sweep.get("values", [])
    return [float(value) for value in values]


def beta_tag(beta: float) -> str:
    value = format(beta, ".12g")
    return value.replace("-", "m").replace(".", "p")


def beta_selection(config: Mapping[str, Any], config_path: Path) -> dict[str, Any]:
    path = state_dir(config, config_path) / "beta-selection.json"
    if not path.exists():
        raise SkillError("No beta has been selected. Run select-beta before instance.")
    selection = json.loads(path.read_text(encoding="utf-8"))
    if selection.get("config_sha256") != config_digest(config):
        raise SkillError("Beta selection belongs to a different configuration; rerun beta-sweep and select-beta")
    selected = selection.get("selected_beta")
    if isinstance(selected, bool) or not isinstance(selected, (int, float)):
        raise SkillError("Invalid beta selection record")
    if not any(math.isclose(float(selected), value, rel_tol=0, abs_tol=1e-12) for value in beta_values(config)):
        raise SkillError("Selected beta is no longer present in instance.beta_sweep.values")
    return selection


def expected_paths(operation: Mapping[str, Any], config: Mapping[str, Any], config_path: Path, context: Mapping[str, str]) -> list[Path]:
    values = operation.get("expected_outputs", [])
    if not isinstance(values, list) or not all(isinstance(v, str) and v for v in values):
        raise SkillError("expected_outputs must be a list of nonempty strings")
    root = resolve_output_root(config, config_path)
    paths: list[Path] = []
    for value in values:
        rendered = value.format_map(StrictFormat(context))
        path = Path(rendered)
        paths.append(path.resolve() if path.is_absolute() else (root / path).resolve())
    return paths


def render_job(
    operation_name: str,
    config: Mapping[str, Any],
    config_path: Path,
    context_overrides: Mapping[str, str] | None = None,
) -> tuple[dict[str, Any], Mapping[str, Any]]:
    commands = require_mapping(config, "commands")
    operation = commands.get(operation_name)
    if not isinstance(operation, Mapping):
        raise SkillError(f"No commands.{operation_name} adapter is configured")
    argv_source = operation.get("argv", [])
    if not isinstance(argv_source, list) or not argv_source:
        raise SkillError(f"commands.{operation_name}.argv is empty")
    if not all(isinstance(item, str) and item for item in argv_source):
        raise SkillError(f"commands.{operation_name}.argv must contain nonempty strings")
    context = command_context(config, config_path)
    context.update(dict(context_overrides or {}))
    argv = [item.format_map(StrictFormat(context)) for item in argv_source]
    cwd_value = str(operation.get("cwd", config_path.parent)).format_map(StrictFormat(context))
    cwd = resolve_local(cwd_value, config_path.parent)
    env_source = operation.get("env", {})
    if not isinstance(env_source, Mapping):
        raise SkillError(f"commands.{operation_name}.env must be a mapping")
    env = {str(k): str(v).format_map(StrictFormat(context)) for k, v in env_source.items()}
    if any(SECRET_KEY.search(key) for key in env):
        raise SkillError("Secret-like environment keys are forbidden in project configuration")
    outputs = expected_paths(operation, config, config_path, context)
    job = {
        "pipeline_version": VERSION,
        "operation": operation_name,
        "created_at": now_iso(),
        "config_sha256": config_digest(config),
        "argv": argv,
        "cwd": str(cwd),
        "env_keys": sorted(env),
        "expected_outputs": [str(path) for path in outputs],
        "status": "planned",
    }
    return job, operation


def run_job(
    operation_name: str,
    config: Mapping[str, Any],
    config_path: Path,
    execute: bool,
    *,
    context_overrides: Mapping[str, str] | None = None,
    record_name: str | None = None,
) -> dict[str, Any]:
    job, operation = render_job(operation_name, config, config_path, context_overrides)
    skill_state = state_dir(config, config_path)
    record_name = record_name or operation_name
    job_path = skill_state / "jobs" / f"{record_name}.json"
    write_json(job_path, job)
    if not execute:
        return job

    cwd = Path(job["cwd"])
    if not cwd.exists() or not cwd.is_dir():
        raise SkillError(f"Command working directory does not exist: {cwd}")
    outputs = [Path(value) for value in job["expected_outputs"]]
    allow_overwrite = bool(require_mapping(config, "output").get("allow_overwrite", False))
    existing = [str(path) for path in outputs if path.exists()]
    if existing and not allow_overwrite:
        raise SkillError(f"Refusing to overwrite existing expected outputs: {existing}")

    context = command_context(config, config_path)
    context.update(dict(context_overrides or {}))
    environment = os.environ.copy()
    environment.update({
        str(k): str(v).format_map(StrictFormat(context))
        for k, v in operation.get("env", {}).items()
    })
    started = now_iso()
    completed = subprocess.run(
        job["argv"], cwd=str(cwd), env=environment, shell=False,
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    run_id = dt.datetime.now().strftime("%Y%m%dT%H%M%S")
    log_root = skill_state / "runs" / f"{record_name}-{run_id}"
    log_root.mkdir(parents=True, exist_ok=True)
    (log_root / "stdout.txt").write_text(completed.stdout, encoding="utf-8")
    (log_root / "stderr.txt").write_text(completed.stderr, encoding="utf-8")
    missing = [str(path) for path in outputs if not path.exists()]
    status = "completed" if completed.returncode == 0 and not missing else "failed"
    run_record = {
        **job,
        "status": status,
        "started_at": started,
        "completed_at": now_iso(),
        "returncode": completed.returncode,
        "missing_expected_outputs": missing,
        "stdout_log": str(log_root / "stdout.txt"),
        "stderr_log": str(log_root / "stderr.txt"),
    }
    write_json(log_root / "run.json", run_record)
    if status != "completed":
        raise SkillError(f"{operation_name} failed with return code {completed.returncode}; missing outputs: {missing}")
    return run_record


def artifact_path(config: Mapping[str, Any], config_path: Path, value: str) -> Path | None:
    if is_remote(value):
        return None
    candidate = Path(value)
    if candidate.is_absolute():
        return candidate.resolve()
    return (resolve_output_root(config, config_path) / candidate).resolve()


def verify_project(config: Mapping[str, Any], config_path: Path) -> dict[str, Any]:
    verification = require_mapping(config, "verification")
    instance = require_mapping(config, "instance")
    output = require_mapping(config, "output")
    checks: dict[str, Any] = {}

    required = verification.get("required_artifacts", [])
    if not isinstance(required, list):
        raise SkillError("verification.required_artifacts must be a list")
    missing: list[str] = []
    present: list[str] = []
    for value in required:
        if not isinstance(value, str) or not value:
            raise SkillError("verification.required_artifacts entries must be nonempty strings")
        path = artifact_path(config, config_path, value)
        if path is None:
            present.append(value + " (remote, existence not checked by local runner)")
        elif path.exists():
            present.append(str(path))
        else:
            missing.append(str(path))
    checks["required_artifacts"] = {"passed": not missing, "present": present, "missing": missing}

    declared = verification.get("checks", {})
    if not isinstance(declared, Mapping):
        raise SkillError("verification.checks must be a mapping")
    required_bools = ("bounds_match", "dtype_safe", "ids_valid", "seams_reviewed", "provenance_complete", "orthogonal_views_reviewed")
    false_or_missing = [name for name in required_bools if declared.get(name) is not True]
    checks["declared_checks"] = {"passed": not false_or_missing, "false_or_missing": false_or_missing}

    pilot_approved = verification.get("pilot_approved") is True
    severe_issue_count = verification.get("severe_issue_count")
    severe_ok = isinstance(severe_issue_count, int) and not isinstance(severe_issue_count, bool) and severe_issue_count == 0
    checks["review"] = {
        "passed": pilot_approved and severe_ok,
        "pilot_approved": pilot_approved,
        "severe_issue_count": severe_issue_count,
    }

    reconciliation = require_mapping(instance, "global_reconciliation")
    reconciliation_ok = True
    reconciliation_note = "not required"
    if instance.get("scope") == "per-block":
        configured_artifact = reconciliation.get("artifact")
        reconciliation_ok = reconciliation.get("completed") is True and isinstance(configured_artifact, str) and bool(configured_artifact)
        if reconciliation_ok:
            path = artifact_path(config, config_path, configured_artifact)
            if path is not None:
                reconciliation_ok = path.exists()
                reconciliation_note = str(path)
            else:
                reconciliation_note = configured_artifact + " (remote, existence not checked)"
        else:
            reconciliation_note = "completion flag or artifact is missing"
    checks["global_reconciliation"] = {"passed": reconciliation_ok, "note": reconciliation_note}

    output_contract_missing = [name for name in ("affinity_uri", "instance_model_grid_uri", "instance_source_grid_uri") if not output.get(name)]
    checks["output_contract"] = {"passed": not output_contract_missing, "missing_fields": output_contract_missing}

    passed = all(section.get("passed") is True for section in checks.values())
    return {
        "pipeline_version": VERSION,
        "verified_at": now_iso(),
        "config_sha256": config_digest(config),
        "passed": passed,
        "checks": checks,
    }


def make_delivery_manifest(config: Mapping[str, Any], config_path: Path) -> dict[str, Any]:
    require_stage(config, config_path, "verify")
    verification_path = state_dir(config, config_path) / "verification.json"
    verification = json.loads(verification_path.read_text(encoding="utf-8"))
    if verification.get("passed") is not True:
        raise SkillError("Verification did not pass; delivery cannot be finalized")
    state = read_state(config, config_path)
    output = require_mapping(config, "output")
    artifacts = {
        "configuration": str(config_path),
        "audit": str(state_dir(config, config_path) / "audit.json"),
        "plan": str(state_dir(config, config_path) / "plan.json"),
        "pilot": str(state_dir(config, config_path) / "pilot.json"),
        "verification": str(verification_path),
        "affinity": output.get("affinity_uri"),
        "instance_model_grid": output.get("instance_model_grid_uri"),
        "instance_source_grid": output.get("instance_source_grid_uri"),
    }
    return {
        "pipeline_version": VERSION,
        "finalized_at": now_iso(),
        "project_id": require_mapping(config, "project").get("id"),
        "config_sha256": config_digest(config),
        "artifacts": artifacts,
        "pipeline_state": state,
        "status": "finalized",
    }


def scaffold(destination: Path) -> None:
    if destination.exists():
        raise SkillError(f"Refusing to overwrite existing file: {destination}")
    assets = Path(__file__).resolve().parent.parent / "assets"
    source = assets / ("project.example.json" if destination.suffix.lower() == ".json" else "project.example.yaml")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)


def cmd_audit(config: Mapping[str, Any], config_path: Path) -> dict[str, Any]:
    report = audit_config(config, config_path)
    path = state_dir(config, config_path) / "audit.json"
    write_json(path, report)
    update_state(config, config_path, "audit", "completed", path)
    return report


def cmd_plan(config: Mapping[str, Any], config_path: Path) -> dict[str, Any]:
    require_stage(config, config_path, "audit")
    audit_config(config, config_path)
    report = create_plan(config, config_path)
    path = state_dir(config, config_path) / "plan.json"
    write_json(path, report)
    update_state(config, config_path, "plan", "completed", path, {"tile_count": report["tiling"]["tile_count"]})
    return report


def cmd_pilot(config: Mapping[str, Any], config_path: Path, execute: bool) -> dict[str, Any]:
    require_stage(config, config_path, "plan")
    plan_path = state_dir(config, config_path) / "plan.json"
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    report: dict[str, Any] = {
        "pipeline_version": VERSION,
        "created_at": now_iso(),
        "source_bboxes_zyx": plan["pilot"]["source_bboxes_zyx"],
        "model_bboxes_zyx": plan["pilot"]["model_bboxes_zyx"],
        "review_required": ["xy_xz_yz_alignment", "affinities", "splits", "merges", "fragments", "seams", "foreground_leakage"],
        "status": "awaiting_review",
    }
    commands = config.get("commands", {})
    if isinstance(commands, Mapping) and isinstance(commands.get("pilot"), Mapping) and commands["pilot"].get("argv"):
        report["job"] = run_job("pilot", config, config_path, execute)
        if execute:
            report["status"] = "executed_awaiting_review"
    path = state_dir(config, config_path) / "pilot.json"
    write_json(path, report)
    update_state(config, config_path, "pilot", "awaiting_review", path)
    return report


def cmd_beta_sweep(config: Mapping[str, Any], config_path: Path, execute: bool) -> dict[str, Any]:
    require_stage(config, config_path, "infer", ("completed", "planned" if not execute else "completed"))
    values = beta_values(config)
    if len(values) < 2:
        raise SkillError("Configure at least two instance.beta_sweep.values before beta-sweep")
    jobs: list[dict[str, Any]] = []
    for value in values:
        tag = beta_tag(value)
        job = run_job(
            "beta_sweep",
            config,
            config_path,
            execute,
            context_overrides={"beta": format(value, ".12g"), "beta_tag": tag},
            record_name=f"beta-sweep-{tag}",
        )
        jobs.append({"beta": value, "beta_tag": tag, "job": job})
    report = {
        "pipeline_version": VERSION,
        "created_at": now_iso(),
        "config_sha256": config_digest(config),
        "candidates": jobs,
        "selection_required": True,
        "status": "completed" if execute else "planned",
    }
    path = state_dir(config, config_path) / "beta-sweep.json"
    write_json(path, report)
    update_state(config, config_path, "beta-sweep", report["status"], path, {"betas": values})
    return report


def cmd_select_beta(config: Mapping[str, Any], config_path: Path, selected_beta: float) -> dict[str, Any]:
    require_stage(config, config_path, "beta-sweep", ("completed",))
    values = beta_values(config)
    matches = [value for value in values if math.isclose(value, selected_beta, rel_tol=0, abs_tol=1e-12)]
    if not matches:
        raise SkillError(f"beta {selected_beta} is not one of the configured candidates: {values}")
    sweep_path = state_dir(config, config_path) / "beta-sweep.json"
    sweep = json.loads(sweep_path.read_text(encoding="utf-8"))
    candidate = next(
        (item for item in sweep.get("candidates", []) if math.isclose(float(item["beta"]), matches[0], rel_tol=0, abs_tol=1e-12)),
        None,
    )
    if candidate is None:
        raise SkillError("Selected beta candidate is absent from beta-sweep.json; rerun beta-sweep")
    missing = [value for value in candidate["job"].get("expected_outputs", []) if not Path(value).exists()]
    if missing:
        raise SkillError(f"Selected beta candidate is incomplete; missing outputs: {missing}")
    report = {
        "pipeline_version": VERSION,
        "selected_at": now_iso(),
        "config_sha256": config_digest(config),
        "selected_beta": matches[0],
        "selected_beta_tag": beta_tag(matches[0]),
        "candidate_outputs": candidate["job"].get("expected_outputs", []),
        "selected_by": "user",
        "status": "completed",
    }
    path = state_dir(config, config_path) / "beta-selection.json"
    write_json(path, report)
    update_state(config, config_path, "select-beta", "completed", path, {"selected_beta": matches[0]})
    return report


def cmd_operation(name: str, config: Mapping[str, Any], config_path: Path, execute: bool) -> dict[str, Any]:
    context_overrides: dict[str, str] = {}
    if name == "infer":
        require_stage(config, config_path, "plan")
        require_stage(config, config_path, "pilot", ("awaiting_review",))
        if require_mapping(config, "verification").get("pilot_approved") is not True:
            raise SkillError("verification.pilot_approved must be true before full inference")
    elif name == "instance":
        require_stage(config, config_path, "infer", ("completed", "planned" if not execute else "completed"))
        if beta_values(config):
            selection = beta_selection(config, config_path)
            selected = float(selection["selected_beta"])
            context_overrides = {"selected_beta": format(selected, ".12g"), "selected_beta_tag": beta_tag(selected)}
    elif name == "reconcile":
        if require_mapping(config, "instance").get("scope") != "per-block":
            raise SkillError("reconcile is only valid for instance.scope=per-block")
        require_stage(config, config_path, "instance", ("completed", "planned" if not execute else "completed"))
    elif name == "restore":
        instance = require_mapping(config, "instance")
        if instance.get("scope") == "per-block":
            require_stage(config, config_path, "reconcile", ("completed", "planned" if not execute else "completed"))
        else:
            require_stage(config, config_path, "instance", ("completed", "planned" if not execute else "completed"))
    result = run_job(name, config, config_path, execute, context_overrides=context_overrides)
    status = "completed" if execute else "planned"
    job_path = state_dir(config, config_path) / "jobs" / f"{name}.json"
    update_state(config, config_path, name, status, job_path)
    return result


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", action="version", version=VERSION)
    subparsers = parser.add_subparsers(dest="command", required=True)
    scaffold_parser = subparsers.add_parser("scaffold", help="Copy the starter YAML/JSON project configuration")
    scaffold_parser.add_argument("config", type=Path)
    for command in ("audit", "plan", "pilot", "infer", "instance", "reconcile", "restore", "verify"):
        child = subparsers.add_parser(command)
        child.add_argument("config", type=Path)
        if command in {"pilot", "infer", "instance", "reconcile", "restore"}:
            child.add_argument("--execute", action="store_true", help="Execute the reviewed local command adapter")
    beta_sweep_parser = subparsers.add_parser("beta-sweep", help="Generate candidate instances for configured beta values")
    beta_sweep_parser.add_argument("config", type=Path)
    beta_sweep_parser.add_argument("--execute", action="store_true", help="Execute every reviewed beta candidate job")
    select_beta_parser = subparsers.add_parser("select-beta", help="Record the user's selected beta")
    select_beta_parser.add_argument("config", type=Path)
    select_beta_parser.add_argument("--beta", type=float, required=True)
    finalize_parser = subparsers.add_parser("finalize")
    finalize_parser.add_argument("config", type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        destination = args.config.resolve()
        if args.command == "scaffold":
            scaffold(destination)
            print(json.dumps({"created": str(destination)}, ensure_ascii=False, indent=2))
            return 0
        config = load_document(destination)
        if args.command == "audit":
            result = cmd_audit(config, destination)
        elif args.command == "plan":
            result = cmd_plan(config, destination)
        elif args.command == "pilot":
            result = cmd_pilot(config, destination, args.execute)
        elif args.command == "beta-sweep":
            result = cmd_beta_sweep(config, destination, args.execute)
        elif args.command == "select-beta":
            result = cmd_select_beta(config, destination, args.beta)
        elif args.command in {"infer", "instance", "reconcile", "restore"}:
            result = cmd_operation(args.command, config, destination, args.execute)
        elif args.command == "verify":
            result = verify_project(config, destination)
            path = state_dir(config, destination) / "verification.json"
            write_json(path, result)
            update_state(config, destination, "verify", "completed" if result["passed"] else "failed", path)
        elif args.command == "finalize":
            result = make_delivery_manifest(config, destination)
            path = state_dir(config, destination) / "delivery-manifest.json"
            write_json(path, result)
            update_state(config, destination, "finalize", "completed", path)
        else:
            raise SkillError(f"Unsupported command: {args.command}")
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (SkillError, json.JSONDecodeError, OSError, subprocess.SubprocessError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
