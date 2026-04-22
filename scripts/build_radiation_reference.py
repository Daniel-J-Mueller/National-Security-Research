#!/usr/bin/env python3
"""
Build coordinate-backed radiation monitor summaries from EPA RadNet archive ZIPs.
"""

from __future__ import annotations

import csv
import io
import json
import re
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from zipfile import ZipFile


ROOT = Path(__file__).resolve().parents[1]
ZIP_DIR = ROOT / "data" / "raw" / "radiation" / "epa_radnet" / "zips"
MANIFEST_JSON = ROOT / "data" / "raw" / "radiation" / "epa_radnet" / "radnet_zip_manifest.json"
PLACE_GAZETTEER = (
    ROOT / "data" / "raw" / "people" / "census" / "2024_Gaz_place_national" / "2024_Gaz_place_national.txt"
)

PUBLIC_DIR = ROOT / "data" / "public" / "radiation"
PRIVATE_DIR = ROOT / "data" / "private" / "radiation"
PUBLIC_CSV = PUBLIC_DIR / "radnet_background_radiation_monitors.csv"
PRIVATE_CSV = PRIVATE_DIR / "radnet_background_radiation_monitors_private.csv"
PUBLIC_METADATA_JSON = PUBLIC_DIR / "radnet_background_radiation_monitors_metadata.json"
PRIVATE_METADATA_JSON = PRIVATE_DIR / "radnet_background_radiation_monitors_private_metadata.json"

CHANNEL_KEYS = [f"GAMMA COUNT RATE R{index:02d} (CPM)" for index in range(2, 10)]
ZIP_NAME_PATTERN = re.compile(r"^(?P<state>[a-z]{2})_(?P<slug>.+)_(?P<end>\d{4})-(?P<start>\d{4})\.zip$", re.IGNORECASE)
PLACE_SUFFIXES = (
    " consolidated government (balance)",
    " metropolitan government (balance)",
    " urban county",
    " zona urbana",
    " city (balance)",
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
    " county",
    " cdp",
)
PLACE_ALIASES = {
    ("GA", "augusta"): "Augusta-Richmond County",
    ("HI", "honolulu"): "Urban Honolulu",
    ("ID", "boise"): "Boise City",
    ("IN", "indianapolis"): "Indianapolis",
    ("KY", "lexington"): "Lexington-Fayette",
    ("NM", "navajo lake"): "Navajo Dam",
    ("PR", "san juan"): "San Juan",
    ("TN", "nashville"): "Nashville-Davidson",
}
STATE_NAMES = {
    "AL": "Alabama",
    "AK": "Alaska",
    "AZ": "Arizona",
    "AR": "Arkansas",
    "CA": "California",
    "CO": "Colorado",
    "CT": "Connecticut",
    "DC": "District of Columbia",
    "DE": "Delaware",
    "FL": "Florida",
    "GA": "Georgia",
    "HI": "Hawaii",
    "IA": "Iowa",
    "ID": "Idaho",
    "IL": "Illinois",
    "IN": "Indiana",
    "KS": "Kansas",
    "KY": "Kentucky",
    "LA": "Louisiana",
    "MA": "Massachusetts",
    "MD": "Maryland",
    "ME": "Maine",
    "MI": "Michigan",
    "MN": "Minnesota",
    "MO": "Missouri",
    "MS": "Mississippi",
    "MT": "Montana",
    "NC": "North Carolina",
    "ND": "North Dakota",
    "NE": "Nebraska",
    "NH": "New Hampshire",
    "NJ": "New Jersey",
    "NM": "New Mexico",
    "NV": "Nevada",
    "NY": "New York",
    "OH": "Ohio",
    "OK": "Oklahoma",
    "OR": "Oregon",
    "PA": "Pennsylvania",
    "PR": "Puerto Rico",
    "RI": "Rhode Island",
    "SC": "South Carolina",
    "SD": "South Dakota",
    "TN": "Tennessee",
    "TX": "Texas",
    "UT": "Utah",
    "VA": "Virginia",
    "VT": "Vermont",
    "WA": "Washington",
    "WI": "Wisconsin",
    "WV": "West Virginia",
    "WY": "Wyoming",
}


def clean_text(value: str | None) -> str:
    if value is None:
        return ""
    return " ".join(str(value).replace("\xa0", " ").split())


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


def to_float(value: str | None) -> float | None:
    text = clean_text(value)
    if not text:
        return None
    try:
        return float(text.replace(",", ""))
    except ValueError:
        return None


def to_string_number(value: float | None, decimals: int = 2) -> str:
    if value is None:
        return ""
    rounded = round(value, decimals)
    if rounded.is_integer():
        return str(int(rounded))
    return f"{rounded:.{decimals}f}".rstrip("0").rstrip(".")


