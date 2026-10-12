import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import type { Catalog } from "../state/useCatalog";
import { useIncidentStream } from "../state/useIncidentStream";
import { useApproval, type Decision } from "../state/useApproval";
import { getHandoff } from "../lib/handoff";
import { getPasscode, setPasscode as storePasscode } from "../lib/passcode";
import { readMock } from "../lib/config";
import { techEnabled } from "../lib/features";
import { fmtDateTime, humanize } from "../lib/format";
import { progressLine, rootCauseSentence, topVerifiedClaims, plainClaimText } from "../lib/techSummary";
import { PasscodeDialog } from "../components/PasscodeDialog";
import { VoicePanel, fmtClock } from "../components/Voice";
import { IconAlert, IconCheck, IconClock, IconInfo, IconLock, IconX, Spinner, StatusBadge } from "../components/ui";

const STEPS = ["Pick", "Stopped", "Root cause", "Safety", "Approve"] as const;
const PICK = 0, STOPPED = 1, CAUSE = 2, SAFETY = 3, APPROVE = 4;

const inputCls = "mt-1 w-full rounded-md border border-line bg-raised px-3 py-3 text-base";
const bigBtn = "!min-h-[56px] !text-base";

export function TechPage({ catalog }: { catalog: Catalog }) {
  if (!catalog.loading && !techEnabled(catalog.config)) {
    return (
      <main className="flex flex-1 items-center justify-center p-6" data-testid="tech-disabled">
        <div className="card max-w-sm p-5 text-center">
          <IconInfo className="mx-auto h-6 w-6 text-muted" />
          <h2 className="mt-2 text-lg font-semibold">Not enabled on this deployment</h2>
          <p className="mt-1 text-sm text-muted">The technician view is a stretch feature and is switched off here. The console has the full investigation.</p>
        </div>
      </main>
    );
  }
  if (catalog.loading) return <p className="p-4 text-sm text-muted">Loading…</p>;
  return <TechFlow catalog={catalog} />;
}

