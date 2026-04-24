#!/usr/bin/env python3
"""
Generate a dry-run input CSV containing every possible IPv4 address.

By default, this script writes to:
  F:/Advancements/National-Security-Research/data/private/cybersecurity/runbook-outputs/_tmp-validation/dry-run-input.csv

Output size: roughly 60–70 GB uncompressed.
Rows: 4,294,967,296 addresses + 1 header row.
The runbook header is preserved, with generated IPv4 addresses written to the
ip column and the remaining columns left blank.

Usage:
  python IPv4_generator.py
  python IPv4_generator.py ipv4_all.csv

Compressed output:
  python IPv4_generator.py ipv4_all.csv.gz
"""

import argparse
import csv
import gzip
import ipaddress
from pathlib import Path
import sys

TOTAL_IPV4 = 2**32
WORKSPACE_ROOT = Path(r"F:\Advancements")
DEFAULT_OUTPUT_PATH = (
    WORKSPACE_ROOT
    / "National-Security-Research"
    / "data"
    / "private"
    / "cybersecurity"
    / "runbook-outputs"
    / "_tmp-validation"
    / "dry-run-input.csv"
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Generate a dry-run input CSV containing every possible IPv4 address."
        )
    )
    parser.add_argument(
        "output",
        nargs="?",
        type=Path,
        default=DEFAULT_OUTPUT_PATH,
        help=(
            "Output CSV path. Defaults to "
            f"{DEFAULT_OUTPUT_PATH}. Use a .gz suffix for gzip output."
        ),
    )
    return parser


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


def open_output(path: Path):
    if path.suffix == ".gz":
        return gzip.open(path, "wt", newline="", encoding="utf-8")
    return open(path, "w", newline="", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    output_path = args.output
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open_output(output_path) as f:
        writer = csv.DictWriter(f, fieldnames=RUNBOOK_FIELDS)
        writer.writeheader()

        for i in range(TOTAL_IPV4):
            writer.writerow({"ip": str(ipaddress.IPv4Address(i))})

            if i and i % 10_000_000 == 0:
                print(f"Wrote {i:,} addresses...", file=sys.stderr)

    print(f"Done. Wrote {TOTAL_IPV4:,} IPv4 addresses to {output_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