def percentile_from_counter(histogram: Counter[float], count: int, percentile: float) -> float | None:
    if count <= 0:
        return None
    target_rank = max(0, int((count - 1) * percentile))
    running = 0
    for value in sorted(histogram):
        running += histogram[value]
        if running > target_rank:
            return value
    return max(histogram) if histogram else None


def humanize_station_slug(slug: str) -> str:
    text = slug.replace("_", " ").replace("-", " ")
    words = [word for word in clean_text(text).split(" ") if word]
    output: list[str] = []
    for word in words:
        lowered = word.lower()
        if lowered == "st":
            output.append("St.")
        elif lowered == "ft":
            output.append("Fort")
        elif lowered in {"la", "el", "los", "las", "san", "santa"}:
            output.append(lowered.capitalize())
        else:
            output.append(lowered.capitalize())
    return " ".join(output)


def load_place_centroids() -> dict[tuple[str, str], dict[str, str]]:
    places: dict[tuple[str, str], dict[str, str]] = {}
    with PLACE_GAZETTEER.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        for row in reader:
            cleaned_row = {clean_text(key): clean_text(value) for key, value in row.items() if key}
            state = clean_text(cleaned_row.get("USPS"))
            name = strip_place_suffix(clean_text(cleaned_row.get("NAME")))
            latitude = clean_text(cleaned_row.get("INTPTLAT"))
            longitude = clean_text(cleaned_row.get("INTPTLONG"))
            if not state or not name or not latitude or not longitude:
                continue
            places[(state, normalize_name(name))] = {
                "state": state,
                "place_name": name,
                "latitude": latitude,
                "longitude": longitude,
            }
    return places


def load_url_map() -> dict[str, str]:
    if not MANIFEST_JSON.exists():
        return {}
    payload = json.loads(MANIFEST_JSON.read_text(encoding="utf-8"))
    return {
        clean_text(entry.get("archive_zip_filename")): clean_text(entry.get("archive_zip_url"))
        for entry in payload.get("entries", [])
        if clean_text(entry.get("archive_zip_filename"))
    }


def summarize_station_zip(path: Path) -> dict[str, object]:
    dose_histogram: Counter[float] = Counter()
    dose_sum = 0.0
    dose_count = 0
    dose_min: float | None = None
    dose_max: float | None = None
    gamma_total_sum = 0.0
    gamma_total_count = 0
    channel_sums = {channel: 0.0 for channel in CHANNEL_KEYS}
    channel_counts = {channel: 0 for channel in CHANNEL_KEYS}
    approved_sample_count = 0
    total_sample_count = 0
    location_name = ""
    first_timestamp: datetime | None = None
    last_timestamp: datetime | None = None
    years_with_data: set[int] = set()

    with ZipFile(path) as archive:
        for entry in archive.infolist():
            if not entry.filename.lower().endswith(".csv"):
                continue
            with archive.open(entry, "r") as handle:
                text_stream = io.TextIOWrapper(handle, encoding="utf-8-sig", newline="")
                reader = csv.DictReader(text_stream)
                for row in reader:
                    total_sample_count += 1
                    if clean_text(row.get("STATUS")).upper() != "APPROVED":
                        continue

                    approved_sample_count += 1
                    location_name = location_name or clean_text(row.get("LOCATION_NAME"))
                    timestamp_text = clean_text(row.get("SAMPLE COLLECTION TIME"))
                    if timestamp_text:
                        timestamp = datetime.strptime(timestamp_text, "%m/%d/%Y %H:%M:%S").replace(tzinfo=UTC)
                        years_with_data.add(timestamp.year)
                        if first_timestamp is None or timestamp < first_timestamp:
                            first_timestamp = timestamp
                        if last_timestamp is None or timestamp > last_timestamp:
                            last_timestamp = timestamp

                    dose_value = to_float(row.get("DOSE EQUIVALENT RATE (nSv/h)"))
                    if dose_value is not None:
                        dose_count += 1
                        dose_sum += dose_value
                        dose_histogram[round(dose_value, 2)] += 1
                        dose_min = dose_value if dose_min is None else min(dose_min, dose_value)
                        dose_max = dose_value if dose_max is None else max(dose_max, dose_value)

                    gamma_values = [to_float(row.get(channel)) for channel in CHANNEL_KEYS]
                    numeric_gamma_values = [value for value in gamma_values if value is not None]
                    if numeric_gamma_values:
                        gamma_total_sum += sum(numeric_gamma_values)
                        gamma_total_count += 1
                    for channel, value in zip(CHANNEL_KEYS, gamma_values):
                        if value is None:
                            continue
                        channel_sums[channel] += value
                        channel_counts[channel] += 1

    return {
        "location_name": location_name,
        "total_sample_count": total_sample_count,
        "approved_sample_count": approved_sample_count,
        "approved_dose_reading_count": dose_count,
        "years_with_data_count": len(years_with_data),
        "monitoring_year_start": min(years_with_data) if years_with_data else None,
        "monitoring_year_end": max(years_with_data) if years_with_data else None,
        "first_sample_at_utc": first_timestamp.isoformat() if first_timestamp else "",
        "last_sample_at_utc": last_timestamp.isoformat() if last_timestamp else "",
        "dose_equivalent_rate_avg_nsvh": (dose_sum / dose_count) if dose_count else None,
        "dose_equivalent_rate_min_nsvh": dose_min,
        "dose_equivalent_rate_median_nsvh": percentile_from_counter(dose_histogram, dose_count, 0.5),
        "dose_equivalent_rate_p95_nsvh": percentile_from_counter(dose_histogram, dose_count, 0.95),
        "dose_equivalent_rate_max_nsvh": dose_max,
        "gamma_count_rate_total_avg_cpm": (gamma_total_sum / gamma_total_count) if gamma_total_count else None,
        "gamma_channel_averages": {
            channel: (channel_sums[channel] / channel_counts[channel]) if channel_counts[channel] else None
            for channel in CHANNEL_KEYS
        },
    }


