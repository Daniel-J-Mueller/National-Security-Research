#!/usr/bin/env python3
"""
Build coordinate-backed raw-material outputs from official USGS and EPA sources.
"""

from __future__ import annotations

import csv
import json
from datetime import UTC, datetime
from pathlib import Path

from xlsx_utils import clean_text, read_sheet_rows


ROOT = Path(__file__).resolve().parents[1]
USGS_CSV = (
    ROOT
    / "data"
    / "raw"
    / "raws"
    / "usgs"
    / "critical_mineral_deposits_bundle"
    / "Critical_mineral_deposits_table_v2_csv.csv"
)
GHGP_XLSX = ROOT / "data" / "raw" / "raws" / "epa" / "2023_data_summary_spreadsheets" / "ghgp_data_2023.xlsx"

PUBLIC_DIR = ROOT / "data" / "public" / "raws"
PRIVATE_DIR = ROOT / "data" / "private" / "raws"
PUBLIC_CSV = PUBLIC_DIR / "raw_material_sites_2023.csv"
PRIVATE_CSV = PRIVATE_DIR / "raw_material_sites_2023_private.csv"
PUBLIC_METADATA_JSON = PUBLIC_DIR / "raw_material_sites_2023_metadata.json"
PRIVATE_METADATA_JSON = PRIVATE_DIR / "raw_material_sites_2023_private_metadata.json"


def to_float(value: str | None) -> float | None:
    text = clean_text(value)
    if not text:
        return None
    try:
        return float(text.replace(",", ""))
    except ValueError:
        return None


def normalize_materials(value: str) -> str:
    materials = [clean_text(item) for item in clean_text(value).split(",") if clean_text(item)]
    return ", ".join(materials)


def first_material(value: str) -> str:
    materials = [clean_text(item) for item in clean_text(value).split(",") if clean_text(item)]
    return materials[0] if materials else ""


def load_usgs_rows() -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    with USGS_CSV.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for index, row in enumerate(reader, start=1):
            latitude = clean_text(row.get("Lat_WGS84"))
            longitude = clean_text(row.get("Long_WGS84"))
            if not latitude or not longitude:
                continue

            production_text = clean_text(row.get("Production"))
            resources_text = clean_text(row.get("Resources"))
            materials = normalize_materials(row.get("CritMin", ""))
            site_name = clean_text(row.get("Deposit")) or f"Unnamed {first_material(materials) or 'raw material'} site {index}"
            rows.append(
                {
                    "asset_id": f"ore-{index}",
                    "asset_type": "ore_site",
                    "site_name": site_name,
                    "state": clean_text(row.get("State")),
                    "county": "",
                    "latitude": latitude,
                    "longitude": longitude,
                    "geometry_precision": "point",
                    "primary_material": first_material(materials),
                    "critical_materials": materials,
                    "dominant_raws_profile": "Ore Site",
                    "asset_status": clean_text(row.get("DepCat")),
                    "rank_score": clean_text(row.get("Rank ")),
                    "presence_count": "1",
                    "production_present_flag": "1" if production_text and production_text.lower() != "unknown." else "0",
                    "resources_present_flag": "1" if resources_text and resources_text.lower() != "unknown." else "0",
                    "total_reported_direct_emissions_mtco2e": "",
                    "iron_and_steel_production_emissions_mtco2e": "",
                    "reporting_year": "2024",
                    "source_dataset": "USGS Critical mineral deposits of the United States v2.0",
                    "source_detail": "ScienceBase data release 10.5066/P9K1HBNT",
                    "mineral_system": clean_text(row.get("MinSystem")),
                    "deposit_type": clean_text(row.get("DepType")),
                    "focus_area": clean_text(row.get("FocusArea")),
                    "production_text": production_text,
                    "resources_text": resources_text,
                    "source_summary": clean_text(row.get("Source_s")),
                    "source_link": clean_text(row.get("Links")),
                    "ghgrp_facility_id": "",
                    "ghgrp_frs_id": "",
                    "ghgrp_address": "",
                    "ghgrp_primary_naics_code": "",
                    "ghgrp_subparts": "",
                    "ghgrp_sector": "",
                }
            )
    return rows


