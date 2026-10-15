import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { Catalog } from "../state/useCatalog";
import { useIncidentStream } from "../state/useIncidentStream";
import { readMock } from "../lib/config";
import { fmtDateTime } from "../lib/format";
import { CostTicker, Mimic } from "./Mimic";
import { claimState, claimsOf, type IncidentState } from "../state/reducer";
import { IconArrowRight, IconCheck as IconCheckK } from "./ui";
import { TracePane } from "./Trace";
import { RcaPane } from "./Rca";
import { getPasscode, setPasscode as storePasscode } from "../lib/passcode";
import { adHocScenario, isUploadId, uploadLabel } from "../lib/uploadMapping";
import { setHandoff, techHref } from "../lib/handoff";
import { langEnabled, techEnabled } from "../lib/features";
import { PasscodeDialog } from "./PasscodeDialog";
import { IconAlert, IconClock, IconInfo, IconPlay, IconStop, Spinner } from "./ui";
import { motion } from "motion/react";
import { Stepper } from "./Stepper";
import { investigationSteps, runStatus, type Decided } from "../lib/progress";
import { publishRun, resetRun } from "../lib/runStore";
import { useHotkeys } from "../lib/hotkeys";

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
  const [decided, setDecided] = useState<Decided>(null);

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

  const techLink = useMemo(() => {
    if (!techEnabled(config) || !state.final || !state.incidentId) return null;
    const href = techHref(state.incidentId, state.scenarioId ?? scenarioId);
    return {
      href,
      onOpen: () => {
        // State travels in memory: no refetch, no re-run.
        setHandoff({ state, scenarioId: state.scenarioId ?? scenarioId, mode: state.mode ?? "replay", passcode });
        window.history.pushState({}, "", href);
        window.dispatchEvent(new PopStateEvent("popstate"));
      },
    };
  }, [config, state, scenarioId, passcode]);

  useEffect(() => setDecided(null), [state.incidentId]);
  const steps = useMemo(() => investigationSteps(state, decided, conn), [state, decided, conn]);
  useEffect(() => publishRun({ ...runStatus(state, decided, conn), steps, scenario: scenario?.title ?? null }), [state, decided, conn, steps, scenario]);
  useEffect(() => resetRun, []);
  const canInvestigate = !streaming && !!scenarioId && !(mode === "replay" && !canReplay);
  const focusPane = (t: Tab) => {
    setTab(t);
    requestAnimationFrame(() => document.getElementById(`pane-${t}`)?.querySelector<HTMLElement>("[role=region], select, button")?.focus());
  };
  useHotkeys({
    i: () => canInvestigate && investigate(),
    "1": () => focusPane("line"),
    "2": () => focusPane("trace"),
    "3": () => focusPane("rca"),
  });

  const showBudgetBanner = budgetHit || (config?.budget.exhausted ?? false);
  const idle = state.phase === "idle" && conn === "idle";
  const rcaReady = !!state.final;

  return (
    <>
      <div className="lg:hidden"><Stepper steps={steps} /></div>
      <Kpis state={state} running={state.phase === "streaming" && conn !== "dropped"} />
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
              className={`relative min-h-[44px] flex-1 whitespace-nowrap px-2 text-sm font-semibold transition-colors ${tab === t ? "text-fg" : "text-muted hover:text-fg"}`}
            >
              {tab === t && <motion.span layoutId="console-tab" aria-hidden className="absolute inset-x-3 bottom-0 h-0.5 rounded-full bg-accent" />}
              {t === "line" ? "Line" : t === "trace" ? "Agent trace" : "Root cause"}
              {t === "rca" && rcaReady && <><span aria-hidden className="ml-1.5 inline-block h-1.5 w-1.5 rounded-full bg-ok align-middle" /><span className="sr-only"> · ready</span></>}
              {t === "trace" && streaming && <><span aria-hidden className="blink ml-1.5 inline-block h-1.5 w-1.5 rounded-full bg-accent align-middle" /><span className="sr-only"> · live</span></>}
            </button>
          ))}
        </div>
      </div>

      <main className="flex min-h-0 flex-1 flex-col xl:grid xl:grid-cols-[minmax(300px,24fr)_44fr_minmax(380px,32fr)] xl:grid-rows-[minmax(0,1fr)] xl:gap-4 xl:pb-3 xl:pl-4 xl:pr-3">
        {/* ---- Left: line mimic ---- */}
        <section id="pane-line" role="tabpanel" aria-labelledby="tab-line" aria-label="Line and controls" className={`${tab === "line" ? "flex" : "hidden"} min-h-0 flex-1 relative flex-col overflow-y-auto xl:flex xl:flex-none`}>
          <div className="space-y-4 p-4 xl:p-0">
            <div className="card space-y-3 p-3">
            <div className="flex items-center justify-between">
              <h2 className="label">Incident</h2>
              <span className="inline-flex items-center gap-1.5 rounded-full bg-bad/10 px-2 py-0.5 text-[11px] font-semibold text-bad">
                <span aria-hidden className="h-1.5 w-1.5 rounded-full bg-bad" />Line L1 · stopped
              </span>
            </div>
            {catalog.error && (
              <p role="alert" className="flex items-start gap-2 rounded-lg border border-bad bg-bad/10 p-2 text-sm"><IconAlert className="mt-0.5 shrink-0 text-bad" /><span><b className="text-bad">API unreachable.</b> {catalog.error}. Add <code className="font-mono">?mock=1</code> to the URL to play the recorded fixture offline.</span></p>
            )}
            <div>
              <label htmlFor="scenario" className="text-xs font-semibold text-muted">Stopped-line scenario</label>
              <select
                id="scenario"
                value={scenarioId ?? ""}
                disabled={streaming || (!scenarios && !adHoc)}
                onChange={(e) => {
                  setScenarioId(e.target.value);
                  reset();
                }}
                className="field mt-1"
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
                <p className="mt-1.5 flex flex-wrap items-center gap-x-1.5 gap-y-1 text-[11px] text-muted">
                  <span className={`chip ${adHoc ? "border-dashed border-accent text-accent" : scenario.real_signal ? "border-fg/70 font-semibold text-fg" : "border-transparent bg-raised"}`}>{adHoc ? "Your data" : scenario.real_signal ? "Real signals" : "Simulated"}</span>
                  <span className="font-mono">{scenario.source_label}</span>{scenario.stop_ts && <span>· stop at {fmtDateTime(scenario.stop_ts)}</span>}
                </p>
              )}
            </div>

            <fieldset className="space-y-1" disabled={streaming}>
              <legend className="mb-1 text-xs font-semibold text-muted">Mode</legend>
              <div className="seg">
                <label>
                  <input type="radio" name="mode" value="replay" checked={mode === "replay"} disabled={adHoc} onChange={() => setMode("replay")} />
                  <IconClock className="h-3.5 w-3.5" aria-hidden />
                  Replay
                </label>
                <label>
                  <input type="radio" name="mode" value="live" checked={mode === "live"} disabled={!liveAllowed} onChange={() => setMode("live")} />
                  <span aria-hidden className={`h-1.5 w-1.5 rounded-full ${mode === "live" ? "bg-bad blink" : "bg-muted"}`} />
                  Run live
                </label>
              </div>
              {adHoc && <p className="text-[11px] text-muted" data-testid="no-replay-note">Replay is not available for uploaded data. This investigates your file live.</p>}
              {!liveAllowed && <p className="text-[11px] text-muted">{config?.budget.exhausted ? "Live is paused: today's budget is used up. Replays are free." : "Live runs are not enabled here."}</p>}
              {mode === "live" && liveAllowed && <p className="text-[11px] text-muted">Needs the demo passcode. Calls Gemini; costs real money.</p>}
              {mode === "replay" && runs.length > 1 && (
                <div>
                  <label htmlFor="run" className="text-xs font-semibold text-muted">Recorded run</label>
                  <select id="run" value={runId ?? ""} onChange={(e) => setRunId(e.target.value)} className="field mt-1">
                    {runs.map((r) => {
                      const info = replays.find((x) => x.run_id === r);
                      return <option key={r} value={r}>{r}{info ? ` · ${info.label.slice(0, 48)}` : ""}</option>;
                    })}
                  </select>
                </div>
              )}
              {mode === "replay" && canReplay && (
                <div role="radiogroup" aria-labelledby="speed-label" className="pt-1">
                  <span id="speed-label" className="mb-1 block text-xs font-semibold text-muted">Replay speed</span>
                  <div className="seg">
                    {[1, 2, 4].map((x) => (
                      <label key={x} title={x === 1 ? "As recorded, long pauses capped" : undefined}>
                        <input type="radio" name="speed" value={x} checked={speed === x} onChange={() => setSpeed(x)} aria-label={x === 1 ? "1x, as recorded with long pauses capped" : `${x}x`} />
                        <span className="font-mono">{x}×</span>
                      </label>
                    ))}
                  </div>
                  <p className="mt-1 text-[11px] text-muted">1× plays as recorded, long pauses capped.</p>
                </div>
              )}
              {mode === "replay" && !canReplay && <p className="text-[11px] text-warn">No recorded run for this scenario yet. Pick one marked ▶ replay, or run live.</p>}
            </fieldset>

            <div className="flex gap-2">
              {streaming ? (
                <button type="button" className="btn !min-h-[44px] flex-1" onClick={abort}><IconStop className="h-3.5 w-3.5 text-bad" />Stop watching</button>
              ) : (
                <button type="button" className="btn-primary group !min-h-[44px] flex-1 !text-[15px]" onClick={investigate} disabled={!canInvestigate} aria-keyshortcuts="i">
                  <IconPlay className="h-4 w-4" />{state.phase === "done" || conn === "dropped" ? "Investigate again" : "Investigate stop"}
                  <span aria-hidden className="ml-1 hidden rounded border border-bg/30 px-1 font-mono text-[10px] leading-4 opacity-70 sm:inline">I</span>
                </button>
              )}
            </div>
            </div>

            <Mimic state={state} stoppedFallback={scenario?.stopped_station ?? null} />
          </div>
        </section>

        {/* ---- Centre: trace ---- */}
        <section id="pane-trace" role="tabpanel" aria-labelledby="tab-trace" aria-label="Agent trace" className={`${tab === "trace" ? "flex" : "hidden"} min-h-0 flex-1 flex-col overflow-hidden bg-panel xl:flex xl:flex-none xl:rounded-2xl`}>
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
        <section id="pane-rca" tabIndex={-1} role="tabpanel" aria-labelledby="tab-rca" aria-label="Root cause and action" className={`${tab === "rca" ? "flex" : "hidden"} min-h-0 flex-1 flex-col overflow-hidden bg-panel xl:flex xl:flex-none xl:rounded-2xl`}>
          <RcaPane key={state.incidentId ?? "none"} onDecided={setDecided} state={state} passcode={state.mode === "live" ? passcode : null} isMock={!!mock} onEvidence={setEvidence} techLink={techLink} langEnabled={langEnabled(config)} />
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
        <div className="flex items-start gap-2 border-b border-line bg-raised/60 px-4 py-2 text-xs" data-testid="replay-banner">
          <IconClock className="mt-0.5 shrink-0 text-muted" />
          <span>
            <b>Replay</b> of run <span className="font-mono">#{p.runId}</span>
            {p.replayInfo ? <> recorded <span className="font-mono">{fmtDateTime(p.replayInfo.recorded_at)}</span>. {p.replayInfo.label}</> : " (recorded earlier). Events are the originals; only timing is replayed."}
          </span>
        </div>
      )}
      {p.mode === "live" && (
        <div className="flex items-center gap-2 border-b border-bad/30 bg-bad/5 px-4 py-2 text-xs" data-testid="live-banner"><span aria-hidden className="h-2 w-2 rounded-full bg-bad blink" /><span><b>Live run.</b> Agents are calling Gemini now.</span></div>
      )}
      {p.notice && (
        <div role="status" className="flex items-start gap-2 border-b border-warn bg-warn/10 px-4 py-2 text-sm" data-testid="budget-notice"><IconInfo className="mt-0.5 shrink-0 text-warn" /><span><b className="text-warn">Budget exhausted: switched to replay.</b> {p.notice}</span></div>
      )}
      {p.showBudgetBanner && (
        <div className="flex items-start gap-2 border-b border-line px-3 py-1.5 text-xs text-muted"><IconInfo className="mt-0.5 shrink-0" />Live budget for today is used up; recorded replays still work.</div>
      )}
      {p.conn === "reconnecting" && (
        <div role="status" className="flex items-center gap-2 border-b border-warn bg-warn/10 px-4 py-2 text-sm" data-testid="reconnecting"><Spinner label="reconnecting" /><b className="text-warn">Connection lost, reconnecting…</b></div>
      )}
      {p.conn === "dropped" && (
        <div role="alert" className="flex flex-wrap items-center gap-2 border-b border-bad bg-bad/10 px-4 py-2 text-sm" data-testid="dropped">
          <IconAlert className="text-bad" />
          <span className="flex-1"><b className="text-bad">Stream dropped.</b> The partial trace above is kept. A live run is never restarted automatically because that would bill a second run.</span>
          {p.canOfferReplay && <button type="button" className="btn" onClick={p.onOfferReplay}>Play the recorded replay</button>}
        </div>
      )}
      {p.httpErrorMsg && (
        <div role="alert" className="flex items-start gap-2 border-b border-bad bg-bad/10 px-4 py-2 text-sm" data-testid="http-error"><IconAlert className="mt-0.5 shrink-0 text-bad" /><span>{p.httpErrorMsg}</span></div>
      )}
    </div>
  );
}

