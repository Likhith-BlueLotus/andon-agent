import { useRef, useState, type ReactNode } from "react";
import { motion } from "motion/react";
import { MAX, RAIL, type useSidebarWidth } from "../state/useSidebarWidth";
import type { Catalog } from "../state/useCatalog";
import { BADGE_TEXT, THEME_STRING, readMock } from "../lib/config";
import { IconAlert, IconChart, IconCheck, IconGrid, IconInfo, IconKeyboard, IconMenu, IconMoon, IconSidebar, IconSun, IconUpload, IconWrench, IconX } from "./ui";
import { AndonTower, RunPill } from "./Brand";
import { useRun } from "../lib/runStore";
import type { Step, StepState } from "../lib/progress";
import { Dialog } from "./Dialog";

interface NavProps {
  path: string;
  navigate: (p: string) => void;
  catalog: Catalog;
  showUpload?: boolean;
  showTech?: boolean;
}

const VIEWS: { to: string; label: string; icon: (p: { className?: string }) => ReactNode; flag?: "upload" | "tech" }[] = [
  { to: "/", label: "Console", icon: IconGrid },
  { to: "/eval", label: "Eval", icon: IconChart },
  { to: "/upload", label: "Upload", icon: IconUpload, flag: "upload" },
  { to: "/tech", label: "Technician", icon: IconWrench, flag: "tech" },
];
const LABEL: Record<string, string> = { "/": "Console", "/eval": "Eval", "/upload": "Upload", "/tech": "Technician" };

/** Sidebar contents, shared by the desktop rail and the mobile drawer. */
function SideNav({ path, navigate, catalog, showUpload, showTech, onNavigate, compact = false }: NavProps & { onNavigate?: () => void; compact?: boolean }) {
  const run = useRun();
  return (
    <div className={`flex h-full flex-col ${compact ? "items-center" : ""}`} data-compact={compact}>
      <a
        href={"/" + window.location.search}
        onClick={(e) => {
          e.preventDefault();
          navigate("/");
          onNavigate?.();
        }}
        className={`flex items-center gap-2.5 rounded-xl py-1.5 ${compact ? "justify-center px-1" : "px-2"}`}
        aria-label={`Andon Agent home. Status: ${run.text}`}
        title={compact ? `Andon Agent · ${run.text}` : undefined}
      >
        <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-fg/5"><AndonTower tone={run.tone} size={18} /></span>
        {!compact && <span className="truncate text-sm font-semibold">Andon Agent</span>}
      </a>
      <p className={compact ? "sr-only" : "side-head"}>Views</p>
      <nav aria-label="Views" className={`space-y-0.5 ${compact ? "mt-3 flex flex-col items-center" : ""}`}>
        {VIEWS.filter((v) => !v.flag || (v.flag === "upload" ? showUpload : showTech)).map((v) => (
          <a
            key={v.to}
            href={v.to + window.location.search}
            aria-current={path === v.to ? "page" : undefined}
            onClick={(e) => {
              e.preventDefault();
              navigate(v.to);
              onNavigate?.();
            }}
            className={`nav-item ${compact ? "!h-10 !w-10 justify-center !px-0" : ""}`}
            title={compact ? v.label : undefined}
          >
            <v.icon className={`shrink-0 text-muted ${compact ? "h-[18px] w-[18px]" : "h-4 w-4"}`} />
            <span className={compact ? "sr-only" : "truncate"}>{v.label}</span>
          </a>
        ))}
      </nav>
      {path === "/" && run.steps && <SideSteps steps={run.steps} compact={compact} />}
      <div className={`mt-auto space-y-2 pt-6 text-[11px] leading-snug text-muted ${compact ? "px-0" : "px-3"}`}>
        {!compact && <p>Real signals are mapped onto a synthetic line; this is not real plant data.</p>}
        <About catalog={catalog} compact={compact} />
        {!compact && <p>{THEME_STRING}</p>}
      </div>
    </div>
  );
}

