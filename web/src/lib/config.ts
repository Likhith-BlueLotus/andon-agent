/** API base URL and runtime switches. No secrets here: the demo passcode lives in memory only. */
export const API_URL: string = (import.meta.env.VITE_API_URL ?? "http://localhost:8080").replace(/\/+$/, "");

export type MockVariant = "ok" | "error" | "drop" | "budget" | "insufficient";

/** `?mock=1` plays the fixture; `?mock=error|drop|budget|insufficient` plays a designed failure state. */
export function readMock(search: string = typeof window === "undefined" ? "" : window.location.search): MockVariant | null {
  const v = new URLSearchParams(search).get("mock");
  if (!v || v === "0" || v === "false") return null;
  if (v === "error" || v === "drop" || v === "budget" || v === "insufficient") return v;
  return "ok";
}

/**
 * Downtime cost shown in the line mimic. This is an ASSUMPTION, not a measurement:
 * ~USD 2.3 M per hour of unplanned automotive downtime (the figure used in docs/DEMO_AND_SUBMISSION.md).
 */
export const ASSUMED_DOWNTIME_USD_PER_HOUR = 2_300_000;
export const ASSUMED_DOWNTIME_USD_PER_MIN = ASSUMED_DOWNTIME_USD_PER_HOUR / 60;

export const THEME_STRING = "Manufacturing: Intelligent Operations & Industrial Efficiency";
export const BADGE_TEXT = "SYNTHETIC LINE · REAL SIGNALS MARKED";
export const MAX_VERIFIER_ITERATIONS = 3;
