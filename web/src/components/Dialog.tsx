import { useEffect, useRef, type ReactNode } from "react";
import { motion } from "motion/react";
import { IconX } from "./ui";

const FOCUSABLE = 'a[href],button:not([disabled]),input:not([disabled]),textarea:not([disabled]),select:not([disabled]),[tabindex]:not([tabindex="-1"])';

/**
 * Modal dialog / side drawer: role=dialog + aria-modal, focus moves in, Tab is trapped,
 * Esc closes, focus returns to the opener.
 */
export function Dialog({ title, onClose, children, side = false, labelId }: { title: string; onClose: () => void; children: ReactNode; side?: boolean | "left"; labelId: string }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const opener = document.activeElement as HTMLElement | null;
    const el = ref.current!;
    const first = el.querySelector<HTMLElement>("[data-autofocus]") ?? el.querySelector<HTMLElement>(FOCUSABLE);
    (first ?? el).focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.stopPropagation();
        onClose();
      } else if (e.key === "Tab") {
        const items = [...el.querySelectorAll<HTMLElement>(FOCUSABLE)].filter((n) => n.offsetParent !== null || n === document.activeElement);
        if (items.length === 0) {
          e.preventDefault();
          return;
        }
        const a = items[0];
        const z = items[items.length - 1];
        if (e.shiftKey && (document.activeElement === a || !el.contains(document.activeElement))) {
          e.preventDefault();
          z.focus();
        } else if (!e.shiftKey && (document.activeElement === z || !el.contains(document.activeElement))) {
          e.preventDefault();
          a.focus();
        }
      }
    };
    document.addEventListener("keydown", onKey, true);
    return () => {
      document.removeEventListener("keydown", onKey, true);
      opener?.focus?.();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  return (
    <div className="fixed inset-0 z-50 flex" data-dialog>
      <motion.div className="absolute inset-0 bg-black/55 backdrop-blur-[2px]" onClick={onClose} aria-hidden initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ duration: 0.18 }} />
      <motion.div
        ref={ref}
        role="dialog"
        aria-modal="true"
        aria-labelledby={labelId}
        tabIndex={-1}
        initial={side ? { x: side === "left" ? -32 : 32 } : { scale: 0.97, y: 6 }}
        animate={side ? { x: 0 } : { scale: 1, y: 0 }}
        transition={{ type: "spring", stiffness: 420, damping: 36 }}
        className={`relative flex max-h-full flex-col overflow-hidden border border-line bg-bg shadow-2xl ${
          side === "left" ? "mr-auto h-full w-[min(86vw,280px)] border-y-0 border-l-0" : side ? "ml-auto h-full w-full max-w-2xl border-y-0 border-r-0" : "m-auto w-[min(92vw,28rem)] rounded-2xl"
        }`}
      >
        <header className="flex items-center justify-between gap-2 border-b border-line px-4 py-3">
          <h2 id={labelId} className="font-mono text-sm font-semibold">{title}</h2>
          <button type="button" className="btn-ghost !min-h-[32px] gap-2" onClick={onClose} aria-label="Close">
            <IconX className="h-4 w-4" />
            <span className="kbd" aria-hidden>Esc</span>
          </button>
        </header>
        <div className="relative min-h-0 flex-1 overflow-y-auto p-4">{children}</div>
      </motion.div>
    </div>
  );
}
