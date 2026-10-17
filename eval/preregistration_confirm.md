# Pre-registration: C-set confirmation run (2026-10-17)

Written and committed **before any system has been run on C001–C010**. Nobody has seen an agent, baseline or tool output on these scenarios. The only C outputs that exist so far are the simulator's own files and the sanity plots (`docs/data_inspection/confirm_set.md`).

## 1. Why this run exists

ADR-026's addendum fixed R002 after the fact: judge v7 adds "sustained compressor loading is the physical correlate of an air leak". The post-hoc S1 numbers (`final_v3_posthoc`, R 0.82) were measured on the same R-set that motivated the fix. This run measures the deployed agent on real-signal scenarios it has never seen, built under the same rules (ADR-018).

**What the set can and cannot confirm.** MetroPT-3 has exactly four failure reports, and R001–R004 use all of them. The USE list therefore holds **no new labelled air leak**, and the C-set cannot re-test the *sensitivity* of the v7 rule. It can test (a) that v7 does not create false air-leak calls on healthy compressor windows, three of which stop on air-sounding glitches, and (b) general accuracy and grounding on unseen real segments. Every fault in the set is a UCI hydraulic condition. All five are 10-minute faults with mean shifts under 1 %, the same profile as R009–R011, which every system missed (ADR-026). That limit comes from what the sources contain, not from a choice made here (section 2).

## 2. The set (frozen)

`uv run python -m simulator.real_signals --set C --out data/scenarios` builds the set with seed 2026 (scenario seed 2026·1000 + 200 + n). It follows the ADR-018 rules unchanged. Truth comes only from the sources' own labels (`truth_source: source_label`). Agent-visible files carry no labels: the UCI condition labels, the MIMII folder and the MetroPT source dates are withheld, exactly as for the R-set. IDs are a seeded shuffle. The construction rules, written before generation and not chosen by looking at outputs, are:

* **MetroPT-3 no_fault:** one normal window per free interval left by R001–R008 and the unlabelled continuous-load episodes. Each stop is at least 3 weeks from any reported failure. No source row is shared with any R window. The history is 7 days, or shorter where the interval is (minimum 4.9 d). Stops follow the R005–R008 benign mix (3 weld-air low-low spikes, 1 fieldbus timeout, 1 light-curtain trip).
* **UCI hydraulic_degradation:** every stable single-component condition in `profile.txt` that R009–R012 did not use, run once (10 cycles) up to the stop. The onset is the first labelled cycle. Cooler 20 % is excluded because the splice would be an unphysical ~9 °C step (the ADR-018 cooler rule).
* **IMS:** none. Bearing 1 is fully used by R015–R017, the other channels need a `spectrum()` change, and other test sets are outside the "one test set only" rule.

| ID | Source | Truth class | Detail (source label) |
|---|---|---|---|
| C001 | MetroPT-3 normal window | no_fault | benign stop: weld-air sensor spike ST20 |
| C002 | UCI hydraulic | hydraulic_degradation @ ST10-PRS | accumulator_slightly_reduced |
| C003 | UCI hydraulic | hydraulic_degradation @ ST10-PRS | valve_small_lag |
| C004 | MetroPT-3 normal window | no_fault | benign stop: fieldbus timeout ST30 |
| C005 | UCI hydraulic | hydraulic_degradation @ ST10-PRS | valve_close_to_total_failure |
| C006 | MetroPT-3 normal window | no_fault | benign stop: weld-air sensor spike ST20 |
| C007 | UCI hydraulic | hydraulic_degradation @ ST10-PRS | accumulator_severely_reduced |
| C008 | MetroPT-3 normal window | no_fault | benign stop: weld-air sensor spike ST30 |
| C009 | UCI hydraulic | hydraulic_degradation @ ST10-PRS | pump_leakage_weak |
| C010 | MetroPT-3 normal window | no_fault | benign stop: light curtain ST20 |

**Class counts:** no_fault 5 (all MetroPT-3), hydraulic_degradation 5 (all UCI), n = 10. For comparison, the R-set has 7 no_fault and 10 fault out of 17.

