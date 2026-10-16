# C-set inspection: pre-registered confirmation set C001–C010

Built by `uv run python -m simulator.real_signals --set C --out data/scenarios` (seed 2026; scenario seed = 2026·1000 + 200 + n). The rules are the R-set's (ADR-018), unchanged. The pre-registration is `eval/preregistration_confirm.md`. These are real signals mapped onto a synthetic line, not plant data. The plots below are the sanity plots, rendered from the written files: red = real-mapped, blue = synthetic coupled to it, dashed = onset from the source label, purple = stop. This page shows truth. It is for people only: the agent never reads `docs/`.

## Why these segments (and what was left out)

**R001–R017 use these source segments** (none are reused in C, except the UCI healthy background noted below):

| R | Source segment |
|---|---|
| R001–R004 | MetroPT-3 failure reports #1–#4 (04-18, 05-29/30, 06-05/07, 07-15). Each window is the 7 days up to the hold rule / weld-air alarm inside the report window. |
| R005–R008 | MetroPT-3 normal windows: the 7 days before 02-20 10:15, 03-25 14:40, 08-10 11:30 and 08-26 16:20. |
| R009–R012 | UCI cycles 1705–1714 (pump leakage 2), 1767–1776 (valve 80 %), 2186–2204 (accumulator 90 bar), 0–209 + 323–332 (cooler 3 %, with warm-up). |
| R009–R014 | UCI healthy background 1787–1796, looped. These are the rig's only stable all-optimal cycles. |
| R015–R017 | IMS test 2, bearing 1, every live snapshot (02-12 10:32 to the end of the test). |

**What the C-set takes:**

* **MetroPT-3, 5 no_fault windows.** There is one window per free interval left between R001–R008 and the unlabelled continuous-load episodes. Each stop is at least 3 weeks from any reported failure. The history is 7 days, or starts at the interval floor where the interval is shorter (C001 4.9 d, C008 5.9 d), the same way R015's history starts at the first IMS snapshot. Code masks every source row before the history start, including the 8 h physics pre-buffer. The Mar 11 afternoon is avoided: it has 8 h of gaps, then low pressure leading into the Mar 12 episode. The stops copy the R005–R008 mix, with one more air-sounding glitch: 3 weld-air low-low spikes, 1 fieldbus timeout and 1 light-curtain trip.
* **UCI, 5 hydraulic_degradation conditions.** These are every stable single-component condition in `profile.txt` that R did not use, run once (10 cycles = 10 min) up to the stop. The onset is the first labelled cycle. Cooler 20 % (cycles 1055–1064) is excluded: its oil runs about 9 °C hotter than the healthy cycles and no single-component warm-up leads into it, so the splice would be an unphysical step (the same reason R012 uses the cooler-3 % warm-up). The looped healthy background is the same as R009–R014's (ADR-018 rule 3). This shared background is the only source data C shares with R. `tests/test_confirm_set.py` checks this from both sets' provenance.
* **Not available.** MetroPT-3 has exactly 4 failure reports, all used by R001–R004, so the C-set has **no new labelled air leak**. IMS bearing 1 is fully used by R015–R017. Its other channels would need `spectrum()` to read a channel other than 1, because `agents/tools.py` hard-codes bearing 1. IMS tests 1 and 3 are outside the "one test set only" rule in `docs/DATA_SOURCES.md`.
* **IDs are a seeded shuffle**, so an ID does not leak its class. Shift notes are the fixed templates: the run made no Flash-Lite call ($0). R-set notes were written by Flash-Lite. Both are written from the stop text only.

## Per scenario

| ID | Source segment (source clock) | Truth (source label) | Stop | History | Plot |
|---|---|---|---|---|---|
| C001 | MetroPT-3, 08-26 18:20 → 08-31 16:40 | no_fault | S-ST20-AIR-LL (2 s spike) | 4.9 d | [C001](confirm_set/C001.png) |
| C002 | UCI cycles 1920–1929 after healthy loop | hydraulic_degradation · accumulator_slightly_reduced (115 bar) | S-ST10-HYD-FLT | 7 d | [C002](confirm_set/C002.png) |
| C003 | UCI cycles 1777–1786 | hydraulic_degradation · valve_small_lag (90 %) | S-ST10-HYD-FLT | 7 d | [C003](confirm_set/C003.png) |
| C004 | MetroPT-3, 03-03 16:45 → 03-10 16:45 | no_fault | S-ST30-COMM-TO | 7 d | [C004](confirm_set/C004.png) |
| C005 | UCI cycles 1757–1766 | hydraulic_degradation · valve_close_to_total_failure (73 %) | S-ST10-HYD-FLT | 7 d | [C005](confirm_set/C005.png) |
| C006 | MetroPT-3, 02-06 08:20 → 02-13 08:20 | no_fault | S-ST20-AIR-LL (2 s spike) | 7 d | [C006](confirm_set/C006.png) |
| C007 | UCI cycles 2053–2062 | hydraulic_degradation · accumulator_severely_reduced (100 bar) | S-ST10-HYD-FLT | 7 d | [C007](confirm_set/C007.png) |
| C008 | MetroPT-3, 03-12 14:00 → 03-18 12:30 | no_fault | S-ST30-AIR-LL (2 s spike) | 5.9 d | [C008](confirm_set/C008.png) |
| C009 | UCI cycles 1746–1755 | hydraulic_degradation · pump_leakage_weak (1) | S-ST10-HYD-FLT | 7 d | [C009](confirm_set/C009.png) |
| C010 | MetroPT-3, 08-12 14:10 → 08-19 14:10 | no_fault | S-ST20-LC-TRIP | 7 d | [C010](confirm_set/C010.png) |

