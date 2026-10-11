"""Mandatory LOTO steps are decided by code (ADR-025, agents/loto_policy.py, agents/drafter.py)."""

from __future__ import annotations

import re
from types import SimpleNamespace

import pytest

from agents import drafter as D
from agents import loto_policy as LP
from agents.schemas import CauseClass
from agents.verifier import check_safety_steps
from simulator import plant
from simulator.manuals import loto as L

# A step whose text opens like a scope condition must be reviewed into CONDITIONAL_STEPS (or be
# consciously left mandatory in ALLOWED_MANDATORY): a new conditional-looking step cannot slip in.
SCOPE_RE = re.compile(r"^(For work on|On ST\d\d|If |When |Before removing|Only )")
ALLOWED_MANDATORY: set[tuple[str, int]] = set()

ASSETS = [(a.asset_id, a.manual) for a in plant.ASSETS if a.manual in L.LOTO]


def test_classification_table_is_pinned_to_the_reviewed_step_texts():
    for doc, table in LP.CONDITIONAL_STEPS.items():
        steps = L.LOTO[doc].steps
        for n, c in table.items():
            assert 1 <= n <= len(steps), (doc, n)
            assert LP.text_sha(steps[n - 1].text) == c.text_sha, (
                f"{doc}:{n} text changed since review; re-review CONDITIONAL_STEPS"
            )
            assert SCOPE_RE.match(steps[n - 1].text), (doc, n, "conditional without a scope phrase")
            assert (c.kind == "asset") == bool(c.assets)


def test_every_scope_phrased_step_is_reviewed():
    for doc, proc in L.LOTO.items():
        for n, s in enumerate(proc.steps, start=1):
            if SCOPE_RE.match(s.text):
                assert n in LP.CONDITIONAL_STEPS[doc] or (doc, n) in ALLOWED_MANDATORY, (doc, n)


def test_changed_text_falls_back_to_mandatory(monkeypatch):
    c = LP.CONDITIONAL_STEPS["compressed_air"][7]
    monkeypatch.setitem(
        LP.CONDITIONAL_STEPS["compressed_air"], 7, c.__class__(c.kind, c.condition, "0" * 16)
    )
    assert LP.step_class("compressed_air", 7, "UT-AIR") == "mandatory"


def test_expected_classes():
    air = LP.classify("compressed_air", "UT-AIR")
    assert [n for n, c in air.items() if c != "mandatory"] == [7, 10]
    assert air[11] == air[12] == air[16] == "mandatory"
    assert sum(c == "mandatory" for c in air.values()) == 19
    assert LP.classify("weld_controller", "ST30-WLD")[7] == "mandatory"
    assert LP.classify("weld_controller", "ST20-WLD")[7] == "not_applicable"
    assert [
        n for n, c in LP.classify("conveyor_drive", "ST50-CNV").items() if c != "mandatory"
    ] == [8]
    assert all(c == "mandatory" for c in LP.classify("sealer_pump", "ST40-SLR").values())
    assert all(c == "mandatory" for c in LP.classify("press_hydraulics", "ST10-PRS").values())


def _assemble(asset_id, ids=(), cause=CauseClass.AIR_PRESSURE_DROP):
    return D.assemble(wo_id="WO-T", incident_id="inc", asset_id=asset_id, cause_class=cause,
                      safety_step_ids=list(ids), repair_steps=["Inspect the part."], parts=[])  # fmt: skip


@pytest.mark.parametrize(("asset_id", "doc"), ASSETS)
def test_every_mandatory_step_is_in_every_assembled_work_order(asset_id, doc):
    mand = LP.mandatory_texts(asset_id)
    for ids in ([], [f"{doc}:1"], [f"{doc}:{i}" for i in range(1, len(L.LOTO[doc].steps) + 1)]):
        wo, errs = _assemble(asset_id, ids)
        assert wo is not None, errs
        texts = [s.text for s in wo.steps if s.is_safety]
        assert set(mand) <= set(texts)
        order = [t for t in (s.text for s in L.LOTO[doc].steps) if t in texts]
        assert texts == order  # manual order kept (apply steps, then release steps)
        assert check_safety_steps(wo) == []
        # apply -> repair -> release structure
        kinds = ["release" if s.is_safety and L.LOTO[doc].steps[[x.text for x in L.LOTO[doc].steps].index(s.text)].phase == "release"
                 else "safety" if s.is_safety else "work" for s in wo.steps]  # fmt: skip
        assert kinds == sorted(kinds, key=["safety", "work", "release"].index)


def test_conditional_steps_can_be_added_and_not_applicable_ones_are_ignored():
    wo, _ = _assemble("UT-AIR")
    base = sum(s.is_safety for s in wo.steps)
    assert base == 19
    wo2, errs = _assemble("UT-AIR", ["compressed_air:7", "compressed_air:10"])
    assert wo2 is not None, errs
    assert sum(s.is_safety for s in wo2.steps) == 21
    st20, _ = _assemble("ST20-WLD", ["weld_controller:7"], CauseClass.SERVO_OVERHEAT)
    assert not any(s.text.startswith("On ST30") for s in st20.steps)
    st30, _ = _assemble("ST30-WLD", [], CauseClass.COOLANT_BLOCKAGE)
    assert sum(s.text.startswith("On ST30") for s in st30.steps) == 3


def test_unknown_ids_still_error():
    wo, errs = _assemble("UT-AIR", ["compressed_air:99"])
    assert wo is None and "unknown safety step ids" in errs[0]


def test_drafter_instruction_lists_only_conditional_steps():
    from agents.schemas import Claim, Hypothesis, RCAReport

    rep = RCAReport(incident_id="i", status="verified", hypotheses=[Hypothesis(
        cause_class=CauseClass.AIR_PRESSURE_DROP, asset_id="UT-AIR", confidence=0.8,
        causal_chain=["UT-AIR"], claims=[Claim(claim_id="c", text="x", kind="qualitative", evidence_ids=["e"])])])  # fmt: skip
    text = D.drafter_instruction(SimpleNamespace(state={"rca_final": rep.model_dump(mode="json")}))
    assert "Code inserts all 19 mandatory" in text
    assert "compressed_air:7 " in text and "compressed_air:10 " in text
    assert "compressed_air:16" not in text and "Test for absence of voltage" not in text
