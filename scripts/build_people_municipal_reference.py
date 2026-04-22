#!/usr/bin/env python3
"""
Build a municipal population reference by joining Census place estimates to
town-hall coordinates when available.
"""

from __future__ import annotations

import csv
import json
import re
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
POPULATION_CSV = ROOT / "data" / "raw" / "people" / "census" / "sub-est2024.csv"
GAZETTEER_TXT = (
    ROOT / "data" / "raw" / "people" / "census" / "2024_Gaz_place_national" / "2024_Gaz_place_national.txt"
)
TOWN_HALL_SOURCE_CANDIDATES = [
    ROOT / "data" / "private" / "people" / "town_halls" / "combined_town_halls.csv",
    ROOT / "data" / "private" / "_tmp_us_town_halls" / "combined_data" / "combined_town_halls.csv",
]
PUBLIC_OUT_DIR = ROOT / "data" / "public" / "people"
PRIVATE_OUT_DIR = ROOT / "data" / "private" / "people"
PUBLIC_OUT_CSV = PUBLIC_OUT_DIR / "municipal_population_town_halls_2024.csv"
PRIVATE_OUT_CSV = PRIVATE_OUT_DIR / "municipal_population_town_halls_2024_private.csv"
PUBLIC_METADATA_JSON = PUBLIC_OUT_DIR / "municipal_population_town_halls_2024_metadata.json"
PRIVATE_METADATA_JSON = PRIVATE_OUT_DIR / "municipal_population_town_halls_2024_private_metadata.json"

PLACE_SUFFIXES = (
    " city and borough",
    " unified government",
    " consolidated government",
    " consolidated gov",
    " municipality",
    " village",
    " borough",
    " township",
    " town",
    " city",
    " cdp",
)

KEYWORD_SCORES = {
    "city hall": 8,
    "town hall": 8,
    "village hall": 8,
    "borough hall": 8,
    "municipal": 6,
    "city of": 5,
    "town of": 5,
    "village of": 5,
    "borough of": 5,
}


def clean_text(value: str | None) -> str:
    if value is None:
        return ""
    return " ".join(str(value).replace("\xa0", " ").split())


