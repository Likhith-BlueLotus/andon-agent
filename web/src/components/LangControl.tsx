import { useId } from "react";
import { LANGS, type LangCode } from "../lib/translate";
import type { WoLang } from "../state/useWoLang";
import { Spinner } from "./ui";

/** Compact language picker + persistent notice + inline error. Native select: keyboard and screen-reader friendly. */
export function LangControl({ wl, large = false }: { wl: WoLang; large?: boolean }) {
  const id = useId();
  const { lang, setLang, data, loading, error, showOriginal, retry } = wl;
  return (
    <div className="space-y-1.5" data-testid="lang-control">
      <div className="flex flex-wrap items-center gap-2">
        <label htmlFor={id} className={`font-semibold ${large ? "text-sm" : "text-xs"}`}>Work order language</label>
        <select
          id={id}
          value={lang ?? ""}
          onChange={(e) => setLang((e.target.value || null) as LangCode | null)}
          className={`rounded border border-line bg-raised px-2 ${large ? "min-h-[44px] text-base" : "py-1 text-xs"}`}
        >
          <option value="">Original (English)</option>
          {LANGS.map((l) => (
            <option key={l.code} value={l.code} lang={l.code}>{l.native}</option>
          ))}
        </select>
        {loading && <Spinner label="translating" />}
        {data && lang && <span className="font-mono text-[11px] text-muted" data-testid="lang-cost">{data.cached ? "cached" : `$${data.cost_usd.toFixed(4)}`}</span>}
      </div>
      <div aria-live="polite">
        {error && (
          <p role="alert" className="flex flex-wrap items-center gap-2 text-sm text-bad" data-testid="lang-error">
            <span>{error}</span>
            <button type="button" className="btn !min-h-0 px-2 py-0.5 text-xs" onClick={retry}>Retry</button>
            <button type="button" className="btn !min-h-0 px-2 py-0.5 text-xs" onClick={showOriginal}>Show original</button>
          </p>
        )}
      </div>
      {data && lang && (
        <p className="rounded border border-warn/60 p-2 text-xs" data-testid="lang-notice">
          <span className="font-semibold">{data.lang_name}: </span>{data.notice}
        </p>
      )}
    </div>
  );
}

/** Translation of a SAFETY step: always secondary to the verbatim original, labelled, never inside the checkbox label. */
export function SafetyTranslation({ text, lang, order }: { text: string | null | undefined; lang: LangCode; order: number }) {
  const id = useId();
  return (
    <div role="group" aria-labelledby={id} className="mt-1.5 rounded border border-dashed border-line bg-raised p-2" data-testid={`safety-translation-${order}`}>
      <p id={id} className="label">Translation (machine, not binding)</p>
      {text ? <p lang={lang} className="mt-0.5 text-[13px]">{text}</p> : <p className="mt-0.5 text-xs italic text-muted">translation unavailable</p>}
    </div>
  );
}
