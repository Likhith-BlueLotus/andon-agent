import { useState } from "react";
import { Dialog } from "./Dialog";

export function PasscodeDialog({ error, onSubmit, onCancel }: { error: string | null; onSubmit: (p: string) => void; onCancel: () => void }) {
  const [v, setV] = useState("");
  return (
    <Dialog title="Demo passcode for live runs" onClose={onCancel} labelId="pass-title">
      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (v.trim()) onSubmit(v.trim());
        }}
        className="space-y-3"
      >
        <p className="text-sm">A live run calls Gemini and spends real budget, so it needs the demo passcode. Replays need none.</p>
        {error && <p role="alert" className="text-sm text-bad">{error}</p>}
        <div>
          <label htmlFor="passcode" className="text-xs font-semibold">Passcode</label>
          <input id="passcode" data-autofocus type="password" value={v} onChange={(e) => setV(e.target.value)} autoComplete="off" className="mt-1 w-full rounded border border-line bg-raised px-2 py-2 font-mono text-sm" />
          <p className="mt-1 text-[11px] text-muted">Kept in memory for this tab only. Never stored or put in a URL.</p>
        </div>
        <div className="flex justify-end gap-2">
          <button type="button" className="btn" onClick={onCancel}>Cancel</button>
          <button type="submit" className="btn-primary" disabled={!v.trim()}>Run live</button>
        </div>
      </form>
    </Dialog>
  );
}
