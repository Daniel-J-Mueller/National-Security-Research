#!/usr/bin/env python3
"""
Build richer private plant profiles from EIA-860 plant, generator, and
environmental workbooks.
"""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile


ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data" / "raw" / "eia860" / "2024"
EPA_DIR = ROOT / "data" / "raw" / "epa"
PRIVATE_DIR = ROOT / "data" / "private" / "eia860_2024"
PROCESSED_DIR = ROOT / "data" / "processed" / "eia860"

PLANT_XLSX = RAW_DIR / "2___Plant_Y2024.xlsx"
GENERATOR_XLSX = RAW_DIR / "3_1_Generator_Y2024.xlsx"
ENVIRO_ASSOC_XLSX = RAW_DIR / "6_1_EnviroAssoc_Y2024.xlsx"
ENVIRO_EQUIP_XLSX = RAW_DIR / "6_2_EnviroEquip_Y2024.xlsx"
PLANT_DETAILS_CSV = PROCESSED_DIR / "plants_2024_clean.csv"
EGRID_XLSX = EPA_DIR / "egrid2023_data_rev2.xlsx"
EGRID_PM25_XLSX = EPA_DIR / "egrid_pm25_2018_2021.xlsx"

OUT_CSV = PRIVATE_DIR / "plant_profiles_private.csv"
OUT_METADATA_JSON = PRIVATE_DIR / "plant_profiles_private_metadata.json"
SOURCE_INVENTORY_CSV = PRIVATE_DIR / "source_inventory.csv"

