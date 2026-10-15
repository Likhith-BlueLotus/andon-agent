import { useCallback, useEffect, useRef, useState } from "react";

export const RAIL = 76; // collapsed: icons only
export const MIN_OPEN = 188;
export const MAX = 380;
export const DEFAULT = 248;
const SNAP_BELOW = 150; // dragging narrower than this collapses to the rail
const KEY = "andon.sidebar";

/** Any requested width becomes either the icon rail or an open width inside [MIN_OPEN, MAX]. */
export function settle(w: number): number {
  if (!Number.isFinite(w)) return DEFAULT;
  if (w < SNAP_BELOW) return RAIL;
  return Math.round(Math.min(MAX, Math.max(MIN_OPEN, w)));
}

function load(): number {
  try {
    const v = Number(localStorage.getItem(KEY));
    return v ? settle(v) : DEFAULT;
  } catch {
    return DEFAULT;
  }
}

/** Sidebar width with drag, keyboard and collapse; remembered per browser (a convenience, never required). */
export function useSidebarWidth() {
  const [width, setWidthRaw] = useState<number>(load);
  const lastOpen = useRef(width > RAIL ? width : DEFAULT);
  const [dragging, setDragging] = useState(false);

  const setWidth = useCallback((w: number) => {
    const s = settle(w);
    if (s > RAIL) lastOpen.current = s;
    setWidthRaw(s);
  }, []);

  useEffect(() => {
    try {
      localStorage.setItem(KEY, String(width));
    } catch {
      /* storage blocked: width still applies for this session */
    }
  }, [width]);

  const toggle = useCallback(() => setWidthRaw((w) => (w > RAIL ? RAIL : lastOpen.current)), []);

  /** Pointer drag from the handle; `left` is the sidebar's left edge in client pixels. */
  const startDrag = useCallback(
    (e: React.PointerEvent, left: number) => {
      e.preventDefault();
      setDragging(true);
      const prevSelect = document.body.style.userSelect;
      document.body.style.userSelect = "none";
      document.body.style.cursor = "col-resize";
      const move = (ev: PointerEvent) => setWidthRaw(Math.min(MAX, Math.max(RAIL, ev.clientX - left)));
      const end = () => {
        window.removeEventListener("pointermove", move);
        window.removeEventListener("pointerup", up);
        window.removeEventListener("pointercancel", end);
        document.body.style.userSelect = prevSelect;
        document.body.style.cursor = "";
        setDragging(false);
      };
      const up = (ev: PointerEvent) => {
        end();
        setWidth(ev.clientX - left);
      };
      window.addEventListener("pointermove", move);
      window.addEventListener("pointerup", up);
      // A cancelled touch drag never sends pointerup; without this the listeners leak and selection stays off.
      window.addEventListener("pointercancel", end);
    },
    [setWidth],
  );

  const onKey = useCallback(
    (e: React.KeyboardEvent) => {
      const step = e.shiftKey ? 48 : 16;
      if (e.key === "ArrowLeft") setWidth(width === RAIL ? RAIL : width - step);
      else if (e.key === "ArrowRight") setWidth(width === RAIL ? MIN_OPEN : width + step);
      else if (e.key === "Home") setWidth(RAIL);
      else if (e.key === "End") setWidth(MAX);
      else if (e.key === "Enter" || e.key === " ") toggle();
      else return;
      e.preventDefault();
    },
    [width, setWidth, toggle],
  );

  return { width, compact: width <= RAIL, dragging, setWidth, toggle, startDrag, onKey };
}
