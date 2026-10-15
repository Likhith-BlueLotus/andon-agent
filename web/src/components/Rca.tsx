import { useEffect, useId, useRef, useState, type ReactNode } from "react";
import type { Citation, Claim, Hypothesis, RCAReport, WorkOrder } from "../types/events";
import { claimState, claimsOf, type ClaimState, type IncidentState } from "../state/reducer";
import type { ClaimVerdict } from "../types/events";
import { useApproval, type Decision } from "../state/useApproval";
import { useWoLang } from "../state/useWoLang";
import { LangControl, SafetyTranslation } from "./LangControl";
import { fmtNum, fmtUsd, humanize } from "../lib/format";
import { MAX_VERIFIER_ITERATIONS } from "../lib/config";
import { motion } from "motion/react";
import type { Decided } from "../lib/progress";
import { EvidenceChip, IconAlert, IconArrowRight, IconCheck, IconClock, IconLock, IconShield, IconWrench, IconX, Popover, Spinner, StatusBadge } from "./ui";

const STATE_VIEW: Record<ClaimState, { word: string; tone: "ok" | "bad" | "warn" | "muted"; icon: ReactNode }> = {
  pending: { word: "pending", tone: "muted", icon: <IconClock className="h-3 w-3" /> },
  verified: { word: "verified", tone: "ok", icon: <IconCheck className="h-3 w-3" /> },
  rejected: { word: "rejected", tone: "bad", icon: <IconX className="h-3 w-3" /> },
  unverifiable: { word: "unverifiable", tone: "warn", icon: <IconAlert className="h-3 w-3" /> },
};

export function CitationBlock({ c }: { c: Citation }) {
  return (
    <figure className="mt-1.5 rounded-r-md border-l-2 border-accent/60 bg-sunken/60 py-1 pl-2.5 pr-2">
      <figcaption className="font-mono text-[11px] text-muted">
        {c.doc} · p.{c.page}
      </figcaption>
      <blockquote className="text-[13px] italic">“{c.quote}”</blockquote>
    </figure>
  );
}

export function ClaimRow({ claim, verdict, onEvidence }: { claim: Claim; verdict: ClaimVerdict | undefined; onEvidence: (id: string) => void }) {
  const st = claimState(verdict ? { [claim.claim_id]: verdict } : {}, claim.claim_id);
  const v = STATE_VIEW[st];
  const struck = st === "rejected" || st === "unverifiable";
  const measured = verdict?.measured_value;
  return (
    <li data-claim-id={claim.claim_id} data-claim-state={st} className="py-1.5">
      <div className="flex items-start gap-2">
        <StatusBadge tone={v.tone} icon={v.icon} className="mt-0.5 shrink-0">{v.word}</StatusBadge>
        <div className="min-w-0 flex-1">
          <p className={`text-[13px] ${struck ? "text-muted line-through decoration-bad decoration-2" : ""}`} data-claim-text>
            {claim.text}
          </p>
          {st === "rejected" && (
            <p className="mt-0.5 text-xs text-bad">
              <Popover
                label={`Why this claim was rejected`}
                trigger={<span className="font-mono font-semibold underline decoration-dotted">{measured != null ? `measured ${fmtNum(measured)}` : "rejected by verifier"}</span>}
              >
                {verdict?.reason}
              </Popover>
              {claim.asserted_value != null && <span className="text-muted"> · model asserted {fmtNum(claim.asserted_value)}</span>}
            </p>
          )}
          {st === "unverifiable" && <p className="mt-0.5 text-xs text-warn">Could not be checked against evidence. Kept visible, not trusted. {verdict?.reason}</p>}
          {st === "verified" && verdict?.reason && <p className="mt-0.5 break-words font-mono text-[11px] text-muted">{verdict.reason}</p>}
          <div className="mt-1 flex flex-wrap items-center gap-1">
            {claim.evidence_ids.map((id) => (
              <EvidenceChip key={id} id={id} onOpen={onEvidence} />
            ))}
            <span className="chip border-transparent bg-raised text-muted">{claim.kind.replace("_", " ")}</span>
          </div>
          {claim.citation && <CitationBlock c={claim.citation} />}
        </div>
      </div>
    </li>
  );
}

