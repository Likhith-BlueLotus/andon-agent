import { useEffect, useRef, useState } from "react";
import type { IncidentState, Lane, ToolCard, TraceItem } from "../state/reducer";
import { argsLine, briefSummary, qualityNotes } from "../lib/summary";
import { humanize } from "../lib/format";
import { MAX_VERIFIER_ITERATIONS } from "../lib/config";
import { EvidenceChip, IconAlert, IconBolt, IconCheck, IconChevron, IconClock, IconX, ProvenanceChip, Spinner, StatusBadge } from "./ui";

export function PlanCard({ plan, done }: { plan: string[]; done: number }) {
  return (
    <section aria-label="Investigation plan" className="card enter p-3">
      <div className="flex items-baseline justify-between">
        <h3 className="label">Plan</h3>
        <span className="font-mono text-[11px] text-muted" title="Indicative progress: plan steps carry no link to individual tool calls">
          {done}/{plan.length} checked
        </span>
      </div>
      <ol className="mt-2 space-y-1.5">
        {plan.map((s, i) => {
          const ticked = i < done;
          return (
            <li key={i} className="flex gap-2 text-[13px]" data-ticked={ticked}>
              <span
                aria-hidden
                className={`mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded-sm border ${
                  ticked ? "border-accent bg-accent text-accent-fg" : i === done ? "border-accent text-accent" : "border-line"
                }`}
              >
                {ticked ? <IconCheck className="h-3 w-3" /> : <span className="font-mono text-[10px]">{i + 1}</span>}
              </span>
              <span className={ticked ? "text-muted" : ""}>
                <span className="sr-only">{ticked ? `Step ${i + 1} checked: ` : `Step ${i + 1}: `}</span>
                {s}
              </span>
            </li>
          );
        })}
      </ol>
    </section>
  );
}

function ToolRow({ t, onEvidence }: { t: ToolCard; onEvidence: (id: string) => void }) {
  const [open, setOpen] = useState(false);
  const notes = t.summary && !t.toolError ? qualityNotes(t.summary) : [];
  const running = t.status === "running";
  return (
    <li
      data-call-id={t.callId}
      data-status={t.status}
      className={`enter rounded border bg-panel px-2.5 py-2 ${running ? "border-accent/70" : t.status === "error" ? "border-warn/70" : "border-line"}`}
    >
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <span className="flex w-4 justify-center" aria-hidden>
          {running ? <span className="spinner" /> : t.status === "error" ? <IconAlert className="text-warn" /> : <IconCheck className="text-muted" />}
        </span>
        <span className="font-mono text-[13px] font-semibold">{t.tool}</span>
        <span className="sr-only">{running ? "running" : t.status === "error" ? "returned an error" : "finished"}</span>
        <EvidenceChip id={t.evidenceId} onOpen={onEvidence} />
        <ProvenanceChip provenance={t.provenance} />
        {t.latencyMs != null && (
          <span className="ml-auto inline-flex items-center gap-1 font-mono text-[11px] text-muted">
            <IconClock className="h-3 w-3" />
            {t.latencyMs} ms
          </span>
        )}
      </div>
      <div className="mt-1 break-words font-mono text-[11px] text-muted">{argsLine(t.args)}</div>
      {t.toolError ? (
        <p className="mt-1 flex items-start gap-1.5 text-xs text-warn">
          <IconAlert className="mt-0.5 shrink-0" />
          <span>
            <span className="font-semibold">Tool error</span> <span className="font-mono">{t.toolError.code}</span>: {t.toolError.message}. The agents continue with other evidence.
          </span>
        </p>
      ) : t.summary ? (
        <p className="mt-1 break-words text-[13px]">{briefSummary(t.tool, t.summary)}</p>
      ) : (
        <p className="mt-1 text-xs text-accent">waiting for result…</p>
      )}
      {notes.map((n, i) => (
        <p key={i} className="mt-0.5 flex items-start gap-1 text-[11px] text-muted" data-quality-note>
          <IconInfo2 />
          <span>{n}</span>
        </p>
      ))}
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen(!open)}
        className="mt-1 inline-flex items-center gap-1 rounded font-mono text-[11px] text-muted hover:text-fg"
      >
        <IconChevron className={`h-3 w-3 transition-transform ${open ? "rotate-90" : ""}`} />
        args {t.summary ? "& summary" : ""}
      </button>
      {open && (
        <div className="mt-1 space-y-1">
          <pre className="max-h-40 overflow-auto rounded bg-raised p-2 font-mono text-[11px]" aria-label="Tool arguments">{JSON.stringify(t.args, null, 2)}</pre>
          {t.summary && (
            <pre className="max-h-56 overflow-auto rounded bg-raised p-2 font-mono text-[11px]" aria-label="Tool result summary">{JSON.stringify(t.summary, null, 2)}</pre>
          )}
        </div>
      )}
    </li>
  );
}

