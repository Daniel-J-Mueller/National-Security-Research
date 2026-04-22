# Public Data Folder

This folder is for clean, non-sensitive public outputs that support resilience analysis.

Category layout:

- `electrical/`
- `agriculture/`
- `raws/`
- `people/`
- `radiation/`

Do not place exact substation coordinates here.
Do not place exact plant coordinates or street addresses here either.

Current generated outputs:

- `electrical/plants_state_summary.csv`
- `electrical/plants_county_summary.csv`
- `people/municipal_population_town_halls_2024.csv`
- `agriculture/county_food_outputs_2022.csv`
- `raws/raw_material_sites_2023.csv`
- `radiation/radnet_background_radiation_monitors.csv`

These are produced from official sources by:

- `scripts/ingest_eia860_plants.py`
- `scripts/build_people_municipal_reference.py`
- `scripts/build_agriculture_county_reference.py`
- `scripts/build_raws_reference.py`
- `scripts/build_radiation_reference.py`
- `scripts/build_bulk_exports.py`
