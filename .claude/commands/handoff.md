---
description: End-of-session handoff note for your teammate (and their Claude)
---

Write a handoff note and append it to `docs/HANDOFF.md` (create if missing), newest at the top, then commit and push it.

Format (≤20 lines):
```
## <YYYY-MM-DD HH:MM IST> — Person <A/B>, branch <name>
Done: (bullets, with file paths and commit hashes)
Working but not merged:
Broken / blocked: (exact error, where, what was tried)
Contract changes: (none, or what + ADR number)
Spend this session: $X (source)
Next for me:
Needs from the other person:
```
Before writing, run `git status`, `git log --oneline -10`, and `uv run pytest -q` so the note is factual. The other person's Claude should start its next session with: "Read docs/HANDOFF.md and continue."
