# Eval plan

The eval is the strongest evidence in the submission. It must be honest, reproducible, statistically sane for small n, and cheap.

## 1. Systems
| ID | System |
|---|---|
| S1 | Full Andon Agent (Pro judge) |
| S2 | S1 with the verifier replaced by an always-PASS stub (ablation: what does verification buy?) |
| S3 | S1 without `listen()` and without real-signal-aware `spectrum` (ablation: what does multimodality buy?) — run only on scenarios with an audio/vibration signature; skip if budget is tight |
| B1 | Naive long-context: one `gemini-3.8-flash` call with telemetry summaries, alarms, notes, WOs and manuals stuffed in; same output schema; no tools, no verifier |
| B2 | Classical: max anomaly-score station in the window + most frequent historical fault class for that asset type |

## 2. Scenario sets
| Set | Size | Ground truth | Purpose |
|---|---|---|---|
| S-set dev | S001–S050 | injected | Development; prompt tuning allowed |
| S-set held-out | S051–S060 | injected | Generalisation; **no tuning, ever** |
| R-set | R001–R017 | **from the source dataset** (failure reports, rig labels, readme) | "Does it work on real signals?" — the answer to the judges' first question |

Report every metric per set. Never merge the R-set into a headline number with the S-set.

## 3. Metrics (`eval/metrics.py`)
| Metric | Definition |
|---|---|
| Top-1 accuracy | top hypothesis `cause_class` AND `asset_id` match truth |
| Top-3 accuracy | truth appears in any of the ≤3 hypotheses |
| Causal-chain F1 | set F1 between predicted and truth chain (asset level) |
| Abstention precision / recall | on `no_fault` scenarios: answered `no_fault`/`sensor_drift`/`insufficient_evidence`; and how often it abstains when there *was* a fault |
| Red-herring robustness | top-1 on `red_herring` variants |
| Imperfection false-alarm rate | share of runs whose top hypothesis blames an injected data imperfection (gap, stuck value, chatter) |
| Unsupported-claim rate | share of claims in the *final* report failing independent re-verification (S1, S2, B1) |
| Verifier catch count | claims rejected during the loop (S1) |
| Calibration | Brier score and a 5-bin reliability table of `confidence` vs correctness (S1, B1) |
| Time to diagnosis | median and p95 wall-clock, `incident_started` → `rca_final` |
| Cost per diagnosis | from the `cost` event |

## 4. Statistics (small n, done properly)
- **95% Wilson intervals** on every accuracy/rate. With n = 60 or 17 the intervals are wide — show them; judges respect honesty more than precision.
- **Paired comparison S1 vs B1 and S1 vs S2:** exact McNemar test on per-scenario top-1 correctness; report the discordant counts (b, c) and p. Don't claim significance you don't have.
- **Run-to-run variance:** LLM outputs vary. Run S1 three times on a fixed 15-scenario subset (S001, S006, … plus 3 R-set) with the Flash judge; report the spread of top-1. If the spread is larger than the S1–B1 gap, say so.
- Seeds, model IDs, prompt versions and git SHA are written into every run's `summary.json`.

## 5. Manual baseline (indicative only)
Plain debug dashboard (raw charts + logs, no agent). Each teammate plus **2–3 outside volunteers** (friends/classmates with an engineering background; no employer data involved) diagnose 3 held-out scenarios each, timed, with a fixed 10-minute cap. Report "n = X people, Y diagnoses, indicative" — never a headline statistic.

## 6. Running
```bash
uv run python -m eval.run_eval --systems S1,S2,B1,B2 --sets S,R --concurrency 4 --out eval/results/$(date +%Y%m%d_%H%M)
uv run python -m eval.run_eval --systems S1 --subset variance15 --repeats 3 --judge flash --out ...
uv run python -m eval.report eval/results/<run> --slide eval/results/<run>/results_slide.png
```
Resumable; cost estimate printed first; confirmation above $25. Prefer the Cloud Run Job for the full run.

## 7. Budget for the eval (fits the ledger in DEVELOPMENT.md §7)
| Run | Approx. runs | Est. cost (assumption: S1 ≈ $0.56 Pro, ≈ $0.30 Flash judge; B1 ≈ $0.10) |
|---|---|---|
| Dev iterations (S001–S020, Flash judge, ~3 passes) | 60 | ~$18 |
| Final S1, Pro judge, S+R sets | 77 | ~$43 |
| S2 ablation (Flash judge) | 77 | ~$23 |
| B1 | 77 | ~$8 |
| Variance (15 × 3, Flash judge) | 45 | ~$14 |
| S3 (only if spare budget) | ~25 | ~$8 |
| **Total** | | **~$106–114** (validate after the first 20 runs; cut S3, then variance repeats to 2, if over) |

