"""Offline tests for the read-only analytics tools (agents/tools.py, analytics/).

Fast path: a DuckDB store built in tmp from two short simulated scenarios (2-day history,
template text, no LLM). Ground truth is read ONLY here, from the simulator's in-memory build
result (never from agents/). Skip-if-absent tests run on the real data/andon.duckdb (S-set,
R002) and on the local raw IMS snapshots (served through a fake GCS reader)."""

from __future__ import annotations

import ast
import inspect
import json
import time
import typing
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq
import pytest

from agents import tools as T
from agents.schemas import CauseClass, Evidence
from analytics import changepoints
from simulator import generate as gen_mod
from simulator.generate import Scenario, Slot, build, write_scenario
from simulator.imperfections import Imperfection
from simulator.load import DuckDBStore, load_duckdb
from simulator.text_artifacts import TextGen, build_work_orders

C = CauseClass
ROOT = Path(__file__).resolve().parents[1]
REAL_DB = ROOT / "data" / "andon.duckdb"
SCEN = ROOT / "data" / "scenarios"
HIST = 4 * 86400  # >= 3 days so the daily profile exists, as in every real scenario (7 d)
FIX = {"S801": (C.AIR_PRESSURE_DROP, 2026801), "S802": (C.CONVEYOR_BEARING_DEFECT, 2026802)}

HAVE_REAL = REAL_DB.exists() and (SCEN / "R002" / "truth.json").exists()
need_real = pytest.mark.skipif(not HAVE_REAL, reason="real data/andon.duckdb + scenarios absent")


