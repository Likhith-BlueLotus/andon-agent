import { useCallback, useEffect, useId, useMemo, useRef, useState } from "react";
import type { Catalog } from "../state/useCatalog";
import { ApiError } from "../lib/api";
import { fmtNum } from "../lib/format";
import { uploadEnabled } from "../lib/features";
import { getPasscode, setPasscode } from "../lib/passcode";
import { postConfirm, postUpload } from "../lib/upload";
import {
  STATIONS, buildConfirm, checkFile, initialRows, initialTimestamp, isHeuristic, LOW_CONFIDENCE, rememberUpload, validate, type MapRow,
} from "../lib/uploadMapping";
import type { TargetAsset, UploadProposal } from "../types/upload";
import { PasscodeDialog } from "../components/PasscodeDialog";
import { IconAlert, IconInfo, IconLock, Spinner, StatusBadge } from "../components/ui";

type Phase = "idle" | "uploading" | "ready" | "confirming";
type Pending = { kind: "upload"; file: File } | { kind: "confirm" } | null;

const ERRORS: Record<string, string> = {
  bad_csv: "We could not read that file as a CSV. Check it is a plain-text, comma-separated historian export with a header row.",
  too_large: "That file is over the 20 MB limit. Export a shorter time window and try again.",
  too_many_columns: "That file has too many columns. Export only the signals around the stop and try again.",
  not_enabled: "Uploads are not enabled on this deployment.",
  bad_mapping: "The server rejected the mapping. Fix the highlighted problem and confirm again.",
  bad_timestamps: "The server could not parse the timestamps in the column you chose. Pick the right timestamp column.",
  unknown_upload: "This upload has expired (files are kept for 2 hours). Upload the file again.",
};
function describe(e: ApiError): string {
  if (e.status === 0) return "Cannot reach the API. Check your connection, or add ?mock=1 to try this page offline.";
  if (e.status === 429) return `Too many requests. ${e.retryAfter ? `Try again in ${e.retryAfter} s. ` : "Wait a minute and try again. "}${e.message}`;
  return `${ERRORS[e.code] ?? e.code}${e.message && !ERRORS[e.code] ? `: ${e.message}` : e.message ? ` (${e.message})` : ""}`;
}

