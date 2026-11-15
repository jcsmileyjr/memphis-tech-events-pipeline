# Memphis Events dashboard — design

A single-page Next.js dashboard (App Router, TypeScript strict, Tailwind CSS,
Recharts) in `dashboard/`. It is the last layer of the pipeline:

Contentful → `extract.py` → `transform.py` → `load.py` → PostgreSQL star schema →
read-only FastAPI (`api/`, see `api-design.md`) → **dashboard**.

It is a local portfolio piece used for screenshots and the README: no filters, no
authentication, no deployment config, no snapshot files.

## The four questions

Each chart's visible title is the question it answers, plus one total card.

| Question | Endpoint | Chart |
|---|---|---|
| How many events are in the warehouse? (card) | `GET /events?page=1` → `total` | Number |
| 1. How many events happen per month? | `GET /stats/events-per-month` | Column chart |
| 2. Which event categories dominate? | `GET /stats/events-per-category` | Horizontal bars |
| 3. Which groups are most active? | `GET /trending/groups?days=730&limit=10` | Horizontal bars |
| 4. What time of day do events usually happen? | `GET /stats/events-per-hour` | Column chart by hour |

Field names from the API are used as-is (`event_count`, `event_category`,
`group_name`, `hour`, ...). The only transformations are display labels (e.g. hour
`18` shown as "6 PM", long group names shortened on the axis; the full name stays
in the tooltip and the accessible table).

## Data notes shown on the page

- **Group coverage (question 3).** Group data is not complete. The chart shows a
  visible note built from the API's `events_with_group` and `events_in_window`
  (today 400 of 440 events, 90.9%), and that events without a group are not
  counted. The groups chart uses the API's longest window (730 days, plus upcoming
  events), which currently reaches back before the first event.
- **Time of day (question 4).** Events with no start time and events at the `23:59`
  placeholder time are excluded by the API. The note shows how many were excluded
  (`excluded_no_time`, `excluded_placeholder`) out of `events_total`. In the
  current load both are 0. Times are Memphis local time.
- **Months (question 1).** Months with zero events are shown (the API fills gaps);
  the latest month may be incomplete because upcoming events are included.

## Why the data is fetched on the server

`app/page.tsx` is a Server Component. `lib/api.ts` calls the API from the Next.js
server (`cache: "no-store"`, 8 s timeout) and passes the results to small client
chart components as props. The browser never calls the API, so **CORS is not
needed and is not enabled** on the API. The base URL comes from `API_BASE_URL`
(default `http://localhost:8000`, set in `dashboard/.env.local`; see
`dashboard/.env.example`).

The project uses Next.js Cache Components, so the static page shell is prerendered
and the data streams in at request time inside a `<Suspense>` boundary. The build
never calls the API.

## Components

- `lib/api.ts` — typed fetchers returning `{ok, data}` or `{ok: false, error}`.
- `lib/format.ts` — display-only helpers (percent, hour label, truncate).
- `components/ChartCard.tsx` — shared section: `<h2>` question, text summary, the
  chart, the data note and a screen-reader-only data table.
- `components/MonthlyChart.tsx`, `CategoryChart.tsx`, `GroupChart.tsx`,
  `HourChart.tsx` — one Recharts client component each.
- `components/TotalCard.tsx`, `StatusNotice.tsx` (error / empty message).
- `components/chartTheme.ts` — shared colors.

## Failure and empty states

Each section handles its own failure. If a request fails, that section shows
"Couldn't load this chart" with the reason. If every request fails, a banner at the
top says the dashboard can't reach the API and how to start it. An empty response
shows "No data yet." The page never crashes.

## Accessibility

- Semantic structure: one `<h1>`, one `<h2>` per question, `<main>`, `<section>`
  with `aria-labelledby`.
- Each chart has a short text summary, an `aria-label` on the chart wrapper, and a
  screen-reader-only data table with the exact values.
- Values are printed on the bars, so meaning does not depend on color. One color
  (blue-700, 6.7:1 on white) is used; text is slate-700 or darker (>= 7:1).
- Responsive: two columns on laptop widths, one on phone widths (checked at 375 px,
  no horizontal scroll).

## Limitations

- Reads from a local API: if the API (or the database) is not running, the page
  shows error messages instead of data.
- Data is only as fresh as the last pipeline run (`load.py`); the page does not
  refresh anything itself, it re-reads the API on each page load.
- The groups chart uses the API's 730-day window. From about 2027-09 it would start
  cutting off the oldest events; an all-time groups endpoint would fix that.
- The total card counts every row in `fact_events`, including any flagged
  `is_active = false`, as the API does.
- No filters, export, authentication or deployment, by design.
