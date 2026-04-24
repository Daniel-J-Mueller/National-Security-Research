# Server Defensive Artifact Matching Workflow

## Purpose

This workflow enriches a private server inventory CSV with safe defensive hardening snippets. It is the safe replacement for trying to download and sort malware-archive material: the script processes local defensive catalog chunks, saves matched hardening snippets, and writes a new CSV with snippet references.

It does not download vx-underground, malware samples, exploit code, payloads, credentials, proof-of-concept material, or offensive procedures.

## Inputs

- A CSV of servers or service scan results that you own or are authorized to assess.
- A local defensive artifact catalog, defaulting to `config/cybersecurity/defensive-artifact-catalog.json`.

The CSV can come from your own inventory export, `scripts/cyber/categorize_server_versions.py`, or `runbook-outputs/csv/runbook-results-0001.csv` written by the runbook scanner. The matcher looks for common columns such as:

- `server`, `host`, `hostname`, `ip`, `target`, or `asset_id`
- `port`
- `service_name` or `service`
- `product`
- `version`
- `cpe`
- `flags`

## Default Command

```powershell
C:\Users\Danie\AppData\Local\Python\bin\python.exe scripts\cyber\match_server_defensive_artifacts.py --servers-csv data\private\cybersecurity\imports\office-home-servers.csv
```

After a batch IP-list scan, point the matcher at the generated private CSV:

```powershell
C:\Users\Danie\AppData\Local\Python\bin\python.exe scripts\cyber\match_server_defensive_artifacts.py --servers-csv data\private\cybersecurity\runbook-outputs\csv\runbook-results-0001.csv
```

## Chunked Catalog Processing

For a larger safe catalog, place JSON, JSONL, or CSV chunks in a directory and point `--catalog` at that directory:

```powershell
C:\Users\Danie\AppData\Local\Python\bin\python.exe scripts\cyber\match_server_defensive_artifacts.py --servers-csv data\private\cybersecurity\imports\office-home-servers.csv --catalog data\private\cybersecurity\safe-catalog-chunks --stop-when-covered
```

The `--stop-when-covered` option stops after every row has at least one non-fallback defensive artifact. Without it, the script reads every supplied catalog chunk and attaches up to `--max-artifacts-per-row` matches per row.

## Output

Results are written under:

```text
data/private/cybersecurity/artifact-matches/<label>/<timestamp>/
```

Each run writes:

- `server-defensive-artifact-matches.csv`
- `server-defensive-artifact-matches.json`
- `snippets/*.md`

The enriched CSV preserves the input columns and adds:

- `defensive_artifact_ids`
- `defensive_artifact_titles`
- `defensive_match_status`
- `defensive_match_rationale`
- `defensive_snippet_paths`
- `defensive_references`

Every row receives at least one defensive artifact. Rows that do not match a specific catalog item receive the fallback `general-service-inventory-review` artifact.

## Catalog Shape

The default catalog is a JSON file with an `artifacts` list. Each artifact must be explicitly defensive:

```json
{
  "id": "web-service-hardening-review",
  "artifact_type": "defensive-hardening",
  "title": "Web Service Hardening Review",
  "priority": "medium",
  "match_any": [
    {
      "service_name_regex": "^(http|https|http-alt)$"
    },
    {
      "port_in": [80, 443, 8080, 8443]
    }
  ],
  "match_rationale": "Web services are common internet-facing entry points.",
  "references": [
    {
      "name": "CISA Known Exploited Vulnerabilities Catalog",
      "url": "https://www.cisa.gov/known-exploited-vulnerabilities-catalog"
    }
  ],
  "snippet": "Confirm the web service is intentionally exposed..."
}
```

Supported `artifact_type` values are:

- `defensive-hardening`
- `defensive-reference`
- `detection-rule-reference`
- `vendor-advisory-reference`
- `general-review`

## Safe Handling

- Use this only with server inventories you own or are authorized to assess.
- Keep outputs private because enriched CSVs can reveal service exposure details.
- Treat matched snippets as hardening prompts, not proof that a server is vulnerable.
- Confirm version findings with vendor advisories, OS package metadata, and CISA KEV.
- Do not add malware samples, exploit procedures, payloads, credentials, or exposed third-party systems to the catalog.
