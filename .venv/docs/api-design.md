# Memphis Events Stats API — design

A small, read-only FastAPI service over the PostgreSQL star schema loaded by
`load.py` (see `schema-design.md`). It is a **stats API for a dashboard**, not a
full event API. It never talks to Contentful and never cleans data; it trusts the
warehouse.

- Stack: FastAPI + Uvicorn, psycopg2 only (no ORM), Pydantic response models.
- Only `GET` endpoints and only `SELECT` queries. All SQL is parameterized (`%s`);
  user input is never formatted into SQL.
- Local only. CORS is **not** enabled (see Limitations).

Run from the project root (after filling the `API_DB_*` variables in `.env`):

```bash
uvicorn api.main:app --reload
```

Interactive docs: `http://127.0.0.1:8000/docs`.

## Files

| File | Purpose |
|---|---|
| `api/main.py` | Routes (thin) and parameter validation |
| `api/db.py` | Connection dependency and all SQL |
| `api/models.py` | Pydantic response models |
| `sql/create_api_user.sql` | Read-only role (run manually in pgAdmin as `postgres`) |
| `.env.example` | Variable names only; real values live in `.env` (git-ignored) |

## Event shape

Used wherever an event is returned. `group_name` is always present and is `null`
when the event has no group.

```json
{
  "event_id": "1B261qVLINLZfoEmNohyR6",
  "event_name": "Vista Data x Epicenter: Working with Claude Cowork",
  "date": "2026-12-02",
  "event_type": "In-Person",
  "event_category": "Workshop",
  "group_name": "Epicenter Memphis"
}
```

"No group" in the warehouse means `fact_events.group_id = 29` ("Random Group",
`dim_group.is_catch_all = true`). The API returns `null` for that group and
excludes it from group trending. No description, time or RSVP fields are exposed.

Every row in `fact_events` is served, including any with `is_active = false`
(events that disappeared from the latest extract). Today all rows are active.

## Pagination

Event lists return 100 events per page (fixed). `page` starts at 1. Responses are
`{page, page_size, total, items}`. Order is newest `date` first, with `event_id`
descending as a tie-breaker so pages are stable. A page past the end returns an
empty `items` list with the real `total`.

## Endpoints

### `GET /events?month=YYYY-MM&category=<name>&page=1`

Paginated event list. Both filters are optional and can be combined.

- `month` must match `YYYY-MM` (month 01–12) or the API returns **422**.
- `category` is a case-insensitive exact match on the category name. An unknown
  category returns an empty page (200), not an error.
- `page` must be ≥ 1 (else 422).

`GET /events?month=2026-11&category=networking` (real data, truncated):

```json
{
  "page": 1,
  "page_size": 100,
  "total": 9,
  "items": [
    {
      "event_id": "1nCtk1qSR0NCr3YV8efxxi",
      "event_name": "Memphis AI Meetup: Free Weekly AI Conversations",
      "date": "2026-11-17",
      "event_type": "In-Person",
      "event_category": "Networking",
      "group_name": "Memphis AI Meetup Group"
    }
  ]
}
```

### `GET /events/{event_id}`

One event in the event shape (see above). **404** `{"detail": "Event not found"}`
if the id does not exist.

### `GET /stats/events-per-month`

Events per month in chronological order, as `{month, event_count}`. Months with
zero events between the first and last event month are included so a chart has no
gaps. Months are derived from `event_date`. Not paginated.

```json
[
  {"month": "2025-09", "event_count": 15},
  {"month": "2025-10", "event_count": 42},
  {"month": "2025-11", "event_count": 27},
  "... 2026-12 has 1 event ..."
]
```

### `GET /trending/groups?days=90&limit=10`

Groups ranked by number of events in the window, highest first (ties broken by
group name). Events with no group are excluded from `items`.
`events_with_group` against `events_in_window` shows how much of the window the
group data covers.

`days` 1–730 (default 90), `limit` 1–50 (default 10); outside the range → 422.

```json
{
  "window_days": 90,
  "events_in_window": 87,
  "events_with_group": 85,
  "items": [
    {"group_name": "Memphis AI Meetup Group", "event_count": 15},
    {"group_name": "Epicenter Memphis", "event_count": 9},
    {"group_name": "Midsouth Makers", "event_count": 8}
  ]
}
```

(Real response as of 2026-11-14; `items` truncated to 3 of 10 here.)

### `GET /trending/categories?days=90&limit=10`

Same idea by category.

```json
{
  "window_days": 30,
  "events_in_window": 35,
  "items": [
    {"event_category": "Networking", "event_count": 15},
    {"event_category": "Tech Talk", "event_count": 12},
    {"event_category": "Workshop", "event_count": 3}
  ]
}
```

(`GET /trending/categories?days=30&limit=3`, real data.)

### `GET /health`

Runs `SELECT 1`. Returns `{"status": "ok", "database": "reachable"}`, or **503**
`{"detail": "Database unavailable"}` if the database cannot be reached.

## Trending definition

"What organizers are focused on" is measured by counting events per group or
category inside a recent window. The window is every event whose `event_date` is
**on or after (today − `days`)**, where *today* is the current date in Memphis
local time (`America/Chicago`). There is no upper bound, so **upcoming events are
included**. It counts events, not attendance.

## Database access

- One short-lived psycopg2 connection per request, via a FastAPI dependency in
  `api/db.py`. The session is read-only and the connection is always closed in a
  `finally` block. A 10 s statement timeout guards against runaway queries.
  Chosen for simplicity: local, low traffic, nothing to leak or pool. A connection
  pool is an easy swap if traffic ever needs it.
- If the database is unreachable or the credentials are rejected, the API returns
  a clean **503** and logs only the exception type, never connection details.
- Settings come from `.env`: `API_DB_HOST`, `API_DB_PORT`, `API_DB_NAME`,
  `API_DB_USER`, `API_DB_PASSWORD` (names listed in `.env.example`).

## Read-only database user

The API does not use the loader's `DATABASE_URL`. `sql/create_api_user.sql`
creates the role `api_reader` with `CONNECT` on the database, `USAGE` on schema
`public`, and `SELECT` only on `fact_events`, `dim_event_type`,
`dim_event_category` and `dim_group`. It has no write privileges and no access to
`dim_date`. The script is **never run by the API or any pipeline script**: it is
run manually in pgAdmin as the `postgres` user, after replacing the `CHANGE_ME`
password placeholder. Even if the API had a bug, the database would refuse writes.

## Limitations

- The API serves whatever `load.py` last loaded; it does not refresh anything.
  Events removed from Contentful stay (flagged `is_active = false`) and are still
  returned.
- Group data is partly missing: 40 of 440 events (9.1%) sit in the "Random Group"
  catch-all and show `group_name: null`. Group trending ignores them; use
  `events_with_group` vs `events_in_window` to see coverage.
- No RSVP or attendance data exists in the warehouse, so none is served and
  "trending" means number of events only.
- Only a few fields per event are returned; there is no description or time.
- CORS is not enabled. A browser dashboard served from a different origin (another
  port, e.g. `localhost:3000` or `5173`) would be blocked by the browser until
  `CORSMiddleware` is added with that origin allowed. A server-side dashboard or
  `curl` is unaffected.
- No authentication, rate limiting or HTTPS; local use only.
