#!/usr/bin/env python3
"""Fail-closed orchestration for external MitoNet/Empanada inference."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from typing import Any, Iterable, Mapping


VERSION = "0.1.0"
HEX64 = re.compile(r"^[0-9a-fA-F]{64}$")
SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
SECRET_KEY = re.compile(r"(?:TOKEN|PASSWORD|PASSWD|SECRET|PRIVATE_KEY|ACCESS_KEY)", re.I)


class SkillError(RuntimeError):
    pass


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def config_digest(config: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json(config).encode("utf-8")).hexdigest()


def load_document(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise SkillError(f"Configuration not found: {path}")
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json":
        value = json.loads(text)
    else:
        try:
            import yaml
        except ImportError as exc:
            raise SkillError("YAML requires PyYAML; JSON is supported without it") from exc
        value = yaml.safe_load(text)
    if not isinstance(value, dict):
        raise SkillError("Configuration root must be a mapping")
    return value


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def mapping(root: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = root.get(key)
    if not isinstance(value, Mapping):
        raise SkillError(f"Missing or invalid mapping: {key}")
    return value


def text(root: Mapping[str, Any], key: str, context: str) -> str:
    value = root.get(key)
    if not isinstance(value, str) or not value.strip():
        raise SkillError(f"Missing or invalid {context}.{key}")
    return value.strip()


def vector(value: Any, length: int, context: str, *, integer: bool = False, positive: bool = False) -> list[Any]:
    if not isinstance(value, list) or len(value) != length:
        raise SkillError(f"{context} must be a list of length {length}")
    result = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            raise SkillError(f"{context} must contain numbers")
        converted = int(item) if integer else float(item)
        if integer and converted != float(item):
            raise SkillError(f"{context} must contain integers")
        if positive and converted <= 0:
            raise SkillError(f"{context} must contain positive values")
        result.append(converted)
    return result


def resolve_local(value: str, base: Path) -> Path:
    candidate = Path(os.path.expandvars(value)).expanduser()
    return candidate.resolve() if candidate.is_absolute() else (base / candidate).resolve()


def output_root(config: Mapping[str, Any], config_path: Path) -> Path:
    return resolve_local(text(mapping(config, "output"), "root", "output"), config_path.parent)


def state_dir(config: Mapping[str, Any], config_path: Path) -> Path:
    return output_root(config, config_path) / "_mitonet_skill"


def read_state(config: Mapping[str, Any], config_path: Path) -> dict[str, Any]:
    path = state_dir(config, config_path) / "state.json"
    if path.exists():
        value = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(value, dict):
            return value
    return {"pipeline_version": VERSION, "stages": {}}


def update_state(config: Mapping[str, Any], config_path: Path, stage: str, status: str, artifact: Path | None = None) -> None:
    state = read_state(config, config_path)
    state["pipeline_version"] = VERSION
    state["config_sha256"] = config_digest(config)
    state.setdefault("stages", {})[stage] = {"status": status, "updated_at": now_iso(), "artifact": str(artifact) if artifact else None}
    write_json(state_dir(config, config_path) / "state.json", state)


def require_stage(config: Mapping[str, Any], config_path: Path, stage: str, statuses: Iterable[str] = ("completed",)) -> None:
    actual = read_state(config, config_path).get("stages", {}).get(stage, {}).get("status")
    if actual not in set(statuses):
        raise SkillError(f"Stage {stage!r} must be {sorted(set(statuses))}; current status is {actual!r}")


def validate_bbox(bbox: list[int], shape: list[int], context: str) -> None:
    for axis, (start, end, maximum) in enumerate(zip(bbox[:3], bbox[3:], shape)):
        if start < 0 or end <= start or end > maximum:
            raise SkillError(f"Invalid {context} on zyx axis {axis}: [{start}, {end}) outside [0, {maximum})")


PROFILE_FIELDS = {
    "median_kernel", "segmentation_confidence", "center_confidence", "center_min_distance",
    "merge_iou", "merge_ioa", "pixel_vote", "cluster_iou", "allow_one_view",
    "fine_boundaries", "min_size_vox", "min_span_slices", "label_divisor",
    "downsample_factor",
}


def profiles(config: Mapping[str, Any]) -> Mapping[str, Mapping[str, Any]]:
    value = mapping(mapping(config, "inference"), "profiles")
    return value  # type: ignore[return-value]


def audit_config(config: Mapping[str, Any], config_path: Path) -> dict[str, Any]:
    project_id = text(mapping(config, "project"), "id", "project")
    if not SAFE_NAME.fullmatch(project_id):
        raise SkillError("project.id must be filesystem-safe")
    source = mapping(config, "source")
    source_uri = text(source, "uri", "source")
    if source_uri.startswith(("http://", "https://", "s3://", "gs://", "precomputed://")):
        source_path = None
    else:
        source_path = resolve_local(source_uri, config_path.parent)
        if not source_path.exists():
            raise SkillError(f"Local source does not exist: {source_path}")
    axes = text(source, "axis_order", "source").lower()
    if sorted(axes) != ["x", "y", "z"]:
        raise SkillError("source.axis_order must contain x, y, z exactly once")
    shape = vector(source.get("shape_zyx"), 3, "source.shape_zyx", integer=True, positive=True)
    resolution = vector(source.get("resolution_nm_zyx"), 3, "source.resolution_nm_zyx", positive=True)
    bbox = vector(source.get("bbox_vox_zyx", [0, 0, 0, *shape]), 6, "source.bbox_vox_zyx", integer=True)
    validate_bbox(bbox, shape, "source.bbox_vox_zyx")
    if source.get("read_only") is not True:
        raise SkillError("source.read_only must be true")
    text(source, "identity", "source")

    model = mapping(config, "model")
    if text(model, "repository", "model") != "volume-em/empanada":
        raise SkillError("model.repository must identify the official volume-em/empanada repository")
    commit = text(model, "repo_commit", "model")
    if not re.fullmatch(r"[0-9a-fA-F]{40}", commit):
        raise SkillError("model.repo_commit must be an exact 40-character commit")
    if model.get("variant") not in {"MitoNet_v1", "MitoNet_v1_mini"}:
        raise SkillError("model.variant must be MitoNet_v1 or MitoNet_v1_mini")
    target = vector(model.get("target_resolution_nm_zyx"), 3, "model.target_resolution_nm_zyx", positive=True)
    z_policy = text(model, "z_policy", "model")
    if z_policy not in {"preserve", "explicit"}:
        raise SkillError("model.z_policy must be preserve or explicit")
    if z_policy == "preserve" and not math.isclose(target[0], resolution[0], abs_tol=1e-9):
        raise SkillError("z_policy is preserve but target z resolution changed")
    checked_hashes = {}
    for field in ("checkpoint", "model_config"):
        value = text(model, field, "model")
        expected = text(model, field + "_sha256", "model")
        if not HEX64.fullmatch(expected):
            raise SkillError(f"model.{field}_sha256 must contain 64 hexadecimal characters")
        path = resolve_local(value, config_path.parent)
        actual = sha256_file(path) if path.exists() and path.is_file() else None
        if actual and actual.lower() != expected.lower():
            raise SkillError(f"model.{field}_sha256 does not match {path}")
        checked_hashes[field] = actual

    planning = mapping(config, "planning")
    rois = planning.get("pilot_rois")
    if not isinstance(rois, list) or not rois:
        raise SkillError("planning.pilot_rois must contain at least one ROI")
    for index, roi in enumerate(rois):
        candidate = vector(roi, 6, f"planning.pilot_rois[{index}]", integer=True)
        validate_bbox(candidate, shape, f"planning.pilot_rois[{index}]")

    configured_profiles = profiles(config)
    if not configured_profiles:
        raise SkillError("inference.profiles cannot be empty")
    anisotropy = max(target) / min(target)
    for name, profile in configured_profiles.items():
        if not isinstance(name, str) or not SAFE_NAME.fullmatch(name) or not isinstance(profile, Mapping):
            raise SkillError("Every inference profile must have a safe name and mapping value")
        missing = PROFILE_FIELDS - set(profile)
        if missing:
            raise SkillError(f"inference.profiles.{name} is missing fields: {sorted(missing)}")
        if profile.get("mode") not in {"stack", "orthoplane"}:
            raise SkillError(f"inference.profiles.{name}.mode must be stack or orthoplane")
        if profile.get("mode") == "orthoplane" and anisotropy > 2 and mapping(config, "inference").get("orthoplane_reviewed") is not True:
            raise SkillError("Strongly anisotropic orthoplane inference requires inference.orthoplane_reviewed=true")
        if profile.get("median_kernel") not in {1, 3, 5, 7, 9, 11}:
            raise SkillError(f"inference.profiles.{name}.median_kernel must be an allowed odd value")
        for field in ("segmentation_confidence", "center_confidence", "merge_iou", "merge_ioa", "cluster_iou"):
            value = profile.get(field)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= float(value) <= 1:
                raise SkillError(f"inference.profiles.{name}.{field} must be between 0 and 1")
        if profile.get("pixel_vote") not in {1, 2, 3}:
            raise SkillError(f"inference.profiles.{name}.pixel_vote must be 1, 2, or 3")
        for field in ("center_min_distance", "min_size_vox", "min_span_slices", "label_divisor"):
            value = profile.get(field)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise SkillError(f"inference.profiles.{name}.{field} must be a positive integer")
        downsample = profile.get("downsample_factor")
        if isinstance(downsample, bool) or not isinstance(downsample, int) or downsample <= 0 or downsample & (downsample - 1):
            raise SkillError(f"inference.profiles.{name}.downsample_factor must be a positive power of two")

    output = mapping(config, "output")
    root = output_root(config, config_path)
    if source_path and (root == source_path or (source_path.is_dir() and source_path in root.parents)):
        raise SkillError("output.root must not equal or be nested inside the source directory")
    commands = mapping(config, "commands")
    for name, command in commands.items():
        if not isinstance(command, Mapping):
            raise SkillError(f"commands.{name} must be a mapping")
        argv = command.get("argv", [])
        if argv and (not isinstance(argv, list) or not all(isinstance(item, str) and item for item in argv)):
            raise SkillError(f"commands.{name}.argv must be a list of nonempty strings")
        env = command.get("env", {})
        if not isinstance(env, Mapping) or any(SECRET_KEY.search(str(key)) for key in env):
            raise SkillError(f"commands.{name}.env must be a non-secret mapping")
    return {
        "pipeline_version": VERSION, "audited_at": now_iso(), "status": "passed",
        "project_id": project_id, "config_sha256": config_digest(config),
        "source": {"uri": source_uri, "shape_zyx": shape, "resolution_nm_zyx": resolution, "bbox_vox_zyx": bbox},
        "model": {"repo_commit": commit, "variant": model["variant"], "target_resolution_nm_zyx": target, "verified_local_hashes": checked_hashes},
        "profiles": sorted(configured_profiles), "output_root": str(root),
    }


def create_plan(config: Mapping[str, Any]) -> dict[str, Any]:
    source, model, planning = mapping(config, "source"), mapping(config, "model"), mapping(config, "planning")
    shape = [int(value) for value in source["shape_zyx"]]
    bbox = [int(value) for value in source.get("bbox_vox_zyx", [0, 0, 0, *shape])]
    source_res = [float(value) for value in source["resolution_nm_zyx"]]
    target_res = [float(value) for value in model["target_resolution_nm_zyx"]]
    selected_shape = [bbox[i + 3] - bbox[i] for i in range(3)]
    extent = [selected_shape[i] * source_res[i] for i in range(3)]
    target_shape = [max(1, round(extent[i] / target_res[i])) for i in range(3)]
    target_extent = [target_shape[i] * target_res[i] for i in range(3)]
    error = [target_extent[i] - extent[i] for i in range(3)]
    maximum = float(planning.get("max_end_error_nm", max(target_res) * 0.51))
    if max(abs(value) for value in error) > maximum:
        raise SkillError(f"Model-grid end error {error} exceeds planning.max_end_error_nm={maximum}")
    return {
        "pipeline_version": VERSION, "planned_at": now_iso(), "status": "planned",
        "source_grid": {"shape_zyx": selected_shape, "resolution_nm_zyx": source_res, "physical_extent_nm_zyx": extent},
        "model_grid": {"shape_zyx": target_shape, "resolution_nm_zyx": target_res, "physical_extent_nm_zyx": target_extent, "end_error_nm_zyx": error},
        "source_to_model_scale_zyx": [source_res[i] / target_res[i] for i in range(3)],
        "pilot_source_bboxes_zyx": planning["pilot_rois"],
    }


class StrictFormat(dict[str, str]):
    def __missing__(self, key: str) -> str:
        raise SkillError(f"Unknown command placeholder: {{{key}}}")


def base_context(config: Mapping[str, Any], config_path: Path) -> dict[str, str]:
    model = mapping(config, "model")
    return {
        "config_path": str(config_path), "output_root": str(output_root(config, config_path)),
        "skill_path": str(Path(__file__).resolve().parent.parent), "repo_path": str(resolve_local(str(model["repo_path"]), config_path.parent)),
        "model_config": str(resolve_local(str(model["model_config"]), config_path.parent)), "checkpoint": str(resolve_local(str(model["checkpoint"]), config_path.parent)),
    }


def profile_context(name: str, profile: Mapping[str, Any]) -> dict[str, str]:
    result = {"profile": name}
    result.update({f"profile_{key}": str(value).lower() if isinstance(value, bool) else str(value) for key, value in profile.items()})
    return result


def render_job(operation_name: str, config: Mapping[str, Any], config_path: Path, overrides: Mapping[str, str] | None = None) -> tuple[dict[str, Any], Mapping[str, Any], dict[str, str]]:
    operation = mapping(config, "commands").get(operation_name)
    if not isinstance(operation, Mapping):
        raise SkillError(f"No commands.{operation_name} adapter is configured")
    argv_source = operation.get("argv", [])
    if not isinstance(argv_source, list) or not argv_source:
        raise SkillError(f"commands.{operation_name}.argv is empty")
    context = base_context(config, config_path)
    context.update(dict(overrides or {}))
    argv = [item.format_map(StrictFormat(context)) for item in argv_source]
    cwd = resolve_local(str(operation.get("cwd", config_path.parent)).format_map(StrictFormat(context)), config_path.parent)
    env_source = operation.get("env", {})
    env = {str(key): str(value).format_map(StrictFormat(context)) for key, value in env_source.items()}
    root = output_root(config, config_path)
    expected = []
    for value in operation.get("expected_outputs", []):
        rendered = str(value).format_map(StrictFormat(context))
        path = Path(rendered)
        expected.append(path.resolve() if path.is_absolute() else (root / path).resolve())
    return ({
        "pipeline_version": VERSION, "operation": operation_name, "created_at": now_iso(),
        "config_sha256": config_digest(config), "argv": argv, "cwd": str(cwd),
        "env_keys": sorted(env), "expected_outputs": [str(path) for path in expected], "status": "planned",
    }, operation, context)


def run_job(operation_name: str, config: Mapping[str, Any], config_path: Path, execute: bool, *, overrides: Mapping[str, str] | None = None, record_name: str | None = None) -> dict[str, Any]:
    job, operation, context = render_job(operation_name, config, config_path, overrides)
    name = record_name or operation_name
    job_path = state_dir(config, config_path) / "jobs" / f"{name}.json"
    write_json(job_path, job)
    if not execute:
        return job
    cwd = Path(job["cwd"])
    if not cwd.is_dir():
        raise SkillError(f"Command working directory does not exist: {cwd}")
    outputs = [Path(value) for value in job["expected_outputs"]]
    if not mapping(config, "output").get("allow_overwrite", False):
        existing = [str(path) for path in outputs if path.exists()]
        if existing:
            raise SkillError(f"Refusing to overwrite expected outputs: {existing}")
    environment = os.environ.copy()
    environment.update({str(key): str(value).format_map(StrictFormat(context)) for key, value in operation.get("env", {}).items()})
    started = now_iso()
    completed = subprocess.run(job["argv"], cwd=cwd, env=environment, shell=False, capture_output=True, text=True, encoding="utf-8", errors="replace")
    run_root = state_dir(config, config_path) / "runs" / f"{name}-{dt.datetime.now().strftime('%Y%m%dT%H%M%S')}"
    run_root.mkdir(parents=True, exist_ok=True)
    (run_root / "stdout.txt").write_text(completed.stdout, encoding="utf-8")
    (run_root / "stderr.txt").write_text(completed.stderr, encoding="utf-8")
    missing = [str(path) for path in outputs if not path.exists()]
    status = "completed" if completed.returncode == 0 and not missing else "failed"
    result = {**job, "status": status, "started_at": started, "completed_at": now_iso(), "returncode": completed.returncode, "missing_expected_outputs": missing, "stdout_log": str(run_root / "stdout.txt"), "stderr_log": str(run_root / "stderr.txt")}
    write_json(run_root / "run.json", result)
    if status != "completed":
        raise SkillError(f"{operation_name} failed with return code {completed.returncode}; missing outputs: {missing}")
    return result


def cmd_audit(config: Mapping[str, Any], path: Path) -> dict[str, Any]:
    result = audit_config(config, path)
    artifact = state_dir(config, path) / "audit.json"
    write_json(artifact, result); update_state(config, path, "audit", "completed", artifact)
    return result


def cmd_plan(config: Mapping[str, Any], path: Path) -> dict[str, Any]:
    require_stage(config, path, "audit"); audit_config(config, path)
    result = create_plan(config)
    artifact = state_dir(config, path) / "plan.json"
    write_json(artifact, result); update_state(config, path, "plan", "completed", artifact)
    return result


def cmd_simple(name: str, prerequisite: str, config: Mapping[str, Any], path: Path, execute: bool) -> dict[str, Any]:
    require_stage(config, path, prerequisite, ("completed", "planned" if not execute else "completed"))
    result = run_job(name, config, path, execute)
    artifact = state_dir(config, path) / "jobs" / f"{name}.json"
    update_state(config, path, name, "completed" if execute else "planned", artifact)
    return result


def cmd_pilot(config: Mapping[str, Any], path: Path, execute: bool) -> dict[str, Any]:
    require_stage(config, path, "prepare", ("completed", "planned" if not execute else "completed"))
    result: dict[str, Any] = {"created_at": now_iso(), "review_required": ["scale", "foreground", "false_positives", "merge_split", "z_continuity"], "status": "awaiting_review"}
    operation = mapping(config, "commands").get("pilot")
    if isinstance(operation, Mapping) and operation.get("argv"):
        result["job"] = run_job("pilot", config, path, execute)
    artifact = state_dir(config, path) / "pilot.json"
    write_json(artifact, result); update_state(config, path, "pilot", "awaiting_review", artifact)
    return result


def cmd_profile_sweep(config: Mapping[str, Any], path: Path, execute: bool) -> dict[str, Any]:
    require_stage(config, path, "pilot", ("awaiting_review",))
    candidates = []
    for name, profile in profiles(config).items():
        context = profile_context(name, profile)
        job = run_job("profile", config, path, execute, overrides=context, record_name=f"profile-{name}")
        candidates.append({"profile": name, "parameters": dict(profile), "job": job})
    result = {"created_at": now_iso(), "config_sha256": config_digest(config), "candidates": candidates, "selection_required": True, "status": "completed" if execute else "planned"}
    artifact = state_dir(config, path) / "profile-sweep.json"
    write_json(artifact, result); update_state(config, path, "profile-sweep", result["status"], artifact)
    return result


def cmd_select_profile(config: Mapping[str, Any], path: Path, name: str) -> dict[str, Any]:
    require_stage(config, path, "profile-sweep", ("completed",))
    if name not in profiles(config):
        raise SkillError(f"Unknown profile {name!r}; choose one of {sorted(profiles(config))}")
    sweep = json.loads((state_dir(config, path) / "profile-sweep.json").read_text(encoding="utf-8"))
    candidate = next((item for item in sweep.get("candidates", []) if item.get("profile") == name), None)
    if not candidate:
        raise SkillError("Selected profile is absent from profile-sweep.json")
    missing = [value for value in candidate["job"].get("expected_outputs", []) if not Path(value).exists()]
    if missing:
        raise SkillError(f"Selected profile is incomplete; missing outputs: {missing}")
    result = {"selected_at": now_iso(), "selected_by": "user", "selected_profile": name, "parameters": dict(profiles(config)[name]), "candidate_outputs": candidate["job"]["expected_outputs"], "config_sha256": config_digest(config), "status": "completed"}
    artifact = state_dir(config, path) / "profile-selection.json"
    write_json(artifact, result); update_state(config, path, "select-profile", "completed", artifact)
    return result


def selected_profile(config: Mapping[str, Any], path: Path) -> dict[str, Any]:
    artifact = state_dir(config, path) / "profile-selection.json"
    if not artifact.exists():
        raise SkillError("No profile selected; run select-profile before infer")
    value = json.loads(artifact.read_text(encoding="utf-8"))
    if value.get("config_sha256") != config_digest(config):
        raise SkillError("Profile selection belongs to a different configuration")
    return value


def cmd_infer(config: Mapping[str, Any], path: Path, execute: bool) -> dict[str, Any]:
    require_stage(config, path, "select-profile")
    if mapping(config, "verification").get("pilot_approved") is not True:
        raise SkillError("verification.pilot_approved must be true before final inference")
    selection = selected_profile(config, path)
    name = selection["selected_profile"]
    context = profile_context(name, profiles(config)[name])
    context["selected_profile"] = name
    result = run_job("infer", config, path, execute, overrides=context)
    artifact = state_dir(config, path) / "jobs" / "infer.json"
    update_state(config, path, "infer", "completed" if execute else "planned", artifact)
    return result


def verify(config: Mapping[str, Any], path: Path) -> dict[str, Any]:
    verification = mapping(config, "verification")
    root = output_root(config, path)
    required = verification.get("required_artifacts", [])
    missing = [str((root / value).resolve()) for value in required if not (root / value).exists()]
    declared = verification.get("checks", {})
    required_checks = ("bounds_match", "dtype_safe", "ids_valid", "z_continuity_reviewed", "false_positive_reviewed", "merge_split_reviewed", "provenance_complete")
    false_checks = [name for name in required_checks if not isinstance(declared, Mapping) or declared.get(name) is not True]
    severe = verification.get("severe_issue_count")
    review_ok = verification.get("pilot_approved") is True and isinstance(severe, int) and not isinstance(severe, bool) and severe == 0
    passed = not missing and not false_checks and review_ok
    return {"verified_at": now_iso(), "passed": passed, "checks": {"artifacts": {"passed": not missing, "missing": missing}, "declared": {"passed": not false_checks, "false_or_missing": false_checks}, "review": {"passed": review_ok, "pilot_approved": verification.get("pilot_approved") is True, "severe_issue_count": severe}}}


def finalize(config: Mapping[str, Any], path: Path) -> dict[str, Any]:
    require_stage(config, path, "verify")
    report = json.loads((state_dir(config, path) / "verification.json").read_text(encoding="utf-8"))
    if report.get("passed") is not True:
        raise SkillError("Verification did not pass")
    return {"finalized_at": now_iso(), "status": "finalized", "project_id": mapping(config, "project")["id"], "config_sha256": config_digest(config), "output": dict(mapping(config, "output")), "state": read_state(config, path)}


def scaffold(destination: Path) -> None:
    if destination.exists():
        raise SkillError(f"Refusing to overwrite {destination}")
    source = Path(__file__).resolve().parent.parent / "assets" / "project.example.yaml"
    destination.parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(source, destination)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    root = argparse.ArgumentParser(description=__doc__)
    root.add_argument("--version", action="version", version=VERSION)
    subs = root.add_subparsers(dest="command", required=True)
    for name in ("scaffold", "audit", "plan", "prepare", "pilot", "profile-sweep", "infer", "restore", "verify", "finalize"):
        child = subs.add_parser(name); child.add_argument("config", type=Path)
        if name in {"prepare", "pilot", "profile-sweep", "infer", "restore"}:
            child.add_argument("--execute", action="store_true")
    select = subs.add_parser("select-profile"); select.add_argument("config", type=Path); select.add_argument("--profile", required=True)
    return root.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        path = args.config.resolve()
        if args.command == "scaffold":
            scaffold(path); result = {"created": str(path)}
        else:
            config = load_document(path)
            if args.command == "audit": result = cmd_audit(config, path)
            elif args.command == "plan": result = cmd_plan(config, path)
            elif args.command == "prepare": result = cmd_simple("prepare", "plan", config, path, args.execute)
            elif args.command == "pilot": result = cmd_pilot(config, path, args.execute)
            elif args.command == "profile-sweep": result = cmd_profile_sweep(config, path, args.execute)
            elif args.command == "select-profile": result = cmd_select_profile(config, path, args.profile)
            elif args.command == "infer": result = cmd_infer(config, path, args.execute)
            elif args.command == "restore": result = cmd_simple("restore", "infer", config, path, args.execute)
            elif args.command == "verify":
                result = verify(config, path); artifact = state_dir(config, path) / "verification.json"; write_json(artifact, result); update_state(config, path, "verify", "completed" if result["passed"] else "failed", artifact)
            elif args.command == "finalize":
                result = finalize(config, path); artifact = state_dir(config, path) / "delivery-manifest.json"; write_json(artifact, result); update_state(config, path, "finalize", "completed", artifact)
            else: raise SkillError(f"Unsupported command: {args.command}")
        print(json.dumps(result, ensure_ascii=False, indent=2)); return 0
    except (SkillError, OSError, ValueError, json.JSONDecodeError, subprocess.SubprocessError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr); return 2


if __name__ == "__main__":
    raise SystemExit(main())
