import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { Catalog } from "../state/useCatalog";
import { useIncidentStream } from "../state/useIncidentStream";
import { readMock } from "../lib/config";
import { fmtDateTime } from "../lib/format";
import { CostTicker, Mimic } from "./Mimic";
import { TracePane } from "./Trace";
import { RcaPane } from "./Rca";
import { getPasscode, setPasscode as storePasscode } from "../lib/passcode";
import { adHocScenario, isUploadId, uploadLabel } from "../lib/uploadMapping";
import { PasscodeDialog } from "./PasscodeDialog";
import { IconAlert, IconClock, IconInfo, Spinner } from "./ui";

const EvidenceDrawer = lazy(() => import("./EvidenceDrawer").then((m) => ({ default: m.EvidenceDrawer })));

type Tab = "line" | "trace" | "rca";

export function Console({ catalog }: { catalog: Catalog }) {
  const mock = readMock();
  const { all, scenarios, replays, config } = catalog;
  // `/?scenario=U001&mode=live` arrives from the upload page: an ad-hoc scenario that is not in /api/scenarios.
  const urlScenario = useMemo(() => {
    const q = new URLSearchParams(window.location.search);
    const id = q.get("scenario");
    return id && /^[A-Za-z0-9_-]{1,32}$/.test(id) ? { id, live: q.get("mode") === "live" } : null;
  }, []);
  const [scenarioId, setScenarioId] = useState<string | null>(urlScenario?.id ?? null);
  const [mode, setMode] = useState<"replay" | "live">(urlScenario && isUploadId(urlScenario.id) ? "live" : "replay");
  const [runId, setRunId] = useState<string | null>(null);
  const [passcode, setPasscode] = useState<string | null>(getPasscode()); // memory only: never in URLs or storage
  const [askPass, setAskPass] = useState<string | null | false>(false); // false = closed, string|null = open with optional error
  const [evidence, setEvidence] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("line");
  const [notice, setNotice] = useState<string | null>(null);
  const [active, setActive] = useState<{ mode: "live" | "replay"; runId: string | null } | null>(null);
  const [speed, setSpeed] = useState(() => {
    const q = Number(new URLSearchParams(window.location.search).get("speed"));
    return q >= 1 && q <= 4 ? q : 1;
  });
  const fellBack = useRef(false);

  const adHoc = isUploadId(scenarioId);
  const scenario = useMemo(() => all.find((s) => s.id === scenarioId) ?? (adHoc && scenarioId ? adHocScenario(scenarioId) : null), [all, scenarioId, adHoc]);
  const { state, conn, httpError, start, abort, reset } = useIncidentStream(scenarioId, mode);

  // Default scenario: the first real-signal one with a recorded replay (the demo path).
  useEffect(() => {
    if (scenarioId || all.length === 0) return;
    const pick = all.find((s) => s.id === "R002") ?? all.find((s) => s.replay_run_ids.length) ?? all[0];
    setScenarioId(pick.id);
  }, [all, scenarioId]);

  const runs = scenario?.replay_run_ids ?? [];
  useEffect(() => {
    setRunId(runs[0] ?? null);
  }, [scenarioId]); // eslint-disable-line react-hooks/exhaustive-deps

  const liveAllowed = (!!config?.modes.live || (adHoc && !!mock)) && !config?.budget.exhausted;
  useEffect(() => {
    if (adHoc && mode !== "live") setMode("live"); // uploads have no recorded replay
  }, [adHoc, mode]);
  const streaming = conn === "connecting" || conn === "streaming" || conn === "reconnecting";
  const canReplay = runs.length > 0;
  const replayInfo = useMemo(() => replays.find((r) => r.run_id === active?.runId) ?? null, [replays, active]);

  const go = useCallback(
    async (m: "live" | "replay", run: string | null, pass: string | null) => {
      setNotice(null);
      setActive({ mode: m, runId: m === "replay" ? run : null });
      setTab("trace");
      fellBack.current = false;
      await start({ runId: run, passcode: pass, speed: m === "replay" ? speed : 1 });
    },
    [start, speed],
  );

  // Arriving from the upload page: start the live run at once with the in-memory passcode (ask if it is missing).
  const autoStarted = useRef(false);
  useEffect(() => {
    if (autoStarted.current || !urlScenario?.live || !isUploadId(urlScenario.id) || !config || scenarioId !== urlScenario.id) return;
    // Deferred and cancellable so React StrictMode's mount/unmount/mount in dev cannot abort the stream it just opened.
    const t = setTimeout(() => {
      autoStarted.current = true;
      if (passcode) void go("live", null, passcode);
      else setAskPass(null);
    }, 0);
    return () => clearTimeout(t);
  }, [config, scenarioId]); // eslint-disable-line react-hooks/exhaustive-deps

  function investigate() {
    if (mode === "live" && !passcode) {
      setAskPass(null);
      return;
    }
    void go(mode, runId, passcode);
  }

  // Wrong / missing passcode: ask again with the reason.
  useEffect(() => {
    if (httpError?.status === 401) {
      setPasscode(null);
      storePasscode(null);
      setAskPass("That passcode was not accepted. Try again, or use a recorded replay.");
    }
  }, [httpError]);

  // Budget exhausted: say why, then switch to a recorded replay automatically.
  const budgetHit = state.errors.some((e) => e.code === "budget_exhausted");
  const replayFor = useCallback(
    (sid: string | null) => {
      const s = all.find((x) => x.id === sid);
      if (s?.replay_run_ids.length) return { sid: s.id, run: s.replay_run_ids[0] };
      const alt = all.find((x) => x.replay_run_ids.length);
      return alt ? { sid: alt.id, run: alt.replay_run_ids[0] } : null;
    },
    [all],
  );
  useEffect(() => {
    if (!budgetHit || state.phase !== "done" || fellBack.current) return;
    fellBack.current = true;
    const r = replayFor(scenarioId);
    setMode("replay");
    if (!r) return;
    setNotice("The daily live-run budget is used up, so this is a recorded replay of a real earlier run instead. Live mode returns when the budget resets.");
    setScenarioId(r.sid);
    setRunId(r.run);
    setTimeout(() => {
      setActive({ mode: "replay", runId: r.run });
      void start({ runId: r.run, mockVariant: "ok" });
    }, 600);
  }, [budgetHit, state.phase]); // eslint-disable-line react-hooks/exhaustive-deps

  function offerReplay() {
    const r = replayFor(scenarioId);
    if (!r) return;
    setMode("replay");
    setScenarioId(r.sid);
    setRunId(r.run);
    void go("replay", r.run, null);
  }

  const showBudgetBanner = budgetHit || (config?.budget.exhausted ?? false);
  const idle = state.phase === "idle" && conn === "idle";
  const rcaReady = !!state.final;

  return (
    <>
      <div className="sticky top-0 z-20 border-b border-line bg-bg xl:hidden">
        <div role="tablist" aria-label="Console sections" className="flex">
          {(["line", "trace", "rca"] as Tab[]).map((t) => (
            <button
              key={t}
              role="tab"
              id={`tab-${t}`}
              aria-selected={tab === t}
              aria-controls={`pane-${t}`}
              type="button"
              onClick={() => setTab(t)}
              className={`min-h-[44px] flex-1 border-b-2 px-2 text-sm font-semibold ${tab === t ? "border-accent text-fg" : "border-transparent text-muted"}`}
            >
              {t === "line" ? "Line" : t === "trace" ? "Agent trace" : "Root cause"}
              {t === "rca" && rcaReady && <span className="ml-1 text-[11px] font-normal text-accent">· ready</span>}
              {t === "trace" && streaming && <span className="ml-1 text-[11px] font-normal text-accent">· live</span>}
            </button>
          ))}
        </div>
      </div>

      <main className="flex min-h-0 flex-1 flex-col xl:grid xl:grid-cols-[25fr_45fr_30fr] xl:grid-rows-[minmax(0,1fr)] xl:gap-px xl:bg-line">
        {/* ---- Left: line mimic ---- */}
        <section id="pane-line" role="tabpanel" aria-labelledby="tab-line" aria-label="Line and controls" className={`${tab === "line" ? "flex" : "hidden"} min-h-0 flex-1 relative flex-col overflow-y-auto bg-panel xl:flex xl:flex-none`}>
          <div className="space-y-3 p-3">
            <h2 className="label">Line L1 · stopped</h2>
            {catalog.error && (
              <p role="alert" className="flex items-start gap-2 rounded border border-bad p-2 text-sm"><IconAlert className="mt-0.5 shrink-0 text-bad" /><span><b className="text-bad">API unreachable.</b> {catalog.error}. Add <code className="font-mono">?mock=1</code> to the URL to play the recorded fixture offline.</span></p>
            )}
            <div>
              <label htmlFor="scenario" className="text-xs font-semibold">Stopped-line scenario</label>
              <select
                id="scenario"
                value={scenarioId ?? ""}
                disabled={streaming || (!scenarios && !adHoc)}
                onChange={(e) => {
                  setScenarioId(e.target.value);
                  reset();
                }}
                className="mt-1 w-full rounded border border-line bg-raised px-2 py-2 text-sm"
              >
                {adHoc && scenarioId && <optgroup label="Your upload"><option value={scenarioId}>{uploadLabel(scenarioId)}</option></optgroup>}
                {scenarios?.groups.map((g) => (
                  <optgroup key={g.id} label={g.id === "synthetic" ? "Synthetic scenarios" : "Real-signal scenarios"}>
                    {g.scenarios.map((s) => (
                      <option key={s.id} value={s.id}>
                        {s.title}
                        {s.replay_run_ids.length ? "  ▶ replay" : ""}
                      </option>
                    ))}
                  </optgroup>
                ))}
              </select>
              {scenario && (
                <p className="mt-1 text-[11px] text-muted">
                  {adHoc ? "Your data" : scenario.real_signal ? "Real signals" : "Simulated"} · <span className="font-mono">{scenario.source_label}</span>{scenario.stop_ts && <> · stop at {fmtDateTime(scenario.stop_ts)}</>}
                </p>
              )}
            </div>

            <fieldset className="space-y-1" disabled={streaming}>
              <legend className="text-xs font-semibold">Mode</legend>
              <div className="flex gap-2">
                <label className={`flex flex-1 items-center gap-2 rounded border px-2 py-1.5 text-sm ${mode === "replay" ? "border-accent" : "border-line"} ${adHoc ? "cursor-not-allowed opacity-60" : "cursor-pointer"}`}>
                  <input type="radio" name="mode" value="replay" checked={mode === "replay"} disabled={adHoc} onChange={() => setMode("replay")} className="accent-[rgb(var(--accent))]" />
                  Replay
                </label>
                <label className={`flex flex-1 items-center gap-2 rounded border px-2 py-1.5 text-sm ${mode === "live" ? "border-accent" : "border-line"} ${liveAllowed ? "cursor-pointer" : "cursor-not-allowed opacity-60"}`}>
                  <input type="radio" name="mode" value="live" checked={mode === "live"} disabled={!liveAllowed} onChange={() => setMode("live")} className="accent-[rgb(var(--accent))]" />
                  Run live
                </label>
              </div>
              {adHoc && <p className="text-[11px] text-muted" data-testid="no-replay-note">Replay is not available for uploaded data. This investigates your file live.</p>}
              {!liveAllowed && <p className="text-[11px] text-muted">{config?.budget.exhausted ? "Live is paused: today's budget is used up. Replays are free." : "Live runs are not enabled here."}</p>}
              {mode === "live" && liveAllowed && <p className="text-[11px] text-muted">Needs the demo passcode. Calls Gemini; costs real money.</p>}
              {mode === "replay" && runs.length > 1 && (
                <div>
                  <label htmlFor="run" className="text-xs font-semibold">Recorded run</label>
                  <select id="run" value={runId ?? ""} onChange={(e) => setRunId(e.target.value)} className="mt-1 w-full rounded border border-line bg-raised px-2 py-2 text-sm">
                    {runs.map((r) => {
                      const info = replays.find((x) => x.run_id === r);
                      return <option key={r} value={r}>{r}{info ? ` · ${info.label.slice(0, 48)}` : ""}</option>;
                    })}
                  </select>
                </div>
              )}
              {mode === "replay" && canReplay && (
                <div>
                  <label htmlFor="speed" className="text-xs font-semibold">Replay speed</label>
                  <select id="speed" value={speed} onChange={(e) => setSpeed(Number(e.target.value))} className="mt-1 w-full rounded border border-line bg-raised px-2 py-2 text-sm">
                    <option value={1}>1x (as recorded, long pauses capped)</option>
                    <option value={2}>2x</option>
                    <option value={4}>4x</option>
                  </select>
                </div>
              )}
              {mode === "replay" && !canReplay && <p className="text-[11px] text-warn">No recorded run for this scenario yet. Pick one marked ▶ replay, or run live.</p>}
            </fieldset>

            <div className="flex gap-2">
              {streaming ? (
                <button type="button" className="btn flex-1" onClick={abort}>Stop watching</button>
              ) : (
                <button type="button" className="btn-primary flex-1" onClick={investigate} disabled={!scenarioId || (mode === "replay" && !canReplay)}>
                  <IconBolt2 />{state.phase === "done" || conn === "dropped" ? "Investigate again" : "Investigate stop"}
                </button>
              )}
            </div>

            <Mimic state={state} stoppedFallback={scenario?.stopped_station ?? null} />
            <CostTicker running={state.phase === "streaming" && conn !== "dropped"} startKey={state.incidentId} />
          </div>
        </section>

        {/* ---- Centre: trace ---- */}
        <section id="pane-trace" role="tabpanel" aria-labelledby="tab-trace" aria-label="Agent trace" className={`${tab === "trace" ? "flex" : "hidden"} min-h-0 flex-1 flex-col bg-panel xl:flex xl:flex-none`}>
          <Banners
            mode={active?.mode ?? null}
            replayInfo={replayInfo}
            runId={active?.runId ?? null}
            conn={conn}
            httpErrorMsg={httpError && httpError.status !== 401 ? describeHttp(httpError.status, httpError.code, httpError.message, httpError.retryAfter) : null}
            notice={notice}
            showBudgetBanner={showBudgetBanner && !notice}
            canOfferReplay={!!replayFor(scenarioId)}
            onOfferReplay={offerReplay}
            idle={idle}
          />
          <TracePane state={state} onEvidence={setEvidence} />
        </section>

        {/* ---- Right: RCA + action ---- */}
        <section id="pane-rca" tabIndex={-1} role="tabpanel" aria-labelledby="tab-rca" aria-label="Root cause and action" className={`${tab === "rca" ? "flex" : "hidden"} min-h-0 flex-1 flex-col bg-panel xl:flex xl:flex-none`}>
          <RcaPane key={state.incidentId ?? "none"} state={state} passcode={state.mode === "live" ? passcode : null} isMock={!!mock} onEvidence={setEvidence} />
        </section>
      </main>

      {/* Announcements for screen readers: verified root cause, rejected claims, errors. */}
      <div aria-live="polite" aria-atomic="false" className="sr-only" data-testid="announcer">
        {state.announcements.slice(-6).map((a) => (
          <p key={a.id}>{a.text}</p>
        ))}
      </div>

      {evidence && <Suspense fallback={null}><EvidenceDrawer state={state} evidenceId={evidence} scenarioId={state.scenarioId ?? scenarioId} isMock={!!mock} onClose={() => setEvidence(null)} /></Suspense>}
      {askPass !== false && (
        <PasscodeDialog
          error={askPass}
          onCancel={() => setAskPass(false)}
          onSubmit={(p) => {
            setPasscode(p);
            storePasscode(p);
            setAskPass(false);
            void go("live", null, p);
          }}
        />
      )}
    </>
  );
}

