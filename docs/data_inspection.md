# Data inspection (Phase 1 Part B)

Inspected 2026-10-11 from the raw files fetched by `scripts/fetch_datasets.py` (hashes in `data/SOURCES.md`). Numbers come from `scripts/inspect_datasets.py` (re-runnable; it also writes one figure per dataset to `docs/data_inspection/`). This page is input to the mappers in `simulator/real_signals.py`. **Nothing here is plant data.** These are real public signals that we will map onto a synthetic line.

Licence check (2026-10-11, page + machine-readable endpoint): every dataset still matches `docs/DATA_SOURCES.md`. MetroPT-3 and UCI hydraulic are CC BY 4.0, IMS is U.S. Government Works (catalog.data.gov), MIMII is CC BY-SA 4.0 (Zenodo API `cc-by-sa-4.0`), and MaintIE is MIT (GitHub API `spdx_id: MIT`). `bosch_cnc` was not fetched (optional).

| ID | On disk | What was fetched |
|---|---|---|
| `metropt3` | 416.5 MiB (zip 218.4 MB + CSV 218.3 MB) | full CSV |
| `uci_hydraulic` | 603.5 MiB (zip + 17 sensor matrices + profile + 2 docs) | full dataset |
| `ims_bearings` | 601.4 MiB (85.6 MB rar + readme + 984 extracted snapshots, 519 MiB) | **test 2 only**, range-extracted from NASA `IMS.zip` (1.07 GB); tests 1 and 3 never downloaded |
| `mimii` | 976.6 MiB (400 wavs) | 6 dB pump/fan/slider/valve wavs only, range-extracted |
| `maintie` | 5.2 MiB | gold + silver JSON + LICENSE at pinned commit `825e771` |

---

## 1. MetroPT-3 (`metropt3`) — figure `data_inspection/metropt3.png`

**File:** `MetroPT3(AirCompressor).csv`, 1,516,948 rows × 17 columns (unnamed `index`, `timestamp`, 7 analogue, 8 digital). Span **2020-02-01 00:00:00 → 2020-09-01 03:59:50**. The page says "February to August", but the data runs 4 h into September.

**Sampling rate (inferred):** **0.1 Hz with jitter.** The `index` column steps by exactly 10 on every row (100%). Consecutive timestamps are 10 s apart for 88.2% of rows, with 9 s (128k rows), 12 s (38k), 13 s (8k) and 11 s (4k) for the rest. So the logger ran at 1 Hz and the published file keeps every 10th sample. The page's "logged at 1Hz" describes the logger; "collected at 0.1Hz" describes this file. Timestamps never go backwards and none are duplicated.

**Gaps:** 331 gaps longer than 60 s, totalling **909.5 h** (about 18% of the span). Most are overnight (the train is parked). The largest is 48 h after 2020-04-25 01:10. The longest gap-free stretch is 4.2 days (2020-03-24 04:03 → 03-28 08:49). **A 7-day scenario history from MetroPT-3 will always contain real gaps.** Keep them, and record them in `truth.imperfections` as source gaps so they are never blamed.

**Columns used (units from the page; ranges from data: min / p1 / median / p99 / max):**

| Column | Unit | Range | Notes |
|---|---|---|---|
| TP2 | bar | −0.03 / −0.02 / −0.01 / 10.35 / 10.68 | compressor outlet; ≈0 when unloaded, so it reads like a duty-cycle signal |
| TP3 | bar | 0.73 / 7.88 / 8.96 / 10.14 / 10.30 | pneumatic panel: **best header-pressure analogue** (normal sawtooth ≈8–10 bar) |
| H1 | bar | −0.04 / −0.02 / 8.78 / 10.11 / 10.29 | |
| DV_pressure | bar | −0.03 / −0.03 / −0.02 / 2.11 / 9.84 | |
| Reservoirs | bar | 0.71 / 7.88 / 8.96 / 10.14 / 10.30 | tracks TP3 closely |
| Oil_temperature | °C (page writes "0C") | 15.4 / 48.8 / 62.7 / 76.2 / 89.1 | |
| Motor_current | A | 0.02 / 0.04 / 0.05 / 6.19 / 9.30 | ≈0 off, ≈4 unloaded, ≈6–7 loaded, ≈9 at start; motor on (>1 A) 45% of the time |
| COMP, DV_eletric, Towers, MPG, LPS, Pressure_switch, Oil_level, Caudal_impulses | 0/1 | {0,1} | digital. The column is spelled `DV_eletric` (sic). LPS (pressure < 7 bar) is active 0.34% of the time overall |

