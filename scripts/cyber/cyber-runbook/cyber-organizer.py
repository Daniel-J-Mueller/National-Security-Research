#!/usr/bin/env python3
"""
Organize cybersecurity runbook outputs for the visualizer.

This no-arg script converges the individual run output directories into
data/private/cybersecurity/group-outputs-main, preserves the original run files
under bulk/, exposes aggregate csv/ and jsonl/ shards for the flow wizard, and
builds multiresolution coordinate chunks for lag-free map loading.
"""

from __future__ import annotations

import csv
from collections import Counter
import hashlib
import ipaddress
import json
import math
import os
import shutil
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[3]
CYBER_DIR = ROOT / "data" / "private" / "cybersecurity"
GROUP_OUTPUT_DIR = CYBER_DIR / "group-outputs-main"

GENERATED_DIRS = [
    "bulk",
    "csv",
    "jsonl",
    "coords",
    "map-chunks",
    "manifest",
]

RUNBOOK_CSV_FIELDS = [
    "target",
    "target_label",
    "host",
    "host_status",
    "scan_status",
    "port",
    "protocol",
    "service_name",
    "product",
    "version",
    "extrainfo",
    "cpe",
    "error",
]

COORDINATE_FIELDS = [
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

MAP_LEVELS = [
    {"id": "z0", "cell_degrees": 20.0, "tile_degrees": 20.0, "split_target_ips": 0},
    {"id": "z1", "cell_degrees": 5.0, "tile_degrees": 10.0, "split_target_ips": 0},
    {"id": "z2", "cell_degrees": 1.0, "tile_degrees": 5.0, "split_target_ips": 100},
    {"id": "z3", "cell_degrees": 0.25, "tile_degrees": 1.0, "split_target_ips": 40},
    {"id": "z4", "cell_degrees": 0.05, "tile_degrees": 0.5, "split_target_ips": 20},
    {"id": "z5", "cell_degrees": 0.01, "tile_degrees": 0.25, "split_target_ips": 10},
]

LIST_FIELD_LIMIT = 24
SAMPLE_IP_LIMIT = 50
MAX_SPLIT_BUCKETS_PER_CELL = 64


@dataclass
class LinkStats:
    linked: int = 0
    copied: int = 0


def utc_timestamp() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def as_ip(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        address = ipaddress.ip_address(text)
    except ValueError:
        return ""
    return address.compressed if isinstance(address, ipaddress.IPv4Address) else ""


def parse_float(value: object) -> float | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def valid_coordinates(row: dict[str, str]) -> tuple[float, float] | None:
    latitude = parse_float(row.get("lat"))
    longitude = parse_float(row.get("long"))
    if latitude is None or longitude is None:
        return None
    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        return None
    return latitude, longitude


def row_ip(row: dict[str, str]) -> str:
    for field in ("host", "target", "ip", "address"):
        ip = as_ip(row.get(field))
        if ip:
            return ip
    return ""


def safe_name(value: str) -> str:
    cleaned = "".join(char if char.isalnum() or char in "._-" else "-" for char in value.strip())
    return cleaned.strip("-") or "run"


def ensure_inside_group(path: Path) -> Path:
    resolved_group = GROUP_OUTPUT_DIR.resolve()
    resolved_path = path.resolve()
    if resolved_path != resolved_group and resolved_group not in resolved_path.parents:
        raise ValueError(f"Refusing to modify path outside group output directory: {resolved_path}")
    return resolved_path


def reset_generated_dirs() -> None:
    GROUP_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for name in GENERATED_DIRS:
        path = ensure_inside_group(GROUP_OUTPUT_DIR / name)
        if path.exists():
            shutil.rmtree(path)
        path.mkdir(parents=True, exist_ok=True)


def has_run_output_data(path: Path) -> bool:
    checks = [
        path / "csv",
        path / "jsonl",
        path / "coords" / "csv",
        path / "coords" / "jsonl",
        path / "coords" / "cache",
    ]
    return any(directory.exists() and any(directory.iterdir()) for directory in checks)


def run_output_dirs() -> list[Path]:
    runs = [
        path
        for path in CYBER_DIR.iterdir()
        if path.is_dir()
        and path.name.startswith("runbook-outputs")
        and path.name != GROUP_OUTPUT_DIR.name
        and has_run_output_data(path)
    ]
    return sorted(runs, key=lambda path: (path.name != "runbook-outputs", path.name))


def link_or_copy(source: Path, destination: Path, stats: LinkStats) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        destination.unlink()
    try:
        os.link(source, destination)
        stats.linked += 1
    except OSError:
        shutil.copy2(source, destination)
        stats.copied += 1


def link_run_files(runs: list[Path]) -> tuple[LinkStats, list[Path], list[Path], list[Path], list[Path]]:
    stats = LinkStats()
    source_csvs: list[Path] = []
    source_jsonls: list[Path] = []
    source_coord_csvs: list[Path] = []
    source_cache_jsons: list[Path] = []

    specs = [
        ("csv", "*.csv", True),
        ("jsonl", "*.jsonl", True),
        ("coords/csv", "*.csv", False),
        ("coords/jsonl", "*.jsonl", False),
        ("coords/cache", "*.json", False),
        ("logs", "*.json", False),
        ("state", "*.json", False),
    ]

    for run in runs:
        run_name = safe_name(run.name)
        for relative_dir, pattern, expose_at_root in specs:
            source_dir = run / relative_dir
            if not source_dir.exists():
                continue
            for source in sorted(source_dir.glob(pattern)):
                if not source.is_file():
                    continue
                bulk_destination = GROUP_OUTPUT_DIR / "bulk" / run_name / relative_dir / source.name
                link_or_copy(source, bulk_destination, stats)

                prefixed_name = f"{run_name}__{source.name}"
                if relative_dir == "csv":
                    source_csvs.append(source)
                elif relative_dir == "jsonl":
                    source_jsonls.append(source)
                elif relative_dir == "coords/csv":
                    source_coord_csvs.append(source)
                elif relative_dir == "coords/cache":
                    source_cache_jsons.append(source)

                if expose_at_root:
                    root_destination = GROUP_OUTPUT_DIR / relative_dir / prefixed_name
                    link_or_copy(source, root_destination, stats)

    return stats, source_csvs, source_jsonls, source_coord_csvs, source_cache_jsons


def append_unique_limited(values: list[str], value: object, limit: int = LIST_FIELD_LIMIT) -> None:
    text = str(value or "").strip()
    if text and text not in values and len(values) < limit:
        values.append(text)


def summarize_runbook_rows(csv_paths: list[Path]) -> dict[str, dict[str, Any]]:
    summaries: dict[str, dict[str, Any]] = {}
    for path in csv_paths:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                ip = row_ip(row)
                if not ip:
                    continue
                summary = summaries.setdefault(
                    ip,
                    {
                        "ip": ip,
                        "row_count": 0,
                        "open_service_count": 0,
                        "target_labels": [],
                        "ports": [],
                        "services": [],
                        "scan_statuses": [],
                    },
                )
                summary["row_count"] += 1
                if row.get("scan_status") == "open-service":
                    summary["open_service_count"] += 1
                append_unique_limited(summary["target_labels"], row.get("target_label") or row.get("target"))
                port_label = " ".join(
                    part
                    for part in (
                        row.get("protocol", ""),
                        row.get("port", ""),
                        row.get("service_name", ""),
                    )
                    if part
                )
                append_unique_limited(summary["ports"], port_label)
                append_unique_limited(summary["services"], row.get("service_name"))
                append_unique_limited(summary["scan_statuses"], row.get("scan_status"))
    return summaries


def coordinate_rank(row: dict[str, str]) -> tuple[int, str]:
    coords = valid_coordinates(row)
    status = str(row.get("coordinate_status") or "").strip()
    quality = 0
    if coords is not None:
        quality += 4
    if status == "ok":
        quality += 2
    if row.get("ping_status") == "up":
        quality += 1
    return quality, str(row.get("looked_up_at") or "")


def normalized_coordinate_row(row: dict[str, object], ip: str) -> dict[str, str]:
    normalized = {field: str(row.get(field, "") or "") for field in COORDINATE_FIELDS}
    normalized["ip"] = ip
    return normalized


def merge_coordinate_csvs(paths: list[Path]) -> dict[str, dict[str, str]]:
    rows_by_ip: dict[str, dict[str, str]] = {}
    for path in paths:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                ip = as_ip(row.get("ip"))
                if not ip:
                    continue
                normalized = normalized_coordinate_row(row, ip)
                current = rows_by_ip.get(ip)
                if current is None or coordinate_rank(normalized) >= coordinate_rank(current):
                    rows_by_ip[ip] = normalized
    return rows_by_ip


def coordinate_cache_shard_id(ip: str) -> str:
    return hashlib.sha256(ip.encode("ascii")).hexdigest()[:2]


def stable_int(value: str) -> int:
    return int(hashlib.sha256(value.encode("utf-8")).hexdigest()[:12], 16)


def merge_coordinate_caches(paths: list[Path], csv_rows_by_ip: dict[str, dict[str, str]]) -> dict[str, dict[str, str]]:
    rows_by_ip = dict(csv_rows_by_ip)
    for path in paths:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        for key, value in payload.items():
            ip = as_ip(key)
            if not ip or not isinstance(value, dict):
                continue
            normalized = normalized_coordinate_row(value, ip)
            current = rows_by_ip.get(ip)
            if current is None or coordinate_rank(normalized) >= coordinate_rank(current):
                rows_by_ip[ip] = normalized
    return rows_by_ip


def write_aggregate_coordinates(rows_by_ip: dict[str, dict[str, str]]) -> None:
    csv_path = GROUP_OUTPUT_DIR / "coords" / "csv" / "ip-coordinate-lookups.csv"
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=COORDINATE_FIELDS, lineterminator="\n")
        writer.writeheader()
        for ip in sorted(rows_by_ip, key=lambda value: int(ipaddress.IPv4Address(value))):
            writer.writerow({field: rows_by_ip[ip].get(field, "") for field in COORDINATE_FIELDS})

    shards: dict[str, dict[str, dict[str, str]]] = {}
    for ip, row in rows_by_ip.items():
        shards.setdefault(coordinate_cache_shard_id(ip), {})[ip] = row

    cache_dir = GROUP_OUTPUT_DIR / "coords" / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    for shard_id, rows in sorted(shards.items()):
        path = cache_dir / f"ip-coordinate-cache-{shard_id}.json"
        path.write_text(json.dumps(rows, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def cell_index(value: float, offset: float, degrees: float, max_index: int) -> int:
    index = math.floor((value + offset) / degrees)
    return min(max_index, max(0, index))


def bbox_for_index(lat_index: int, lon_index: int, degrees: float) -> dict[str, float]:
    south = -90.0 + lat_index * degrees
    west = -180.0 + lon_index * degrees
    return {
        "south": round(max(-90.0, south), 6),
        "north": round(min(90.0, south + degrees), 6),
        "west": round(max(-180.0, west), 6),
        "east": round(min(180.0, west + degrees), 6),
    }


def add_to_point(point: dict[str, Any], ip: str, coord: dict[str, str], summary: dict[str, Any]) -> None:
    latitude, longitude = valid_coordinates(coord) or (0.0, 0.0)
    point["ip_count"] += 1
    point["row_count"] += int(summary.get("row_count") or 0)
    point["open_service_count"] += int(summary.get("open_service_count") or 0)
    point["_lat_sum"] += latitude
    point["_long_sum"] += longitude
    append_unique_limited(point["ips"], ip, SAMPLE_IP_LIMIT)
    for field in ("ports", "services", "scan_statuses"):
        for value in summary.get(field, []):
            append_unique_limited(point[field], value)
    for field in ("city", "region", "country", "org", "asn", "coordinate_provider", "coordinate_status"):
        if not point.get(field):
            point[field] = coord.get(field, "")
    point["_records"].append(
        {
            "ip": ip,
            "target_labels": "; ".join(summary.get("target_labels", [])) or coord.get("target_labels", ""),
            "ping_status": coord.get("ping_status", ""),
            "ping_rtt_ms": coord.get("ping_rtt_ms", ""),
            "long": coord.get("long", ""),
            "lat": coord.get("lat", ""),
            "coordinate_status": coord.get("coordinate_status", ""),
            "coordinate_provider": coord.get("coordinate_provider", ""),
            "city": coord.get("city", ""),
            "region": coord.get("region", ""),
            "country": coord.get("country", ""),
            "org": coord.get("org", ""),
            "asn": coord.get("asn", ""),
            "error": coord.get("error", ""),
            "looked_up_at": coord.get("looked_up_at", ""),
            "runbook_row_count": summary.get("row_count", 0),
            "open_service_count": summary.get("open_service_count", 0),
            "ports": summary.get("ports", []),
            "services": summary.get("services", []),
            "scan_statuses": summary.get("scan_statuses", []),
        }
    )


def finalize_point(point: dict[str, Any]) -> dict[str, Any]:
    ip_count = max(1, int(point["ip_count"]))
    latitude = point.pop("_lat_sum") / ip_count
    longitude = point.pop("_long_sum") / ip_count
    bucket_count = int(point.pop("_bucket_count", 1) or 1)
    bucket_id = int(point.pop("_bucket_id", 0) or 0)
    bbox = point.get("bbox", {})
    if bucket_count > 1 and isinstance(bbox, dict):
        south = float(bbox.get("south", latitude))
        north = float(bbox.get("north", latitude))
        west = float(bbox.get("west", longitude))
        east = float(bbox.get("east", longitude))
        lat_span = max(0.0001, north - south)
        long_span = max(0.0001, east - west)
        angle = (bucket_id * 2.399963229728653) % (math.pi * 2)
        ring = 0.2 + 0.75 * ((bucket_id % bucket_count) + 1) / bucket_count
        latitude += math.sin(angle) * lat_span * 0.42 * ring
        longitude += math.cos(angle) * long_span * 0.42 * ring
        latitude = min(north - lat_span * 0.03, max(south + lat_span * 0.03, latitude))
        longitude = min(east - long_span * 0.03, max(west + long_span * 0.03, longitude))
        point["display_bucket"] = bucket_id + 1
        point["display_buckets"] = bucket_count
    point["lat"] = round(latitude, 6)
    point["long"] = round(longitude, 6)
    point["lat_text"] = f"{latitude:.6f}"
    point["long_text"] = f"{longitude:.6f}"
    return point


def write_point_records(level_id: str, point: dict[str, Any]) -> None:
    records = point.pop("_records", [])
    if not isinstance(records, list):
        records = []
    records.sort(key=lambda item: str(item.get("ip", "")) if isinstance(item, dict) else "")
    record_id = hashlib.sha256(str(point.get("key", "")).encode("utf-8")).hexdigest()[:16]
    relative_path = Path("map-chunks") / level_id / "records" / f"{record_id}.json"
    output_path = GROUP_OUTPUT_DIR / relative_path
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(
            {
                "key": point.get("key", ""),
                "level": level_id,
                "record_count": len(records),
                "records": records,
            },
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )
    point["records_path"] = relative_path.as_posix()
    point["record_count"] = len(records)


def build_map_chunks(
    coordinate_rows_by_ip: dict[str, dict[str, str]],
    summaries_by_ip: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    map_root = GROUP_OUTPUT_DIR / "map-chunks"
    map_root.mkdir(parents=True, exist_ok=True)

    mapped_ips = [
        ip
        for ip, row in coordinate_rows_by_ip.items()
        if ip in summaries_by_ip and valid_coordinates(row) is not None
    ]

    manifest: dict[str, Any] = {
        "version": 1,
        "generated_at": utc_timestamp(),
        "mapped_ip_count": len(mapped_ips),
        "runbook_ip_count": len(summaries_by_ip),
        "levels": {},
    }

    for level in MAP_LEVELS:
        level_id = str(level["id"])
        cell_degrees = float(level["cell_degrees"])
        tile_degrees = float(level["tile_degrees"])
        split_target_ips = int(level.get("split_target_ips") or 0)
        max_cell_lat = math.ceil(180.0 / cell_degrees) - 1
        max_cell_lon = math.ceil(360.0 / cell_degrees) - 1
        max_tile_lat = math.ceil(180.0 / tile_degrees) - 1
        max_tile_lon = math.ceil(360.0 / tile_degrees) - 1
        cell_counts: Counter[tuple[int, int]] = Counter()
        for ip in mapped_ips:
            latitude, longitude = valid_coordinates(coordinate_rows_by_ip[ip]) or (0.0, 0.0)
            cell_counts[
                (
                    cell_index(latitude, 90.0, cell_degrees, max_cell_lat),
                    cell_index(longitude, 180.0, cell_degrees, max_cell_lon),
                )
            ] += 1

        tiles: dict[tuple[int, int], dict[str, dict[str, Any]]] = {}

        for ip in mapped_ips:
            coord = coordinate_rows_by_ip[ip]
            summary = summaries_by_ip[ip]
            latitude, longitude = valid_coordinates(coord) or (0.0, 0.0)
            cell_lat = cell_index(latitude, 90.0, cell_degrees, max_cell_lat)
            cell_lon = cell_index(longitude, 180.0, cell_degrees, max_cell_lon)
            tile_lat = cell_index(latitude, 90.0, tile_degrees, max_tile_lat)
            tile_lon = cell_index(longitude, 180.0, tile_degrees, max_tile_lon)
            bbox = bbox_for_index(cell_lat, cell_lon, cell_degrees)
            cell_count = cell_counts[(cell_lat, cell_lon)]
            bucket_count = 1
            bucket_id = 0
            if split_target_ips > 0 and cell_count > split_target_ips:
                bucket_count = min(MAX_SPLIT_BUCKETS_PER_CELL, math.ceil(cell_count / split_target_ips))
                bucket_id = stable_int(f"{level_id}:{cell_lat}:{cell_lon}:{ip}") % bucket_count
            key = f"{level_id}:{cell_lat}:{cell_lon}:{bucket_id}" if bucket_count > 1 else f"{level_id}:{cell_lat}:{cell_lon}"
            tile = tiles.setdefault((tile_lat, tile_lon), {})
            point = tile.setdefault(
                key,
                {
                    "key": key,
                    "level": level_id,
                    "cell": {"lat": cell_lat, "lon": cell_lon},
                    "display_bucket": bucket_id + 1,
                    "display_buckets": bucket_count,
                    "bbox": bbox,
                    "ip_count": 0,
                    "ips": [],
                    "row_count": 0,
                    "open_service_count": 0,
                    "ports": [],
                    "services": [],
                    "scan_statuses": [],
                    "_lat_sum": 0.0,
                    "_long_sum": 0.0,
                    "_bucket_id": bucket_id,
                    "_bucket_count": bucket_count,
                    "_records": [],
                },
            )
            add_to_point(point, ip, coord, summary)

        level_dir = map_root / level_id
        level_dir.mkdir(parents=True, exist_ok=True)
        chunks: list[dict[str, Any]] = []
        point_count = 0
        for (tile_lat, tile_lon), points_by_key in sorted(tiles.items()):
            points = [finalize_point(point) for point in points_by_key.values()]
            for point in points:
                write_point_records(level_id, point)
            points.sort(key=lambda point: (point.get("country", ""), point.get("region", ""), point["key"]))
            tile_bbox = bbox_for_index(tile_lat, tile_lon, tile_degrees)
            ip_count = sum(int(point.get("ip_count") or 0) for point in points)
            point_count += len(points)
            file_name = f"chunk-{tile_lat:04d}-{tile_lon:04d}.json"
            relative_path = Path("map-chunks") / level_id / file_name
            payload = {
                "level": level_id,
                "bbox": tile_bbox,
                "point_count": len(points),
                "ip_count": ip_count,
                "points": points,
            }
            (GROUP_OUTPUT_DIR / relative_path).write_text(
                json.dumps(payload, separators=(",", ":")) + "\n",
                encoding="utf-8",
            )
            chunks.append(
                {
                    "path": relative_path.as_posix(),
                    "bbox": tile_bbox,
                    "point_count": len(points),
                    "ip_count": ip_count,
                }
            )

        manifest["levels"][level_id] = {
            **level,
            "point_count": point_count,
            "chunk_count": len(chunks),
            "chunks": chunks,
        }

    manifest_path = map_root / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


def write_manifest(
    runs: list[Path],
    link_stats: LinkStats,
    csv_paths: list[Path],
    jsonl_paths: list[Path],
    coordinate_rows: dict[str, dict[str, str]],
    summaries: dict[str, dict[str, Any]],
    map_manifest: dict[str, Any],
) -> None:
    path = GROUP_OUTPUT_DIR / "manifest" / "organizer-manifest.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": utc_timestamp(),
        "group_output_dir": str(GROUP_OUTPUT_DIR),
        "source_runs": [str(path) for path in runs],
        "bulk_dir": str(GROUP_OUTPUT_DIR / "bulk"),
        "csv_shards": len(csv_paths),
        "jsonl_shards": len(jsonl_paths),
        "coordinate_rows": len(coordinate_rows),
        "runbook_ips": len(summaries),
        "mapped_runbook_ips": map_manifest.get("mapped_ip_count", 0),
        "hardlinked_files": link_stats.linked,
        "copied_files": link_stats.copied,
        "map_chunk_manifest": str(GROUP_OUTPUT_DIR / "map-chunks" / "manifest.json"),
        "map_levels": map_manifest.get("levels", {}),
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    if len(sys.argv) > 1:
        print("This script intentionally runs without arguments.", file=sys.stderr)
        return 2

    try:
        runs = run_output_dirs()
        if not runs:
            raise FileNotFoundError(f"No runbook output directories with data were found under {CYBER_DIR}")

        print(f"[{utc_timestamp()}] rebuilding {GROUP_OUTPUT_DIR}", flush=True)
        reset_generated_dirs()
        link_stats, csv_paths, jsonl_paths, coord_csv_paths, cache_json_paths = link_run_files(runs)
        print(
            f"[{utc_timestamp()}] linked/copied {link_stats.linked + link_stats.copied} files "
            f"from {len(runs)} runs",
            flush=True,
        )

        summaries = summarize_runbook_rows(csv_paths)
        coord_rows = merge_coordinate_csvs(coord_csv_paths)
        coord_rows = merge_coordinate_caches(cache_json_paths, coord_rows)
        write_aggregate_coordinates(coord_rows)
        map_manifest = build_map_chunks(coord_rows, summaries)
        write_manifest(runs, link_stats, csv_paths, jsonl_paths, coord_rows, summaries, map_manifest)

        print(f"[{utc_timestamp()}] runbook IPs: {len(summaries):,}", flush=True)
        print(f"[{utc_timestamp()}] coordinate rows: {len(coord_rows):,}", flush=True)
        print(f"[{utc_timestamp()}] mapped runbook IPs: {map_manifest.get('mapped_ip_count', 0):,}", flush=True)
        print(f"[{utc_timestamp()}] output: {GROUP_OUTPUT_DIR}", flush=True)
        return 0
    except Exception as exc:  # noqa: BLE001 - no-arg operator script should surface local failure clearly.
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
