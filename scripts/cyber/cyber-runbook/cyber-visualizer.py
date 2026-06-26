#!/usr/bin/env python3
"""
Launch the cybersecurity runbook visualizer with no arguments.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
VISUALIZER_RUNNER = ROOT / "data" / "private" / "cybersecurity" / "visualizer" / "runner.py"

INCLUDED_RUNBOOK_OUTPUT_PATHS = [
    ROOT / "data" / "private" / "cybersecurity" / "group-outputs-main",
    ROOT / "data" / "private" / "cybersecurity" / "runbook-outputs-3-full-20260626",
    ROOT / "data" / "private" / "cybersecurity" / "runbook-outputs-3-20260626",
    ROOT / "data" / "private" / "cybersecurity" / "runbook-outputs-2-20260626",
    ROOT / "data" / "private" / "cybersecurity" / "runbook-outputs",
]


def has_visualizer_data(path: Path) -> bool:
    csv_dir = path / "csv"
    jsonl_dir = path / "jsonl"
    return (
        csv_dir.exists()
        and any(csv_dir.glob("*.csv"))
    ) or (
        jsonl_dir.exists()
        and any(jsonl_dir.glob("*.jsonl"))
    )


def has_pipeline_state(path: Path) -> bool:
    return (path / "state" / "pipeline-state.json").exists()


def choose_output_dir() -> Path:
    for path in INCLUDED_RUNBOOK_OUTPUT_PATHS:
        if has_visualizer_data(path):
            return path
    for path in INCLUDED_RUNBOOK_OUTPUT_PATHS:
        if has_pipeline_state(path):
            return path
    formatted_paths = "\n".join(f"  - {path}" for path in INCLUDED_RUNBOOK_OUTPUT_PATHS)
    raise FileNotFoundError(
        "No included runbook output directory contains csv/*.csv or jsonl/*.jsonl:\n"
        f"{formatted_paths}"
    )


def main() -> int:
    if len(sys.argv) > 1:
        print("This script intentionally runs without arguments.", file=sys.stderr)
        return 2
    if not VISUALIZER_RUNNER.exists():
        print(f"Missing visualizer runner: {VISUALIZER_RUNNER}", file=sys.stderr)
        return 1

    try:
        output_dir = choose_output_dir()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print("Included runbook output paths:", flush=True)
    for path in INCLUDED_RUNBOOK_OUTPUT_PATHS:
        marker = (
            "selected"
            if path == output_dir
            else "active"
            if has_pipeline_state(path)
            else "available"
            if has_visualizer_data(path)
            else "pending"
        )
        print(f"  - {path} [{marker}]", flush=True)
    print("", flush=True)

    command = [
        sys.executable,
        str(VISUALIZER_RUNNER),
        "--output-dir",
        str(output_dir),
    ]
    return subprocess.run(command, cwd=ROOT, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
