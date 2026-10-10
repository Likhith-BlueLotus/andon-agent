---
description: Audit every external dataset and text for licence, attribution, provenance and honest wording
---

Use the `security-reviewer` subagent (read-only) for this audit, with docs/DATA_SOURCES.md as the rulebook. Do not edit files; report findings.

Checks (show the command or file:line for each):
1. **Allowed sources only:** every dataset referenced in `scripts/`, `simulator/`, `data/SOURCES.md` is on the USE list. `git grep -iE` for every DO-NOT-USE dataset name returns nothing outside docs.
2. **No raw data in git:** `git ls-files data/raw` is empty; no file > 5 MB tracked outside `eval/results` (list `git ls-files` sizes).
3. **SOURCES.md complete:** each dataset has URL, licence, licence-check date, files used, SHA-256, transforms, citation copied from the source page.
4. **Provenance:** provenance test passes; spot-check 3 R-set scenarios — provenance rows point to real source rows/files and the stated transform matches the code.
5. **Truth honesty:** R-set `truth.json` files have `truth_source: source_label`, and the label matches the source (MetroPT-3 failure-report window, UCI cycle label, IMS readme).
6. **Share-alike:** MIMII clips live in GCS, marked CC BY-SA 4.0 with attribution; none committed.
7. **Attribution surfaces:** README data section, UI footer (`/api/sources`), deck data slide — all list the datasets used.
8. **Wording:** grep README, deck/, web/src and prompts for "real plant", "real factory", "production data" and similar; flag anything overstating that the line is real.
9. **Employer/startup terms:** `git grep -i` for the names the humans give you; report the exact command.

Output: table (check · pass/fail · evidence · fix), then **Clean / Not clean** with blocking items.
