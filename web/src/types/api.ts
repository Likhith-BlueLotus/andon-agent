/** Shapes of the REST (non-SSE) endpoints, as observed from api/routes.py and api/catalog.py. */
export interface ScenarioInfo {
  id: string;
  title: string;
  group: "synthetic" | "real_signal";
  line_id: string;
  stopped_station: string;
  stop_ts: string;
  source_label: string;
  real_signal: boolean;
  replay_run_ids: string[];
}
export interface ScenarioGroup {
  id: string;
  title: string;
  scenarios: ScenarioInfo[];
}
export interface ScenariosResponse {
  badge: string;
  groups: ScenarioGroup[];
}
export interface ReplayInfo {
  run_id: string;
  scenario_id: string;
  label: string;
  recorded_at: string;
  duration_s: number;
  cost_usd: number;
  final_status: string;
  verifier_rejections: number;
  has_work_order: boolean;
  source: string;
}
export interface ApiConfig {
  theme: string;
  version: string;
  contract_version: string;
  badge: string;
  modes: { replay: boolean; live: boolean; live_requires_passcode: boolean };
  budget: { daily_usd: number; remaining_usd: number; exhausted: boolean };
  limits: { live_runs_per_day: number; live_runs_per_min_per_ip: number };
  replays_available: number;
  /** Not in the contract yet: stretch feature flags, if the API ever reports them (see lib/features.ts). */
  stretch?: unknown;
  features?: unknown;
}
export interface SourceDataset {
  id: string;
  name: string;
  page: string;
  licence: string;
  maps_to: string;
  downloaded?: string;
  citation: string;
}
export interface SourcesResponse {
  note: string;
  badge: string;
  datasets: SourceDataset[];
}
export interface ApproveRequest {
  decision: "approve" | "reject";
  rca_decision: "accept" | "edit" | "reject";
  ticked_safety_steps: number[];
  approver_name: string;
  note?: string;
  edits?: string | null;
}
export interface ApproveResponse {
  incident_id: string;
  wo_id: string;
  status: "APPROVED" | "REJECTED" | "PENDING_APPROVAL";
  decided_at: string;
  demo: boolean;
  collection: string;
}
/** GET /api/scenarios/{id}/telemetry (backend in progress; shape agreed with the coordinator). */
export interface TelemetryResponse {
  scenario_id: string;
  asset_id: string;
  t0: string;
  t1: string;
  series: { tag: string; unit: string | null; points: [string, number | null][] }[];
  provenance: { source_id: string; real: boolean; source_ref: string | null }[];
  downsampled: boolean;
}
