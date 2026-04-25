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
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from collections.abc import Callable, Iterable, Iterator
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_DIR = ROOT / "data" / "private" / "cybersecurity" / "runbook-outputs"
DEFAULT_TARGETS = ROOT / "data" / "private" / "cybersecurity" / "runbook-input" / "dry-run-input.csv"
DEFAULT_RUN_DATA = Path(__file__).with_name("cyber-runbook") / "run-data.info"

DEFAULT_MAX_CHUNK_MB = 75
DEFAULT_MAX_TARGETS = 0
DEFAULT_TIMEOUT_SECONDS = 120
DEFAULT_WORKERS = 128
WORKFLOW_ID = "owner-authorized-batch-service-version-scan"
IPV4_ZERO_BLOCK_ROWS = ipaddress.ip_network("0.0.0.0/8").num_addresses
GENERATED_IPV4_FIRST_KEPT_ADDRESS_INDEX = IPV4_ZERO_BLOCK_ROWS
GENERATED_IPV4_FIRST_KEPT_CSV_LINE = IPV4_ZERO_BLOCK_ROWS + 2

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
    source_index: int = 0


@dataclass
class RunbookScanResult:
    host_summaries: list[dict[str, Any]]
    services: list[dict[str, Any]]
    errors: list[dict[str, Any]]
    rows: list[dict[str, Any]]
    csv_shards: list[dict[str, Any]]
    jsonl_shards: list[dict[str, Any]]
    target_count: int = 0
    row_count: int = 0
    service_count: int = 0
    error_count: int = 0


