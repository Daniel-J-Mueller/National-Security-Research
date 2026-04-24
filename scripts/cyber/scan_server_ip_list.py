#!/usr/bin/env python3
"""
Run owner-authorized Nmap service-version scans for a server IP list.

The batch workflow keeps output intentionally small: sharded CSV plus optional
sharded JSONL rows. It records service inventory from open ports only and does
not run exploit checks, brute force modules, vulnerability scripts, payloads, or
intrusive validation.
"""

from __future__ import annotations

import argparse
import csv
import ipaddress
import json
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_DIR = ROOT / "data" / "private" / "cybersecurity" / "runbook-outputs"
DEFAULT_TARGETS = ROOT / "data" / "private" / "cybersecurity" / "runbook-input" / "dry-run-input.csv"

DEFAULT_MAX_CHUNK_MB = 75
DEFAULT_MAX_TARGETS = 16
WORKFLOW_ID = "owner-authorized-batch-service-version-scan"

TARGET_FIELD_NAMES = ("target", "ip", "host", "hostname", "address")
LABEL_FIELD_NAMES = ("target_label", "label", "name", "asset_id", "server")
RESULT_CSV_FIELDS = [
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


@dataclass(frozen=True)
class ServerTarget:
    target: str
    label: str


@dataclass
class RunbookScanResult:
    host_summaries: list[dict[str, Any]]
    services: list[dict[str, Any]]
    errors: list[dict[str, Any]]
    rows: list[dict[str, Any]]
    csv_shards: list[dict[str, Any]]
    jsonl_shards: list[dict[str, Any]]


def clean_label(value: str) -> str:
    label = re.sub(r"[^A-Za-z0-9_.-]+", "_", value.strip())
    return label.strip("._") or "server"


def utc_timestamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def check_nmap(path: str) -> str:
    resolved = shutil.which(path)
    if resolved:
        return resolved
    candidate = Path(path)
    if candidate.exists():
        return str(candidate)
    raise FileNotFoundError(
        "Nmap was not found. Install Nmap or pass --nmap-path with the executable path."
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run Nmap service-version detection against a small list of servers "
            "you own or are authorized to scan, then write sharded CSV and JSONL."
        )
    )
    parser.add_argument(
        "--targets",
        type=Path,
        default=DEFAULT_TARGETS,
        help=(
            "Path to a JSON, JSONL, CSV, or TXT list of server IPs/hostnames. "
            "JSON may be a list or an object with a targets/servers/hosts list. "
            "Default: %(default)s"
        ),
    )
    parser.add_argument(
        "--i-own-these-servers",
        action="store_true",
        help="Required before running Nmap. Confirms authorization to scan every listed target.",
    )
    parser.add_argument(
        "--run-label",
        help="Deprecated; outputs are written directly under --output-dir.",
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
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Directory for private scan outputs.",
    )
    parser.add_argument(
        "--chunk-size-mb",
        type=float,
        default=DEFAULT_MAX_CHUNK_MB,
        help="Maximum size for each JSONL shard. Default: %(default)s MB.",
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
        help="Validate inputs and write planned target rows without running Nmap.",
    )
    parser.add_argument(
        "--no-jsonl",
        action="store_true",
        help="Write only the CSV output and skip JSONL shards.",
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


def target_identity(value: str) -> str:
    stripped = value.strip()
    try:
        return ipaddress.ip_address(stripped).compressed.lower()
    except ValueError:
        return stripped.rstrip(".").lower()


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
        key = target_identity(target.target)
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


def csv_cell(value: Any) -> str:
    if isinstance(value, list):
        return "; ".join(str(item) for item in value if item)
    return str(value or "")


def csv_bytes_for_row(row: dict[str, Any] | None = None) -> bytes:
    from io import StringIO

    buffer = StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=RESULT_CSV_FIELDS, lineterminator="\n")
    if row is None:
        writer.writeheader()
    else:
        writer.writerow({field: csv_cell(row.get(field, "")) for field in RESULT_CSV_FIELDS})
    return buffer.getvalue().encode("utf-8")


