import { useEffect, useRef, type ReactNode } from "react";

const FOCUSABLE = 'a[href],button:not([disabled]),input:not([disabled]),textarea:not([disabled]),select:not([disabled]),[tabindex]:not([tabindex="-1"])';

/**
 * Modal dialog / side drawer: role=dialog + aria-modal, focus moves in, Tab is trapped,
 * Esc closes, focus returns to the opener.
 */
export function Dialog({ title, onClose, children, side = false, labelId }: { title: string; onClose: () => void; children: ReactNode; side?: boolean; labelId: string }) {
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
      <div className="absolute inset-0 bg-black/60" onClick={onClose} aria-hidden />
      <div
        ref={ref}
        role="dialog"
        aria-modal="true"
        aria-labelledby={labelId}
        tabIndex={-1}
        className={`relative flex max-h-full flex-col overflow-hidden border border-line bg-panel shadow-2xl ${
          side ? "ml-auto h-full w-full max-w-2xl border-y-0 border-r-0" : "m-auto w-[min(92vw,28rem)] rounded-md"
        }`}
      >
        <header className="flex items-center justify-between gap-2 border-b border-line px-4 py-3">
          <h2 id={labelId} className="font-mono text-sm font-semibold">{title}</h2>
          <button type="button" className="btn !min-h-[32px]" onClick={onClose} aria-label="Close">Close (Esc)</button>
        </header>
        <div className="relative min-h-0 flex-1 overflow-y-auto p-4">{children}</div>
      </div>
    </div>
  );
}
