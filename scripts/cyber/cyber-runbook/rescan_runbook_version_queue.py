#!/usr/bin/env python3
"""
Run targeted service-version rescans from the version-rescan queue.

This consumes group-outputs-main/quick-output/version-rescan-queue.csv and writes
normal runbook CSV/JSONL rows under runbook-outputs-version-rescan. It does not
modify existing runbook shards; rerun cyber-organizer.py afterward to include
the refreshed rows in group-outputs-main.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


CYBER_DIR = Path(__file__).resolve().parents[1]
ROOT = Path(__file__).resolve().parents[3]
if str(CYBER_DIR) not in sys.path:
    sys.path.insert(0, str(CYBER_DIR))

import scan_server_ip_list as scan  # noqa: E402


GROUP_OUTPUT_DIR = ROOT / "data" / "private" / "cybersecurity" / "group-outputs-main"
DEFAULT_QUEUE = GROUP_OUTPUT_DIR / "quick-output" / "version-rescan-queue.csv"
DEFAULT_OUTPUT_DIR = ROOT / "data" / "private" / "cybersecurity" / "runbook-outputs-version-rescan"
DEFAULT_MAX_CHUNK_MB = 75


@dataclass(frozen=True)
class QueueEntry:
    index: int
    host: str
    target: str
    target_label: str
    port: str
    protocol: str
    service_name: str = ""
    product: str = ""
    cpe: str = ""


@dataclass
class QueueResult:
    index: int
    rows: list[dict[str, Any]]
    error: str = ""


def utc_timestamp() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def normalize(value: object) -> str:
    return str(value or "").strip()


def chunk_size_bytes(chunk_size_mb: float) -> int:
    if chunk_size_mb <= 0:
        raise ValueError("--chunk-size-mb must be greater than 0")
    return int(chunk_size_mb * 1024 * 1024)


def read_queue(path: Path) -> list[QueueEntry]:
    entries: list[QueueEntry] = []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for index, row in enumerate(reader, start=1):
            host = normalize(row.get("host"))
            port = normalize(row.get("port"))
            protocol = normalize(row.get("protocol")) or "tcp"
            if not host or not port:
                continue
            entries.append(
                QueueEntry(
                    index=index,
                    host=host,
                    target=normalize(row.get("target")) or host,
                    target_label=normalize(row.get("target_label")) or host,
                    port=port,
                    protocol=protocol,
                    service_name=normalize(row.get("service_name")),
                    product=normalize(row.get("product")),
                    cpe=normalize(row.get("cpe")),
                )
            )
    return entries


def state_path(output_dir: Path) -> Path:
    return output_dir / "state" / "version-rescan-state.json"


def load_completed_indices(output_dir: Path) -> set[int]:
    path = state_path(output_dir)
    if not path.exists():
        return set()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    values = payload.get("completed_indices", []) if isinstance(payload, dict) else []
    return {int(value) for value in values if str(value).isdigit()}


def write_state(output_dir: Path, completed_indices: set[int], total_queue_rows: int) -> None:
    path = state_path(output_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "updated_at": utc_timestamp(),
        "total_queue_rows": total_queue_rows,
        "completed_count": len(completed_indices),
        "completed_indices": sorted(completed_indices),
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def select_entries(
    entries: list[QueueEntry],
    completed_indices: set[int],
    start_index: int,
    limit: int,
    only_port: str,
    only_products: set[str],
    skip_products: set[str],
    known_product_only: bool,
    no_resume: bool,
) -> list[QueueEntry]:
    selected: list[QueueEntry] = []
    for entry in entries:
        if entry.index < start_index:
            continue
        if only_port and entry.port != only_port:
            continue
        product = normalize(entry.product).casefold()
        if known_product_only and not product:
            continue
        if only_products and product not in only_products:
            continue
        if skip_products and product in skip_products:
            continue
        if not no_resume and entry.index in completed_indices:
            continue
        selected.append(entry)
        if limit > 0 and len(selected) >= limit:
            break
    return selected


def sample_commands(
    entries: list[QueueEntry],
    nmap_path: str,
    timeout_seconds: int,
    assume_host_up: bool,
    tcp_connect_scan: bool,
) -> list[str]:
    commands: list[str] = []
    for entry in entries:
        args = argparse.Namespace(
            timeout_seconds=timeout_seconds,
            assume_host_up=assume_host_up,
            ports=entry.port,
            top_ports=None,
            version_all=True,
            tcp_connect_scan=tcp_connect_scan,
        )
        commands.append(" ".join(scan.build_nmap_command(nmap_path, entry.host, args)))
    return commands


def scan_entry(
    entry: QueueEntry,
    nmap_path: str,
    timeout_seconds: int,
    assume_host_up: bool,
    tcp_connect_scan: bool,
) -> QueueResult:
    args = argparse.Namespace(
        dry_run=False,
        timeout_seconds=timeout_seconds,
        assume_host_up=assume_host_up,
        ports=entry.port,
        top_ports=None,
        version_all=True,
        tcp_connect_scan=tcp_connect_scan,
    )
    try:
        target = scan.ServerTarget(target=scan.validate_target(entry.host), label=scan.clean_label(entry.target_label))
        host_summaries, services, errors = scan.scan_target(args, target, nmap_path)
        rows = scan.build_result_rows([target], host_summaries, services, errors)
        return QueueResult(index=entry.index, rows=rows)
    except Exception as exc:  # noqa: BLE001 - persisted into normal runbook error rows.
        error_row = scan.error_to_result_row(
            {
                "target": entry.host,
                "target_label": entry.target_label,
                "error": f"Version rescan failed for {entry.host}:{entry.port}/{entry.protocol}: {exc}",
            }
        )
        return QueueResult(index=entry.index, rows=[error_row], error=str(exc))


def write_manifest(
    output_dir: Path,
    queue_path: Path,
    selected_count: int,
    completed_indices: set[int],
    rows_written: int,
    errors: int,
    csv_shards: list[dict[str, Any]],
    jsonl_shards: list[dict[str, Any]],
) -> None:
    path = output_dir / "manifest" / "version-rescan-manifest.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": utc_timestamp(),
        "queue_path": str(queue_path),
        "selected_queue_rows": selected_count,
        "completed_queue_rows": len(completed_indices),
        "rows_written": rows_written,
        "error_rows": errors,
        "csv_shards": csv_shards,
        "jsonl_shards": jsonl_shards,
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run targeted Nmap --version-all rescans from version-rescan-queue.csv.")
    parser.add_argument("--queue", type=Path, default=DEFAULT_QUEUE, help="version-rescan-queue.csv path.")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR, help="Destination runbook output dir.")
    parser.add_argument(
        "--i-own-these-servers",
        action="store_true",
        help="Required before running Nmap. Confirms authorization for every queued host/port.",
    )
    parser.add_argument("--nmap-path", default="nmap", help="Path to nmap executable.")
    parser.add_argument("--timeout-seconds", type=int, default=180, help="Per-entry Nmap timeout.")
    parser.add_argument("--workers", type=int, default=8, help="Concurrent Nmap workers.")
    parser.add_argument("--limit", type=int, default=0, help="Maximum queue rows for this invocation. 0 means all.")
    parser.add_argument("--start-index", type=int, default=1, help="1-based queue row index to start from.")
    parser.add_argument("--only-port", help="Only scan queue rows for this port.")
    parser.add_argument("--only-product", action="append", default=[], help="Only scan this exact product. Repeatable.")
    parser.add_argument("--skip-product", action="append", default=[], help="Skip this exact product. Repeatable.")
    parser.add_argument(
        "--known-product-only",
        action="store_true",
        help="Skip queue rows whose product field is blank.",
    )
    parser.add_argument("--assume-host-up", action="store_true", help="Pass -Pn to Nmap.")
    parser.add_argument(
        "--no-tcp-connect-scan",
        dest="tcp_connect_scan",
        action="store_false",
        default=True,
        help="Disable the default Nmap -sT TCP connect scan mode.",
    )
    parser.add_argument("--no-resume", action="store_true", help="Ignore completed indices in the state file.")
    parser.add_argument("--dry-run", action="store_true", help="Print planned Nmap commands without scanning.")
    parser.add_argument(
        "--chunk-size-mb",
        type=float,
        default=DEFAULT_MAX_CHUNK_MB,
        help="Maximum CSV/JSONL shard size.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.timeout_seconds <= 0:
        print("ERROR: --timeout-seconds must be greater than 0", file=sys.stderr)
        return 2
    if args.workers <= 0:
        print("ERROR: --workers must be greater than 0", file=sys.stderr)
        return 2
    if not args.queue.exists():
        print(f"ERROR: missing queue: {args.queue}", file=sys.stderr)
        return 1
    if not args.dry_run and not args.i_own_these_servers:
        print(
            "ERROR: refusing to scan without --i-own-these-servers. Only scan systems you own or are authorized to assess.",
            file=sys.stderr,
        )
        return 2

    entries = read_queue(args.queue)
    completed_indices = set() if args.no_resume else load_completed_indices(args.output_dir)
    only_products = {normalize(product).casefold() for product in args.only_product if normalize(product)}
    skip_products = {normalize(product).casefold() for product in args.skip_product if normalize(product)}
    selected = select_entries(
        entries,
        completed_indices,
        max(1, args.start_index),
        max(0, args.limit),
        normalize(args.only_port),
        only_products,
        skip_products,
        bool(args.known_product_only),
        args.no_resume,
    )

    if args.dry_run:
        print(f"Queue rows available: {len(entries):,}")
        print(f"Queue rows selected: {len(selected):,}")
        for command in sample_commands(
            selected[:10],
            args.nmap_path,
            args.timeout_seconds,
            args.assume_host_up,
            args.tcp_connect_scan,
        ):
            print(command)
        return 0

    nmap_path = scan.check_nmap(args.nmap_path)
    max_bytes = chunk_size_bytes(args.chunk_size_mb)
    csv_writer = scan.CsvShardWriter(args.output_dir / "csv", "version-rescan-results", max_bytes)
    jsonl_writer = scan.JsonlShardWriter(args.output_dir / "jsonl", "version-rescan-results", max_bytes)

    rows_written = 0
    error_rows = 0
    processed = 0
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {
            pool.submit(
                scan_entry,
                entry,
                nmap_path,
                args.timeout_seconds,
                args.assume_host_up,
                args.tcp_connect_scan,
            ): entry
            for entry in selected
        }
        for future in as_completed(futures):
            entry = futures[future]
            result = future.result()
            csv_writer.write_rows(result.rows)
            jsonl_writer.write_rows(result.rows)
            completed_indices.add(entry.index)
            rows_written += len(result.rows)
            if result.error or any(normalize(row.get("scan_status")) == "error" for row in result.rows):
                error_rows += 1
            processed += 1
            if processed % 100 == 0:
                write_state(args.output_dir, completed_indices, len(entries))
                print(f"[{utc_timestamp()}] processed {processed:,}/{len(selected):,}", flush=True)

    write_state(args.output_dir, completed_indices, len(entries))
    csv_shards = csv_writer.finalize()
    jsonl_shards = jsonl_writer.finalize()
    write_manifest(
        args.output_dir,
        args.queue,
        len(selected),
        completed_indices,
        rows_written,
        error_rows,
        csv_shards,
        jsonl_shards,
    )
    print(f"Scanned queue rows: {processed:,}")
    print(f"Rows written: {rows_written:,}")
    print(f"Error rows: {error_rows:,}")
    print(f"Output: {args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
