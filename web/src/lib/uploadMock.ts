import type { ConfirmRequest, ConfirmResponse, UploadProposal } from "../types/upload";

const cols = ["Timestamp", "Compressor_Amps", "Header_P_bar", "Gun_Air_ST20", "Gun_Air_ST30", "Operator_Note"];
const t = (i: number) => new Date(Date.UTC(2026, 9, 11, 8, i * 5)).toISOString().replace(".000Z", "Z");
const rows = Array.from({ length: 10 }, (_, i) => ({
  Timestamp: t(i),
  Compressor_Amps: Number((41.2 + i * 0.35).toFixed(2)),
  Header_P_bar: Number((7.8 - i * 0.06).toFixed(2)),
  Gun_Air_ST20: Number((6.1 - i * 0.04).toFixed(2)),
  Gun_Air_ST30: Number((6.2 - i * 0.01).toFixed(2)),
  Operator_Note: i === 4 ? "hissing near ST20" : null,
}));

export function MOCK_PROPOSAL(filename: string, heuristic: boolean): UploadProposal {
  const r = (s: string) => (heuristic ? "heuristic" : s);
  return {
    upload_id: "up_mock_01",
    filename,
    n_rows: 2880,
    columns: [
      { name: cols[0], dtype: "time", sample: rows.slice(0, 3).map((x) => x.Timestamp) },
      { name: cols[1], dtype: "number", sample: [41.2, 41.55, 41.9] },
      { name: cols[2], dtype: "number", sample: [7.8, 7.74, 7.68] },
      { name: cols[3], dtype: "number", sample: [6.1, 6.06, 6.02] },
      { name: cols[4], dtype: "number", sample: [6.2, 6.19, 6.18] },
      { name: cols[5], dtype: "text", sample: ["hissing near ST20"] },
    ],
    preview: rows,
    proposed: {
      timestamp_column: "Timestamp",
      columns: [
        { column: "Compressor_Amps", asset_id: "UT-AIR", tag: "motor_current", unit: "A", scale: 1, confidence: heuristic ? 0.4 : 0.93, reason: r("Amps on a compressor maps to motor current.") },
        { column: "Header_P_bar", asset_id: "UT-AIR", tag: "header_pressure", unit: "bar", scale: 1, confidence: heuristic ? 0.4 : 0.88, reason: r("Header pressure in bar.") },
        { column: "Gun_Air_ST20", asset_id: "ST20-WLD", tag: "air_pressure", unit: "bar", scale: 1, confidence: heuristic ? 0.4 : 0.71, reason: r("Gun air at station ST20.") },
        { column: "Gun_Air_ST30", asset_id: "ST30-WLD", tag: "air_pressure", unit: "bar", scale: 1, confidence: heuristic ? 0.4 : 0.42, reason: r("Same pattern as ST20 but the station name is ambiguous.") },
        { column: "Operator_Note", asset_id: null, tag: null, unit: null, scale: 1, confidence: 0.1, reason: r("Free text, not a signal.") },
      ],
    },
    targets: [
      { asset_id: "UT-AIR", name: "Compressed air utility", tags: [
        { tag: "motor_current", unit: "A", normal_lo: 30, normal_hi: 45 },
        { tag: "header_pressure", unit: "bar", normal_lo: 7, normal_hi: 8.5 },
        { tag: "load_ratio", unit: "%", normal_lo: 40, normal_hi: 70 },
      ] },
      { asset_id: "ST20-WLD", name: "Weld A", tags: [
        { tag: "air_pressure", unit: "bar", normal_lo: 5.5, normal_hi: 6.5 },
        { tag: "weld_current", unit: "kA", normal_lo: 8, normal_hi: 12 },
      ] },
      { asset_id: "ST30-WLD", name: "Weld B", tags: [
        { tag: "air_pressure", unit: "bar", normal_lo: 5.5, normal_hi: 6.5 },
        { tag: "weld_current", unit: "kA", normal_lo: 8, normal_hi: 12 },
      ] },
    ],
    cost_usd: 0.0007,
  };
}

export function mockConfirm(b: ConfirmRequest): ConfirmResponse {
  return {
    scenario_id: "U001",
    line_id: "L1",
    stopped_station: b.stopped_station,
    stop_ts: b.stop_ts ?? t(2879),
    n_points: 2880 * b.columns.length,
    t0: t(0),
    t1: t(2879),
    mapped: b.columns.map((c) => ({ asset_id: c.asset_id, tag: c.tag, column: c.column, n: 2880 })),
    provenance_source_id: "user_upload",
  };
}
