"""Offline tests for the deterministic Verifier (agents/verifier.py, AGENTS_SPEC §5).

Evidence is produced by the real tools on a small generated DuckDB scenario (as in
tests/test_tools.py): S801 is a synthetic air leak; R801 is the same build with the UT-AIR
provenance rows relabelled as MetroPT-3, so its UT-AIR evidence carries ``real: true`` the way the
R-set does. Ground truth is read only here, from the simulator's in-memory build result.
"""

from __future__ import annotations

import warnings
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from google.adk.agents import BaseAgent, RunConfig
from google.adk.apps import App
from google.adk.events import Event, EventActions
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

import config
from agents import tools as T
from agents import verifier as V
from agents.adk_budget import AndonBudgetPlugin
from agents.llm import LLM, SpendTracker
from agents.schemas import (
    CauseClass,
    Citation,
    Claim,
    Hypothesis,
    RCAReport,
    WorkOrder,
    WorkOrderStep,
)
from simulator import generate as gen_mod
from simulator.generate import Scenario, Slot, build, write_scenario
from simulator.imperfections import Imperfection
from simulator.load import load_duckdb
from simulator.manuals import locate_quote
from simulator.manuals.loto import LOTO
from simulator.text_artifacts import TextGen, build_work_orders

C = CauseClass
HIST = 4 * 86400
SEED = 2026801


