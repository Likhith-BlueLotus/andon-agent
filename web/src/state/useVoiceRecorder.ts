import { useCallback, useEffect, useRef, useState } from "react";
import { MAX_NOTE_SECONDS, pickMimeType, recorderSupported } from "../lib/voice";

export type RecStatus = "idle" | "requesting" | "recording" | "recorded" | "denied" | "unsupported" | "error";

/**
 * Recorder state machine: idle -> requesting -> recording -> recorded (-> idle on discard).
 * Auto-stops at MAX_NOTE_SECONDS. Always releases the microphone (tracks stopped) and the preview URL.
 */
export function useVoiceRecorder(maxSeconds: number = MAX_NOTE_SECONDS) {
  const [status, setStatus] = useState<RecStatus>(() => (recorderSupported() ? "idle" : "unsupported"));
  const [elapsed, setElapsed] = useState(0);
  const [blob, setBlob] = useState<Blob | null>(null);
  const [url, setUrl] = useState<string | null>(null);
  const [durationS, setDurationS] = useState(0);
  const [autoStopped, setAutoStopped] = useState(false);
  const rec = useRef<MediaRecorder | null>(null);
  const stream = useRef<MediaStream | null>(null);
  const chunks = useRef<Blob[]>([]);
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);
  const t0 = useRef(0);
  const urlRef = useRef<string | null>(null);

  const release = useCallback(() => {
    if (timer.current) clearInterval(timer.current);
    timer.current = null;
    stream.current?.getTracks().forEach((t) => t.stop());
    stream.current = null;
  }, []);

  const stop = useCallback(() => {
    const r = rec.current;
    if (r && r.state !== "inactive") r.stop();
  }, []);

  const clearBlob = useCallback(() => {
    if (urlRef.current) URL.revokeObjectURL(urlRef.current);
    urlRef.current = null;
    setUrl(null);
    setBlob(null);
  }, []);

  const start = useCallback(async () => {
    if (!recorderSupported()) {
      setStatus("unsupported");
      return;
    }
    clearBlob();
    setAutoStopped(false);
    setElapsed(0);
    setStatus("requesting");
    let s: MediaStream;
    try {
      s = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch (e) {
      const n = (e as DOMException).name;
      setStatus(n === "NotAllowedError" || n === "SecurityError" || n === "PermissionDeniedError" ? "denied" : "error");
      return;
    }
    stream.current = s;
    const mimeType = pickMimeType() ?? undefined;
    let r: MediaRecorder;
    try {
      r = new MediaRecorder(s, mimeType ? { mimeType } : undefined);
    } catch {
      release();
      setStatus("error");
      return;
    }
    rec.current = r;
    chunks.current = [];
    r.ondataavailable = (e: BlobEvent) => {
      if (e.data && e.data.size > 0) chunks.current.push(e.data);
    };
    r.onstop = () => {
      const secs = Math.min(maxSeconds, (Date.now() - t0.current) / 1000);
      release();
      const b = new Blob(chunks.current, { type: r.mimeType || mimeType || "audio/webm" });
      if (b.size === 0) {
        setStatus("error");
        return;
      }
      const u = URL.createObjectURL(b);
      urlRef.current = u;
      setBlob(b);
      setUrl(u);
      setDurationS(Math.round(secs * 10) / 10);
      setElapsed(Math.floor(secs));
      setStatus("recorded");
    };
    r.onerror = () => {
      release();
      setStatus("error");
    };
    t0.current = Date.now();
    r.start();
    setStatus("recording");
    timer.current = setInterval(() => {
      const secs = (Date.now() - t0.current) / 1000;
      setElapsed(Math.min(maxSeconds, Math.floor(secs)));
      if (secs >= maxSeconds) {
        setAutoStopped(true);
        stop();
      }
    }, 200);
  }, [clearBlob, maxSeconds, release, stop]);

  const discard = useCallback(() => {
    clearBlob();
    setElapsed(0);
    setAutoStopped(false);
    setStatus(recorderSupported() ? "idle" : "unsupported");
  }, [clearBlob]);

  useEffect(
    () => () => {
      const r = rec.current;
      if (r) {
        r.onstop = null;
        if (r.state !== "inactive") r.stop();
      }
      release();
      if (urlRef.current) URL.revokeObjectURL(urlRef.current);
    },
    [release],
  );

  return { status, elapsed, blob, url, durationS, autoStopped, start, stop, discard, maxSeconds };
}
