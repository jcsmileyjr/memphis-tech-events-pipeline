"""
transform.py -- flatten the raw Contentful snapshot, trim it to the columns
you care about, and report duplicate IDs and missing values.

Run from the project root (same place you run extract.py):
    python src/transform.py            # transform the newest raw snapshot
    python src/transform.py --inspect  # just print every column json_normalize finds

Workflow: run --inspect first, then edit COLUMN_MAP below to match your real fields.
"""

import json
import logging
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("transform")

RAW_DIR = Path("data/raw")
CLEAN_DIR = Path("data/clean")

# Left side: the column name json_normalize produces (see --inspect output).
# Right side: the name you want in your clean dataset.
# These field names are GUESSES from your project notes. Edit them to match your space.
COLUMN_MAP = {
    "sys.id": "event_id",
    "sys.createdAt": "created_at",
    "sys.updatedAt": "updated_at",
    "fields.name": "name",
    "fields.date": "date",
    "fields.time": "time",
    "fields.eventType": "event_type",
    "fields.eventCategory": "event_category",
    "fields.RSVP": "rsvp",
    "fields.description": "description",
    "fields.shortIntro": "short_intro",
}
ID_COLUMN = "event_id"


def latest_raw_file() -> Path:
    files = sorted(RAW_DIR.glob("events_*.json"))
    if not files:
        raise FileNotFoundError(f"No events_*.json found in {RAW_DIR}. Run extract.py first.")
    return files[-1]


def flatten(payload: dict) -> pd.DataFrame:
    """Unnest the Contentful items into one row per entry."""
    return pd.json_normalize(payload["items"])


def trim(df: pd.DataFrame) -> pd.DataFrame:
    """Keep only the mapped columns and rename them."""
    missing_sources = [col for col in COLUMN_MAP if col not in df.columns]
    if missing_sources:
        log.warning("COLUMN_MAP references columns not in the data (skipped): %s", missing_sources)
    present = {src: dst for src, dst in COLUMN_MAP.items() if src in df.columns}
    return df[list(present)].rename(columns=present)


def report_quality(df: pd.DataFrame) -> None:
    """Log duplicate IDs and missing values. Reports only; does not change the data."""
    log.info("Rows: %s | Columns: %s", len(df), len(df.columns))

    if ID_COLUMN in df.columns:
        dupes = df[df.duplicated(subset=ID_COLUMN, keep=False)]
        if dupes.empty:
            log.info("Duplicate %s: none", ID_COLUMN)
        else:
            log.warning("Duplicate %s: %s rows share an ID", ID_COLUMN, len(dupes))
            log.warning("Sample duplicate IDs: %s", dupes[ID_COLUMN].unique()[:5].tolist())
    else:
        log.warning("ID column '%s' not found; skipping duplicate check", ID_COLUMN)

    # Count both true nulls and empty/whitespace-only strings as missing
    def is_missing(series: pd.Series) -> pd.Series:
        return series.isna() | series.astype(str).str.strip().eq("")

    log.info("Missing values per column:")
    for col in df.columns:
        n = int(is_missing(df[col]).sum())
        pct = n / len(df) * 100 if len(df) else 0
        flag = "  <-- check" if n else ""
        log.info("  %-18s %4d missing (%5.1f%%)%s", col, n, pct, flag)


def save_clean(df: pd.DataFrame) -> Path:
    CLEAN_DIR.mkdir(parents=True, exist_ok=True)
    out = CLEAN_DIR / f"events_clean_{datetime.now().strftime('%Y-%m-%d')}.json"
    # orient="records" writes an array of objects: [{...}, {...}]
    df.to_json(out, orient="records", indent=2, date_format="iso", force_ascii=False)
    return out


def main() -> None:
    raw_path = latest_raw_file()
    log.info("Reading %s", raw_path)
    with raw_path.open(encoding="utf-8") as f:
        payload = json.load(f)

    flat = flatten(payload)

    if "--inspect" in sys.argv:
        log.info("Columns found by json_normalize:")
        for col in flat.columns:
            log.info("  %s", col)
        return

    clean = trim(flat)
    report_quality(clean)
    out = save_clean(clean)
    log.info("Saved %s rows to %s", len(clean), out)


if __name__ == "__main__":
    main()
