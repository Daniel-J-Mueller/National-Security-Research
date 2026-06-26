#!/usr/bin/env python3
"""
Run the chunk 3 expanded-IP service/version pipeline.

This reads data/private/cybersecurity/runbook-input/chunk_3.json as the source
of truth, expands each selected range into individual IP targets, writes about
10,000 IPs per batch, scans each batch with the existing owner-authorized
scanner, copies finished result shards into one cumulative output directory,
and runs coordinate accumulation after every batch.

The script is intentionally no-arg and resumable. If interrupted, rerun the
same command and it will continue from the last fully coordinated batch.
"""

from __future__ import annotations

import csv
import ipaddress
import json
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[3]
INPUT_JSON = ROOT / "data" / "private" / "cybersecurity" / "runbook-input" / "chunk_3.json"
OUTPUT_DIR = ROOT / "data" / "private" / "cybersecurity" / "runbook-outputs-3-full-20260626"
WORK_DIR = OUTPUT_DIR / "_work"
STATE_PATH = OUTPUT_DIR / "state" / "pipeline-state.json"
SUMMARY_DIR = OUTPUT_DIR / "logs"

SCAN_SCRIPT = ROOT / "scripts" / "cyber" / "scan_server_ip_list.py"
COORDINATE_SCRIPT = ROOT / "scripts" / "cyber" / "saturate_runbook_coordinates.py"
ORGANIZER_SCRIPT = ROOT / "scripts" / "cyber" / "cyber-runbook" / "cyber-organizer.py"
VISUALIZER_SCRIPT = ROOT / "data" / "private" / "cybersecurity" / "visualizer" / "runner.py"

PIPELINE_KIND = "chunk_3_expanded_ip_targets"
PIPELINE_STATE_VERSION = 3
CHUNK_SIZE = 10_000
EXPECTED_INPUT_TOTAL_ADDRESSES = 1_537_376_256
FIRST_CHUNK3_TARGET_IP = int(ipaddress.IPv4Address("100.0.0.0"))
SCAN_WORKERS = 128
SCAN_TIMEOUT_SECONDS = 120

TARGET_FIELDS = [
    "target",
    "target_label",
    "from_ip",
    "to_ip",
    "total_ips",
    "range_index",
    "offset_in_range",
    "global_target_index",
    "source_file",
]


@dataclass(frozen=True)
class IpRange:
    source_index: int
    start: int
    end: int
    total: int


@dataclass(frozen=True)
class ChunkBuild:
    rows: list[dict[str, str]]
    next_range_index: int
    next_ip: int | None
    processed_target_delta: int
    processed_range_delta: int


def utc_timestamp() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def compact_timestamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def ip_text(value: int) -> str:
    return str(ipaddress.IPv4Address(value))


def parse_count(value: Any, index: int) -> int:
    text = str(value).strip().replace(",", "")
    if not text:
        raise ValueError(f"Range {index} has an empty address count")
    count = int(text)
    if count < 1:
        raise ValueError(f"Range {index} address count must be positive")
    return count


def parse_ipv4(value: Any, index: int, field: str) -> int:
    address = ipaddress.ip_address(str(value).strip())
    if not isinstance(address, ipaddress.IPv4Address):
        raise ValueError(f"Range {index} {field} must be IPv4, got {value!r}")
    return int(address)


def load_ranges(path: Path) -> list[IpRange]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError(f"{path} must be a JSON list of [start, end, count] rows")

    ranges: list[IpRange] = []
    for index, row in enumerate(payload, start=1):
        if not isinstance(row, list) or len(row) != 3:
            raise ValueError(f"Range {index} must be [start_ip, end_ip, count]")
        start = parse_ipv4(row[0], index, "start")
        end = parse_ipv4(row[1], index, "end")
        if end < start:
            raise ValueError(f"Range {index} end IP is before start IP")
        total = parse_count(row[2], index)
        computed = end - start + 1
        if total != computed:
            raise ValueError(f"Range {index} count mismatch: supplied {total}, computed {computed}")
        ranges.append(IpRange(source_index=index, start=start, end=end, total=total))

    total_addresses = sum(item.total for item in ranges)
    if total_addresses != EXPECTED_INPUT_TOTAL_ADDRESSES:
        raise ValueError(
            f"Expected {EXPECTED_INPUT_TOTAL_ADDRESSES} addresses, but {path} contains {total_addresses}"
        )
    return ranges


