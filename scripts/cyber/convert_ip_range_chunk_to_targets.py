#!/usr/bin/env python3
"""
Convert a JSON chunk of IPv4 ranges into scan target CSV rows.

Each input row must be a three-item list:
    [range_start_ip, range_end_ip, address_count]

The service-version scanner only accepts exact IPs/hostnames, so this converter
writes one target per range using the range start IP, preserving the source
range metadata in extra CSV columns.
"""

from __future__ import annotations

import argparse
import csv
import ipaddress
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INPUT = ROOT / "data" / "private" / "cybersecurity" / "runbook-input" / "chunk_3.json"
DEFAULT_OUTPUT = (
    ROOT
    / "data"
    / "private"
    / "cybersecurity"
    / "runbook-input"
    / "chunk_3-range-start-targets-20260626.csv"
)

FIELDNAMES = [
    "target",
    "target_label",
    "from_ip",
    "to_ip",
    "total_ips",
    "range_index",
    "source_file",
]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Convert JSON IPv4 ranges into range-start scan target CSV rows."
    )
    parser.add_argument("--input-json", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output-csv", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--label-prefix",
        default="chunk-3-range",
        help="Prefix for generated target_label values. Default: %(default)s.",
    )
    parser.add_argument(
        "--allow-count-mismatch",
        action="store_true",
        help="Write rows even if the supplied count does not match start/end.",
    )
    return parser


def parse_count(value: Any, index: int) -> int:
    text = str(value).strip().replace(",", "")
    if not text:
        raise ValueError(f"Range {index} has an empty address count")
    try:
        count = int(text)
    except ValueError as exc:
        raise ValueError(f"Range {index} has invalid address count {value!r}") from exc
    if count < 1:
        raise ValueError(f"Range {index} address count must be positive")
    return count


def parse_ip(value: Any, index: int, field: str) -> ipaddress.IPv4Address:
    try:
        address = ipaddress.ip_address(str(value).strip())
    except ValueError as exc:
        raise ValueError(f"Range {index} has invalid {field} IP {value!r}") from exc
    if not isinstance(address, ipaddress.IPv4Address):
        raise ValueError(f"Range {index} {field} must be IPv4, got {value!r}")
    return address


def load_ranges(path: Path) -> list[Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("Input JSON must be a list of [start, end, count] rows")
    return payload


def convert_ranges(args: argparse.Namespace) -> tuple[int, int]:
    rows = load_ranges(args.input_json)
    args.output_csv.parent.mkdir(parents=True, exist_ok=True)

    accumulated_addresses = 0
    with args.output_csv.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDNAMES, lineterminator="\n")
        writer.writeheader()

        for index, row in enumerate(rows, start=1):
            if not isinstance(row, list) or len(row) != 3:
                raise ValueError(f"Range {index} must be [start_ip, end_ip, count]")
            start_ip = parse_ip(row[0], index, "start")
            end_ip = parse_ip(row[1], index, "end")
            if int(end_ip) < int(start_ip):
                raise ValueError(f"Range {index} end IP is before start IP")

            supplied_count = parse_count(row[2], index)
            computed_count = int(end_ip) - int(start_ip) + 1
            if supplied_count != computed_count and not args.allow_count_mismatch:
                raise ValueError(
                    f"Range {index} count mismatch: supplied {supplied_count}, "
                    f"computed {computed_count}"
                )

            accumulated_addresses += supplied_count
            writer.writerow(
                {
                    "target": str(start_ip),
                    "target_label": (
                        f"{args.label_prefix}-{index:05d}-{start_ip}-{end_ip}"
                    ),
                    "from_ip": str(start_ip),
                    "to_ip": str(end_ip),
                    "total_ips": str(supplied_count),
                    "range_index": str(index),
                    "source_file": str(args.input_json),
                }
            )

    return len(rows), accumulated_addresses


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        range_count, accumulated_addresses = convert_ranges(args)
    except Exception as exc:
        print(f"ERROR: {exc}")
        return 1

    print(f"Ranges read: {range_count}")
    print(f"Targets written: {range_count}")
    print(f"Accumulated addresses: {accumulated_addresses}")
    print(f"CSV target file: {args.output_csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