def _iso(d: datetime) -> str:
    return d.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _p(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(UTC)


# --- fixtures --------------------------------------------------------------------------------
@pytest.fixture(scope="module")
def world(tmp_path_factory):
    root = tmp_path_factory.mktemp("verifier")
    g = TextGen(mode="template")
    wos, labels = g.run(build_work_orders(g, 200, 7, Path("/nonexistent")))
    kinds = {lb["wo_id"]: lb["kind"] for lb in labels}
    pool = [w for w in wos if kinds[w["wo_id"]] == "normal"]
    truth = None
    for sid in ("S801", "R801"):
        b = build(Scenario(sid, SEED, Slot(C.AIR_PRESSURE_DROP, "clean", 0), HIST),
                  TextGen(mode="template"), pool)  # fmt: skip
        write_scenario(root / "scenarios", sid, b)
        truth = truth or b["truth"]
    prov_path = root / "scenarios" / "R801" / "provenance.parquet"
    table = pq.read_table(prov_path)
    prov = table.to_pandas()
    air = prov["asset_id"] == "UT-AIR"
    prov.loc[air, "source_id"] = "metropt3"
    prov.loc[air, "source_ref"] = "MetroPT3 rows 1-345600 (test relabel)"
    pq.write_table(pa.Table.from_pandas(prov, schema=table.schema, preserve_index=False), prov_path)
    pq.write_table(gen_mod.wo_table(pool, None), root / "work_orders.parquet")
    store = load_duckdb(root / "scenarios", root / "andon.duckdb")
    models = tmp_path_factory.mktemp("models")
    yield store, truth, models
    store.close()


def _tctx(store, sid, models, state=None):
    return T.ToolContext(store, sid, state={} if state is None else state, model_dir=models,
                         now=lambda: datetime(2026, 10, 11, tzinfo=UTC))  # fmt: skip


@pytest.fixture(scope="module")
def ev(world) -> dict[str, Any]:
    """Evidence for S801 built by the real tools; returns ids, summaries and the state."""
    store, truth, models = world
    ctx = _tctx(store, "S801", models)
    stop = truth.stop_ts
    t0, t1 = _iso(stop - timedelta(hours=24)), _iso(stop)
    out: dict[str, Any] = {"truth": truth}
    out["cp_air"] = T.detect_change_points(ctx, asset_id="UT-AIR", tag="compressor_current_a", t0=t0, t1=t1)  # fmt: skip
    out["cp_wld"] = T.detect_change_points(ctx, asset_id="ST30-WLD", tag="air_pressure_bar", t0=t0, t1=t1)  # fmt: skip
    out["q_air"] = T.query_telemetry(ctx, asset_id="UT-AIR", tags=["header_pressure_bar", "compressor_current_a"],
                                     t0=_iso(stop - timedelta(hours=3)), t1=t1)  # fmt: skip
    out["alarms"] = T.search_alarms(ctx, line_id="L1", t0=t0, t1=_iso(stop + timedelta(minutes=10)))
    stuck = next(
        Imperfection.parse(s) for s in truth.imperfections if Imperfection.parse(s).kind == "stuck"
    )
    out["stuck_imp"] = stuck
    out["cp_stuck"] = T.detect_change_points(
        ctx, asset_id=stuck.asset_id, tag=stuck.tag,
        t0=_iso(stuck.t0 - timedelta(hours=3)), t1=_iso(stuck.t1 + timedelta(hours=2)),
    )  # fmt: skip
    for k in ("cp_air", "cp_wld", "q_air", "alarms", "cp_stuck"):
        assert out[k]["evidence_id"], (k, out[k])
    out["state"] = dict(ctx.state)
    return out


def _vctx(world, ev, sid="S801", state=None):
    store, _, models = world
    return _tctx(store, sid, models, state=dict(ev["state"]) if state is None else state)


def claim(cid, kind, eids, text="", **kw) -> Claim:
    return Claim(
        claim_id=cid, text=text or f"{kind} claim {cid}", kind=kind, evidence_ids=eids, **kw
    )


def report(
    *claims, asset="UT-AIR", chain=("UT-AIR", "ST30-WLD"), cls=C.AIR_PRESSURE_DROP, extra=()
):
    hyps = [Hypothesis(cause_class=cls, asset_id=asset, confidence=0.7, causal_chain=list(chain),
                       claims=list(claims))]  # fmt: skip
    hyps += list(extra)
    return RCAReport(incident_id="INC-S801", hypotheses=hyps, status="verified")


def one(world, ev, c: Claim, **kw):
    v, cvs = V.verify_report(report(c, **kw), _vctx(world, ev), 1)
    assert len(cvs) == 1 and v.claims == cvs
    return cvs[0]


def _first_up(ev):
    s = ev["cp_air"]["summary"]
    return next(c for c in s["change_points"] if c["direction"] == "up")


def _true_numeric(ev, cid="n1"):
    mean = ev["q_air"]["summary"]["tags"]["header_pressure_bar"]["mean"]
    return claim(cid, "numeric", [ev["q_air"]["evidence_id"]], asserted_value=mean,
                 text=f"Header pressure averaged {mean} bar (path: tags.header_pressure_bar.mean)")  # fmt: skip


def _true_temporal(ev, cid="t1", offset_s=30):
    ts = _p(_first_up(ev)["ts"]) + timedelta(seconds=offset_s)
    return claim(cid, "temporal", [ev["cp_air"]["evidence_id"]], asserted_ts=ts,
                 text="Compressor duty began rising")  # fmt: skip


# --- numeric ---------------------------------------------------------------------------------
def test_true_numeric_claim_passes(world, ev):
    cv = one(world, ev, _true_numeric(ev))
    assert cv.verdict == "pass", cv
    assert cv.measured_value == ev["q_air"]["summary"]["tags"]["header_pressure_bar"]["mean"]


def test_implicit_numeric_match_and_percent_and_sign(world, ev):
    cp = _first_up(ev)
    eid = ev["cp_air"]["evidence_id"]
    # no path: matched against all numeric leaves
    cv = one(world, ev, claim("n", "numeric", [eid], asserted_value=cp["after_mean"],
                              text="Duty rose after the onset"))  # fmt: skip
    assert cv.verdict == "pass" and "change_points" in cv.reason, cv
    # fraction stated as percent
    lf = ev["q_air"]["summary"]["tags"]["compressor_current_a"]["loaded_fraction"]
    cv = one(world, ev, claim("p", "numeric", [ev["q_air"]["evidence_id"]], asserted_value=lf * 100,
                              text=f"Compressor loaded {lf * 100:.1f}% of the time "
                                   "(path: tags.compressor_current_a.loaded_fraction)"))  # fmt: skip
    assert cv.verdict == "pass" and "percent" in cv.reason, cv
    # sign: a negative delta stated as a positive drop passes only with consistent direction words
    wcp = ev["cp_wld"]["summary"]["change_points"][0]
    assert wcp["delta"] < 0
    weid = ev["cp_wld"]["evidence_id"]
    path = "path: change_points[0].delta"
    ok = one(world, ev, claim("s1", "numeric", [weid], asserted_value=abs(wcp["delta"]),
                              text=f"Gun air pressure dropped by {abs(wcp['delta'])} bar ({path})"))  # fmt: skip
    assert ok.verdict == "pass", ok
    bad = one(world, ev, claim("s2", "numeric", [weid], asserted_value=abs(wcp["delta"]),
                               text=f"Gun air pressure rose by {abs(wcp['delta'])} bar ({path})"))  # fmt: skip
    assert bad.verdict == "fail", bad


def test_inflated_number_fails_with_measured_value(world, ev):
    mean = ev["q_air"]["summary"]["tags"]["header_pressure_bar"]["mean"]
    c = _true_numeric(ev).model_copy(update={"asserted_value": round(mean * 1.3, 3)})
    cv = one(world, ev, c)
    assert cv.verdict == "fail" and cv.measured_value == mean
    assert "tags.header_pressure_bar.mean" in cv.reason and ev["q_air"]["evidence_id"] in cv.reason
    # implicit form: the closest leaf is reported with its path
    cv = one(world, ev, c.model_copy(update={"text": "Header pressure averaged far higher"}))
    assert cv.verdict == "fail" and cv.measured_value is not None and "closest" in cv.reason


def test_unresolvable_path_and_missing_value(world, ev):
    eid = ev["q_air"]["evidence_id"]
    cv = one(
        world, ev, claim("x", "numeric", [eid], asserted_value=1.0, text="x (path: tags.nope.mean)")
    )
    assert cv.verdict == "fail" and "not a numeric field" in cv.reason
    assert one(world, ev, claim("y", "numeric", [eid])).verdict == "unverifiable"
    assert one(world, ev, claim("z", "numeric", [], asserted_value=1.0)).verdict == "fail"


def test_rerun_mismatch_means_not_reproducible(world, ev):
    state = dict(ev["state"])
    key = "evidence:" + ev["q_air"]["evidence_id"]
    tampered = {**state[key], "summary": {**state[key]["summary"]}}
    tags = {**tampered["summary"]["tags"]}
    tags["header_pressure_bar"] = {**tags["header_pressure_bar"], "mean": 99.0}
    tampered["summary"]["tags"] = tags
    state[key] = tampered
    c = _true_numeric(ev).model_copy(update={"asserted_value": 99.0})
    _, cvs = V.verify_report(report(c), _vctx(world, ev, state=state), 1)
    assert cvs[0].verdict == "fail" and "not reproducible" in cvs[0].reason


# --- temporal --------------------------------------------------------------------------------
def test_temporal_claims(world, ev):
    assert one(world, ev, _true_temporal(ev, offset_s=45)).verdict == "pass"
    cv = one(world, ev, _true_temporal(ev, offset_s=900))
    assert cv.verdict == "fail" and "closest event" in cv.reason and cv.measured_value == 900
    stop = ev["alarms"]["summary"]["first_stop_or_trip"]["ts"]
    cv = one(world, ev, claim("a", "temporal", [ev["alarms"]["evidence_id"]], asserted_ts=_p(stop)))
    assert cv.verdict == "pass", cv
    naive = _p(_first_up(ev)["ts"]).replace(tzinfo=None)  # naive = UTC
    assert one(world, ev, claim("n", "temporal", [ev["cp_air"]["evidence_id"]], asserted_ts=naive)).verdict == "pass"  # fmt: skip


# --- citation --------------------------------------------------------------------------------
LOTO_STEP = LOTO["compressed_air"].steps[4].text


def _page(quote, doc="compressed_air"):
    pages = locate_quote(doc, quote)
    assert pages, quote
    return pages[0]


def test_real_quote_passes_and_fabricated_fails(world, ev):
    pg = _page(LOTO_STEP)
    ok = claim(
        "c1", "citation", [], citation=Citation(doc="compressed_air", page=pg, quote=LOTO_STEP)
    )
    assert one(world, ev, ok).verdict == "pass"
    # whitespace differences are normalised
    spaced = ok.model_copy(update={"citation": Citation(doc="compressed_air", page=pg,
                                                       quote="  " + LOTO_STEP.replace(" ", "\n  "))})  # fmt: skip
    assert one(world, ev, spaced).verdict == "pass"
    fake = "Shut the compressor down at once and vent the receiver through the drain."
    cv = one(
        world,
        ev,
        claim("c2", "citation", [], citation=Citation(doc="compressed_air", page=pg, quote=fake)),
    )
    assert cv.verdict == "fail" and "not found" in cv.reason
    cv = one(
        world,
        ev,
        claim(
            "c3",
            "citation",
            [],
            citation=Citation(doc="compressed_air", page=pg + 1, quote=LOTO_STEP),
        ),
    )
    assert cv.verdict == "fail" and str(pg) in cv.reason
    short = claim(
        "c4",
        "citation",
        [],
        citation=Citation(doc="compressed_air", page=pg, quote="main disconnect"),
    )
    assert one(world, ev, short).verdict == "fail"
    assert one(world, ev, claim("c5", "citation", [])).verdict == "fail"
    bad_doc = claim("c6", "citation", [], citation=Citation(doc="nope", page=1, quote=LOTO_STEP))
    assert one(world, ev, bad_doc).verdict == "fail"


# --- causal order ----------------------------------------------------------------------------
def test_causal_order(world, ev):
    eids = [ev["cp_air"]["evidence_id"], ev["cp_wld"]["evidence_id"]]
    fwd = claim("k", "causal_order", eids, text="Air leak at the compressor came first")
    cv = one(world, ev, fwd, chain=("UT-AIR header leak", "ST30 gun air pressure low"))
    assert cv.verdict == "pass" and "precedes" in cv.reason, cv
    rev = one(world, ev, fwd, asset="ST30-WLD", chain=("ST30-WLD", "UT-AIR"))
    assert rev.verdict == "fail" and "reversed" in rev.reason, rev
    # missing evidence for the downstream asset -> unverifiable, not fail
    miss = claim("m", "causal_order", eids[:1])
    assert one(world, ev, miss).verdict == "unverifiable"
    assert (
        one(world, ev, miss, asset="ST30-WLD", chain=("ST30-WLD", "UT-AIR")).verdict
        == "unverifiable"
    )
    assert V.chain_assets(["UTAIR leak", "ST20 and ST30-WLD", "UT-AIR again"]) == ["UT-AIR", "ST20-WLD", "ST30-WLD"]  # fmt: skip


# --- evidence ids, provenance ----------------------------------------------------------------
def test_unknown_evidence_id_fails_any_kind(world, ev):
    for kind in ("numeric", "temporal", "qualitative", "causal_order", "citation"):
        c = claim(
            "u", kind, [ev["q_air"]["evidence_id"], "ev_query_telemetry_999"], asserted_value=1.0
        )
        cv = one(world, ev, c)
        assert cv.verdict == "fail" and "ev_query_telemetry_999" in cv.reason, (kind, cv)


@pytest.mark.parametrize(
    "text",
    ["The real data shows the header pressure dropping",
     "Measured on the plant: the header averaged {v} bar",
     "Field data confirms a mean of {v} bar",
     "Header pressure from the plant averaged {v} bar"],
)  # fmt: skip
def test_real_data_claim_on_synthetic_evidence_fails(world, ev, text):
    c = _true_numeric(ev)
    c = c.model_copy(
        update={"text": text.format(v=c.asserted_value) + " (path: tags.header_pressure_bar.mean)"}
    )
    cv = one(world, ev, c)
    assert cv.verdict == "fail" and "real provenance" in cv.reason, cv


def test_real_data_claim_on_real_evidence_passes(world, ev):
    store, truth, models = world
    ctx = _tctx(store, "R801", models)
    stop = truth.stop_ts
    out = T.query_telemetry(ctx, asset_id="UT-AIR", tags=["header_pressure_bar"],
                            t0=_iso(stop - timedelta(hours=3)), t1=_iso(stop))  # fmt: skip
    assert all(p["real"] for p in out["provenance"])
    mean = out["summary"]["tags"]["header_pressure_bar"]["mean"]
    c = claim("r", "numeric", [out["evidence_id"]], asserted_value=mean,
              text=f"Real signals (MetroPT-3) mapped onto the line: header mean {mean} bar")  # fmt: skip
    _, cvs = V.verify_report(report(c), _tctx(store, "R801", models, state=dict(ctx.state)), 1)
    assert cvs[0].verdict == "pass", cvs[0]


def test_negated_real_phrases_are_not_flagged():
    assert V.real_data_phrase("synthetic line, not real data") is None
    assert V.real_data_phrase("simulated plant data") is None
    assert V.real_data_phrase("the measured mean was 6.1 bar") is None
    assert V.real_data_phrase("real signals mapped onto a synthetic line") == "real signals"


# --- data artefacts --------------------------------------------------------------------------
def test_stuck_value_change_point_claims_fail(world, ev):
    s = ev["cp_stuck"]["summary"]
    eid = ev["cp_stuck"]["evidence_id"]
    flagged = [i for i, c in enumerate(s["change_points"]) if c.get("data_issue") == "stuck_value"]
    assert flagged, s["change_points"]
    i = flagged[0]
    cp = s["change_points"][i]
    cv = one(world, ev, claim("d1", "numeric", [eid], asserted_value=cp["delta"],
                              text=f"Oil temperature shifted by {cp['delta']} (path: change_points[{i}].delta)"))  # fmt: skip
    assert cv.verdict == "fail" and "data artefact" in cv.reason, cv
    cv = one(
        world, ev, claim("d2", "temporal", [eid], asserted_ts=_p(cp["ts"]), text="Oil temp changed")
    )
    assert cv.verdict == "fail" and "data artefact" in cv.reason, cv
    # the stuck-period start itself is a data-quality boundary, not a machine event
    st = _p(s["data_quality"]["stuck_periods"][0]["start"])
    cv = one(world, ev, claim("d3", "temporal", [eid], asserted_ts=st, text="Oil temp event"))
    assert cv.verdict == "fail", cv


# --- overall verdict, feedback ---------------------------------------------------------------
def test_qualitative_only_report_fails_overall(world, ev):
    qs = [
        claim(f"q{i}", "qualitative", [ev["q_air"]["evidence_id"]], text="Pressure looks low")
        for i in range(4)
    ]
    v, cvs = V.verify_report(report(*qs), _vctx(world, ev), 1)
    assert v.overall == "FAIL" and all(c.verdict == "pass" for c in cvs)
    assert one(world, ev, claim("q", "qualitative", [])).verdict == "unverifiable"
    rej = V.rejected_claims(cvs, report(*qs))
    assert [r["claim_id"] for r in rej] == ["_report"] and "needs 2" in rej[0]["reason"]


def test_pass_requires_two_distinct_checkable_claims_and_no_failures(world, ev):
    n, t = _true_numeric(ev), _true_temporal(ev)
    v, _ = V.verify_report(report(n, t), _vctx(world, ev), 2)
    assert v.overall == "PASS" and v.iteration == 2
    # the same numeric claim twice counts once
    v, _ = V.verify_report(report(n, n.model_copy(update={"claim_id": "n2"})), _vctx(world, ev), 1)
    assert v.overall == "FAIL"
    # one failure on the top hypothesis -> FAIL; failures on lower hypotheses do not block
    bad = _true_temporal(ev, "t9", offset_s=5000)
    v, cvs = V.verify_report(report(n, t, bad), _vctx(world, ev), 1)
    assert v.overall == "FAIL" and [c.verdict for c in cvs] == ["pass", "pass", "fail"]
    alt = Hypothesis(cause_class=C.SENSOR_DRIFT, asset_id="UT-AIR", confidence=0.1,
                     causal_chain=["UT-AIR"], claims=[bad])  # fmt: skip
    rep = report(n, t, extra=[alt])
    v, cvs = V.verify_report(rep, _vctx(world, ev), 1)
    assert v.overall == "PASS" and [c.claim_id for c in cvs] == ["n1", "t1", "t9"]
    rej = V.rejected_claims(cvs, rep)
    assert rej == [{"claim_id": "t9", "text": bad.text, "kind": "temporal", "verdict": "fail",
                    "reason": cvs[2].reason, "measured_value": 5000.0}]  # fmt: skip
    # duplicate claim ids across hypotheses
    dup = Hypothesis(cause_class=C.SENSOR_DRIFT, asset_id="UT-AIR", confidence=0.1,
                     causal_chain=["UT-AIR"], claims=[n])  # fmt: skip
    _, cvs = V.verify_report(report(n, t, extra=[dup]), _vctx(world, ev), 1)
    assert cvs[2].verdict == "fail" and "duplicate" in cvs[2].reason
    v, _ = V.verify_report(
        RCAReport(incident_id="x", hypotheses=[], status="verified"), _vctx(world, ev), 1
    )
    assert v.overall == "FAIL"


# --- safety steps ----------------------------------------------------------------------------
def _wo(*steps):
    return WorkOrder(wo_id="WO-1", incident_id="INC-S801", asset_id="UT-AIR",
                     cause_class=C.AIR_PRESSURE_DROP, steps=list(steps), parts=[])  # fmt: skip


def test_check_safety_steps():
    pg = _page(LOTO_STEP)
    cit = Citation(doc="compressed_air", page=pg, quote=LOTO_STEP)
    ok = WorkOrderStep(order=1, text=LOTO_STEP, is_safety=True, citation=cit)
    plain = WorkOrderStep(
        order=2, text="Inspect the drop-leg couplings with leak spray.", is_safety=False
    )
    assert V.check_safety_steps(_wo(ok, plain)) == []
    reworded = ok.model_copy(
        update={"text": "Turn the compressor disconnect OFF so it cannot restart."}
    )
    errs = V.check_safety_steps(_wo(reworded))
    assert len(errs) == 1 and "reworded" in errs[0]
    wrong_page = ok.model_copy(update={"citation": cit.model_copy(update={"page": pg + 1})})
    assert any(f"page(s) [{pg}]" in e for e in V.check_safety_steps(_wo(wrong_page)))
    assert (
        "no manual citation"
        in V.check_safety_steps(_wo(ok.model_copy(update={"citation": None})))[0]
    )
    sneaky = WorkOrderStep(
        order=3, text="Apply lockout and tag to the main switch.", is_safety=False
    )
    assert "not marked is_safety" in V.check_safety_steps(_wo(ok, sneaky))[0]
    assert (
        "duplicate step order"
        in V.check_safety_steps(_wo(ok, plain.model_copy(update={"order": 1})))[0]
    )


# --- ADK agent -------------------------------------------------------------------------------
class FakeJudge(BaseAgent):
    """Writes the next scripted draft to state['rca_draft'] on each loop iteration."""

    drafts: list[dict]
    calls: int = 0

    async def _run_async_impl(self, ctx) -> AsyncGenerator[Event, None]:
        d = self.drafts[min(self.calls, len(self.drafts) - 1)]
        self.calls += 1
        yield Event(author=self.name, invocation_id=ctx.invocation_id,
                    actions=EventActions(state_delta={"rca_draft": d}))  # fmt: skip


async def _run_loop(world, ev, drafts):
    store, _, models = world
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        from google.adk.agents import LoopAgent

        judge = FakeJudge(name="rca_judge", drafts=drafts)
        verifier = V.Verifier(
            name="verifier", ctx_factory=lambda st: _tctx(store, "S801", models, state=st)
        )
        loop = LoopAgent(name="rca_loop", sub_agents=[judge, verifier],
                         max_iterations=config.VERIFIER_MAX_ITERATIONS)  # fmt: skip
    plugin = AndonBudgetPlugin(llm=LLM(spend=SpendTracker(daily_budget_usd=1.0)))
    app = App(name="andon", root_agent=loop, plugins=[plugin])
    svc = InMemorySessionService()
    runner = Runner(app=app, session_service=svc)
    s = await svc.create_session(app_name="andon", user_id="u", state=dict(ev["state"]))
    msg = types.Content(role="user", parts=[types.Part(text="verify")])
    events = [e async for e in runner.run_async(user_id="u", session_id=s.id, new_message=msg,
                                                run_config=RunConfig())]  # fmt: skip
    final = await svc.get_session(app_name="andon", user_id="u", session_id=s.id)
    return events, final.state, judge


def _andon(events, kind):
    return [e for e in events if (e.custom_metadata or {}).get("andon_event") == kind]


async def test_adk_verifier_fail_then_pass_escalates(world, ev):
    bad = report(_true_numeric(ev), _true_temporal(ev, offset_s=4000)).model_dump(mode="json")
    good = report(_true_numeric(ev), _true_temporal(ev)).model_dump(mode="json")
    events, state, judge = await _run_loop(world, ev, [bad, good])
    assert judge.calls == 2
    verdicts = _andon(events, "verifier_verdict")
    assert [e.custom_metadata["data"]["overall"] for e in verdicts] == ["FAIL", "PASS"]
    assert [e.custom_metadata["data"]["iteration"] for e in verdicts] == [1, 2]
    assert not verdicts[0].actions.escalate and verdicts[1].actions.escalate
    cv = _andon(events, "claim_verdict")
    assert len(cv) == 4 and all(e.author == "verifier" for e in cv)
    assert cv[0].custom_metadata["hypothesis_index"] == 0
    assert state["verifier_iteration"] == 2 and state["verifier_verdict"]["overall"] == "PASS"
    assert state["rca_final"]["status"] == "verified"
    assert state["rejected_claims"] == []
    assert len(state["rca_final_claims"]) == 2


async def test_adk_verifier_three_fails_insufficient_evidence(world, ev):
    weak = report(_true_numeric(ev), _true_temporal(ev, offset_s=4000)).model_dump(mode="json")
    worse = report(claim("q", "qualitative", ["ev_nope_1"])).model_dump(mode="json")
    events, state, judge = await _run_loop(world, ev, [worse, weak, worse])
    assert judge.calls == 3
    verdicts = _andon(events, "verifier_verdict")
    assert [e.custom_metadata["data"]["overall"] for e in verdicts] == ["FAIL"] * 3
    assert verdicts[-1].actions.escalate and not any(e.actions.escalate for e in verdicts[:2])
    final = RCAReport.model_validate(state["rca_final"])
    assert final.status == "insufficient_evidence"
    assert [c.claim_id for c in final.hypotheses[0].claims] == ["n1", "t1"]  # best partial = weak
    assert state["verifier_best"]["iteration"] == 2
    assert [c["verdict"] for c in state["rca_final_claims"]] == ["pass", "fail"]
    assert state["rejected_claims"][0]["claim_id"] == "q"


async def test_adk_verifier_invalid_draft_is_fail(world, ev):
    events, state, _ = await _run_loop(world, ev, [{"incident_id": "INC-S801", "hypotheses": "?"}])
    verdicts = _andon(events, "verifier_verdict")
    assert len(verdicts) == 3 and not _andon(events, "claim_verdict")
    assert state["rca_final"] == {
        "incident_id": "INC-S801",
        "hypotheses": [],
        "status": "insufficient_evidence",
    }
    assert "invalid" in state["rejected_claims"][0]["reason"]
