/** Shapes of the "bring your own CSV" endpoints (POST /api/uploads, POST /api/uploads/{id}/confirm). */
export type Dtype = "number" | "time" | "text";
export interface UploadColumn {
  name: string;
  dtype: Dtype;
  sample: (string | number | null)[];
}
export interface ProposedColumn {
  column: string;
  asset_id: string | null;
  tag: string | null;
  unit: string | null;
  scale: number;
  confidence: number;
  reason: string;
}
export interface TargetTag {
  tag: string;
  unit: string | null;
  normal_lo: number | null;
  normal_hi: number | null;
}
export interface TargetAsset {
  asset_id: string;
  name: string;
  tags: TargetTag[];
}
export interface UploadProposal {
  upload_id: string;
  filename: string;
  n_rows: number;
  columns: UploadColumn[];
  preview: Record<string, string | number | null>[];
  proposed: { timestamp_column: string | null; columns: ProposedColumn[] };
  targets: TargetAsset[];
  cost_usd: number;
}
export interface ConfirmRequest {
  timestamp_column: string;
  columns: { column: string; asset_id: string; tag: string; scale: number }[];
  stopped_station: string;
  stop_ts: string | null;
  stop_text: string;
}
export interface ConfirmResponse {
  scenario_id: string;
  line_id: string;
  stopped_station: string;
  stop_ts: string;
  n_points: number;
  t0: string;
  t1: string;
  mapped: { asset_id: string; tag: string; column: string; n: number }[];
  provenance_source_id: string;
}
