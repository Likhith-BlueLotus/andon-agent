import { describe, expect, it } from "vitest";
import { MOCK_PROPOSAL } from "./uploadMock";
import { buildConfirm, checkFile, initialRows, initialTimestamp, isHeuristic, isUploadId, stopTsToIso, validate } from "./uploadMapping";

const p = MOCK_PROPOSAL("upload_air_leak.csv", false);

describe("proposal to editable rows", () => {
  it("maps proposed columns and ignores the unmapped one", () => {
    const rows = initialRows(p);
    expect(initialTimestamp(p)).toBe("Timestamp");
    expect(rows.find((r) => r.column === "Compressor_Amps")).toMatchObject({ ignore: false, asset_id: "UT-AIR", tag: "motor_current" });
    expect(rows.find((r) => r.column === "Operator_Note")?.ignore).toBe(true);
  });
  it("detects the heuristic fallback", () => {
    expect(isHeuristic(p)).toBe(false);
    expect(isHeuristic(MOCK_PROPOSAL("x.csv", true))).toBe(true);
  });
});

describe("validate", () => {
  it("accepts the proposal as it comes", () => {
    expect(validate(initialRows(p), "Timestamp", p.targets).ok).toBe(true);
  });
  it("flags duplicate asset/tag on both columns", () => {
    const rows = initialRows(p).map((r) => (r.column === "Gun_Air_ST30" ? { ...r, asset_id: "ST20-WLD" } : r));
    const v = validate(rows, "Timestamp", p.targets);
    expect(v.ok).toBe(false);
    expect(v.rowErrors.Gun_Air_ST30).toMatch(/Duplicate/);
    expect(v.rowErrors.Gun_Air_ST20).toMatch(/Duplicate/);
  });
  it("requires a timestamp column", () => {
    const v = validate(initialRows(p), "", p.targets);
    expect(v.ok).toBe(false);
    expect(v.global.join(" ")).toMatch(/timestamp/i);
  });
  it("requires at least one mapped column", () => {
    const rows = initialRows(p).map((r) => ({ ...r, ignore: true }));
    expect(validate(rows, "Timestamp", p.targets).global.join(" ")).toMatch(/at least one/i);
  });
  it("flags missing tag and bad scale", () => {
    const rows = initialRows(p).map((r) => (r.column === "Header_P_bar" ? { ...r, tag: "" } : r.column === "Compressor_Amps" ? { ...r, scale: "0" } : r));
    const v = validate(rows, "Timestamp", p.targets);
    expect(v.rowErrors.Header_P_bar).toMatch(/tag/i);
    expect(v.rowErrors.Compressor_Amps).toMatch(/scale/i);
  });
});

describe("buildConfirm", () => {
  it("builds the contract payload without ignored or timestamp columns", () => {
    const b = buildConfirm(initialRows(p), "Timestamp", "ST20-WLD", "2026-10-11T10:30", "  hissing ");
    expect(b).toEqual({
      timestamp_column: "Timestamp",
      columns: [
        { column: "Compressor_Amps", asset_id: "UT-AIR", tag: "motor_current", scale: 1 },
        { column: "Header_P_bar", asset_id: "UT-AIR", tag: "header_pressure", scale: 1 },
        { column: "Gun_Air_ST20", asset_id: "ST20-WLD", tag: "air_pressure", scale: 1 },
        { column: "Gun_Air_ST30", asset_id: "ST30-WLD", tag: "air_pressure", scale: 1 },
      ],
      stopped_station: "ST20-WLD",
      stop_ts: "2026-10-11T10:30:00.000Z",
      stop_text: "hissing",
    });
  });
  it("sends null stop_ts when blank", () => {
    expect(buildConfirm(initialRows(p), "Timestamp", "ST20-WLD", "", "").stop_ts).toBeNull();
    expect(stopTsToIso("")).toBeNull();
  });
});

describe("checkFile", () => {
  it("enforces .csv and 20 MB", () => {
    expect(checkFile({ name: "a.csv", size: 10 })).toBeNull();
    expect(checkFile({ name: "a.xlsx", size: 10 })).toMatch(/csv/i);
    expect(checkFile({ name: "a.csv", size: 21 * 1024 * 1024 })).toMatch(/20 MB/);
  });
});

describe("upload scenario ids", () => {
  it("accepts the ids the API issues (U + 10 base32) and the mock id", () => {
    expect(isUploadId("UK7Q2ZD4MXA")).toBe(true); // shape of api/uploads.py UPLOAD_ID_RE
    expect(isUploadId("U001")).toBe(true);
  });
  it("rejects catalog scenarios and malformed ids", () => {
    for (const id of ["R002", "S014", "U", "Uk7q2zd4mxa", "UK7Q2ZD4MX", "up_e5b01bbc82b9", null]) expect(isUploadId(id)).toBe(false);
  });
});
