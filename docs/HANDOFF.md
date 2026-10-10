# Handoff log (newest first)

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
