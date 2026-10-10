---
description: Phase 6 — post-freeze hardening (reliability, cost, security) before recording
---

# Phase 6 — Hardening (Fri Oct 16, after freeze — fixes only, no features)

Run `/freeze-check` first; if the freeze tag `v1.0-freeze` doesn't exist, stop and tell me.

Delegate to `sre-devops-engineer` and `security-reviewer`; fixes to the owning engineer subagent.

1. **Reliability:** 5 consecutive live runs on the deployed stack (3 different scenarios) with the Pro judge; record p50/p95 latency and failures. Force a 429 path (test hook or tiny quota) and confirm fallback + `model_fallback` event. Kill a stream mid-way and confirm cancel + UI reconnect/replay offer.
2. **Cold start:** measure with min-instances 0 and 1; set 1 for recording via `infra/warm.sh on`.
3. **Cost:** print total spend so far (audit log + billing), projected spend for the judging window with replay-by-default, and confirm the kill switch value. Delete stale context caches.
4. **Security + data:** full `security-reviewer` checklist and `/data-audit`; fix blockers only. Disable any stretch endpoint that isn't finished (`ENABLE_STRETCH`).
5. **Content:** grep the repo and UI for any employer/startup names or terminology, TODOs visible in UI, lorem ipsum, console errors in the browser.
6. **Replays:** make sure the 3 replay runs are from the final build and include one verifier rejection.
7. **Judging-window readiness:** `infra/judging_check.sh` works; the runbook names who runs it each day Oct 19–Nov 6; remaining budget vs ledger lines for the judging window and the finalist reserve.
8. Tag `v1.0-rc` and push.

Report: reliability table, cold-start numbers, spend, blockers fixed, and a go/no-go for recording.
