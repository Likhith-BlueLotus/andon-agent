import { readMock } from "./config";

/** Stretch features, gated per deployment. `/api/config` has no stretch field yet, so we also read `VITE_ENABLE_STRETCH` ("upload,tech,..."). Mock mode shows everything. */
export function uploadEnabled(config: { stretch?: unknown; features?: unknown } | null): boolean {
  if (readMock()) return true;
  const env = String(import.meta.env.VITE_ENABLE_STRETCH ?? "").toLowerCase();
  if (env.split(/[\s,]+/).includes("upload")) return true;
  for (const f of [config?.stretch, config?.features]) {
    if (Array.isArray(f) && f.includes("upload")) return true;
    if (f && typeof f === "object" && (f as Record<string, unknown>).upload === true) return true;
  }
  return false;
}
