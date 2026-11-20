"""Cleaning rules in transform.py. Pure: small made-up DataFrames, no network, no database."""

import json
import logging

import pandas as pd
import pytest

import transform


def warnings_text(caplog) -> str:
    return " ".join(r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING)


def clean_column(values, column, canonical):
    df = pd.DataFrame({column: values})
    return transform.standardize_column(df, column, canonical)[column].tolist()


# --- event_type -------------------------------------------------------------

def test_event_type_spelling_variants_become_in_person():
    out = clean_column(["In Person", "INPERSON", "In-Person"], "event_type", transform.EVENT_TYPE_CANONICAL)
    assert out == ["In-Person"] * 3


def test_event_type_virtual_and_hybrid():
    out = clean_column(["VIRTUAL", "Hybrid", "hybrid"], "event_type", transform.EVENT_TYPE_CANONICAL)
    assert out == ["Virtual", "Hybrid", "Hybrid"]


def test_unknown_event_type_is_flagged_not_guessed(caplog):
    with caplog.at_level(logging.INFO, logger="transform"):
        out = clean_column(["Outdoors", "In Person"], "event_type", transform.EVENT_TYPE_CANONICAL)
    assert out == ["Outdoors", "In-Person"]
    assert "Outdoors" in warnings_text(caplog)


# --- event_category ---------------------------------------------------------

def test_category_known_data_entry_errors():
    out = clean_column(["WORKSHOP", "Tech TalkNetworking"], "event_category", transform.EVENT_CATEGORY_CANONICAL)
    assert out == ["Workshop", "Tech Talk"]


def test_all_seven_valid_categories_pass_through_unchanged(caplog):
    valid = ["Networking", "Tech Talk", "Workshop", "Entrepreneur", "Conference", "Hackathon", "AI"]
    with caplog.at_level(logging.INFO, logger="transform"):
        out = clean_column(valid, "event_category", transform.EVENT_CATEGORY_CANONICAL)
    assert out == valid
    assert warnings_text(caplog) == ""


def test_unknown_category_is_flagged_not_guessed(caplog):
    with caplog.at_level(logging.INFO, logger="transform"):
        out = clean_column(["Karaoke"], "event_category", transform.EVENT_CATEGORY_CANONICAL)
    assert out == ["Karaoke"]
    assert "Karaoke" in warnings_text(caplog)


# --- time -------------------------------------------------------------------

@pytest.mark.parametrize("raw, expected", [
    ("4PM", "16:00"), ("11AM", "11:00"), ("0900", "09:00"), ("1730", "17:30"),
    ("9:15", "09:15"), ("18:00", "18:00"),
    ("12AM", "00:00"), ("12PM", "12:00"), ("4:30 PM", "16:30"),
])
def test_normalize_time_to_24_hour(raw, expected):
    assert transform.normalize_time(raw) == expected


@pytest.mark.parametrize("raw", ["9", "25:00", "13PM", "noon", "18:75", ""])
def test_normalize_time_rejects_what_it_cannot_parse(raw):
    assert transform.normalize_time(raw) is None


def test_standardize_time_reports_unparseable_and_invents_nothing(caplog):
    df = pd.DataFrame({"time": ["4PM", None, "noon", "23:59", ""]})
    with caplog.at_level(logging.INFO, logger="transform"):
        out = transform.standardize_time(df)["time"]
    assert out[0] == "16:00"
    assert pd.isna(out[1])             # missing stays missing, no fake value
    assert out[2] == "noon"            # unparseable left as-is...
    assert "noon" in warnings_text(caplog)  # ...and reported
    assert out[3] == "23:59"           # a real HH:MM is not rewritten
    assert out[4] == ""                # blank is not given a time


# --- group_id ---------------------------------------------------------------

def test_group_id_stays_integer_with_missing_values():
    df = pd.DataFrame({"group_id": [9, None, 29]})  # pandas makes this 9.0 / NaN / 29.0
    out = transform.standardize_group_id(df)
    assert str(out["group_id"].dtype) == "Int64"
    assert out["group_id"][0] == 9 and isinstance(out["group_id"][0].item(), int)
    assert pd.isna(out["group_id"][1])
    # what load.py actually reads: whole numbers in the JSON, never 9.0
    written = json.loads(out.to_json(orient="records"))
    assert written[0]["group_id"] == 9 and "9.0" not in out.to_json(orient="records")


def test_group_id_text_and_blank_values():
    out = transform.standardize_group_id(pd.DataFrame({"group_id": ["9", "", "  ", "29"]}))
    assert out["group_id"].tolist()[0] == 9
    assert out["group_id"].isna().tolist() == [False, True, True, False]


def test_group_id_non_numeric_and_fractional_become_null(caplog):
    df = pd.DataFrame({"group_id": ["abc", 9.5, 3]})
    with caplog.at_level(logging.INFO, logger="transform"):
        out = transform.standardize_group_id(df)["group_id"]
    assert out.isna().tolist() == [True, True, False]
    assert out[2] == 3
    assert "abc" in warnings_text(caplog)


def test_check_group_ids_flags_unknown_id(tmp_path, caplog):
    groups_file = tmp_path / "groups.json"
    groups_file.write_text(json.dumps([{"id": 1, "name": "A"}, {"id": 9, "name": "B"}]), encoding="utf-8")
    groups = transform.load_groups(groups_file)

    known = transform.standardize_group_id(pd.DataFrame({"group_id": [1, 9]}))
    with caplog.at_level(logging.INFO, logger="transform"):
        transform.check_group_ids(known, groups)
    assert warnings_text(caplog) == ""

    caplog.clear()
    unknown = transform.standardize_group_id(pd.DataFrame({"group_id": [1, 99]}))
    with caplog.at_level(logging.INFO, logger="transform"):
        transform.check_group_ids(unknown, groups)
    assert "99" in warnings_text(caplog)


# --- duplicates and column mapping -------------------------------------------

def test_duplicate_event_ids_are_reported(caplog):
    with caplog.at_level(logging.INFO, logger="transform"):
        transform.report_quality(pd.DataFrame({"event_id": ["a", "b", "a"], "name": ["x", "y", "z"]}))
    assert "Duplicate event_id: 2 rows share an ID" in warnings_text(caplog)

    caplog.clear()
    with caplog.at_level(logging.INFO, logger="transform"):
        transform.report_quality(pd.DataFrame({"event_id": ["a", "b"], "name": ["x", "y"]}))
    assert "Duplicate event_id: none" in caplog.text
    assert warnings_text(caplog) == ""


def test_column_map_keeps_group_id_mapped(caplog):
    """A misspelled source field (groupID vs groupId) silently drops group_id, which would
    send every event to the catch-all group. trim() only warns, so pin the spelling."""
    assert transform.COLUMN_MAP["fields.groupId"] == "group_id"

    raw = pd.DataFrame({"sys.id": ["a"], "fields.groupID": [9]})  # wrong spelling
    with caplog.at_level(logging.INFO, logger="transform"):
        out = transform.trim(raw)
    assert "group_id" not in out.columns
    assert "fields.groupId" in warnings_text(caplog)
