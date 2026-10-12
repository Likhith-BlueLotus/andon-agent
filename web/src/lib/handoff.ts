import type { IncidentState } from "../state/reducer";

/**
 * Console -> /tech handoff. The finished incident state is passed in module memory (no refetch, no re-run,
 * and nothing in the URL beyond the incident id). A page reload loses it; /tech then falls back to a replay.
 */
export interface Handoff {
  state: IncidentState;
  scenarioId: string | null;
  mode: "live" | "replay";
  passcode: string | null;
}
let current: Handoff | null = null;
export const setHandoff = (h: Handoff | null): void => {
  current = h;
};
export const getHandoff = (incidentId: string | null): Handoff | null => (current && incidentId && current.state.incidentId === incidentId ? current : null);

/** `/tech?incident=…&scenario=…`, keeping only the mock switch from the current query. */
export function techHref(incidentId: string, scenarioId: string | null, search: string = window.location.search): string {
  const q = new URLSearchParams(search);
  q.delete("scenario");
  q.delete("mode");
  q.delete("incident");
  q.set("incident", incidentId);
  if (scenarioId) q.set("scenario", scenarioId);
  return `/tech?${q.toString()}`;
}
