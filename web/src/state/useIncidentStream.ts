import { useCallback, useEffect, useReducer, useRef, useState } from "react";
import type { AndonEvent } from "../types/events";
import { ApiError } from "../lib/api";
import { readMock, type MockVariant } from "../lib/config";
import { mockEvents, playEvents } from "../lib/mock";
import { streamInvestigate } from "../lib/sseClient";
import { initialState, reduce } from "./reducer";

export type Connection =
  | "idle"
  | "connecting"
  | "streaming"
  | "reconnecting" // one automatic retry (replay only)
  | "dropped" // stream lost and not recoverable: offer a replay
  | "closed" // clean end after `done`
  | "failed"; // HTTP-level refusal (see httpError)

export interface StartOptions {
  runId?: string | null;
  speed?: number;
  passcode?: string | null;
  /** mock mode only: play this variant instead of the one in the URL (used by the budget fallback) */
  mockVariant?: MockVariant;
}

export interface HttpProblem {
  status: number;
  code: string;
  message: string;
  retryAfter: number | null;
}

/**
 * useIncidentStream(scenarioId, mode): POST-SSE client + pure reducer.
 * - `start()` opens the stream (fetch + ReadableStream; EventSource cannot POST).
 * - `abort()` cancels via AbortController.
 * - A dropped replay stream is retried once ("reconnecting"); a dropped live stream is NOT re-run
 *   (that would start a second paid run: the API has no resume), the UI offers a replay instead.
 */
export function useIncidentStream(scenarioId: string | null, mode: "live" | "replay") {
  const [state, dispatch] = useReducer(reduce, initialState);
  const [conn, setConn] = useState<Connection>("idle");
  const [httpError, setHttpError] = useState<HttpProblem | null>(null);
  const ctl = useRef<AbortController | null>(null);
  const mock = useRef<MockVariant | null>(readMock());

  const abort = useCallback(() => {
    ctl.current?.abort();
    ctl.current = null;
  }, []);

  useEffect(() => abort, [abort]);

  const start = useCallback(
    async (opts: StartOptions = {}) => {
      if (!scenarioId) return;
      abort();
      const ac = new AbortController();
      ctl.current = ac;
      dispatch({ type: "reset" });
      setHttpError(null);
      setConn("connecting");
      const variant = mock.current ? (opts.mockVariant ?? mock.current) : null;
      const maxAttempts = mode === "replay" ? 2 : 1;

      for (let attempt = 1; attempt <= maxAttempts; attempt++) {
        try {
          const source: AsyncIterable<AndonEvent> = variant
            ? playEvents(mockEvents(variant), ac.signal, 6, 700, variant === "drop" && attempt === 1 ? 24 : undefined)
            : streamInvestigate({ scenarioId, mode, runId: opts.runId, speed: opts.speed, passcode: opts.passcode }, ac.signal);
          let first = attempt > 1;
          for await (const ev of source) {
            if (ac.signal.aborted) return;
            if (first) {
              dispatch({ type: "reset" }); // keep the partial trace on screen until the retry delivers
              first = false;
            }
            setConn("streaming");
            dispatch(ev);
            if (ev.type === "done") {
              setConn("closed");
              return;
            }
          }
          setConn("closed");
          return;
        } catch (e) {
          if (ac.signal.aborted || (e as Error).name === "AbortError") return;
          if (e instanceof ApiError && e.code !== "network") {
            setHttpError({ status: e.status, code: e.code, message: e.message, retryAfter: e.retryAfter });
            setConn("failed");
            return;
          }
          if (attempt < maxAttempts) {
            setConn("reconnecting");
            await new Promise((r) => setTimeout(r, 1500));
            continue;
          }
          setConn("dropped");
          return;
        }
      }
    },
    [scenarioId, mode, abort],
  );

  const reset = useCallback(() => {
    abort();
    dispatch({ type: "reset" });
    setConn("idle");
    setHttpError(null);
  }, [abort]);

  return { state, conn, httpError, start, abort, reset, mock: mock.current };
}
