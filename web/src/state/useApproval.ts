import { useEffect, useMemo, useState } from "react";
import type { WorkOrder, WorkOrderStep } from "../types/events";
import type { ApproveResponse } from "../types/api";
import { ApiError, postApprove } from "../lib/api";

export type Decision = "accept" | "edit" | "reject";

export interface ApprovalInput {
  wo: WorkOrder | null;
  incidentId: string | null;
  decision: Decision | null;
  edits: string;
  /** the verified root cause has arrived */
  enabled: boolean;
  passcode: string | null;
  isMock: boolean;
}

/**
 * The approval gate shared by the console's WorkOrderPanel and the technician view:
 * safety ticks, approver name, the lock reasons, and the POST /approve call with its 409/401 handling.
 * One implementation, so the two surfaces cannot drift apart.
 */
export function useApproval({ wo, incidentId, decision, edits, enabled, passcode, isMock }: ApprovalInput) {
  const steps: WorkOrderStep[] = useMemo(() => (wo ? [...wo.steps].sort((a, b) => a.order - b.order) : []), [wo]);
  const safety = useMemo(() => steps.filter((s) => s.is_safety), [steps]);
  const [ticked, setTicked] = useState<Set<number>>(new Set());
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<ApproveResponse | null>(null);
  const woId = wo?.wo_id ?? null;

  useEffect(() => {
    setTicked(new Set());
    setResult(null);
    setError(null);
  }, [woId]);

  const allTicked = safety.every((s) => ticked.has(s.order));
  const missing: string[] = [];
  if (!enabled) missing.push("wait for the verified root cause");
  else if (decision !== "accept" && decision !== "edit") missing.push(decision === "reject" ? "the root cause was rejected" : "accept or edit the root cause");
  if (!allTicked) missing.push(`tick all ${safety.length} safety steps (${ticked.size}/${safety.length} done)`);
  if (!name.trim()) missing.push("enter the approver name");
  const canApprove = !!wo && missing.length === 0 && !busy && !result;
  const decided = result?.status ?? (wo && wo.status !== "PENDING_APPROVAL" ? wo.status : null);

  function toggle(order: number, on?: boolean) {
    setTicked((prev) => {
      const n = new Set(prev);
      const want = on ?? !n.has(order);
      if (want) n.add(order);
      else n.delete(order);
      return n;
    });
  }

  async function submit(kind: "approve" | "reject") {
    if (!incidentId || !wo) return;
    setBusy(true);
    setError(null);
    const body = {
      decision: kind,
      rca_decision: (kind === "reject" ? "reject" : decision === "edit" ? "edit" : "accept") as Decision,
      ticked_safety_steps: [...ticked].sort((a, b) => a - b),
      approver_name: name.trim() || "unnamed",
      note: "",
      edits: decision === "edit" ? edits || null : null,
    };
    try {
      if (isMock) {
        await new Promise((r) => setTimeout(r, 400));
        setResult({ incident_id: incidentId, wo_id: wo.wo_id, status: kind === "approve" ? "APPROVED" : "REJECTED", decided_at: new Date().toISOString(), demo: true, collection: "mock (no server call)" });
      } else {
        setResult(await postApprove(incidentId, body, passcode));
      }
    } catch (e) {
      if (e instanceof ApiError) {
        setError(
          e.status === 409
            ? `Refused (409 ${e.code}): ${e.message}`
            : e.status === 401
              ? "This incident needs the demo passcode (live run). Re-enter it from Run live."
              : `${e.code}: ${e.message}`,
        );
      } else setError("Unexpected error while sending the decision.");
    } finally {
      setBusy(false);
    }
  }

  return { steps, safety, ticked, toggle, name, setName, busy, error, result, decided, missing, allTicked, canApprove, submit };
}
