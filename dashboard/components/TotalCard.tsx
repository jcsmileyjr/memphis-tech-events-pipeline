type Props = { total: number };

export default function TotalCard({ total }: Props) {
  return (
    <section
      aria-labelledby="total-title"
      className="rounded-xl border border-slate-300 bg-white p-4 shadow-sm sm:p-6"
    >
      <h2 id="total-title" className="text-lg font-semibold text-slate-900">
        How many events are in the warehouse?
      </h2>
      <p className="mt-2 text-5xl font-bold text-blue-800">{total.toLocaleString("en-US")}</p>
      <p className="mt-1 text-sm text-slate-700">events in total, across all months</p>
    </section>
  );
}
