# Server IP List Version Scan Workflow

## Purpose

This workflow runs owner-authorized Nmap service-version detection for a server IP list, then writes sharded CSV plus optional sharded JSONL rows. The scanner keeps only concise service inventory fields for open ports.

The scan is inventory-oriented. It does not run exploit checks, brute force modules, vulnerability scripts, payloads, or intrusive validation.

## Inputs

- A JSON, JSONL, CSV, or TXT file containing exact server IP addresses or DNS names that you own or are authorized to scan.
- Nmap installed locally.

The CSV shape can be as small as:

```csv
target,target_label
127.0.0.1,local-loopback
```

The JSON shape can be either a list:

```json
[
  "203.0.113.10",
  "198.51.100.25"
]
```

Or an object with labels:

```json
{
  "targets": [
    {
      "label": "home-web",
      "ip": "203.0.113.10"
    },
    {
      "label": "office-db",
      "ip": "198.51.100.25"
    }
  ]
}
```

Replace the example addresses with your own authorized server IPs.

## Default Command

```powershell
C:\Users\Danie\AppData\Local\Python\bin\python.exe scripts\cyber\scan_server_ip_list.py --i-own-these-servers
```

The default target file is:

```text
data/private/cybersecurity/runbook-input/dry-run-input.csv
```

You can override it when needed:

```powershell
C:\Users\Danie\AppData\Local\Python\bin\python.exe scripts\cyber\scan_server_ip_list.py --targets data\private\cybersecurity\imports\other-server-list.json --i-own-these-servers
```

The `--i-own-these-servers` flag is required before the script will run Nmap. Use `--dry-run` first if you want to validate the target file and print planned commands without scanning.

If the default input is the generated all-IPv4 dry-run file, the reader fast-forwards past the leading `0.0.0.0/8` block and starts at IPv4 address index `16,777,216` (`1.0.0.0`). In CSV line-number terms, that is line `16,777,218` because line 1 is the header and line 2 is `0.0.0.0`. Live scans still require a target file containing only systems you own or are authorized to assess.

The default per-target timeout is 120 seconds. The runner passes that value to both Python's process timeout and Nmap's `--host-timeout`.

## Useful Options

Scan only specific ports:

```powershell
C:\Users\Danie\AppData\Local\Python\bin\python.exe scripts\cyber\scan_server_ip_list.py --i-own-these-servers --ports 22,80,443
```

Use Nmap's top-ports mode:

```powershell
C:\Users\Danie\AppData\Local\Python\bin\python.exe scripts\cyber\scan_server_ip_list.py --i-own-these-servers --top-ports 200
```

If ICMP probes are blocked for your servers:

```powershell
C:\Users\Danie\AppData\Local\Python\bin\python.exe scripts\cyber\scan_server_ip_list.py --i-own-these-servers --assume-host-up
```

Optionally cap one run during testing. By default there is no artificial target limit:

```powershell
C:\Users\Danie\AppData\Local\Python\bin\python.exe scripts\cyber\scan_server_ip_list.py --dry-run --max-targets 25
```

Change the CSV/JSONL shard cap:

```powershell
C:\Users\Danie\AppData\Local\Python\bin\python.exe scripts\cyber\scan_server_ip_list.py --i-own-these-servers --chunk-size-mb 75
```

Skip JSONL and write only the CSV shards:

```powershell
C:\Users\Danie\AppData\Local\Python\bin\python.exe scripts\cyber\scan_server_ip_list.py --i-own-these-servers --no-jsonl
```

## What The Script Runs

For each target, the script runs:

```text
nmap --open -sV --version-light --host-timeout 120s -oX - <target>
```

It scans one listed target at a time so output records keep local labels attached. Duplicate exact IPs or DNS names in the input list are scanned once. The script rejects ranges, CIDR blocks, wildcards, and comma-separated target lists by default. The default `--max-targets` value is `0`, which means no artificial limit.

## Output

Results are written under:

```text
data/private/cybersecurity/runbook-outputs/
```

Each run writes:

- `csv/runbook-results-0001.csv`, plus additional CSV shards if needed
- `jsonl/runbook-results-0001.jsonl`, plus additional JSONL shards if needed

The runner starts a one-target worker process for each IP or DNS name, appends that target's rows to the active shards, closes the CSV/JSONL files, and only then moves to the next target.

The CSV and JSONL rows use these fields:

```text
target,target_label,host,host_status,scan_status,port,protocol,service_name,product,version,extrainfo,cpe,error
```

Rows with open ports use `scan_status=open-service`. Targets with no open services are omitted from the CSV/JSONL outputs. Errors and dry-run rows are still represented once with the appropriate `scan_status`.

## Coordinate Lookup

Runbook result CSV/JSONL shards do not carry coordinate columns. The coordinate lookup script writes raw coordinate records separately after a run:

```powershell
C:\Users\Danie\AppData\Local\Python\bin\python.exe scripts\cyber\saturate_runbook_coordinates.py --i-own-these-servers
```

The coordinate script writes:

- `coords/csv/ip-coordinate-lookups.csv`
- `coords/jsonl/ip-coordinate-lookups.jsonl`
- `coords/cache/ip-coordinate-cache-*.json`
- `coords/cache/ip-coordinate-cache-manifest.json`

By default the coordinate script writes each completed IP to the private coordinate CSV/JSONL files immediately. The default `ip-api` provider uses its batch endpoint, up to 100 IPs per request, and honors the provider's `X-Rl`/`X-Ttl` rate-limit headers before continuing.

```powershell
C:\Users\Danie\AppData\Local\Python\bin\python.exe scripts\cyber\saturate_runbook_coordinates.py --i-own-these-servers --workers 64
```

Use `--only-ip 1.0.208.102` to update one address, `--fallback-provider ipapi-co` to try a second provider if the default `ip-api` lookup fails, or `--ip-api-batch-size 1` to intentionally use the older per-IP lookup behavior. For very large refreshes, a local GeoIP database is preferable because it avoids public API rate limits.

Consecutive runs use the sharded cache to skip both ping and provider lookup for IPs that already have cached `long`/`lat`, unless `--force-refresh` is used. Use `--reconcile-coordinate-store` when you intentionally want to scan older raw coordinate reports and fill missing cache/report fields before processing.

The first CSV shard can be passed to the defensive artifact matcher:

```powershell
C:\Users\Danie\AppData\Local\Python\bin\python.exe scripts\cyber\match_server_defensive_artifacts.py --servers-csv data\private\cybersecurity\runbook-outputs\csv\runbook-results-0001.csv
```

## Safe Handling

- Scan only systems you own or are explicitly authorized to assess.
- Keep outputs under `data/private/cybersecurity/runbook-outputs/`.
- Treat detected versions as inventory leads, not proof that a host is vulnerable.
- Confirm apparent outdated versions against vendor advisories, OS package metadata, and CISA KEV.
