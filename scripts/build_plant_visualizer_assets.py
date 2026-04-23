#!/usr/bin/env python3
"""
Build browser-ready visualizer assets for electrical, people, agriculture, and raws.
"""

from __future__ import annotations

import csv
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

PLANT_PROFILE_CSV = ROOT / "data" / "private" / "electrical" / "eia860_2024" / "plant_profiles_private.csv"
PLANT_DETAILS_CSV = ROOT / "data" / "processed" / "electrical" / "eia860" / "plants_2024_clean.csv"
PLANT_COORDS_CSV = ROOT / "data" / "private" / "electrical" / "eia860_2024" / "plant_locations_private.csv"
LEGACY_OUT_DIR = ROOT / "data" / "private" / "electrical" / "visualizer"
LEGACY_OUT_JSON = LEGACY_OUT_DIR / "plants_reference.json"
LEGACY_OUT_SUMMARY_JSON = LEGACY_OUT_DIR / "plants_reference_summary.json"

PEOPLE_PRIVATE_CSV = ROOT / "data" / "private" / "people" / "municipal_population_town_halls_2024_private.csv"
AGRICULTURE_PRIVATE_CSV = ROOT / "data" / "private" / "agriculture" / "county_food_outputs_2022_private.csv"
RAWS_PRIVATE_CSV = ROOT / "data" / "private" / "raws" / "raw_material_sites_2023_private.csv"
RADIATION_PRIVATE_CSV = ROOT / "data" / "private" / "radiation" / "radnet_background_radiation_monitors_private.csv"

VISUALIZER_OUT_DIR = ROOT / "data" / "private" / "visualizer"
VISUALIZER_DATASET_DIR = VISUALIZER_OUT_DIR / "datasets"
VISUALIZER_MANIFEST_JSON = VISUALIZER_OUT_DIR / "visualizer_manifest.json"

MAX_REPO_FILE_BYTES = 75_000_000
DATASET_SHARD_TARGET_BYTES = 50_000_000

BASE_METRICS = [
    "generator_count",
    "operable_nameplate_capacity_mw",
    "operable_summer_capacity_mw",
    "operable_winter_capacity_mw",
    "carbon_capture_generator_count",
    "co2_emissions_value",
    "co2e_emissions_value",
    "ch4_emissions_value",
    "n2o_emissions_value",
    "so2_emissions_value",
    "nox_emissions_value",
    "particulate_matter_emissions_value",
    "mercury_emissions_value",
    "radioisotopic_emissions_value",
]

ELECTRICAL_METRICS = [
    {"key": "generator_count", "label": "Generator Count", "unit": "count"},
    {"key": "operable_nameplate_capacity_mw", "label": "Operable Nameplate Capacity", "unit": "MW"},
    {"key": "operable_summer_capacity_mw", "label": "Operable Summer Capacity", "unit": "MW"},
    {"key": "operable_winter_capacity_mw", "label": "Operable Winter Capacity", "unit": "MW"},
    {"key": "carbon_capture_generator_count", "label": "Carbon Capture Generator Count", "unit": "count"},
    {"key": "co2_emissions_value", "label": "CO2 Emissions", "unit": "tons"},
    {"key": "co2e_emissions_value", "label": "CO2e Emissions", "unit": "tons"},
    {"key": "ch4_emissions_value", "label": "CH4 Emissions", "unit": "lb"},
    {"key": "n2o_emissions_value", "label": "N2O Emissions", "unit": "lb"},
    {"key": "so2_emissions_value", "label": "SO2 Emissions", "unit": "tons"},
    {"key": "nox_emissions_value", "label": "NOx Emissions", "unit": "tons"},
    {"key": "particulate_matter_emissions_value", "label": "Particulate Matter Emissions", "unit": "tons"},
    {"key": "mercury_emissions_value", "label": "Mercury Emissions", "unit": "lb"},
    {"key": "radioisotopic_emissions_value", "label": "Radioisotopic Emissions", "unit": "unknown"},
]

