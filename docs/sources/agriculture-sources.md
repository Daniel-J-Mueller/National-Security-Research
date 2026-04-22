# Agriculture Sources

This category is the starting source log for coordinate-backed agriculture outputs.

## Priority official sources

1. USDA NASS Quick Stats
   - Purpose: county-level crop, livestock, and milk production for major food outputs.
   - URL: https://www.nass.usda.gov/Quick_Stats/
   - Planned coordinate strategy: join county-level production rows to Census county centroids when facility-level coordinates are not available.
2. Census Gazetteer county files
   - Purpose: latitude/longitude centroids for county-based agriculture summaries.
   - URL: https://www.census.gov/geographies/reference-files/time-series/geo/gazetteer-files.html
3. USDA ERS food-system references
   - Purpose: identify high-value food production and processing patterns worth normalizing after the first county output pass.
   - URL: https://www.ers.usda.gov/

## Initial normalization plan

- `commodity`
- `state`
- `county`
- `latitude`
- `longitude`
- `geometry_precision`
- `output_value`
- `output_unit`
- `reporting_year`
- `source_name`