def _iso(d: datetime) -> str:
    return d.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _p(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(UTC)


def _truth_file(sid: str) -> dict:
    return json.loads((SCEN / sid / "truth.json").read_text())


# --- fixtures --------------------------------------------------------------------------------
@pytest.fixture(scope="module")
def fixture_store(tmp_path_factory):
    root = tmp_path_factory.mktemp("tools")
    g = TextGen(mode="template")
    wos, labels = g.run(build_work_orders(g, 200, 7, Path("/nonexistent")))
    kinds = {lb["wo_id"]: lb["kind"] for lb in labels}
    pool = [w for w in wos if kinds[w["wo_id"]] == "normal"]
    truths = {}
    for sid, (cls, seed) in FIX.items():
        b = build(Scenario(sid, seed, Slot(cls, "clean", 0), HIST), TextGen(mode="template"), pool)
        write_scenario(root / "scenarios", sid, b)
        truths[sid] = b["truth"]
    pq.write_table(gen_mod.wo_table(pool, None), root / "work_orders.parquet")
    store = load_duckdb(root / "scenarios", root / "andon.duckdb")
    models = tmp_path_factory.mktemp("models")
    yield store, truths, models
    store.close()


@pytest.fixture(scope="module")
def real_store():
    if not HAVE_REAL:
        pytest.skip("real store absent")
    s = DuckDBStore(REAL_DB)
    yield s
    s.close()


def _ctx(store, sid, models=None, **kw):
    if models is not None:
        kw["model_dir"] = models
    return T.ToolContext(store, sid, now=lambda: datetime(2026, 10, 11, tzinfo=UTC), **kw)


def _window(truth, hours: float = 24) -> tuple[str, str]:
    stop = truth.stop_ts
    return _iso(stop - timedelta(hours=hours)), _iso(stop)


# --- change points ---------------------------------------------------------------------------
def test_pelt_matches_ruptures():
    rpt = pytest.importorskip("ruptures")
    rng = np.random.default_rng(7)
    y = np.r_[rng.normal(0, 1, 80), rng.normal(3, 1, 60), rng.normal(-1, 1, 60)]
    for pen in (5.0, 15.0, 40.0):
        ref = rpt.Pelt(model="l2", min_size=3, jump=1).fit(y).predict(pen=pen)[:-1]
        assert changepoints.pelt_l2(y, pen, 3) == ref


def test_air_leak_change_point_near_onset_synthetic(fixture_store):
    store, truths, models = fixture_store
    tr = truths["S801"]
    ctx = _ctx(store, "S801", models)
    t0, t1 = _window(tr, 24)
    r = T.detect_change_points(ctx, asset_id="UT-AIR", tag="compressor_current_a", t0=t0, t1=t1)
    s = r["summary"]
    assert s["signal"].startswith("duty_fraction_") and s["status"] == "ok"
    ups = [c for c in s["change_points"] if c["direction"] == "up"]
    assert ups, s
    # This seed's leak is an exponential ramp starting right after the night-shift changeover:
    # 26 min after the labelled ramp start the duty has risen by only ~0.03 (the bin noise), so
    # that is the physical detection limit; linear/step leaks land within minutes (S-set test).
    err = abs((_p(ups[0]["ts"]) - tr.onset_ts).total_seconds())
    assert err <= 30 * 60, f"onset {tr.onset_ts}, change point {ups[0]['ts']}"
    assert ups[0]["after_mean"] > ups[0]["before_mean"] + 0.3


@need_real
def test_air_leak_change_points_near_onset_sset(real_store):
    sids = [p.name for p in sorted(SCEN.iterdir()) if p.name.startswith("S")]
    air = [s for s in sids if _truth_file(s)["root_cause_class"] == "air_pressure_drop"]
    assert air
    for sid in air:
        tr = _truth_file(sid)
        ctx = _ctx(real_store, sid)
        stop = _p(tr["stop_ts"])
        r = T.detect_change_points(ctx, asset_id="UT-AIR", tag="compressor_current_a",
                                   t0=_iso(stop - timedelta(days=7)), t1=_iso(stop))  # fmt: skip
        ups = [c for c in r["summary"]["change_points"] if c["direction"] == "up"]
        err = min(abs((_p(c["ts"]) - _p(tr["onset_ts"])).total_seconds()) for c in ups)
        assert err <= 25 * 60, (sid, tr["onset_ts"], ups)


@need_real
def test_r002_duty_change_point_vs_source_report(real_store):
    """R002 = MetroPT-3 failure report #2 (air leak). The real motor goes continuously loaded at
    ~17:43Z, ~17 min before the report's start (18:00Z); the tool must find that, not a gap edge."""
    tr = _truth_file("R002")
    ctx = _ctx(real_store, "R002")
    stop = _p(tr["stop_ts"])
    r = T.detect_change_points(ctx, asset_id="UT-AIR", tag="compressor_current_a",
                               t0=_iso(stop - timedelta(days=7)), t1=_iso(stop))  # fmt: skip
    s = r["summary"]
    last = s["change_points"][-1]
    assert last["direction"] == "up" and last["after_mean"] > 0.9 and not last["across_gap"]
    assert abs((_p(last["ts"]) - _p(tr["onset_ts"])).total_seconds()) <= 30 * 60, last
    assert "data_issue" not in last  # motor-off flats are a machine state, not a stuck sensor
    assert any(p["real"] and "MetroPT3" in (p["source_ref"] or "") for p in r["provenance"])


@need_real
def test_clean_windows_have_at_most_one_change_point(real_store):
    clean = [p.name for p in sorted(SCEN.iterdir()) if p.name.startswith("S")
             and _truth_file(p.name)["variant"] == "no_fault"][:2]  # fmt: skip
    from simulator import plant

    for sid in clean:
        stop = _p(_truth_file(sid)["stop_ts"]) - timedelta(minutes=5)
        ctx = _ctx(real_store, sid)
        for a in plant.ASSETS:
            for t in a.tags:
                r = T.detect_change_points(ctx, asset_id=a.asset_id, tag=t.tag,
                                           t0=_iso(stop - timedelta(hours=24)), t1=_iso(stop))  # fmt: skip
                cps = [c for c in r["summary"]["change_points"] if not c["at_changeover"]]
                assert len(cps) <= 1, (sid, a.asset_id, t.tag, cps)


# --- data quality ----------------------------------------------------------------------------
def test_gaps_and_stuck_values_are_reported(fixture_store):
    store, truths, models = fixture_store
    tr = truths["S801"]
    items = [Imperfection.parse(s) for s in tr.imperfections]
    ctx = _ctx(store, "S801", models)
    stuck = next(i for i in items if i.kind == "stuck")
    r = T.query_telemetry(ctx, asset_id=stuck.asset_id, tags=[stuck.tag],
                          t0=_iso(stuck.t0 - timedelta(hours=1)), t1=_iso(stuck.t1 + timedelta(hours=1)))  # fmt: skip
    dq = r["summary"]["tags"][stuck.tag]["data_quality"]
    want = (stuck.t1 - stuck.t0).total_seconds()
    assert any(abs((_p(p["start"]) - stuck.t0).total_seconds()) <= 5
               and abs(p["duration_s"] - want) <= 5 for p in dq["stuck_periods"]), dq  # fmt: skip
    gap = next(i for i in items if i.kind == "gap" and (i.t1 - i.t0).total_seconds() >= 20)
    from simulator import plant

    tag = plant.asset(gap.asset_id).tags[0].tag
    r = T.query_telemetry(ctx, asset_id=gap.asset_id, tags=[tag],
                          t0=_iso(gap.t0 - timedelta(minutes=30)), t1=_iso(gap.t1 + timedelta(minutes=30)))  # fmt: skip
    dq = r["summary"]["tags"][tag]["data_quality"]
    dur = (gap.t1 - gap.t0).total_seconds()
    assert any(abs((_p(g["start"]) - gap.t0).total_seconds()) <= 3
               and abs(g["duration_s"] - dur) <= 3 for g in dq["gaps"]), dq  # fmt: skip
    assert r["summary"]["data_quality"]["n"] == r["summary"]["tags"][tag]["n"]


# --- evidence, rerun, provenance, scoping ----------------------------------------------------
def _all_calls(truth) -> list[tuple[str, dict]]:
    t0, t1 = _window(truth, 12)
    return [
        ("get_stop_event", {"line_id": "L1"}),
        ("list_assets", {"line_id": "L1", "upstream_of": "ST30-WLD"}),
        ("query_telemetry", {"asset_id": "UT-AIR", "tags": ["header_pressure_bar", "compressor_current_a"], "t0": t0, "t1": t1}),
        ("detect_change_points", {"asset_id": "ST50-CNV", "tag": "vibration_rms_mms", "t0": t0, "t1": t1}),
        ("spectrum", {"asset_id": "ST50-CNV", "tag": "vibration_rms_mms", "t0": t0, "t1": t1}),
        ("anomaly_score", {"asset_id": "UT-AIR", "t0": t0, "t1": t1}),
        ("search_alarms", {"line_id": "L1", "t0": t0, "t1": _iso(truth.stop_ts + timedelta(minutes=10))}),
        ("get_work_orders", {"asset_id": "UT-AIR", "since": "2025-01-01T00:00:00Z"}),
        ("get_shift_notes", {"line_id": "L1", "t0": t0, "t1": t1}),
    ]  # fmt: skip


def test_every_tool_stores_evidence_and_rerun_reproduces_it(fixture_store):
    store, truths, models = fixture_store
    ctx = _ctx(store, "S801", models)
    for name, args in _all_calls(truths["S801"]):
        out = T.TOOL_REGISTRY[name].fn(ctx, **args)
        assert "error" not in out, (name, out)
        eid = out["evidence_id"]
        assert eid == f"ev_{name}_1"
        assert set(out) == {"evidence_id", "summary", "provenance"}
        ev = ctx.evidence[eid]
        assert isinstance(ev, Evidence) and ev.tool == name and ev.args == args
        assert ctx.state[f"evidence:{eid}"]["summary"] == out["summary"]
        assert all(p["real"] is False for p in out["provenance"])  # synthetic scenario
        json.dumps(out, allow_nan=False)
        if name in T.SIGNAL_TOOLS:  # numeric summaries carry data quality
            assert "data_quality" in json.dumps(out["summary"]), name
        # a fresh context (fresh caches, as the verifier would have) reproduces it exactly
        again = T.rerun(_ctx(store, "S801", models), ev)
        assert json.dumps(again["summary"], sort_keys=True) == json.dumps(
            ev.summary, sort_keys=True
        )
        assert again["provenance"] == [p.model_dump(mode="json") for p in ev.provenance]
    assert len(ctx.evidence) == len(_all_calls(truths["S801"]))
    # the summary never carries raw series
    big = max(len(json.dumps(ctx.state[k])) for k in ctx.state)
    assert big < 20_000


def test_evidence_ids_are_collision_free_across_branches(fixture_store):
    store, truths, models = fixture_store
    shared: dict = {}
    base = _ctx(store, "S801", models, state=shared)
    a, b = base.with_state({}), base.with_state({})  # two parallel branches, separate deltas
    t0, t1 = _window(truths["S801"], 2)
    ids = [
        T.query_telemetry(c, asset_id="UT-CHL", tags=["supply_temp_c"], t0=t0, t1=t1)["evidence_id"]
        for c in (a, b, a, base)
    ]
    assert ids == [f"ev_query_telemetry_{n}" for n in (1, 2, 3, 4)]
    # a resumed session (new context over existing state) continues the numbering
    resumed = _ctx(store, "S801", models, state={**a.state, **b.state, **shared})
    nxt = T.query_telemetry(resumed, asset_id="UT-CHL", tags=["supply_temp_c"], t0=t0, t1=t1)
    assert nxt["evidence_id"] == "ev_query_telemetry_5"
    # merged branch deltas (as ADK commits them) hold every id exactly once
    assert sorted(resumed.evidence) == [f"ev_query_telemetry_{n}" for n in (1, 2, 3, 4, 5)]
    assert sorted(a.evidence) == ["ev_query_telemetry_1", "ev_query_telemetry_3"]


def test_scenario_scoping(fixture_store):
    store, truths, models = fixture_store
    a, b = _ctx(store, "S801", models), _ctx(store, "S802", models)
    sa = T.get_stop_event(a, line_id="L1")["summary"]
    sb = T.get_stop_event(b, line_id="L1")["summary"]
    assert sa["stop_ts"] == _iso(truths["S801"].stop_ts) != sb["stop_ts"]
    # the model cannot pass a scenario
    r = T.TOOL_REGISTRY["get_stop_event"].fn(a, line_id="L1", scenario_id="S802")
    assert r["evidence_id"] is None and r["error"]["code"] == "bad_args"
    # S802's window lies outside S801's history -> no silent cross-scenario read
    t0, t1 = _window(truths["S802"], 6)
    if _p(t0) > truths["S801"].stop_ts + timedelta(hours=1):
        r = T.query_telemetry(a, asset_id="UT-AIR", tags=["header_pressure_bar"], t0=t0, t1=t1)
        assert r["error"]["code"] == "window_outside_history"
    # the closure surface has no scenario parameter at all
    for f in T.bind_tools(a):
        assert "scenario_id" not in inspect.signature(f).parameters
    assert T.bind_tools(a, ["get_stop_event"])[0](line_id="L1")["evidence_id"]


@pytest.mark.parametrize(
    ("name", "args", "code"),
    [
        ("query_telemetry", {"asset_id": "UT-AIR", "tags": ["header_pressure_bar"], "t0": "yesterday", "t1": "2026-09-06T00:00:00Z"}, "bad_time"),
        ("query_telemetry", {"asset_id": "UT-AIR", "tags": ["header_pressure_bar"], "t0": "2026-09-06T00:00:00Z", "t1": "2026-09-05T00:00:00Z"}, "bad_window"),
        ("query_telemetry", {"asset_id": "UT-AIR", "tags": ["header_pressure_bar"], "t0": "2026-08-20T00:00:00Z", "t1": "2026-09-06T00:00:00Z"}, "window_too_long"),
        ("query_telemetry", {"asset_id": "ST99-XXX", "tags": ["x"], "t0": "2026-09-05T00:00:00Z", "t1": "2026-09-06T00:00:00Z"}, "unknown_asset"),
        ("query_telemetry", {"asset_id": "UT-AIR", "tags": ["flux_capacitor"], "t0": "2026-09-05T00:00:00Z", "t1": "2026-09-06T00:00:00Z"}, "unknown_tag"),
        ("query_telemetry", {"asset_id": "UT-AIR", "tags": [], "t0": "2026-09-05T00:00:00Z", "t1": "2026-09-06T00:00:00Z"}, "bad_tags"),
        ("query_telemetry", {"asset_id": "UT-AIR", "tags": ["header_pressure_bar"], "t0": "2025-01-01T00:00:00Z", "t1": "2025-01-02T00:00:00Z"}, "window_outside_history"),
        ("get_stop_event", {"line_id": "L9"}, "unknown_line"),
        ("list_assets", {"line_id": "L1", "upstream_of": "nope"}, "unknown_asset"),
        ("search_alarms", {"line_id": "L1", "t0": "2026-09-05T00:00:00Z", "t1": "2026-09-06T00:00:00Z", "codes": 5}, "bad_codes"),
        ("get_work_orders", {"asset_id": "UT-AIR", "since": "2027-01-01"}, "bad_since"),
        ("detect_change_points", {"asset_id": "UT-AIR", "t0": "2026-09-05T00:00:00Z", "t1": "2026-09-06T00:00:00Z"}, "bad_args"),
    ],
)  # fmt: skip
def test_bad_args_return_error_dicts(fixture_store, name, args, code):
    store, _, models = fixture_store
    ctx = _ctx(store, "S801", models)
    out = T.TOOL_REGISTRY[name].fn(ctx, **args)
    assert out["evidence_id"] is None and out["error"]["code"] == code, out
    assert isinstance(out["error"]["message"], str)
    assert len(ctx.evidence) == 0


def test_call_limits(fixture_store):
    store, _, models = fixture_store
    ctx = _ctx(store, "S801", models, limits={"get_stop_event": 1})
    assert T.get_stop_event(ctx, line_id="L1")["evidence_id"] == "ev_get_stop_event_1"
    assert T.get_stop_event(ctx, line_id="L1")["error"]["code"] == "call_limit"


# --- ADK binding -----------------------------------------------------------------------------
def test_bind_tools_signatures_and_adk_declarations(fixture_store):
    store, _, models = fixture_store
    ctx = _ctx(store, "S801", models)
    fns = T.bind_tools(ctx)
    assert [f.__name__ for f in fns] == list(T.TOOL_REGISTRY)
    for f in fns:
        sig_ = inspect.signature(f)
        assert f.__doc__ and "ctx" not in sig_.parameters
        assert list(sig_.parameters) == list(T.TOOL_REGISTRY[f.__name__].signature.parameters)
        assert typing.get_type_hints(f)["return"] is dict
    from google.adk.tools import FunctionTool

    adk_fns = T.bind_tools(ctx, adk=True)
    for f in adk_fns:
        decl = FunctionTool(f)._get_declaration()
        assert decl.name == f.__name__
        if decl.parameters_json_schema is not None:  # ADK JSON-schema declarations
            props = set(decl.parameters_json_schema.get("properties", {}))
        else:
            props = set((decl.parameters.properties or {}) if decl.parameters else {})
        assert "tool_context" not in props and "ctx" not in props
        assert props == set(T.TOOL_REGISTRY[f.__name__].signature.parameters)

    class FakeToolContext:  # what ADK injects: only .state is used
        def __init__(self) -> None:
            self.state: dict = {}

    tc = FakeToolContext()
    out = adk_fns[0](line_id="L1", tool_context=tc)
    assert f"evidence:{out['evidence_id']}" in tc.state and not ctx.state


# --- provenance on real data -----------------------------------------------------------------
@need_real
def test_real_and_synthetic_provenance_flags(real_store):
    stop = _p(_truth_file("R002")["stop_ts"])
    ctx = _ctx(real_store, "R002")
    w = {"t0": _iso(stop - timedelta(hours=12)), "t1": _iso(stop)}
    r = T.query_telemetry(
        ctx, asset_id="UT-AIR", tags=["header_pressure_bar", "compressor_current_a"], **w
    )
    assert r["provenance"] and all(p["real"] and p["source_id"] == "metropt3" and p["source_ref"]
                                   for p in r["provenance"])  # fmt: skip
    r = T.query_telemetry(ctx, asset_id="ST20-WLD", tags=["air_pressure_bar"], **w)
    assert all(not p["real"] for p in r["provenance"])
    wo = T.get_work_orders(ctx, asset_id="UT-AIR", since="2024-01-01T00:00:00Z")
    assert any(p["real"] and p["source_id"] == "metropt3" for p in wo["provenance"]) or all(
        not p["real"] for p in wo["provenance"]
    )


# --- spectrum ---------------------------------------------------------------------------------
class FakeGCS:
    """gs:// -> local raw IMS file, using the scenario's vibration index (tests only)."""

    def __init__(self, sid: str) -> None:
        idx = json.loads((SCEN / sid / "vibration_index.json").read_text())["snapshots"]
        self.map = {s["gs_uri"]: ROOT / s["local_file"] for s in idx}
        self.reads: list[str] = []

    def read_bytes(self, uri: str) -> bytes:
        self.reads.append(uri)
        return self.map[uri].read_bytes()


HAVE_IMS = (SCEN / "R017" / "vibration_index.json").exists() and (
    ROOT / "data/raw/ims_bearings/2nd_test/2nd_test"
).exists()


@pytest.mark.skipif(not (HAVE_REAL and HAVE_IMS), reason="raw IMS snapshots or R017 absent")
def test_spectrum_on_ims_near_failure_shows_outer_race_band(real_store):
    fake = FakeGCS("R017")
    ctx = _ctx(real_store, "R017", gcs=fake)
    idx = json.loads((SCEN / "R017" / "vibration_index.json").read_text())["snapshots"]
    end = _p(idx[-1]["ts"]) + timedelta(minutes=1)
    r = T.spectrum(ctx, asset_id="ST50-CNV", tag="vibration_rms_mms",
                   t0=_iso(end - timedelta(hours=6)), t1=_iso(end))  # fmt: skip
    s = r["summary"]
    assert s["source"] == "raw_snapshots" and s["snapshots_used"] == 6 and len(fake.reads) == 6
    assert s["fs_hz"] == 20000
    assert any(215 <= p["freq_hz"] <= 245 for p in s["envelope_peaks"]), s["envelope_peaks"]
    assert r["provenance"][0]["real"] and "gs://" in r["provenance"][0]["source_ref"]
    again = T.rerun(ctx, ctx.evidence[r["evidence_id"]])
    assert again["summary"] == s


def test_spectrum_1hz_shows_conveyor_rotation_on_bearing_defect(fixture_store):
    store, truths, models = fixture_store
    tr = truths["S802"]
    ctx = _ctx(store, "S802", models)
    late = T.spectrum(ctx, asset_id="ST50-CNV", tag="vibration_rms_mms",
                      t0=_iso(tr.stop_ts - timedelta(hours=3)), t1=_iso(tr.stop_ts))["summary"]  # fmt: skip
    early = T.spectrum(ctx, asset_id="ST50-CNV", tag="vibration_rms_mms",
                       t0=_iso(tr.onset_ts - timedelta(hours=6)), t1=_iso(tr.onset_ts))["summary"]  # fmt: skip

    def rot(s):
        return max(
            (p["amplitude"] for p in s["peaks"] if abs(p["freq_hz"] - 0.255) < 0.01), default=0
        )

    assert late["source"] == "1hz_series" and rot(late) > 3 * rot(early) > 0


def test_anomaly_score_rises_on_fault(fixture_store):
    store, truths, models = fixture_store
    tr = truths["S802"]
    ctx = _ctx(store, "S802", models)
    hi = T.anomaly_score(ctx, asset_id="ST50-CNV", t0=_iso(tr.stop_ts - timedelta(hours=6)),
                         t1=_iso(tr.stop_ts))["summary"]  # fmt: skip
    lo = T.anomaly_score(ctx, asset_id="ST50-CNV", t0=_iso(tr.onset_ts - timedelta(hours=12)),
                         t1=_iso(tr.onset_ts - timedelta(hours=1)))["summary"]  # fmt: skip
    assert 0 <= lo["score"] < 0.5 < hi["score"] <= 1
    assert hi["top_tags"][0]["tag"] in {"vibration_rms_mms", "bearing_temp_c", "motor_current_a"}


# --- latency on the real store ------------------------------------------------------------
@need_real
def test_each_tool_under_1_5_s_on_real_duckdb(real_store):
    for sid in ("R002", "S005"):
        tr = _truth_file(sid)
        stop = _p(tr["stop_ts"])
        ctx = _ctx(real_store, sid)
        week = {"t0": _iso(stop - timedelta(days=7)), "t1": _iso(stop)}
        T.anomaly_score(ctx, asset_id="ST10-PRS", **week)  # warm the lazily loaded models
        calls = [
            ("get_stop_event", {"line_id": "L1"}),
            ("list_assets", {"line_id": "L1", "upstream_of": "ST60-VIS"}),
            ("query_telemetry", {"asset_id": "ST30-WLD", "tags": ["weld_current_ka", "tip_resistance_mohm", "servo_temp_c", "cycle_time_s", "air_pressure_bar", "coolant_flow_lpm"], **week}),
            ("detect_change_points", {"asset_id": "UT-AIR", "tag": "compressor_current_a", **week}),
            ("spectrum", {"asset_id": "ST50-CNV", "tag": "vibration_rms_mms", **week}),
            ("anomaly_score", {"asset_id": "ST30-WLD", **week}),
            ("search_alarms", {"line_id": "L1", **week}),
            ("get_work_orders", {"asset_id": "UT-AIR", "since": "2024-01-01T00:00:00Z"}),
            ("get_shift_notes", {"line_id": "L1", **week}),
        ]  # fmt: skip
        for name, args in calls:
            t = time.perf_counter()
            out = T.TOOL_REGISTRY[name].fn(ctx, **args)
            dt = time.perf_counter() - t
            assert "error" not in out, (sid, name, out)
            assert dt < 1.5, f"{sid} {name} took {dt:.2f} s"


# --- guards -----------------------------------------------------------------------------------
@pytest.mark.parametrize("pkg", ["agents", "analytics"])
def test_tools_never_touch_ground_truth(pkg):
    for path in (ROOT / pkg).rglob("*.py"):
        src = path.read_text()
        for word in ("truth.json", "sim_meta", "audio_truth", "work_orders_labels"):
            assert word not in src, f"{path} mentions {word}"
        for node in ast.walk(ast.parse(src)):
            mods = []
            if isinstance(node, ast.Import):
                mods = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                mods = [node.module]
            for m in mods:
                assert not m.startswith(("simulator.truth_schema", "simulator.generate",
                                         "simulator.faults", "eval")), f"{path} imports {m}"  # fmt: skip


def test_detect_direction_follows_reported_delta_under_daily_profile():
    """Regression: PELT runs on the de-seasonalised series, so a step during a falling daily
    profile is "up" vs normal while the raw before/after means fall. The reported direction
    must follow the reported (raw) delta. Before the fix this case gave direction "up" with
    delta < 0."""
    import numpy as np

    from analytics import changepoints as cpm
    from analytics.series import Series, signal_def

    sd = signal_def("UT-CHL", "supply_temp_c")
    day = 86400
    t1 = 1_791_590_400
    t = np.arange(t1 - 7 * day, t1, dtype=np.int64)
    rng = np.random.default_rng(1)
    v = 7.0 + 3.0 * np.sin(2 * np.pi * ((t % day) / day)) + rng.normal(0, 0.05, len(t))
    v = v + np.where(t >= t1 - day + 20 * 3600, 0.8, 0.0)
    out = cpm.detect(Series(t, v), t1 - day, t1, sd, history=Series(t, v))
    cps = [c for c in out["change_points"] if c["delta"]]
    assert cps
    for c in cps:
        assert (c["delta"] > 0) == (c["direction"] == "up"), c


def test_gcs_reader_returns_data_when_cache_dir_is_read_only(tmp_path, monkeypatch):
    """Cloud Run runs the image as a non-root user: a failed cache write must not fail the read (listen index)."""
    import stat
    from types import SimpleNamespace

    from agents.tools import GCSReader

    ro = tmp_path / "ro"
    ro.mkdir()
    ro.chmod(stat.S_IRUSR | stat.S_IXUSR)
    blob = SimpleNamespace(download_as_bytes=lambda timeout: b'{"clips": []}')
    client = SimpleNamespace(bucket=lambda name: SimpleNamespace(blob=lambda key: blob))
    r = GCSReader(cache_dir=ro / "gcs")
    r._client = client
    try:
        assert r.read_bytes("gs://b/audio/R002/audio_index.json") == b'{"clips": []}'
    finally:
        ro.chmod(stat.S_IRWXU)
