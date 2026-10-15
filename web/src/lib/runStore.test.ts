import { describe, expect, it } from "vitest";
import { getRun, publishRun, resetRun } from "./runStore";

describe("runStore", () => {
  it("resetRun drops a stale 'Investigating' lamp once the console (and its stream) is gone", () => {
    publishRun({ tone: "running", text: "Investigating", steps: [], scenario: "R002" });
    resetRun();
    expect(getRun()).toEqual({ tone: "idle", text: "Line stopped · awaiting investigation", steps: null, scenario: null });
  });
});