function HypothesisCard({ h, rank, verdicts, final, onEvidence }: { h: Hypothesis; rank: number; verdicts: Record<string, ClaimVerdict>; final: boolean; onEvidence: (id: string) => void }) {
  const pct = Math.round(h.confidence * 100);
  return (
    <motion.article
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: 0.05 * (rank - 1), duration: 0.3, ease: [0.2, 0.8, 0.2, 1] }}
      className={`card p-3 ${rank === 1 && final ? "border-line-strong" : ""}`}
      aria-label={`Hypothesis ${rank}: ${humanize(h.cause_class)} at ${h.asset_id}`}
      data-hypothesis-rank={rank}
    >
      <header className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
        <span className={`flex h-5 min-w-[20px] items-center justify-center self-center rounded-md px-1 font-mono text-[11px] font-semibold ${rank === 1 ? "bg-fg text-bg" : "bg-raised text-muted"}`}>#{rank}</span>
        <h3 className="text-[15px] font-semibold capitalize">{humanize(h.cause_class)}</h3>
        <span className="font-mono text-xs text-muted">{h.cause_class}</span>
        <span className="ml-auto rounded-md border border-line bg-sunken px-1.5 font-mono text-xs">{h.asset_id}</span>
      </header>
      <div className="mt-2 flex items-center gap-2">
        <div role="meter" aria-label="Confidence" aria-valuemin={0} aria-valuemax={100} aria-valuenow={pct} className="h-1.5 flex-1 overflow-hidden rounded-full bg-sunken">
          <motion.div className={`h-full rounded-full ${final && rank === 1 ? "bg-ok" : "bg-fg/60"}`} initial={{ width: 0 }} animate={{ width: `${pct}%` }} transition={{ duration: 0.7, ease: [0.2, 0.8, 0.2, 1] }} />
        </div>
        <span className="font-mono text-xs tabular-nums">{pct}%{final ? "" : " (draft)"}</span>
      </div>
      {h.causal_chain.length > 0 && (
        <p className="mt-2 flex flex-wrap items-center gap-1 font-mono text-[11px] text-muted" aria-label={`Causal chain ${h.causal_chain.join(" then ")}`}>
          {h.causal_chain.map((c, i) => (
            <span key={i} aria-hidden className="inline-flex items-center gap-1">
              {i > 0 && <IconArrowRight className="h-3 w-3" />}
              <span className="rounded border border-line bg-sunken px-1.5 py-0.5 text-fg">{c}</span>
            </span>
          ))}
        </p>
      )}
      <ul className="mt-1 divide-y divide-line" aria-label="Claims">
        {h.claims.map((c) => (
          <ClaimRow key={c.claim_id} claim={c} verdict={verdicts[c.claim_id]} onEvidence={onEvidence} />
        ))}
      </ul>
      {h.refuting_evidence_ids.length > 0 && (
        <p className="mt-1 flex flex-wrap items-center gap-1 text-xs text-muted">
          Evidence against:
          {h.refuting_evidence_ids.map((id) => (
            <EvidenceChip key={id} id={id} onOpen={onEvidence} />
          ))}
        </p>
      )}
      {h.next_check && (
        <p className="mt-1 text-xs"><span className="font-semibold">Next check:</span> {h.next_check}</p>
      )}
    </motion.article>
  );
}