**Data fingerprints (SHA-256).** The generator is deterministic: a rerun was byte-identical. Any later change to these files means the set is no longer this pre-registered set.

| ID | truth.json | telemetry.parquet |
|---|---|---|
| C001 | `26bba3e24c108554f5eabe6921b7a88e9b272ab0da12200ae0611ed9337f5894` | `7c33b6cd8ec1298b0e9b61b57e25b5472c8c0e364949bfb9242f4386c0b5f763` |
| C002 | `d6f728c78c96ee651adafa514b292abf0d0874dd3606db4e2bd3c48906b16155` | `11224f8cf3147d46b95ddd208decd4c360125a55ed8028a66aa57289a1616182` |
| C003 | `e8650dac7dbd8ffca3a65ddc1597e3999e1fa101551b5350275be0340ee0cdca` | `feb694302c1f3eb9f116922639929b2035ce50a806b00e73fdbe3b01958d5f1f` |
| C004 | `65acf3d13744a89b8be3aea19490043ff5ec4abc62cab2ea5c8cd533f1d7d8eb` | `197afe13a0ff2b111b557b86ff85c590a2d5c3908698604288951b98cc4462c0` |
| C005 | `9ca234ccc3301a63f7295e50684be0b8d439181704d068bfe3ed00db4e965621` | `111117653455008a254551baa75ca290178ebe7a660bbe0e8f6aba0cd337dc3b` |
| C006 | `2f74ed0285a5d061d5b4e3283081083c61aed5ce5053bc4e81a06ea56b1c49c3` | `563a9d9b3e6111f41d89fce0c986295f8edd957c31fd119c950b45aa79ecd6cf` |
| C007 | `e83f19e1b769bb0e732ea0618e363e0fe88c47bfa625a0b1804be2455a96a3b3` | `c6f74f0cb632ae992917318aff83e1ea94010cac28a90341f6274cd768277c39` |
| C008 | `b84e108317846de4082d51729ef53156f20ce16c127175d8cad9510b071eda2a` | `6bedeadbbb1a1318ed106110199f00df716b644eece1574c1c08db09621cf0d4` |
| C009 | `88c0e4bbe0719afe110b514c908e12ab4e76dc3520dae1c5e22340dffabf54e9` | `ef32deda9000717e987d9ebec1b67974a1fb11558cde1aa4d3a9a12152a0f36c` |
| C010 | `048ff0b215dc4c0e5d99cb731ec081b778371bfa7a0d85631d6d3c8ac3b515a2` | `f640729e22cc0d836ac7e36f16493a672c8f423936b6ae18e64fb4f6a6d0e959` |

## 3. Systems

* **S1, the deployed agent:** the full graph with the Flash judge (`config.JUDGE_MODEL`, judge prompt v7). The code under test is `agents/`, `analytics/`, `config.py` and `agents/prompts/`, byte-identical to the deployed build (`/health` git_sha `6f6ea10`). Run it from a clean checkout where `git diff --quiet 6f6ea10 -- agents analytics config.py` holds. Uncommitted or later changes to those paths (for example the short-fault detection work in progress) are **not** S1 for this run.
* **B1:** fixed tool battery plus one Flash call, from the same checkout.
* **B2:** classical, no LLM, from the same checkout.

Each system gets one repeat on all 10 scenarios, at concurrency ≤ 2 (ADR-031). Only infrastructure errors (429, model unavailable) are retried, by resuming the same `--out`. Agent errors and timeouts count as misses (ADR-026). C audio clips must be in GCS before the run so that `listen` works as it does on the R-set.

## 4. Metrics and analysis

