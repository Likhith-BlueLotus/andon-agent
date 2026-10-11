/**
 * The /api/eval/latest schema is not fixed yet (phase 5). This reader accepts the shapes we can
 * reasonably expect and renders what is there instead of guessing missing numbers:
 *   { sets: { S: Rows, R: Rows } }  or  { S: Rows, R: Rows }  or  { results: { S, R } }
 * where Rows is an array of row objects, or an object keyed by system name. A cell is a number,
 * a string, or { value | point | rate, lo | ci_lo | wilson_lo, hi | ci_hi | wilson_hi, n? }.
 */
export interface Cell {
  value: number | null;
  lo: number | null;
  hi: number | null;
  text: string;
}
export interface EvalRow {
  system: string;
  cells: Record<string, Cell>;
}
export interface EvalSet {
  id: string;
  title: string;
  columns: string[];
  rows: EvalRow[];
}
export interface EvalView {
  sets: EvalSet[];
  meta: { label: string; value: string }[];
}

type Obj = Record<string, unknown>;
const isObj = (v: unknown): v is Obj => !!v && typeof v === "object" && !Array.isArray(v);
const numOf = (v: unknown): number | null => (typeof v === "number" && Number.isFinite(v) ? v : null);
const pick = (o: Obj, keys: string[]): number | null => {
  for (const k of keys) {
    const n = numOf(o[k]);
    if (n != null) return n;
  }
  return null;
};

export function toCell(v: unknown): Cell {
  if (isObj(v)) {
    const value = pick(v, ["value", "point", "rate", "mean", "estimate"]);
    const ci = Array.isArray(v.ci) ? (v.ci as unknown[]) : Array.isArray(v.wilson) ? (v.wilson as unknown[]) : null;
    const lo = pick(v, ["lo", "ci_lo", "wilson_lo", "low", "lower"]) ?? (ci ? numOf(ci[0]) : null);
    const hi = pick(v, ["hi", "ci_hi", "wilson_hi", "high", "upper"]) ?? (ci ? numOf(ci[1]) : null);
    const text = value == null ? "n/a" : lo != null && hi != null ? `${fmt(value)} [${fmt(lo)}, ${fmt(hi)}]` : fmt(value);
    return { value, lo, hi, text };
  }
  const n = numOf(v);
  if (n != null) return { value: n, lo: null, hi: null, text: fmt(n) };
  return { value: null, lo: null, hi: null, text: v == null ? "n/a" : String(v) };
}
const fmt = (n: number) => (Number.isInteger(n) ? String(n) : n.toFixed(2));

function rowsOf(v: unknown): EvalRow[] {
  const toRow = (system: string, o: Obj): EvalRow => {
    const cells: Record<string, Cell> = {};
    for (const [k, x] of Object.entries(o)) if (k !== "system" && k !== "name" && k !== "id") cells[k] = toCell(x);
    return { system, cells };
  };
  if (Array.isArray(v)) return v.filter(isObj).map((o, i) => toRow(String(o.system ?? o.name ?? o.id ?? `row ${i + 1}`), o));
  if (isObj(v)) return Object.entries(v).filter(([, o]) => isObj(o)).map(([k, o]) => toRow(k, o as Obj));
  return [];
}

export function readEval(raw: unknown): EvalView | null {
  if (!isObj(raw)) return null;
  const container = isObj(raw.sets) ? raw.sets : isObj(raw.results) ? raw.results : raw;
  const sets: EvalSet[] = [];
  for (const [id, title] of [["S", "S-set · synthetic line"], ["R", "R-set · real signals on the synthetic line"]] as const) {
    const key = Object.keys(container).find((k) => k.toLowerCase() === id.toLowerCase() || k.toLowerCase() === `${id.toLowerCase()}_set` || k.toLowerCase() === `${id.toLowerCase()}-set`);
    if (!key) continue;
    const rows = rowsOf(container[key]);
    const columns = [...new Set(rows.flatMap((r) => Object.keys(r.cells)))];
    sets.push({ id, title, columns, rows });
  }
  const meta: { label: string; value: string }[] = [];
  for (const [k, v] of Object.entries(raw)) if (typeof v === "string" || typeof v === "number") meta.push({ label: k.replace(/_/g, " "), value: String(v) });
  return sets.length ? { sets, meta } : null;
}

export const MOCK_EVAL = {
  run_id: "mock-eval",
  generated_at: "2026-10-11T12:00:00Z",
  note: "Mock data for ?mock=1. Not a result.",
  sets: {
    S: [
      { system: "S1 full pipeline", n: 60, top1: { value: 0.83, lo: 0.72, hi: 0.91 }, evidence_grounded: { value: 0.96, lo: 0.88, hi: 0.99 } },
      { system: "B1 single prompt", n: 60, top1: { value: 0.55, lo: 0.42, hi: 0.67 }, evidence_grounded: { value: 0.61, lo: 0.48, hi: 0.72 } },
    ],
    R: [
      { system: "S1 full pipeline", n: 17, top1: { value: 0.76, lo: 0.53, hi: 0.9 }, evidence_grounded: { value: 0.94, lo: 0.74, hi: 0.99 } },
      { system: "B1 single prompt", n: 17, top1: { value: 0.47, lo: 0.26, hi: 0.69 }, evidence_grounded: { value: 0.53, lo: 0.31, hi: 0.74 } },
    ],
  },
};
