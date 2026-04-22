#!/usr/bin/env python3
"""
Build browser-ready private plant map assets from EIA-860 coordinate data.
"""

from __future__ import annotations

import csv
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PLANT_DETAILS_CSV = ROOT / "data" / "processed" / "eia860" / "plants_2024_clean.csv"
PLANT_COORDS_CSV = ROOT / "data" / "private" / "eia860_2024" / "plant_locations_private.csv"
OUT_DIR = ROOT / "data" / "private" / "visualizer"
OUT_JSON = OUT_DIR / "plants_reference.json"
OUT_SUMMARY_JSON = OUT_DIR / "plants_reference_summary.json"

BASE_METRICS = [
    "generator_count",
    "operable_nameplate_capacity_mw",
    "operable_summer_capacity_mw",
    "operable_winter_capacity_mw",
]


def clean_text(value: str | None) -> str:
    if value is None:
        return ""
    return " ".join(value.replace("\xa0", " ").split())


def parse_float(value: str | None) -> float | None:
    text = clean_text(value)
    if not text:
        return None
    try:
        return float(text.replace(",", ""))
    except ValueError:
        return None


def parse_int(value: str | None) -> int | None:
    number = parse_float(value)
    if number is None:
        return None
    return int(number)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        return [{key: clean_text(value) for key, value in row.items()} for row in reader]


def join_rows() -> list[dict[str, object]]:
    detail_rows = read_csv(PLANT_DETAILS_CSV)
    detail_by_code = {row["plant_code"]: row for row in detail_rows if row.get("plant_code")}

    joined_rows: list[dict[str, object]] = []
    for row in read_csv(PLANT_COORDS_CSV):
        plant_code = row.get("plant_code", "")
        latitude = parse_float(row.get("latitude"))
        longitude = parse_float(row.get("longitude"))
        if not plant_code or latitude is None or longitude is None:
            continue

        detail = detail_by_code.get(plant_code, {})
        joined_rows.append(
            {
                "plant_code": plant_code,
                "plant_name": detail.get("plant_name") or row.get("plant_name", ""),
                "utility_id": detail.get("utility_id") or row.get("utility_id", ""),
                "utility_name": detail.get("utility_name") or row.get("utility_name", ""),
                "city": detail.get("city") or row.get("city", ""),
                "county": detail.get("county") or row.get("county", ""),
                "state": detail.get("state") or row.get("state", ""),
                "zip_code": detail.get("zip_code") or row.get("zip_code", ""),
                "latitude": round(latitude, 6),
                "longitude": round(longitude, 6),
                "coordinate_status": row.get("coordinate_status", ""),
                "nerc_region": detail.get("nerc_region", ""),
                "balancing_authority_code": detail.get("balancing_authority_code", ""),
                "balancing_authority_name": detail.get("balancing_authority_name", ""),
                "sector_name": detail.get("sector_name", ""),
                "regulatory_status": detail.get("regulatory_status", ""),
                "transmission_owner": detail.get("transmission_owner", ""),
                "energy_storage_flag": detail.get("energy_storage_flag", ""),
                "generator_count": parse_int(detail.get("generator_count")),
                "operable_nameplate_capacity_mw": parse_float(detail.get("operable_nameplate_capacity_mw")),
                "operable_summer_capacity_mw": parse_float(detail.get("operable_summer_capacity_mw")),
                "operable_winter_capacity_mw": parse_float(detail.get("operable_winter_capacity_mw")),
                "primary_fuel_code": detail.get("primary_fuel_code", ""),
                "primary_technology": detail.get("primary_technology", ""),
                "status_mix": detail.get("status_mix", ""),
                "source_dataset": detail.get("source_dataset") or row.get("source_dataset", "EIA-860 2024"),
            }
        )

    joined_rows.sort(
        key=lambda item: (
            str(item.get("state", "")),
            str(item.get("county", "")),
            str(item.get("plant_name", "")),
            str(item.get("plant_code", "")),
        )
    )
    return joined_rows


def build_summary(rows: list[dict[str, object]]) -> dict[str, object]:
    state_counts = Counter(str(row["state"]) for row in rows if row.get("state"))
    fuel_counts = Counter(str(row["primary_fuel_code"]) for row in rows if row.get("primary_fuel_code"))

    latitudes = [float(row["latitude"]) for row in rows]
    longitudes = [float(row["longitude"]) for row in rows]
    total_nameplate = sum(float(row["operable_nameplate_capacity_mw"] or 0) for row in rows)

    return {
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "source_files": [
            str(PLANT_DETAILS_CSV.relative_to(ROOT)),
            str(PLANT_COORDS_CSV.relative_to(ROOT)),
        ],
        "output_file": str(OUT_JSON.relative_to(ROOT)),
        "plant_count": len(rows),
        "state_count": len(state_counts),
        "fuel_code_count": len(fuel_counts),
        "base_metrics": BASE_METRICS,
        "states": sorted(state_counts),
        "fuel_codes": sorted(fuel_counts),
        "total_operable_nameplate_capacity_mw": round(total_nameplate, 3),
        "bounds": {
            "min_latitude": min(latitudes),
            "max_latitude": max(latitudes),
            "min_longitude": min(longitudes),
            "max_longitude": max(longitudes),
        },
    }


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def main() -> None:
    if not PLANT_DETAILS_CSV.exists():
        raise FileNotFoundError(f"Missing plant details CSV: {PLANT_DETAILS_CSV}")
    if not PLANT_COORDS_CSV.exists():
        raise FileNotFoundError(f"Missing plant coordinates CSV: {PLANT_COORDS_CSV}")

    rows = join_rows()
    if not rows:
        raise ValueError("No joined plant rows were built")

    summary = build_summary(rows)
    write_json(
        OUT_JSON,
        {
            "metadata": summary,
            "plants": rows,
        },
    )
    write_json(OUT_SUMMARY_JSON, summary)

    print(f"Wrote {len(rows)} joined plant rows to {OUT_JSON}")
    print(f"Wrote summary metadata to {OUT_SUMMARY_JSON}")


if __name__ == "__main__":
    main()
