# Handoff log (newest first)

## 2026-10-10 night — Person A — Phase 0 (partial)
**Done:** repo skeleton on `a/bootstrap`; `config.py` with verified pinned IDs + prices (ADR-015); `agents/llm.py` v0 (pinned guard, retry/backoff, judge fallback on 429/5xx/timeout, cost maths incl. Pro long-context tier, IST daily kill switch) — 22 offline tests green; `/healthz` exercised locally; infra scripts + `scripts/smoke_models.py` written, **not yet run** (no GCP project).
**GCP (project `andon-agent-511218`, gcloud config `andon`, account srilakshmikripa26@gmail.com):** bootstrap + IAM done — APIs, Artifact Registry `andon`, SAs `andon-api@`/`andon-eval@`, BQ dataset `andon`, buckets `-assets`/`-eval`, Firestore native asia-south1, budget `andon-300` = ₹26,500 (billing account is INR; ~88 INR/USD assumed), credits excluded so alerts fire on gross cost.
**Still open:** first Cloud Run deploy failed — Cloud Build's default compute SA lacks storage access on a new project. Plan: dedicated `andon-build@` SA with `roles/cloudbuild.builds.builder`, pass `--build-service-account`. ADC still points at another account → run `gcloud auth application-default login` as the project account before `scripts/smoke_models.py`.
**Follow-ups from principal-engineer review (not done):**
- Phase 2: ADK calls bypass llm.py → AndonBudgetPlugin (RISKS #22). Residency mode needs `Gemini(..., client_kwargs={"location": "asia-south1"})`.
- Phase 3: spend counter → Firestore (then raise max-instances); `roles/datastore.user` allows deletes, so append-only audit must be enforced in code + test (Firestore rules don't bind server SDKs) — fix SECURITY.md wording; deploy must set `ALLOWED_ORIGINS` + `DAILY_BUDGET_USD`; `.dockerignore` excludes `data/` (replay fixtures need GCS or an allow-list); ledger rows for failed/timed-out calls.
**For Person B:** contracts (`/phase-1 contracts`) not started; ARCHITECTURE §4 is the source. Note ruff ≥0.17 formats Markdown code blocks — `*.md` is now excluded.
