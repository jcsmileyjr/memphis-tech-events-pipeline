type Props = { id: string; question: string; kind: "error" | "empty"; message: string };

/** Shown in place of a chart when its data failed to load or is empty. */
export default function StatusNotice({ id, question, kind, message }: Props) {
  const isError = kind === "error";
  return (
    <section
      aria-labelledby={`${id}-title`}
      className="rounded-xl border border-slate-300 bg-white p-4 sm:p-6"
    >
      <h2 id={`${id}-title`} className="text-lg font-semibold text-slate-900">
        {question}
      </h2>
      <p
        role={isError ? "alert" : "status"}
        className={`mt-3 rounded-md border p-3 text-sm ${
          isError
            ? "border-red-700 bg-red-50 text-red-900"
            : "border-slate-400 bg-slate-50 text-slate-800"
        }`}
      >
        <strong>{isError ? "Couldn’t load this chart." : "No data yet."}</strong> {message}
      </p>
    </section>
  );
}
