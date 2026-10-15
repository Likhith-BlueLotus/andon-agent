import { useEffect, useRef } from "react";

/** True when a keystroke belongs to a text field, a modal, or carries a modifier: shortcuts stay out of the way. */
export function ignoreKey(e: KeyboardEvent): boolean {
  if (e.metaKey || e.ctrlKey || e.altKey) return true;
  const t = e.target as HTMLElement | null;
  if (t && (t.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName))) return true;
  return !!document.querySelector("[data-dialog]");
}

/** Single-key shortcuts. `map` keys are KeyboardEvent.key values. */
export function useHotkeys(map: Record<string, () => void>, enabled = true): void {
  const ref = useRef(map);
  ref.current = map;
  useEffect(() => {
    if (!enabled) return;
    const on = (e: KeyboardEvent) => {
      if (e.repeat || ignoreKey(e)) return;
      const f = ref.current[e.key];
      if (f) {
        e.preventDefault();
        f();
      }
    };
    window.addEventListener("keydown", on);
    return () => window.removeEventListener("keydown", on);
  }, [enabled]);
}
