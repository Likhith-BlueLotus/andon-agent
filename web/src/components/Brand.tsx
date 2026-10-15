import type { RunTone } from "../lib/progress";

/**
 * Andon tower: the stack light above every assembly station. Red = stopped, amber = someone
 * is working on it, green = resolved. Here it mirrors the investigation, so the logo is a status.
 */
export function AndonTower({ tone, size = 22 }: { tone: RunTone; size?: number }) {
  const red = tone === "idle" || tone === "bad";
  const amber = tone === "running" || tone === "warn";
  const green = tone === "verified" || tone === "approved";
  const lamp = (on: boolean, color: string, blink = false) => ({
    fill: on ? `rgb(var(--${color}))` : `rgb(var(--${color}) / 0.16)`,
    className: on && blink ? "blink" : undefined,
    style: on ? { filter: `drop-shadow(0 0 3px rgb(var(--${color}) / 0.9))` } : undefined,
  });
  return (
    <svg width={size * 0.62} height={size} viewBox="0 0 14 24" aria-hidden className="shrink-0">
      <rect x="2" y="0.5" width="10" height="1.6" rx="0.8" fill="rgb(var(--line-strong))" />
      <rect x="2.5" y="2.6" width="9" height="5" rx="1.4" {...lamp(red, "bad")} />
      <rect x="2.5" y="8.3" width="9" height="5" rx="1.4" {...lamp(amber, "warn", tone === "running")} />
      <rect x="2.5" y="14" width="9" height="5" rx="1.4" {...lamp(green, "ok")} />
      <rect x="6" y="19.6" width="2" height="2.6" fill="rgb(var(--line-strong))" />
      <rect x="3" y="22.2" width="8" height="1.6" rx="0.8" fill="rgb(var(--line-strong))" />
    </svg>
  );
}

const TONE_CLS: Record<RunTone, string> = {
  idle: "border-bad/40 text-bad",
  running: "border-warn/40 text-warn",
  verified: "border-ok/40 text-ok",
  approved: "border-ok/40 text-ok",
  warn: "border-warn/40 text-warn",
  bad: "border-bad/40 text-bad",
};
const DOT: Record<RunTone, string> = { idle: "bg-bad", running: "bg-warn blink", verified: "bg-ok", approved: "bg-ok", warn: "bg-warn", bad: "bg-bad" };

export function RunPill({ tone, text }: { tone: RunTone; text: string }) {
  return (
    <span className={`inline-flex items-center gap-2 rounded-full border bg-sunken/80 px-2.5 py-1 text-xs font-semibold ${TONE_CLS[tone]}`} data-testid="run-pill" data-tone={tone}>
      <span aria-hidden className={`h-2 w-2 rounded-full ${DOT[tone]}`} />
      <span className="text-fg">{text}</span>
    </span>
  );
}