@dataclass
class TargetScanResult:
    target: ServerTarget
    host_summaries: list[dict[str, Any]]
    services: list[dict[str, Any]]
    errors: list[dict[str, Any]]
    rows: list[dict[str, Any]]


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
            "Run Nmap service-version detection against a list of servers "
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
        help="Optional limit for one run. Use 0 for no limit. Default: %(default)s.",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=DEFAULT_TIMEOUT_SECONDS,
        help="Per-target Nmap timeout. Default: %(default)s seconds.",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=DEFAULT_WORKERS,
        help="Concurrent per-target Nmap workers. Default: %(default)s.",
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
    parser.add_argument(
        "--run-data",
        type=Path,
        default=DEFAULT_RUN_DATA,
        help="Small checkpoint file that stores the next input index for resumable CSV streaming.",
    )
    parser.add_argument(
        "--reset-run-data",
        action="store_true",
        help="Ignore and reset the checkpoint so this run starts at the first input row.",
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


def read_jsonl_targets(path: Path, start_index: int = 1) -> Iterator[tuple[int, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if line_number < start_index:
                continue
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            try:
                yield line_number, json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSONL on line {line_number}: {exc}") from exc


def read_csv_targets(path: Path, start_index: int = 2) -> Iterator[tuple[int, dict[str, str]]]:
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise ValueError(f"No header row found in {path}")
        if should_stream_skip_generated_ipv4_zero_block(path, start_index):
            start_index = GENERATED_IPV4_FIRST_KEPT_CSV_LINE
        for line_number, row in enumerate(reader, start=2):
            if line_number < start_index:
                continue
            yield line_number, dict(row)


def read_text_targets(path: Path, start_index: int = 1) -> Iterator[tuple[int, str]]:
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if line_number < start_index:
                continue
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            yield line_number, stripped


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


def looks_like_generated_ipv4_input(path: Path) -> bool:
    try:
        with path.open("r", encoding="utf-8-sig") as handle:
            first_lines = [handle.readline().strip() for _line in range(4)]
    except OSError:
        return False
    return first_lines == ["ip", "0.0.0.0", "0.0.0.1", "0.0.0.2"]


def fast_forward_generated_ipv4_start_index(path: Path, start_index: int) -> int:
    if not should_stream_skip_generated_ipv4_zero_block(path, start_index):
        return start_index
    return GENERATED_IPV4_FIRST_KEPT_CSV_LINE


def should_stream_skip_generated_ipv4_zero_block(path: Path, start_index: int) -> bool:
    if path.suffix.lower() != ".csv":
        return False
    if not looks_like_generated_ipv4_input(path):
        return False
    if start_index >= GENERATED_IPV4_FIRST_KEPT_CSV_LINE:
        return False
    return True


def guard_live_target_file(args: argparse.Namespace, path: Path) -> None:
    return


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
        return ServerTarget(target=target, label=clean_label(target), source_index=index)

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
    return ServerTarget(target=target, label=label, source_index=index)


def first_target_index(path: Path) -> int:
    return 2 if path.suffix.lower() == ".csv" else 1


def iter_target_entries(path: Path, start_index: int | None = None) -> Iterator[tuple[int, Any]]:
    if not path.exists():
        raise FileNotFoundError(f"Target file not found: {path}")

    start = max(start_index or first_target_index(path), first_target_index(path))
    suffix = path.suffix.lower()
    if suffix == ".json":
        for index, entry in enumerate(read_json_targets(path), start=1):
            if index >= start:
                yield index, entry
    elif suffix in {".jsonl", ".ndjson"}:
        yield from read_jsonl_targets(path, start)
    elif suffix == ".csv":
        yield from read_csv_targets(path, start)
    else:
        yield from read_text_targets(path, start)


def iter_targets(
    path: Path,
    max_targets: int,
    start_index: int | None = None,
    *,
    skip_duplicates: bool = False,
    stop_at_max: bool = True,
) -> Iterator[ServerTarget]:
    if max_targets < 0:
        raise ValueError("--max-targets must be 0 or greater")

    seen: set[str] | None = set() if skip_duplicates else None
    target_count = 0
    for index, entry in iter_target_entries(path, start_index):
        if seen is None and max_targets and target_count >= max_targets:
            break
        target = normalize_target_entry(entry, index)
        if seen is not None:
            key = target_identity(target.target)
            if key in seen:
                continue
            seen.add(key)
        if max_targets and target_count >= max_targets:
            if stop_at_max:
                break
            raise ValueError(
                f"Refusing to scan more than {max_targets} targets in one run; "
                f"--max-targets is {max_targets}."
            )
        target_count += 1
        yield target

    if target_count == 0:
        raise ValueError(
            f"No targets found in {path} at or after index {start_index or first_target_index(path)}"
        )


def load_targets(path: Path, max_targets: int) -> list[ServerTarget]:
    targets = list(iter_targets(path, max_targets, skip_duplicates=True, stop_at_max=False))

    if not targets:
        raise ValueError(f"No targets found in {path}")
    if max_targets < 0:
        raise ValueError("--max-targets must be 0 or greater")
    if max_targets and len(targets) > max_targets:
        raise ValueError(
            f"Refusing to scan {len(targets)} targets in one run; --max-targets is {max_targets}."
        )
    return targets


def read_run_data_index(run_data_path: Path, target_path: Path, default_index: int) -> int:
    if not run_data_path.exists():
        return default_index

    text = run_data_path.read_text(encoding="utf-8").strip()
    if not text:
        return default_index

    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        try:
            return max(default_index, int(text))
        except ValueError as exc:
            raise ValueError(f"Invalid run-data checkpoint in {run_data_path}") from exc

    if not isinstance(payload, dict):
        raise ValueError(f"Invalid run-data checkpoint in {run_data_path}")

    recorded_target = payload.get("target_file")
    if recorded_target and str(recorded_target) != str(target_path.resolve()):
        return default_index

    try:
        return max(default_index, int(payload.get("next_index", default_index)))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid next_index in {run_data_path}") from exc


def acquire_run_data_lock(lock_path: Path, timeout_seconds: float = 30.0) -> None:
    deadline = time.monotonic() + timeout_seconds
    while True:
        try:
            lock_fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            try:
                os.write(lock_fd, f"{os.getpid()}\n{datetime.now(UTC).isoformat()}\n".encode("utf-8"))
            finally:
                os.close(lock_fd)
            return
        except FileExistsError:
            try:
                age_seconds = time.time() - lock_path.stat().st_mtime
                if age_seconds > timeout_seconds:
                    lock_path.unlink()
                    continue
            except FileNotFoundError:
                continue
        except PermissionError:
            pass

        if time.monotonic() >= deadline:
            raise TimeoutError(f"Timed out waiting for checkpoint lock: {lock_path}")
        time.sleep(0.05)


def release_run_data_lock(lock_path: Path) -> None:
    for _attempt in range(20):
        try:
            lock_path.unlink()
            return
        except FileNotFoundError:
            return
        except PermissionError:
            time.sleep(0.05)


def replace_with_retries(temp_path: Path, destination: Path, timeout_seconds: float = 10.0) -> None:
    deadline = time.monotonic() + timeout_seconds
    while True:
        try:
            temp_path.replace(destination)
            return
        except PermissionError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.05)


def write_run_data_index(
    run_data_path: Path,
    target_path: Path,
    next_index: int,
    *,
    allow_decrease: bool = False,
) -> None:
    run_data_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = run_data_path.with_name(f"{run_data_path.name}.lock")
    temp_path: Path | None = None
    acquire_run_data_lock(lock_path)
    try:
        index_to_write = next_index
        if not allow_decrease:
            current_index = read_run_data_index(run_data_path, target_path, next_index)
            index_to_write = max(current_index, next_index)

        payload = {
            "target_file": str(target_path.resolve()),
            "next_index": index_to_write,
            "updated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        }
        temp_fd, temp_name = tempfile.mkstemp(
            prefix=f"{run_data_path.name}.",
            suffix=".tmp",
            dir=run_data_path.parent,
            text=True,
        )
        temp_path = Path(temp_name)
        with os.fdopen(temp_fd, "w", encoding="utf-8") as temp_handle:
            temp_handle.write(json.dumps(payload, indent=2) + "\n")
        replace_with_retries(temp_path, run_data_path)
        temp_path = None
    finally:
        release_run_data_lock(lock_path)
        if temp_path is not None:
            try:
                temp_path.unlink()
            except FileNotFoundError:
                pass


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


def next_shard_index(output_dir: Path, stem: str, suffix: str) -> int:
    if not output_dir.exists():
        return 1

    pattern = re.compile(rf"^{re.escape(stem)}-(\d+)\.{re.escape(suffix)}$")
    highest = 0
    for path in output_dir.iterdir():
        match = pattern.match(path.name)
        if match:
            highest = max(highest, int(match.group(1)))
    return highest + 1


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
        self.shard_index = next_shard_index(output_dir, stem, "csv")
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
        self.shard_index = next_shard_index(output_dir, stem, "jsonl")
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
    timeout_seconds = int(getattr(args, "timeout_seconds", DEFAULT_TIMEOUT_SECONDS))
    command = [
        nmap_path,
        "--open",
        "-sV",
        "--version-light",
        "--host-timeout",
        f"{timeout_seconds}s",
        "-oX",
        "-",
    ]
    if args.assume_host_up:
        command.append("-Pn")
    if args.ports:
        command.extend(["-p", args.ports])
    elif args.top_ports:
        command.extend(["--top-ports", str(args.top_ports)])
    command.append(target)
    return command


def run_nmap(command: list[str], timeout_seconds: int) -> tuple[str, str, int]:
    if timeout_seconds <= 0:
        raise ValueError("--timeout-seconds must be greater than 0")
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
    targets: Iterable[ServerTarget],
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


def dry_run_host_summary_to_result_row(host_summary: dict[str, Any]) -> dict[str, Any]:
    return {
        "target": host_summary.get("input_target", ""),
        "target_label": host_summary.get("target_label", ""),
        "host": host_summary.get("detected_address", ""),
        "host_status": "dry-run-planned",
        "scan_status": "dry-run-planned",
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
    targets: Iterable[ServerTarget],
    host_summaries: list[dict[str, Any]],
    services: list[dict[str, Any]],
    errors: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    services_by_target: dict[str, list[dict[str, Any]]] = {}
    errors_by_target: dict[str, list[dict[str, Any]]] = {}
    host_summaries_by_target_host: dict[tuple[str, str], dict[str, Any]] = {}
    first_host_summary_by_target: dict[str, dict[str, Any]] = {}

    for service in services:
        services_by_target.setdefault(host_key(service), []).append(service)
    for host in host_summaries:
        key = host_key(host)
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
        target_rows.extend(error_to_result_row(error) for error in errors_by_target.get(key, []))
        if not target_rows:
            host_summary = first_host_summary_by_target.get(key)
            if host_summary and host_summary.get("host_status") == "dry-run-planned":
                target_rows.append(dry_run_host_summary_to_result_row(host_summary))
        rows.extend(target_rows)

    return dedupe_result_rows(rows)


def scan_target_for_output(args: argparse.Namespace, server_target: ServerTarget) -> TargetScanResult:
    target_host_summaries, target_services, target_errors = scan_target_in_worker(
        args,
        server_target,
    )
    target_rows = build_result_rows(
        [server_target],
        target_host_summaries,
        target_services,
        target_errors,
    )
    return TargetScanResult(
        target=server_target,
        host_summaries=target_host_summaries,
        services=target_services,
        errors=target_errors,
        rows=target_rows,
    )


def completed_future_result(
    future: Future[TargetScanResult],
    server_target: ServerTarget,
) -> TargetScanResult:
    try:
        return future.result()
    except Exception as exc:
        errors = worker_error(server_target, f"Per-target worker failed unexpectedly: {exc}")
        rows = build_result_rows([server_target], [], [], errors)
        return TargetScanResult(
            target=server_target,
            host_summaries=[],
            services=[],
            errors=errors,
            rows=rows,
        )


def scan_targets_to_sharded_outputs(
    args: argparse.Namespace,
    targets: Iterable[ServerTarget],
    output_root: Path,
    max_bytes: int,
    write_jsonl: bool,
    on_target_complete: Callable[[ServerTarget], None] | None = None,
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

    target_count = 0
    row_count = 0
    service_count = 0
    error_count = 0
    worker_count = int(getattr(args, "workers", DEFAULT_WORKERS) or DEFAULT_WORKERS)
    if worker_count < 1:
        raise ValueError("--workers must be at least 1")

    target_iter = iter(targets)
    pending: dict[Future[TargetScanResult], tuple[int, ServerTarget]] = {}
    completed_for_checkpoint: dict[int, ServerTarget] = {}
    next_submit_order = 0
    next_checkpoint_order = 0
    completed_count = 0
    targets_exhausted = False
    stop_requested = False

    def submit_next(executor: ThreadPoolExecutor) -> bool:
        nonlocal next_submit_order, target_count, targets_exhausted
        if targets_exhausted:
            return False
        try:
            server_target = next(target_iter)
        except StopIteration:
            targets_exhausted = True
            return False

        order = next_submit_order
        next_submit_order += 1
        target_count += 1
        future = executor.submit(scan_target_for_output, args, server_target)
        pending[future] = (order, server_target)
        return True

    def advance_checkpoint() -> None:
        nonlocal next_checkpoint_order
        if on_target_complete is None:
            return
        while next_checkpoint_order in completed_for_checkpoint:
            target = completed_for_checkpoint.pop(next_checkpoint_order)
            on_target_complete(target)
            next_checkpoint_order += 1

    def write_completed_result(order: int, result: TargetScanResult) -> None:
        nonlocal completed_count, row_count, service_count, error_count, stop_requested
        service_count += len(result.services)
        error_count += len(result.errors)
        row_count += len(result.rows)
        csv_writer.write_rows(result.rows)
        if jsonl_writer is not None:
            jsonl_writer.write_rows(result.rows)

        if getattr(args, "echo_planned_commands", False):
            for host in result.host_summaries:
                command = " ".join(str(part) for part in host.get("nmap_command", []))
                if command:
                    print(f"Planned command: {command}")

        if on_target_complete is not None:
            completed_for_checkpoint[order] = result.target
            advance_checkpoint()
        completed_count += 1

        print(
            f"Completed {completed_count} target(s); "
            f"latest={result.target.target}; open_services={len(result.services)}; rows={len(result.rows)}",
            file=sys.stderr,
            flush=True,
        )

        if result.errors and getattr(args, "stop_on_error", False):
            stop_requested = True

    executor = ThreadPoolExecutor(max_workers=worker_count)
    try:
        while len(pending) < worker_count and submit_next(executor):
            pass

        while pending:
            done, _not_done = wait(pending, return_when=FIRST_COMPLETED)
            for future in done:
                order, server_target = pending.pop(future)
                result = completed_future_result(future, server_target)
                write_completed_result(order, result)

            if stop_requested:
                for future in pending:
                    future.cancel()
                break

            while len(pending) < worker_count and submit_next(executor):
                pass
    finally:
        executor.shutdown(wait=True, cancel_futures=True)

    if target_count == 0:
        raise ValueError("No targets found.")

    return RunbookScanResult(
        host_summaries=[],
        services=[],
        errors=[],
        rows=[],
        csv_shards=csv_writer.finalize(),
        jsonl_shards=jsonl_writer.finalize() if jsonl_writer is not None else [],
        target_count=target_count,
        row_count=row_count,
        service_count=service_count,
        error_count=error_count,
    )


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    try:
        if not args.dry_run and not args.i_own_these_servers:
            raise PermissionError(
                "Refusing to scan without --i-own-these-servers. Only scan systems you own or are authorized to assess."
            )
        if args.timeout_seconds <= 0:
            raise ValueError("--timeout-seconds must be greater than 0")
        if not args.targets.exists():
            raise FileNotFoundError(f"Target file not found: {args.targets}")
        guard_live_target_file(args, args.targets)

        max_bytes = chunk_size_bytes(args.chunk_size_mb)
        output_root = args.output_dir
        first_index = first_target_index(args.targets)
        raw_start_index = first_index
        if args.reset_run_data:
            raw_start_index = first_index
        else:
            raw_start_index = read_run_data_index(args.run_data, args.targets, first_index)
        start_index = fast_forward_generated_ipv4_start_index(args.targets, raw_start_index)
        if args.reset_run_data or start_index != raw_start_index:
            write_run_data_index(
                args.run_data,
                args.targets,
                start_index,
                allow_decrease=args.reset_run_data,
            )

        if args.reset_run_data or raw_start_index <= first_index:
            reset_output_dirs(output_root)
        else:
            output_root.mkdir(parents=True, exist_ok=True)

        args.echo_planned_commands = bool(args.dry_run)
        targets = iter_targets(args.targets, args.max_targets, start_index=start_index)
        result = scan_targets_to_sharded_outputs(
            args,
            targets,
            output_root,
            max_bytes,
            write_jsonl=not args.no_jsonl,
            on_target_complete=lambda target: write_run_data_index(
                args.run_data,
                args.targets,
                (target.source_index or start_index) + 1,
            ),
        )
        csv_shards = result.csv_shards
        jsonl_shards = result.jsonl_shards
        target_count = result.target_count
        row_count = result.row_count
        service_count = result.service_count
        error_count = result.error_count
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(f"Targets processed: {target_count}")
    print(f"Rows written: {row_count}")
    print(f"Open services detected: {service_count}")
    print(f"Errors: {error_count}")
    for shard in csv_shards:
        print(f"CSV shard: {shard['path']} ({shard['bytes']} bytes)")
    for shard in jsonl_shards:
        print(f"JSONL shard: {shard['path']} ({shard['bytes']} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
