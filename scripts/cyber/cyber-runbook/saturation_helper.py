#!/usr/bin/env python3
"""
Run one no-argument version-saturation batch.

This is the fast path for old unversioned rows:
1. run port-specific --version-all rescans from the existing queue,
2. rebuild group-outputs-main,
3. run the local CPE/version enrichment pass,
4. refresh the local visualizer if it is already running.

The helper intentionally accepts no arguments. Rerun it to process the next
resumable batch.
"""

from __future__ import annotations

import json
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
CYBER_RUNBOOK_DIR = Path(__file__).resolve().parent
GROUP_OUTPUT_DIR = ROOT / "data" / "private" / "cybersecurity" / "group-outputs-main"

RESCAN_SCRIPT = CYBER_RUNBOOK_DIR / "rescan_runbook_version_queue.py"
ORGANIZER_SCRIPT = CYBER_RUNBOOK_DIR / "cyber-organizer.py"
ENRICH_SCRIPT = CYBER_RUNBOOK_DIR / "enrich_runbook_cpe_versions.py"

BATCH_LIMIT = 1000
WORKERS = 32
TIMEOUT_SECONDS = 45
VISUALIZER_REFRESH_URLS = (
    "http://127.0.0.1:8766/api/refresh",
    "http://127.0.0.1:8765/api/refresh",
)

LIKELY_VERSIONED_PRODUCTS = (
    "nginx",
    "Apache httpd",
    "Gunicorn",
    "Apache Tomcat",
    "Apache Tomcat/Coyote JSP engine",
    "OpenResty web app server",
    "Microsoft IIS httpd",
    "lighttpd",
    "HAProxy http proxy",
    "Exim smtpd",
    "OpenSSH",
    "Samba smbd",
    "Jetty",
    "Caddy httpd",
)


def utc_timestamp() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def command_text(command: list[str]) -> str:
    return " ".join(str(part) for part in command)


def run_command(name: str, command: list[str]) -> None:
    print(f"[{utc_timestamp()}] {name}: {command_text(command)}", flush=True)
    subprocess.run(command, cwd=ROOT, check=True)


def rescan_command() -> list[str]:
    command = [
        sys.executable,
        str(RESCAN_SCRIPT),
        "--i-own-these-servers",
        "--limit",
        str(BATCH_LIMIT),
        "--workers",
        str(WORKERS),
        "--timeout-seconds",
        str(TIMEOUT_SECONDS),
        "--known-product-only",
    ]
    for product in LIKELY_VERSIONED_PRODUCTS:
        command.extend(["--only-product", product])
    return command


def organizer_command() -> list[str]:
    return [sys.executable, str(ORGANIZER_SCRIPT)]


def enrich_command() -> list[str]:
    return [
        sys.executable,
        str(ENRICH_SCRIPT),
        "--apply",
        "--output-dir",
        str(GROUP_OUTPUT_DIR),
    ]


def refresh_visualizer() -> None:
    for url in VISUALIZER_REFRESH_URLS:
        request = urllib.request.Request(url, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                payload = response.read().decode("utf-8", errors="replace")
        except (OSError, urllib.error.URLError):
            continue
        try:
            ok = bool(json.loads(payload).get("ok"))
        except json.JSONDecodeError:
            ok = False
        if ok:
            print(f"[{utc_timestamp()}] refreshed visualizer: {url}", flush=True)
            return
    print(f"[{utc_timestamp()}] visualizer refresh skipped: no local visualizer responded.", flush=True)


def main() -> int:
    if len(sys.argv) > 1:
        print("saturation_helper intentionally runs without arguments.", file=sys.stderr)
        return 2

    for required in (RESCAN_SCRIPT, ORGANIZER_SCRIPT, ENRICH_SCRIPT):
        if not required.exists():
            print(f"Missing required file: {required}", file=sys.stderr)
            return 1

    try:
        run_command("version saturation rescan", rescan_command())
        run_command("rebuild grouped runbook output", organizer_command())
        run_command("saturate grouped CPE/version data", enrich_command())
        refresh_visualizer()
        print(f"[{utc_timestamp()}] saturation helper complete", flush=True)
        return 0
    except KeyboardInterrupt:
        print("\nInterrupted. Rerun saturation_helper to resume the next batch.", file=sys.stderr)
        return 130
    except subprocess.CalledProcessError as exc:
        print(f"ERROR: {exc.cmd} failed with exit code {exc.returncode}", file=sys.stderr)
        return exc.returncode or 1


if __name__ == "__main__":
    raise SystemExit(main())