export function UploadPage({ catalog, navigate }: { catalog: Catalog; navigate: (to: string) => void }) {
  const enabled = uploadEnabled(catalog.config);
  const [phase, setPhase] = useState<Phase>("idle");
  const [fileErr, setFileErr] = useState<string | null>(null);
  const [apiErr, setApiErr] = useState<ApiError | null>(null);
  const [proposal, setProposal] = useState<UploadProposal | null>(null);
  const [rows, setRows] = useState<MapRow[]>([]);
  const [ts, setTs] = useState("");
  const [station, setStation] = useState("ST20-WLD");
  const [stopLocal, setStopLocal] = useState("");
  const [stopText, setStopText] = useState("");
  const [showErrors, setShowErrors] = useState(false);
  const [askPass, setAskPass] = useState<string | null | false>(false);
  const pending = useRef<Pending>(null);
  const abort = useRef<AbortController | null>(null);
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => () => abort.current?.abort(), []);

  const targets: TargetAsset[] = proposal?.targets ?? [];
  const v = useMemo(() => validate(rows, ts, targets), [rows, ts, targets]);

  const doUpload = useCallback(async (file: File) => {
    const pass = getPasscode();
    if (!pass) {
      pending.current = { kind: "upload", file };
      setAskPass(null);
      return;
    }
    abort.current?.abort();
    const ac = (abort.current = new AbortController());
    setPhase("uploading");
    setApiErr(null);
    try {
      const p = await postUpload(file, pass, ac.signal);
      setProposal(p);
      setRows(initialRows(p));
      setTs(initialTimestamp(p));
      setShowErrors(false);
      setPhase("ready");
    } catch (e) {
      if (ac.signal.aborted || (e as Error).name === "AbortError") return;
      setPhase("idle");
      if (e instanceof ApiError && e.status === 401) {
        setPasscode(null);
        pending.current = { kind: "upload", file };
        setAskPass("That passcode was not accepted. Try again.");
        return;
      }
      setApiErr(e instanceof ApiError ? e : new ApiError(0, "network", "Cannot reach the API"));
    }
  }, []);

  const onFile = useCallback((f: File | undefined | null) => {
    if (!f) return;
    const err = checkFile(f);
    setFileErr(err);
    if (!err) void doUpload(f);
  }, [doUpload]);

  const doConfirm = useCallback(async () => {
    if (!proposal) return;
    setShowErrors(true);
    if (!v.ok) return;
    const pass = getPasscode();
    if (!pass) {
      pending.current = { kind: "confirm" };
      setAskPass(null);
      return;
    }
    setPhase("confirming");
    setApiErr(null);
    try {
      const body = buildConfirm(rows, ts, station, stopLocal, stopText);
      const r = await postConfirm(proposal.upload_id, body, pass);
      rememberUpload(r.scenario_id, { filename: proposal.filename, station: r.stopped_station, stop_ts: r.stop_ts });
      navigate(`/?scenario=${encodeURIComponent(r.scenario_id)}&mode=live`);
    } catch (e) {
      setPhase("ready");
      if (e instanceof ApiError && e.status === 401) {
        setPasscode(null);
        pending.current = { kind: "confirm" };
        setAskPass("That passcode was not accepted. Try again.");
        return;
      }
      setApiErr(e instanceof ApiError ? e : new ApiError(0, "network", "Cannot reach the API"));
    }
  }, [proposal, v.ok, rows, ts, station, stopLocal, stopText, navigate]);

  function reset() {
    abort.current?.abort();
    setProposal(null);
    setRows([]);
    setApiErr(null);
    setFileErr(null);
    setPhase("idle");
    setTimeout(() => heading.current?.focus(), 0);
  }

  if (catalog.loading && !enabled) return <div className="p-4 text-sm text-muted"><Spinner label="loading" /> Loading…</div>;
  if (!enabled)
    return (
      <main className="mx-auto w-full max-w-3xl flex-1 overflow-y-auto p-4">
        <div className="rounded-md border border-dashed border-line p-6" data-testid="upload-disabled">
          <p className="flex items-center gap-2 font-semibold"><IconLock />Not enabled on this deployment</p>
          <p className="mt-1 text-sm text-muted">Bring-your-own-CSV is a stretch feature and is switched off here. The console, replays and live runs on the built-in scenarios work as normal.</p>
          <a href="/" className="btn mt-3" onClick={(e) => { e.preventDefault(); navigate("/"); }}>Back to the console</a>
        </div>
      </main>
    );

  const heuristic = proposal ? isHeuristic(proposal) : false;
  const upd = (col: string, patch: Partial<MapRow>) => setRows((rs) => rs.map((r) => (r.column === col ? { ...r, ...patch } : r)));

  return (
    <main className="mx-auto w-full max-w-5xl flex-1 space-y-5 overflow-y-auto overflow-x-hidden p-3 sm:p-4">
      <header>
        <h1 ref={heading} tabIndex={-1} className="text-xl font-semibold outline-none">Bring your own CSV</h1>
        <p className="text-sm text-muted">Drop a historian export from a stopped line. Gemini proposes which column is which signal; you check and confirm; then the agents investigate your data live.</p>
        <p className="mt-2 flex items-start gap-2 rounded border border-line bg-raised p-2 text-xs" data-testid="upload-privacy">
          <IconInfo className="mt-0.5 shrink-0" />
          <span>Your file stays in this demo's memory for 2 hours and is never stored in git or cloud storage. Analysis calls Gemini (costs the demo budget). Every evidence card from it is marked <span className="chip border-dashed border-accent text-accent">USER UPLOAD</span>.</span>
        </p>
      </header>

      {apiErr && (
        <div role="alert" className="flex items-start gap-2 rounded border border-bad bg-bad/10 p-3 text-sm" data-testid="upload-error">
          <IconAlert className="mt-0.5 shrink-0 text-bad" />
          <span><b className="text-bad">{apiErr.code}.</b> {describe(apiErr)}</span>
        </div>
      )}

      {(phase === "idle" || phase === "uploading") && (
        <DropZone busy={phase === "uploading"} error={fileErr} onFile={onFile} />
      )}

      {proposal && (phase === "ready" || phase === "confirming") && (
        <>
          <section aria-labelledby="up-file" className="card p-3">
            <div className="flex flex-wrap items-center gap-2">
              <h2 id="up-file" className="label">File</h2>
              <span className="break-all font-mono text-sm">{proposal.filename}</span>
              <span className="text-xs text-muted">{proposal.n_rows.toLocaleString("en-US")} rows · {proposal.columns.length} columns · mapping cost ${proposal.cost_usd.toFixed(4)}</span>
              <button type="button" className="btn ml-auto !min-h-[32px]" onClick={reset} disabled={phase === "confirming"}>Choose another file</button>
            </div>
            <PreviewTable proposal={proposal} />
          </section>

          <section aria-labelledby="up-map" className="card p-3">
            <h2 id="up-map" className="label">Column mapping</h2>
            {heuristic && (
              <p role="status" className="mt-2 flex items-start gap-2 rounded border border-warn bg-warn/10 p-2 text-sm" data-testid="heuristic-banner">
                <IconAlert className="mt-0.5 shrink-0 text-warn" />
                <span><b className="text-warn">Automatic mapping unavailable.</b> Suggestions are name matches; check them.</span>
              </p>
            )}
            <div className="mt-2 max-w-sm">
              <label htmlFor="ts-col" className="text-xs font-semibold">Timestamp column</label>
              <select id="ts-col" value={ts} onChange={(e) => setTs(e.target.value)} aria-invalid={showErrors && !ts} className="mt-1 w-full rounded border border-line bg-raised px-2 py-2 text-sm">
                <option value="">Choose…</option>
                {proposal.columns.map((c) => <option key={c.name} value={c.name}>{c.name} ({c.dtype})</option>)}
              </select>
            </div>
            <ul className="mt-3 space-y-2" aria-label="Columns">
              {proposal.columns.filter((c) => c.name !== ts).map((c) => (
                <MapRowCard key={c.name} col={c} row={rows.find((r) => r.column === c.name)!} targets={targets} error={showErrors || v.rowErrors[c.name]?.startsWith("Duplicate") ? v.rowErrors[c.name] : undefined} onChange={(p) => upd(c.name, p)} />
              ))}
            </ul>
          </section>

          <section aria-labelledby="up-stop" className="card space-y-3 p-3">
            <h2 id="up-stop" className="label">The stop</h2>
            <div className="grid gap-3 sm:grid-cols-2">
              <div>
                <label htmlFor="stn" className="text-xs font-semibold">Stopped station</label>
                <select id="stn" value={station} onChange={(e) => setStation(e.target.value)} className="mt-1 w-full rounded border border-line bg-raised px-2 py-2 text-sm">
                  {STATIONS.map((s) => <option key={s.id} value={s.id}>{s.id} · {s.name}</option>)}
                </select>
              </div>
              <div>
                <label htmlFor="stop-ts" className="text-xs font-semibold">Stop time, UTC (optional)</label>
                <input id="stop-ts" type="datetime-local" value={stopLocal} onChange={(e) => setStopLocal(e.target.value)} className="mt-1 w-full rounded border border-line bg-raised px-2 py-2 text-sm" aria-describedby="stop-ts-help" />
                <p id="stop-ts-help" className="mt-1 text-[11px] text-muted">Leave blank to use the last timestamp in the file.</p>
              </div>
            </div>
            <div>
              <label htmlFor="stop-text" className="text-xs font-semibold">What happened (short, optional)</label>
              <textarea id="stop-text" rows={2} maxLength={400} value={stopText} onChange={(e) => setStopText(e.target.value)} placeholder="e.g. Line stopped at ST20, weld gun faults, operator heard hissing" className="mt-1 w-full rounded border border-line bg-raised px-2 py-2 text-sm" />
            </div>
          </section>

          <div className="sticky bottom-0 z-10 -mx-3 border-t border-line bg-bg/95 p-3 backdrop-blur sm:mx-0 sm:rounded-md sm:border">
            {showErrors && !v.ok && (
              <ul role="alert" className="mb-2 space-y-0.5 text-sm text-bad" data-testid="validation-summary">
                {v.global.map((g) => <li key={g} className="flex items-start gap-1"><IconAlert className="mt-0.5 shrink-0" />{g}</li>)}
                {Object.keys(v.rowErrors).length > 0 && <li className="flex items-start gap-1"><IconAlert className="mt-0.5 shrink-0" />{Object.keys(v.rowErrors).length} column(s) need attention (marked above).</li>}
              </ul>
            )}
            <div className="flex flex-wrap items-center gap-3">
              <button type="button" className="btn-primary" onClick={() => void doConfirm()} disabled={phase === "confirming"}>
                {phase === "confirming" ? <><Spinner label="confirming" />Preparing…</> : <><span aria-hidden className="font-mono">▶</span>Confirm mapping &amp; investigate</>}
              </button>
              <span className="text-xs text-muted">{v.mappedCount} column(s) mapped. Runs live, spends demo budget.</span>
            </div>
          </div>
        </>
      )}

      {askPass !== false && (
        <PasscodeDialog
          error={askPass}
          cta="Continue"
          intro="Uploading and analysing a file calls Gemini and spends real budget, so it needs the demo passcode."
          onCancel={() => { setAskPass(false); pending.current = null; }}
          onSubmit={(p) => {
            setPasscode(p);
            setAskPass(false);
            const job = pending.current;
            pending.current = null;
            if (job?.kind === "upload") void doUpload(job.file);
            else if (job?.kind === "confirm") setTimeout(() => void doConfirm(), 0);
          }}
        />
      )}
    </main>
  );
}

