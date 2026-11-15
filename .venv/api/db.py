"""Database access for the read-only API.

One short-lived psycopg2 connection per request (FastAPI dependency), opened in
a read-only session and always closed. Every query is a parameterized SELECT.
The SQL fragments assembled here are fixed strings; user input only ever
travels as %s parameters.
"""

import logging
import os
from datetime import date
from pathlib import Path
from typing import Iterator, Optional

import psycopg2
from dotenv import load_dotenv
from fastapi import HTTPException
from psycopg2.extras import RealDictCursor

log = logging.getLogger("api.db")

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

PAGE_SIZE = 100
MEMPHIS_TZ = "America/Chicago"

# "Today" in Memphis local time, as a date.
TODAY_SQL = f"(now() AT TIME ZONE '{MEMPHIS_TZ}')::date"


# ---------------------------------------------------------------------------
# Connection handling
# ---------------------------------------------------------------------------

def get_conn() -> Iterator:
    """FastAPI dependency: yield a read-only connection, close it afterwards.

    A new connection per request keeps this simple and leak-free for a local,
    low-traffic API. Unreachable database or bad credentials -> clean 503.
    """
    try:
        conn = psycopg2.connect(
            host=os.getenv("API_DB_HOST"),
            port=os.getenv("API_DB_PORT"),
            dbname=os.getenv("API_DB_NAME"),
            user=os.getenv("API_DB_USER"),
            password=os.getenv("API_DB_PASSWORD"),
            connect_timeout=5,
            options="-c statement_timeout=10000",
        )
    except psycopg2.Error as exc:
        # Log the exception type only; never echo connection details.
        log.error("Database connection failed: %s", type(exc).__name__)
        raise HTTPException(status_code=503, detail="Database unavailable")
    try:
        conn.set_session(readonly=True, autocommit=True)
        yield conn
    except psycopg2.Error as exc:
        log.error("Database query failed: %s", type(exc).__name__)
        raise HTTPException(status_code=503, detail="Database error")
    finally:
        conn.close()


def _fetch_all(conn, sql: str, params: tuple = ()) -> list[dict]:
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(sql, params)
        return cur.fetchall()


def _fetch_one(conn, sql: str, params: tuple = ()) -> Optional[dict]:
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(sql, params)
        return cur.fetchone()


# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------

# Event shape. A catch-all group ("Random Group") means "no group" -> NULL.
EVENT_SELECT = """
    SELECT f.event_id,
           f.name                  AS event_name,
           f.event_date            AS date,
           t.event_type_name       AS event_type,
           c.event_category_name   AS event_category,
           CASE WHEN g.is_catch_all THEN NULL ELSE g.group_name END AS group_name
    FROM fact_events f
    JOIN dim_event_type     t ON t.event_type_id     = f.event_type_id
    JOIN dim_event_category c ON c.event_category_id = f.event_category_id
    JOIN dim_group          g ON g.group_id          = f.group_id
"""


def ping(conn) -> None:
    _fetch_one(conn, "SELECT 1")


def list_events(conn, month: Optional[str], category: Optional[str], page: int) -> tuple[int, list[dict]]:
    """Return (total, rows for this page). month is 'YYYY-MM' (already validated)."""
    conditions, params = [], []
    if month:
        first_day = date.fromisoformat(month + "-01")
        conditions.append("f.event_date >= %s AND f.event_date < (%s::date + interval '1 month')")
        params += [first_day, first_day]
    if category:
        conditions.append("lower(c.event_category_name) = lower(%s)")
        params.append(category)
    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    total = _fetch_one(
        conn,
        f"""
        SELECT count(*) AS n
        FROM fact_events f
        JOIN dim_event_category c ON c.event_category_id = f.event_category_id
        {where}
        """,
        tuple(params),
    )["n"]

    rows = _fetch_all(
        conn,
        f"""
        {EVENT_SELECT}
        {where}
        ORDER BY f.event_date DESC, f.event_id DESC
        LIMIT %s OFFSET %s
        """,
        tuple(params) + (PAGE_SIZE, (page - 1) * PAGE_SIZE),
    )
    return total, rows


def get_event(conn, event_id: str) -> Optional[dict]:
    return _fetch_one(conn, f"{EVENT_SELECT} WHERE f.event_id = %s", (event_id,))


