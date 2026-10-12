import { claimState, type IncidentState } from "../state/reducer";
import type { Claim, Hypothesis } from "../types/events";
import { humanize } from "./format";

const str = (v: unknown): string | null => (typeof v === "string" && v ? v : null);

/** One compact line for the Stopped card, from the latest tool_call (not the full trace). */
export function progressLine(state: IncidentState): string {
  if (state.final) return "Investigation finished.";
  if (state.verifier.checking) return "Verifying every claim with code…";
  if (state.verifier.revising) return "A claim failed verification. The Judge is revising…";
  const last = [...state.toolOrder].reverse().map((id) => state.tools[id]).find((t) => t && t.status === "running") ?? state.tools[state.toolOrder[state.toolOrder.length - 1]];
  if (!last) return state.phase === "streaming" ? "Planning the investigation…" : "";
  const asset = str(last.args.asset_id) ?? state.stoppedStation ?? "the line";
  switch (last.tool) {
    case "query_telemetry":
      return `Checking ${asset} telemetry…`;
    case "detect_change_points":
      return `Looking for sudden changes on ${asset}…`;
    case "get_stop_event":
      return "Reading the stop event…";
    case "list_assets":
      return "Mapping upstream stations…";
    case "search_alarms":
      return "Searching alarms…";
    case "get_work_orders":
      return `Reading ${asset} maintenance history…`;
    case "cite_manual":
      return "Finding the manual passage…";
    default:
      return `Running ${humanize(last.tool)}…`;
  }
}

export function capitalise(s: string): string {
  return s.charAt(0).toUpperCase() + s.slice(1);
}

/** "Air pressure drop at UT-AIR" */
export function rootCauseSentence(h: Hypothesis): string {
  return `${capitalise(humanize(h.cause_class))} at ${h.asset_id}`;
}

/** The first `n` claims of the top hypothesis that code has verified. */
export function topVerifiedClaims(state: IncidentState, n = 2): Claim[] {
  const h = state.final?.hypotheses[0];
  if (!h) return [];
  return h.claims.filter((c) => claimState(state.verdicts, c.claim_id) === "verified").slice(0, n);
}
