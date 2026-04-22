# Plant Emissions Visualizer

This static app now auto-loads a private browser-friendly asset built from the plant profile CSV and keeps the workflow focused on one thing:

- choose an emission
- watch the heatmap and results update immediately
- hover or click any plant to inspect the full source row

## What It Does

- Loads the private visualizer asset:
  - `data/private/visualizer/plants_reference.json`
- That asset is built from:
  - `data/private/eia860_2024/plant_profiles_private.csv`
- Renders:
  - point markers for plant-level inspection
  - heatmaps weighted by the selected emission
  - filterable result rows and a plant detail panel that shows the full CSV row on hover
- Exposes built-in base metrics from the private profile, including:
  - capacity and generator count
  - carbon-capture generator count
  - EPA eGRID2023 annual CO2, CO2e, CH4, N2O, SO2, NOx, and mercury values where available
  - EPA PM2.5 2021 plant-level values where available
  - EIA-derived SO2 and particulate design-rate fallbacks where EPA values are unavailable

## Example Views

### National emissions view

![National emissions view](../../images/US%20Emissions%20data.png)

### Texas mercury example

![Texas mercury example](../../images/Texas_HG_Emissions.png)

## Build The Private Asset

From the repo root:

```powershell
C:\Windows\py.exe scripts\build_private_plant_profiles.py
```

This writes the source CSV:

- `data/private/eia860_2024/plant_profiles_private.csv`
- `data/private/eia860_2024/plant_profiles_private_metadata.json`

Then build the browser-ready private visualizer asset:

```powershell
C:\Windows\py.exe scripts\build_plant_visualizer_assets.py
```

This writes:

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

## Interaction Model

- `plants_reference.json` is loaded automatically when the page opens.
- That JSON asset is generated from `plant_profiles_private.csv`.
- The emission selector drives both the point sizing/coloring and the heatmap weighting.
- State, fuel, search, and minimum-value filters narrow the mapped plant set.
- Hovering a plant or result row fills the detail panel with the complete source row.
- Clicking a plant or result row locks that plant into the detail panel and centers the map on it.

## Privacy Boundary

Exact coordinates stay in `data/private/` and are not copied into `data/public/`.
Keep `plant_profiles_private.csv`, `plants_reference.json`, and any related derived artifacts outside public outputs.
