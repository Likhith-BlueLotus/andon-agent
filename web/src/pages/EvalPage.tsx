import { useEffect, useState } from "react";
import { Bar, BarChart, CartesianGrid, ErrorBar, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { ApiError, getEvalLatest } from "../lib/api";
import { readMock } from "../lib/config";
import { MOCK_EVAL, readEval, type EvalSet, type EvalView } from "../lib/evalData";
import { IconInfo, Spinner } from "../components/ui";

type S = { s: "loading" } | { s: "none" } | { s: "error"; msg: string } | { s: "ok"; view: EvalView };

export function EvalPage() {
  const [st, setSt] = useState<S>({ s: "loading" });
  useEffect(() => {
    const ac = new AbortController();
    (async () => {
      try {
        const raw = readMock() ? MOCK_EVAL : await getEvalLatest(ac.signal);
        const view = readEval(raw);
        setSt(view ? { s: "ok", view } : { s: "error", msg: "The eval file is present but its shape was not recognised." });
      } catch (e) {
        if (ac.signal.aborted) return;
        if (e instanceof ApiError && e.status === 404) setSt({ s: "none" });
        else setSt({ s: "error", msg: e instanceof ApiError ? e.message : "Cannot reach the API" });
      }
    })();
    return () => ac.abort();
  }, []);

  return (
    <main className="mx-auto w-full max-w-5xl flex-1 space-y-6 relative overflow-y-auto p-4">
      <header>
        <h1 className="text-xl font-semibold">Evaluation</h1>
        <p className="text-sm text-muted">Latest committed run. Rates carry Wilson 95% intervals; small sets mean wide intervals, so read the interval, not just the point.</p>
      </header>
      {st.s === "loading" && <p className="flex items-center gap-2 text-sm text-muted"><Spinner label="loading" />Loading eval results…</p>}
      {st.s === "none" && (
        <div className="rounded-md border border-dashed border-line p-6" data-testid="eval-empty">
          <p className="flex items-center gap-2 font-semibold"><IconInfo />No eval run published yet</p>
          <p className="mt-1 text-sm text-muted">The S-set (60 synthetic incidents) and R-set (17 real-signal incidents) tables appear here after the eval job has run and its results are committed. Nothing is shown rather than a made-up number.</p>
        </div>
      )}
      {st.s === "error" && <p role="alert" className="rounded border border-bad p-3 text-sm">{st.msg}</p>}
      {st.s === "ok" && (
        <>
          {st.view.meta.length > 0 && (
            <dl className="flex flex-wrap gap-x-6 gap-y-1 font-mono text-xs text-muted">
              {st.view.meta.map((m) => (<div key={m.label}><dt className="inline">{m.label}: </dt><dd className="inline text-fg">{m.value}</dd></div>))}
            </dl>
          )}
          {st.view.sets.map((s) => (<SetBlock key={s.id} set={s} />))}
        </>
      )}
    </main>
  );
}

function SetBlock({ set }: { set: EvalSet }) {
  const metric = set.columns.find((c) => set.rows.some((r) => r.cells[c]?.value != null && r.cells[c].lo != null)) ?? set.columns.find((c) => set.rows.some((r) => r.cells[c]?.value != null && c !== "n"));
  const data = set.rows.map((r) => {
    const c = metric ? r.cells[metric] : null;
    return { system: r.system, value: c?.value ?? 0, err: c && c.lo != null && c.hi != null && c.value != null ? [c.value - c.lo, c.hi - c.value] : [0, 0] };
  });
  return (
    <section aria-label={set.title} className="card p-4" data-eval-set={set.id}>
      <h2 className="text-base font-semibold">{set.title}</h2>
      <div className="mt-2 overflow-x-auto">
        <table className="w-full min-w-[32rem] border-collapse text-sm">
          <caption className="sr-only">{set.title} results</caption>
          <thead>
            <tr className="border-b border-line text-left">
              <th scope="col" className="py-1.5 pr-3 label">System</th>
              {set.columns.map((c) => (<th key={c} scope="col" className="py-1.5 pr-3 label">{c.replace(/_/g, " ")}</th>))}
            </tr>
          </thead>
          <tbody>
            {set.rows.map((r) => (
              <tr key={r.system} className="border-b border-line/60">
                <th scope="row" className="py-1.5 pr-3 text-left font-medium">{r.system}</th>
                {set.columns.map((c) => (<td key={c} className="py-1.5 pr-3 font-mono text-xs tabular-nums">{r.cells[c]?.text ?? "n/a"}</td>))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {metric && data.length > 0 && (
        <div className="mt-3 h-56" role="img" aria-label={`Bar chart of ${metric.replace(/_/g, " ")} by system with Wilson intervals. Values are in the table above.`}>
          <ResponsiveContainer width="100%" height="100%" minWidth={200} minHeight={160}>
            <BarChart data={data} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
              <CartesianGrid stroke="rgb(var(--line))" strokeDasharray="3 3" />
              <XAxis dataKey="system" stroke="rgb(var(--muted))" tick={{ fontSize: 11 }} interval={0} tickFormatter={(v: string) => v.split(" ")[0]} />
              <YAxis domain={[0, 1]} stroke="rgb(var(--muted))" tick={{ fontSize: 11 }} width={36} />
              <Tooltip contentStyle={{ background: "rgb(var(--raised))", border: "1px solid rgb(var(--line))", fontSize: 12 }} />
              <Legend wrapperStyle={{ fontSize: 11 }} />
              <Bar dataKey="value" name={metric.replace(/_/g, " ")} fill="rgb(var(--accent))" isAnimationActive={false}>
                <ErrorBar dataKey="err" stroke="rgb(var(--fg))" width={4} />
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
    </section>
  );
}
