"""
load.py -- load the newest cleaned events file into the Postgres star schema.

Run from the project root (same place you run extract.py and transform.py):
    python load.py                # load the newest data/clean/events_clean_*.json
    python load.py --dry-run      # validate the file and report; no database connection
    python load.py --init         # run sql/create_tables.sql first, then load
    python load.py --file PATH    # load a specific clean file

Connection: DATABASE_URL (e.g. postgresql://user:pass@localhost:5432/memphis_events),
read from the environment or .env. If it is unset, libpq's PG* variables are used.

Order (see docs/schema-design.md, section 10), all in ONE transaction:
    dim_group, dim_event_type, dim_event_category, dim_date  ->  fact_events upsert
    -> flag events missing from this snapshot as is_active = false.
Re-running never creates duplicates: every table is upserted on its natural key.
"""

import argparse
import json
import logging
import math
import os
import sys
from dataclasses import dataclass
from datetime import date, datetime, time
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger("load")

CLEAN_DIR = Path("data/clean")
GROUPS_FILE = Path("data/reference/groups.json")
CREATE_TABLES_SQL = Path("sql/create_tables.sql")

# Allowed values (same sets transform.py standardizes to).
EVENT_TYPES = ["In-Person", "Virtual", "Hybrid"]
EVENT_CATEGORIES = ["Networking", "Tech Talk", "Workshop", "Entrepreneur", "Conference", "Hackathon", "AI"]

# "Random Group": the source's bucket for events with no group (design doc, 8.1).
CATCH_ALL_GROUP_ID = 29
CATCH_ALL_GROUP_NAME = "Random Group"

# Abort rather than deactivate everything after a failed or partial extract.
MIN_SNAPSHOT_FRACTION = 0.5


# ---------------------------------------------------------------------------
# Reading and validating the clean file (no database needed)
# ---------------------------------------------------------------------------

def clean_value(value: Any) -> Any:
    """NaN, pandas NA-like values and blank strings become None; strings are stripped."""
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    if isinstance(value, str):
        value = value.strip()
        return value or None
    return value


def latest_clean_file() -> Path:
    files = sorted(CLEAN_DIR.glob("events_clean_*.json"))
    if not files:
        raise FileNotFoundError(f"No events_clean_*.json found in {CLEAN_DIR}. Run transform.py first.")
    return files[-1]


def parse_time(value: Any) -> Optional[time]:
    """'HH:MM' -> time. Blank or unparseable becomes None; no placeholder is invented."""
    value = clean_value(value)
    if value is None:
        return None
    try:
        return datetime.strptime(str(value), "%H:%M").time()
    except ValueError:
        log.warning("Unparseable time %r stored as NULL", value)
        return None


def parse_timestamp(value: Any) -> datetime:
    """ISO string ending in Z -> timezone-aware datetime (UTC)."""
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def parse_group_id(value: Any) -> int:
    """Whole number; blank/null maps to the catch-all group. Never a float."""
    value = clean_value(value)
    if value is None:
        return CATCH_ALL_GROUP_ID
    number = float(value)
    if number != int(number):
        raise ValueError(f"group_id {value!r} is not a whole number")
    return int(number)


@dataclass
class Event:
    event_id: str
    date_key: int
    event_date: date
    event_time: Optional[time]
    event_type: str
    event_category: str
    group_id: int
    name: str
    description: Optional[str]
    short_intro: Optional[str]
    created_at: datetime
    updated_at: datetime


def build_event(row: dict) -> Event:
    """Validate one clean-JSON row and convert it to typed values. Raises ValueError if unusable."""
    required = ["event_id", "date", "name", "event_type", "event_category", "created_at", "updated_at"]
    values = {key: clean_value(row.get(key)) for key in required}
    missing = [key for key, v in values.items() if v is None]
    if missing:
        raise ValueError(f"missing required field(s): {missing}")
    if values["event_type"] not in EVENT_TYPES:
        raise ValueError(f"event_type {values['event_type']!r} is not one of {EVENT_TYPES}")
    if values["event_category"] not in EVENT_CATEGORIES:
        raise ValueError(f"event_category {values['event_category']!r} is not one of {EVENT_CATEGORIES}")

    event_date = date.fromisoformat(values["date"])
    return Event(
        event_id=str(values["event_id"]),
        date_key=event_date.year * 10000 + event_date.month * 100 + event_date.day,
        event_date=event_date,
        event_time=parse_time(row.get("time")),
        event_type=values["event_type"],
        event_category=values["event_category"],
        group_id=parse_group_id(row.get("group_id")),
        name=values["name"],
        description=clean_value(row.get("description")),
        short_intro=clean_value(row.get("short_intro")),
        created_at=parse_timestamp(values["created_at"]),
        updated_at=parse_timestamp(values["updated_at"]),
    )


