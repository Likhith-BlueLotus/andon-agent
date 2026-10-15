import { lazy, Suspense, useCallback, useEffect, useState } from "react";
import { Console } from "./components/Console";
import { MobileFooter, Sidebar, TopBar } from "./components/Shell";
import { techEnabled, uploadEnabled } from "./lib/features";
import { useCatalog } from "./state/useCatalog";
import { useTheme } from "./state/useTheme";
import { MotionConfig } from "motion/react";
import { useHotkeys } from "./lib/hotkeys";
import { useSidebarWidth } from "./state/useSidebarWidth";
import { Dialog } from "./components/Dialog";

const UploadPage = lazy(() => import("./pages/UploadPage").then((m) => ({ default: m.UploadPage })));
const TechPage = lazy(() => import("./pages/TechPage").then((m) => ({ default: m.TechPage })));
const EvalPage = lazy(() => import("./pages/EvalPage").then((m) => ({ default: m.EvalPage })));

const ROUTES = ["/eval", "/upload", "/tech"];

function currentPath(): string {
  const p = window.location.pathname.replace(/\/+$/, "") || "/";
  return ROUTES.includes(p) ? p : "/";
}

export default function App() {
  const [path, setPath] = useState(currentPath());
  const [theme, toggleTheme] = useTheme();
  const catalog = useCatalog();
  useEffect(() => {
    const on = () => setPath(currentPath());
    window.addEventListener("popstate", on);
    return () => window.removeEventListener("popstate", on);
  }, []);
  const navigate = useCallback((to: string) => {
    // `to` may carry its own query (e.g. "/?scenario=U001&mode=live"); keep the mock switches from the current URL.
    const [p, q = ""] = to.split("?");
    const next = new URLSearchParams(q);
    const cur = new URLSearchParams(window.location.search);
    for (const [k, val] of cur) if (k !== "scenario" && k !== "mode" && k !== "incident" && !next.has(k)) next.set(k, val);
    const qs = next.toString();
    window.history.pushState({}, "", p + (qs ? `?${qs}` : ""));
    setPath(ROUTES.includes(p) ? p : "/");
  }, []);
  const [shortcuts, setShortcuts] = useState(false);
  const sb = useSidebarWidth();
  useHotkeys({ "?": () => setShortcuts(true), t: toggleTheme, "[": sb.toggle });
  return (
    <MotionConfig reducedMotion="user">
    <div className="relative flex h-dvh overflow-hidden">
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-50 focus:rounded focus:bg-accent focus:px-3 focus:py-2 focus:text-accent-fg">Skip to content</a>
      {path === "/" && <a href="#pane-rca" className="sr-only xl:focus:not-sr-only xl:focus:absolute xl:focus:left-60 xl:focus:top-2 xl:focus:z-50 xl:focus:rounded xl:focus:bg-accent xl:focus:px-3 xl:focus:py-2 xl:focus:text-accent-fg">Skip to root cause</a>}
      <Sidebar sb={sb} path={path} navigate={navigate} catalog={catalog} showUpload={uploadEnabled(catalog.config)} showTech={techEnabled(catalog.config)} />
      <div className="flex min-w-0 flex-1 flex-col">
      <TopBar sb={sb} path={path} navigate={navigate} theme={theme} onTheme={toggleTheme} catalog={catalog} showUpload={uploadEnabled(catalog.config)} showTech={techEnabled(catalog.config)} onShortcuts={() => setShortcuts(true)} />
      <div id="main" className="flex min-h-0 flex-1 flex-col">
        {path === "/eval" ? (
          <Suspense fallback={<p className="flex items-center gap-2 p-4 text-sm text-muted"><span className="spinner" aria-hidden />Loading eval…</p>}><EvalPage /></Suspense>
        ) : path === "/tech" ? (
          <Suspense fallback={<p className="p-4 text-sm text-muted">Loading…</p>}><TechPage catalog={catalog} /></Suspense>
        ) : path === "/upload" ? (
          <Suspense fallback={<p className="p-4 text-sm text-muted">Loading…</p>}><UploadPage catalog={catalog} navigate={navigate} /></Suspense>
        ) : (
          <Console catalog={catalog} />
        )}
      </div>
      <MobileFooter catalog={catalog} />
      </div>
      {shortcuts && <ShortcutsDialog onClose={() => setShortcuts(false)} />}
    </div>
    </MotionConfig>
  );
}

const SHORTCUTS: [string, string][] = [
  ["I", "Investigate the selected stop"],
  ["1 · 2 · 3", "Jump to line, agent trace, root cause"],
  ["T", "Toggle light / dark theme"],
  ["[", "Collapse or expand the sidebar"],
  ["Esc", "Close a drawer or dialog"],
  ["?", "Show this list"],
];

function ShortcutsDialog({ onClose }: { onClose: () => void }) {
  return (
    <Dialog title="Keyboard shortcuts" onClose={onClose} labelId="keys-title">
      <dl className="space-y-2 text-sm">
        {SHORTCUTS.map(([k, v]) => (
          <div key={k} className="flex items-center justify-between gap-4">
            <dt className="text-muted">{v}</dt>
            <dd className="flex gap-1">{k.split(" · ").map((x) => <kbd key={x} className="kbd">{x}</kbd>)}</dd>
          </div>
        ))}
      </dl>
      <p className="mt-4 text-xs text-muted">Shortcuts are ignored while you type in a field. Everything is also reachable with Tab.</p>
    </Dialog>
  );
}