const DOT: Record<StepState, string> = {
  todo: "border-line-strong bg-transparent",
  active: "border-accent bg-accent",
  done: "border-ok bg-ok",
  fail: "border-bad bg-bad",
  warn: "border-warn bg-warn",
  skip: "border-dashed border-line-strong bg-transparent",
};

/** The investigation as a vertical checklist, the way the kit lists pages in its sidebar. */
function SideSteps({ steps, compact = false }: { steps: Step[]; compact?: boolean }) {
  if (compact) {
    return (
      <section aria-label="Investigation progress" className="mt-5 flex flex-col items-center" data-testid="side-steps">
        <span aria-hidden className="mb-2 h-px w-8 bg-line" />
        <ol className="flex flex-col items-center gap-2.5">
          {steps.map((s) => (
            <li key={s.id} data-step={s.id} data-state={s.state} title={`${s.label}: ${s.detail}`} aria-current={s.state === "active" ? "step" : undefined}>
              <span aria-hidden className={`block h-2.5 w-2.5 rounded-full border-2 ${DOT[s.state]} ${s.state === "active" ? "blink" : ""}`} />
              <span className="sr-only">{s.label}: {s.state === "todo" ? "not started" : s.state === "active" ? "in progress" : s.state}, {s.detail}</span>
            </li>
          ))}
        </ol>
      </section>
    );
  }
  return (
    <section aria-label="Investigation progress" className="mt-1" data-testid="side-steps">
      <p className="side-head">Investigation</p>
      <ol className="relative ml-3 space-y-0.5 border-l border-line pl-0">
        {steps.map((s) => (
          <li key={s.id} className="relative flex items-start gap-2.5 py-1 pl-4 pr-2" data-step={s.id} data-state={s.state} aria-current={s.state === "active" ? "step" : undefined}>
            <span aria-hidden className={`absolute -left-[5px] top-[9px] flex h-[9px] w-[9px] items-center justify-center rounded-full border-2 ${DOT[s.state]} ${s.state === "active" ? "blink" : ""}`} />
            <span className="min-w-0">
              <span className={`flex items-center gap-1 text-sm ${s.state === "todo" || s.state === "skip" ? "text-muted" : "text-fg"}`}>
                {s.label}
                {s.state === "done" && <IconCheck className="h-3 w-3 text-ok" aria-hidden />}
                {s.state === "fail" && <IconX className="h-3 w-3 text-bad" aria-hidden />}
                {s.state === "warn" && <IconAlert className="h-3 w-3 text-warn" aria-hidden />}
                <span className="sr-only">: {s.state === "todo" ? "not started" : s.state === "active" ? "in progress" : s.state}</span>
              </span>
              <span className={`block truncate text-xs ${s.state === "active" ? "text-accent" : "text-muted"}`}>{s.detail}</span>
            </span>
          </li>
        ))}
      </ol>
    </section>
  );
}

type Sb = ReturnType<typeof useSidebarWidth>;

/** Floating glass sidebar. Drag (or focus and use arrow keys on) the right edge to resize; narrow it to an icon rail. */
export function Sidebar({ sb, ...p }: NavProps & { sb: Sb }) {
  const ref = useRef<HTMLElement>(null);
  return (
    <motion.aside
      ref={ref}
      initial={false}
      animate={{ width: sb.width }}
      transition={sb.dragging ? { duration: 0 } : { type: "spring", stiffness: 420, damping: 40 }}
      className="glass relative z-20 my-3 ml-3 hidden shrink-0 rounded-3xl lg:block"
      aria-label="Sidebar"
      data-testid="sidebar"
    >
      <div className={`h-full overflow-y-auto overflow-x-hidden py-5 ${sb.compact ? "px-2" : "px-3"}`}>
        <SideNav {...p} compact={sb.compact} />
      </div>
      <div
        role="separator"
        aria-orientation="vertical"
        aria-label="Resize sidebar"
        aria-valuemin={RAIL}
        aria-valuemax={MAX}
        aria-valuenow={sb.width}
        aria-valuetext={sb.compact ? "collapsed to icons" : `${sb.width} pixels wide`}
        aria-keyshortcuts="ArrowLeft ArrowRight Home End Enter"
        tabIndex={0}
        title="Drag to resize · double-click to collapse"
        onPointerDown={(e) => sb.startDrag(e, ref.current!.getBoundingClientRect().left)}
        onDoubleClick={sb.toggle}
        onKeyDown={sb.onKey}
        className="group absolute -right-2 top-6 bottom-6 flex w-4 cursor-col-resize touch-none items-center justify-center rounded-full focus-visible:outline-none"
        data-testid="sidebar-resize"
      >
        <span aria-hidden className={`h-12 w-1 rounded-full transition-all duration-150 group-hover:h-20 group-hover:bg-accent group-focus-visible:h-20 group-focus-visible:bg-accent ${sb.dragging ? "h-24 bg-accent" : "bg-line-strong/70"}`} />
      </div>
    </motion.aside>
  );
}

