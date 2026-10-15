import { describe, expect, it } from "vitest";
import fixtureRaw from "../../../tests/fixtures/sample_stream.jsonl?raw";
import { parseJsonl } from "./mock";
import { initialState, reduceAll } from "../state/reducer";
import type { AndonEvent } from "../types/events";
import { investigationSteps, runStatus } from "./progress";

const events: AndonEvent[] = parseJsonl(fixtureRaw);
const byId = (steps: ReturnType<typeof investigationSteps>) => Object.fromEntries(steps.map((s) => [s.id, s.state]));

describe("investigationSteps", () => {
  it("is all todo before anything streams", () => {
    expect(Object.values(byId(investigationSteps(initialState)))).toEqual(Array(7).fill("todo"));
    expect(runStatus(initialState, null, "idle").tone).toBe("idle");
  });

  it("marks the plan active right after the incident opens", () => {
    const first = events.findIndex((e) => e.type === "plan");
    const s = reduceAll(events.slice(0, first));
    const st = byId(investigationSteps(s, null, "streaming"));
    expect(st.stop).toBe("done");
    expect(st.plan).toBe("active");
    expect(runStatus(s, null, "streaming")).toEqual({ tone: "running", text: "Investigating" });
  });

  it("ends with every machine step done and the human gate waiting", () => {
    const s = reduceAll(events);
    const st = byId(investigationSteps(s, null, "closed"));
    expect(st).toMatchObject({ stop: "done", plan: "done", evidence: "done", hypotheses: "done", verify: "done", workorder: "done", approval: "active" });
    expect(runStatus(s, null, "closed").tone).toBe("verified");
  });

  it("follows the human decision", () => {
    const s = reduceAll(events);
    expect(byId(investigationSteps(s, "APPROVED")).approval).toBe("done");
    expect(byId(investigationSteps(s, "REJECTED")).approval).toBe("fail");
    expect(runStatus(s, "APPROVED", "closed").text).toBe("Work order approved");
  });

  it("flags the active step when the stream drops", () => {
    const mid = events.findIndex((e) => e.type === "tool_call") + 1;
    const s = reduceAll(events.slice(0, mid));
    const steps = investigationSteps(s, null, "dropped");
    expect(steps.some((x) => x.state === "warn" && x.detail === "stream dropped")).toBe(true);
    expect(runStatus(s, null, "dropped").tone).toBe("bad");
  });
});