class CsvShardWriter:
    """Append CSV rows without keeping shard file handles open between writes."""

    def __init__(self, output_dir: Path, stem: str, max_bytes: int) -> None:
        self.output_dir = output_dir
        self.stem = stem
        self.max_bytes = max_bytes
        self.header = csv_bytes_for_row()
        if len(self.header) > max_bytes:
            raise ValueError("CSV header is larger than the configured shard size.")

        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.shards: list[dict[str, Any]] = []
        self.shard_index = 1
        self.current_size = 0
        self.current_record_count = 0

    def write_rows(self, rows: list[dict[str, Any]]) -> None:
        for row in rows:
            row_bytes = csv_bytes_for_row(row)
            if len(self.header) + len(row_bytes) > self.max_bytes:
                raise ValueError("A single CSV row is larger than the configured shard size.")
            if not self.shards or (
                self.current_record_count > 0 and self.current_size + len(row_bytes) > self.max_bytes
            ):
                self._start_shard()
            self._append_to_current_shard(row_bytes, record_count_delta=1)

    def finalize(self) -> list[dict[str, Any]]:
        if not self.shards:
            self._start_shard()
        return self.shards

    def _start_shard(self) -> None:
        path = self.output_dir / f"{self.stem}-{self.shard_index:04d}.csv"
        self.shards.append({"path": str(path), "bytes": 0, "record_count": 0})
        self.shard_index += 1
        with path.open("wb") as handle:
            handle.write(self.header)
        self.shards[-1]["bytes"] = len(self.header)
        self.current_size = len(self.header)
        self.current_record_count = 0

    def _append_to_current_shard(self, payload: bytes, record_count_delta: int = 0) -> None:
        path = Path(self.shards[-1]["path"])
        with path.open("ab") as handle:
            handle.write(payload)
        self.shards[-1]["bytes"] += len(payload)
        self.shards[-1]["record_count"] += record_count_delta
        self.current_size += len(payload)
        self.current_record_count += record_count_delta


class JsonlShardWriter:
    """Append JSONL rows without keeping shard file handles open between writes."""

    def __init__(self, output_dir: Path, stem: str, max_bytes: int) -> None:
        self.output_dir = output_dir
        self.stem = stem
        self.max_bytes = max_bytes
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.shards: list[dict[str, Any]] = []
        self.shard_index = 1
        self.current_size = 0
        self.current_record_count = 0

    def write_rows(self, rows: list[dict[str, Any]]) -> None:
        for row in rows:
            line = (
                json.dumps({field: row.get(field, "") for field in RESULT_CSV_FIELDS}, ensure_ascii=False)
                + "\n"
            ).encode("utf-8")
            if len(line) > self.max_bytes:
                raise ValueError("A single JSONL row is larger than the configured shard size.")
            if not self.shards or (
                self.current_record_count > 0 and self.current_size + len(line) > self.max_bytes
            ):
                self._start_shard()
            self._append_to_current_shard(line, record_count_delta=1)

    def finalize(self) -> list[dict[str, Any]]:
        if not self.shards:
            self._start_shard()
        return self.shards

    def _start_shard(self) -> None:
        path = self.output_dir / f"{self.stem}-{self.shard_index:04d}.jsonl"
        self.shards.append({"path": str(path), "bytes": 0, "record_count": 0})
        self.shard_index += 1
        self.current_size = 0
        self.current_record_count = 0
        with path.open("wb"):
            pass

    def _append_to_current_shard(self, payload: bytes, record_count_delta: int = 0) -> None:
        path = Path(self.shards[-1]["path"])
        with path.open("ab") as handle:
            handle.write(payload)
        self.shards[-1]["bytes"] += len(payload)
        self.shards[-1]["record_count"] += record_count_delta
        self.current_size += len(payload)
        self.current_record_count += record_count_delta


def write_csv_shards(
    output_dir: Path,
    stem: str,
    rows: list[dict[str, Any]],
    max_bytes: int,
) -> list[dict[str, Any]]:
    writer = CsvShardWriter(output_dir, stem, max_bytes)
    writer.write_rows(rows)
    return writer.finalize()


def write_jsonl_shards(
    output_dir: Path,
    stem: str,
    rows: list[dict[str, Any]],
    max_bytes: int,
) -> list[dict[str, Any]]:
    writer = JsonlShardWriter(output_dir, stem, max_bytes)
    writer.write_rows(rows)
    return writer.finalize()


def build_nmap_command(nmap_path: str, target: str, args: argparse.Namespace) -> list[str]:
    command = [nmap_path, "--open", "-sV", "--version-light", "-oX", "-"]
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

        open_service_count = 0
        if ports_node is not None:
            for port_node in ports_node.findall("port"):
                state_node = port_node.find("state")
                if state_node is not None and state_node.get("state") == "open":
                    open_service_count += 1

        summaries.append(
            {
                "input_target": server_target.target,
                "target_label": server_target.label,
                "detected_address": address_node.get("addr", "") if address_node is not None else "",
                "host_status": status_node.get("state", "unknown") if status_node is not None else "unknown",
                "open_service_count": open_service_count,
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
            "host_status": "no-host-record",
            "open_service_count": 0,
            "nmap_command": command,
            "nmap_stderr": nmap_stderr.strip(),
        }
    ]