PEOPLE_METRICS = [
    {"key": "population_2024", "label": "Population 2024", "unit": "people"},
    {"key": "population_per_town_hall", "label": "Population per Town Hall", "unit": "people"},
    {"key": "matched_town_hall_rows_with_coordinates", "label": "Matched Town Hall Rows", "unit": "count"},
    {"key": "land_area_sqmi", "label": "Land Area", "unit": "sq_miles"},
]

AGRICULTURE_METRICS = [
    {"key": "vegetables_market_value_share_pct", "label": "Vegetables Market Value Share", "unit": "percent"},
    {"key": "fruits_tree_nuts_berries_market_value_share_pct", "label": "Fruits, Tree Nuts, and Berries Market Value Share", "unit": "percent"},
    {"key": "poultry_eggs_market_value_share_pct", "label": "Poultry and Eggs Market Value Share", "unit": "percent"},
    {"key": "milk_from_cows_market_value_share_pct", "label": "Milk from Cows Market Value Share", "unit": "percent"},
    {"key": "cattle_calves_market_value_share_pct", "label": "Cattle and Calves Market Value Share", "unit": "percent"},
    {"key": "hogs_pigs_market_value_share_pct", "label": "Hogs and Pigs Market Value Share", "unit": "percent"},
    {"key": "cattle_calves_per_100_acres", "label": "Cattle and Calves per 100 Acres", "unit": "count"},
    {"key": "milk_cows_inventory", "label": "Milk Cows Inventory", "unit": "count"},
    {"key": "cattle_calves_sold_count", "label": "Cattle and Calves Sold", "unit": "count"},
    {"key": "corn_grain_harvested_share_pct", "label": "Corn Harvested Share", "unit": "percent"},
    {"key": "all_wheat_harvested_share_pct", "label": "All Wheat Harvested Share", "unit": "percent"},
    {"key": "soybeans_harvested_share_pct", "label": "Soybeans Harvested Share", "unit": "percent"},
    {"key": "potatoes_harvested_share_pct", "label": "Potatoes Harvested Share", "unit": "percent"},
    {"key": "vegetables_harvested_share_pct", "label": "Vegetables Harvested Share", "unit": "percent"},
]

RAWS_METRICS = [
    {"key": "presence_count", "label": "Presence Count", "unit": "count"},
    {"key": "rank_score", "label": "USGS Rank Score", "unit": "score"},
    {"key": "production_present_flag", "label": "Production Present Flag", "unit": "flag"},
    {"key": "resources_present_flag", "label": "Resources Present Flag", "unit": "flag"},
    {"key": "total_reported_direct_emissions_mtco2e", "label": "Total Reported Direct Emissions", "unit": "mtco2e"},
    {"key": "iron_and_steel_production_emissions_mtco2e", "label": "Iron and Steel Production Emissions", "unit": "mtco2e"},
]

RADIATION_METRICS = [
    {"key": "dose_equivalent_rate_avg_nsvh", "label": "Average Dose Equivalent Rate", "unit": "nSv/h"},
    {"key": "dose_equivalent_rate_p95_nsvh", "label": "P95 Dose Equivalent Rate", "unit": "nSv/h"},
    {"key": "dose_equivalent_rate_max_nsvh", "label": "Max Dose Equivalent Rate", "unit": "nSv/h"},
    {"key": "gamma_count_rate_total_avg_cpm", "label": "Average Total Gamma Count Rate", "unit": "CPM"},
    {"key": "approved_dose_reading_count", "label": "Approved Dose Readings", "unit": "count"},
    {"key": "approved_sample_count", "label": "Approved Samples", "unit": "count"},
    {"key": "years_with_data_count", "label": "Years With Data", "unit": "count"},
]


def clean_text(value: str | None) -> str:
    if value is None:
        return ""
    return " ".join(str(value).replace("\xa0", " ").split())


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


