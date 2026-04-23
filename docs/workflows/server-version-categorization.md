# Server Version Categorization Workflow

## Purpose

This workflow inventories exposed services on a server you own, captures product/version strings with standard Nmap service detection, and sorts the results into defensive VX-style version categories.

The reference to vx-underground is used only as a loose sorting inspiration: collect observed items, group them by family/version, and keep clear category labels. This workflow does not use malware samples, exploit code, IOCs, leaked data, or offensive procedures.

## Inputs

- A server IP address or DNS name that you own or are authorized to scan.
- Nmap installed locally.
- Optional lifecycle baseline rules in `config/cybersecurity/vx-version-categories.json`.

## Default Command

```powershell
C:\Users\Danie\AppData\Local\Python\bin\python.exe scripts\categorize_server_versions.py --target 203.0.113.10 --i-own-this-server
```

Replace `203.0.113.10` with your server IP. The `--i-own-this-server` flag is required before the script will run Nmap.

## Useful Options

Scan only specific ports:

```powershell
C:\Users\Danie\AppData\Local\Python\bin\python.exe scripts\categorize_server_versions.py --target 203.0.113.10 --i-own-this-server --ports 22,80,443
```

Use Nmap's top-ports mode:

```powershell
C:\Users\Danie\AppData\Local\Python\bin\python.exe scripts\categorize_server_versions.py --target 203.0.113.10 --i-own-this-server --top-ports 200
```

Parse an existing Nmap XML file instead of scanning:

```powershell
C:\Users\Danie\AppData\Local\Python\bin\python.exe scripts\categorize_server_versions.py --from-nmap-xml data\private\cybersecurity\imports\server-scan.xml --target-label my-server
```

If ICMP probes are blocked for your server:

```powershell
C:\Users\Danie\AppData\Local\Python\bin\python.exe scripts\categorize_server_versions.py --target 203.0.113.10 --i-own-this-server --assume-host-up
```

## What The Script Runs

By default the script runs:

```text
nmap -sV --version-light -oX - <target>
```

It does not run exploit checks, vulnerability scripts, brute force modules, or intrusive validation. Results are categorized from the service fingerprint metadata in the Nmap XML.

## Output

Results are written under:

```text
data/private/cybersecurity/scans/<target-label>/<timestamp>/
```

Each run writes:

- `service-version-categories.json`
- `service-version-categories.csv`
- `nmap-service-scan.xml`, unless `--no-save-raw-xml` is used

These outputs can contain sensitive exposure details and should stay private.

## Categories

| Category | Meaning |
| --- | --- |
| `vx-unknown-fingerprint` | Open service, but no usable product/version was detected. |
| `vx-review-versioned` | Product/version detected, but no enabled lifecycle baseline matched. |
| `vx-baseline-accepted` | Version met an enabled local baseline rule. |
| `vx-baseline-behind` | Version was below an enabled local minimum-supported baseline. |
| `vx-eol-or-legacy` | Version was below an enabled local EOL/legacy threshold. |

The script also adds defensive flags, such as `remote_admin_service`, `database_service`, or `cleartext_or_legacy_service`, when a detected service name or port deserves extra review.

## Configure Version Baselines

Edit:

```text
config/cybersecurity/vx-version-categories.json
```

The bundled rules are disabled examples. Enable and adjust them only after checking the vendor or OS distribution support baseline. This matters because Linux distributions often backport security patches while keeping an older upstream version string.

Example rule shape:

```json
{
  "id": "org-openssh-baseline",
  "enabled": true,
  "service_name_regex": "^ssh$",
  "product_regex": "OpenSSH",
  "minimum_supported_version": "9.6",
  "eol_below_version": "8.4",
  "notes": "Use the organization's approved OpenSSH baseline."
}
```

## Safe Handling

- Scan only systems you own or are explicitly authorized to assess.
- Keep output under `data/private/cybersecurity/scans/`.
- Treat versions as leads, not proof of vulnerability.
- Verify apparent outdated versions against vendor advisories, OS package metadata, and CISA KEV.
- Do not add exploit steps, payloads, credentials, exposed third-party hosts, or facility-specific remote-access details to this repository.
