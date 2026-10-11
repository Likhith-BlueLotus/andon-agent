# Plant data spec (hybrid: synthetic plant + real signals)

The plant is a generic synthetic automotive line. Where a public dataset gives us a **real** signal or text, we map it into the plant and record provenance. Licences and attribution live in `docs/DATA_SOURCES.md`; nothing outside its USE list may be used.

Do not use any real company's station names, tag naming scheme, alarm codes or layouts.

## 1. Line model (`simulator/plant.py`)
Generic body-in-white style line, 6 stations in series, `line_id = "L1"`:

| Station | asset_id | asset_type | Tags (1 Hz) | Real-signal source (when a scenario uses it) |
|---|---|---|---|---|
| ST10 Press | `ST10-PRS` | press_hydraulics | `motor_current_a`, `vibration_rms_mms`, `hyd_pressure_bar`, `oil_temp_c`, `cycle_time_s` | `uci_hydraulic` (PS/EPS/TS/VS) |
| ST20 Weld cell A | `ST20-WLD` | weld_controller | `weld_current_ka`, `tip_resistance_mohm`, `servo_temp_c`, `cycle_time_s`, `air_pressure_bar` | synthetic (C-MAPSS-shaped wear) |
| ST30 Weld cell B | `ST30-WLD` | weld_controller | same as ST20 + `coolant_flow_lpm` | synthetic |
| ST40 Sealer | `ST40-SLR` | sealer_pump | `pump_pressure_bar`, `flow_rate_ccm`, `motor_current_a`, `bead_width_mm` | synthetic + `mimii` pump audio |
| ST50 Conveyor | `ST50-CNV` | conveyor_drive | `motor_current_a`, `vibration_rms_mms`, `speed_mpm`, `bearing_temp_c` | `ims_bearings` vibration + `mimii` slider audio |
| ST60 Vision check | `ST60-VIS` | vision | `reject_rate_pct`, `cycle_time_s` | synthetic |
| Plant air | `UT-AIR` | compressed_air | `header_pressure_bar`, `compressor_current_a`, `oil_temp_c` | `metropt3` + `mimii` valve audio |
| Chiller | `UT-CHL` | chiller | `supply_temp_c` | synthetic |

Normal behaviour: base + shift pattern (3 shifts, changeovers at shift start) + noise + benign spikes. One week of history per scenario ending at the stop.

## 2. Realistic imperfections (every scenario, seeded)
Real plant data is messy, and a judge who has seen a historian export will notice if ours isn't. Inject: 0.5–2% missing samples and 1–3 short gaps (10–120 s) per day; one stuck-value period on a random healthy tag; alarm chatter (the same alarm repeating 3–10× within a minute); duplicate shift-note entries; an off-by-a-few-seconds clock skew on one station's alarms. Tools must cope (report `n` and gaps), and the verifier tolerances already allow for it. Record all imperfections in `truth.json` → `imperfections` so the eval can check none were mistaken for root causes.

## 3. Fault classes (`simulator/faults.py`) — 11 + no_fault
Each fault: onset, ramp shape (step / linear / exponential; wear curves shaped from C-MAPSS trajectories), affected tags with direction and magnitude, propagation downstream with lag, alarms, optional audio signature, and the manual page documenting it.

| cause_class | Root asset | Primary signature | Downstream symptoms | Audio | Real-signal variant |
|---|---|---|---|---|---|
| weld_tip_wear | ST20/ST30 | `tip_resistance` ↑ linear, `weld_current` ↑ | ST60 `reject_rate` ↑ | — | — |
| sealer_pump_cavitation | ST40 | `pump_pressure` oscillation, `flow_rate` ↓ | ST60 rejects ↑, bead width variance ↑ | MIMII pump abnormal | — |
| conveyor_bearing_defect | ST50 | `vibration_rms` ↑ exp, spectral peak, `bearing_temp` ↑ | upstream cycle_time ↑ (blocking) | MIMII slider abnormal | **IMS run-to-failure** |
| servo_overheat | ST20/ST30 | `servo_temp` ↑, then cycle_time ↑ | downstream starvation | MIMII fan abnormal | — |
| air_pressure_drop | UT-AIR | `header_pressure` ↓ | ST20/ST30 `air_pressure` ↓, weld faults at both | MIMII valve abnormal | **MetroPT-3 air leaks** |
| sensor_drift | any | one tag drifts, **no physical correlates** | alarm on that tag only | — | — |
| plc_timer_misconfig | any | `cycle_time` step exactly at a shift change, nothing else moves | starvation/blocking | — | — |
| coolant_blockage | ST30 | `coolant_flow` ↓, `servo_temp` ↑ | ST30 weld faults | — | — |
| fixture_misalignment | ST20 | `cycle_time` variance ↑, weld current normal | ST60 rejects ↑ | — | — |
| changeover_error | ST10 | after a changeover note, `hyd_pressure` setpoint wrong | ST20 weld faults on new model | — | — |
| hydraulic_degradation | ST10 | pressure/flow/power pattern of pump leakage, valve lag, accumulator loss or cooler loss (sub-type in `truth.detail`) | ST10 cycle_time ↑, downstream starvation | — | **UCI hydraulic labelled cycles** |

`no_fault`: a benign glitch triggers a stop alarm; nothing upstream is abnormal.

