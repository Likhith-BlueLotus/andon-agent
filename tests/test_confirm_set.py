"""C-set: the pre-registered confirmation set (eval/preregistration_confirm.md).

Same construction rules as the R-set (ADR-018), so the generic R checks are reused on C scenarios;
on top: the source segments are disjoint from every R scenario's, truth comes only from the source
labels, labels never reach agent-visible files, and IDs do not leak the cause.

Unit tests run anywhere; integration tests skip if the C (or R) scenarios were not generated, and
raw-data cross-checks skip without data/raw."""

from __future__ import annotations

import itertools
import json
import re
from collections import Counter
from datetime import timedelta

import numpy as np
import pandas as pd
import pytest

import tests.test_real_signals as rtest
from simulator import plant
from simulator import real_signals as rs

ROOT, SCEN, RAW = rtest.ROOT, rtest.SCEN, rtest.RAW
C_IDS = [f"C{i:03d}" for i in range(1, 11)]
HAVE_C = all((SCEN / sid / "truth.json").exists() for sid in C_IDS)
need_c = pytest.mark.skipif(
    not HAVE_C, reason="C-set not generated (simulator.real_signals --set C)"
)
need_rc = pytest.mark.skipif(
    not (HAVE_C and rtest.HAVE_R), reason="R- and C-set not both generated"
)
HAVE_MP = (RAW / "metropt3" / rs.METROPT3_CSV).exists()
_p, _load = rtest._p, rtest._load


# --- unit: the specification -----------------------------------------------------------------
def test_c_specs_are_deterministic_shuffled_and_balanced():
    assert rs._confirm_specs() == rs.C_SPECS  # same seed, same ids
    assert [s.sid for s in rs.C_SPECS] == C_IDS
    kinds = Counter(s.kind for s in rs.C_SPECS)
    assert kinds == {"metropt3_normal": 5, "uci": 5}
    # the ID order is a shuffle, not the construction order (an ID never leaks its cause)
    assert [s.kind for s in rs.C_SPECS] != sorted(s.kind for s in rs.C_SPECS)
    assert [s.kind for s in rs.C_SPECS] != sorted((s.kind for s in rs.C_SPECS), reverse=True)
    uci = [s for s in rs.C_SPECS if s.kind == "uci"]
    assert sorted(s.condition for s in uci) == sorted(rs.CONFIRM_UCI_CONDITIONS)
    assert all(s.benign is None for s in uci)
    assert all(s.benign and s.floor and s.normal_stop for s in rs.C_SPECS if s.kind != "uci")


def test_c_uci_conditions_are_new_and_cover_every_unused_stable_condition():
    used_by_r = {s.condition for s in rs.R_SPECS if s.condition}
    assert not used_by_r & set(rs.CONFIRM_UCI_CONDITIONS)
    r_cycles = {c for n in used_by_r for c in rs.UCI_CONDITIONS[n]["cycles"]}
    for n in rs.CONFIRM_UCI_CONDITIONS:
        assert not r_cycles & set(rs.UCI_CONDITIONS[n]["cycles"]), n
        assert len(rs.UCI_CONDITIONS[n]["cycles"]) == 10  # run once, never repeated (ADR-018)


@pytest.mark.skipif(not (RAW / "uci_hydraulic" / "profile.txt").exists(), reason="no UCI raw data")
def test_c_uci_selection_rule_against_profile():
    """Every stable single-component condition in profile.txt is in R or C, except cooler 20 %
    (excluded: no warm-up into it; the splice would be a ~9 degC step)."""
    prof = pd.read_csv(RAW / "uci_hydraulic" / "profile.txt", sep="\t", header=None).to_numpy(int)
    opt = np.array([100, 100, 0, 130])
    labels = {
        tuple(int(v) for v in row[:4])
        for row in prof
        if row[4] == 0 and (row[:4] != opt).sum() == 1
    }
    have = {c["label"] for c in rs.UCI_CONDITIONS.values()}
    assert labels - have == {(20, 100, 0, 130)}