def read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        headers = [clean_text(value) for value in (reader.fieldnames or [])]
        rows = [{key: clean_text(value) for key, value in row.items()} for row in reader]
        return headers, rows


def join_profile_rows() -> tuple[list[str], list[dict[str, object]]]:
    rows: list[dict[str, object]] = []
    headers, profile_rows = read_csv(PLANT_PROFILE_CSV)
    for row in profile_rows:
        plant_code = row.get("plant_code", "")
        latitude = parse_float(row.get("latitude"))
        longitude = parse_float(row.get("longitude"))
        if not plant_code or latitude is None or longitude is None:
            continue

        rows.append(
            {
                "plant_code": plant_code,
                "plant_name": row.get("plant_name", ""),
                "utility_id": row.get("utility_id", ""),
                "utility_name": row.get("utility_name", ""),
                "city": row.get("city", ""),
                "county": row.get("county", ""),
                "state": row.get("state", ""),
                "zip_code": row.get("zip_code", ""),
                "latitude": round(latitude, 6),
                "longitude": round(longitude, 6),
                "coordinate_status": row.get("coordinate_status", ""),
                "nerc_region": row.get("nerc_region", ""),
                "balancing_authority_code": row.get("balancing_authority_code", ""),
                "balancing_authority_name": row.get("balancing_authority_name", ""),
                "sector_name": row.get("sector_name", ""),
                "regulatory_status": row.get("regulatory_status", ""),
                "transmission_owner": row.get("transmission_owner", ""),
                "energy_storage_flag": row.get("energy_storage_flag", ""),
                "generator_count": parse_int(row.get("generator_count")),
                "operable_nameplate_capacity_mw": parse_float(row.get("operable_nameplate_capacity_mw")),
                "operable_summer_capacity_mw": parse_float(row.get("operable_summer_capacity_mw")),
                "operable_winter_capacity_mw": parse_float(row.get("operable_winter_capacity_mw")),
                "primary_fuel_code": row.get("primary_fuel_code", ""),
                "primary_technology": row.get("primary_technology", ""),
                "status_mix": row.get("status_mix", ""),
                "carbon_capture_generator_count": parse_int(row.get("carbon_capture_generator_count")),
                "carbon_capture_present_flag": row.get("carbon_capture_present_flag", ""),
                "co2_emissions_value": parse_float(row.get("co2_emissions_value")),
                "co2_emissions_unit": row.get("co2_emissions_unit", ""),
                "co2e_emissions_value": parse_float(row.get("co2e_emissions_value")),
                "co2e_emissions_unit": row.get("co2e_emissions_unit", ""),
                "ch4_emissions_value": parse_float(row.get("ch4_emissions_value")),
                "ch4_emissions_unit": row.get("ch4_emissions_unit", ""),
                "n2o_emissions_value": parse_float(row.get("n2o_emissions_value")),
                "n2o_emissions_unit": row.get("n2o_emissions_unit", ""),
                "so2_emissions_value": parse_float(row.get("so2_emissions_value")),
                "so2_emissions_unit": row.get("so2_emissions_unit", ""),
                "nox_emissions_value": parse_float(row.get("nox_emissions_value")),
                "nox_emissions_unit": row.get("nox_emissions_unit", ""),
                "particulate_matter_emissions_value": parse_float(row.get("particulate_matter_emissions_value")),
                "particulate_matter_emissions_unit": row.get("particulate_matter_emissions_unit", ""),
                "mercury_emissions_value": parse_float(row.get("mercury_emissions_value")),
                "mercury_emissions_unit": row.get("mercury_emissions_unit", ""),
                "radioisotopic_emissions_value": parse_float(row.get("radioisotopic_emissions_value")),
                "radioisotopic_emissions_unit": row.get("radioisotopic_emissions_unit", ""),
                "source_dataset": row.get("source_dataset", "EIA-860 2024"),
                "raw_row": [row.get(header, "") for header in headers],
            }
        )

    rows.sort(
        key=lambda item: (
            str(item.get("state", "")),
            str(item.get("county", "")),
            str(item.get("plant_name", "")),
            str(item.get("plant_code", "")),
        )
    )
    return headers, rows


