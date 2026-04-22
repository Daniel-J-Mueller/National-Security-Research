#!/usr/bin/env python3
"""
Download official EPA RadNet archive ZIPs for station-level background radiation summaries.
"""

from __future__ import annotations

import argparse
import json
import re
import urllib.request
from datetime import UTC, datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data" / "raw" / "radiation" / "epa_radnet"
ZIP_DIR = RAW_DIR / "zips"
DOWNLOAD_PAGE_URL = "https://www.epa.gov/radnet/radnet-csv-file-downloads"
DOWNLOAD_PAGE_HTML = RAW_DIR / "radnet_csv_file_downloads.html"
MANIFEST_JSON = RAW_DIR / "radnet_zip_manifest.json"
USER_AGENT = "Mozilla/5.0 (compatible; National-Security-Research/1.0)"

ZIP_URL_PATTERN = re.compile(
    r"https://www\.epa\.gov/system/files/other-files/\d{4}-\d{2}/[A-Za-z0-9_.-]+\.zip",
    re.IGNORECASE,
)


def fetch_text(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request) as response:
        return response.read().decode("utf-8", errors="replace")


def fetch_binary(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request) as response:
        return response.read()


def unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true", help="re-download ZIPs even if they already exist")
    args = parser.parse_args()

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    ZIP_DIR.mkdir(parents=True, exist_ok=True)

    html = fetch_text(DOWNLOAD_PAGE_URL)
    DOWNLOAD_PAGE_HTML.write_text(html, encoding="utf-8")

    zip_urls = unique(ZIP_URL_PATTERN.findall(html))
    if not zip_urls:
        raise ValueError("No EPA RadNet ZIP URLs were found on the download page")

    downloaded_count = 0
    skipped_count = 0
    manifest_entries: list[dict[str, str]] = []

    for url in zip_urls:
        filename = Path(url).name
        out_path = ZIP_DIR / filename
        if out_path.exists() and not args.force:
            skipped_count += 1
        else:
            payload = fetch_binary(url)
            with out_path.open("wb") as handle:
                handle.write(payload)
            downloaded_count += 1

        manifest_entries.append(
            {
                "archive_zip_url": url,
                "archive_zip_file": str(out_path.relative_to(ROOT)),
                "archive_zip_filename": filename,
            }
        )

    manifest = {
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "download_page_url": DOWNLOAD_PAGE_URL,
        "download_page_file": str(DOWNLOAD_PAGE_HTML.relative_to(ROOT)),
        "zip_count": len(manifest_entries),
        "downloaded_count": downloaded_count,
        "skipped_count": skipped_count,
        "entries": manifest_entries,
    }
    MANIFEST_JSON.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    print(f"Saved RadNet download page to {DOWNLOAD_PAGE_HTML}")
    print(f"Found {len(zip_urls)} archive ZIP files")
    print(f"Downloaded {downloaded_count} ZIPs and skipped {skipped_count}")


if __name__ == "__main__":
    main()
