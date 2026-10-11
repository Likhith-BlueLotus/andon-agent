import fixtureRaw from "../../../tests/fixtures/sample_stream.jsonl?raw";
import type { AndonEvent } from "../types/events";
import type { ReplayInfo, ScenariosResponse, SourcesResponse, ApiConfig, TelemetryResponse } from "../types/api";
import type { MockVariant } from "./config";
import { BADGE_TEXT, THEME_STRING } from "./config";

export function parseJsonl(raw: string): AndonEvent[] {
  return raw
    .split("\n")
    .map((l) => l.trim())
    .filter(Boolean)
    .map((l) => JSON.parse(l) as AndonEvent);
}

export const FIXTURE_EVENTS: AndonEvent[] = parseJsonl(fixtureRaw);

/** Events for a mock variant. `ok` is the fixture verbatim; the rest edit it to exercise a designed state. */
export function mockEvents(variant: MockVariant): AndonEvent[] {
  const ev = FIXTURE_EVENTS.map((e) => structuredClone(e));
  if (variant === "ok" || variant === "drop") return ev;
  const iid = ev[0].incident_id;
  if (variant === "budget") {
    return [
      ev[0],
      {
        type: "error",
        incident_id: iid,
        seq: 1,
        ts: ev[0].ts,
        agent: null,
        data: { code: "budget_exhausted", message: "Daily live-run budget is used up. Recorded replays are still available.", retryable: false },
      },
      { type: "done", incident_id: iid, seq: 2, ts: ev[0].ts, agent: null, data: { duration_ms: 0 } },
    ];
  }
  if (variant === "error") {
    // c3 returns a tool error, a retryable error event follows, then the run continues.
    const out: AndonEvent[] = [];
    for (const e of ev) {
      if (e.type === "tool_result" && e.data.call_id === "c3") {
        e.data = { ...e.data, evidence_id: "", summary: { error: { code: "store_timeout", message: "telemetry store timed out after 5 s" } }, provenance: [] };
        out.push(e);
        out.push({
          type: "error",
          incident_id: iid,
          seq: e.seq,
          ts: e.ts,
          agent: e.agent,
          data: { code: "store_timeout", message: "telemetry store timed out; retrying the query", retryable: true },
        });
      } else out.push(e);
    }
    return out;
  }
  // insufficient: the Judge cannot support any hypothesis
  const out: AndonEvent[] = [];
  for (const e of ev) {
    if (e.type === "rca_final") {
      out.push({ ...e, data: { ...e.data, status: "insufficient_evidence", hypotheses: e.data.hypotheses.map((h) => ({ ...h, confidence: 0.31, next_check: "Pull the UT-AIR ultrasonic leak survey and re-run." })) } });
    } else if (e.type === "work_order_draft") continue;
    else out.push(e);
  }
  return out;
}

const gapMs = (a: AndonEvent, b: AndonEvent) => Math.max(0, Date.parse(b.ts) - Date.parse(a.ts));

/** Play events with their ts-derived spacing, divided by `speedup` and capped per gap. */
export async function* playEvents(events: AndonEvent[], signal: AbortSignal, speedup = 6, capMs = 700, dropAfter?: number): AsyncGenerator<AndonEvent> {
  let prev: AndonEvent | null = null;
  let n = 0;
  for (const e of events) {
    if (prev) await sleep(Math.min(capMs, gapMs(prev, e) / speedup), signal);
    if (dropAfter != null && n >= dropAfter) throw new Error("stream_closed");
    yield e;
    prev = e;
    n++;
  }
}

export function sleep(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal.aborted) return reject(new DOMException("aborted", "AbortError"));
    const t = setTimeout(resolve, ms);
    signal.addEventListener(
      "abort",
      () => {
        clearTimeout(t);
        reject(new DOMException("aborted", "AbortError"));
      },
      { once: true },
    );
  });
}

export const MOCK_REPLAY_ID = "fixture";