function TechFlow({ catalog }: { catalog: Catalog }) {
  const isMock = !!readMock();
  const { all, scenarios, config } = catalog;
  const params = useMemo(() => new URLSearchParams(window.location.search), []);
  const handoff = useMemo(() => getHandoff(params.get("incident")), [params]);
  const urlScenario = params.get("scenario");

  const [scenarioId, setScenarioId] = useState<string | null>(handoff?.scenarioId ?? urlScenario ?? null);
  const [mode, setMode] = useState<"replay" | "live">(handoff?.mode ?? "replay");
  const [passcode, setPasscode] = useState<string | null>(handoff?.passcode ?? getPasscode());
  const [askPass, setAskPass] = useState<string | null | false>(false);
  const [step, setStep] = useState<number>(handoff?.state.final ? CAUSE : PICK);
  const [maxStep, setMaxStep] = useState(step);
  const [decision, setDecision] = useState<Decision | null>(null);
  const [edits, setEdits] = useState("");
  const [announce, setAnnounce] = useState("");

  const { state, conn, httpError, start, abort, reset } = useIncidentStream(scenarioId, mode, handoff?.state);
  const scenario = all.find((s) => s.id === scenarioId) ?? null;
  const runs = scenario?.replay_run_ids ?? [];
  const streaming = conn === "connecting" || conn === "streaming" || conn === "reconnecting";
  const insufficient = state.final?.status === "insufficient_evidence";
  const top = state.final?.hypotheses[0] ?? null;

  const approval = useApproval({
    wo: state.workOrder,
    incidentId: state.incidentId,
    decision,
    edits,
    enabled: !!state.final && !insufficient,
    passcode: state.mode === "live" ? passcode : null,
    isMock,
  });

  const go = useCallback(
    async (m: "live" | "replay", pass: string | null) => {
      if (!scenarioId) return;
      setDecision(null);
      setEdits("");
      setStep(STOPPED);
      setMaxStep((x) => Math.max(x, STOPPED));
      await start({ runId: m === "replay" ? runs[0] ?? null : null, passcode: pass, speed: m === "replay" ? 2 : 1 });
    },
    [scenarioId, runs, start],
  );

  // Arrived without handed-over state but with a scenario: start a replay of it (deferred so StrictMode cannot abort it).
  const auto = useRef(false);
  useEffect(() => {
    if (handoff || auto.current || !urlScenario || all.length === 0) return;
    const s = all.find((x) => x.id === urlScenario);
    if (!s || s.replay_run_ids.length === 0) return;
    const t = setTimeout(() => {
      auto.current = true;
      setScenarioId(s.id);
      setStep(STOPPED);
      setMaxStep(STOPPED);
      void start({ runId: s.replay_run_ids[0], speed: 2 });
    }, 0);
    return () => clearTimeout(t);
  }, [all]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (httpError?.status === 401) {
      setPasscode(null);
      storePasscode(null);
      setAskPass("That passcode was not accepted. Try again, or use a recorded replay.");
    }
  }, [httpError]);

  // Announce card changes and the verified root cause.
  const heading = useRef<HTMLHeadingElement>(null);
  const first = useRef(true);
  useEffect(() => {
    setAnnounce(`Step ${step + 1} of ${STEPS.length}: ${STEPS[step]}`);
    if (first.current) first.current = false;
    else heading.current?.focus();
  }, [step]);
  const announcedFinal = useRef(false);
  useEffect(() => {
    if (state.final && top && !insufficient && !announcedFinal.current) {
      announcedFinal.current = true;
      setAnnounce(`Verified root cause: ${rootCauseSentence(top)}, confidence ${Math.round(top.confidence * 100)} percent.`);
    }
    if (!state.final) announcedFinal.current = false;
  }, [state.final, top, insufficient]);

  const goTo = (n: number) => {
    setStep(n);
    setMaxStep((x) => Math.max(x, n));
  };

  const decidedWo = approval.decided;
  const nextState: { label: string; ok: boolean; hint: string; to: number } | null = (() => {
    switch (step) {
      case STOPPED:
        return state.final
          ? { label: "Root cause", ok: true, hint: "", to: CAUSE }
          : { label: "Root cause", ok: false, hint: streaming ? "Waiting for the verified root cause…" : "No root cause yet.", to: CAUSE };
      case CAUSE:
        if (insufficient) return null;
        if (decision === "reject") return { label: "Record rejection", ok: true, hint: "", to: APPROVE };
        return { label: "Safety checklist", ok: decision === "accept" || decision === "edit", hint: "Accept or edit the root cause to continue.", to: SAFETY };
      case SAFETY: {
        const miss: string[] = [];
        if (!approval.allTicked) miss.push(`tick all ${approval.safety.length} safety steps (${approval.ticked.size}/${approval.safety.length})`);
        if (!approval.name.trim()) miss.push("enter the approver name");
        return { label: "Approve", ok: !!state.workOrder && miss.length === 0, hint: state.workOrder ? `Locked until you ${miss.join(" and ")}.` : "Waiting for the draft work order…", to: APPROVE };
      }
      default:
        return null;
    }
  })();
  const backTo = step === APPROVE && decision === "reject" ? CAUSE : step - 1;

  const disabledLive = !config?.modes.live || !!config?.budget.exhausted;

  return (
    <div className="flex min-h-0 flex-1 flex-col" data-testid="tech-page">
      <Dots step={step} maxStep={maxStep} />
      <div className="min-h-0 flex-1 overflow-y-auto">
        <div className="mx-auto w-full max-w-xl space-y-3 p-3">
          {step === PICK && (
            <section className="card space-y-4 p-4" aria-labelledby="tech-h">
              <h2 id="tech-h" ref={heading} tabIndex={-1} className="text-xl font-semibold">Pick a stopped line</h2>
              <div>
                <label htmlFor="t-scenario" className="text-sm font-semibold">Scenario</label>
                <select id="t-scenario" value={scenarioId ?? ""} onChange={(e) => { setScenarioId(e.target.value || null); reset(); }} className={inputCls}>
                  <option value="">Choose…</option>
                  {scenarios?.groups.map((g) => (
                    <optgroup key={g.id} label={g.id === "synthetic" ? "Synthetic scenarios" : "Real-signal scenarios"}>
                      {g.scenarios.map((s) => (
                        <option key={s.id} value={s.id}>{s.title}{s.replay_run_ids.length ? "  ▶ replay" : ""}</option>
                      ))}
                    </optgroup>
                  ))}
                </select>
              </div>
              <fieldset>
                <legend className="text-sm font-semibold">Mode</legend>
                <div className="mt-1 grid grid-cols-2 gap-2">
                  <label className={`flex min-h-[52px] cursor-pointer items-center gap-2 rounded-md border px-3 ${mode === "replay" ? "border-accent" : "border-line"}`}>
                    <input type="radio" name="t-mode" checked={mode === "replay"} onChange={() => setMode("replay")} className="h-5 w-5 accent-[rgb(var(--accent))]" />Replay
                  </label>
                  <label className={`flex min-h-[52px] items-center gap-2 rounded-md border px-3 ${mode === "live" ? "border-accent" : "border-line"} ${disabledLive ? "cursor-not-allowed opacity-60" : "cursor-pointer"}`}>
                    <input type="radio" name="t-mode" checked={mode === "live"} disabled={disabledLive} onChange={() => setMode("live")} className="h-5 w-5 accent-[rgb(var(--accent))]" />Run live
                  </label>
                </div>
                <p className="mt-1 text-xs text-muted">{mode === "live" ? "Needs the demo passcode. Calls Gemini and costs real money." : "Plays a recorded real run. Free, no passcode."}</p>
              </fieldset>
              {scenario && mode === "replay" && runs.length === 0 && <p className="text-sm text-warn">No recorded run for this scenario. Pick one marked ▶ replay, or run live.</p>}
              <button
                type="button"
                className={`btn-primary w-full ${bigBtn}`}
                disabled={!scenarioId || (mode === "replay" && runs.length === 0)}
                onClick={() => {
                  if (mode === "live" && !passcode) setAskPass(null);
                  else void go(mode, passcode);
                }}
              >
                <span aria-hidden>▶</span> Start
              </button>
            </section>
          )}

          {step === STOPPED && (
            <StoppedCard
              state={state}
              scenarioTitle={scenario?.title ?? null}
              stopTs={scenario?.stop_ts ?? null}
              sourceLabel={scenario?.source_label ?? null}
              real={!!scenario?.real_signal}
              fallbackStation={scenario?.stopped_station ?? null}
              streaming={streaming}
              conn={conn}
              httpMsg={httpError && httpError.status !== 401 ? `${httpError.code}: ${httpError.message}` : null}
              heading={heading}
              canReplay={runs.length > 0 || all.some((s) => s.replay_run_ids.length)}
              onReplay={() => { const s = scenario && scenario.replay_run_ids.length ? scenario : all.find((x) => x.replay_run_ids.length); if (s) { setScenarioId(s.id); setMode("replay"); abort(); void start({ runId: s.replay_run_ids[0], speed: 2 }); } }}
            />
          )}

          {step === CAUSE && (
            <CauseCard heading={heading} state={state} insufficient={insufficient} decision={decision} setDecision={setDecision} edits={edits} setEdits={setEdits} />
          )}

          {step === SAFETY && (
            <section className="card space-y-3 p-3" aria-labelledby="tech-h" data-testid="card-safety">
              <div className="sticky top-0 z-10 -mx-3 -mt-3 flex items-baseline justify-between gap-2 rounded-t-md border-b border-line bg-panel px-3 py-2">
                <h2 id="tech-h" ref={heading} tabIndex={-1} className="text-xl font-semibold">Safety checklist</h2>
                <p className="font-mono text-2xl font-semibold tabular-nums" aria-live="polite" data-testid="safety-count">
                  <span className="sr-only">Ticked </span>{approval.ticked.size} / {approval.safety.length}
                </p>
              </div>
              {!state.workOrder ? (
                <p className="flex items-center gap-2 text-sm"><Spinner label="drafting" />The draft work order is still arriving…</p>
              ) : (
                <>
                  <p className="text-xs text-muted">Lockout/tagout steps are quoted verbatim from the manual. Tick each one as you complete it. Nothing here is paraphrased.</p>
                  <ol className="space-y-2" aria-label="Lockout and tagout steps">
                    {approval.safety.map((s) => {
                      const on = approval.ticked.has(s.order);
                      return (
                        <li key={s.order}>
                          <label className={`flex min-h-[56px] cursor-pointer items-start gap-3 rounded-md border-2 p-3 ${on ? "border-ok" : "border-warn/70"}`} data-safety-step={s.order}>
                            <input type="checkbox" checked={on} onChange={(e) => approval.toggle(s.order, e.target.checked)} disabled={!!decidedWo} className="mt-0.5 h-7 w-7 shrink-0 accent-[rgb(var(--accent))]" />
                            <span className="min-w-0">
                              <span className="flex items-center gap-1 font-mono text-[11px] font-semibold uppercase text-warn"><IconLock className="h-3 w-3" />LOTO step {s.order}{on && <span className="text-ok"> · done</span>}</span>
                              <span className="block text-base">{s.text}</span>
                              {s.citation && <span className="mt-0.5 block font-mono text-xs text-muted">{s.citation.doc} · p.{s.citation.page}</span>}
                            </span>
                          </label>
                        </li>
                      );
                    })}
                  </ol>
                  <div>
                    <label htmlFor="t-approver" className="text-sm font-semibold">Approver name</label>
                    <input id="t-approver" value={approval.name} onChange={(e) => approval.setName(e.target.value)} maxLength={80} autoComplete="name" className={inputCls} />
                  </div>
                </>
              )}
            </section>
          )}

          {step === APPROVE && (
            <section className="card space-y-3 p-3" aria-labelledby="tech-h" data-testid="card-approve" data-wo-status={decidedWo ?? "PENDING_APPROVAL"}>
              <h2 id="tech-h" ref={heading} tabIndex={-1} className="text-xl font-semibold">{decision === "reject" ? "Record rejection" : "Approve work order"}</h2>
              {top && <p className="text-base"><b>{rootCauseSentence(top)}</b>{state.workOrder && <> · <span className="font-mono text-sm">{state.workOrder.wo_id}</span></>}</p>}
              {state.workOrder && (
                <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-sm">
                  <dt className="text-muted">Safety steps</dt><dd className="font-mono">{approval.ticked.size} / {approval.safety.length} ticked</dd>
                  <dt className="text-muted">Parts</dt><dd>{state.workOrder.parts.length ? state.workOrder.parts.join(", ") : "none listed"}</dd>
                  <dt className="text-muted">Approver</dt><dd>{approval.name || "(not entered)"}</dd>
                </dl>
              )}
              {state.workOrder && approval.steps.some((s) => !s.is_safety) && (
                <details>
                  <summary className="inline-flex min-h-[44px] items-center text-sm font-semibold text-accent underline">Other work order steps ({approval.steps.filter((s) => !s.is_safety).length})</summary>
                  <ol className="mt-1 space-y-1 text-sm">{approval.steps.filter((s) => !s.is_safety).map((s) => <li key={s.order}><span className="font-mono text-xs text-muted">{s.order}. </span>{s.text}</li>)}</ol>
                </details>
              )}
              {decision === "reject" && !decidedWo && (
                <div>
                  <label htmlFor="t-approver2" className="text-sm font-semibold">Your name</label>
                  <input id="t-approver2" value={approval.name} onChange={(e) => approval.setName(e.target.value)} maxLength={80} autoComplete="name" className={inputCls} />
                </div>
              )}
              <p aria-live="polite" className="sr-only" data-testid="decision-announcer">{decidedWo === "APPROVED" ? "Work order approved and sent to the mock CMMS." : decidedWo ? "Work order rejected." : ""}</p>
              {decidedWo ? (
                <div className={`flex items-start gap-2 rounded-md border-2 p-3 ${decidedWo === "APPROVED" ? "border-ok" : "border-bad"}`} data-testid="decision-banner" role="status">
                  {decidedWo === "APPROVED" ? <IconCheck className="mt-1 h-5 w-5 text-ok" /> : <IconX className="mt-1 h-5 w-5 text-bad" />}
                  <span className="text-base">
                    <b className={decidedWo === "APPROVED" ? "text-ok" : "text-bad"}>{decidedWo === "APPROVED" ? "Approved and sent to the mock CMMS" : "Rejected"}</b>
                    {approval.result && <><br /><span className="font-mono text-xs">{approval.result.wo_id} · {approval.result.decided_at.slice(0, 19).replace("T", " ")}Z{approval.result.demo ? " · demo record" : ""}</span></>}
                  </span>
                </div>
              ) : decision === "reject" ? (
                <button type="button" className={`btn w-full ${bigBtn}`} disabled={approval.busy || !approval.name.trim() || !state.workOrder} onClick={() => void approval.submit("reject")}>{approval.busy ? "Sending…" : "Record rejection"}</button>
              ) : (
                <>
                  <button type="button" className={`btn-primary w-full !min-h-[64px] !text-lg`} disabled={!approval.canApprove} aria-describedby="t-why" onClick={() => void approval.submit("approve")}>
                    {approval.busy ? "Sending…" : "Approve & send to CMMS (mock)"}
                  </button>
                  <p id="t-why" className="text-xs text-muted">{approval.canApprove ? "Ready. Approval is recorded with your name in the audit log." : `Locked until: ${approval.missing.join("; ")}.`}</p>
                </>
              )}
              {approval.error && <p role="alert" className="flex items-start gap-1.5 text-sm text-bad"><IconAlert className="mt-0.5 shrink-0" />{approval.error}</p>}
              <p className="text-xs text-muted">Drafts only: nothing is written to a PLC, SCADA or historian.</p>
            </section>
          )}

          {maxStep >= CAUSE && state.incidentId && (
            <div hidden={step < CAUSE}>
              <VoicePanel incidentId={state.incidentId} passcode={state.mode === "live" ? passcode : null} />
            </div>
          )}
        </div>
      </div>

      {step !== PICK && (
        <div className="shrink-0 border-t border-line bg-panel px-3 pb-[max(0.75rem,env(safe-area-inset-bottom))] pt-3">
          <div className="mx-auto max-w-xl">
            {nextState && !nextState.ok && nextState.hint && <p className="mb-2 text-center text-xs text-muted" data-testid="next-hint">{nextState.hint}</p>}
            <div className="grid grid-cols-2 gap-3">
              <button type="button" className={`btn ${bigBtn}`} onClick={() => { if (step === STOPPED && streaming) abort(); goTo(backTo); }} data-testid="back">← Back</button>
              {nextState ? (
                <button type="button" className={`btn-primary ${bigBtn}`} disabled={!nextState.ok} onClick={() => goTo(nextState.to)} data-testid="next">{nextState.label} →</button>
              ) : step === APPROVE && decidedWo ? (
                <button type="button" className={`btn-primary ${bigBtn}`} onClick={() => { reset(); setDecision(null); setMaxStep(PICK); goTo(PICK); }}>New incident</button>
              ) : (
                <span />
              )}
            </div>
          </div>
        </div>
      )}

      <div aria-live="polite" className="sr-only" data-testid="tech-announcer">
        <p>{announce}</p>
        {state.announcements.slice(-6).map((a) => <p key={a.id}>{a.text}</p>)}
      </div>

      {askPass !== false && (
        <PasscodeDialog
          error={askPass}
          onCancel={() => setAskPass(false)}
          onSubmit={(p) => {
            setPasscode(p);
            storePasscode(p);
            setAskPass(false);
            void go("live", p);
          }}
        />
      )}
    </div>
  );
}

