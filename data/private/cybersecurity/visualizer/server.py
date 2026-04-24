#!/usr/bin/env python3
"""
Serve the private cybersecurity runbook flow visualizer.

The browser UI reads through this local server so exports can be written back to
data/private/cybersecurity/runbook-outputs/quick-output.
"""

from __future__ import annotations

import argparse
import csv
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

OPTIONS_LIMIT = 5000
ROW_PREVIEW_LIMIT = 500

_DATA_CACHE: dict[str, object] = {
    "signature": None,
    "rows": [],
    "headers": [],
    "shards": [],
    "source_format": "",
}


def source_files() -> tuple[str, list[Path]]:
    """Prefer CSV shards because they are smaller and faster to parse here."""
    csv_files = sorted(CSV_DIR.glob("*.csv")) if CSV_DIR.exists() else []
    if csv_files:
        return "csv", csv_files

    jsonl_files = sorted(JSONL_DIR.glob("*.jsonl")) if JSONL_DIR.exists() else []
    return "jsonl", jsonl_files


def file_signature(paths: list[Path]) -> tuple[tuple[str, int, int], ...]:
    return tuple((str(path), path.stat().st_size, path.stat().st_mtime_ns) for path in paths)


def normalize_value(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return "; ".join(normalize_value(item) for item in value if normalize_value(item))
    return str(value)


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
                normalized = {key: normalize_value(value) for key, value in row.items() if key}
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


def row_matches(row: dict[str, str], filters: dict[str, str]) -> bool:
    return all(row.get(field, "") == value for field, value in filters.items())


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
    limit: int | None = OPTIONS_LIMIT,
) -> dict[str, object]:
    active_filters = prefix_filters(field, hierarchy, filters)
    counter: Counter[str] = Counter()
    matched_rows = 0

    for row in rows:
        if row_matches(row, active_filters):
            matched_rows += 1
            counter[row.get(field, "")] += 1

    items = sorted(counter.items(), key=option_sort_key)
    truncated = bool(limit is not None and len(items) > limit)
    if limit is not None:
        items = items[:limit]

    return {
        "field": field,
        "active_filters": active_filters,
        "matched_rows": matched_rows,
        "total_options": len(counter),
        "truncated": truncated,
        "options": [{"value": value, "count": count} for value, count in items],
    }


def build_view(filters: dict[str, str]) -> dict[str, object]:
    dataset = get_dataset()
    rows = dataset["rows"]  # type: ignore[assignment]
    headers = dataset["headers"]  # type: ignore[assignment]
    assert isinstance(rows, list)
    assert isinstance(headers, list)

    hierarchy = build_hierarchy(headers)
    valid_filters = {field: value for field, value in filters.items() if field in headers}
    matching_rows = [row for row in rows if row_matches(row, valid_filters)]

    return {
        "source_format": dataset["source_format"],
        "shards": dataset["shards"],
        "headers": headers,
        "hierarchy": hierarchy,
        "filters": valid_filters,
        "total_rows": len(rows),
        "matching_count": len(matching_rows),
        "row_preview_limit": ROW_PREVIEW_LIMIT,
        "rows": matching_rows[:ROW_PREVIEW_LIMIT],
        "columns": [
            build_field_options(rows, field, valid_filters, hierarchy, OPTIONS_LIMIT)
            for field in hierarchy
        ],
    }


def safe_filename_part(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip())
    return cleaned.strip("-") or "blank"


def write_column_export(field: str, filters: dict[str, str]) -> dict[str, object]:
    dataset = get_dataset()
    rows = dataset["rows"]  # type: ignore[assignment]
    headers = dataset["headers"]  # type: ignore[assignment]
    assert isinstance(rows, list)
    assert isinstance(headers, list)

    hierarchy = build_hierarchy(headers)
    if field not in hierarchy:
        raise ValueError(f"Unknown field: {field}")

    QUICK_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    column = build_field_options(rows, field, filters, hierarchy, limit=None)
    timestamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    output_path = QUICK_OUTPUT_DIR / f"{timestamp}-{safe_filename_part(field)}-column.csv"
    active_filters = column["active_filters"]
    assert isinstance(active_filters, dict)

    filter_label = "; ".join(f"{key}={value}" for key, value in active_filters.items())

    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "field",
                "value",
                "count",
                "active_filters",
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


def write_rows_export(filters: dict[str, str]) -> dict[str, object]:
    dataset = get_dataset()
    rows = dataset["rows"]  # type: ignore[assignment]
    headers = dataset["headers"]  # type: ignore[assignment]
    assert isinstance(rows, list)
    assert isinstance(headers, list)

    matching_rows = [row for row in rows if row_matches(row, filters)]
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
            self.respond_json(build_view(filters))
            return
        super().do_GET()

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path != "/api/export":
            self.send_error(HTTPStatus.NOT_FOUND)
            return

        try:
            payload = self.read_json_body()
            filters = parse_filters(json.dumps(payload.get("filters", {})))
            export_type = normalize_value(payload.get("type"))
            if export_type == "rows":
                result = write_rows_export(filters)
            else:
                field = normalize_value(payload.get("field"))
                result = write_column_export(field, filters)
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
        return {
            "source_format": dataset["source_format"],
            "shards": dataset["shards"],
            "headers": headers,
            "hierarchy": build_hierarchy(headers),
            "total_rows": len(rows),
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
    return parser


def main() -> None:
    args = build_parser().parse_args()
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
