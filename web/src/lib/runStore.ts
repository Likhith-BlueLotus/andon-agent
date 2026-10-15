import { useSyncExternalStore } from "react";
import type { RunTone, Step } from "./progress";

/** The console publishes its run status here so the header's andon lamp can follow it. */
export interface RunSnapshot {
  tone: RunTone;
  text: string;
  /** investigation steps while the console is mounted; null elsewhere */
  steps: Step[] | null;
  /** scenario label for the breadcrumb */
  scenario: string | null;
}
const IDLE: RunSnapshot = { tone: "idle", text: "Line stopped · awaiting investigation", steps: null, scenario: null };
let snap: RunSnapshot = IDLE;
const subs = new Set<() => void>();

export function publishRun(patch: Partial<RunSnapshot>): void {
  const next = { ...snap, ...patch };
  if (next.tone === snap.tone && next.text === snap.text && next.steps === snap.steps && next.scenario === snap.scenario) return;
  snap = next;
  for (const f of subs) f();
}

/** The console unmounted: its stream is aborted and its state is gone, so the lamp goes back to idle. */
export function resetRun(): void {
  publishRun(IDLE);
}

export function getRun(): RunSnapshot {
  return snap;
}

export function useRun(): RunSnapshot {
  return useSyncExternalStore(
    (f) => {
      subs.add(f);
      return () => subs.delete(f);
    },
    () => snap,
    () => snap,
  );
}
