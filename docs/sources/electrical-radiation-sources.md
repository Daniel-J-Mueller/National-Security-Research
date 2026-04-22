# Electrical Radiation Sources

This note tracks official radiation-related sources for the electrical category.

## Current state

- `radioisotopic_emissions_value` remains blank in the current plant profile build.
- The existing EPA eGRID and PM2.5 workbooks do not populate a plant-level radioisotopic field.

## Candidate official sources

1. NRC operating reactor performance indicators
   - Relevant measures: public radiation safety and occupational radiation safety.
   - Search anchor: https://www.nrc.gov/reactors/operating/oversight/docket-chart
   - Notes: promising for a numeric per-reactor radiation-related series, but not a direct substitute for radioisotopic emission totals.
2. NRC annual occupational radiation reports
   - Search anchor: https://www.nrc.gov/reading-rm/doc-collections/nuregs/staff/sr0713/
   - Notes: official annual radiation exposure reporting; likely useful for a reactor-level radiation layer.

## Implementation note

The repo is now structured so an NRC-backed join can be added under:

- `data/raw/electrical/nrc/`
- `data/private/electrical/eia860_2024/`

without changing the public or visualizer folder layout again.