**Failure-report table (from the page), deduplicated.** The page labels both of the first two rows "#1". They are different events by time, so the second is renumbered #2. Times are as written by the operator, on the same clock as the CSV `timestamp`; no timezone is stated.

| # | Start | End | Failure | Severity | Page note | Rows in window (expected @0.1 Hz) | CSV `index` range |
|---|---|---|---|---|---|---|---|
| 1 | 2020-04-18 00:00 | 2020-04-18 23:59 | Air leak | High stress | — | 8,657 (8,635) | 5,625,640–5,712,200 |
| 2 (page "#1") | 2020-05-29 23:30 | 2020-05-30 06:00 | Air Leak | High stress | "Maintenance on 30Apr at 12:00" | 2,360 (2,341) | 8,407,400–8,430,990 |
| 3 | 2020-06-05 10:00 | 2020-06-07 14:30 | Air Leak | High stress | "Maintenance on 8Jun at 16:00" | 17,315 (18,901) | 8,908,100–9,081,240 |
| 4 | 2020-07-15 14:30 | 2020-07-15 19:00 | Air Leak | High stress | "Maintenance on 16Jul at 00:00" | 1,622 (1,621) | 11,710,930–11,727,140 |

What the data shows inside each window, compared with the preceding 24 h:

| # | TP3 mean (window vs pre-24 h) | TP3 min | Motor on share (window vs pre) | LPS share (window vs pre) |
|---|---|---|---|---|
| 1 | 8.81 vs 8.47 | 8.04 | 0.99 vs 0.10 | 0 vs 0.003 |
| 2 | 8.40 vs 9.02 | 8.06 | 1.00 vs 0.49 | 0 vs 0 |
| 3 | 8.02 vs 9.02 | 2.82 | 1.00 vs 0.40 | 0.011 vs 0 |
| 4 | 8.21 vs 9.11 | 5.93 | 1.00 vs 0.96 | 0.33 vs 0.001 |

