# UX spec

## Users
- **Primary:** maintenance technician on shift (often night shift, under time pressure, may be on a tablet).
- **Secondary:** shift supervisor (approves), reliability engineer (reviews evidence later).

## Visual direction
Industrial control-room calm, not a generic AI chat UI. Dark-first theme with a light theme toggle. One accent colour for "agent activity", standard status colours used only for status: red = stopped/failed claim, amber = degraded/fallback, green = verified. Monospace for tag names, values and evidence IDs; a clean sans for prose. No chat bubbles: the agent's work is shown as a **trace of cards**, because that is what proves it is not a chatbot. Load the `frontend-design` skill before building.

## Screen 1 — Incident console (the only screen that must be great)
Three panes on desktop (≥1280 px), stacked on tablet/mobile:

1. **Line mimic (left, 25%)** — 6 stations as blocks in a row with flow arrows; stopped station pulses red; stations the agents are examining get an outlined highlight; a downtime cost counter (`$ / s` from a labelled assumption) ticks while the stream runs. Scenario picker grouped as "Synthetic scenarios" and "Real-signal scenarios" (R-set entries show their source, e.g. "Air leak · MetroPT-3") + "Investigate stop" button. `SYNTHETIC LINE · REAL SIGNALS MARKED` badge always visible.
2. **Agent trace (centre, 45%)** — Plan card on top, then lanes per agent. Each `tool_call` is a compact card: tool name, args (collapsible), spinner → result summary, evidence chip `ev_…`, latency, and a **provenance chip** ("REAL · MetroPT-3" in a distinct outlined style, or "SYNTHETIC") whose tooltip shows source rows and transforms. Data-quality notes (gaps, stuck values) render as a small grey line so users see the agent noticed them. Cache-hit and model-fallback events render as small inline badges. Auto-scroll with a "pause auto-scroll" toggle.
3. **RCA + action (right, 30%)** — Hypothesis cards ranked with confidence bars; each claim shows its verifier state (pending / ✓ verified / struck-through red with "measured X" tooltip). Manual citations show `doc · p.42` and the verbatim quote. When `rca_final` arrives: Accept / Edit / Reject. Then the work order with steps; safety steps marked and each has a checkbox. **Approve & send to CMMS (mock)** stays disabled until every safety step is ticked. Cost chip at the bottom (tokens, $, cache savings).

## Polish layer (UI/UX pass, 2026-10-12)
- **Investigation stepper** under the header: Stop → Plan → Evidence → Hypotheses → Verify → Work order → You. Derived only from received events (`web/src/lib/progress.ts`, unit-tested on the fixture). Phones get a one-line "Step n/7" bar instead of a rail.
- **Andon-tower logo** mirrors the run (red stopped, amber blinking while investigating, green verified/approved), with a status pill on wide screens.
- **Verdict hero** when `rca_final` is verified: cause, asset, confidence ring, and the verifier tally ("n/n claims checked by code", "n wrong claims caught & corrected", citations).
- **Mimic:** status-lamp station tiles, halted conveyor (the line is stopped, so nothing flows), green ring on the verified root-cause station, legend.
- **Approval:** safety-step progress bar; Approve shows a lock until every gate is met.
- **Eval:** interval plot (point + Wilson 95% whisker) replaces the bar chart, so the interval is what the eye reads first.
- **Keyboard:** `I` investigate, `1/2/3` panes, `T` theme, `?` list, `Esc` close. Ignored while typing or when a dialog is open.
- Motion via `motion` (enter-only, `MotionConfig reducedMotion="user"`); CSS loops are off under `prefers-reduced-motion`. Contrast of every text token on every surface is checked by `web/src/lib/contrast.test.ts`.

### Visual system: Snow Dashboard UI Kit style (2026-10-12)
Restyled after the community *Snow Dashboard UI Kit* (Figma, by ByeWind), used as a visual reference only; no assets copied. Inter for prose, IBM Plex Mono for values. Left sidebar (Views + a vertical "Investigation" checklist + attributions and theme line), breadcrumb top bar with a search-style Shortcuts pill, a row of pastel KPI tiles (downtime cost (assumption), evidence, claims verified, root-cause confidence), then flat 16 px-radius cards for line, trace and root cause. Dark theme is #1c1c1c with white-5% cards; pastel tiles keep dark ink in both themes, as in the kit. The kit's 40%-grey secondary text was darkened to keep 4.5:1. Phones: drawer navigation, compact step bar, swipeable KPI row.
Navigation chrome (sidebar, top bar, phone footer) is floating frosted glass with rounded corners over a soft ambient gradient; content cards stay solid so text contrast is guaranteed (glass contrast over the strongest tint is in the contrast test). The sidebar is resizable: drag its right edge (188–380 px), drag below 150 px to collapse to a 76 px icon rail, double-click the edge or press `[` or the top-bar button to toggle; the edge is a focusable `separator` (arrows ±16 px, Shift ±48, Home/End, Enter). Width is remembered in localStorage when available.

## Other views
- **Replay:** same console, banner "Replay of run #id recorded <timestamp>". Default for anonymous visitors; "Run live" requires the passcode.
- **Evidence drawer:** click any evidence chip → side drawer with the tool's args and a small chart of the queried window (Recharts).
- **Eval page (`/eval`):** the results table + bar chart from the latest committed run.
- **About/attribution footer:** dataset citations from `data/SOURCES.md` (MetroPT-3, UCI hydraulic, IMS, MIMII, MaintIE, OSHA 1910.147), synthetic-line statement, theme name.
- **Eval page** also shows the R-set table separately and the confidence intervals.

## Stretch views (DEVELOPMENT.md §9b — only if the gate opens)
- **Technician view (`/tech`, mobile-first):** one card at a time — stopped station, verified root cause in one sentence, confidence, the work order's safety checklist as large tap targets, a big Approve button; a "record voice note" button (≤60 s, MediaRecorder) that becomes a shift note in the trace. Works one-handed, high contrast, ≥44 px targets.
- **Bring your own CSV (`/upload`):** drag a CSV → preview first rows → Flash-Lite's proposed column→tag mapping shown as an editable table with confidence → user confirms → "Investigate" on the uploaded data, all evidence chips marked `USER UPLOAD`.
- **Language toggle on the work order:** translated non-safety steps; safety steps stay verbatim with the translation beside them, labelled "machine translation — not the controlling text".

## States to design (every one, not just the happy path)
idle · streaming · tool error (retrying) · model fallback · verifier FAIL → revising (show loop counter 1/3) · insufficient evidence · stream dropped (auto-reconnect with "reconnecting…", then offer replay) · budget exhausted (switch to replay with explanation) · approved.

## Accessibility (part of the 10% UX score — do it)
Full keyboard path: pick scenario → investigate → expand evidence → accept → tick safety steps → approve. Visible focus rings. Status never conveyed by colour alone (icons + text). `aria-live="polite"` region announces "Verified root cause: …" and "Claim rejected: …". Contrast ≥ 4.5:1 in both themes. Respect `prefers-reduced-motion` (no pulsing).

## Tech
React + Vite + TypeScript + Tailwind; Recharts for evidence charts; native `fetch` streaming reader for SSE over POST (EventSource does not support POST); types in `web/src/types/events.ts` mirror `api/events.py`; a `useIncidentStream` hook reduces events into UI state (pure reducer, unit-tested against `tests/fixtures/sample_stream.jsonl`).