export function TopBar({ path, navigate, theme, onTheme, catalog, showUpload = false, showTech = false, onShortcuts, sb }: NavProps & { theme: "dark" | "light"; onTheme: () => void; onShortcuts?: () => void; sb?: Sb }) {
  const mock = readMock();
  const run = useRun();
  const [drawer, setDrawer] = useState(false);
  return (
    <header className="glass relative z-30 mx-2 mt-2 flex shrink-0 flex-wrap items-center md:flex-nowrap gap-x-3 gap-y-2 rounded-2xl px-3 py-2.5 sm:mx-3 sm:mt-3 lg:ml-4 lg:px-4">
      <button type="button" className="btn-ghost !min-h-[40px] !min-w-[40px] lg:hidden" aria-label="Open navigation" onClick={() => setDrawer(true)}>
        <IconMenu className="h-5 w-5" />
      </button>
      {sb && (
        <button type="button" className="btn-ghost hidden !min-h-[34px] !min-w-[34px] lg:inline-flex" aria-label={sb.compact ? "Expand sidebar" : "Collapse sidebar"} aria-expanded={!sb.compact} title={`${sb.compact ? "Expand" : "Collapse"} sidebar ([)`} onClick={sb.toggle}>
          <IconSidebar className="h-4 w-4" />
        </button>
      )}
      <nav aria-label="Breadcrumb" className="min-w-0 md:flex-1">
        <ol className="flex min-w-0 items-center gap-2 whitespace-nowrap text-sm">
          <li className="hidden text-muted sm:block">Andon Agent</li>
          <li aria-hidden className="hidden text-line-strong sm:block">/</li>
          <li aria-current="page" className="font-medium">{LABEL[path] ?? "Console"}</li>
          {path === "/" && run.scenario && (
            <>
              <li aria-hidden className="hidden text-line-strong md:block">/</li>
              <li className="hidden min-w-0 truncate font-mono text-xs text-muted md:block" title={run.scenario}>{run.scenario}</li>
            </>
          )}
        </ol>
      </nav>
      <div className="ml-auto flex shrink-0 flex-wrap items-center justify-end gap-2 md:flex-nowrap">
        <span
          data-testid="synthetic-badge"
          className="chip border-fg/60 !text-[10px] font-semibold tracking-wide text-fg sm:!text-[11px]"
          title="The line is simulated. Signals marked REAL come from public datasets mapped onto it; they are not real plant data."
        >
          {catalog.scenarios?.badge ?? BADGE_TEXT}
        </span>
        {mock && <span className="chip hidden border-dashed border-line-strong text-muted sm:inline-flex">MOCK FIXTURE ({mock})</span>}
        {path === "/" && (
          <span className="hidden xl:inline-flex" aria-live="off">
            <RunPill tone={run.tone} text={run.text} />
          </span>
        )}
        {onShortcuts && (
          <button type="button" onClick={onShortcuts} className="hidden min-h-[32px] items-center gap-6 rounded-lg bg-fg/5 px-2.5 text-sm text-muted transition-colors hover:bg-fg/10 md:inline-flex" aria-label="Keyboard shortcuts">
            <span className="inline-flex items-center gap-1.5"><IconKeyboard className="h-4 w-4" />Shortcuts</span>
            <kbd className="kbd">?</kbd>
          </button>
        )}
        <button type="button" onClick={onTheme} className="btn-ghost !min-h-[36px] !min-w-[36px]" aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} theme`} title={`${theme === "dark" ? "Light" : "Dark"} theme (T)`}>
          {theme === "dark" ? <IconSun className="h-4 w-4" /> : <IconMoon className="h-4 w-4" />}
        </button>
      </div>
      {drawer && (
        <Dialog title="Navigation" onClose={() => setDrawer(false)} side="left" labelId="nav-title">
          <SideNav path={path} navigate={navigate} catalog={catalog} showUpload={showUpload} showTech={showTech} onNavigate={() => setDrawer(false)} />
        </Dialog>
      )}
    </header>
  );
}

/** Small footer for screens without the sidebar, so the theme line and attributions stay reachable. */
export function MobileFooter({ catalog }: { catalog: Catalog }) {
  return (
    <footer className="glass mx-2 mb-2 flex shrink-0 flex-wrap items-center gap-x-3 gap-y-0.5 rounded-2xl px-4 py-1.5 text-[11px] text-muted sm:mx-3 sm:mb-3 lg:hidden">
      <span className="font-mono">{THEME_STRING}</span>
      <span className="hidden md:inline">Real signals are mapped onto a synthetic line; this is not real plant data.</span>
      <span className="ml-auto"><About catalog={catalog} /></span>
    </footer>
  );
}

function About({ catalog, compact = false }: { catalog: Catalog; compact?: boolean }) {
  const [open, setOpen] = useState(false);
  const src = catalog.sources;
  return (
    <>
      {compact ? (
        <button type="button" className="btn-ghost !h-10 !w-10 !px-0" onClick={() => setOpen(true)} aria-label="Data attributions & about" title="Data attributions & about · synthetic line, real signals marked">
          <IconInfo className="h-[18px] w-[18px]" />
        </button>
      ) : (
        <button type="button" className="rounded text-left font-semibold text-fg underline-offset-2 hover:underline" onClick={() => setOpen(true)}>
          Data attributions &amp; about
        </button>
      )}
    {open && (
      <Dialog title="Data attributions & about" onClose={() => setOpen(false)} side labelId="attr-title">
        <div className="space-y-4 text-sm">
          <p><b>{THEME_STRING}</b></p>
          <p>Andon Agent investigates a stopped automotive line: it plans checks, runs analytics, cites the manual, has code verify every claim, and hands a human a verified root cause plus a safety-gated draft work order. The plant is <b>synthetic</b>. Real public-dataset signals are mapped onto it and are always marked <span className="font-mono">REAL</span>. Nothing here writes to a PLC, SCADA or historian; the only write is a draft work order awaiting human approval in a mock CMMS.</p>
          {!src && <p className="text-muted">Attributions load from the API (<span className="font-mono">/api/sources</span>); not available right now.</p>}
          {src && (
            <ul className="space-y-3">
              {src.datasets.map((d) => (
                <li key={d.id} className="card-raised p-3">
                  <p className="font-semibold">{d.name}</p>
                  <p className="text-xs text-muted">Licence: {d.licence}</p>
                  <p className="text-xs">Used for: {d.maps_to}</p>
                  <a href={d.page} target="_blank" rel="noreferrer noopener" className="break-all text-xs text-accent underline">{d.page}</a>
                  <details className="mt-1"><summary className="cursor-pointer text-xs text-muted underline">Citation</summary><pre className="mt-1 whitespace-pre-wrap font-sans text-xs">{d.citation}</pre></details>
                </li>
              ))}
            </ul>
          )}
          <p className="text-xs text-muted">Lockout/tagout steps are quoted verbatim from fictional equipment manuals written for this demo; the procedure structure follows OSHA 29 CFR 1910.147 (public domain).</p>
          {src && <p className="text-xs text-muted">{src.note}</p>}
        </div>
      </Dialog>
    )}
    </>
  );
}
