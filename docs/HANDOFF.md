# Handoff log (newest first)

## 2026-10-10 night — Person A — Phase 0 (partial)
**Done:** repo skeleton on `a/bootstrap`; `config.py` with verified pinned IDs + prices (ADR-015); `agents/llm.py` v0 (pinned guard, retry/backoff, judge fallback on 429/5xx/timeout, cost maths incl. Pro long-context tier, IST daily kill switch) — 22 offline tests green; `/healthz` exercised locally; infra scripts + `scripts/smoke_models.py` written, **not yet run** (no GCP project).
**Blocked on:** GCP project ID + billing account → `infra/bootstrap.sh`, `infra/iam.sh`, smoke_models, first deploy. Public GitHub repo not created yet (nothing pushed).
**Follow-ups from principal-engineer review (not done):**
- Phase 2: ADK calls bypass llm.py → AndonBudgetPlugin (RISKS #22). Residency mode needs `Gemini(..., client_kwargs={"location": "asia-south1"})`.
- Phase 3: spend counter → Firestore (then raise max-instances); `roles/datastore.user` allows deletes, so append-only audit must be enforced in code + test (Firestore rules don't bind server SDKs) — fix SECURITY.md wording; deploy must set `ALLOWED_ORIGINS` + `DAILY_BUDGET_USD`; `.dockerignore` excludes `data/` (replay fixtures need GCS or an allow-list); ledger rows for failed/timed-out calls.
**For Person B:** contracts (`/phase-1 contracts`) not started; ARCHITECTURE §4 is the source. Note ruff ≥0.17 formats Markdown code blocks — `*.md` is now excluded.
