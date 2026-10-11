import { ApiError, toApiError } from "./api";
import { API_URL, readMock } from "./config";
import type { ConfirmRequest, ConfirmResponse, UploadProposal } from "../types/upload";
import { MOCK_PROPOSAL, mockConfirm } from "./uploadMock";

const delay = (ms: number, s?: AbortSignal) =>
  new Promise<void>((res, rej) => {
    const t = setTimeout(res, ms);
    s?.addEventListener("abort", () => { clearTimeout(t); rej(new DOMException("aborted", "AbortError")); });
  });

/** `?mockupload=bad_csv|too_large|too_many_columns|not_enabled|rate|heuristic|bad_mapping|bad_timestamps|unknown_upload` exercises the designed error states offline. */
function mockVariant(): string {
  return new URLSearchParams(window.location.search).get("mockupload") ?? "";
}
const MOCK_ERR: Record<string, [number, string, string]> = {
  bad_csv: [400, "bad_csv", "Could not parse this file as CSV."],
  too_large: [413, "too_large", "File exceeds the 20 MB limit."],
  too_many_columns: [400, "too_many_columns", "More than 60 columns; trim the export first."],
  not_enabled: [404, "not_enabled", "Uploads are not enabled."],
  rate: [429, "rate_limited", "Too many uploads; wait a minute."],
  unauthorized: [401, "unauthorized", "Missing or wrong passcode."],
};

function headers(passcode: string | null, json: boolean): Record<string, string> {
  const h: Record<string, string> = { Accept: "application/json" };
  if (json) h["Content-Type"] = "application/json";
  if (passcode) h["X-Demo-Passcode"] = passcode;
  return h;
}

async function send(path: string, init: RequestInit): Promise<Response> {
  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, init);
  } catch (e) {
    if ((e as Error).name === "AbortError") throw e;
    throw new ApiError(0, "network", "Cannot reach the API");
  }
  if (!res.ok) throw await toApiError(res);
  return res;
}

export async function postUpload(file: File, passcode: string | null, signal?: AbortSignal): Promise<UploadProposal> {
  if (readMock()) {
    await delay(900, signal);
    const v = mockVariant();
    if (!passcode) throw new ApiError(401, "unauthorized", MOCK_ERR.unauthorized[2]);
    if (MOCK_ERR[v]) throw new ApiError(...MOCK_ERR[v]);
    return MOCK_PROPOSAL(file.name, v === "heuristic");
  }
  const fd = new FormData();
  fd.append("file", file);
  const res = await send("/api/uploads", { method: "POST", headers: headers(passcode, false), body: fd, signal });
  return (await res.json()) as UploadProposal;
}

export async function postConfirm(uploadId: string, body: ConfirmRequest, passcode: string | null, signal?: AbortSignal): Promise<ConfirmResponse> {
  if (readMock()) {
    await delay(600, signal);
    const v = mockVariant();
    if (!passcode) throw new ApiError(401, "unauthorized", MOCK_ERR.unauthorized[2]);
    if (v === "bad_mapping") throw new ApiError(400, "bad_mapping", "Column Gun_Air_ST20 is not numeric.");
    if (v === "bad_timestamps") throw new ApiError(400, "bad_timestamps", "Could not parse timestamps in column Timestamp.");
    if (v === "unknown_upload") throw new ApiError(404, "unknown_upload", "This upload expired (2 hours). Upload the file again.");
    return mockConfirm(body);
  }
  const res = await send(`/api/uploads/${encodeURIComponent(uploadId)}/confirm`, { method: "POST", headers: headers(passcode, true), body: JSON.stringify(body), signal });
  return (await res.json()) as ConfirmResponse;
}
