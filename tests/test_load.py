"""Loader validation and guards that need no database."""

import json
import logging
from datetime import time

import pytest

import load
from conftest import SMALL_FIXTURE, FakeCursor


def good_row(**overrides) -> dict:
    row = {
        "event_id": "e1", "name": "Made-up event", "date": "2026-10-01", "time": "18:00",
        "event_type": "In-Person", "event_category": "Networking", "group_id": 9,
        "created_at": "2026-09-01T12:00:00.000Z", "updated_at": "2026-09-02T12:00:00.000Z",
    }
    row.update(overrides)
    return row


# --- row validation -----------------------------------------------------------

def test_good_row_builds_typed_event():
    event = load.build_event(good_row())
    assert event.date_key == 20261001
    assert event.event_time == time(18, 0)
    assert event.group_id == 9 and isinstance(event.group_id, int)


@pytest.mark.parametrize("field", ["event_id", "date", "name", "event_type", "event_category",
                                   "created_at", "updated_at"])
def test_required_field_missing_is_rejected(field):
    for blank in (None, "", "   "):
        with pytest.raises(ValueError, match="missing required"):
            load.build_event(good_row(**{field: blank}))


@pytest.mark.parametrize("overrides", [
    {"event_type": "In Person"},   # un-standardized spelling must not slip through
    {"event_type": "Outdoors"},
    {"event_category": "WORKSHOP"},
    {"event_category": "Karaoke"},
])
def test_unrecognized_type_or_category_is_rejected(overrides):
    with pytest.raises(ValueError, match="is not one of"):
        load.build_event(good_row(**overrides))


def test_read_events_skips_bad_rows_but_remembers_their_ids(write_snapshot, caplog):
    path = write_snapshot([good_row(event_id="ok"), good_row(event_id="bad", name=None)])
    with caplog.at_level(logging.INFO, logger="load"):
        events, present_ids = load.read_events(path)
    assert [e.event_id for e in events] == ["ok"]
    assert present_ids == {"ok", "bad"}  # a rejected row must not look "removed from the source"
    assert "Rejected row 1" in caplog.text


def test_read_events_refuses_duplicate_event_ids(write_snapshot):
    path = write_snapshot([good_row(event_id="dup"), good_row(event_id="dup")])
    with pytest.raises(ValueError, match="duplicate event_id"):
        load.read_events(path)


# --- blank times and group ids -------------------------------------------------

def test_blank_or_bad_time_is_null_never_a_placeholder():
    assert load.parse_time(None) is None
    assert load.parse_time("") is None
    assert load.parse_time("   ") is None
    assert load.parse_time("noon") is None
    assert load.parse_time("17:30") == time(17, 30)


def test_group_id_is_a_whole_number_and_blank_means_catch_all():
    assert load.parse_group_id(None) == load.CATCH_ALL_GROUP_ID
    assert load.parse_group_id("") == load.CATCH_ALL_GROUP_ID
    for value in (9, 9.0, "9"):
        result = load.parse_group_id(value)
        assert result == 9 and type(result) is int
    with pytest.raises(ValueError):
        load.parse_group_id(9.5)


# --- the "snapshot too small" guard ---------------------------------------------

def test_guard_refuses_snapshot_under_half_of_active_events():
    cur = FakeCursor(active_count=10)
    with pytest.raises(RuntimeError, match="aborting"):
        load.deactivate_missing(cur, {f"e{i}" for i in range(4)})
    assert not any("UPDATE" in s for s in cur.statements)  # nothing was deactivated


def test_guard_allows_exactly_half():
    cur = FakeCursor(active_count=10, update_rowcount=5)
    assert load.deactivate_missing(cur, {f"e{i}" for i in range(5)}) == 5
    assert any("UPDATE" in s for s in cur.statements)


# --- dry run ----------------------------------------------------------------------

def test_dry_run_validates_without_connecting(monkeypatch, caplog):
    def no_database(*args, **kwargs):
        raise AssertionError("--dry-run must not connect to a database")

    monkeypatch.setattr(load, "connect", no_database)
    monkeypatch.setattr("sys.argv", ["load.py", "--dry-run", "--file", str(SMALL_FIXTURE)])
    with caplog.at_level(logging.INFO, logger="load"):
        load.main()
    assert "Dry run: validation passed" in caplog.text


def test_main_exits_when_no_row_is_valid(monkeypatch, write_snapshot):
    path = write_snapshot([good_row(name=None)])
    monkeypatch.setattr("sys.argv", ["load.py", "--dry-run", "--file", str(path)])
    with pytest.raises(SystemExit):
        load.main()
