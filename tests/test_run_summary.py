"""Guards the log lines scripts/run_summary.py depends on.

The logs are produced by running the real extract/transform/load code (network and
database stubbed out), so rewording a log message in a script fails here instead of
silently emptying the run summary.
"""

import importlib
import logging
import sys

import pytest

import load
import transform
from conftest import ROOT

sys.path.insert(0, str(ROOT / "scripts"))
import run_summary  # noqa: E402

PROD_FORMAT = "%(asctime)s %(levelname)s %(message)s"


def sample_item(event_id, **fields):
    base = {"name": f"Event {event_id}", "date": "2026-10-01", "time": "18:00",
            "eventType": "Virtual", "eventCategory": "Networking",
            "description": "d", "shortIntro": "s"}
    base.update(fields)
    return {"sys": {"id": event_id, "createdAt": "2026-09-01T12:00:00.000Z",
                    "updatedAt": "2026-09-02T12:00:00.000Z"}, "fields": base}


@pytest.fixture
def pipeline_logs(monkeypatch, tmp_path, caplog):
    """Run extract (stubbed fetch), transform and load --dry-run for real; return the three logs."""
    caplog.handler.setFormatter(logging.Formatter(PROD_FORMAT))  # same prefix as production

    items = [
        sample_item("a", eventType="In Person", eventCategory="WORKSHOP", time="4PM", groupId=9),
        sample_item("b"),                                        # no group -> catch-all
        sample_item("c", eventType="Hybrid", eventCategory="AI", time="0900", groupId=1),
    ]
    monkeypatch.setenv("CONTENTFUL_SPACE_ID", "test-space")
    monkeypatch.setenv("CONTENTFUL_ACCESS_TOKEN", "test-token")
    extract = importlib.import_module("extract")
    monkeypatch.setattr(extract, "fetch_page", lambda skip: {"total": 3, "items": items, "includes": {}})
    monkeypatch.setattr(extract, "RAW_DIR", tmp_path / "raw")
    monkeypatch.setattr(transform, "RAW_DIR", tmp_path / "raw")
    monkeypatch.setattr(transform, "CLEAN_DIR", tmp_path / "clean")
    monkeypatch.setattr(load, "connect", lambda *a, **k: pytest.fail("dry run must not connect"))

    logs = {}
    with caplog.at_level(logging.INFO):
        extract.main()
        logs["extract"] = caplog.text
        caplog.clear()

        monkeypatch.setattr("sys.argv", ["transform.py"])
        transform.main()
        logs["transform"] = caplog.text
        clean_file = sorted((tmp_path / "clean").glob("events_clean_*.json"))[-1]
        caplog.clear()

        monkeypatch.setattr("sys.argv", ["load.py", "--dry-run", "--file", str(clean_file)])
        load.main()
        logs["load"] = caplog.text
    return logs


def test_summary_finds_every_figure_in_real_logs(pipeline_logs):
    info = run_summary.parse(pipeline_logs["extract"], pipeline_logs["transform"], pipeline_logs["load"])
    assert info["extracted"] == 3
    assert (info["std_event_type"], info["std_event_category"], info["std_time"]) == (1, 1, 2)
    assert info["group_present"] == (2, 3)
    assert info["group_ids_known"] is True
    assert info["duplicates"] == "none"
    assert info["transform_rows"] == 3
    assert info["read"] == (3, 3, 0)
    assert info["range"][2] == "1" and info["range"][3] == "0"  # one catch-all event, none without a time
    assert info["dry_run"] is True
    assert info["issues"] == []

    markdown, missing = run_summary.render(info)
    assert run_summary.NOT_FOUND not in markdown
    assert missing == []
    assert "2 of 3 (66.7%)" in markdown            # real group coverage = valid minus catch-all
    assert "dry run, nothing written" in markdown


def test_missing_log_lines_are_reported_not_silently_empty():
    info = run_summary.parse("", "", "")
    markdown, missing = run_summary.render(info)
    assert markdown.count(run_summary.NOT_FOUND) >= 8
    assert "events extracted" in missing and "load result (inserted/updated/flagged)" in missing
    assert "Not found in the logs" in markdown


def test_warnings_and_errors_are_listed_and_cannot_break_the_code_fence():
    log = "2026-11-20 03:23:01,123 WARNING event_type: 1 value(s) not in the canonical lookup: {'```x': 1}\n"
    markdown, _ = run_summary.render(run_summary.parse("", log, ""))
    assert "Warnings and errors (1)" in markdown
    assert markdown.count("```") == 2  # only our own opening and closing fence


def test_gate_fails_on_rejected_rows_and_passes_when_clean(caplog, write_snapshot):
    caplog.handler.setFormatter(logging.Formatter(PROD_FORMAT))
    row = {"event_id": "ok", "name": "n", "date": "2026-10-01", "event_type": "Virtual",
           "event_category": "AI", "created_at": "2026-09-01T12:00:00Z", "updated_at": "2026-09-02T12:00:00Z"}

    with caplog.at_level(logging.INFO, logger="load"):
        load.read_events(write_snapshot([row, dict(row, event_id="bad", name=None)]))
    code, message = run_summary.gate(caplog.text)
    assert code == 1 and "1 row(s) were rejected" in message

    caplog.clear()
    with caplog.at_level(logging.INFO, logger="load"):
        load.read_events(write_snapshot([row]))
    assert run_summary.gate(caplog.text)[0] == 0

    assert run_summary.gate("")[0] == 1  # no line at all must not pass silently


def test_main_writes_summary_file_and_warns_about_missing_lines(tmp_path, capsys):
    out = tmp_path / "summary.md"
    code = run_summary.main(["summary", "--output", str(out), "--dry-run"])
    assert code == 0
    assert "Pipeline run summary" in out.read_text(encoding="utf-8")
    assert "::warning::" in capsys.readouterr().out
