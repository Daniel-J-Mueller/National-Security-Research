#!/usr/bin/env python3
"""
Backfill runbook service versions and versioned CPEs from existing fingerprints.

The script does not scan networks and does not invent product mappings without
local evidence. It learns from rows that already contain a product/version/CPE
fingerprint, then applies only unambiguous facts to matching rows.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[3]
CYBER_DIR = ROOT / "data" / "private" / "cybersecurity"
GROUP_OUTPUT_DIR = CYBER_DIR / "group-outputs-main"
RUNBOOK_FIELDNAMES = [
    "target",
    "target_label",
    "host",
    "host_status",
    "scan_status",
    "port",
    "protocol",
    "service_name",
    "product",
    "version",
    "extrainfo",
    "cpe",
    "error",
]
REPAIR_FIELDS = ["product", "version", "extrainfo", "cpe"]
RESCAN_QUEUE_FIELDS = [
    "host",
    "target",
    "target_label",
    "port",
    "protocol",
    "service_name",
    "product",
    "cpe",
    "row_count",
    "suggested_nmap_args",
]
CPE_SPLIT_RE = re.compile(r"\s*;\s*|\s*\|\s*")
LEADING_VERSION_RE = re.compile(r"^v?(\d+(?:[._+-][0-9A-Za-z]+)*(?:[A-Za-z][0-9]*)?)")
INNER_VERSION_RE = re.compile(r"\bv?(\d+(?:[._+-][0-9A-Za-z]+)+[A-Za-z0-9]*)\b")


@dataclass
class FingerprintFacts:
    products: Counter[str] = field(default_factory=Counter)
    versions: Counter[str] = field(default_factory=Counter)
    extrainfos: Counter[str] = field(default_factory=Counter)
    cpe_bases: Counter[str] = field(default_factory=Counter)


@dataclass
class EnrichmentStats:
    files_seen: int = 0
    files_changed: int = 0
    rows_seen: int = 0
    open_rows: int = 0
    rows_changed: int = 0
    product_from_endpoint: int = 0
    version_from_endpoint_product: int = 0
    version_from_endpoint: int = 0
    version_from_product_cpe: int = 0
    version_from_product: int = 0
    version_from_cpe: int = 0
    cpe_versioned_from_row_version: int = 0
    stale_unversioned_cpe_removed: int = 0
    cpe_added_from_endpoint: int = 0
    cpe_added_from_product_version: int = 0
    cpe_added_from_product: int = 0

    def add(self, other: "EnrichmentStats") -> None:
        for field_name in self.__dataclass_fields__:
            setattr(self, field_name, getattr(self, field_name) + getattr(other, field_name))

    def as_dict(self) -> dict[str, int]:
        return {field_name: getattr(self, field_name) for field_name in self.__dataclass_fields__}


@dataclass
class LearnedFacts:
    endpoint_facts: dict[tuple[str, str, str, str], FingerprintFacts]
    endpoint_product_facts: dict[tuple[str, str, str, str, str], FingerprintFacts]
    service_product_bases: dict[tuple[str, str], Counter[str]]
    service_product_version_bases: dict[tuple[str, str, str], Counter[str]]
    service_product_versions: dict[tuple[str, str], FingerprintFacts]
    service_product_cpe_versions: dict[tuple[str, str, str], FingerprintFacts]


def utc_timestamp() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def normalize(value: object) -> str:
    return str(value or "").strip()


def source_output_dirs() -> list[Path]:
    if not CYBER_DIR.exists():
        return []
    output_dirs: list[Path] = []
    for path in sorted(CYBER_DIR.glob("runbook-outputs*")):
        if not path.is_dir() or path == GROUP_OUTPUT_DIR:
            continue
        if data_files(path, "csv") or data_files(path, "jsonl"):
            output_dirs.append(path)
    return output_dirs


def data_files(output_dir: Path, kind: str) -> list[Path]:
    suffix = ".csv" if kind == "csv" else ".jsonl"
    return sorted((output_dir / kind).glob(f"*{suffix}")) if (output_dir / kind).exists() else []


def parse_cpes(value: object) -> list[str]:
    if isinstance(value, list):
        parts = [normalize(item) for item in value]
    else:
        text = normalize(value)
        if not text:
            return []
        if text.startswith("["):
            try:
                payload = json.loads(text)
            except json.JSONDecodeError:
                payload = None
            if isinstance(payload, list):
                parts = [normalize(item) for item in payload]
            else:
                parts = CPE_SPLIT_RE.split(text)
        else:
            parts = CPE_SPLIT_RE.split(text)

    cpes: list[str] = []
    for part in parts:
        if part and part not in cpes:
            cpes.append(part)
    return cpes


def cpe_parts(cpe: str) -> list[str]:
    return cpe.split(":")


def cpe_version(cpe: str) -> str:
    parts = cpe_parts(cpe)
    if len(parts) >= 6 and parts[:2] == ["cpe", "2.3"]:
        return parts[5]
    if len(parts) >= 5 and parts[0] == "cpe" and parts[1].startswith("/"):
        return parts[4]
    return ""


def cpe_base(cpe: str) -> str:
    parts = cpe_parts(cpe)
    if len(parts) >= 5 and parts[:2] == ["cpe", "2.3"]:
        return ":".join(parts[:5])
    if len(parts) >= 4 and parts[0] == "cpe" and parts[1].startswith("/"):
        return ":".join(parts[:4])
    return cpe


def cpe_has_version(cpe: str) -> bool:
    version = cpe_version(cpe)
    return bool(version and version not in {"*", "-"})


def version_token(value: object) -> str:
    text = normalize(value)
    if not text:
        return ""
    match = LEADING_VERSION_RE.search(text)
    if not match:
        match = INNER_VERSION_RE.search(text)
    if not match:
        return ""
    token = match.group(1).strip("._+-")
    token = re.sub(r"[^A-Za-z0-9._+-]+", "_", token)
    return token.lower().strip("_")


def versioned_cpe(cpe: str, version: str) -> str:
    token = version_token(version)
    if not token:
        return cpe
    parts = cpe_parts(cpe)
    if len(parts) >= 6 and parts[:2] == ["cpe", "2.3"]:
        if parts[5] in {"", "*", "-"}:
            parts[5] = token
            return ":".join(parts)
        return cpe
    if len(parts) >= 4 and parts[0] == "cpe" and parts[1].startswith("/"):
        if len(parts) == 4:
            parts.append(token)
            return ":".join(parts)
        if parts[4] in {"", "*", "-"}:
            parts[4] = token
            return ":".join(parts)
    return cpe


def endpoint(row: dict[str, Any]) -> str:
    return normalize(row.get("host")) or normalize(row.get("target"))


def endpoint_key(row: dict[str, Any]) -> tuple[str, str, str, str]:
    return (
        endpoint(row),
        normalize(row.get("port")),
        normalize(row.get("protocol")),
        normalize(row.get("service_name")),
    )


def endpoint_product_key(row: dict[str, Any]) -> tuple[str, str, str, str, str]:
    return (*endpoint_key(row), normalize(row.get("product")))


def is_open_service(row: dict[str, Any]) -> bool:
    return normalize(row.get("scan_status")) == "open-service"


def unique_counter_value(counter: Counter[str], min_count: int = 1) -> str:
    values = [value for value, count in counter.items() if value and count > 0]
    if len(values) != 1:
        return ""
    value = values[0]
    return value if counter[value] >= min_count else ""


def add_row_facts(row: dict[str, Any], facts: LearnedFacts) -> None:
    if not is_open_service(row):
        return
    product = normalize(row.get("product"))
    version = normalize(row.get("version"))
    extrainfo = normalize(row.get("extrainfo"))
    cpes = parse_cpes(row.get("cpe"))
    bases = [cpe_base(cpe) for cpe in cpes if cpe_base(cpe).startswith("cpe:")]
    key = endpoint_key(row)
    product_key = endpoint_product_key(row)

    if product:
        facts.endpoint_facts[key].products[product] += 1
    if version:
        facts.endpoint_facts[key].versions[version] += 1
        facts.endpoint_product_facts[product_key].versions[version] += 1
    if extrainfo:
        facts.endpoint_facts[key].extrainfos[extrainfo] += 1
        facts.endpoint_product_facts[product_key].extrainfos[extrainfo] += 1
    for base in bases:
        facts.endpoint_facts[key].cpe_bases[base] += 1
        facts.endpoint_product_facts[product_key].cpe_bases[base] += 1
        if product:
            service_product = (normalize(row.get("service_name")), product)
            facts.service_product_bases[service_product][base] += 1
            if version:
                facts.service_product_version_bases[(*service_product, version_token(version))][base] += 1
                facts.service_product_cpe_versions[(*service_product, base)].versions[version] += 1
    if product and version:
        facts.service_product_versions[(normalize(row.get("service_name")), product)].versions[version] += 1


def iter_csv_rows(path: Path) -> Iterable[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        yield from csv.DictReader(handle)


def iter_jsonl_rows(path: Path) -> Iterable[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped:
                continue
            payload = json.loads(stripped)
            if isinstance(payload, dict):
                yield payload


def learn_facts(output_dirs: list[Path]) -> LearnedFacts:
    facts = LearnedFacts(
        endpoint_facts=defaultdict(FingerprintFacts),
        endpoint_product_facts=defaultdict(FingerprintFacts),
        service_product_bases=defaultdict(Counter),
        service_product_version_bases=defaultdict(Counter),
        service_product_versions=defaultdict(FingerprintFacts),
        service_product_cpe_versions=defaultdict(FingerprintFacts),
    )
    for output_dir in output_dirs:
        csv_files = data_files(output_dir, "csv")
        source_files = csv_files if csv_files else data_files(output_dir, "jsonl")
        for path in source_files:
            rows = iter_csv_rows(path) if path.suffix.lower() == ".csv" else iter_jsonl_rows(path)
            for row in rows:
                add_row_facts(row, facts)
    return facts


def add_cpe_if_missing(row: dict[str, Any], base: str, stats: EnrichmentStats, reason: str) -> bool:
    version = normalize(row.get("version"))
    cpe = versioned_cpe(base, version)
    if not cpe_has_version(cpe):
        return False
    cpes = parse_cpes(row.get("cpe"))
    if cpe in cpes:
        return False
    cpes.append(cpe)
    row["cpe"] = cpes
    if reason == "endpoint":
        stats.cpe_added_from_endpoint += 1
    elif reason == "product_version":
        stats.cpe_added_from_product_version += 1
    else:
        stats.cpe_added_from_product += 1
    return True


def remove_stale_unversioned_cpes(cpes: list[str], stats: EnrichmentStats) -> tuple[list[str], bool]:
    versioned_bases = {cpe_base(cpe) for cpe in cpes if cpe_has_version(cpe)}
    if not versioned_bases:
        return cpes, False

    next_cpes: list[str] = []
    removed = 0
    for cpe in cpes:
        if not cpe_has_version(cpe) and cpe_base(cpe) in versioned_bases:
            removed += 1
            continue
        next_cpes.append(cpe)

    if not removed:
        return cpes, False
    stats.stale_unversioned_cpe_removed += removed
    return next_cpes, True


def enrich_row(row: dict[str, Any], facts: LearnedFacts, stats: EnrichmentStats, min_version_evidence: int) -> bool:
    stats.rows_seen += 1
    if not is_open_service(row):
        return False
    stats.open_rows += 1

    changed = False
    product = normalize(row.get("product"))
    version = normalize(row.get("version"))
    cpes = parse_cpes(row.get("cpe"))
    key = endpoint_key(row)
    endpoint_fact = facts.endpoint_facts.get(key, FingerprintFacts())

    if not product:
        learned_product = unique_counter_value(endpoint_fact.products)
        if learned_product:
            row["product"] = learned_product
            product = learned_product
            stats.product_from_endpoint += 1
            changed = True

    product_fact = facts.endpoint_product_facts.get(endpoint_product_key(row), FingerprintFacts())
    if not version:
        learned_version = unique_counter_value(product_fact.versions)
        if learned_version:
            row["version"] = learned_version
            version = learned_version
            stats.version_from_endpoint_product += 1
            changed = True
        else:
            learned_version = unique_counter_value(endpoint_fact.versions)
            if learned_version:
                row["version"] = learned_version
                version = learned_version
                stats.version_from_endpoint += 1
                changed = True

    if not version:
        cpe_versions = {cpe_version(cpe) for cpe in cpes if cpe_has_version(cpe)}
        cpe_versions.discard("")
        if len(cpe_versions) == 1:
            row["version"] = cpe_versions.pop()
            version = normalize(row.get("version"))
            stats.version_from_cpe += 1
            changed = True

    if not version and product:
        service_product = (normalize(row.get("service_name")), product)
        for base in [cpe_base(cpe) for cpe in cpes if cpe_base(cpe).startswith("cpe:")]:
            learned_version = unique_counter_value(
                facts.service_product_cpe_versions[(*service_product, base)].versions,
                min_version_evidence,
            )
            if learned_version:
                row["version"] = learned_version
                version = learned_version
                stats.version_from_product_cpe += 1
                changed = True
                break
    if not version and product:
        learned_version = unique_counter_value(
            facts.service_product_versions[(normalize(row.get("service_name")), product)].versions,
            min_version_evidence,
        )
        if learned_version:
            row["version"] = learned_version
            version = learned_version
            stats.version_from_product += 1
            changed = True

    if version and cpes:
        next_cpes = [versioned_cpe(cpe, version) for cpe in cpes]
        if next_cpes != cpes:
            row["cpe"] = next_cpes
            cpes = next_cpes
            stats.cpe_versioned_from_row_version += 1
            changed = True

    if cpes:
        next_cpes, removed_stale = remove_stale_unversioned_cpes(cpes, stats)
        if removed_stale:
            row["cpe"] = next_cpes
            cpes = next_cpes
            changed = True

    if version and not parse_cpes(row.get("cpe")):
        base = unique_counter_value(product_fact.cpe_bases)
        if base and add_cpe_if_missing(row, base, stats, "endpoint"):
            changed = True
        elif product:
            service_product = (normalize(row.get("service_name")), product)
            base = unique_counter_value(facts.service_product_version_bases[(*service_product, version_token(version))])
            if base and add_cpe_if_missing(row, base, stats, "product_version"):
                changed = True
            else:
                base = unique_counter_value(facts.service_product_bases[service_product])
                if base and add_cpe_if_missing(row, base, stats, "product"):
                    changed = True

    if changed:
        stats.rows_changed += 1
    return changed


def serialize_csv_row(row: dict[str, Any], fieldnames: list[str]) -> dict[str, str]:
    output: dict[str, str] = {}
    for fieldname in fieldnames:
        value = row.get(fieldname, "")
        if fieldname == "cpe":
            output[fieldname] = "; ".join(parse_cpes(value))
        elif isinstance(value, list):
            output[fieldname] = "; ".join(normalize(item) for item in value if normalize(item))
        else:
            output[fieldname] = normalize(value)
    return output


def write_jsonl_row(row: dict[str, Any]) -> str:
    cpes = parse_cpes(row.get("cpe"))
    row["cpe"] = cpes
    return json.dumps(row, ensure_ascii=False, sort_keys=False) + "\n"


def replace_file(path: Path, content_path: Path, dry_run: bool) -> None:
    if dry_run:
        content_path.unlink(missing_ok=True)
        return
    os.replace(content_path, path)


def enrich_csv_file(path: Path, facts: LearnedFacts, dry_run: bool, min_version_evidence: int) -> EnrichmentStats:
    stats = EnrichmentStats(files_seen=1)
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = list(reader.fieldnames or [])
        for fieldname in RUNBOOK_FIELDNAMES:
            if fieldname not in fieldnames:
                fieldnames.append(fieldname)
        rows = [dict(row) for row in reader]

    changed = False
    for row in rows:
        changed = enrich_row(row, facts, stats, min_version_evidence) or changed

    if not changed:
        return stats

    temp_path = path.with_name(f"{path.name}.tmp")
    with temp_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow(serialize_csv_row(row, fieldnames))
    replace_file(path, temp_path, dry_run)
    stats.files_changed = 1
    return stats


def enrich_jsonl_file(path: Path, facts: LearnedFacts, dry_run: bool, min_version_evidence: int) -> EnrichmentStats:
    stats = EnrichmentStats(files_seen=1)
    changed = False
    temp_path = path.with_name(f"{path.name}.tmp")
    with path.open("r", encoding="utf-8") as source, temp_path.open("w", encoding="utf-8", newline="") as target:
        for line in source:
            stripped = line.strip()
            if not stripped:
                target.write(line)
                continue
            try:
                row = json.loads(stripped)
            except json.JSONDecodeError:
                target.write(line)
                continue
            if not isinstance(row, dict):
                target.write(line)
                continue
            changed = enrich_row(row, facts, stats, min_version_evidence) or changed
            target.write(write_jsonl_row(row))

    if not changed:
        temp_path.unlink(missing_ok=True)
        return stats

    replace_file(path, temp_path, dry_run)
    stats.files_changed = 1
    return stats


def enrich_output_dir(
    output_dir: Path,
    facts: LearnedFacts,
    dry_run: bool,
    min_version_evidence: int,
) -> dict[str, Any]:
    output_stats = EnrichmentStats()
    file_reports: list[dict[str, Any]] = []
    for kind, handler in (("csv", enrich_csv_file), ("jsonl", enrich_jsonl_file)):
        for path in data_files(output_dir, kind):
            stats = handler(path, facts, dry_run, min_version_evidence)
            output_stats.add(stats)
            if stats.rows_changed:
                file_reports.append(
                    {
                        "kind": kind,
                        "path": str(path.relative_to(ROOT)),
                        **stats.as_dict(),
                    }
                )
    audit = audit_output_dir(output_dir)
    queue = version_rescan_queue(output_dir)
    queue_path = write_rescan_queue(output_dir, queue, dry_run)

    return {
        "output_dir": str(output_dir.relative_to(ROOT)),
        "stats": output_stats.as_dict(),
        "audit": audit,
        "version_rescan_queue_rows": len(queue),
        "version_rescan_queue_path": queue_path,
        "changed_files": file_reports,
    }


def write_manifest(output_dir: Path, payload: dict[str, Any], dry_run: bool) -> None:
    if dry_run:
        return
    manifest_dir = output_dir / "manifest"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    path = manifest_dir / "cpe-version-enrichment-manifest.json"
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def audit_row(row: dict[str, Any], audit: Counter[str]) -> None:
    audit["rows"] += 1
    if not is_open_service(row):
        return
    audit["open_rows"] += 1
    product = normalize(row.get("product"))
    version = normalize(row.get("version"))
    cpes = parse_cpes(row.get("cpe"))
    if not version:
        audit["missing_version"] += 1
        if product:
            audit["product_no_version"] += 1
    if not cpes:
        audit["blank_cpe"] += 1
        if version:
            audit["version_no_cpe"] += 1
        return
    if any(cpe_has_version(cpe) for cpe in cpes):
        audit["versioned_cpe"] += 1
    if any(not cpe_has_version(cpe) for cpe in cpes):
        audit["unversioned_cpe"] += 1


def audit_output_dir(output_dir: Path) -> dict[str, int]:
    audit: Counter[str] = Counter()
    paths = data_files(output_dir, "csv")
    kind = "csv"
    if not paths:
        paths = data_files(output_dir, "jsonl")
        kind = "jsonl"
    for path in paths:
        rows = iter_csv_rows(path) if kind == "csv" else iter_jsonl_rows(path)
        for row in rows:
            audit_row(row, audit)
    return {
        "rows": audit["rows"],
        "open_rows": audit["open_rows"],
        "missing_version": audit["missing_version"],
        "product_no_version": audit["product_no_version"],
        "blank_cpe": audit["blank_cpe"],
        "version_no_cpe": audit["version_no_cpe"],
        "versioned_cpe": audit["versioned_cpe"],
        "unversioned_cpe": audit["unversioned_cpe"],
    }


def version_rescan_queue(output_dir: Path) -> list[dict[str, str]]:
    queued: dict[tuple[str, str, str], dict[str, str]] = {}
    paths = data_files(output_dir, "csv")
    kind = "csv"
    if not paths:
        paths = data_files(output_dir, "jsonl")
        kind = "jsonl"
    for path in paths:
        rows = iter_csv_rows(path) if kind == "csv" else iter_jsonl_rows(path)
        for row in rows:
            if not is_open_service(row) or normalize(row.get("version")):
                continue
            host = endpoint(row)
            port = normalize(row.get("port"))
            protocol = normalize(row.get("protocol")) or "tcp"
            if not host or not port:
                continue
            key = (host, port, protocol)
            queued_row = queued.setdefault(
                key,
                {
                    "host": host,
                    "target": normalize(row.get("target")),
                    "target_label": normalize(row.get("target_label")),
                    "port": port,
                    "protocol": protocol,
                    "service_name": normalize(row.get("service_name")),
                    "product": normalize(row.get("product")),
                    "cpe": "; ".join(parse_cpes(row.get("cpe"))),
                    "row_count": "0",
                    "suggested_nmap_args": f"--open -sV --version-all -p {port} {host}",
                },
            )
            queued_row["row_count"] = str(int(queued_row["row_count"]) + 1)
            for field_name in ("service_name", "product", "cpe", "target_label"):
                if not queued_row[field_name] and normalize(row.get(field_name)):
                    queued_row[field_name] = normalize(row.get(field_name))

    return sorted(
        queued.values(),
        key=lambda item: (
            item["protocol"],
            int(item["port"]) if item["port"].isdigit() else 0,
            item["host"],
        ),
    )


def write_rescan_queue(output_dir: Path, rows: list[dict[str, str]], dry_run: bool) -> str:
    if dry_run:
        return ""
    quick_output_dir = output_dir / "quick-output"
    quick_output_dir.mkdir(parents=True, exist_ok=True)
    path = quick_output_dir / "version-rescan-queue.csv"
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=RESCAN_QUEUE_FIELDS, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({field_name: row.get(field_name, "") for field_name in RESCAN_QUEUE_FIELDS})
    return str(path.relative_to(ROOT))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Backfill missing runbook service versions and versioned CPE values from local fingerprints."
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        action="append",
        help="Runbook output directory to update. Repeatable. Defaults to source runbook-outputs* directories.",
    )
    parser.add_argument(
        "--include-group-output",
        action="store_true",
        help="Also update data/private/cybersecurity/group-outputs-main when using default output dirs.",
    )
    parser.add_argument(
        "--min-version-evidence",
        type=int,
        default=3,
        help=(
            "Minimum local rows required before filling a blank version from service/product evidence. "
            "Default: %(default)s."
        ),
    )
    parser.add_argument("--apply", action="store_true", help="Write changes. Without this, only report a dry run.")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    output_dirs = [path.resolve() for path in (args.output_dir or source_output_dirs())]
    if args.include_group_output and not args.output_dir and GROUP_OUTPUT_DIR.exists():
        output_dirs.append(GROUP_OUTPUT_DIR.resolve())
    output_dirs = [path for path in output_dirs if path.exists()]
    if not output_dirs:
        print("ERROR: no runbook output directories with data were found.", file=sys.stderr)
        return 1

    dry_run = not args.apply
    facts = learn_facts(output_dirs)
    min_version_evidence = max(1, args.min_version_evidence)
    reports = [
        enrich_output_dir(output_dir, facts, dry_run, min_version_evidence)
        for output_dir in output_dirs
    ]
    total = EnrichmentStats()
    for report in reports:
        stats = EnrichmentStats(**report["stats"])
        total.add(stats)

    payload = {
        "generated_at": utc_timestamp(),
        "dry_run": dry_run,
        "min_version_evidence": min_version_evidence,
        "output_dirs": [str(path.relative_to(ROOT)) for path in output_dirs],
        "totals": total.as_dict(),
        "reports": reports,
    }
    audit_totals: Counter[str] = Counter()
    queue_rows = 0
    for report in reports:
        audit_totals.update(report["audit"])
        queue_rows += int(report.get("version_rescan_queue_rows") or 0)
    payload["audit_totals"] = dict(audit_totals)
    payload["version_rescan_queue_rows"] = queue_rows

    for output_dir in output_dirs:
        write_manifest(output_dir, payload, dry_run)

    mode = "DRY RUN" if dry_run else "APPLIED"
    print(f"{mode}: scanned {total.rows_seen:,} rows in {total.files_seen:,} files")
    print(f"{mode}: changed {total.rows_changed:,} rows in {total.files_changed:,} files")
    print(f"{mode}: versions from endpoint/product: {total.version_from_endpoint_product:,}")
    print(f"{mode}: versions from endpoint: {total.version_from_endpoint:,}")
    print(f"{mode}: versions from product+CPE evidence: {total.version_from_product_cpe:,}")
    print(f"{mode}: versions from product evidence: {total.version_from_product:,}")
    print(f"{mode}: CPEs versioned from row version: {total.cpe_versioned_from_row_version:,}")
    print(f"{mode}: stale unversioned CPEs removed: {total.stale_unversioned_cpe_removed:,}")
    print(f"{mode}: CPEs added from product/version evidence: {total.cpe_added_from_product_version:,}")
    print(f"{mode}: CPEs added from product evidence: {total.cpe_added_from_product:,}")
    print(f"{mode}: remaining open-service rows missing versions: {audit_totals['missing_version']:,}")
    print(f"{mode}: version rescan queue rows: {queue_rows:,}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
