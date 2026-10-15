import { useId, useState, type ReactNode } from "react";
import type { ProvenanceRef } from "../types/events";
import { sourceName } from "../lib/format";

type IconProps = { className?: string };
const base = (p: IconProps) => ({ width: 14, height: 14, viewBox: "0 0 16 16", fill: "none", stroke: "currentColor", strokeWidth: 1.8, strokeLinecap: "round" as const, strokeLinejoin: "round" as const, "aria-hidden": true as const, className: p.className });

export const IconCheck = (p: IconProps) => (<svg {...base(p)}><path d="M3 8.5l3.2 3L13 4.5" /></svg>);
export const IconX = (p: IconProps) => (<svg {...base(p)}><path d="M4 4l8 8M12 4l-8 8" /></svg>);
export const IconAlert = (p: IconProps) => (<svg {...base(p)}><path d="M8 2l6.5 11.5h-13z" /><path d="M8 6.5v3.2M8 11.5v.1" /></svg>);
export const IconLock = (p: IconProps) => (<svg {...base(p)}><rect x="3" y="7" width="10" height="7" rx="1.5" /><path d="M5.5 7V5a2.5 2.5 0 015 0v2" /></svg>);
export const IconInfo = (p: IconProps) => (<svg {...base(p)}><circle cx="8" cy="8" r="6" /><path d="M8 7.2v4M8 4.9v.1" /></svg>);
export const IconChevron = (p: IconProps) => (<svg {...base(p)}><path d="M6 3.5L10.5 8 6 12.5" /></svg>);
export const IconClock = (p: IconProps) => (<svg {...base(p)}><circle cx="8" cy="8" r="6" /><path d="M8 4.5V8l2.3 1.5" /></svg>);
export const IconSun = (p: IconProps) => (<svg {...base(p)}><circle cx="8" cy="8" r="2.8" /><path d="M8 1.5v1.8M8 12.7v1.8M1.5 8h1.8M12.7 8h1.8M3.4 3.4l1.3 1.3M11.3 11.3l1.3 1.3M12.6 3.4l-1.3 1.3M4.7 11.3l-1.3 1.3" /></svg>);
export const IconMoon = (p: IconProps) => (<svg {...base(p)}><path d="M13 9.5A5.5 5.5 0 116.5 3a4.5 4.5 0 006.5 6.5z" /></svg>);
export const IconBolt = (p: IconProps) => (<svg {...base(p)}><path d="M9 1.5L3.5 9H8l-1 5.5L12.5 7H8z" /></svg>);
export const IconPlay = (p: IconProps) => (<svg {...base(p)}><path d="M5 3.2v9.6L12.8 8z" fill="currentColor" /></svg>);
export const IconPause = (p: IconProps) => (<svg {...base(p)}><path d="M5.5 3.5v9M10.5 3.5v9" /></svg>);
export const IconChart = (p: IconProps) => (<svg {...base(p)}><path d="M2.5 13.5h11M4.5 11V8M8 11V4.5M11.5 11V6.5" /></svg>);
export const IconUpload = (p: IconProps) => (<svg {...base(p)}><path d="M8 10.5V2.5M5 5.5l3-3 3 3M2.5 10v2.5a1 1 0 001 1h9a1 1 0 001-1V10" /></svg>);
export const IconMenu = (p: IconProps) => (<svg {...base(p)}><path d="M2.5 4.5h11M2.5 8h11M2.5 11.5h11" /></svg>);
export const IconSidebar = (p: IconProps) => (<svg {...base(p)}><rect x="2" y="2.5" width="12" height="11" rx="2" /><path d="M6 2.5v11" /></svg>);
export const IconGrid = (p: IconProps) => (<svg {...base(p)}><rect x="2.5" y="2.5" width="4.5" height="4.5" rx="1" /><rect x="9" y="2.5" width="4.5" height="4.5" rx="1" /><rect x="2.5" y="9" width="4.5" height="4.5" rx="1" /><rect x="9" y="9" width="4.5" height="4.5" rx="1" /></svg>);
export const IconStop = (p: IconProps) => (<svg {...base(p)}><rect x="4" y="4" width="8" height="8" rx="1.2" fill="currentColor" /></svg>);
export const IconArrowRight = (p: IconProps) => (<svg {...base(p)}><path d="M3 8h10M9 4l4 4-4 4" /></svg>);
export const IconKeyboard = (p: IconProps) => (<svg {...base(p)}><rect x="1.5" y="4" width="13" height="8" rx="1.5" /><path d="M4 6.5h.01M6.5 6.5h.01M9 6.5h.01M11.5 6.5h.01M5 9.5h6" /></svg>);
export const IconShield = (p: IconProps) => (<svg {...base(p)}><path d="M8 1.8l5 2v4c0 3-2.2 5.3-5 6.4-2.8-1.1-5-3.4-5-6.4v-4z" /><path d="M5.8 8.2l1.6 1.5 2.9-3" /></svg>);
export const IconWrench = (p: IconProps) => (<svg {...base(p)}><path d="M10.2 2.2a3.2 3.2 0 00-3.9 4.3L2.2 10.6a1.3 1.3 0 001.8 1.8l4.1-4.1a3.2 3.2 0 004.3-3.9l-1.9 1.9-1.6-.4-.4-1.6z" /></svg>);
export const IconCompass = (p: IconProps) => (<svg {...base(p)}><circle cx="8" cy="8" r="6" /><path d="M10.5 5.5L9 9 5.5 10.5 7 7z" /></svg>);
export const IconWave = (p: IconProps) => (<svg {...base(p)}><path d="M1.5 8h2l1.5-4 2 8 2-6 1.5 4 1-2h3" /></svg>);
export const IconBook = (p: IconProps) => (<svg {...base(p)}><path d="M2.5 3.2c2-.8 3.8-.6 5.5.6v9.4c-1.7-1.2-3.5-1.4-5.5-.6zM13.5 3.2c-2-.8-3.8-.6-5.5.6v9.4c1.7-1.2 3.5-1.4 5.5-.6z" /></svg>);
export const IconScale = (p: IconProps) => (<svg {...base(p)}><path d="M8 2v12M4.5 14h7M3 4.5h10M3 4.5L1.5 8.5a2 2 0 003 0zM13 4.5l-1.5 4a2 2 0 003 0z" /></svg>);
export const IconClipboard = (p: IconProps) => (<svg {...base(p)}><rect x="3" y="2.8" width="10" height="11.5" rx="1.5" /><path d="M6 2.8V2h4v.8M5.5 7h5M5.5 9.5h5M5.5 12h3" /></svg>);
export const IconLayers = (p: IconProps) => (<svg {...base(p)}><path d="M8 2l6 3.2-6 3.2-6-3.2z" /><path d="M2 8.2l6 3.2 6-3.2M2 11l6 3.2 6-3.2" /></svg>);

