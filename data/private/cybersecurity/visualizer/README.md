# Cyber Visualizer

This private local visualizer reads owner-authorized runbook output shards from:

```text
data/private/cybersecurity/runbook-outputs/csv
```

CSV shards are used first because they are smaller and faster for this workflow. If no CSV shards exist, the server falls back to JSONL shards under `runbook-outputs/jsonl`.

Run it from the repository root:

```powershell
python data\private\cybersecurity\visualizer\runner.py
```

Then open:

```text
http://127.0.0.1:8010/
```

Each flow column is filtered by the selections to its left. Column value lists and matching rows page in as you scroll, and each list has its own search field. The `Export column CSV` button writes the currently displayed value/count column to:

```text
data/private/cybersecurity/runbook-outputs/quick-output
```

The `Export matching rows` button writes the full matching source rows to the same quick-output directory. The `Export mapped IPs` button writes the mapped IP coordinate records for the current refined selection.

The map reads point placement from the raw coordinate lookup CSV. The coordinate-specific copy is preferred when present:

```text
data/private/cybersecurity/runbook-outputs/coords/csv/ip-coordinate-lookups.csv
```

Legacy root-level lookup files are still readable when present, but new coordinate runs write to `coords/csv`.

Selecting a map point refines the flow wizard to that coordinate region and shows the matching cached coordinate records from:

```text
data/private/cybersecurity/runbook-outputs/coords/cache/ip-coordinate-cache-*.json
```

Populate or refresh those files with:

```powershell
python scripts\cyber\saturate_runbook_coordinates.py --i-own-these-servers
```

The coordinate lookup writes each newly completed IP into the private report/cache and `coords/csv` plus `coords/jsonl` files as soon as it finishes, so the map can be refreshed while a larger run is still progressing. The default `ip-api` path batches lookups and waits on provider rate-limit headers; cached coordinates are skipped quickly from the sharded cache unless `--force-refresh` is used. It does not modify the source runbook result shards.