NS = {"a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}

PLANT_SHEET = "Plant"
GENERATOR_SHEET = "Operable"
EMISSION_STANDARDS_SHEET = "Emission Standards & Strategies"
COOLING_SHEET = "Cooling"
FGP_SHEET = "FGP"
FGD_SHEET = "FGD"
STACK_FLUE_SHEET = "Stack Flue"
EGRID_UNIT_SHEET = "UNT23"
EGRID_PLANT_SHEET = "PLNT23"
EGRID_PM25_PLANT_SHEET = "2021 PM Plant-level Data"

YES_VALUES = {"y", "yes", "true", "1"}
NO_VALUES = {"n", "no", "false", "0"}

FIELDNAMES = [
    "plant_code",
    "plant_name",
    "utility_id",
    "utility_name",
    "street_address",
    "city",
    "county",
    "state",
    "zip_code",
    "latitude",
    "longitude",
    "coordinate_status",
    "nerc_region",
    "balancing_authority_code",
    "balancing_authority_name",
    "sector_name",
    "regulatory_status",
    "transmission_owner",
    "grid_voltage_1_kv",
    "grid_voltage_2_kv",
    "grid_voltage_3_kv",
    "energy_storage_flag",
    "generator_count",
    "operable_nameplate_capacity_mw",
    "operable_summer_capacity_mw",
    "operable_winter_capacity_mw",
    "primary_fuel_code",
    "primary_technology",
    "status_mix",
    "carbon_capture_generator_count",
    "carbon_capture_generator_ids",
    "carbon_capture_present_flag",
    "boiler_id_count",
    "boiler_ids",
    "cooling_id_count",
    "cooling_ids",
    "particulate_control_id_count",
    "particulate_control_ids",
    "so2_control_id_count",
    "so2_control_ids",
    "nox_control_id_count",
    "nox_control_ids",
    "mercury_control_id_count",
    "mercury_control_ids",
    "stack_flue_id_count",
    "stack_flue_ids",
    "emissions_control_equipment_count",
    "emissions_control_equipment_types",
    "acid_gas_control_present_flag",
    "emissions_control_statuses",
    "emissions_control_total_cost_thousand_dollars",
    "emissions_control_inservice_years",
    "emissions_control_retirement_years",
    "new_source_review_flags",
    "new_source_review_permits",
    "new_source_review_years",
    "sulfur_regulations",
    "sulfur_standard_rates",
    "sulfur_standard_units",
    "sulfur_standard_periods",
    "sulfur_percent_scrubbed_values",
    "sulfur_compliance_years",
    "sulfur_existing_strategies",
    "sulfur_proposed_strategies",
    "nitrogen_regulations",
    "nitrogen_standard_rates",
    "nitrogen_standard_units",
    "nitrogen_standard_periods",
    "nitrogen_compliance_years",
    "nitrogen_existing_strategies",
    "nitrogen_proposed_strategies",
    "particulate_regulations",
    "particulate_standard_rates",
    "particulate_standard_units",
    "particulate_standard_periods",
    "particulate_compliance_years",
    "mercury_regulations",
    "mercury_compliance_years",
    "mercury_existing_strategies",
    "mercury_proposed_strategies",
    "cooling_statuses",
    "cooling_types",
    "cooling_water_sources",
    "cooling_water_discharges",
    "cooling_intake_rate_gpm_total",
    "cooling_power_requirement_mw_total",
    "cooling_total_cost_thousand_dollars",
    "particulate_collector_types",
    "particulate_collection_efficiency_pct_max",
    "particulate_design_emission_rate_lb_per_hour_total",
    "particulate_gas_exit_rate_cfm_total",
    "particulate_gas_exit_temperature_f_max",
    "so2_control_types",
    "so2_sorbent_types",
    "so2_removal_efficiency_pct_max",
    "so2_design_emission_rate_lb_per_hour_total",
    "so2_flue_gas_exit_rate_cfm_total",
    "so2_flue_gas_exit_temperature_f_max",
    "so2_fgd_total_cost_thousand_dollars",
    "stack_flue_statuses",
    "stack_height_ft_max",
    "stack_exit_rate_100_cfm_total",
    "stack_exit_temperature_100_f_max",
    "stack_exit_velocity_100_ft_per_second_max",
    "co2_emissions_value",
    "co2_emissions_unit",
    "co2_emissions_basis",
    "co2_emissions_source",
    "co2_emissions_reporting_year",
    "co2e_emissions_value",
    "co2e_emissions_unit",
    "co2e_emissions_basis",
    "co2e_emissions_source",
    "co2e_emissions_reporting_year",
    "ch4_emissions_value",
    "ch4_emissions_unit",
    "ch4_emissions_basis",
    "ch4_emissions_source",
    "ch4_emissions_reporting_year",
    "n2o_emissions_value",
    "n2o_emissions_unit",
    "n2o_emissions_basis",
    "n2o_emissions_source",
    "n2o_emissions_reporting_year",
    "so2_emissions_value",
    "so2_emissions_unit",
    "so2_emissions_basis",
    "so2_emissions_source",
    "so2_emissions_reporting_year",
    "nox_emissions_value",
    "nox_emissions_unit",
    "nox_emissions_basis",
    "nox_emissions_source",
    "nox_emissions_reporting_year",
    "particulate_matter_emissions_value",
    "particulate_matter_emissions_unit",
    "particulate_matter_emissions_basis",
    "particulate_matter_emissions_source",
    "particulate_matter_emissions_reporting_year",
    "mercury_emissions_value",
    "mercury_emissions_unit",
    "mercury_emissions_basis",
    "mercury_emissions_source",
    "mercury_emissions_reporting_year",
    "radioisotopic_emissions_value",
    "radioisotopic_emissions_unit",
    "radioisotopic_emissions_basis",
    "radioisotopic_emissions_source",
    "radioisotopic_emissions_reporting_year",
    "emissions_profile_status",
    "source_dataset",
    "source_sheets",
]


def clean_text(value: str | None) -> str:
    if value is None:
        return ""
    return " ".join(value.replace("\xa0", " ").split())


def clean_number(value: str | None) -> str:
    text = clean_text(value)
    if not text:
        return ""
    try:
        number = float(text.replace(",", ""))
    except ValueError:
        return text
    if number.is_integer():
        return str(int(number))
    return f"{number:.6f}".rstrip("0").rstrip(".")


def to_float(value: str | None) -> float | None:
    text = clean_text(value)
    if not text:
        return None
    try:
        return float(text.replace(",", ""))
    except ValueError:
        return None


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


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        return [{key: clean_text(value) for key, value in row.items()} for row in reader]


def add_text_value(target: set[str], value: str | None) -> None:
    text = clean_text(value)
    if text:
        target.add(text)


def add_numeric_sum(bucket: dict[str, object], key: str, value: str | None) -> None:
    number = to_float(value)
    if number is None:
        return
    bucket[key] = float(bucket.get(key, 0.0)) + number


def add_numeric_max(bucket: dict[str, object], key: str, value: str | None) -> None:
    number = to_float(value)
    if number is None:
        return
    previous = bucket.get(key)
    bucket[key] = number if previous is None else max(float(previous), number)


def format_joined(values: set[str]) -> str:
    if not values:
        return ""
    return "|".join(sorted(values))


def format_sum(value: object) -> str:
    if value in (None, 0, 0.0):
        return ""
    return clean_number(str(value))


def format_max(value: object) -> str:
    if value is None:
        return ""
    return clean_number(str(value))


def normalize_yes_no_flag(value: str | None) -> str:
    text = clean_text(value).lower()
    if not text:
        return ""
    if text in YES_VALUES:
        return "Y"
    if text in NO_VALUES:
        return "N"
    return clean_text(value)


def load_clean_plant_details() -> dict[str, dict[str, str]]:
    return {row["plant_code"]: row for row in read_csv(PLANT_DETAILS_CSV) if row.get("plant_code")}


def summarize_carbon_capture() -> dict[str, dict[str, str]]:
    by_plant: dict[str, dict[str, object]] = defaultdict(
        lambda: {
            "generator_ids": set(),
        }
    )
    for row in iter_sheet_rows(GENERATOR_XLSX, GENERATOR_SHEET, header_row_number=2):
        plant_code = clean_number(row.get("Plant Code"))
        if not plant_code:
            continue
        capture_flag = normalize_yes_no_flag(row.get("Carbon Capture Technology?"))
        if capture_flag != "Y":
            continue
        bucket = by_plant[plant_code]
        add_text_value(bucket["generator_ids"], row.get("Generator ID"))  # type: ignore[arg-type]

    output: dict[str, dict[str, str]] = {}
    for plant_code, bucket in by_plant.items():
        generator_ids: set[str] = bucket["generator_ids"]  # type: ignore[assignment]
        output[plant_code] = {
            "carbon_capture_generator_count": str(len(generator_ids)),
            "carbon_capture_generator_ids": format_joined(generator_ids),
            "carbon_capture_present_flag": "Y" if generator_ids else "N",
        }
    return output


def summarize_enviro_associations() -> dict[str, dict[str, str]]:
    by_plant: dict[str, dict[str, object]] = defaultdict(
        lambda: {
            "boiler_ids": set(),
            "cooling_ids": set(),
            "particulate_control_ids": set(),
            "so2_control_ids": set(),
            "nox_control_ids": set(),
            "mercury_control_ids": set(),
            "stack_flue_ids": set(),
            "equipment_types": set(),
            "equipment_statuses": set(),
            "inservice_years": set(),
            "retirement_years": set(),
            "acid_gas_control_present": False,
            "equipment_count": 0,
            "equipment_total_cost_thousand_dollars": 0.0,
        }
    )

    association_sheets = [
        ("Boiler Generator", None),
        ("Boiler Cooling", "Cooling ID"),
        ("Boiler Particulate Matter", "Particulate Matter Control ID"),
        ("Boiler SO2", "SO2 Control ID"),
        ("Boiler NOx", "NOx Control ID"),
        ("Boiler Mercury", "Mercury Control ID"),
        ("Boiler Stack Flue", "Stack / Flue ID"),
    ]

    for sheet_name, id_field in association_sheets:
        for row in iter_sheet_rows(ENVIRO_ASSOC_XLSX, sheet_name, header_row_number=2):
            plant_code = clean_number(row.get("Plant Code"))
            if not plant_code:
                continue
            bucket = by_plant[plant_code]
            add_text_value(bucket["boiler_ids"], row.get("Boiler ID"))  # type: ignore[arg-type]
            if id_field == "Cooling ID":
                add_text_value(bucket["cooling_ids"], row.get(id_field))  # type: ignore[arg-type]
            elif id_field == "Particulate Matter Control ID":
                add_text_value(bucket["particulate_control_ids"], row.get(id_field))  # type: ignore[arg-type]
            elif id_field == "SO2 Control ID":
                add_text_value(bucket["so2_control_ids"], row.get(id_field))  # type: ignore[arg-type]
            elif id_field == "NOx Control ID":
                add_text_value(bucket["nox_control_ids"], row.get(id_field))  # type: ignore[arg-type]
            elif id_field == "Mercury Control ID":
                add_text_value(bucket["mercury_control_ids"], row.get(id_field))  # type: ignore[arg-type]
            elif id_field == "Stack / Flue ID":
                add_text_value(bucket["stack_flue_ids"], row.get(id_field))  # type: ignore[arg-type]

    for row in iter_sheet_rows(ENVIRO_ASSOC_XLSX, "Emissions Control Equipment", header_row_number=2):
        plant_code = clean_number(row.get("Plant Code"))
        if not plant_code:
            continue
        bucket = by_plant[plant_code]
        bucket["equipment_count"] = int(bucket["equipment_count"]) + 1
        add_text_value(bucket["equipment_types"], row.get("Equipment Type"))  # type: ignore[arg-type]
        add_text_value(bucket["equipment_statuses"], row.get("Status"))  # type: ignore[arg-type]
        add_text_value(bucket["inservice_years"], row.get("Inservice Year"))  # type: ignore[arg-type]
        add_text_value(bucket["retirement_years"], row.get("Retirement Year"))  # type: ignore[arg-type]
        add_text_value(bucket["particulate_control_ids"], row.get("Particulate Matter Control ID"))  # type: ignore[arg-type]
        add_text_value(bucket["so2_control_ids"], row.get("SO2 Control ID"))  # type: ignore[arg-type]
        add_text_value(bucket["nox_control_ids"], row.get("NOx Control ID"))  # type: ignore[arg-type]
        add_text_value(bucket["mercury_control_ids"], row.get("Mercury Control ID"))  # type: ignore[arg-type]
        if normalize_yes_no_flag(row.get("Acid Gas Control?")) == "Y":
            bucket["acid_gas_control_present"] = True
        add_numeric_sum(bucket, "equipment_total_cost_thousand_dollars", row.get("Total Cost (Thousand Dollars)"))

    output: dict[str, dict[str, str]] = {}
    for plant_code, bucket in by_plant.items():
        boiler_ids: set[str] = bucket["boiler_ids"]  # type: ignore[assignment]
        cooling_ids: set[str] = bucket["cooling_ids"]  # type: ignore[assignment]
        particulate_control_ids: set[str] = bucket["particulate_control_ids"]  # type: ignore[assignment]
        so2_control_ids: set[str] = bucket["so2_control_ids"]  # type: ignore[assignment]
        nox_control_ids: set[str] = bucket["nox_control_ids"]  # type: ignore[assignment]
        mercury_control_ids: set[str] = bucket["mercury_control_ids"]  # type: ignore[assignment]
        stack_flue_ids: set[str] = bucket["stack_flue_ids"]  # type: ignore[assignment]
        equipment_types: set[str] = bucket["equipment_types"]  # type: ignore[assignment]
        equipment_statuses: set[str] = bucket["equipment_statuses"]  # type: ignore[assignment]
        inservice_years: set[str] = bucket["inservice_years"]  # type: ignore[assignment]
        retirement_years: set[str] = bucket["retirement_years"]  # type: ignore[assignment]
        output[plant_code] = {
            "boiler_id_count": str(len(boiler_ids)),
            "boiler_ids": format_joined(boiler_ids),
            "cooling_id_count": str(len(cooling_ids)),
            "cooling_ids": format_joined(cooling_ids),
            "particulate_control_id_count": str(len(particulate_control_ids)),
            "particulate_control_ids": format_joined(particulate_control_ids),
            "so2_control_id_count": str(len(so2_control_ids)),
            "so2_control_ids": format_joined(so2_control_ids),
            "nox_control_id_count": str(len(nox_control_ids)),
            "nox_control_ids": format_joined(nox_control_ids),
            "mercury_control_id_count": str(len(mercury_control_ids)),
            "mercury_control_ids": format_joined(mercury_control_ids),
            "stack_flue_id_count": str(len(stack_flue_ids)),
            "stack_flue_ids": format_joined(stack_flue_ids),
            "emissions_control_equipment_count": str(bucket["equipment_count"]) if bucket["equipment_count"] else "",
            "emissions_control_equipment_types": format_joined(equipment_types),
            "acid_gas_control_present_flag": "Y" if bucket["acid_gas_control_present"] else "N",
            "emissions_control_statuses": format_joined(equipment_statuses),
            "emissions_control_total_cost_thousand_dollars": format_sum(
                bucket["equipment_total_cost_thousand_dollars"]
            ),
            "emissions_control_inservice_years": format_joined(inservice_years),
            "emissions_control_retirement_years": format_joined(retirement_years),
        }
    return output


def summarize_emission_standards() -> dict[str, dict[str, str]]:
    by_plant: dict[str, dict[str, object]] = defaultdict(
        lambda: {
            "new_source_review_flags": set(),
            "new_source_review_permits": set(),
            "new_source_review_years": set(),
            "sulfur_regulations": set(),
            "sulfur_standard_rates": set(),
            "sulfur_standard_units": set(),
            "sulfur_standard_periods": set(),
            "sulfur_percent_scrubbed_values": set(),
            "sulfur_compliance_years": set(),
            "sulfur_existing_strategies": set(),
            "sulfur_proposed_strategies": set(),
            "nitrogen_regulations": set(),
            "nitrogen_standard_rates": set(),
            "nitrogen_standard_units": set(),
            "nitrogen_standard_periods": set(),
            "nitrogen_compliance_years": set(),
            "nitrogen_existing_strategies": set(),
            "nitrogen_proposed_strategies": set(),
            "particulate_regulations": set(),
            "particulate_standard_rates": set(),
            "particulate_standard_units": set(),
            "particulate_standard_periods": set(),
            "particulate_compliance_years": set(),
            "mercury_regulations": set(),
            "mercury_compliance_years": set(),
            "mercury_existing_strategies": set(),
            "mercury_proposed_strategies": set(),
        }
    )

    for row in iter_sheet_rows(ENVIRO_EQUIP_XLSX, EMISSION_STANDARDS_SHEET, header_row_number=2):
        plant_code = clean_number(row.get("Plant Code"))
        if not plant_code:
            continue
        bucket = by_plant[plant_code]

        add_text_value(bucket["new_source_review_flags"], row.get("New Source Review"))  # type: ignore[arg-type]
        add_text_value(bucket["new_source_review_permits"], row.get("New Source Review Permit"))  # type: ignore[arg-type]
        add_text_value(bucket["new_source_review_years"], row.get("New Source Review Year"))  # type: ignore[arg-type]

        add_text_value(bucket["sulfur_regulations"], row.get("Regulation Sulfur"))  # type: ignore[arg-type]
        add_text_value(bucket["sulfur_standard_rates"], row.get("Standard Sulfur Rate"))  # type: ignore[arg-type]
        add_text_value(bucket["sulfur_standard_units"], row.get("Unit Sulfur"))  # type: ignore[arg-type]
        add_text_value(bucket["sulfur_standard_periods"], row.get("Period Sulfur"))  # type: ignore[arg-type]
        add_text_value(
            bucket["sulfur_percent_scrubbed_values"],
            row.get("Standard Sulfur Percent Scrubbed"),
        )  # type: ignore[arg-type]
        add_text_value(bucket["sulfur_compliance_years"], row.get("Compliance Year Sulfur"))  # type: ignore[arg-type]
        for field in (
            "Sulfur Dioxide Control Existing Strategy 1",
            "Sulfur Dioxide Control Existing Strategy 2",
            "Sulfur Dioxide Control Existing Strategy 3",
        ):
            add_text_value(bucket["sulfur_existing_strategies"], row.get(field))  # type: ignore[arg-type]
        for field in (
            "Sulfur Dioxide Control Proposed Strategy 1",
            "Sulfur Dioxide Control Proposed Strategy 2",
            "Sulfur Dioxide Control Proposed Strategy 3",
        ):
            add_text_value(bucket["sulfur_proposed_strategies"], row.get(field))  # type: ignore[arg-type]

        add_text_value(bucket["nitrogen_regulations"], row.get("Regulation Nitrogen"))  # type: ignore[arg-type]
        add_text_value(bucket["nitrogen_standard_rates"], row.get("Standard Nitrogen Rate"))  # type: ignore[arg-type]
        add_text_value(bucket["nitrogen_standard_units"], row.get("Unit Nitrogen"))  # type: ignore[arg-type]
        add_text_value(bucket["nitrogen_standard_periods"], row.get("Period Nitrogen"))  # type: ignore[arg-type]
        add_text_value(bucket["nitrogen_compliance_years"], row.get("Compliance Year Nitrogen"))  # type: ignore[arg-type]
        for field in (
            "Nitrogen Oxide Control Existing Strategy 1",
            "Nitrogen Oxide Control Existing Strategy 2",
            "Nitrogen Oxide Control Existing Strategy 3",
        ):
            add_text_value(bucket["nitrogen_existing_strategies"], row.get(field))  # type: ignore[arg-type]
        for field in (
            "Nitrogen Oxide Control Proposed Strategy 1",
            "Nitrogen Oxide Control Proposed Strategy 2",
            "Nitrogen Oxide Control Proposed Strategy 3",
        ):
            add_text_value(bucket["nitrogen_proposed_strategies"], row.get(field))  # type: ignore[arg-type]

        add_text_value(bucket["particulate_regulations"], row.get("Regulation Particulate"))  # type: ignore[arg-type]
        add_text_value(bucket["particulate_standard_rates"], row.get("Standard Particulate Rate"))  # type: ignore[arg-type]
        add_text_value(bucket["particulate_standard_units"], row.get("Unit Particulate"))  # type: ignore[arg-type]
        add_text_value(bucket["particulate_standard_periods"], row.get("Period Particulate"))  # type: ignore[arg-type]
        add_text_value(
            bucket["particulate_compliance_years"],
            row.get("Compliance Year Particulate"),
        )  # type: ignore[arg-type]

        add_text_value(bucket["mercury_regulations"], row.get("Regulation Mercury"))  # type: ignore[arg-type]
        add_text_value(bucket["mercury_compliance_years"], row.get("Compliance Year Mercury"))  # type: ignore[arg-type]
        for field in (
            "Mercury Control Existing Strategy 1",
            "Mercury Control Existing Strategy 2",
            "Mercury Control Existing Strategy 3",
        ):
            add_text_value(bucket["mercury_existing_strategies"], row.get(field))  # type: ignore[arg-type]
        for field in (
            "Mercury Control Proposed Strategy 1",
            "Mercury Control Proposed Strategy 2",
            "Mercury Control Proposed Strategy 3",
        ):
            add_text_value(bucket["mercury_proposed_strategies"], row.get(field))  # type: ignore[arg-type]

    output: dict[str, dict[str, str]] = {}
    for plant_code, bucket in by_plant.items():
        output[plant_code] = {
            "new_source_review_flags": format_joined(bucket["new_source_review_flags"]),  # type: ignore[arg-type]
            "new_source_review_permits": format_joined(bucket["new_source_review_permits"]),  # type: ignore[arg-type]
            "new_source_review_years": format_joined(bucket["new_source_review_years"]),  # type: ignore[arg-type]
            "sulfur_regulations": format_joined(bucket["sulfur_regulations"]),  # type: ignore[arg-type]
            "sulfur_standard_rates": format_joined(bucket["sulfur_standard_rates"]),  # type: ignore[arg-type]
            "sulfur_standard_units": format_joined(bucket["sulfur_standard_units"]),  # type: ignore[arg-type]
            "sulfur_standard_periods": format_joined(bucket["sulfur_standard_periods"]),  # type: ignore[arg-type]
            "sulfur_percent_scrubbed_values": format_joined(
                bucket["sulfur_percent_scrubbed_values"]
            ),  # type: ignore[arg-type]
            "sulfur_compliance_years": format_joined(bucket["sulfur_compliance_years"]),  # type: ignore[arg-type]
            "sulfur_existing_strategies": format_joined(bucket["sulfur_existing_strategies"]),  # type: ignore[arg-type]
            "sulfur_proposed_strategies": format_joined(bucket["sulfur_proposed_strategies"]),  # type: ignore[arg-type]
            "nitrogen_regulations": format_joined(bucket["nitrogen_regulations"]),  # type: ignore[arg-type]
            "nitrogen_standard_rates": format_joined(bucket["nitrogen_standard_rates"]),  # type: ignore[arg-type]
            "nitrogen_standard_units": format_joined(bucket["nitrogen_standard_units"]),  # type: ignore[arg-type]
            "nitrogen_standard_periods": format_joined(bucket["nitrogen_standard_periods"]),  # type: ignore[arg-type]
            "nitrogen_compliance_years": format_joined(bucket["nitrogen_compliance_years"]),  # type: ignore[arg-type]
            "nitrogen_existing_strategies": format_joined(
                bucket["nitrogen_existing_strategies"]
            ),  # type: ignore[arg-type]
            "nitrogen_proposed_strategies": format_joined(
                bucket["nitrogen_proposed_strategies"]
            ),  # type: ignore[arg-type]
            "particulate_regulations": format_joined(bucket["particulate_regulations"]),  # type: ignore[arg-type]
            "particulate_standard_rates": format_joined(
                bucket["particulate_standard_rates"]
            ),  # type: ignore[arg-type]
            "particulate_standard_units": format_joined(
                bucket["particulate_standard_units"]
            ),  # type: ignore[arg-type]
            "particulate_standard_periods": format_joined(
                bucket["particulate_standard_periods"]
            ),  # type: ignore[arg-type]
            "particulate_compliance_years": format_joined(
                bucket["particulate_compliance_years"]
            ),  # type: ignore[arg-type]
            "mercury_regulations": format_joined(bucket["mercury_regulations"]),  # type: ignore[arg-type]
            "mercury_compliance_years": format_joined(bucket["mercury_compliance_years"]),  # type: ignore[arg-type]
            "mercury_existing_strategies": format_joined(
                bucket["mercury_existing_strategies"]
            ),  # type: ignore[arg-type]
            "mercury_proposed_strategies": format_joined(
                bucket["mercury_proposed_strategies"]
            ),  # type: ignore[arg-type]
        }
    return output


def summarize_cooling() -> dict[str, dict[str, str]]:
    by_plant: dict[str, dict[str, object]] = defaultdict(
        lambda: {
            "cooling_statuses": set(),
            "cooling_types": set(),
            "cooling_water_sources": set(),
            "cooling_water_discharges": set(),
            "cooling_intake_rate_gpm_total": 0.0,
            "cooling_power_requirement_mw_total": 0.0,
            "cooling_total_cost_thousand_dollars": 0.0,
        }
    )

    for row in iter_sheet_rows(ENVIRO_EQUIP_XLSX, COOLING_SHEET, header_row_number=2):
        plant_code = clean_number(row.get("Plant Code"))
        if not plant_code:
            continue
        bucket = by_plant[plant_code]
        add_text_value(bucket["cooling_statuses"], row.get("Cooling Status"))  # type: ignore[arg-type]
        for field in ("Cooling Type 1", "Cooling Type 2", "Cooling Type 3", "Cooling Type 4"):
            add_text_value(bucket["cooling_types"], row.get(field))  # type: ignore[arg-type]
        add_text_value(bucket["cooling_water_sources"], row.get("Cooling Water Source"))  # type: ignore[arg-type]
        add_text_value(bucket["cooling_water_discharges"], row.get("Cooling Water Discharge"))  # type: ignore[arg-type]
        add_numeric_sum(bucket, "cooling_intake_rate_gpm_total", row.get("Intake Rate at 100% (Gallons per Minute)"))
        add_numeric_sum(bucket, "cooling_power_requirement_mw_total", row.get("Power Requirement (MW)"))
        add_numeric_sum(bucket, "cooling_total_cost_thousand_dollars", row.get("Cost Total (Thousand Dollars)"))

    output: dict[str, dict[str, str]] = {}
    for plant_code, bucket in by_plant.items():
        output[plant_code] = {
            "cooling_statuses": format_joined(bucket["cooling_statuses"]),  # type: ignore[arg-type]
            "cooling_types": format_joined(bucket["cooling_types"]),  # type: ignore[arg-type]
            "cooling_water_sources": format_joined(bucket["cooling_water_sources"]),  # type: ignore[arg-type]
            "cooling_water_discharges": format_joined(bucket["cooling_water_discharges"]),  # type: ignore[arg-type]
            "cooling_intake_rate_gpm_total": format_sum(bucket["cooling_intake_rate_gpm_total"]),
            "cooling_power_requirement_mw_total": format_sum(bucket["cooling_power_requirement_mw_total"]),
            "cooling_total_cost_thousand_dollars": format_sum(bucket["cooling_total_cost_thousand_dollars"]),
        }
    return output


def summarize_fgp() -> dict[str, dict[str, str]]:
    by_plant: dict[str, dict[str, object]] = defaultdict(
        lambda: {
            "particulate_collector_types": set(),
            "particulate_collection_efficiency_pct_max": None,
            "particulate_design_emission_rate_lb_per_hour_total": 0.0,
            "particulate_gas_exit_rate_cfm_total": 0.0,
            "particulate_gas_exit_temperature_f_max": None,
        }
    )

    for row in iter_sheet_rows(ENVIRO_EQUIP_XLSX, FGP_SHEET, header_row_number=2):
        plant_code = clean_number(row.get("Plant Code"))
        if not plant_code:
            continue
        bucket = by_plant[plant_code]
        for field in ("Collector Type 1", "Collector Type 2", "Collector Type 3"):
            add_text_value(bucket["particulate_collector_types"], row.get(field))  # type: ignore[arg-type]
        add_numeric_max(bucket, "particulate_collection_efficiency_pct_max", row.get("Collection Efficiency"))
        add_numeric_sum(bucket, "particulate_design_emission_rate_lb_per_hour_total", row.get("Emission Rate (Pounds per Hour)"))
        add_numeric_sum(bucket, "particulate_gas_exit_rate_cfm_total", row.get("Gas Exit Rate (Cubic Feet per Minute)"))
        add_numeric_max(bucket, "particulate_gas_exit_temperature_f_max", row.get("Gas Exit Temperature (Fahrenheit)"))

    output: dict[str, dict[str, str]] = {}
    for plant_code, bucket in by_plant.items():
        output[plant_code] = {
            "particulate_collector_types": format_joined(bucket["particulate_collector_types"]),  # type: ignore[arg-type]
            "particulate_collection_efficiency_pct_max": format_max(
                bucket["particulate_collection_efficiency_pct_max"]
            ),
            "particulate_design_emission_rate_lb_per_hour_total": format_sum(
                bucket["particulate_design_emission_rate_lb_per_hour_total"]
            ),
            "particulate_gas_exit_rate_cfm_total": format_sum(bucket["particulate_gas_exit_rate_cfm_total"]),
            "particulate_gas_exit_temperature_f_max": format_max(
                bucket["particulate_gas_exit_temperature_f_max"]
            ),
        }
    return output


def summarize_fgd() -> dict[str, dict[str, str]]:
    by_plant: dict[str, dict[str, object]] = defaultdict(
        lambda: {
            "so2_control_types": set(),
            "so2_sorbent_types": set(),
            "so2_removal_efficiency_pct_max": None,
            "so2_design_emission_rate_lb_per_hour_total": 0.0,
            "so2_flue_gas_exit_rate_cfm_total": 0.0,
            "so2_flue_gas_exit_temperature_f_max": None,
            "so2_fgd_total_cost_thousand_dollars": 0.0,
        }
    )

    for row in iter_sheet_rows(ENVIRO_EQUIP_XLSX, FGD_SHEET, header_row_number=2):
        plant_code = clean_number(row.get("Plant Code"))
        if not plant_code:
            continue
        bucket = by_plant[plant_code]
        for field in ("SO2 Type 1", "SO2 Type 2", "SO2 Type 3", "SO2 Type 4"):
            add_text_value(bucket["so2_control_types"], row.get(field))  # type: ignore[arg-type]
        for field in ("Sorbent Type 1", "Sorbent Type 2", "Sorbent Type 3", "Sorbent Type 4"):
            add_text_value(bucket["so2_sorbent_types"], row.get(field))  # type: ignore[arg-type]
        add_numeric_max(bucket, "so2_removal_efficiency_pct_max", row.get("Removal Efficiency of Sulfur"))
        add_numeric_sum(bucket, "so2_design_emission_rate_lb_per_hour_total", row.get("Sulfur Emission Rate (Pounds per Hour)"))
        add_numeric_sum(bucket, "so2_flue_gas_exit_rate_cfm_total", row.get("Flue Gas Exit Rate (Cubic Feet per Minute)"))
        add_numeric_max(bucket, "so2_flue_gas_exit_temperature_f_max", row.get("Flue Gas Exit Temperature (Fahrenheit)"))
        add_numeric_sum(bucket, "so2_fgd_total_cost_thousand_dollars", row.get("Cost Total (Thousand Dollars)"))

    output: dict[str, dict[str, str]] = {}
    for plant_code, bucket in by_plant.items():
        output[plant_code] = {
            "so2_control_types": format_joined(bucket["so2_control_types"]),  # type: ignore[arg-type]
            "so2_sorbent_types": format_joined(bucket["so2_sorbent_types"]),  # type: ignore[arg-type]
            "so2_removal_efficiency_pct_max": format_max(bucket["so2_removal_efficiency_pct_max"]),
            "so2_design_emission_rate_lb_per_hour_total": format_sum(
                bucket["so2_design_emission_rate_lb_per_hour_total"]
            ),
            "so2_flue_gas_exit_rate_cfm_total": format_sum(bucket["so2_flue_gas_exit_rate_cfm_total"]),
            "so2_flue_gas_exit_temperature_f_max": format_max(bucket["so2_flue_gas_exit_temperature_f_max"]),
            "so2_fgd_total_cost_thousand_dollars": format_sum(bucket["so2_fgd_total_cost_thousand_dollars"]),
        }
    return output


def summarize_stack_flue() -> dict[str, dict[str, str]]:
    by_plant: dict[str, dict[str, object]] = defaultdict(
        lambda: {
            "stack_flue_statuses": set(),
            "stack_height_ft_max": None,
            "stack_exit_rate_100_cfm_total": 0.0,
            "stack_exit_temperature_100_f_max": None,
            "stack_exit_velocity_100_ft_per_second_max": None,
        }
    )

    for row in iter_sheet_rows(ENVIRO_EQUIP_XLSX, STACK_FLUE_SHEET, header_row_number=2):
        plant_code = clean_number(row.get("Plant Code"))
        if not plant_code:
            continue
        bucket = by_plant[plant_code]
        add_text_value(bucket["stack_flue_statuses"], row.get("Stack Flue Status"))  # type: ignore[arg-type]
        add_numeric_max(bucket, "stack_height_ft_max", row.get("Stack Height (Feet)"))
        add_numeric_sum(bucket, "stack_exit_rate_100_cfm_total", row.get("Exit Rate 100% (Cubic Feet per Minute)"))
        add_numeric_max(bucket, "stack_exit_temperature_100_f_max", row.get("Exit Temperature 100% (Fahrenheit)"))
        add_numeric_max(
            bucket,
            "stack_exit_velocity_100_ft_per_second_max",
            row.get("Exit Velocity 100% (Feet per Second)"),
        )

    output: dict[str, dict[str, str]] = {}
    for plant_code, bucket in by_plant.items():
        output[plant_code] = {
            "stack_flue_statuses": format_joined(bucket["stack_flue_statuses"]),  # type: ignore[arg-type]
            "stack_height_ft_max": format_max(bucket["stack_height_ft_max"]),
            "stack_exit_rate_100_cfm_total": format_sum(bucket["stack_exit_rate_100_cfm_total"]),
            "stack_exit_temperature_100_f_max": format_max(bucket["stack_exit_temperature_100_f_max"]),
            "stack_exit_velocity_100_ft_per_second_max": format_max(
                bucket["stack_exit_velocity_100_ft_per_second_max"]
            ),
        }
    return output


def load_egrid_plant_emissions() -> dict[str, dict[str, str]]:
    if not EGRID_XLSX.exists():
        return {}

    output: dict[str, dict[str, str]] = {}
    for row in iter_sheet_rows(EGRID_XLSX, EGRID_PLANT_SHEET, header_row_number=2):
        plant_code = clean_number(row.get("ORISPL"))
        if not plant_code:
            continue
        output[plant_code] = {
            "co2_emissions_value": clean_number(row.get("PLCO2AN")),
            "co2_emissions_unit": "tons" if clean_text(row.get("PLCO2AN")) else "",
            "co2_emissions_basis": "annual_mass" if clean_text(row.get("PLCO2AN")) else "",
            "co2_emissions_source": "EPA eGRID2023 PLNT23" if clean_text(row.get("PLCO2AN")) else "",
            "co2_emissions_reporting_year": "2023" if clean_text(row.get("PLCO2AN")) else "",
            "co2e_emissions_value": clean_number(row.get("PLCO2EQA")),
            "co2e_emissions_unit": "tons" if clean_text(row.get("PLCO2EQA")) else "",
            "co2e_emissions_basis": "annual_mass" if clean_text(row.get("PLCO2EQA")) else "",
            "co2e_emissions_source": "EPA eGRID2023 PLNT23" if clean_text(row.get("PLCO2EQA")) else "",
            "co2e_emissions_reporting_year": "2023" if clean_text(row.get("PLCO2EQA")) else "",
            "ch4_emissions_value": clean_number(row.get("PLCH4AN")),
            "ch4_emissions_unit": "lbs" if clean_text(row.get("PLCH4AN")) else "",
            "ch4_emissions_basis": "annual_mass" if clean_text(row.get("PLCH4AN")) else "",
            "ch4_emissions_source": "EPA eGRID2023 PLNT23" if clean_text(row.get("PLCH4AN")) else "",
            "ch4_emissions_reporting_year": "2023" if clean_text(row.get("PLCH4AN")) else "",
            "n2o_emissions_value": clean_number(row.get("PLN2OAN")),
            "n2o_emissions_unit": "lbs" if clean_text(row.get("PLN2OAN")) else "",
            "n2o_emissions_basis": "annual_mass" if clean_text(row.get("PLN2OAN")) else "",
            "n2o_emissions_source": "EPA eGRID2023 PLNT23" if clean_text(row.get("PLN2OAN")) else "",
            "n2o_emissions_reporting_year": "2023" if clean_text(row.get("PLN2OAN")) else "",
            "so2_emissions_value": clean_number(row.get("PLSO2AN")),
            "so2_emissions_unit": "tons" if clean_text(row.get("PLSO2AN")) else "",
            "so2_emissions_basis": "annual_mass" if clean_text(row.get("PLSO2AN")) else "",
            "so2_emissions_source": "EPA eGRID2023 PLNT23" if clean_text(row.get("PLSO2AN")) else "",
            "so2_emissions_reporting_year": "2023" if clean_text(row.get("PLSO2AN")) else "",
            "nox_emissions_value": clean_number(row.get("PLNOXAN")),
            "nox_emissions_unit": "tons" if clean_text(row.get("PLNOXAN")) else "",
            "nox_emissions_basis": "annual_mass" if clean_text(row.get("PLNOXAN")) else "",
            "nox_emissions_source": "EPA eGRID2023 PLNT23" if clean_text(row.get("PLNOXAN")) else "",
            "nox_emissions_reporting_year": "2023" if clean_text(row.get("PLNOXAN")) else "",
            "mercury_emissions_value": clean_number(row.get("PLHGAN")),
            "mercury_emissions_unit": "lbs" if clean_text(row.get("PLHGAN")) else "",
            "mercury_emissions_basis": "annual_mass" if clean_text(row.get("PLHGAN")) else "",
            "mercury_emissions_source": "EPA eGRID2023 PLNT23" if clean_text(row.get("PLHGAN")) else "",
            "mercury_emissions_reporting_year": "2023" if clean_text(row.get("PLHGAN")) else "",
        }

    unit_mercury_by_plant: dict[str, float] = defaultdict(float)
    for row in iter_sheet_rows(EGRID_XLSX, EGRID_UNIT_SHEET, header_row_number=2):
        plant_code = clean_number(row.get("ORISPL"))
        mercury_value = to_float(row.get("HGAN"))
        if not plant_code or mercury_value is None:
            continue
        unit_mercury_by_plant[plant_code] += mercury_value

    for plant_code, mercury_total in unit_mercury_by_plant.items():
        entry = output.setdefault(plant_code, {})
        if clean_text(entry.get("mercury_emissions_value")):
            continue
        entry["mercury_emissions_value"] = clean_number(str(mercury_total))
        entry["mercury_emissions_unit"] = "lbs"
        entry["mercury_emissions_basis"] = "annual_mass_unit_rollup"
        entry["mercury_emissions_source"] = "EPA eGRID2023 UNT23 summed to plant"
        entry["mercury_emissions_reporting_year"] = "2023"
    return output


def load_egrid_pm25_emissions() -> dict[str, dict[str, str]]:
    if not EGRID_PM25_XLSX.exists():
        return {}

    output: dict[str, dict[str, str]] = {}
    for row in iter_sheet_rows(EGRID_PM25_XLSX, EGRID_PM25_PLANT_SHEET, header_row_number=2):
        plant_code = clean_number(row.get("ORISPL"))
        if not plant_code:
            continue
        pm_value = clean_number(row.get("PLPM25AN"))
        output[plant_code] = {
            "particulate_matter_emissions_value": pm_value,
            "particulate_matter_emissions_unit": "tons" if pm_value else "",
            "particulate_matter_emissions_basis": "annual_mass" if pm_value else "",
            "particulate_matter_emissions_source": "EPA eGRID PM2.5 2021 Plant-level Data" if pm_value else "",
            "particulate_matter_emissions_reporting_year": "2021" if pm_value else "",
        }
    return output


def build_emissions_columns(
    row: dict[str, str],
    egrid_emissions: dict[str, str],
    pm25_emissions: dict[str, str],
) -> dict[str, str]:
    so2_value = row.get("so2_design_emission_rate_lb_per_hour_total", "")
    particulate_value = row.get("particulate_design_emission_rate_lb_per_hour_total", "")
    output = {
        "co2_emissions_value": "",
        "co2_emissions_unit": "",
        "co2_emissions_basis": "",
        "co2_emissions_source": "",
        "co2_emissions_reporting_year": "",
        "co2e_emissions_value": "",
        "co2e_emissions_unit": "",
        "co2e_emissions_basis": "",
        "co2e_emissions_source": "",
        "co2e_emissions_reporting_year": "",
        "ch4_emissions_value": "",
        "ch4_emissions_unit": "",
        "ch4_emissions_basis": "",
        "ch4_emissions_source": "",
        "ch4_emissions_reporting_year": "",
        "n2o_emissions_value": "",
        "n2o_emissions_unit": "",
        "n2o_emissions_basis": "",
        "n2o_emissions_source": "",
        "n2o_emissions_reporting_year": "",
        "so2_emissions_value": "",
        "so2_emissions_unit": "",
        "so2_emissions_basis": "",
        "so2_emissions_source": "",
        "so2_emissions_reporting_year": "",
        "nox_emissions_value": "",
        "nox_emissions_unit": "",
        "nox_emissions_basis": "",
        "nox_emissions_source": "",
        "nox_emissions_reporting_year": "",
        "particulate_matter_emissions_value": "",
        "particulate_matter_emissions_unit": "",
        "particulate_matter_emissions_basis": "",
        "particulate_matter_emissions_source": "",
        "particulate_matter_emissions_reporting_year": "",
        "mercury_emissions_value": "",
        "mercury_emissions_unit": "",
        "mercury_emissions_basis": "",
        "mercury_emissions_source": "",
        "mercury_emissions_reporting_year": "",
        "radioisotopic_emissions_value": "",
        "radioisotopic_emissions_unit": "",
        "radioisotopic_emissions_basis": "",
        "radioisotopic_emissions_source": "",
        "radioisotopic_emissions_reporting_year": "",
        "emissions_profile_status": "external_join_required",
    }

    output.update(egrid_emissions)
    output.update(pm25_emissions)

    if not output["so2_emissions_value"] and so2_value:
        output["so2_emissions_value"] = so2_value
        output["so2_emissions_unit"] = "lb_per_hour"
        output["so2_emissions_basis"] = "design_100_percent_load"
        output["so2_emissions_source"] = "EIA-860 2024 FGD"
        output["so2_emissions_reporting_year"] = "2024"

    if not output["particulate_matter_emissions_value"] and particulate_value:
        output["particulate_matter_emissions_value"] = particulate_value
        output["particulate_matter_emissions_unit"] = "lb_per_hour"
        output["particulate_matter_emissions_basis"] = "design_100_percent_load"
        output["particulate_matter_emissions_source"] = "EIA-860 2024 FGP"
        output["particulate_matter_emissions_reporting_year"] = "2024"

    has_epa_egrid = any(
        output[field]
        for field in (
            "co2_emissions_value",
            "co2e_emissions_value",
            "ch4_emissions_value",
            "n2o_emissions_value",
            "so2_emissions_value",
            "nox_emissions_value",
            "mercury_emissions_value",
        )
    )
    has_pm25 = bool(pm25_emissions.get("particulate_matter_emissions_value"))
    has_design_fallback = (
        output["so2_emissions_source"] == "EIA-860 2024 FGD"
        or output["particulate_matter_emissions_source"] == "EIA-860 2024 FGP"
    )
    if has_epa_egrid and has_pm25:
        output["emissions_profile_status"] = "populated_from_epa_egrid_2023_and_pm25_2021"
    elif has_epa_egrid and has_design_fallback:
        output["emissions_profile_status"] = "populated_from_epa_egrid_2023_with_eia_design_fallbacks"
    elif has_epa_egrid:
        output["emissions_profile_status"] = "populated_from_epa_egrid_2023"
    elif has_design_fallback:
        output["emissions_profile_status"] = "partial_eia860_design_rates_ready_for_external_join"

    return output


def build_profile_rows() -> list[dict[str, str]]:
    clean_details = load_clean_plant_details()
    carbon_capture = summarize_carbon_capture()
    env_associations = summarize_enviro_associations()
    emission_standards = summarize_emission_standards()
    cooling = summarize_cooling()
    fgp = summarize_fgp()
    fgd = summarize_fgd()
    stack_flue = summarize_stack_flue()
    egrid_emissions = load_egrid_plant_emissions()
    pm25_emissions = load_egrid_pm25_emissions()

    source_datasets = ["EIA-860 2024"]
    source_sheets = [
        "Plant",
        "Operable",
        "Boiler Generator",
        "Boiler Cooling",
        "Boiler Particulate Matter",
        "Boiler SO2",
        "Boiler NOx",
        "Boiler Mercury",
        "Boiler Stack Flue",
        "Emissions Control Equipment",
        "Emission Standards & Strategies",
        "Cooling",
        "FGP",
        "FGD",
        "Stack Flue",
    ]
    if egrid_emissions:
        source_datasets.append("EPA eGRID2023")
        source_sheets.append(EGRID_PLANT_SHEET)
    if pm25_emissions:
        source_datasets.append("EPA eGRID PM2.5 2021")
        source_sheets.append(EGRID_PM25_PLANT_SHEET)

    rows: list[dict[str, str]] = []
    for row in iter_sheet_rows(PLANT_XLSX, PLANT_SHEET, header_row_number=2):
        plant_code = clean_number(row.get("Plant Code"))
        if not plant_code:
            continue
        clean_detail = clean_details.get(plant_code, {})

        values = {
            "plant_code": plant_code,
            "plant_name": clean_text(row.get("Plant Name")),
            "utility_id": clean_number(row.get("Utility ID")),
            "utility_name": clean_text(row.get("Utility Name")),
            "street_address": clean_text(row.get("Street Address")),
            "city": clean_text(row.get("City")),
            "county": clean_text(row.get("County")),
            "state": clean_text(row.get("State")),
            "zip_code": clean_text(row.get("Zip")),
            "latitude": clean_number(row.get("Latitude")),
            "longitude": clean_number(row.get("Longitude")),
            "coordinate_status": "present"
            if clean_text(row.get("Latitude")) and clean_text(row.get("Longitude"))
            else "missing_or_partial",
            "nerc_region": clean_detail.get("nerc_region", ""),
            "balancing_authority_code": clean_detail.get("balancing_authority_code", ""),
            "balancing_authority_name": clean_detail.get("balancing_authority_name", ""),
            "sector_name": clean_detail.get("sector_name", ""),
            "regulatory_status": clean_detail.get("regulatory_status", ""),
            "transmission_owner": clean_detail.get("transmission_owner", ""),
            "grid_voltage_1_kv": clean_detail.get("grid_voltage_1_kv", ""),
            "grid_voltage_2_kv": clean_detail.get("grid_voltage_2_kv", ""),
            "grid_voltage_3_kv": clean_detail.get("grid_voltage_3_kv", ""),
            "energy_storage_flag": clean_detail.get("energy_storage_flag", ""),
            "generator_count": clean_detail.get("generator_count", ""),
            "operable_nameplate_capacity_mw": clean_detail.get("operable_nameplate_capacity_mw", ""),
            "operable_summer_capacity_mw": clean_detail.get("operable_summer_capacity_mw", ""),
            "operable_winter_capacity_mw": clean_detail.get("operable_winter_capacity_mw", ""),
            "primary_fuel_code": clean_detail.get("primary_fuel_code", ""),
            "primary_technology": clean_detail.get("primary_technology", ""),
            "status_mix": clean_detail.get("status_mix", ""),
            "source_dataset": "|".join(source_datasets),
            "source_sheets": "|".join(source_sheets),
        }
        values.update(carbon_capture.get(plant_code, {}))
        values.update(env_associations.get(plant_code, {}))
        values.update(emission_standards.get(plant_code, {}))
        values.update(cooling.get(plant_code, {}))
        values.update(fgp.get(plant_code, {}))
        values.update(fgd.get(plant_code, {}))
        values.update(stack_flue.get(plant_code, {}))
        values.update(
            build_emissions_columns(
                values,
                egrid_emissions.get(plant_code, {}),
                pm25_emissions.get(plant_code, {}),
            )
        )

        rows.append({field: values.get(field, "") for field in FIELDNAMES})

    rows.sort(key=lambda item: (item["state"], item["county"], item["plant_name"], item["plant_code"]))
    return rows


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)


