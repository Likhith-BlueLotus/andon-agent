import { useEffect, useState } from "react";
import { motion } from "motion/react";
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
    <main className="relative mx-auto w-full max-w-5xl flex-1 space-y-6 overflow-y-auto p-4 sm:p-6">
      <header className="pt-2">
        <p className="eyebrow text-accent">Does it work?</p>
        <h1 className="mt-1 text-2xl font-semibold tracking-tight">Evaluation</h1>
        <p className="mt-1 max-w-2xl text-sm text-muted">Latest committed run. Rates carry Wilson 95% intervals; small sets mean wide intervals, so read the interval, not just the point.</p>
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
            <dl className="flex flex-wrap gap-x-6 gap-y-1 rounded-lg border border-line bg-panel/70 px-3 py-2 font-mono text-xs text-muted">
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
  const lead = metric ? set.rows.find((r) => r.cells[metric]?.value != null) : null;
  const leadCell = lead && metric ? lead.cells[metric] : null;
  const unitScale = metric ? set.rows.every((r) => (r.cells[metric]?.hi ?? r.cells[metric]?.value ?? 0) <= 1) : true;
  return (
    <section aria-label={set.title} className="card overflow-hidden" data-eval-set={set.id}>
      <header className="flex flex-wrap items-end justify-between gap-4 border-b border-line p-4">
        <div>
          <p className="label">{set.id}-set</p>
          <h2 className="mt-0.5 text-lg font-semibold tracking-tight">{set.title}</h2>
        </div>
        {leadCell?.value != null && metric && (
          <div className="text-right">
            <p className="label">{lead!.system} · {metric.replace(/_/g, " ")}</p>
            <p className="font-mono text-3xl font-semibold leading-none tracking-tight tabular-nums">{fmt(leadCell.value, unitScale)}</p>
            {leadCell.lo != null && leadCell.hi != null && <p className="mt-1 font-mono text-[11px] text-muted">95% CI {fmt(leadCell.lo, unitScale)} to {fmt(leadCell.hi, unitScale)}</p>}
          </div>
        )}
      </header>
      {metric && unitScale && set.rows.some((r) => r.cells[metric]?.value != null) && (
        <div className="border-b border-line p-4">
          <p className="label mb-3">{metric.replace(/_/g, " ")} · point and Wilson 95% interval</p>
          <ul className="space-y-3" role="img" aria-label={`Interval plot of ${metric.replace(/_/g, " ")} by system. Exact values and intervals are in the table below.`}>
            {set.rows.map((r, i) => {
              const c = r.cells[metric];
              if (c?.value == null) return null;
              return (
                <li key={r.system} className="grid grid-cols-[minmax(7rem,12rem)_1fr_3.5rem] items-center gap-3" aria-hidden>
                  <span className={`truncate text-sm ${i === 0 ? "font-semibold" : "text-muted"}`}>{r.system}</span>
                  <span className="relative h-6">
                    <span className="absolute inset-x-0 top-1/2 h-px bg-line" />
                    {[0.25, 0.5, 0.75].map((t) => <span key={t} className="absolute top-1 h-4 w-px bg-line/70" style={{ left: `${t * 100}%` }} />)}
                    {c.lo != null && c.hi != null && (
                      <motion.span className={`absolute top-1/2 h-2 -translate-y-1/2 rounded-full ${i === 0 ? "bg-accent/35" : "bg-muted/30"}`} initial={{ opacity: 0 }} animate={{ opacity: 1 }} style={{ left: `${c.lo * 100}%`, width: `${(c.hi - c.lo) * 100}%` }} />
                    )}
                    <motion.span className={`absolute top-1/2 h-3.5 w-3.5 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-panel ${i === 0 ? "bg-accent" : "bg-muted"}`} initial={{ left: "0%" }} animate={{ left: `${c.value * 100}%` }} transition={{ duration: 0.7, ease: [0.2, 0.8, 0.2, 1], delay: 0.05 * i }} />
                  </span>
                  <span className="text-right font-mono text-sm tabular-nums">{fmt(c.value, true)}</span>
                </li>
              );
            })}
          </ul>
          <div aria-hidden className="mt-1 grid grid-cols-[minmax(7rem,12rem)_1fr_3.5rem] gap-3 font-mono text-[10px] text-muted">
            <span />
            <span className="flex justify-between"><span>0</span><span>0.5</span><span>1</span></span>
            <span />
          </div>
        </div>
      )}
      <div className="overflow-x-auto p-4 pt-2">
        <table className="w-full min-w-[32rem] border-collapse text-sm">
          <caption className="sr-only">{set.title} results</caption>
          <thead>
            <tr className="border-b border-line text-left">
              <th scope="col" className="label py-2 pr-3">System</th>
              {set.columns.map((c) => (<th key={c} scope="col" className="label py-2 pr-3">{c.replace(/_/g, " ")}</th>))}
            </tr>
          </thead>
          <tbody>
            {set.rows.map((r) => (
              <tr key={r.system} className="border-b border-line/60 transition-colors last:border-0 hover:bg-raised/50">
                <th scope="row" className="py-2 pr-3 text-left font-medium">{r.system}</th>
                {set.columns.map((c) => (<td key={c} className="py-2 pr-3 font-mono text-xs tabular-nums">{r.cells[c]?.text ?? "n/a"}</td>))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function fmt(v: number, unit: boolean): string {
  return unit ? v.toFixed(2) : String(Number(v.toPrecision(4)));
}
