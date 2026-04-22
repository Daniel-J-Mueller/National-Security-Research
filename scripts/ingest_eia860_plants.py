#!/usr/bin/env python3
"""
Build resilience-safe EIA-860 plant tables from the official 2024 workbook set.

This script intentionally excludes exact coordinates and street addresses from
the cleaned outputs. The raw official source files remain in data/raw/.
"""

from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterable
from xml.etree import ElementTree as ET
from zipfile import ZipFile


ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data" / "raw" / "electrical" / "eia860" / "2024"
OUT_DIR = ROOT / "data" / "processed" / "electrical" / "eia860"
PUBLIC_DIR = ROOT / "data" / "public" / "electrical"

PLANT_XLSX = RAW_DIR / "2___Plant_Y2024.xlsx"
GENERATOR_XLSX = RAW_DIR / "3_1_Generator_Y2024.xlsx"

NS = {"a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}


def clean_text(value: str | None) -> str:
    if value is None:
        return ""
    return " ".join(value.replace("\xa0", " ").split())


def clean_number(value: str | None) -> str:
    text = clean_text(value)
    if not text:
        return ""
    try:
        number = float(text)
    except ValueError:
        return text
    if number.is_integer():
        return str(int(number))
    return f"{number:.6f}".rstrip("0").rstrip(".")


def to_float(value: str | None) -> float:
    text = clean_text(value)
    if not text:
        return 0.0
    try:
        return float(text)
    except ValueError:
        return 0.0


def excel_column(ref: str) -> str:
    letters = []
    for char in ref:
        if char.isalpha():
            letters.append(char)
        else:
            break
    return "".join(letters)


def load_shared_strings(archive: ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in archive.namelist():
        return []
    root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
    shared_strings: list[str] = []
    for item in root.findall("a:si", NS):
        shared_strings.append("".join(node.text or "" for node in item.iterfind(".//a:t", NS)))
    return shared_strings


def resolve_sheet_path(archive: ZipFile, sheet_name: str) -> str:
    workbook = ET.fromstring(archive.read("xl/workbook.xml"))
    relationships = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    rel_map = {rel.attrib["Id"]: rel.attrib["Target"] for rel in relationships}
    sheets = workbook.find("a:sheets", NS)
    if sheets is None:
        raise ValueError("Workbook does not contain sheets")
    for sheet in sheets:
        if sheet.attrib.get("name") != sheet_name:
            continue
        rel_id = sheet.attrib["{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"]
        target = rel_map[rel_id]
        return f"xl/{target}"
    raise ValueError(f"Sheet '{sheet_name}' not found")


def iter_sheet_rows(path: Path, sheet_name: str) -> Iterable[dict[str, str]]:
    with ZipFile(path) as archive:
        shared_strings = load_shared_strings(archive)
        sheet_path = resolve_sheet_path(archive, sheet_name)
        xml_bytes = archive.read(sheet_path)

    root = ET.fromstring(xml_bytes)
    sheet_data = root.find("a:sheetData", NS)
    if sheet_data is None:
        return

    header_map: dict[str, str] | None = None
    for row in sheet_data.findall("a:row", NS):
        values_by_column: dict[str, str] = {}
        for cell in row.findall("a:c", NS):
            ref = cell.attrib.get("r", "")
            column = excel_column(ref)
            cell_type = cell.attrib.get("t")
            value_node = cell.find("a:v", NS)
            value = ""
            if cell_type == "s" and value_node is not None:
                value = shared_strings[int(value_node.text)]
            elif cell_type == "inlineStr":
                value = "".join(node.text or "" for node in cell.iterfind(".//a:t", NS))
            elif value_node is not None and value_node.text is not None:
                value = value_node.text
            values_by_column[column] = clean_text(value)

        row_number = int(row.attrib.get("r", "0"))
        if row_number == 2:
            header_map = {column: name for column, name in values_by_column.items() if name}
            continue
        if row_number < 3 or not header_map:
            continue

        record: dict[str, str] = {}
        for column, header in header_map.items():
            record[header] = values_by_column.get(column, "")
        if any(record.values()):
            yield record


def summarize_generators() -> dict[str, dict[str, str]]:
    by_plant: dict[str, dict[str, object]] = defaultdict(
        lambda: {
            "generator_count": 0,
            "operable_nameplate_capacity_mw": 0.0,
            "operable_summer_capacity_mw": 0.0,
            "operable_winter_capacity_mw": 0.0,
            "primary_fuels": Counter(),
            "technologies": Counter(),
            "statuses": Counter(),
        }
    )

    for row in iter_sheet_rows(GENERATOR_XLSX, "Operable"):
        plant_code = clean_number(row.get("Plant Code"))
        if not plant_code:
            continue
        summary = by_plant[plant_code]
        summary["generator_count"] += 1
        summary["operable_nameplate_capacity_mw"] += to_float(row.get("Nameplate Capacity (MW)"))
        summary["operable_summer_capacity_mw"] += to_float(row.get("Summer Capacity (MW)"))
        summary["operable_winter_capacity_mw"] += to_float(row.get("Winter Capacity (MW)"))

        fuel = clean_text(row.get("Energy Source 1"))
        technology = clean_text(row.get("Technology"))
        status = clean_text(row.get("Status"))
        if fuel:
            summary["primary_fuels"][fuel] += 1
        if technology:
            summary["technologies"][technology] += 1
        if status:
            summary["statuses"][status] += 1

    normalized: dict[str, dict[str, str]] = {}
    for plant_code, summary in by_plant.items():
        fuels: Counter[str] = summary["primary_fuels"]  # type: ignore[assignment]
        technologies: Counter[str] = summary["technologies"]  # type: ignore[assignment]
        statuses: Counter[str] = summary["statuses"]  # type: ignore[assignment]
        normalized[plant_code] = {
            "generator_count": str(summary["generator_count"]),
            "operable_nameplate_capacity_mw": clean_number(str(summary["operable_nameplate_capacity_mw"])),
            "operable_summer_capacity_mw": clean_number(str(summary["operable_summer_capacity_mw"])),
            "operable_winter_capacity_mw": clean_number(str(summary["operable_winter_capacity_mw"])),
            "primary_fuel_code": fuels.most_common(1)[0][0] if fuels else "",
            "primary_technology": technologies.most_common(1)[0][0] if technologies else "",
            "status_mix": "|".join(f"{name}:{count}" for name, count in statuses.most_common()),
        }
    return normalized


def build_clean_plants(generator_summary: dict[str, dict[str, str]]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for row in iter_sheet_rows(PLANT_XLSX, "Plant"):
        plant_code = clean_number(row.get("Plant Code"))
        if not plant_code:
            continue
        grid = generator_summary.get(plant_code, {})
        rows.append(
            {
                "plant_code": plant_code,
                "plant_name": clean_text(row.get("Plant Name")),
                "utility_id": clean_number(row.get("Utility ID")),
                "utility_name": clean_text(row.get("Utility Name")),
                "city": clean_text(row.get("City")),
                "county": clean_text(row.get("County")),
                "state": clean_text(row.get("State")),
                "zip_code": clean_text(row.get("Zip")),
                "nerc_region": clean_text(row.get("NERC Region")),
                "balancing_authority_code": clean_text(row.get("Balancing Authority Code")),
                "balancing_authority_name": clean_text(row.get("Balancing Authority Name")),
                "sector_name": clean_text(row.get("Sector Name")),
                "regulatory_status": clean_text(row.get("Regulatory Status")),
                "transmission_owner": clean_text(row.get("Transmission or Distribution System Owner")),
                "grid_voltage_1_kv": clean_number(row.get("Grid Voltage (kV)")),
                "grid_voltage_2_kv": clean_number(row.get("Grid Voltage 2 (kV)")),
                "grid_voltage_3_kv": clean_number(row.get("Grid Voltage 3 (kV)")),
                "energy_storage_flag": clean_text(row.get("Energy Storage")),
                "generator_count": grid.get("generator_count", "0"),
                "operable_nameplate_capacity_mw": grid.get("operable_nameplate_capacity_mw", "0"),
                "operable_summer_capacity_mw": grid.get("operable_summer_capacity_mw", "0"),
                "operable_winter_capacity_mw": grid.get("operable_winter_capacity_mw", "0"),
                "primary_fuel_code": grid.get("primary_fuel_code", ""),
                "primary_technology": grid.get("primary_technology", ""),
                "status_mix": grid.get("status_mix", ""),
                "source_dataset": "EIA-860 2024",
            }
        )
    rows.sort(key=lambda item: (item["state"], item["county"], item["plant_name"], item["plant_code"]))
    return rows


def aggregate(rows: list[dict[str, str]], group_fields: list[str]) -> list[dict[str, str]]:
    buckets: dict[tuple[str, ...], dict[str, object]] = {}
    for row in rows:
        key = tuple(row[field] for field in group_fields)
        bucket = buckets.setdefault(
            key,
            {
                "plant_count": 0,
                "generator_count": 0,
                "operable_nameplate_capacity_mw": 0.0,
                "operable_summer_capacity_mw": 0.0,
                "operable_winter_capacity_mw": 0.0,
                "primary_fuels": Counter(),
            },
        )
        bucket["plant_count"] += 1
        bucket["generator_count"] += int(row["generator_count"] or "0")
        bucket["operable_nameplate_capacity_mw"] += to_float(row["operable_nameplate_capacity_mw"])
        bucket["operable_summer_capacity_mw"] += to_float(row["operable_summer_capacity_mw"])
        bucket["operable_winter_capacity_mw"] += to_float(row["operable_winter_capacity_mw"])
        if row["primary_fuel_code"]:
            bucket["primary_fuels"][row["primary_fuel_code"]] += 1

    output: list[dict[str, str]] = []
    for key, bucket in buckets.items():
        record = {field: value for field, value in zip(group_fields, key)}
        fuels: Counter[str] = bucket["primary_fuels"]  # type: ignore[assignment]
        record.update(
            {
                "plant_count": str(bucket["plant_count"]),
                "generator_count": str(bucket["generator_count"]),
                "operable_nameplate_capacity_mw": clean_number(str(bucket["operable_nameplate_capacity_mw"])),
                "operable_summer_capacity_mw": clean_number(str(bucket["operable_summer_capacity_mw"])),
                "operable_winter_capacity_mw": clean_number(str(bucket["operable_winter_capacity_mw"])),
                "dominant_primary_fuel_code": fuels.most_common(1)[0][0] if fuels else "",
            }
        )
        output.append(record)
    output.sort(key=lambda item: tuple(item[field] for field in group_fields))
    return output


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        raise ValueError(f"No rows available for {path.name}")
    fieldnames = list(rows[0].keys())
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_metadata(rows: list[dict[str, str]], state_rows: list[dict[str, str]], county_rows: list[dict[str, str]]) -> None:
    total_nameplate = sum(to_float(row["operable_nameplate_capacity_mw"]) for row in rows)
    total_summer = sum(to_float(row["operable_summer_capacity_mw"]) for row in rows)
    total_winter = sum(to_float(row["operable_winter_capacity_mw"]) for row in rows)
    metadata = {
        "dataset": "EIA-860 2024",
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "source_files": [
            str(PLANT_XLSX.relative_to(ROOT)),
            str(GENERATOR_XLSX.relative_to(ROOT)),
        ],
        "outputs": [
            "data/processed/electrical/eia860/plants_2024_clean.csv",
            "data/public/electrical/plants_state_summary.csv",
            "data/public/electrical/plants_county_summary.csv",
        ],
        "safety_note": "Clean outputs exclude exact coordinates and street addresses.",
        "record_counts": {
            "plants": len(rows),
            "states": len(state_rows),
            "counties": len(county_rows),
        },
        "capacity_mw": {
            "operable_nameplate_total": clean_number(str(total_nameplate)),
            "operable_summer_total": clean_number(str(total_summer)),
            "operable_winter_total": clean_number(str(total_winter)),
        },
    }
    path = OUT_DIR / "ingestion_metadata_2024.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")


def main() -> None:
    if not PLANT_XLSX.exists():
        raise FileNotFoundError(f"Missing source workbook: {PLANT_XLSX}")
    if not GENERATOR_XLSX.exists():
        raise FileNotFoundError(f"Missing source workbook: {GENERATOR_XLSX}")

    generator_summary = summarize_generators()
    plants = build_clean_plants(generator_summary)
    state_summary = aggregate(plants, ["state"])
    county_summary = aggregate(plants, ["state", "county"])

    write_csv(OUT_DIR / "plants_2024_clean.csv", plants)
    write_csv(PUBLIC_DIR / "plants_state_summary.csv", state_summary)
    write_csv(PUBLIC_DIR / "plants_county_summary.csv", county_summary)
    write_metadata(plants, state_summary, county_summary)

    print(f"Wrote {len(plants)} plant rows")
    print(f"Wrote {len(state_summary)} state summary rows")
    print(f"Wrote {len(county_summary)} county summary rows")


if __name__ == "__main__":
    main()