def write_metadata(rows: list[dict[str, str]]) -> None:
    def non_empty_count(field: str) -> int:
        return sum(1 for row in rows if clean_text(row.get(field)))

    source_files = [
        str(PLANT_XLSX.relative_to(ROOT)),
        str(GENERATOR_XLSX.relative_to(ROOT)),
        str(ENVIRO_ASSOC_XLSX.relative_to(ROOT)),
        str(ENVIRO_EQUIP_XLSX.relative_to(ROOT)),
        str(PLANT_DETAILS_CSV.relative_to(ROOT)),
    ]
    if EGRID_XLSX.exists():
        source_files.append(str(EGRID_XLSX.relative_to(ROOT)))
    if EGRID_PM25_XLSX.exists():
        source_files.append(str(EGRID_PM25_XLSX.relative_to(ROOT)))

    metadata = {
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "source_files": source_files,
        "output_file": str(OUT_CSV.relative_to(ROOT)),
        "plant_count": len(rows),
        "coordinate_rows_present": non_empty_count("latitude"),
        "carbon_capture_plants": sum(1 for row in rows if row.get("carbon_capture_present_flag") == "Y"),
        "co2_rows": non_empty_count("co2_emissions_value"),
        "co2e_rows": non_empty_count("co2e_emissions_value"),
        "ch4_rows": non_empty_count("ch4_emissions_value"),
        "n2o_rows": non_empty_count("n2o_emissions_value"),
        "so2_rows": non_empty_count("so2_emissions_value"),
        "nox_rows": non_empty_count("nox_emissions_value"),
        "mercury_rows": non_empty_count("mercury_emissions_value"),
        "particulate_rows": non_empty_count("particulate_matter_emissions_value"),
        "notes": [
            "CO2, CO2e, CH4, N2O, NOx, SO2, and mercury columns are populated from EPA eGRID2023 plant-level data when available.",
            "Particulate matter values are populated from EPA's eGRID PM2.5 2021 supplemental workbook when available, otherwise the file falls back to EIA-860 design-rate fields.",
            "Radioisotopic emissions remain blank because they were not available in the downloaded official EPA sources used for this build.",
        ],
    }
    OUT_METADATA_JSON.write_text(json.dumps(metadata, indent=2), encoding="utf-8")


