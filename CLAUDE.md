# CLAUDE.md — Andon Agent

> Loaded automatically by Claude Code. Keep it short, true, and current. If a fact here goes stale, fix it in the same commit that discovers it.

## Mission (one sentence)
When an automotive assembly line stops, Andon Agent investigates like a reliability engineer: it plans checks, runs analytics on telemetry and machine sound, cites the manual, has code verify every claim, and hands a human a verified root cause plus a safety-gated draft work order.

**Theme (use this exact string everywhere):** `Manufacturing: Intelligent Operations & Industrial Efficiency`

## Hard rules (never break these)
1. **Fresh code only.** Everything is written during the hackathon window. No code, data, names, tag lists, plant layouts or terminology from any employer, startup or past research. The reference repo `ayoisio/ep2-agent-bake-off-finserv-agents` is a structural reference only; do not copy from it.
2. **Public or synthetic data only, and only from the USE list in `docs/DATA_SOURCES.md`.** Never commit raw external data (fetch script + `data/SOURCES.md` instead). Every real-sourced segment carries provenance. Say "real signals mapped onto a synthetic line", never "real plant data". The UI shows a persistent `SYNTHETIC LINE · REAL SIGNALS MARKED` badge.
3. **No physical writes.** No tool may write to a PLC, SCADA, historian or any real system. The only write tool is `draft_work_order`, which creates `PENDING_APPROVAL` records in a mock CMMS (Firestore).
4. **Every LLM claim is verified by code** before it reaches the UI. Unverifiable claims are shown struck through, never silently dropped.
5. **Safety text is verbatim.** Lockout/tagout (LOTO) steps are exact quotes from the manual with page numbers. The model never paraphrases a safety procedure.
6. **Pinned models only** (see below). Never use Gemini 1.x, 2.0 or 2.5 models. Never use an unpinned alias like `*-latest`.
7. **Money is a constraint.** $300 total until Dec 4. Every Gemini call goes through `agents/llm.py`, which logs tokens and cost and enforces the daily kill switch.
8. **Secrets never touch git or prompts.** No API keys in code; use ADC + Secret Manager. Never read `.env*` files into the conversation.

## Pinned models (`config.py` is the single source of truth)
| Role | Model ID | Notes |
|---|---|---|
| Tool loops, planning, drafting | `gemini-3.8-flash` | GA. Thinking LOW/MEDIUM/HIGH. Do not send temperature/top_p/top_k. |
| Bulk triage, text generation for simulator, claim normalisation | `gemini-3.1-flash-lite` | Cheapest. |
| RCA Judge (final causal ranking) | `gemini-3.1-pro-preview` | Preview, `global` only. Fallback to `gemini-3.8-flash` (thinking HIGH) on 429 or >60 s. |
| Residency mode (pitch only) | `gemini-3.5-flash` | Regional in asia-south1 / asia-southeast1. |

Location for Gemini calls: `global`. Everything else in `asia-south1`. **Phase 0 verifies these IDs with a live call; if any 404s, fix `config.py`, this table, and log it in `docs/DECISIONS.md`.**

## Stack
Python 3.12 · `uv` · `google-adk` · `google-genai` (Agent Platform / Vertex mode) · FastAPI + SSE · Pydantic v2 · BigQuery (cloud) / DuckDB (local + tests) behind one `TelemetryStore` interface · Firestore (sessions, audit, mock CMMS) · Cloud Storage (audio, manuals) · Cloud Run (API, eval job) · React + Vite + TypeScript + Tailwind on Firebase Hosting · pytest · ruff.

## Repo map
```
config.py                 pinned models, regions, budgets, limits
scripts/                  fetch_datasets.py, smoke.sh, smoke_models.py
data/                     raw/ (gitignored), scenarios/, SOURCES.md (generated, committed)
simulator/                synthetic plant, real-signal mapping, imperfections, fault injector, truth.json, provenance, text, manuals
agents/                   schemas.py (CONTRACT), llm.py, tools.py, verifier.py, cache.py, graph.py, prompts/
api/                      main.py (FastAPI), events.py (SSE CONTRACT), replay.py, budget.py
web/                      React app (consumes api/events.py contract)
eval/                     run_eval.py, baselines.py, metrics.py, results/
infra/                    bootstrap.sh, deploy_api.sh, deploy_web.sh, iam.sh
tests/                    unit + contract + e2e
docs/                     specs, decisions, risks, data sources, lessons learned, handoff
```