export function Spinner({ label }: { label?: string }) {
  return (
    <span role="status" className="inline-flex items-center">
      <span className="spinner" aria-hidden />
      <span className="sr-only">{label ?? "running"}</span>
    </span>
  );
}

/** Inline popover that opens on hover and keyboard focus, closes on Escape. */
export function Popover({ trigger, children, label, className = "" }: { trigger: ReactNode; children: ReactNode; label: string; className?: string }) {
  const [open, setOpen] = useState(false);
  const id = useId();
  return (
    <span className={`relative inline-block ${className}`} onMouseEnter={() => setOpen(true)} onMouseLeave={() => setOpen(false)}>
      <button
        type="button"
        aria-label={label}
        aria-describedby={open ? id : undefined}
        onFocus={() => setOpen(true)}
        onBlur={() => setOpen(false)}
        onKeyDown={(e) => {
          if (e.key === "Escape") setOpen(false);
        }}
        className="inline-flex items-center rounded"
      >
        {trigger}
      </button>
      {open && (
        <span id={id} role="tooltip" className="absolute left-0 top-full z-30 mt-1 w-72 max-w-[80vw] rounded-md border border-line bg-raised p-2 text-left text-xs font-normal normal-case tracking-normal text-fg shadow-lg">
          {children}
        </span>
      )}
    </span>
  );
}

/** Real-signal provenance: outlined. Synthetic: filled and muted. Tooltip lists the source rows. */
export function ProvenanceChip({ provenance }: { provenance: ProvenanceRef[] }) {
  if (provenance.length === 0) return null;
  const groups = new Map<string, ProvenanceRef[]>();
  for (const p of provenance) groups.set(`${p.source_id}|${p.real}`, [...(groups.get(`${p.source_id}|${p.real}`) ?? []), p]);
  return (
    <span className="inline-flex flex-wrap gap-1">
      {[...groups.values()].map((refs) => {
        const r = refs[0];
        const upload = r.source_id === "user_upload";
        const text = upload ? "USER UPLOAD" : r.real ? `REAL · ${sourceName(r.source_id)}` : "SYNTHETIC";
        return (
          <Popover
            key={`${r.source_id}${r.real}`}
            label={`${text}. Show source rows and transform`}
            trigger={
              <span
                className={`chip ${upload ? "border-dashed border-accent bg-accent/10 font-semibold text-accent" : r.real ? "border-fg bg-transparent font-semibold text-fg" : "border-transparent bg-raised text-muted"}`}
                data-provenance={upload ? "upload" : r.real ? "real" : "synthetic"}
              >
                {text}
              </span>
            }
          >
            <span className="block font-mono text-[11px] uppercase tracking-wider text-muted">
              {upload ? "Your uploaded file, mapped by you onto the synthetic line. Not a verified public source." : r.real ? "Real signal mapped onto a synthetic line" : "Simulated on the synthetic line"}
            </span>
            <ul className="mt-1 space-y-1">
              {refs.map((x, i) => (
                <li key={i} className="break-words font-mono text-[11px]">
                  <span className="text-muted">source_id </span>
                  {x.source_id}
                  <br />
                  <span className="text-muted">source_ref </span>
                  {x.source_ref ?? "(none given)"}
                </li>
              ))}
            </ul>
          </Popover>
        );
      })}
    </span>
  );
}

export function EvidenceChip({ id, onOpen }: { id: string; onOpen?: (id: string) => void }) {
  if (!id) return null;
  return (
    <button
      type="button"
      onClick={() => onOpen?.(id)}
      aria-label={`Open evidence ${id}`}
      data-evidence-id={id}
      className="chip border-accent/60 bg-transparent text-accent hover:bg-accent/10"
    >
      {id}
    </button>
  );
}

export type Tone = "ok" | "warn" | "bad" | "accent" | "muted";
const TONE: Record<Tone, string> = {
  ok: "border-ok text-ok",
  warn: "border-warn text-warn",
  bad: "border-bad text-bad",
  accent: "border-accent text-accent",
  muted: "border-line text-muted",
};
/** Status is never colour-only: every badge carries an icon and a word. */
export function StatusBadge({ tone, icon, children, className = "" }: { tone: Tone; icon?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <span className={`chip ${TONE[tone]} bg-transparent font-semibold ${className}`}>
      {icon}
      {children}
    </span>
  );
}
