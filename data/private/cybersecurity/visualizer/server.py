#!/usr/bin/env python3
"""
Serve the private cybersecurity runbook flow visualizer.

The browser UI reads through this local server so exports can be written back to
data/private/cybersecurity/runbook-outputs/quick-output.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import ipaddress
import json
import re
from collections import Counter
from datetime import datetime
from functools import partial
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse


ROOT = Path(__file__).resolve().parents[4]
VISUALIZER_DIR = Path(__file__).resolve().parent
RUNBOOK_OUTPUTS_DIR = ROOT / "data" / "private" / "cybersecurity" / "runbook-outputs"
CSV_DIR = RUNBOOK_OUTPUTS_DIR / "csv"
JSONL_DIR = RUNBOOK_OUTPUTS_DIR / "jsonl"
QUICK_OUTPUT_DIR = RUNBOOK_OUTPUTS_DIR / "quick-output"
COORDINATE_LOOKUPS_CSV = RUNBOOK_OUTPUTS_DIR / "coords" / "csv" / "ip-coordinate-lookups.csv"
LEGACY_COORDINATE_LOOKUPS_CSV = RUNBOOK_OUTPUTS_DIR / "ip-coordinate-lookups.csv"
COORDINATE_LOOKUPS_CSV_ALIASES = (
    COORDINATE_LOOKUPS_CSV,
    LEGACY_COORDINATE_LOOKUPS_CSV,
    RUNBOOK_OUTPUTS_DIR / "ip_coordinate-lookups.csv",
)
COORDINATE_CACHE_DIR = RUNBOOK_OUTPUTS_DIR / "coords" / "cache"
COORDINATE_CACHE_SHARD_GLOB = "ip-coordinate-cache-*.json"
LEGACY_COORDINATE_CACHE_JSON = RUNBOOK_OUTPUTS_DIR / "ip-coordinate-cache.json"
MAP_CHUNKS_DIR = RUNBOOK_OUTPUTS_DIR / "map-chunks"
MAP_CHUNK_MANIFEST_JSON = MAP_CHUNKS_DIR / "manifest.json"
WORK_DIR = RUNBOOK_OUTPUTS_DIR / "_work"

PREFERRED_HIERARCHY = [
    "protocol",
    "service_name",
    "product",
    "version",
    "port",
    "host",
    "target_label",
    "scan_status",
    "host_status",
    "cpe",
    "extrainfo",
    "error",
    "target",
]

OPTION_PAGE_SIZE = 120
ROW_PAGE_SIZE = 250
MAP_POINT_LIMIT = 10000
MAP_CHUNK_RESPONSE_POINT_LIMIT = 500

_DATA_CACHE: dict[str, object] = {
    "signature": None,
    "rows": [],
    "headers": [],
    "shards": [],
    "source_format": "",
}

_COORDINATE_CACHE: dict[str, object] = {
    "signature": None,
    "source_files": [],
    "lookup_row_count": 0,
    "lookup_error_count": 0,
    "lookup_ok_count": 0,
}

_COORDINATE_RECORD_CACHE: dict[str, object] = {
    "signature": None,
    "source_signature": None,
    "ips": set(),
    "lookup_rows_by_ip": {},
    "cache_rows_by_ip": {},
}

_MAP_CHUNK_MANIFEST_CACHE: dict[str, object] = {
    "signature": None,
    "manifest": {},
}


def reset_caches() -> None:
    _DATA_CACHE.update(
        {
            "signature": None,
            "rows": [],
            "headers": [],
            "shards": [],
            "source_format": "",
        }
    )
    _COORDINATE_CACHE.update(
        {
            "signature": None,
            "source_files": [],
            "lookup_row_count": 0,
            "lookup_error_count": 0,
            "lookup_ok_count": 0,
        }
    )
    _COORDINATE_RECORD_CACHE.update(
        {
            "signature": None,
            "source_signature": None,
            "ips": set(),
            "lookup_rows_by_ip": {},
            "cache_rows_by_ip": {},
        }
    )
    _MAP_CHUNK_MANIFEST_CACHE.update(
        {
            "signature": None,
            "manifest": {},
        }
    )


def configure_runbook_outputs(output_dir: Path) -> None:
    global RUNBOOK_OUTPUTS_DIR
    global CSV_DIR
    global JSONL_DIR
    global QUICK_OUTPUT_DIR
    global COORDINATE_LOOKUPS_CSV
    global LEGACY_COORDINATE_LOOKUPS_CSV
    global COORDINATE_LOOKUPS_CSV_ALIASES
    global COORDINATE_CACHE_DIR
    global LEGACY_COORDINATE_CACHE_JSON
    global MAP_CHUNKS_DIR
    global MAP_CHUNK_MANIFEST_JSON
    global WORK_DIR

    RUNBOOK_OUTPUTS_DIR = output_dir.resolve()
    CSV_DIR = RUNBOOK_OUTPUTS_DIR / "csv"
    JSONL_DIR = RUNBOOK_OUTPUTS_DIR / "jsonl"
    QUICK_OUTPUT_DIR = RUNBOOK_OUTPUTS_DIR / "quick-output"
    COORDINATE_LOOKUPS_CSV = RUNBOOK_OUTPUTS_DIR / "coords" / "csv" / "ip-coordinate-lookups.csv"
    LEGACY_COORDINATE_LOOKUPS_CSV = RUNBOOK_OUTPUTS_DIR / "ip-coordinate-lookups.csv"
    COORDINATE_LOOKUPS_CSV_ALIASES = (
        COORDINATE_LOOKUPS_CSV,
        LEGACY_COORDINATE_LOOKUPS_CSV,
        RUNBOOK_OUTPUTS_DIR / "ip_coordinate-lookups.csv",
    )
    COORDINATE_CACHE_DIR = RUNBOOK_OUTPUTS_DIR / "coords" / "cache"
    LEGACY_COORDINATE_CACHE_JSON = RUNBOOK_OUTPUTS_DIR / "ip-coordinate-cache.json"
    MAP_CHUNKS_DIR = RUNBOOK_OUTPUTS_DIR / "map-chunks"
    MAP_CHUNK_MANIFEST_JSON = MAP_CHUNKS_DIR / "manifest.json"
    WORK_DIR = RUNBOOK_OUTPUTS_DIR / "_work"
    reset_caches()


def source_files() -> tuple[str, list[Path]]:
    """Prefer CSV shards because they are smaller and faster to parse here."""
    csv_files = sorted(CSV_DIR.glob("*.csv")) if CSV_DIR.exists() else []
    if csv_files:
        return "csv", csv_files

    jsonl_files = sorted(JSONL_DIR.glob("*.jsonl")) if JSONL_DIR.exists() else []
    return "jsonl", jsonl_files


def pipeline_state_path() -> Path:
    return RUNBOOK_OUTPUTS_DIR / "state" / "pipeline-state.json"


def count_target_rows(path: Path) -> int:
    if not path.exists():
        return 0
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            return max(0, sum(1 for _line in handle) - 1)
    except OSError:
        return 0


def active_work_chunk(chunks_completed: int) -> dict[str, object]:
    if not WORK_DIR.exists():
        return {}
    candidates: list[tuple[int, Path]] = []
    for path in WORK_DIR.iterdir():
        if not path.is_dir():
            continue
        match = re.fullmatch(r"chunk-(\d+)", path.name)
        if not match:
            continue
        chunk_number = int(match.group(1))
        if chunk_number > chunks_completed:
            candidates.append((chunk_number, path))
    if not candidates:
        return {}

    chunk_number, chunk_dir = sorted(candidates)[-1]
    run_data_path = chunk_dir / "run-data.info"
    target_path = chunk_dir / "targets.csv"
    completed_targets = 0
    updated_at = ""
    if run_data_path.exists():
        try:
            payload = json.loads(run_data_path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                completed_targets = int(payload.get("next_index") or 0)
                updated_at = normalize_value(payload.get("updated_at"))
        except (OSError, ValueError, json.JSONDecodeError):
            completed_targets = 0
    return {
        "chunk_number": chunk_number,
        "completed_targets": completed_targets,
        "target_count": count_target_rows(target_path),
        "updated_at": updated_at,
        "work_dir": str(chunk_dir.relative_to(ROOT)),
    }


def pipeline_progress() -> dict[str, object]:
    path = pipeline_state_path()
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"state_path": str(path.relative_to(ROOT)), "status": "unreadable"}
    if not isinstance(payload, dict):
        return {"state_path": str(path.relative_to(ROOT)), "status": "invalid"}

    selected_ranges = int(payload.get("selected_ranges") or 0)
    processed_ranges = int(payload.get("processed_ranges") or 0)
    selected_addresses = int(payload.get("selected_addresses") or 0)
    processed_addresses = int(payload.get("processed_addresses") or 0)
    selected_targets = int(payload.get("selected_targets") or selected_addresses or 0)
    processed_targets = int(payload.get("processed_targets") or processed_addresses or 0)
    range_percent = (processed_ranges / selected_ranges * 100) if selected_ranges else 0.0
    address_percent = (processed_addresses / selected_addresses * 100) if selected_addresses else 0.0
    target_percent = (processed_targets / selected_targets * 100) if selected_targets else 0.0
    current_chunk = payload.get("current_chunk")
    current_chunk_number = ""
    if isinstance(current_chunk, dict):
        current_chunk_number = str(current_chunk.get("chunk_number") or "")
    active_chunk = active_work_chunk(int(payload.get("chunks_completed") or 0))
    if active_chunk and not current_chunk_number:
        current_chunk_number = str(active_chunk.get("chunk_number") or "")

    return {
        "state_path": str(path.relative_to(ROOT)),
        "status": "ok",
        "phase": payload.get("phase", ""),
        "pipeline_kind": payload.get("pipeline_kind", ""),
        "chunks_completed": payload.get("chunks_completed", 0),
        "current_chunk": current_chunk_number,
        "active_chunk": active_chunk,
        "processed_ranges": processed_ranges,
        "selected_ranges": selected_ranges,
        "range_percent": round(range_percent, 2),
        "processed_addresses": processed_addresses,
        "selected_addresses": selected_addresses,
        "address_percent": round(address_percent, 2),
        "processed_targets": processed_targets,
        "selected_targets": selected_targets,
        "target_percent": round(target_percent, 2),
        "skipped_redundant_ranges": payload.get("skipped_redundant_ranges", 0),
        "skipped_redundant_addresses": payload.get("skipped_redundant_addresses", 0),
        "updated_at": payload.get("updated_at", ""),
    }


def map_chunk_manifest() -> dict[str, object]:
    path = MAP_CHUNK_MANIFEST_JSON
    if not path.exists():
        return {}

    signature = file_signature([path])
    if _MAP_CHUNK_MANIFEST_CACHE["signature"] == signature:
        manifest = _MAP_CHUNK_MANIFEST_CACHE["manifest"]
        return manifest if isinstance(manifest, dict) else {}

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        payload = {}
    if not isinstance(payload, dict):
        payload = {}

    _MAP_CHUNK_MANIFEST_CACHE.update({"signature": signature, "manifest": payload})
    return payload


def organized_map_available() -> bool:
    manifest = map_chunk_manifest()
    return bool(manifest.get("levels"))


def map_level_items(manifest: dict[str, object]) -> list[dict[str, object]]:
    levels = manifest.get("levels", {})
    if not isinstance(levels, dict):
        return []
    items = [value for value in levels.values() if isinstance(value, dict)]
    return sorted(items, key=lambda item: float(item.get("cell_degrees") or 999.0), reverse=True)


def organized_map_counts(manifest: dict[str, object]) -> tuple[int, int]:
    levels = map_level_items(manifest)
    finest = levels[-1] if levels else {}
    return int(finest.get("point_count") or 0), int(manifest.get("mapped_ip_count") or 0)


def parse_float_query(value: object, default: float) -> float:
    try:
        parsed = float(normalize_value(value))
    except ValueError:
        return default
    return parsed


def normalized_bounds(
    north: object = 90.0,
    south: object = -90.0,
    east: object = 180.0,
    west: object = -180.0,
) -> dict[str, float]:
    north_value = min(90.0, max(-90.0, parse_float_query(north, 90.0)))
    south_value = min(90.0, max(-90.0, parse_float_query(south, -90.0)))
    east_value = min(180.0, max(-180.0, parse_float_query(east, 180.0)))
    west_value = min(180.0, max(-180.0, parse_float_query(west, -180.0)))
    if south_value > north_value:
        south_value, north_value = north_value, south_value
    if west_value > east_value:
        west_value, east_value = east_value, west_value
    return {
        "north": north_value,
        "south": south_value,
        "east": east_value,
        "west": west_value,
    }


def bbox_from_payload(payload: object) -> dict[str, float]:
    if not isinstance(payload, dict):
        return {}
    raw_bbox = payload.get("bbox", payload)
    if not isinstance(raw_bbox, dict):
        return {}
    bounds = normalized_bounds(
        raw_bbox.get("north", 90.0),
        raw_bbox.get("south", -90.0),
        raw_bbox.get("east", 180.0),
        raw_bbox.get("west", -180.0),
    )
    if bounds == {"north": 90.0, "south": -90.0, "east": 180.0, "west": -180.0}:
        return {}
    return bounds


def bbox_intersects(a: dict[str, float], b: dict[str, float]) -> bool:
    return not (
        a["east"] < b["west"]
        or a["west"] > b["east"]
        or a["north"] < b["south"]
        or a["south"] > b["north"]
    )


def bbox_contains_coordinates(bounds: dict[str, float], latitude: float, longitude: float) -> bool:
    return (
        bounds["south"] <= latitude <= bounds["north"]
        and bounds["west"] <= longitude <= bounds["east"]
    )


def chunk_bbox(chunk: dict[str, object]) -> dict[str, float]:
    bbox = chunk.get("bbox", {})
    return bbox_from_payload(bbox) or normalized_bounds()


def level_for_zoom(levels: list[dict[str, object]], zoom: float) -> dict[str, object]:
    if not levels:
        return {}
    selected = levels[0]
    for level in levels:
        min_zoom = float(level.get("min_zoom") or 0)
        max_zoom = float(level.get("max_zoom") or 0)
        if min_zoom <= zoom <= max_zoom:
            return level
        if zoom >= min_zoom:
            selected = level
    return selected


def candidate_chunks(level: dict[str, object], bounds: dict[str, float]) -> list[dict[str, object]]:
    chunks = level.get("chunks", [])
    if not isinstance(chunks, list):
        return []
    return [
        chunk
        for chunk in chunks
        if isinstance(chunk, dict) and bbox_intersects(chunk_bbox(chunk), bounds)
    ]


def choose_chunk_level(
    levels: list[dict[str, object]],
    zoom: float,
    bounds: dict[str, float],
) -> tuple[dict[str, object], list[dict[str, object]], int]:
    if not levels:
        return {}, [], 0
    best_level = levels[0]
    best_chunks = candidate_chunks(best_level, bounds)
    best_estimate = sum(int(chunk.get("point_count") or 0) for chunk in best_chunks)
    for level in reversed(levels):
        chunks = candidate_chunks(level, bounds)
        estimate = sum(int(chunk.get("point_count") or 0) for chunk in chunks)
        if estimate <= MAP_CHUNK_RESPONSE_POINT_LIMIT:
            return level, chunks, estimate
        if estimate < best_estimate:
            best_level = level
            best_chunks = chunks
            best_estimate = estimate
    return best_level, best_chunks, best_estimate


def safe_chunk_path(relative_path: object) -> Path | None:
    text = normalize_value(relative_path).strip()
    if not text:
        return None
    candidate = RUNBOOK_OUTPUTS_DIR / Path(text)
    try:
        resolved = candidate.resolve()
        root = RUNBOOK_OUTPUTS_DIR.resolve()
        if resolved != root and root not in resolved.parents:
            return None
    except OSError:
        return None
    return candidate


def build_map_chunks_payload(zoom: float, bounds: dict[str, float]) -> dict[str, object]:
    manifest = map_chunk_manifest()
    levels = map_level_items(manifest)
    if not levels:
        dataset = get_dataset()
        rows = dataset["rows"]  # type: ignore[assignment]
        assert isinstance(rows, list)
        points, point_count, mapped_ip_count = build_map_points(rows)
        return {
            "ok": True,
            "chunked": False,
            "level": "",
            "zoom": zoom,
            "bounds": bounds,
            "points": points,
            "loaded_chunks": 0,
            "candidate_points": point_count,
            "total_points": point_count,
            "mapped_ip_count": mapped_ip_count,
            "map_point_limit": MAP_POINT_LIMIT,
        }

    level, chunks, estimate = choose_chunk_level(levels, zoom, bounds)
    level_id = normalize_value(level.get("id"))
    points: list[dict[str, object]] = []
    loaded_chunks = 0
    for chunk in chunks:
        path = safe_chunk_path(chunk.get("path"))
        if path is None or not path.exists():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        chunk_points = payload.get("points", [])
        if not isinstance(chunk_points, list):
            continue
        for point in chunk_points:
            if not isinstance(point, dict):
                continue
            point_bounds = bbox_from_payload(point.get("bbox", {})) or bounds
            if bbox_intersects(point_bounds, bounds):
                points.append(point)
        loaded_chunks += 1

    total_points = int(level.get("point_count") or len(points))
    return {
        "ok": True,
        "chunked": True,
        "level": level_id,
        "zoom": zoom,
        "bounds": bounds,
        "points": points,
        "loaded_chunks": loaded_chunks,
        "candidate_points": estimate,
        "total_points": total_points,
        "mapped_ip_count": int(manifest.get("mapped_ip_count") or 0),
        "map_point_limit": MAP_CHUNK_RESPONSE_POINT_LIMIT,
    }


def build_map_selection_payload(relative_path: object) -> dict[str, object]:
    path = safe_chunk_path(relative_path)
    if path is None:
        raise ValueError("Invalid map selection path.")
    if not path.exists():
        raise FileNotFoundError(f"Map selection records not found: {relative_path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Map selection records are invalid JSON: {relative_path}") from exc
    if not isinstance(payload, dict):
        raise ValueError("Map selection records must be a JSON object.")
    records = payload.get("records", [])
    if not isinstance(records, list):
        records = []
    return {
        "ok": True,
        "key": normalize_value(payload.get("key", "")),
        "level": normalize_value(payload.get("level", "")),
        "record_count": int(payload.get("record_count") or len(records)),
        "records": [record for record in records if isinstance(record, dict)],
    }


def file_signature(paths: list[Path]) -> tuple[tuple[str, int, int], ...]:
    return tuple((str(path), path.stat().st_size, path.stat().st_mtime_ns) for path in paths)


def normalize_value(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return "; ".join(normalize_value(item) for item in value if normalize_value(item))
    return str(value)


def join_values(value: object) -> str:
    if isinstance(value, list):
        return "; ".join(normalize_value(item) for item in value if normalize_value(item))
    return normalize_value(value)


def normalize_row(row: dict[str, object]) -> dict[str, str]:
    normalized = {key: normalize_value(value) for key, value in row.items() if key}
    return normalize_legacy_shifted_runbook_row(normalized)


def normalize_legacy_shifted_runbook_row(row: dict[str, str]) -> dict[str, str]:
    """Repair rows appended by older scanners before long/lat were present."""
    if not row.get("long") and not row.get("lat") and row.get("host") in {"open-service", "error", "dry-run-planned"}:
        return {
            **row,
            "host": row.get("target", "") if row.get("host") != "error" else "",
            "host_status": "up" if row.get("host") == "open-service" else "",
            "scan_status": row.get("host", ""),
            "port": row.get("host_status", ""),
            "protocol": row.get("scan_status", ""),
            "service_name": row.get("port", ""),
            "product": row.get("protocol", ""),
            "version": row.get("service_name", ""),
            "extrainfo": row.get("product", ""),
            "cpe": row.get("version", ""),
            "error": row.get("extrainfo", ""),
        }

    if not row.get("long") or not row.get("lat"):
        return row
    if not as_ip(row.get("long")):
        return row
    if row.get("host") not in {"open-service", "error", "dry-run-planned"}:
        return row

    return {
        **row,
        "long": "",
        "lat": "",
        "host": row.get("long", ""),
        "host_status": row.get("lat", ""),
        "scan_status": row.get("host", ""),
        "port": row.get("host_status", ""),
        "protocol": row.get("scan_status", ""),
        "service_name": row.get("port", ""),
        "product": row.get("protocol", ""),
        "version": row.get("service_name", ""),
        "extrainfo": row.get("product", ""),
        "cpe": row.get("version", ""),
        "error": row.get("extrainfo", ""),
    }


def as_ip(value: object) -> str:
    text = normalize_value(value).strip()
    if not text:
        return ""
    try:
        return ipaddress.ip_address(text).compressed
    except ValueError:
        return ""


def parse_float(value: object) -> float | None:
    text = normalize_value(value).strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def first_value(row: dict[str, str], fields: tuple[str, ...]) -> str:
    for field in fields:
        value = row.get(field, "")
        if value:
            return value
    return ""


def row_ip(row: dict[str, str]) -> str:
    for field in ("host", "target", "ip", "address"):
        ip = as_ip(row.get(field))
        if ip:
            return ip
    return ""


def row_coordinates(row: dict[str, str]) -> tuple[float, float, str, str] | None:
    lat_text = first_value(row, ("lat", "latitude"))
    long_text = first_value(row, ("long", "longitude", "lon"))
    latitude = parse_float(lat_text)
    longitude = parse_float(long_text)
    if latitude is None or longitude is None:
        return None
    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        return None
    return latitude, longitude, lat_text, long_text


def append_unique(values: list[str], value: str) -> None:
    if value and value not in values:
        values.append(value)


def row_sortable_time(row: dict[str, str]) -> str:
    return row.get("looked_up_at", "")


def build_runbook_ip_summary(rows: list[dict[str, str]]) -> dict[str, dict[str, object]]:
    summaries: dict[str, dict[str, object]] = {}
    for row in rows:
        ip = row_ip(row)
        if not ip:
            continue
        summary = summaries.setdefault(
            ip,
            {
                "row_count": 0,
                "open_service_count": 0,
                "labels": [],
                "ports": [],
                "services": [],
                "scan_statuses": [],
                "errors": [],
            },
        )
        summary["row_count"] = int(summary["row_count"]) + 1
        if row.get("scan_status") == "open-service":
            summary["open_service_count"] = int(summary["open_service_count"]) + 1
        labels = summary["labels"]
        ports = summary["ports"]
        services = summary["services"]
        statuses = summary["scan_statuses"]
        errors = summary["errors"]
        assert isinstance(labels, list)
        assert isinstance(ports, list)
        assert isinstance(services, list)
        assert isinstance(statuses, list)
        assert isinstance(errors, list)
        append_unique(labels, row.get("target_label", ""))
        port_label = " ".join(
            part
            for part in (
                row.get("protocol", ""),
                row.get("port", ""),
                row.get("service_name", ""),
            )
            if part
        )
        append_unique(ports, port_label)
        append_unique(services, row.get("service_name", ""))
        append_unique(statuses, row.get("scan_status", ""))
        append_unique(errors, row.get("error", ""))
    return summaries


def coordinate_record_for_ip(
    ip: str,
    lookup_row: dict[str, str],
    cache_row: dict[str, str],
    runbook_summary: dict[str, object],
) -> dict[str, object]:
    fields = (
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
    )
    merged = {
        field: cache_row.get(field) or lookup_row.get(field, "")
        for field in fields
    }
    merged["ip"] = ip
    merged["runbook_row_count"] = runbook_summary.get("row_count", 0)
    merged["open_service_count"] = runbook_summary.get("open_service_count", 0)
    merged["ports"] = runbook_summary.get("ports", [])
    merged["services"] = runbook_summary.get("services", [])
    merged["scan_statuses"] = runbook_summary.get("scan_statuses", [])
    return merged


def build_map_points(
    rows: list[dict[str, str]],
    limit: int | None = MAP_POINT_LIMIT,
    include_records: bool = False,
) -> tuple[list[dict[str, object]], int, int]:
    if not rows:
        return [], 0, 0

    runbook_summaries = build_runbook_ip_summary(rows)
    if not runbook_summaries:
        return [], 0, 0
    matching_ips = set(runbook_summaries)
    coordinate_records = get_coordinate_records_for_ips(matching_ips)
    lookup_rows_by_ip = coordinate_records["lookup_rows_by_ip"]  # type: ignore[assignment]
    cache_rows = coordinate_records["cache_rows_by_ip"]  # type: ignore[assignment]
    assert isinstance(lookup_rows_by_ip, dict)
    assert isinstance(cache_rows, dict)

    latest_lookup_by_ip: dict[str, dict[str, str]] = {}
    for ip, row in lookup_rows_by_ip.items():
        ip = as_ip(ip)
        assert isinstance(row, dict)
        if not ip:
            continue
        if row_coordinates(row) is None:
            continue
        latest_lookup_by_ip[ip] = row
    for ip in matching_ips:
        if ip in latest_lookup_by_ip:
            continue
        cache_row = cache_rows.get(ip, {})
        if not isinstance(cache_row, dict) or row_coordinates(cache_row) is None:
            continue
        latest_lookup_by_ip[ip] = {str(key): normalize_value(value) for key, value in cache_row.items()}

    grouped: dict[tuple[float, float], dict[str, object]] = {}
    mapped_ip_count = 0
    for ip, lookup_row in latest_lookup_by_ip.items():
        coordinates = row_coordinates(lookup_row)
        if coordinates is None:
            continue
        latitude, longitude, lat_text, long_text = coordinates
        cache_row = cache_rows.get(ip, {})
        if not isinstance(cache_row, dict):
            cache_row = {}
        cache_record = {str(key): normalize_value(value) for key, value in cache_row.items()}
        runbook_summary = runbook_summaries.get(ip, {})
        point = grouped.setdefault(
            (latitude, longitude),
            {
                "key": f"{latitude:.6f},{longitude:.6f}",
                "lat": latitude,
                "long": longitude,
                "lat_text": lat_text,
                "long_text": long_text,
                "ip_count": 0,
                "ips": [],
                "row_count": 0,
                "open_service_count": 0,
                "ports": [],
                "services": [],
                "scan_statuses": [],
            },
        )
        if include_records and "cache_records" not in point:
            point["cache_records"] = []
        point["ip_count"] = int(point["ip_count"]) + 1
        point["row_count"] = int(point["row_count"]) + int(runbook_summary.get("row_count", 0) or 0)
        point["open_service_count"] = int(point["open_service_count"]) + int(
            runbook_summary.get("open_service_count", 0) or 0
        )
        ips = point["ips"]
        ports = point["ports"]
        services = point["services"]
        statuses = point["scan_statuses"]
        assert isinstance(ips, list)
        assert isinstance(ports, list)
        assert isinstance(services, list)
        assert isinstance(statuses, list)
        append_unique(ips, ip)
        for port in runbook_summary.get("ports", []):
            append_unique(ports, normalize_value(port))
        for service in runbook_summary.get("services", []):
            append_unique(services, normalize_value(service))
        for status in runbook_summary.get("scan_statuses", []):
            append_unique(statuses, normalize_value(status))
        for field in ("city", "region", "country", "org", "asn", "coordinate_provider", "coordinate_status"):
            if not point.get(field):
                point[field] = normalize_value(cache_record.get(field) or lookup_row.get(field, ""))
        if include_records:
            cache_records = point["cache_records"]
            assert isinstance(cache_records, list)
            cache_records.append(coordinate_record_for_ip(ip, lookup_row, cache_record, runbook_summary))
        mapped_ip_count += 1

    points = sorted(
        grouped.values(),
        key=lambda point: (
            normalize_value(point.get("country")),
            normalize_value(point.get("region")),
            normalize_value(point.get("key")),
        ),
    )
    total_points = len(points)
    for point in points:
        records = point.get("cache_records", [])
        assert isinstance(records, list)
        records.sort(key=lambda item: normalize_value(item.get("ip") if isinstance(item, dict) else ""))
        first_record = records[0] if records and isinstance(records[0], dict) else {}
        if first_record:
            for field in ("city", "region", "country", "org", "asn", "coordinate_provider", "coordinate_status"):
                point[field] = normalize_value(first_record.get(field, ""))
    if limit is None:
        return points, total_points, mapped_ip_count
    return points[:limit], total_points, mapped_ip_count


def add_header(headers: list[str], field: str) -> None:
    if field and field not in headers:
        headers.append(field)


def load_csv_rows(paths: list[Path]) -> tuple[list[dict[str, str]], list[str]]:
    rows: list[dict[str, str]] = []
    headers: list[str] = []

    for path in paths:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            for field in reader.fieldnames or []:
                add_header(headers, field)

            for row in reader:
                normalized = normalize_row(row)
                for field in normalized:
                    add_header(headers, field)
                rows.append(normalized)

    return rows, headers


def load_jsonl_rows(paths: list[Path]) -> tuple[list[dict[str, str]], list[str]]:
    rows: list[dict[str, str]] = []
    headers: list[str] = []

    for path in paths:
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
                normalized = {key: normalize_value(value) for key, value in payload.items()}
                for field in normalized:
                    add_header(headers, field)
                rows.append(normalized)

    return rows, headers


def get_dataset() -> dict[str, object]:
    source_format, paths = source_files()
    signature = (source_format, file_signature(paths))

    if _DATA_CACHE["signature"] == signature:
        return _DATA_CACHE

    if not paths:
        _DATA_CACHE.update(
            {
                "signature": signature,
                "rows": [],
                "headers": [],
                "shards": [],
                "source_format": source_format,
            }
        )
        return _DATA_CACHE

    if source_format == "csv":
        rows, headers = load_csv_rows(paths)
    else:
        rows, headers = load_jsonl_rows(paths)

    _DATA_CACHE.update(
        {
            "signature": signature,
            "rows": rows,
            "headers": headers,
            "shards": [
                {
                    "name": path.name,
                    "relative_path": str(path.relative_to(ROOT)),
                    "bytes": path.stat().st_size,
                }
                for path in paths
            ],
            "source_format": source_format,
        }
    )
    return _DATA_CACHE


def coordinate_lookup_csv_path() -> Path:
    for path in COORDINATE_LOOKUPS_CSV_ALIASES:
        if path.exists():
            return path
    return COORDINATE_LOOKUPS_CSV


def coordinate_cache_paths() -> list[Path]:
    shard_paths = (
        sorted(
            path
            for path in COORDINATE_CACHE_DIR.glob(COORDINATE_CACHE_SHARD_GLOB)
            if re.fullmatch(r"ip-coordinate-cache-[0-9a-f]{2}\.json", path.name)
        )
        if COORDINATE_CACHE_DIR.exists()
        else []
    )
    if shard_paths:
        return shard_paths
    legacy_paths = [
        COORDINATE_CACHE_DIR / "ip-coordinate-cache.json",
        LEGACY_COORDINATE_CACHE_JSON,
    ]
    return [path for path in legacy_paths if path.exists()]


def coordinate_source_paths() -> list[Path]:
    lookup_path = coordinate_lookup_csv_path()
    paths = [lookup_path] if lookup_path.exists() else []
    paths.extend(coordinate_cache_paths())
    return paths


def coordinate_source_signature() -> tuple[str, tuple[tuple[str, int, int], ...]]:
    lookup_path = coordinate_lookup_csv_path()
    return str(lookup_path), file_signature(coordinate_source_paths())


def coordinate_source_files_payload(paths: list[Path]) -> list[dict[str, object]]:
    return [
        {
            "name": path.name,
            "relative_path": str(path.relative_to(ROOT)),
            "bytes": path.stat().st_size,
        }
        for path in paths
    ]


def coordinate_cache_shard_id(ip: str) -> str:
    return hashlib.sha256(ip.encode("ascii")).hexdigest()[:2]


def coordinate_cache_path_for_ip(ip: str) -> Path:
    return COORDINATE_CACHE_DIR / f"ip-coordinate-cache-{coordinate_cache_shard_id(ip)}.json"


def raw_field(row: list[str], index: int | None) -> str:
    if index is None or index >= len(row):
        return ""
    return row[index]


def row_has_valid_coordinates(row: list[str], lat_index: int | None, long_index: int | None) -> bool:
    try:
        latitude = float(raw_field(row, lat_index))
        longitude = float(raw_field(row, long_index))
    except ValueError:
        return False
    return -90 <= latitude <= 90 and -180 <= longitude <= 180


def normalize_csv_row(headers: list[str], row: list[str]) -> dict[str, str]:
    return normalize_row({field: row[index] if index < len(row) else "" for index, field in enumerate(headers)})


def scan_coordinate_lookup_csv(
    path: Path,
    target_ips: set[str] | None = None,
) -> tuple[dict[str, dict[str, str]], int, int, int]:
    if not path.exists():
        return {}, 0, 0, 0

    lookup_rows_by_ip: dict[str, dict[str, str]] = {}
    row_count = 0
    ok_count = 0
    error_count = 0
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle)
        headers = next(reader, [])
        indexes = {field: index for index, field in enumerate(headers)}
        ip_index = indexes.get("ip")
        lat_index = indexes.get("lat")
        long_index = indexes.get("long")
        status_index = indexes.get("coordinate_status")

        for row in reader:
            row_count += 1
            if row_has_valid_coordinates(row, lat_index, long_index):
                ok_count += 1
            else:
                status = raw_field(row, status_index)
                if status and status not in {"skipped-provider-none", "cached"}:
                    error_count += 1

            if target_ips is None:
                continue

            raw_ip = raw_field(row, ip_index).strip()
            ip = raw_ip if raw_ip in target_ips else as_ip(raw_ip)
            if ip and ip in target_ips:
                lookup_rows_by_ip[ip] = normalize_csv_row(headers, row)

    return lookup_rows_by_ip, row_count, ok_count, error_count


def load_coordinate_cache_file(path: Path, target_ips: set[str] | None = None) -> dict[str, dict[str, str]]:
    rows: dict[str, dict[str, str]] = {}
    if not path.exists():
        return rows

    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        return rows

    for key, value in payload.items():
        ip = as_ip(key)
        if not ip or not isinstance(value, dict):
            continue
        if target_ips is not None and ip not in target_ips:
            continue
        rows[ip] = normalize_row(value)
    return rows


def load_coordinate_cache_rows_for_ips(ips: set[str]) -> dict[str, dict[str, str]]:
    rows: dict[str, dict[str, str]] = {}
    if not ips:
        return rows

    if COORDINATE_CACHE_DIR.exists():
        paths = sorted({coordinate_cache_path_for_ip(ip) for ip in ips}, key=str)
    else:
        paths = [
            path
            for path in (COORDINATE_CACHE_DIR / "ip-coordinate-cache.json", LEGACY_COORDINATE_CACHE_JSON)
            if path.exists()
        ]

    for path in paths:
        rows.update(load_coordinate_cache_file(path, ips))
    return rows


def get_coordinate_dataset() -> dict[str, object]:
    paths = coordinate_source_paths()
    signature = coordinate_source_signature()
    if _COORDINATE_CACHE["signature"] == signature:
        return _COORDINATE_CACHE

    _lookup_rows, lookup_row_count, ok_count, error_count = scan_coordinate_lookup_csv(coordinate_lookup_csv_path())

    _COORDINATE_CACHE.update(
        {
            "signature": signature,
            "source_files": coordinate_source_files_payload(paths),
            "lookup_row_count": lookup_row_count,
            "lookup_error_count": error_count,
            "lookup_ok_count": ok_count,
        }
    )
    return _COORDINATE_CACHE


def get_coordinate_records_for_ips(ips: set[str]) -> dict[str, object]:
    source_signature = coordinate_source_signature()
    signature = (source_signature, tuple(sorted(ips)))
    if _COORDINATE_RECORD_CACHE["signature"] == signature:
        return _COORDINATE_RECORD_CACHE

    cached_ips = _COORDINATE_RECORD_CACHE.get("ips", set())
    if (
        _COORDINATE_RECORD_CACHE.get("source_signature") == source_signature
        and isinstance(cached_ips, set)
        and ips.issubset(cached_ips)
    ):
        cached_lookup_rows = _COORDINATE_RECORD_CACHE.get("lookup_rows_by_ip", {})
        cached_cache_rows = _COORDINATE_RECORD_CACHE.get("cache_rows_by_ip", {})
        assert isinstance(cached_lookup_rows, dict)
        assert isinstance(cached_cache_rows, dict)
        return {
            "signature": signature,
            "source_signature": source_signature,
            "ips": ips,
            "lookup_rows_by_ip": {ip: cached_lookup_rows[ip] for ip in ips if ip in cached_lookup_rows},
            "cache_rows_by_ip": {ip: cached_cache_rows[ip] for ip in ips if ip in cached_cache_rows},
        }

    lookup_rows_by_ip, lookup_row_count, ok_count, error_count = scan_coordinate_lookup_csv(
        coordinate_lookup_csv_path(),
        ips,
    )
    missing_ips = {ip for ip in ips if ip not in lookup_rows_by_ip}
    cache_rows_by_ip = load_coordinate_cache_rows_for_ips(missing_ips)

    _COORDINATE_RECORD_CACHE.update(
        {
            "signature": signature,
            "source_signature": source_signature,
            "ips": set(ips),
            "lookup_rows_by_ip": lookup_rows_by_ip,
            "cache_rows_by_ip": cache_rows_by_ip,
        }
    )
    _COORDINATE_CACHE.update(
        {
            "signature": coordinate_source_signature(),
            "source_files": coordinate_source_files_payload(coordinate_source_paths()),
            "lookup_row_count": lookup_row_count,
            "lookup_error_count": error_count,
            "lookup_ok_count": ok_count,
        }
    )
    return _COORDINATE_RECORD_CACHE


def build_hierarchy(headers: list[str]) -> list[str]:
    ordered = [field for field in PREFERRED_HIERARCHY if field in headers]
    ordered.extend(field for field in headers if field not in ordered)
    return ordered


def parse_filters(raw_value: str | None) -> dict[str, str]:
    if not raw_value:
        return {}
    try:
        payload = json.loads(raw_value)
    except json.JSONDecodeError:
        return {}
    if not isinstance(payload, dict):
        return {}
    return {
        str(key): normalize_value(value)
        for key, value in payload.items()
        if str(key)
    }


def parse_geo_filter(raw_value: object) -> dict[str, object]:
    if not raw_value:
        return {}

    payload: object = raw_value
    if isinstance(raw_value, str):
        try:
            payload = json.loads(raw_value)
        except json.JSONDecodeError:
            return {}

    if not isinstance(payload, dict):
        return {}

    ips: list[str] = []
    for value in payload.get("ips", []):
        ip = as_ip(value)
        if ip and ip not in ips:
            ips.append(ip)

    key = normalize_value(payload.get("key")).strip()
    label = normalize_value(payload.get("label")).strip()
    bbox = bbox_from_payload(payload.get("bbox", {}))
    level = normalize_value(payload.get("level")).strip()
    if not key and not ips and not bbox:
        return {}

    result: dict[str, object] = {
        "key": key,
        "label": label,
        "ips": ips,
    }
    if bbox:
        result["bbox"] = bbox
    if level:
        result["level"] = level
    return result


def parse_positive_int(value: object, default: int, maximum: int) -> int:
    try:
        parsed = int(normalize_value(value))
    except ValueError:
        return default
    return min(maximum, max(0, parsed))


def row_matches(row: dict[str, str], filters: dict[str, str]) -> bool:
    return all(row.get(field, "") == value for field, value in filters.items())


def row_matches_text(row: dict[str, str], headers: list[str], search: str) -> bool:
    needle = search.strip().casefold()
    if not needle:
        return True
    return any(needle in normalize_value(row.get(field, "")).casefold() for field in headers)


def known_ips(rows: list[dict[str, str]]) -> set[str]:
    return {ip for row in rows if (ip := row_ip(row))}


def prefix_filters(field: str, hierarchy: list[str], filters: dict[str, str]) -> dict[str, str]:
    if field not in hierarchy:
        return dict(filters)
    selected: dict[str, str] = {}
    for current_field in hierarchy:
        if current_field == field:
            break
        if current_field in filters:
            selected[current_field] = filters[current_field]
    return selected


def resolve_geo_filter(rows: list[dict[str, str]], geo_filter: dict[str, object]) -> dict[str, object]:
    if not geo_filter:
        return {}

    ips = [as_ip(value) for value in geo_filter.get("ips", []) if as_ip(value)]
    key = normalize_value(geo_filter.get("key")).strip()
    label = normalize_value(geo_filter.get("label")).strip()
    bbox = bbox_from_payload(geo_filter.get("bbox", {}))
    level = normalize_value(geo_filter.get("level")).strip()

    if bbox:
        unique_ips: list[str] = []
        for ip in ips:
            if ip and ip not in unique_ips:
                unique_ips.append(ip)
        result: dict[str, object] = {
            "key": key,
            "label": label or key,
            "ips": unique_ips,
            "bbox": bbox,
        }
        if level:
            result["level"] = level
        return result

    if not ips and key:
        map_points, _point_count, _mapped_ip_count = build_map_points(rows, limit=None)
        for point in map_points:
            if normalize_value(point.get("key")) != key:
                continue
            point_ips = point.get("ips", [])
            if isinstance(point_ips, list):
                ips = [as_ip(value) for value in point_ips if as_ip(value)]
            if not label:
                label = ", ".join(
                    value
                    for value in (
                        normalize_value(point.get("city")),
                        normalize_value(point.get("region")),
                        normalize_value(point.get("country")),
                    )
                    if value
                )
            break

    unique_ips: list[str] = []
    for ip in ips:
        if ip and ip not in unique_ips:
            unique_ips.append(ip)

    if not unique_ips:
        return {}

    return {
        "key": key,
        "label": label,
        "ips": unique_ips,
    }


def ips_within_bbox(rows: list[dict[str, str]], bounds: dict[str, float]) -> set[str]:
    row_ips = {row_ip(row) for row in rows if row_ip(row)}
    if not row_ips:
        return set()
    coordinate_records = get_coordinate_records_for_ips(row_ips)
    lookup_rows_by_ip = coordinate_records["lookup_rows_by_ip"]  # type: ignore[assignment]
    cache_rows_by_ip = coordinate_records["cache_rows_by_ip"]  # type: ignore[assignment]
    assert isinstance(lookup_rows_by_ip, dict)
    assert isinstance(cache_rows_by_ip, dict)

    allowed: set[str] = set()
    for ip in row_ips:
        row = lookup_rows_by_ip.get(ip) or cache_rows_by_ip.get(ip) or {}
        if not isinstance(row, dict):
            continue
        coordinates = row_coordinates({str(key): normalize_value(value) for key, value in row.items()})
        if coordinates is None:
            continue
        latitude, longitude, _lat_text, _long_text = coordinates
        if bbox_contains_coordinates(bounds, latitude, longitude):
            allowed.add(ip)
    return allowed


def apply_geo_filter(rows: list[dict[str, str]], geo_filter: dict[str, object]) -> list[dict[str, str]]:
    if not geo_filter:
        return rows
    ips = {as_ip(value) for value in geo_filter.get("ips", []) if as_ip(value)}
    bbox = bbox_from_payload(geo_filter.get("bbox", {}))
    if bbox:
        bbox_ips = ips_within_bbox(rows, bbox)
        ips = ips.intersection(bbox_ips) if ips else bbox_ips
    if not ips:
        return []
    return [row for row in rows if row_ip(row) in ips]


def option_sort_key(item: tuple[str, int]) -> tuple[int, int, object, str]:
    value, _count = item
    if value == "":
        return (1, 1, "", value)
    if re.fullmatch(r"\d+", value):
        return (0, 0, int(value), value)
    return (0, 1, value.casefold(), value)


def build_field_options(
    rows: list[dict[str, str]],
    field: str,
    filters: dict[str, str],
    hierarchy: list[str],
    limit: int | None = OPTION_PAGE_SIZE,
    offset: int = 0,
    search: str = "",
) -> dict[str, object]:
    active_filters = prefix_filters(field, hierarchy, filters)
    row_counter: Counter[str] = Counter()
    ip_counter: dict[str, set[str]] = {}
    matched_rows = 0
    matched_ips: set[str] = set()

    for row in rows:
        if row_matches(row, active_filters):
            matched_rows += 1
            ip = row_ip(row)
            if ip:
                matched_ips.add(ip)
            value = row.get(field, "")
            row_counter[value] += 1
            if ip:
                ip_counter.setdefault(value, set()).add(ip)

    items = sorted(row_counter.items(), key=option_sort_key)
    if search.strip():
        needle = search.strip().casefold()
        items = [
            item
            for item in items
            if needle in item[0].casefold() or (item[0] == "" and needle in "(blank)")
        ]

    total_options = len(items)
    offset = min(max(0, offset), total_options)
    truncated = bool(limit is not None and offset + limit < total_options)
    if limit is not None:
        items = items[offset : offset + limit]

    return {
        "field": field,
        "active_filters": active_filters,
        "matched_rows": matched_rows,
        "matched_ip_count": len(matched_ips),
        "total_options": total_options,
        "unsearched_total_options": len(row_counter),
        "offset": offset,
        "limit": limit,
        "has_more": truncated,
        "search": search,
        "truncated": truncated,
        "options": [
            {
                "value": value,
                "count": len(ip_counter.get(value, set())) or row_count,
                "ip_count": len(ip_counter.get(value, set())),
                "row_count": row_count,
            }
            for value, row_count in items
        ],
    }


def build_view(filters: dict[str, str], geo_filter: dict[str, object] | None = None) -> dict[str, object]:
    dataset = get_dataset()
    rows = dataset["rows"]  # type: ignore[assignment]
    headers = dataset["headers"]  # type: ignore[assignment]
    assert isinstance(rows, list)
    assert isinstance(headers, list)

    hierarchy = build_hierarchy(headers)
    valid_filters = {field: value for field, value in filters.items() if field in headers}
    resolved_geo_filter = resolve_geo_filter(rows, geo_filter or {})
    geo_rows = apply_geo_filter(rows, resolved_geo_filter)
    matching_rows = [row for row in geo_rows if row_matches(row, valid_filters)]
    known_ip_count = len(known_ips(rows))
    matching_known_ip_count = len(known_ips(matching_rows))
    chunk_manifest = map_chunk_manifest()
    if organized_map_available():
        map_points = []
        map_point_count, mapped_ip_count = organized_map_counts(chunk_manifest)
        map_chunked = True
    else:
        map_points, map_point_count, mapped_ip_count = build_map_points(rows)
        map_chunked = False
    if resolved_geo_filter and not map_chunked:
        refined_map_points, refined_map_point_count, refined_mapped_ip_count = build_map_points(
            matching_rows,
            include_records=True,
        )
    else:
        refined_map_points = []
        refined_map_point_count = 0
        refined_mapped_ip_count = 0
    coordinate_dataset = get_coordinate_dataset()

    return {
        "source_format": dataset["source_format"],
        "shards": dataset["shards"],
        "headers": headers,
        "hierarchy": hierarchy,
        "filters": valid_filters,
        "geo_filter": resolved_geo_filter,
        "total_rows": len(rows),
        "matching_count": len(matching_rows),
        "known_ip_count": known_ip_count,
        "matching_known_ip_count": matching_known_ip_count,
        "row_page_size": ROW_PAGE_SIZE,
        "rows": matching_rows[:ROW_PAGE_SIZE],
        "rows_has_more": len(matching_rows) > ROW_PAGE_SIZE,
        "map_points": map_points,
        "map_point_count": map_point_count,
        "mapped_ip_count": mapped_ip_count,
        "map_point_limit": MAP_POINT_LIMIT,
        "map_chunked": map_chunked,
        "refined_map_points": refined_map_points,
        "refined_map_point_count": refined_map_point_count,
        "refined_mapped_ip_count": refined_mapped_ip_count,
        "coordinate_lookup_count": coordinate_dataset["lookup_row_count"],
        "coordinate_lookup_ok_count": coordinate_dataset["lookup_ok_count"],
        "coordinate_lookup_error_count": coordinate_dataset["lookup_error_count"],
        "coordinate_sources": coordinate_dataset["source_files"],
        "columns": [
            build_field_options(geo_rows, field, valid_filters, hierarchy, OPTION_PAGE_SIZE)
            for field in hierarchy
        ],
    }


def build_options_page(
    field: str,
    filters: dict[str, str],
    geo_filter: dict[str, object],
    search: str,
    offset: int,
    limit: int,
) -> dict[str, object]:
    dataset = get_dataset()
    rows = dataset["rows"]  # type: ignore[assignment]
    headers = dataset["headers"]  # type: ignore[assignment]
    assert isinstance(rows, list)
    assert isinstance(headers, list)

    hierarchy = build_hierarchy(headers)
    if field not in hierarchy:
        raise ValueError(f"Unknown field: {field}")

    valid_filters = {filter_field: value for filter_field, value in filters.items() if filter_field in headers}
    resolved_geo_filter = resolve_geo_filter(rows, geo_filter)
    geo_rows = apply_geo_filter(rows, resolved_geo_filter)
    result = build_field_options(geo_rows, field, valid_filters, hierarchy, limit, offset, search)
    result["geo_filter"] = resolved_geo_filter
    return result


def build_rows_page(
    filters: dict[str, str],
    geo_filter: dict[str, object],
    search: str,
    offset: int,
    limit: int,
) -> dict[str, object]:
    dataset = get_dataset()
    rows = dataset["rows"]  # type: ignore[assignment]
    headers = dataset["headers"]  # type: ignore[assignment]
    assert isinstance(rows, list)
    assert isinstance(headers, list)

    valid_filters = {field: value for field, value in filters.items() if field in headers}
    resolved_geo_filter = resolve_geo_filter(rows, geo_filter)
    geo_rows = apply_geo_filter(rows, resolved_geo_filter)
    matching_rows = [row for row in geo_rows if row_matches(row, valid_filters)]
    searched_rows = [row for row in matching_rows if row_matches_text(row, headers, search)]
    total_rows = len(searched_rows)
    offset = min(max(0, offset), total_rows)
    page_rows = searched_rows[offset : offset + limit]

    return {
        "ok": True,
        "headers": headers,
        "filters": valid_filters,
        "geo_filter": resolved_geo_filter,
        "search": search,
        "offset": offset,
        "limit": limit,
        "matching_count": len(matching_rows),
        "matching_known_ip_count": len(known_ips(matching_rows)),
        "total_rows": total_rows,
        "rows": page_rows,
        "has_more": offset + len(page_rows) < total_rows,
    }


def safe_filename_part(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip())
    return cleaned.strip("-") or "blank"


def write_column_export(field: str, filters: dict[str, str], geo_filter: dict[str, object]) -> dict[str, object]:
    dataset = get_dataset()
    rows = dataset["rows"]  # type: ignore[assignment]
    headers = dataset["headers"]  # type: ignore[assignment]
    assert isinstance(rows, list)
    assert isinstance(headers, list)

    hierarchy = build_hierarchy(headers)
    if field not in hierarchy:
        raise ValueError(f"Unknown field: {field}")

    QUICK_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    resolved_geo_filter = resolve_geo_filter(rows, geo_filter)
    geo_rows = apply_geo_filter(rows, resolved_geo_filter)
    valid_filters = {filter_field: value for filter_field, value in filters.items() if filter_field in headers}
    column = build_field_options(geo_rows, field, valid_filters, hierarchy, limit=None)
    timestamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    output_path = QUICK_OUTPUT_DIR / f"{timestamp}-{safe_filename_part(field)}-column.csv"
    active_filters = column["active_filters"]
    assert isinstance(active_filters, dict)

    filter_label = "; ".join(f"{key}={value}" for key, value in active_filters.items())
    geo_label = normalize_value(resolved_geo_filter.get("label") or resolved_geo_filter.get("key"))

    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "field",
                "value",
                "count",
                "active_filters",
                "geo_filter",
                "source_format",
                "source_shards",
                "exported_at",
            ],
        )
        writer.writeheader()
        for option in column["options"]:
            writer.writerow(
                {
                    "field": field,
                    "value": option["value"],
                    "count": option["count"],
                    "active_filters": filter_label,
                    "geo_filter": geo_label,
                    "source_format": dataset["source_format"],
                    "source_shards": "; ".join(shard["name"] for shard in dataset["shards"]),  # type: ignore[index]
                    "exported_at": timestamp,
                }
            )

    return {
        "ok": True,
        "field": field,
        "path": str(output_path.relative_to(ROOT)),
        "rows_written": len(column["options"]),
    }


def write_rows_export(filters: dict[str, str], geo_filter: dict[str, object]) -> dict[str, object]:
    dataset = get_dataset()
    rows = dataset["rows"]  # type: ignore[assignment]
    headers = dataset["headers"]  # type: ignore[assignment]
    assert isinstance(rows, list)
    assert isinstance(headers, list)

    valid_filters = {field: value for field, value in filters.items() if field in headers}
    resolved_geo_filter = resolve_geo_filter(rows, geo_filter)
    geo_rows = apply_geo_filter(rows, resolved_geo_filter)
    matching_rows = [row for row in geo_rows if row_matches(row, valid_filters)]
    QUICK_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    output_path = QUICK_OUTPUT_DIR / f"{timestamp}-matching-rows.csv"

    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers)
        writer.writeheader()
        for row in matching_rows:
            writer.writerow({field: row.get(field, "") for field in headers})

    return {
        "ok": True,
        "path": str(output_path.relative_to(ROOT)),
        "rows_written": len(matching_rows),
    }


def write_mapped_ips_export(filters: dict[str, str], geo_filter: dict[str, object]) -> dict[str, object]:
    dataset = get_dataset()
    rows = dataset["rows"]  # type: ignore[assignment]
    headers = dataset["headers"]  # type: ignore[assignment]
    assert isinstance(rows, list)
    assert isinstance(headers, list)

    valid_filters = {field: value for field, value in filters.items() if field in headers}
    resolved_geo_filter = resolve_geo_filter(rows, geo_filter)
    geo_rows = apply_geo_filter(rows, resolved_geo_filter)
    matching_rows = [row for row in geo_rows if row_matches(row, valid_filters)]
    map_points, _point_count, _mapped_ip_count = build_map_points(
        matching_rows,
        limit=None,
        include_records=True,
    )

    QUICK_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    output_path = QUICK_OUTPUT_DIR / f"{timestamp}-mapped-ips.csv"
    filter_label = "; ".join(f"{key}={value}" for key, value in valid_filters.items())
    geo_label = normalize_value(resolved_geo_filter.get("label") or resolved_geo_filter.get("key"))

    fieldnames = [
        "ip",
        "map_key",
        "long",
        "lat",
        "city",
        "region",
        "country",
        "org",
        "asn",
        "coordinate_provider",
        "coordinate_status",
        "ping_status",
        "runbook_row_count",
        "open_service_count",
        "ports",
        "services",
        "scan_statuses",
        "active_filters",
        "geo_filter",
        "source_format",
        "source_shards",
        "exported_at",
    ]

    rows_written = 0
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for point in map_points:
            records = point.get("cache_records", [])
            if not isinstance(records, list):
                continue
            for record in records:
                if not isinstance(record, dict):
                    continue
                writer.writerow(
                    {
                        "ip": record.get("ip", ""),
                        "map_key": point.get("key", ""),
                        "long": point.get("long_text") or point.get("long", ""),
                        "lat": point.get("lat_text") or point.get("lat", ""),
                        "city": record.get("city") or point.get("city", ""),
                        "region": record.get("region") or point.get("region", ""),
                        "country": record.get("country") or point.get("country", ""),
                        "org": record.get("org", ""),
                        "asn": record.get("asn", ""),
                        "coordinate_provider": record.get("coordinate_provider", ""),
                        "coordinate_status": record.get("coordinate_status", ""),
                        "ping_status": record.get("ping_status", ""),
                        "runbook_row_count": record.get("runbook_row_count", ""),
                        "open_service_count": record.get("open_service_count", ""),
                        "ports": join_values(record.get("ports", [])),
                        "services": join_values(record.get("services", [])),
                        "scan_statuses": join_values(record.get("scan_statuses", [])),
                        "active_filters": filter_label,
                        "geo_filter": geo_label,
                        "source_format": dataset["source_format"],
                        "source_shards": "; ".join(shard["name"] for shard in dataset["shards"]),  # type: ignore[index]
                        "exported_at": timestamp,
                    }
                )
                rows_written += 1

    return {
        "ok": True,
        "path": str(output_path.relative_to(ROOT)),
        "rows_written": rows_written,
    }


class VisualizerHandler(SimpleHTTPRequestHandler):
    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/manifest":
            self.respond_json(self.manifest_payload())
            return
        if parsed.path == "/api/view":
            query = parse_qs(parsed.query)
            filters = parse_filters(query.get("filters", [""])[0])
            geo_filter = parse_geo_filter(query.get("geo_filter", [""])[0])
            self.respond_json(build_view(filters, geo_filter))
            return
        if parsed.path == "/api/map-chunks":
            query = parse_qs(parsed.query)
            try:
                zoom = parse_float_query(query.get("zoom", ["2"])[0], 2.0)
                bounds = normalized_bounds(
                    query.get("north", ["90"])[0],
                    query.get("south", ["-90"])[0],
                    query.get("east", ["180"])[0],
                    query.get("west", ["-180"])[0],
                )
                self.respond_json(build_map_chunks_payload(zoom, bounds))
            except Exception as exc:  # noqa: BLE001 - surfaced to the local UI.
                self.respond_json({"ok": False, "error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            return
        if parsed.path == "/api/map-selection":
            query = parse_qs(parsed.query)
            try:
                self.respond_json(build_map_selection_payload(query.get("path", [""])[0]))
            except Exception as exc:  # noqa: BLE001 - surfaced to the local UI.
                self.respond_json({"ok": False, "error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            return
        if parsed.path == "/api/options":
            query = parse_qs(parsed.query)
            try:
                filters = parse_filters(query.get("filters", [""])[0])
                geo_filter = parse_geo_filter(query.get("geo_filter", [""])[0])
                field = normalize_value(query.get("field", [""])[0])
                search = normalize_value(query.get("search", [""])[0])
                offset = parse_positive_int(query.get("offset", ["0"])[0], 0, 1_000_000)
                limit = parse_positive_int(query.get("limit", [str(OPTION_PAGE_SIZE)])[0], OPTION_PAGE_SIZE, 100_000)
                self.respond_json(build_options_page(field, filters, geo_filter, search, offset, limit))
            except Exception as exc:  # noqa: BLE001 - surfaced to the local UI.
                self.respond_json({"ok": False, "error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            return
        if parsed.path == "/api/rows":
            query = parse_qs(parsed.query)
            try:
                filters = parse_filters(query.get("filters", [""])[0])
                geo_filter = parse_geo_filter(query.get("geo_filter", [""])[0])
                search = normalize_value(query.get("search", [""])[0])
                offset = parse_positive_int(query.get("offset", ["0"])[0], 0, 1_000_000)
                limit = parse_positive_int(query.get("limit", [str(ROW_PAGE_SIZE)])[0], ROW_PAGE_SIZE, 100_000)
                self.respond_json(build_rows_page(filters, geo_filter, search, offset, limit))
            except Exception as exc:  # noqa: BLE001 - surfaced to the local UI.
                self.respond_json({"ok": False, "error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            return
        super().do_GET()

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/refresh":
            try:
                reset_caches()
                self.respond_json({"ok": True, "manifest": self.manifest_payload()})
            except Exception as exc:  # noqa: BLE001 - surfaced to the local UI.
                self.respond_json({"ok": False, "error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            return

        if parsed.path != "/api/export":
            self.send_error(HTTPStatus.NOT_FOUND)
            return

        try:
            payload = self.read_json_body()
            filters = parse_filters(json.dumps(payload.get("filters", {})))
            geo_filter = parse_geo_filter(payload.get("geo_filter", {}))
            export_type = normalize_value(payload.get("type"))
            if export_type == "rows":
                result = write_rows_export(filters, geo_filter)
            elif export_type == "mapped-ips":
                result = write_mapped_ips_export(filters, geo_filter)
            else:
                field = normalize_value(payload.get("field"))
                result = write_column_export(field, filters, geo_filter)
            self.respond_json(result)
        except Exception as exc:  # noqa: BLE001 - surfaced to the local UI.
            self.respond_json({"ok": False, "error": str(exc)}, status=HTTPStatus.BAD_REQUEST)

    def read_json_body(self) -> dict[str, object]:
        length = int(self.headers.get("Content-Length", "0") or 0)
        raw_body = self.rfile.read(length)
        if not raw_body:
            return {}
        payload = json.loads(raw_body.decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("Request body must be a JSON object.")
        return payload

    def manifest_payload(self) -> dict[str, object]:
        dataset = get_dataset()
        headers = dataset["headers"]  # type: ignore[assignment]
        rows = dataset["rows"]  # type: ignore[assignment]
        assert isinstance(headers, list)
        assert isinstance(rows, list)
        chunk_manifest = map_chunk_manifest()
        if organized_map_available():
            map_point_count, mapped_ip_count = organized_map_counts(chunk_manifest)
            map_chunked = True
        else:
            _map_points, map_point_count, mapped_ip_count = build_map_points(rows)
            map_chunked = False
        coordinate_dataset = get_coordinate_dataset()
        return {
            "source_format": dataset["source_format"],
            "shards": dataset["shards"],
            "headers": headers,
            "hierarchy": build_hierarchy(headers),
            "total_rows": len(rows),
            "known_ip_count": len(known_ips(rows)),
            "map_point_count": map_point_count,
            "mapped_ip_count": mapped_ip_count,
            "map_point_limit": MAP_POINT_LIMIT,
            "map_chunked": map_chunked,
            "map_chunk_response_point_limit": MAP_CHUNK_RESPONSE_POINT_LIMIT,
            "coordinate_lookup_count": coordinate_dataset["lookup_row_count"],
            "coordinate_lookup_ok_count": coordinate_dataset["lookup_ok_count"],
            "coordinate_lookup_error_count": coordinate_dataset["lookup_error_count"],
            "coordinate_sources": coordinate_dataset["source_files"],
            "pipeline_progress": pipeline_progress(),
            "output_dir": str(QUICK_OUTPUT_DIR.relative_to(ROOT)),
            "csv_dir": str(CSV_DIR.relative_to(ROOT)),
            "jsonl_dir": str(JSONL_DIR.relative_to(ROOT)),
        }

    def respond_json(self, payload: object, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Serve the cybersecurity runbook visualizer.")
    parser.add_argument("--bind", default="127.0.0.1", help="Host or IP address to bind to.")
    parser.add_argument("--port", type=int, default=8010, help="Port to listen on.")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=RUNBOOK_OUTPUTS_DIR,
        help="Runbook output directory containing csv/, jsonl/, and optional coords/ subdirectories.",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    configure_runbook_outputs(args.output_dir)
    handler = partial(VisualizerHandler, directory=str(VISUALIZER_DIR))
    server = ThreadingHTTPServer((args.bind, args.port), handler)

    print(f"Serving cybersecurity visualizer at http://{args.bind}:{args.port}/")
    print(f"Reading runbook shards from {CSV_DIR}")
    print(f"Writing quick exports to {QUICK_OUTPUT_DIR}")
    print("Press Ctrl+C to stop.")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down server.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
