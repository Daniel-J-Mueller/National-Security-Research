#!/usr/bin/env python3
"""
Enrich an owner-authorized server CSV with safe defensive hardening artifacts.

This workflow does not download malware archives or extract exploit snippets.
It processes local defensive catalog chunks, writes matched hardening snippets,
and outputs a CSV with snippet references for each server inventory row.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections.abc import Iterable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CATALOG = ROOT / "config" / "cybersecurity" / "defensive-artifact-catalog.json"
DEFAULT_OUTPUT_DIR = ROOT / "data" / "private" / "cybersecurity" / "artifact-matches"

ALLOWED_ARTIFACT_TYPES = {
    "defensive-hardening",
    "defensive-reference",
    "detection-rule-reference",
    "vendor-advisory-reference",
    "general-review",
}
CATALOG_EXTENSIONS = {".json", ".jsonl", ".csv"}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Read a private server CSV, match each row to safe defensive "
            "hardening artifacts, save compatible snippets, and write an "
            "enriched CSV containing snippet references."
        )
    )
    parser.add_argument(
        "--servers-csv",
        type=Path,
        required=True,
        help="CSV exported from your owned office/home server inventory or scan results.",
    )
    parser.add_argument(
        "--catalog",
        type=Path,
        default=DEFAULT_CATALOG,
        help=(
            "Defensive artifact catalog file or directory of catalog chunks. "
            "Supports JSON, JSONL, and CSV."
        ),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Directory for private enriched CSVs and matched snippet files.",
    )
    parser.add_argument(
        "--label",
        help="Safe label for the output folder. Defaults to the input CSV filename.",
    )
    parser.add_argument(
        "--server-id-column",
        help=(
            "Optional column name used as the server identifier. If omitted, "
            "common columns such as server, host, hostname, ip, target, or asset_id are used."
        ),
    )
    parser.add_argument(
        "--max-artifacts-per-row",
        type=int,
        default=3,
        help="Maximum non-fallback artifacts to attach to each CSV row.",
    )
    parser.add_argument(
        "--stop-when-covered",
        action="store_true",
        help="Stop processing catalog chunks once every CSV row has at least one non-fallback match.",
    )
    return parser


def utc_timestamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def clean_label(value: str) -> str:
    label = re.sub(r"[^A-Za-z0-9_.-]+", "_", value.strip())
    return label.strip("._") or "server-inventory"


def normalize_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def row_lookup(row: dict[str, str]) -> dict[str, str]:
    return {normalize_key(key): value for key, value in row.items()}


def get_first(row: dict[str, str], candidates: Iterable[str]) -> str:
    lookup = row_lookup(row)
    for candidate in candidates:
        value = lookup.get(normalize_key(candidate), "")
        if value:
            return value
    return ""


def server_id(row: dict[str, str], requested_column: str | None) -> str:
    if requested_column:
        value = row.get(requested_column, "")
        if value:
            return value
    return (
        get_first(
            row,
            [
                "server_id",
                "server",
                "host",
                "hostname",
                "host_name",
                "ip",
                "ip_address",
                "target",
                "asset",
                "asset_id",
            ],
        )
        or "unknown-server"
    )


def read_server_csv(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise ValueError(f"{path} does not contain a CSV header")
        rows = [{key: value or "" for key, value in row.items()} for row in reader]
        return rows, list(reader.fieldnames)


def discover_catalog_chunks(path: Path) -> list[Path]:
    if path.is_file():
        return [path]
    if path.is_dir():
        chunks = [
            item
            for item in sorted(path.iterdir())
            if item.is_file() and item.suffix.lower() in CATALOG_EXTENSIONS
        ]
        if chunks:
            return chunks
    raise FileNotFoundError(f"No defensive catalog chunks found at {path}")


def parse_json_catalog(path: Path) -> Iterator[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                yield item
        return
    if isinstance(data, dict):
        artifacts = data.get("artifacts", [])
        if not isinstance(artifacts, list):
            raise ValueError(f"{path} has an artifacts field, but it is not a list")
        for item in artifacts:
            if isinstance(item, dict):
                yield item
        return
    raise ValueError(f"{path} is not a supported JSON catalog shape")


def parse_jsonl_catalog(path: Path) -> Iterator[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                item = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_number} is not valid JSONL: {exc}") from exc
            if isinstance(item, dict):
                yield item


def parse_csv_catalog(path: Path) -> Iterator[dict[str, Any]]:
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise ValueError(f"{path} does not contain a CSV header")
        for row in reader:
            item: dict[str, Any] = {key: value or "" for key, value in row.items()}
            for structured_field in ("match_any", "references"):
                value = item.get(structured_field)
                if value:
                    item[structured_field] = json.loads(value)
            yield item


def parse_catalog_chunk(path: Path) -> Iterator[dict[str, Any]]:
    suffix = path.suffix.lower()
    if suffix == ".json":
        yield from parse_json_catalog(path)
    elif suffix == ".jsonl":
        yield from parse_jsonl_catalog(path)
    elif suffix == ".csv":
        yield from parse_csv_catalog(path)
    else:
        raise ValueError(f"Unsupported catalog chunk type: {path}")


def validate_artifact(artifact: dict[str, Any], source: Path) -> tuple[bool, str]:
    artifact_id = str(artifact.get("id", "")).strip()
    if not artifact_id:
        return False, "missing id"
    artifact_type = str(artifact.get("artifact_type", "")).strip()
    if artifact_type not in ALLOWED_ARTIFACT_TYPES:
        return False, f"{artifact_id}: unsupported artifact_type {artifact_type!r}"
    if not str(artifact.get("title", "")).strip():
        return False, f"{artifact_id}: missing title"
    if not str(artifact.get("snippet", "")).strip():
        return False, f"{artifact_id}: missing defensive snippet"
    match_any = artifact.get("match_any", [{}])
    if not isinstance(match_any, list):
        return False, f"{artifact_id}: match_any must be a list"
    if artifact.get("fallback") is not True and not match_any:
        return False, f"{artifact_id}: no match selectors"
    return True, str(source)


def compile_regex(pattern: Any) -> re.Pattern[str] | None:
    if not pattern:
        return None
    return re.compile(str(pattern), re.IGNORECASE)


def parse_port(value: str) -> int | None:
    try:
        return int(str(value).strip())
    except ValueError:
        return None


def row_port(row: dict[str, str]) -> int | None:
    return parse_port(get_first(row, ["port", "service_port", "dst_port", "destination_port"]))


def split_multi_value(value: str) -> list[str]:
    return [item.strip().lower() for item in re.split(r"[;,|]", value or "") if item.strip()]


def selector_matches(selector: dict[str, Any], row: dict[str, str]) -> bool:
    service_name = get_first(row, ["service_name", "service", "name"]).strip()
    product = get_first(row, ["product", "software", "application", "banner_product"]).strip()
    version = get_first(row, ["version", "service_version", "product_version"]).strip()
    cpe = get_first(row, ["cpe", "cpes"]).strip()
    flags = get_first(row, ["flags", "service_flags"]).strip()
    vx_category = get_first(row, ["vx_category", "category"]).strip()
    port = row_port(row)

    service_regex = compile_regex(selector.get("service_name_regex"))
    if service_regex and not service_regex.search(service_name):
        return False

    product_regex = compile_regex(selector.get("product_regex"))
    if product_regex and not product_regex.search(product):
        return False

    version_regex = compile_regex(selector.get("version_regex"))
    if version_regex and not version_regex.search(version):
        return False

    cpe_regex = compile_regex(selector.get("cpe_regex"))
    if cpe_regex and not cpe_regex.search(cpe):
        return False

    if selector.get("requires_version") is True and not version:
        return False

    flag_contains = selector.get("flag_contains")
    if flag_contains:
        normalized_flags = split_multi_value(flags)
        if str(flag_contains).lower() not in normalized_flags and str(flag_contains).lower() not in flags.lower():
            return False

    category_values = selector.get("vx_category_in")
    if category_values:
        accepted = {str(item).lower() for item in category_values}
        if vx_category.lower() not in accepted:
            return False

    port_values = selector.get("port_in")
    if port_values:
        accepted_ports = {parse_port(str(item)) for item in port_values}
        accepted_ports.discard(None)
        if port not in accepted_ports:
            return False

    return True


def artifact_matches(artifact: dict[str, Any], row: dict[str, str]) -> bool:
    if artifact.get("fallback") is True:
        return False
    selectors = artifact.get("match_any") or [{}]
    return any(selector_matches(selector, row) for selector in selectors if isinstance(selector, dict))


def safe_filename(value: str) -> str:
    return clean_label(value).lower()


def format_references(artifact: dict[str, Any]) -> str:
    references = artifact.get("references", [])
    if not isinstance(references, list):
        return ""
    formatted = []
    for reference in references:
        if not isinstance(reference, dict):
            continue
        name = str(reference.get("name", "")).strip()
        url = str(reference.get("url", "")).strip()
        if name and url:
            formatted.append(f"{name}: {url}")
        elif url:
            formatted.append(url)
    return "; ".join(formatted)


def snippet_text(artifact: dict[str, Any]) -> str:
    references = format_references(artifact)
    lines = [
        f"# {artifact['title']}",
        "",
        f"- Artifact ID: {artifact['id']}",
        f"- Type: {artifact['artifact_type']}",
        f"- Priority: {artifact.get('priority', 'review')}",
    ]
    if artifact.get("summary"):
        lines.append(f"- Summary: {artifact['summary']}")
    if references:
        lines.append(f"- References: {references}")
    lines.extend(["", str(artifact["snippet"]).strip(), ""])
    return "\n".join(lines)


def write_snippet(snippet_dir: Path, artifact: dict[str, Any]) -> Path:
    snippet_dir.mkdir(parents=True, exist_ok=True)
    path = snippet_dir / f"{safe_filename(artifact['id'])}.md"
    if not path.exists():
        path.write_text(snippet_text(artifact), encoding="utf-8")
    return path


def output_fieldnames(input_fieldnames: list[str]) -> list[str]:
    additions = [
        "defensive_artifact_ids",
        "defensive_artifact_titles",
        "defensive_match_status",
        "defensive_match_rationale",
        "defensive_snippet_paths",
        "defensive_references",
    ]
    fields = list(input_fieldnames)
    for field in additions:
        if field not in fields:
            fields.append(field)
    return fields


def relative_to_output(path: Path, output_root: Path) -> str:
    try:
        return path.relative_to(output_root).as_posix()
    except ValueError:
        return path.as_posix()


def write_enriched_csv(
    csv_path: Path,
    input_fieldnames: list[str],
    rows: list[dict[str, str]],
    row_matches: list[list[dict[str, Any]]],
    snippet_paths: dict[str, Path],
    output_root: Path,
) -> None:
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        fieldnames = output_fieldnames(input_fieldnames)
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row, matches in zip(rows, row_matches, strict=True):
            enriched = dict(row)
            artifact_ids = [item["id"] for item in matches]
            enriched["defensive_artifact_ids"] = "; ".join(artifact_ids)
            enriched["defensive_artifact_titles"] = "; ".join(str(item["title"]) for item in matches)
            enriched["defensive_match_status"] = (
                "fallback" if matches and matches[0].get("fallback") is True else "matched"
            )
            enriched["defensive_match_rationale"] = "; ".join(
                str(item.get("match_rationale", "")) for item in matches if item.get("match_rationale")
            )
            enriched["defensive_snippet_paths"] = "; ".join(
                relative_to_output(snippet_paths[item_id], output_root) for item_id in artifact_ids
            )
            enriched["defensive_references"] = " | ".join(format_references(item) for item in matches)
            writer.writerow({field: enriched.get(field, "") for field in fieldnames})


def build_summary(
    args: argparse.Namespace,
    rows: list[dict[str, str]],
    row_matches: list[list[dict[str, Any]]],
    chunk_summaries: list[dict[str, Any]],
    skipped_artifacts: list[str],
    enriched_csv: Path,
    output_root: Path,
) -> dict[str, Any]:
    unique_servers = {
        server_id(row, args.server_id_column)
        for row in rows
    }
    fallback_rows = sum(1 for matches in row_matches if matches and matches[0].get("fallback") is True)
    matched_rows = len(row_matches) - fallback_rows
    artifact_counts: dict[str, int] = {}
    for matches in row_matches:
        for artifact in matches:
            artifact_counts[artifact["id"]] = artifact_counts.get(artifact["id"], 0) + 1
    return {
        "workflow": "safe-server-defensive-artifact-matching",
        "generated_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "source_csv": str(args.servers_csv),
        "catalog": str(args.catalog),
        "output_csv": str(enriched_csv),
        "summary": {
            "rows": len(rows),
            "unique_servers": len(unique_servers),
            "matched_rows": matched_rows,
            "fallback_rows": fallback_rows,
            "artifact_counts": dict(sorted(artifact_counts.items())),
        },
        "catalog_chunks": chunk_summaries,
        "skipped_artifacts": skipped_artifacts,
        "handling_notes": [
            "Use this only with server inventories you own or are authorized to assess.",
            "Matched snippets are defensive hardening prompts, not proof of vulnerability.",
            "This workflow intentionally avoids malware samples, exploit code, payloads, and offensive procedures.",
            "Keep enriched CSVs and snippets private because they can reveal service exposure details.",
        ],
        "relative_output_csv": relative_to_output(enriched_csv, output_root),
    }


def all_rows_have_nonfallback(row_matches: list[list[dict[str, Any]]]) -> bool:
    return all(matches and matches[0].get("fallback") is not True for matches in row_matches)


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    try:
        if args.max_artifacts_per_row < 1:
            raise ValueError("--max-artifacts-per-row must be at least 1")

        rows, fieldnames = read_server_csv(args.servers_csv)
        if not rows:
            raise ValueError(f"{args.servers_csv} does not contain any data rows")

        output_root = args.output_dir / clean_label(args.label or args.servers_csv.stem) / utc_timestamp()
        snippet_dir = output_root / "snippets"
        output_root.mkdir(parents=True, exist_ok=True)

        catalog_chunks = discover_catalog_chunks(args.catalog)
        row_matches: list[list[dict[str, Any]]] = [[] for _ in rows]
        fallback_artifacts: list[dict[str, Any]] = []
        matched_artifacts: dict[str, dict[str, Any]] = {}
        skipped_artifacts: list[str] = []
        chunk_summaries: list[dict[str, Any]] = []

        for chunk in catalog_chunks:
            chunk_seen = 0
            chunk_used = 0
            for artifact in parse_catalog_chunk(chunk):
                chunk_seen += 1
                is_valid, reason = validate_artifact(artifact, chunk)
                if not is_valid:
                    skipped_artifacts.append(reason)
                    continue
                if artifact.get("fallback") is True:
                    fallback_artifacts.append(artifact)
                    continue

                matched_in_chunk = False
                for index, row in enumerate(rows):
                    if len(row_matches[index]) >= args.max_artifacts_per_row:
                        continue
                    if artifact_matches(artifact, row):
                        row_matches[index].append(artifact)
                        matched_artifacts[str(artifact["id"])] = artifact
                        matched_in_chunk = True
                if matched_in_chunk:
                    chunk_used += 1

            chunk_summaries.append(
                {
                    "path": str(chunk),
                    "artifacts_seen": chunk_seen,
                    "artifacts_used": chunk_used,
                }
            )
            if args.stop_when_covered and all_rows_have_nonfallback(row_matches):
                break

        if not fallback_artifacts:
            raise ValueError("The defensive catalog does not contain a fallback artifact")
        fallback = fallback_artifacts[0]
        for index, matches in enumerate(row_matches):
            if not matches:
                row_matches[index].append(fallback)
                matched_artifacts[str(fallback["id"])] = fallback

        snippet_paths = {
            artifact_id: write_snippet(snippet_dir, artifact)
            for artifact_id, artifact in sorted(matched_artifacts.items())
        }

        enriched_csv = output_root / "server-defensive-artifact-matches.csv"
        write_enriched_csv(enriched_csv, fieldnames, rows, row_matches, snippet_paths, output_root)

        summary = build_summary(
            args,
            rows,
            row_matches,
            chunk_summaries,
            skipped_artifacts,
            enriched_csv,
            output_root,
        )
        summary_path = output_root / "server-defensive-artifact-matches.json"
        with summary_path.open("w", encoding="utf-8") as handle:
            json.dump(summary, handle, indent=2)
            handle.write("\n")

    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(f"Rows enriched: {len(rows)}")
    print(f"CSV:  {enriched_csv}")
    print(f"JSON: {summary_path}")
    print(f"Snippets: {snippet_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
