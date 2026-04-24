# Cyber Runbook

## Purpose

This runbook scans a small owner-authorized server IP list, fills the same CSV columns used by the runbook template, and writes sharded CSV and JSONL outputs under:

```text
data\private\cybersecurity\runbook-outputs
```

The workflow is inventory-oriented. It uses Nmap service-version detection only and does not run exploit checks, brute force modules, vulnerability scripts, payloads, or intrusive validation.

## Runbook CSV

Edit:

```text
scripts\cyber\cyber-runbook\server-version-runbook.csv
```

The CSV header is the output contract. Leave every column blank except:

- `ip`: Fill 2-3 exact IP addresses or DNS names you own or are authorized to scan.
- `target_label`: Optional safe local label for each row.

The runner ignores fully blank rows. It rejects CIDR ranges, wildcards, comma lists, whitespace targets, and other expanded target expressions.

## Dry Run

Validate the CSV and write planned commands without scanning:

```powershell
C:\Users\Danie\AppData\Local\Python\bin\python.exe scripts\cyber\cyber-runbook\run_server_version_runbook.py --dry-run
```

## Live Run

Run the service-version scan after confirming authorization:

```powershell
C:\Users\Danie\AppData\Local\Python\bin\python.exe scripts\cyber\cyber-runbook\run_server_version_runbook.py --i-own-these-servers
```

Scan only specific ports:

```powershell
C:\Users\Danie\AppData\Local\Python\bin\python.exe scripts\cyber\cyber-runbook\run_server_version_runbook.py --i-own-these-servers --ports 22,80,443
```

If ICMP probes are blocked for your servers:

```powershell
C:\Users\Danie\AppData\Local\Python\bin\python.exe scripts\cyber\cyber-runbook\run_server_version_runbook.py --i-own-these-servers --assume-host-up
```

## Outputs

Each run writes a timestamped folder:

```text
data\private\cybersecurity\runbook-outputs\<run-label>\<timestamp>\
```

Files written:

- `csv\runbook-results-0001.csv`, with additional numbered shards as needed.
- `jsonl\runbook-results-0001.jsonl`, with additional numbered shards as needed.
- `runbook-summary.json`
- `manifest.json`

The CSV and JSONL result shards use the same columns as the runbook CSV. The default shard limit is 75 MB:

```powershell
C:\Users\Danie\AppData\Local\Python\bin\python.exe scripts\cyber\cyber-runbook\run_server_version_runbook.py --i-own-these-servers --chunk-size-mb 75
```

## Safe Handling

- Scan only systems you own or are explicitly authorized to assess.
- Keep outputs under `data\private\cybersecurity\runbook-outputs`.
- Treat detected versions as inventory leads, not proof that a host is vulnerable.
- Confirm apparent outdated versions against vendor advisories, OS package metadata, and CISA KEV.
- Do not add exploit steps, payloads, credentials, third-party target lists, or facility-specific remote-access details to this repository.
