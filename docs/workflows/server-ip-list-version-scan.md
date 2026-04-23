# Server IP List Version Scan Workflow

## Purpose

This workflow runs owner-authorized Nmap service-version detection for a small server IP list, then writes JSON outputs and a Markdown report. Service records are split into JSON chunk files so each JSON file stays under the configured size limit, which defaults to 75 MB.

The scan is inventory-oriented. It uses Nmap service-version detection and does not run exploit checks, brute force modules, vulnerability scripts, payloads, or intrusive validation.

## Inputs

- A JSON, JSONL, CSV, or TXT file containing exact server IP addresses or DNS names that you own or are authorized to scan.
- Nmap installed locally.
- Optional lifecycle baseline rules in `config/cybersecurity/vx-version-categories.json`.

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

Replace the example TEST-NET addresses with your own authorized server IPs.

## Default Command

```powershell
C:\Users\Danie\AppData\Local\Python\bin\python.exe scripts\cyber\scan_server_ip_list.py --targets data\private\cybersecurity\imports\server-ip-list.json --i-own-these-servers
```

The `--i-own-these-servers` flag is required before the script will run Nmap. Use `--dry-run` first if you want to validate the target file and write planned commands without scanning.

## Useful Options

Scan only specific ports:

```powershell
C:\Users\Danie\AppData\Local\Python\bin\python.exe scripts\cyber\scan_server_ip_list.py --targets data\private\cybersecurity\imports\server-ip-list.json --i-own-these-servers --ports 22,80,443
```

Use Nmap's top-ports mode:

```powershell
C:\Users\Danie\AppData\Local\Python\bin\python.exe scripts\cyber\scan_server_ip_list.py --targets data\private\cybersecurity\imports\server-ip-list.json --i-own-these-servers --top-ports 200
```

If ICMP probes are blocked for your servers:

```powershell
C:\Users\Danie\AppData\Local\Python\bin\python.exe scripts\cyber\scan_server_ip_list.py --targets data\private\cybersecurity\imports\server-ip-list.json --i-own-these-servers --assume-host-up
```

Change the JSON chunk cap:

```powershell
C:\Users\Danie\AppData\Local\Python\bin\python.exe scripts\cyber\scan_server_ip_list.py --targets data\private\cybersecurity\imports\server-ip-list.json --i-own-these-servers --chunk-size-mb 75
```

## What The Script Runs

For each target, the script runs:

```text
nmap -sV --version-light -oX - <target>
```

It scans one listed target at a time so the output records keep your local labels attached. The script rejects ranges, CIDR blocks, wildcards, and comma-separated target lists by default. The default `--max-targets` value is 16; your planned list of about 5 servers fits inside that.

## Output

Results are written under:

```text
data/private/cybersecurity/scans/<run-label>/<timestamp>/
```

Each run writes:

- `json/service-records-0001.json`, plus additional chunks if needed
- `json/server-version-scan-report.json`
- `json/manifest.json`
- `server-version-scan-report.md`

The manifest records each JSON file path, byte size, SHA-256 hash, and record count. The service chunk files use this shape:

```json
{
  "metadata": {},
  "chunk": {
    "index": 1,
    "record_count": 0,
    "max_bytes": 78643200
  },
  "records": []
}
```

## Safe Handling

- Scan only systems you own or are explicitly authorized to assess.
- Keep outputs under `data/private/cybersecurity/scans/`.
- Treat detected versions as inventory leads, not proof that a host is vulnerable.
- Confirm apparent outdated versions against vendor advisories, OS package metadata, and CISA KEV.
- Do not add exploit steps, payloads, credentials, exposed third-party hosts, or facility-specific remote-access details to this repository.
