import { Suspense } from "react";
import CategoryChart from "@/components/CategoryChart";
import ChartCard from "@/components/ChartCard";
import GroupChart from "@/components/GroupChart";
import HourChart from "@/components/HourChart";
import MonthlyChart from "@/components/MonthlyChart";
import StatusNotice from "@/components/StatusNotice";
import TotalCard from "@/components/TotalCard";
import {
  API_BASE_URL,
  fetchEventsPerCategory,
  fetchEventsPerHour,
  fetchEventsPerMonth,
  fetchTopGroups,
  fetchTotalEvents,
} from "@/lib/api";
import { hourLabel, percent } from "@/lib/format";

const Q_MONTH = "How many events happen per month?";
const Q_CATEGORY = "Which event categories dominate?";
const Q_GROUP = "Which groups are most active?";
const Q_HOUR = "What time of day do events usually happen?";

// The page shell is static; the data (fetched with cache: "no-store") streams in at
// request time inside this Suspense boundary, so the build never calls the API.
export default function Home() {
  return (
    <Suspense
      fallback={
        <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-8 sm:px-6">
          <h1 className="text-3xl font-bold text-slate-900">Memphis Tech Events</h1>
          <p role="status" className="mt-2 text-slate-700">
            Loading data from the API…
          </p>
        </main>
      }
    >
      <Dashboard />
    </Suspense>
  );
}

async function Dashboard() {
  const [total, months, categories, groups, hours] = await Promise.all([
    fetchTotalEvents(),
    fetchEventsPerMonth(),
    fetchEventsPerCategory(),
    fetchTopGroups(),
    fetchEventsPerHour(),
  ]);

  const everythingFailed = [total, months, categories, groups, hours].every((r) => !r.ok);

  return (
    <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-8 sm:px-6">
      <header>
        <h1 className="text-3xl font-bold text-slate-900">Memphis Tech Events</h1>
        <p className="mt-2 max-w-3xl text-slate-700">
          Four questions about Memphis tech event data, answered from the read-only stats API on top of the
          PostgreSQL warehouse. Data is as fresh as the last pipeline run.
        </p>
      </header>

      {everythingFailed && (
        <p role="alert" className="mt-6 rounded-md border border-red-700 bg-red-50 p-4 text-red-900">
          <strong>The dashboard can’t reach the API.</strong> Expected it at {API_BASE_URL}. Start it from the
          project root with <code>uvicorn api.main:app</code>, then reload this page.
        </p>
      )}

      <div className="mt-6 grid gap-6 lg:grid-cols-2">
        <div className="lg:col-span-2">
          {total.ok ? (
            <TotalCard total={total.data.total} />
          ) : (
            <StatusNotice id="total" question="How many events are in the warehouse?" kind="error" message={total.error} />
          )}
        </div>

        {!months.ok ? (
          <StatusNotice id="month" question={Q_MONTH} kind="error" message={months.error} />
        ) : months.data.length === 0 ? (
          <StatusNotice id="month" question={Q_MONTH} kind="empty" message="The API returned no months." />
        ) : (
          <ChartCard
            id="month"
            question={Q_MONTH}
            summary={`Events by month, from ${months.data[0].month} to ${months.data[months.data.length - 1].month}. Busiest month: ${
              [...months.data].sort((a, b) => b.event_count - a.event_count)[0].month
            } with ${Math.max(...months.data.map((m) => m.event_count))} events.`}
            note="Months with no events are still shown. The latest month may be incomplete if it includes upcoming events."
            table={{ headers: ["Month", "Events"], rows: months.data.map((m) => [m.month, m.event_count]) }}
          >
            <MonthlyChart data={months.data} />
          </ChartCard>
        )}

        {!categories.ok ? (
          <StatusNotice id="category" question={Q_CATEGORY} kind="error" message={categories.error} />
        ) : categories.data.length === 0 ? (
          <StatusNotice id="category" question={Q_CATEGORY} kind="empty" message="The API returned no categories." />
        ) : (
          <ChartCard
            id="category"
            question={Q_CATEGORY}
            summary={`All-time events per category. ${categories.data[0].event_category} leads with ${categories.data[0].event_count} events.`}
            note="All events, all time."
            table={{
              headers: ["Category", "Events"],
              rows: categories.data.map((c) => [c.event_category, c.event_count]),
            }}
          >
            <CategoryChart data={categories.data} />
          </ChartCard>
        )}

        {!groups.ok ? (
          <StatusNotice id="group" question={Q_GROUP} kind="error" message={groups.error} />
        ) : groups.data.items.length === 0 ? (
          <StatusNotice id="group" question={Q_GROUP} kind="empty" message="No events with a group were found." />
        ) : (
          <ChartCard
            id="group"
            question={Q_GROUP}
            summary={`Top ${groups.data.items.length} groups by number of events. ${groups.data.items[0].group_name} leads with ${groups.data.items[0].event_count} events.`}
            note={
              <>
                <strong>Coverage:</strong> {groups.data.events_with_group} of {groups.data.events_in_window} events (
                {percent(groups.data.events_with_group, groups.data.events_in_window)}) have a group; the rest are
                not counted here. Window: the last {groups.data.window_days} days plus upcoming events.
              </>
            }
            table={{
              headers: ["Group", "Events"],
              rows: groups.data.items.map((g) => [g.group_name, g.event_count]),
            }}
          >
            <GroupChart data={groups.data.items} />
          </ChartCard>
        )}

        {!hours.ok ? (
          <StatusNotice id="hour" question={Q_HOUR} kind="error" message={hours.error} />
        ) : hours.data.items.length === 0 ? (
          <StatusNotice id="hour" question={Q_HOUR} kind="empty" message="No events have a usable start time." />
        ) : (
          <ChartCard
            id="hour"
            question={Q_HOUR}
            summary={`Events by start hour. Busiest hour: ${hourLabel(
              [...hours.data.items].sort((a, b) => b.event_count - a.event_count)[0].hour,
            )} with ${Math.max(...hours.data.items.map((h) => h.event_count))} events.`}
            note={
              <>
                Showing {hours.data.events_with_time} of {hours.data.events_total} events. Excluded:{" "}
                {hours.data.excluded_no_time} with no start time and {hours.data.excluded_placeholder} with the
                23:59 placeholder time. Times are Memphis local time.
              </>
            }
            table={{
              headers: ["Start hour", "Events"],
              rows: hours.data.items.map((h) => [hourLabel(h.hour), h.event_count]),
            }}
          >
            <HourChart data={hours.data.items} />
          </ChartCard>
        )}
      </div>

      <footer className="mt-8 text-sm text-slate-700">
        Source: Contentful → extract → transform → load → PostgreSQL star schema → read-only FastAPI → this page.
      </footer>
    </main>
  );
}