def events_per_month(conn) -> list[dict]:
    """Every month from the first to the last event month, zeros included."""
    return _fetch_all(
        conn,
        """
        WITH bounds AS (
            SELECT date_trunc('month', min(event_date))::date AS first_month,
                   date_trunc('month', max(event_date))::date AS last_month
            FROM fact_events
        ),
        months AS (
            SELECT generate_series(first_month, last_month, interval '1 month')::date AS month_start
            FROM bounds
        )
        SELECT to_char(m.month_start, 'YYYY-MM') AS month,
               count(f.event_id)::int            AS event_count
        FROM months m
        LEFT JOIN fact_events f
               ON f.event_date >= m.month_start
              AND f.event_date <  m.month_start + interval '1 month'
        GROUP BY m.month_start
        ORDER BY m.month_start
        """,
    )


def trending_groups(conn, days: int, limit: int) -> dict:
    window = f"f.event_date >= {TODAY_SQL} - %s::int"
    totals = _fetch_one(
        conn,
        f"""
        SELECT count(*)::int AS events_in_window,
               (count(*) FILTER (WHERE NOT g.is_catch_all))::int AS events_with_group
        FROM fact_events f
        JOIN dim_group g ON g.group_id = f.group_id
        WHERE {window}
        """,
        (days,),
    )
    items = _fetch_all(
        conn,
        f"""
        SELECT g.group_name, count(*)::int AS event_count
        FROM fact_events f
        JOIN dim_group g ON g.group_id = f.group_id
        WHERE {window} AND NOT g.is_catch_all
        GROUP BY g.group_id, g.group_name
        ORDER BY event_count DESC, g.group_name
        LIMIT %s
        """,
        (days, limit),
    )
    return {"window_days": days, **totals, "items": items}


def trending_categories(conn, days: int, limit: int) -> dict:
    window = f"f.event_date >= {TODAY_SQL} - %s::int"
    totals = _fetch_one(
        conn,
        f"SELECT count(*)::int AS events_in_window FROM fact_events f WHERE {window}",
        (days,),
    )
    items = _fetch_all(
        conn,
        f"""
        SELECT c.event_category_name AS event_category, count(*)::int AS event_count
        FROM fact_events f
        JOIN dim_event_category c ON c.event_category_id = f.event_category_id
        WHERE {window}
        GROUP BY c.event_category_id, c.event_category_name
        ORDER BY event_count DESC, c.event_category_name
        LIMIT %s
        """,
        (days, limit),
    )
    return {"window_days": days, **totals, "items": items}


def events_per_category(conn) -> list[dict]:
    """All-time event count per category, highest first (no window)."""
    return _fetch_all(
        conn,
        """
        SELECT c.event_category_name AS event_category, count(f.event_id)::int AS event_count
        FROM dim_event_category c
        LEFT JOIN fact_events f ON f.event_category_id = c.event_category_id
        GROUP BY c.event_category_id, c.event_category_name
        ORDER BY event_count DESC, c.event_category_name
        """,
    )


# Start time that means "unknown" rather than a real 11:59 PM event.
PLACEHOLDER_TIME = "23:59"


def events_per_hour(conn) -> dict:
    """Events per local start hour, excluding NULL times and the 23:59 placeholder."""
    totals = _fetch_one(
        conn,
        """
        SELECT count(*)::int                                          AS events_total,
               (count(*) FILTER (WHERE event_time IS NULL))::int      AS excluded_no_time,
               (count(*) FILTER (WHERE event_time = %s::time))::int   AS excluded_placeholder
        FROM fact_events
        """,
        (PLACEHOLDER_TIME,),
    )
    items = _fetch_all(
        conn,
        """
        WITH usable AS (
            SELECT EXTRACT(hour FROM event_time)::int AS hour
            FROM fact_events
            WHERE event_time IS NOT NULL AND event_time <> %s::time
        ),
        bounds AS (SELECT min(hour) AS first_hour, max(hour) AS last_hour FROM usable),
        hours AS (SELECT generate_series(first_hour, last_hour) AS hour FROM bounds)
        SELECT h.hour, count(u.hour)::int AS event_count
        FROM hours h
        LEFT JOIN usable u ON u.hour = h.hour
        GROUP BY h.hour
        ORDER BY h.hour
        """,
        (PLACEHOLDER_TIME,),
    )
    return {
        **totals,
        "events_with_time": totals["events_total"] - totals["excluded_no_time"] - totals["excluded_placeholder"],
        "items": items,
    }