function Dots({ step, maxStep }: { step: number; maxStep: number }) {
  return (
    <nav aria-label="Progress" className="shrink-0 border-b border-line bg-panel px-3 py-2">
      <div className="mx-auto flex max-w-xl items-center justify-between gap-3">
        <ol className="flex items-center gap-2">
          {STEPS.map((name, i) => (
            <li key={name} aria-current={i === step ? "step" : undefined} data-step-dot={i}>
              <span className={`block h-3 rounded-full border ${i === step ? "w-7 border-accent bg-accent" : i <= maxStep ? "w-3 border-fg/70 bg-fg/70" : "w-3 border-muted bg-transparent"}`} aria-hidden />
              <span className="sr-only">{`Step ${i + 1} of ${STEPS.length}: ${name}${i === step ? " (current)" : ""}`}</span>
            </li>
          ))}
        </ol>
        <p className="text-sm font-semibold" data-testid="step-label">{step + 1}/{STEPS.length} · {STEPS[step]}</p>
      </div>
    </nav>
  );
}

function StoppedCard(p: {
  state: ReturnType<typeof useIncidentStream>["state"];
  scenarioTitle: string | null;
  stopTs: string | null;
  sourceLabel: string | null;
  real: boolean;
  fallbackStation: string | null;
  streaming: boolean;
  conn: string;
  httpMsg: string | null;
  heading: React.RefObject<HTMLHeadingElement | null>;
  canReplay: boolean;
  onReplay: () => void;
}) {
  const { state } = p;
  const station = state.stoppedStation ?? p.fallbackStation ?? "…";
  const [now, setNow] = useState(0);
  const t0 = useRef(Date.now());
  useEffect(() => {
    if (!p.streaming) return;
    const t = setInterval(() => setNow((n) => n + 1), 1000);
    return () => clearInterval(t);
  }, [p.streaming]);
  void now;
  const elapsed = state.done ? state.done.duration_ms / 1000 : (Date.now() - t0.current) / 1000;
  const problem = state.errors.filter((e) => !e.retryable || !e.retrying).slice(-1)[0];
  return (
    <section className="card space-y-3 p-4" aria-labelledby="tech-h" data-testid="card-stopped">
      <div className="flex flex-wrap items-center gap-2">
        <h2 id="tech-h" ref={p.heading} tabIndex={-1} className="text-xl font-semibold">Stopped</h2>
        <StatusBadge tone="bad" icon={<IconX className="h-3 w-3" />}>LINE STOPPED</StatusBadge>
      </div>
      <p className="font-mono text-4xl font-semibold leading-tight" data-testid="stopped-station">{station}</p>
      <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-sm">
        {p.scenarioTitle && (<><dt className="text-muted">Stop</dt><dd>{p.scenarioTitle}</dd></>)}
        {p.stopTs && (<><dt className="text-muted">Stopped at</dt><dd className="font-mono">{fmtDateTime(p.stopTs)}</dd></>)}
        {p.sourceLabel && (<><dt className="text-muted">Signals</dt><dd><span className={`chip ${p.real ? "border-fg font-semibold text-fg" : "border-transparent bg-raised text-muted"}`}>{p.real ? `REAL · ${p.sourceLabel}` : "SYNTHETIC"}</span></dd></>)}
        <dt className="text-muted">{state.done ? "Diagnosed in" : "Investigating"}</dt>
        <dd className="flex items-center gap-1 font-mono"><IconClock className="h-3.5 w-3.5" />{fmtClock(elapsed)}</dd>
      </dl>
      <div className="rounded-md border border-line bg-raised p-3" data-testid="progress-line" role="status">
        {p.streaming ? (
          <p className="flex items-center gap-2 text-base"><Spinner label="working" />{progressLine(state)}</p>
        ) : state.final ? (
          <p className="flex items-center gap-2 text-base"><IconCheck className="text-ok" />Root cause ready. Tap Root cause.</p>
        ) : (
          <p className="text-base text-muted">{p.conn === "dropped" ? "The stream dropped." : "Not running."}</p>
        )}
        {state.mode === "replay" && <p className="mt-1 text-xs text-muted">Replay of a recorded run.</p>}
      </div>
      {(p.conn === "dropped" || p.httpMsg || problem) && (
        <div role="alert" className="flex flex-col gap-2 rounded-md border border-bad p-3 text-sm" data-testid="tech-problem">
          <span className="flex items-start gap-2"><IconAlert className="mt-0.5 shrink-0 text-bad" />
            <span>{p.httpMsg ?? (p.conn === "dropped" ? "Stream dropped. The partial result is kept; a live run is never restarted automatically." : `${problem.code}: ${problem.message}`)}</span></span>
          {p.canReplay && <button type="button" className={`btn ${bigBtn}`} onClick={p.onReplay}>Play the recorded replay</button>}
        </div>
      )}
    </section>
  );
}