export function VerifierCard({ state }: { state: IncidentState }) {
  const v = state.verifier;
  if (!v.iteration && !v.checking && state.revisions.length === 0) return null;
  const iter = Math.max(1, v.checking && v.overall == null ? v.iteration + 1 : v.iteration);
  const label = v.checking ? "checking claims…" : v.overall === "FAIL" ? (v.revising ? "FAIL · Judge is revising" : "FAIL · iteration limit reached") : v.overall === "PASS" ? "PASS" : "…";
  return (
    <section className="card p-3" aria-label="Verifier loop" data-verifier={v.overall ?? "checking"}>
      <div className="flex flex-wrap items-center gap-2">
        <IconShield className="h-4 w-4 text-muted" />
        <h3 className="label">Verifier</h3>
        <span className="font-mono text-xs" data-testid="verifier-iteration">iteration {Math.min(iter, MAX_VERIFIER_ITERATIONS)}/{MAX_VERIFIER_ITERATIONS}</span>
        {v.checking ? (
          <StatusBadge tone="accent" icon={<Spinner label="checking" />}>{label}</StatusBadge>
        ) : v.overall === "PASS" ? (
          <StatusBadge tone="ok" icon={<IconCheck className="h-3 w-3" />}>{label}</StatusBadge>
        ) : v.overall === "FAIL" ? (
          <StatusBadge tone="bad" icon={<IconX className="h-3 w-3" />}>{label}</StatusBadge>
        ) : null}
      </div>
      <div aria-hidden className="mt-2 flex gap-1">
        {Array.from({ length: MAX_VERIFIER_ITERATIONS }, (_, i) => {
          const n = i + 1;
          const failed = state.revisions.some((r) => r.iteration === n);
          const passed = v.overall === "PASS" && n === v.iteration;
          const now = v.checking && n === iter;
          return <span key={n} className={`h-1 flex-1 rounded-full ${passed ? "bg-ok" : failed ? "bg-bad" : now ? "bg-accent blink" : "bg-sunken"}`} />;
        })}
      </div>
      <p className="mt-1.5 text-xs text-muted">Code re-runs the tools and compares every number, timestamp, quote and ordering. The model does not grade itself.</p>
      {state.revisions.map((r) => (
        <div key={r.iteration} className="mt-2 rounded-lg border border-bad/40 bg-bad/5 p-2" data-revision={r.iteration}>
          <p className="text-xs font-semibold text-bad">Iteration {r.iteration}: {r.rejected.length} claim{r.rejected.length > 1 ? "s" : ""} rejected, Judge asked to revise</p>
          <ul className="mt-1 space-y-1">
            {r.rejected.map(({ claim, verdict }) => (
              <li key={claim.claim_id} className="text-xs">
                <span className="text-muted line-through decoration-bad decoration-2">{claim.text}</span>
                <div className="font-mono text-[11px] text-bad">{verdict.verdict === "fail" ? "rejected" : "unverifiable"}{verdict.measured_value != null ? ` · measured ${fmtNum(verdict.measured_value)}` : ""} · {verdict.reason}</div>
              </li>
            ))}
          </ul>
        </div>
      ))}
    </section>
  );
}

export function CostChip({ state }: { state: IncidentState }) {
  const c = state.cost;
  if (!c) return null;
  return (
    <details className="card px-3 py-2 text-xs" data-testid="cost-chip">
      <summary className="flex cursor-pointer flex-wrap items-center gap-x-3 gap-y-1 font-mono">
        <span className="label">Run cost</span>
        <span className="text-sm font-semibold">{fmtUsd(c.usd)}</span>
        <span className="text-muted">{c.input_tokens.toLocaleString("en-US")} in · {c.output_tokens.toLocaleString("en-US")} out · {c.cached_tokens.toLocaleString("en-US")} cached</span>
        {state.cacheSavedUsd > 0 && <span className="text-muted">cache saved {fmtUsd(state.cacheSavedUsd)}</span>}
      </summary>
      <table className="mt-2 w-full font-mono text-[11px]">
        <caption className="sr-only">Cost by model</caption>
        <tbody>
          {Object.entries(c.by_model).map(([m, usd]) => (
            <tr key={m}><th scope="row" className="py-0.5 pr-2 text-left font-normal text-muted">{m}</th><td className="text-right">{fmtUsd(usd)}</td></tr>
          ))}
        </tbody>
      </table>
    </details>
  );
}

export interface RcaPaneProps {
  state: IncidentState;
  passcode: string | null;
  isMock: boolean;
  onEvidence: (id: string) => void;
  /** Technician view handoff (only when the "tech" feature is on). */
  techLink?: { href: string; onOpen: () => void } | null;
  /** Work-order language toggle (stretch "lang" flag). */
  langEnabled?: boolean;
  /** Told when the human approves or rejects the work order (drives the progress rail). */
  onDecided?: (d: Decided) => void;
}

