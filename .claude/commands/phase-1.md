---
description: Phase 1 — contracts, dataset fetch, synthetic plant (S-set), real-signal scenarios (R-set), text, manuals, provenance
argument-hint: "[contracts | fetch | v1 | v2 | rset]"
---

# Phase 1 — Contracts + hybrid plant data

Mode: $ARGUMENTS (default: the next unfinished part, in the order below).

Specs: docs/SYNTHETIC_DATA_SPEC.md (what to build), docs/DATA_SOURCES.md (what you may use and how to attribute it), docs/ARCHITECTURE.md §4 (contracts). Delegate data work to `senior-data-ml-engineer`, contracts to `principal-engineer`. Anything not on the DATA_SOURCES USE list is forbidden.

## Part A — contracts (Sat night, both humans)
Write `agents/schemas.py`, `api/events.py`, `simulator/truth_schema.py` exactly from ARCHITECTURE §4 (including `ProvenanceRef`, `HYDRAULIC_DEGRADATION`, `scenario_set`, `truth_source`, `imperfections`), plus:
- `tests/test_contracts.py` round-tripping every model and event type;
- `tests/fixtures/sample_stream.jsonl`: a realistic hand-written stream for one **real-signal** air-leak incident (R002-style) with a verifier FAIL then PASS, a `cache_hit`, a `model_fallback`, provenance chips on real evidence, `rca_final`, `work_order_draft`, `cost`, `done`;
- `web/src/types/events.ts` mirroring `api/events.py`.
Show me the three contract files before merging.

## Part B — fetch (Sat night; start the downloads, let them run)
`scripts/fetch_datasets.py --only metropt3,uci_hydraulic,ims_bearings,mimii,maintie[,bosch_cnc]`:
- Before each download, open the dataset page, confirm the licence still matches DATA_SOURCES.md, record the date.
- MIMII: use `remotezip` to list the 6 dB zips for pump, fan, slider, valve and extract ~50 normal + ~50 abnormal wavs per machine type (not whole zips). IMS: one test set only.
- Write `data/raw/<id>/`, SHA-256 per file, and generate `data/SOURCES.md` (licence, URL, date, files, hashes, citation copied from the source page).
- Then a short **inspection report** per dataset in `docs/data_inspection.md`: real sampling rate (MetroPT-3's page is inconsistent — infer from timestamps), units and ranges, the failure windows/labels found (dedupe MetroPT's duplicated "#1"), which IMS bearing failed per the bundled readme, anything surprising. Plot 1 figure per dataset to `docs/data_inspection/`.

## Part C — S-set v1 (Sun Oct 11)
1. `simulator/plant.py` (6 stations + UT-AIR + UT-CHL, normal behaviour with shift patterns), `simulator/faults.py` with weld_tip_wear, sealer_pump_cavitation, conveyor_bearing_defect, air_pressure_drop, sensor_drift; propagation with lags; alarms.
2. `simulator/imperfections.py`: gaps, missing samples, one stuck value, alarm chatter, clock skew (SPEC §2), recorded in truth.
3. `simulator/generate.py --set S --n --seed --out`: deterministic, seeded shuffled IDs, writes per-scenario files + `truth.json` + `provenance.parquet`.
4. `simulator/load.py` with `TelemetryStore` (DuckDB first; BigQuery behind the same interface).
5. Tests: per-class signature/direction/onset, causal order, determinism, imperfections never at the root asset's onset, IDs don't encode class.

## Part D — S-set v2 (Mon Oct 12)
1. Remaining classes (servo_overheat, plc_timer_misconfig, coolant_blockage, fixture_misalignment, changeover_error) + no_fault; red_herring and dual_fault variants → S001–S060.
2. `simulator/text_artifacts.py`: shift notes (Flash-Lite, visible symptoms only) and 2,000 WOs using **MaintIE short texts as few-shot style exemplars**; schema-validated; cached; print generation cost.
3. Five manuals (`weld_controller`, `sealer_pump`, `conveyor_drive`, `press_hydraulics`, `compressed_air`) with page markers, troubleshooting tables, cross-references, spec limits matching the simulator, and **LOTO sections structured on OSHA 29 CFR 1910.147** with section citations. Show me every LOTO section for review before commit. Report total tokens via `count_tokens` (< 200K).
4. MIMII clip placement per SPEC §7, upload to GCS, `audio_index.json`.

## Part E — R-set (Tue Oct 13 morning)
`simulator/real_signals.py`: map MetroPT-3 → UT-AIR (R001–R008), UCI hydraulic → ST10 (R009–R014), IMS → ST50 (R015–R017) per SPEC §4, with resampling/rescaling recorded in `provenance.parquet` and `truth_source: source_label`. The line around the real signal (downstream propagation, alarms, notes, WOs) is generated as usual from visible symptoms only. The 4 MetroPT-3 failure reports become WOs on UT-AIR with provenance. Upload raw IMS snapshots for those windows to GCS for `spectrum`.
Tests: every real-sourced segment has provenance; R-set truth comes only from source labels; one sanity plot per R scenario.

## Load + exit
Load S and R sets into DuckDB and BigQuery.
Exit criterion: `uv run pytest -q` green; 60 S + 17 R scenarios; `data/SOURCES.md` complete; guard test proves `truth.json` is unreadable from `agents/` and `api/`; provenance test passes. Update LESSONS_LEARNED, commit, push. Report counts, download sizes, generation cost, and anything that looked unrealistic or any licence surprise.
