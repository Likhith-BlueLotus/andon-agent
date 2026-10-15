import { useEffect, useRef, useState } from "react";
import type { IncidentState, Lane, ToolCard, TraceItem } from "../state/reducer";
import { argsLine, briefSummary, qualityNotes } from "../lib/summary";
import { humanize } from "../lib/format";
import { MAX_VERIFIER_ITERATIONS } from "../lib/config";
import type { ReactNode } from "react";
import { motion } from "motion/react";
import { EvidenceChip, IconAlert, IconBolt, IconBook, IconCheck, IconChevron, IconClipboard, IconClock, IconCompass, IconLayers, IconPause, IconPlay, IconScale, IconShield, IconWave, IconX, ProvenanceChip, Spinner, StatusBadge } from "./ui";

/** One glyph per agent so a lane is recognisable before its name is read. */
const AGENT_GLYPH: Record<string, (p: { className?: string }) => ReactNode> = {
  commander: IconCompass,
  signal_analyst: IconWave,
  evidence_librarian: IconBook,
  rca_judge: IconScale,
  verifier: IconShield,
  action_drafter: IconClipboard,
};
const enter = { initial: { opacity: 0, y: 6 }, animate: { opacity: 1, y: 0 }, transition: { duration: 0.26, ease: [0.2, 0.8, 0.2, 1] as const } };