function DropZone({ busy, error, onFile }: { busy: boolean; error: string | null; onFile: (f: File | undefined) => void }) {
  const [over, setOver] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  const hid = useId();
  return (
    <section aria-label="Upload a CSV file">
      <div
        data-testid="dropzone"
        onDragOver={(e) => { e.preventDefault(); setOver(true); }}
        onDragLeave={() => setOver(false)}
        onDrop={(e) => { e.preventDefault(); setOver(false); if (!busy) onFile(e.dataTransfer.files?.[0]); }}
        className={`flex flex-col items-center gap-2 rounded-md border-2 border-dashed p-8 text-center ${over ? "border-accent bg-accent/10" : "border-line"}`}
      >
        {busy ? (
          <p className="flex items-center gap-2 text-sm" role="status"><Spinner label="uploading" />Uploading and mapping columns with Gemini…</p>
        ) : (
          <>
            <p className="text-sm font-semibold">Drag a .csv here</p>
            <p className="text-xs text-muted">Up to 20 MB, a header row, one timestamp column and numeric signal columns.</p>
            <input ref={input} id={hid} type="file" accept=".csv,text/csv" className="sr-only" onChange={(e) => { onFile(e.target.files?.[0]); e.target.value = ""; }} aria-describedby={error ? `${hid}-err` : undefined} />
            <button type="button" className="btn-primary" onClick={() => input.current?.click()}>Choose CSV file</button>
          </>
        )}
      </div>
      {error && <p id={`${hid}-err`} role="alert" className="mt-2 flex items-center gap-1 text-sm text-bad"><IconAlert />{error}</p>}
    </section>
  );
}

