# Andon Agent web console

React + Vite + TypeScript + Tailwind + Recharts. Consumes the SSE contract in `src/types/events.ts`
(mirrors `api/events.py`; do not edit without a contract bump).

## Run

```bash
cd web && npm i
VITE_API_URL=http://localhost:8080 npm run dev     # http://localhost:5173 (CORS allows this origin)
npm run lint        # tsc --noEmit
npm test -- --run   # vitest: SSE parser, reducer over tests/fixtures/sample_stream.jsonl, UI components
npm run build       # tsc + vite build -> dist/
```

| Env var | Meaning |
|---|---|
| `VITE_API_URL` | API base URL, no trailing slash. Default `http://localhost:8080`. Prod: `https://andon-api-891056416508.asia-south1.run.app` |

The demo passcode for live runs is typed into a dialog and kept in memory only (never in a URL, localStorage or sessionStorage).

## URL switches

| URL | Effect |
|---|---|
| `/` | Incident console (replay by default) |
| `/eval` | Eval results from `/api/eval/latest` (graceful "No eval run published yet" on 404) |
| `?mock=1` | Play `tests/fixtures/sample_stream.jsonl` offline with its ts-derived timing (6x faster, gaps capped). No API needed. |
| `?mock=error` / `drop` / `budget` / `insufficient` | The fixture edited to show the tool-error/retrying, dropped-stream/reconnecting, budget-exhausted (auto-switches to replay) and insufficient-evidence states |
| `?speed=2` | Initial replay speed for real replays (1-4) |

## Layout

- `src/state/reducer.ts` pure `reduce(state, event)`; `useIncidentStream.ts` fetch + ReadableStream SSE with abort and one auto-reconnect (replays only: a dropped live run is never restarted automatically because that would bill a second run).
- `src/lib/sse.ts` pure incremental SSE parser. `src/lib/summary.ts` tool-aware summary lines and data-quality notes.
- `src/components/` Mimic (line + utilities rail + cost estimate), Trace (plan, lanes, tool cards), Rca (hypotheses, claims, verifier, work order, approval), EvidenceDrawer, Dialog (focus trap).

## Known assumptions

- `GET /api/scenarios/{id}/telemetry` is used by the evidence drawer; until the API serves it the drawer shows an "no stored series" state. Mock mode draws a clearly-labelled curve from the summary statistics.
- `/api/eval/latest` has no fixed schema yet; `src/lib/evalData.ts` reads `{sets:{S:[...],R:[...]}}` with `{value, lo, hi}` cells and renders whatever columns exist.
- Plan-step ticking is indicative (the contract does not link plan steps to tool calls).
- Downtime cost is `US$2.3M/h` x elapsed run time, labelled as an assumption.
