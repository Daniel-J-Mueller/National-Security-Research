#!/usr/bin/env python3
"""
Generate a dry-run input CSV containing every possible IPv4 address.

By default, this script writes to:
  data/private/cybersecurity/runbook-input/dry-run-input.csv

Output size: roughly 60-70 GB uncompressed.
Rows: 4,294,967,296 addresses + 1 header row.
The runbook input header is preserved, with generated IPv4 addresses written to
the ip column.

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
ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_PATH = (
    ROOT
    / "data"
    / "private"
    / "cybersecurity"
    / "runbook-input"
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
]


def open_output(path: Path):
    if path.suffix == ".gz":
        return gzip.open(path, "wt", newline="", encoding="utf-8")
    return open(path, "w", newline="", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    output_path = args.output
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open_output(output_path) as handle:
        writer = csv.DictWriter(handle, fieldnames=RUNBOOK_FIELDS)
        writer.writeheader()

        for i in range(TOTAL_IPV4):
            writer.writerow({"ip": str(ipaddress.IPv4Address(i))})

            if i and i % 10_000_000 == 0:
                print(f"Wrote {i:,} addresses...", file=sys.stderr)

    print(f"Done. Wrote {TOTAL_IPV4:,} IPv4 addresses to {output_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
