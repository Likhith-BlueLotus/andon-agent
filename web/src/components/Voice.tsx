import { useEffect, useState } from "react";
import type { VoiceNoteResponse } from "../types/api";
import { ApiError } from "../lib/api";
import { describeVoiceError, getVoiceNotes, postVoiceNote } from "../lib/voice";
import { getPasscode, setPasscode } from "../lib/passcode";
import { useVoiceRecorder } from "../state/useVoiceRecorder";
import { PasscodeDialog } from "./PasscodeDialog";
import { IconAlert, IconInfo, Spinner } from "./ui";

export const fmtClock = (s: number) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;

/** The structured shift note. Deliberately NOT styled as verified: dashed border, neutral tone, explicit label. */
export function ShiftNoteCard({ r }: { r: VoiceNoteResponse }) {
  const n = r.note;
  const lists: [string, string[] | undefined][] = [
    ["Observations", n.observations],
    ["Actions taken", n.actions_taken],
    ["Parts used", n.parts_used],
    ["Safety concerns reported", n.safety_concerns],
  ];
  return (
    <article className="rounded-md border-2 border-dashed border-muted bg-raised p-3" data-testid="shift-note" data-untrusted="true" aria-label="Shift note, machine transcription, untrusted">
      <p className="flex items-center gap-1.5 font-mono text-[11px] font-semibold uppercase tracking-wide text-muted">
        <IconInfo className="shrink-0" />
        Shift note · machine transcription · untrusted
      </p>
      <p className="mt-2 text-[15px]">{n.summary}</p>
      {lists.map(([title, items]) =>
        items && items.length > 0 ? (
          <div key={title} className="mt-2">
            <h4 className="text-xs font-semibold">{title}</h4>
            <ul className="list-disc pl-5 text-[13px]">
              {items.map((x, i) => (
                <li key={i}>{x}</li>
              ))}
            </ul>
          </div>
        ) : null,
      )}
      <p className="mt-2 text-[11px] text-muted">
        Said by the technician and transcribed by a model. Not checked by the verifier and never used to change the root cause or the work order. · {Math.round(r.duration_s)} s · language {n.language || "unknown"} · <span className="font-mono">{r.model_id}</span>
      </p>
      <details className="mt-2">
        <summary className="inline-flex min-h-[44px] cursor-pointer items-center text-sm font-semibold text-accent underline">Transcript</summary>
        <p className="whitespace-pre-wrap text-[13px]" data-testid="transcript">{r.transcript || "(empty)"}</p>
      </details>
    </article>
  );
}

type SendState = { kind: "idle" } | { kind: "sending" } | { kind: "error"; msg: string };