def parse_open_services(xml_text: str) -> list[dict[str, Any]]:
    root = ET.fromstring(xml_text)
    services: list[dict[str, Any]] = []
    for host in root.findall("host"):
        address_node = host.find("address")
        host_address = address_node.get("addr") if address_node is not None else ""
        ports_node = host.find("ports")
        if ports_node is None:
            continue
        for port_node in ports_node.findall("port"):
            state_node = port_node.find("state")
            if state_node is None or state_node.get("state") != "open":
                continue
            service_node = port_node.find("service")
            cpes = [
                cpe.text.strip()
                for cpe in (service_node.findall("cpe") if service_node is not None else [])
                if cpe.text and cpe.text.strip()
            ]
            services.append(
                {
                    "host": host_address,
                    "port": port_node.get("portid", ""),
                    "protocol": port_node.get("protocol", ""),
                    "service_name": service_node.get("name", "") if service_node is not None else "",
                    "product": service_node.get("product", "") if service_node is not None else "",
                    "version": service_node.get("version", "") if service_node is not None else "",
                    "extrainfo": service_node.get("extrainfo", "") if service_node is not None else "",
                    "cpe": cpes,
                }
            )
    return sorted(services, key=lambda item: (str(item["host"]), str(item["protocol"]), int(item["port"] or 0)))


def enrich_services(
    services: list[dict[str, Any]],
    server_target: ServerTarget,
) -> list[dict[str, Any]]:
    enriched: list[dict[str, Any]] = []
    for service in services:
        record = dict(service)
        record["input_target"] = server_target.target
        record["target_label"] = server_target.label
        enriched.append(record)
    return enriched


def planned_host_summary(server_target: ServerTarget, command: list[str]) -> dict[str, Any]:
    return {
        "input_target": server_target.target,
        "target_label": server_target.label,
        "detected_address": "",
        "host_status": "dry-run-planned",
        "open_service_count": 0,
        "nmap_command": command,
        "nmap_stderr": "",
    }


