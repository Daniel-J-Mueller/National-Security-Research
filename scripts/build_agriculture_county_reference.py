#!/usr/bin/env python3
"""
Build coordinate-backed agriculture outputs from the USDA 2022 Ag Census web maps.
"""

from __future__ import annotations

import csv
import json
from datetime import UTC, datetime
from pathlib import Path

from xlsx_utils import clean_text, read_sheet_rows


ROOT = Path(__file__).resolve().parents[1]
WORKBOOK = ROOT / "data" / "raw" / "agriculture" / "usda" / "NASSAgCensusDownload2022_175maps_Links.xlsx"
COUNTY_GAZETTEER = (
    ROOT
    / "data"
    / "raw"
    / "agriculture"
    / "census"
    / "2024_Gaz_counties_national"
    / "2024_Gaz_counties_national.txt"
)

PUBLIC_DIR = ROOT / "data" / "public" / "agriculture"
PRIVATE_DIR = ROOT / "data" / "private" / "agriculture"
PUBLIC_CSV = PUBLIC_DIR / "county_food_outputs_2022.csv"
PRIVATE_CSV = PRIVATE_DIR / "county_food_outputs_2022_private.csv"
PUBLIC_METADATA_JSON = PUBLIC_DIR / "county_food_outputs_2022_metadata.json"
PRIVATE_METADATA_JSON = PRIVATE_DIR / "county_food_outputs_2022_private_metadata.json"

SELECTED_METRICS = [
    {
        "key": "vegetables_market_value_share_pct",
        "map_id": "y22_M013",
        "sheet": "Economics",
        "label": "Vegetables, Melons, Potatoes, and Sweet Potatoes Market Value Share",
        "unit": "percent",
    },
    {
        "key": "fruits_tree_nuts_berries_market_value_share_pct",
        "map_id": "y22_M014",
        "sheet": "Economics",
        "label": "Fruits, Tree Nuts, and Berries Market Value Share",
        "unit": "percent",
    },
    {
        "key": "poultry_eggs_market_value_share_pct",
        "map_id": "y22_M018",
        "sheet": "Economics",
        "label": "Poultry and Eggs Market Value Share",
        "unit": "percent",
    },
    {
        "key": "milk_from_cows_market_value_share_pct",
        "map_id": "y22_M019",
        "sheet": "Economics",
        "label": "Milk from Cows Market Value Share",
        "unit": "percent",
    },
    {
        "key": "cattle_calves_market_value_share_pct",
        "map_id": "y22_M020",
        "sheet": "Economics",
        "label": "Cattle and Calves Market Value Share",
        "unit": "percent",
    },
    {
        "key": "hogs_pigs_market_value_share_pct",
        "map_id": "y22_M021",
        "sheet": "Economics",
        "label": "Hogs and Pigs Market Value Share",
        "unit": "percent",
    },
    {
        "key": "cattle_calves_per_100_acres",
        "map_id": "y22_M098",
        "sheet": "Livestock and Animals",
        "label": "Cattle and Calves per 100 Acres of All Land in Farms",
        "unit": "cattle_and_calves",
    },
    {
        "key": "milk_cows_inventory",
        "map_id": "y22_M099",
        "sheet": "Livestock and Animals",
        "label": "Cows and Heifers That Had Calved Inventory",
        "unit": "cows_and_heifers",
    },
    {
        "key": "cattle_calves_sold_count",
        "map_id": "y22_M101",
        "sheet": "Livestock and Animals",
        "label": "Cattle and Calves Sold",
        "unit": "cattle_and_calves",
    },
    {
        "key": "corn_grain_harvested_share_pct",
        "map_id": "y22_M107",
        "sheet": "Crops and Plants",
        "label": "Corn Grain Harvested Share of Harvested Cropland",
        "unit": "percent",
    },
    {
        "key": "all_wheat_harvested_share_pct",
        "map_id": "y22_M112",
        "sheet": "Crops and Plants",
        "label": "All Wheat Harvested Share of Harvested Cropland",
        "unit": "percent",
    },
    {
        "key": "soybeans_harvested_share_pct",
        "map_id": "y22_M126",
        "sheet": "Crops and Plants",
        "label": "Soybeans Harvested Share of Harvested Cropland",
        "unit": "percent",
    },
    {
        "key": "potatoes_harvested_share_pct",
        "map_id": "y22_M129",
        "sheet": "Crops and Plants",
        "label": "Potatoes Harvested Share of Harvested Cropland",
        "unit": "percent",
    },
    {
        "key": "vegetables_harvested_share_pct",
        "map_id": "y22_M141",
        "sheet": "Crops and Plants",
        "label": "Vegetables Harvested Share of Harvested Cropland",
        "unit": "percent",
    },
]

