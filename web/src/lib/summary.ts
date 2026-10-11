import { fmtNum, fmtTime } from "./format";

type Obj = Record<string, unknown>;
const isObj = (v: unknown): v is Obj => !!v && typeof v === "object" && !Array.isArray(v);
const num = (v: unknown): number | null => (typeof v === "number" && Number.isFinite(v) ? v : null);

/** Per-tag statistic blocks. Real runs nest them under `tags`; the fixture puts them at top level. */
export function tagStats(summary: Obj): Record<string, Obj> {
  const src = isObj(summary.tags) ? (summary.tags as Obj) : summary;
  const out: Record<string, Obj> = {};
  for (const [k, v] of Object.entries(src)) {
    if (k === "data_quality" || !isObj(v)) continue;
    if ("mean" in v || "n" in v) out[k] = v;
  }
  return out;
}

/** A one-line, tool-aware headline for a tool result. Falls back to scalar keys. */
export function briefSummary(tool: string, summary: Obj): string {
  const stats = tagStats(summary);
  const tags = Object.keys(stats);
  if (tags.length) {
    return tags
      .slice(0, 4)
      .map((t) => {
        const s = stats[t];
        const unit = typeof s.unit === "string" ? ` ${s.unit}` : "";
        const m = num(s.mean);
        return m == null ? t : `${t} μ ${fmtNum(m)}${unit}`;
      })
      .join(" · ");
  }
  if (Array.isArray(summary.change_points)) {
    const cps = summary.change_points as Obj[];
    if (cps.length === 0) return `${summary.tag ?? "signal"}: no change point`;
    const c = cps[0];
    const mag = num(c.magnitude_pct);
    return `${cps.length} change point${cps.length > 1 ? "s" : ""} · first ${fmtTime(String(c.ts))}${mag != null ? ` · ${mag > 0 ? "+" : ""}${mag}%` : ""}`;
  }
  if (tool === "search_alarms" && num(summary.count) != null) {
    const by = isObj(summary.by_station) ? Object.entries(summary.by_station as Obj).sort((a, b) => Number(b[1]) - Number(a[1]))[0] : null;
    return `${summary.count} alarms${by ? ` · most at ${by[0]} (${by[1]})` : ""}`;
  }
  if (Array.isArray(summary.citations)) {
    const c = summary.citations as Obj[];
    return `${c.length} manual citation${c.length === 1 ? "" : "s"}${c[0] ? ` · ${c[0].doc} p.${c[0].page}` : ""}`;
  }
  if (Array.isArray(summary.assets)) return `${(summary.assets as unknown[]).length} assets`;
  if (Array.isArray(summary.rows)) return `${summary.count ?? (summary.rows as unknown[]).length} row${summary.count === 1 ? "" : "s"}${summary.truncated ? " (truncated)" : ""}`;
  const parts: string[] = [];
  for (const [k, v] of Object.entries(summary)) {
    if (typeof v === "string" || typeof v === "number" || typeof v === "boolean") parts.push(`${k} ${v}`);
    if (parts.length >= 4) break;
  }
  return parts.join(" · ") || "ok";
}

/** Data-quality observations the agent saw, as short grey lines. */
export function qualityNotes(summary: Obj): string[] {
  const notes: string[] = [];
  const blocks: [string | null, Obj][] = [];
  if (isObj(summary.data_quality)) blocks.push([null, summary.data_quality as Obj]);
  for (const [tag, s] of Object.entries(tagStats(summary))) if (isObj(s.data_quality)) blocks.push([tag, s.data_quality as Obj]);
  const seen = new Set<string>();
  for (const [tag, q] of blocks) {
    const pre = tag ? `${tag}: ` : "";
    const miss = num(q.missing_pct);
    if (miss != null && miss > 0) notes.push(`${pre}${miss}% samples missing`);
    const gaps = Array.isArray(q.gaps) ? (q.gaps as Obj[]) : [];
    const gapTotal = num(q.gap_total_s);
    if (gaps.length) {
      const g = gaps[0];
      notes.push(`${pre}${gaps.length} gap${gaps.length > 1 ? "s" : ""}${gapTotal ? `, ${fmtNum(gapTotal)} s total` : g.duration_s ? `, ${g.duration_s} s` : ""}${g.start ? ` from ${fmtTime(String(g.start))}` : ""}`);
    }
    const stuck = Array.isArray(q.stuck_periods) ? (q.stuck_periods as unknown[]) : [];
    if (stuck.length) notes.push(`${pre}${stuck.length} stuck-value period${stuck.length > 1 ? "s" : ""}`);
  }
  // Notes the tool itself raised.
  if (summary.truncated === true) notes.push("result truncated; older rows not shown");
  if (Array.isArray(summary.possible_duplicates) && summary.possible_duplicates.length) notes.push(`${summary.possible_duplicates.length} possible duplicate record${summary.possible_duplicates.length > 1 ? "s" : ""}`);
  if (Array.isArray(summary.chatter)) for (const c of summary.chatter as Obj[]) notes.push(`alarm chatter: ${c.code} x${c.repeats} within ${c.within_s} s`);
  if (summary.changeover_excluded === true) notes.push("changeover windows excluded from change-point search");
  if (typeof summary.status === "string" && summary.status !== "ok") notes.push(`status: ${summary.status}`);
  return notes.filter((n) => (seen.has(n) ? false : (seen.add(n), true)));
}

/** Assets mentioned in a tool call's args (for the mimic highlight). */
export function assetsInArgs(args: Obj): string[] {
  const out: string[] = [];
  for (const k of ["asset_id", "upstream_of", "station", "asset"]) if (typeof args[k] === "string") out.push(args[k] as string);
  return out;
}

export function argsLine(args: Obj): string {
  const parts: string[] = [];
  for (const [k, v] of Object.entries(args)) {
    if (v == null) continue;
    const val = Array.isArray(v) ? `[${v.length}]` : typeof v === "string" ? (/^\d{4}-\d\d-\d\dT/.test(v) ? fmtTime(v) : v) : String(v);
    parts.push(`${k}=${val.length > 28 ? val.slice(0, 27) + "…" : val}`);
  }
  return parts.join(" ");
}

/** Query shape for the telemetry endpoint, when a tool call carries one. */
export function telemetryQuery(tool: string, args: Obj): { asset_id: string; tags: string[]; t0: string; t1: string } | null {
  if (typeof args.asset_id !== "string" || typeof args.t0 !== "string" || typeof args.t1 !== "string") return null;
  let tags: string[] = [];
  if (Array.isArray(args.tags)) tags = args.tags.filter((t): t is string => typeof t === "string");
  else if (typeof args.tag === "string") tags = [args.tag];
  if (!tags.length) return null;
  if (tool !== "query_telemetry" && tool !== "detect_change_points") return null;
  return { asset_id: args.asset_id, tags, t0: args.t0, t1: args.t1 };
}