const IconInfo2 = () => <span aria-hidden className="mt-px font-mono">·</span>;

function InlineBadge({ item }: { item: Exclude<TraceItem, { kind: "tool" }> }) {
  if (item.kind === "proposed") {
    return (
      <li className="enter px-1 text-[11px] text-muted" data-kind="proposed">
        proposed <span className="font-semibold text-fg">{item.count} hypothes{item.count === 1 ? "is" : "es"}</span>
        {item.top && <> · top: <span className="font-mono">{item.top}</span></>} · awaiting verifier
      </li>
    );
  }
  if (item.kind === "verdict") {
    const v = item.verdict;
    const bad = v.verdict !== "pass";
    return (
      <li className="enter flex items-start gap-1.5 px-1 text-[12px]" data-kind="verdict" data-verdict={v.verdict}>
        {bad ? <IconX className="mt-0.5 shrink-0 text-bad" /> : <IconCheck className="mt-0.5 shrink-0 text-ok" />}
        <span className="min-w-0">
          <span className={`font-semibold ${bad ? "text-bad" : "text-ok"}`}>{v.verdict === "pass" ? "verified" : v.verdict === "fail" ? "rejected" : "unverifiable"}</span>{" "}
          <span className="font-mono text-[11px] text-muted">{v.claim_id}</span>{" "}
          <span className={bad ? "text-muted line-through decoration-bad" : "text-muted"}>{item.text}</span>
          {v.measured_value != null && bad && <span className="font-mono text-bad"> · measured {v.measured_value}</span>}
        </span>
      </li>
    );
  }
  if (item.kind === "verdict_summary") {
    return (
      <li className="enter px-1" data-kind="verdict_summary">
        <StatusBadge tone={item.overall === "PASS" ? "ok" : "bad"} icon={item.overall === "PASS" ? <IconCheck className="h-3 w-3" /> : <IconX className="h-3 w-3" />}>
          iteration {item.iteration}/{MAX_VERIFIER_ITERATIONS} · {item.overall}{item.overall === "FAIL" ? " · revising" : ""}
        </StatusBadge>
      </li>
    );
  }
  if (item.kind === "cache") {
    return (
      <li className="enter flex items-center gap-2 px-1 text-[11px] text-muted" data-kind="cache">
        <IconBolt className="text-accent" />
        <span>
          <span className="font-semibold text-fg">cache hit</span> <span className="font-mono" title={item.data.cache_name}>{item.data.cache_name.includes("/") ? `…${item.data.cache_name.slice(-10)}` : item.data.cache_name}</span> · {item.data.cached_tokens.toLocaleString("en-US")} tokens · saved ${item.data.saved_usd.toFixed(4)}
        </span>
      </li>
    );
  }
  return (
    <li className="enter" data-kind="fallback">
      <StatusBadge tone="warn" icon={<IconAlert className="h-3 w-3" />} className="!whitespace-normal">
        model fallback · <span className="font-normal">{item.data.from_model} to {item.data.to_model} ({item.data.reason})</span>
      </StatusBadge>
    </li>
  );
}

