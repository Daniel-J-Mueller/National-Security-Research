#!/usr/bin/env python3
"""
Scan one owner-authorized target and emit JSON for the batch runner.

The batch runner starts this script once per target so scan-side process state is
released by process exit before the next target is handled.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

import scan_server_ip_list as scan


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Scan one exact owner-authorized IP or DNS target and emit JSON."
    )
    parser.add_argument("--target", required=True, help="Exact IP or DNS name to scan.")
    parser.add_argument("--target-label", required=True, help="Label to carry into output rows.")
    parser.add_argument(
        "--i-own-these-servers",
        action="store_true",
        help="Required before running Nmap. Confirms authorization for this target.",
    )
    parser.add_argument("--ports", help="Optional Nmap port expression.")
    parser.add_argument("--top-ports", type=int, help="Optional Nmap --top-ports value.")
    parser.add_argument("--assume-host-up", action="store_true", help="Pass -Pn to Nmap.")
    parser.add_argument("--nmap-path", default="nmap", help="Path to nmap executable.")
    parser.add_argument("--timeout-seconds", type=int, default=900, help="Nmap timeout.")
    parser.add_argument("--dry-run", action="store_true", help="Emit the planned scan only.")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    try:
        if not args.dry_run and not args.i_own_these_servers:
            raise PermissionError(
                "Refusing to scan without --i-own-these-servers. Only scan systems you own or are authorized to assess."
            )

        target = scan.validate_target(args.target)
        server_target = scan.ServerTarget(target=target, label=scan.clean_label(args.target_label))
        nmap_path = args.nmap_path if args.dry_run else scan.check_nmap(args.nmap_path)
        host_summaries, services, errors = scan.scan_target(args, server_target, nmap_path)
        payload: dict[str, Any] = {
            "host_summaries": host_summaries,
            "services": services,
            "errors": errors,
        }
        json.dump(payload, sys.stdout)
        sys.stdout.write("\n")
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
