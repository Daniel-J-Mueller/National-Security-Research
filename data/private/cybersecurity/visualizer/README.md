# Cybersecurity Runbook Flow Visualizer

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

Each flow column is filtered by the selections to its left. The `Export column CSV` button writes the currently displayed value/count column to:

```text
data/private/cybersecurity/runbook-outputs/quick-output
```

The `Export matching rows` button writes the full matching source rows to the same quick-output directory.
