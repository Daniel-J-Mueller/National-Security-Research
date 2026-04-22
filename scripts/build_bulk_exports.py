#!/usr/bin/env python3
"""
Create one bulk CSV per category for public and private data consumers.
"""

from __future__ import annotations

import csv
import json
import shutil
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

from xlsx_utils import clean_text


ROOT = Path(__file__).resolve().parents[1]
PUBLIC_BULK_DIR = ROOT / "data" / "public-bulk"
PRIVATE_BULK_DIR = ROOT / "data" / "private-bulk"
COUNTY_GAZETTEER = (
    ROOT
    / "data"
    / "raw"
    / "agriculture"
    / "census"
    / "2024_Gaz_counties_national"
    / "2024_Gaz_counties_national.txt"
)

PUBLIC_COPY_SOURCES = {
    "people": ROOT / "data" / "public" / "people" / "municipal_population_town_halls_2024.csv",
    "agriculture": ROOT / "data" / "public" / "agriculture" / "county_food_outputs_2022.csv",
    "raws": ROOT / "data" / "public" / "raws" / "raw_material_sites_2023.csv",
    "radiation": ROOT / "data" / "public" / "radiation" / "radnet_background_radiation_monitors.csv",
}
PRIVATE_COPY_SOURCES = {
    "people": ROOT / "data" / "private" / "people" / "municipal_population_town_halls_2024_private.csv",
    "agriculture": ROOT / "data" / "private" / "agriculture" / "county_food_outputs_2022_private.csv",
    "raws": ROOT / "data" / "private" / "raws" / "raw_material_sites_2023_private.csv",
    "radiation": ROOT / "data" / "private" / "radiation" / "radnet_background_radiation_monitors_private.csv",
    "electrical": ROOT / "data" / "private" / "electrical" / "eia860_2024" / "plant_profiles_private.csv",
}

PUBLIC_COUNTY_SUMMARY = ROOT / "data" / "public" / "electrical" / "plants_county_summary.csv"
PUBLIC_STATE_SUMMARY = ROOT / "data" / "public" / "electrical" / "plants_state_summary.csv"


def normalize_county_name(value: str) -> str:
    text = clean_text(value).lower()
    suffixes = (
        " county",
        " parish",
        " borough",
        " census area",
        " municipality",
        " city and borough",
        " district",
        " municipality",
    )
    for suffix in suffixes:
        if text.endswith(suffix):
            text = text[: -len(suffix)]
            break
    return " ".join(text.split())


def load_county_centroids() -> dict[tuple[str, str], dict[str, str]]:
    county_centroids: dict[tuple[str, str], dict[str, str]] = {}
    with COUNTY_GAZETTEER.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        for row in reader:
            cleaned_row = {clean_text(key): clean_text(value) for key, value in row.items() if key}
            state = clean_text(cleaned_row.get("USPS"))
            county_name = clean_text(cleaned_row.get("NAME"))
            if not state or not county_name:
                continue
            county_centroids[(state, normalize_county_name(county_name))] = {
                "latitude": clean_text(cleaned_row.get("INTPTLAT")),
                "longitude": clean_text(cleaned_row.get("INTPTLONG")),
            }
    return county_centroids


def load_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return [{key: clean_text(value) for key, value in row.items()} for row in csv.DictReader(handle)]


