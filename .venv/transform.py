"""
transform.py -- flatten the raw Contentful snapshot, trim it to the columns
you care about, standardize event_type, event_category and time values, and report duplicate IDs and
missing values.

Run from the project root (same place you run extract.py):
    python src/transform.py            # transform the newest raw snapshot
    python src/transform.py --inspect  # just print every column json_normalize finds

Workflow: run --inspect first, then edit COLUMN_MAP below to match your real fields.
"""

import json
import logging
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

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
    "fields.rsvp": "rsvp",
    "fields.description": "description",
    "fields.shortIntro": "short_intro",
}
ID_COLUMN = "event_id"

# Canonical eventType values. The lookup key is the raw value lowercased with
# everything except letters removed, so "In-Person", "In Person" and "INPERSON"
# all become "inperson" and map to the same canonical value.
EVENT_TYPE_CANONICAL = {
    "inperson": "In-Person",
    "virtual": "Virtual",
    "hybrid": "Hybrid",
}

# Canonical eventCategory values, same key rule as above.
# "Tech TalkNetworking" is a known data-entry glitch (two categories run together);
# it is deliberately mapped to "Tech Talk".
EVENT_CATEGORY_CANONICAL = {
    "networking": "Networking",
    "techtalk": "Tech Talk",
    "techtalknetworking": "Tech Talk",
    "workshop": "Workshop",
    "entrepreneur": "Entrepreneur",
    "conference": "Conference",
    "hackathon": "Hackathon",
    "ai": "AI",
}


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


def standardize_column(df: pd.DataFrame, column: str, canonical: dict) -> pd.DataFrame:
    """Collapse spelling/case variants in `column` into the canonical values.

    `canonical` maps a normalized key (lowercase, letters only) to the final value.
    Unknown values are left unchanged and logged, never guessed at.
    """
    if column not in df.columns:
        log.warning("%s column not found; skipping standardization", column)
        return df

    df = df.copy()
    raw = df[column]
    keys = raw.astype("string").str.lower().str.replace(r"[^a-z]", "", regex=True)
    mapped = keys.map(canonical)

    # Only overwrite where we recognized the value; keep everything else as-is
    recognized = mapped.notna()
    changed = recognized & (raw != mapped)
    log.info("%s: standardized %s value(s)", column, int(changed.sum()))
    df.loc[recognized, column] = mapped[recognized]

    unknown = raw[~recognized & raw.notna()]
    if not unknown.empty:
        log.warning(
            "%s: %s value(s) not in the canonical lookup (left unchanged): %s",
            column,
            len(unknown),
            unknown.value_counts().to_dict(),
        )
    return df


# Matches "18:00", "9:15", "0900", "1730", "4PM", "11 am", "4:30 PM"
TIME_PATTERN = re.compile(r"^(\d{1,2}):?(\d{2})?\s*([ap]m)?$", re.IGNORECASE)


def normalize_time(value) -> Optional[str]:
    """Convert a messy time string to 24-hour 'HH:MM'. Returns None if it can't be parsed."""
    if value is None or pd.isna(value):
        return None
    match = TIME_PATTERN.match(str(value).strip())
    if not match:
        return None

    hour_text, minute_text, meridiem = match.groups()
    # A bare number like "9" is ambiguous: require minutes or AM/PM
    if minute_text is None and meridiem is None:
        return None

    hour = int(hour_text)
    minute = int(minute_text) if minute_text else 0
    if minute > 59:
        return None

    if meridiem:
        if not 1 <= hour <= 12:
            return None
        hour = hour % 12 + (12 if meridiem.lower() == "pm" else 0)
    elif hour > 23:
        return None

    return f"{hour:02d}:{minute:02d}"


def standardize_time(df: pd.DataFrame, column: str = "time") -> pd.DataFrame:
    """Normalize the time column to 'HH:MM'. Unparseable values are left unchanged and logged."""
    if column not in df.columns:
        log.warning("%s column not found; skipping standardization", column)
        return df

    df = df.copy()
    raw = df[column]
    parsed = raw.map(normalize_time)

    recognized = parsed.notna()
    changed = recognized & (raw != parsed)
    log.info("%s: standardized %s value(s)", column, int(changed.sum()))
    df.loc[recognized, column] = parsed[recognized]

    unknown = raw[~recognized & raw.notna()]
    if not unknown.empty:
        log.warning(
            "%s: %s value(s) could not be parsed (left unchanged): %s",
            column,
            len(unknown),
            unknown.value_counts().to_dict(),
        )
    return df


def check_time_format(df: pd.DataFrame, column: str = "time") -> None:
    """Confirm every non-null time is in 'HH:MM' form and show the final distinct values."""
    if column not in df.columns:
        return
    values = df[column].dropna()
    bad = values[~values.astype(str).str.fullmatch(r"\d{2}:\d{2}")]
    log.info("%s: %s distinct value(s) after cleaning", column, values.nunique())
    if bad.empty:
        log.info("%s: all values are in HH:MM format", column)
    else:
        log.warning("%s: %s value(s) not in HH:MM format: %s", column, len(bad), bad.unique().tolist())


def check_allowed_values(df: pd.DataFrame, column: str, allowed: set) -> None:
    """Log the final value counts for a column and flag anything outside the allowed set."""
    if column not in df.columns:
        return
    counts = df[column].value_counts(dropna=False)
    log.info("%s value counts: %s", column, counts.to_dict())
    bad = df[~df[column].isin(allowed) & df[column].notna()]
    if bad.empty:
        log.info("%s: all values are in the allowed set", column)
    else:
        log.warning("%s: %s row(s) outside allowed set %s", column, len(bad), sorted(allowed))


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
    clean = standardize_column(clean, "event_type", EVENT_TYPE_CANONICAL)
    clean = standardize_column(clean, "event_category", EVENT_CATEGORY_CANONICAL)
    clean = standardize_time(clean, "time")
    check_time_format(clean, "time")
    check_allowed_values(clean, "event_type", set(EVENT_TYPE_CANONICAL.values()))
    check_allowed_values(clean, "event_category", set(EVENT_CATEGORY_CANONICAL.values()))
    report_quality(clean)
    out = save_clean(clean)
    log.info("Saved %s rows to %s", len(clean), out)


if __name__ == "__main__":
    main()