def select_chunk3_ranges(ranges: list[IpRange]) -> tuple[list[IpRange], list[IpRange]]:
    selected = [item for item in ranges if item.start >= FIRST_CHUNK3_TARGET_IP]
    skipped = [item for item in ranges if item.start < FIRST_CHUNK3_TARGET_IP]
    if not selected:
        raise ValueError("No chunk 3 ranges found at or after 100.0.0.0")
    return selected, skipped


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f"{path.name}.{compact_timestamp()}.tmp")
    temp_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temp_path.replace(path)


def has_final_output_data() -> bool:
    checks = [
        (OUTPUT_DIR / "csv", "*.csv"),
        (OUTPUT_DIR / "jsonl", "*.jsonl"),
        (OUTPUT_DIR / "coords" / "csv", "*.csv"),
    ]
    return any(any(path.glob(pattern)) if path.exists() else False for path, pattern in checks)


def archive_incompatible_state() -> None:
    if has_final_output_data():
        raise ValueError(
            f"{OUTPUT_DIR} contains output from an incompatible older pipeline. "
            "Move it aside before starting the expanded chunk 3 pipeline."
        )

    timestamp = compact_timestamp()
    archive_dir = OUTPUT_DIR / "state" / f"incompatible-{timestamp}"
    archive_dir.mkdir(parents=True, exist_ok=True)
    if STATE_PATH.exists():
        shutil.move(str(STATE_PATH), str(archive_dir / STATE_PATH.name))
    if WORK_DIR.exists():
        shutil.move(str(WORK_DIR), str(OUTPUT_DIR / f"_work-incompatible-{timestamp}"))


def new_state(selected_ranges: list[IpRange], skipped_ranges: list[IpRange]) -> dict[str, Any]:
    selected_addresses = sum(item.total for item in selected_ranges)
    skipped_addresses = sum(item.total for item in skipped_ranges)
    return {
        "version": PIPELINE_STATE_VERSION,
        "pipeline_kind": PIPELINE_KIND,
        "input_json": str(INPUT_JSON),
        "output_dir": str(OUTPUT_DIR),
        "chunk_size": CHUNK_SIZE,
        "first_target_ip": ip_text(FIRST_CHUNK3_TARGET_IP),
        "input_total_ranges": len(selected_ranges) + len(skipped_ranges),
        "input_total_addresses": EXPECTED_INPUT_TOTAL_ADDRESSES,
        "selected_ranges": len(selected_ranges),
        "selected_addresses": selected_addresses,
        "selected_targets": selected_addresses,
        "skipped_redundant_ranges": len(skipped_ranges),
        "skipped_redundant_addresses": skipped_addresses,
        "phase": "scan",
        "next_range_index": 0,
        "next_ip": ip_text(selected_ranges[0].start),
        "processed_ranges": 0,
        "processed_addresses": 0,
        "processed_targets": 0,
        "chunks_completed": 0,
        "created_at": utc_timestamp(),
        "updated_at": utc_timestamp(),
    }


def load_state(selected_ranges: list[IpRange], skipped_ranges: list[IpRange]) -> dict[str, Any]:
    if STATE_PATH.exists():
        state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        if not isinstance(state, dict):
            raise ValueError(f"Invalid pipeline state: {STATE_PATH}")
        if state.get("version") != PIPELINE_STATE_VERSION or state.get("pipeline_kind") != PIPELINE_KIND:
            archive_incompatible_state()
            return new_state(selected_ranges, skipped_ranges)
        if state.get("chunk_size") != CHUNK_SIZE:
            raise ValueError(f"State chunk_size mismatch in {STATE_PATH}")
        if state.get("selected_targets") != sum(item.total for item in selected_ranges):
            raise ValueError(f"State selected_targets mismatch in {STATE_PATH}")
        return state

    if has_final_output_data():
        raise ValueError(
            f"{OUTPUT_DIR} already contains output but no compatible state file. "
            "Move it aside before starting a fresh expanded full pipeline run."
        )
    return new_state(selected_ranges, skipped_ranges)