## 8. Outputs and the one slide
Each run: `results.jsonl`, `summary.json` (with intervals and tests), `cost.json`, `calibration.csv`, `results_slide.png`.
**Slide:** left — table of S1/S2/B1/B2 × {top-1 [95% CI], top-3, unsupported-claim rate, median time, $/run} for the S-set; a second, smaller table for the R-set ("real signals, n = 17"). Right — top-1 bar chart with CI whiskers, held-out marked. Footnote: "S-set: 60 synthetic scenarios with injected ground truth. R-set: real compressor (MetroPT-3), hydraulic rig (UCI) and bearing (IMS) signals with the source's own labels; surrounding plant context synthetic. Run <id>, <date>."

## 8b. Verifier fault injection (`eval/stress_verifier.py`, ADR-032; offline, $0)
**Why.** The S1-vs-S2 ablation (§1) cannot show what the deterministic verifier is for: the generator rarely makes a checkable error on these prompts, so S2 (verifier always PASS, every claim displayed as verified) matches S1 on top-1 and nearly on unsupported claims. This test injects the errors instead and asks whether code strikes them through.

**Method.** `uv run python -m eval.stress_verifier --run eval/results/final_v2` (seed 2026, local DuckDB, a few minutes, no Gemini). For every S1 run with a report: rebuild the evidence from the run's own tool calls exactly as `eval/checker.py` does and re-execute it against the store (the system's verdicts are never read); grade the unmutated report with `verify_report` (false-alarm rate; equals the checker's verdicts, asserted in the summary). Only claims that pass at baseline are attacked, one fault at a time, whole mutated report re-graded, verdict of the mutated claim read. Caught = `fail` or `unverifiable` (both are struck through in the UI); missed = `pass`.

| Fault | Injection |
|---|---|
| Number off by ±10% / ±25% | `asserted_value` x (1 ± p), beyond the 5% tolerance |
| Number sign flipped | value negated and direction words in the text swapped; skipped where the baseline pass itself relied on the sign relaxation |
| Timestamp shifted | `asserted_ts` ± 15 min / ± 2 h (tolerance 60 s) |
| Quote with one word altered | antonym swap, else number change, else one word replaced |
| Quote on the wrong page | page ± 1 where the quote is absent |
| Quote from another manual | a verbatim sentence of a different manual under the original doc/page |
| Causal order reversed | chain reversed, root = previous last asset |
| Non-existent evidence id | one fabricated numeric, temporal and qualitative claim per run citing `ev_nonexistent_999` |
| Premise-false citation | verbatim passage with measurable premises (`simulator/manuals/premises.py`, read-only), appended as a citation claim, sampled (8 per run, seeded) from passages that diagnose a different cause class than the injected one, whose manual covers neither the true asset/chain nor the asset the report blames. Ground truth is read grader-side only to label this. |

**Outputs.** `eval/results/stress_verifier/{summary.json,table.md,stress.png}`: catch rate per fault with 95% Wilson intervals, n, overall catch rate, false-alarm rate on unmutated claims, and the S2 line ("S2 shows all mutated claims as verified: catch 0%"). Numeric faults are also split into explicit `path:` claims and implicit leaf search.

**Reading it.** This measures the safety net, not how often the model errs. Faults are synthetic, single, and injected into fields the verifier reads; trials are clustered by run (intervals are optimistic). A fault type that is not caught is reported as measured and the verifier is not tuned to it. Misses and `unverifiable` outcomes are listed in `summary.json` (`missed_examples`).

## 9. Integrity rules
- Report whatever is measured, including slices where S1 loses. If S1 doesn't beat B1 on the S-set top-1 or unsupported-claim rate, stop and fix before submission, or say so plainly.
- No tuning on S051–S060 or the R-set. The demo scenario is named in the README.
- If numbers look too good, check for leakage (truth fields in prompts, scenario IDs encoding the cause, red herrings that are too easy) before celebrating.
- Commit truth files and run outputs (minus raw data) to the public repo after the final run.
