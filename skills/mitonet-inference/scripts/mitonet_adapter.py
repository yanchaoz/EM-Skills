#!/usr/bin/env python3
"""Invoke the pinned official Empanada 3D inference entrypoint."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time


TRACKER_SIGNATURE_FIX_COMMIT = "01c6e7aa3ad0e3c3334df8b129b0122724b6ad2e"


def parse_bool(value: str | bool) -> bool:
    if isinstance(value, bool):
        return value
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise argparse.ArgumentTypeError(f"Expected a boolean, got {value!r}")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def resolve_repo_revision(repo: Path) -> str:
    """Resolve a pinned revision from Git metadata or a GitHub archive directory."""
    completed = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode == 0:
        revision = completed.stdout.strip()
        if re.fullmatch(r"[0-9a-fA-F]{40}", revision):
            return revision.lower()
    match = re.search(r"([0-9a-fA-F]{40})$", repo.name)
    if match:
        return match.group(1).lower()
    raise RuntimeError(
        "Cannot establish the Empanada revision: use a Git checkout or a GitHub "
        "archive directory whose name ends in the full 40-character commit."
    )


def prepare_entrypoint(entrypoint: Path, revision: str, work: Path) -> tuple[Path, list[dict]]:
    """Apply narrowly scoped, auditable upstream compatibility fixes."""
    if revision != TRACKER_SIGNATURE_FIX_COMMIT:
        return entrypoint, []
    source = entrypoint.read_text(encoding="utf-8")
    old = "update_trackers(rle_seg, index, trackers[axis_name], axis, stack)"
    new = "update_trackers(rle_seg, index, trackers[axis_name])"
    if source.count(old) != 1:
        raise RuntimeError(
            "The pinned v0.1.7 compatibility target changed; refusing an unverified patch."
        )
    patched = work / "pdl_inference3d-v0.1.7-compat.py"
    patched.write_text(source.replace(old, new), encoding="utf-8")
    return patched, [{
        "id": "empanada-v0.1.7-update-trackers-signature",
        "reason": "The generic 3D script passes two parameters removed from the v0.1.7 helper; the repository's MitoNet evaluate3d.py uses the three-argument call.",
        "source_sha256": sha256(entrypoint),
        "executed_sha256": sha256(patched),
    }]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--model-config", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--mode", choices=("stack", "orthoplane"), default="stack")
    parser.add_argument("--median-kernel", type=int, choices=(1, 3, 5, 7, 9, 11), default=3)
    parser.add_argument("--seg-thr", type=float, default=0.3)
    parser.add_argument("--center-thr", type=float, default=0.1)
    parser.add_argument("--center-min-distance", type=int, default=3)
    parser.add_argument("--merge-iou", type=float, default=0.25)
    parser.add_argument("--merge-ioa", type=float, default=0.25)
    parser.add_argument("--pixel-vote", type=int, choices=(1, 2, 3), default=2)
    parser.add_argument("--cluster-iou", type=float, default=0.75)
    parser.add_argument("--min-size", type=int, default=500)
    parser.add_argument("--min-span", type=int, default=4)
    parser.add_argument("--label-divisor", type=int, default=20000)
    parser.add_argument("--downsample-factor", type=int, default=1)
    parser.add_argument("--allow-one-view", nargs="?", const=True, default=False, type=parse_bool)
    parser.add_argument("--fine-boundaries", nargs="?", const=True, default=False, type=parse_bool)
    parser.add_argument("--use-cpu", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repo, model_config, checkpoint, source, output = [path.resolve() for path in (args.repo, args.model_config, args.checkpoint, args.input, args.output)]
    entrypoint = repo / "scripts" / "pdl_inference3d.py"
    for path in (repo, entrypoint, model_config, checkpoint, source):
        if not path.exists():
            raise FileNotFoundError(path)
    if output.exists():
        raise FileExistsError(f"Refusing to overwrite {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        import yaml
    except ImportError as exc:
        raise RuntimeError("PyYAML is required by the MitoNet adapter") from exc
    config = yaml.safe_load(model_config.read_text(encoding="utf-8"))
    if not isinstance(config, dict):
        raise ValueError("Model configuration root must be a mapping")
    config["model"] = str(checkpoint)
    config["model_quantized"] = str(checkpoint) if args.use_cpu else config.get("model_quantized")
    commit = resolve_repo_revision(repo)
    with tempfile.TemporaryDirectory(prefix="mitonet-", dir=str(output.parent)) as directory:
        work = Path(directory)
        executed_entrypoint, compatibility_patches = prepare_entrypoint(entrypoint, commit, work)
        staged_input = work / "input.tif"
        shutil.copyfile(source, staged_input)
        frozen_config = work / "model-config.yaml"
        frozen_config.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
        command = [
            sys.executable, str(executed_entrypoint), str(frozen_config), str(staged_input),
            "-mode", args.mode, "-qlen", str(args.median_kernel), "-nmax", str(args.label_divisor),
            "-seg-thr", str(args.seg_thr), "-nms-thr", str(args.center_thr),
            "-nms-kernel", str(args.center_min_distance), "-iou-thr", str(args.merge_iou),
            "-ioa-thr", str(args.merge_ioa), "-pixel-vote-thr", str(args.pixel_vote),
            "-cluster-iou-thr", str(args.cluster_iou), "-min-size", str(args.min_size),
            "-min-span", str(args.min_span), "-downsample-f", str(args.downsample_factor),
        ]
        if args.allow_one_view: command.append("--one-view")
        if args.fine_boundaries: command.append("--fine-boundaries")
        if args.use_cpu: command.append("--use-cpu")
        environment = os.environ.copy()
        environment["PYTHONPATH"] = str(repo) + os.pathsep + environment.get("PYTHONPATH", "")
        started = time.perf_counter()
        completed = subprocess.run(command, cwd=repo, env=environment, shell=False, text=True, capture_output=True)
        runtime = time.perf_counter() - started
        (output.parent / (output.stem + ".stdout.txt")).write_text(completed.stdout, encoding="utf-8")
        (output.parent / (output.stem + ".stderr.txt")).write_text(completed.stderr, encoding="utf-8")
        produced = work / "input_mito.tif"
        if completed.returncode != 0 or not produced.exists():
            raise RuntimeError(f"Official Empanada inference failed with code {completed.returncode}; see logs beside {output}")
        os.replace(produced, output)
    record = {
        "completed_at": dt.datetime.now(dt.timezone.utc).isoformat(), "official_entrypoint": str(entrypoint),
        "empanada_commit": commit, "model_config_sha256": sha256(model_config),
        "checkpoint_sha256": sha256(checkpoint), "input_sha256": sha256(source), "output_sha256": sha256(output),
        "output": str(output), "runtime_seconds": runtime, "parameters": vars(args),
        "compatibility_patches": compatibility_patches,
    }
    record["parameters"] = {key: str(value) if isinstance(value, Path) else value for key, value in record["parameters"].items()}
    provenance = output.with_suffix(output.suffix + ".provenance.json")
    provenance.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(record, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
