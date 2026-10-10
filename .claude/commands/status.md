---
description: Where are we vs. the plan — phases, tests, deploy, spend vs ledger, risks, next action
---

Report project status in under 30 lines. Gather facts, don't guess:

1. Today's date/time in IST and this person's row from DEVELOPMENT.md §5.
2. Each phase's exit criterion (DEVELOPMENT.md §4): met / partly / not started — with evidence (test name, URL, file).
3. `git log --oneline -15` summary and unpushed commits on this branch; anything in docs/HANDOFF.md waiting on this person.
4. `uv run pytest -q` result (offline only — don't run `-m live`).
5. Live URL health (`scripts/smoke.sh` if the URL exists).
6. **Spend vs ledger:** each DEVELOPMENT.md §7 line — spent / allocation / hard stop — from our cost accounting and audit log. Flag any line above 80%.
7. **Risks:** any docs/RISKS.md trigger that has fired, and the mitigation due today.
8. **Stretch gate** (§9b): open / closed, and why.
9. Cut-list decision for today (at/after 20:00 IST be decisive).
10. The single next action for this person.