export function RcaPane({ state, passcode, isMock, onEvidence, techLink, langEnabled, onDecided }: RcaPaneProps) {
  const report: RCAReport | null = state.final ?? state.draft;
  const isFinal = !!state.final;
  const insufficient = state.final?.status === "insufficient_evidence";
  const [decision, setDecision] = useState<Decision | null>(null);
  const [edits, setEdits] = useState("");
  const decisionHint = useId();

  const empty = !report && !state.verifier.iteration && state.phase !== "streaming";
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="pane-head"><h2 className="label">Root cause &amp; action</h2></div>
      <div className="relative min-h-0 flex-1 space-y-3 overflow-y-auto p-3" tabIndex={0} role="region" aria-label="Root cause and action, scrollable">
        {empty && (
          <div className="rounded-xl border border-dashed border-line-strong/70 p-5 text-sm text-muted">
            <div aria-hidden className="mb-3 flex items-end gap-1.5">
              {[72, 48, 30].map((w, i) => (
                <span key={i} className="block h-2 rounded-full bg-raised" style={{ width: `${w}%`, opacity: 1 - i * 0.25 }} />
              ))}
            </div>
            <p className="font-semibold text-fg">No root cause yet.</p>
            <p className="mt-1">Hypotheses appear here ranked by confidence. Every claim starts as <span className="font-semibold">pending</span> and turns <span className="font-semibold">verified</span> or struck through once code has checked it.</p>
          </div>
        )}
        {!report && state.phase === "streaming" && (
          <div className="space-y-2" aria-hidden={false}>
            <p className="flex items-center gap-2 text-sm text-muted"><Spinner label="investigating" />The Judge will rank hypotheses once the evidence is in.</p>
            {[0, 1].map((i) => (
              <div key={i} aria-hidden className="card space-y-2 p-3 motion-safe:animate-pulse" style={{ opacity: 1 - i * 0.4 }}>
                <div className="h-3 w-1/2 rounded bg-raised" />
                <div className="h-1.5 w-full rounded-full bg-raised" />
                <div className="h-2.5 w-4/5 rounded bg-raised" />
              </div>
            ))}
          </div>
        )}
        {state.verifier.revising && (
          <div role="status" className="flex items-start gap-2 rounded border border-bad p-2 text-sm" data-testid="revising-banner">
            <IconX className="mt-0.5 shrink-0 text-bad" />
            <span><span className="font-semibold text-bad">Verifier FAIL, revising</span> (iteration {state.verifier.iteration}/{MAX_VERIFIER_ITERATIONS}). The rejected claim stays visible below; the Judge must correct it against the measured value.</span>
          </div>
        )}
        <VerifierCard state={state} />

        {insufficient && (
          <section className="rounded-xl border border-warn/60 bg-gradient-to-br from-warn/10 to-transparent p-4" aria-label="Insufficient evidence" data-testid="insufficient-evidence">
            <p className="flex items-center gap-2 font-semibold text-warn"><IconAlert />Insufficient evidence</p>
            <p className="mt-1 text-sm">No hypothesis survived verification, so none is offered as a root cause and no work order is drafted. The candidates below are unverified leads, listed so a human can decide what to check next.</p>
          </section>
        )}

        {report && report.hypotheses.length > 0 && (
          <section aria-label={isFinal && !insufficient ? "Verified root cause" : "Hypotheses"} className="space-y-2" data-final={isFinal}>
            {!isFinal && <p className="label">Draft hypotheses · not yet verified</p>}
            {isFinal && !insufficient && <VerdictHero report={report} state={state} />}
            {isFinal && !insufficient && <p className="label pt-1">Ranked hypotheses · claim by claim</p>}
            {report.hypotheses.map((h, i) => (
              <HypothesisCard key={`${h.cause_class}${h.asset_id}${i}`} h={h} rank={i + 1} verdicts={state.verdicts} final={isFinal} onEvidence={onEvidence} />
            ))}
          </section>
        )}

        {isFinal && !insufficient && (
          <section aria-label="Your decision on the root cause" className={`card p-3 ${decision ? "" : "border-accent/50"}`}>
            <div className="flex items-center gap-2">
              <span aria-hidden className={`flex h-5 w-5 items-center justify-center rounded-full font-mono text-[10px] font-bold ${decision ? "bg-ok text-bg" : "bg-accent text-accent-fg"}`}>{decision ? <IconCheck className="h-3 w-3" /> : 1}</span>
              <h3 className="label">Your decision</h3>
            </div>
            <div role="group" aria-describedby={decisionHint} className="mt-2 grid grid-cols-3 gap-2">
              {(["accept", "edit", "reject"] as Decision[]).map((d) => {
                const on = decision === d;
                const tone = d === "reject" ? "border-bad bg-bad/15 text-bad" : d === "edit" ? "border-warn bg-warn/15 text-warn" : "border-ok bg-ok/15 text-ok";
                return (
                  <button key={d} type="button" className={`btn !min-h-[42px] ${on ? `${tone} !font-semibold` : ""}`} aria-pressed={on} onClick={() => setDecision(d)}>
                    {d === "accept" ? <IconCheck className="h-4 w-4" /> : d === "edit" ? <IconWrench className="h-4 w-4" /> : <IconX className="h-4 w-4" />}
                    {d === "accept" ? "Accept" : d === "edit" ? "Edit" : "Reject"}
                  </button>
                );
              })}
            </div>
            <p id={decisionHint} className="mt-1 text-xs text-muted">Accepting is a human judgement. The work order below stays locked until you decide.</p>
            {decision === "edit" && (
              <div className="mt-2">
                <label htmlFor="rca-edits" className="text-xs font-semibold">Your correction (kept in the audit log)</label>
                <textarea id="rca-edits" value={edits} onChange={(e) => setEdits(e.target.value)} rows={3} maxLength={4000} className="field mt-1" />
              </div>
            )}
            {decision === "reject" && <p className="mt-2 text-sm text-bad"><span className="font-semibold">Root cause rejected.</span> The work order cannot be approved. Record the rejection below.</p>}
          </section>
        )}

        {techLink && isFinal && (state.workOrder || insufficient || state.phase === "done") && (
          <a href={techLink.href} onClick={(e) => { e.preventDefault(); techLink.onOpen(); }} className="btn group w-full !min-h-[44px] justify-between" data-testid="open-tech">
            Open in technician view <IconArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-0.5" />
          </a>
        )}
        {state.workOrder && !insufficient && (
          <WorkOrderPanel key={state.workOrder.wo_id} onDecided={onDecided} wo={state.workOrder} incidentId={state.incidentId} decision={decision} edits={edits} enabled={isFinal} passcode={passcode} isMock={isMock} langEnabled={langEnabled} />
        )}
        <CostChip state={state} />
        {state.phase === "done" && state.done && <p className="font-mono text-[11px] text-muted">run finished in {(state.done.duration_ms / 1000).toFixed(1)} s · {claimsOf(report).length} claims checked</p>}
      </div>
    </div>
  );
}

