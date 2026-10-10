---
description: Phase 0 — bootstrap repo, GCP project, pinned-model smoke test, Cloud Run hello-world
argument-hint: "[gcp-project-id]"
---

# Phase 0 — Bootstrap (target: Sat Oct 10 night, ≤3 hours)

GCP project id: $ARGUMENTS (if empty, ask me for it once, then continue).

Create a task list for the steps below and work through them. Delegate infra to the `sre-devops-engineer` subagent and the repo skeleton review to `principal-engineer`.

1. **Repo skeleton** exactly as in CLAUDE.md "Repo map", with `__init__.py` files, `pyproject.toml` (uv, Python 3.12, deps from docs/TECH_STACK.md, pytest markers `live`), `ruff.toml`, `.gitignore` (data/raw, data/*.duckdb, .env*, node_modules, eval/results/*/raw), `.env.example`, `Dockerfile` (multi-stage, python:3.12-slim, uv), `.pre-commit-config.yaml` with ruff + gitleaks, MIT `LICENSE`, and a README whose first line is `Theme: Manufacturing: Intelligent Operations & Industrial Efficiency`.
2. **`config.py`**: pinned model IDs, locations, budgets, limits from CLAUDE.md, read overrides from env, no secrets.
3. **Verify the platform before trusting our docs:** fetch the current ADK docs (adk.dev) and the Gemini Enterprise Agent Platform model pages for each pinned model; check the install name of ADK and google-genai, the env var that switches google-genai to Agent Platform/Vertex mode, and the context-cache minimum token count. Fix any doc in this repo that is wrong and add an ADR or lessons-learned entry.
4. **`agents/llm.py` v0**: a thin wrapper around google-genai with retry/backoff, model fallback hook, token + cost accounting (prices in `config.py` with the source URL and date in a comment), and an in-memory daily spend counter. Unit-test the cost maths offline.
5. **Live model smoke test** `scripts/smoke_models.py`: one tiny call to each pinned model on `location=global` (and `gemini-3.5-flash` on `asia-south1`), print model id, latency, tokens, cost. If any ID fails, stop and tell me the exact error and the closest valid ID from the docs.
6. **GCP bootstrap** via `infra/bootstrap.sh` and `infra/iam.sh` (see docs/TECH_STACK.md and docs/SECURITY.md). Show me each command before running anything that creates billable resources. Budget alerts at $100/$200/$250 — if the billing account id is needed, ask me.
7. **Hello-world API**: `api/main.py` with `/health` only; deploy with `infra/deploy_api.sh` using the `andon-api@` service account; run `scripts/smoke.sh <url>`.
8. **Day-0 hygiene:** confirm team registration screenshot exists (ask me), the eligibility email is sent (RISKS #2), free disk ≥ 30 GB for datasets, budget ledger copied into `/status` output format.
9. Commit (`chore: bootstrap`) and push.

Exit criterion: the smoke script shows all pinned models answering, and `/health` responds from the Cloud Run URL. Then update docs/LESSONS_LEARNED.md and tell me the URL, the measured cost of the smoke test, and anything that differed from our docs.
