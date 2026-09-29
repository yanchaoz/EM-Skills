#!/usr/bin/env python3
"""Query, validate, and export handoffs from the bundled vEM catalog."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse


SKILL_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CATALOG = SKILL_ROOT / "references" / "datasets.json"
ACCESS_STATES = {"open", "registration", "request", "restricted", "unknown"}
EVIDENCE_STATES = {"reported", "partially_verified", "verified"}
TRISTATE = {"yes", "no", "unknown"}
DOWNSTREAM = {
    "segneuron-inference",
    "mitonet-inference",
    "suggest-em-annotations",
    "review-em-segmentation",
    "cloudvolume-video",
}


def load_catalog(path: Path | str = DEFAULT_CATALOG) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _valid_url(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def validate_catalog(catalog: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if not str(catalog.get("schema_version", "")).startswith("1."):
        errors.append("schema_version must use supported major version 1")
    if not isinstance(catalog.get("snapshot"), dict):
        errors.append("snapshot must be an object")
    datasets = catalog.get("datasets")
    if not isinstance(datasets, list) or not datasets:
        return errors + ["datasets must be a non-empty array"]

    required_lists = (
        "aliases",
        "species",
        "tissues",
        "modalities",
        "annotations",
        "tasks",
        "sources",
    )
    seen: set[str] = set()
    for index, record in enumerate(datasets):
        prefix = f"datasets[{index}]"
        if not isinstance(record, dict):
            errors.append(f"{prefix} must be an object")
            continue
        dataset_id = record.get("id")
        if not isinstance(dataset_id, str) or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", dataset_id):
            errors.append(f"{prefix}.id must be lowercase kebab-case")
            dataset_id = f"index-{index}"
        elif dataset_id in seen:
            errors.append(f"duplicate dataset id: {dataset_id}")
        seen.add(dataset_id)
        if not isinstance(record.get("name"), str) or not record["name"].strip():
            errors.append(f"{dataset_id}.name must be a non-empty string")
        for field in required_lists:
            value = record.get(field)
            if not isinstance(value, list) or (field != "aliases" and not value):
                errors.append(f"{dataset_id}.{field} must be a non-empty array")
            elif not all(isinstance(item, str) and item.strip() for item in value):
                errors.append(f"{dataset_id}.{field} must contain non-empty strings")

        voxel = record.get("voxel_size_nm_zyx")
        if voxel is not None:
            valid_voxel = (
                isinstance(voxel, list)
                and len(voxel) == 3
                and all(isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0 for v in voxel)
            )
            if not valid_voxel:
                errors.append(f"{dataset_id}.voxel_size_nm_zyx must be null or three positive numbers")

        for field in ("raw_available", "labels_available"):
            if record.get(field) not in TRISTATE:
                errors.append(f"{dataset_id}.{field} must be one of {sorted(TRISTATE)}")
        if record.get("metadata_status") not in EVIDENCE_STATES:
            errors.append(f"{dataset_id}.metadata_status must be one of {sorted(EVIDENCE_STATES)}")

        access = record.get("access")
        if not isinstance(access, dict):
            errors.append(f"{dataset_id}.access must be an object")
            continue
        if access.get("status") not in ACCESS_STATES:
            errors.append(f"{dataset_id}.access.status must be one of {sorted(ACCESS_STATES)}")
        if not isinstance(access.get("dataset_license"), str) or not access["dataset_license"].strip():
            errors.append(f"{dataset_id}.access.dataset_license must be explicit, using 'unknown' when unresolved")
        urls = access.get("urls")
        if not isinstance(urls, list) or not urls:
            errors.append(f"{dataset_id}.access.urls must be a non-empty array")
        else:
            for url_index, item in enumerate(urls):
                if not isinstance(item, dict) or not _valid_url(item.get("url")):
                    errors.append(f"{dataset_id}.access.urls[{url_index}] must contain a valid http(s) URL")
        for source_index, source in enumerate(record.get("sources", [])):
            if not _valid_url(source):
                errors.append(f"{dataset_id}.sources[{source_index}] must be a valid http(s) URL")
    return errors


def _norm(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value).lower()).strip()


def _text_match(needle: str | None, values: Iterable[str]) -> bool:
    if not needle:
        return True
    query = _norm(needle)
    return any(query in _norm(value) for value in values)


def _has_tags(requested: Iterable[str] | None, available: Iterable[str]) -> bool:
    requested_set = {_norm(value) for value in requested or []}
    available_set = {_norm(value) for value in available}
    return requested_set.issubset(available_set)


def unresolved_fields(record: dict[str, Any]) -> list[str]:
    missing: list[str] = []
    if record.get("voxel_size_nm_zyx") is None:
        missing.append("voxel_size_nm_zyx")
    access = record.get("access", {})
    if access.get("dataset_license", "unknown").lower() == "unknown":
        missing.append("dataset_license")
    if access.get("status") == "unknown":
        missing.append("access_status")
    if record.get("raw_available") == "unknown":
        missing.append("raw_availability")
    if record.get("labels_available") == "unknown":
        missing.append("label_availability")
    if record.get("metadata_status") != "verified":
        missing.append("authoritative_verification")
    return missing


def readiness_score(record: dict[str, Any]) -> int:
    evidence_score = {"reported": 1, "partially_verified": 2, "verified": 3}
    score = evidence_score.get(record.get("metadata_status"), 0)
    score += int(record.get("voxel_size_nm_zyx") is not None)
    score += int(record.get("access", {}).get("status") == "open")
    score += int(record.get("raw_available") == "yes")
    score += int(record.get("labels_available") == "yes")
    score += int(record.get("access", {}).get("dataset_license", "unknown").lower() != "unknown")
    return score


def query_catalog(catalog: dict[str, Any], criteria: dict[str, Any]) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    for record in catalog["datasets"]:
        if not _text_match(criteria.get("species"), record["species"]):
            continue
        if not _text_match(criteria.get("tissue"), record["tissues"]):
            continue
        if not _text_match(criteria.get("modality"), record["modalities"]):
            continue
        if not _has_tags(criteria.get("annotations"), record["annotations"]):
            continue
        if not _has_tags(criteria.get("tasks"), record["tasks"]):
            continue
        access_states = criteria.get("access_states") or []
        if access_states and record["access"]["status"] not in access_states:
            continue
        if criteria.get("require_raw") and record["raw_available"] != "yes":
            continue
        if criteria.get("require_labels") and record["labels_available"] != "yes":
            continue

        voxel = record.get("voxel_size_nm_zyx")
        if criteria.get("max_xy_nm") is not None:
            if voxel is None and not criteria.get("include_unknown_resolution"):
                continue
            if voxel is not None and max(voxel[1], voxel[2]) > criteria["max_xy_nm"]:
                continue
        if criteria.get("max_z_nm") is not None:
            if voxel is None and not criteria.get("include_unknown_resolution"):
                continue
            if voxel is not None and voxel[0] > criteria["max_z_nm"]:
                continue

        free_text = criteria.get("text")
        if free_text:
            searchable = [
                record["id"],
                record["name"],
                record.get("notes", ""),
                *record["aliases"],
                *record["species"],
                *record["tissues"],
                *record["modalities"],
                *record["annotations"],
                *record["tasks"],
            ]
            tokens = _norm(free_text).split()
            haystack = _norm(" ".join(searchable))
            if not all(token in haystack for token in tokens):
                continue

        enriched = dict(record)
        enriched["readiness_score"] = readiness_score(record)
        enriched["unresolved_fields"] = unresolved_fields(record)
        matches.append(enriched)
    matches.sort(key=lambda item: (-item["readiness_score"], item["name"].lower()))
    limit = criteria.get("limit")
    return matches[:limit] if limit else matches


def _compatibility(record: dict[str, Any], downstream: str) -> tuple[str, list[str]]:
    annotations = set(record["annotations"])
    tasks = set(record["tasks"])
    reasons: list[str] = []
    compatible = record["raw_available"] == "yes"
    if not compatible:
        reasons.append("raw availability is not confirmed")
    if downstream == "segneuron-inference" and "neuron_segmentation" not in tasks:
        compatible = False
        reasons.append("catalog does not report neuron-segmentation suitability")
    elif downstream == "mitonet-inference" and not ({"mitochondria_instance", "mitochondria_semantic"} & annotations):
        compatible = False
        reasons.append("catalog does not report mitochondria annotations")
    elif downstream == "review-em-segmentation" and record["labels_available"] != "yes":
        compatible = False
        reasons.append("labels are not confirmed for review")
    elif downstream == "cloudvolume-video" and not record["access"]["urls"]:
        compatible = False
        reasons.append("no source URL is recorded")
    if compatible:
        reasons.append("catalog metadata indicate a plausible handoff; source audit remains required")
    return ("candidate" if compatible else "needs_review"), reasons


def build_manifest(catalog: dict[str, Any], dataset_id: str, downstream: str) -> dict[str, Any]:
    try:
        record = next(item for item in catalog["datasets"] if item["id"] == dataset_id)
    except StopIteration as exc:
        raise KeyError(f"unknown dataset id: {dataset_id}") from exc
    compatibility, reasons = _compatibility(record, downstream)
    return {
        "manifest_version": "1.0",
        "catalog_snapshot": catalog["snapshot"],
        "dataset": record,
        "handoff": {
            "downstream_skill": downstream,
            "compatibility": compatibility,
            "reasons": reasons,
            "unresolved_fields": unresolved_fields(record),
            "required_checks": [
                "verify authoritative landing page and immutable dataset/version identity",
                "confirm dataset-specific license, terms, and citation requirements",
                "inspect actual axes, shape, voxel size, offset, and physical bounds",
                "confirm raw and label paths plus label semantics",
                "define leakage-safe train, validation, test, and holdout scope",
                "estimate transfer size and obtain authorization before large download",
                "record checksums or equivalent source identities for acquired artifacts"
            ],
            "execution_authorized": False
        }
    }


def _write_text(text: str, output: str | None) -> None:
    if output:
        Path(output).write_text(text, encoding="utf-8")
    else:
        print(text)


def _format_table(records: list[dict[str, Any]]) -> str:
    headers = ("id", "species", "tissue", "voxel_nm_zyx", "annotations", "access", "score", "unresolved")
    rows = []
    for item in records:
        voxel = item.get("voxel_size_nm_zyx")
        rows.append((
            item["id"],
            ",".join(item["species"]),
            ",".join(item["tissues"]),
            "?" if voxel is None else "x".join(str(value) for value in voxel),
            ",".join(item["annotations"]),
            item["access"]["status"],
            str(item["readiness_score"]),
            ",".join(item["unresolved_fields"]) or "none",
        ))
    if not rows:
        return "No datasets matched the strict filters."
    widths = [max(len(headers[i]), *(len(row[i]) for row in rows)) for i in range(len(headers))]
    line = " | ".join(headers[i].ljust(widths[i]) for i in range(len(headers)))
    divider = "-+-".join("-" * width for width in widths)
    body = [" | ".join(row[i].ljust(widths[i]) for i in range(len(headers))) for row in rows]
    return "\n".join([line, divider, *body])


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", default=str(DEFAULT_CATALOG), help="Path to catalog JSON")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("validate", help="Validate structure and local invariants")

    query = subparsers.add_parser("query", help="Filter the catalog")
    query.add_argument("--species")
    query.add_argument("--tissue")
    query.add_argument("--modality")
    query.add_argument("--annotation", action="append", dest="annotations")
    query.add_argument("--task", action="append", dest="tasks")
    query.add_argument("--access-status", action="append", choices=sorted(ACCESS_STATES), dest="access_states")
    query.add_argument("--max-xy-nm", type=float)
    query.add_argument("--max-z-nm", type=float)
    query.add_argument("--include-unknown-resolution", action="store_true")
    query.add_argument("--require-raw", action="store_true")
    query.add_argument("--require-labels", action="store_true")
    query.add_argument("--text")
    query.add_argument("--limit", type=int)
    query.add_argument("--format", choices=("table", "json"), default="table")
    query.add_argument("--output")

    manifest = subparsers.add_parser("manifest", help="Export one candidate downstream handoff")
    manifest.add_argument("--id", required=True, dest="dataset_id")
    manifest.add_argument("--downstream", required=True, choices=sorted(DOWNSTREAM))
    manifest.add_argument("--output")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    catalog = load_catalog(args.catalog)
    errors = validate_catalog(catalog)
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 2
    if args.command == "validate":
        print(f"OK: {len(catalog['datasets'])} dataset records validated")
        return 0
    if args.command == "query":
        criteria = vars(args)
        records = query_catalog(catalog, criteria)
        if args.format == "json":
            omitted = {"catalog", "command", "format", "output"}
            active_criteria = {
                key: value
                for key, value in criteria.items()
                if key not in omitted and value is not None and value is not False and value != []
            }
            payload = {
                "catalog_snapshot": catalog["snapshot"],
                "criteria": active_criteria,
                "result_count": len(records),
                "results": records,
            }
            rendered = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
        else:
            rendered = _format_table(records) + "\n"
        _write_text(rendered, args.output)
        return 0
    if args.command == "manifest":
        try:
            payload = build_manifest(catalog, args.dataset_id, args.downstream)
        except KeyError as exc:
            print(f"ERROR: {exc.args[0]}", file=sys.stderr)
            return 2
        _write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", args.output)
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
