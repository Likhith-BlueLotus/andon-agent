---
description: Phase 3 — FastAPI SSE service, HITL approval, audit, replay, budget protection, Cloud Run deploy
argument-hint: "[stream | hitl | replay | protect | deploy]"
---

# Phase 3 — API + deploy (Tue Oct 13 → Wed Oct 14)

Focus: $ARGUMENTS (default: next unfinished).

Delegate API work to `senior-backend-engineer`, deploys to `sre-devops-engineer`, and run `security-reviewer` before the first public deploy.

1. **Streaming endpoint**: `POST /api/incidents/{scenario_id}/investigate` streams events from the agent graph per docs/ARCHITECTURE.md §4.2; heartbeats; disconnect cancels; errors become events. Tests with a fake runner.
2. **Deploy early** (today, even if only step 1 works): `infra/deploy_api.sh` with `--timeout 900`, `STORE_BACKEND=bigquery`, `andon-api@` SA. Run `scripts/smoke.sh <url>` and a curl that prints the raw SSE stream for S001. Fix buffering if events arrive in one lump.
3. **Firestore**: ADK session persistence, append-only audit (`audit/{incident_id}/steps/{seq}`), mock CMMS collection.
4. **HITL**: `POST /api/incidents/{id}/approve` — rejects if any safety step unticked; writes APPROVED/REJECTED + audit entry.
5. **Replay**: `?mode=replay&run_id=` streams a stored run with original timing; seed 3 replays from real live runs (R002 demo scenario, one S-set with audio, and one with a verifier rejection).
6. **Protection**: passcode header for live mode (Secret Manager), per-IP and per-day rate limits, daily budget kill switch (`budget_exhausted` event), CORS allow-list, `--max-instances 3`.
7. **Other endpoints**: `/api/scenarios` (grouped synthetic / real-signal with source), `/api/incidents/{id}/audit`, `/api/eval/latest`, `/api/sources`.
8. Redeploy, run smoke + one full live run against the URL, record it as a replay.

Exit criterion: from a laptop that isn't yours (or incognito + curl), the Cloud Run URL streams a full live investigation with the passcode and a replay without it; approval writes to the mock CMMS; kill switch tested by setting `DAILY_BUDGET_USD=0.01` temporarily. Security review has no blocking findings. Update LESSONS_LEARNED, commit, push, report the URL and measured cost per live run.
