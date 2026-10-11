import { API_URL } from "./config";
import type {
  ApiConfig,
  ApproveRequest,
  ApproveResponse,
  ReplayInfo,
  ScenariosResponse,
  SourcesResponse,
  TelemetryResponse,
} from "../types/api";

export class ApiError extends Error {
  status: number;
  code: string;
  retryAfter: number | null;
  constructor(status: number, code: string, message: string, retryAfter: number | null = null) {
    super(message);
    this.status = status;
    this.code = code;
    this.retryAfter = retryAfter;
  }
}

/** Error bodies are `{"detail": {"code", "message", ...}}` (api/routes.py). */
export async function toApiError(res: Response): Promise<ApiError> {
  let code = `http_${res.status}`;
  let message = res.statusText || `HTTP ${res.status}`;
  try {
    const body = await res.json();
    const d = body?.detail;
    if (d && typeof d === "object") {
      code = String(d.code ?? code);
      message = String(d.message ?? message);
    } else if (typeof d === "string") message = d;
  } catch {
    /* non-JSON body */
  }
  const ra = res.headers.get("Retry-After");
  return new ApiError(res.status, code, message, ra ? Number(ra) || null : null);
}

async function getJson<T>(path: string, signal?: AbortSignal): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, { signal, headers: { Accept: "application/json" } });
  } catch (e) {
    if ((e as Error).name === "AbortError") throw e;
    throw new ApiError(0, "network", "Cannot reach the API");
  }
  if (!res.ok) throw await toApiError(res);
  return (await res.json()) as T;
}

export const getConfig = (s?: AbortSignal) => getJson<ApiConfig>("/api/config", s);
export const getScenarios = (s?: AbortSignal) => getJson<ScenariosResponse>("/api/scenarios", s);
export const getReplays = async (s?: AbortSignal) => (await getJson<{ replays: ReplayInfo[] }>("/api/replays", s)).replays;
export const getSources = (s?: AbortSignal) => getJson<SourcesResponse>("/api/sources", s);
export const getEvalLatest = (s?: AbortSignal) => getJson<unknown>("/api/eval/latest", s);

export function getTelemetry(
  scenarioId: string,
  q: { asset_id: string; tags: string[]; t0: string; t1: string; max_points?: number },
  signal?: AbortSignal,
): Promise<TelemetryResponse> {
  const p = new URLSearchParams({
    asset_id: q.asset_id,
    tags: q.tags.join(","),
    t0: q.t0,
    t1: q.t1,
    max_points: String(q.max_points ?? 300),
  });
  return getJson<TelemetryResponse>(`/api/scenarios/${encodeURIComponent(scenarioId)}/telemetry?${p}`, signal);
}

export async function postApprove(
  incidentId: string,
  body: ApproveRequest,
  passcode: string | null,
): Promise<ApproveResponse> {
  const headers: Record<string, string> = { "Content-Type": "application/json", Accept: "application/json" };
  if (passcode) headers["X-Demo-Passcode"] = passcode;
  let res: Response;
  try {
    res = await fetch(`${API_URL}/api/incidents/${encodeURIComponent(incidentId)}/approve`, {
      method: "POST",
      headers,
      body: JSON.stringify(body),
    });
  } catch {
    throw new ApiError(0, "network", "Cannot reach the API");
  }
  if (!res.ok) throw await toApiError(res);
  return (await res.json()) as ApproveResponse;
}
