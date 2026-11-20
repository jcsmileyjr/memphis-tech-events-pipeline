"""Re-run behavior against a throwaway local Postgres. See the `db` fixture in conftest.py.

Skipped unless TEST_DATABASE_URL is set. Refuses to run against a non-local host or
anything containing 'supabase'. Never reads DATABASE_URL.
"""

import copy
import logging
import re

import pytest

import load

pytestmark = pytest.mark.db


def run_load(path, caplog) -> tuple[int, int, int]:
    """Run the real load() and return (inserted, updated, deactivated) from its log line."""
    caplog.clear()
    events, present_ids = load.read_events(path)
    with caplog.at_level(logging.INFO, logger="load"):
        load.load(events, present_ids, load.read_groups())
    match = re.search(r"(\d+) inserted, (\d+) updated, (\d+) flagged", caplog.text)
    assert match, caplog.text
    return tuple(int(n) for n in match.groups())


def query(db, sql, params=None):
    with db() as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchall()


def test_rerun_inserts_nothing_updates_everything_and_applies_changes(db, small_events, write_snapshot, caplog):
    first = write_snapshot(small_events)
    assert run_load(first, caplog) == (5, 0, 0)
    assert query(db, "SELECT count(*) FROM fact_events") == [(5,)]

    # Same events again, but one is renamed at the source
    changed = copy.deepcopy(small_events)
    changed[0]["name"] = "Fixture Event 1 (renamed)"
    second = write_snapshot(changed)
    assert run_load(second, caplog) == (0, 5, 0)

    assert query(db, "SELECT count(*) FROM fact_events") == [(5,)]
    assert query(db, "SELECT name FROM fact_events WHERE event_id = 'fixture-evt-1'") == [
        ("Fixture Event 1 (renamed)",)
    ]
    # blank time and blank group were stored honestly, not with placeholders
    assert query(db, "SELECT event_time FROM fact_events WHERE event_id = 'fixture-evt-2'") == [(None,)]
    assert query(db, "SELECT group_id FROM fact_events WHERE event_id = 'fixture-evt-3'") == [
        (load.CATCH_ALL_GROUP_ID,)
    ]


def test_event_missing_from_a_later_snapshot_is_deactivated_not_deleted(db, small_events, write_snapshot, caplog):
    assert run_load(write_snapshot(small_events), caplog) == (5, 0, 0)

    without_last = small_events[:4]
    assert run_load(write_snapshot(without_last), caplog) == (0, 4, 1)
    assert query(db, "SELECT count(*) FROM fact_events") == [(5,)]  # never deleted
    assert query(db, "SELECT event_id FROM fact_events WHERE NOT is_active") == [("fixture-evt-5",)]
    assert query(db, "SELECT count(*) FROM fact_events WHERE is_active") == [(4,)]

    # it comes back when it reappears in the source
    assert run_load(write_snapshot(small_events), caplog) == (0, 5, 0)
    assert query(db, "SELECT count(*) FROM fact_events WHERE is_active") == [(5,)]


def test_guard_refuses_a_too_small_snapshot_and_rolls_back(db, small_events, write_snapshot, caplog):
    assert run_load(write_snapshot(small_events), caplog) == (5, 0, 0)

    tiny = copy.deepcopy(small_events[:2])  # 2 of 5 active is under half
    tiny[0]["name"] = "Should Not Be Saved"
    events, present_ids = load.read_events(write_snapshot(tiny))
    with pytest.raises(RuntimeError, match="aborting"):
        load.load(events, present_ids, load.read_groups())

    assert query(db, "SELECT count(*) FROM fact_events WHERE is_active") == [(5,)]
    assert query(db, "SELECT name FROM fact_events WHERE event_id = 'fixture-evt-1'") == [("Fixture Event 1",)]
