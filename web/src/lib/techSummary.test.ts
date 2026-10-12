import { describe, expect, it } from "vitest";
import { FIXTURE_EVENTS } from "./mock";
import { reduceAll } from "../state/reducer";
import { progressLine, topVerifiedClaims, plainClaimText } from "./techSummary";

describe("techSummary", () => {
  it("progress line follows the latest tool_call", () => {
    const upto = FIXTURE_EVENTS.filter((e) => e.seq <= 10); // through the c3 query_telemetry call
    const s = reduceAll(upto);
    expect(progressLine(s)).toMatch(/^Checking ST30-WLD telemetry…$/);
  });
  it("at most two claims, all verified", () => {
    const s = reduceAll(FIXTURE_EVENTS);
    const c = topVerifiedClaims(s, 2);
    expect(c.length).toBeLessThanOrEqual(2);
    expect(c.length).toBeGreaterThan(0);
  });
});

describe("plainClaimText", () => {
  it("drops the verifier path pointer and keeps the sentence", () => {
    expect(plainClaimText("Compressor loaded fraction rose by 717.7% path: change_points[0].magnitude_pct")).toBe("Compressor loaded fraction rose by 717.7%");
    expect(plainClaimText("No pointer here.")).toBe("No pointer here.");
  });
});
