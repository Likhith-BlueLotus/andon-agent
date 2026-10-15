import { motion } from "motion/react";
import type { Step, StepState } from "../lib/progress";
import { IconAlert, IconCheck, IconX } from "./ui";

const NODE: Record<StepState, string> = {
  todo: "border-line-strong bg-sunken text-muted",
  active: "border-accent bg-accent/15 text-accent",
  done: "border-ok bg-ok text-bg",
  fail: "border-bad bg-bad text-bg",
  warn: "border-warn bg-warn/15 text-warn",
  skip: "border-dashed border-line-strong bg-transparent text-muted",
};
const WORD: Record<StepState, string> = { todo: "not started", active: "in progress", done: "done", fail: "rejected", warn: "needs attention", skip: "skipped" };

/** Investigation progress, read from the event stream. A list for assistive tech; a rail for the eye. */
export function Stepper({ steps }: { steps: Step[] }) {
  const current = steps.findIndex((s) => s.state === "active" || s.state === "warn");
  return (
    <nav aria-label="Investigation progress" className="shrink-0 border-b border-line bg-panel/70 px-3 py-2 backdrop-blur-sm" data-testid="stepper">
      <Compact steps={steps} current={current} />
      <ol className="hidden items-start gap-0 overflow-x-auto [scrollbar-width:none] md:flex">
        {steps.map((s, i) => {
          const isCurrent = i === current;
          const doneLine = s.state === "done" && i < steps.length - 1;
          return (
            <li key={s.id} className={`flex items-start ${i < steps.length - 1 ? "min-w-[104px] flex-1" : "flex-none"}`} data-step={s.id} data-state={s.state} aria-current={isCurrent ? "step" : undefined}>
              <div className="flex w-[84px] shrink-0 flex-col items-center gap-1 px-1 text-center">
                <span className="relative flex h-6 w-6 items-center justify-center">
                  {s.state === "active" && <span aria-hidden className="absolute inset-0 rounded-full bg-accent/30 motion-safe:animate-ping" />}
                  <motion.span
                    key={s.state}
                    initial={{ scale: 0.6, opacity: 0.4 }}
                    animate={{ scale: 1, opacity: 1 }}
                    transition={{ type: "spring", stiffness: 520, damping: 26 }}
                    className={`relative flex h-6 w-6 items-center justify-center rounded-full border-2 font-mono text-[10px] font-bold ${NODE[s.state]}`}
                    aria-hidden
                  >
                    {s.state === "done" ? <IconCheck className="h-3.5 w-3.5" /> : s.state === "fail" ? <IconX className="h-3.5 w-3.5" /> : s.state === "warn" ? <IconAlert className="h-3 w-3" /> : i + 1}
                  </motion.span>
                </span>
                <span className={`text-[12px] font-semibold leading-tight ${s.state === "todo" || s.state === "skip" ? "text-muted" : "text-fg"}`}>
                  {s.label}
                  <span className="sr-only">: {WORD[s.state]}, {s.detail}</span>
                </span>
                <span aria-hidden className={`hidden truncate font-mono text-[10px] leading-tight sm:block ${s.state === "active" ? "text-accent" : s.state === "warn" ? "text-warn" : "text-muted"} max-w-full`}>
                  {s.detail}
                </span>
              </div>
              {i < steps.length - 1 && (
                <span aria-hidden className="relative mt-3 h-0.5 min-w-[16px] flex-1 overflow-hidden rounded-full bg-line">
                  <motion.span className="absolute inset-y-0 left-0 rounded-full bg-ok" initial={false} animate={{ width: doneLine && steps[i + 1].state !== "todo" ? "100%" : doneLine ? "50%" : "0%" }} transition={{ duration: 0.45, ease: [0.2, 0.8, 0.2, 1] }} />
                </span>
              )}
            </li>
          );
        })}
      </ol>
    </nav>
  );
}

const BAR: Record<StepState, string> = { todo: "bg-sunken", active: "bg-accent blink", done: "bg-ok", fail: "bg-bad", warn: "bg-warn", skip: "bg-line" };

/** Phones: one line of text plus a segmented bar, instead of a rail that would scroll sideways. */
function Compact({ steps, current }: { steps: Step[]; current: number }) {
  const lastDone = steps.reduce((n, s, i) => (s.state === "done" ? i : n), -1);
  const focus = current >= 0 ? current : Math.min(lastDone + 1, steps.length - 1);
  const s = steps[focus];
  const allDone = steps.every((x) => x.state === "done" || x.state === "skip");
  return (
    <div className="md:hidden" data-testid="stepper-compact">
      <div className="flex items-baseline justify-between gap-2 text-xs">
        <span className="font-semibold">
          {allDone ? "All steps done" : <>Step {focus + 1}/{steps.length} · {s.label}</>}
        </span>
        <span className={`truncate font-mono text-[11px] ${s.state === "active" ? "text-accent" : s.state === "warn" ? "text-warn" : "text-muted"}`}>{allDone ? steps[steps.length - 1].detail : s.detail}</span>
      </div>
      <div aria-hidden className="mt-1.5 flex gap-1">
        {steps.map((x) => (
          <span key={x.id} className={`h-1 flex-1 rounded-full ${BAR[x.state]}`} />
        ))}
      </div>
    </div>
  );
}