def _r_metropt_windows() -> list[tuple]:
    """Source-time [start, end] of every R MetroPT-3 window (7 d history; failures end at the
    report end at the latest; one extra hour each side for the grid margin)."""
    out = []
    for s in rs.R_SPECS:
        if s.kind == "metropt3_normal":
            out.append((s.normal_stop - timedelta(seconds=rs.HISTORY_S), s.normal_stop))
        elif s.kind == "metropt3_failure":
            out.append((s.report.start - timedelta(seconds=rs.HISTORY_S), s.report.end))
    return out


def test_c_metropt_windows_follow_the_r_rules_and_avoid_r_windows():
    episodes = (  # unlabelled continuous-load episodes (docs/data_inspection.md, Part E)
        ("2020-03-12 04:00", "2020-03-12 12:10"), ("2020-03-27 11:00", "2020-03-27 11:55"),
        ("2020-03-29 01:00", "2020-03-29 19:55"), ("2020-04-12 15:35", "2020-04-12 23:50"),
        ("2020-05-13 17:35", "2020-05-14 01:20"), ("2020-05-20 02:05", "2020-05-20 19:50"),
        ("2020-06-22 18:55", "2020-06-25 05:30"),
    )  # fmt: skip
    for stop, floor in rs.METROPT3_CONFIRM_STOPS:
        start = max(floor, stop - timedelta(seconds=rs.HISTORY_S))
        assert (stop - start) >= timedelta(days=4.5)
        for r in rs.METROPT3_FAILURES:  # stop >= 3 weeks from any reported failure
            assert abs(stop - r.start) >= timedelta(days=21) and abs(stop - r.end) >= timedelta(
                days=21
            )
        for a, b in episodes:
            assert stop <= pd.Timestamp(a) or start >= pd.Timestamp(b), (stop, a)
        for a, b in _r_metropt_windows():
            assert stop <= a - timedelta(minutes=30) or start >= b, (stop, a, b)
    stops = sorted(rs.METROPT3_CONFIRM_STOPS)
    for (s1, _), (s2, f2) in itertools.pairwise(stops):  # C windows disjoint, too
        assert max(f2, s2 - timedelta(seconds=rs.HISTORY_S)) >= s1


@pytest.mark.skipif(not HAVE_MP, reason="no MetroPT-3 raw data")
def test_c_metropt_histories_never_trigger_the_hold_rule():
    df = rs.load_metropt3(RAW)
    for stop, floor in rs.METROPT3_CONFIRM_STOPS:
        start = max(floor, stop - timedelta(seconds=rs.HISTORY_S))
        assert rs.hold_rule_fire(df, start, stop) is None, stop


# --- integration: generated C-set ------------------------------------------------------------
@need_c
@pytest.mark.parametrize("sid", C_IDS)
def test_every_real_segment_has_provenance(sid):
    rtest.test_every_real_segment_has_provenance(sid)


@need_c
@pytest.mark.parametrize("sid", C_IDS)
def test_visible_files_never_name_the_cause_or_source_label(sid):
    rtest.test_rset_visible_files_never_name_the_cause(sid)
    blob = (SCEN / sid / "stop_event.json").read_text()
    blob += json.dumps(_load(sid, "provenance.parquet").astype(str).to_dict("records"))
    # no source date (MetroPT-3 windows could be matched against the failure table), no UCI
    # label text, no condition names
    assert not re.search(r"\b2020-\d\d-\d\d", blob), sid
    for word in [
        *rs.CONFIRM_UCI_CONDITIONS,
        "small lag",
        "severe lag",
        "reduced pressure",
        "weak leakage",
        "close to total",
    ]:
        assert word not in blob.lower(), (sid, word)