function CauseCard(p: {
  heading: React.RefObject<HTMLHeadingElement | null>;
  state: ReturnType<typeof useIncidentStream>["state"];
  insufficient: boolean;
  decision: Decision | null;
  setDecision: (d: Decision) => void;
  edits: string;
  setEdits: (s: string) => void;
}): ReactNode {
  const { state } = p;
  const top = state.final?.hypotheses[0];
  const claims = topVerifiedClaims(state, 2);
  const pct = top ? Math.round(top.confidence * 100) : 0;
  return (
    <section className="card space-y-3 p-4" aria-labelledby="tech-h" data-testid="card-cause">
      <h2 id="tech-h" ref={p.heading} tabIndex={-1} className="text-xl font-semibold">Root cause</h2>
      {!state.final || !top ? (
        <p className="text-base text-muted">No root cause yet.</p>
      ) : p.insufficient ? (
        <div className="rounded-md border-2 border-warn p-3" data-testid="insufficient-evidence">
          <p className="flex items-center gap-2 text-lg font-semibold text-warn"><IconAlert />Insufficient evidence</p>
          <p className="mt-1 text-sm">No hypothesis survived verification, so none is offered and no work order is drafted. Lead only, unverified: {rootCauseSentence(top)}. Check it by hand.</p>
          {top.next_check && <p className="mt-1 text-sm"><b>Next check:</b> {top.next_check}</p>}
        </div>
      ) : (
        <>
          <p className="text-2xl font-semibold leading-snug" data-testid="cause-sentence">{rootCauseSentence(top)}</p>
          <div className="flex items-center gap-3">
            <span className="font-mono text-5xl font-semibold tabular-nums" data-testid="confidence">{pct}%</span>
            <div className="flex-1">
              <p className="text-xs text-muted">confidence</p>
              <div role="meter" aria-label="Confidence" aria-valuemin={0} aria-valuemax={100} aria-valuenow={pct} className="h-3 overflow-hidden rounded-sm bg-raised"><div className="h-full bg-fg/80" style={{ width: `${pct}%` }} /></div>
            </div>
          </div>
          <StatusBadge tone={state.verifier.overall === "FAIL" ? "bad" : "ok"} icon={state.verifier.overall === "FAIL" ? <IconX className="h-3 w-3" /> : <IconCheck className="h-3 w-3" />}>
            {state.verifier.overall === "FAIL" ? "NOT VERIFIED" : "VERIFIED BY CODE"}
          </StatusBadge>
          {claims.length > 0 && (
            <ul className="space-y-2" aria-label="Top verified claims">
              {claims.map((c) => (
                <li key={c.claim_id} className="flex items-start gap-2 text-base"><IconCheck className="mt-1 shrink-0 text-ok" /><span><span className="sr-only">Verified: </span>{plainClaimText(c.text)}</span></li>
              ))}
            </ul>
          )}
          {top.causal_chain.length > 0 && <p className="font-mono text-xs text-muted">{top.causal_chain.join(" → ")}</p>}
          <div role="group" aria-label="Your decision on the root cause" className="grid grid-cols-3 gap-2 pt-1">
            {(["accept", "edit", "reject"] as Decision[]).map((d) => (
              <button key={d} type="button" aria-pressed={p.decision === d} onClick={() => p.setDecision(d)} className={`${p.decision === d ? "btn-primary" : "btn"} ${bigBtn}`}>
                {p.decision === d && <IconCheck className="h-4 w-4" />}{humanize(d).replace(/^./, (c) => c.toUpperCase())}
              </button>
            ))}
          </div>
          {p.decision === "edit" && (
            <div>
              <label htmlFor="t-edits" className="text-sm font-semibold">Your correction (kept in the audit log)</label>
              <textarea id="t-edits" value={p.edits} onChange={(e) => p.setEdits(e.target.value)} rows={3} maxLength={4000} className={inputCls} />
            </div>
          )}
          {p.decision === "reject" && <p className="text-sm text-bad"><b>Root cause rejected.</b> Continue to record the rejection.</p>}
          <p className="text-xs text-muted">Accepting is your judgement. The checklist stays locked until you decide.</p>
        </>
      )}
    </section>
  );
}