export function VoicePanel({ incidentId, passcode }: { incidentId: string | null; passcode: string | null }) {
  const rec = useVoiceRecorder();
  const [send, setSend] = useState<SendState>({ kind: "idle" });
  const [notes, setNotes] = useState<VoiceNoteResponse[]>([]);
  const [askPass, setAskPass] = useState<string | null | false>(false);
  const [announce, setAnnounce] = useState("");

  useEffect(() => {
    if (!incidentId) return;
    const ac = new AbortController();
    getVoiceNotes(incidentId, ac.signal).then((n) => {
      if (!ac.signal.aborted) setNotes((prev) => [...n.filter((x) => !prev.some((p) => p.note_id === x.note_id)), ...prev].sort((a, b) => a.created_at.localeCompare(b.created_at)));
    });
    return () => ac.abort();
  }, [incidentId]);

  useEffect(() => {
    if (rec.status === "recording") setAnnounce("Recording started");
    else if (rec.status === "recorded") setAnnounce(rec.autoStopped ? "Recording stopped at the 60 second limit" : "Recording stopped");
  }, [rec.status, rec.autoStopped]);

  async function doSend(pass: string | null) {
    if (!rec.blob || !incidentId) return;
    setSend({ kind: "sending" });
    try {
      const r = await postVoiceNote(incidentId, rec.blob, rec.durationS, pass ?? passcode ?? getPasscode());
      setNotes((n) => [...n, r]);
      setSend({ kind: "idle" });
      rec.discard();
      setAnnounce("Voice note sent and transcribed. The shift note is shown below and is unverified.");
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) setAskPass(pass ? "That passcode was not accepted." : null);
      setSend({ kind: "error", msg: describeVoiceError(e) });
    }
  }

  const sending = send.kind === "sending";
  return (
    <section aria-label="Voice note" className="card p-3" data-testid="voice-panel">
      <h3 className="label">Voice note</h3>
      <p className="sr-only" aria-live="polite">{announce}</p>

      {rec.status === "unsupported" && (
        <p role="alert" className="mt-2 flex items-start gap-2 text-sm" data-testid="rec-unsupported">
          <IconAlert className="mt-0.5 shrink-0 text-warn" />
          <span>This browser cannot record audio here (it needs a secure https page, a microphone and MediaRecorder). Voice notes are unavailable.</span>
        </p>
      )}
      {rec.status === "denied" && (
        <p role="alert" className="mt-2 flex items-start gap-2 text-sm" data-testid="rec-denied">
          <IconAlert className="mt-0.5 shrink-0 text-bad" />
          <span><b className="text-bad">Microphone blocked.</b> Allow microphone access for this site in the browser settings, then try again.</span>
        </p>
      )}
      {rec.status === "error" && (
        <p role="alert" className="mt-2 flex items-start gap-2 text-sm">
          <IconAlert className="mt-0.5 shrink-0 text-bad" />
          <span>The recording failed or was empty. Check the microphone and try again.</span>
        </p>
      )}

      {(rec.status === "idle" || rec.status === "denied" || rec.status === "error") && (
        <button type="button" className="btn-primary mt-2 !min-h-[52px] w-full !text-base" onClick={() => void rec.start()} disabled={!incidentId}>
          <span aria-hidden>●</span> Record voice note
        </button>
      )}
      {rec.status === "requesting" && <p className="mt-2 flex items-center gap-2 text-sm"><Spinner label="waiting for microphone" />Waiting for microphone permission…</p>}
      {rec.status === "recording" && (
        <div className="mt-2 space-y-2">
          <p className="flex items-center gap-2 text-lg font-semibold" data-testid="rec-timer">
            <span aria-hidden className="inline-block h-3 w-3 rounded-full bg-bad" />
            <span className="text-bad">REC</span>
            <span className="font-mono tabular-nums">{fmtClock(rec.elapsed)} / {fmtClock(rec.maxSeconds)}</span>
          </p>
          <button type="button" className="btn !min-h-[52px] w-full border-bad !text-base" onClick={rec.stop}>
            <span aria-hidden>■</span> Stop
          </button>
        </div>
      )}
      {rec.status === "recorded" && rec.url && (
        <div className="mt-2 space-y-2">
          {rec.autoStopped && <p className="text-xs text-warn" data-testid="rec-autostop">Stopped automatically at the 60 s limit.</p>}
          <p className="text-sm">Recorded <span className="font-mono">{fmtClock(rec.durationS)}</span>. Listen, then send or discard.</p>
          <audio controls src={rec.url} className="w-full" aria-label="Voice note preview" />
          {send.kind === "error" && <p role="alert" className="flex items-start gap-1.5 text-sm text-bad"><IconAlert className="mt-0.5 shrink-0" />{send.msg}</p>}
          <div className="grid grid-cols-2 gap-2">
            <button type="button" className="btn !min-h-[52px] !text-base" onClick={() => { setSend({ kind: "idle" }); rec.discard(); }} disabled={sending}>Discard</button>
            <button type="button" className="btn-primary !min-h-[52px] !text-base" onClick={() => void doSend(null)} disabled={sending}>{sending ? "Sending…" : "Send"}</button>
          </div>
          {sending && <p className="flex items-center gap-2 text-xs text-muted"><Spinner label="transcribing" />Transcribing and structuring the note…</p>}
        </div>
      )}

      {notes.length > 0 && (
        <div className="mt-3 space-y-3" data-testid="notes-list">
          {notes.map((n) => (
            <ShiftNoteCard key={n.note_id} r={n} />
          ))}
        </div>
      )}
      {askPass !== false && (
        <PasscodeDialog
          cta="Send note"
          intro="Voice notes on live incidents need the demo passcode."
          error={askPass}
          onCancel={() => setAskPass(false)}
          onSubmit={(p) => {
            setPasscode(p);
            setAskPass(false);
            void doSend(p);
          }}
        />
      )}
    </section>
  );
}
