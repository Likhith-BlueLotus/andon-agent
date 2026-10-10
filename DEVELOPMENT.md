# DEVELOPMENT.md — how work flows in this repo

## 1. Operating model: two humans, one AI org

Two humans, each driving one Claude Code session at a time on their own branch. Inside a session, the main Claude thread acts as **Engineering Manager**: it plans, delegates focused work to role subagents in `.claude/agents/`, integrates results, and runs the definition of done.

| Role subagent | Owns | Delegate when… |
|---|---|---|
| `principal-engineer` | Architecture, contracts, cross-cutting trade-offs, ADRs, scope vs calendar | A decision touches >1 layer, a contract, cost, or the "is this a wrapper?" question |
| `staff-engineer-agents` | ADK graph, prompts, tools wiring, model routing, verifier loop, caching | Anything in `agents/` beyond a one-line fix |
| `senior-backend-engineer` | FastAPI, SSE, Firestore, audit, replay, budget, (stretch) ingest/voice endpoints | Anything in `api/` |
| `senior-data-ml-engineer` | Dataset fetch + inspection, simulator, real-signal mapping, provenance, imperfections, ground truth, stores, signal maths | Anything in `simulator/`, `scripts/fetch_datasets.py`, or numeric tools |
| `ux-ui-engineer` | React app, trace UI, provenance chips, technician view, accessibility | Anything in `web/` |
| `sre-devops-engineer` | GCP bootstrap, IAM, Cloud Run, Firebase, budgets, deploy scripts, warm/cold | `infra/`, any deploy, any 429/timeout/cold-start issue |
| `qa-eval-engineer` | Tests, fixtures, eval harness, baselines, statistics, results slide | `tests/` or `eval/` |
| `security-reviewer` | IAM, secrets, injection, safety rules, data licences (read-only) | Before each deploy, before freeze, `/data-audit` |
| `hackathon-judge` | Skeptical scoring against the rubric (read-only) | `/judge-review`, end of each day |
| `pitch-lead` | Demo script, deck, README story, Q&A prep, submission | Phase 7, and whenever a result is worth a slide |

Human split (both full-stack; ownership, not exclusivity):
- **Person A — agents, backend, infra, eval harness.** The eval lives next to the agents because it calls them.
- **Person B — data (S-set + R-set), frontend, deck/video, manual-baseline study.**

## 2. Contracts first (night one)
`agents/schemas.py`, `api/events.py`, `simulator/truth_schema.py` are written together, reviewed by `principal-engineer`, merged, then frozen except by mutual agreement. B builds the UI against `tests/fixtures/sample_stream.jsonl` while A builds the real stream; Tuesday integration is a URL swap.

## 3. Branching, commits, merging
- `main` is always deployable after Tuesday. Work on `a/<topic>` or `b/<topic>`; merge via PR; `/judge-review` on big ones.
- Conventional commits. Rebase on `main` at the start of every session. Push at least every 2 hours.
- End every session with `/handoff`. Start every session with "Read docs/HANDOFF.md and continue."
- Optional `git worktree` lets one human run two Claude sessions (e.g., agents + eval) without collisions.

## 4. Phases and exit criteria
| Phase | Command | Exit criterion (demonstrably true) |
|---|---|---|
| 0 Bootstrap | `/phase-0` | GCP ready, budget alerts set, pinned models answer live, Cloud Run hello-world deployed, repo pushed |
| 1 Hybrid plant data | `/phase-1` | Contracts merged; datasets fetched with `data/SOURCES.md`; 60 S + 17 R scenarios with truth + provenance; loads into DuckDB and BigQuery; guard + provenance tests green |
| 2 Agents | `/phase-2` | `agents.cli` prints a verified `RCAReport` with provenance; verifier rejects a forced false claim in a test |
| 3 API + deploy | `/phase-3` | Live Cloud Run URL streams the full event sequence; HITL works; replay works; kill switch tested |
| 4 Frontend | `/phase-4` | Deployed web app runs live + replay end to end; keyboard-only path works; provenance chips visible |
| 5 Eval | `/phase-5` | S1/S2/B1/B2 on S+R sets with intervals, McNemar, variance; slide PNG |
| 6 Hardening | `/phase-6` | Fallback proven, cold start measured, security + data audit clean, 5 consecutive live runs |
| 7 Ship | `/phase-7` | Video <3:00 public, deck PDF, public repo + README, form submitted with exact theme |

