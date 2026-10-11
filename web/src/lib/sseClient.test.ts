import { afterEach, describe, expect, it, vi } from "vitest";
import { streamInvestigate } from "./sseClient";
import { FIXTURE_EVENTS } from "./mock";
import { reduceAll } from "../state/reducer";
import type { AndonEvent } from "../types/events";

function sseBody(events: AndonEvent[], chunkSize: number): ReadableStream<Uint8Array> {
  const text = ": ping\n\n" + events.map((e) => `id: ${e.seq}\nevent: ${e.type}\ndata: ${JSON.stringify(e)}\n\n`).join("");
  const bytes = new TextEncoder().encode(text);
  let i = 0;
  return new ReadableStream({
    pull(c) {
      if (i >= bytes.length) return c.close();
      c.enqueue(bytes.slice(i, i + chunkSize));
      i += chunkSize;
    },
  });
}

async function collect(it: AsyncIterable<AndonEvent>) {
  const out: AndonEvent[] = [];
  for await (const e of it) out.push(e);
  return out;
}

afterEach(() => vi.unstubAllGlobals());

describe("streamInvestigate", () => {
  it("rebuilds the exact event list from odd-sized byte chunks (even mid-UTF-8) and ignores pings", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(sseBody(FIXTURE_EVENTS, 37), { status: 200 })));
    const got = await collect(streamInvestigate({ scenarioId: "R002", mode: "replay", runId: "r002-cloud-1", speed: 2 }, new AbortController().signal));
    expect(got).toEqual(FIXTURE_EVENTS);
    expect(reduceAll(got).phase).toBe("done");
    const [url, init] = (fetch as unknown as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(String(url)).toContain("/api/incidents/R002/investigate?mode=replay&run_id=r002-cloud-1&speed=2");
    expect(init.method).toBe("POST");
    expect(init.headers["X-Demo-Passcode"]).toBeUndefined();
  });

  it("sends the passcode only for live runs, as a header", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(sseBody(FIXTURE_EVENTS.slice(-1), 100), { status: 200 })));
    await collect(streamInvestigate({ scenarioId: "R002", mode: "live", passcode: "pw" }, new AbortController().signal));
    const [url, init] = (fetch as unknown as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(String(url)).not.toContain("pw");
    expect(init.headers["X-Demo-Passcode"]).toBe("pw");
  });

  it("maps a 401 body to an ApiError with the server's code", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: { code: "passcode_required", message: "nope" } }), { status: 401 })));
    await expect(collect(streamInvestigate({ scenarioId: "R002", mode: "live", passcode: "x" }, new AbortController().signal))).rejects.toMatchObject({ status: 401, code: "passcode_required" });
  });

  it("throws stream_closed when the body ends before `done`", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(sseBody(FIXTURE_EVENTS.slice(0, 5), 64), { status: 200 })));
    await expect(collect(streamInvestigate({ scenarioId: "R002", mode: "replay" }, new AbortController().signal))).rejects.toThrow("stream_closed");
  });
});
