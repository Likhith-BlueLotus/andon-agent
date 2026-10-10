---
description: Phase 4 — the incident console frontend (mock stream first, then live), deployed to Firebase Hosting
argument-hint: "[scaffold | trace | rca | states | a11y | deploy]"
---

# Phase 4 — Frontend (Tue Oct 13 → Thu Oct 15)

Focus: $ARGUMENTS (default: next unfinished).

Delegate to `ux-ui-engineer`. docs/UX_SPEC.md is the spec; `web/src/types/events.ts` and `tests/fixtures/sample_stream.jsonl` are the contract. Load the `frontend-design` skill (if available) before choosing the visual direction, and propose the direction in 5 bullets before building.

1. **Scaffold** `web/` (Vite + React + TS + Tailwind + Recharts + vitest), dark/light tokens, layout shell with the three panes and the `SYNTHETIC LINE · REAL SIGNALS MARKED` badge.
2. **Stream hook + reducer**: `useIncidentStream` (fetch-based SSE over POST, ping handling, abort, reconnect) and a pure `reduce(state, event)`; vitest against the fixture stream. `?mock=1` plays the fixture with timing.
3. **Agent trace pane**: plan card, agent lanes, tool cards (args collapsible, result summary, evidence chip, **provenance chip** with source/transform tooltip, data-quality line, latency), cache and fallback badges, auto-scroll toggle.
4. **Line mimic**: stations incl. UT-AIR and UT-CHL, stopped/alarming stations, highlighted stations under investigation, cost counter labelled as an assumption-based estimate; scenario picker grouped synthetic vs real-signal (with source names).
5. **RCA + action pane**: ranked hypotheses, per-claim verifier state (pending / verified / struck through with measured value), citations with page + verbatim quote, Accept/Edit/Reject, work order with safety checkboxes gating Approve, cost chip.
6. **Evidence drawer** with a Recharts plot of the queried window (needs `/api/incidents/{id}/audit` + a small telemetry endpoint if missing — ask the backend owner rather than inventing fields).
7. **All states** from the spec, replay banner, passcode prompt for live, eval page reading `/api/eval/latest` (S-set and R-set tables with intervals), footer attributions from `/api/sources`.
8. **Accessibility pass**: keyboard-only full path, focus rings, aria-live announcements, contrast, reduced motion, mobile width.
9. **Deploy**: `infra/deploy_web.sh` to Firebase Hosting with `VITE_API_URL` = Cloud Run URL; add the Hosting domain to the API's CORS list.

10. **Stretch (only if DEVELOPMENT.md §9b gate is open, in order):** `/upload` BYO-CSV with editable mapping table → `/tech` mobile technician view with voice note → WO language toggle. Each finished + tested before freeze or reverted.

Exit criterion: on the deployed Firebase URL, one full live investigation of R002 (with passcode) and one replay run end to end, provenance chips visible, approval works, keyboard-only path works, screenshots saved to `docs/screenshots/` (desktop + mobile). Update LESSONS_LEARNED, commit, push.
