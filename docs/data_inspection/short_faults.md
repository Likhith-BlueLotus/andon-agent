# Short faults before a stop: why the detector missed them, and the fix (ADR-033)

2026-10-17 · data/ML · offline, deterministic, no LLM, $0.

## 1. What every system missed

UCI hydraulic R009–R011 (and the C-set's five unused UCI conditions) are 10–19 min faults right
before the stop, with level shifts of 0.2–3 % (ADR-018). In `eval/results/final_v2` the analyst
called `detect_change_points` on ST10-PRS with 1 h and 24 h windows ending at the stop. Every
call returned `n_change_points: 0`, and S1, S2 and B1 all answered `no_fault`.

## 2. Root cause (signal level)

Running the detector stage by stage on those exact windows:

| check | finding |
|---|---|
| bin size | not it: 60 s bins on 1 h and 24 h windows (10–19 fault bins). Only 7-day windows use 600 s bins. |
| changeover mask | not it: no changeover bin overlaps the faults. |
| data gaps | not it: ST10 has < 2 % missing, no gap in the last hour. |
| PELT | finds the step; then **`merge_small` removes it**. |
| `min_effect` | `0.08 × normal span` = 2.4 bar / 1.28 A / 1.6 °C / 0.28 mm/s. The faults: −0.4 bar, +0.7 A, −0.5 °C, −0.07 mm/s (R009); −0.9 °C (R011). That is 10–30 bin-sigmas, but 15–60 % of the floor. |

The physical floor is right for what it was calibrated for: multi-day windows with daily patterns
and recipe steps, where clean windows must return ≤ 1 change point. Structurally, though, it
cannot report a 0.3–6 % step that lasts 10 minutes. R010 (valve lag) is a second, different
case: the 1-min level does not move at all (the fault changes the shape within each cycle), so
no level detector sees it.

## 3. Fix: an end-anchored short-shift scan, reported alongside

`analytics.changepoints.short_shift`, returned as `detect_change_points.summary.short_shift`.
It is an additive key. `change_points`, `n_change_points` and every other key are unchanged:
on 5,400 S-set tool outputs (60 scenarios × every tag × 1 h / 24 h / 7 d windows),
the output equals the previous detector's byte for byte apart from the new key.

* **Question asked:** do the last *L* minutes of the window (L = 5…60 min) sit at a different
  level from the ≤ 4 h before? The stop is at the window end, and the fault that stopped the
  line is active there.
* **Signal:** 1-min bins of the tag's robust aggregate. Gaps and changeovers are removed, and
  only data after the last planned changeover is used (no recipe change between baseline and
  tail). The daily pattern is removed with a 5-min profile from whole local days before the
  tested tail, so a fault never enters its own baseline. Only 1-min signals are scanned;
  per-cycle, duty and chiller tags report `not_applicable`.
* **Null:** for each L, the spread of an L-bin mean from the baseline itself: the max of an
  AR(1) long-run-variance model and the empirical spread of rolling L-means. It is inflated if
  the tail is noisier than the baseline (a noise increase is not a level shift).
* **Decision:** max |z| ≥ 8, the shift persists over ≥ 75 % of the tail bins, and
  |delta| ≥ max(1 % of the normal span, 2 × resolution, the tag's own floor). A frozen sensor
  through the tail is marked `data_issue: stuck_value`.
* **Onset:** likelihood-ratio estimate, argmax_L L·(mean_L − μ)².
* **Cost:** +~20 ms per `detect_change_points` call (≈0.10 s vs 0.08 s).

## 4. Validation on a new synthetic dev set (not R, not C)

`uv run python -m simulator.generate --set D --out data/scenarios_dev` writes S101–S112, a
seeded shuffle of 10 short hydraulic faults and 2 ST10 `no_fault` controls (seed 2033, template
text, $0). The faults come from `simulator.faults.short_hydraulic`: onset 10–20 min before the
stop, a log-uniform 0.5–6 % level shift on the subtype's tags with a first-order response, and
the plant's own AR(1) noise. That noise makes these harder than the looped UCI cycles, whose
healthy 1-min medians barely move. The dev set lives in its own directory and DuckDB
(`data/andon_dev.duckdb`) so it never enters the eval sets or the published store.

`uv run python scripts/short_fault_check.py` measures detection on every signature tag, with
windows ending at the stop. *Before* = a change point in the right direction with onset ≥ truth
onset − 15 min. *After* = before, or a `short_shift` in the right direction with the same onset
rule.

| id | subtype | shift | duration | before (1 h / 4 h / 24 h) | after | short_shift found (z) |
|---|---|---|---|---|---|---|
| S101 | cooler loss | 1.36 % | 19 min | – / – / – | ✓ ✓ ✓ | oil_temp +0.45 °C (13.6) |
| S102 | valve lag | 4.83 % | 15 min | – / – / – | ✓ ✓ ✓ | vibration +0.11 mm/s (11.2) |
| S104 | pump leakage | 1.48 % | 12 min | – / ✓ / – | ✓ ✓ ✓ | pressure −2.26 bar (22.1) |
| S105 | cooler loss | 3.04 % | 20 min | – / – / – | ✓ ✓ ✓ | oil_temp +0.99 °C (18.0) |
| S107 | accumulator | 0.87 % | 11 min | – / – / – | – – – | none (max \|z\| 5.7) |
| S108 | accumulator | 5.11 % | 14 min | ✓ / ✓ / ✓ | ✓ ✓ ✓ | motor current +2.15 A (21.3) |
| S109 | pump leakage | 1.23 % | 13 min | – / – / – | ✓ ✓ ✓ | pressure −2.03 bar (17.2) |
| S110 | accumulator | 2.14 % | 17 min | – / – / – | ✓ ✓ ✓ | motor current +0.94 A (15.6) |
| S111 | valve lag | 1.08 % | 16 min | – / – / – | – – – | none (max \|z\| 1.7): 0.024 mm/s is below the noise |
| S112 | pump leakage | 1.80 % | 13 min | – / – / – | – – – | `insufficient_data`: the fault lies inside the 14:00 changeover + restart window, which both detectors exclude |
| **total** | | | | **1 / 2 / 1 of 10** | **7 / 7 / 7 of 10** | |

Onsets of the found shifts are within 0–2 min of truth for step-like faults. For the cooler
they are within 3–5 min, because the tank temperature rises with a 10-min time constant.

Threshold: z_min = 8 was set in the design before any measurement. The sweep shows a plateau,
with detection 7/10 for z_min 6–10 and 8/10 for 4–5. The highest z on any healthy window is
5.3, so 8 keeps a margin.

## 5. False positives (healthy windows)

The same analytics call is made on every tag of every asset, with 1 h / 4 h / 24 h windows.

| healthy set | tag-windows | short_shift found (z ≥ 8) | before |
|---|---|---|---|
| S-set: all 10 `no_fault` at the stop + 50 fault scenarios ending 1 h before the earliest abnormality (primary/secondary onset, herring noise) | 5,400 | **0 (0.00 %)** | key did not exist |
| S-set fault scenarios at the stop, assets with no part in any fault | 2,652 | **0 (0.00 %)** | – |
| dev `no_fault` S103, S106 at the stop | 180 | **0** | – |

`change_points` false positives are unchanged by construction: identical output (section 3).

Two artefacts were found and fixed during calibration. They are kept here because they are the
kind of thing that would bite again.

1. **Daily profile cut mid-day.** A profile ending at the tail start mixes 7-day medians before
   the cut with 6-day medians after it; pandas averages the two middle values of an even count.
   On ST10 pressure, whose setpoint follows the product model (180 / 190 bar by shift), that
   alone produced a fake +4.8 bar step at z = 52 (S025 healthy window). Fix: build the profile
   from whole local days. Regression test: `test_setpoint_by_product_model_is_not_a_short_shift`,
   which fails on the old cut.
2. **Per-cycle tags.** Letting 5-min-bin tags in made the scan report real but off-chain
   cycle-time rises (a derating weld cell slows ST60 through the buffers, below the truth's
   4 s chain threshold): 9 tag-windows at z ≥ 8. These would mislead causal ordering, so
   coarse-bin tags are out of scope (`not_applicable`).

## 6. Post-hoc look at R009–R014 (parameters frozen before this; not used to tune)

Tool level, 1 h and 24 h windows ending at the stop, ST10 continuous tags:

| id | truth | short_shift |
|---|---|---|
| R009 | pump leakage, 10 min | found on all 4 tags, onset = source onset (07:26:36): current +0.69 A (z 32), oil −0.5 °C (z −32), pressure −0.38 bar (z −24), vibration −0.07 (z −16) |
| R010 | valve lag, 10 min | none (max \|z\| ≤ 5.7): the level does not move (section 2) |
| R011 | accumulator, 19 min | found on oil_temp −0.9 °C (z −78), onset = source onset (07:20:49); pressure/current z 11–15 but not persistent over the tail |
| R012 | cooler, 3.7 h | none (outside the 60 min scan); PELT reports oil/current/vibration changes on 24 h windows as before |
| R013 | no_fault | `insufficient_data` (stop 23 min after a changeover) |
| R014 | no_fault | none |

Whether this changes the agent's diagnosis is a separate question: the analyst must read
`short_shift`, and the verifier/premise checks still use only `change_points` (section 7). The
eval reruns answer it.

## 7. Limits

* **Dev set:** 10 faults is small. Detection depends on shift / noise: ≤ 1 % shifts on noisy
  tags (S107, S111) stay below the noise. Faults inside a changeover are invisible by design.
* **R010-like faults** (shape within a cycle, no level change) need a dispersion or within-cycle
  feature. Not done.
* **Anchored at the window end:** a short fault that ended well before the window end is still
  only PELT's job.
* **Agent integration:** the analyst prompt (not owned by data) does not mention `short_shift`
  yet. The tool docstring (model-facing) does. `premise_check` and the verifier's causal-order
  rule read only `change_points`, so a claim built on `short_shift` is checked numerically (path
  lookup) but not by the causal-order rule.