GROUP_METRIC_KEYS = [
    "vegetables_market_value_share_pct",
    "fruits_tree_nuts_berries_market_value_share_pct",
    "poultry_eggs_market_value_share_pct",
    "milk_from_cows_market_value_share_pct",
    "cattle_calves_market_value_share_pct",
    "hogs_pigs_market_value_share_pct",
    "corn_grain_harvested_share_pct",
    "all_wheat_harvested_share_pct",
    "soybeans_harvested_share_pct",
    "potatoes_harvested_share_pct",
    "vegetables_harvested_share_pct",
]

STATUS_ORDER = {
    "reported_numeric": 3,
    "withheld_disclosure": 2,
    "class_range_only": 1,
    "blank": 0,
}


def to_float(value: str | None) -> float | None:
    text = clean_text(value)
    if not text:
        return None
    try:
        return float(text.replace(",", ""))
    except ValueError:
        return None


def to_string_number(value: float | None) -> str:
    if value is None:
        return ""
    if value.is_integer():
        return str(int(value))
    return f"{value:.6f}".rstrip("0").rstrip(".")


def load_counties() -> dict[str, dict[str, str]]:
    counties: dict[str, dict[str, str]] = {}
    with COUNTY_GAZETTEER.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        for row in reader:
            cleaned_row = {clean_text(key): clean_text(value) for key, value in row.items() if key}
            geoid = clean_text(cleaned_row.get("GEOID"))
            if not geoid:
                continue
            counties[geoid] = {
                "state": clean_text(cleaned_row.get("USPS")),
                "county_name": clean_text(cleaned_row.get("NAME")),
                "latitude": clean_text(cleaned_row.get("INTPTLAT")),
                "longitude": clean_text(cleaned_row.get("INTPTLONG")),
                "land_area_sqmi": clean_text(cleaned_row.get("ALAND_SQMI")),
                "water_area_sqmi": clean_text(cleaned_row.get("AWATER_SQMI")),
            }
    return counties


def load_metric_rows() -> dict[str, dict[str, str]]:
    rows_by_sheet: dict[str, dict[str, dict[str, str]]] = {}
    for sheet_name in sorted({metric["sheet"] for metric in SELECTED_METRICS}):
        _headers, rows = read_sheet_rows(WORKBOOK, sheet_name, header_row_number=1)
        rows_by_sheet[sheet_name] = {
            clean_text(row.get("FIPSTEXT")).zfill(5): row
            for row in rows
            if clean_text(row.get("FIPSTEXT")) and clean_text(row.get("FIPSTEXT")) != "00000"
        }
    return {
        sheet_name: row_map
        for sheet_name, row_map in rows_by_sheet.items()
    }


def metric_status(numeric_value: str, value_text: str, class_range: str) -> str:
    if clean_text(numeric_value):
        return "reported_numeric"
    if clean_text(value_text) == "(D)":
        return "withheld_disclosure"
    if clean_text(class_range):
        return "class_range_only"
    return "blank"


def dominant_output_profile(row: dict[str, str]) -> str:
    best_key = ""
    best_value = float("-inf")
    for metric in SELECTED_METRICS:
        if metric["key"] not in GROUP_METRIC_KEYS:
            continue
        value = to_float(row.get(metric["key"]))
        if value is None or value <= best_value:
            continue
        best_value = value
        best_key = metric["key"]
    if not best_key:
        return "No dominant food signal"
    label = next(metric["label"] for metric in SELECTED_METRICS if metric["key"] == best_key)
    return label