export function WorkOrderPanel({
  wo,
  incidentId,
  decision,
  edits,
  enabled,
  passcode,
  isMock,
  langEnabled = false,
  onDecided,
}: {
  wo: WorkOrder;
  incidentId: string | null;
  decision: Decision | null;
  edits: string;
  enabled: boolean;
  passcode: string | null;
  isMock: boolean;
  langEnabled?: boolean;
  onDecided?: (d: Decided) => void;
}) {
  const wl = useWoLang(langEnabled ? wo : null, incidentId, passcode, isMock);
  const { steps, safety, ticked, toggle, name, setName, busy, error, result, decided, missing, canApprove, submit } = useApproval({ wo, incidentId, decision, edits, enabled, passcode, isMock });
  const bannerRef = useRef<HTMLDivElement>(null);
  const why = useId();
  // the Approve button unmounts on decision; keep keyboard focus in the pane
  useEffect(() => {
    if (result) bannerRef.current?.focus();
  }, [result]);
  useEffect(() => {
    if (decided === "APPROVED" || decided === "REJECTED") onDecided?.(decided);
  }, [decided]); // eslint-disable-line react-hooks/exhaustive-deps
  const safetyPct = safety.length ? (ticked.size / safety.length) * 100 : 100;

  return (
    <section aria-label="Draft work order" className={`card p-3 ${decided === "APPROVED" ? "border-ok/60" : ""}`} data-wo-status={decided ?? wo.status}>
      <header className="flex flex-wrap items-center gap-2">
        <IconWrench className="h-4 w-4 text-muted" />
        <h3 className="label">Draft work order</h3>
        <span className="font-mono text-xs">{wo.wo_id}</span>
        {decided === "APPROVED" ? (
          <StatusBadge tone="ok" icon={<IconCheck className="h-3 w-3" />}>APPROVED</StatusBadge>
        ) : decided === "REJECTED" ? (
          <StatusBadge tone="bad" icon={<IconX className="h-3 w-3" />}>REJECTED</StatusBadge>
        ) : (
          <StatusBadge tone="warn" icon={<IconClock className="h-3 w-3" />}>PENDING APPROVAL</StatusBadge>
        )}
      </header>
      <p className="mt-1 text-xs text-muted">
        {humanize(wo.cause_class)} · <span className="font-mono">{wo.asset_id}</span> · drafts only: nothing is written to a PLC, SCADA or historian.
      </p>
      {langEnabled && <div className="mt-2"><LangControl wl={wl} /></div>}
      {wo.parts.length > 0 && <p className="mt-1 text-xs"><span className="font-semibold">Parts:</span> {wo.parts.join(", ")}</p>}
      {wl.lang && wl.data && wl.data.parts.some((p) => p.translation) && (
        <p className="text-xs text-muted" lang={wl.lang} data-testid="parts-translation"><span className="font-semibold">Parts ({wl.data.lang_name}, machine): </span>{wl.data.parts.map((p) => p.translation ?? p.original).join(", ")}</p>
      )}

      <ol className="mt-2 space-y-2" aria-label="Work order steps">
        {steps.map((s) =>
          s.is_safety ? (
            <li key={s.order} className={`rounded-lg border p-2.5 transition-colors duration-200 ${ticked.has(s.order) ? "border-ok/50 bg-ok/5" : "border-warn/50 bg-warn/5"}`} data-safety-step={s.order}>
              <label className="flex cursor-pointer items-start gap-2.5">
                <input
                  type="checkbox"
                  className="mt-0.5 h-5 w-5 shrink-0 accent-[rgb(var(--ok))]"
                  checked={ticked.has(s.order)}
                  disabled={!!decided}
                  onChange={(e) => toggle(s.order, e.target.checked)}
                />
                <span className="min-w-0">
                  <span className={`mb-0.5 flex items-center gap-1 font-mono text-[11px] font-semibold uppercase ${ticked.has(s.order) ? "text-ok" : "text-warn"}`}>
                    <IconLock className="h-3 w-3" />LOTO safety step {s.order}
                  </span>
                  <span className="block text-[13px]">{s.text}</span>
                </span>
              </label>
              {s.citation && (
                <div className="ml-[30px]">
                  <p className="font-mono text-[11px] text-muted">verbatim from {s.citation.doc} · p.{s.citation.page}</p>
                  {s.citation.quote !== s.text && <CitationBlock c={s.citation} />}
                </div>
              )}
              {wl.lang && wl.data && <div className="ml-[30px]"><SafetyTranslation text={wl.byOrder.get(s.order)} lang={wl.lang} order={s.order} /></div>}
            </li>
          ) : (
            <li key={s.order} className="flex gap-2 text-[13px]" data-step={s.order}>
              <span className="w-5 shrink-0 text-right font-mono text-xs text-muted">{s.order}.</span>
              {wl.lang && wl.data ? (
                <span className="min-w-0">
                  {wl.byOrder.get(s.order) ? (
                    <>
                      <span lang={wl.lang} className="block" data-testid={`translated-${s.order}`}>{wl.byOrder.get(s.order)}</span>
                      <span className="block text-[11px] text-muted" data-testid={`original-${s.order}`}>{s.text}</span>
                    </>
                  ) : (
                    <>
                      <span className="block">{s.text}</span>
                      <span className="block text-[11px] italic text-muted">translation unavailable</span>
                    </>
                  )}
                </span>
              ) : (
                <span>{s.text}</span>
              )}
            </li>
          ),
        )}
      </ol>

      {/* always mounted, so screen readers announce the outcome (a live region inserted with its text is often skipped) */}
      <p aria-live="polite" className="sr-only" data-testid="decision-announcer">
        {decided === "APPROVED" ? `Work order ${result?.wo_id ?? wo.wo_id} approved and sent to the mock CMMS.` : decided ? "Work order rejected." : ""}
      </p>
      {decided ? (
        <motion.div
          ref={bannerRef}
          tabIndex={-1}
          initial={{ opacity: 0, scale: 0.97 }}
          animate={{ opacity: 1, scale: 1 }}
          transition={{ type: "spring", stiffness: 400, damping: 30 }}
          className={`mt-3 flex items-start gap-2.5 rounded-lg border p-3 text-sm ${decided === "APPROVED" ? "border-ok bg-ok/10" : "border-bad bg-bad/10"}`}
          data-testid="decision-banner"
        >
          <span aria-hidden className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-full ${decided === "APPROVED" ? "bg-ok" : "bg-bad"}`} style={{ color: "rgb(var(--bg))" }}>
            {decided === "APPROVED" ? <IconCheck className="h-4 w-4" /> : <IconX className="h-4 w-4" />}
          </span>
          <span>
            <span className={`font-semibold ${decided === "APPROVED" ? "text-ok" : "text-bad"}`}>{decided === "APPROVED" ? "Approved and sent to the mock CMMS" : "Rejected"}</span>
            {result && <> · <span className="font-mono text-xs">{result.wo_id}</span> · {result.decided_at.slice(0, 19).replace("T", " ")}Z{result.demo ? " · demo record (mock CMMS)" : ""}</>}
          </span>
        </motion.div>
      ) : (
        <div className="mt-3 space-y-2 border-t border-line pt-3">
          <div>
            <label htmlFor="approver" className="text-xs font-semibold">Approver name</label>
            <input id="approver" value={name} onChange={(e) => setName(e.target.value)} maxLength={80} autoComplete="name" className="field mt-1" />
          </div>
          <div>
            <p className="flex items-center justify-between text-xs" aria-live="polite">
              <span className="font-semibold">Safety steps ticked: </span>
              <span className={`font-mono ${ticked.size === safety.length ? "text-ok" : ""}`} data-testid="safety-count">{ticked.size}/{safety.length}</span>
            </p>
            <div aria-hidden className="mt-1 h-1.5 overflow-hidden rounded-full bg-sunken">
              <motion.div className={`h-full rounded-full ${safetyPct === 100 ? "bg-ok" : "bg-warn"}`} initial={false} animate={{ width: `${safetyPct}%` }} transition={{ duration: 0.3 }} />
            </div>
          </div>
          <div className="flex flex-wrap gap-2">
            <button type="button" className="btn-ok !min-h-[44px] flex-1" disabled={!canApprove} aria-describedby={why} onClick={() => submit("approve")}>
              {busy ? <Spinner label="sending" /> : canApprove ? <IconCheck className="h-4 w-4" /> : <IconLock className="h-4 w-4" />}
              {busy ? "Sending…" : "Approve & send to CMMS (mock)"}
            </button>
            {enabled && decision === "reject" && (
              <button type="button" className="btn !min-h-[44px] border-bad/60 text-bad" disabled={busy || !name.trim()} onClick={() => submit("reject")}>Record rejection</button>
            )}
          </div>
          <p id={why} className="text-xs text-muted">{canApprove ? "Ready. Approval is recorded with your name in the audit log." : `Locked until: ${missing.join("; ")}.`}</p>
          {error && <p role="alert" className="flex items-start gap-1.5 text-sm text-bad"><IconAlert className="mt-0.5 shrink-0" />{error}</p>}
        </div>
      )}
    </section>
  );
}

/** Animated confidence ring. The number is the Judge's confidence, shown as-is. */
export function ConfidenceRing({ pct, size = 76 }: { pct: number; size?: number }) {
  const r = (size - 8) / 2;
  const c = 2 * Math.PI * r;
  return (
    <div className="relative shrink-0" style={{ width: size, height: size }} role="img" aria-label={`Confidence ${pct} percent`}>
      <svg width={size} height={size} className="-rotate-90" aria-hidden>
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="rgb(var(--ok) / 0.15)" strokeWidth="6" />
        <motion.circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="rgb(var(--ok))" strokeWidth="6" strokeLinecap="round" strokeDasharray={c} initial={{ strokeDashoffset: c }} animate={{ strokeDashoffset: c * (1 - pct / 100) }} transition={{ duration: 0.9, ease: [0.2, 0.8, 0.2, 1], delay: 0.15 }} />
      </svg>
      <span aria-hidden className="absolute inset-0 flex flex-col items-center justify-center">
        <span className="font-mono text-lg font-semibold leading-none tabular-nums">{pct}<span className="text-xs text-muted">%</span></span>
        <span className="mt-0.5 font-mono text-[9px] uppercase tracking-wider text-muted">conf.</span>
      </span>
    </div>
  );
}

/** The moment the investigation lands: verified cause, confidence, and what the verifier caught on the way. */
function VerdictHero({ report, state }: { report: RCAReport; state: IncidentState }) {
  const h = report.hypotheses[0];
  if (!h) return null;
  const claims = claimsOf(report);
  const verified = claims.filter((c) => claimState(state.verdicts, c.claim_id) === "verified").length;
  const caught = state.revisions.reduce((n, r) => n + r.rejected.length, 0);
  const cited = claims.filter((c) => c.citation).length;
  return (
    <motion.section
      initial={{ opacity: 0, y: 10, scale: 0.98 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      transition={{ type: "spring", stiffness: 300, damping: 28 }}
      className="relative overflow-hidden rounded-xl border border-ok/50 bg-gradient-to-br from-ok/15 via-ok/[0.04] to-transparent p-4"
      aria-label="Verified root cause summary"
      data-testid="verdict-hero"
    >
      <div aria-hidden className="pointer-events-none absolute -right-10 -top-10 h-32 w-32 rounded-full bg-ok/20 blur-3xl" />
      <p className="eyebrow flex items-center gap-1.5 text-ok"><IconShield className="h-3.5 w-3.5" />Verified root cause</p>
      <div className="mt-2 flex items-start gap-3">
        <div className="min-w-0 flex-1">
          <h3 className="text-xl font-semibold capitalize leading-tight tracking-tight">{humanize(h.cause_class)}</h3>
          <p className="mt-1 text-sm text-muted">
            at <span className="rounded-md border border-line bg-sunken px-1.5 font-mono text-[13px] text-fg">{h.asset_id}</span>
            {state.verifier.iteration > 0 && <> · passed on iteration {Math.min(state.verifier.iteration, MAX_VERIFIER_ITERATIONS)}/{MAX_VERIFIER_ITERATIONS}</>}
          </p>
        </div>
        <ConfidenceRing pct={Math.round(h.confidence * 100)} />
      </div>
      <ul className="mt-3 flex flex-wrap gap-1.5 text-xs" aria-label="Verifier tally">
        <li className="inline-flex items-center gap-1 rounded-md border border-ok/40 bg-panel/60 px-2 py-1"><IconCheck className="h-3 w-3 text-ok" /><span className="font-mono font-semibold">{verified}/{claims.length}</span> claims checked by code</li>
        {caught > 0 && <li className="inline-flex items-center gap-1 rounded-md border border-bad/40 bg-panel/60 px-2 py-1"><IconX className="h-3 w-3 text-bad" /><span className="font-mono font-semibold">{caught}</span> wrong claim{caught > 1 ? "s" : ""} caught &amp; corrected</li>}
        {cited > 0 && <li className="inline-flex items-center gap-1 rounded-md border border-line bg-panel/60 px-2 py-1"><span className="font-mono font-semibold">{cited}</span> manual citation{cited > 1 ? "s" : ""}</li>}
      </ul>
    </motion.section>
  );
}
