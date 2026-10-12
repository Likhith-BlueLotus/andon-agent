import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ShiftNoteCard, VoicePanel } from "./Voice";
import type { VoiceNoteResponse } from "../types/api";

const resp: VoiceNoteResponse = {
  note_id: "vn1",
  incident_id: "inc1",
  created_at: "2026-10-12T10:00:00Z",
  duration_s: 12.4,
  note: { summary: "Loose fitting on the header.", observations: ["Hiss near header"], actions_taken: ["Tightened fitting"], parts_used: ["O-ring"], safety_concerns: ["Hot surface"], language: "en" },
  transcript: "there was a hiss near the header",
  model_id: "gemini-3.1-flash-lite",
  cost_usd: 0.0003,
  untrusted: true,
};

afterEach(cleanup);

describe("ShiftNoteCard", () => {
  it("is labelled untrusted machine transcription and never styled as verified", () => {
    render(<ShiftNoteCard r={resp} />);
    const card = screen.getByTestId("shift-note");
    expect(card.getAttribute("data-untrusted")).toBe("true");
    expect(card).toHaveTextContent("Shift note · machine transcription · untrusted");
    expect(card.className).toMatch(/border-dashed/);
    expect(card.className).not.toMatch(/\bok\b/);
    expect(card.innerHTML).not.toMatch(/text-ok|border-ok/);
    expect(card.textContent).not.toMatch(/verified by|VERIFIED/);
    expect(screen.getByText("Loose fitting on the header.")).toBeInTheDocument();
    expect(screen.getByText("O-ring")).toBeInTheDocument();
    expect(screen.getByText("Hot surface")).toBeInTheDocument();
    // transcript is collapsed by default
    expect((screen.getByTestId("transcript").closest("details") as HTMLDetailsElement).open).toBe(false);
  });

  it("renders note text as plain text, not HTML", () => {
    render(<ShiftNoteCard r={{ ...resp, note: { ...resp.note, summary: "<img src=x onerror=alert(1)>" } }} />);
    expect(document.querySelector("img")).toBeNull();
  });
});

describe("VoicePanel send flow", () => {
  beforeEach(() => {
    class R {
      static isTypeSupported = () => true;
      state = "inactive";
      mimeType = "audio/webm;codecs=opus";
      ondataavailable: ((e: { data: Blob }) => void) | null = null;
      onstop: (() => void) | null = null;
      start() { this.state = "recording"; }
      stop() { this.state = "inactive"; this.ondataavailable?.({ data: new Blob(["x"]) }); this.onstop?.(); }
    }
    vi.stubGlobal("MediaRecorder", R);
    Object.defineProperty(navigator, "mediaDevices", { configurable: true, value: { getUserMedia: vi.fn().mockResolvedValue({ getTracks: () => [{ stop() {} }] }) } });
    URL.createObjectURL = vi.fn(() => "blob:x");
    URL.revokeObjectURL = vi.fn();
  });
  afterEach(() => vi.unstubAllGlobals());

  it("record -> stop -> Send posts multipart audio + duration_s with the passcode, then shows the untrusted note; 429 keeps the recording", async () => {
    const u = userEvent.setup();
    const calls: { url: string; init: RequestInit }[] = [];
    let n = 0;
    vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
      if (!init || init.method !== "POST") return new Response(JSON.stringify({ notes: [] }), { status: 200 });
      calls.push({ url, init });
      if (n++ === 0) return new Response(JSON.stringify({ detail: { code: "rate_limited", message: "slow down" } }), { status: 429, headers: { "Retry-After": "7" } });
      return new Response(JSON.stringify(resp), { status: 200 });
    }));
    render(<VoicePanel incidentId="inc1" passcode="pw" />);
    await u.click(screen.getByRole("button", { name: /Record voice note/ }));
    await u.click(await screen.findByRole("button", { name: /Stop/ }));
    await u.click(screen.getByRole("button", { name: "Send" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/Try again in 7 s/);
    expect(screen.getByRole("button", { name: "Send" })).toBeInTheDocument(); // recording kept
    await u.click(screen.getByRole("button", { name: "Send" }));
    expect(await screen.findByTestId("shift-note")).toHaveTextContent("untrusted");
    expect(calls[0].url).toMatch(/\/api\/incidents\/inc1\/voice-note$/);
    const body = calls[0].init.body as FormData;
    expect(body.get("audio")).toBeInstanceOf(Blob);
    expect(body.get("duration_s")).not.toBeNull();
    expect((calls[0].init.headers as Record<string, string>)["X-Demo-Passcode"]).toBe("pw");
  });
});
