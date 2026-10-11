"""eval/metrics.py: every EVAL_PLAN §3 metric on hand-built runs."""

from datetime import UTC, datetime

import pytest

from eval import metrics
from simulator.truth_schema import GroundTruth

T0 = datetime(2026, 8, 1, tzinfo=UTC)


def truth(sid, cls, asset, variant="clean", chain=None, secondary=None):
    return GroundTruth(
        scenario_id=sid, seed=1, scenario_set="synthetic" if sid[0] == "S" else "real_signal",
        truth_source="injected", variant=variant, root_cause_class=cls, asset_id=asset,
        onset_ts=T0, causal_chain=chain if chain is not None else ([asset] if asset else []),
        secondary_cause=secondary, distractors=[], stop_station="ST20-WLD", stop_ts=T0,
    )  # fmt: skip


def hyp(cls, asset, conf=0.8, chain=None):
    return {"cause_class": cls, "asset_id": asset, "confidence": conf,
            "causal_chain": chain if chain is not None else [asset], "claims": []}  # fmt: skip


def row(sid, hyps, system="S1", status="rca", repeat=0, usd=0.1, dur=10.0, **kw):
    rep = None if hyps is None else {"incident_id": "x", "hypotheses": hyps,
                                      "status": status if status != "rca" else "verified"}  # fmt: skip
    return {"run_key": f"{system}|{sid}|{repeat}", "system": system, "scenario_id": sid,
            "repeat": repeat, "status": "ok" if rep else "error", "report": rep,
            "cost": {"usd": usd}, "duration_s": dur, "verifier": kw.get("verifier", {}),
            "independent": kw.get("independent")}  # fmt: skip


def test_top1_needs_class_and_asset():
    t = truth("S001", "weld_tip_wear", "ST20-WLD")
    assert metrics.grade_run(row("S001", [hyp("weld_tip_wear", "ST20-WLD")]), t)["top1"]
    assert not metrics.grade_run(row("S001", [hyp("weld_tip_wear", "ST30-WLD")]), t)["top1"]
    assert not metrics.grade_run(row("S001", [hyp("servo_overheat", "ST20-WLD")]), t)["top1"]


def test_top3_and_top1_differ():
    t = truth("S001", "weld_tip_wear", "ST20-WLD")
    g = metrics.grade_run(
        row("S001", [hyp("servo_overheat", "ST20-WLD"), hyp("weld_tip_wear", "ST20-WLD")]), t
    )
    assert g["top3"] and not g["top1"]


def test_failed_run_is_a_miss_not_an_abstention():
    t = truth("S003", "no_fault", None, variant="no_fault")
    g = metrics.grade_run(row("S003", None), t)
    assert g["status"] == "error" and not g["top1"] and not g["abstained"]


def test_no_fault_truth_matches_on_class_only():
    t = truth("S003", "no_fault", None, variant="no_fault")
    assert metrics.grade_run(row("S003", [hyp("no_fault", "ST20-WLD")]), t)["top1"]


def test_abstention_definition():
    t = truth("S003", "no_fault", None, variant="no_fault")
    assert metrics.grade_run(row("S003", [hyp("sensor_drift", "ST10-PRS")]), t)["abstained"]
    assert metrics.grade_run(row("S003", [hyp("weld_tip_wear", "ST20-WLD")],
                                 status="insufficient_evidence"), t)["abstained"]  # fmt: skip
    assert metrics.grade_run(row("S003", []), t)["abstained"]
    assert not metrics.grade_run(row("S003", [hyp("weld_tip_wear", "ST20-WLD")]), t)["abstained"]


def test_chain_f1():
    t = truth("S001", "plc_timer_misconfig", "ST30-WLD", chain=["ST30-WLD", "ST20-WLD", "ST10-PRS"])
    h = hyp("plc_timer_misconfig", "ST30-WLD", chain=["ST30-WLD: timer changed", "ST20-WLD"])
    g = metrics.grade_run(row("S001", [h]), t)
    assert g["chain_f1"] == pytest.approx(2 * 1.0 * (2 / 3) / (1.0 + 2 / 3))
    assert metrics.set_f1([], []) == 1.0 and metrics.set_f1(["A"], ["B"]) == 0.0
    assert metrics.chain_assets(["ST20-WLD then ST20-WLD", "UT-AIR"]) == ["ST20-WLD", "UT-AIR"]


def test_dual_fault_secondary_and_imperfection_false_alarm():
    t = truth("S002", "changeover_error", "ST10-PRS", variant="dual_fault",
              secondary="air_pressure_drop")  # fmt: skip
    g = metrics.grade_run(row("S002", [hyp("changeover_error", "ST10-PRS"),
                                       hyp("air_pressure_drop", "UT-AIR")]), t)  # fmt: skip
    assert g["secondary_in_top3"] is True and g["imperfection_false_alarm"] is False
    g2 = metrics.grade_run(row("S002", [hyp("sensor_drift", "ST10-PRS")]), t)
    assert g2["imperfection_false_alarm"] is True
    nf = truth("S003", "no_fault", None, variant="no_fault")
    assert (
        metrics.grade_run(row("S003", [hyp("sensor_drift", "ST10-PRS")]), nf)[
            "imperfection_false_alarm"
        ]
        is None
    )


