import { useEffect, useMemo, useState } from "react";
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { IncidentState, ToolCard } from "../state/reducer";
import { getTelemetry, ApiError } from "../lib/api";
import { mockTelemetry } from "../lib/mock";
import { briefSummary, qualityNotes, telemetryQuery } from "../lib/summary";
import { fmtTime } from "../lib/format";
import type { TelemetryResponse } from "../types/api";
import { Dialog } from "./Dialog";
import { IconAlert, ProvenanceChip, Spinner } from "./ui";

const COLORS = ["rgb(var(--accent))", "rgb(var(--warn))", "rgb(var(--ok))", "rgb(var(--fg))"];

type Load = { s: "idle" } | { s: "loading" } | { s: "ok"; data: TelemetryResponse } | { s: "error"; msg: string };

/** Pivot series into rows keyed by timestamp. null values stay null so Recharts draws a gap. */
export function pivot(t: TelemetryResponse): Record<string, number | string | null>[] {
  const rows = new Map<string, Record<string, number | string | null>>();
  for (const s of t.series) {
    for (const [ts, v] of s.points) {
      const r = rows.get(ts) ?? { ts };
      r[s.tag] = v;
      rows.set(ts, r);
    }
  }
  return [...rows.values()].sort((a, b) => String(a.ts).localeCompare(String(b.ts)));
}

export function EvidenceDrawer({ state, evidenceId, scenarioId, isMock, onClose }: { state: IncidentState; evidenceId: string; scenarioId: string | null; isMock: boolean; onClose: () => void }) {
  const card: ToolCard | undefined = useMemo(() => state.toolOrder.map((id) => state.tools[id]).find((t) => t.evidenceId === evidenceId), [state, evidenceId]);
  const q = card ? telemetryQuery(card.tool, card.args) : null;
  const [load, setLoad] = useState<Load>({ s: "idle" });

  useEffect(() => {
    if (!q || !scenarioId) return;
    const ac = new AbortController();
    setLoad({ s: "loading" });
    (async () => {
      try {
        const data = isMock ? mockTelemetry(scenarioId, q, card!.summary && typeof card!.summary.tags === "object" ? (card!.summary.tags as Record<string, unknown>) : card!.summary) : await getTelemetry(scenarioId, q, ac.signal);
        if (isMock) await new Promise((r) => setTimeout(r, 300));
        if (!ac.signal.aborted) setLoad({ s: "ok", data });
      } catch (e) {
        if (ac.signal.aborted) return;
        const msg =
          e instanceof ApiError && e.status === 404
            ? "No stored series for this query (the telemetry endpoint answered 404). The summary above is what the agent saw."
            : e instanceof ApiError
              ? `Could not load the series: ${e.message}`
              : "Could not load the series.";
        setLoad({ s: "error", msg });
      }
    })();
    return () => ac.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [evidenceId, scenarioId]);

  const rows = load.s === "ok" ? pivot(load.data) : [];
  const notes = card?.summary ? qualityNotes(card.summary) : [];
  
  return (
    <Dialog title={evidenceId} onClose={onClose} side labelId="evidence-title">
      {!card ? (
        <p className="text-sm">This evidence id is not part of the current trace.</p>
      ) : (
        <div className="space-y-4">
          <section>
            <h3 className="label">Tool call</h3>
            <p className="font-mono text-sm font-semibold" data-autofocus tabIndex={-1}>{card.tool} <span className="font-normal text-muted">by {card.agent ?? "system"}</span></p>
            <p className="mt-1 text-[13px]">{card.summary ? briefSummary(card.tool, card.summary) : "no result yet"}</p>
            <div className="mt-1 flex flex-wrap items-center gap-2">
              <ProvenanceChip provenance={card.provenance} />
              {card.latencyMs != null && <span className="font-mono text-[11px] text-muted">{card.latencyMs} ms</span>}
            </div>
            {notes.map((n, i) => <p key={i} className="mt-1 text-[11px] text-muted">· {n}</p>)}
          </section>

          {q && (
            <section aria-label="Queried window chart">
              <h3 className="label">Queried window</h3>
              <p className="font-mono text-[11px] text-muted">{q.asset_id} · {q.tags.join(", ")} · {fmtTime(q.t0)} to {fmtTime(q.t1)}</p>
              {load.s === "loading" && <p className="mt-2 flex items-center gap-2 text-sm text-muted"><Spinner label="loading series" />Loading series…</p>}
              {load.s === "error" && <p role="alert" className="mt-2 flex items-start gap-2 text-sm text-warn"><IconAlert className="mt-0.5 shrink-0" />{load.msg}</p>}
              {load.s === "ok" && (
                <>
                  <div className="mt-2 space-y-2" role="img" aria-label={`Line charts of ${q.tags.join(", ")} for ${q.asset_id}, one per tag. Gaps in the data are shown as breaks in the line.`}>
                    {load.data.series.map((s, i) => (
                      <figure key={s.tag} className="m-0">
                        <figcaption className="font-mono text-[11px] text-muted">{s.tag}{s.unit ? ` (${s.unit})` : ""}</figcaption>
                        <div className="h-28 w-full">
                          <ResponsiveContainer width="100%" height="100%" minWidth={200} minHeight={80}>
                            <LineChart data={rows} margin={{ top: 4, right: 12, bottom: 0, left: 0 }}>
                              <CartesianGrid stroke="rgb(var(--line))" strokeDasharray="3 3" />
                              <XAxis dataKey="ts" tickFormatter={(v) => fmtTime(String(v)).slice(0, 5)} stroke="rgb(var(--muted))" tick={{ fontSize: 10 }} minTickGap={28} hide={i < load.data.series.length - 1} />
                              <YAxis stroke="rgb(var(--muted))" tick={{ fontSize: 10 }} width={44} domain={["auto", "auto"]} />
                              <Tooltip labelFormatter={(v) => fmtTime(String(v))} contentStyle={{ background: "rgb(var(--raised))", border: "1px solid rgb(var(--line))", fontSize: 12 }} />
                              <Line type="monotone" dataKey={s.tag} name={s.unit ? `${s.tag} (${s.unit})` : s.tag} stroke={COLORS[i % COLORS.length]} dot={false} strokeWidth={1.8} connectNulls={false} isAnimationActive={false} />
                            </LineChart>
                          </ResponsiveContainer>
                        </div>
                      </figure>
                    ))}
                  </div>
                  <p className="mt-1 text-[11px] text-muted">
                    {load.data.downsampled ? "Downsampled for display. " : ""}Breaks in a line are missing samples.
                  </p>
                  <div className="mt-1"><ProvenanceChip provenance={load.data.provenance} /></div>
                </>
              )}
            </section>
          )}

          <section>
            <h3 className="label">Arguments</h3>
            <pre className="mt-1 max-h-48 overflow-auto rounded bg-raised p-2 font-mono text-[11px]">{JSON.stringify(card.args, null, 2)}</pre>
          </section>
          <section>
            <h3 className="label">Summary the agent received</h3>
            <pre className="mt-1 max-h-72 overflow-auto rounded bg-raised p-2 font-mono text-[11px]">{JSON.stringify(card.summary, null, 2)}</pre>
          </section>
        </div>
      )}
    </Dialog>
  );
}
