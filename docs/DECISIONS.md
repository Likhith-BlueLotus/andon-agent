# Decision log (ADRs, newest at the bottom)

Format: **ADR-NNN — title** · date · status · context → decision → alternatives rejected → consequences.

**ADR-001 — Theme: Manufacturing** · 2026-10-10 · accepted
Context: six themes, same rubric. → Decision: Manufacturing (agentic RCA). → Rejected: BFSI (crowded, temptation to reuse startup work), Retail/Media/Future of Work (wrapper-heavy), Sustainability (impact unverifiable in 7 days). → Consequence: theme string fixed everywhere.

**ADR-002 — Product: Andon Agent (multi-source RCA + verifier + HITL)** · 2026-10-10 · accepted
Rejected: predictive-maintenance dashboard, chat-with-manual RAG, vision defect explainer (YOLO does it cheaper), warranty text clustering (demos as analytics).

**ADR-003 — Orchestration: ADK workflow agents** · 2026-10-10 · accepted
Sequential → Parallel → Loop(Judge ↔ deterministic Verifier, max 3) → Drafter. Rejected: single LlmAgent with all tools (no guaranteed verification, worse eval story); A2A multi-service (latency + deploy cost; stretch only, post-freeze if ever).

**ADR-004 — Retrieval: context cache for manuals, SQL for keyed data, no vector search in v1** · 2026-10-10 · accepted
Manuals <200K tokens, interlinked, reused per incident. WOs/alarms have keys. Vector search documented as the scale path.

**ADR-005 — Model routing** · 2026-10-10 · accepted (verify IDs in Phase 0)
3.8 Flash for loops, 3.1 Flash-Lite for volume, 3.1 Pro preview for the judge with Flash fallback. Judge runs on Flash during development to save credits.

**ADR-006 — Frontend: React + Vite SPA on Firebase Hosting, calling Cloud Run directly** · 2026-10-10 · accepted
Changed from the research report's Next.js on App Hosting: a static SPA is less to deploy and debug in 7 days, and a Hosting rewrite could cut long SSE streams. Fallback: serve the built SPA from FastAPI.

**ADR-007 — Storage abstraction: `TelemetryStore` with DuckDB and BigQuery backends** · 2026-10-10 · accepted
Tests run offline and free; cloud demo uses BigQuery. Same SQL dialect subset only.

**ADR-008 — Public demo: replay by default, live behind passcode, daily kill switch** · 2026-10-10 · accepted
Protects the $300 budget through the Dec 4 finale.

**ADR-009 — Hybrid data: synthetic line + real public signals with provenance** · 2026-10-10 · accepted
Context: "it's all synthetic" was the self-assessment's top weakness. → Decision: map MetroPT-3 (compressed air), UCI hydraulic (press), IMS (bearings) and MIMII (audio) into specific stations; MaintIE for work-order style; OSHA 1910.147 for LOTO structure; provenance on every real segment. → Rejected: fully synthetic (weak credibility); a fully real line dataset (none exists openly for automotive lines); non-commercial datasets (Paderborn, ToyADMOS, MIMII DUE/DG). → Consequence: new `hydraulic_degradation` class, 5 manuals, provenance contract field, R-set.

**ADR-010 — R-set graded by source labels, reported separately** · 2026-10-10 · accepted
17 real-signal scenarios whose truth comes from failure reports / rig labels / readme. Never merged into S-set headline numbers. Honest wording: root-cause signal real, surrounding plant synthetic.

**ADR-011 — Small-n statistics in the eval** · 2026-10-10 · accepted
Wilson intervals, exact McNemar for paired system comparisons, a 3× variance run, calibration. Rejected: bare accuracy numbers (overclaim risk with n = 60 / 17).

**ADR-012 — Eval harness owned by Person A** · 2026-10-10 · accepted
The harness calls the agents and shares `agents/llm.py`; Person B takes data (incl. R-set), frontend and pitch. Rebalances Tue–Thu load.

**ADR-013 — Stretch ladder behind a gate** · 2026-10-10 · accepted
BYO-CSV → technician view + voice note → multilingual WO, only if phases 1–4 pass and Run-20 shows S1 ≥ B1 by Thu 12:00 IST; otherwise a deck slide with a mock.

**ADR-014 — Demo scenario: real-signal air leak (R-set)** · 2026-10-10 · accepted
Weld cells alarm, root cause upstream in plant air: the clearest "alarm at the wrong station" story, on real data with an operator-labelled ground truth. Backup: S-set sealer cavitation with audio.

**ADR-015 — Phase 0 platform verification results** · 2026-10-10 · accepted
Context: pinned IDs, prices, SDK names checked against live docs (Agent Platform model + pricing pages, PyPI, adk.dev). → Decision: all four pinned IDs exist (3.5 Flash GA and regional in asia-south1 — residency mode valid); prices in `config.py` with source URL; set both `GOOGLE_GENAI_USE_ENTERPRISE` and `GOOGLE_GENAI_USE_VERTEXAI` (SDK 2.29 prefers the former); `llm.py` passes `vertexai=True` explicitly so behaviour doesn't depend on env; fastapi floor lowered to what google-adk 2.11 allows; Hosting rewrite still 60 s → keep direct Cloud Run calls (ADR-006 stands). → Consequences: 3.8 Flash price doubles on 2027-01-01 (after Dec 4, no impact); residency calls cost +10% (non-global rate). Live call confirmation pending GCP project.

**ADR-016 — Trunk-based development on `main`** · 2026-10-11 · accepted
Context: owner preference; two people, one week, PR overhead slows integration. → Decision: commit directly to `main`; no `a/`/`b/` branches. → Rejected: branch + PR per topic (DEVELOPMENT §3 v1). → Consequences: every commit must pass tests + ruff; `git pull --rebase` before push; directory ownership avoids conflicts; contract files still need both humans' OK.

**ADR-017 — Contracts v1.0.0 frozen** · 2026-10-11 · accepted (Person A; Person B to confirm)
Written from ARCHITECTURE §4 with five additions: `RCAReport.hypotheses` max 3 enforced; `AgentData.model_id` nullable (deterministic verifier has no model); `ErrorData.code` documents `budget_exhausted`; `encode_sse()` sends `id: <seq>` for resumable streams; `parse_event()` validates the discriminated union. `tests/test_contracts.py` keeps `web/src/types/events.ts` in sync (event types, cause classes, version, interface fields). Guard test forbids `agents/`/`api/` from importing truth/eval modules or mentioning `truth.json`.
