Theme: Manufacturing: Intelligent Operations & Industrial Efficiency

# Andon Agent

When an automotive assembly line stops, Andon Agent investigates like a reliability engineer: it plans checks, runs analytics on telemetry and machine sound, cites the manual, has code verify every claim, and hands a human a verified root cause plus a safety-gated draft work order.

**Live app:** https://andon-agent-b9c77.web.app · **API:** https://andon-api-359520289475.asia-south1.run.app/health · **Repo:** https://github.com/Likhith-BlueLotus/andon-agent

Replays play for anyone, no login. Live investigations call Gemini and need the demo passcode (ask the team). Every screen shows `SYNTHETIC LINE · REAL SIGNALS MARKED`: the line is simulated and real public signals are mapped onto it, each with its provenance. This is not real plant data.

## 60-second judge path
1. Open the live app. Pick **R002 · MetroPT-3 compressor** (replay), press **Investigate stop**.
2. Watch the trace: the commander plans, the signal analyst works upstream from the alarming weld cell to the plant air header (evidence chips marked `REAL · MetroPT-3`), the librarian cites the compressed-air manual.
3. Click any evidence chip: the drawer charts the real telemetry window behind the claim.
4. Right pane: every claim is re-checked by code (pass / struck through with the measured value). Accept the root cause, tick the lockout/tagout steps (quoted verbatim with page numbers), approve; the work order lands in a mock CMMS as `APPROVED`. Nothing touches a machine.
5. Replay **S014** to see the verifier reject a reversed cause-and-effect claim and the judge revise it. `/eval` shows the results below.

## Results (committed run `eval/results/final_v2`)
Top-1 = right cause class and right asset. 95% Wilson intervals. Failed runs count as misses.

| System | S-set top-1 (n=60) | R-set top-1 (n=17) | Unsupported claims (S+R) | $/run |
|---|---|---|---|---|
| **S1 Andon Agent** (Gemini 3.8 Flash judge) | **0.98** [0.91, 1.00] | **0.76** [0.53, 0.90] | **1 / 586 (0.2%)** | 0.11 |
| S2 same pipeline, verifier always passes | 1.00 [0.94, 1.00] | 0.76 [0.53, 0.90] | 4 / 609 | 0.11 |
| B1 single long prompt, same evidence | 0.92 [0.82, 0.96] | 0.59 [0.36, 0.78] | 54 / 645 (8.4%) | 0.09 |
| B2 classical (anomaly score + history) | 0.15 [0.08, 0.26] | 0.24 [0.10, 0.47] | n/a | 0 |

**Honest reading.** The top-1 difference against a single long prompt is **not significant** (exact McNemar p = 0.219 S-set, 0.375 R-set). The clear win is **grounding**: 0.2% vs 8.4% of claims that independent code could not back. Held-out S051–S060: S1 10/10. Variance over 3 repeats of 15 scenarios: 0.80 / 0.73 / 0.87. A Gemini 3.1 Pro judge measured worse (S 0.90 / R 0.71) and is not used.

**What the verifier is worth.** In the eval above the verifier rarely fires, because the judge rarely makes checkable mistakes, so S1 and S2 score alike. We therefore tested it directly (offline, $0, ADR-032): 2,778 faults injected into real S1 reports (wrong numbers, timestamps, misquotes, reversed cause and effect, false citation premises). The verifier caught **97.1% [96.4, 97.7]**; S2 (verifier always passes) caught 0%. Weakest classes: sign flips (rose vs fell) 92.6% and false premises 90.6%. It wrongly flagged 8 of 586 true claims. Results: `eval/results/stress_verifier/`.

**Pre-registered confirmation (C-set, `eval/preregistration_confirm.md`).** Before running, we fixed 10 new scenarios from unused segments of the real sources plus pass/fail criteria. Result: S1 top-1 0.40 [0.17, 0.69], failing our own bar (P1); S1 still beat the single prompt (0.20, P2 pass, p = 0.50) with 0/80 unsupported claims vs 6/91. Healthy compressors 4/5; short real hydraulic faults 0/5, as predicted.

**Post-hoc changes, reported separately.** After the eval we changed two things, and every number below was measured after the change: a judge rule (R002 was unstable across repeats, ADR-026) and an end-anchored short-shift detector for brief faults just before a stop (ADR-033, validated on a separate synthetic dev set: 7/10 detected, 0 false positives in 8,000+ healthy windows). Rerun of S1 on the final build (`eval/results/posthoc_v4`): **S 0.97 [0.89, 0.99], R 0.82 [0.59, 0.94], C 0.50 [0.24, 0.76]**, 0 unsupported claims out of 648. The detector removed the healthy-compressor false alarm (C 5/5 healthy), but the model still calls the short real hydraulic faults healthy (R009–R011 missed, C 0/5): the tool now reports the shift, but the judge does not yet trust a 0.3–6% change over minutes. That is the main open weakness.