def build_rows() -> tuple[list[dict[str, str]], list[dict[str, str]], dict[str, object], dict[str, object]]:
    places = load_place_centroids()
    url_map = load_url_map()

    interim_rows: list[dict[str, object]] = []
    missing_coordinate_matches: list[str] = []

    for zip_path in sorted(ZIP_DIR.glob("*.zip")):
        match = ZIP_NAME_PATTERN.match(zip_path.name)
        if not match:
            continue
        state = match.group("state").upper()
        station_slug = match.group("slug").lower()
        station_name_guess = humanize_station_slug(station_slug)
        candidate_names = [
            PLACE_ALIASES.get((state, normalize_name(station_name_guess)), ""),
            strip_place_suffix(station_name_guess),
            station_name_guess,
        ]
        place = None
        for candidate_name in candidate_names:
            if not candidate_name:
                continue
            place = places.get((state, normalize_name(candidate_name)))
            if place:
                break
        if not place:
            missing_coordinate_matches.append(zip_path.name)
            continue

        summary = summarize_station_zip(zip_path)
        interim_rows.append(
            {
                "station_id": f"radnet-{state.lower()}-{station_slug}",
                "state": state,
                "state_name": STATE_NAMES.get(state, ""),
                "station_name": place["place_name"],
                "place_name": place["place_name"],
                "latitude": place["latitude"],
                "longitude": place["longitude"],
                "coordinate_source": "Census Gazetteer 2024 place centroid matched to EPA RadNet station city",
                "geometry_precision": "place_centroid",
                "archive_zip_file": str(zip_path.relative_to(ROOT)),
                "archive_zip_url": url_map.get(zip_path.name, ""),
                "source_dataset": "EPA RadNet near-real-time air monitor archives",
                **summary,
            }
        )

    if not interim_rows:
        raise ValueError("No radiation station rows were built")

    dose_averages = sorted(
        float(row["dose_equivalent_rate_avg_nsvh"])
        for row in interim_rows
        if isinstance(row.get("dose_equivalent_rate_avg_nsvh"), float)
    )
    lower_cut = dose_averages[len(dose_averages) // 3] if dose_averages else None
    upper_cut = dose_averages[(2 * len(dose_averages)) // 3] if dose_averages else None

    public_rows: list[dict[str, str]] = []
    private_rows: list[dict[str, str]] = []
    gamma_only_count = 0

    for row in sorted(interim_rows, key=lambda item: (str(item["state"]), str(item["station_name"]))):
        dose_average = row["dose_equivalent_rate_avg_nsvh"]
        if dose_average is None:
            background_band = "Dose unavailable"
            dominant_profile = "Gamma count-only monitor"
            gamma_only_count += 1
        else:
            dominant_profile = "Ambient gamma exposure monitor"
            if lower_cut is None or upper_cut is None:
                background_band = "Measured background gamma"
            elif float(dose_average) <= lower_cut:
                background_band = "Lower background gamma"
            elif float(dose_average) <= upper_cut:
                background_band = "Mid background gamma"
            else:
                background_band = "Higher background gamma"

        public_row = {
            "station_id": clean_text(str(row["station_id"])),
            "state": clean_text(str(row["state"])),
            "state_name": clean_text(str(row["state_name"])),
            "station_name": clean_text(str(row["station_name"])),
            "place_name": clean_text(str(row["place_name"])),
            "latitude": clean_text(str(row["latitude"])),
            "longitude": clean_text(str(row["longitude"])),
            "coordinate_source": clean_text(str(row["coordinate_source"])),
            "geometry_precision": clean_text(str(row["geometry_precision"])),
            "monitoring_year_start": str(row["monitoring_year_start"] or ""),
            "monitoring_year_end": str(row["monitoring_year_end"] or ""),
            "years_with_data_count": str(row["years_with_data_count"] or ""),
            "approved_sample_count": str(row["approved_sample_count"] or ""),
            "approved_dose_reading_count": str(row["approved_dose_reading_count"] or ""),
            "dose_equivalent_rate_avg_nsvh": to_string_number(row["dose_equivalent_rate_avg_nsvh"]),
            "dose_equivalent_rate_p95_nsvh": to_string_number(row["dose_equivalent_rate_p95_nsvh"]),
            "dose_equivalent_rate_max_nsvh": to_string_number(row["dose_equivalent_rate_max_nsvh"]),
            "gamma_count_rate_total_avg_cpm": to_string_number(row["gamma_count_rate_total_avg_cpm"]),
            "background_radiation_band": background_band,
            "dominant_radiation_profile": dominant_profile,
            "source_dataset": clean_text(str(row["source_dataset"])),
        }
        private_row = {
            **public_row,
            "location_name": clean_text(str(row["location_name"])),
            "total_sample_count": str(row["total_sample_count"] or ""),
            "first_sample_at_utc": clean_text(str(row["first_sample_at_utc"])),
            "last_sample_at_utc": clean_text(str(row["last_sample_at_utc"])),
            "dose_equivalent_rate_min_nsvh": to_string_number(row["dose_equivalent_rate_min_nsvh"]),
            "dose_equivalent_rate_median_nsvh": to_string_number(row["dose_equivalent_rate_median_nsvh"]),
            "archive_zip_file": clean_text(str(row["archive_zip_file"])),
            "archive_zip_url": clean_text(str(row["archive_zip_url"])),
        }
        for channel, value in row["gamma_channel_averages"].items():
            key = channel.lower().replace("gamma count rate ", "").replace(" (cpm)", "").replace(" ", "_") + "_avg_cpm"
            private_row[key] = to_string_number(value)

        public_rows.append(public_row)
        private_rows.append(private_row)

    generated_at = datetime.now(UTC).isoformat()
    public_metadata = {
        "generated_at_utc": generated_at,
        "source_files": [
            str(MANIFEST_JSON.relative_to(ROOT)) if MANIFEST_JSON.exists() else "",
            str(ZIP_DIR.relative_to(ROOT)),
            str(PLACE_GAZETTEER.relative_to(ROOT)),
        ],
        "output_file": str(PUBLIC_CSV.relative_to(ROOT)),
        "monitor_count": len(public_rows),
        "gamma_only_monitor_count": gamma_only_count,
        "missing_coordinate_matches": len(missing_coordinate_matches),
        "notes": [
            "Station summaries are built from official EPA RadNet archive ZIP files and represent approved near-real-time ambient gamma monitoring results.",
            "Coordinates use Census Gazetteer 2024 place centroids matched to EPA station-city names.",
            "Public output keeps station-level background-dose summaries while withholding raw archive URLs and per-channel gamma averages.",
        ],
    }
    private_metadata = {
        "generated_at_utc": generated_at,
        "source_files": public_metadata["source_files"],
        "output_file": str(PRIVATE_CSV.relative_to(ROOT)),
        "monitor_count": len(private_rows),
        "gamma_only_monitor_count": gamma_only_count,
        "missing_coordinate_matches": missing_coordinate_matches,
        "notes": [
            "Private output retains archive ZIP provenance, raw EPA location labels, and per-channel gamma averages.",
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
    if not ZIP_DIR.exists():
        raise FileNotFoundError(f"Missing RadNet ZIP directory: {ZIP_DIR}")
    if not PLACE_GAZETTEER.exists():
        raise FileNotFoundError(f"Missing place gazetteer: {PLACE_GAZETTEER}")

    public_rows, private_rows, public_metadata, private_metadata = build_rows()
    write_csv(PUBLIC_CSV, public_rows)
    write_csv(PRIVATE_CSV, private_rows)
    PUBLIC_METADATA_JSON.write_text(json.dumps(public_metadata, indent=2), encoding="utf-8")
    PRIVATE_METADATA_JSON.write_text(json.dumps(private_metadata, indent=2), encoding="utf-8")

    print(f"Wrote {len(public_rows)} public radiation rows to {PUBLIC_CSV}")
    print(f"Wrote {len(private_rows)} private radiation rows to {PRIVATE_CSV}")


if __name__ == "__main__":
    main()
