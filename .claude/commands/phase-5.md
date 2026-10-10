---
description: Phase 5 — eval harness, baselines, S-set + R-set runs, statistics, results slide
argument-hint: "[harness | baselines | run20 | final | variance | report | manual]"
---

# Phase 5 — Evaluation (Wed Oct 14 → Thu Oct 15)

Focus: $ARGUMENTS (default: next unfinished).

Delegate to `qa-eval-engineer`; baselines that call Gemini go through `agents/llm.py`. docs/EVAL_PLAN.md is the spec, including its budget table — check spend against DEVELOPMENT.md §7 before every paid run.

1. **Harness** `eval/run_eval.py`: systems S1/S2/S3/B1/B2, sets `S`, `R`, named subsets, `--repeats`, bounded concurrency (4), resumable, cost estimate + confirmation over $25, outputs per EVAL_PLAN §8. Deployable as a Cloud Run Job (`infra/deploy_eval_job.sh`).
2. **Baselines** `eval/baselines.py`: B1, B2, S2 (always-PASS verifier), S3 (no audio / no real-signal spectrum).
3. **Metrics + stats** `eval/metrics.py`, `eval/stats.py`: every metric in EVAL_PLAN §3; Wilson intervals; exact McNemar with discordant counts; Brier + reliability bins; unit tests on hand-built examples (including a case where McNemar is not significant).
4. **Independent checker**: grades S2 and B1 claims with verifier rules but re-executes evidence from `eval/`, never trusting the system's own verdicts.
5. **Run 20** (S-set dev subset, Flash judge). Read every failure by hand; group into categories (prompt, tool, verifier rule, simulator realism, data imperfection mistaken for cause). Propose the smallest fix per category, apply, rerun only the failures. Never touch S051–S060 or the R-set while tuning.
6. **Final runs**: S1 (Pro judge if the ledger allows) on S+R; S2, B1, B2 on S+R; variance subset ×3 with the Flash judge; S3 only if budget remains.
7. **Report** `eval/report.py` → slide PNG (S-set table, R-set table, CI whiskers, footnote text from EVAL_PLAN §8) + README markdown table + `calibration.csv`. Commit the run directory (no raw data) and truth files.
8. **Manual baseline kit**: the plain debug dashboard view and a timing sheet (`eval/manual_baseline.md`) I'll use with 2–3 outside volunteers.

Exit criterion: committed results for S1/S2/B1/B2 on both sets with intervals and the McNemar result, variance numbers, slide PNG readable at slide size, total eval spend reported against the ledger. If S1 doesn't beat B1 on S-set top-1 or unsupported-claim rate, or if the R-set result is poor, stop and tell me plainly with the failure analysis — don't dress it up.
