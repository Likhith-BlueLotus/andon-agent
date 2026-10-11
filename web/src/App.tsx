import { useCallback, useEffect, useState } from "react";
import { Console } from "./components/Console";
import { Footer, Header } from "./components/Shell";
import { EvalPage } from "./pages/EvalPage";
import { useCatalog } from "./state/useCatalog";
import { useTheme } from "./state/useTheme";

function currentPath(): string {
  const p = window.location.pathname.replace(/\/+$/, "") || "/";
  return p === "/eval" ? "/eval" : "/";
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
    window.history.pushState({}, "", to + window.location.search);
    setPath(to === "/eval" ? "/eval" : "/");
  }, []);
  return (
    <div className="relative flex h-dvh flex-col overflow-hidden">
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-50 focus:rounded focus:bg-accent focus:px-3 focus:py-2 focus:text-accent-fg">Skip to content</a>
      <Header path={path} navigate={navigate} theme={theme} onTheme={toggleTheme} catalog={catalog} />
      <div id="main" className="flex min-h-0 flex-1 flex-col">
        {path === "/eval" ? <EvalPage /> : <Console catalog={catalog} />}
      </div>
      <Footer catalog={catalog} />
    </div>
  );
}