### MetroPT-3 windows: compressor duty vs the R-set

"Loaded" means compressor current above 55.2 A (the source's 4.8 A, the hold-rule threshold). Coverage is the fraction of history seconds that have a real 1 Hz row. Gaps are recorded `source_gap` imperfections. Transients are restart dips under 3 min (`source_transient`).

| ID | Coverage | Gaps (longest) | Transients | Loaded: all / last 24 h / last 4 h | Header mean: all / last 24 h (bar) |
|---|---|---|---|---|---|
| C001 | 0.88 | 8 (3.8 h) | 0 | 0.13 / 0.13 / 0.13 | 6.79 / 6.79 |
| C004 | 0.86 | 12 (8.2 h) | 1 | 0.15 / 0.15 / 0.20 | 6.82 / 6.82 |
| C006 | 0.86 | 14 (4.7 h) | 0 | 0.07 / 0.06 / 0.08 | 6.73 / 6.72 |
| C008 | 0.83 | 15 (7.3 h) | 2 | 0.09 / 0.06 / 0.06 | 6.75 / 6.74 |
| C010 | 0.89 | 12 (7.3 h) | 0 | 0.12 / 0.14 / 0.22 | 6.77 / 6.78 |
| *R005–R008 (no_fault)* | 0.72–0.92 | 7–11 | 0–4 | 0.05–0.14 / 0.05–0.12 / 0.05–0.13 | 6.72–6.79 |
| *R001–R004 (air leak)* | 0.74–0.90 | 10–15 | 0–5 | 0.13–0.21 / 0.17–0.47 / **0.92–0.95** | 6.60–6.75 / 6.46–6.78 |

The C windows look like R005–R008: the hold rule never fires (a test checks this against the CSV), and loading in the last 4 h is at most 0.22, where every real leak is at or above 0.92. A judge that reads "sustained loading" correctly (judge v7) should call them no_fault. The C-set can only show false positives of the v7 rule. It cannot show its sensitivity (see above).

### UCI conditions: how visible the fault is at 1 Hz

The table gives the change of the fault cycles against the hour before onset, in %, for the mean and (in brackets) the per-second standard deviation.

| ID | Condition | Pressure | Motor current | Oil temp | Vibration |
|---|---|---|---|---|---|
| C002 | accumulator 115 bar | −0.02 (+0.3) | +0.27 (+0.1) | +0.10 (+8.5) | −3.6 (−7.9) |
| C003 | valve 90 % | +0.02 (+0.4) | +0.22 (+1.2) | −0.11 (−4.8) | −0.6 (−12.7) |
| C005 | valve 73 % | +0.09 (+1.7) | +0.18 (+0.9) | −0.39 (+7.7) | −0.3 (−5.0) |
| C007 | accumulator 100 bar | −0.01 (+0.4) | +0.17 (−0.0) | −0.34 (+5.7) | −1.3 (−10.7) |
| C009 | pump leakage 1 | −0.12 (+0.3) | +0.67 (+0.0) | −0.63 (+4.0) | −0.2 (+4.7) |
| *R009 / R010 / R011* | pump 2 / valve 80 % / accumulator 90 bar | −0.18 / +0.06 / +0.08 | +1.70 / +0.18 / +0.45 | −1.2 / −0.2 / −2.0 | −3.0 / −0.5 / −0.6 |

All five are 10-minute faults with shifts under 1 % of the mean. Every system missed R009–R011, which have the same profile (ADR-026). Expect them to be hard. The C-set's fault side is dominated by the hardest real class, and that is why the pre-registration reports the two strata separately.

## Checks (tests/test_confirm_set.py)

Provenance exists for every real segment (the R test is reused). No row is interpolated across a source gap. The rescale is the R-set's fixed per-tag map. Truth comes only from the source labels (UCI `profile.txt` labels are re-checked against the raw file). No C source row appears in any R scenario. No source row precedes the history floor. The agent-visible files carry no cause class, no UCI label text, no condition name and no source date. Partition keys and GCS ids accept `C`. Generation is deterministic: a second run was byte-identical for all 10 scenarios, and R001–R017 regenerate unchanged.
