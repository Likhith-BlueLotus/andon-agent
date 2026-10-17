# Handoff log (newest first)

## 2026-10-17 (late) — Person A — Three weaknesses addressed, post-hoc rerun
**Verifier value (ADR-032):** offline fault injection, 2,778 faults, caught 97.1% [96.4, 97.7] vs S2 0%; sign flips 92.6%, false premises 90.6%; 8/586 true claims wrongly flagged (`eval/results/stress_verifier/`).
**Pre-registered C-set:** S1 0.40 (P1 FAIL), B1 0.20 (P2 pass), unsupported 0/80 vs 6/91 (`eval/results/confirm_c_v1`, results in `eval/preregistration_confirm.md`).
**Short-fault detector (ADR-033) + analyst v4, post-hoc S1 rerun `eval/results/posthoc_v4`:** S 0.97 [0.89, 0.99] (58/60; S024, S046 missed), R 0.82 [0.59, 0.94] (14/17; R009–R011 missed), C 0.50 (healthy 5/5, short hydraulic 0/5), 0/648 unsupported. No regression → deploy. The detector removes the false alarm but the judge still calls short real hydraulic faults healthy (open weakness, said plainly in README + Q&A).
**Fix found by the rerun:** dropped Gemini connections (`httpx.ReadError`) failed whole runs; `PinnedGemini` now retries before any output (RISKS #28, 13dea08).
**Spend:** eval ≈ $99.8 of $120 hard stop; Gemini total ≈ $107. Eval's $8 cap is per process; the live API's Firestore counter is separate.
**Deployed:** revision andon-api-00005-sxj, `/health` git_sha 5cb4b35; judging_check ALL PASS; replay R002 PASS.
**Deck/slide:** use the `final_v2` table as the headline; post-hoc numbers and `posthoc_v4/results_slide.png` only as a labelled post-hoc slide or in Q&A.

## 2026-10-17 — Person A — Release candidate v1.0-rc (new GCP project andon-511816)
**Live:** web https://andon-agent-b9c77.web.app · API https://andon-api-359520289475.asia-south1.run.app (revision with `/health` git_sha 6f6ea10, max-instances 1, stretch upload,tech,lang). Old project `andon-agent-511218` suspended 2026-10-13 (appeal pending) → moved per ADR-031; new demo passcode in Secret Manager (`--project andon-511816`).
**Release check: all pass.** main green (708 pytest, ruff, 150 vitest + build); judging_check ALL PASS; live R002 in the browser verified air_pressure_drop @ UT-AIR (7/7 claims, PASS iter 1, 19 LOTO steps, $0.14); replay `r002-cloud-1` re-recorded on the final build, `s014-cloud-1` keeps the verifier rejection; final security review + data audit: OK to submit, no blockers.
**Hardening:** 5/5 live runs PASS (p50 104 s, p95 112 s, 0 fallbacks, $0.77); warm /health 0.16 s; cancel on client disconnect does NOT happen on Cloud Run (RISKS #27, bounded by limits + kill switch); andon.* INFO logs (cost ledger) now reach Cloud Logging.
**Fixes in the move:** new endpoint rejects tools + JSON schema in one request → set_model_response path (ADR-031 lesson); deploy script exit bug; publish --workers.
**Spend:** ≈ $86 Gemini to date (ledger in DEVELOPMENT.md §7); eval $79 of $120 hard stop.
**Remaining (Person B / both):** record screen segments (no mock screenshots 04/53), edit + upload the video (<3:00, public), deck content + PDF, fresh screenshots of the redesigned UI, submission form + confirmation screenshot, Q&A rehearsal. Daily judging check owners in docs/RUNBOOK_JUDGING.md. Warm for recording: `bash infra/warm.sh on` (off after).

## 2026-10-12 — Person A — Phase 5 DONE (eval), ADR-025/026/027
**Results (final_v2, Flash judge, `eval/results/final_v2`, slide `results_slide.png`, live at /eval):** S-set top-1 S1 0.98 [0.91, 1.00] · S2 1.00 · B1 0.92 · B2 0.15; held-out S051–S060 S1 10/10, B1 9/10. R-set S1 0.76 [0.53, 0.90] · S2 0.76 · B1 0.59 · B2 0.24. Unsupported claims S1 1/586 vs B1 54/645. S1 vs B1 top-1 not significant (McNemar p 0.219 S / 0.375 R). Variance (15×3): 0.80/0.73/0.87. S3 (no audio/spectrum) 1.00 on the audio subset. S1 Pro judge: S 0.90 / R 0.71, $0.16/run → Flash stays.
**Honest reading:** the win over one long prompt is grounding, not accuracy; the verifier loop adds little over S2 in this eval (its value is code-checked LOTO + premises); UCI R009–R011 missed by every system; R002 (demo) unstable across repeats.
**Fixed because of the eval:** ADR-025 mandatory LOTO + citation premises; ADR-027 runaway tool loop; shared manuals cache. Deployed API = evaluated build. Replays: r002-cloud-1 re-recorded (19 safety steps), r002-live-1 removed.
**Spend:** eval $70.24 of $110; live/dev today ≈ $1.
**Open for the owner:** (1) R002 instability — fix (makes R-set post-hoc) or leave; (2) run `/release-check` before phase 6; stretch gate (§9b) is open on Run-20 numbers.

## 2026-10-11 — Person A — Phase 4 DONE (frontend live)
**Live app:** https://andon-agent-b9c77.web.app (Firebase project `andon-agent-b9c77`, hosting only — ADR-024; API/data stay in `andon-agent-511218`). Deploy: `bash infra/deploy_web.sh` (tests → build → deploy → 200 + CORS checks); API CORS now allows only the b9c77 origins (`localhost` removed; `DEV=1` re-adds it).
**Built (web/):** 3-pane console (mimic + utilities rail, agent trace with provenance chips, RCA + verifier + safety-gated WO), evidence drawer with real telemetry (`GET /api/scenarios/{id}/telemetry`, ADR-023), every state in UX_SPEC (`?mock=1|error|drop|budget|insufficient`), `/eval` page, attributions dialog. 42 vitest; Recharts lazy-loaded (main chunk 324 kB).
**Exit checks on the deployed URL:** replay R002 keyboard-only → evidence drawer (Esc returns focus) → Accept → 17 safety boxes by Space → approver → Approve → APPROVED (demo record); live R002 with passcode: top-1 air_pressure_drop @ UT-AIR, verifier PASS iter 1, 128 s, $0.189. 375 px: no horizontal scroll. Screenshots `docs/screenshots/01–26`.
**Found in the live run (fixing now, ADR-025):** (1) drafter LLM could omit unconditional LOTO steps (live WO had 16/21, missing the absence-of-voltage test) → code will insert every mandatory step; (2) a citation's premise ("sustained fall in header pressure") was not met by R002 evidence yet passed verbatim check → verifier will check passage preconditions against evidence. The live R002 WO from that run was left PENDING (not approved).
**Not done:** stretch views (§9b gate closed until Run-20).
**Next:** ADR-025 fixes → `/phase-5` (harness being built) → `/phase-6`.

## 2026-10-11 — Person A — Phase 3 DONE
**Live API:** https://andon-api-891056416508.asia-south1.run.app (stale: old project suspended — now https://andon-api-359520289475.asia-south1.run.app, ADR-031) (public; revision andon-api-00007). Replay for everyone, live behind `X-Demo-Passcode` (Secret Manager `demo-passcode`; read with `gcloud secrets versions access latest --secret demo-passcode` under config `andon` — never paste it anywhere).
**Endpoints:** `POST /api/incidents/{id}/investigate?mode=live|replay&run_id=&speed=` (SSE), `POST /api/incidents/{id}/approve`, `GET /api/incidents/{id}/audit`, `/api/scenarios`, `/api/replays`, `/api/config`, `/api/sources`, `/api/eval/latest` (404 until phase 5), `/health`.
**Replays:** `r002-cloud-1` (demo: real MetroPT-3 leak, listen on UT-AIR, approved WO), `s014-cloud-1` (verifier rejects reversed causal order → revision → PASS), `r002-live-1` (local live).
**Exit checks passed on the URL:** live R002 from a clean curl ($0.156, 117 s, verified air_pressure_drop @ UT-AIR); live S014 ($0.171, 95 s, verified sealer_pump_cavitation @ ST40-SLR, 1 natural rejection); approve → 409 partial / APPROVED in Firestore `work_orders` / 409 second decision; kill switch at $0.01 refused live with `budget_exhausted` from the shared Firestore counter (restored to $8, secret v2 disabled); anonymous live 401; CORS rejects other origins; security review: OK to make public, all should-fix items done.
**For Person B:** `VITE_API_URL=https://andon-api-891056416508.asia-south1.run.app (stale: old project suspended — now https://andon-api-359520289475.asia-south1.run.app, ADR-031)`; CORS allows `https://andon-agent-511218.web.app`, `.firebaseapp.com` and `http://localhost:5173`. Stream contract = `api/events.py` / `web/src/types/events.ts`; replay first, live with passcode.
**Next (A): `/phase-5 harness`** (eval) — the Phase 4 frontend is Person B's.
**Open:** `/api/eval/latest` needs `eval/results/latest.json` copied into the image (phase 5); judging-window runbook in `docs/RUNBOOK_JUDGING.md`.

## 2026-10-11 — Person A — Phase 1 + Phase 2 DONE
**Phase 1:** 60 S + 17 R scenarios in DuckDB (`data/andon.duckdb`, rebuild: generate → real_signals → audio → load) and BigQuery `andon` (1.36 B telemetry rows). 5 manuals (50,135 tokens) with LOTO reviewed (ADR-019, hash `c5b39659…`). Contracts v1.0.0 (ADR-017). Data: `data/SOURCES.md`, `docs/data_inspection.md`.
**Phase 2:** full ADK graph runs end to end. `uv run python -m agents.cli --scenario R002 --mode replay` ($0, <3 s) or `--mode live` (~$0.15–0.19 with Flash judge, 80–95 s). `--force-bad-claim` shows a verifier rejection → revision → PASS. Live (Flash judge): R002, S005, S010 all top-1 correct vs truth (clean variants only — eval will test red herrings / no_fault).
**Spend to date:** ≈ $1.25 Gemini (ledger line Phase 0–2: $45).
**Next (A): `/phase-3`** — FastAPI SSE forwarding `agents.events_map.run_incident`, HITL approve, audit, replay, passcode/rate limit, deploy.
**Phase 3 decisions waiting:** (1) RISKS #24 BigQuery 7–16 s per tool → per-incident DuckDB from GCS Parquet (leaning); (2) manuals cache created per run (~$0.044) → share one cache per API process with TTL refresh; (3) DuckDB queries share one process lock → fine at max-instances 1; (4) image 1.19 GB → cold start; (5) spend counter → Firestore before raising max-instances.
**Known quality risks:** RISKS #25 Gemini audio verdicts unreliable (MFCC is the checkable number); anomaly_score misreads the real start/stop compressor (hint only).
**For Person B (frontend):** the real stream matches `tests/fixtures/sample_stream.jsonl` shape; `uv run python -m agents.cli --scenario R002 --mode replay --json` prints real contract events (JSONL) to build against.

## 2026-10-11 ~01:00 IST — Person A — Phase 0 DONE
**Live:** API https://andon-api-891056416508.asia-south1.run.app (stale: old project suspended — now https://andon-api-359520289475.asia-south1.run.app, ADR-031)/health (runtime SA `andon-api@`, max-instances 1, timeout 900 s, docs disabled in prod). Repo: https://github.com/Likhith-BlueLotus/andon-agent, trunk-based on `main` (ADR-016), CI = ruff + pytest + gitleaks.
**GCP `andon-agent-511218`** (gcloud config `andon`; run `export CLOUDSDK_ACTIVE_CONFIG_NAME=andon`): APIs, Artifact Registry, SAs `andon-api@` / `andon-eval@` / `andon-build@`, BQ `andon`, buckets `-assets` / `-eval`, Firestore native asia-south1, budget `andon-300` ₹26,500 (INR account; credits excluded).
**Model smoke (live, 2026-10-11):** all 4 pinned IDs answer — 3.8 Flash 2.4 s, 3.1 Flash-Lite 1.3 s, 3.1 Pro preview 4.0 s, 3.5 Flash asia-south1 1.6 s; total $0.0019. Flash-Lite still spent 144 thinking tokens at LOW.
**Spend to date:** ~$0.002 Gemini + Cloud Build minutes (free tier).
**Next (A):** `/phase-1 contracts` with B (show both humans before merge), then `/phase-2`.
**Follow-ups from principal-engineer review:**
- Phase 2: ADK calls bypass llm.py → AndonBudgetPlugin (RISKS #22). Residency mode needs `Gemini(..., client_kwargs={"location": "asia-south1"})`. Confirm explicit-cache minimum on 3.8 Flash with one live `caches.create`.
- Phase 3: spend counter → Firestore (then raise max-instances); `roles/datastore.user` allows deletes, so append-only audit must be enforced in code + test — fix SECURITY.md wording; `.dockerignore` excludes `data/` (replay fixtures need GCS or an allow-list); ledger rows for failed/timed-out calls; set real `ALLOWED_ORIGINS` once Firebase site exists.
- Local ADC on this laptop still belongs to another account; use `scripts/smoke_models.py --gcloud-token` or re-run `gcloud auth application-default login`.
**For Person B:** ruff ≥0.17 formats Markdown code blocks — `*.md` is excluded in ruff.toml. No route may end in `z` (Cloud Run).
