# Public Data Folder

This folder is for clean, non-sensitive public outputs that support resilience analysis.

Recommended first outputs:

- `plants_county_summary.csv`
- `plants_state_summary.csv`
- `transmission_corridors_generalized.geojson`
- `substations_regional_summary.csv`

Do not place exact substation coordinates here.
Do not place exact plant coordinates or street addresses here either.

Current generated outputs:

- `plants_state_summary.csv`
- `plants_county_summary.csv`

These are produced from the official EIA-860 2024 source by:

- `scripts/ingest_eia860_plants.py`