## 5. Day plan (IST)
| Day | Person A | Person B |
|---|---|---|
| Sat Oct 10 (night) | **Register team.** `/phase-0` | Contracts with A (`/phase-1 contracts`), start downloads (`/phase-1 fetch`) |
| Sun Oct 11 | `/phase-2`: tools + Commander + Signal Analyst on DuckDB | Data inspection report; `/phase-1 v1` (5 classes, imperfections, loaders) |
| Mon Oct 12 | `/phase-2`: verifier, Librarian + cache, Judge loop | `/phase-1 v2`: remaining classes, text (MaintIE style), 5 manuals (OSHA LOTO), MIMII placement |
| Tue Oct 13 | `/phase-2` finish (drafter, event mapper, fixtures); `/phase-3` stream + **first Cloud Run deploy** | AM: `/phase-1 rset`. PM: `/phase-4` scaffold + trace pane on fixture stream |
| Wed Oct 14 | AM: `/phase-3` HITL, audit, replay, protection. PM: `/phase-5 harness` + baselines + run20 | `/phase-4`: RCA pane, provenance chips, states; switch to live URL; deploy web |
| Thu Oct 15 | `/phase-5 final` runs + fixes from failures; `/freeze-check` 23:59 | `/phase-4` a11y + mobile; stretch item 1 if the gate allows; screenshots; manual-baseline sessions |
| Fri Oct 16 | `/phase-6` hardening | `/phase-7 script` + record video (3 takes); deck draft |
| Sat Oct 17 | README, final tag, Q&A rehearsal | Deck PDF, upload video, **submit by 18:00** |
| Sun Oct 18 | Buffer | Buffer |

## 6. Testing strategy
- **Unit (offline, every commit):** fault signatures, propagation, imperfections, real-signal mapping transforms, every tool's maths, verifier rules (incl. provenance rule), schema validation, SSE serialisation, budget arithmetic, statistics functions.
- **Contract tests:** round-trip every schema/event; `web/src/types/events.ts` matches `api/events.py`.
- **Guard tests:** `truth.json` unreadable from `agents/`/`api/`; exactly one write tool; injection scenarios don't change behaviour; every real-sourced segment has provenance; no forbidden dataset IDs referenced.
- **Agent tests (offline):** fake LLM replaying fixtures; tool budgets, stop conditions, fallback on simulated 429.
- **Live tests (`-m live`, costs money):** 3 fixed scenarios (one R-set). A few times a day at most.
- **E2E:** `scripts/smoke.sh <API_URL>`.
- **Regression rule:** failing test first, then fix.

## 7. LLM discipline and the budget ledger ($300 to Dec 4)
All Gemini calls go through `agents/llm.py` (backoff, fallback, accounting, audit, kill switch). Flash judge in development; Pro only for final eval and recording. GC context caches at session end. Record fixtures from interesting live runs.

| Line | Allocation | Hard stop |
|---|---|---|
| Phase 0–2 development runs + text generation | $45 | $60 |
| Phase 3–4 integration + live testing | $20 | $30 |
| Eval (EVAL_PLAN §7) | $110 | $120 |
| Recording + hardening | $10 | $15 |
| Infra (Cloud Run, Firebase, BQ, GCS, Firestore, logs) to Dec 4 | $35 | $45 |
| Judging window demo (replay default, live capped) | $30 | $40 |
| **Reserve** (finalist rework before Dec 4) | $50 | — |
| **Total** | **$300** | |
`/status` reports spend vs this table. If a line hits its hard stop, the principal-engineer decides what to cut before more is spent.

## 8. Freeze rules (Thu Oct 15 23:59 IST)
After freeze: bug fixes, copy, styling, performance, docs only. No new agents, tools, endpoints or screens (stretch items not started by freeze are dropped). `/freeze-check` must pass before tagging `v1.0-freeze`.

## 9. Cut list (cut from the top when behind; decide at 20:00 each day)
1. S3 ablation and variance repeats → 2
2. IMS bearings in the R-set (R015–R017)
3. Audio `listen()` tool (keep only if working by end of Oct 13)
4. Pro Judge (use `gemini-3.8-flash` thinking HIGH)
5. Firebase frontend (serve built SPA from FastAPI on Cloud Run — still compliant)
6. BigQuery (DuckDB on Parquet inside the container)
7. S-set N 60 → 30

**Never cut:** Verifier, eval with B1, the R-set MetroPT-3 scenarios, HITL approval gate, deployed live URL, provenance.

## 9b. Stretch ladder (only when the gate is open)
**Gate:** phases 1–4 exit criteria met *and* Run-20 eval shows S1 ≥ B1, by Thu Oct 15 12:00 IST. Take items in order; each must be finished and tested before freeze or it is reverted.
1. **Bring-your-own CSV** (ARCHITECTURE §8) — answers "does it work on my data?" and proves the adapter story. Highest judge value.
2. **Technician mobile view + voice note** — one-card layout, big Approve, 60 s voice note → shift note. Lifts the 10% UX score and adds multimodal input.
3. **Multilingual work-order summary** (Hindi/Tamil/Bahasa/Vietnamese) with verbatim safety steps + labelled translation — a JAPAC story for Singapore.
If the gate is closed, these become one deck slide ("next 30 days") with a mock, not code.

## 10. Retrospective habit
After every phase and every bug that cost >30 minutes, append to `docs/LESSONS_LEARNED.md`. Decisions with alternatives go to `docs/DECISIONS.md`. Risks change → `docs/RISKS.md`.
