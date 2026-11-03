"""Audit/plan native backend jobs; execute explicitly configured argv lists."""
from __future__ import annotations
import argparse
import datetime
import json
from pathlib import Path
import re
import subprocess
import sys
from registration_common import digest_file, identity, load_project, read_json, read_plane, resolve, write_json

BACKENDS = {"sofima": {"sofima"}, "metroem-corgie": {"metroem", "corgie"}, "feabas": {"feabas"}}


def audit(project, group_id=None):
    path, cfg, output = load_project(project)
    records = []
    for group in cfg["groups"]:
        if group_id is not None and group["id"] != group_id:
            continue
        shape = dtype = None
        sections = []
        for s in group["sections"]:
            p = resolve(path.parent, s["path"])
            before = p.stat()
            a = read_plane(p)
            sha = digest_file(p)
            after = p.stat()
            if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                raise ValueError(f"Input changed during audit: {p}")
            if shape is None:
                shape, dtype = list(a.shape), str(a.dtype)
            if list(a.shape) != shape or str(a.dtype) != dtype:
                raise ValueError(f"Inconsistent section shape/dtype in {group['id']}")
            sections.append({"id": s["id"], "z_index": s["z_index"], "path": str(p), "bytes": after.st_size, "sha256": sha, "min": float(a.min()), "max": float(a.max()), "constant": bool(a.min() == a.max())})
        records.append({"id": group["id"], "shape_zyx": [len(sections), *shape], "dtype": dtype, "sections": sections})
    return {"status": "audited", "source_grid": {"axes": "zyx", "voxel_size_nm_xyz": cfg["voxel_size_nm_xyz"]}, "groups": records, "output_root": str(output), "note": "Content integrity and explicit order; not an alignment-quality decision"}


def make_plan(project, backend, group_id, stage):
    path, cfg, output = load_project(project)
    if backend not in BACKENDS or stage not in ("pilot", "full"):
        raise ValueError("Unknown backend or stage")
    group = next((g for g in cfg["groups"] if g["id"] == group_id), None)
    if group is None:
        raise ValueError("Unknown independent group")
    spec = cfg.get("backends", {}).get(backend, {})
    jobs = spec.get("stages", {}).get(stage, [])
    run_dir = output / group_id / backend / stage
    tokens = {"project": str(path), "group": group_id, "run_dir": str(run_dir), "python": spec.get("python", sys.executable)}
    commands = []
    for job in jobs:
        if not isinstance(job.get("argv"), list) or not job["argv"] or any(not isinstance(v, str) or not v for v in job["argv"]):
            raise ValueError("Commands must be nonempty argv string arrays, never shell text")
        def expand(text):
            for key, value in tokens.items():
                text = text.replace("{" + key + "}", value)
            if re.search(r"\{[A-Za-z_][A-Za-z0-9_]*\}", text):
                raise ValueError(f"Unresolved command token: {text}")
            return text
        expected = job.get("expected_outputs", [])
        if not expected:
            raise ValueError("Each command must declare expected native outputs")
        cwd = resolve(path.parent, expand(job.get("cwd", str(run_dir))))
        outputs = [resolve(cwd, expand(p)) for p in expected]
        if any(run_dir not in p.parents for p in outputs):
            raise ValueError("Expected outputs must be descendants of this group's backend/stage run directory")
        commands.append({"argv": [expand(v) for v in job["argv"]], "cwd": str(cwd), "expected_outputs": [str(p) for p in outputs]})
    repositories = spec.get("repositories", [])
    names = {r.get("name") for r in repositories}
    unresolved = []
    if not BACKENDS[backend].issubset(names):
        unresolved.append("Pin every required upstream repository")
    for repo in repositories:
        if not re.fullmatch(r"[0-9a-fA-F]{40}", repo.get("commit", "")) or not repo.get("path"):
            unresolved.append("Repository path and full commit SHA required")
    if not commands:
        unresolved.append(f"Configure native {stage} commands from references/{backend}.md")
    models = spec.get("models", [])
    if backend == "metroem-corgie" and (not models or not spec.get("model_resolution_nm_xy")):
        unresolved.append("SEAMLeSS requires checkpoint SHA256 and documented physical input scale")
    for model in models:
        if not re.fullmatch(r"[0-9a-fA-F]{64}", model.get("sha256", "")) or not model.get("path"):
            unresolved.append("Model checkpoint path/SHA256 missing")
    return {"schema_version": 1, "status": "needs_configuration" if unresolved else "planned", "backend": backend, "group": group_id, "stage": stage, "run_dir": str(run_dir), "project": str(path), "project_sha256": digest_file(path), "voxel_size_nm_xyz": cfg["voxel_size_nm_xyz"], "section_order": [s["id"] for s in group["sections"]], "commands": commands, "repositories": repositories, "models": models, "unresolved": unresolved, "scope": "Native command execution; result/QC/export acceptance is separate"}


