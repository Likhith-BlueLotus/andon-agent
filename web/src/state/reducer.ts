import type {
  AndonEvent,
  CacheHitData,
  Claim,
  ClaimVerdict,
  CostData,
  DoneData,
  ErrorData,
  ModelFallbackData,
  ProvenanceRef,
  RCAReport,
  WorkOrder,
} from "../types/events";
import { MAX_VERIFIER_ITERATIONS } from "../lib/config";

export interface ToolCard {
  callId: string;
  tool: string;
  agent: string | null;
  args: Record<string, unknown>;
  status: "running" | "done" | "error";
  evidenceId: string;
  summary: Record<string, unknown> | null;
  provenance: ProvenanceRef[];
  latencyMs: number | null;
  callTs: string;
  toolError: { code: string; message: string } | null;
}

export type TraceItem =
  | { kind: "tool"; callId: string }
  | { kind: "cache"; data: CacheHitData; seq: number }
  | { kind: "fallback"; data: ModelFallbackData; seq: number }
  | { kind: "proposed"; count: number; top: string | null; seq: number }
  | { kind: "verdict"; verdict: ClaimVerdict; text: string; seq: number }
  | { kind: "verdict_summary"; overall: "PASS" | "FAIL"; iteration: number; seq: number };

export interface Lane {
  id: string;
  agent: string;
  modelId: string | null;
  status: "running" | "finished";
  startedSeq: number;
  items: TraceItem[];
}

export interface RejectedClaim {
  claim: Claim;
  verdict: ClaimVerdict;
}
export interface Revision {
  iteration: number;
  rejected: RejectedClaim[];
}

export interface StreamError extends ErrorData {
  seq: number;
  ts: string;
  /** true while a retryable error has not yet been followed by further progress */
  retrying: boolean;
}

export interface IncidentState {
  phase: "idle" | "streaming" | "done";
  incidentId: string | null;
  scenarioId: string | null;
  lineId: string | null;
  stoppedStation: string | null;
  mode: "live" | "replay" | null;
  startedTs: string | null;
  lastSeq: number;
  plan: string[] | null;
  /** index of plan steps considered done (indicative: the contract has no step-to-tool link) */
  planDone: number;
  planBaseline: number;
  lanes: Lane[];
  tools: Record<string, ToolCard>;
  toolOrder: string[];
  /** latest (draft) hypotheses of the current verification round */
  draft: RCAReport | null;
  verdicts: Record<string, ClaimVerdict>;
  verifier: {
    iteration: number;
    overall: "PASS" | "FAIL" | null;
    checking: boolean;
    revising: boolean;
  };
  revisions: Revision[];
  final: RCAReport | null;
  workOrder: WorkOrder | null;
  cost: CostData | null;
  cacheSavedUsd: number;
  cachedTokens: number;
  fallbacks: ModelFallbackData[];
  errors: StreamError[];
  done: DoneData | null;
  /** polite aria-live announcements, newest last */
  announcements: { id: number; text: string }[];
}

export const initialState: IncidentState = {
  phase: "idle",
  incidentId: null,
  scenarioId: null,
  lineId: null,
  stoppedStation: null,
  mode: null,
  startedTs: null,
  lastSeq: -1,
  plan: null,
  planDone: 0,
  planBaseline: 0,
  lanes: [],
  tools: {},
  toolOrder: [],
  draft: null,
  verdicts: {},
  verifier: { iteration: 0, overall: null, checking: false, revising: false },
  revisions: [],
  final: null,
  workOrder: null,
  cost: null,
  cacheSavedUsd: 0,
  cachedTokens: 0,
  fallbacks: [],
  errors: [],
  done: null,
  announcements: [],
};

export type Action = AndonEvent | { type: "reset" };

function announce(s: IncidentState, text: string): IncidentState["announcements"] {
  return [...s.announcements, { id: s.announcements.length + 1, text }];
}

function laneFor(lanes: Lane[], agent: string | null): number {
  if (agent) {
    for (let i = lanes.length - 1; i >= 0; i--) if (lanes[i].agent === agent) return i;
  }
  return -1;
}

function withItem(lanes: Lane[], agent: string | null, item: TraceItem, seq: number): Lane[] {
  const name = agent ?? "system";
  let i = laneFor(lanes, name);
  if (i === -1) {
    const lane: Lane = { id: `${name}#${seq}`, agent: name, modelId: null, status: "running", startedSeq: seq, items: [item] };
    return [...lanes, lane];
  }
  return lanes.map((l, k) => (k === i ? { ...l, items: [...l.items, item] } : l));
}

