import type { ConfirmRequest, TargetAsset, UploadProposal } from "../types/upload";

/** Heuristic fallback marker: the API sets this as the reason when Flash-Lite was unavailable. */
export const LOW_CONFIDENCE = 0.5;
export const MAX_BYTES = 20 * 1024 * 1024;
export const STATIONS = [
  { id: "ST10-PRS", name: "Press" },
  { id: "ST20-WLD", name: "Weld A" },
  { id: "ST30-WLD", name: "Weld B" },
  { id: "ST40-SLR", name: "Sealer" },
  { id: "ST50-CNV", name: "Conveyor" },
  { id: "ST60-VIS", name: "Vision" },
];

export interface MapRow {
  column: string;
  ignore: boolean;
  asset_id: string;
  tag: string;
  scale: string; // text so the user can type freely
  confidence: number;
  reason: string;
}

export function isHeuristic(p: UploadProposal): boolean {
  return p.proposed.columns.some((c) => c.reason.trim().toLowerCase() === "heuristic");
}

export function checkFile(f: { name: string; size: number }): string | null {
  if (!f.name.toLowerCase().endsWith(".csv")) return "Only .csv files are accepted.";
  if (f.size > MAX_BYTES) return `That file is ${(f.size / 1048576).toFixed(1)} MB; the limit is 20 MB.`;
  if (f.size === 0) return "That file is empty.";
  return null;
}

export function initialTimestamp(p: UploadProposal): string {
  return p.proposed.timestamp_column ?? p.columns.find((c) => c.dtype === "time")?.name ?? "";
}

/** One editable row per CSV column; columns the model left unmapped start as "ignored". */
export function initialRows(p: UploadProposal): MapRow[] {
  const by = new Map(p.proposed.columns.map((c) => [c.column, c]));
  return p.columns.map((col) => {
    const m = by.get(col.name);
    const mapped = !!(m && m.asset_id && m.tag);
    return {
      column: col.name,
      ignore: !mapped,
      asset_id: mapped ? m!.asset_id! : "",
      tag: mapped ? m!.tag! : "",
      scale: String(m?.scale ?? 1),
      confidence: m?.confidence ?? 0,
      reason: m?.reason ?? "",
    };
  });
}

export interface Validation {
  rowErrors: Record<string, string>;
  global: string[];
  mappedCount: number;
  ok: boolean;
}

export function validate(rows: MapRow[], tsColumn: string, targets: TargetAsset[]): Validation {
  const rowErrors: Record<string, string> = {};
  const global: string[] = [];
  if (!tsColumn) global.push("Choose the timestamp column.");
  const active = rows.filter((r) => !r.ignore && r.column !== tsColumn);
  const seen = new Map<string, string>();
  for (const r of active) {
    const asset = targets.find((a) => a.asset_id === r.asset_id);
    if (!r.asset_id || !r.tag) rowErrors[r.column] = "Choose an asset and a tag, or ignore this column.";
    else if (!asset?.tags.some((t) => t.tag === r.tag)) rowErrors[r.column] = "That tag does not exist on this asset.";
    else {
      const s = Number(r.scale);
      if (r.scale.trim() === "" || !Number.isFinite(s) || s === 0) rowErrors[r.column] = "Scale must be a non-zero number.";
      else {
        const key = `${r.asset_id}/${r.tag}`;
        const other = seen.get(key);
        if (other) {
          rowErrors[r.column] = `Duplicate: ${key} is already mapped from "${other}".`;
          rowErrors[other] ??= `Duplicate: ${key} is also mapped from "${r.column}".`;
        } else seen.set(key, r.column);
      }
    }
  }
  const mappedCount = active.length;
  if (mappedCount === 0) global.push("Map at least one column to an asset tag.");
  return { rowErrors, global, mappedCount, ok: global.length === 0 && Object.keys(rowErrors).length === 0 };
}

/** The `datetime-local` value is read as UTC (the label says so). Blank means "last timestamp in the file". */
export function stopTsToIso(v: string): string | null {
  if (!v) return null;
  const d = new Date(v.length === 16 ? `${v}:00Z` : v.endsWith("Z") ? v : `${v}Z`);
  return Number.isNaN(d.getTime()) ? null : d.toISOString();
}

export function buildConfirm(rows: MapRow[], tsColumn: string, station: string, stopLocal: string, stopText: string): ConfirmRequest {
  return {
    timestamp_column: tsColumn,
    columns: rows
      .filter((r) => !r.ignore && r.column !== tsColumn)
      .map((r) => ({ column: r.column, asset_id: r.asset_id, tag: r.tag, scale: Number(r.scale) })),
    stopped_station: station,
    stop_ts: stopTsToIso(stopLocal),
    stop_text: stopText.trim(),
  };
}

/** The console picker needs to know about an ad-hoc upload scenario (it is not in /api/scenarios). Memory only. */
export interface UploadMeta { filename: string; station: string; stop_ts: string }
const uploads = new Map<string, UploadMeta>();
export const rememberUpload = (scenarioId: string, meta: UploadMeta) => void uploads.set(scenarioId, meta);
export const uploadMeta = (scenarioId: string): UploadMeta | null => uploads.get(scenarioId) ?? null;
export const isUploadId = (id: string | null | undefined): boolean => !!id && /^U\d+$/.test(id);
export const uploadLabel = (id: string): string => `${id} · your upload (${uploadMeta(id)?.filename ?? "file"})`;

/** A ScenarioInfo-shaped stand-in so the console can run an uploaded scenario. */
export function adHocScenario(id: string) {
  const m = uploadMeta(id);
  return {
    id,
    title: uploadLabel(id),
    group: "synthetic" as const,
    line_id: "L1",
    stopped_station: m?.station ?? "",
    stop_ts: m?.stop_ts ?? "",
    source_label: "Your upload (USER UPLOAD)",
    real_signal: false,
    replay_run_ids: [] as string[],
  };
}