def update_source_inventory() -> None:
    existing_rows: list[dict[str, str]] = []
    if SOURCE_INVENTORY_CSV.exists():
        existing_rows = read_csv(SOURCE_INVENTORY_CSV)

    kept_rows = [
        row
        for row in existing_rows
        if row.get("output_file")
        not in {
            "data/private/eia860_2024/plant_profiles_private.csv",
            "data/private/eia860_2024/plant_profiles_private_metadata.json",
        }
    ]

    kept_rows.extend(
        [
            {
                "source_file": "data/raw/eia860/2024/2___Plant_Y2024.xlsx|data/raw/epa/egrid2023_data_rev2.xlsx|data/raw/epa/egrid_pm25_2018_2021.xlsx",
                "sheet_name": f"{PLANT_SHEET}|{EGRID_PLANT_SHEET}|{EGRID_PM25_PLANT_SHEET}",
                "output_file": "data/private/eia860_2024/plant_profiles_private.csv",
                "purpose": "Private plant-level profile with exact coordinates, environmental controls, and EPA-populated emissions columns.",
            },
            {
                "source_file": "data/raw/eia860/2024/3_1_Generator_Y2024.xlsx|data/raw/eia860/2024/6_1_EnviroAssoc_Y2024.xlsx|data/raw/eia860/2024/6_2_EnviroEquip_Y2024.xlsx|data/processed/eia860/plants_2024_clean.csv|data/raw/epa/egrid2023_data_rev2.xlsx|data/raw/epa/egrid_pm25_2018_2021.xlsx",
                "sheet_name": "Operable|Boiler Generator|Boiler Cooling|Boiler Particulate Matter|Boiler SO2|Boiler NOx|Boiler Mercury|Boiler Stack Flue|Emissions Control Equipment|Emission Standards & Strategies|Cooling|FGP|FGD|Stack Flue|PLNT23|2021 PM Plant-level Data",
                "output_file": "data/private/eia860_2024/plant_profiles_private_metadata.json",
                "purpose": "Metadata summary for the private plant profile build, including emissions-column coverage notes.",
            },
        ]
    )

    fieldnames = ["source_file", "sheet_name", "output_file", "purpose"]
    with SOURCE_INVENTORY_CSV.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(kept_rows)


def main() -> None:
    required_paths = [
        PLANT_XLSX,
        GENERATOR_XLSX,
        ENVIRO_ASSOC_XLSX,
        ENVIRO_EQUIP_XLSX,
        PLANT_DETAILS_CSV,
    ]
    for path in required_paths:
        if not path.exists():
            raise FileNotFoundError(f"Missing required input: {path}")

    rows = build_profile_rows()
    if not rows:
        raise ValueError("No plant profiles were built")
    write_csv(OUT_CSV, rows)
    write_metadata(rows)
    update_source_inventory()
    print(f"Wrote {len(rows)} private plant profiles to {OUT_CSV}")
    print(f"Wrote metadata to {OUT_METADATA_JSON}")


if __name__ == "__main__":
    main()
