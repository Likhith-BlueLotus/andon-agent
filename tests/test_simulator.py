"""Offline tests for the synthetic plant (S-set): signatures, causality, determinism,
imperfections, ID shuffling, provenance and the DuckDB store. Short histories keep it fast."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import ClassVar

import numpy as np
import pyarrow.parquet as pq
import pytest

from agents.schemas import CauseClass
from simulator import faults, plant, qa
from simulator import generate as gen_mod
from simulator.faults import FaultContext
from simulator.generate import Scenario, Slot, assign_ids, build, write_scenario
from simulator.imperfections import PROTECT_S, Imperfection
from simulator.text_artifacts import TextGen, build_work_orders

C = CauseClass
HIST = int(2.5 * 86400)
STOP = datetime(2026, 9, 10, 8, 13, 7, tzinfo=UTC)
ROOT = Path(__file__).resolve().parents[1]


# --- helpers ---------------------------------------------------------------------------------
def _inject(cls: CauseClass, seed: int):
    tl = plant.make_timeline(STOP, HIST, plant.rng_for(seed, "tl"))
    mods = plant.Modifiers(tl.n)
    f = faults.inject(cls, FaultContext(tl, plant.rng_for(seed, "f")), mods)
    sim = plant.simulate(tl, mods, seed)
    return tl, faults.finalize(f, sim), sim


def _ref(onset: int) -> tuple[int, int]:
    return max(0, onset - 24 * 3600), onset - 3600


_SIMS: dict[tuple[str, int], tuple] = {}


def sim_for(cls: CauseClass, seed: int):
    key = (cls.value, seed)
    if key not in _SIMS:
        _SIMS[key] = _inject(cls, seed)
    return _SIMS[key]


CLASS_SEEDS = [(c, s) for c in faults.FAULTS for s in (11, 12)] + [
    (C.HYDRAULIC_DEGRADATION, s) for s in (13, 14, 15, 16)
]


@pytest.fixture(scope="module")
def wo_pool():
    g = TextGen(mode="template")
    wos, labels = g.run(build_work_orders(g, 200, 7, Path("/nonexistent")))
    kinds = {lb["wo_id"]: lb["kind"] for lb in labels}
    return [w for w in wos if kinds[w["wo_id"]] == "normal"]


_BUILT: dict[str, dict] = {}


def built(sid: str, cls: CauseClass, variant: str, pool) -> dict:
    if sid not in _BUILT:
        sc = Scenario(sid, 2026_000 + int(sid[1:]), Slot(cls, variant, 0), HIST)  # type: ignore[arg-type]
        _BUILT[sid] = build(sc, TextGen(mode="template"), pool)
    return _BUILT[sid]


VARIANT_CASES = [
    ("S901", C.WELD_TIP_WEAR, "red_herring"),
    ("S902", C.AIR_PRESSURE_DROP, "dual_fault"),
    ("S903", C.CONVEYOR_BEARING_DEFECT, "no_fault"),
    ("S904", C.SENSOR_DRIFT, "clean"),
    ("S905", C.CHANGEOVER_ERROR, "red_herring"),
    ("S906", C.SERVO_OVERHEAT, "dual_fault"),
    ("S907", C.PLC_TIMER_MISCONFIG, "clean"),
    ("S908", C.COOLANT_BLOCKAGE, "clean"),
]


# --- catalogue -------------------------------------------------------------------------------
def test_plant_matches_spec_section_1():
    want = {
        "ST10-PRS": ("press_hydraulics", {"motor_current_a", "vibration_rms_mms", "hyd_pressure_bar", "oil_temp_c", "cycle_time_s"}),
        "ST20-WLD": ("weld_controller", {"weld_current_ka", "tip_resistance_mohm", "servo_temp_c", "cycle_time_s", "air_pressure_bar"}),
        "ST30-WLD": ("weld_controller", {"weld_current_ka", "tip_resistance_mohm", "servo_temp_c", "cycle_time_s", "air_pressure_bar", "coolant_flow_lpm"}),
        "ST40-SLR": ("sealer_pump", {"pump_pressure_bar", "flow_rate_ccm", "motor_current_a", "bead_width_mm"}),
        "ST50-CNV": ("conveyor_drive", {"motor_current_a", "vibration_rms_mms", "speed_mpm", "bearing_temp_c"}),
        "ST60-VIS": ("vision", {"reject_rate_pct", "cycle_time_s"}),
        "UT-AIR": ("compressed_air", {"header_pressure_bar", "compressor_current_a", "oil_temp_c"}),
        "UT-CHL": ("chiller", {"supply_temp_c"}),
    }  # fmt: skip
    got = {a.asset_id: (a.asset_type, {t.tag for t in a.tags}) for a in plant.ASSETS}
    assert got == want
    for row in plant.spec_limits():
        assert (
            row["normal_lo"] < row["nominal"] < row["normal_hi"] or row["tag"] == "reject_rate_pct"
        )
        for lo in (row["alarm_lo"], row["trip_lo"]):
            assert lo is None or lo < row["normal_lo"]
        for hi in (row["alarm_hi"], row["trip_hi"]):
            assert hi is None or hi > row["normal_hi"]


def test_every_cause_class_has_an_injector():
    assert set(faults.FAULTS) == set(CauseClass) - {C.NO_FAULT}
    assert len(faults.S_SET_CLASSES) == 10 and C.HYDRAULIC_DEGRADATION not in faults.S_SET_CLASSES


def test_normal_plant_stays_inside_normal_ranges():
    tl = plant.make_timeline(STOP, HIST, plant.rng_for(1, "tl"))
    sim = plant.simulate(tl, plant.Modifiers(tl.n), 1)
    prod = ~tl.changeover
    for i in tl.shift_starts:  # ramp-up cycles after a changeover
        prod[i : i + plant.CHANGEOVER_S + 400] = False
    for key, spec in plant.TAG_SPECS.items():
        x = sim.values[key][prod]
        lo, hi = np.percentile(x, [0.5, 99.5])
        assert (
            lo >= spec.normal_lo - 3 * spec.noise_std and hi <= spec.normal_hi + 3 * spec.noise_std
        ), key


# --- signatures and causality ----------------------------------------------------------------
@pytest.mark.parametrize(("cls", "seed"), CLASS_SEEDS, ids=lambda v: getattr(v, "value", str(v)))
def test_signature_after_onset_not_before(cls, seed):
    tl, f, sim = sim_for(cls, seed)
    on = f.onset_idx
    assert f.signature and on is not None
    for s in f.signature:
        key = (s.asset_id, s.tag)
        ref = _ref(on)
        before = qa.detect(key, sim.values[key], tl, s.direction, ref, (ref[1], on - 300))
        after = qa.detect(key, sim.values[key], tl, s.direction, ref, (on - 300, tl.n))
        assert before is None, f"{key} changes before onset"
        assert after is not None, f"{key} shows no {s.direction:+d} change after onset"
        assert after >= on - max(300, qa.detect_params(key, s.direction)["width"])


@pytest.mark.parametrize(("cls", "seed"), CLASS_SEEDS, ids=lambda v: getattr(v, "value", str(v)))
def test_root_changes_before_downstream(cls, seed):
    tl, f, sim = sim_for(cls, seed)
    on = f.onset_idx
    first: dict[str, int] = {}
    for s in f.signature:
        key = (s.asset_id, s.tag)
        d = qa.detect(key, sim.values[key], tl, s.direction, _ref(on), (on - 300, tl.n))
        assert d is not None
        first[s.asset_id] = min(first.get(s.asset_id, d), d)
    assert f.chain[0] == f.asset_id
    root = first[f.asset_id]
    for aid, t in first.items():
        assert t >= root, f"{aid} changed before root {f.asset_id}"
    assert all(a in f.chain for a in first), "every signature asset is on the causal chain"


def test_sensor_drift_has_no_physical_correlates():
    for seed in (21, 22, 23):
        tl, f, sim = _inject(C.SENSOR_DRIFT, seed)
        drifting = (f.signature[0].asset_id, f.signature[0].tag)
        for t in plant.asset(f.asset_id).tags:
            key = (f.asset_id, t.tag)
            if key == drifting:
                continue
            for d in (1, -1):
                assert (
                    qa.detect(
                        key, sim.values[key], tl, d, _ref(f.onset_idx), (f.onset_idx, tl.n - 60)
                    )
                    is None
                ), key
        assert f.stop and f.stop.trigger == (drifting,)


def test_plc_timer_step_lands_on_a_shift_change():
    for seed in (31, 32):
        tl, f, _ = _inject(C.PLC_TIMER_MISCONFIG, seed)
        assert f.onset_idx in set(tl.shift_starts.tolist())


def test_changeover_error_onset_is_a_model_change():
    for seed in (41, 42):
        stop = STOP
        tl0 = plant.make_timeline(stop, HIST, plant.rng_for(seed, "timeline"))
        idx = FaultContext(tl0, plant.rng_for(seed, "probe")).shift_change_onset(1.0, 6.0)
        tl = plant.make_timeline(
            stop, HIST, plant.rng_for(seed, "timeline"), force_model_change_at=idx
        )
        f = faults.inject(
            C.CHANGEOVER_ERROR, FaultContext(tl, plant.rng_for(seed, "f")), plant.Modifiers(tl.n)
        )
        k = list(tl.shift_starts).index(f.onset_idx)
        prev = tl.models[k - 1] if k else tl.first_model
        assert tl.models[k] != prev


def test_hydraulic_subtypes_all_reachable():
    seen = {_inject(C.HYDRAULIC_DEGRADATION, s)[1].detail for s in range(40, 60)}
    assert seen == set(faults.HYDRAULIC_SUBTYPES)


# --- scenario-level --------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("sid", "cls", "variant"), VARIANT_CASES, ids=[c[0] for c in VARIANT_CASES]
)
def test_scenario_alarm_flood_and_stop(sid, cls, variant, wo_pool):
    b = built(sid, cls, variant, wo_pool)
    tl, al = b["tl"], b["imp"].alarms
    stop = tl.stop
    flood = [a for a in al if stop - timedelta(minutes=30) <= a.ts <= stop + timedelta(minutes=3)]
    chatter = sum(
        int(i.split("|")[5].split("=")[1])
        for i in b["truth"].imperfections
        if i.startswith("chatter")
    )
    assert 5 <= len(flood) <= 30 + chatter
    stops = [a for a in al if a.severity == "stop"]
    assert len(stops) == 1 and stops[0].ts == stop and stops[0].asset_id == b["truth"].stop_station


@pytest.mark.parametrize(
    ("sid", "cls", "variant"), VARIANT_CASES, ids=[c[0] for c in VARIANT_CASES]
)
def test_imperfections_never_on_causal_onsets(sid, cls, variant, wo_pool):
    b = built(sid, cls, variant, wo_pool)
    tl, truth, meta = b["tl"], b["truth"], b["meta"]
    items = [Imperfection.parse(s) for s in truth.imperfections]
    kinds = {i.kind for i in items}
    assert {"missing", "gap", "stuck", "chatter", "clock_skew", "duplicate_note"} <= kinds
    onsets: dict[str, list[datetime]] = {}
    chain: set[str] = set(truth.causal_chain)
    touched: set[tuple[str, str]] = set()
    for f in (meta["primary"], meta["secondary"]):
        if not f:
            continue
        chain |= set(f["chain"])
        for a, t in f["asset_onsets"].items():
            onsets.setdefault(a, []).append(datetime.fromisoformat(t.replace("Z", "+00:00")))
        touched |= {(s["asset_id"], s["tag"]) for s in f["signature"]}
    for it in items:
        if it.kind == "gap":
            for o in onsets.get(it.asset_id, []):
                assert it.t1 <= o - timedelta(seconds=PROTECT_S) or it.t0 >= o + timedelta(
                    seconds=PROTECT_S
                )
        if it.kind in ("stuck", "chatter", "clock_skew"):
            assert it.asset_id not in chain and it.asset_id != truth.stop_station
        if it.kind == "stuck":
            assert (it.asset_id, it.tag) not in touched
    # missing samples never inside a protected window on that asset
    for aid, ons in onsets.items():
        for o in ons:
            i = tl.index(o)
            for t in plant.asset(aid).tags:
                keep = b["imp"].keep[(aid, t.tag)]
                lo, hi = max(i - PROTECT_S, 0), min(i + PROTECT_S, tl.n)
                assert keep[lo:hi].all(), (aid, t.tag)


@pytest.mark.parametrize(
    ("sid", "cls", "variant"), VARIANT_CASES, ids=[c[0] for c in VARIANT_CASES]
)
def test_hard_limit_stop_fires_at_the_stop(sid, cls, variant, wo_pool):
    """A trip that stops a station must not have fired hours before the stop."""
    b = built(sid, cls, variant, wo_pool)
    stop = b["meta"]["primary"]["stop"]
    if not stop.get("limit"):
        return
    aid, tag = stop["trigger"][0]
    lvl = {"trip": ("LL", "HH"), "alarm": ("LO", "HI")}[stop["limit"]]
    codes = {f"A-{plant.asset(aid).station}-{plant.tag_spec(aid, tag).abbr}-{x}" for x in lvl}
    tl = b["tl"]
    first = [a.ts for a in b["imp"].alarms if a.code in codes]
    assert first and min(first) >= tl.stop - timedelta(seconds=30)
    assert b["truth"].stop_ts == tl.stop and tl.n == HIST


def test_no_fault_scenario_has_nothing_abnormal(wo_pool):
    b = built("S903", C.CONVEYOR_BEARING_DEFECT, "no_fault", wo_pool)
    tl, sim, truth = b["tl"], b["sim"], b["truth"]
    assert (
        truth.root_cause_class is C.NO_FAULT and truth.asset_id is None and truth.causal_chain == []
    )
    n = tl.n
    ref = (n - 30 * 3600, n - 7 * 3600)
    for key in plant.TAG_SPECS:
        for d in (1, -1):
            hit = qa.detect_onset(qa.residual(key, sim.values[key], tl), tl, d, ref, (n - 6 * 3600, n - 10),
                                  width=300, k=7.0, persist=2)  # fmt: skip
            assert hit is None, (key, d)


def test_red_herring_blamed_asset_is_refutable(wo_pool):
    b = built("S901", C.WELD_TIP_WEAR, "red_herring", wo_pool)
    truth, tl, sim = b["truth"], b["tl"], b["sim"]
    planted = [d for d in truth.distractors if d.startswith(("planted_note", "planted_wo"))]
    noisy = [d for d in truth.distractors if d.startswith("noisy_tag")]
    assert len(planted) == 1 and len(noisy) == 1
    blamed = planted[0].split("|")[1]
    assert blamed not in truth.causal_chain
    n = tl.n
    for t in plant.asset(blamed).tags:
        key = (blamed, t.tag)
        for d in (1, -1):
            hit = qa.detect_onset(qa.residual(key, sim.values[key], tl), tl, d, (n - 36 * 3600, n - 13 * 3600),
                                  (n - 12 * 3600, n - 10), width=300, k=7.0, persist=2)  # fmt: skip
            assert hit is None, key
    # the noisy tag changes spread, not level
    _, aid, tag, t0, _ = noisy[0].split("|")
    i0 = tl.index(datetime.fromisoformat(t0.replace("Z", "+00:00")))
    x = sim.values[(aid, tag)].astype(float)
    assert np.std(np.diff(x[i0:])) > 2 * np.std(np.diff(x[i0 - 7200 : i0]))


def test_dual_fault_secondary_is_compatible(wo_pool):
    n = 0
    for sid, cls, variant in VARIANT_CASES:
        if variant != "dual_fault":
            continue
        b = built(sid, cls, variant, wo_pool)
        sec, prim = b["meta"]["secondary"], b["meta"]["primary"]
        assert sec and b["truth"].secondary_cause is CauseClass(sec["cause"])
        assert sec["asset_id"] not in prim["chain"]
        trigger = {tuple(t) for t in prim["stop"]["trigger"]}
        assert faults.FAULTS[CauseClass(sec["cause"])].static_touched.isdisjoint(trigger)
        assert b["truth"].stop_station == prim["stop"]["station"]
        n += 1
    assert n == 2


# --- IDs ---------------------------------------------------------------------------------------
def test_ids_do_not_encode_class():
    ids = assign_ids(2026)
    assert len(ids) == 60 and sorted(ids) == [f"S{i:03d}" for i in range(1, 61)]
    held = {ids[f"S{i:03d}"].group_class for i in range(51, 61)}
    assert len(held) >= 8
    assert {ids[f"S{i:03d}"].variant for i in range(51, 61)} == {
        "clean",
        "red_herring",
        "dual_fault",
        "no_fault",
    }
    nums = {sid: int(sid[1:]) for sid in ids}
    for mod in range(2, 13):
        for r in range(mod):
            classes = {ids[s].group_class for s, n in nums.items() if n % mod == r}
            assert len(classes) >= 2, f"id % {mod} == {r} encodes a class"
    for blk in range(0, 60, 6):
        assert len({ids[f"S{i:03d}"].group_class for i in range(blk + 1, blk + 7)}) >= 3
    counts = {c: sum(1 for s in ids.values() if s.group_class is c) for c in faults.S_SET_CLASSES}
    assert set(counts.values()) == {6}
    assert assign_ids(2026) == ids and assign_ids(2027) != ids


def test_visible_files_never_name_the_cause(tmp_path, wo_pool):
    labels = [c.value for c in CauseClass] + ["red_herring", "dual_fault", "injected"]
    for sid, cls, variant in VARIANT_CASES[:4]:
        d = write_scenario(tmp_path, sid, built(sid, cls, variant, wo_pool))
        blob = (d / "stop_event.json").read_text().lower()
        for name in ("alarms", "shift_notes", "work_orders", "provenance"):
            t = pq.read_table(d / f"{name}.parquet").to_pylist()
            blob += json.dumps(t, default=str).lower()
        for lab in labels:
            assert lab not in blob, f"{sid}: '{lab}' leaks into visible files"


# --- determinism, provenance, store ----------------------------------------------------------
def _hashes(d: Path) -> dict[str, str]:
    return {f.name: hashlib.sha256(f.read_bytes()).hexdigest() for f in sorted(d.iterdir())}


def test_same_seed_gives_identical_bytes(tmp_path, wo_pool):
    sc = Scenario(
        "S950", 2026_950, Slot(C.SEALER_PUMP_CAVITATION, "dual_fault", 0), int(1.5 * 86400)
    )
    a = write_scenario(tmp_path / "a", sc.scenario_id, build(sc, TextGen(mode="template"), wo_pool))
    b = write_scenario(tmp_path / "b", sc.scenario_id, build(sc, TextGen(mode="template"), wo_pool))
    assert _hashes(a) == _hashes(b)
    sc2 = Scenario("S950", 2026_951, sc.slot, sc.history_s)
    c = write_scenario(
        tmp_path / "c", sc2.scenario_id, build(sc2, TextGen(mode="template"), wo_pool)
    )
    assert _hashes(c)["telemetry.parquet"] != _hashes(a)["telemetry.parquet"]


@pytest.fixture(scope="module")
def store_dir(tmp_path_factory, wo_pool):
    root = tmp_path_factory.mktemp("data")
    scen = root / "scenarios"
    for sid, cls, variant in VARIANT_CASES[:3]:
        write_scenario(scen, sid, built(sid, cls, variant, wo_pool))
    gen_mod.wo_table(wo_pool, None)
    pq.write_table(gen_mod.wo_table(wo_pool, None), root / "work_orders.parquet")
    return scen


def test_every_segment_has_provenance(store_dir):
    for d in sorted(store_dir.iterdir()):
        tel = pq.read_table(d / "telemetry.parquet").to_pandas()
        prov = pq.read_table(d / "provenance.parquet").to_pandas()
        spans = tel.groupby(["asset_id", "tag"], observed=True)["ts"].agg(["min", "max"])
        for (aid, tag), row in spans.iterrows():
            p = prov[(prov.asset_id == aid) & (prov.tag == tag)]
            assert not p.empty, (d.name, aid, tag)
            assert (p.t0 <= row["min"]).any() and (p.t1 >= row["max"]).any()
        for art in ("alarms", "shift_notes", "work_orders"):
            assert (prov.tag == art).any()
        assert set(prov.source_id) == {"synthetic"} and prov["transform"].nunique() <= 4


@pytest.mark.parametrize("mode", ["view", "table"])
def test_duckdb_store_round_trip(store_dir, tmp_path, mode):
    from simulator.load import DuckDBStore, TelemetryStore, load_duckdb

    store = load_duckdb(store_dir, tmp_path / "andon.duckdb", telemetry=mode)
    assert isinstance(store, TelemetryStore)
    assert store.list_scenarios() == ["S901", "S902", "S903"]
    se = store.get_stop_event("S902")
    stop = se["stop_ts"]
    assert se["stopped_station"] in ("ST20-WLD", "ST30-WLD") and "root_cause_class" not in se
    t0 = stop - timedelta(hours=2)
    df = store.query_telemetry("S902", "UT-AIR", ["header_pressure_bar"], t0, stop)
    raw = pq.read_table(store_dir / "S902" / "telemetry.parquet").to_pandas()
    want = raw[
        (raw.asset_id == "UT-AIR")
        & (raw.tag == "header_pressure_bar")
        & (raw.ts >= t0)
        & (raw.ts < stop)
    ]
    assert len(df) == len(want) > 6000
    assert np.allclose(df["value"].to_numpy(), want.sort_values("ts")["value"].to_numpy())
    al = store.get_alarms("S902", stop - timedelta(minutes=30), stop + timedelta(minutes=5))
    assert (al.severity == "stop").sum() == 1
    assert store.get_alarms("S902", t0, stop, codes=["NOPE"]).empty
    assert not store.get_shift_notes(
        "S902", stop - timedelta(hours=24), stop + timedelta(hours=1)
    ).empty
    wo = store.get_work_orders("S902", "ST20-WLD", "2024-01-01", limit=5)
    assert len(wo) <= 5 and (wo.date < stop).all()
    prov = store.get_provenance("S902", "UT-AIR", ["header_pressure_bar"], t0, stop)
    assert len(prov) == 1 and prov.iloc[0].source_id == "synthetic"
    ups = [a["asset_id"] for a in store.list_assets(upstream_of="ST30-WLD")]
    assert ups == ["ST20-WLD", "ST10-PRS", "UT-AIR", "UT-CHL"]
    assert {r["tag"] for r in store.spec_limits("ST40-SLR")} == {
        "pump_pressure_bar",
        "flow_rate_ccm",
        "motor_current_a",
        "bead_width_mm",
    }
    # truth never enters the store
    tables = {
        r[0]
        for r in store.con.execute("SELECT table_name FROM information_schema.tables").fetchall()
    }
    assert not {t for t in tables if "truth" in t or "label" in t or t == "meta"}
    cols = {
        r[0]
        for r in store.con.execute("SELECT column_name FROM information_schema.columns").fetchall()
    }
    assert not cols & {
        "root_cause_class",
        "causal_chain",
        "distractors",
        "imperfections",
        "variant",
        "onset_ts",
    }
    store.close()
    reopened = DuckDBStore(tmp_path / "andon.duckdb")
    assert len(reopened.query_telemetry("S901", "ST20-WLD", ["servo_temp_c"], t0, stop)) >= 0
    reopened.close()


def test_agents_and_api_never_read_hidden_sim_files():
    for pkg in ("agents", "api"):
        for f in (ROOT / pkg).rglob("*.py"):
            src = f.read_text()
            for hidden in ("sim_meta", "work_orders_labels", "simulator.faults", "simulator.qa"):
                assert hidden not in src, f"{f} references {hidden}"


def test_bigquery_store_uses_parameterised_shared_sql():
    from types import SimpleNamespace

    from simulator.load import BigQueryStore

    seen: list[tuple[str, object]] = []

    class FakeRows(list):
        schema: ClassVar[list] = [
            SimpleNamespace(name="ts"),
            SimpleNamespace(name="tag"),
            SimpleNamespace(name="value"),
        ]

    class FakeClient:
        project = "proj"

        def query(self, sql, job_config):
            seen.append((sql, job_config))
            return SimpleNamespace(result=lambda: FakeRows())

    s = BigQueryStore(client=FakeClient(), dataset="andon")
    df = s.query_telemetry("S001", "UT-AIR", ["header_pressure_bar"], "2026-09-01T00:00:00Z", STOP)
    assert df.empty and list(df.columns) == ["ts", "tag", "value"]
    sql, cfg = seen[0]
    assert "`proj.andon`.telemetry" in sql and "tag IN UNNEST(@tags)" in sql
    assert "S001" not in sql and "UT-AIR" not in sql  # values only travel as parameters
    params = {p.name: p for p in cfg.query_parameters}
    assert set(params) == {"sid", "asset", "tags", "t0", "t1"}
    assert params["t0"].type_ == "TIMESTAMP" and params["tags"].array_type == "STRING"
    assert cfg.maximum_bytes_billed == BigQueryStore.MAX_BYTES_BILLED