def join_rows() -> tuple[list[str], list[dict[str, object]]]:
    if PLANT_PROFILE_CSV.exists():
        return join_profile_rows()

    _detail_headers, detail_rows = read_csv(PLANT_DETAILS_CSV)
    detail_by_code = {row["plant_code"]: row for row in detail_rows if row.get("plant_code")}

    joined_rows: list[dict[str, object]] = []
    _coord_headers, coord_rows = read_csv(PLANT_COORDS_CSV)
    for row in coord_rows:
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
    fallback_headers = [key for key in joined_rows[0].keys() if key != "raw_row"] if joined_rows else []
    return fallback_headers, joined_rows


def build_legacy_summary(rows: list[dict[str, object]]) -> dict[str, object]:
    state_counts = Counter(str(row["state"]) for row in rows if row.get("state"))
    fuel_counts = Counter(str(row["primary_fuel_code"]) for row in rows if row.get("primary_fuel_code"))
    source_files = [str(PLANT_PROFILE_CSV.relative_to(ROOT))] if PLANT_PROFILE_CSV.exists() else [
        str(PLANT_DETAILS_CSV.relative_to(ROOT)),
        str(PLANT_COORDS_CSV.relative_to(ROOT)),
    ]

    latitudes = [float(row["latitude"]) for row in rows]
    longitudes = [float(row["longitude"]) for row in rows]
    total_nameplate = sum(float(row["operable_nameplate_capacity_mw"] or 0) for row in rows)

    return {
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "source_files": source_files,
        "output_file": str(LEGACY_OUT_JSON.relative_to(ROOT)),
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
    write_text_atomic(path, json.dumps(payload, indent=2))


def write_text_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f".{path.name}.tmp")
    temp_path.write_text(text, encoding="utf-8")
    temp_path.replace(path)


def compact_json_text(payload: object) -> str:
    return json.dumps(payload, ensure_ascii=True, separators=(",", ":"))


def byte_count(text: str) -> int:
    return len(text.encode("utf-8"))


def dataset_manifest_path(key: str) -> Path:
    return VISUALIZER_DATASET_DIR / key / "manifest.json"


def app_relative_dataset_manifest_path(key: str) -> str:
    return f"../../data/private/visualizer/datasets/{key}/manifest.json"


def app_relative_dataset_shard_path(key: str, filename: str) -> str:
    return f"../../data/private/visualizer/datasets/{key}/{filename}"


def search_text(parts: list[str]) -> str:
    return " ".join(clean_text(part) for part in parts if clean_text(part)).lower()


def build_bounds(records: list[dict[str, object]]) -> dict[str, float]:
    latitudes = [float(record["latitude"]) for record in records]
    longitudes = [float(record["longitude"]) for record in records]
    return {
        "min_latitude": min(latitudes),
        "max_latitude": max(latitudes),
        "min_longitude": min(longitudes),
        "max_longitude": max(longitudes),
    }


def dataset_output_path(key: str) -> Path:
    return VISUALIZER_DATASET_DIR / f"{key}.json"


def app_relative_dataset_path(key: str) -> str:
    return f"../../data/private/visualizer/datasets/{key}.json"


def remove_stale_dataset_assets(key: str, *, keep_shards: bool) -> None:
    single_path = dataset_output_path(key)
    shard_dir = dataset_manifest_path(key).parent
    if keep_shards:
        if single_path.exists():
            single_path.unlink()
        if shard_dir.exists():
            for shard_path in shard_dir.glob("*.json"):
                shard_path.unlink()
        shard_dir.mkdir(parents=True, exist_ok=True)
        return

    if shard_dir.exists():
        for shard_path in shard_dir.glob("*.json"):
            shard_path.unlink()


