# Cyber Runbook

## Purpose

This runbook scans a small owner-authorized server target list and writes sharded CSV plus optional sharded JSONL rows under:

```text
data\private\cybersecurity\runbook-outputs
```

The workflow is inventory-oriented. It uses Nmap service-version detection on open ports only and does not run exploit checks, brute force modules, vulnerability scripts, payloads, or intrusive validation.

## Runbook Input

Edit:

```text
data\private\cybersecurity\runbook-input\dry-run-input.csv
```

The input is intentionally just one column:

```csv
ip
127.0.0.1
```

Fill exact IP addresses or DNS names you own or are authorized to scan. The runner ignores blank rows and rejects CIDR ranges, wildcards, comma lists, whitespace targets, and other expanded target expressions.

## Dry Run

Validate the CSV and print planned commands without scanning:

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

Each run resets and writes directly to:

```text
data\private\cybersecurity\runbook-outputs\
```

Files written:

- `csv\runbook-results-0001.csv`, with additional CSV shards as needed
- `jsonl\runbook-results-0001.jsonl`, with additional JSONL shards as needed

The runner starts a one-target worker process for each IP or DNS name, appends that target's rows to the active shards, closes the CSV/JSONL files, and only then moves to the next target.

The CSV and JSONL output rows use these columns:

```text
target,target_label,host,host_status,scan_status,port,protocol,service_name,product,version,extrainfo,cpe,error
```

The default JSONL shard limit is 75 MB:

```powershell
C:\Users\Danie\AppData\Local\Python\bin\python.exe scripts\cyber\cyber-runbook\run_server_version_runbook.py --i-own-these-servers --chunk-size-mb 75
```

## Safe Handling

- Scan only systems you own or are explicitly authorized to assess.
- Keep outputs under `data\private\cybersecurity\runbook-outputs`.
- Treat detected versions as inventory leads, not proof that a host is vulnerable.
- Confirm apparent outdated versions against vendor advisories, OS package metadata, and CISA KEV.
- Do not add exploit steps, payloads, credentials, third-party target lists, or facility-specific remote-access details to this repository.