@need_c
def test_c_truth_comes_only_from_source_labels():
    specs = {s.sid: s for s in rs.C_SPECS}
    for sid in C_IDS:
        t, meta, spec = _load(sid, "truth.json"), _load(sid, "sim_meta.json"), specs[sid]
        assert t["scenario_set"] == "real_signal" and t["truth_source"] == "source_label", sid
        assert t["distractors"] == [] and t["secondary_cause"] is None
        assert t["seed"] == 2026 * 1000 + rs.SEED_OFFSET_C + int(sid[1:])
        assert meta["set"] == "C" and meta["source_kind"] == spec.kind
        if spec.kind == "metropt3_normal":
            assert (t["root_cause_class"], t["asset_id"], t["onset_ts"]) == ("no_fault", None, None)
            assert t["variant"] == "no_fault" and t["causal_chain"] == []
            assert meta["real"]["normal_stop_src"] == str(spec.normal_stop)
            se = _load(sid, "stop_event.json")
            tm = rs.TimeMap(meta["real"]["time_shift_days"])
            assert _p(se["stop_ts"]) == tm.to_plant(spec.normal_stop)
        else:
            uci = meta["real"]["uci"][0]
            assert uci["condition"] == spec.condition == t["detail"]
            assert (t["root_cause_class"], t["asset_id"]) == ("hydraulic_degradation", "ST10-PRS")
            onset = _p(t["onset_ts"])
            assert int(onset.timestamp()) == uci["onset_epoch"]
            assert (_p(t["stop_ts"]) - onset).total_seconds() == 600  # 10 labelled cycles, once


@need_c
def test_c_metropt_rows_start_at_the_history_floor():
    """No real row before max(floor, stop - 7 d) (provenance and telemetry agree)."""
    for spec in (s for s in rs.C_SPECS if s.kind == "metropt3_normal"):
        meta = _load(spec.sid, "sim_meta.json")
        tm = rs.TimeMap(meta["real"]["time_shift_days"])
        start = tm.to_plant(max(spec.floor, spec.normal_stop - timedelta(seconds=rs.HISTORY_S)))
        se = _load(spec.sid, "stop_event.json")
        assert _p(se["history_start"]) == start
        tel = _load(spec.sid, "telemetry.parquet")
        prov = _load(spec.sid, "provenance.parquet")
        for m in rs.METROPT3_MAPS:
            ts = tel[(tel.asset_id == m.asset_id) & (tel.tag == m.tag)].ts
            assert ts.min().to_pydatetime() >= start
            p = prov[(prov.asset_id == m.asset_id) & (prov.tag == m.tag)]
            assert p.t0.min().to_pydatetime() >= start


@need_rc
def test_c_source_segments_are_disjoint_from_every_r_scenario():
    """Source rows (MetroPT-3) and fault cycles (UCI) of C never appear in any R scenario. The
    looped healthy UCI background (cycles 1787-1796) is the only shared source data: it is the
    rig's only stable all-optimal run (ADR-018 rule 3)."""

    def spans(ids: list[str]) -> dict[str, set[tuple[int, int]]]:
        out: dict[str, set[tuple[int, int]]] = {"metropt3": set(), "uci": set()}
        for sid in ids:
            prov = _load(sid, "provenance.parquet")
            for ref in prov[prov.source_id.isin(["metropt3", "uci_hydraulic"])].source_ref:
                if m := re.search(r"rows index (\d+)-(\d+)", ref):
                    out["metropt3"].add((int(m[1]), int(m[2])))
                elif m := re.search(r"rows \(cycles\) (\d+)-(\d+)", ref):
                    out["uci"].add((int(m[1]), int(m[2])))
        return out

    r, c = spans(rtest.R_IDS), spans(C_IDS)
    assert c["metropt3"] and c["uci"]
    for src in ("metropt3", "uci"):
        for a0, a1 in c[src]:
            for b0, b1 in r[src]:
                if src == "uci" and (a0, a1) == (b0, b1) == (rs.UCI_HEALTHY[0], rs.UCI_HEALTHY[-1]):
                    continue
                assert a1 < b0 or b1 < a0, (src, (a0, a1), (b0, b1))
    # C windows are disjoint from each other, too
    mp = sorted(c["metropt3"])
    starts = {}
    for sid in C_IDS:
        prov = _load(sid, "provenance.parquet")
        refs = prov[prov.source_id == "metropt3"].source_ref
        idx = [int(x) for ref in refs for x in re.findall(r"rows index (\d+)-(\d+)", ref)[0]]
        if idx:
            starts[sid] = (min(idx), max(idx))
    w = sorted(starts.values())
    assert all(a[1] < b[0] for a, b in itertools.pairwise(w)) and len(mp) > 5