def write_dataset_assets(
    key: str,
    payload: dict[str, object],
    manifest_entry: dict[str, object],
) -> dict[str, object]:
    single_text = json.dumps(payload, indent=2)
    if byte_count(single_text) <= MAX_REPO_FILE_BYTES:
        remove_stale_dataset_assets(key, keep_shards=False)
        output_path = dataset_output_path(key)
        write_text_atomic(output_path, single_text)
        manifest_entry["path"] = app_relative_dataset_path(key)
        manifest_entry.pop("sharded", None)
        manifest_entry.pop("shard_count", None)
        return manifest_entry

    return write_sharded_dataset_assets(key, payload, manifest_entry)


def write_sharded_dataset_assets(
    key: str,
    payload: dict[str, object],
    manifest_entry: dict[str, object],
) -> dict[str, object]:
    records = payload.get("records")
    if not isinstance(records, list) or not records:
        raise ValueError(f"Cannot shard dataset {key}: payload does not contain records")

    remove_stale_dataset_assets(key, keep_shards=True)
    shard_dir = dataset_manifest_path(key).parent
    shard_entries: list[dict[str, object]] = []
    current_records: list[str] = []
    current_bytes = byte_count('{"records":[]}')

    def flush_shard() -> None:
        nonlocal current_records, current_bytes
        if not current_records:
            return

        filename = f"part-{len(shard_entries) + 1:04d}.json"
        shard_text = '{"records":[' + ",".join(current_records) + "]}"
        shard_size = byte_count(shard_text)
        if shard_size > MAX_REPO_FILE_BYTES:
            raise ValueError(
                f"Shard {filename} for dataset {key} would be {shard_size:,} bytes, "
                f"above the {MAX_REPO_FILE_BYTES:,}-byte repository limit."
            )

        write_text_atomic(shard_dir / filename, shard_text)
        shard_entries.append(
            {
                "file": filename,
                "path": app_relative_dataset_shard_path(key, filename),
                "record_count": len(current_records),
                "bytes": shard_size,
            }
        )
        current_records = []
        current_bytes = byte_count('{"records":[]}')

    for record in records:
        record_text = compact_json_text(record)
        record_size = byte_count(record_text)
        separator_size = 1 if current_records else 0
        projected_size = current_bytes + separator_size + record_size
        if current_records and projected_size > DATASET_SHARD_TARGET_BYTES:
            flush_shard()
            separator_size = 0
            projected_size = current_bytes + record_size

        current_records.append(record_text)
        current_bytes = projected_size

    flush_shard()

    sharded_payload = {
        key_name: value
        for key_name, value in payload.items()
        if key_name != "records"
    }
    metadata = dict(sharded_payload.get("metadata") or {})
    metadata["output_file"] = str(dataset_manifest_path(key).relative_to(ROOT))
    metadata["shard_count"] = len(shard_entries)
    metadata["shard_target_bytes"] = DATASET_SHARD_TARGET_BYTES
    sharded_payload["metadata"] = metadata
    sharded_payload["sharded"] = True
    sharded_payload["record_count"] = len(records)
    sharded_payload["shards"] = shard_entries
    write_json(dataset_manifest_path(key), sharded_payload)

    manifest_entry["path"] = app_relative_dataset_manifest_path(key)
    manifest_entry["sharded"] = True
    manifest_entry["shard_count"] = len(shard_entries)
    return manifest_entry


