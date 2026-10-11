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

**ADR-018 — R-set construction rules (Phase 1 Part E)** · 2026-10-11 · accepted (data)
Context: the R-set must take truth only from the sources and still be a line stop the agent can investigate. → Decisions: (1) *Time:* the source clock is read as plant local time and shifted by whole days into Aug–Sep 2026. (2) *MetroPT-3* is 0.1 Hz: 1 Hz rows only between real samples ≤ 20 s apart, never across longer gaps (`source_gap` imperfections). Weld-cell air follows the existing regulator model driven by the mapped header (gaps bridged by hold *for the physics only*). Stop = first weld-air low alarm after the report start, else the operator rule "compressor loaded ≥ 95 % of the last 4 h" (line held at ST20). Onset = report start. (3) *UCI:* the 10 stable all-optimal cycles are looped to fill the week (no other healthy stable cycles exist); the labelled condition's cycles run once, in order, to the stop; onset = first labelled cycle. Cooler 3 % uses the rig's own warm-up cycles 0–209 (flag 1), which avoids a 20 °C step at the splice. (4) *IMS:* RMS per snapshot held at 1 Hz; bearing temperature and drive current follow the real vibration through the S-set's gains; the readme documents no onset, so `onset_ts` is **null** for R016/R017 rather than invented. (5) Agent-visible provenance names exact rows, cycles and files but **withholds labels** (UCI condition labels, the MIMII normal/abnormal folder, MetroPT source dates); labels live in `sim_meta.json` / `audio_truth.json`, never loaded. (6) All R stops are generated from visible symptoms or benign glitches; no-fault stops include air- and hydraulic-sounding glitches so the stop text alone doesn't give the answer. → Rejected: per-segment normalisation (erases 0.3–6 % shifts); repeating fault cycles to lengthen faults (invents duration); a detector-estimated IMS onset as truth (our estimate, not the source's). → Consequences: R009–R012 faults are short (10–19 min, cooler 3.7 h); R001–R003 stop on duty alone (no pressure drop), which is the real signature; the LLM may recognise public datasets from provenance names (IMS test 2, MetroPT-3), so R-set results carry a contamination caveat.

**ADR-019 — LOTO procedures approved (content hash `c5b39659e8d912ea8732b6766bdcd5db4275aa5646636f575e4a6108fb57df1b`)** · 2026-10-11 · accepted
Context: CLAUDE.md hard rule 5 requires review of every energy-control step before the manuals are used. → Review: the project owner (Likhith M, Person A) delegated the step-by-step review to Claude Code and directed approval. All 94 steps in `docs/review/LOTO_REVIEW.md` were checked against 29 CFR 1910.147 (sequence (d)(1)→(d)(6)→(e), every Table 8-1 energy source isolated + locked + stored energy released, notification per (c)(9), (e)(1)–(3) release order, one imperative sentence each, citation matches action). Three defects fixed before approval: (1) weld_controller — servo gun rested / balancer locked moved before cell-air venting (was after: gravity hazard); (2) sealer_pump — follower plate / ram rested moved before ram-air venting (same hazard); (3) press_hydraulics — safety blocks removed under (e)(1) with tools, before the all-clear, instead of after it. → Consequence: any change to `simulator/manuals/loto.py` changes the hash and needs a new review. Caveat kept in every manual: fictional equipment, not a site-specific procedure. Person B may re-review; a human safety professional has not reviewed these steps.