function LaneView({ lane, tools, onEvidence }: { lane: Lane; tools: Record<string, ToolCard>; onEvidence: (id: string) => void }) {
  return (
    <section aria-label={`${humanize(lane.agent)} lane`} className="space-y-1.5" data-lane={lane.agent}>
      <header className="flex flex-wrap items-center gap-2">
        <h3 className="font-mono text-xs font-semibold uppercase tracking-wider">{humanize(lane.agent)}</h3>
        {lane.modelId && <span className="chip border-line text-muted">{lane.modelId}</span>}
        {!lane.modelId && lane.agent === "verifier" && <span className="chip border-line text-muted">deterministic code · no LLM</span>}
        {lane.status === "running" ? (
          <span className="inline-flex items-center gap-1 text-[11px] text-accent"><Spinner label="agent running" />working</span>
        ) : (
          <span className="inline-flex items-center gap-1 text-[11px] text-muted"><IconCheck className="h-3 w-3" />finished</span>
        )}
      </header>
      {lane.items.length > 0 && (
        <ul className="space-y-1.5 border-l border-line pl-2.5">
          {lane.items.map((it, i) =>
            it.kind === "tool" ? <ToolRow key={it.callId} t={tools[it.callId]} onEvidence={onEvidence} /> : <InlineBadge key={`${it.kind}${i}`} item={it} />,
          )}
        </ul>
      )}
    </section>
  );
}

export function TracePane({ state, onEvidence }: { state: IncidentState; onEvidence: (id: string) => void }) {
  const [auto, setAuto] = useState(true);
  const box = useRef<HTMLDivElement>(null);
  const size = state.toolOrder.length + state.lanes.length + state.errors.length + (state.draft ? 1 : 0) + Object.keys(state.verdicts).length + state.lanes.reduce((n, l) => n + l.items.length, 0);
  useEffect(() => {
    const el = box.current;
    if (auto && el && state.phase === "streaming") el.scrollTop = el.scrollHeight;
  }, [size, auto, state.phase]);
  const empty = state.phase === "idle" && !state.plan && state.lanes.length === 0;
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex items-center justify-between border-b border-line px-3 py-2">
        <h2 className="label">Agent trace</h2>
        <button type="button" className="btn !min-h-[28px] !px-2 !py-0.5 text-xs" aria-pressed={!auto} onClick={() => setAuto(!auto)}>
          {auto ? "Pause auto-scroll" : "Resume auto-scroll"}
        </button>
      </div>
      <div ref={box} className="relative min-h-0 flex-1 space-y-3 overflow-y-auto p-3" tabIndex={0} aria-label="Agent trace, scrollable" role="region">
        {empty && (
          <div className="rounded-md border border-dashed border-line p-4 text-sm text-muted">
            <p className="font-semibold text-fg">Idle. Nothing investigated yet.</p>
            <p className="mt-1">Pick a stopped-line scenario and press <span className="font-semibold">Investigate stop</span>. You will see the plan, every tool call with its evidence and provenance, the verifier checking each claim, and a safety-gated draft work order. This is a trace of work, not a chat.</p>
          </div>
        )}
        {state.plan && <PlanCard plan={state.plan} done={state.planDone} />}
        {state.lanes.map((l) => (
          <LaneView key={l.id} lane={l} tools={state.tools} onEvidence={onEvidence} />
        ))}
        {state.errors.map((e) => (
          <div key={e.seq} role="alert" className={`flex items-start gap-2 rounded border p-2 text-sm ${e.retryable ? "border-warn text-warn" : "border-bad text-bad"}`} data-error-code={e.code}>
            <IconAlert className="mt-0.5 shrink-0" />
            <div className="text-fg">
              <span className={`font-semibold ${e.retryable ? "text-warn" : "text-bad"}`}>{e.retrying ? "Error, retrying…" : e.retryable ? "Error (retried)" : "Error"}</span>{" "}
              <span className="font-mono text-xs text-muted">{e.code}</span>
              <div>{e.message}</div>
            </div>
          </div>
        ))}
        {state.phase === "streaming" && state.lanes.every((l) => l.status === "finished") && (
          <p className="flex items-center gap-2 text-xs text-muted"><Spinner label="working" />waiting for the next agent…</p>
        )}
      </div>
    </div>
  );
}
