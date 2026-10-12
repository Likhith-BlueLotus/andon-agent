import { API_URL } from "./config";
import { ApiError, toApiError } from "./api";
import type { WorkOrder } from "../types/events";

/** Work-order language toggle (stretch item 3). Contract: GET /api/incidents/{id}/work-order?lang=hi|ta|id|vi */
export type LangCode = "hi" | "ta" | "id" | "vi";
export const LANGS: { code: LangCode; native: string; name: string }[] = [
  { code: "hi", native: "हिन्दी", name: "Hindi" },
  { code: "ta", native: "தமிழ்", name: "Tamil" },
  { code: "id", native: "Bahasa Indonesia", name: "Indonesian" },
  { code: "vi", native: "Tiếng Việt", name: "Vietnamese" },
];

export interface TranslatedStep {
  order: number;
  is_safety: boolean;
  original: string;
  translation: string | null;
  citation: unknown;
}
export interface WoTranslation {
  incident_id: string;
  wo_id: string;
  lang: LangCode;
  lang_name: string;
  model_id: string;
  cost_usd: number;
  cached: boolean;
  notice: string;
  steps: TranslatedStep[];
  parts: { original: string; translation: string | null }[];
}

export async function getWoTranslation(incidentId: string, lang: LangCode, passcode: string | null, signal?: AbortSignal): Promise<WoTranslation> {
  const headers: Record<string, string> = { Accept: "application/json" };
  if (passcode) headers["X-Demo-Passcode"] = passcode;
  let res: Response;
  try {
    res = await fetch(`${API_URL}/api/incidents/${encodeURIComponent(incidentId)}/work-order?lang=${lang}`, { headers, signal });
  } catch (e) {
    if ((e as Error).name === "AbortError") throw e;
    throw new ApiError(0, "network", "Cannot reach the API");
  }
  if (!res.ok) throw await toApiError(res);
  return (await res.json()) as WoTranslation;
}

const MOCK_PREFIX: Record<LangCode, string> = {
  hi: "[डेमो अनुवाद] ",
  ta: "[டெமோ மொழிபெயர்ப்பு] ",
  id: "[terjemahan demo] ",
  vi: "[bản dịch demo] ",
};

/** `?mock=1` stand-in for the endpoint. Obviously fake text; the last non-safety step is left untranslated to exercise that state. */
export function mockWoTranslation(wo: WorkOrder, lang: LangCode): WoTranslation {
  const info = LANGS.find((l) => l.code === lang)!;
  const lastPlain = [...wo.steps].filter((s) => !s.is_safety).sort((a, b) => b.order - a.order)[0]?.order;
  return {
    incident_id: wo.incident_id,
    wo_id: wo.wo_id,
    lang,
    lang_name: info.name,
    model_id: "mock",
    cost_usd: 0.0007,
    cached: false,
    notice: "Machine translation — not the controlling text. Safety steps are always shown in the original, verbatim from the manual. (mock)",
    steps: wo.steps.map((s) => ({
      order: s.order,
      is_safety: s.is_safety,
      original: s.text,
      translation: s.order === lastPlain && lang === "vi" ? null : `${MOCK_PREFIX[lang]}${s.text}`,
      citation: s.citation,
    })),
    parts: wo.parts.map((p) => ({ original: p, translation: `${MOCK_PREFIX[lang]}${p}` })),
  };
}