def build_rows() -> tuple[list[dict[str, str]], list[dict[str, str]], dict[str, object], dict[str, object]]:
    counties = load_counties()
    sheet_rows = load_metric_rows()

    public_rows: list[dict[str, str]] = []
    private_rows: list[dict[str, str]] = []
    missing_county_coords = 0
    counties_with_metrics = 0

    all_geoids = sorted({geoid for rows in sheet_rows.values() for geoid in rows})
    for geoid in all_geoids:
        county = counties.get(geoid)
        if not county:
            missing_county_coords += 1
            continue

        counties_with_metrics += 1
        public_row = {
            "state": county["state"],
            "county_name": county["county_name"],
            "geoid": geoid,
            "latitude": county["latitude"],
            "longitude": county["longitude"],
            "geometry_precision": "county_centroid",
            "land_area_sqmi": county["land_area_sqmi"],
            "water_area_sqmi": county["water_area_sqmi"],
            "reporting_year": "2022",
            "source_dataset": "USDA NASS 2022 Ag Census Web Maps",
            "coordinate_source": "Census Gazetteer 2024 county centroid",
        }
        private_row = dict(public_row)

        withheld_metric_count = 0
        for metric in SELECTED_METRICS:
            row = sheet_rows[metric["sheet"]].get(geoid, {})
            numeric_column = f"{metric['map_id']}_valueNumeric"
            text_column = f"{metric['map_id']}_valueText"
            class_column = f"{metric['map_id']}_classRange"

            numeric_value = clean_text(row.get(numeric_column))
            value_text = clean_text(row.get(text_column))
            class_range = clean_text(row.get(class_column))
            status = metric_status(numeric_value, value_text, class_range)

            if status != "reported_numeric" and status != "blank":
                withheld_metric_count += 1

            public_row[metric["key"]] = numeric_value
            private_row[metric["key"]] = numeric_value
            private_row[f"{metric['key']}_value_text"] = value_text
            private_row[f"{metric['key']}_class_range"] = class_range
            private_row[f"{metric['key']}_status"] = status

        public_row["withheld_metric_count"] = str(withheld_metric_count)
        private_row["withheld_metric_count"] = str(withheld_metric_count)
        public_row["dominant_output_profile"] = dominant_output_profile(public_row)
        private_row["dominant_output_profile"] = public_row["dominant_output_profile"]

        public_rows.append(public_row)
        private_rows.append(private_row)

    public_metadata = {
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "source_files": [
            str(WORKBOOK.relative_to(ROOT)),
            str(COUNTY_GAZETTEER.relative_to(ROOT)),
        ],
        "output_file": str(PUBLIC_CSV.relative_to(ROOT)),
        "county_count": len(public_rows),
        "selected_metric_count": len(SELECTED_METRICS),
        "missing_county_coordinates": missing_county_coords,
        "notes": [
            "Coordinates come from Census Gazetteer county centroids.",
            "Public output keeps the numeric values and a per-county withheld metric count.",
            "Some selected USDA measures are shares or inventories rather than absolute tonnage because those are the county-level web-map fields published in the official workbook.",
        ],
        "selected_metrics": [
            {
                "key": metric["key"],
                "map_id": metric["map_id"],
                "sheet": metric["sheet"],
                "label": metric["label"],
                "unit": metric["unit"],
            }
            for metric in SELECTED_METRICS
        ],
    }
    private_metadata = {
        "generated_at_utc": public_metadata["generated_at_utc"],
        "source_files": public_metadata["source_files"],
        "output_file": str(PRIVATE_CSV.relative_to(ROOT)),
        "county_count": len(private_rows),
        "selected_metric_count": len(SELECTED_METRICS),
        "missing_county_coordinates": missing_county_coords,
        "notes": [
            "Private output retains USDA value text, class ranges, and disclosure-status flags for each selected metric.",
            "Rows still use county centroids rather than farm-level locations.",
        ],
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
    if not WORKBOOK.exists():
        raise FileNotFoundError(f"Missing workbook: {WORKBOOK}")
    if not COUNTY_GAZETTEER.exists():
        raise FileNotFoundError(f"Missing county gazetteer: {COUNTY_GAZETTEER}")

    public_rows, private_rows, public_metadata, private_metadata = build_rows()
    if not public_rows or not private_rows:
        raise ValueError("No agriculture rows were built")

    write_csv(PUBLIC_CSV, public_rows)
    write_csv(PRIVATE_CSV, private_rows)
    PUBLIC_METADATA_JSON.write_text(json.dumps(public_metadata, indent=2), encoding="utf-8")
    PRIVATE_METADATA_JSON.write_text(json.dumps(private_metadata, indent=2), encoding="utf-8")

    print(f"Wrote {len(public_rows)} public agriculture rows to {PUBLIC_CSV}")
    print(f"Wrote {len(private_rows)} private agriculture rows to {PRIVATE_CSV}")


if __name__ == "__main__":
    main()