export const MOCK_SCENARIOS: ScenariosResponse = {
  badge: BADGE_TEXT,
  groups: [
    {
      id: "synthetic",
      title: "Synthetic line (S-set)",
      scenarios: [
        { id: "S014", title: "S014 · line stop at ST60-VIS", group: "synthetic", line_id: "L1", stopped_station: "ST60-VIS", stop_ts: "2026-09-14T11:48:45Z", source_label: "Synthetic line", real_signal: false, replay_run_ids: [MOCK_REPLAY_ID] },
        { id: "S003", title: "S003 · line stop at ST30-WLD", group: "synthetic", line_id: "L1", stopped_station: "ST30-WLD", stop_ts: "2026-09-27T00:41:07Z", source_label: "Synthetic line", real_signal: false, replay_run_ids: [] },
      ],
    },
    {
      id: "real_signal",
      title: "Real signals mapped onto a synthetic line (R-set)",
      scenarios: [
        { id: "R002", title: "R002 · line stop at ST30-WLD · MetroPT-3 compressor", group: "real_signal", line_id: "L1", stopped_station: "ST30-WLD", stop_ts: "2026-10-11T08:42:10Z", source_label: "MetroPT-3 compressor", real_signal: true, replay_run_ids: [MOCK_REPLAY_ID] },
      ],
    },
  ],
};

export const MOCK_REPLAYS: ReplayInfo[] = [
  { run_id: MOCK_REPLAY_ID, scenario_id: "R002", label: "Fixture stream (mock mode): verifier FAIL then PASS", recorded_at: FIXTURE_EVENTS[0].ts, duration_s: 34, cost_usd: 0.1312, final_status: "verified", verifier_rejections: 1, has_work_order: true, source: "fixture" },
];

export const MOCK_CONFIG: ApiConfig = {
  theme: THEME_STRING,
  version: "mock",
  contract_version: "1.0.0",
  badge: BADGE_TEXT,
  modes: { replay: true, live: false, live_requires_passcode: true },
  budget: { daily_usd: 8, remaining_usd: 8, exhausted: false },
  limits: { live_runs_per_day: 30, live_runs_per_min_per_ip: 3 },
  replays_available: 1,
};

export const MOCK_SOURCES: SourcesResponse = {
  note: "Real signals are mapped onto a synthetic line; they are not real plant data.",
  badge: BADGE_TEXT,
  datasets: [
    { id: "metropt3", name: "MetroPT-3 Dataset (UCI #791)", page: "https://archive.ics.uci.edu/dataset/791", licence: "CC BY 4.0", maps_to: "UT-AIR compressor signals; R-set", citation: "Veloso et al. (2022). The MetroPT dataset for predictive maintenance. Scientific Data." },
  ],
};

/** Deterministic demo series from summary statistics, with a visible gap, for mock mode only. */
export function mockTelemetry(
  scenarioId: string,
  q: { asset_id: string; tags: string[]; t0: string; t1: string },
  summary: Record<string, unknown> | null,
): TelemetryResponse {
  const t0 = Date.parse(q.t0);
  const t1 = Date.parse(q.t1);
  const n = 120;
  const series = q.tags.map((tag, k) => {
    const st = (summary?.[tag] ?? {}) as { mean?: number; std?: number; min?: number; max?: number };
    const mean = st.mean ?? 5;
    const amp = st.std ?? Math.abs(mean) * 0.05 + 0.1;
    const points: [string, number | null][] = [];
    for (let i = 0; i < n; i++) {
      const t = t0 + ((t1 - t0) * i) / (n - 1);
      const frac = i / (n - 1);
      const trend = tag.includes("pressure") ? -amp * 2.2 * Math.max(0, frac - 0.6) / 0.4 : amp * 0.8 * frac;
      const wave = Math.sin(i / 5 + k) * amp * 0.5;
      const gap = i >= 58 && i < 62;
      points.push([new Date(t).toISOString(), gap ? null : Math.round((mean + wave + trend) * 1000) / 1000]);
    }
    return { tag, unit: tag.endsWith("_bar") ? "bar" : tag.endsWith("_c") ? "C" : tag.endsWith("_a") ? "A" : null, points };
  });
  return {
    scenario_id: scenarioId,
    asset_id: q.asset_id,
    t0: q.t0,
    t1: q.t1,
    series,
    provenance: [{ source_id: "synthetic", real: false, source_ref: "mock mode: curve drawn from summary statistics, not stored data" }],
    downsampled: true,
  };
}