/** Pastel KPI tiles, after the kit's top row. Every number is read from the stream or labelled as an assumption. */
function Kpis({ state, running }: { state: IncidentState; running: boolean }) {
  const report = state.final ?? state.draft;
  const claims = claimsOf(report);
  const verified = claims.filter((c) => claimState(state.verdicts, c.claim_id) === "verified").length;
  const caught = state.revisions.reduce((n, r) => n + r.rejected.length, 0);
  const real = state.toolOrder.filter((id) => state.tools[id]?.provenance.some((p) => p.real)).length;
  const top = state.final?.status === "verified" ? state.final.hypotheses[0] : null;
  return (
    <section aria-label="Incident at a glance" className="flex shrink-0 snap-x gap-3 overflow-x-auto px-4 py-3 [scrollbar-width:none] sm:grid sm:grid-cols-2 sm:overflow-visible sm:px-3 lg:gap-4 lg:pl-4 lg:pr-3 lg:pt-4 xl:grid-cols-4 [&>div]:min-w-[168px] [&>div]:snap-start [&>div]:max-sm:p-3">
      <h2 className="sr-only">Incident at a glance</h2>
      <CostTicker running={running} startKey={state.incidentId} />
      <div className="kpi kpi-2" data-testid="kpi-evidence">
        <p className="text-sm font-semibold">Evidence</p>
        <div className="mt-2 flex items-end justify-between gap-2">
          <span className="text-2xl font-semibold leading-none tabular-nums">{state.toolOrder.length}</span>
          <span className="kpi-muted text-xs">{real ? `${real} on REAL signals` : "tool calls"}</span>
        </div>
      </div>
      <div className="kpi kpi-1" data-testid="kpi-claims">
        <p className="text-sm font-semibold">Claims verified</p>
        <div className="mt-2 flex items-end justify-between gap-2">
          <span className="text-2xl font-semibold leading-none tabular-nums">{claims.length ? `${verified}/${claims.length}` : "–"}</span>
          {caught > 0 ? (
            <span className="kpi-muted inline-flex items-center gap-1 text-xs">{caught} caught <IconArrowRight className="h-3 w-3 -rotate-45" /></span>
          ) : (
            <span className="kpi-muted text-xs">checked by code</span>
          )}
        </div>
      </div>
      <div className="kpi kpi-2" data-testid="kpi-root">
        <p className="text-sm font-semibold">Root cause</p>
        <div className="mt-2 flex items-end justify-between gap-2">
          <span className="text-2xl font-semibold leading-none tabular-nums">{top ? `${Math.round(top.confidence * 100)}%` : "–"}</span>
          <span className="kpi-muted inline-flex min-w-0 items-center gap-1 truncate text-xs">
            {top ? <><IconCheckK className="h-3 w-3 shrink-0" /><span className="truncate font-mono">{top.asset_id}</span></> : state.final ? "insufficient evidence" : "not yet verified"}
          </span>
        </div>
      </div>
    </section>
  );
}
