---
description: Gate for the Thu Oct 15 23:59 IST feature freeze — tag v1.0-freeze only if it passes
---

Check each item and show evidence. If all pass, tag `v1.0-freeze` and push the tag. If any fail, list them with the smallest fix and do not tag.

- [ ] `main` is green: `uv run pytest -q`, `ruff check .`, `cd web && npm run build && npx vitest run`
- [ ] Deployed API and web match `main` HEAD (compare `/healthz` version to `git rev-parse --short HEAD`)
- [ ] Full live investigation of R002 succeeds on the deployed web app; replay works without passcode
- [ ] Verifier rejection visible in at least one replay; provenance chips visible on real evidence
- [ ] HITL approval gate works and refuses unticked safety steps; LOTO steps verbatim
- [ ] Eval results for S1/S2/B1/B2 on S-set and R-set committed with intervals, McNemar, and the results slide
- [ ] Only one write tool; `truth.json` guard, provenance and injection tests pass
- [ ] Kill switch, rate limit, passcode tested
- [ ] `/data-audit` clean
- [ ] Unfinished stretch items reverted or disabled (`ENABLE_STRETCH` empty unless finished)
- [ ] README first line has the exact theme string; live URL in README
- [ ] No employer/startup names or terminology anywhere (report the `git grep -i` command used)
- [ ] Spend so far within ledger (target ≤ $150 at freeze)

After tagging: only bug fixes, copy, styling, performance and docs.
