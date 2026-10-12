import { readMock } from "./config";

type FlagSource = { stretch?: unknown; features?: unknown } | null;

/** Stretch features, gated per deployment. Reads `/api/config.features` (or `.stretch`), then `VITE_ENABLE_STRETCH` ("upload,tech,..."). Mock mode shows everything. */
export function featureEnabled(config: FlagSource, name: string): boolean {
  if (readMock()) return true;
  const env = String(import.meta.env.VITE_ENABLE_STRETCH ?? "").toLowerCase();
  if (env.split(/[\s,]+/).includes(name)) return true;
  for (const f of [config?.stretch, config?.features]) {
    if (Array.isArray(f) && f.includes(name)) return true;
    if (f && typeof f === "object" && (f as Record<string, unknown>)[name] === true) return true;
  }
  return false;
}

export const uploadEnabled = (config: FlagSource): boolean => featureEnabled(config, "upload");
export const techEnabled = (config: FlagSource): boolean => featureEnabled(config, "tech");
export const langEnabled = (config: FlagSource): boolean => featureEnabled(config, "lang");