**Takeaways for the `air_pressure_drop` mapping:**
- The consistent leak signature is **compressor duty**: the motor runs non-stop, and the normal load/unload sawtooth disappears (see the zoom on #4 in the figure). Mean header pressure drops by 0.6–1.0 bar in #2–#4, and TP3 slides from 10 to 6 bar in #4.
- #1 is subtle: its mean pressure is *higher* than the previous day, and only the duty cycle gives it away. A pressure-only detector would miss #1, so map `compressor_current_a` as well as `header_pressure_bar`.
- In the figure, oil temperature also rises during #3 and #4.

**Oddities:**
- Report #2's note says "Maintenance on 30Apr", a month *before* the failure. This is probably a typo for 30 May. Keep the source text verbatim in provenance and don't "fix" it in truth.
- Window #3 contains a 3.8 h gap (after 2020-06-06 15:55:17), and a 21.5 h gap starts 11 min before its end (2020-06-07 14:19:39).
- Window #1 has a 6 min gap at 00:18. Window #4 has a 2 min gap at 17:22.
- Raw TP3 dips below 1 bar are very short (hourly minimum only). They happen outside the failure windows and look like compressor-off/start transients, not leaks. They are good red-herring material.

---

## 2. UCI hydraulic (`uci_hydraulic`) — figure `data_inspection/uci_hydraulic.png`

**Files:** 17 tab-separated matrices with rows = 2,205 cycles of 60 s, plus `profile.txt` (labels). Shapes were verified: PS1–6 and EPS1 are 2205×6000 (100 Hz), FS1/FS2 are 2205×600 (10 Hz), and TS1–4, VS1, CE, CP, SE are 2205×60 (1 Hz). The rates on the page are correct.

| Sensor | Unit | Hz | min / median / max |
|---|---|---|---|
| PS1 | bar | 100 | 133.1 / 153.9 / 191.9 |
| PS2 | bar | 100 | 0 / 125.7 / 167.8 |
| PS3 | bar | 100 | 0 / 2.05 / 18.8 |
| PS4 | bar | 100 | 0 / 0 / 10.3 |
| PS5 / PS6 | bar | 100 | 8.3 / 9.1 / 10.0 |
| EPS1 | W | 100 | 2098 / 2426 / 2995 |
| FS1 | l/min | 10 | 0 / 7.64 / 20.5 |
| FS2 | l/min | 10 | 8.76 / 9.69 / 10.45 |
| TS1–TS4 | °C | 1 | 30.4 / ~45 / 62.2 |
| VS1 | mm/s | 1 | 0.48 / 0.60 / 2.55 |
| CE | % | 1 | 17.0 / 27.3 / 48.8 |
| CP | kW | 1 | 1.02 / 1.74 / 2.91 |
| SE | % | 1 | 0 / 67.1 / 100.6 |

**Label distribution (all 2,205 cycles):** cooler 3% / 20% / 100% = 732 / 732 / 741. Valve 73 / 80 / 90 / 100 = 360 / 360 / 360 / 1,125. Pump leak 0 / 1 / 2 = 1,221 / 492 / 492. Accumulator 90 / 100 / 115 / 130 bar = 808 / 399 / 399 / 599.

**Stable flag: the name is inverted.** `0` means *stable* and `1` means static conditions may not have been reached yet. There are 1,449 stable and 756 unstable cycles. The first 211 cycles (0–210) are all unstable warm-up, and there are further unstable blocks at 732–942 and 1,464–1,674 (each condition change of the cooler). Single unstable cycles also appear about every 41 cycles.

**Design, not degradation.** The rig steps through a factorial design (144 label combinations in the stable cycles, usually in runs of 10 cycles). Labels are **not** a run-to-failure progression, and most cycles have several components degraded at once. Stable cycles where *only one* component is off-nominal (others at 100% / 100% / 0 / 130 bar):

| Condition (others optimal, stable) | Cycles | Cycle indices |
|---|---|---|
| all optimal (healthy) | **10** | 1664–1673 (plus unstable 1756, 1787–1796) |
| pump leak = 2 (severe) | 10 | within 1674–1714 |
| valve = 80 (severe lag) | 10 | 1767–1776 |
| valve = 73 (near failure) | 10 | 1757–1766 |
| accumulator = 90 (near failure) | 19 | within 1464–2204 |
| cooler = 3 (near failure) | 10 | within 0–332 |

**This limits R009–R014.** Each clean single-fault condition is only about 10 min of real signal (10 cycles × 60 s). An R scenario will be a short real segment of labelled cycles, stitched in label order, inside a synthetic week. The stitching must be recorded in provenance with the cycle numbers. Alternatively, include multi-fault cycles and say in `truth.detail` that other components were also off-nominal. The two "healthy" scenarios share one pool of only 10 stable all-optimal cycles. Don't invent labels. If more healthy data is needed, R013/R014 can use stable cycles where valve/pump/accumulator are optimal and the cooler is at 20%; label that cooler state honestly (cooler is a separate sub-type).

**How visible each fault is in 1 Hz cycle means** (change vs the healthy cycles; healthy cycle-to-cycle noise is tiny, so even small shifts are many σ):

| Condition | Clearest 1 Hz correlates |
|---|---|
| pump leak 2 | SE −6.1%, FS1 −4.1%, PS3 −3.7%, EPS1 +1.7%, PS1 −0.3% |
| valve 73/80 | cycle means move < 1% (PS2 −0.5%). Lag is a *transient* effect, so aggregate with **std/max per second**, not just the mean |
| accumulator 90 | TS1 −2.6%, CE −2.3%; pressures < 0.5% |
| cooler 3 | TS1 +51%, CE −57%, PS3 −12%, FS2 −10%: very obvious |

**Takeaways:**
- Use one **fixed affine rescale per tag**, shared by all scenarios. Never normalise per segment, or the 0.3–6% fault shifts disappear.
- Aggregate 100 Hz → 1 Hz as mean/std/max per second, as planned.
- The press-pressure mapping should start from PS1 (133–192 bar), since it is the system pressure.
- The UCI documentation itself says pump and accumulator states are the hard targets.

**Oddities:** `description.txt` and `documentation.txt` are Latin-1 encoded (mojibake for "Schütze" and "Saarbrücken"). SE reaches 100.6% (>100). FS1 drops to 0 within cycles (valve switching), which is not a sensor fault.

---

## 3. IMS bearings (`ims_bearings`, test 2 only) — figure `data_inspection/ims_bearings.png`

**Source and selection:** NASA `IMS.zip` (data.nasa.gov → presigned S3; 1.07 GB) contains `1st_test.rar` (367 MB), `2nd_test.rar` (85.6 MB), `3rd_test.rar` (609 MB) and the readme PDF. Only `2nd_test.rar` and the readme were range-extracted with `remotezip`. Tests 1 and 3 were never downloaded. The PHM Society mirror (`4. Bearings.zip`) holds a single 1.07 GB `.7z` and was not used.

**From the bundled readme (verbatim facts):**
- Rexnord ZA-2115 double-row bearings on one shaft, 4 bearings, 2000 RPM, 6000 lb radial load, force-lubricated.
- PCB 353B33 accelerometers. Each file is 1 s at **20 kHz (20,480 points)**, taken every 10 min.
- **Set No. 2:** "February 12, 2004 10:32:39 to February 19, 2004 06:22:39". 984 files, 4 channels (Bearing 1–4 → Ch 1–4). "At the end of the test-to-failure experiment, **outer race failure occurred in bearing 1**."

So the R015–R017 truth is `conveyor_bearing_defect`, detail "outer race failure, bearing 1 (IMS test 2)", with `truth_source: source_label`.

**What the data shows:**
- 984 files, all 20,480 × 4, at exactly 10-minute spacing with no gaps. Units are g (acceleration). The readme gives no units; the values fit g.
- **The last 2 snapshots (2004-02-19 06:12:39 and 06:22:39) are dead**: RMS about 0.002 g on all channels. The rig or DAQ had stopped. The last live snapshot is **06:02:39**. Exclude the dead files, or treat them as "machine stopped", not as a sensor reading.
- Bearing 1 RMS is 0.077 g at baseline and 0.48 g at the last live snapshot (peak 0.725 g). Kurtosis peaks at 17.1.
- Bearing 1 clips at ±5.0 g in 2 snapshots (ADC limit).
- Onset estimate (B1 RMS > baseline + 6σ for 1 h): **2004-02-16 05:02:39** (snapshot 543). In the figure, a clearer step appears around **2004-02-17 07:00** (RMS 0.10 → 0.17 g), then a recovery dip, then a run-up from 02-18 onwards.
- **Spectral evidence:** the envelope spectrum (2–8 kHz band) of B1 peaks at **229.5 Hz** 50 snapshots after onset. That is close to the ZA-2115 BPFO of ≈236 Hz at 2000 RPM; the difference is plausibly belt slip. In the last live snapshot it peaks at **461 Hz ≈ 2×BPFO**. The plain Welch peaks are dominated by structural resonances. `spectrum()` should offer an envelope option, or the bearing class may not "show its peak".
- **Suggested R windows:** healthy = 02-12 to 02-15. Degrading = after 02-17 07:00. Near failure = 02-19 00:00 → 06:02 (live only).

---

## 4. MIMII (`mimii`, 6 dB subset) — figure `data_inspection/mimii.png`

**What was fetched:** the 6 dB zips on Zenodo record 3384388 are 7.7 GB (pump), 10.2 GB (fan), 7.1 GB (slider) and 6.9 GB (valve). The script read only each zip's central directory and then **range-extracted 400 individual wavs (976.6 MB)**. No whole zip was downloaded. Selection is deterministic: 50 normal + 50 abnormal clips per machine type, spread over the 4 machine ids (id_00/02 get 13, id_04/06 get 12), using a seeded shuffle (`seed 2026|<machine>|<label>`). A rerun lists the zips and fetches 0 files. MIMII DUE/DG were not touched.

**Available in each 6 dB zip** (from the central directory; pump shown): id_00 has 1,007 normal / 144 abnormal clips, id_02 1,006 / 112, id_04 703 / 101, id_06 1,037 / 103. That is 4,218 entries in total.

| Machine | Clips (normal / abnormal) | Format | Duration | RMS ch0 median, normal → abnormal (full-scale) | Maps to |
|---|---|---|---|---|---|
| pump | 50 / 50 | 16 kHz, **8 ch**, 16-bit PCM | 10.0 s each | 0.0051 → 0.0058 (abnormal p99 0.015) | ST40 sealer pump |
| fan | 50 / 50 | same | 10.0 s | 0.0055 → 0.0052 | ST20/ST30 cooling |
| slider | 50 / 50 | same | 10.0 s | 0.0052 → 0.0067 | ST50 conveyor |
| valve | 50 / 50 | same | 10.0 s | 0.0053 → 0.0056 | UT-AIR |

Each clip is 2.56 MB, and every clip is exactly 10 s, 8 channels, 16 kHz.

**Takeaways for `listen()` and the MFCC baseline:**
- **Loudness does not separate the classes.** The normal and abnormal RMS ranges overlap for every machine, and almost completely for fan and valve. Abnormal pump and slider clips have higher broadband energy (pump about 2–4 kHz, slider 2–6 kHz plus tonal peaks). The fan's mean spectra are nearly identical. Valve sound is intermittent (open/close events), so its anomalies are in timing, not level. The MFCC distance must compare against the **same machine id's** normal clips. Per id, the median level change from normal to abnormal runs from −41% to +133%, and it **flips sign**: fan id_06 and valve id_00 abnormal clips are *quieter* than normal, while pump id_00 and slider id_00 are about 2.3–2.5× louder. Normal levels also differ between ids (pump 0.0042–0.0057).
- The clips are **8-channel** (microphone array). Downmix (channel 0 or the mean) before Gemini `listen` and the MFCC baseline, and record which in provenance. An 8-ch upload is 8× the bytes and tokens.
- All clips are exactly 10 s long, so placing them in a scenario needs no trimming.
- Share-alike: every clip uploaded to GCS stays CC BY-SA 4.0 with attribution (see `data/SOURCES.md`).

---

## 5. MaintIE (`maintie`) — figure `data_inspection/maintie.png`

**Files:** `gold_release.json` (1,076 records; the README's statistics section says 1,067, but the file holds 1,076) and `silver_release.json` (7,000). Each record has `text`, `tokens`, `entities` (token spans and a hierarchical type) and `relations`. In total there are 8,076 texts with 4 duplicates in silver and 1 in gold.

| | Tokens min / median / p99 / max (mean) | Chars median / max | Share with `<id>` |
|---|---|---|---|
| gold | 2 / 6 / 10 / 12 (5.7) | 34 / 74 | 66.5% |
| silver | 1 / 5 / 10 / 13 (5.4) | 33 / 78 | 56.6% |

**Five examples** (seeded sample, `random.Random(2026)`):
1. `repair and replace chain guide`
2. `<id> replace extinguisher and bracket`
3. `hoist chain pin fell out`
4. `bolts out of cable handler`
5. `grease pump`

**Style notes for the work-order generator:**
- Texts are lower-case and terse. They are already **normalised and sanitised**: asset identifiers are replaced by `<id>`, numbers by `<num>`, and abbreviations were expanded (`unserviceable` appears 409×).
- Top words are replace, repair, change, hand/right/left, hose, oil, leak, pulley, engine, bucket. The domain is mining fleet and fixed plant, not automotive.
- So MaintIE gives *length and syntax* style only. Our generator should add the abbreviations and typos it lacks (for example "chk", "repl", "u/s") and must not copy mining-specific nouns.
- Entity types: PhysicalObject ≫ Activity > State > Process > Property.

---

## 6. Surprises worth remembering
1. **UCI download throttling:** one connection crawled at about 25 KB/s while fresh connections got over 1.5 MB/s, and UCI ignores HTTP Range. `fetch_datasets.py` now drops and reopens a connection that stays under 64 KB/s for 60 s.
2. **NASA IMS.zip is a zip of RARs**, so `remotezip` can pull a single test set (85.6 MB instead of 1.07 GB). The final 2 snapshots of test 2 are dead.
3. **MetroPT-3:** the file is 0.1 Hz decimated from a 1 Hz logger, ~18% of the span is gaps, the leak shows mainly as compressor duty rather than pressure, and the failure table has duplicate numbering plus an impossible maintenance date.
4. **UCI hydraulic:** `stable_flag` 0 means stable, and only about 10 stable cycles exist per clean single-fault condition.
5. **Citations differ slightly from the DATA_SOURCES.md pointers.** The IMS readme cites Qiu, Lee, Lin (3 authors) with the title "...Roller Bearing Prognostics". The MetroPT-3 page asks for the DSAA 2021 paper *and* the Sci. Data 2022 paper. `data/SOURCES.md` copies the source text.
