// CONTRACT — mirrors api/events.py and agents/schemas.py (CONTRACT_VERSION below).
// tests/test_contracts.py checks that event types, cause classes and the version stay in sync.
// Change only with both humans' OK.

export const CONTRACT_VERSION = "1.0.0";

export type CauseClass =
  | "weld_tip_wear"
  | "sealer_pump_cavitation"
  | "conveyor_bearing_defect"
  | "servo_overheat"
  | "air_pressure_drop"
  | "sensor_drift"
  | "plc_timer_misconfig"
  | "coolant_blockage"
  | "fixture_misalignment"
  | "changeover_error"
  | "hydraulic_degradation"
  | "no_fault";

export interface ProvenanceRef {
  source_id: string;
  real: boolean;
  source_ref: string | null;
}

export interface Citation {
  doc: string;
  page: number;
  quote: string;
}

export type ClaimKind = "numeric" | "temporal" | "citation" | "causal_order" | "qualitative";

export interface Claim {
  claim_id: string;
  text: string;
  kind: ClaimKind;
  evidence_ids: string[];
  asserted_value: number | null;
  asserted_ts: string | null; // ISO 8601
  citation: Citation | null;
}

export interface Hypothesis {
  cause_class: CauseClass;
  asset_id: string;
  confidence: number; // 0..1
  causal_chain: string[];
  claims: Claim[];
  refuting_evidence_ids: string[];
  next_check: string | null;
}

export interface RCAReport {
  incident_id: string;
  hypotheses: Hypothesis[]; // ranked, max 3
  status: "verified" | "insufficient_evidence";
}

export interface ClaimVerdict {
  claim_id: string;
  verdict: "pass" | "fail" | "unverifiable";
  reason: string;
  measured_value: number | null;
}

export interface VerifierVerdict {
  overall: "PASS" | "FAIL";
  claims: ClaimVerdict[];
  iteration: number;
}

export interface WorkOrderStep {
  order: number;
  text: string;
  is_safety: boolean;
  citation: Citation | null;
}

export interface WorkOrder {
  wo_id: string;
  incident_id: string;
  asset_id: string;
  cause_class: CauseClass;
  steps: WorkOrderStep[];
  parts: string[];
  status: "PENDING_APPROVAL" | "APPROVED" | "REJECTED";
}

export interface IncidentStartedData {
  scenario_id: string;
  line_id: string;
  stopped_station: string;
  mode: "live" | "replay";
}
export interface PlanData {
  steps: string[];
}
export interface AgentData {
  agent: string;
  model_id: string | null;
}
export interface ToolCallData {
  call_id: string;
  tool: string;
  args: Record<string, unknown>;
}
export interface ToolResultData {
  call_id: string;
  evidence_id: string;
  summary: Record<string, unknown>;
  provenance: ProvenanceRef[];
  latency_ms: number;
}
export interface CacheHitData {
  cache_name: string;
  cached_tokens: number;
  saved_usd: number;
}
export interface ModelFallbackData {
  from_model: string;
  to_model: string;
  reason: string;
}
export interface CostData {
  input_tokens: number;
  output_tokens: number;
  cached_tokens: number;
  usd: number;
  by_model: Record<string, number>;
}
export interface ErrorData {
  code: string;
  message: string;
  retryable: boolean;
}
export interface DoneData {
  duration_ms: number;
}

interface Envelope<T extends string, D> {
  type: T;
  incident_id: string;
  seq: number;
  ts: string; // ISO 8601
  agent: string | null;
  data: D;
}

export type AndonEvent =
  | Envelope<"incident_started", IncidentStartedData>
  | Envelope<"plan", PlanData>
  | Envelope<"agent_started", AgentData>
  | Envelope<"agent_finished", AgentData>
  | Envelope<"tool_call", ToolCallData>
  | Envelope<"tool_result", ToolResultData>
  | Envelope<"cache_hit", CacheHitData>
  | Envelope<"hypotheses", RCAReport>
  | Envelope<"claim_verdict", ClaimVerdict>
  | Envelope<"verifier_verdict", VerifierVerdict>
  | Envelope<"model_fallback", ModelFallbackData>
  | Envelope<"rca_final", RCAReport>
  | Envelope<"work_order_draft", WorkOrder>
  | Envelope<"cost", CostData>
  | Envelope<"error", ErrorData>
  | Envelope<"done", DoneData>;

export type EventType = AndonEvent["type"];

export const EVENT_TYPES: readonly EventType[] = [
  "incident_started",
  "plan",
  "agent_started",
  "agent_finished",
  "tool_call",
  "tool_result",
  "cache_hit",
  "hypotheses",
  "claim_verdict",
  "verifier_verdict",
  "model_fallback",
  "rca_final",
  "work_order_draft",
  "cost",
  "error",
  "done",
] as const;
