import { describe, expect, it } from "vitest";
import { argsLine, briefSummary, qualityNotes, telemetryQuery, tagStats } from "./summary";
import { FIXTURE_EVENTS } from "./mock";
import { readEval, MOCK_EVAL } from "./evalData";

const result = (id: string) => {
  const e = FIXTURE_EVENTS.find((x) => x.type === "tool_result" && x.data.evidence_id === id);
  if (!e || e.type !== "tool_result") throw new Error(id);
  return e.data.summary;
};

describe("summary helpers on fixture summaries", () => {
  it("reads gaps and missing percentage from the fixture's query_telemetry data_quality", () => {
    const notes = qualityNotes(result("ev_query_telemetry_1"));
    expect(notes).toContain("1% samples missing");
    expect(notes.some((n) => n.startsWith("1 gap, 48 s from 07:15:02Z"))).toBe(true);
  });

  it("reads per-tag data quality in the real nested shape", () => {
    const s = { tags: { a: { mean: 1, n: 3, data_quality: { missing_pct: 2.5, gaps: [{ start: "2026-01-01T00:00:00Z", duration_s: 9 }], stuck_periods: [[1, 2]] } } } };
    const notes = qualityNotes(s);
    expect(notes).toEqual(expect.arrayContaining(["a: 2.5% samples missing", "a: 1 gap, 9 s from 00:00:00Z", "a: 1 stuck-value period"]));
    expect(Object.keys(tagStats(s))).toEqual(["a"]);
  });

  it("surfaces alarm chatter and truncation", () => {
    expect(qualityNotes(result("ev_search_alarms_1"))).toContain("alarm chatter: A-ST20-AIR-LO x6 within 50 s");
    expect(qualityNotes({ truncated: true })).toContain("result truncated; older rows not shown");
  });

  it("writes tool-aware headlines", () => {
    expect(briefSummary("query_telemetry", result("ev_query_telemetry_1"))).toMatch(/air_pressure_bar μ 5.71/);
    expect(briefSummary("detect_change_points", result("ev_detect_change_points_1"))).toMatch(/1 change point · first 07:58:20Z · -14%/);
    expect(briefSummary("search_alarms", result("ev_search_alarms_1"))).toMatch(/23 alarms · most at ST30 \(11\)/);
    expect(briefSummary("cite_manual", result("ev_cite_manual_1"))).toMatch(/citations? · compressed_air p\.15/);
  });

  it("builds a telemetry query from query_telemetry and detect_change_points args only", () => {
    const a = { asset_id: "UT-AIR", tags: ["x", "y"], t0: "2026-01-01T00:00:00Z", t1: "2026-01-01T01:00:00Z" };
    expect(telemetryQuery("query_telemetry", a)).toEqual(a);
    expect(telemetryQuery("detect_change_points", { asset_id: "UT-AIR", tag: "x", t0: a.t0, t1: a.t1 })?.tags).toEqual(["x"]);
    expect(telemetryQuery("search_alarms", { line_id: "L1", t0: a.t0, t1: a.t1 })).toBeNull();
    expect(argsLine({ asset_id: "UT-AIR", tags: ["a", "b"], t0: a.t0 })).toBe("asset_id=UT-AIR tags=[2] t0=00:00:00Z");
  });
});

describe("readEval", () => {
  it("reads S and R tables with Wilson intervals", () => {
    const v = readEval(MOCK_EVAL)!;
    expect(v.sets.map((s) => s.id)).toEqual(["S", "R"]);
    const top1 = v.sets[0].rows[0].cells.top1;
    expect(top1).toMatchObject({ value: 0.83, lo: 0.72, hi: 0.91 });
    expect(top1.text).toBe("0.83 [0.72, 0.91]");
  });
  it("returns null for unrecognised shapes", () => {
    expect(readEval({ foo: 1 })).toBeNull();
    expect(readEval(null)).toBeNull();
  });
});
