# Strategic Resource Visualizer

This static app now loads a category manifest and can switch across:

- private electrical plant records
- municipality population points
- county-level agriculture outputs
- ore and steel-adjacent raw-material sites
- ambient radiation monitor summaries

## What It Loads

The browser app reads:

- `data/private/visualizer/visualizer_manifest.json`

That manifest points to category dataset assets under:

- `data/private/visualizer/datasets/electrical.json`
- `data/private/visualizer/datasets/people.json`
- `data/private/visualizer/datasets/agriculture.json`
- `data/private/visualizer/datasets/raws.json`
- `data/private/visualizer/datasets/radiation.json`

The legacy electrical-only asset is still generated for compatibility:

- `data/private/electrical/visualizer/plants_reference.json`

## Build Order

From the repo root:

```powershell
C:\Windows\py.exe scripts\build_private_plant_profiles.py
C:\Users\Danie\AppData\Local\Python\bin\python.exe scripts\download_radnet_background_data.py
C:\Users\Danie\AppData\Local\Python\bin\python.exe scripts\build_radiation_reference.py
C:\Users\Danie\AppData\Local\Python\bin\python.exe scripts\build_people_municipal_reference.py
C:\Users\Danie\AppData\Local\Python\bin\python.exe scripts\build_agriculture_county_reference.py
C:\Users\Danie\AppData\Local\Python\bin\python.exe scripts\build_raws_reference.py
C:\Users\Danie\AppData\Local\Python\bin\python.exe scripts\build_bulk_exports.py
C:\Users\Danie\AppData\Local\Python\bin\python.exe scripts\build_plant_visualizer_assets.py
```

## Run The Visualizer

Serve the repo root over HTTP, then open:

```powershell
C:\Windows\py.exe scripts\serve_repo_root.py
```

- `http://localhost:8000/docs/plant-emissions-visualizer/`

The page should not be opened with `file:///...` because the browser needs HTTP access to fetch the local JSON assets.

## Interaction Model

- Switch categories with the category selector.
- Change the active metric per category.
- Filter by state, category-specific group, search text, and minimum metric value.
- Toggle between heatmap and point views.
- Hover or click any point or result row to inspect the full source row.

## Privacy Boundary

Public and private category outputs now diverge intentionally:

- public files keep non-sensitive coordinate-backed summaries
- private files retain withheld or richer detail where needed
- the local visualizer reads private category assets and should stay outside public publishing workflows
