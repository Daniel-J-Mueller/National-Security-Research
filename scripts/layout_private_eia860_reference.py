#!/usr/bin/env python3
"""
Build CSV-style private reference documents from the EIA-860 2024 layout workbook.

This script does not extract or materialize exact plant coordinates or street
addresses into public outputs. It creates private CSV outputs that document the
official layout and preserve exact plant location data in the private folder.
"""

from __future__ import annotations

import csv
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile


ROOT = Path(__file__).resolve().parents[1]
LAYOUT_XLSX = ROOT / "data" / "raw" / "eia860" / "2024" / "LayoutY2024.xlsx"
PLANT_XLSX = ROOT / "data" / "raw" / "eia860" / "2024" / "2___Plant_Y2024.xlsx"
OUT_DIR = ROOT / "data" / "private" / "eia860_2024"

NS = {"a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
FIELD_DIRECTORY_SHEET = "Field Directory"
PLANT_SHEET = "Plant"


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


def excel_column(ref: str) -> str:
    letters: list[str] = []
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
    values: list[str] = []
    for item in root.findall("a:si", NS):
        values.append("".join(node.text or "" for node in item.iterfind(".//a:t", NS)))
    return values


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
        return f"xl/{rel_map[rel_id]}"
    raise ValueError(f"Sheet '{sheet_name}' not found")


def iter_field_directory_rows(path: Path) -> list[dict[str, str]]:
    with ZipFile(path) as archive:
        shared_strings = load_shared_strings(archive)
        sheet_path = resolve_sheet_path(archive, FIELD_DIRECTORY_SHEET)
        root = ET.fromstring(archive.read(sheet_path))

    sheet_data = root.find("a:sheetData", NS)
    if sheet_data is None:
        return []

    header_map: dict[str, str] | None = None
    rows: list[dict[str, str]] = []
    for row in sheet_data.findall("a:row", NS):
        row_number = int(row.attrib.get("r", "0"))
        values_by_column: dict[str, str] = {}
        for cell in row.findall("a:c", NS):
            ref = cell.attrib.get("r", "")
            column = excel_column(ref)
            cell_type = cell.attrib.get("t")
            value_node = cell.find("a:v", NS)
            value = ""
            if cell_type == "s" and value_node is not None and value_node.text is not None:
                value = shared_strings[int(value_node.text)]
            elif cell_type == "inlineStr":
                value = "".join(node.text or "" for node in cell.iterfind(".//a:t", NS))
            elif value_node is not None and value_node.text is not None:
                value = value_node.text
            values_by_column[column] = clean_text(value)

        if row_number == 3:
            header_map = {
                column: clean_text(name).lower().replace("/", "_").replace(" ", "_")
                for column, name in values_by_column.items()
                if clean_text(name)
            }
            continue
        if row_number < 4 or not header_map:
            continue

        record: dict[str, str] = {}
        for column, header in header_map.items():
            record[header] = values_by_column.get(column, "")
        if any(record.values()):
            rows.append(record)
    return rows


def iter_sheet_rows(path: Path, sheet_name: str, header_row_number: int) -> list[dict[str, str]]:
    with ZipFile(path) as archive:
        shared_strings = load_shared_strings(archive)
        sheet_path = resolve_sheet_path(archive, sheet_name)
        root = ET.fromstring(archive.read(sheet_path))

    sheet_data = root.find("a:sheetData", NS)
    if sheet_data is None:
        return []

    header_map: dict[str, str] | None = None
    rows: list[dict[str, str]] = []
    for row in sheet_data.findall("a:row", NS):
        row_number = int(row.attrib.get("r", "0"))
        values_by_column: dict[str, str] = {}
        for cell in row.findall("a:c", NS):
            ref = cell.attrib.get("r", "")
            column = excel_column(ref)
            cell_type = cell.attrib.get("t")
            value_node = cell.find("a:v", NS)
            value = ""
            if cell_type == "s" and value_node is not None and value_node.text is not None:
                value = shared_strings[int(value_node.text)]
            elif cell_type == "inlineStr":
                value = "".join(node.text or "" for node in cell.iterfind(".//a:t", NS))
            elif value_node is not None and value_node.text is not None:
                value = value_node.text
            values_by_column[column] = clean_text(value)

        if row_number == header_row_number:
            header_map = {column: name for column, name in values_by_column.items() if name}
            continue
        if row_number < header_row_number + 1 or not header_map:
            continue

        record: dict[str, str] = {}
        for column, header in header_map.items():
            record[header] = values_by_column.get(column, "")
        if any(record.values()):
            rows.append(record)
    return rows


def is_sensitive_location_field(record: dict[str, str]) -> bool:
    text = " ".join(
        [
            record.get("field_name", ""),
            record.get("description", ""),
            record.get("notes", ""),
        ]
    ).lower()
    markers = (
        "latitude",
        "longitude",
        "street address",
        "physical address",
        "location of the plant",
        "gps",
    )
    return any(marker in text for marker in markers)


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        raise ValueError(f"No rows available for {path}")
    fieldnames = list(rows[0].keys())
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def build_private_plant_location_rows() -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for row in iter_sheet_rows(PLANT_XLSX, PLANT_SHEET, header_row_number=2):
        plant_code = clean_number(row.get("Plant Code"))
        if not plant_code:
            continue
        latitude = clean_number(row.get("Latitude"))
        longitude = clean_number(row.get("Longitude"))
        rows.append(
            {
                "plant_code": plant_code,
                "plant_name": clean_text(row.get("Plant Name")),
                "utility_id": clean_number(row.get("Utility ID")),
                "utility_name": clean_text(row.get("Utility Name")),
                "street_address": clean_text(row.get("Street Address")),
                "city": clean_text(row.get("City")),
                "county": clean_text(row.get("County")),
                "state": clean_text(row.get("State")),
                "zip_code": clean_text(row.get("Zip")),
                "latitude": latitude,
                "longitude": longitude,
                "coordinate_status": "present" if latitude and longitude else "missing_or_partial",
                "source_dataset": "EIA-860 2024",
                "source_sheet": PLANT_SHEET,
            }
        )
    rows.sort(key=lambda item: (item["state"], item["county"], item["plant_name"], item["plant_code"]))
    return rows


def build_coordinate_summary_rows(location_rows: list[dict[str, str]]) -> list[dict[str, str]]:
    by_state: dict[str, dict[str, int]] = {}
    for row in location_rows:
        state = row["state"] or "UNKNOWN"
        bucket = by_state.setdefault(
            state,
            {
                "plant_count": 0,
                "coordinates_present_count": 0,
                "coordinates_missing_or_partial_count": 0,
            },
        )
        bucket["plant_count"] += 1
        if row["coordinate_status"] == "present":
            bucket["coordinates_present_count"] += 1
        else:
            bucket["coordinates_missing_or_partial_count"] += 1

    summary_rows: list[dict[str, str]] = []
    for state, stats in sorted(by_state.items()):
        summary_rows.append(
            {
                "state": state,
                "plant_count": str(stats["plant_count"]),
                "coordinates_present_count": str(stats["coordinates_present_count"]),
                "coordinates_missing_or_partial_count": str(stats["coordinates_missing_or_partial_count"]),
                "source_dataset": "EIA-860 2024",
            }
        )
    return summary_rows


def build_reference_outputs(rows: list[dict[str, str]], location_rows: list[dict[str, str]]) -> None:
    field_rows: list[dict[str, str]] = []
    sensitive_rows: list[dict[str, str]] = []
    for row in rows:
        field_rows.append(row)
        if is_sensitive_location_field(row):
            sensitive_rows.append(
                {
                    "field_name": row.get("field_name", ""),
                    "form_eia-860_schedule": row.get("form_eia-860_schedule", ""),
                    "form_eia-860_line_number": row.get("form_eia-860_line_number", ""),
                    "description": row.get("description", ""),
                    "notes": row.get("notes", ""),
                    "private_handling_status": "withheld_exact_location_values",
                    "recommended_safe_alternative": "Use city, county, state, NERC region, balancing authority, or other coarse geography.",
                }
            )

    dataset_rows = [
        {
            "source_file": "data/raw/eia860/2024/LayoutY2024.xlsx",
            "sheet_name": FIELD_DIRECTORY_SHEET,
            "output_file": "data/private/eia860_2024/field_directory.csv",
            "purpose": "CSV reference copy of the official layout field directory.",
        },
        {
            "source_file": "data/raw/eia860/2024/LayoutY2024.xlsx",
            "sheet_name": FIELD_DIRECTORY_SHEET,
            "output_file": "data/private/eia860_2024/sensitive_fields_manifest.csv",
                    "purpose": "Sensitive field inventory for withheld exact location/address data.",
        },
        {
            "source_file": "data/raw/eia860/2024/2___Plant_Y2024.xlsx",
            "sheet_name": PLANT_SHEET,
            "output_file": "data/private/eia860_2024/plant_locations_private.csv",
            "purpose": "Private plant-level location table with exact coordinates and address fields from the official plant workbook.",
        },
        {
            "source_file": "data/raw/eia860/2024/2___Plant_Y2024.xlsx",
            "sheet_name": PLANT_SHEET,
            "output_file": "data/private/eia860_2024/plant_coordinates_state_summary_private.csv",
            "purpose": "Private state summary of coordinate coverage for plant location records.",
        },
    ]

    write_csv(OUT_DIR / "field_directory.csv", field_rows)
    write_csv(OUT_DIR / "sensitive_fields_manifest.csv", sensitive_rows)
    write_csv(OUT_DIR / "plant_locations_private.csv", location_rows)
    write_csv(OUT_DIR / "plant_coordinates_state_summary_private.csv", build_coordinate_summary_rows(location_rows))
    write_csv(OUT_DIR / "source_inventory.csv", dataset_rows)


def main() -> None:
    if not LAYOUT_XLSX.exists():
        raise FileNotFoundError(f"Missing layout workbook: {LAYOUT_XLSX}")
    if not PLANT_XLSX.exists():
        raise FileNotFoundError(f"Missing plant workbook: {PLANT_XLSX}")
    rows = iter_field_directory_rows(LAYOUT_XLSX)
    location_rows = build_private_plant_location_rows()
    build_reference_outputs(rows, location_rows)
    print(f"Wrote {len(rows)} field directory rows")
    print(f"Wrote {len(location_rows)} private plant location rows")


if __name__ == "__main__":
    main()