## 4. Scenario sets
### S-set: synthetic, 60 scenarios (`S001–S060`)
10 classes (all except hydraulic_degradation) × 6: 3 clean · 1 red_herring (planted work order or shift note blaming the wrong asset, plus a noisy unrelated tag) · 1 dual_fault (secondary fault elsewhere; truth keeps the one that caused the stop) · 1 no_fault/sensor-glitch at that class's station. Seeds `2026*1000+n`. Scenario numbering is a seeded shuffle of (class, variant), so an ID never encodes its cause, and the held-out block still covers ≥8 classes. **Held out: S051–S060** (never used for prompt tuning).

### R-set: real-signal scenarios (`R001–R017`) — ground truth from the source, not from us
| IDs | Source | Content | Truth |
|---|---|---|---|
| R001–R004 | MetroPT-3 | The 4 documented air-leak windows mapped onto `UT-AIR`, with our propagation model carrying the pressure drop to the weld cells | `air_pressure_drop` @ UT-AIR; onset = failure-report start time (`truth_source: source_label`) |
| R005–R008 | MetroPT-3 | 4 normal windows far from any failure, with a benign stop alarm | `no_fault` (abstention test on real data) |
| R009–R014 | UCI hydraulic | Sequences of labelled cycles on ST10: pump leakage severe, valve severe lag, accumulator near failure, cooler near failure, + 2 healthy sequences | `hydraulic_degradation` with detail, or `no_fault` |
| R015–R017 | IMS bearings | One run-to-failure test mapped onto ST50 (RMS at 1 Hz held between snapshots; raw snapshots in GCS for `spectrum`) — pick 3 windows (healthy, degrading, near failure) | from the bundled readme; `conveyor_bearing_defect` or `no_fault` |

**Honesty rule for the R-set:** the *root-cause signal* is real; the line around it, the alarms, shift notes and work orders are synthetic (generated only from visible symptoms). The README, eval report and deck say exactly this.

## 5. Text artifacts (`simulator/text_artifacts.py`)
- **Alarms:** deterministic from signatures, generic codes like `A-ST40-PRS-LO`; floods of 5–30 alarms, mostly downstream; chatter per §2.
- **Shift notes:** 2–6 per scenario, generated by `gemini-3.1-flash-lite` from visible symptoms only. Mix of terse English and Hinglish, typos allowed. Red-herring notes from fixed templates.
- **Work orders:** 2,000 historical WOs `{wo_id, date, asset_id, symptom, action, outcome, technician_role}`, generated in batches with **MaintIE short texts as few-shot style exemplars** (terse, abbreviated, inconsistent), schema-validated, cached to `data/work_orders.parquet`. ~5% are wrong first diagnoses later corrected. The 4 MetroPT-3 failure reports are rewritten into WOs on `UT-AIR` with `provenance: metropt3`.
- Generation is cached; reruns cost $0. Print the generation cost once.

## 6. Manuals (`simulator/manuals/`) — 5 manuals, < 200K tokens total
`weld_controller`, `sealer_pump`, `conveyor_drive`, `press_hydraulics`, `compressed_air` (`.md` with `<!-- page N -->` markers, rendered to PDF for display). Each: troubleshooting table per fault, cross-references ("see Table 7-3"), spec limits that match the simulator's normal ranges, and a **LOTO section structured on OSHA 29 CFR 1910.147** (preparation and notification → shutdown → isolation → lockout/tagout → stored-energy release (hydraulic accumulators, compressed air, springs) → verification of isolation → release from lockout), citing the section numbers. Draft with Gemini; a human reviews every LOTO section before commit. Check total with `count_tokens` and record it.

## 7. Audio
MIMII clips per `DATA_SOURCES.md`, pulled with `remotezip`, uploaded to `gs://<bucket>/audio/{scenario_id}/{asset_id}/{ts}.wav`. One abnormal clip in the fault window for classes with an audio signature; normal clips elsewhere; one deliberately "noisy but normal" clip per 10 scenarios (tests that `listen` doesn't cry wolf).

## 8. Provenance (required for every tag segment, text and clip)
Table `provenance(scenario_id, asset_id, tag, t0, t1, source_id, source_ref, transform)` — e.g. `("R002","UT-AIR","header_pressure_bar", t0, t1, "metropt3", "rows 812000–815600, col TP2", "resample 1Hz; affine rescale to 6.0–7.5 bar")`. Tools attach a `provenance` summary to every `tool_result` (`real: bool`, `sources: [...]`), the UI shows it as a chip, and the eval reports results split by real vs synthetic. **A test fails if any real-sourced segment lacks provenance.**

## 9. Outputs
```
data/raw/<source_id>/...            (gitignored; from scripts/fetch_datasets.py)
data/scenarios/{S001..S060,R001..R017}/
  telemetry.parquet  alarms.parquet  shift_notes.parquet  audio_index.json
  provenance.parquet stop_event.json truth.json   (truth never readable from agents/ or api/ — guard test)
  audio_truth.json  sim_meta.json                 (eval/QA only, never loaded: clip labels, hidden fault metadata)
  vibration_index.json                            (R015–R017: raw IMS snapshots in gs://…/vibration/{scenario_id}/)
data/audio/clips/                                 (downmixed mono MIMII clips, gitignored; served from gs://…/audio/)
data/work_orders.parquet
data/SOURCES.md                      (generated: licences, URLs, dates, SHA-256, transforms, citations)
```
`truth.json` adds: `scenario_set: "synthetic"|"real_signal"`, `truth_source: "injected"|"source_label"`, `detail`, `imperfections`.

`simulator.load` writes everything to DuckDB (`data/andon.duckdb`) or BigQuery dataset `andon` (partitioned by `scenario_id`).
