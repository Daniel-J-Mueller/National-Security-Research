# Plant Emissions Visualizer

This static app plots exact plant coordinates from the private data tree and now includes an import wizard that can either:

- use the uploaded file as its own mapped dataset when it already has coordinates
- join uploaded numeric columns onto the base plant asset by `plant_code`

## What It Does

- Loads a browser-friendly private asset generated from:
  - `data/private/eia860_2024/plant_profiles_private.csv`
- Renders:
  - point markers for plant-level inspection
  - heatmaps weighted by the selected metric
  - filterable result rows and a plant detail panel
- Analyzes uploaded files in-browser to detect:
  - likely plant ID columns
  - latitude and longitude columns
  - numeric metric columns
  - related unit, basis, source, and reporting-year columns when present
- Exposes built-in base metrics from the private profile, including:
  - capacity and generator count
  - carbon-capture generator count
  - EPA eGRID2023 annual CO2, CO2e, CH4, N2O, SO2, NOx, and mercury values where available
  - EPA PM2.5 2021 plant-level values where available
  - EIA-derived SO2 and particulate design-rate fallbacks where EPA values are unavailable
- Accepts uploaded emissions tables with columns like:
  - `plant_code`
  - `latitude`
  - `longitude`
  - `co2_tons`
  - `co2e_tons`
  - `ch4_lb`
  - `n2o_lb`
  - `mercury_lb`
  - `so2_tons`
  - `nox_tons`
  - `particulate_matter_tons`
  - `radioisotopic_release_value`

Any numeric column in the uploaded file becomes a selectable metric once the wizard applies the dataset.

## Example Views

### National emissions view

![National emissions view](../../images/US%20Emissions%20data.png)

### Texas mercury example

![Texas mercury example](../../images/Texas_HG_Emissions.png)

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

## Upload Wizard

Use `docs/plant-emissions-visualizer/emissions-template.csv` as the starting header when you want a simple overlay keyed by plant ID.

How it behaves:

- If the uploaded file has `latitude` and `longitude`, the wizard can map that file directly.
- If the uploaded file has `plant_code`, the wizard can join it onto the base plant coordinate asset.
- If both are present, you can choose either mode.
- All other numeric columns are treated as selectable metrics.
- Duplicate plant rows are summed by plant code in join mode.
- Related columns such as `*_unit`, `*_basis`, `*_source`, and `*_reporting_year` are carried into plant detail when available.
- Very small metric values are formatted with scientific notation so tiny radioisotopic values stay visible instead of rounding to `0.00`.
- The built-in annual base metrics come from EPA eGRID2023 and EPA's PM2.5 2021 supplemental workbook where available.
- If EPA PM2.5 or SO2 values are unavailable for a plant, the private profile can still expose EIA-860 design/load-rate fallbacks.

## Privacy Boundary

Exact coordinates stay in `data/private/` and are not copied into `data/public/`.
Keep the generated visualizer asset and any emissions tables outside public outputs.