## Which doc answers what
| Question | Doc |
|---|---|
| What are we building, how do pieces talk? | `docs/ARCHITECTURE.md` (contracts §4, capability matrix §7, stretch §8) |
| What does each agent do? | `docs/AGENTS_SPEC.md` |
| What data, from where, under what licence? | `docs/DATA_SOURCES.md`, `docs/SYNTHETIC_DATA_SPEC.md` |
| How do we prove it works? | `docs/EVAL_PLAN.md` |
| What could sink us? | `docs/RISKS.md` |
| How much can we spend? | `DEVELOPMENT.md` §7 ledger |
| What do judges see and ask? | `docs/DEMO_AND_SUBMISSION.md` |

## Contract files (change only with both humans' OK)
- `agents/schemas.py` — Evidence, Claim, Hypothesis, RCAReport, VerifierVerdict, WorkOrder
- `api/events.py` — SSE event union consumed by the frontend
- `simulator/truth_schema.py` — ground truth format consumed by the eval

A contract change = bump `CONTRACT_VERSION`, update `tests/test_contracts.py`, update `web/src/types/events.ts`, note it in `docs/DECISIONS.md`.

## Commands
```bash
uv sync                                   # install
uv run pytest -q                          # all tests (offline, DuckDB, LLM mocked)
uv run pytest -q -m live                  # tests that call Gemini (costs money; run sparingly)
uv run ruff check . && uv run ruff format .
uv run python scripts/fetch_datasets.py --only metropt3,uci_hydraulic,ims_bearings,mimii,maintie
uv run python -m simulator.generate --set S --n 60 --seed 2026 --out data/scenarios
uv run python -m simulator.real_signals --out data/scenarios                 # R001–R017
uv run python -m simulator.load --scenarios data/scenarios --target duckdb   # or bigquery
uv run python -m agents.cli --scenario S001                                 # one diagnosis in terminal
uv run uvicorn api.main:app --reload --port 8080
cd web && npm i && npm run dev                                               # VITE_API_URL=http://localhost:8080
uv run python -m eval.run_eval --systems S1,S2,B1,B2 --sets S,R
bash infra/deploy_api.sh && bash infra/deploy_web.sh
```

## How to work in this repo
- Plan first (≤10 bullets), name the subagent(s) you delegate to, then execute. Use the role subagents in `.claude/agents/` for focused work; the main session coordinates and integrates.
- Verify fast-moving APIs (ADK, google-genai, Cloud Run flags, model pages) against live docs before writing code against them. Record surprises in `docs/LESSONS_LEARNED.md`.
- Small commits, conventional messages (`feat(agents): …`, `fix(api): …`). Push at least every 2 hours.
- Tests run offline by default. LLM calls are mocked with recorded fixtures in `tests/fixtures/`.
- Prompts live in `agents/prompts/*.md`, not inline strings, and are versioned.
- When behind schedule, follow the cut list in `DEVELOPMENT.md` §9. Never cut the Verifier, the eval, the MetroPT-3 R-set, provenance, or the HITL gate. Stretch work only through the §9b gate.
- Check spend against the `DEVELOPMENT.md` §7 ledger before any paid batch (eval, text generation).
- Think in all dimensions before calling something done: does it work live, is it honest (provenance, labelled assumptions), is it safe, what does it cost, how does a judge see it, and does it survive the judging window unattended?

## Definition of done (any task)
1. Code + tests written, `uv run pytest -q` and `ruff` green.
2. Exercised for real once (CLI, curl, or browser) and the output looked at.
3. Docs touched if behaviour or a contract changed.
4. Committed and pushed; `docs/LESSONS_LEARNED.md` updated if anything surprised you.

## Key dates (IST)
Team registration closes **Oct 11** · Feature freeze **Thu Oct 15 23:59** · Video + deck **Fri Oct 16** · Submit **Sat Oct 17 18:00** · Official deadline Oct 18 · Finalists Nov 7 · Singapore finale Dec 4.