def to_float(value: str | None) -> float | None:
    text = clean_text(value)
    if not text:
        return None
    try:
        return float(text.replace(",", ""))
    except ValueError:
        return None


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        raise ValueError(f"No rows available for {path}")
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def build_public_electrical_bulk() -> tuple[list[dict[str, str]], dict[str, object]]:
    county_centroids = load_county_centroids()
    county_rows = load_csv_rows(PUBLIC_COUNTY_SUMMARY)
    state_rows = load_csv_rows(PUBLIC_STATE_SUMMARY)

    bulk_rows: list[dict[str, str]] = []
    state_coordinate_samples: dict[str, list[tuple[float, float]]] = defaultdict(list)

    for row in county_rows:
        state = clean_text(row.get("state"))
        county = clean_text(row.get("county"))
        centroid = county_centroids.get((state, normalize_county_name(county)))
        latitude = centroid.get("latitude", "") if centroid else ""
        longitude = centroid.get("longitude", "") if centroid else ""
        latitude_value = to_float(latitude)
        longitude_value = to_float(longitude)
        if latitude_value is not None and longitude_value is not None:
            state_coordinate_samples[state].append((latitude_value, longitude_value))

        bulk_rows.append(
            {
                "record_scope": "county",
                "state": state,
                "county": county,
                "latitude": latitude,
                "longitude": longitude,
                "geometry_precision": "county_centroid",
                "plant_count": clean_text(row.get("plant_count")),
                "generator_count": clean_text(row.get("generator_count")),
                "operable_nameplate_capacity_mw": clean_text(row.get("operable_nameplate_capacity_mw")),
                "operable_summer_capacity_mw": clean_text(row.get("operable_summer_capacity_mw")),
                "operable_winter_capacity_mw": clean_text(row.get("operable_winter_capacity_mw")),
                "dominant_primary_fuel_code": clean_text(row.get("dominant_primary_fuel_code")),
                "source_dataset": "EIA-860 2024 public county summary",
            }
        )

    for row in state_rows:
        state = clean_text(row.get("state"))
        samples = state_coordinate_samples.get(state, [])
        latitude = ""
        longitude = ""
        if samples:
            latitude = f"{sum(sample[0] for sample in samples) / len(samples):.6f}"
            longitude = f"{sum(sample[1] for sample in samples) / len(samples):.6f}"

        bulk_rows.append(
            {
                "record_scope": "state",
                "state": state,
                "county": "",
                "latitude": latitude,
                "longitude": longitude,
                "geometry_precision": "derived_state_centroid",
                "plant_count": clean_text(row.get("plant_count")),
                "generator_count": clean_text(row.get("generator_count")),
                "operable_nameplate_capacity_mw": clean_text(row.get("operable_nameplate_capacity_mw")),
                "operable_summer_capacity_mw": clean_text(row.get("operable_summer_capacity_mw")),
                "operable_winter_capacity_mw": clean_text(row.get("operable_winter_capacity_mw")),
                "dominant_primary_fuel_code": clean_text(row.get("dominant_primary_fuel_code")),
                "source_dataset": "EIA-860 2024 public state summary",
            }
        )

    metadata = {
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "source_files": [
            str(PUBLIC_COUNTY_SUMMARY.relative_to(ROOT)),
            str(PUBLIC_STATE_SUMMARY.relative_to(ROOT)),
            str(COUNTY_GAZETTEER.relative_to(ROOT)),
        ],
        "county_row_count": len(county_rows),
        "state_row_count": len(state_rows),
        "output_file": str((PUBLIC_BULK_DIR / "electrical" / "electrical.csv").relative_to(ROOT)),
        "notes": [
            "County rows use Census Gazetteer county centroids.",
            "State rows use the simple mean of matched county centroids inside each state.",
        ],
    }
    return bulk_rows, metadata


def copy_bulk_source(source: Path, out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, out_path)


def main() -> None:
    metadata: dict[str, object] = {
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "public_bulk_files": {},
        "private_bulk_files": {},
    }

    public_electrical_rows, public_electrical_metadata = build_public_electrical_bulk()
    public_electrical_out = PUBLIC_BULK_DIR / "electrical" / "electrical.csv"
    write_csv(public_electrical_out, public_electrical_rows)
    metadata["public_bulk_files"]["electrical"] = {
        "path": str(public_electrical_out.relative_to(ROOT)),
        "source_summary": public_electrical_metadata,
    }

    for category, source in PUBLIC_COPY_SOURCES.items():
        if not source.exists():
            raise FileNotFoundError(f"Missing public bulk source for {category}: {source}")
        out_path = PUBLIC_BULK_DIR / category / f"{category}.csv"
        copy_bulk_source(source, out_path)
        metadata["public_bulk_files"][category] = {
            "path": str(out_path.relative_to(ROOT)),
            "source_file": str(source.relative_to(ROOT)),
        }

    for category, source in PRIVATE_COPY_SOURCES.items():
        if not source.exists():
            raise FileNotFoundError(f"Missing private bulk source for {category}: {source}")
        out_path = PRIVATE_BULK_DIR / category / f"{category}.csv"
        copy_bulk_source(source, out_path)
        metadata["private_bulk_files"][category] = {
            "path": str(out_path.relative_to(ROOT)),
            "source_file": str(source.relative_to(ROOT)),
        }

    metadata_path = PRIVATE_BULK_DIR / "bulk_exports_metadata.json"
    metadata_path.parent.mkdir(parents=True, exist_ok=True)
    metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")

    print(f"Wrote public bulk exports under {PUBLIC_BULK_DIR}")
    print(f"Wrote private bulk exports under {PRIVATE_BULK_DIR}")


if __name__ == "__main__":
    main()