function toolError(summary: Record<string, unknown>): { code: string; message: string } | null {
  const e = summary.error;
  if (e && typeof e === "object") {
    const o = e as Record<string, unknown>;
    return { code: String(o.code ?? "tool_error"), message: String(o.message ?? "") };
  }
  return null;
}

/** All claims of a report, flattened. */
export function claimsOf(r: RCAReport | null): Claim[] {
  return r ? r.hypotheses.flatMap((h) => h.claims) : [];
}

export function reduce(state: IncidentState, event: Action): IncidentState {
  if (event.type === "reset") return initialState;
  const base: IncidentState = { ...state, lastSeq: Math.max(state.lastSeq, event.seq) };
  // Any progress after a retryable error means the retry happened.
  const progressed = event.type !== "error" && event.type !== "done";
  const errors = progressed && state.errors.some((e) => e.retrying) ? state.errors.map((e) => ({ ...e, retrying: false })) : state.errors;
  const s: IncidentState = { ...base, errors, incidentId: event.incident_id || base.incidentId };

  switch (event.type) {
    case "incident_started": {
      const d = event.data;
      return {
        ...initialState,
        phase: "streaming",
        incidentId: event.incident_id,
        scenarioId: d.scenario_id,
        lineId: d.line_id,
        stoppedStation: d.stopped_station,
        mode: d.mode,
        startedTs: event.ts,
        lastSeq: event.seq,
      };
    }
    case "plan":
      return {
        ...s,
        phase: s.phase === "idle" ? "streaming" : s.phase,
        plan: event.data.steps,
        planBaseline: s.toolOrder.filter((id) => s.tools[id].status !== "running").length,
      };
    case "agent_started": {
      const lane: Lane = {
        id: `${event.data.agent}#${event.seq}`,
        agent: event.data.agent,
        modelId: event.data.model_id,
        status: "running",
        startedSeq: event.seq,
        items: [],
      };
      return { ...s, phase: s.phase === "idle" ? "streaming" : s.phase, lanes: [...s.lanes, lane] };
    }
    case "agent_finished": {
      const i = laneFor(s.lanes, event.data.agent);
      if (i === -1) return s;
      return {
        ...s,
        lanes: s.lanes.map((l, k) => (k === i ? { ...l, status: "finished", modelId: event.data.model_id ?? l.modelId } : l)),
      };
    }
    case "tool_call": {
      const d = event.data;
      const card: ToolCard = {
        callId: d.call_id,
        tool: d.tool,
        agent: event.agent,
        args: d.args,
        status: "running",
        evidenceId: "",
        summary: null,
        provenance: [],
        latencyMs: null,
        callTs: event.ts,
        toolError: null,
      };
      return {
        ...s,
        tools: { ...s.tools, [d.call_id]: card },
        toolOrder: s.toolOrder.includes(d.call_id) ? s.toolOrder : [...s.toolOrder, d.call_id],
        lanes: withItem(s.lanes, event.agent, { kind: "tool", callId: d.call_id }, event.seq),
      };
    }
    case "tool_result": {
      const d = event.data;
      const prev = s.tools[d.call_id];
      const err = toolError(d.summary);
      const card: ToolCard = {
        ...(prev ?? {
          callId: d.call_id,
          tool: "unknown",
          agent: event.agent,
          args: {},
          callTs: event.ts,
        }),
        status: err ? "error" : "done",
        evidenceId: d.evidence_id,
        summary: d.summary,
        provenance: d.provenance,
        latencyMs: d.latency_ms,
        toolError: err,
      };
      const known = !!prev;
      const doneCount = s.toolOrder.filter((id) => id !== d.call_id && s.tools[id].status !== "running").length + 1;
      const sincePlan = s.plan ? Math.max(0, doneCount - s.planBaseline) : 0;
      const planDone = s.plan ? Math.max(s.planDone, Math.min(s.plan.length, Math.floor(sincePlan / 2))) : 0;
      return {
        ...s,
        tools: { ...s.tools, [d.call_id]: card },
        toolOrder: known ? s.toolOrder : [...s.toolOrder, d.call_id],
        lanes: known ? s.lanes : withItem(s.lanes, event.agent, { kind: "tool", callId: d.call_id }, event.seq),
        planDone,
      };
    }
    case "cache_hit":
      return {
        ...s,
        cacheSavedUsd: s.cacheSavedUsd + event.data.saved_usd,
        cachedTokens: s.cachedTokens + event.data.cached_tokens,
        lanes: withItem(s.lanes, event.agent, { kind: "cache", data: event.data, seq: event.seq }, event.seq),
      };
    case "model_fallback":
      return {
        ...s,
        fallbacks: [...s.fallbacks, event.data],
        lanes: withItem(s.lanes, event.agent, { kind: "fallback", data: event.data, seq: event.seq }, event.seq),
      };
    case "hypotheses": {
      // A new draft: the previous round's rejected claims move to the revision history.
      const rejected: RejectedClaim[] = [];
      for (const c of claimsOf(s.draft)) {
        const v = s.verdicts[c.claim_id];
        if (v && v.verdict !== "pass") rejected.push({ claim: c, verdict: v });
      }
      const revisions = rejected.length ? [...s.revisions, { iteration: s.verifier.iteration, rejected }] : s.revisions;
      return {
        ...s,
        draft: event.data,
        verdicts: {},
        revisions,
        lanes: withItem(
          s.lanes,
          event.agent,
          { kind: "proposed", count: event.data.hypotheses.length, top: event.data.hypotheses[0] ? `${event.data.hypotheses[0].cause_class} at ${event.data.hypotheses[0].asset_id}` : null, seq: event.seq },
          event.seq,
        ),
        planDone: s.plan ? s.plan.length : 0,
        verifier: { ...s.verifier, checking: false, revising: false, overall: null },
      };
    }
    case "claim_verdict":
      return {
        ...s,
        verdicts: { ...s.verdicts, [event.data.claim_id]: event.data },
        verifier: { ...s.verifier, checking: true },
        lanes: withItem(s.lanes, event.agent, { kind: "verdict", verdict: event.data, text: claimText(s.draft, event.data.claim_id) ?? event.data.claim_id, seq: event.seq }, event.seq),
        announcements:
          event.data.verdict === "pass"
            ? s.announcements
            : announce(
                s,
                `Claim ${event.data.verdict === "fail" ? "rejected" : "unverifiable"}: ${
                  claimText(s.draft, event.data.claim_id) ?? event.data.claim_id
                }${event.data.measured_value != null ? `, measured ${event.data.measured_value}` : ""}`,
              ),
      };
    case "verifier_verdict": {
      const v = event.data;
      const verdicts = { ...s.verdicts };
      for (const c of v.claims) if (!verdicts[c.claim_id]) verdicts[c.claim_id] = c;
      return {
        ...s,
        verdicts,
        lanes: withItem(s.lanes, event.agent, { kind: "verdict_summary", overall: v.overall, iteration: v.iteration, seq: event.seq }, event.seq),
        verifier: {
          iteration: v.iteration,
          overall: v.overall,
          checking: false,
          revising: v.overall === "FAIL" && v.iteration < MAX_VERIFIER_ITERATIONS,
        },
      };
    }
    case "rca_final": {
      const r = event.data;
      const top = r.hypotheses[0];
      const text =
        r.status === "verified" && top
          ? `Verified root cause: ${top.cause_class.replace(/_/g, " ")} at ${top.asset_id}, confidence ${Math.round(top.confidence * 100)} percent`
          : "Insufficient evidence: no root cause could be verified";
      return {
        ...s,
        final: r,
        planDone: s.plan ? s.plan.length : 0,
        verifier: { ...s.verifier, checking: false, revising: false },
        announcements: announce(s, text),
      };
    }
    case "work_order_draft":
      return { ...s, workOrder: event.data, announcements: announce(s, "Draft work order ready. Tick every safety step to enable approval.") };
    case "cost":
      return { ...s, cost: event.data };
    case "error":
      return {
        ...s,
        errors: [...s.errors, { ...event.data, seq: event.seq, ts: event.ts, retrying: event.data.retryable }],
        announcements: announce(s, `Error: ${event.data.message}`),
      };
    case "done":
      return {
        ...s,
        phase: "done",
        done: event.data,
        errors: s.errors.map((e) => ({ ...e, retrying: false })),
        lanes: s.lanes.map((l) => (l.status === "running" ? { ...l, status: "finished" } : l)),
      };
    default:
      return s;
  }
}

function claimText(r: RCAReport | null, id: string): string | null {
  return claimsOf(r).find((c) => c.claim_id === id)?.text ?? null;
}

/** Fold a whole event list (used by tests and replays of recorded runs). */
export function reduceAll(events: AndonEvent[], from: IncidentState = initialState): IncidentState {
  return events.reduce<IncidentState>((st, e) => reduce(st, e), from);
}

/** Display state of a claim given the current verdicts. */
export type ClaimState = "pending" | "verified" | "rejected" | "unverifiable";
export function claimState(verdicts: Record<string, ClaimVerdict>, claimId: string): ClaimState {
  const v = verdicts[claimId];
  if (!v) return "pending";
  return v.verdict === "pass" ? "verified" : v.verdict === "fail" ? "rejected" : "unverifiable";
}
