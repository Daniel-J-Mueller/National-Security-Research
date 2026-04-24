#!/usr/bin/env python3
"""
Run the owner-authorized server version runbook CSV.

The runbook CSV uses the same columns as the output CSV. Users fill only the
ip column, plus optional target_label values, and this runner writes sharded
CSV and JSONL result sets under data/private/cybersecurity/runbook-outputs.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import sys
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


CYBER_DIR = Path(__file__).resolve().parents[1]
ROOT = Path(__file__).resolve().parents[3]
if str(CYBER_DIR) not in sys.path:
    sys.path.insert(0, str(CYBER_DIR))

import scan_server_ip_list as scan  # noqa: E402


WORKFLOW_ID = "owner-authorized-cyber-runbook-server-version-scan"
DEFAULT_RUNBOOK_CSV = Path(__file__).with_name("server-version-runbook.csv")
DEFAULT_OUTPUT_DIR = ROOT / "data" / "private" / "cybersecurity" / "runbook-outputs"
DEFAULT_MAX_CHUNK_MB = 75
DEFAULT_MAX_TARGETS = 16

RUNBOOK_FIELDS = [
    "ip",
    "target_label",
    "host",
    "port",
    "protocol",
    "service_name",
    "product",
    "version",
    "extrainfo",
    "cpe",
    "vx_category",
    "vx_category_label",
    "category_rationale",
    "flags",
    "nmap_command",
    "scan_status",
    "error",
]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Read the cyber runbook CSV, scan exact owner-authorized IPs with "
            "safe Nmap service-version detection, and write sharded CSV/JSONL outputs."
        )
    )
    parser.add_argument(
        "--runbook-csv",
        type=Path,
        default=DEFAULT_RUNBOOK_CSV,
        help="Runbook CSV with the same columns as the output CSV.",
    )
    parser.add_argument(
        "--i-own-these-servers",
        action="store_true",
        help="Required before running Nmap. Confirms authorization for every listed IP.",
    )
    parser.add_argument(
        "--run-label",
        help="Safe local label for the output folder. Defaults to the runbook CSV name.",
    )
    parser.add_argument(
        "--ports",
        help="Optional Nmap port expression, such as 22,80,443 or 1-1024.",
    )
    parser.add_argument(
        "--top-ports",
        type=int,
        help="Optional Nmap --top-ports value. Ignored when --ports is provided.",
    )
    parser.add_argument(
        "--assume-host-up",
        action="store_true",
        help="Pass -Pn to Nmap when ICMP probes are blocked for your servers.",
    )
    parser.add_argument(
        "--nmap-path",
        default="nmap",
        help="Path to nmap executable. Default: %(default)s",
    )
    parser.add_argument(
        "--rules",
        type=Path,
        default=scan.DEFAULT_RULES,
        help="Category taxonomy and optional version baseline rules.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Directory for private runbook outputs.",
    )
    parser.add_argument(
        "--chunk-size-mb",
        type=float,
        default=DEFAULT_MAX_CHUNK_MB,
        help="Maximum size for each CSV or JSONL result shard. Default: %(default)s MB.",
    )
    parser.add_argument(
        "--max-targets",
        type=int,
        default=DEFAULT_MAX_TARGETS,
        help="Safety limit for one run. Default: %(default)s targets.",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=900,
        help="Per-target Nmap timeout. Default: %(default)s seconds.",
    )
    parser.add_argument(
        "--stop-on-error",
        action="store_true",
        help="Stop the batch if any target scan fails. By default, later targets still run.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate the runbook and write planned commands without running Nmap.",
    )
    return parser


def read_runbook_targets(path: Path, max_targets: int) -> list[scan.ServerTarget]:
    if not path.exists():
        raise FileNotFoundError(f"Runbook CSV not found: {path}")

    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        fieldnames = list(reader.fieldnames or [])
        if fieldnames != RUNBOOK_FIELDS:
            raise ValueError(
                "Runbook CSV header must exactly match the output columns: "
                + ", ".join(RUNBOOK_FIELDS)
            )

        targets: list[scan.ServerTarget] = []
        seen: set[str] = set()
        for line_number, row in enumerate(reader, start=2):
            normalized = {
                field: (row.get(field) or "").strip()
                for field in RUNBOOK_FIELDS
            }
            if not any(normalized.values()):
                continue
            if not normalized["ip"]:
                raise ValueError(f"Row {line_number} has data but no ip value.")

            target = scan.validate_target(normalized["ip"])
            key = target.lower()
            if key in seen:
                continue
            seen.add(key)
            label = scan.clean_label(normalized["target_label"] or target)
            targets.append(scan.ServerTarget(target=target, label=label))

    if not targets:
        raise ValueError(f"No IPs found in {path}. Fill the ip column for 2-3 rows.")
    if max_targets < 1:
        raise ValueError("--max-targets must be at least 1")
    if len(targets) > max_targets:
        raise ValueError(
            f"Refusing to scan {len(targets)} targets in one run; --max-targets is {max_targets}."
        )
    return targets


def command_text(command: Any) -> str:
    if isinstance(command, list):
        return " ".join(str(part) for part in command)
    return str(command or "")


def blank_row() -> dict[str, str]:
    return {field: "" for field in RUNBOOK_FIELDS}


def service_to_runbook_row(service: dict[str, Any]) -> dict[str, str]:
    row = blank_row()
    row["ip"] = str(service.get("input_target") or service.get("host") or "")
    row["target_label"] = str(service.get("target_label") or "")
    for field in (
        "host",
        "port",
        "protocol",
        "service_name",
        "product",
        "version",
        "extrainfo",
        "cpe",
        "vx_category",
        "vx_category_label",
        "category_rationale",
        "flags",
        "nmap_command",
    ):
        row[field] = scan.service_csv_value(service, field)
    row["scan_status"] = "open-service"
    return row


def host_summary_to_runbook_row(host: dict[str, Any]) -> dict[str, str]:
    row = blank_row()
    row["ip"] = str(host.get("input_target") or "")
    row["target_label"] = str(host.get("target_label") or "")
    row["host"] = str(host.get("detected_address") or "")
    row["nmap_command"] = command_text(host.get("nmap_command"))
    host_status = str(host.get("host_status") or "host-summary")
    if host_status == "dry-run-planned":
        row["scan_status"] = host_status
    elif int(host.get("open_service_count") or 0) == 0:
        row["scan_status"] = "no-open-services"
    else:
        row["scan_status"] = host_status
    return row


def error_to_runbook_row(error: dict[str, Any]) -> dict[str, str]:
    row = blank_row()
    row["ip"] = str(error.get("target") or "")
    row["target_label"] = str(error.get("target_label") or "")
    row["nmap_command"] = command_text(error.get("nmap_command"))
    row["scan_status"] = "error"
    row["error"] = str(error.get("error") or "")
    return row


def build_runbook_rows(
    targets: list[scan.ServerTarget],
    host_summaries: list[dict[str, Any]],
    services: list[dict[str, Any]],
    errors: list[dict[str, Any]],
) -> list[dict[str, str]]:
    services_by_target: dict[str, list[dict[str, Any]]] = defaultdict(list)
    hosts_by_target: dict[str, list[dict[str, Any]]] = defaultdict(list)
    errors_by_target: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for service in services:
        services_by_target[str(service.get("input_target") or "").lower()].append(service)
    for host in host_summaries:
        hosts_by_target[str(host.get("input_target") or "").lower()].append(host)
    for error in errors:
        errors_by_target[str(error.get("target") or "").lower()].append(error)

    rows: list[dict[str, str]] = []
    for target in targets:
        key = target.target.lower()
        target_services = services_by_target.get(key, [])
        if target_services:
            rows.extend(service_to_runbook_row(service) for service in target_services)
        else:
            rows.extend(
                host_summary_to_runbook_row(host)
                for host in hosts_by_target.get(key, [])
            )
        rows.extend(error_to_runbook_row(error) for error in errors_by_target.get(key, []))
    return rows


def file_info(path: Path, payload: bytes, record_count: int) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return {
        "path": str(path),
        "bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "record_count": record_count,
    }


def csv_bytes_for_row(row: dict[str, str] | None = None) -> bytes:
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=RUNBOOK_FIELDS, lineterminator="\n")
    if row is None:
        writer.writeheader()
    else:
        writer.writerow({field: row.get(field, "") for field in RUNBOOK_FIELDS})
    return buffer.getvalue().encode("utf-8")


def write_csv_shards(
    output_dir: Path,
    stem: str,
    rows: list[dict[str, str]],
    max_bytes: int,
) -> list[dict[str, Any]]:
    header = csv_bytes_for_row()
    if len(header) > max_bytes:
        raise ValueError("CSV header is larger than the configured shard size.")

    shards: list[dict[str, Any]] = []
    shard_rows: list[bytes] = []
    shard_record_count = 0
    shard_size = len(header)
    shard_index = 1

    def flush() -> None:
        nonlocal shard_index, shard_rows, shard_record_count, shard_size
        payload = header + b"".join(shard_rows)
        path = output_dir / f"{stem}-{shard_index:04d}.csv"
        shards.append(file_info(path, payload, shard_record_count))
        shard_index += 1
        shard_rows = []
        shard_record_count = 0
        shard_size = len(header)

    for row in rows:
        row_bytes = csv_bytes_for_row(row)
        if len(header) + len(row_bytes) > max_bytes:
            raise ValueError("A single CSV row is larger than the configured shard size.")
        if shard_rows and shard_size + len(row_bytes) > max_bytes:
            flush()
        shard_rows.append(row_bytes)
        shard_record_count += 1
        shard_size += len(row_bytes)

    flush()
    return shards


def write_jsonl_shards(
    output_dir: Path,
    stem: str,
    rows: list[dict[str, str]],
    max_bytes: int,
) -> list[dict[str, Any]]:
    shards: list[dict[str, Any]] = []
    shard_lines: list[bytes] = []
    shard_record_count = 0
    shard_size = 0
    shard_index = 1

    def flush() -> None:
        nonlocal shard_index, shard_lines, shard_record_count, shard_size
        payload = b"".join(shard_lines)
        path = output_dir / f"{stem}-{shard_index:04d}.jsonl"
        shards.append(file_info(path, payload, shard_record_count))
        shard_index += 1
        shard_lines = []
        shard_record_count = 0
        shard_size = 0

    for row in rows:
        line = (json.dumps(row, ensure_ascii=False) + "\n").encode("utf-8")
        if len(line) > max_bytes:
            raise ValueError("A single JSONL row is larger than the configured shard size.")
        if shard_lines and shard_size + len(line) > max_bytes:
            flush()
        shard_lines.append(line)
        shard_record_count += 1
        shard_size += len(line)

    flush()
    return shards


def build_summary(
    args: argparse.Namespace,
    run_label: str,
    output_root: Path,
    targets: list[scan.ServerTarget],
    rules: dict[str, Any],
    host_summaries: list[dict[str, Any]],
    services: list[dict[str, Any]],
    errors: list[dict[str, Any]],
    rows: list[dict[str, str]],
    csv_shards: list[dict[str, Any]],
    jsonl_shards: list[dict[str, Any]],
    max_bytes: int,
) -> dict[str, Any]:
    summary = scan.summarize_run(targets, host_summaries, services, errors)
    summary["runbook_rows"] = len(rows)
    summary["csv_shards"] = len(csv_shards)
    summary["jsonl_shards"] = len(jsonl_shards)
    return {
        "workflow": WORKFLOW_ID,
        "generated_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "run_label": run_label,
        "output_root": str(output_root),
        "input_path": str(args.runbook_csv),
        "dry_run": args.dry_run,
        "scan_options": {
            "ports": args.ports,
            "top_ports": args.top_ports,
            "assume_host_up": args.assume_host_up,
            "timeout_seconds": args.timeout_seconds,
        },
        "limits": {
            "max_targets": args.max_targets,
            "max_output_file_bytes": max_bytes,
        },
        "taxonomy": {
            "name": rules.get("taxonomy_name"),
            "version": rules.get("taxonomy_version"),
            "rules_path": str(args.rules),
        },
        "targets": [
            {
                "ip": target.target,
                "target_label": target.label,
            }
            for target in targets
        ],
        "summary": summary,
        "result_csv_shards": csv_shards,
        "result_jsonl_shards": jsonl_shards,
        "handling_notes": [
            "Scan only systems you own or are explicitly authorized to assess.",
            "Outputs may reveal sensitive service exposure details and should remain under data/private.",
            "The Nmap command uses service-version detection only and does not perform exploitation or vulnerability validation.",
            "Version strings can be misleading when distributions backport security patches; confirm findings with vendor package metadata and advisories.",
            "This runbook rejects ranges, CIDR blocks, wildcards, whitespace targets, and comma target lists.",
            "Result CSV and JSONL files are sharded so each result file stays under the configured byte limit.",
        ],
    }


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    try:
        if not args.dry_run and not args.i_own_these_servers:
            raise PermissionError(
                "Refusing to scan without --i-own-these-servers. Only scan systems you own or are authorized to assess."
            )

        targets = read_runbook_targets(args.runbook_csv, args.max_targets)
        rules = scan.load_rules(args.rules)
        max_bytes = scan.chunk_size_bytes(args.chunk_size_mb)
        run_label = scan.clean_label(args.run_label or args.runbook_csv.stem)
        timestamp = scan.utc_timestamp()
        output_root = args.output_dir / run_label / timestamp

        scan_args = argparse.Namespace(
            nmap_path=args.nmap_path,
            dry_run=args.dry_run,
            assume_host_up=args.assume_host_up,
            ports=args.ports,
            top_ports=args.top_ports,
            timeout_seconds=args.timeout_seconds,
            stop_on_error=args.stop_on_error,
        )
        host_summaries, services, errors = scan.scan_targets(scan_args, targets, rules)
        rows = build_runbook_rows(targets, host_summaries, services, errors)
        csv_shards = write_csv_shards(output_root / "csv", "runbook-results", rows, max_bytes)
        jsonl_shards = write_jsonl_shards(
            output_root / "jsonl",
            "runbook-results",
            rows,
            max_bytes,
        )
        summary = build_summary(
            args,
            run_label,
            output_root,
            targets,
            rules,
            host_summaries,
            services,
            errors,
            rows,
            csv_shards,
            jsonl_shards,
            max_bytes,
        )
        summary_info = scan.write_json_checked(
            output_root / "runbook-summary.json",
            summary,
            max_bytes,
        )
        manifest = {
            "workflow": WORKFLOW_ID,
            "generated_at_utc": summary["generated_at_utc"],
            "run_label": run_label,
            "output_root": str(output_root),
            "max_output_file_bytes": max_bytes,
            "runbook_csv": str(args.runbook_csv),
            "summary_json": summary_info,
            "result_csv_shards": csv_shards,
            "result_jsonl_shards": jsonl_shards,
        }
        manifest_info = scan.write_json_checked(output_root / "manifest.json", manifest, max_bytes)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(f"Targets processed: {len(targets)}")
    print(f"Runbook rows written: {len(rows)}")
    print(f"Open services detected: {len(services)}")
    print(f"Errors: {len(errors)}")
    print(f"Output root: {output_root}")
    print(f"Summary:     {summary_info['path']}")
    print(f"Manifest:    {manifest_info['path']}")
    for shard in csv_shards:
        print(f"CSV shard:   {shard['path']} ({shard['bytes']} bytes)")
    for shard in jsonl_shards:
        print(f"JSONL shard: {shard['path']} ({shard['bytes']} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