def build_dataset_payload(
    *,
    key: str,
    label: str,
    source_csv: Path,
    metrics: list[dict[str, str]],
    default_metric_key: str,
    group_field: str,
    group_label: str,
    results_label: str,
    search_placeholder: str,
    description: str,
    build_id,
    build_title,
    build_subtitle,
    build_search_parts,
) -> tuple[dict[str, object], dict[str, object]]:
    headers, rows = read_csv(source_csv)
    records: list[dict[str, object]] = []
    states = set()
    groups = set()

    for index, row in enumerate(rows, start=1):
        latitude = parse_float(row.get("latitude"))
        longitude = parse_float(row.get("longitude"))
        if latitude is None or longitude is None:
            continue

        metrics_payload = {}
        for metric in metrics:
            value = parse_float(row.get(metric["key"]))
            if value is not None:
                metrics_payload[metric["key"]] = value

        group_value = clean_text(row.get(group_field)) or "Unspecified"
        state_value = clean_text(row.get("state"))
        county_value = clean_text(row.get("county")) or clean_text(row.get("county_name"))
        title = clean_text(build_title(row, index))

        record = {
            "id": clean_text(build_id(row, index)),
            "title": title or f"{label} {index}",
            "subtitle": clean_text(build_subtitle(row)),
            "state": state_value,
            "county": county_value,
            "latitude": round(latitude, 6),
            "longitude": round(longitude, 6),
            "group_value": group_value,
            "group_display": group_value,
            "search_text": search_text(build_search_parts(row)),
            "metrics": metrics_payload,
            "row": row,
        }
        records.append(record)
        if state_value:
            states.add(state_value)
        if group_value:
            groups.add(group_value)

    if not records:
        raise ValueError(f"No mappable records were built for {key}")

    payload = {
        "metadata": {
            "category_key": key,
            "category_label": label,
            "description": description,
            "default_metric_key": default_metric_key,
            "group_field": group_field,
            "group_label": group_label,
            "results_label": results_label,
            "search_placeholder": search_placeholder,
            "source_files": [str(source_csv.relative_to(ROOT))],
            "output_file": str(dataset_output_path(key).relative_to(ROOT)),
            "record_count": len(records),
            "states": sorted(states),
            "group_values": sorted(groups),
            "metrics": metrics,
            "bounds": build_bounds(records),
        },
        "headers": headers,
        "records": records,
    }
    manifest_entry = {
        "key": key,
        "label": label,
        "path": app_relative_dataset_path(key),
        "record_count": len(records),
        "default_metric_key": default_metric_key,
        "group_label": group_label,
        "description": description,
    }
    return payload, manifest_entry


def build_electrical_dataset() -> tuple[dict[str, object], dict[str, object]]:
    headers, rows = read_csv(PLANT_PROFILE_CSV)
    records: list[dict[str, object]] = []
    states = set()
    groups = set()

    for index, row in enumerate(rows, start=1):
        latitude = parse_float(row.get("latitude"))
        longitude = parse_float(row.get("longitude"))
        if latitude is None or longitude is None:
            continue

        metrics_payload = {}
        for metric in ELECTRICAL_METRICS:
            value = parse_float(row.get(metric["key"]))
            if value is not None:
                metrics_payload[metric["key"]] = value

        fuel_code = clean_text(row.get("primary_fuel_code")) or "Unspecified"
        state_value = clean_text(row.get("state"))
        county_value = clean_text(row.get("county"))
        record = {
            "id": clean_text(row.get("plant_code")) or f"plant-{index}",
            "title": clean_text(row.get("plant_name")) or f"Plant {index}",
            "subtitle": " | ".join(
                part
                for part in [
                    f"{county_value}, {state_value}" if county_value and state_value else county_value or state_value,
                    fuel_code,
                    clean_text(row.get("primary_technology")),
                ]
                if part
            ),
            "state": state_value,
            "county": county_value,
            "latitude": round(latitude, 6),
            "longitude": round(longitude, 6),
            "group_value": fuel_code,
            "group_display": fuel_code,
            "search_text": search_text(
                [
                    row.get("plant_code"),
                    row.get("plant_name"),
                    row.get("utility_name"),
                    row.get("street_address"),
                    row.get("city"),
                    row.get("county"),
                    row.get("state"),
                    row.get("primary_fuel_code"),
                    row.get("primary_technology"),
                ]
            ),
            "metrics": metrics_payload,
            "row": row,
        }
        records.append(record)
        if state_value:
            states.add(state_value)
        groups.add(fuel_code)

    payload = {
        "metadata": {
            "category_key": "electrical",
            "category_label": "Electrical",
            "description": "Private plant-level electrical generation and emissions records.",
            "default_metric_key": "co2_emissions_value",
            "group_field": "primary_fuel_code",
            "group_label": "Fuel",
            "results_label": "Plants",
            "search_placeholder": "Search plant, utility, county, or code",
            "source_files": [str(PLANT_PROFILE_CSV.relative_to(ROOT))],
            "output_file": str(dataset_output_path("electrical").relative_to(ROOT)),
            "record_count": len(records),
            "states": sorted(states),
            "group_values": sorted(groups),
            "metrics": ELECTRICAL_METRICS,
            "bounds": build_bounds(records),
        },
        "headers": headers,
        "records": records,
    }
    manifest_entry = {
        "key": "electrical",
        "label": "Electrical",
        "path": app_relative_dataset_path("electrical"),
        "record_count": len(records),
        "default_metric_key": "co2_emissions_value",
        "group_label": "Fuel",
        "description": payload["metadata"]["description"],
    }
    return payload, manifest_entry


