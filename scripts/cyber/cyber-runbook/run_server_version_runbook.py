#!/usr/bin/env python3
"""
Run the owner-authorized server version runbook CSV.

Users fill the ip column. The runner writes sharded CSV and optional sharded
JSONL rows directly under data/private/cybersecurity/runbook-outputs.
"""

from __future__ import annotations

import argparse
import csv
import shutil
import sys
from collections.abc import Iterator
from pathlib import Path


CYBER_DIR = Path(__file__).resolve().parents[1]
ROOT = Path(__file__).resolve().parents[3]
if str(CYBER_DIR) not in sys.path:
    sys.path.insert(0, str(CYBER_DIR))

import scan_server_ip_list as scan  # noqa: E402


WORKFLOW_ID = "owner-authorized-cyber-runbook-server-version-scan"
DEFAULT_RUNBOOK_CSV = ROOT / "data" / "private" / "cybersecurity" / "runbook-input" / "dry-run-input.csv"
DEFAULT_OUTPUT_DIR = ROOT / "data" / "private" / "cybersecurity" / "runbook-outputs"
DEFAULT_RUN_DATA = Path(__file__).with_name("run-data.info")
DEFAULT_MAX_CHUNK_MB = 75
DEFAULT_MAX_TARGETS = scan.DEFAULT_MAX_TARGETS
DEFAULT_TIMEOUT_SECONDS = scan.DEFAULT_TIMEOUT_SECONDS


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Read the cyber runbook IP CSV, scan exact owner-authorized targets with "
            "Nmap service-version detection on open ports, and write CSV/JSONL outputs."
        )
    )
    parser.add_argument(
        "--runbook-csv",
        type=Path,
        default=DEFAULT_RUNBOOK_CSV,
        help="Runbook input CSV with an ip column.",
    )
    parser.add_argument(
        "--i-own-these-servers",
        action="store_true",
        help="Required before running Nmap. Confirms authorization for every listed target.",
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
        help="Directory for private runbook outputs.",
    )
    parser.add_argument(
        "--chunk-size-mb",
        type=float,
        default=DEFAULT_MAX_CHUNK_MB,
        help="Maximum size for each JSONL result shard. Default: %(default)s MB.",
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
        default=scan.DEFAULT_WORKERS,
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
        help="Validate the runbook and write planned target rows without running Nmap.",
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
        help="Small checkpoint file that stores the next CSV row number for resumable streaming.",
    )
    parser.add_argument(
        "--reset-run-data",
        action="store_true",
        help="Ignore and reset the checkpoint so this run starts at the first CSV row.",
    )
    return parser


def iter_runbook_targets(
    path: Path,
    max_targets: int,
    start_index: int = 2,
) -> Iterator[scan.ServerTarget]:
    if not path.exists():
        raise FileNotFoundError(f"Runbook CSV not found: {path}")
    if max_targets < 0:
        raise ValueError("--max-targets must be 0 or greater")

    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        fieldnames = list(reader.fieldnames or [])
        normalized_fieldnames = {field.lower() for field in fieldnames}
        if "ip" not in normalized_fieldnames and "target" not in normalized_fieldnames:
            raise ValueError("Runbook CSV must contain an ip column.")

        target_count = 0
        for line_number, row in enumerate(reader, start=2):
            if line_number < start_index:
                continue
            if max_targets and target_count >= max_targets:
                break
            normalized = {key.lower(): (value or "").strip() for key, value in row.items()}
            target_value = normalized.get("ip") or normalized.get("target") or ""
            if not any(normalized.values()):
                continue
            if not target_value:
                raise ValueError(f"Row {line_number} has data but no ip value.")

            target = scan.validate_target(target_value)
            label = scan.clean_label(normalized.get("target_label") or target)
            target_count += 1
            yield scan.ServerTarget(target=target, label=label, source_index=line_number)

    if target_count == 0:
        raise ValueError(f"No targets found in {path} at or after row {start_index}.")


def reset_output_dirs(output_root: Path) -> None:
    output_root.mkdir(parents=True, exist_ok=True)
    for child_name in ("csv", "jsonl"):
        child = output_root / child_name
        if child.exists():
            shutil.rmtree(child)


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
        if not args.runbook_csv.exists():
            raise FileNotFoundError(f"Runbook CSV not found: {args.runbook_csv}")
        scan.guard_live_target_file(args, args.runbook_csv)

        max_bytes = scan.chunk_size_bytes(args.chunk_size_mb)
        output_root = args.output_dir
        first_index = 2
        raw_start_index = first_index
        if args.reset_run_data:
            raw_start_index = first_index
        else:
            raw_start_index = scan.read_run_data_index(args.run_data, args.runbook_csv, first_index)
        start_index = scan.fast_forward_generated_ipv4_start_index(args.runbook_csv, raw_start_index)
        if args.reset_run_data or start_index != raw_start_index:
            scan.write_run_data_index(
                args.run_data,
                args.runbook_csv,
                start_index,
                allow_decrease=args.reset_run_data,
            )

        if args.reset_run_data or raw_start_index <= first_index:
            reset_output_dirs(output_root)
        else:
            output_root.mkdir(parents=True, exist_ok=True)

        scan_args = argparse.Namespace(
            nmap_path=args.nmap_path,
            dry_run=args.dry_run,
            i_own_these_servers=args.i_own_these_servers,
            assume_host_up=args.assume_host_up,
            ports=args.ports,
            top_ports=args.top_ports,
            timeout_seconds=args.timeout_seconds,
            workers=args.workers,
            stop_on_error=args.stop_on_error,
            echo_planned_commands=args.dry_run,
        )
        targets = iter_runbook_targets(args.runbook_csv, args.max_targets, start_index=start_index)
        result = scan.scan_targets_to_sharded_outputs(
            scan_args,
            targets,
            output_root,
            max_bytes,
            write_jsonl=not args.no_jsonl,
            on_target_complete=lambda target: scan.write_run_data_index(
                args.run_data,
                args.runbook_csv,
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