def indep(*verdicts):
    return {"claims": [{"claim_id": f"c{i}", "kind": k, "verdict": v}
                       for i, (k, v) in enumerate(verdicts)]}  # fmt: skip


def test_unsupported_claims_and_unflagged():
    t = truth("S001", "weld_tip_wear", "ST20-WLD")
    r = row("S001", [hyp("weld_tip_wear", "ST20-WLD")],
            independent=indep(("numeric", "pass"), ("numeric", "fail"), ("qualitative", "unverifiable")),
            verifier={"claim_verdicts": {"c0": "pass", "c1": "pass", "c2": "fail"}, "catches": 2})  # fmt: skip
    g = metrics.grade_run(r, t)
    assert (g["n_claims"], g["n_unsupported"]) == (3, 2)
    assert (g["n_checkable"], g["n_unsupported_checkable"]) == (2, 1)
    assert g["n_unflagged_unsupported"] == 1 and g["n_sys_pass"] == 2
    assert g["verifier_catches"] == 2


def _graded(specs):
    out = []
    for _i, (sid, tr, hy, kw) in enumerate(specs):
        out.append(metrics.grade_run(row(sid, hy, **kw), tr))
    return out


def test_summarize_all_metrics():
    ts = [
        truth("S001", "weld_tip_wear", "ST20-WLD"),
        truth("S002", "air_pressure_drop", "UT-AIR", variant="red_herring"),
        truth("S003", "no_fault", None, variant="no_fault"),
        truth("S004", "servo_overheat", "ST30-WLD"),
    ]
    rows = [
        metrics.grade_run(row("S001", [hyp("weld_tip_wear", "ST20-WLD", 0.9)], usd=0.2, dur=10), ts[0]),
        metrics.grade_run(row("S002", [hyp("air_pressure_drop", "ST20-WLD", 0.8)], usd=0.4, dur=30), ts[1]),
        metrics.grade_run(row("S003", [hyp("no_fault", "ST20-WLD", 0.6)], usd=0.0, dur=20), ts[2]),
        metrics.grade_run(row("S004", None, usd=0.0), ts[3]),
    ]  # fmt: skip
    m = metrics.summarize(rows)
    assert m["n"] == 4 and m["n_error"] == 1
    assert (m["top1"].k, m["top1"].n) == (2, 4)
    assert (m["top3"].k, m["top3"].n) == (2, 4)
    assert (m["red_herring_top1"].k, m["red_herring_top1"].n) == (0, 1)
    assert (m["abstention"]["recall"].k, m["abstention"]["recall"].n) == (1, 1)
    assert (m["abstention"]["precision"].k, m["abstention"]["precision"].n) == (1, 1)
    assert m["calibration"]["brier"] == pytest.approx(((0.1) ** 2 + 0.8**2 + 0.4**2) / 3)
    assert m["calibration"]["n"] == 3
    assert m["time_s"]["median"] == 20 and m["cost"]["mean_usd"] == pytest.approx(0.15)
    assert m["by_variant"]["red_herring"]["top1"].k == 0
    assert m["by_cause"]["weld_tip_wear"]["top1"].k == 1


def test_headline_uses_first_repeat_and_compare_mcnemar():
    t = truth("S001", "weld_tip_wear", "ST20-WLD")
    good, bad = hyp("weld_tip_wear", "ST20-WLD"), hyp("servo_overheat", "ST20-WLD")
    rows = [
        metrics.grade_run(row("S001", [good], system="S1", repeat=0), t),
        metrics.grade_run(row("S001", [bad], system="S1", repeat=1), t),
        metrics.grade_run(row("S001", [bad], system="B1"), t),
    ]
    head = metrics.headline(rows)
    assert len(head) == 2
    c = metrics.compare(head, "S1", "B1")
    assert (c["a_only"], c["b_only"]) == (1, 0) and c["n"] == 1
    assert metrics.compare(head, "S1", "B2") is None


def test_variance_spread_and_unstable():
    ts = [truth(f"S00{i}", "weld_tip_wear", "ST20-WLD") for i in range(1, 5)]
    good, bad = hyp("weld_tip_wear", "ST20-WLD"), hyp("servo_overheat", "ST20-WLD")
    rows = []
    for rep, wrong in enumerate([[], [0], [0, 1]]):
        for i, t in enumerate(ts):
            h = bad if i in wrong else good
            rows.append(metrics.grade_run(row(t.scenario_id, [h], repeat=rep), t))
    v = metrics.variance(rows, "S1")
    assert v["top1_by_repeat"] == [1.0, 0.75, 0.5]
    assert v["spread"]["range"] == pytest.approx(0.5)
    assert v["unstable_scenarios"] == ["S001", "S002"]
    assert metrics.variance(rows[:4], "S1") is None
