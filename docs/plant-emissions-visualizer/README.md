# Plant Emissions Visualizer

This static app plots exact EIA-860 plant coordinates from the private data tree and lets you layer any local emissions CSV on top by `plant_code`.

## What It Does

- Loads a browser-friendly private asset generated from:
  - `data/private/eia860_2024/plant_profiles_private.csv`
- Renders:
  - point markers for plant-level inspection
  - heatmaps weighted by the selected metric
  - filterable result rows and a plant detail panel
- Exposes built-in base metrics from the private profile, including:
  - capacity and generator count
  - carbon-capture generator count
  - EPA eGRID2023 annual CO2, CO2e, CH4, N2O, SO2, NOx, and mercury values where available
  - EPA PM2.5 2021 plant-level values where available
  - EIA-derived SO2 and particulate design-rate fallbacks where EPA values are unavailable
- Accepts uploaded emissions tables with columns like:
  - `plant_code`
  - `co2_tons`
  - `co2e_tons`
  - `ch4_lb`
  - `n2o_lb`
  - `mercury_lb`
  - `so2_tons`
  - `nox_tons`
  - `particulate_matter_tons`
  - `radioisotopic_release_value`

Any numeric column in the uploaded CSV becomes a selectable map metric.

## Build The Private Asset

From the repo root:

```powershell
C:\Windows\py.exe scripts\build_private_plant_profiles.py
C:\Windows\py.exe scripts\build_plant_visualizer_assets.py
```

This writes:

- `data/private/eia860_2024/plant_profiles_private.csv`
- `data/private/eia860_2024/plant_profiles_private_metadata.json`
- `data/private/visualizer/plants_reference.json`
- `data/private/visualizer/plants_reference_summary.json`

## Run The Visualizer

Serve the repo root over HTTP, then open the app:

```powershell
C:\Windows\py.exe -m http.server 8000
```

Open:

- `http://localhost:8000/docs/plant-emissions-visualizer/`

The page should not be opened with `file:///...` because the browser needs HTTP access to fetch the local JSON asset.

## Emissions CSV Shape

Use `docs/plant-emissions-visualizer/emissions-template.csv` as the starting header.

Rules:

- `plant_code` is required.
- All other numeric columns are treated as selectable metrics.
- Duplicate `plant_code` rows are summed.
- Non-numeric columns such as `plant_name`, `county`, and `state` are ignored as metrics.
- The built-in annual base metrics come from EPA eGRID2023 and EPA's PM2.5 2021 supplemental workbook where available.
- If EPA PM2.5 or SO2 values are unavailable for a plant, the private profile can still expose EIA-860 design/load-rate fallbacks.

## Privacy Boundary

Exact coordinates stay in `data/private/` and are not copied into `data/public/`.
Keep the generated visualizer asset and any emissions tables outside public outputs.
