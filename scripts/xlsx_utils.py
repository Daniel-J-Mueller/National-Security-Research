#!/usr/bin/env python3
"""
Small helpers for reading simple XLSX worksheets with the standard library.
"""

from __future__ import annotations

from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile


NS = {"a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}


def clean_text(value: str | None) -> str:
    if value is None:
        return ""
    return " ".join(str(value).replace("\xa0", " ").split())


def excel_column(cell_ref: str) -> str:
    letters: list[str] = []
    for char in cell_ref:
        if char.isalpha():
            letters.append(char)
        else:
            break
    return "".join(letters)


def load_shared_strings(archive: ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in archive.namelist():
        return []
    root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
    return [
        "".join(node.text or "" for node in item.iterfind(".//a:t", NS))
        for item in root.findall("a:si", NS)
    ]


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


def read_sheet_rows(path: Path, sheet_name: str, header_row_number: int = 1) -> tuple[list[str], list[dict[str, str]]]:
    with ZipFile(path) as archive:
        shared_strings = load_shared_strings(archive)
        sheet_path = resolve_sheet_path(archive, sheet_name)
        root = ET.fromstring(archive.read(sheet_path))

    sheet_data = root.find("a:sheetData", NS)
    if sheet_data is None:
        return [], []

    header_map: dict[str, str] | None = None
    headers: list[str] = []
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
            headers = [values_by_column[column] for column in sorted(values_by_column) if values_by_column[column]]
            header_map = {column: value for column, value in values_by_column.items() if value}
            continue
        if row_number < header_row_number + 1 or not header_map:
            continue

        record = {header: values_by_column.get(column, "") for column, header in header_map.items()}
        if any(record.values()):
            rows.append(record)

    return headers, rows