def save_state(state: dict[str, Any]) -> None:
    state["updated_at"] = utc_timestamp()
    atomic_write_json(STATE_PATH, state)


def count_completed_ranges(ranges: list[IpRange], next_range_index: int, next_ip: int | None) -> int:
    if next_ip is None:
        return len(ranges)
    if next_range_index >= len(ranges):
        return len(ranges)
    current = ranges[next_range_index]
    return next_range_index if next_ip <= current.end else next_range_index + 1


def build_chunk(
    ranges: list[IpRange],
    range_index: int,
    next_ip: int,
    processed_targets: int,
) -> ChunkBuild:
    rows: list[dict[str, str]] = []
    current_range_index = range_index
    current_ip = next_ip
    starting_completed_ranges = count_completed_ranges(ranges, range_index, next_ip)

    while current_range_index < len(ranges) and len(rows) < CHUNK_SIZE:
        current_range = ranges[current_range_index]
        if current_ip < current_range.start:
            current_ip = current_range.start
        if current_ip > current_range.end:
            current_range_index += 1
            if current_range_index < len(ranges):
                current_ip = ranges[current_range_index].start
            continue

        take = min(CHUNK_SIZE - len(rows), current_range.end - current_ip + 1)
        for offset in range(take):
            address_int = current_ip + offset
            address = ip_text(address_int)
            global_target_index = processed_targets + len(rows) + 1
            rows.append(
                {
                    "target": address,
                    "target_label": f"chunk-3-expanded-{global_target_index:012d}-{address}",
                    "from_ip": ip_text(current_range.start),
                    "to_ip": ip_text(current_range.end),
                    "total_ips": str(current_range.total),
                    "range_index": str(current_range.source_index),
                    "offset_in_range": str(address_int - current_range.start),
                    "global_target_index": str(global_target_index),
                    "source_file": str(INPUT_JSON),
                }
            )

        current_ip += take
        if current_ip > current_range.end:
            current_range_index += 1
            if current_range_index < len(ranges):
                current_ip = ranges[current_range_index].start

    if not rows:
        return ChunkBuild(
            rows=[],
            next_range_index=current_range_index,
            next_ip=None,
            processed_target_delta=0,
            processed_range_delta=0,
        )

    next_ip_value: int | None = None if current_range_index >= len(ranges) else current_ip
    ending_completed_ranges = count_completed_ranges(ranges, current_range_index, next_ip_value)
    return ChunkBuild(
        rows=rows,
        next_range_index=current_range_index,
        next_ip=next_ip_value,
        processed_target_delta=len(rows),
        processed_range_delta=max(0, ending_completed_ranges - starting_completed_ranges),
    )