def read_events(path: Path) -> tuple[list[Event], set[str]]:
    """Return (valid events, every event_id present in the file).

    Rows that fail validation are logged and skipped, but their IDs stay in the
    second set so they are not wrongly flagged as removed from the source.
    """
    with path.open(encoding="utf-8") as f:
        rows = json.load(f)
    if not isinstance(rows, list) or not rows:
        raise ValueError(f"{path} is empty or not a JSON array")

    ids = [clean_value(r.get("event_id")) for r in rows]
    present_ids = {i for i in ids if i is not None}
    dupes = {i for i in present_ids if ids.count(i) > 1}
    if dupes:
        raise ValueError(f"duplicate event_id(s) in {path}: {sorted(dupes)[:5]}")

    events, rejected = [], 0
    for position, row in enumerate(rows):
        try:
            events.append(build_event(row))
        except (ValueError, TypeError) as exc:
            rejected += 1
            log.error("Rejected row %s (event_id=%s): %s", position, ids[position], exc)
    log.info("Read %s rows from %s: %s valid, %s rejected", len(rows), path, len(events), rejected)
    return events, present_ids


def read_groups(path: Path = GROUPS_FILE) -> list[dict]:
    with path.open(encoding="utf-8") as f:
        groups = json.load(f)
    ids = [g["id"] for g in groups]
    if len(ids) != len(set(ids)):
        raise ValueError(f"duplicate group id(s) in {path}")
    catch_all = [g for g in groups if g["id"] == CATCH_ALL_GROUP_ID]
    if not catch_all or catch_all[0]["name"] != CATCH_ALL_GROUP_NAME:
        raise ValueError(
            f"group id {CATCH_ALL_GROUP_ID} in {path} is not {CATCH_ALL_GROUP_NAME!r}; "
            "update CATCH_ALL_GROUP_ID/NAME in load.py"
        )
    return groups


def check_groups_exist(events: list[Event], groups: list[dict]) -> None:
    known = {g["id"] for g in groups}
    unknown = sorted({e.group_id for e in events} - known)
    if unknown:
        raise ValueError(f"event group_id(s) not in {GROUPS_FILE}: {unknown}")


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

def connect(autocommit: bool = False):
    import psycopg2
    from dotenv import load_dotenv

    load_dotenv()
    url = os.getenv("DATABASE_URL")
    conn = psycopg2.connect(url) if url else psycopg2.connect()
    conn.autocommit = autocommit
    return conn


def run_init() -> None:
    """Create tables and static seeds from sql/create_tables.sql (idempotent)."""
    sql = CREATE_TABLES_SQL.read_text(encoding="utf-8")
    conn = connect(autocommit=True)  # the script has its own BEGIN/COMMIT
    try:
        with conn.cursor() as cur:
            cur.execute(sql)
        log.info("Ran %s", CREATE_TABLES_SQL)
    finally:
        conn.close()


def upsert_groups(cur, groups: list[dict]) -> None:
    from psycopg2.extras import execute_values

    rows = [(g["id"], g["name"], g.get("description"), g["id"] == CATCH_ALL_GROUP_ID) for g in groups]
    execute_values(
        cur,
        """
        INSERT INTO dim_group (group_id, group_name, group_description, is_catch_all)
        VALUES %s
        ON CONFLICT (group_id) DO UPDATE SET
            group_name = EXCLUDED.group_name,
            group_description = EXCLUDED.group_description,
            is_catch_all = EXCLUDED.is_catch_all
        """,
        rows,
    )
    log.info("dim_group: upserted %s group(s)", len(rows))


def ensure_lookup(cur, table: str, id_col: str, name_col: str, values: list[str]) -> dict[str, int]:
    """Insert any missing values (DO NOTHING) and return {value: surrogate id}."""
    from psycopg2.extras import execute_values

    execute_values(
        cur,
        f"INSERT INTO {table} ({name_col}) VALUES %s ON CONFLICT ({name_col}) DO NOTHING",
        [(v,) for v in values],
    )
    cur.execute(f"SELECT {name_col}, {id_col} FROM {table}")
    return dict(cur.fetchall())


def extend_dim_date(cur, events: list[Event]) -> None:
    """Make sure dim_date covers every event date (no-op while inside the seeded range)."""
    first = min(e.event_date for e in events)
    last = max(e.event_date for e in events)
    cur.execute(
        """
        INSERT INTO dim_date (date_key, full_date, year, quarter, month, month_name,
                              month_start, day_of_week, day_name, is_weekend)
        SELECT
            EXTRACT(year FROM d)::int * 10000 + EXTRACT(month FROM d)::int * 100 + EXTRACT(day FROM d)::int,
            d::date,
            EXTRACT(year FROM d)::smallint,
            EXTRACT(quarter FROM d)::smallint,
            EXTRACT(month FROM d)::smallint,
            trim(to_char(d, 'Month')),
            date_trunc('month', d)::date,
            EXTRACT(isodow FROM d)::smallint,
            trim(to_char(d, 'Day')),
            EXTRACT(isodow FROM d) IN (6, 7)
        FROM generate_series(%s::date, %s::date, interval '1 day') AS g(d)
        ON CONFLICT (date_key) DO NOTHING
        """,
        (first, last),
    )
    log.info("dim_date: ensured coverage %s to %s (%s row(s) added)", first, last, cur.rowcount)


