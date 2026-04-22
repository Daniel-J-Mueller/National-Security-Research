# People Sources

This category links public population counts to municipal coordinates.

## Active official sources

1. Census place population estimates
   - Purpose: annual municipal population counts.
   - URL: https://www2.census.gov/programs-surveys/popest/datasets/2020-2024/cities/totals/sub-est2024.csv
2. Census Gazetteer place file
   - Purpose: place centroid coordinates and geometry metadata.
   - URL: https://www2.census.gov/geo/docs/maps-data/data/gazetteer/2024_Gazetteer/2024_Gaz_place_national.zip
3. US_Town_Halls municipal directory
   - Purpose: town-hall coordinates used as a civic-location anchor for local population outputs.
   - URL: https://github.com/Daniel-J-Mueller/US_Town_Halls

## Current output

- `data/public/people/municipal_population_town_halls_2024.csv`

## Join strategy

- Match Census places to town-hall localities by normalized city or town name plus state.
- Prefer town-hall coordinates when a clean municipal match exists.
- Fall back to Census place centroids when no town-hall coordinate is available.