def build_people_dataset() -> tuple[dict[str, object], dict[str, object]]:
    return build_dataset_payload(
        key="people",
        label="People",
        source_csv=PEOPLE_PRIVATE_CSV,
        metrics=PEOPLE_METRICS,
        default_metric_key="population_2024",
        group_field="dominant_people_profile",
        group_label="Coordinate Basis",
        results_label="Municipalities",
        search_placeholder="Search municipality, state, or town hall",
        description="Municipal population points anchored to matched town halls where available.",
        build_id=lambda row, index: row.get("geoid") or f"people-{index}",
        build_title=lambda row, index: row.get("place_name") or row.get("census_name") or f"Municipality {index}",
        build_subtitle=lambda row: " | ".join(
            part
            for part in [
                clean_text(row.get("state_name")) or clean_text(row.get("state")),
                f"Population {clean_text(row.get('population_2024'))}" if clean_text(row.get("population_2024")) else "",
            ]
            if part
        ),
        build_search_parts=lambda row: [
            row.get("place_name"),
            row.get("census_name"),
            row.get("state"),
            row.get("state_name"),
            row.get("town_hall_name"),
            row.get("town_hall_locality"),
        ],
    )


def build_agriculture_dataset() -> tuple[dict[str, object], dict[str, object]]:
    return build_dataset_payload(
        key="agriculture",
        label="Agriculture",
        source_csv=AGRICULTURE_PRIVATE_CSV,
        metrics=AGRICULTURE_METRICS,
        default_metric_key="corn_grain_harvested_share_pct",
        group_field="dominant_output_profile",
        group_label="Dominant Output",
        results_label="Counties",
        search_placeholder="Search county, state, or output profile",
        description="County-level food-output proxies from the USDA 2022 Ag Census web maps.",
        build_id=lambda row, index: row.get("geoid") or f"agriculture-{index}",
        build_title=lambda row, index: row.get("county_name") or f"Agriculture County {index}",
        build_subtitle=lambda row: " | ".join(
            part
            for part in [
                clean_text(row.get("state")),
                clean_text(row.get("dominant_output_profile")),
            ]
            if part
        ),
        build_search_parts=lambda row: [
            row.get("county_name"),
            row.get("state"),
            row.get("dominant_output_profile"),
        ],
    )


def build_raws_dataset() -> tuple[dict[str, object], dict[str, object]]:
    return build_dataset_payload(
        key="raws",
        label="Raws",
        source_csv=RAWS_PRIVATE_CSV,
        metrics=RAWS_METRICS,
        default_metric_key="presence_count",
        group_field="dominant_raws_profile",
        group_label="Asset Type",
        results_label="Sites",
        search_placeholder="Search site, state, material, or facility",
        description="Coordinate-backed ore sites and steel facilities from official USGS and EPA sources.",
        build_id=lambda row, index: row.get("asset_id") or f"raws-{index}",
        build_title=lambda row, index: row.get("site_name") or f"Raw Site {index}",
        build_subtitle=lambda row: " | ".join(
            part
            for part in [
                clean_text(row.get("state")),
                clean_text(row.get("asset_type")).replace("_", " ").title(),
                clean_text(row.get("primary_material")),
            ]
            if part
        ),
        build_search_parts=lambda row: [
            row.get("site_name"),
            row.get("state"),
            row.get("county"),
            row.get("primary_material"),
            row.get("critical_materials"),
            row.get("ghgrp_primary_naics_code"),
        ],
    )