def upsert_events(cur, events: list[Event], type_ids: dict, category_ids: dict) -> tuple[int, int]:
    """Upsert fact_events. Returns (inserted, updated)."""
    from psycopg2.extras import execute_values

    rows = [
        (
            e.event_id, e.date_key, e.event_date, e.event_time,
            type_ids[e.event_type], category_ids[e.event_category], e.group_id,
            e.name, e.description, e.short_intro, e.created_at, e.updated_at,
        )
        for e in events
    ]
    result = execute_values(
        cur,
        """
        INSERT INTO fact_events (event_id, date_key, event_date, event_time, event_type_id,
                                 event_category_id, group_id, name, description, short_intro,
                                 created_at, updated_at)
        VALUES %s
        ON CONFLICT (event_id) DO UPDATE SET
            date_key = EXCLUDED.date_key,
            event_date = EXCLUDED.event_date,
            event_time = EXCLUDED.event_time,
            event_type_id = EXCLUDED.event_type_id,
            event_category_id = EXCLUDED.event_category_id,
            group_id = EXCLUDED.group_id,
            name = EXCLUDED.name,
            description = EXCLUDED.description,
            short_intro = EXCLUDED.short_intro,
            created_at = EXCLUDED.created_at,
            updated_at = EXCLUDED.updated_at,
            is_active = true,
            loaded_at = now()
        RETURNING (xmax = 0) AS inserted
        """,
        rows,
        page_size=500,
        fetch=True,
    )
    inserted = sum(1 for (flag,) in result if flag)
    return inserted, len(result) - inserted


def deactivate_missing(cur, present_ids: set[str]) -> int:
    """Flag events absent from this snapshot as is_active = false. Never deletes rows."""
    cur.execute("SELECT count(*) FROM fact_events WHERE is_active")
    active_before = cur.fetchone()[0]
    if active_before and len(present_ids) < active_before * MIN_SNAPSHOT_FRACTION:
        raise RuntimeError(
            f"Snapshot has {len(present_ids)} event(s) but {active_before} are active in the warehouse "
            f"(less than {MIN_SNAPSHOT_FRACTION:.0%}); aborting so a partial extract cannot deactivate them"
        )
    cur.execute(
        "UPDATE fact_events SET is_active = false WHERE is_active AND event_id <> ALL(%s)",
        (list(present_ids),),
    )
    return cur.rowcount


def load(events: list[Event], present_ids: set[str], groups: list[dict]) -> None:
    conn = connect()
    try:
        with conn:  # one transaction: commit on success, roll back on any error
            with conn.cursor() as cur:
                upsert_groups(cur, groups)
                type_ids = ensure_lookup(cur, "dim_event_type", "event_type_id", "event_type_name", EVENT_TYPES)
                category_ids = ensure_lookup(
                    cur, "dim_event_category", "event_category_id", "event_category_name", EVENT_CATEGORIES
                )
                extend_dim_date(cur, events)
                inserted, updated = upsert_events(cur, events, type_ids, category_ids)
                deactivated = deactivate_missing(cur, present_ids)
        log.info("fact_events: %s inserted, %s updated, %s flagged is_active = false", inserted, updated, deactivated)
    finally:
        conn.close()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="validate the file and report; do not connect")
    parser.add_argument("--init", action="store_true", help="run sql/create_tables.sql before loading")
    parser.add_argument("--file", type=Path, help="clean JSON file to load (default: newest in data/clean)")
    args = parser.parse_args()

    path = args.file or latest_clean_file()
    events, present_ids = read_events(path)
    if not events:
        sys.exit("No valid events to load.")
    groups = read_groups()
    check_groups_exist(events, groups)

    caught_all = sum(1 for e in events if e.group_id == CATCH_ALL_GROUP_ID)
    log.info("Date range %s to %s; %s event(s) in the catch-all group; %s without a time",
             min(e.event_date for e in events), max(e.event_date for e in events), caught_all,
             sum(1 for e in events if e.event_time is None))

    if args.dry_run:
        log.info("Dry run: validation passed, nothing written")
        return
    if args.init:
        run_init()
    load(events, present_ids, groups)


if __name__ == "__main__":
    main()
