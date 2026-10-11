import { lazy, Suspense, useCallback, useEffect, useState } from "react";
import { Console } from "./components/Console";
import { Footer, Header } from "./components/Shell";
import { uploadEnabled } from "./lib/features";
import { useCatalog } from "./state/useCatalog";
import { useTheme } from "./state/useTheme";

const UploadPage = lazy(() => import("./pages/UploadPage").then((m) => ({ default: m.UploadPage })));
const EvalPage = lazy(() => import("./pages/EvalPage").then((m) => ({ default: m.EvalPage })));

function currentPath(): string {
  const p = window.location.pathname.replace(/\/+$/, "") || "/";
  return p === "/eval" || p === "/upload" ? p : "/";
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
    for (const [k, val] of cur) if (k !== "scenario" && k !== "mode" && !next.has(k)) next.set(k, val);
    const qs = next.toString();
    window.history.pushState({}, "", p + (qs ? `?${qs}` : ""));
    setPath(p === "/eval" || p === "/upload" ? p : "/");
  }, []);
  return (
    <div className="relative flex h-dvh flex-col overflow-hidden">
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-50 focus:rounded focus:bg-accent focus:px-3 focus:py-2 focus:text-accent-fg">Skip to content</a>
      {path === "/" && <a href="#pane-rca" className="sr-only xl:focus:not-sr-only xl:focus:absolute xl:focus:left-40 xl:focus:top-2 xl:focus:z-50 xl:focus:rounded xl:focus:bg-accent xl:focus:px-3 xl:focus:py-2 xl:focus:text-accent-fg">Skip to root cause</a>}
      <Header path={path} navigate={navigate} theme={theme} onTheme={toggleTheme} catalog={catalog} showUpload={uploadEnabled(catalog.config)} />
      <div id="main" className="flex min-h-0 flex-1 flex-col">
        {path === "/eval" ? (
          <Suspense fallback={<p className="p-4 text-sm text-muted">Loading eval…</p>}><EvalPage /></Suspense>
        ) : path === "/upload" ? (
          <Suspense fallback={<p className="p-4 text-sm text-muted">Loading…</p>}><UploadPage catalog={catalog} navigate={navigate} /></Suspense>
        ) : (
          <Console catalog={catalog} />
        )}
      </div>
      <Footer catalog={catalog} />
    </div>
  );
}
