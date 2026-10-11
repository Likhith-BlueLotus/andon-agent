# Handoff log (newest first)

## 2026-10-11 — Person A — Phase 1 + Phase 2 DONE
**Phase 1:** 60 S + 17 R scenarios in DuckDB (`data/andon.duckdb`, rebuild: generate → real_signals → audio → load) and BigQuery `andon` (1.36 B telemetry rows). 5 manuals (50,135 tokens) with LOTO reviewed (ADR-019, hash `c5b39659…`). Contracts v1.0.0 (ADR-017). Data: `data/SOURCES.md`, `docs/data_inspection.md`.
**Phase 2:** full ADK graph runs end to end. `uv run python -m agents.cli --scenario R002 --mode replay` ($0, <3 s) or `--mode live` (~$0.15–0.19 with Flash judge, 80–95 s). `--force-bad-claim` shows a verifier rejection → revision → PASS. Live (Flash judge): R002, S005, S010 all top-1 correct vs truth (clean variants only — eval will test red herrings / no_fault).
**Spend to date:** ≈ $1.25 Gemini (ledger line Phase 0–2: $45).
**Next (A): `/phase-3`** — FastAPI SSE forwarding `agents.events_map.run_incident`, HITL approve, audit, replay, passcode/rate limit, deploy.
**Phase 3 decisions waiting:** (1) RISKS #24 BigQuery 7–16 s per tool → per-incident DuckDB from GCS Parquet (leaning); (2) manuals cache created per run (~$0.044) → share one cache per API process with TTL refresh; (3) DuckDB queries share one process lock → fine at max-instances 1; (4) image 1.19 GB → cold start; (5) spend counter → Firestore before raising max-instances.
**Known quality risks:** RISKS #25 Gemini audio verdicts unreliable (MFCC is the checkable number); anomaly_score misreads the real start/stop compressor (hint only).
**For Person B (frontend):** the real stream matches `tests/fixtures/sample_stream.jsonl` shape; `uv run python -m agents.cli --scenario R002 --mode replay --json` prints real contract events (JSONL) to build against.

## 2026-10-11 ~01:00 IST — Person A — Phase 0 DONE
**Live:** API https://andon-api-891056416508.asia-south1.run.app/health (runtime SA `andon-api@`, max-instances 1, timeout 900 s, docs disabled in prod). Repo: https://github.com/Likhith-BlueLotus/andon-agent, trunk-based on `main` (ADR-016), CI = ruff + pytest + gitleaks.
**GCP `andon-agent-511218`** (gcloud config `andon`; run `export CLOUDSDK_ACTIVE_CONFIG_NAME=andon`): APIs, Artifact Registry, SAs `andon-api@` / `andon-eval@` / `andon-build@`, BQ `andon`, buckets `-assets` / `-eval`, Firestore native asia-south1, budget `andon-300` ₹26,500 (INR account; credits excluded).
**Model smoke (live, 2026-10-11):** all 4 pinned IDs answer — 3.8 Flash 2.4 s, 3.1 Flash-Lite 1.3 s, 3.1 Pro preview 4.0 s, 3.5 Flash asia-south1 1.6 s; total $0.0019. Flash-Lite still spent 144 thinking tokens at LOW.
**Spend to date:** ~$0.002 Gemini + Cloud Build minutes (free tier).
**Next (A):** `/phase-1 contracts` with B (show both humans before merge), then `/phase-2`.
**Follow-ups from principal-engineer review:**
- Phase 2: ADK calls bypass llm.py → AndonBudgetPlugin (RISKS #22). Residency mode needs `Gemini(..., client_kwargs={"location": "asia-south1"})`. Confirm explicit-cache minimum on 3.8 Flash with one live `caches.create`.
- Phase 3: spend counter → Firestore (then raise max-instances); `roles/datastore.user` allows deletes, so append-only audit must be enforced in code + test — fix SECURITY.md wording; `.dockerignore` excludes `data/` (replay fixtures need GCS or an allow-list); ledger rows for failed/timed-out calls; set real `ALLOWED_ORIGINS` once Firebase site exists.
- Local ADC on this laptop still belongs to another account; use `scripts/smoke_models.py --gcloud-token` or re-run `gcloud auth application-default login`.
**For Person B:** ruff ≥0.17 formats Markdown code blocks — `*.md` is excluded in ruff.toml. No route may end in `z` (Cloud Run).
