#!/usr/bin/env python3
"""
Run owner-authorized Nmap service-version scans for a small server IP list.

Outputs are JSON-first and service records are chunked so no JSON output file
exceeds the configured size limit. The workflow performs inventory-oriented
version detection only; it does not run exploit checks, brute force modules, or
vulnerability validation scripts.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import ipaddress
import json
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

try:
    from categorize_server_versions import (
        DEFAULT_OUTPUT_DIR,
        DEFAULT_RULES,
        check_nmap,
        clean_label,
        load_rules,
        parse_nmap_xml,
        utc_timestamp,
    )
except ImportError:
    from .categorize_server_versions import (
        DEFAULT_OUTPUT_DIR,
        DEFAULT_RULES,
        check_nmap,
        clean_label,
        load_rules,
        parse_nmap_xml,
        utc_timestamp,
    )


DEFAULT_MAX_CHUNK_MB = 75
DEFAULT_MAX_TARGETS = 16
DEFAULT_REPORT_SERVICE_LIMIT = 200
WORKFLOW_ID = "owner-authorized-batch-service-version-scan"

TARGET_FIELD_NAMES = ("target", "ip", "host", "hostname", "address")
LABEL_FIELD_NAMES = ("label", "name", "asset_id", "server")


@dataclass(frozen=True)
class ServerTarget:
    target: str
    label: str


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run Nmap service-version detection against a small list of servers "
            "you own or are authorized to scan, then write chunked JSON outputs "
            "and a defensive report."
        )
    )
    parser.add_argument(
        "--targets",
        type=Path,
        required=True,
        help=(
            "Path to a JSON, JSONL, CSV, or TXT list of server IPs/hostnames. "
            "JSON may be a list or an object with a targets/servers/hosts list."
        ),
    )
    parser.add_argument(
        "--i-own-these-servers",
        action="store_true",
        help="Required before running Nmap. Confirms authorization to scan every listed target.",
    )
    parser.add_argument(
        "--run-label",
        help="Safe local label for the output folder. Defaults to the target file name.",
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
        default=DEFAULT_RULES,
        help="Category taxonomy and optional version baseline rules.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Directory for private scan outputs.",
    )
    parser.add_argument(
        "--chunk-size-mb",
        type=float,
        default=DEFAULT_MAX_CHUNK_MB,
        help="Maximum size for each JSON output file. Default: %(default)s MB.",
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
        help="Validate inputs and write the planned commands without running Nmap.",
    )
    parser.add_argument(
        "--report-service-limit",
        type=int,
        default=DEFAULT_REPORT_SERVICE_LIMIT,
        help="Maximum service rows to include in the Markdown report table.",
    )
    return parser


def read_json_targets(path: Path) -> list[Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("targets", "servers", "hosts"):
            values = payload.get(key)
            if isinstance(values, list):
                return values
    raise ValueError(
        "JSON target file must be a list, or an object with a targets, servers, or hosts list."
    )


def read_jsonl_targets(path: Path) -> list[Any]:
    entries: list[Any] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            try:
                entries.append(json.loads(stripped))
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSONL on line {line_number}: {exc}") from exc
    return entries


def read_csv_targets(path: Path) -> list[dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise ValueError(f"No header row found in {path}")
        return [dict(row) for row in reader]


def read_text_targets(path: Path) -> list[str]:
    entries: list[str] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            entries.append(stripped)
    return entries


def looks_like_single_target(value: str) -> bool:
    stripped = value.strip()
    if not stripped:
        return False
    if any(marker in stripped for marker in ("/", "*", ",")):
        return False
    if re.search(r"\s", stripped):
        return False
    try:
        ipaddress.ip_address(stripped)
        return True
    except ValueError:
        pass
    if len(stripped) > 253:
        return False
    labels = stripped.rstrip(".").split(".")
    if not labels:
        return False
    label_regex = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$")
    return all(label_regex.match(label) for label in labels)


def validate_target(value: str) -> str:
    target = value.strip()
    if not looks_like_single_target(target):
        raise ValueError(
            f"Refusing target {value!r}. Provide exact IPs or DNS names only; ranges, CIDR blocks, wildcards, and comma lists are not accepted."
        )
    return target


def first_non_empty(row: dict[str, Any], field_names: tuple[str, ...]) -> str | None:
    lower_map = {key.lower(): value for key, value in row.items()}
    for field in field_names:
        value = lower_map.get(field)
        if value is not None and str(value).strip():
            return str(value).strip()
    return None


def normalize_target_entry(entry: Any, index: int) -> ServerTarget:
    if isinstance(entry, str):
        target = validate_target(entry)
        return ServerTarget(target=target, label=clean_label(target))

    if not isinstance(entry, dict):
        raise ValueError(f"Target entry {index} must be a string or object.")

    target_value = first_non_empty(entry, TARGET_FIELD_NAMES)
    label_value = first_non_empty(entry, LABEL_FIELD_NAMES)

    if not target_value:
        server_value = entry.get("server")
        if server_value and looks_like_single_target(str(server_value)):
            target_value = str(server_value).strip()

    if not target_value:
        raise ValueError(
            f"Target entry {index} is missing one of these fields: {', '.join(TARGET_FIELD_NAMES)}."
        )

    target = validate_target(str(target_value))
    label = clean_label(label_value or target)
    return ServerTarget(target=target, label=label)


def load_targets(path: Path, max_targets: int) -> list[ServerTarget]:
    if not path.exists():
        raise FileNotFoundError(f"Target file not found: {path}")

    suffix = path.suffix.lower()
    if suffix == ".json":
        raw_entries = read_json_targets(path)
    elif suffix in {".jsonl", ".ndjson"}:
        raw_entries = read_jsonl_targets(path)
    elif suffix == ".csv":
        raw_entries = read_csv_targets(path)
    else:
        raw_entries = read_text_targets(path)

    targets: list[ServerTarget] = []
    seen: set[str] = set()
    for index, entry in enumerate(raw_entries, start=1):
        target = normalize_target_entry(entry, index)
        key = target.target.lower()
        if key in seen:
            continue
        seen.add(key)
        targets.append(target)

    if not targets:
        raise ValueError(f"No targets found in {path}")
    if max_targets < 1:
        raise ValueError("--max-targets must be at least 1")
    if len(targets) > max_targets:
        raise ValueError(
            f"Refusing to scan {len(targets)} targets in one run; --max-targets is {max_targets}."
        )
    return targets


def chunk_size_bytes(chunk_size_mb: float) -> int:
    if chunk_size_mb <= 0:
        raise ValueError("--chunk-size-mb must be greater than 0")
    return int(chunk_size_mb * 1024 * 1024)


def serialize_json_bytes(payload: Any) -> bytes:
    return (json.dumps(payload, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def write_json_checked(path: Path, payload: Any, max_bytes: int) -> dict[str, Any]:
    encoded = serialize_json_bytes(payload)
    if len(encoded) > max_bytes:
        raise ValueError(
            f"Refusing to write {path}; JSON would be {len(encoded):,} bytes, above the {max_bytes:,}-byte limit."
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(encoded)
    return {
        "path": str(path),
        "bytes": len(encoded),
        "sha256": hashlib.sha256(encoded).hexdigest(),
    }


def chunk_records(
    records: list[dict[str, Any]],
    metadata: dict[str, Any],
    output_dir: Path,
    stem: str,
    max_bytes: int,
) -> list[dict[str, Any]]:
    output_dir.mkdir(parents=True, exist_ok=True)
    chunks: list[dict[str, Any]] = []
    current_records: list[dict[str, Any]] = []
    chunk_index = 1

    def make_payload(index: int, chunk_rows: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "metadata": metadata,
            "chunk": {
                "index": index,
                "record_count": len(chunk_rows),
                "max_bytes": max_bytes,
            },
            "records": chunk_rows,
        }

    if not records:
        path = output_dir / f"{stem}-0001.json"
        info = write_json_checked(path, make_payload(1, []), max_bytes)
        info["record_count"] = 0
        chunks.append(info)
        return chunks

    for record in records:
        candidate_records = current_records + [record]
        candidate_payload = make_payload(chunk_index, candidate_records)
        if len(serialize_json_bytes(candidate_payload)) <= max_bytes:
            current_records = candidate_records
            continue

        if not current_records:
            raise ValueError(
                "A single service record is larger than the configured JSON chunk size."
            )

        path = output_dir / f"{stem}-{chunk_index:04d}.json"
        info = write_json_checked(path, make_payload(chunk_index, current_records), max_bytes)
        info["record_count"] = len(current_records)
        chunks.append(info)
        chunk_index += 1
        current_records = [record]

    if current_records:
        path = output_dir / f"{stem}-{chunk_index:04d}.json"
        info = write_json_checked(path, make_payload(chunk_index, current_records), max_bytes)
        info["record_count"] = len(current_records)
        chunks.append(info)

    return chunks


def build_nmap_command(nmap_path: str, target: str, args: argparse.Namespace) -> list[str]:
    command = [nmap_path, "-sV", "--version-light", "-oX", "-"]
    if args.assume_host_up:
        command.append("-Pn")
    if args.ports:
        command.extend(["-p", args.ports])
    elif args.top_ports:
        command.extend(["--top-ports", str(args.top_ports)])
    command.append(target)
    return command


def run_nmap(command: list[str], timeout_seconds: int) -> tuple[str, str, int]:
    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
    )
    return completed.stdout, completed.stderr, completed.returncode


def parse_host_summaries(
    xml_text: str,
    server_target: ServerTarget,
    command: list[str],
    nmap_stderr: str,
) -> list[dict[str, Any]]:
    root = ET.fromstring(xml_text)
    summaries: list[dict[str, Any]] = []
    for host in root.findall("host"):
        status_node = host.find("status")
        address_node = host.find("address")
        ports_node = host.find("ports")
        hostnames_node = host.find("hostnames")

        state_counts: Counter[str] = Counter()
        if ports_node is not None:
            for port_node in ports_node.findall("port"):
                state_node = port_node.find("state")
                state = state_node.get("state", "unknown") if state_node is not None else "unknown"
                state_counts[state] += 1

        hostnames = []
        if hostnames_node is not None:
            hostnames = [
                item.get("name", "")
                for item in hostnames_node.findall("hostname")
                if item.get("name")
            ]

        summaries.append(
            {
                "input_target": server_target.target,
                "target_label": server_target.label,
                "detected_address": address_node.get("addr", "") if address_node is not None else "",
                "hostnames": hostnames,
                "host_status": status_node.get("state", "unknown") if status_node is not None else "unknown",
                "port_state_counts": dict(sorted(state_counts.items())),
                "open_service_count": state_counts.get("open", 0),
                "nmap_command": command,
                "nmap_stderr": nmap_stderr.strip(),
            }
        )

    if summaries:
        return summaries

    return [
        {
            "input_target": server_target.target,
            "target_label": server_target.label,
            "detected_address": "",
            "hostnames": [],
            "host_status": "no-host-record",
            "port_state_counts": {},
            "open_service_count": 0,
            "nmap_command": command,
            "nmap_stderr": nmap_stderr.strip(),
        }
    ]


def enrich_services(
    services: list[dict[str, Any]],
    server_target: ServerTarget,
    command: list[str],
) -> list[dict[str, Any]]:
    enriched: list[dict[str, Any]] = []
    for service in services:
        record = dict(service)
        record["input_target"] = server_target.target
        record["target_label"] = server_target.label
        record["nmap_command"] = command
        enriched.append(record)
    return enriched


def summarize_run(
    targets: list[ServerTarget],
    host_summaries: list[dict[str, Any]],
    services: list[dict[str, Any]],
    errors: list[dict[str, Any]],
) -> dict[str, Any]:
    categories = Counter(service.get("vx_category", "") for service in services)
    flags = Counter(flag["id"] for service in services for flag in service.get("flags", []))
    ports = Counter(str(service.get("port", "")) for service in services)
    services_by_target = Counter(service.get("target_label", "") for service in services)
    hosts_by_status = Counter(host.get("host_status", "unknown") for host in host_summaries)
    return {
        "targets_requested": len(targets),
        "hosts_reported": len(host_summaries),
        "targets_with_errors": len({error.get("target") for error in errors}),
        "errors": len(errors),
        "open_services": len(services),
        "hosts_by_status": dict(sorted(hosts_by_status.items())),
        "categories": dict(sorted(categories.items())),
        "flags": dict(sorted(flags.items())),
        "open_ports": dict(sorted(ports.items(), key=lambda item: int(item[0]) if item[0].isdigit() else 0)),
        "services_by_target": dict(sorted(services_by_target.items())),
    }


def markdown_escape(value: Any) -> str:
    text = "" if value is None else str(value)
    return text.replace("|", "\\|").replace("\n", " ")


def flags_text(service: dict[str, Any]) -> str:
    return ", ".join(flag.get("id", "") for flag in service.get("flags", []) if flag.get("id"))


def build_markdown_report(
    report: dict[str, Any],
    services: list[dict[str, Any]],
    service_limit: int,
) -> str:
    summary = report["summary"]
    lines = [
        "# Server Version Scan Report",
        "",
        f"- Generated UTC: {report['generated_at_utc']}",
        f"- Run label: `{markdown_escape(report['run_label'])}`",
        f"- Target file: `{markdown_escape(report['input_path'])}`",
        f"- Targets requested: {summary['targets_requested']}",
        f"- Open services detected: {summary['open_services']}",
        f"- Scan errors: {summary['errors']}",
        "",
        "## Target Summary",
        "",
        "| Target | Label | Status | Open Services | Notes |",
        "| --- | --- | --- | ---: | --- |",
    ]

    error_by_target = {error["target"]: error for error in report["errors"]}
    summarized_targets = set()
    for host in report["hosts"]:
        summarized_targets.add(host["input_target"])
        notes = error_by_target.get(host["input_target"], {}).get("error", "")
        lines.append(
            "| "
            + " | ".join(
                [
                    markdown_escape(host["input_target"]),
                    markdown_escape(host["target_label"]),
                    markdown_escape(host["host_status"]),
                    markdown_escape(host["open_service_count"]),
                    markdown_escape(notes),
                ]
            )
            + " |"
        )

    if report["errors"]:
        for error in report["errors"]:
            if error.get("target") in summarized_targets:
                continue
            lines.append(
                "| "
                + " | ".join(
                    [
                        markdown_escape(error.get("target", "")),
                        markdown_escape(error.get("target_label", "")),
                        "error",
                        "0",
                        markdown_escape(error.get("error", "")),
                    ]
                )
                + " |"
            )

    lines.extend(["", "## Category Summary", ""])
    if summary["categories"]:
        for category, count in summary["categories"].items():
            lines.append(f"- `{category}`: {count}")
    else:
        lines.append("- No open services were categorized.")

    lines.extend(["", "## Flag Summary", ""])
    if summary["flags"]:
        for flag, count in summary["flags"].items():
            lines.append(f"- `{flag}`: {count}")
    else:
        lines.append("- No defensive service flags were detected.")

    lines.extend(
        [
            "",
            "## Service Findings",
            "",
            "| Target | Port | Service | Product | Version | Category | Flags |",
            "| --- | ---: | --- | --- | --- | --- | --- |",
        ]
    )

    rows = services[: max(service_limit, 0)]
    for service in rows:
        lines.append(
            "| "
            + " | ".join(
                [
                    markdown_escape(service.get("target_label", service.get("host", ""))),
                    markdown_escape(service.get("port", "")),
                    markdown_escape(service.get("service_name", "")),
                    markdown_escape(service.get("product", "")),
                    markdown_escape(service.get("version", "")),
                    markdown_escape(service.get("vx_category", "")),
                    markdown_escape(flags_text(service)),
                ]
            )
            + " |"
        )

    if len(services) > len(rows):
        lines.extend(
            [
                "",
                f"Only the first {len(rows)} service rows are shown here. See the JSON chunks for all records.",
            ]
        )
    elif not services:
        lines.append("|  |  |  |  |  | No open services detected |  |")

    lines.extend(
        [
            "",
            "## Handling Notes",
            "",
        ]
    )
    for note in report["handling_notes"]:
        lines.append(f"- {note}")

    return "\n".join(lines) + "\n"


def build_report(
    args: argparse.Namespace,
    run_label: str,
    output_root: Path,
    targets: list[ServerTarget],
    rules: dict[str, Any],
    host_summaries: list[dict[str, Any]],
    services: list[dict[str, Any]],
    errors: list[dict[str, Any]],
    service_chunks: list[dict[str, Any]],
    max_bytes: int,
) -> dict[str, Any]:
    return {
        "workflow": WORKFLOW_ID,
        "generated_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "run_label": run_label,
        "output_root": str(output_root),
        "input_path": str(args.targets),
        "dry_run": args.dry_run,
        "scan_options": {
            "ports": args.ports,
            "top_ports": args.top_ports,
            "assume_host_up": args.assume_host_up,
            "timeout_seconds": args.timeout_seconds,
        },
        "limits": {
            "max_targets": args.max_targets,
            "max_json_chunk_bytes": max_bytes,
            "report_service_limit": args.report_service_limit,
        },
        "taxonomy": {
            "name": rules.get("taxonomy_name"),
            "version": rules.get("taxonomy_version"),
            "rules_path": str(args.rules),
        },
        "targets": [
            {
                "target": target.target,
                "label": target.label,
            }
            for target in targets
        ],
        "summary": summarize_run(targets, host_summaries, services, errors),
        "hosts": host_summaries,
        "errors": errors,
        "service_record_chunks": service_chunks,
        "handling_notes": [
            "Scan only systems you own or are explicitly authorized to assess.",
            "Outputs may reveal sensitive service exposure details and should remain under data/private.",
            "The Nmap command uses service-version detection only and does not perform exploitation or vulnerability validation.",
            "Version strings can be misleading when distributions backport security patches; confirm findings with vendor package metadata and advisories.",
            "This batch workflow rejects ranges, CIDR blocks, wildcards, and comma target lists by default.",
        ],
    }


def planned_host_summary(server_target: ServerTarget, command: list[str]) -> dict[str, Any]:
    return {
        "input_target": server_target.target,
        "target_label": server_target.label,
        "detected_address": "",
        "hostnames": [],
        "host_status": "dry-run-planned",
        "port_state_counts": {},
        "open_service_count": 0,
        "nmap_command": command,
        "nmap_stderr": "",
    }


def scan_targets(
    args: argparse.Namespace,
    targets: list[ServerTarget],
    rules: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    services: list[dict[str, Any]] = []
    host_summaries: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    nmap_path = args.nmap_path if args.dry_run else check_nmap(args.nmap_path)
    for server_target in targets:
        command = build_nmap_command(nmap_path, server_target.target, args)
        if args.dry_run:
            host_summaries.append(planned_host_summary(server_target, command))
            continue

        try:
            xml_text, nmap_stderr, returncode = run_nmap(command, args.timeout_seconds)
            if returncode != 0:
                raise RuntimeError(
                    f"Nmap exited with {returncode}. STDERR: {nmap_stderr.strip()}"
                )
            parsed_services = parse_nmap_xml(xml_text, rules)
            services.extend(enrich_services(parsed_services, server_target, command))
            host_summaries.extend(
                parse_host_summaries(xml_text, server_target, command, nmap_stderr)
            )
        except Exception as exc:
            errors.append(
                {
                    "target": server_target.target,
                    "target_label": server_target.label,
                    "error": str(exc),
                    "nmap_command": command,
                }
            )
            if args.stop_on_error:
                break

    return host_summaries, services, errors


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    try:
        if not args.dry_run and not args.i_own_these_servers:
            raise PermissionError(
                "Refusing to scan without --i-own-these-servers. Only scan systems you own or are authorized to assess."
            )

        targets = load_targets(args.targets, args.max_targets)
        rules = load_rules(args.rules)
        max_bytes = chunk_size_bytes(args.chunk_size_mb)
        run_label = clean_label(args.run_label or args.targets.stem or "server-ip-list")
        timestamp = utc_timestamp()
        output_root = args.output_dir / run_label / timestamp
        json_dir = output_root / "json"

        host_summaries, services, errors = scan_targets(args, targets, rules)
        metadata = {
            "workflow": WORKFLOW_ID,
            "generated_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "run_label": run_label,
            "input_path": str(args.targets),
            "taxonomy": {
                "name": rules.get("taxonomy_name"),
                "version": rules.get("taxonomy_version"),
                "rules_path": str(args.rules),
            },
        }
        service_chunks = chunk_records(
            services,
            metadata,
            json_dir,
            "service-records",
            max_bytes,
        )
        report = build_report(
            args,
            run_label,
            output_root,
            targets,
            rules,
            host_summaries,
            services,
            errors,
            service_chunks,
            max_bytes,
        )
        report_json_info = write_json_checked(
            json_dir / "server-version-scan-report.json",
            report,
            max_bytes,
        )
        manifest = {
            "workflow": WORKFLOW_ID,
            "generated_at_utc": report["generated_at_utc"],
            "run_label": run_label,
            "output_root": str(output_root),
            "max_json_chunk_bytes": max_bytes,
            "report_json": report_json_info,
            "service_record_chunks": service_chunks,
        }
        manifest_info = write_json_checked(json_dir / "manifest.json", manifest, max_bytes)

        markdown_path = output_root / "server-version-scan-report.md"
        markdown_path.parent.mkdir(parents=True, exist_ok=True)
        markdown_path.write_text(
            build_markdown_report(report, services, args.report_service_limit),
            encoding="utf-8",
        )
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(f"Targets processed: {len(targets)}")
    print(f"Open services detected: {len(services)}")
    print(f"Errors: {len(errors)}")
    print(f"Report JSON: {report_json_info['path']}")
    print(f"Manifest:    {manifest_info['path']}")
    print(f"Markdown:    {markdown_path}")
    for chunk in service_chunks:
        print(f"Chunk:       {chunk['path']} ({chunk['bytes']} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