@need_c
@pytest.mark.skipif(not (RAW / "uci_hydraulic" / "profile.txt").exists(), reason="no UCI raw data")
def test_c_uci_fault_cycles_carry_the_source_label():
    prof = pd.read_csv(RAW / "uci_hydraulic" / "profile.txt", sep="\t", header=None).to_numpy(int)
    for spec in (s for s in rs.C_SPECS if s.kind == "uci"):
        uci = _load(spec.sid, "sim_meta.json")["real"]["uci"][0]
        want = rs.UCI_CONDITIONS[spec.condition]["label"]
        assert all(tuple(prof[c][:4]) == want and prof[c][4] == 0 for c in uci["fault_cycles"])


@need_c
def test_c_rescale_is_the_r_rescale():
    """The C-set uses the same fixed per-tag affine maps as the R-set."""
    maps = {m.key: m.describe() for m in (*rs.METROPT3_MAPS, *rs.UCI_MAPS)}
    for sid in C_IDS:
        prov = _load(sid, "provenance.parquet")
        for r in prov[prov.source_id.isin(["metropt3", "uci_hydraulic"])].itertuples():
            assert maps[(r.asset_id, r.tag)] in r.transform, (sid, r.tag)


@need_c
@pytest.mark.parametrize("sid", [s.sid for s in rs.C_SPECS if s.kind == "metropt3_normal"])
def test_c_metropt_no_interpolation_across_real_gaps(sid):
    rtest.test_no_interpolation_across_real_gaps(sid)


@need_c
def test_c_benign_stops_and_no_fault_air_context():
    """No-fault stops include air-sounding glitches; the compressor is not running continuously
    loaded at the stop (so the stop is benign by the operator's own hold rule)."""
    codes = Counter()
    for spec in (s for s in rs.C_SPECS if s.kind == "metropt3_normal"):
        se = _load(spec.sid, "stop_event.json")
        codes[se["stop_code"].split("-")[-1]] += 1
        tel = _load(spec.sid, "telemetry.parquet")
        cur = tel[(tel.asset_id == "UT-AIR") & (tel.tag == "compressor_current_a")]
        last4h = cur[cur.ts >= cur.ts.max() - pd.Timedelta(hours=4)].value
        assert (last4h > rs.HOLD_LOADED_A * 11.5).mean() < rs.HOLD_FRACTION, spec.sid
    assert codes["LL"] == 3 and sum(codes.values()) == 5
    for spec in (s for s in rs.C_SPECS if s.kind == "uci"):
        assert _load(spec.sid, "stop_event.json")["stop_code"] == "S-ST10-HYD-FLT"


@need_c
def test_c_alarm_and_wo_ids_do_not_collide_with_r():
    for sid in C_IDS:
        wos = _load(sid, "work_orders.parquet")
        n = int(sid[1:])
        assert all(
            w.startswith("WO-") and 97000 + n * 10 <= int(w[-5:]) < 97000 + n * 10 + 10
            for w in wos.wo_id
        )


@need_c
def test_sanity_png_per_c_scenario():
    for sid in C_IDS:
        p = ROOT / "docs" / "data_inspection" / "confirm_set" / f"{sid}.png"
        assert p.exists() and p.stat().st_size > 10_000, sid


def test_scenario_partition_keys_do_not_collide():
    from simulator.blobstore import SCENARIO_ID_RE
    from simulator.load import scenario_num

    ids = [f"S{i:03d}" for i in range(1, 61)] + rtest.R_IDS + C_IDS
    assert len({scenario_num(i) for i in ids}) == len(ids)
    assert all(SCENARIO_ID_RE.match(i) for i in ids)
    assert plant.LINE_ID  # the C-set lives on the same synthetic line