export function PlanCard({ plan, done }: { plan: string[]; done: number }) {
  return (
    <motion.section {...enter} aria-label="Investigation plan" className="card p-3">
      <div className="flex items-baseline justify-between">
        <h3 className="label">Plan</h3>
        <span className="font-mono text-[11px] text-muted" title="Indicative progress: plan steps carry no link to individual tool calls">
          {done}/{plan.length} checked
        </span>
      </div>
      <div aria-hidden className="mt-2 h-1 overflow-hidden rounded-full bg-sunken">
        <motion.div className="h-full rounded-full bg-accent" initial={false} animate={{ width: `${plan.length ? (Math.min(done, plan.length) / plan.length) * 100 : 0}%` }} transition={{ duration: 0.5, ease: [0.2, 0.8, 0.2, 1] }} />
      </div>
      <ol className="mt-2 space-y-1.5">
        {plan.map((s, i) => {
          const ticked = i < done;
          return (
            <li key={i} className="flex gap-2 text-[13px]" data-ticked={ticked}>
              <span
                aria-hidden
                className={`mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded border transition-colors duration-300 ${
                  ticked ? "border-accent bg-accent text-accent-fg" : i === done ? "border-accent text-accent" : "border-line-strong text-muted"
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
    </motion.section>
  );
}

function ToolRow({ t, onEvidence }: { t: ToolCard; onEvidence: (id: string) => void }) {
  const [open, setOpen] = useState(false);
  const notes = t.summary && !t.toolError ? qualityNotes(t.summary) : [];
  const running = t.status === "running";
  return (
    <motion.li
      {...enter}
      data-call-id={t.callId}
      data-status={t.status}
      className={`relative rounded-lg border bg-panel px-3 py-2 transition-colors duration-300 ${running ? "sheen border-transparent" : t.status === "error" ? "border-warn/70" : "border-line hover:border-line-strong"}`}
    >
      <span aria-hidden className={`absolute -left-[17px] top-3 h-2 w-2 rounded-full ring-4 ring-panel ${running ? "bg-accent" : t.status === "error" ? "bg-warn" : "bg-line-strong"}`} />
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <span className="flex w-4 justify-center" aria-hidden>
          {running ? <span className="spinner" /> : t.status === "error" ? <IconAlert className="text-warn" /> : <IconCheck className="text-ok" />}
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
          <pre className="well max-h-40 overflow-auto p-2 font-mono text-[11px]" aria-label="Tool arguments">{JSON.stringify(t.args, null, 2)}</pre>
          {t.summary && (
            <pre className="well max-h-56 overflow-auto p-2 font-mono text-[11px]" aria-label="Tool result summary">{JSON.stringify(t.summary, null, 2)}</pre>
          )}
        </div>
      )}
    </motion.li>
  );
}

const IconInfo2 = () => <span aria-hidden className="mt-px font-mono">·</span>;

function InlineBadge({ item }: { item: Exclude<TraceItem, { kind: "tool" }> }) {
  if (item.kind === "proposed") {
    return (
      <motion.li {...enter} className="px-1 text-[11px] text-muted" data-kind="proposed">
        proposed <span className="font-semibold text-fg">{item.count} hypothes{item.count === 1 ? "is" : "es"}</span>
        {item.top && <> · top: <span className="font-mono">{item.top}</span></>} · awaiting verifier
      </motion.li>
    );
  }
  if (item.kind === "verdict") {
    const v = item.verdict;
    const bad = v.verdict !== "pass";
    return (
      <motion.li {...enter} className="flex items-start gap-1.5 px-1 text-[12px]" data-kind="verdict" data-verdict={v.verdict}>
        {bad ? <IconX className="mt-0.5 shrink-0 text-bad" /> : <IconCheck className="mt-0.5 shrink-0 text-ok" />}
        <span className="min-w-0">
          <span className={`font-semibold ${bad ? "text-bad" : "text-ok"}`}>{v.verdict === "pass" ? "verified" : v.verdict === "fail" ? "rejected" : "unverifiable"}</span>{" "}
          <span className="font-mono text-[11px] text-muted">{v.claim_id}</span>{" "}
          <span className={bad ? "text-muted line-through decoration-bad" : "text-muted"}>{item.text}</span>
          {v.measured_value != null && bad && <span className="font-mono text-bad"> · measured {v.measured_value}</span>}
        </span>
      </motion.li>
    );
  }
  if (item.kind === "verdict_summary") {
    return (
      <motion.li {...enter} className="px-1" data-kind="verdict_summary">
        <StatusBadge tone={item.overall === "PASS" ? "ok" : "bad"} icon={item.overall === "PASS" ? <IconCheck className="h-3 w-3" /> : <IconX className="h-3 w-3" />}>
          iteration {item.iteration}/{MAX_VERIFIER_ITERATIONS} · {item.overall}{item.overall === "FAIL" ? " · revising" : ""}
        </StatusBadge>
      </motion.li>
    );
  }
  if (item.kind === "cache") {
    return (
      <motion.li {...enter} className="flex items-center gap-2 px-1 text-[11px] text-muted" data-kind="cache">
        <IconBolt className="text-accent" />
        <span>
          <span className="font-semibold text-fg">cache hit</span> <span className="font-mono" title={item.data.cache_name}>{item.data.cache_name.includes("/") ? `…${item.data.cache_name.slice(-10)}` : item.data.cache_name}</span> · {item.data.cached_tokens.toLocaleString("en-US")} tokens · saved ${item.data.saved_usd.toFixed(4)}
        </span>
      </motion.li>
    );
  }
  return (
    <motion.li {...enter} data-kind="fallback">
      <StatusBadge tone="warn" icon={<IconAlert className="h-3 w-3" />} className="!whitespace-normal">
        model fallback · <span className="font-normal">{item.data.from_model} to {item.data.to_model} ({item.data.reason})</span>
      </StatusBadge>
    </motion.li>
  );
}

function LaneView({ lane, tools, onEvidence }: { lane: Lane; tools: Record<string, ToolCard>; onEvidence: (id: string) => void }) {
  return (
    <motion.section {...enter} aria-label={`${humanize(lane.agent)} lane`} className="space-y-2" data-lane={lane.agent}>
      <header className="flex flex-wrap items-center gap-2">
        <span aria-hidden className={`relative flex h-7 w-7 items-center justify-center rounded-lg border ${lane.status === "running" ? "border-accent bg-accent/15 text-accent" : "border-line-strong bg-raised text-fg"}`}>
          <Glyph agent={lane.agent} />
          {lane.status === "running" && <span className="absolute -right-0.5 -top-0.5 h-2 w-2 rounded-full bg-accent ring-2 ring-panel blink" />}
        </span>
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
        <ul className="ml-3.5 space-y-1.5 border-l border-line pl-3">
          {lane.items.map((it, i) =>
            it.kind === "tool" ? <ToolRow key={it.callId} t={tools[it.callId]} onEvidence={onEvidence} /> : <InlineBadge key={`${it.kind}${i}`} item={it} />,
          )}
        </ul>
      )}
    </motion.section>
  );
}

function Glyph({ agent }: { agent: string }) {
  const G = AGENT_GLYPH[agent] ?? IconLayers;
  return <G className="h-4 w-4" />;
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
      <div className="pane-head justify-between">
        <div className="flex min-w-0 items-center gap-3">
          <h2 className="label whitespace-nowrap">Agent trace</h2>
          {state.toolOrder.length > 0 && (
            <span className="hidden truncate whitespace-nowrap font-mono text-[11px] text-muted sm:inline">
              {state.lanes.length} agent{state.lanes.length === 1 ? "" : "s"} · {state.toolOrder.length} tool call{state.toolOrder.length === 1 ? "" : "s"}
            </span>
          )}
        </div>
        <button type="button" className="btn-ghost !min-h-[30px] whitespace-nowrap text-xs" aria-pressed={!auto} onClick={() => setAuto(!auto)}>
          {auto ? <IconPause className="h-3.5 w-3.5" /> : <IconPlay className="h-3.5 w-3.5" />}
          {auto ? "Pause auto-scroll" : "Resume auto-scroll"}
        </button>
      </div>
      <div ref={box} className="relative min-h-0 flex-1 space-y-3 overflow-y-auto p-3" tabIndex={0} aria-label="Agent trace, scrollable" role="region">
        {empty && <TraceEmpty />}
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

const PREVIEW: { glyph: (p: { className?: string }) => ReactNode; title: string; text: string }[] = [
  { glyph: IconCompass, title: "Plan", text: "The commander lays out which checks to run." },
  { glyph: IconWave, title: "Evidence", text: "Every tool call shows its evidence id and whether the signal is REAL or SYNTHETIC." },
  { glyph: IconShield, title: "Verify", text: "Code re-checks every claim. Wrong ones are struck through, never hidden." },
  { glyph: IconClipboard, title: "Act", text: "A draft work order with verbatim LOTO steps waits for a human." },
];

function TraceEmpty() {
  return (
    <div className="mx-auto max-w-xl py-6">
      <p className="text-base font-semibold">Idle. Nothing investigated yet.</p>
      <p className="mt-1 text-sm text-muted">
        Pick a stopped-line scenario and press <span className="font-semibold text-fg">Investigate stop</span> <span className="kbd" aria-hidden>I</span>. This is a trace of work, not a chat.
      </p>
      <ol className="mt-5 space-y-2">
        {PREVIEW.map((p, i) => (
          <motion.li key={p.title} initial={{ opacity: 0, x: -6 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: 0.06 * i, duration: 0.3 }} className="flex items-start gap-3 rounded-lg border border-dashed border-line-strong/70 p-3">
            <span aria-hidden className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-line bg-raised text-accent"><p.glyph className="h-4 w-4" /></span>
            <span className="min-w-0">
              <span className="block text-sm font-semibold"><span className="mr-1.5 font-mono text-xs text-muted">{i + 1}</span>{p.title}</span>
              <span className="block text-[13px] text-muted">{p.text}</span>
            </span>
          </motion.li>
        ))}
      </ol>
    </div>
  );
}