def write_target_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=TARGET_FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def run_command(name: str, command: list[str], stderr_log: Path) -> str:
    stderr_log.parent.mkdir(parents=True, exist_ok=True)
    print(f"[{utc_timestamp()}] {name}: {' '.join(command)}", flush=True)
    with stderr_log.open("w", encoding="utf-8", errors="replace") as stderr_handle:
        completed = subprocess.run(
            command,
            check=False,
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=stderr_handle,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    stdout = completed.stdout.strip()
    if stdout:
        print(stdout, flush=True)
    if completed.returncode != 0:
        raise RuntimeError(f"{name} failed with exit code {completed.returncode}; stderr: {stderr_log}")
    return stdout


def scanner_command(target_csv: Path, stage_output: Path, run_data_path: Path) -> list[str]:
    return [
        sys.executable,
        str(SCAN_SCRIPT),
        "--targets",
        str(target_csv),
        "--output-dir",
        str(stage_output),
        "--run-data",
        str(run_data_path),
        "--reset-run-data",
        "--i-own-these-servers",
        "--workers",
        str(SCAN_WORKERS),
        "--timeout-seconds",
        str(SCAN_TIMEOUT_SECONDS),
    ]


def coordinate_command(stage_output: Path) -> list[str]:
    coords_csv = OUTPUT_DIR / "coords" / "csv" / "ip-coordinate-lookups.csv"
    coords_jsonl = OUTPUT_DIR / "coords" / "jsonl" / "ip-coordinate-lookups.jsonl"
    return [
        sys.executable,
        str(COORDINATE_SCRIPT),
        "--output-dir",
        str(stage_output),
        "--cache-path",
        str(OUTPUT_DIR / "coords" / "cache"),
        "--report-path",
        str(coords_csv),
        "--coords-csv-path",
        str(coords_csv),
        "--coords-jsonl-path",
        str(coords_jsonl),
        "--skip-ping",
        "--reconcile-coordinate-store",
    ]


def organizer_command() -> list[str]:
    return [
        sys.executable,
        str(ORGANIZER_SCRIPT),
    ]


def copy_stage_shards(stage_output: Path, chunk_number: int) -> dict[str, int]:
    copied = {"csv": 0, "jsonl": 0}
    for kind, suffix in (("csv", ".csv"), ("jsonl", ".jsonl")):
        destination_dir = OUTPUT_DIR / kind
        destination_dir.mkdir(parents=True, exist_ok=True)
        for source in sorted((stage_output / kind).glob(f"*{suffix}")):
            shard_id = source.stem.rsplit("-", 1)[-1]
            destination = destination_dir / f"runbook-results-{chunk_number:06d}-{shard_id}{suffix}"
            if destination.exists():
                destination.unlink()
            shutil.copy2(source, destination)
            copied[kind] += 1
    return copied


def write_chunk_summary(chunk_number: int, summary: dict[str, Any]) -> None:
    SUMMARY_DIR.mkdir(parents=True, exist_ok=True)
    atomic_write_json(SUMMARY_DIR / f"chunk-{chunk_number:06d}.json", summary)


def chunk_work_paths(chunk_number: int) -> dict[str, Path]:
    chunk_dir = WORK_DIR / f"chunk-{chunk_number:06d}"
    return {
        "chunk_dir": chunk_dir,
        "target_csv": chunk_dir / "targets.csv",
        "stage_output": chunk_dir / "stage-output",
        "run_data": chunk_dir / "run-data.info",
        "scan_stderr": chunk_dir / "scan-stderr.log",
        "coordinate_stderr": chunk_dir / "coordinate-stderr.log",
    }


def remove_stale_work_dir(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)


def coordinate_current_chunk(state: dict[str, Any]) -> dict[str, Any]:
    current = state.get("current_chunk")
    if not isinstance(current, dict):
        raise ValueError("State phase is coordinate but current_chunk is missing")

    chunk_number = int(current["chunk_number"])
    paths = chunk_work_paths(chunk_number)
    stage_output = Path(current.get("stage_output_dir") or paths["stage_output"])
    run_command(
        f"chunk {chunk_number} coordinates",
        coordinate_command(stage_output),
        paths["coordinate_stderr"],
    )

    summary = dict(current.get("summary") or {})
    summary["coordinate_completed_at"] = utc_timestamp()
    write_chunk_summary(chunk_number, summary)

    processed_targets = int(current["next_processed_targets"])
    processed_ranges = int(current["next_processed_ranges"])
    state.update(
        {
            "phase": "scan",
            "next_range_index": int(current["next_range_index"]),
            "next_ip": current.get("next_ip"),
            "processed_ranges": processed_ranges,
            "processed_targets": processed_targets,
            "processed_addresses": processed_targets,
            "chunks_completed": chunk_number,
            "last_completed_chunk": chunk_number,
            "current_chunk": None,
        }
    )
    save_state(state)
    remove_stale_work_dir(paths["chunk_dir"])
    run_command(
        f"chunk {chunk_number} organizer",
        organizer_command(),
        SUMMARY_DIR / f"chunk-{chunk_number:06d}-organizer-stderr.log",
    )
    print(
        f"[{utc_timestamp()}] chunk {chunk_number} complete; "
        f"expanded_targets={processed_targets}/{state['selected_targets']}",
        flush=True,
    )
    return state


def scan_next_chunk(state: dict[str, Any], ranges: list[IpRange]) -> dict[str, Any]:
    processed_targets = int(state["processed_targets"])
    if processed_targets >= int(state["selected_targets"]):
        state["phase"] = "complete"
        save_state(state)
        return state

    next_ip_text = state.get("next_ip")
    if not next_ip_text:
        state["phase"] = "complete"
        save_state(state)
        return state

    chunk_number = int(state["chunks_completed"]) + 1
    paths = chunk_work_paths(chunk_number)
    remove_stale_work_dir(paths["chunk_dir"])

    chunk = build_chunk(
        ranges,
        int(state["next_range_index"]),
        int(ipaddress.IPv4Address(str(next_ip_text))),
        processed_targets,
    )
    if not chunk.rows:
        state["phase"] = "complete"
        save_state(state)
        return state

    write_target_csv(paths["target_csv"], chunk.rows)
    first_ip = chunk.rows[0]["target"]
    last_ip = chunk.rows[-1]["target"]
    next_processed_targets = processed_targets + chunk.processed_target_delta
    next_processed_ranges = int(state["processed_ranges"]) + chunk.processed_range_delta
    print(
        f"[{utc_timestamp()}] chunk {chunk_number}: scanning {len(chunk.rows)} expanded IP targets "
        f"({first_ip} - {last_ip})",
        flush=True,
    )

    scan_stdout = run_command(
        f"chunk {chunk_number} scan",
        scanner_command(paths["target_csv"], paths["stage_output"], paths["run_data"]),
        paths["scan_stderr"],
    )
    copied = copy_stage_shards(paths["stage_output"], chunk_number)

    current_chunk = {
        "chunk_number": chunk_number,
        "target_count": len(chunk.rows),
        "first_ip": first_ip,
        "last_ip": last_ip,
        "stage_output_dir": str(paths["stage_output"]),
        "next_range_index": chunk.next_range_index,
        "next_ip": ip_text(chunk.next_ip) if chunk.next_ip is not None else None,
        "next_processed_targets": next_processed_targets,
        "next_processed_ranges": next_processed_ranges,
        "summary": {
            "chunk_number": chunk_number,
            "target_count": len(chunk.rows),
            "first_ip": first_ip,
            "last_ip": last_ip,
            "scan_completed_at": utc_timestamp(),
            "copied_csv_shards": copied["csv"],
            "copied_jsonl_shards": copied["jsonl"],
            "scan_stdout": scan_stdout,
        },
    }
    state.update({"phase": "coordinate", "current_chunk": current_chunk})
    save_state(state)
    return coordinate_current_chunk(state)


def print_completion() -> None:
    print(f"[{utc_timestamp()}] expanded chunk 3 pipeline complete", flush=True)
    print(
        "Visualizer command:\n"
        f"{sys.executable} {VISUALIZER_SCRIPT} --output-dir {OUTPUT_DIR}",
        flush=True,
    )


def main() -> int:
    if len(sys.argv) > 1:
        print("This script intentionally runs without arguments.", file=sys.stderr)
        return 2

    for required in (INPUT_JSON, SCAN_SCRIPT, COORDINATE_SCRIPT, ORGANIZER_SCRIPT):
        if not required.exists():
            print(f"Missing required file: {required}", file=sys.stderr)
            return 1

    try:
        ranges = load_ranges(INPUT_JSON)
        selected_ranges, skipped_ranges = select_chunk3_ranges(ranges)
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        state = load_state(selected_ranges, skipped_ranges)
        save_state(state)

        if state["skipped_redundant_ranges"]:
            print(
                f"[{utc_timestamp()}] skipping {state['skipped_redundant_ranges']} redundant "
                f"pre-100.0.0.0 ranges covering {state['skipped_redundant_addresses']} addresses",
                flush=True,
            )

        while state.get("phase") != "complete":
            if state.get("phase") == "coordinate":
                state = coordinate_current_chunk(state)
            elif state.get("phase") == "scan":
                state = scan_next_chunk(state, selected_ranges)
            else:
                raise ValueError(f"Unknown pipeline phase: {state.get('phase')!r}")

        print_completion()
        return 0
    except KeyboardInterrupt:
        print("\nInterrupted. Rerun this script to resume.", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        print(f"State file: {STATE_PATH}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
