import type { IncidentState } from "../state/reducer";
import { MAX_VERIFIER_ITERATIONS } from "./config";

export type StepState = "todo" | "active" | "done" | "fail" | "warn" | "skip";
export type StepId = "stop" | "plan" | "evidence" | "hypotheses" | "verify" | "workorder" | "approval";
export interface Step {
  id: StepId;
  label: string;
  state: StepState;
  detail: string;
}
export type Decided = "APPROVED" | "REJECTED" | null;
export type Conn = "idle" | "connecting" | "streaming" | "reconnecting" | "dropped" | "closed" | string;

/**
 * Where the investigation is, derived only from the event stream (plus the human's decision).
 * Indicative: it reads which events have arrived, it does not invent progress.
 */
export function investigationSteps(s: IncidentState, decided: Decided = null, conn: Conn = "idle"): Step[] {
  const live = s.phase === "streaming";
  const started = s.phase !== "idle";
  const insufficient = s.final?.status === "insufficient_evidence";
  const verified = s.final?.status === "verified";
  const tools = s.toolOrder.length;
  const running = s.toolOrder.some((id) => s.tools[id]?.status === "running");
  const hyp = (s.final ?? s.draft)?.hypotheses.length ?? 0;
  const judgeRunning = s.lanes.some((l) => l.agent === "rca_judge" && l.status === "running");

  const steps: Step[] = [
    { id: "stop", label: "Stop", state: started ? "done" : "todo", detail: s.stoppedStation ?? "line stopped" },
    { id: "plan", label: "Plan", state: s.plan ? "done" : live ? "active" : "todo", detail: s.plan ? `${s.plan.length} checks` : "pending" },
    {
      id: "evidence",
      label: "Evidence",
      state: s.draft || s.final ? "done" : running || (live && s.plan) ? "active" : tools ? "done" : "todo",
      detail: tools ? `${tools} tool call${tools === 1 ? "" : "s"}` : "pending",
    },
    {
      id: "hypotheses",
      label: "Hypotheses",
      state: hyp ? "done" : judgeRunning ? "active" : "todo",
      detail: hyp ? `${hyp} ranked` : "pending",
    },
    {
      id: "verify",
      label: "Verify",
      state: verified ? "done" : insufficient ? "warn" : s.verifier.checking || s.verifier.revising || (s.verifier.iteration > 0 && live) ? "active" : "todo",
      detail: s.verifier.iteration ? `iteration ${Math.min(s.verifier.iteration, MAX_VERIFIER_ITERATIONS)}/${MAX_VERIFIER_ITERATIONS}${s.verifier.overall ? ` · ${s.verifier.overall}` : ""}` : "code checks claims",
    },
    {
      id: "workorder",
      label: "Work order",
      state: insufficient ? "skip" : s.workOrder ? "done" : verified && live ? "active" : "todo",
      detail: insufficient ? "not drafted" : s.workOrder ? "drafted · LOTO cited" : "pending",
    },
    {
      id: "approval",
      label: "You",
      state: insufficient ? "skip" : decided === "APPROVED" ? "done" : decided === "REJECTED" ? "fail" : s.workOrder && s.final ? "active" : "todo",
      detail: decided === "APPROVED" ? "approved" : decided === "REJECTED" ? "rejected" : s.workOrder && s.final ? "needs your decision" : "human gate",
    },
  ];
  if (conn === "dropped") {
    const i = steps.findIndex((x) => x.state === "active");
    if (i >= 0) steps[i] = { ...steps[i], state: "warn", detail: "stream dropped" };
  }
  return steps;
}

export type RunTone = "idle" | "running" | "verified" | "warn" | "approved" | "bad";
/** One-line status for the header lamp. */
export function runStatus(s: IncidentState, decided: Decided, conn: Conn): { tone: RunTone; text: string } {
  if (conn === "dropped") return { tone: "bad", text: "Stream dropped" };
  if (decided === "APPROVED") return { tone: "approved", text: "Work order approved" };
  if (decided === "REJECTED") return { tone: "bad", text: "Root cause rejected" };
  if (s.final?.status === "insufficient_evidence") return { tone: "warn", text: "Insufficient evidence" };
  if (s.final?.status === "verified") return { tone: "verified", text: "Root cause verified" };
  if (s.verifier.revising) return { tone: "running", text: "Verifier failed a claim · revising" };
  if (s.phase === "streaming" || conn === "connecting" || conn === "streaming" || conn === "reconnecting") return { tone: "running", text: "Investigating" };
  return { tone: "idle", text: "Line stopped · awaiting investigation" };
}
