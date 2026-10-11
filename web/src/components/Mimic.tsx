import { useEffect, useMemo, useState } from "react";
import type { IncidentState } from "../state/reducer";
import { stationKey } from "../lib/format";
import { assetsInArgs } from "../lib/summary";
import { ASSUMED_DOWNTIME_USD_PER_MIN } from "../lib/config";
import { IconAlert, IconCheck, IconX, Spinner } from "./ui";

interface Station {
  key: string;
  label: string;
  name: string;
}

const DEFAULT_LINE: Station[] = [
  { key: "ST10", label: "ST10", name: "Press" },
  { key: "ST20", label: "ST20", name: "Weld A" },
  { key: "ST30", label: "ST30", name: "Weld B" },
  { key: "ST40", label: "ST40", name: "Sealer" },
  { key: "ST50", label: "ST50", name: "Conveyor" },
  { key: "ST60", label: "ST60", name: "Vision" },
];
const DEFAULT_UTIL: Station[] = [
  { key: "UT-AIR", label: "UT-AIR", name: "Compressed air" },
  { key: "UT-CHL", label: "UT-CHL", name: "Chilled water" },
];

type Obj = Record<string, unknown>;

/** Stations from list_assets when the run returned full asset records; otherwise the default line. */
export function stationsFrom(state: IncidentState): { line: Station[]; util: Station[] } {
  const line = new Map<string, Station>();
  const util = new Map<string, Station>();
  for (const id of state.toolOrder) {
    const t = state.tools[id];
    if (t?.tool !== "list_assets" || !t.summary || !Array.isArray(t.summary.assets)) continue;
    for (const a of t.summary.assets as unknown[]) {
      if (!a || typeof a !== "object") continue;
      const o = a as Obj;
      const aid = typeof o.asset_id === "string" ? o.asset_id : null;
      if (!aid) continue;
      const key = stationKey(aid);
      const name = typeof o.name === "string" ? o.name.replace(/^ST\d+\s*/i, "") : aid;
      (key.startsWith("UT-") ? util : line).set(key, { key, label: key, name });
    }
  }
  const sort = (m: Map<string, Station>) => [...m.values()].sort((a, b) => a.key.localeCompare(b.key));
  return { line: line.size >= 3 ? sort(line) : DEFAULT_LINE, util: util.size ? sort(util) : DEFAULT_UTIL };
}

export function alarmCounts(state: IncidentState): Record<string, number> {
  const out: Record<string, number> = {};
  for (const id of state.toolOrder) {
    const t = state.tools[id];
    if (t?.tool !== "search_alarms" || !t.summary) continue;
    const by = t.summary.by_station;
    if (by && typeof by === "object") for (const [k, v] of Object.entries(by as Obj)) if (typeof v === "number" && v > 0) out[stationKey(k)] = v;
  }
  return out;
}

interface Marks {
  stopped: string;
  active: Set<string>;
  seen: Set<string>;
  alarms: Record<string, number>;
  root: string | null;
}

export function marksFor(state: IncidentState, stoppedFallback: string | null): Marks {
  const active = new Set<string>();
  const seen = new Set<string>();
  for (const id of state.toolOrder) {
    const t = state.tools[id];
    for (const a of assetsInArgs(t.args)) {
      seen.add(stationKey(a));
      if (t.status === "running") active.add(stationKey(a));
    }
  }
  const top = state.final?.status === "verified" ? state.final.hypotheses[0] : null;
  return {
    stopped: stationKey(state.stoppedStation ?? stoppedFallback),
    active,
    seen,
    alarms: alarmCounts(state),
    root: top ? stationKey(top.asset_id) : null,
  };
}

function Block({ s, m }: { s: Station; m: Marks }) {
  const stopped = m.stopped === s.key;
  const active = m.active.has(s.key);
  const seen = m.seen.has(s.key);
  const alarms = m.alarms[s.key] ?? 0;
  const root = m.root === s.key;
  const status: string[] = [];
  if (stopped) status.push("stopped");
  if (alarms) status.push(`${alarms} alarms`);
  if (active) status.push("being checked");
  else if (seen) status.push("checked");
  if (root) status.push("verified root cause");
  return (
    <li
      data-station={s.key}
      data-state={status.join(",") || "ok"}
      aria-label={`${s.label} ${s.name}: ${status.join(", ") || "running"}`}
      className={`relative min-w-0 rounded border px-1.5 py-1.5 text-center ${
        stopped ? "station-stopped border-bad bg-bad/10" : "border-line bg-raised"
      } ${seen || active ? "outline outline-2 outline-offset-1 outline-accent" : ""}`}
    >
      <div className="font-mono text-xs font-semibold">{s.label}</div>
      <div className="truncate text-[11px] text-muted">{s.name}</div>
      <div className="mt-1 flex min-h-[16px] flex-col items-center gap-0.5 text-[10px] font-semibold leading-3">
        {stopped && (
          <span className="inline-flex items-center gap-0.5 text-bad"><IconX className="h-3 w-3" />STOPPED</span>
        )}
        {alarms > 0 && !stopped && (
          <span className="inline-flex items-center gap-0.5 text-warn"><IconAlert className="h-3 w-3" />ALARM {alarms}</span>
        )}
        {active && <span className="inline-flex items-center gap-1 text-accent"><Spinner label="checking" />CHECK</span>}
        {!active && seen && !root && <span className="text-accent">checked</span>}
        {root && <span className="inline-flex items-center gap-0.5 text-ok"><IconCheck className="h-3 w-3" />ROOT CAUSE</span>}
      </div>
    </li>
  );
}

