import { useEffect, useMemo, useState } from "react";
import { motion } from "motion/react";
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
  const lamp = root ? "bg-ok lamp-glow-ok" : stopped ? "bg-bad lamp-glow-bad" : alarms ? "bg-warn lamp-glow-warn" : active ? "bg-accent lamp-glow-accent" : seen ? "bg-accent/60" : "bg-line-strong";
  const frame = root
    ? "border-ok bg-ok/10 ring-2 ring-ok/50 ring-offset-2 ring-offset-panel"
    : stopped
      ? "station-stopped border-bad bg-bad/10"
      : active
        ? "scan border-accent bg-accent/5"
        : seen
          ? "border-accent/50 bg-raised"
          : "border-line bg-raised";
  return (
    <motion.li
      data-station={s.key}
      data-state={status.join(",") || "ok"}
      aria-label={`${s.label} ${s.name}: ${status.join(", ") || "running"}`}
      animate={root ? { scale: [1, 1.07, 1] } : { scale: 1 }}
      transition={{ duration: 0.5, ease: "easeOut" }}
      className={`relative min-w-0 overflow-hidden rounded-lg border px-2 pb-1.5 pt-2.5 text-left transition-colors duration-300 ${frame}`}
    >
      <span aria-hidden className={`absolute inset-x-0 top-0 h-[3px] ${lamp}`} />
      <div className="flex items-center justify-between gap-1">
        <span className="font-mono text-[12px] font-semibold">{s.label}</span>
        {seen && !active && !root && <IconCheck className="h-3 w-3 shrink-0 text-accent" aria-hidden />}
      </div>
      <div className="truncate text-[11px] text-muted">{s.name}</div>
      <div className="mt-1 flex min-h-[16px] flex-col gap-0.5 text-[10px] font-semibold uppercase leading-3 tracking-wide">
        {stopped && !root && (
          <span className="inline-flex items-center gap-0.5 text-bad"><IconX className="h-3 w-3" />Stopped</span>
        )}
        {alarms > 0 && !stopped && (
          <span className="inline-flex items-center gap-0.5 text-warn"><IconAlert className="h-3 w-3" />Alarm {alarms}</span>
        )}
        {active && <span className="inline-flex items-center gap-1 text-accent"><Spinner label="checking" />Check</span>}
        {!active && seen && !root && !stopped && !alarms && <span className="normal-case tracking-normal text-accent">checked</span>}
        {root && <span className="inline-flex items-center gap-0.5 text-ok"><IconCheck className="h-3 w-3" />Root cause</span>}
      </div>
    </motion.li>
  );
}

/** Conveyor segment between stations. The line is stopped, so the belt is halted (static red hatching). */
const Belt = ({ dir }: { dir: "r" | "l" }) => (
  <li aria-hidden className="flex items-center justify-center">
    <span className="relative flex w-4 flex-col items-center gap-0.5 text-muted">
      <span className="conveyor halted h-1 w-full rounded-full" />
      <svg width="10" height="8" viewBox="0 0 10 8" className={dir === "l" ? "rotate-180" : ""}><path d="M1 1l3 3-3 3M5 1l3 3-3 3" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" /></svg>
    </span>
  </li>
);

const LEGEND: { cls: string; text: string }[] = [
  { cls: "bg-bad", text: "stopped" },
  { cls: "bg-warn", text: "alarm" },
  { cls: "bg-accent", text: "agent checked" },
  { cls: "bg-ok", text: "verified root cause" },
];