def load_steel_rows() -> list[dict[str, str]]:
    _headers, rows = read_sheet_rows(GHGP_XLSX, "Direct Point Emitters", header_row_number=4)
    selected_rows: list[dict[str, str]] = []
    for row in rows:
        iron_and_steel = clean_text(row.get("Iron and Steel Production"))
        subparts = clean_text(row.get("Industry Type (subparts)"))
        sectors = clean_text(row.get("Industry Type (sectors)"))
        if not iron_and_steel and "Q" not in subparts and "Iron and Steel" not in sectors and "Metals" not in sectors:
            continue

        latitude = clean_text(row.get("Latitude"))
        longitude = clean_text(row.get("Longitude"))
        if not latitude or not longitude:
            continue

        facility_id = clean_text(row.get("Facility Id"))
        selected_rows.append(
            {
                "asset_id": f"steel-{facility_id or len(selected_rows) + 1}",
                "asset_type": "steel_facility",
                "site_name": clean_text(row.get("Facility Name")),
                "state": clean_text(row.get("State")),
                "county": clean_text(row.get("County")),
                "latitude": latitude,
                "longitude": longitude,
                "geometry_precision": "point",
                "primary_material": "steel",
                "critical_materials": "",
                "dominant_raws_profile": "Steel Facility",
                "asset_status": "reported_facility",
                "rank_score": "",
                "presence_count": "1",
                "production_present_flag": "",
                "resources_present_flag": "",
                "total_reported_direct_emissions_mtco2e": clean_text(row.get("Total reported direct emissions")),
                "iron_and_steel_production_emissions_mtco2e": iron_and_steel,
                "reporting_year": "2023",
                "source_dataset": "EPA GHGRP 2023 Data Summary Spreadsheets",
                "source_detail": "Direct Point Emitters sheet",
                "mineral_system": "",
                "deposit_type": "",
                "focus_area": "",
                "production_text": "",
                "resources_text": "",
                "source_summary": "",
                "source_link": "",
                "ghgrp_facility_id": facility_id,
                "ghgrp_frs_id": clean_text(row.get("FRS Id")),
                "ghgrp_address": clean_text(row.get("Address")),
                "ghgrp_primary_naics_code": clean_text(row.get("Primary NAICS Code")),
                "ghgrp_subparts": subparts,
                "ghgrp_sector": sectors,
            }
        )
    return selected_rows


def build_rows() -> tuple[list[dict[str, str]], list[dict[str, str]], dict[str, object], dict[str, object]]:
    usgs_rows = load_usgs_rows()
    steel_rows = load_steel_rows()
    private_rows = sorted(
        [*usgs_rows, *steel_rows],
        key=lambda row: (row["asset_type"], row["state"], row["site_name"]),
    )

    public_rows: list[dict[str, str]] = []
    for row in private_rows:
        public_rows.append(
            {
                "asset_id": row["asset_id"],
                "asset_type": row["asset_type"],
                "site_name": row["site_name"],
                "state": row["state"],
                "county": row["county"],
                "latitude": row["latitude"],
                "longitude": row["longitude"],
                "geometry_precision": row["geometry_precision"],
                "primary_material": row["primary_material"],
                "critical_materials": row["critical_materials"],
                "dominant_raws_profile": row["dominant_raws_profile"],
                "asset_status": row["asset_status"],
                "rank_score": row["rank_score"],
                "presence_count": row["presence_count"],
                "production_present_flag": row["production_present_flag"],
                "resources_present_flag": row["resources_present_flag"],
                "total_reported_direct_emissions_mtco2e": row["total_reported_direct_emissions_mtco2e"],
                "iron_and_steel_production_emissions_mtco2e": row["iron_and_steel_production_emissions_mtco2e"],
                "reporting_year": row["reporting_year"],
                "source_dataset": row["source_dataset"],
                "source_detail": row["source_detail"],
            }
        )

    generated_at = datetime.now(UTC).isoformat()
    public_metadata = {
        "generated_at_utc": generated_at,
        "source_files": [
            str(USGS_CSV.relative_to(ROOT)),
            str(GHGP_XLSX.relative_to(ROOT)),
        ],
        "output_file": str(PUBLIC_CSV.relative_to(ROOT)),
        "row_count": len(public_rows),
        "ore_site_count": sum(1 for row in public_rows if row["asset_type"] == "ore_site"),
        "steel_facility_count": sum(1 for row in public_rows if row["asset_type"] == "steel_facility"),
        "notes": [
            "Public output keeps coordinate-backed ore sites and steel facilities with numeric metrics and high-level descriptors.",
            "Private output adds narrative production/resource text, source links, and facility address/registry fields.",
        ],
    }
    private_metadata = {
        "generated_at_utc": generated_at,
        "source_files": public_metadata["source_files"],
        "output_file": str(PRIVATE_CSV.relative_to(ROOT)),
        "row_count": len(private_rows),
        "ore_site_count": public_metadata["ore_site_count"],
        "steel_facility_count": public_metadata["steel_facility_count"],
    }
    return public_rows, private_rows, public_metadata, private_metadata


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        raise ValueError(f"No rows available for {path}")
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    if not USGS_CSV.exists():
        raise FileNotFoundError(f"Missing USGS CSV: {USGS_CSV}")
    if not GHGP_XLSX.exists():
        raise FileNotFoundError(f"Missing EPA workbook: {GHGP_XLSX}")

    public_rows, private_rows, public_metadata, private_metadata = build_rows()
    if not public_rows or not private_rows:
        raise ValueError("No raws rows were built")

    write_csv(PUBLIC_CSV, public_rows)
    write_csv(PRIVATE_CSV, private_rows)
    PUBLIC_METADATA_JSON.write_text(json.dumps(public_metadata, indent=2), encoding="utf-8")
    PRIVATE_METADATA_JSON.write_text(json.dumps(private_metadata, indent=2), encoding="utf-8")

    print(f"Wrote {len(public_rows)} public raws rows to {PUBLIC_CSV}")
    print(f"Wrote {len(private_rows)} private raws rows to {PRIVATE_CSV}")


if __name__ == "__main__":
    main()
