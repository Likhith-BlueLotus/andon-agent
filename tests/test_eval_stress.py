"""Verifier fault injection (eval/stress_verifier.py): every fault type is caught on a hand-built
report, the unmutated report passes, injection is deterministic, outputs render. Offline, no LLM."""

from __future__ import annotations

import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from agents import tools as T
from eval import checker
from eval import stress_verifier as sv
from simulator.manuals import find_quote, normalise, pages
from simulator.manuals.premises import premises_for
from tests.llm_replay import build_store

WIN = {"t0": "2026-09-02T22:49:39Z", "t1": "2026-09-06T22:49:39Z"}


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    store = build_store(tmp_path_factory.mktemp("stress"), "S801")
    state: dict = {}
    ctx = T.ToolContext(store=store, scenario_id="S801", state=state, _lock=threading.RLock())
    for a, t in (("ST20-WLD", "air_pressure_bar"), ("UT-AIR", "header_pressure_bar")):
        T.TOOL_REGISTRY["detect_change_points"].fn(ctx, asset_id=a, tag=t, **WIN)
    evidence = [
        checker._evidence(v) | {"produced_at": "2026-01-01T00:00:00Z"}
        for v in (json_safe(x) for x in state.values())
    ]
    yield store, evidence
    store.close()


def json_safe(ev):
    d = ev.model_dump(mode="json") if hasattr(ev, "model_dump") else dict(ev)
    return d


def _plain_quote() -> tuple[str, int, str]:
    """A premise-free sentence of compressed_air with an antonym-able word."""
    for pg, text in sorted(pages("compressed_air").items()):
        for s in normalise(text).split(". "):
            s = s.strip()
            if (
                60 <= len(s) <= 200
                and "|" not in s
                and "#" not in s
                and find_quote("compressed_air", pg, s)
                and not premises_for("compressed_air", pg, s)
            ):
                return "compressed_air", pg, s
    raise AssertionError("no plain sentence")


def _report(evidence):
    ids = {e["tool"] + e["args"]["asset_id"]: e["evidence_id"] for e in evidence}
    e_w, e_a = ids["detect_change_pointsST20-WLD"], ids["detect_change_pointsUT-AIR"]
    doc, page, quote = _plain_quote()
    return {
        "incident_id": "t",
        "status": "verified",
        "hypotheses": [
            {
                "cause_class": "air_pressure_drop",
                "asset_id": "ST20-WLD",
                "confidence": 0.8,
                "causal_chain": ["ST20-WLD", "UT-AIR"],
                "refuting_evidence_ids": [],
                "claims": [
                    {
                        "claim_id": "n1",
                        "kind": "numeric",
                        "evidence_ids": [e_w],
                        "text": "Gun air pressure fell 7.262 % path: change_points[0].magnitude_pct",
                        "asserted_value": -7.262,
                    },
                    {
                        "claim_id": "n2",
                        "kind": "numeric",
                        "evidence_ids": [e_w],
                        "text": "Median was 5.6 bar before. path: change_points[0].before_mean",
                        "asserted_value": 5.6,
                    },
                    {
                        "claim_id": "t1",
                        "kind": "temporal",
                        "evidence_ids": [e_w],
                        "text": "Step began 12:26",
                        "asserted_ts": "2026-09-06T12:26:39Z",
                    },
                    {
                        "claim_id": "c1",
                        "kind": "citation",
                        "evidence_ids": [e_w],
                        "text": "Manual says so",
                        "citation": {"doc": doc, "page": page, "quote": quote},
                    },
                    {
                        "claim_id": "o1",
                        "kind": "causal_order",
                        "evidence_ids": [e_w, e_a],
                        "text": "ST20 air drop precedes the header excursion",
                    },
                    {
                        "claim_id": "q1",
                        "kind": "qualitative",
                        "evidence_ids": [e_w],
                        "text": "Looks abnormal.",
                    },
                ],
            }
        ],
    }


def test_unmutated_report_passes_and_matches_checker(env):
    store, evidence = env
    rep = _report(evidence)
    g = sv.RunGrader(evidence, store, "S801")
    v = g.verdicts(rep)
    assert {k: x["verdict"] for k, x in v.items()} == {
        c: "pass" for c in ("n1", "n2", "t1", "c1", "o1", "q1")
    }
    ind = checker.check_report(rep, evidence, store, "S801")
    assert {c["claim_id"]: c["verdict"] for c in ind["claims"]} == {
        k: x["verdict"] for k, x in v.items()
    }


def test_every_fault_type_is_caught(env):
    store, evidence = env
    truth = SimpleNamespace(
        asset_id="UT-AIR",
        causal_chain=["UT-AIR"],
        root_cause_class=SimpleNamespace(value="air_pressure_drop"),
    )
    res = sv.stress_run(_report(evidence), evidence, store, "S801", truth=truth)
    assert all(b["verdict"] == "pass" for b in res["baseline"])
    by: dict[str, list[dict]] = {}
    for t in res["trials"]:
        by.setdefault(t["fault"], []).append(t)
    for fault in sv.FAULTS:
        assert by.get(fault), f"fault {fault} produced no trials"
    for fault, ts in by.items():
        if fault == "premise_false":
            continue  # label is by construction; asserted separately below
        missed = [t for t in ts if not t["caught"]]
        assert not missed, (fault, missed)
    assert {t["variant"] for t in by["num_10"]} == {"+10%", "-10%"}
    assert len(by["fabricated_evidence"]) == 3
    # the premise faults are injected claims on a doc that does not cover the blamed asset
    assert all(t["claim_id"].startswith("zz_premise_") for t in by["premise_false"])


def test_mutations_change_exactly_one_claim(env):
    _, evidence = env
    rep = _report(evidence)
    base = {"measured": -7.262}
    claim = rep["hypotheses"][0]["claims"][0]
    muts = sv.mutations_for(rep, 0, claim, base, "s")
    assert {m[0] for m in muts} == {"num_10", "num_25", "num_sign"}
    for _, _, m in muts:
        diff = [
            (a["claim_id"])
            for a, b in zip(
                rep["hypotheses"][0]["claims"], m["hypotheses"][0]["claims"], strict=True
            )
            if a != b
        ]
        assert diff == ["n1"]
    # a claim that only passed through the sign relaxation is not sign-flipped
    flipped = sv.mutations_for(rep, 0, claim, {"measured": 7.262}, "s")
    assert "num_sign" not in {m[0] for m in flipped}


def test_alter_sentence_never_a_noop():
    for q in (
        "The header rises when the compressor loads.",
        "Check the drop leg first today.",
        "Set the limit to 12 bar on site.",
        "xxxx yyyy zzzz wwww vvvv",
    ):
        assert sv.alter_sentence(q, "s") != q


def test_deterministic_and_outputs(env, tmp_path):
    store, evidence = env
    rep = _report(evidence)
    a = sv.stress_run(rep, evidence, store, "S801", seed=7)
    b = sv.stress_run(rep, evidence, store, "S801", seed=7)
    assert a == b
    s = sv.aggregate({"S801|0": a}, {"equal": 6, "total": 6})
    s.update(source_run="unit", seed=7, n_runs=1, n_trials=s["overall"]["n"])
    assert s["overall"]["value"] == 1.0 and s["false_alarm_all_claims"]["k"] == 0
    assert s["s2"]["catch"]["k"] == 0
    md = sv.markdown(s)
    assert "S2 comparison" in md and "Number off by ±10%" in md
    png = Path(tmp_path) / "stress.png"
    sv.render_png(s, png)
    assert png.stat().st_size > 10_000
