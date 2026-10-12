import { getPasscode } from "./passcode";
import { API_URL, readMock } from "./config";
import { ApiError, toApiError } from "./api";
import type { VoiceNoteResponse } from "../types/api";

export const MAX_NOTE_SECONDS = 60;

/** Prefer webm/opus (Chrome, Firefox, Android); Safari only records mp4. */
export const MIME_CANDIDATES = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4"] as const;

export function pickMimeType(): string | null {
  if (typeof MediaRecorder === "undefined") return null;
  for (const m of MIME_CANDIDATES) if (MediaRecorder.isTypeSupported?.(m)) return m;
  return null;
}

export function recorderSupported(): boolean {
  return typeof navigator !== "undefined" && !!navigator.mediaDevices?.getUserMedia && typeof MediaRecorder !== "undefined" && pickMimeType() !== null;
}

const extFor = (mime: string) => (mime.includes("mp4") ? "m4a" : "webm");

export async function postVoiceNote(incidentId: string, blob: Blob, durationS: number, passcode: string | null): Promise<VoiceNoteResponse> {
  if (readMock()) return mockVoiceNote(incidentId, durationS);
  const form = new FormData();
  form.append("audio", blob, `voice-note.${extFor(blob.type || "audio/webm")}`);
  form.append("duration_s", durationS.toFixed(1));
  const headers: Record<string, string> = { Accept: "application/json" };
  if (passcode) headers["X-Demo-Passcode"] = passcode;
  let res: Response;
  try {
    res = await fetch(`${API_URL}/api/incidents/${encodeURIComponent(incidentId)}/voice-note`, { method: "POST", headers, body: form });
  } catch {
    throw new ApiError(0, "network", "Cannot reach the API");
  }
  if (!res.ok) throw await toApiError(res);
  return (await res.json()) as VoiceNoteResponse;
}

export async function getVoiceNotes(incidentId: string, signal?: AbortSignal): Promise<VoiceNoteResponse[]> {
  if (readMock()) return [];
  try {
    // notes need the passcode (they are the passcode holder's speech); without it there is nothing to list
    const pc = getPasscode();
    if (!pc) return [];
    const res = await fetch(`${API_URL}/api/incidents/${encodeURIComponent(incidentId)}/voice-notes`, { signal, headers: { Accept: "application/json", "X-Demo-Passcode": pc } });
    if (!res.ok) return [];
    return ((await res.json()) as { notes?: VoiceNoteResponse[] }).notes ?? [];
  } catch {
    return [];
  }
}

/** Plain-language message per documented error. */
export function describeVoiceError(e: unknown): string {
  if (!(e instanceof ApiError)) return "Could not send the voice note.";
  switch (e.status) {
    case 0:
      return "Cannot reach the API. Your recording is kept: try Send again.";
    case 400:
      return "The server could not read that audio (bad_audio). Record it again.";
    case 413:
      return "That recording is too large (413). Keep it under 60 seconds and record again.";
    case 415:
      return "This browser's audio format is not accepted (415 unsupported_audio).";
    case 404:
      return e.code === "not_enabled" ? "Voice notes are not enabled on this deployment." : "This incident is unknown to the server (404), so a note cannot be attached.";
    case 401:
      return "Voice notes on this incident need the demo passcode.";
    case 429:
      return `Too many requests. ${e.retryAfter ? `Try again in ${e.retryAfter} s.` : "Try again shortly."} Your recording is kept.`;
    default:
      return `${e.code}: ${e.message}`;
  }
}

function mockVoiceNote(incidentId: string, durationS: number): Promise<VoiceNoteResponse> {
  return new Promise((resolve) =>
    setTimeout(
      () =>
        resolve({
          note_id: `vn_mock_${Date.now().toString(36)}`,
          incident_id: incidentId,
          created_at: new Date().toISOString(),
          duration_s: durationS,
          note: {
            summary: "Mock note (no server call): technician heard a hiss near the header and found a loose fitting.",
            observations: ["Audible hiss near the header fitting", "Compressor running continuously"],
            actions_taken: ["Tightened the fitting"],
            parts_used: [],
            safety_concerns: [],
            language: "en",
          },
          transcript: "Mock transcript: there is a hiss near the header, I tightened the fitting.",
          model_id: "mock",
          cost_usd: 0,
          untrusted: true,
        }),
      700,
    ),
  );
}