def to_float(value: str | None) -> float | None:
    text = clean_text(value)
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def normalize_name(value: str) -> str:
    text = clean_text(value).lower()
    text = text.replace("&", " and ")
    text = re.sub(r"\bsaint\b", "st", text)
    text = re.sub(r"\bst\.\b", "st", text)
    text = re.sub(r"\bfort\b", "ft", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


def strip_place_suffix(name: str) -> str:
    normalized = clean_text(name)
    lowered = normalized.lower()
    for suffix in PLACE_SUFFIXES:
        if lowered.endswith(suffix):
            return normalized[: -len(suffix)].strip(" ,")
    return normalized


def parse_locality(locality: str) -> tuple[str, str]:
    match = re.match(r"^(.*?),\s*([A-Z]{2})\b", clean_text(locality))
    if not match:
        return "", ""
    return clean_text(match.group(1)), match.group(2)


def score_business_name(name: str) -> int:
    text = clean_text(name).lower()
    score = 0
    for token, weight in KEYWORD_SCORES.items():
        if token in text:
            score += weight
    return score


def pick_town_hall_source() -> Path:
    for candidate in TOWN_HALL_SOURCE_CANDIDATES:
        if candidate.exists():
            return candidate
    raise FileNotFoundError(
        "Missing town hall CSV. Expected one of: "
        + ", ".join(str(path.relative_to(ROOT)) for path in TOWN_HALL_SOURCE_CANDIDATES)
    )


def load_census_places() -> dict[tuple[str, str], dict[str, str]]:
    gazetteer_rows: dict[str, dict[str, str]] = {}
    with GAZETTEER_TXT.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        for row in reader:
            cleaned_row = {clean_text(key): clean_text(value) for key, value in row.items() if key}
            geoid = clean_text(cleaned_row.get("GEOID"))
            if geoid:
                gazetteer_rows[geoid] = cleaned_row

    places: dict[tuple[str, str], dict[str, str]] = {}
    with POPULATION_CSV.open("r", encoding="latin-1", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            if clean_text(row.get("SUMLEV")) != "162":
                continue
            state_fips = clean_text(row.get("STATE"))
            place_fips = clean_text(row.get("PLACE"))
            geoid = f"{state_fips}{place_fips}"
            gazetteer = gazetteer_rows.get(geoid)
            if not gazetteer:
                continue

            display_name = strip_place_suffix(clean_text(row.get("NAME")))
            key = (clean_text(gazetteer.get("USPS")), normalize_name(display_name))
            places[key] = {
                "state": clean_text(gazetteer.get("USPS")),
                "state_name": clean_text(row.get("STNAME")),
                "place_name": display_name,
                "census_name": clean_text(row.get("NAME")),
                "population_2024": clean_text(row.get("POPESTIMATE2024")),
                "latitude": clean_text(gazetteer.get("INTPTLAT")),
                "longitude": clean_text(gazetteer.get("INTPTLONG")),
                "geoid": geoid,
                "aland_sqmi": clean_text(gazetteer.get("ALAND_SQMI")),
                "awater_sqmi": clean_text(gazetteer.get("AWATER_SQMI")),
            }
    return places


def load_town_hall_groups() -> tuple[Path, dict[tuple[str, str], dict[str, object]]]:
    source_path = pick_town_hall_source()
    grouped: dict[tuple[str, str], dict[str, object]] = defaultdict(
        lambda: {
            "matched_rows": 0,
            "rows_with_coordinates": 0,
            "best_score": -1,
            "best_row": None,
        }
    )

    with source_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            locality = clean_text(row.get("locality"))
            city, state = parse_locality(locality)
            if not city or not state:
                continue

            key = (state, normalize_name(city))
            bucket = grouped[key]
            bucket["matched_rows"] += 1

            latitude = to_float(row.get("latitude"))
            longitude = to_float(row.get("longitude"))
            if latitude is None or longitude is None:
                continue

            bucket["rows_with_coordinates"] += 1
            score = score_business_name(clean_text(row.get("businessName")))
            best_row = bucket["best_row"]
            if (
                best_row is None
                or score > int(bucket["best_score"])
                or (
                    score == int(bucket["best_score"])
                    and clean_text(row.get("businessName")) < clean_text(best_row.get("businessName"))
                )
            ):
                bucket["best_score"] = score
                bucket["best_row"] = {
                    "town_hall_name": clean_text(row.get("businessName")),
                    "town_hall_address": clean_text(row.get("streetAddress")),
                    "town_hall_locality": locality,
                    "town_hall_latitude": f"{latitude:.6f}",
                    "town_hall_longitude": f"{longitude:.6f}",
                }

    return source_path, grouped


def build_rows() -> tuple[list[dict[str, str]], list[dict[str, str]], dict[str, object], dict[str, object]]:
    census_places = load_census_places()
    town_hall_source, town_hall_groups = load_town_hall_groups()

    public_rows: list[dict[str, str]] = []
    private_rows: list[dict[str, str]] = []
    matched_count = 0
    fallback_count = 0
    total_population = 0

    for key, place in sorted(census_places.items()):
        town_hall = town_hall_groups.get(key)
        best_row = town_hall.get("best_row") if town_hall else None
        matched_rows = int(town_hall.get("rows_with_coordinates", 0)) if town_hall else 0
        population = int(place["population_2024"] or "0")
        total_population += population

        if best_row:
            matched_count += 1
            latitude = best_row["town_hall_latitude"]
            longitude = best_row["town_hall_longitude"]
            coordinate_source = "town_hall"
            match_status = "town_hall_coordinate_match"
            population_per_town_hall = (
                f"{population / matched_rows:.2f}" if matched_rows > 0 else ""
            )
        else:
            fallback_count += 1
            latitude = place["latitude"]
            longitude = place["longitude"]
            coordinate_source = "census_place_centroid"
            match_status = "census_centroid_fallback"
            population_per_town_hall = ""
            best_row = {
                "town_hall_name": "",
                "town_hall_address": "",
                "town_hall_locality": "",
                "town_hall_latitude": "",
                "town_hall_longitude": "",
            }

        public_rows.append(
            {
                "state": place["state"],
                "state_name": place["state_name"],
                "place_name": place["place_name"],
                "census_name": place["census_name"],
                "geoid": place["geoid"],
                "population_2024": place["population_2024"],
                "latitude": latitude,
                "longitude": longitude,
                "coordinate_source": coordinate_source,
                "geometry_precision": "point",
                "matched_town_hall_rows_with_coordinates": str(matched_rows),
                "population_per_town_hall": population_per_town_hall,
                "land_area_sqmi": place["aland_sqmi"],
                "water_area_sqmi": place["awater_sqmi"],
                "match_status": match_status,
                "source_population_dataset": "Census Population Estimates 2024",
                "source_coordinate_dataset": (
                    "US_Town_Halls"
                    if coordinate_source == "town_hall"
                    else "Census Gazetteer 2024"
                ),
                "dominant_people_profile": "Town hall anchored municipality"
                if coordinate_source == "town_hall"
                else "Census centroid municipality",
            }
        )
        private_rows.append(
            {
                **public_rows[-1],
                "town_hall_name": best_row["town_hall_name"],
                "town_hall_address": best_row["town_hall_address"],
                "town_hall_locality": best_row["town_hall_locality"],
                "town_hall_latitude": best_row["town_hall_latitude"],
                "town_hall_longitude": best_row["town_hall_longitude"],
            }
        )

    public_metadata = {
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "source_files": [
            str(POPULATION_CSV.relative_to(ROOT)),
            str(GAZETTEER_TXT.relative_to(ROOT)),
            str(town_hall_source.relative_to(ROOT)),
        ],
        "output_file": str(PUBLIC_OUT_CSV.relative_to(ROOT)),
        "municipality_count": len(public_rows),
        "town_hall_coordinate_matches": matched_count,
        "census_centroid_fallbacks": fallback_count,
        "population_total_2024": total_population,
        "notes": [
            "Coordinates prefer a matched town hall when a municipal locality and state align cleanly.",
            "Rows without a usable town hall coordinate fall back to the Census Gazetteer place centroid.",
            "Public output keeps municipal coordinates but withholds the matched town-hall name and street-address fields.",
        ],
    }
    private_metadata = {
        "generated_at_utc": public_metadata["generated_at_utc"],
        "source_files": public_metadata["source_files"],
        "output_file": str(PRIVATE_OUT_CSV.relative_to(ROOT)),
        "municipality_count": len(private_rows),
        "town_hall_coordinate_matches": matched_count,
        "census_centroid_fallbacks": fallback_count,
        "population_total_2024": total_population,
        "notes": [
            "Private output retains matched town-hall names, addresses, and explicit town-hall coordinates where available.",
        ],
    }
    return public_rows, private_rows, public_metadata, private_metadata


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    if not POPULATION_CSV.exists():
        raise FileNotFoundError(f"Missing population file: {POPULATION_CSV}")
    if not GAZETTEER_TXT.exists():
        raise FileNotFoundError(f"Missing Gazetteer file: {GAZETTEER_TXT}")

    public_rows, private_rows, public_metadata, private_metadata = build_rows()
    if not public_rows or not private_rows:
        raise ValueError("No municipal population rows were built")

    write_csv(PUBLIC_OUT_CSV, public_rows)
    write_csv(PRIVATE_OUT_CSV, private_rows)
    PUBLIC_METADATA_JSON.write_text(json.dumps(public_metadata, indent=2), encoding="utf-8")
    PRIVATE_METADATA_JSON.write_text(json.dumps(private_metadata, indent=2), encoding="utf-8")

    print(f"Wrote {len(public_rows)} public municipal population rows to {PUBLIC_OUT_CSV}")
    print(f"Wrote {len(private_rows)} private municipal population rows to {PRIVATE_OUT_CSV}")


if __name__ == "__main__":
    main()