S-set: 60 synthetic scenarios with injected ground truth. R-set: real compressor (MetroPT-3), hydraulic rig (UCI) and bearing (IMS) signals with the sources' own labels; surrounding plant context synthetic. Method: `docs/EVAL_PLAN.md`; decisions: `docs/DECISIONS.md` ADR-026.

## How it works
Six ADK agents on Gemini (Agent Platform, `global`): **Commander** (plans competing checks) → **Signal Analyst** (change points, spectra, `listen` on machine audio) ∥ **Evidence Librarian** (alarms, shift notes, work orders, manual citations from a context cache) → **RCA Judge** (ranks causes, cites evidence ids) → **Deterministic Verifier** (no model: re-runs every number, timestamp, quote, causal order and citation premise; FAIL sends rejected claims back, max 3 loops) → **Action Drafter** (work order; code inserts every mandatory LOTO step verbatim) → human approval. Models: `gemini-3.8-flash` (reasoning, judge), `gemini-3.1-flash-lite` (triage, mapping, transcription). Diagram: `docs/screenshots/video-04-architecture.png`; detail: `docs/ARCHITECTURE.md`, `docs/AGENTS_SPEC.md`.

**Google Cloud:** Agent Platform (Gemini), Cloud Run (API, SSE), Firebase Hosting (web), Firestore (audit log, mock CMMS, shared spend counter), Cloud Storage (published scenario store, audio clips), Secret Manager, Cloud Build + Artifact Registry. Live tools query a per-incident DuckDB built from Parquet in Cloud Storage (ADR-021); a BigQuery dataset is provisioned for analytics.

**Also live:** bring-your-own CSV (`/upload`: Flash-Lite proposes a column→tag mapping, a human confirms, then a normal investigation runs on the upload), a technician view (`/tech`: one card at a time, big safety checklist, voice note → structured shift note marked untrusted) and a work-order language toggle (Hindi, Tamil, Bahasa Indonesia, Vietnamese; safety steps stay verbatim in the original with the translation beside them).

## Safety and honesty rules (enforced in code and tests)
- **No physical writes.** The only write tool drafts `PENDING_APPROVAL` work orders in a mock CMMS; a human approves.
- **Safety text is verbatim.** Lockout/tagout steps are exact manual quotes with page numbers; mandatory steps are inserted by code (ADR-025).
- **Every claim is verified by code** before it reaches the UI; unverifiable claims are shown struck through, never dropped.
- **Provenance everywhere.** Real-signal evidence is marked with its source and rows; uploads are marked `USER UPLOAD`.
- **Cost guard.** Every Gemini call goes through one gateway with a ledger and a daily kill switch; replay is free.

## Data and sources
Public datasets only, used under their licences: MetroPT-3 (UCI, CC BY 4.0), UCI Condition Monitoring of Hydraulic Systems (CC BY 4.0), IMS Bearings (Univ. of Cincinnati via NASA PCoE, U.S. Government Works), MIMII (Zenodo, CC BY-SA 4.0; clips we serve stay CC BY-SA), MaintIE (MIT; style reference for synthetic notes). Raw data is never committed; `scripts/fetch_datasets.py` downloads it and `data/SOURCES.md` records URLs, licences, checksums and citations. Lockout/tagout structure follows OSHA 29 CFR 1910.147; the five equipment manuals are fictional, written for this demo. Downtime figure in the video: Siemens, *The True Cost of Downtime 2024*, p. 2 ("an hour's downtime in a large automotive plant now costs $2.3 million"). Details: `docs/DATA_SOURCES.md`.

## Run locally
```bash
uv sync
uv run pytest -q                                   # 700+ offline tests, LLM mocked
uv run python -m agents.cli --scenario R002 --mode replay
uv run uvicorn api.main:app --reload --port 8080
cd web && npm i && npm run dev                     # VITE_API_URL=http://localhost:8080
```
Data rebuild, eval and deploy commands: `CLAUDE.md` (Commands). Judging-window operations: `docs/RUNBOOK_JUDGING.md`.

## Repo map
`agents/` ADK graph, tools, verifier, prompts · `api/` FastAPI + SSE, audit, replay, uploads · `web/` React console · `simulator/` synthetic plant, real-signal mapping, manuals · `eval/` harness, baselines, statistics, results · `infra/` bootstrap, IAM, deploy, judging check · `video/` motion graphics · `docs/` architecture, decisions, risks, runbook.

Built during the Google Cloud AI Builder Cup 2026 hackathon window. Code licence: MIT.
