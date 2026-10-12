import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, renderHook } from "@testing-library/react";
import { useVoiceRecorder } from "./useVoiceRecorder";

class FakeRecorder {
  static instances: FakeRecorder[] = [];
  static isTypeSupported = (m: string) => m === "audio/webm;codecs=opus";
  state: "inactive" | "recording" = "inactive";
  mimeType: string;
  ondataavailable: ((e: { data: Blob }) => void) | null = null;
  onstop: (() => void) | null = null;
  onerror: (() => void) | null = null;
  constructor(_s: unknown, opts?: { mimeType?: string }) {
    this.mimeType = opts?.mimeType ?? "";
    FakeRecorder.instances.push(this);
  }
  start() {
    this.state = "recording";
  }
  stop() {
    this.state = "inactive";
    this.ondataavailable?.({ data: new Blob(["abc"], { type: this.mimeType }) });
    this.onstop?.();
  }
}

const track = { stop: vi.fn() };

beforeEach(() => {
  vi.useFakeTimers();
  FakeRecorder.instances = [];
  track.stop.mockClear();
  vi.stubGlobal("MediaRecorder", FakeRecorder);
  Object.defineProperty(navigator, "mediaDevices", { configurable: true, value: { getUserMedia: vi.fn().mockResolvedValue({ getTracks: () => [track] }) } });
  URL.createObjectURL = vi.fn(() => "blob:fake");
  URL.revokeObjectURL = vi.fn();
});
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("useVoiceRecorder", () => {
  it("records, auto-stops at 60 s with the preferred mime type, and releases the mic", async () => {
    const { result } = renderHook(() => useVoiceRecorder());
    expect(result.current.status).toBe("idle");
    await act(async () => {
      await result.current.start();
    });
    expect(result.current.status).toBe("recording");
    expect(FakeRecorder.instances[0].mimeType).toBe("audio/webm;codecs=opus");
    await act(async () => {
      vi.advanceTimersByTime(30_000);
    });
    expect(result.current.elapsed).toBe(30);
    expect(result.current.status).toBe("recording");
    await act(async () => {
      vi.advanceTimersByTime(30_400);
    });
    expect(result.current.status).toBe("recorded");
    expect(result.current.autoStopped).toBe(true);
    expect(result.current.durationS).toBe(60);
    expect(result.current.blob?.size).toBeGreaterThan(0);
    expect(result.current.url).toBe("blob:fake");
    expect(track.stop).toHaveBeenCalled();
    act(() => result.current.discard());
    expect(result.current.status).toBe("idle");
    expect(result.current.blob).toBeNull();
  });

  it("manual stop works and does not flag auto-stop", async () => {
    const { result } = renderHook(() => useVoiceRecorder());
    await act(async () => {
      await result.current.start();
    });
    await act(async () => {
      vi.advanceTimersByTime(5000);
    });
    act(() => result.current.stop());
    expect(result.current.status).toBe("recorded");
    expect(result.current.autoStopped).toBe(false);
  });

  it("reports a denied microphone", async () => {
    (navigator.mediaDevices.getUserMedia as ReturnType<typeof vi.fn>).mockRejectedValueOnce(Object.assign(new Error("no"), { name: "NotAllowedError" }));
    const { result } = renderHook(() => useVoiceRecorder());
    await act(async () => {
      await result.current.start();
    });
    expect(result.current.status).toBe("denied");
  });

  it("reports unsupported when MediaRecorder is missing", () => {
    vi.stubGlobal("MediaRecorder", undefined);
    const { result } = renderHook(() => useVoiceRecorder());
    expect(result.current.status).toBe("unsupported");
  });
});
