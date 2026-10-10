# Data sources register (licence + provenance)

Single source of truth for every external dataset or text. Nothing enters the repo, GCS, prompts, the UI or the deck unless it's listed here as **USE**. Licences were checked on 2026-10-10; re-check the page when you download and note the date in `data/SOURCES.md`. Copy each citation from the dataset page itself (the short forms below are pointers, not final citation text).

## Policy
1. **Never commit raw external data.** Commit `scripts/fetch_datasets.py` (downloads + checksums) and `data/SOURCES.md` (generated citations). Raw files live in `data/raw/` (gitignored) and, where needed at runtime, in GCS.
2. **Attribute everywhere it's shown:** README "Data" section, UI footer, deck data slide, and the evidence drawer's provenance chip.
3. **Share-alike (CC BY-SA):** any redistributed clip or derived *dataset* stays CC BY-SA 4.0 with attribution. Our code is unaffected. Keep MIMII clips in GCS, mark them in `data/SOURCES.md`.
4. **Be honest about mapping.** Real signals are *mapped* into a generic automotive line (rescaled, resampled, relabelled to our tags). Say "real compressor failure data from a metro operator, mapped onto the plant air header", never "real automotive plant data".
5. **Non-commercial or unlicensed = don't use**, even "just for calibration": the repo is public and the pitch is commercial.

## USE

| ID | Dataset | Licence (as published) | What we take | Maps to | Size / access notes | Cite |
|---|---|---|---|---|---|---|
| `metropt3` | MetroPT-3, UCI #791 | CC BY 4.0 | Analogue pressures, motor current, oil temp; the 4 air-leak failure windows from the operator's failure reports | `UT-AIR` header pressure + compressor current; `air_pressure_drop` real scenarios; 4 real work orders rewritten from the failure-report table | ~208 MB CSV. Page states both 1 Hz and 0.1 Hz: **infer the real rate from timestamps**. Failure table lists "#1" twice: dedupe by time. | "The MetroPT dataset for predictive maintenance", Scientific Data (2022) + UCI DOI 10.24432/C5VW3R |
| `uci_hydraulic` | Condition Monitoring of Hydraulic Systems, UCI #447 | CC BY 4.0 | PS1–PS6 pressure (100 Hz), EPS1 motor power, FS flow, TS temps, VS1 vibration; per-cycle labels for cooler, valve, pump leakage, accumulator | ST10 press hydraulics; `hydraulic_degradation` real scenarios with source labels | 2,205 × 60 s cycles. Aggregate 100 Hz → 1 Hz (mean/std/max per second). Use the `stable` flag to drop unsettled cycles. | Helwig, Pignanelli, Schütze (I2MTC 2015) + UCI |
| `ims_bearings` | IMS Bearings (Univ. of Cincinnati, via NASA PCoE) | Listed on data.gov as a US government work | Run-to-failure vibration snapshots | ST50 conveyor vibration; `conveyor_bearing_defect` real scenarios; raw snapshots feed `spectrum()` | Large zip: download one test set only. Which bearing failed and how is in the bundled readme: **read it and record it in `truth.json` as `truth_source: source_label`**. | Qiu, Lee, Lin, Yu (J. Sound & Vibration 2006) + NASA PCoE / data.gov |
| `mimii` | MIMII, Zenodo 3384388 (Hitachi) | CC BY-SA 4.0 | Normal + abnormal wav clips: pump, fan, slider, valve | `listen()`: pump→ST40, slider→ST50, fan→ST20/ST30 cooling, valve→UT-AIR | **100.2 GB total; one zip is 7–11 GB.** Use the `remotezip` package to pull ~50 individual wavs per machine type from the 6 dB zips. Do not use MIMII DUE/DG (non-commercial). | Purohit et al., DCASE 2019 Workshop (arXiv:1909.09347) |
| `bosch_cnc` (optional) | Bosch CNC Machining, UCI #752 | CC BY 4.0 (data folder) | Real accelerometer from a production CNC, normal/abnormal processes | Second vibration texture for ST10/ST20 if time allows | Small. | Tnani, Feil, Diepold (Procedia CIRP 2022) + UCI |
| `cmapss` | NASA C-MAPSS | NASA repository; no explicit licence on the open-data record | Degradation trajectory *shapes* only (no rows redistributed) | Wear curves for weld tip, servo, coolant | Use shapes, don't republish data. | Saxena & Goebel (2008), NASA PCoE |
| `maintie` | MaintIE, github.com/nlp-tlp/maintie | MIT | ~8,000 real maintenance work-order short texts with entity annotations | Few-shot **style** examples for the work-order generator (terse, abbreviated, ~5 words); optional vocabulary for the work-order search | Small JSON. Use as style exemplars; don't present them as our plant's history. | Bikaun et al., LREC-COLING 2024 |
| `osha_loto` | OSHA 29 CFR 1910.147 (Control of Hazardous Energy) | US federal regulation (public domain) | Required LOTO procedure elements and sequence | Structure of every manual's LOTO section; cited in the work-order safety block | Use the eCFR text. Cite the section numbers. | 29 CFR 1910.147 |

## DO NOT USE
| Dataset | Why |
|---|---|
| Paderborn (KAt) bearings | CC BY-NC 4.0, academic only |
| ToyADMOS / ToyADMOS2 | Non-commercial licence |
| MIMII DUE / MIMII DG | CC BY-NC-SA 4.0 |
| IEEE DataPort resistance spot-welding (BIW) | Subscription, no stated licence |
| SKAB | Repo GPL-3.0; data licence unclear |
| CWRU bearings | No published licence |
| Bosch Production Line Performance (Kaggle) | Competition rules |
| HCRL CAN datasets | Academic use only |
| AI4I 2020 | CC BY 4.0, but itself synthetic: adds no realism |
| Any employer, startup or past-research data | Hard rule |

## `data/SOURCES.md` (generated by `scripts/fetch_datasets.py`)
Per dataset: name, URL, licence, date downloaded, files used, SHA-256 of each file, transforms applied, citation. The eval report and README link to it.
