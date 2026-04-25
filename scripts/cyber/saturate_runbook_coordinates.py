#!/usr/bin/env python3
"""
Build private IP coordinate files from runbook result shards.

The script reads the private runbook CSV/JSONL shards, runs concurrent ping and
coordinate lookup workers, writes each completed IP to raw private coordinate
reports/cache, and leaves the original runbook result shards unchanged.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import ipaddress
import json
import platform
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator


ROOT = Path(__file__).resolve().parents[2]
PRIVATE_ROOT = ROOT / "data" / "private"
DEFAULT_OUTPUT_DIR = PRIVATE_ROOT / "cybersecurity" / "runbook-outputs"
DEFAULT_COORDS_DIR = DEFAULT_OUTPUT_DIR / "coords"
DEFAULT_CACHE_PATH = DEFAULT_COORDS_DIR / "cache"
DEFAULT_COORDS_CSV_PATH = DEFAULT_COORDS_DIR / "csv" / "ip-coordinate-lookups.csv"
DEFAULT_COORDS_JSONL_PATH = DEFAULT_COORDS_DIR / "jsonl" / "ip-coordinate-lookups.jsonl"
DEFAULT_REPORT_PATH = DEFAULT_COORDS_CSV_PATH
LEGACY_CACHE_NAME = "ip-coordinate-cache.json"
LEGACY_REPORT_NAME = "ip-coordinate-lookups.csv"
CACHE_SHARD_PREFIX = "ip-coordinate-cache"
CACHE_SHARD_HEX_LENGTH = 2
CACHE_MANIFEST_NAME = "ip-coordinate-cache-manifest.json"

REPORT_FIELDS = [
    "ip",
    "target_labels",
    "ping_status",
    "ping_rtt_ms",
    "long",
    "lat",
    "coordinate_status",
    "coordinate_provider",
    "city",
    "region",
    "country",
    "org",
    "asn",
    "error",
    "looked_up_at",
]
PROVIDER_URLS = {
    "ipapi-co": "https://ipapi.co/{ip}/json/",
    "ip-api": (
        "http://ip-api.com/json/{ip}"
        "?fields=status,message,query,lat,lon,country,regionName,city,isp,org,as"
    ),
}
IP_API_FIELDS = "status,message,query,lat,lon,country,regionName,city,isp,org,as"
IP_API_BATCH_URL = f"http://ip-api.com/batch?fields={IP_API_FIELDS}"
IP_API_MAX_BATCH_SIZE = 100
DEFAULT_PROVIDER = "ip-api"
DEFAULT_WORKERS = 32
DEFAULT_IP_API_BATCH_SIZE = 100
DEFAULT_IP_API_RETRIES = 3


@dataclass
class RunbookTarget:
    ip: str
    labels: set[str]


def utc_timestamp() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def compact_timestamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def ensure_private_path(path: Path, label: str) -> None:
    resolved = path.resolve()
    private_root = PRIVATE_ROOT.resolve()
    if not resolved.is_relative_to(private_root):
        raise ValueError(f"{label} must stay under {private_root}")


def ensure_not_output_root_file(path: Path, output_dir: Path, label: str) -> None:
    resolved = path.resolve()
    output_root = output_dir.resolve()
    if resolved.parent == output_root and path.suffix and not (path.exists() and path.is_dir()):
        raise ValueError(f"{label} must be in a subdirectory of {output_root}, not directly in that root")


def is_cache_file_path(path: Path) -> bool:
    return path.suffix.lower() == ".json"


def cache_shard_id(ip: str) -> str:
    return hashlib.sha256(ip.encode("ascii")).hexdigest()[:CACHE_SHARD_HEX_LENGTH]


def cache_shard_path(cache_path: Path, shard_id: str) -> Path:
    return cache_path / f"{CACHE_SHARD_PREFIX}-{shard_id}.json"


def is_cache_shard_file(path: Path) -> bool:
    return bool(re.fullmatch(rf"{re.escape(CACHE_SHARD_PREFIX)}-[0-9a-f]{{{CACHE_SHARD_HEX_LENGTH}}}\.json", path.name))


def cache_path_for_ip(cache_path: Path, ip: str) -> Path:
    if is_cache_file_path(cache_path):
        return cache_path
    return cache_shard_path(cache_path, cache_shard_id(ip))


def cache_manifest_path(cache_path: Path) -> Path | None:
    if is_cache_file_path(cache_path):
        return None
    return cache_path / CACHE_MANIFEST_NAME


def file_metadata(path: Path) -> dict[str, object]:
    stat = path.stat()
    return {
        "path": str(path.resolve()),
        "bytes": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
    }


def load_cache_manifest(cache_path: Path) -> dict[str, object]:
    manifest_path = cache_manifest_path(cache_path)
    if manifest_path is None or not manifest_path.exists():
        return {}
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def legacy_cache_was_migrated(cache_path: Path, legacy_path: Path) -> bool:
    manifest = load_cache_manifest(cache_path)
    migrated = manifest.get("migrated_legacy_caches", [])
    if not isinstance(migrated, list) or not legacy_path.exists():
        return False
    current = file_metadata(legacy_path)
    return any(isinstance(item, dict) and item == current for item in migrated)


def write_cache_manifest(cache_path: Path, migrated_legacy_paths: list[Path]) -> None:
    manifest_path = cache_manifest_path(cache_path)
    if manifest_path is None:
        return
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    existing = load_cache_manifest(cache_path)
    migrated: list[dict[str, object]] = []
    for item in existing.get("migrated_legacy_caches", []):
        if isinstance(item, dict):
            migrated.append(item)
    seen = {json.dumps(item, sort_keys=True) for item in migrated}
    for path in migrated_legacy_paths:
        if not path.exists():
            continue
        metadata = file_metadata(path)
        key = json.dumps(metadata, sort_keys=True)
        if key not in seen:
            migrated.append(metadata)
            seen.add(key)
    write_json(
        manifest_path,
        {
            "cache_layout": "sha256-prefix-json-shards",
            "shard_hex_length": CACHE_SHARD_HEX_LENGTH,
            "migrated_legacy_caches": migrated,
            "updated_at": utc_timestamp(),
        },
    )


def legacy_coordinate_cache_paths(output_dir: Path, cache_path: Path) -> list[Path]:
    candidates = [
        output_dir / LEGACY_CACHE_NAME,
        output_dir / "coords" / "cache" / LEGACY_CACHE_NAME,
    ]
    seen: set[Path] = set()
    paths: list[Path] = []
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved == cache_path.resolve() or resolved in seen:
            continue
        seen.add(resolved)
        paths.append(candidate)
    return paths


def as_ip(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        return ipaddress.ip_address(text).compressed
    except ValueError:
        return ""


def row_ip(row: dict[str, Any]) -> str:
    for field in ("host", "target", "ip", "address"):
        ip = as_ip(row.get(field))
        if ip:
            return ip
    return ""


def add_target(targets: dict[str, RunbookTarget], ip: str, label: str) -> None:
    if not ip:
        return
    targets.setdefault(ip, RunbookTarget(ip=ip, labels=set()))
    if label:
        targets[ip].labels.add(label)


def collect_csv_targets(path: Path, targets: dict[str, RunbookTarget]) -> int:
    row_count = 0
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            row_count += 1
            add_target(targets, row_ip(row), str(row.get("target_label") or row.get("target") or ""))
    return row_count


def collect_jsonl_targets(path: Path, targets: dict[str, RunbookTarget]) -> int:
    row_count = 0
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                payload = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_number} is not valid JSONL: {exc}") from exc
            if not isinstance(payload, dict):
                continue
            row_count += 1
            add_target(targets, row_ip(payload), str(payload.get("target_label") or payload.get("target") or ""))
    return row_count


def source_files(output_dir: Path) -> tuple[list[Path], list[Path]]:
    csv_files = sorted((output_dir / "csv").glob("*.csv"))
    jsonl_files = sorted((output_dir / "jsonl").glob("*.jsonl"))
    return csv_files, jsonl_files


def collect_targets(output_dir: Path) -> tuple[list[RunbookTarget], int, list[Path], list[Path]]:
    csv_files, jsonl_files = source_files(output_dir)
    if not csv_files and not jsonl_files:
        raise FileNotFoundError(f"No CSV or JSONL runbook shards found under {output_dir}")

    targets: dict[str, RunbookTarget] = {}
    row_count = 0
    for path in csv_files:
        row_count += collect_csv_targets(path, targets)
    for path in jsonl_files:
        row_count += collect_jsonl_targets(path, targets)

    return list(targets.values()), row_count, csv_files, jsonl_files


def ping_command(ip: str, timeout_ms: int) -> list[str]:
    if platform.system().lower().startswith("win"):
        return ["ping", "-n", "1", "-w", str(timeout_ms), ip]
    timeout_seconds = max(1, round(timeout_ms / 1000))
    return ["ping", "-c", "1", "-W", str(timeout_seconds), ip]


def parse_ping_rtt(output: str) -> str:
    match = re.search(r"time[=<]\s*([0-9.]+)\s*ms", output, flags=re.IGNORECASE)
    if match:
        return match.group(1)
    match = re.search(r"Average\s*=\s*([0-9.]+)\s*ms", output, flags=re.IGNORECASE)
    if match:
        return match.group(1)
    return ""


def ping_once(ip: str, timeout_ms: int) -> tuple[str, str, str]:
    command = ping_command(ip, timeout_ms)
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=max(2, timeout_ms / 1000 + 2),
        )
    except FileNotFoundError as exc:
        return "error", "", f"ping executable not found: {exc}"
    except subprocess.TimeoutExpired as exc:
        return "timeout", "", str(exc)

    combined_output = "\n".join(part for part in (completed.stdout, completed.stderr) if part)
    if completed.returncode == 0:
        return "up", parse_ping_rtt(combined_output), ""
    return "down", parse_ping_rtt(combined_output), combined_output.strip()


def user_agent() -> str:
    return "National-Security-Research runbook coordinate enricher"


def fetch_json(url: str, timeout_seconds: int) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": user_agent(),
        },
    )
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        body = response.read().decode("utf-8")
    payload = json.loads(body)
    if not isinstance(payload, dict):
        raise ValueError("Coordinate provider returned a non-object JSON payload")
    return payload


def fetch_json_array(
    url: str,
    payload: object,
    timeout_seconds: int,
) -> tuple[list[Any], Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": user_agent(),
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        body = response.read().decode("utf-8")
        headers = response.headers
    decoded = json.loads(body)
    if not isinstance(decoded, list):
        raise ValueError("Coordinate provider returned a non-array JSON payload")
    return decoded, headers


def clean_provider_value(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def normalize_coordinate_record(record: dict[str, Any], ip: str = "") -> dict[str, str]:
    normalized = {field: clean_provider_value(record.get(field, "")) for field in REPORT_FIELDS}
    normalized["ip"] = as_ip(normalized.get("ip")) or as_ip(ip)
    return normalized


def merge_coordinate_records(*records: dict[str, str]) -> dict[str, str]:
    merged = {field: "" for field in REPORT_FIELDS}
    for record in records:
        normalized = normalize_coordinate_record(record)
        for field in REPORT_FIELDS:
            if not merged[field] and normalized.get(field):
                merged[field] = normalized[field]
    return merged


def record_has_coordinates(record: dict[str, str]) -> bool:
    return bool(record.get("lat") and record.get("long"))


def extract_generic_coordinates(payload: dict[str, Any]) -> tuple[str, str]:
    lat = clean_provider_value(payload.get("latitude") or payload.get("lat"))
    lon = clean_provider_value(payload.get("longitude") or payload.get("lon") or payload.get("long"))
    if (not lat or not lon) and payload.get("loc"):
        parts = str(payload["loc"]).split(",", maxsplit=1)
        if len(parts) == 2:
            lat = clean_provider_value(parts[0])
            lon = clean_provider_value(parts[1])
    return lat, lon


def provider_url(args: argparse.Namespace, ip: str, provider: str) -> str:
    template = args.provider_url_template if provider == args.provider else None
    template = template or PROVIDER_URLS[provider]
    return template.format(ip=ip)


def provider_sequence(args: argparse.Namespace) -> list[str]:
    providers: list[str] = []
    for provider in [args.provider, *args.fallback_provider]:
        if provider not in providers:
            providers.append(provider)
    return providers


def lookup_coordinates_from_provider(
    args: argparse.Namespace,
    ip: str,
    provider: str,
) -> dict[str, str]:
    address = ipaddress.ip_address(ip)
    if not address.is_global:
        return {
            "long": "",
            "lat": "",
            "coordinate_status": "skipped-non-global-ip",
            "coordinate_provider": provider,
            "error": "Non-global IP addresses do not have public geolocation coordinates.",
        }

    if provider == "none":
        return {
            "long": "",
            "lat": "",
            "coordinate_status": "skipped-provider-none",
            "coordinate_provider": provider,
            "error": "",
        }

    payload = fetch_json(provider_url(args, ip, provider), args.lookup_timeout_seconds)
    return coordinate_record_from_provider_payload(provider, payload)


def coordinate_record_from_provider_payload(provider: str, payload: dict[str, Any]) -> dict[str, str]:
    if provider == "ip-api" and clean_provider_value(payload.get("status")) != "success":
        raise ValueError(clean_provider_value(payload.get("message")) or "ip-api lookup failed")
    if provider == "ipapi-co" and payload.get("error"):
        raise ValueError(clean_provider_value(payload.get("reason")) or "ipapi.co lookup failed")

    lat, lon = extract_generic_coordinates(payload)
    if not lat or not lon:
        raise ValueError("Coordinate provider did not return latitude and longitude")

    return {
        "long": lon,
        "lat": lat,
        "coordinate_status": "ok",
        "coordinate_provider": provider,
        "city": clean_provider_value(payload.get("city")),
        "region": clean_provider_value(payload.get("region") or payload.get("regionName")),
        "country": clean_provider_value(payload.get("country_name") or payload.get("country")),
        "org": clean_provider_value(payload.get("org") or payload.get("isp")),
        "asn": clean_provider_value(payload.get("asn") or payload.get("as")),
        "error": "",
    }


def parse_header_int(headers: Any, name: str) -> int:
    try:
        return int(str(headers.get(name, "")).strip())
    except (AttributeError, TypeError, ValueError):
        return 0


def wait_for_ip_api_limit(headers: Any) -> None:
    remaining = parse_header_int(headers, "X-Rl")
    ttl = parse_header_int(headers, "X-Ttl")
    if remaining == 0 and ttl > 0:
        print(f"ip-api rate limit reached; sleeping {ttl + 1}s", file=sys.stderr, flush=True)
        time.sleep(ttl + 1)


def fetch_ip_api_batch(args: argparse.Namespace, ips: list[str]) -> list[dict[str, Any]]:
    last_error: Exception | None = None
    for attempt in range(args.ip_api_retries + 1):
        try:
            payload, headers = fetch_json_array(IP_API_BATCH_URL, ips, args.lookup_timeout_seconds)
            wait_for_ip_api_limit(headers)
            rows: list[dict[str, Any]] = []
            for item in payload:
                if isinstance(item, dict):
                    rows.append(item)
            return rows
        except urllib.error.HTTPError as exc:
            last_error = exc
            if exc.code == 429 and attempt < args.ip_api_retries:
                ttl = parse_header_int(exc.headers, "X-Ttl") or 60
                print(f"ip-api returned 429; sleeping {ttl + 1}s before retry", file=sys.stderr, flush=True)
                time.sleep(ttl + 1)
                continue
            raise
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            last_error = exc
            if attempt < args.ip_api_retries:
                time.sleep(min(2 ** attempt, 10))
                continue
            raise
    raise ValueError(str(last_error) if last_error else "ip-api batch lookup failed")


def fallback_providers_after_ip_api(args: argparse.Namespace) -> list[str]:
    return [provider for provider in provider_sequence(args) if provider != "ip-api" and provider != "none"]


def lookup_fallback_coordinates(args: argparse.Namespace, ip: str, primary_error: str) -> dict[str, str]:
    errors = [f"ip-api: {primary_error}"] if primary_error else []
    for provider in fallback_providers_after_ip_api(args):
        try:
            return lookup_coordinates_from_provider(args, ip, provider)
        except (OSError, ValueError, urllib.error.URLError, json.JSONDecodeError) as exc:
            errors.append(f"{provider}: {exc}")
    raise ValueError("; ".join(errors) or "No coordinate provider succeeded")


def lookup_coordinates(args: argparse.Namespace, ip: str) -> dict[str, str]:
    errors: list[str] = []
    for provider in provider_sequence(args):
        try:
            return lookup_coordinates_from_provider(args, ip, provider)
        except (OSError, ValueError, urllib.error.URLError, json.JSONDecodeError) as exc:
            errors.append(f"{provider}: {exc}")
    raise ValueError("; ".join(errors) or "No coordinate provider succeeded")


def load_cache_file(path: Path) -> dict[str, dict[str, str]]:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Invalid coordinate cache: {path}")
    cache: dict[str, dict[str, str]] = {}
    for ip, record in payload.items():
        if isinstance(record, dict):
            normalized_ip = as_ip(ip)
            if normalized_ip:
                cache[normalized_ip] = normalize_coordinate_record(record, normalized_ip)
    return cache


def load_cache(path: Path, ips: set[str] | None = None) -> dict[str, dict[str, str]]:
    if is_cache_file_path(path):
        return load_cache_file(path)

    cache: dict[str, dict[str, str]] = {}
    paths: list[Path]
    if ips is None:
        paths = sorted(
            (candidate for candidate in path.glob(f"{CACHE_SHARD_PREFIX}-*.json") if is_cache_shard_file(candidate)),
            key=str,
        ) if path.exists() else []
    else:
        paths = sorted({cache_path_for_ip(path, ip) for ip in ips}, key=str)

    for shard_path in paths:
        for ip, record in load_cache_file(shard_path).items():
            cache[ip] = record
    return cache


def load_cache_for_targets(
    cache_path: Path,
    target_ips: set[str],
    legacy_paths: list[Path],
) -> tuple[dict[str, dict[str, str]], list[Path]]:
    cache = load_cache(cache_path, target_ips)
    migrated_legacy_paths: list[Path] = []

    if is_cache_file_path(cache_path):
        return cache, migrated_legacy_paths

    missing_ips = {ip for ip in target_ips if ip not in cache}
    for legacy_path in legacy_paths:
        if not missing_ips or not legacy_path.exists() or legacy_cache_was_migrated(cache_path, legacy_path):
            continue
        legacy_cache = load_cache_file(legacy_path)
        for ip, record in legacy_cache.items():
            cache[ip] = record
        migrated_legacy_paths.append(legacy_path)
        missing_ips = {ip for ip in missing_ips if ip not in cache}

    return cache, migrated_legacy_paths


def write_cache_store(path: Path, cache: dict[str, dict[str, str]]) -> None:
    if is_cache_file_path(path):
        write_json(path, cache)
        return

    path.mkdir(parents=True, exist_ok=True)
    records_by_shard: dict[str, dict[str, dict[str, str]]] = {}
    for ip, record in cache.items():
        records_by_shard.setdefault(cache_shard_id(ip), {})[ip] = normalize_coordinate_record(record, ip)
    for shard_id, records in records_by_shard.items():
        write_json(cache_shard_path(path, shard_id), records)


def write_cache_record(path: Path, cache: dict[str, dict[str, str]], ip: str) -> None:
    if is_cache_file_path(path):
        write_json(path, cache)
        return

    shard_id = cache_shard_id(ip)
    shard_records = {
        cached_ip: normalize_coordinate_record(record, cached_ip)
        for cached_ip, record in cache.items()
        if cache_shard_id(cached_ip) == shard_id
    }
    write_json(cache_shard_path(path, shard_id), shard_records)


def load_report(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    rows: list[dict[str, str]] = []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            record = normalize_coordinate_record(dict(row))
            if record.get("ip"):
                rows.append(record)
    return rows


def same_path(left: Path, right: Path) -> bool:
    return left.resolve() == right.resolve()


def legacy_coordinate_report_paths(output_dir: Path, report_path: Path, coords_csv_path: Path) -> list[Path]:
    candidates = [
        output_dir / LEGACY_REPORT_NAME,
        output_dir / "ip_coordinate-lookups.csv",
    ]
    existing = {report_path.resolve(), coords_csv_path.resolve()}
    seen: set[Path] = set()
    paths: list[Path] = []
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved in existing or resolved in seen:
            continue
        seen.add(resolved)
        paths.append(candidate)
    return paths


def load_combined_reports(args: argparse.Namespace) -> list[dict[str, str]]:
    report_rows = load_report(args.report_path)
    seen_report_rows = {
        (
            row.get("ip", ""),
            row.get("looked_up_at", ""),
            row.get("coordinate_status", ""),
            row.get("lat", ""),
            row.get("long", ""),
        )
        for row in report_rows
    }

    extra_paths: list[Path] = []
    if not same_path(args.coords_csv_path, args.report_path):
        extra_paths.append(args.coords_csv_path)
    extra_paths.extend(legacy_coordinate_report_paths(args.output_dir, args.report_path, args.coords_csv_path))

    for path in extra_paths:
        for row in load_report(path):
            key = (
                row.get("ip", ""),
                row.get("looked_up_at", ""),
                row.get("coordinate_status", ""),
                row.get("lat", ""),
                row.get("long", ""),
            )
            if key not in seen_report_rows:
                report_rows.append(row)
                seen_report_rows.add(key)
    return report_rows


def latest_records_by_ip(records: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    latest: dict[str, dict[str, str]] = {}
    for record in records:
        ip = record.get("ip", "")
        if not ip:
            continue
        previous = latest.get(ip)
        if previous is None:
            latest[ip] = record
            continue
        previous_score = int(record_has_coordinates(previous))
        current_score = int(record_has_coordinates(record))
        if current_score > previous_score or (
            current_score == previous_score
            and record.get("looked_up_at", "") >= previous.get("looked_up_at", "")
        ):
            latest[ip] = record
    return latest


def reconcile_coordinate_store(
    cache: dict[str, dict[str, str]],
    report_rows: list[dict[str, str]],
) -> tuple[dict[str, dict[str, str]], list[dict[str, str]], bool]:
    latest = latest_records_by_ip(report_rows)
    changed = False

    reconciled_cache: dict[str, dict[str, str]] = {}
    for ip in sorted(set(cache) | set(latest)):
        cache_record_for_ip = cache.get(ip, {})
        latest_record = latest.get(ip, {})
        merged = merge_coordinate_records(cache_record_for_ip, latest_record, {"ip": ip})
        if merged != cache.get(ip):
            changed = True
        reconciled_cache[ip] = merged

    reconciled_rows: list[dict[str, str]] = []
    seen_row_ips: set[str] = set()
    for row in report_rows:
        ip = row.get("ip", "")
        merged = merge_coordinate_records(row, reconciled_cache.get(ip, {}), latest.get(ip, {}), {"ip": ip})
        if merged != row:
            changed = True
        reconciled_rows.append(merged)
        if ip:
            seen_row_ips.add(ip)

    for ip, record in reconciled_cache.items():
        if ip not in seen_row_ips and record_has_coordinates(record):
            reconciled_rows.append(record)
            changed = True

    return reconciled_cache, reconciled_rows, changed


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f"{path.name}.{compact_timestamp()}.tmp")
    temp_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    deadline = time.monotonic() + 10.0
    while True:
        try:
            temp_path.replace(path)
            return
        except PermissionError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.05)


def labels_text(target: RunbookTarget) -> str:
    return "; ".join(sorted(target.labels))


def finalize_coordinate_record(
    target: RunbookTarget,
    record: dict[str, str],
    ping_status: str,
    ping_rtt_ms: str,
    ping_error: str,
) -> dict[str, str]:
    if ping_error and not record.get("error"):
        record["error"] = ping_error

    record.update(
        {
            "ip": target.ip,
            "target_labels": labels_text(target),
            "ping_status": ping_status,
            "ping_rtt_ms": ping_rtt_ms,
            "looked_up_at": utc_timestamp(),
        }
    )
    return normalize_coordinate_record(record)


def build_coordinate_record(
    args: argparse.Namespace,
    target: RunbookTarget,
    cache: dict[str, dict[str, str]],
) -> dict[str, str]:
    cached = cache.get(target.ip)
    if cached and cached.get("lat") and cached.get("long") and not args.force_refresh:
        record = merge_coordinate_records(
            {
                "ip": target.ip,
                "target_labels": labels_text(target),
                "coordinate_status": "cached",
                "ping_status": "skipped-cached-location",
                "ping_rtt_ms": "",
                "error": "",
                "looked_up_at": utc_timestamp(),
            },
            cached,
        )
        return normalize_coordinate_record(record)

    ping_status = "skipped"
    ping_rtt_ms = ""
    ping_error = ""
    if not args.skip_ping:
        ping_status, ping_rtt_ms, ping_error = ping_once(target.ip, args.ping_timeout_ms)

    try:
        record = lookup_coordinates(args, target.ip)
    except (OSError, ValueError, urllib.error.URLError, json.JSONDecodeError) as exc:
        record = {
            "long": "",
            "lat": "",
            "coordinate_status": "error",
            "coordinate_provider": args.provider,
            "error": str(exc),
        }

    return finalize_coordinate_record(target, record, ping_status, ping_rtt_ms, ping_error)


def write_report(path: Path, records: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=REPORT_FIELDS, lineterminator="\n")
        writer.writeheader()
        for record in records:
            writer.writerow(normalize_coordinate_record(record))


def write_jsonl_report(path: Path, records: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(normalize_coordinate_record(record), ensure_ascii=False) + "\n")


def initialize_report(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=REPORT_FIELDS, lineterminator="\n")
        writer.writeheader()


def initialize_jsonl_report(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("", encoding="utf-8")


def append_report_record(path: Path, record: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    needs_header = not path.exists() or path.stat().st_size == 0
    with path.open("a", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=REPORT_FIELDS, lineterminator="\n")
        if needs_header:
            writer.writeheader()
        writer.writerow(normalize_coordinate_record(record))


def append_jsonl_record(path: Path, record: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(normalize_coordinate_record(record), ensure_ascii=False) + "\n")


def target_needs_coordinate_lookup(
    args: argparse.Namespace,
    target: RunbookTarget,
    cache: dict[str, dict[str, str]],
) -> bool:
    if args.provider == "none":
        return False
    if not ipaddress.ip_address(target.ip).is_global:
        return False
    cached = cache.get(target.ip, {})
    return bool(args.force_refresh or not cached.get("lat") or not cached.get("long"))


def successful_coordinate_record(record: dict[str, str]) -> bool:
    return record_has_coordinates(record)


def cache_record(record: dict[str, str]) -> dict[str, str]:
    return normalize_coordinate_record(record)


def target_has_cached_coordinates(
    args: argparse.Namespace,
    target: RunbookTarget,
    cache: dict[str, dict[str, str]],
) -> bool:
    cached = cache.get(target.ip, {})
    return bool(cached.get("lat") and cached.get("long") and not args.force_refresh)


def target_will_ping(
    args: argparse.Namespace,
    target: RunbookTarget,
    cache: dict[str, dict[str, str]],
) -> bool:
    return bool(not args.skip_ping and not target_has_cached_coordinates(args, target, cache))


def process_target(
    args: argparse.Namespace,
    target: RunbookTarget,
    cache_snapshot: dict[str, dict[str, str]],
) -> tuple[RunbookTarget, dict[str, str]]:
    return target, build_coordinate_record(args, target, cache_snapshot)


def should_use_ip_api_batch(args: argparse.Namespace) -> bool:
    return bool(args.provider == "ip-api" and not args.provider_url_template and args.ip_api_batch_size > 1)


def chunked_targets(targets: list[RunbookTarget], size: int) -> Iterator[list[RunbookTarget]]:
    for index in range(0, len(targets), size):
        yield targets[index : index + size]


def ping_targets(
    args: argparse.Namespace,
    targets: list[RunbookTarget],
) -> dict[str, tuple[str, str, str]]:
    if args.skip_ping:
        return {target.ip: ("skipped", "", "") for target in targets}

    ping_results: dict[str, tuple[str, str, str]] = {}
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {executor.submit(ping_once, target.ip, args.ping_timeout_ms): target for target in targets}
        for future in as_completed(futures):
            target = futures[future]
            ping_results[target.ip] = future.result()
    return ping_results


def ip_api_batch_record_for_target(
    args: argparse.Namespace,
    target: RunbookTarget,
    payload: dict[str, Any] | None,
    batch_error: str,
    ping_result: tuple[str, str, str],
) -> dict[str, str]:
    ping_status, ping_rtt_ms, ping_error = ping_result
    try:
        if batch_error:
            raise ValueError(batch_error)
        if payload is None:
            raise ValueError("ip-api batch response did not include this IP")
        record = coordinate_record_from_provider_payload("ip-api", payload)
    except (ValueError, OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
        try:
            record = lookup_fallback_coordinates(args, target.ip, str(exc))
        except (OSError, ValueError, urllib.error.URLError, json.JSONDecodeError) as fallback_exc:
            record = {
                "long": "",
                "lat": "",
                "coordinate_status": "error",
                "coordinate_provider": "ip-api",
                "error": str(fallback_exc),
            }
    return finalize_coordinate_record(target, record, ping_status, ping_rtt_ms, ping_error)


def persist_coordinate_record(
    args: argparse.Namespace,
    cache: dict[str, dict[str, str]],
    target: RunbookTarget,
    record: dict[str, str],
    write_coordinate_shards: bool,
) -> tuple[int, int]:
    if successful_coordinate_record(record):
        if record.get("coordinate_status") == "cached" and target.ip in cache:
            cache[target.ip] = merge_coordinate_records(cache[target.ip], cache_record(record))
        else:
            cache[target.ip] = merge_coordinate_records(cache_record(record), cache.get(target.ip, {}))
        write_cache_record(args.cache_path, cache, target.ip)

    append_report_record(args.report_path, record)

    coordinate_csv_rows_written = 1 if same_path(args.coords_csv_path, args.report_path) else 0
    if write_coordinate_shards:
        if not same_path(args.coords_csv_path, args.report_path):
            append_report_record(args.coords_csv_path, record)
            coordinate_csv_rows_written = 1
        append_jsonl_record(args.coords_jsonl_path, record)
        return coordinate_csv_rows_written, 1

    return coordinate_csv_rows_written, 0


def process_ip_api_batches(
    args: argparse.Namespace,
    targets: list[RunbookTarget],
    cache: dict[str, dict[str, str]],
    cache_snapshot: dict[str, dict[str, str]],
    write_coordinate_shards: bool,
) -> tuple[int, int, int]:
    coordinate_csv_rows_written = 0
    coordinate_jsonl_rows_written = 0
    completed_count = 0
    lookup_targets = [target for target in targets if target_needs_coordinate_lookup(args, target, cache_snapshot)]
    lookup_ips = {target.ip for target in lookup_targets}
    no_lookup_targets = [target for target in targets if target.ip not in lookup_ips]
    total_targets = len(targets)

    for target in no_lookup_targets:
        record = build_coordinate_record(args, target, cache_snapshot)
        csv_delta, jsonl_delta = persist_coordinate_record(args, cache, target, record, write_coordinate_shards)
        coordinate_csv_rows_written += csv_delta
        coordinate_jsonl_rows_written += jsonl_delta
        completed_count += 1
        print(
            f"{completed_count}/{total_targets} {target.ip}: ping={record['ping_status']} "
            f"coords={record['coordinate_status']} provider={record['coordinate_provider']}",
            file=sys.stderr,
            flush=True,
        )

    batch_size = min(args.ip_api_batch_size, IP_API_MAX_BATCH_SIZE)
    for chunk in chunked_targets(lookup_targets, batch_size):
        ping_results = ping_targets(args, chunk)
        batch_error = ""
        payloads_by_ip: dict[str, dict[str, Any]] = {}
        try:
            payloads = fetch_ip_api_batch(args, [target.ip for target in chunk])
            for payload in payloads:
                ip = as_ip(payload.get("query") if isinstance(payload, dict) else "")
                if ip:
                    payloads_by_ip[ip] = payload
        except (OSError, ValueError, urllib.error.URLError, json.JSONDecodeError) as exc:
            batch_error = f"ip-api batch: {exc}"

        for target in chunk:
            record = ip_api_batch_record_for_target(
                args,
                target,
                payloads_by_ip.get(target.ip),
                batch_error,
                ping_results.get(target.ip, ("skipped", "", "")),
            )
            csv_delta, jsonl_delta = persist_coordinate_record(args, cache, target, record, write_coordinate_shards)
            coordinate_csv_rows_written += csv_delta
            coordinate_jsonl_rows_written += jsonl_delta
            completed_count += 1
            print(
                f"{completed_count}/{total_targets} {target.ip}: ping={record['ping_status']} "
                f"coords={record['coordinate_status']} provider={record['coordinate_provider']}",
                file=sys.stderr,
                flush=True,
            )

    return len(lookup_targets), coordinate_csv_rows_written, coordinate_jsonl_rows_written


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Ping each unique IP from private runbook outputs with concurrent workers, "
            "look up coordinates, and write raw coordinate files without changing runbook shards."
        )
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Private runbook output directory containing csv/ and jsonl/ shards.",
    )
    parser.add_argument(
        "--cache-path",
        type=Path,
        default=DEFAULT_CACHE_PATH,
        help="Directory for sharded coordinate cache JSON files, or a legacy single JSON file.",
    )
    parser.add_argument("--report-path", type=Path, default=DEFAULT_REPORT_PATH)
    parser.add_argument("--coords-csv-path", type=Path, default=DEFAULT_COORDS_CSV_PATH)
    parser.add_argument("--coords-jsonl-path", type=Path, default=DEFAULT_COORDS_JSONL_PATH)
    parser.add_argument(
        "--provider",
        choices=["ipapi-co", "ip-api", "none"],
        default=DEFAULT_PROVIDER,
        help="Coordinate provider. Use none to only add blank long/lat fields and a ping report.",
    )
    parser.add_argument(
        "--fallback-provider",
        action="append",
        choices=["ipapi-co", "ip-api"],
        default=[],
        help="Fallback coordinate provider to try when the primary provider fails. Repeat for multiple.",
    )
    parser.add_argument(
        "--provider-url-template",
        help="Custom JSON lookup URL template. Use {ip} where the IP should be inserted.",
    )
    parser.add_argument("--max-targets", type=int, default=0, help="Optional IP limit. 0 means no limit.")
    parser.add_argument(
        "--only-ip",
        action="append",
        default=[],
        help="Limit coordinate lookup to one IP. Repeat for multiple IPs.",
    )
    parser.add_argument("--ping-timeout-ms", type=int, default=1000)
    parser.add_argument("--lookup-timeout-seconds", type=int, default=10)
    parser.add_argument(
        "--workers",
        type=int,
        default=DEFAULT_WORKERS,
        help="Concurrent ping/coordinate workers. Default: %(default)s.",
    )
    parser.add_argument(
        "--rate-limit-seconds",
        type=float,
        default=0.0,
        help="Optional delay between submitting uncached coordinate lookups. Default: %(default)s.",
    )
    parser.add_argument(
        "--ip-api-batch-size",
        type=int,
        default=DEFAULT_IP_API_BATCH_SIZE,
        help=(
            "Use ip-api's batch endpoint with this many IPs per request. "
            "Set to 1 to use per-IP requests. Max: 100. Default: %(default)s."
        ),
    )
    parser.add_argument(
        "--ip-api-retries",
        type=int,
        default=DEFAULT_IP_API_RETRIES,
        help="Retries for ip-api batch requests, including 429 waits. Default: %(default)s.",
    )
    parser.add_argument(
        "--i-own-these-servers",
        action="store_true",
        help="Required before live pinging the listed IPs.",
    )
    parser.add_argument("--skip-ping", action="store_true", help="Do not send ICMP pings.")
    parser.add_argument("--dry-run", action="store_true", help="Show planned work without network calls or writes.")
    parser.add_argument(
        "--cached-only",
        action="store_true",
        help="Process only IPs that already have cached long/lat values.",
    )
    parser.add_argument(
        "--no-coordinate-shards",
        action="store_true",
        help="Skip the extra coordinate JSONL shard. The CSV report/cache still stay under subdirectories.",
    )
    parser.add_argument(
        "--no-update-shards",
        action="store_true",
        help="Accepted for older commands; runbook result shards are never updated.",
    )
    parser.add_argument(
        "--overwrite-coordinates",
        action="store_true",
        help="Accepted for older commands; coordinate files are raw append-only outputs.",
    )
    parser.add_argument("--force-refresh", action="store_true", help="Ignore cached coordinate values.")
    parser.add_argument(
        "--reconcile-coordinate-store",
        action="store_true",
        help="Scan existing coordinate reports and cache shards to fill missing fields before processing.",
    )
    parser.add_argument("--no-backup", action="store_true", help="Accepted for older commands; no runbook shard backups are made.")
    parser.add_argument("--reset-report", action="store_true", help="Clear the coordinate lookup report before appending.")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    try:
        if args.max_targets < 0:
            raise ValueError("--max-targets must be 0 or greater")
        if args.ping_timeout_ms <= 0:
            raise ValueError("--ping-timeout-ms must be greater than 0")
        if args.lookup_timeout_seconds <= 0:
            raise ValueError("--lookup-timeout-seconds must be greater than 0")
        if args.workers < 1:
            raise ValueError("--workers must be at least 1")
        if args.rate_limit_seconds < 0:
            raise ValueError("--rate-limit-seconds must be 0 or greater")
        if not 1 <= args.ip_api_batch_size <= IP_API_MAX_BATCH_SIZE:
            raise ValueError(f"--ip-api-batch-size must be between 1 and {IP_API_MAX_BATCH_SIZE}")
        if args.ip_api_retries < 0:
            raise ValueError("--ip-api-retries must be 0 or greater")

        ensure_private_path(args.output_dir, "--output-dir")
        ensure_private_path(args.cache_path, "--cache-path")
        ensure_private_path(args.report_path, "--report-path")
        ensure_private_path(args.coords_csv_path, "--coords-csv-path")
        ensure_private_path(args.coords_jsonl_path, "--coords-jsonl-path")
        ensure_not_output_root_file(args.cache_path, args.output_dir, "--cache-path")
        ensure_not_output_root_file(args.report_path, args.output_dir, "--report-path")
        ensure_not_output_root_file(args.coords_csv_path, args.output_dir, "--coords-csv-path")
        ensure_not_output_root_file(args.coords_jsonl_path, args.output_dir, "--coords-jsonl-path")

        targets, row_count, csv_files, jsonl_files = collect_targets(args.output_dir)
        if args.only_ip:
            selected_ips = {ipaddress.ip_address(value).compressed for value in args.only_ip}
            targets = [target for target in targets if target.ip in selected_ips]
            if not targets:
                raise ValueError("None of the --only-ip values were found in the runbook shards")
        if args.max_targets:
            targets = targets[: args.max_targets]

        target_ips = {target.ip for target in targets}
        cache, migrated_legacy_cache_paths = load_cache_for_targets(
            args.cache_path,
            target_ips,
            legacy_coordinate_cache_paths(args.output_dir, args.cache_path),
        )
        report_rows: list[dict[str, str]] = []
        reconciled_existing_records = False
        if args.reset_report:
            pass
        elif args.reconcile_coordinate_store or not cache:
            report_rows = load_combined_reports(args)
            cache, report_rows, reconciled_existing_records = reconcile_coordinate_store(cache, report_rows)
        if args.cached_only:
            targets = [
                target
                for target in targets
                if cache.get(target.ip, {}).get("lat") and cache.get(target.ip, {}).get("long")
            ]
            if not targets:
                raise ValueError("No cached coordinate records were found for the selected targets")

        if args.dry_run:
            print(f"Rows scanned for IPs: {row_count}")
            print(f"Unique IPs planned: {len(targets)}")
            print(f"CSV shards: {len(csv_files)}")
            print(f"JSONL shards: {len(jsonl_files)}")
            print(f"Private report path: {args.report_path}")
            print(f"Private coordinate CSV path: {args.coords_csv_path}")
            print(f"Private coordinate JSONL path: {args.coords_jsonl_path}")
            print(f"Private coordinate cache path: {args.cache_path}")
            return 0

        write_coordinate_shards = not args.no_coordinate_shards
        if migrated_legacy_cache_paths:
            write_cache_store(args.cache_path, cache)
            write_cache_manifest(args.cache_path, migrated_legacy_cache_paths)
        if args.reset_report:
            initialize_report(args.report_path)
            if write_coordinate_shards and not same_path(args.coords_csv_path, args.report_path):
                initialize_report(args.coords_csv_path)
            if write_coordinate_shards:
                initialize_jsonl_report(args.coords_jsonl_path)
        elif (
            reconciled_existing_records
            or (report_rows and not args.report_path.exists())
            or (
                write_coordinate_shards
                and report_rows
                and (not args.coords_csv_path.exists() or not args.coords_jsonl_path.exists())
            )
        ):
            write_cache_store(args.cache_path, cache)
            write_report(args.report_path, report_rows)
            if write_coordinate_shards:
                if not same_path(args.coords_csv_path, args.report_path):
                    write_report(args.coords_csv_path, report_rows)
                write_jsonl_report(args.coords_jsonl_path, report_rows)

        cache_snapshot = {ip: dict(record) for ip, record in cache.items()}
        selected_target_count = len(targets)
        cached_skip_count = 0
        if not args.cached_only and not args.force_refresh:
            active_targets = [
                target
                for target in targets
                if not target_has_cached_coordinates(args, target, cache_snapshot)
            ]
            cached_skip_count = len(targets) - len(active_targets)
            targets = active_targets
        will_ping = (
            not args.skip_ping
            and any(target_will_ping(args, target, cache_snapshot) for target in targets)
        )
        if will_ping and not args.i_own_these_servers:
            raise PermissionError(
                "Refusing to ping without --i-own-these-servers. Only probe systems you own or are authorized to assess."
            )

        uncached_lookup_count = 0
        coordinate_csv_rows_written = 0
        coordinate_jsonl_rows_written = 0
        if should_use_ip_api_batch(args):
            (
                uncached_lookup_count,
                coordinate_csv_rows_written,
                coordinate_jsonl_rows_written,
            ) = process_ip_api_batches(args, targets, cache, cache_snapshot, write_coordinate_shards)
        else:
            futures: list[Future[tuple[RunbookTarget, dict[str, str]]]] = []
            submitted = 0

            with ThreadPoolExecutor(max_workers=args.workers) as executor:
                for target in targets:
                    if target_needs_coordinate_lookup(args, target, cache_snapshot):
                        uncached_lookup_count += 1
                        if submitted > 0 and args.rate_limit_seconds:
                            time.sleep(args.rate_limit_seconds)
                    futures.append(executor.submit(process_target, args, target, cache_snapshot))
                    submitted += 1

                for completed_count, future in enumerate(as_completed(futures), start=1):
                    target, record = future.result()
                    csv_delta, jsonl_delta = persist_coordinate_record(
                        args,
                        cache,
                        target,
                        record,
                        write_coordinate_shards,
                    )
                    coordinate_csv_rows_written += csv_delta
                    coordinate_jsonl_rows_written += jsonl_delta

                    print(
                        f"{completed_count}/{len(targets)} {target.ip}: ping={record['ping_status']} "
                        f"coords={record['coordinate_status']} provider={record['coordinate_provider']}",
                        file=sys.stderr,
                        flush=True,
                    )

    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(f"Rows scanned for IPs: {row_count}")
    print(f"Unique IPs selected: {selected_target_count}")
    print(f"Unique IPs processed: {len(targets)}")
    print(f"Cached coordinate skips: {cached_skip_count}")
    print(f"Uncached coordinate lookups: {uncached_lookup_count}")
    print("Runbook CSV rows updated: 0")
    print("Runbook JSONL rows updated: 0")
    print(f"Coordinate CSV rows written: {coordinate_csv_rows_written}")
    print(f"Coordinate JSONL rows written: {coordinate_jsonl_rows_written}")
    print(f"Private coordinate cache shards: {args.cache_path}")
    print(f"Private coordinate report: {args.report_path}")
    if write_coordinate_shards:
        print(f"Private coordinate CSV shard: {args.coords_csv_path}")
        print(f"Private coordinate JSONL shard: {args.coords_jsonl_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