def build_radiation_dataset() -> tuple[dict[str, object], dict[str, object]]:
    return build_dataset_payload(
        key="radiation",
        label="Radiation",
        source_csv=RADIATION_PRIVATE_CSV,
        metrics=RADIATION_METRICS,
        default_metric_key="dose_equivalent_rate_avg_nsvh",
        group_field="background_radiation_band",
        group_label="Background Band",
        results_label="Monitors",
        search_placeholder="Search monitor, city, state, or radiation band",
        description="EPA RadNet station summaries for ambient gamma background and dose-equivalent measurements.",
        build_id=lambda row, index: row.get("station_id") or f"radiation-{index}",
        build_title=lambda row, index: row.get("station_name") or row.get("place_name") or f"Radiation Monitor {index}",
        build_subtitle=lambda row: " | ".join(
            part
            for part in [
                clean_text(row.get("state_name")) or clean_text(row.get("state")),
                clean_text(row.get("background_radiation_band")),
                (
                    f"{clean_text(row.get('monitoring_year_start'))}-{clean_text(row.get('monitoring_year_end'))}"
                    if clean_text(row.get("monitoring_year_start")) and clean_text(row.get("monitoring_year_end"))
                    else ""
                ),
            ]
            if part
        ),
        build_search_parts=lambda row: [
            row.get("station_name"),
            row.get("place_name"),
            row.get("state"),
            row.get("state_name"),
            row.get("background_radiation_band"),
            row.get("dominant_radiation_profile"),
        ],
    )


def main() -> None:
    if not PLANT_PROFILE_CSV.exists() and not PLANT_DETAILS_CSV.exists():
        raise FileNotFoundError(f"Missing plant details CSV: {PLANT_DETAILS_CSV}")
    if not PLANT_PROFILE_CSV.exists() and not PLANT_COORDS_CSV.exists():
        raise FileNotFoundError(f"Missing plant coordinates CSV: {PLANT_COORDS_CSV}")
    for required in [PEOPLE_PRIVATE_CSV, AGRICULTURE_PRIVATE_CSV, RAWS_PRIVATE_CSV, RADIATION_PRIVATE_CSV]:
        if not required.exists():
            raise FileNotFoundError(f"Missing visualizer source CSV: {required}")

    legacy_headers, legacy_rows = join_rows()
    if not legacy_rows:
        raise ValueError("No joined plant rows were built")

    legacy_summary = build_legacy_summary(legacy_rows)
    write_json(
        LEGACY_OUT_JSON,
        {
            "metadata": legacy_summary,
            "headers": legacy_headers,
            "plants": legacy_rows,
        },
    )
    write_json(LEGACY_OUT_SUMMARY_JSON, legacy_summary)

    dataset_builders = [
        build_electrical_dataset,
        build_people_dataset,
        build_agriculture_dataset,
        build_raws_dataset,
        build_radiation_dataset,
    ]

    manifest = {
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "datasets": [],
    }
    for builder in dataset_builders:
        payload, manifest_entry = builder()
        manifest_entry = write_dataset_assets(manifest_entry["key"], payload, manifest_entry)
        manifest["datasets"].append(manifest_entry)

    write_json(VISUALIZER_MANIFEST_JSON, manifest)

    print(f"Wrote legacy electrical asset to {LEGACY_OUT_JSON}")
    print(f"Wrote category visualizer manifest to {VISUALIZER_MANIFEST_JSON}")


if __name__ == "__main__":
    main()