def scan_target(
    args: argparse.Namespace,
    server_target: ServerTarget,
    nmap_path: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    command = build_nmap_command(nmap_path, server_target.target, args)
    if args.dry_run:
        return [planned_host_summary(server_target, command)], [], []

    try:
        xml_text, nmap_stderr, returncode = run_nmap(command, args.timeout_seconds)
        if returncode != 0:
            raise RuntimeError(
                f"Nmap exited with {returncode}. STDERR: {nmap_stderr.strip()}"
            )
        services = enrich_services(parse_open_services(xml_text), server_target)
        host_summaries = parse_host_summaries(xml_text, server_target, command, nmap_stderr)
        return host_summaries, services, []
    except Exception as exc:
        return (
            [],
            [],
            [
                {
                    "target": server_target.target,
                    "target_label": server_target.label,
                    "error": str(exc),
                }
            ],
        )


def scan_targets(
    args: argparse.Namespace,
    targets: list[ServerTarget],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    services: list[dict[str, Any]] = []
    host_summaries: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    nmap_path = args.nmap_path if args.dry_run else check_nmap(args.nmap_path)
    for server_target in targets:
        target_host_summaries, target_services, target_errors = scan_target(
            args,
            server_target,
            nmap_path,
        )
        host_summaries.extend(target_host_summaries)
        services.extend(target_services)
        errors.extend(target_errors)
        if target_errors and args.stop_on_error:
            break

    return host_summaries, services, errors


def build_target_worker_command(args: argparse.Namespace, server_target: ServerTarget) -> list[str]:
    worker_path = Path(__file__).with_name("scan_server_ip_once.py")
    command = [
        sys.executable,
        str(worker_path),
        "--target",
        server_target.target,
        "--target-label",
        server_target.label,
        "--nmap-path",
        args.nmap_path,
        "--timeout-seconds",
        str(args.timeout_seconds),
    ]
    if args.dry_run:
        command.append("--dry-run")
    elif getattr(args, "i_own_these_servers", False):
        command.append("--i-own-these-servers")
    if args.assume_host_up:
        command.append("--assume-host-up")
    if args.ports:
        command.extend(["--ports", args.ports])
    elif args.top_ports:
        command.extend(["--top-ports", str(args.top_ports)])
    return command


def worker_error(server_target: ServerTarget, message: str) -> list[dict[str, Any]]:
    return [
        {
            "target": server_target.target,
            "target_label": server_target.label,
            "error": message,
        }
    ]


def scan_target_in_worker(
    args: argparse.Namespace,
    server_target: ServerTarget,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    command = build_target_worker_command(args, server_target)
    timeout_seconds = 60 if args.dry_run else int(args.timeout_seconds) + 60
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        return [], [], worker_error(
            server_target,
            f"Per-target worker timed out after {timeout_seconds} seconds: {exc}",
        )

    if completed.returncode != 0:
        message = (completed.stderr or completed.stdout or "").strip()
        return [], [], worker_error(
            server_target,
            f"Per-target worker exited with {completed.returncode}: {message}",
        )

    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        return [], [], worker_error(
            server_target,
            f"Per-target worker returned invalid JSON: {exc}",
        )

    return (
        list(payload.get("host_summaries") or []),
        list(payload.get("services") or []),
        list(payload.get("errors") or []),
    )


def reset_output_dirs(output_root: Path) -> None:
    output_root.mkdir(parents=True, exist_ok=True)
    for child_name in ("csv", "jsonl"):
        child = output_root / child_name
        if child.exists():
            shutil.rmtree(child)


def host_key(row: dict[str, Any]) -> str:
    return target_identity(str(row.get("input_target") or row.get("target") or ""))


def service_to_result_row(
    service: dict[str, Any],
    host_summaries: dict[tuple[str, str], dict[str, Any]],
    target_summaries: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    target = str(service.get("input_target") or service.get("host") or "")
    host = str(service.get("host") or "")
    target_key = target_identity(target)
    summary = host_summaries.get((target_key, host)) or target_summaries.get(target_key, {})
    return {
        "target": target,
        "target_label": service.get("target_label", ""),
        "host": host,
        "host_status": summary.get("host_status", ""),
        "scan_status": "open-service",
        "port": service.get("port", ""),
        "protocol": service.get("protocol", ""),
        "service_name": service.get("service_name", ""),
        "product": service.get("product", ""),
        "version": service.get("version", ""),
        "extrainfo": service.get("extrainfo", ""),
        "cpe": service.get("cpe", []),
        "error": "",
    }


def host_summary_to_result_row(host: dict[str, Any]) -> dict[str, Any]:
    host_status = str(host.get("host_status") or "")
    if host_status == "dry-run-planned":
        scan_status = "dry-run-planned"
    elif int(host.get("open_service_count") or 0) == 0:
        scan_status = "no-open-services"
    else:
        scan_status = "host-summary"
    return {
        "target": host.get("input_target", ""),
        "target_label": host.get("target_label", ""),
        "host": host.get("detected_address", ""),
        "host_status": host_status,
        "scan_status": scan_status,
        "port": "",
        "protocol": "",
        "service_name": "",
        "product": "",
        "version": "",
        "extrainfo": "",
        "cpe": [],
        "error": "",
    }


def error_to_result_row(error: dict[str, Any]) -> dict[str, Any]:
    return {
        "target": error.get("target", ""),
        "target_label": error.get("target_label", ""),
        "host": "",
        "host_status": "",
        "scan_status": "error",
        "port": "",
        "protocol": "",
        "service_name": "",
        "product": "",
        "version": "",
        "extrainfo": "",
        "cpe": [],
        "error": error.get("error", ""),
    }


def not_scanned_row(target: ServerTarget) -> dict[str, Any]:
    return {
        "target": target.target,
        "target_label": target.label,
        "host": "",
        "host_status": "",
        "scan_status": "not-scanned",
        "port": "",
        "protocol": "",
        "service_name": "",
        "product": "",
        "version": "",
        "extrainfo": "",
        "cpe": [],
        "error": "",
    }


def dedupe_result_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, ...]] = set()
    unique_rows: list[dict[str, Any]] = []
    for row in rows:
        key = tuple(csv_cell(row.get(field, "")) for field in RESULT_CSV_FIELDS)
        if key in seen:
            continue
        seen.add(key)
        unique_rows.append(row)
    return unique_rows


def build_result_rows(
    targets: list[ServerTarget],
    host_summaries: list[dict[str, Any]],
    services: list[dict[str, Any]],
    errors: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    services_by_target: dict[str, list[dict[str, Any]]] = {}
    hosts_by_target: dict[str, list[dict[str, Any]]] = {}
    errors_by_target: dict[str, list[dict[str, Any]]] = {}
    host_summaries_by_target_host: dict[tuple[str, str], dict[str, Any]] = {}
    first_host_summary_by_target: dict[str, dict[str, Any]] = {}

    for service in services:
        services_by_target.setdefault(host_key(service), []).append(service)
    for host in host_summaries:
        key = host_key(host)
        hosts_by_target.setdefault(key, []).append(host)
        first_host_summary_by_target.setdefault(key, host)
        detected_address = str(host.get("detected_address") or "")
        if detected_address:
            host_summaries_by_target_host.setdefault((key, detected_address), host)
    for error in errors:
        errors_by_target.setdefault(target_identity(str(error.get("target") or "")), []).append(error)

    rows: list[dict[str, Any]] = []
    for target in targets:
        key = target_identity(target.target)
        target_rows: list[dict[str, Any]] = []
        for service in services_by_target.get(key, []):
            target_rows.append(
                service_to_result_row(
                    service,
                    host_summaries_by_target_host,
                    first_host_summary_by_target,
                )
            )
        if not target_rows and key not in errors_by_target:
            target_rows.extend(host_summary_to_result_row(host) for host in hosts_by_target.get(key, []))
        target_rows.extend(error_to_result_row(error) for error in errors_by_target.get(key, []))
        if not target_rows:
            target_rows.append(not_scanned_row(target))
        rows.extend(target_rows)

    return dedupe_result_rows(rows)


def scan_targets_to_sharded_outputs(
    args: argparse.Namespace,
    targets: list[ServerTarget],
    output_root: Path,
    max_bytes: int,
    write_jsonl: bool,
) -> RunbookScanResult:
    if not args.dry_run and not getattr(args, "i_own_these_servers", False):
        raise PermissionError(
            "Refusing to scan without --i-own-these-servers. Only scan systems you own or are authorized to assess."
        )

    csv_writer = CsvShardWriter(output_root / "csv", "runbook-results", max_bytes)
    jsonl_writer = (
        JsonlShardWriter(output_root / "jsonl", "runbook-results", max_bytes)
        if write_jsonl
        else None
    )

    host_summaries: list[dict[str, Any]] = []
    services: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []

    for index, server_target in enumerate(targets):
        target_host_summaries, target_services, target_errors = scan_target_in_worker(
            args,
            server_target,
        )
        host_summaries.extend(target_host_summaries)
        services.extend(target_services)
        errors.extend(target_errors)

        target_rows = build_result_rows(
            [server_target],
            target_host_summaries,
            target_services,
            target_errors,
        )
        rows.extend(target_rows)
        csv_writer.write_rows(target_rows)
        if jsonl_writer is not None:
            jsonl_writer.write_rows(target_rows)

        if target_errors and getattr(args, "stop_on_error", False):
            for skipped_target in targets[index + 1 :]:
                skipped_rows = [not_scanned_row(skipped_target)]
                rows.extend(skipped_rows)
                csv_writer.write_rows(skipped_rows)
                if jsonl_writer is not None:
                    jsonl_writer.write_rows(skipped_rows)
            break

    return RunbookScanResult(
        host_summaries=host_summaries,
        services=services,
        errors=errors,
        rows=rows,
        csv_shards=csv_writer.finalize(),
        jsonl_shards=jsonl_writer.finalize() if jsonl_writer is not None else [],
    )


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    try:
        if not args.dry_run and not args.i_own_these_servers:
            raise PermissionError(
                "Refusing to scan without --i-own-these-servers. Only scan systems you own or are authorized to assess."
            )

        targets = load_targets(args.targets, args.max_targets)
        max_bytes = chunk_size_bytes(args.chunk_size_mb)
        output_root = args.output_dir
        reset_output_dirs(output_root)

        result = scan_targets_to_sharded_outputs(
            args,
            targets,
            output_root,
            max_bytes,
            write_jsonl=not args.no_jsonl,
        )
        host_summaries = result.host_summaries
        services = result.services
        errors = result.errors
        rows = result.rows
        csv_shards = result.csv_shards
        jsonl_shards = result.jsonl_shards
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(f"Targets processed: {len(targets)}")
    print(f"Rows written: {len(rows)}")
    print(f"Open services detected: {len(services)}")
    print(f"Errors: {len(errors)}")
    for shard in csv_shards:
        print(f"CSV shard: {shard['path']} ({shard['bytes']} bytes)")
    for shard in jsonl_shards:
        print(f"JSONL shard: {shard['path']} ({shard['bytes']} bytes)")
    if args.dry_run:
        for host in host_summaries:
            print("Planned command: " + " ".join(str(part) for part in host.get("nmap_command", [])))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
