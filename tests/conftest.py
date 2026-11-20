"""Shared test setup.

Nothing here reads DATABASE_URL or any real credentials. Database tests use
TEST_DATABASE_URL only, and refuse to run against anything but a local server.
"""

import json
import os
import uuid
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).resolve().parent / "fixtures"
SMALL_FIXTURE = FIXTURES / "events_clean_small.json"

LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


@pytest.fixture(autouse=True)
def _run_from_repo_root(monkeypatch):
    """transform.py and load.py use paths relative to the project root."""
    monkeypatch.chdir(ROOT)


@pytest.fixture
def small_events() -> list[dict]:
    return json.loads(SMALL_FIXTURE.read_text(encoding="utf-8"))


@pytest.fixture
def write_snapshot(tmp_path):
    """Write a list of event dicts to a temp clean-JSON file and return its path."""
    counter = {"n": 0}

    def _write(rows: list[dict]) -> Path:
        counter["n"] += 1
        path = tmp_path / f"snapshot_{counter['n']}.json"
        path.write_text(json.dumps(rows), encoding="utf-8")
        return path

    return _write


class FakeCursor:
    """Stands in for a psycopg2 cursor in deactivate_missing (no database)."""

    def __init__(self, active_count: int, update_rowcount: int = 0):
        self._active_count = active_count
        self.rowcount = update_rowcount
        self.statements: list[str] = []

    def execute(self, sql, params=None):
        self.statements.append(sql)

    def fetchone(self):
        return (self._active_count,)


# ---------------------------------------------------------------------------
# Database safety. Only TEST_DATABASE_URL, only local hosts, only our own schema.
# ---------------------------------------------------------------------------

def check_test_database_url(url: str) -> None:
    """Fail loudly (not skip) if the URL could point at anything but a local throwaway DB."""
    if "supabase" in url.lower():
        pytest.fail("TEST_DATABASE_URL contains 'supabase'. Refusing to run: use a local throwaway Postgres.")
    parsed = urlparse(url)
    hosts = {parsed.hostname or ""}
    # libpq also accepts host= in the query string, which would override the URL host
    query = parse_qs(parsed.query)
    for key in ("host", "hostaddr"):
        hosts.update(query.get(key, []))
    bad = {h for h in hosts if h.lower() not in LOCAL_HOSTS}
    if bad:
        pytest.fail(
            f"TEST_DATABASE_URL host {sorted(bad)} is not localhost, 127.0.0.1 or ::1. "
            "Refusing to run database tests against a non-local server."
        )


@pytest.fixture
def db(monkeypatch):
    """A throwaway schema (test_<random>) in the local TEST_DATABASE_URL database.

    load.connect is replaced so load.py talks to that schema only; search_path has
    no 'public' fallback. The schema is dropped afterwards, but only if this
    fixture created it and its name starts with 'test_'.
    """
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL is not set")
    check_test_database_url(url)

    import psycopg2

    import load

    schema = f"test_{uuid.uuid4().hex[:10]}"
    created: set[str] = set()

    def connect(autocommit: bool = False):
        conn = psycopg2.connect(url, options=f"-c search_path={schema}")
        conn.autocommit = autocommit
        return conn

    monkeypatch.delenv("DATABASE_URL", raising=False)  # load.py must never see the real one
    monkeypatch.setattr(load, "connect", connect)

    admin = psycopg2.connect(url)
    admin.autocommit = True
    try:
        with admin.cursor() as cur:
            cur.execute(f'CREATE SCHEMA "{schema}"')
        created.add(schema)

        with connect(autocommit=True) as conn, conn.cursor() as cur:
            cur.execute("SELECT current_schema()")
            current = cur.fetchone()[0]
        assert current == schema, f"current_schema() is {current!r}, expected {schema!r}"

        load.run_init()  # creates the real tables, in the test schema only
        yield connect
    finally:
        try:
            if schema in created and schema.startswith("test_"):
                with admin.cursor() as cur:
                    cur.execute(f'DROP SCHEMA "{schema}" CASCADE')
        finally:
            admin.close()
