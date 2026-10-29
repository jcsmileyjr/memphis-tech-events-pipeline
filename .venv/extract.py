"""
extract.py -- pull entries from the Contentful Content Delivery API and
save the untouched JSON to data/raw/ as a dated snapshot.

Setup:
    pip install requests python-dotenv

    .env (never commit this file):
        CONTENTFUL_SPACE_ID=your_space_id
        CONTENTFUL_ACCESS_TOKEN=your_content_delivery_token
        CONTENTFUL_ENVIRONMENT=master
        CONTENTFUL_CONTENT_TYPE=your_event_content_type_id

Run:
    python extract.py
"""

import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("extract")

SPACE_ID = os.environ["CONTENTFUL_SPACE_ID"]
ACCESS_TOKEN = os.environ["CONTENTFUL_ACCESS_TOKEN"]
ENVIRONMENT = os.getenv("CONTENTFUL_ENVIRONMENT", "master")
CONTENT_TYPE = os.getenv("CONTENTFUL_CONTENT_TYPE")  # optional filter

BASE_URL = f"https://cdn.contentful.com/spaces/{SPACE_ID}/environments/{ENVIRONMENT}/entries"
PAGE_SIZE = 100       # Contentful allows up to 1000; smaller pages keep responses light when include is used
INCLUDE_DEPTH = 2     # resolve linked entries/assets (max 10)
RAW_DIR = Path("data/raw")
MAX_RETRIES = 5


def fetch_page(skip: int) -> dict:
    """Fetch one page of entries, retrying on rate limits and transient errors."""
    params = {
        "limit": PAGE_SIZE,
        "skip": skip,
        "include": INCLUDE_DEPTH,
        "order": "sys.createdAt",  # stable ordering so pages don't shift between calls
    }
    if CONTENT_TYPE:
        params["content_type"] = CONTENT_TYPE

    headers = {"Authorization": f"Bearer {ACCESS_TOKEN}"}

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = requests.get(BASE_URL, params=params, headers=headers, timeout=30)
        except requests.RequestException as exc:
            log.warning("Request error (attempt %s/%s): %s", attempt, MAX_RETRIES, exc)
            time.sleep(2 ** attempt)
            continue

        if resp.status_code == 429:
            wait = int(resp.headers.get("X-Contentful-RateLimit-Reset", 2 ** attempt))
            log.warning("Rate limited; sleeping %ss", wait)
            time.sleep(wait)
            continue

        if resp.status_code >= 500:
            log.warning("Server error %s (attempt %s/%s)", resp.status_code, attempt, MAX_RETRIES)
            time.sleep(2 ** attempt)
            continue

        resp.raise_for_status()  # 4xx (bad token, bad content type) should fail loudly
        return resp.json()

    raise RuntimeError(f"Failed to fetch page at skip={skip} after {MAX_RETRIES} attempts")


def extract_all() -> dict:
    """Page through every entry and return a single combined payload."""
    items = []
    linked_entries = {}
    linked_assets = {}
    skip = 0
    total = None

    while True:
        page = fetch_page(skip)
        total = page["total"]
        items.extend(page["items"])

        # Each page returns its own includes; merge by sys.id so links resolve later
        includes = page.get("includes", {})
        for entry in includes.get("Entry", []):
            linked_entries[entry["sys"]["id"]] = entry
        for asset in includes.get("Asset", []):
            linked_assets[asset["sys"]["id"]] = asset

        log.info("Fetched %s/%s entries", len(items), total)
        skip += PAGE_SIZE
        if skip >= total:
            break

    if len(items) != total:
        log.warning("Expected %s entries but collected %s", total, len(items))

    return {
        "extracted_at": datetime.now(timezone.utc).isoformat(),
        "space_id": SPACE_ID,
        "environment": ENVIRONMENT,
        "content_type": CONTENT_TYPE,
        "total": total,
        "items": items,
        "includes": {
            "Entry": list(linked_entries.values()),
            "Asset": list(linked_assets.values()),
        },
    }


def save_raw(payload: dict) -> Path:
    """Write the untouched payload to a dated file. Raw layer: never edit it afterwards."""
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    out_path = RAW_DIR / f"events_{datetime.now().strftime('%Y-%m-%d')}.json"
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return out_path


def main() -> None:
    payload = extract_all()
    path = save_raw(payload)
    log.info("Saved %s entries to %s", payload["total"], path)


if __name__ == "__main__":
    main()
