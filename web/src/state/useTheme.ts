import { useCallback, useState } from "react";

type Theme = "dark" | "light";
const KEY = "andon.theme";

export function useTheme(): [Theme, () => void] {
  const [theme, setTheme] = useState<Theme>(() => (document.documentElement.dataset.theme === "light" ? "light" : "dark"));
  const toggle = useCallback(() => {
    const next: Theme = theme === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    try {
      localStorage.setItem(KEY, next);
    } catch {
      /* storage blocked: the theme still applies for this session */
    }
    setTheme(next);
  }, [theme]);
  return [theme, toggle];
}
