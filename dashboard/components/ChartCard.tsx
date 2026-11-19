import type { ReactNode } from "react";

type Props = {
  id: string;
  /** The question this chart answers; shown as the visible heading. */
  question: string;
  /** Short text summary of what the chart shows (also read by screen readers). */
  summary: string;
  /** Visible data note (coverage, exclusions). */
  note?: ReactNode;
  /** Column headers and rows of the chart data, exposed to screen readers. */
  table: { headers: [string, string]; rows: [string | number, number][] };
  children: ReactNode;
};

/** Semantic wrapper shared by every chart: heading, summary, chart, note, data table. */
export default function ChartCard({ id, question, summary, note, table, children }: Props) {
  return (
    <section
      aria-labelledby={`${id}-title`}
      className="min-w-0 rounded-xl border border-slate-300 bg-white p-4 shadow-sm sm:p-6"
    >
      <h2 id={`${id}-title`} className="text-lg font-semibold text-slate-900">
        {question}
      </h2>
      <p className="mt-1 text-sm text-slate-700">{summary}</p>
      <div role="img" aria-label={`${question} ${summary}`} className="mt-4">
        {children}
      </div>
      {note && <p className="mt-3 text-sm text-slate-700">{note}</p>}
      <table className="sr-only">
        <caption>{question}</caption>
        <thead>
          <tr>
            <th scope="col">{table.headers[0]}</th>
            <th scope="col">{table.headers[1]}</th>
          </tr>
        </thead>
        <tbody>
          {table.rows.map(([label, value]) => (
            <tr key={label}>
              <th scope="row">{label}</th>
              <td>{value}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
