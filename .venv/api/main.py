"""Read-only stats API over the Memphis Events warehouse.

Run from the project root:
    uvicorn api.main:app --reload
Design notes: docs/api-design.md
"""

from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Query

from api import db
from api.models import (
    Event,
    EventPage,
    Health,
    MonthCount,
    TrendingCategories,
    TrendingGroups,
)

app = FastAPI(title="Memphis Events Stats API", version="0.1.0")

MONTH_PATTERN = r"^\d{4}-(0[1-9]|1[0-2])$"


@app.get("/health", response_model=Health)
def health(conn=Depends(db.get_conn)):
    db.ping(conn)
    return {"status": "ok", "database": "reachable"}


@app.get("/events", response_model=EventPage)
def list_events(
    month: Optional[str] = Query(None, pattern=MONTH_PATTERN, description="YYYY-MM"),
    category: Optional[str] = Query(None, description="Case-insensitive exact category name"),
    page: int = Query(1, ge=1),
    conn=Depends(db.get_conn),
):
    total, rows = db.list_events(conn, month, category, page)
    return {"page": page, "page_size": db.PAGE_SIZE, "total": total, "items": rows}


@app.get("/events/{event_id}", response_model=Event)
def get_event(event_id: str, conn=Depends(db.get_conn)):
    row = db.get_event(conn, event_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Event not found")
    return row


@app.get("/stats/events-per-month", response_model=list[MonthCount])
def events_per_month(conn=Depends(db.get_conn)):
    return db.events_per_month(conn)


@app.get("/trending/groups", response_model=TrendingGroups)
def trending_groups(
    days: int = Query(90, ge=1, le=730),
    limit: int = Query(10, ge=1, le=50),
    conn=Depends(db.get_conn),
):
    return db.trending_groups(conn, days, limit)


@app.get("/trending/categories", response_model=TrendingCategories)
def trending_categories(
    days: int = Query(90, ge=1, le=730),
    limit: int = Query(10, ge=1, le=50),
    conn=Depends(db.get_conn),
):
    return db.trending_categories(conn, days, limit)
