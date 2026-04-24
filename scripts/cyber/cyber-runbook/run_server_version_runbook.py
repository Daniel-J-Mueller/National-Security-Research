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
from pathlib import Path
from typing import Any


CYBER_DIR = Path(__file__).resolve().parents[1]
ROOT = Path(__file__).resolve().parents[3]
if str(CYBER_DIR) not in sys.path:
    sys.path.insert(0, str(CYBER_DIR))

import scan_server_ip_list as scan  # noqa: E402


WORKFLOW_ID = "owner-authorized-cyber-runbook-server-version-scan"
DEFAULT_RUNBOOK_CSV = ROOT / "data" / "private" / "cybersecurity" / "runbook-input" / "dry-run-input.csv"
DEFAULT_OUTPUT_DIR = ROOT / "data" / "private" / "cybersecurity" / "runbook-outputs"
DEFAULT_MAX_CHUNK_MB = 75
DEFAULT_MAX_TARGETS = 2**32


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
        help="Validate the runbook and write planned target rows without running Nmap.",
    )
    parser.add_argument(
        "--no-jsonl",
        action="store_true",
        help="Write only the CSV output and skip JSONL shards.",
    )
    return parser


def read_runbook_targets(path: Path, max_targets: int) -> list[scan.ServerTarget]:
    if not path.exists():
        raise FileNotFoundError(f"Runbook CSV not found: {path}")

    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        fieldnames = list(reader.fieldnames or [])
        normalized_fieldnames = {field.lower() for field in fieldnames}
        if "ip" not in normalized_fieldnames and "target" not in normalized_fieldnames:
            raise ValueError("Runbook CSV must contain an ip column.")

        targets: list[scan.ServerTarget] = []
        seen: set[str] = set()
        for line_number, row in enumerate(reader, start=2):
            normalized = {key.lower(): (value or "").strip() for key, value in row.items()}
            target_value = normalized.get("ip") or normalized.get("target") or ""
            if not any(normalized.values()):
                continue
            if not target_value:
                raise ValueError(f"Row {line_number} has data but no ip value.")

            target = scan.validate_target(target_value)
            key = scan.target_identity(target)
            if key in seen:
                continue
            seen.add(key)
            label = scan.clean_label(normalized.get("target_label") or target)
            targets.append(scan.ServerTarget(target=target, label=label))

    if not targets:
        raise ValueError(f"No targets found in {path}. Fill the ip column for 2-3 rows.")
    if max_targets < 1:
        raise ValueError("--max-targets must be at least 1")
    if len(targets) > max_targets:
        raise ValueError(
            f"Refusing to scan {len(targets)} targets in one run; --max-targets is {max_targets}."
        )
    return targets


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

        targets = read_runbook_targets(args.runbook_csv, args.max_targets)
        max_bytes = scan.chunk_size_bytes(args.chunk_size_mb)
        output_root = args.output_dir
        reset_output_dirs(output_root)

        scan_args = argparse.Namespace(
            nmap_path=args.nmap_path,
            dry_run=args.dry_run,
            i_own_these_servers=args.i_own_these_servers,
            assume_host_up=args.assume_host_up,
            ports=args.ports,
            top_ports=args.top_ports,
            timeout_seconds=args.timeout_seconds,
            stop_on_error=args.stop_on_error,
        )
        result = scan.scan_targets_to_sharded_outputs(
            scan_args,
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
