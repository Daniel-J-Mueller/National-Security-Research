# Radiation Sources

This note tracks official coordinate-backed radiation sources being added to the repo.

## Active source

1. EPA RadNet near-real-time air monitor archives
   - Download page: `https://www.epa.gov/radnet/radnet-csv-file-downloads`
   - Data type: station-level gamma background and dose-equivalent monitoring results
   - Coordinate strategy: join EPA station-city names to Census Gazetteer 2024 place centroids
   - Why it fits: official EPA radiation monitoring, stable monitor points, and clean coordinate association

## First-pass outputs

- `data/raw/radiation/epa_radnet/`
- `data/public/radiation/radnet_background_radiation_monitors.csv`
- `data/private/radiation/radnet_background_radiation_monitors_private.csv`

## Next official candidates

1. EPA Radon Zone Map
   - Useful for county-scale indoor radiation risk context
2. NRC operating reactor radiation performance indicators
   - Useful for plant-adjacent radiological performance context, but not the same as ambient background radiation
3. DOE or USGS radiological legacy-site inventories
   - Useful for expanding beyond monitor points into historic contamination or remediation footprints
