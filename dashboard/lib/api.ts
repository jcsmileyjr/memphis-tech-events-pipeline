/**
 * Data-fetching module. Runs on the server only (called from Server Components),
 * so the browser never talks to the API and CORS is not needed.
 *
 * Types mirror the API responses (api/models.py) exactly; field names are not
 * renamed or reshaped.
 */

export const API_BASE_URL = process.env.API_BASE_URL ?? "http://localhost:8000";

const REQUEST_TIMEOUT_MS = 8000;

// ---- Response types (see docs/api-design.md) --------------------------------

export type MonthCount = { month: string; event_count: number };

export type CategoryCount = { event_category: string; event_count: number };

export type GroupCount = { group_name: string; event_count: number };

export type TrendingGroups = {
  window_days: number;
  events_in_window: number;
  events_with_group: number;
  items: GroupCount[];
};

export type HourCount = { hour: number; event_count: number };

export type EventsPerHour = {
  events_total: number;
  events_with_time: number;
  excluded_no_time: number;
  excluded_placeholder: number;
  items: HourCount[];
};

/** Only the field the dashboard needs from the paginated /events response. */
export type EventPageTotal = { total: number };

// ---- Fetching ---------------------------------------------------------------

export type ApiResult<T> = { ok: true; data: T } | { ok: false; error: string };

async function get<T>(path: string): Promise<ApiResult<T>> {
  try {
    const response = await fetch(`${API_BASE_URL}${path}`, {
      cache: "no-store",
      signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
    });
    if (!response.ok) {
      return { ok: false, error: `The API answered ${response.status} for ${path}.` };
    }
    return { ok: true, data: (await response.json()) as T };
  } catch {
    return { ok: false, error: `Could not reach the API at ${API_BASE_URL}.` };
  }
}

// Longest window the API allows; covers every event while the data is < 2 years old.
const ALL_EVENTS_DAYS = 730;

export const fetchTotalEvents = () => get<EventPageTotal>("/events?page=1");
export const fetchEventsPerMonth = () => get<MonthCount[]>("/stats/events-per-month");
export const fetchEventsPerCategory = () => get<CategoryCount[]>("/stats/events-per-category");
export const fetchTopGroups = () =>
  get<TrendingGroups>(`/trending/groups?days=${ALL_EVENTS_DAYS}&limit=10`);
export const fetchEventsPerHour = () => get<EventsPerHour>("/stats/events-per-hour");