* **Primary:** top-1 accuracy (top hypothesis has the right cause class AND the right asset; for no_fault truth only the class must match), as graded by `eval/report.py` / `eval/metrics.py`.
* **Secondary:** the unsupported-claim rate, from claims re-checked independently by `eval/checker.py` (pooled, plus the run-level rate).
* **Intervals:** 95 % Wilson intervals for each rate.
* **Paired test:** exact two-sided McNemar on top-1 discordant pairs, S1 vs B1 (and S1 vs B2, reported). With n = 10, p < 0.05 needs at least 6 discordant pairs all in one direction. A non-significant result is reported as "no evidence of a difference", never as "S1 is better".
* **Pre-registered strata (descriptive, no bar):** (a) MetroPT-3 no_fault correct, out of 5, per system. (b) The number of those 5 where the system's top-1 is `air_pressure_drop`. This is the direct check of whether v7 over-fires. (c) UCI hydraulic hits, out of 5, per system.

## 5. Pass bars (decided now)

1. **P1:** S1 top-1 ≥ 0.53, the lower Wilson bound of S1's R-set top-1 in `final_v2` (0.76 [0.53, 0.90]). With n = 10 this needs at least 6/10.
2. **P2:** S1 top-1 ≥ B1 top-1 (point estimates; a tie passes).
3. **Secondary bar S:** S1's pooled unsupported-claim rate ≤ 2 % and below B1's.

**Prediction, written before the run.** The no_fault side looks like R005–R008: loading in the last 4 h is at most 0.22, against at least 0.92 for every real leak. The UCI side looks like R009–R011. If the agent behaves as it did on the R-set, S1 scores about 5/10. **P1 then fails** unless at least one 10-minute UCI fault is found. That outcome would mean "consistent with the R-set on the comparable strata", and it is reported as a fail of P1 all the same.

## 6. Rules

* Results are reported whatever they are, in `eval/results/confirm_c_v1/` and as a dated addendum to ADR-026, including a failed P1/P2 and every error.
* No change after seeing results: not to the set, truth, scenarios, systems, prompts, code, metrics, bars or analysis. Any later fix is post-hoc and is always labelled as such, as for `final_v3_posthoc`. The C-set is never used for tuning: `--purpose dev` refuses it, as it refuses held-out scenarios.
* Amendments to this file are allowed only before the first C run, as a separate dated commit with the reason.
* No C scenario is opened in the UI, replayed or run live before the confirmatory run. C is not published to the live serving prefix before the run, because the public catalogue would list it.
* Contamination caveat (as for R): provenance names MetroPT-3 rows and UCI cycles, so a model could recognise the public datasets.

## 7. Command

After applying the C-set registry patch to `eval/` (`sets.C`) and uploading the C audio clips, run from the clean checkout:

```bash
uv run python -m eval.run_eval --systems S1,B1,B2 --sets C --purpose final --repeats 1 \
  --concurrency 2 --out eval/results/confirm_c_v1
```

Estimated cost: $2.12 (S1 $1.21, B1 $0.91, B2 $0). The ledger then stands at $88.22 of $110 for eval.

## Results (appended 2026-10-17 after the single confirmatory run; nothing above was changed)
Run `eval/results/confirm_c_v1` (S1 = deployed build 6f6ea10, B1, B2; concurrency 2; $2.34).
| | S1 | B1 | B2 |
|---|---|---|---|
| Top-1 [95% Wilson] | 0.40 [0.17, 0.69] | 0.20 [0.06, 0.51] | 0.00 [0.00, 0.28] |
| Top-3 | 0.90 | 0.70 | 0.00 |
| Unsupported claims | 0 / 80 | 6 / 91 | n/a |
- **P1 (S1 top-1 ≥ 0.53): FAIL.** **P2 (S1 ≥ B1): PASS** (2 discordant for S1, 0 for B1; exact McNemar p = 0.50, not significant). **Secondary (≤ 2% and below B1): PASS.**
- Strata: healthy compressor windows 4/5 correct for S1 (C001 called air_pressure_drop at ST20-WLD; none called a UT-AIR leak); short UCI hydraulic faults 0/5 for S1 and B1 (as predicted above).
- Reading: judge v7 did not turn healthy compressors into UT-AIR leak calls on unseen data; the short-fault weakness is confirmed on unseen data. Any later detector change makes further C results post-hoc.