export function Mimic({ state, stoppedFallback }: { state: IncidentState; stoppedFallback: string | null }) {
  const { line, util } = useMemo(() => stationsFrom(state), [state]);
  const m = marksFor(state, stoppedFallback);
  const top = line.slice(0, 3);
  const bottom = line.slice(3).reverse();
  return (
    <section aria-label="Line mimic" className="card space-y-3 p-3">
      <div className="flex items-center justify-between">
        <h3 className="label">Line L1 · synthetic</h3>
        <span className="inline-flex items-center gap-1.5 font-mono text-[10px] font-semibold uppercase tracking-wider text-bad">
          <span aria-hidden className="h-1.5 w-1.5 rounded-full bg-bad blink" />conveyor halted
        </span>
      </div>
      <ol className="grid grid-cols-[1fr_auto_1fr_auto_1fr] items-stretch gap-1" aria-label="Production line, flow left to right then back along the second row">
        {top.map((s, i) => (
          <FlowItem key={s.key} s={s} m={m} arrow={i < top.length - 1 ? "r" : null} />
        ))}
        <li aria-hidden className="col-span-5 -my-0.5 flex justify-end pr-[15%] text-muted">
          <svg width="10" height="14" viewBox="0 0 10 14"><path d="M5 1v10" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeDasharray="2 2" /><path d="M2 8l3 3 3-3" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" /></svg>
        </li>
        {bottom.map((s, i) => (
          <FlowItem key={s.key} s={s} m={m} arrow={i < bottom.length - 1 ? "l" : null} />
        ))}
      </ol>
      <div className="relative pt-3">
        <div className="absolute left-0 right-0 top-1.5 h-[3px] rounded-full bg-gradient-to-r from-line via-line-strong to-line" aria-hidden />
        <span className="label absolute -top-0.5 left-2 bg-panel px-1.5">utilities header</span>
        <ul className="mt-2 grid grid-cols-2 gap-1" aria-label="Utilities feeding the line">
          {util.map((s) => (
            <Block key={s.key} s={s} m={m} />
          ))}
        </ul>
      </div>
      <ul className="flex flex-wrap gap-x-3 gap-y-1 border-t border-line pt-2 text-[10px] text-muted" aria-label="Legend">
        {LEGEND.map((l) => (
          <li key={l.text} className="inline-flex items-center gap-1"><span aria-hidden className={`h-1.5 w-3 rounded-full ${l.cls}`} />{l.text}</li>
        ))}
      </ul>
    </section>
  );
}

function FlowItem({ s, m, arrow }: { s: Station; m: Marks; arrow: "r" | "l" | null }) {
  return (
    <>
      <Block s={s} m={m} />
      {arrow ? <Belt dir={arrow} /> : null}
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
  const mm = String(Math.floor(elapsed / 60)).padStart(2, "0");
  const ss = String(Math.floor(elapsed % 60)).padStart(2, "0");
  return (
    <div className="kpi kpi-1" data-testid="cost-ticker">
      <div className="flex items-center justify-between">
        <p className="text-sm font-semibold">Downtime cost · est.</p>
        <span className="kpi-muted inline-flex items-center gap-1 font-mono text-[11px]" aria-label={`Elapsed ${mm} minutes ${ss} seconds`}>
          {running && <span aria-hidden className="blink h-1.5 w-1.5 rounded-full" style={{ background: "rgb(200 36 36)" }} />}
          {mm}:{ss}
        </span>
      </div>
      <div className="mt-2 flex items-end justify-between gap-2">
        <span className="text-2xl font-semibold leading-none tabular-nums" aria-label={`Estimated downtime cost ${Math.round(usd)} dollars`}>${Math.round(usd).toLocaleString("en-US")}</span>
      </div>
      <p className="kpi-muted mt-1.5 text-[11px] leading-snug sm:hidden">est. · assumed ${Math.round(ASSUMED_DOWNTIME_USD_PER_MIN).toLocaleString("en-US")}/min · not a measurement</p>
      <p className="kpi-muted mt-1.5 hidden text-[11px] leading-snug sm:block">est. · assumption: ${Math.round(ASSUMED_DOWNTIME_USD_PER_MIN).toLocaleString("en-US")}/min (US$2.3M/h unplanned automotive downtime, Siemens 2024). Not a measurement.</p>
    </div>
  );
}
