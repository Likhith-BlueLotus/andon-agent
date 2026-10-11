"""R-set (real signals mapped onto the synthetic line) and audio placement.

Unit tests run anywhere. Integration tests check the generated scenarios under data/scenarios
(skipped if they have not been generated; raw-data cross-checks skip without data/raw)."""

from __future__ import annotations

import itertools
import json
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import pytest

from agents.schemas import CauseClass
from simulator import audio as audio_mod
from simulator import plant
from simulator import real_signals as rs
from simulator.imperfections import Imperfection

C = CauseClass
ROOT = Path(__file__).resolve().parents[1]
SCEN = ROOT / "data" / "scenarios"
RAW = ROOT / "data" / "raw"
R_IDS = [f"R{i:03d}" for i in range(1, 18)]
HAVE_R = all((SCEN / sid / "truth.json").exists() for sid in R_IDS)
need_r = pytest.mark.skipif(not HAVE_R, reason="R-set not generated (simulator.real_signals)")


def _p(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(UTC)


_CACHE: dict[str, object] = {}


def _load(sid: str, name: str):
    key = f"{sid}/{name}"
    if key not in _CACHE:
        p = SCEN / sid / name
        _CACHE[key] = (
            pq.read_table(p).to_pandas() if name.endswith(".parquet") else json.loads(p.read_text())
        )
    return _CACHE[key]


# --- unit: mapping maths ---------------------------------------------------------------------
def test_upsample_never_bridges_long_gaps():
    src = np.array([0, 10, 20, 31, 100, 110, 200])  # 31->100 and 110->200 are real gaps
    x = np.array([0.0, 1.0, 2.0, 3.1, 10.0, 11.0, 20.0])
    grid = np.arange(-5, 215)
    lin = rs.upsample(src, x, grid, "linear")
    hold = rs.upsample(src, x, grid, "hold")
    v = dict(zip(grid.tolist(), lin.tolist(), strict=True))
    h = dict(zip(grid.tolist(), hold.tolist(), strict=True))
    for t in [-5, -1, *range(32, 100), *range(111, 200), 201, 214]:
        assert np.isnan(v[t]) and np.isnan(h[t]), t
    assert v[0] == 0.0 and v[5] == pytest.approx(0.5) and v[25] == pytest.approx(2.0 + 5 * 1.1 / 11)
    assert h[5] == 0.0 and h[30] == 2.0 and h[105] == 10.0
    assert v[100] == 10.0 and v[200] == 20.0  # exact samples are always kept
    assert not np.isnan(v[31]) and np.isnan(v[32])


def test_fixed_rescale_maps_source_normal_into_plant_normal():
    """One fixed affine map per tag; the source's normal operating values land inside the
    plant's normal band (so a real excursion is an excursion on the plant too)."""
    keys = [m.key for m in (*rs.METROPT3_MAPS, *rs.UCI_MAPS, rs.IMS_MAP)]
    assert len(keys) == len(set(keys))
    src_normal = {  # source values from docs/data_inspection.md
        ("UT-AIR", "header_pressure_bar"): (8.0, 10.0),
        ("UT-AIR", "oil_temp_c"): (50.0, 75.0),
        ("ST10-PRS", "hyd_pressure_bar"): (146.5, 191.4),
        ("ST10-PRS", "motor_current_a"): (2337.0, 2937.0),
        ("ST10-PRS", "oil_temp_c"): (35.5, 44.0),
        ("ST10-PRS", "vibration_rms_mms"): (0.5, 0.65),
        ("ST50-CNV", "vibration_rms_mms"): (0.07, 0.08),
    }
    maps = {m.key: m for m in (*rs.METROPT3_MAPS, *rs.UCI_MAPS, rs.IMS_MAP)}
    for key, (lo, hi) in src_normal.items():
        spec = plant.TAG_SPECS[key]
        y = maps[key].apply(np.array([lo, hi]))
        assert spec.normal_lo <= y.min() and y.max() <= spec.normal_hi, (key, y)
    # loaded compressor current maps inside the band, the source maximum stays below the alarm
    cur = maps[("UT-AIR", "compressor_current_a")]
    assert 30 <= cur.apply(np.array([5.6]))[0] <= 100
    assert cur.apply(np.array([9.3]))[0] < plant.tag_spec("UT-AIR", "compressor_current_a").alarm_hi
    # the source's own 7 bar low-pressure switch maps onto the header alarm limit
    hdr = maps[("UT-AIR", "header_pressure_bar")].apply(np.array([7.0]))[0]
    assert hdr == pytest.approx(plant.tag_spec("UT-AIR", "header_pressure_bar").alarm_lo, abs=0.06)


def test_timemap_reads_source_clock_as_plant_local_time():
    tm = rs.TimeMap(2300)
    src = datetime(2020, 4, 18, 6, 0, 0)
    p = tm.to_plant(src)
    local = p + timedelta(seconds=plant.PLANT_UTC_OFFSET_S)
    assert (local.hour, local.minute) == (6, 0)
    assert (local.date() - src.date()).days == 2300
    assert int(tm.epoch(np.array([src], dtype="datetime64[s]"))[0]) == int(p.timestamp())


def test_metropt3_failure_reports_become_source_work_orders():
    wos, labels = rs.metropt3_work_orders()
    assert len(wos) == 4 == len(labels)
    assert {w["asset_id"] for w in wos} == {"UT-AIR"} and {w["source_id"] for w in wos} == {
        "metropt3"
    }
    assert {lb["kind"] for lb in labels} == {"source_report"}  # never in the recent-WO pool
    reports = {r.report for r in rs.METROPT3_FAILURES if r.report}
    assert reports <= {w["action"] for w in wos}  # verbatim, incl. the "30Apr" typo
    from simulator.text_artifacts import WO_END, WO_START

    assert all(WO_START <= w["date"] <= WO_END for w in wos)
    assert len({w["wo_id"] for w in wos}) == 4


def test_uci_conditions_are_single_component_labels():
    for name, c in rs.UCI_CONDITIONS.items():
        off = [
            i
            for i, (v, ok) in enumerate(zip(c["label"], (100, 100, 0, 130), strict=True))
            if v != ok
        ]
        assert len(off) == 1, name


@pytest.mark.skipif(not (RAW / "uci_hydraulic" / "profile.txt").exists(), reason="no UCI raw data")
def test_uci_cycles_match_profile_labels():
    prof = pd.read_csv(RAW / "uci_hydraulic" / "profile.txt", sep="\t", header=None).to_numpy(int)
    for c in rs.UCI_HEALTHY:
        assert tuple(prof[c][:4]) == (100, 100, 0, 130) and prof[c][4] == 0
    for name, cond in rs.UCI_CONDITIONS.items():
        for c in cond["cycles"]:
            assert tuple(prof[c][:4]) == cond["label"], (name, c)
        stable = [c for c in cond["cycles"] if prof[c][4] == 0]
        assert len(stable) >= 10, name
        if name != "cooler_near_failure":  # the cooler uses the rig's real warm-up (flag 1) first
            assert len(stable) == len(cond["cycles"]), name


# --- unit: audio placement -------------------------------------------------------------------
def _fake_pool():
    pool = {}
    for mtype in ("pump", "fan", "slider", "valve"):
        for mid in ("id_00", "id_02", "id_04", "id_06"):
            pool[(mtype, mid)] = {
                lab: [
                    audio_mod.SourceClip(
                        mtype,
                        mid,
                        lab,
                        f"6_dB/{mtype}/{mid}/{lab}/{k:08d}.wav",
                        f"{mtype}{mid}{lab}{k}",
                    )
                    for k in range(12)
                ]
                for lab in ("normal", "abnormal")
            }
    return pool


def test_audio_plan_one_abnormal_clip_after_fault_is_audible():
    stop = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
    start = stop - timedelta(days=7)
    hint = audio_mod.Hint("ST40-SLR", "pump", stop - timedelta(hours=5))
    a = audio_mod.plan("S999", 7, start, stop, [hint], _fake_pool(), noisy=True)
    b = audio_mod.plan("S999", 7, start, stop, [hint], _fake_pool(), noisy=True)
    assert a == b  # deterministic
    assert {p.asset_id for p in a} == set(audio_mod.AUDIO_ASSETS)
    ab = [p for p in a if p.src.label == "abnormal"]
    assert len(ab) == 1 and ab[0].asset_id == "ST40-SLR" and ab[0].ts >= hint.from_ts
    for p in a:
        assert start <= p.ts and p.ts + timedelta(seconds=10) <= stop
        if p.asset_id == "ST40-SLR" and p.src.label == "normal":
            assert p.ts < hint.from_ts  # earlier clips on the faulty asset are pre-fault
    ids = {p.asset_id: {q.src.machine_id for q in a if q.asset_id == p.asset_id} for p in a}
    assert all(len(v) == 1 for v in ids.values())  # one machine id per asset
    assert ids["ST20-WLD"] != ids["ST30-WLD"]  # two different fans
    noisy = [p for p in a if p.noisy]
    assert len(noisy) == 1 and noisy[0].src.label == "normal" and noisy[0].asset_id != "ST40-SLR"


def test_noisy_clip_one_per_block_of_ten():
    ids = [f"S{i:03d}" for i in range(1, 61)] + R_IDS
    picked = audio_mod.noisy_scenarios(ids)
    assert len(picked) == 8  # 6 S blocks + R001-R010 + R011-R017
    for blk in range(6):
        assert sum(f"S{blk * 10 + 1:03d}" <= s <= f"S{blk * 10 + 10:03d}" for s in picked) == 1


def test_noise_reaches_the_target_snr():
    rng = np.random.default_rng(0)
    y = 0.05 * rng.standard_normal(audio_mod.SAMPLE_RATE_HZ * 2)
    z = audio_mod.add_noise(y, "ab" * 10)
    snr = 10 * np.log10(np.mean(y**2) / np.mean((z - y) ** 2))
    assert snr == pytest.approx(audio_mod.NOISY_SNR_DB, abs=0.05)


# --- integration: generated R-set ------------------------------------------------------------
@need_r
@pytest.mark.parametrize("sid", R_IDS)
def test_every_real_segment_has_provenance(sid):
    tel = _load(sid, "telemetry.parquet")
    prov = _load(sid, "provenance.parquet")
    real = prov[(prov.source_id != "synthetic") & (prov.tag != "audio")]
    assert not real.empty, f"{sid} has no real-sourced segment"
    assert real.source_ref.str.len().gt(20).all() and real["transform"].str.len().gt(20).all()
    real_keys = set(zip(real.asset_id, real.tag, strict=True))
    for (aid, tag), g in tel.groupby(["asset_id", "tag"], observed=True):
        p = prov[(prov.asset_id == aid) & (prov.tag == tag)]
        assert not p.empty, (sid, aid, tag)
        if (aid, tag) in real_keys:
            assert set(p.source_id) == {
                real[(real.asset_id == aid) & (real.tag == tag)].source_id.iloc[0]
            }
            t = g.ts.to_numpy(dtype="datetime64[s]").astype(np.int64)
            t0 = p.t0.to_numpy(dtype="datetime64[s]").astype(np.int64)
            t1 = p.t1.to_numpy(dtype="datetime64[s]").astype(np.int64)
            i = np.searchsorted(t0, t, side="right") - 1
            assert (i >= 0).all() and (t < t1[i]).all(), (
                f"{sid} {aid}.{tag}: real rows outside provenance"
            )
        else:
            assert set(p.source_id) == {"synthetic"}
    # every clip has a mimii provenance row at its timestamp
    idx = _load(sid, "audio_index.json")
    aud = prov[prov.tag == "audio"]
    assert len(aud) == len(idx["clips"]) and set(aud.source_id) == {"mimii"}
    got = {(r.asset_id, r.t0.to_pydatetime()) for r in aud.itertuples()}
    assert got == {(c["asset_id"], _p(c["ts"])) for c in idx["clips"]}


@need_r
def test_ims_provenance_points_at_raw_snapshots_in_gcs():
    for sid in ("R015", "R016", "R017"):
        prov = _load(sid, "provenance.parquet")
        vib = prov[(prov.source_id == "ims_bearings")]
        assert len(vib) > 400 and set(vib.tag) == {"vibration_rms_mms"}
        assert (
            vib["transform"]
            .str.contains(rf"gs://[^ ]+/vibration/{sid}/\d{{8}}T\d{{6}}Z\.txt")
            .all()
        )
        assert (
            vib["transform"].str.contains("20 kHz").all()
            and vib.source_ref.str.contains("2nd_test/").all()
        )
        vi = _load(sid, "vibration_index.json")
        assert len(vi["snapshots"]) == len(vib) and {
            s["sample_rate_hz"] for s in vi["snapshots"]
        } == {20000}


@need_r
def test_rset_truth_comes_only_from_source_labels():
    for sid in R_IDS:
        t = _load(sid, "truth.json")
        meta = _load(sid, "sim_meta.json")
        assert t["scenario_set"] == "real_signal" and t["truth_source"] == "source_label", sid
        assert t["distractors"] == [] and t["secondary_cause"] is None
        assert t["seed"] == 2026 * 1000 + rs.SEED_OFFSET + int(sid[1:])
        days = meta["real"]["time_shift_days"]
        if sid <= "R004":
            r = rs.METROPT3_FAILURES[int(sid[1:]) - 1]
            want = rs.TimeMap(days).to_plant(r.start)
            assert (t["root_cause_class"], t["asset_id"]) == ("air_pressure_drop", "UT-AIR")
            assert _p(t["onset_ts"]) == want, f"{sid}: onset must be the failure-report start"
            assert (
                want < _p(t["stop_ts"]) <= rs.TimeMap(days).to_plant(r.end) + timedelta(seconds=1)
            )
        elif sid <= "R008":
            assert (
                t["root_cause_class"] == "no_fault"
                and t["onset_ts"] is None
                and t["asset_id"] is None
            )
        elif sid <= "R014":
            uci = meta["real"]["uci"][0]
            cond = rs.R_SPECS[int(sid[1:]) - 1].condition
            assert uci["condition"] == cond
            if cond:
                assert t["root_cause_class"] == "hydraulic_degradation" and t["detail"] == cond
                assert t["asset_id"] == "ST10-PRS"
                onset = _p(t["onset_ts"])
                assert int(onset.timestamp()) == uci["onset_epoch"]
                # the fault cycles run exactly from the onset to the stop
                assert (_p(t["stop_ts"]) - onset).total_seconds() == 60 * len(
                    rs.UCI_CONDITIONS[cond]["cycles"]
                )
            else:
                assert t["root_cause_class"] == "no_fault" and t["onset_ts"] is None
        else:
            if sid == "R015":
                assert t["root_cause_class"] == "no_fault"
            else:
                # the IMS readme names the failure but documents no onset time: none is invented
                assert t["root_cause_class"] == "conveyor_bearing_defect" and t["onset_ts"] is None
                assert t["asset_id"] == "ST50-CNV" and rs.IMS_DETAIL in t["detail"]


@need_r
@pytest.mark.parametrize("sid", R_IDS[:8])
def test_no_interpolation_across_real_gaps(sid):
    tel = _load(sid, "telemetry.parquet")
    prov = _load(sid, "provenance.parquet")
    for m in rs.METROPT3_MAPS:
        ts = np.sort(
            tel[(tel.asset_id == m.asset_id) & (tel.tag == m.tag)]
            .ts.to_numpy("datetime64[s]")
            .astype(np.int64)
        )
        segs = prov[(prov.asset_id == m.asset_id) & (prov.tag == m.tag)].sort_values("t0")
        n_in = 0
        for r in segs.itertuples():
            a, b = int(r.t0.timestamp()), int(r.t1.timestamp())
            inside = ts[(ts >= a) & (ts < b)]
            assert len(inside) == b - a, (
                f"{sid} {m.tag}: segment {r.t0}-{r.t1} is not gap-free at 1 Hz"
            )
            n_in += len(inside)
        assert n_in == len(ts), f"{sid} {m.tag}: rows outside real segments"
        # between segments there are no rows, and every such gap is longer than the bridge limit
        gaps = np.diff(ts)
        assert ((gaps == 1) | (gaps > rs.MAX_BRIDGE_S)).all()


@need_r
@pytest.mark.skipif(
    not (RAW / "metropt3" / rs.METROPT3_CSV).exists(), reason="no MetroPT-3 raw data"
)
def test_real_rows_exist_only_between_close_source_samples():
    """Independent re-derivation from the CSV for one scenario: a 1 Hz row exists iff it sits on
    a source sample or between two source samples <= MAX_BRIDGE_S apart."""
    sid = "R002"
    meta = _load(sid, "sim_meta.json")
    tm = rs.TimeMap(meta["real"]["time_shift_days"])
    df = pd.read_csv(
        RAW / "metropt3" / rs.METROPT3_CSV, usecols=["timestamp", "TP3"], parse_dates=["timestamp"]
    )
    src = tm.epoch(df["timestamp"])
    tel = _load(sid, "telemetry.parquet")
    ts = tel[(tel.asset_id == "UT-AIR") & (tel.tag == "header_pressure_bar")].ts
    got = set(ts.to_numpy("datetime64[s]").astype(np.int64).tolist())
    first, hi = min(got), max(got)
    s = src[(src >= first - 3600) & (src <= hi + 60)]
    want: set[int] = set()
    for a, b in itertools.pairwise(s):
        if b - a <= rs.MAX_BRIDGE_S:
            want.update(range(int(a), int(b) + 1))
        else:
            want.update((int(a), int(b)))
    want = {t for t in want if first <= t <= hi}
    assert got == want
    # and the values are the fixed affine map of TP3 at the source samples
    v = tel[(tel.asset_id == "UT-AIR") & (tel.tag == "header_pressure_bar")].set_index("ts")[
        "value"
    ]
    on = df[(src >= first) & (src <= hi)].iloc[:50]
    for row, t in zip(on.itertuples(), tm.epoch(on["timestamp"]), strict=True):
        assert v[pd.Timestamp(int(t), unit="s", tz="UTC")] == pytest.approx(
            0.55 * row.TP3 + 1.8, abs=0.006
        )


@need_r
def test_source_gaps_are_recorded_as_imperfections():
    for sid in R_IDS[:8]:
        t = _load(sid, "truth.json")
        gaps = [Imperfection.parse(x) for x in t["imperfections"] if x.startswith("source_gap|")]
        assert gaps, sid
        tel = _load(sid, "telemetry.parquet")
        ts = np.sort(
            tel[(tel.asset_id == "UT-AIR") & (tel.tag == "header_pressure_bar")]
            .ts.to_numpy("datetime64[s]")
            .astype(np.int64)
        )
        holes = [(int(a) + 1, int(b)) for a, b in itertools.pairwise(ts) if b - a > 1]
        recorded = {(int(g.t0.timestamp()), int(g.t1.timestamp())) for g in gaps}
        assert set(holes) <= recorded, sid


@need_r
def test_rescale_is_fixed_per_tag_across_scenarios():
    seen: dict[tuple[str, str, str], set[str]] = {}
    for sid in R_IDS:
        prov = _load(sid, "provenance.parquet")
        for r in prov[(prov.source_id != "synthetic") & (prov.tag != "audio")].itertuples():
            m = re.search(r"fixed affine y = [^;]+", r.transform)
            assert m, (sid, r.tag)
            seen.setdefault((r.source_id, r.asset_id, r.tag), set()).add(m.group(0))
    assert len(seen) == 8  # 3 MetroPT-3 + 4 UCI + 1 IMS tags
    for k, v in seen.items():
        assert len(v) == 1, f"{k} rescaled differently across scenarios: {v}"


@need_r
def test_air_leak_root_precedes_downstream_and_stop_is_explained():
    for sid in R_IDS[:4]:
        t = _load(sid, "truth.json")
        meta = _load(sid, "sim_meta.json")
        on = {a: _p(x) for a, x in meta["primary"]["asset_onsets"].items()}
        assert t["causal_chain"][0] == "UT-AIR"
        assert all(on[a] >= on["UT-AIR"] for a in t["causal_chain"])
        se = _load(sid, "stop_event.json")
        assert se["stop_code"] in ("S-ST20-AIR-HOLD", "S-ST20-AIR-LO", "S-ST30-AIR-LO")


@need_r
@pytest.mark.parametrize("sid", R_IDS)
def test_rset_visible_files_never_name_the_cause(sid):
    """Agent-visible files carry no cause class, no source label and no failure dates. (Background
    historical work orders may mention leaks etc. - that is plant history, as in the S-set.)"""
    classes = [c.value for c in CauseClass] + ["abnormal"]
    source_words = [
        "leak", "cooler", "accumulator", "valve %", "pump leakage", "stable flag", "optimal",
        "outer race", "failure report", "high stress", "near_failure", "degrading", "healthy",
        "2020-04-18", "2020-05-29", "2020-05-30", "2020-06-0", "2020-07-15",
    ]  # fmt: skip
    blob = (SCEN / sid / "stop_event.json").read_text().lower()
    blob += (SCEN / sid / "audio_index.json").read_text().lower()
    if (SCEN / sid / "vibration_index.json").exists():
        blob += (SCEN / sid / "vibration_index.json").read_text().lower()
    for name in ("alarms", "shift_notes", "provenance"):
        blob += json.dumps(_load(sid, f"{name}.parquet").astype(str).to_dict("records")).lower()
    wos = json.dumps(_load(sid, "work_orders.parquet").astype(str).to_dict("records")).lower()
    hits = [w for w in classes if w in blob or w in wos] + [w for w in source_words if w in blob]
    assert not hits, f"{sid}: {hits} leak into agent-visible files"


@need_r
def test_sanity_png_per_r_scenario():
    for sid in R_IDS:
        p = ROOT / "docs" / "rset_inspection" / f"{sid}.png"
        assert p.exists() and p.stat().st_size > 10_000, sid


# --- integration: audio (S + R) --------------------------------------------------------------
def _audio_dirs() -> list[Path]:
    if not SCEN.exists():
        return []
    return sorted(d for d in SCEN.iterdir() if (d / "audio_index.json").exists())


@pytest.mark.skipif(not _audio_dirs(), reason="audio not placed (simulator.audio)")
def test_audio_index_exposes_no_label():
    dirs = _audio_dirs()
    n_noisy = 0
    for d in dirs:
        txt = (d / "audio_index.json").read_text().lower()
        assert "normal" not in txt and "abnormal" not in txt, d.name  # 'abnormal' contains 'normal'
        prov = pq.read_table(d / "provenance.parquet").to_pandas()
        aud = prov[prov.tag == "audio"]
        blob = " ".join(aud.source_ref) + " " + " ".join(aud["transform"])
        assert "normal" not in blob.lower(), d.name
        truth = json.loads((d / "audio_truth.json").read_text())
        meta = json.loads((d / "sim_meta.json").read_text())
        hints = audio_mod.hints_from_meta(meta)
        ab = [c for c in truth["clips"] if c["label"] == "abnormal"]
        assert len(ab) == len(hints), d.name
        for h in hints:
            got = [c for c in ab if c["asset_id"] == h.asset_id]
            assert len(got) == 1 and _p(got[0]["ts"]) >= h.from_ts, d.name
        n_noisy += sum(c["noisy_normal"] for c in truth["clips"])
        assert all(c["label"] == "normal" for c in truth["clips"] if c["noisy_normal"])
    names = [d.name for d in dirs]
    assert n_noisy == len(audio_mod.noisy_scenarios(names) & set(names))


def test_hidden_audio_truth_never_read_by_agents_or_loaded():
    from simulator.load import NEVER_LOAD

    assert "audio_truth.json" in NEVER_LOAD
    for pkg in ("agents", "api"):
        for f in (ROOT / pkg).rglob("*.py"):
            assert "audio_truth" not in f.read_text(), f
