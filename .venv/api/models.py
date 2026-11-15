"""Pydantic response models for the Memphis Events stats API."""

from datetime import date
from typing import Optional

from pydantic import BaseModel


class Event(BaseModel):
    event_id: str
    event_name: str
    date: date
    event_type: str
    event_category: str
    group_name: Optional[str] = None  # null when the event has no group (always present)


class EventPage(BaseModel):
    page: int
    page_size: int
    total: int
    items: list[Event]


class MonthCount(BaseModel):
    month: str  # YYYY-MM
    event_count: int


class GroupCount(BaseModel):
    group_name: str
    event_count: int


class TrendingGroups(BaseModel):
    window_days: int
    events_in_window: int
    events_with_group: int
    items: list[GroupCount]


class CategoryCount(BaseModel):
    event_category: str
    event_count: int


class TrendingCategories(BaseModel):
    window_days: int
    events_in_window: int
    items: list[CategoryCount]


class Health(BaseModel):
    status: str
    database: str


class HourCount(BaseModel):
    hour: int  # 0-23, local Memphis start hour
    event_count: int


class EventsPerHour(BaseModel):
    events_total: int
    events_with_time: int
    excluded_no_time: int
    excluded_placeholder: int  # events at the 23:59 placeholder time
    items: list[HourCount]