function PreviewTable({ proposal }: { proposal: UploadProposal }) {
  const cols = proposal.columns.map((c) => c.name);
  const rows = proposal.preview.slice(0, 10);
  return (
    <div className="mt-2 max-w-full overflow-x-auto rounded border border-line" tabIndex={0} role="region" aria-label={`Preview of the first ${rows.length} rows (scrolls sideways)`}>
      <table className="w-max min-w-full border-collapse text-xs">
        <thead>
          <tr className="bg-raised text-left">
            {cols.map((c) => <th key={c} scope="col" className="whitespace-nowrap border-b border-line px-2 py-1 font-mono font-semibold">{c}</th>)}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i} className="border-b border-line/60 last:border-0">
              {cols.map((c) => <td key={c} className="whitespace-nowrap px-2 py-1 font-mono">{r[c] == null || r[c] === "" ? <span className="text-muted">·</span> : String(r[c])}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function MapRowCard({ col, row, targets, error, onChange }: { col: UploadProposal["columns"][number]; row: MapRow; targets: TargetAsset[]; error?: string; onChange: (p: Partial<MapRow>) => void }) {
  const id = useId();
  const asset = targets.find((a) => a.asset_id === row.asset_id);
  const tag = asset?.tags.find((t) => t.tag === row.tag);
  const pct = Math.round(row.confidence * 100);
  const low = !row.ignore && row.confidence < LOW_CONFIDENCE;
  return (
    <li className={`rounded border p-2 ${error ? "border-bad" : "border-line"} ${row.ignore ? "opacity-80" : ""}`} data-testid={`map-${col.name}`}>
      <div className="flex flex-wrap items-start gap-x-3 gap-y-1">
        <div className="min-w-0 flex-1 basis-48">
          <p className="break-all font-mono text-sm font-semibold">{col.name} <span className="chip border-line text-muted">{col.dtype}</span></p>
          <p className="truncate text-[11px] text-muted" title={col.sample.join(", ")}>e.g. {col.sample.slice(0, 3).map((s) => String(s)).join(", ") || "(empty)"}</p>
        </div>
        <label className="flex min-h-[36px] items-center gap-2 text-sm">
          <input type="checkbox" checked={row.ignore} onChange={(e) => onChange({ ignore: e.target.checked })} aria-label={`Ignore column ${col.name}`} className="h-4 w-4 accent-[rgb(var(--accent))]" />
          Ignore this column
        </label>
      </div>
      {!row.ignore && (
        <div className="mt-2 grid gap-2 sm:grid-cols-[1fr_1fr_6rem]">
          <div>
            <label htmlFor={`${id}-a`} className="text-xs font-semibold">Asset</label>
            <select id={`${id}-a`} value={row.asset_id} onChange={(e) => onChange({ asset_id: e.target.value, tag: "" })} aria-invalid={!!error} className="mt-1 w-full rounded border border-line bg-raised px-2 py-2 text-sm">
              <option value="">Choose…</option>
              {targets.map((a) => <option key={a.asset_id} value={a.asset_id}>{a.asset_id} · {a.name}</option>)}
            </select>
          </div>
          <div>
            <label htmlFor={`${id}-t`} className="text-xs font-semibold">Tag</label>
            <select id={`${id}-t`} value={row.tag} disabled={!asset} onChange={(e) => onChange({ tag: e.target.value })} aria-invalid={!!error} className="mt-1 w-full rounded border border-line bg-raised px-2 py-2 text-sm">
              <option value="">{asset ? "Choose…" : "Pick an asset first"}</option>
              {asset?.tags.map((t) => <option key={t.tag} value={t.tag}>{t.tag}{t.unit ? ` (${t.unit})` : ""}</option>)}
            </select>
          </div>
          <div>
            <label htmlFor={`${id}-s`} className="text-xs font-semibold">Scale</label>
            <input id={`${id}-s`} inputMode="decimal" value={row.scale} onChange={(e) => onChange({ scale: e.target.value })} aria-invalid={!!error} className="mt-1 w-full rounded border border-line bg-raised px-2 py-2 font-mono text-sm" />
          </div>
          {tag && (
            <p className="text-[11px] text-muted sm:col-span-3" data-testid={`range-${col.name}`}>
              Normal range for {tag.tag}: {tag.normal_lo != null ? fmtNum(tag.normal_lo) : "?"} to {tag.normal_hi != null ? fmtNum(tag.normal_hi) : "?"} {tag.unit ?? ""}. Scale multiplies your values into this unit.
            </p>
          )}
          <div className="flex flex-wrap items-center gap-2 text-xs sm:col-span-3">
            <span className="flex items-center gap-1" role="img" aria-label={`Model confidence ${pct} percent`}>
              <span className="inline-block h-2 w-20 overflow-hidden rounded bg-raised ring-1 ring-line" aria-hidden><span className={`block h-full ${low ? "bg-warn" : "bg-accent"}`} style={{ width: `${pct}%` }} /></span>
              <span className="font-mono">{pct}%</span>
            </span>
            {low && <StatusBadge tone="warn" icon={<IconAlert />}>Low confidence: check this</StatusBadge>}
            {row.reason && <span className="min-w-0 flex-1 basis-40 text-muted">{row.reason}</span>}
          </div>
        </div>
      )}
      {error && <p role="alert" className="mt-2 flex items-start gap-1 text-sm text-bad"><IconAlert className="mt-0.5 shrink-0" />{error}</p>}
    </li>
  );
}
