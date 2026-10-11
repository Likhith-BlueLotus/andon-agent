import { describe, expect, it } from "vitest";
import fixtureRaw from "../../../tests/fixtures/sample_stream.jsonl?raw";
import { parseJsonl } from "../lib/mock";
import { claimState, initialState, reduce, reduceAll } from "./reducer";
import { EVENT_TYPES, type AndonEvent } from "../types/events";

const events: AndonEvent[] = parseJsonl(fixtureRaw);

describe("fixture", () => {
  it("covers all but a few event types and only known types", () => {
    const types = new Set(events.map((e) => e.type));
    for (const t of types) expect(EVENT_TYPES).toContain(t);
    expect(types.has("rca_final")).toBe(true);
  });
});

describe("reduce over sample_stream.jsonl", () => {
  const final = reduceAll(events);

  it("finishes done with the incident metadata", () => {
    expect(final.phase).toBe("done");
    expect(final.scenarioId).toBe("R002");
    expect(final.stoppedStation).toBe("ST30");
    expect(final.mode).toBe("replay");
    expect(final.done?.duration_ms).toBe(33650);
    expect(final.lastSeq).toBe(events[events.length - 1].seq);
  });

  it("builds lanes per agent with their model ids", () => {
    const names = final.lanes.map((l) => l.agent);
    expect(names).toEqual(expect.arrayContaining(["commander", "signal_analyst", "evidence_librarian", "rca_judge", "verifier", "action_drafter"]));
    expect(final.lanes.find((l) => l.agent === "commander")?.modelId).toBe("gemini-3.8-flash");
    expect(final.lanes.every((l) => l.status === "finished")).toBe(true);
  });

  it("resolves every tool call with evidence and provenance", () => {
    const calls = events.filter((e) => e.type === "tool_call").length;
    expect(final.toolOrder).toHaveLength(calls);
    for (const id of final.toolOrder) expect(final.tools[id].status).toBe("done");
    const real = final.tools["c7"];
    expect(real.evidenceId).toBe("ev_query_telemetry_2");
    expect(real.provenance[0]).toMatchObject({ source_id: "metropt3", real: true });
    expect(final.tools["c1"].provenance[0].real).toBe(false);
  });

  it("records cache hit and model fallback inline in the lane", () => {
    expect(final.cacheSavedUsd).toBeCloseTo(0.0413);
    expect(final.fallbacks).toEqual([{ from_model: "gemini-3.1-pro-preview", to_model: "gemini-3.8-flash", reason: "429" }]);
    const judge = final.lanes.find((l) => l.agent === "rca_judge");
    expect(judge?.items.some((i) => i.kind === "fallback")).toBe(true);
  });

  it("keeps the first rejected claim in the revision history and ends verified", () => {
    expect(final.revisions).toHaveLength(1);
    expect(final.revisions[0].iteration).toBe(1);
    expect(final.revisions[0].rejected[0].claim.claim_id).toBe("cl1");
    expect(final.revisions[0].rejected[0].claim.text).toContain("18%");
    expect(final.revisions[0].rejected[0].verdict.measured_value).toBe(-14.0);
    expect(final.verifier).toMatchObject({ iteration: 2, overall: "PASS", revising: false });
    expect(final.final?.status).toBe("verified");
    for (const c of final.final!.hypotheses[0].claims) expect(claimState(final.verdicts, c.claim_id)).toBe("verified");
  });

  it("announces the verified root cause and the rejected claim", () => {
    const texts = final.announcements.map((a) => a.text);
    expect(texts.some((t) => t.startsWith("Claim rejected: UT-AIR header pressure fell 18%"))).toBe(true);
    expect(texts.some((t) => t.startsWith("Verified root cause: air pressure drop at UT-AIR"))).toBe(true);
  });

  it("holds the draft work order with safety steps and a cost", () => {
    expect(final.workOrder?.status).toBe("PENDING_APPROVAL");
    expect(final.workOrder?.steps.some((s) => s.is_safety && s.citation)).toBe(true);
    expect(final.cost?.usd).toBe(0.1312);
    expect(final.planDone).toBe(final.plan?.length);
  });
});

describe("reduce, partial streams", () => {
  it("shows FAIL as revising until the next hypotheses arrive", () => {
    const upTo = events.filter((e) => e.seq <= 37);
    const s = reduceAll(upTo);
    expect(s.verifier).toMatchObject({ iteration: 1, overall: "FAIL", revising: true });
    expect(claimState(s.verdicts, "cl1")).toBe("rejected");
    expect(claimState(s.verdicts, "cl2")).toBe("verified");
    expect(s.phase).toBe("streaming");
    expect(s.final).toBeNull();
  });

  it("claims are pending before any verdict", () => {
    const s = reduceAll(events.filter((e) => e.seq <= 29));
    expect(s.draft?.hypotheses[0].claims.every((c) => claimState(s.verdicts, c.claim_id) === "pending")).toBe(true);
  });

  it("a tool_call without a result stays running", () => {
    const s = reduceAll(events.filter((e) => e.seq <= 11));
    expect(s.tools["c3"].status).toBe("running");
  });

  it("treats a summary.error as a tool error card and marks retryable errors as retrying", () => {
    const base = reduceAll(events.filter((e) => e.seq <= 11));
    const withErr = reduce(base, {
      type: "tool_result", incident_id: "x", seq: 12, ts: "t", agent: "signal_analyst",
      data: { call_id: "c3", evidence_id: "", summary: { error: { code: "audio_unavailable", message: "no audio" } }, provenance: [], latency_ms: 3 },
    });
    expect(withErr.tools["c3"].status).toBe("error");
    expect(withErr.tools["c3"].toolError?.code).toBe("audio_unavailable");
    const retrying = reduce(withErr, { type: "error", incident_id: "x", seq: 13, ts: "t", agent: null, data: { code: "x", message: "m", retryable: true } });
    expect(retrying.errors[0].retrying).toBe(true);
    const after = reduce(retrying, { type: "agent_finished", incident_id: "x", seq: 14, ts: "t", agent: "signal_analyst", data: { agent: "signal_analyst", model_id: null } });
    expect(after.errors[0].retrying).toBe(false);
  });

  it("handles insufficient_evidence without dropping hypotheses", () => {
    const s = reduceAll(events.map((e) => (e.type === "rca_final" ? { ...e, data: { ...e.data, status: "insufficient_evidence" as const } } : e)));
    expect(s.final?.status).toBe("insufficient_evidence");
    expect(s.announcements.at(-1)?.text).toMatch(/^Insufficient evidence|^Verified root cause|Draft work order/);
  });

  it("reset returns to idle", () => {
    expect(reduce(reduceAll(events), { type: "reset" })).toEqual(initialState);
  });
});
