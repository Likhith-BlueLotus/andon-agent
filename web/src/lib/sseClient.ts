import { API_URL } from "./config";
import { ApiError, toApiError } from "./api";
import { SseParser } from "./sse";
import { EVENT_TYPES, type AndonEvent, type EventType } from "../types/events";

export interface InvestigateParams {
  scenarioId: string;
  mode: "live" | "replay";
  runId?: string | null;
  speed?: number;
  passcode?: string | null;
}

const KNOWN = new Set<string>(EVENT_TYPES);

/** Validate the minimal envelope; unknown event types are ignored (forward compatible). */
export function toEvent(frameEvent: string, data: string): AndonEvent | null {
  let obj: unknown;
  try {
    obj = JSON.parse(data);
  } catch {
    return null;
  }
  if (!obj || typeof obj !== "object") return null;
  const o = obj as Record<string, unknown>;
  const type = (typeof o.type === "string" ? o.type : frameEvent) as EventType;
  if (!KNOWN.has(type) || typeof o.seq !== "number" || typeof o.data !== "object") return null;
  return { ...o, type } as unknown as AndonEvent;
}

/**
 * POST the investigate request and yield contract events as they arrive. Throws ApiError for
 * non-2xx answers (401 passcode, 404 no replay, 429 limits) and a plain Error("stream_closed")
 * when the body ends without a `done` event.
 */
export async function* streamInvestigate(p: InvestigateParams, signal: AbortSignal): AsyncGenerator<AndonEvent> {
  const q = new URLSearchParams({ mode: p.mode });
  if (p.runId) q.set("run_id", p.runId);
  if (p.speed && p.speed > 1) q.set("speed", String(p.speed));
  const headers: Record<string, string> = { Accept: "text/event-stream" };
  if (p.mode === "live" && p.passcode) headers["X-Demo-Passcode"] = p.passcode;
  let res: Response;
  try {
    res = await fetch(`${API_URL}/api/incidents/${encodeURIComponent(p.scenarioId)}/investigate?${q}`, {
      method: "POST",
      headers,
      signal,
    });
  } catch (e) {
    if ((e as Error).name === "AbortError") throw e;
    throw new ApiError(0, "network", "Cannot reach the API");
  }
  if (!res.ok) throw await toApiError(res);
  if (!res.body) throw new ApiError(0, "no_stream", "The browser cannot stream this response");
  const reader = res.body.getReader();
  const dec = new TextDecoder();
  const parser = new SseParser();
  let sawDone = false;
  try {
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      for (const f of parser.push(dec.decode(value, { stream: true })).frames) {
        const ev = toEvent(f.event, f.data);
        if (!ev) continue;
        if (ev.type === "done") sawDone = true;
        yield ev;
      }
    }
  } finally {
    reader.cancel().catch(() => undefined);
  }
  if (!sawDone) throw new Error("stream_closed");
}
