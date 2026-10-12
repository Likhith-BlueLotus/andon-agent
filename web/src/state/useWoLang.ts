import { useCallback, useEffect, useRef, useState } from "react";
import type { WorkOrder } from "../types/events";
import { ApiError } from "../lib/api";
import { getWoTranslation, mockWoTranslation, type LangCode, type WoTranslation } from "../lib/translate";

function describe(e: unknown): string {
  if (e instanceof ApiError) {
    if (e.status === 429) return `Too many requests${e.retryAfter ? `, retry in ${e.retryAfter} s` : ""}.`;
    if (e.status === 401) return "Translation needs the demo passcode (live run). Re-enter it from Run live.";
    if (e.code === "budget_exhausted") return "Translation is paused: the daily budget is used up.";
    if (e.code === "translation_failed") return "The translation failed. Nothing was changed.";
    return `${e.code}: ${e.message}`;
  }
  return "Unexpected error while translating.";
}

/** Selected work-order language, fetched translation, a per-(wo_id, lang) client cache, and stale-request abort. Ticks live in useApproval and are untouched. */
export function useWoLang(wo: WorkOrder | null, incidentId: string | null, passcode: string | null, isMock: boolean) {
  const [lang, setLang] = useState<LangCode | null>(null);
  const [data, setData] = useState<WoTranslation | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const cache = useRef(new Map<string, WoTranslation>());
  const woId = wo?.wo_id ?? null;
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    setError(null);
    if (!lang || !wo || !woId) {
      setData(null);
      setLoading(false);
      return;
    }
    const key = `${woId}:${lang}`;
    const hit = cache.current.get(key);
    if (hit) {
      setData(hit);
      setLoading(false);
      return;
    }
    setData(null);
    setLoading(true);
    const ctl = new AbortController();
    (async () => {
      try {
        let r: WoTranslation;
        if (isMock) {
          await new Promise((res) => setTimeout(res, 500));
          r = mockWoTranslation(wo, lang);
        } else {
          if (!incidentId) throw new ApiError(0, "no_incident", "No incident to translate");
          r = await getWoTranslation(incidentId, lang, passcode, ctl.signal);
        }
        if (ctl.signal.aborted) return;
        cache.current.set(key, r);
        setData(r);
      } catch (e) {
        if ((e as Error).name === "AbortError") return;
        setError(describe(e));
      } finally {
        if (!ctl.signal.aborted) setLoading(false);
      }
    })();
    return () => ctl.abort();
    // wo identity changes with the stream; the work order id is what matters
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lang, woId, incidentId, passcode, isMock, attempt]);

  const showOriginal = useCallback(() => setLang(null), []);
  const retry = useCallback(() => setAttempt((n) => n + 1), []);
  const byOrder = new Map(data?.steps.map((s) => [s.order, s.translation]) ?? []);
  return { lang, setLang, data, loading, error, byOrder, showOriginal, retry };
}
export type WoLang = ReturnType<typeof useWoLang>;
