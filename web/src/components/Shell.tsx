import { useState } from "react";
import type { Catalog } from "../state/useCatalog";
import { BADGE_TEXT, THEME_STRING, readMock } from "../lib/config";
import { IconMoon, IconSun } from "./ui";
import { Dialog } from "./Dialog";

export function Header({ path, navigate, theme, onTheme, catalog }: { path: string; navigate: (p: string) => void; theme: "dark" | "light"; onTheme: () => void; catalog: Catalog }) {
  const mock = readMock();
  const link = (to: string, label: string) => (
    <a
      href={to + window.location.search}
      aria-current={path === to ? "page" : undefined}
      onClick={(e) => {
        e.preventDefault();
        navigate(to);
      }}
      className={`rounded px-2 py-1 text-sm ${path === to ? "bg-raised font-semibold text-fg" : "text-muted hover:text-fg"}`}
    >
      {label}
    </a>
  );
  return (
    <header className="flex shrink-0 flex-wrap items-center gap-x-3 gap-y-1 border-b border-line bg-panel px-3 py-2">
      <div className="flex items-center gap-2">
        <span aria-hidden className="inline-block h-3 w-3 rounded-full bg-accent" />
        <span className="font-mono text-sm font-semibold tracking-wide">ANDON AGENT</span>
      </div>
      <span
        data-testid="synthetic-badge"
        className="chip border-fg/70 bg-raised !text-[11px] font-semibold tracking-wide text-fg"
        title="The line is simulated. Signals marked REAL come from public datasets mapped onto it; they are not real plant data."
      >
        {catalog.scenarios?.badge ?? BADGE_TEXT}
      </span>
      {mock && <span className="chip border-line text-muted">MOCK FIXTURE ({mock})</span>}
      <nav aria-label="Views" className="ml-auto flex items-center gap-1">
        {link("/", "Console")}
        {link("/eval", "Eval")}
        <button type="button" onClick={onTheme} className="btn !min-h-[32px] !px-2" aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} theme`}>
          {theme === "dark" ? <IconSun /> : <IconMoon />}
          <span className="hidden sm:inline">{theme === "dark" ? "Light" : "Dark"}</span>
        </button>
      </nav>
    </header>
  );
}

export function Footer({ catalog }: { catalog: Catalog }) {
  const [open, setOpen] = useState(false);
  const src = catalog.sources;
  return (
    <footer className="shrink-0 border-t border-line bg-panel px-3 py-1.5 text-[11px] text-muted">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-0.5">
        <span className="font-mono">{THEME_STRING}</span>
        <span>Real signals are mapped onto a synthetic line; this is not real plant data.</span>
        <button type="button" className="ml-auto rounded font-semibold text-accent underline" onClick={() => setOpen(true)}>
          Data attributions &amp; about
        </button>
      </div>
      {open && (
        <Dialog title="Data attributions & about" onClose={() => setOpen(false)} side labelId="attr-title">
          <div className="space-y-4 text-sm">
            <p><b>{THEME_STRING}</b></p>
            <p>Andon Agent investigates a stopped automotive line: it plans checks, runs analytics, cites the manual, has code verify every claim, and hands a human a verified root cause plus a safety-gated draft work order. The plant is <b>synthetic</b>. Real public-dataset signals are mapped onto it and are always marked <span className="font-mono">REAL</span>. Nothing here writes to a PLC, SCADA or historian; the only write is a draft work order awaiting human approval in a mock CMMS.</p>
            {!src && <p className="text-muted">Attributions load from the API (<span className="font-mono">/api/sources</span>); not available right now.</p>}
            {src && (
              <ul className="space-y-3">
                {src.datasets.map((d) => (
                  <li key={d.id} className="rounded border border-line p-2">
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
    </footer>
  );
}