const Arrow = ({ dir }: { dir: "r" | "l" | "d" }) => (
  <li aria-hidden className="flex items-center justify-center text-muted">
    <svg width="14" height="14" viewBox="0 0 14 14" className={dir === "l" ? "rotate-180" : dir === "d" ? "rotate-90" : ""}>
      <path d="M1 7h11" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" className="flow-dash" /><path d="M8 3.5L12 7l-4 3.5" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  </li>
);

export function Mimic({ state, stoppedFallback }: { state: IncidentState; stoppedFallback: string | null }) {
  const { line, util } = useMemo(() => stationsFrom(state), [state]);
  const m = marksFor(state, stoppedFallback);
  const top = line.slice(0, 3);
  const bottom = line.slice(3).reverse();
  return (
    <section aria-label="Line mimic" className="space-y-2">
      <ol className="grid grid-cols-[1fr_auto_1fr_auto_1fr] items-stretch gap-1" aria-label="Production line, flow left to right then back along the second row">
        {top.map((s, i) => (
          <FlowItem key={s.key} s={s} m={m} arrow={i < top.length - 1 ? "r" : null} />
        ))}
        <li aria-hidden className="col-span-5 -my-0.5 flex justify-end pr-[14%] text-muted">
          <svg width="14" height="16" viewBox="0 0 14 16"><path d="M7 1v11" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" className="flow-dash" /><path d="M3 9l4 4 4-4" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" /></svg>
        </li>
        {bottom.map((s, i) => (
          <FlowItem key={s.key} s={s} m={m} arrow={i < bottom.length - 1 ? "l" : null} />
        ))}
      </ol>
      <div className="relative pt-3">
        <div className="absolute left-0 right-0 top-1.5 h-px bg-line" aria-hidden />
        <span className="label absolute -top-0.5 left-0 bg-panel pr-2">utilities rail</span>
        <ul className="mt-2 grid grid-cols-2 gap-1" aria-label="Utilities feeding the line">
          {util.map((s) => (
            <Block key={s.key} s={s} m={m} />
          ))}
        </ul>
      </div>
    </section>
  );
}

function FlowItem({ s, m, arrow }: { s: Station; m: Marks; arrow: "r" | "l" | null }) {
  return (
    <>
      <Block s={s} m={m} />
      {arrow ? <Arrow dir={arrow} /> : null}
    </>
  );
}

/** Downtime cost: elapsed wall time while the stream runs x an ASSUMED rate. Never a measurement. */
export function CostTicker({ running, startKey }: { running: boolean; startKey: string | null }) {
  const [elapsed, setElapsed] = useState(0);
  useEffect(() => {
    setElapsed(0);
  }, [startKey]);
  useEffect(() => {
    if (!running || !startKey) return; // stopped: the last value stays on screen
    const t0 = Date.now();
    const id = setInterval(() => setElapsed((Date.now() - t0) / 1000), 500);
    return () => clearInterval(id);
  }, [running, startKey]);
  const usd = (elapsed / 60) * ASSUMED_DOWNTIME_USD_PER_MIN;
  return (
    <div className="rounded border border-line bg-raised px-2 py-1.5" data-testid="cost-ticker">
      <div className="label">Downtime cost · est.</div>
      <div className="font-mono text-lg font-semibold tabular-nums" aria-label={`Estimated downtime cost ${Math.round(usd)} dollars`}>
        ${Math.round(usd).toLocaleString("en-US")}
      </div>
      <div className="text-[11px] text-muted">
        est. · assumption: ${Math.round(ASSUMED_DOWNTIME_USD_PER_MIN).toLocaleString("en-US")}/min (US$2.3M/h unplanned automotive downtime, Siemens 2024). Not a measurement.
      </div>
    </div>
  );
}
