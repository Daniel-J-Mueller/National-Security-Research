#!/usr/bin/env python3
"""
Stream a generated IPv4 CSV and remove the leading 0.0.0.0/8 data rows.

This is a local file-maintenance helper for the generated dry-run CSV. It keeps
the header, verifies that the first data row is 0.0.0.0, skips exactly
16,777,216 data rows, verifies that the next retained row is 1.0.0.0, and then
streams the remainder to a new CSV.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INPUT = ROOT / "data" / "private" / "cybersecurity" / "runbook-input" / "dry-run-input.csv"
ZERO_BLOCK_ROWS = 2**24
FIRST_ZERO_BLOCK_ROW = b"0.0.0.0"
LAST_ZERO_BLOCK_ROW = b"0.255.255.255"
FIRST_RETAINED_ROW = b"1.0.0.0"
COPY_BUFFER_BYTES = 8 * 1024 * 1024


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Remove the leading 0.0.0.0/8 rows from a generated IPv4 CSV by streaming it."
    )
    parser.add_argument(
        "input",
        nargs="?",
        type=Path,
        default=DEFAULT_INPUT,
        help=f"Generated IPv4 CSV to trim. Default: {DEFAULT_INPUT}",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Destination CSV. Defaults to <input-stem>-without-0-block.csv.",
    )
    parser.add_argument(
        "--replace",
        action="store_true",
        help="Replace the input file after writing a same-directory temporary file.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite an existing --output path.",
    )
    return parser


def stripped_line(line: bytes) -> bytes:
    return line.strip().removeprefix(b"\xef\xbb\xbf")


def default_output_path(input_path: Path) -> Path:
    return input_path.with_name(f"{input_path.stem}-without-0-block{input_path.suffix}")


def validate_destination(input_path: Path, output_path: Path, replace: bool, force: bool) -> None:
    if replace:
        if output_path != input_path:
            raise ValueError("--replace cannot be combined with a different --output path")
        return
    if output_path == input_path:
        raise ValueError("Use --replace when the output path is the same as the input path")
    if output_path.exists() and not force:
        raise FileExistsError(f"Output already exists: {output_path}. Use --force to overwrite it.")


def trim_zero_block(input_path: Path, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with input_path.open("rb") as source, output_path.open("wb") as destination:
        header = source.readline()
        if not header:
            raise ValueError(f"{input_path} is empty")

        first_data_row = source.readline()
        if stripped_line(first_data_row) != FIRST_ZERO_BLOCK_ROW:
            raise ValueError(
                f"{input_path} does not start with {FIRST_ZERO_BLOCK_ROW.decode()} after the header; no trim was done."
            )

        last_skipped = first_data_row
        for skipped_count in range(1, ZERO_BLOCK_ROWS):
            last_skipped = source.readline()
            if not last_skipped:
                raise ValueError(f"{input_path} ended before the full 0.0.0.0/8 block was skipped.")
            if skipped_count % 1_000_000 == 0:
                print(f"Skipped {skipped_count:,} rows...", file=sys.stderr, flush=True)

        if stripped_line(last_skipped) != LAST_ZERO_BLOCK_ROW:
            raise ValueError(
                "The skipped block did not end at "
                f"{LAST_ZERO_BLOCK_ROW.decode()}; found {stripped_line(last_skipped).decode(errors='replace')!r}."
            )

        first_retained = source.readline()
        if stripped_line(first_retained) != FIRST_RETAINED_ROW:
            raise ValueError(
                "The first retained row was expected to be "
                f"{FIRST_RETAINED_ROW.decode()}; found {stripped_line(first_retained).decode(errors='replace')!r}."
            )

        destination.write(header)
        destination.write(first_retained)
        shutil.copyfileobj(source, destination, length=COPY_BUFFER_BYTES)


def main() -> int:
    args = build_parser().parse_args()
    input_path = args.input
    if not input_path.exists():
        print(f"ERROR: Input file not found: {input_path}", file=sys.stderr)
        return 1

    output_path = input_path if args.replace else args.output or default_output_path(input_path)
    temp_path = output_path.with_name(f"{output_path.name}.tmp")

    try:
        validate_destination(input_path, output_path, args.replace, args.force)
        if temp_path.exists() and not args.force:
            raise FileExistsError(f"Temporary output already exists: {temp_path}. Use --force to overwrite it.")
        trim_zero_block(input_path, temp_path)
        if args.replace:
            temp_path.replace(input_path)
            print(f"Replaced {input_path} with a copy starting at {FIRST_RETAINED_ROW.decode()}.")
        else:
            temp_path.replace(output_path)
            print(f"Wrote {output_path} starting at {FIRST_RETAINED_ROW.decode()}.")
    except Exception as exc:
        try:
            temp_path.unlink()
        except FileNotFoundError:
            pass
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
