#!/usr/bin/env python3
"""
Generate a CSV containing every possible IPv4 address.

Output size: roughly 60–70 GB uncompressed.
Rows: 4,294,967,296 addresses + 1 header row.

Usage:
  python generate_all_ipv4_csv.py ipv4_all.csv

Compressed output:
  python generate_all_ipv4_csv.py ipv4_all.csv.gz
"""

import csv
import gzip
import ipaddress
import sys
from pathlib import Path


TOTAL_IPV4 = 2**32


def open_output(path: Path):
    if path.suffix == ".gz":
        return gzip.open(path, "wt", newline="", encoding="utf-8")
    return open(path, "w", newline="", encoding="utf-8")


def main():
    if len(sys.argv) != 2:
        print("Usage: python generate_all_ipv4_csv.py <output.csv|output.csv.gz>")
        sys.exit(1)

    output_path = Path(sys.argv[1])

    with open_output(output_path) as f:
        writer = csv.writer(f)
        writer.writerow(["ipv4"])

        for i in range(TOTAL_IPV4):
            writer.writerow([str(ipaddress.IPv4Address(i))])

            if i and i % 10_000_000 == 0:
                print(f"Wrote {i:,} addresses...", file=sys.stderr)

    print(f"Done. Wrote {TOTAL_IPV4:,} IPv4 addresses to {output_path}", file=sys.stderr)


if __name__ == "__main__":
    main()