const IconBolt2 = () => <span aria-hidden className="font-mono">▶</span>;

function describeHttp(status: number, code: string, message: string, retryAfter: number | null): string {
  if (status === 429) return `Too many requests (${code}). ${retryAfter ? `Try again in ${retryAfter} s. ` : ""}${message}`;
  if (status === 404 && code === "no_replay") return "There is no recorded run for this scenario. Choose one marked ▶ replay.";
  if (status === 403) return `Live mode is not available: ${message}`;
  if (status === 0) return "Cannot reach the API. Check your connection, or add ?mock=1 to play the recorded fixture.";
  return `${code}: ${message}`;
}

function Banners(p: {
  mode: "live" | "replay" | null;
  replayInfo: { run_id: string; recorded_at: string; label: string } | null;
  runId: string | null;
  conn: string;
  httpErrorMsg: string | null;
  notice: string | null;
  showBudgetBanner: boolean;
  canOfferReplay: boolean;
  onOfferReplay: () => void;
  idle: boolean;
}) {
  return (
    <div className="space-y-px">
      {p.mode === "replay" && p.runId && (
        <div className="flex items-start gap-2 border-b border-line bg-raised px-3 py-1.5 text-xs" data-testid="replay-banner">
          <IconClock className="mt-0.5 shrink-0 text-muted" />
          <span>
            <b>Replay</b> of run <span className="font-mono">#{p.runId}</span>
            {p.replayInfo ? <> recorded <span className="font-mono">{fmtDateTime(p.replayInfo.recorded_at)}</span>. {p.replayInfo.label}</> : " (recorded earlier). Events are the originals; only timing is replayed."}
          </span>
        </div>
      )}
      {p.mode === "live" && (
        <div className="border-b border-line bg-raised px-3 py-1.5 text-xs" data-testid="live-banner"><b>Live run.</b> Agents are calling Gemini now.</div>
      )}
      {p.notice && (
        <div role="status" className="flex items-start gap-2 border-b border-warn bg-warn/10 px-3 py-2 text-sm" data-testid="budget-notice"><IconInfo className="mt-0.5 shrink-0 text-warn" /><span><b className="text-warn">Budget exhausted: switched to replay.</b> {p.notice}</span></div>
      )}
      {p.showBudgetBanner && (
        <div className="flex items-start gap-2 border-b border-line px-3 py-1.5 text-xs text-muted"><IconInfo className="mt-0.5 shrink-0" />Live budget for today is used up; recorded replays still work.</div>
      )}
      {p.conn === "reconnecting" && (
        <div role="status" className="flex items-center gap-2 border-b border-warn bg-warn/10 px-3 py-2 text-sm" data-testid="reconnecting"><Spinner label="reconnecting" /><b className="text-warn">Connection lost, reconnecting…</b></div>
      )}
      {p.conn === "dropped" && (
        <div role="alert" className="flex flex-wrap items-center gap-2 border-b border-bad bg-bad/10 px-3 py-2 text-sm" data-testid="dropped">
          <IconAlert className="text-bad" />
          <span className="flex-1"><b className="text-bad">Stream dropped.</b> The partial trace above is kept. A live run is never restarted automatically because that would bill a second run.</span>
          {p.canOfferReplay && <button type="button" className="btn" onClick={p.onOfferReplay}>Play the recorded replay</button>}
        </div>
      )}
      {p.httpErrorMsg && (
        <div role="alert" className="flex items-start gap-2 border-b border-bad bg-bad/10 px-3 py-2 text-sm" data-testid="http-error"><IconAlert className="mt-0.5 shrink-0 text-bad" /><span>{p.httpErrorMsg}</span></div>
      )}
    </div>
  );
}
