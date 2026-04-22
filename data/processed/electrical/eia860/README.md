# EIA-860 Processed Data

This folder contains cleaned plant-level outputs derived from the official 2024 EIA-860 workbook set.

Current files:

- `plants_2024_clean.csv`
- `ingestion_metadata_2024.json`

The cleaned plant table intentionally excludes:

- street address
- latitude
- longitude

To rebuild these outputs, run:

```powershell
C:\Windows\py.exe scripts\ingest_eia860_plants.py
```
