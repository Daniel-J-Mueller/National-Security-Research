#!/usr/bin/env python3
"""
Run an Nmap service-version scan and categorize results.

Raw scan artifacts are written under data/private by default.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RULES = ROOT / "config" / "cybersecurity" / "vx-version-categories.json"
DEFAULT_OUTPUT_DIR = ROOT / "data" / "private" / "cybersecurity" / "scans"

ADMIN_AND_INFRA_PORTS = {22, 23, 3389, 5900, 5901, 5985, 5986}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Scan a server you own with Nmap -sV and sort detected service "
            "versions into defensive VX-style lifecycle categories."
        )
    )
    parser.add_argument(
        "--target",
        help="IP address or DNS name of a server you own or are authorized to scan.",
    )
    parser.add_argument(
        "--i-own-this-server",
        action="store_true",
        help="Required when running Nmap. Confirms authorization to scan the target.",
    )
    parser.add_argument(
        "--from-nmap-xml",
        type=Path,
        help="Parse an existing Nmap XML file instead of running a new scan.",
    )
    parser.add_argument(
        "--target-label",
        help="Safe local label for output folders. Defaults to the target or XML filename.",
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
        help="Pass -Pn to Nmap when ICMP probes are blocked for your server.",
    )
    parser.add_argument(
        "--nmap-path",
        default="nmap",
        help="Path to nmap executable. Default: %(default)s",
    )
    parser.add_argument(
        "--rules",
        type=Path,
        default=DEFAULT_RULES,
        help="Category taxonomy and optional version baseline rules.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Directory for private scan outputs.",
    )
    parser.add_argument(
        "--no-save-raw-xml",
        action="store_true",
        help="Do not write the raw Nmap XML alongside parsed results.",
    )
    return parser


def clean_label(value: str) -> str:
    label = re.sub(r"[^A-Za-z0-9_.-]+", "_", value.strip())
    return label.strip("._") or "server"


def utc_timestamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def load_rules(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        rules = json.load(handle)
    category_map = {item["id"]: item for item in rules.get("categories", [])}
    if not category_map:
        raise ValueError(f"No categories found in {path}")
    rules["_category_map"] = category_map
    return rules


def check_nmap(path: str) -> str:
    resolved = shutil.which(path)
    if resolved:
        return resolved
    candidate = Path(path)
    if candidate.exists():
        return str(candidate)
    raise FileNotFoundError(
        "Nmap was not found. Install Nmap or pass --nmap-path with the executable path."
    )


def run_nmap(args: argparse.Namespace) -> tuple[str, list[str], str]:
    if not args.target:
        raise ValueError("--target is required unless --from-nmap-xml is used")
    if not args.i_own_this_server:
        raise PermissionError(
            "Refusing to scan without --i-own-this-server. Only scan systems you own or are authorized to assess."
        )
    nmap_path = check_nmap(args.nmap_path)
    command = [nmap_path, "-sV", "--version-light", "-oX", "-"]
    if args.assume_host_up:
        command.append("-Pn")
    if args.ports:
        command.extend(["-p", args.ports])
    elif args.top_ports:
        command.extend(["--top-ports", str(args.top_ports)])
    command.append(args.target)

    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        timeout=900,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"Nmap exited with {completed.returncode}.\nSTDERR:\n{completed.stderr.strip()}"
        )
    return completed.stdout, command, completed.stderr


def version_parts(value: str) -> tuple[int, ...]:
    return tuple(int(part) for part in re.findall(r"\d+", value or ""))


def compare_versions(left: str, right: str) -> int | None:
    left_parts = version_parts(left)
    right_parts = version_parts(right)
    if not left_parts or not right_parts:
        return None
    max_len = max(len(left_parts), len(right_parts))
    padded_left = left_parts + (0,) * (max_len - len(left_parts))
    padded_right = right_parts + (0,) * (max_len - len(right_parts))
    if padded_left < padded_right:
        return -1
    if padded_left > padded_right:
        return 1
    return 0


def regex_matches(pattern: str | None, value: str) -> bool:
    if not pattern:
        return True
    return re.search(pattern, value or "", re.IGNORECASE) is not None


def detect_flags(service_name: str, port: int, rules: dict[str, Any]) -> list[dict[str, str]]:
    detected: list[dict[str, str]] = []
    service_lower = service_name.lower()
    for flag in rules.get("service_flags", []):
        names = {name.lower() for name in flag.get("service_names", [])}
        if service_lower in names:
            detected.append(
                {
                    "id": flag["id"],
                    "label": flag.get("label", flag["id"]),
                    "recommended_action": flag.get("recommended_action", ""),
                }
            )
    if port in ADMIN_AND_INFRA_PORTS and not any(
        item["id"] == "remote_admin_service" for item in detected
    ):
        detected.append(
            {
                "id": "remote_admin_port",
                "label": "Remote administration or infrastructure port",
                "recommended_action": "Confirm exposure is intentional, restricted, monitored, and authenticated.",
            }
        )
    return detected


def categorize_service(service: dict[str, Any], rules: dict[str, Any]) -> tuple[str, str, str]:
    category_map = rules["_category_map"]
    service_name = service.get("service_name") or ""
    product = service.get("product") or ""
    version = service.get("version") or ""

    if not product and not version:
        category_id = "vx-unknown-fingerprint"
        category = category_map[category_id]
        return category_id, category["label"], "No usable product/version fingerprint was detected."

    for rule in rules.get("version_rules", []):
        if not rule.get("enabled"):
            continue
        if not regex_matches(rule.get("service_name_regex"), service_name):
            continue
        if not regex_matches(rule.get("product_regex"), product):
            continue

        eol_below = rule.get("eol_below_version")
        if eol_below:
            comparison = compare_versions(version, eol_below)
            if comparison is not None and comparison < 0:
                category_id = "vx-eol-or-legacy"
                category = category_map[category_id]
                return (
                    category_id,
                    category["label"],
                    f"Matched rule {rule['id']}; version {version} is below legacy threshold {eol_below}.",
                )

        minimum = rule.get("minimum_supported_version")
        if minimum:
            comparison = compare_versions(version, minimum)
            if comparison is not None and comparison < 0:
                category_id = "vx-baseline-behind"
                category = category_map[category_id]
                return (
                    category_id,
                    category["label"],
                    f"Matched rule {rule['id']}; version {version} is below baseline {minimum}.",
                )
            if comparison is not None and comparison >= 0:
                category_id = "vx-baseline-accepted"
                category = category_map[category_id]
                return (
                    category_id,
                    category["label"],
                    f"Matched rule {rule['id']}; version {version} meets baseline {minimum}.",
                )

    category_id = rules.get("default_category", "vx-review-versioned")
    category = category_map[category_id]
    return (
        category_id,
        category["label"],
        "Version was detected, but no enabled lifecycle baseline rule matched it.",
    )


def parse_nmap_xml(xml_text: str, rules: dict[str, Any]) -> list[dict[str, Any]]:
    root = ET.fromstring(xml_text)
    services: list[dict[str, Any]] = []
    for host in root.findall("host"):
        address_node = host.find("address")
        host_address = address_node.get("addr") if address_node is not None else ""
        ports_node = host.find("ports")
        if ports_node is None:
            continue
        for port_node in ports_node.findall("port"):
            state_node = port_node.find("state")
            if state_node is None or state_node.get("state") != "open":
                continue
            service_node = port_node.find("service")
            port = int(port_node.get("portid", "0"))
            service_name = service_node.get("name", "") if service_node is not None else ""
            product = service_node.get("product", "") if service_node is not None else ""
            version = service_node.get("version", "") if service_node is not None else ""
            extrainfo = service_node.get("extrainfo", "") if service_node is not None else ""
            cpes = [
                cpe.text.strip()
                for cpe in (service_node.findall("cpe") if service_node is not None else [])
                if cpe.text and cpe.text.strip()
            ]
            record: dict[str, Any] = {
                "host": host_address,
                "port": port,
                "protocol": port_node.get("protocol", ""),
                "service_name": service_name,
                "product": product,
                "version": version,
                "extrainfo": extrainfo,
                "cpe": cpes,
            }
            category_id, category_label, rationale = categorize_service(record, rules)
            record["vx_category"] = category_id
            record["vx_category_label"] = category_label
            record["category_rationale"] = rationale
            record["flags"] = detect_flags(service_name, port, rules)
            services.append(record)
    category_map = rules["_category_map"]
    return sorted(
        services,
        key=lambda item: (
            category_map.get(item["vx_category"], {}).get("sort_order", 999),
            item["port"],
        ),
    )


def write_outputs(
    output_root: Path,
    target_label: str,
    timestamp: str,
    report: dict[str, Any],
    xml_text: str,
    save_raw_xml: bool,
) -> tuple[Path, Path, Path | None]:
    scan_dir = output_root / target_label / timestamp
    scan_dir.mkdir(parents=True, exist_ok=True)

    json_path = scan_dir / "service-version-categories.json"
    csv_path = scan_dir / "service-version-categories.csv"
    xml_path = scan_dir / "nmap-service-scan.xml" if save_raw_xml else None

    with json_path.open("w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2)
        handle.write("\n")

    rows = report["services"]
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        fieldnames = [
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
        ]
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            csv_row = dict(row)
            csv_row["cpe"] = "; ".join(row.get("cpe", []))
            csv_row["flags"] = "; ".join(flag["id"] for flag in row.get("flags", []))
            writer.writerow({key: csv_row.get(key, "") for key in fieldnames})

    if xml_path is not None:
        xml_path.write_text(xml_text, encoding="utf-8")
    return json_path, csv_path, xml_path


def build_report(
    args: argparse.Namespace,
    rules: dict[str, Any],
    services: list[dict[str, Any]],
    command: list[str] | None,
    nmap_stderr: str,
) -> dict[str, Any]:
    categories = Counter(service["vx_category"] for service in services)
    flags = Counter(flag["id"] for service in services for flag in service.get("flags", []))
    return {
        "workflow": "owner-authorized-service-version-categorization",
        "generated_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "target": args.target,
        "target_label": args.target_label,
        "source_xml": str(args.from_nmap_xml) if args.from_nmap_xml else None,
        "nmap_command": command,
        "nmap_stderr": nmap_stderr.strip(),
        "taxonomy": {
            "name": rules.get("taxonomy_name"),
            "version": rules.get("taxonomy_version"),
            "rules_path": str(args.rules),
        },
        "summary": {
            "open_services": len(services),
            "categories": dict(sorted(categories.items())),
            "flags": dict(sorted(flags.items())),
        },
        "services": services,
        "handling_notes": [
            "Scan only systems you own or are authorized to assess.",
            "Results may include sensitive service exposure details and should remain private.",
            "Version strings can be misleading when distributions backport security patches; confirm with vendor package metadata.",
            "This workflow does not perform exploitation or vulnerability validation.",
        ],
    }


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    try:
        rules = load_rules(args.rules)
        command: list[str] | None = None
        nmap_stderr = ""
        if args.from_nmap_xml:
            xml_text = args.from_nmap_xml.read_text(encoding="utf-8")
            if not args.target_label:
                args.target_label = clean_label(args.target or args.from_nmap_xml.stem)
        else:
            xml_text, command, nmap_stderr = run_nmap(args)
            args.target_label = clean_label(args.target_label or args.target)

        services = parse_nmap_xml(xml_text, rules)
        report = build_report(args, rules, services, command, nmap_stderr)
        json_path, csv_path, xml_path = write_outputs(
            args.output_dir,
            args.target_label,
            utc_timestamp(),
            report,
            xml_text,
            save_raw_xml=not args.no_save_raw_xml,
        )
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(f"Open services categorized: {len(services)}")
    print(f"JSON: {json_path}")
    print(f"CSV:  {csv_path}")
    if xml_path:
        print(f"XML:  {xml_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