def run(project, backend, group, stage):
    plan = make_plan(project, backend, group, stage)
    if plan["status"] != "planned":
        raise ValueError("; ".join(plan["unresolved"]))
    base = Path(plan["project"]).parent
    for repo in plan["repositories"]:
        root = resolve(base, repo["path"])
        head = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()
        dirty = subprocess.check_output(["git", "-C", str(root), "status", "--porcelain", "--untracked-files=no"], text=True).strip()
        if head.lower() != repo["commit"].lower() or dirty:
            raise ValueError(f"Pinned source mismatch or tracked edits: {root}")
    for model in plan["models"]:
        if digest_file(resolve(base, model["path"])) != model["sha256"].lower():
            raise ValueError("Checkpoint SHA256 mismatch")
    selected = audit(project, group)["groups"][0]
    run_dir = Path(plan["run_dir"])
    command_files = {}
    for command in plan["commands"]:
        for arg in command["argv"]:
            try:
                p = resolve(command["cwd"], arg)
                if p.is_file() and run_dir not in p.parents:
                    command_files[str(p)] = digest_file(p)
            except OSError:
                pass  # An argv JSON processor specification is not a filesystem path.
    fingerprint = identity({"plan": plan, "source": selected, "command_files": command_files})
    lock = run_dir / "run-identity.json"
    if run_dir.exists() and not lock.exists() and any(run_dir.iterdir()):
        raise ValueError("Untracked existing output; inspect or choose a new run directory")
    if lock.exists() and read_json(lock)["identity"] != fingerprint:
        raise ValueError("Source/configuration/code changed; use a new run instead of stale checkpoints")
    run_dir.mkdir(parents=True, exist_ok=True)
    write_json(lock, {"identity": fingerprint, "plan": plan, "source": selected, "command_files": command_files})
    write_json(run_dir / "ordered-sections.json", selected)
    for i, command in enumerate(plan["commands"]):
        if not Path(command["cwd"]).is_dir():
            raise ValueError(f"Working directory is missing: {command['cwd']}")
        with (run_dir / f"command-{i:02d}.log").open("ab") as stream:
            completed = subprocess.run(command["argv"], cwd=command["cwd"], stdin=subprocess.DEVNULL, stdout=stream, stderr=subprocess.STDOUT, shell=False, check=False)
        if completed.returncode:
            write_json(run_dir / "execution.json", {"status": "failed", "command": i, "returncode": completed.returncode})
            raise RuntimeError(f"Backend command {i} failed; inspect its log before retrying")
        if any(not Path(p).exists() for p in command["expected_outputs"]):
            raise ValueError(f"Backend command {i} did not produce declared artifacts")
    record = {"status": "native_commands_completed", "backend": backend, "group": group, "stage": stage, "identity": fingerprint, "completed_at": datetime.datetime.now(datetime.timezone.utc).isoformat(), "scientific_acceptance": "not_granted_by_command_exit_status"}
    write_json(run_dir / "execution.json", record)
    return record


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("mode", choices=["audit", "plan", "run"])
    p.add_argument("project")
    p.add_argument("--backend", choices=sorted(BACKENDS))
    p.add_argument("--group")
    p.add_argument("--stage", choices=["pilot", "full"], default="pilot")
    p.add_argument("--out")
    p.add_argument("--execute", action="store_true")
    a = p.parse_args()
    if a.mode == "audit":
        result = audit(a.project)
    else:
        if not a.backend or not a.group:
            p.error("--backend and --group are required")
        result = run(a.project, a.backend, a.group, a.stage) if a.mode == "run" and a.execute else make_plan(a.project, a.backend, a.group, a.stage)
    if a.out:
        write_json(a.out, result)
    print(json.dumps(result, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
