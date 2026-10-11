"""Contract tests: every model and event round-trips; Python and TypeScript contracts agree;
the sample stream is a valid, complete incident."""

import json
import re
import typing
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from agents import schemas as S
from api import events as E
from simulator.truth_schema import GroundTruth

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "sample_stream.jsonl"
TS_FILE = ROOT / "web" / "src" / "types" / "events.ts"
NOW = datetime(2026, 10, 11, 8, 42, 10, tzinfo=UTC)

CIT = S.Citation(doc="compressed_air", page=14, quote="exact words")
CLAIM = S.Claim(
    claim_id="cl1",
    text="pressure fell 14%",
    kind="numeric",
    evidence_ids=["ev_x_1"],
    asserted_value=-14.0,
    asserted_ts=NOW,
    citation=CIT,
)
HYP = S.Hypothesis(
    cause_class=S.CauseClass.AIR_PRESSURE_DROP,
    asset_id="UT-AIR",
    confidence=0.8,
    causal_chain=["UT-AIR", "ST30-WLD"],
    claims=[CLAIM],
)
REPORT = S.RCAReport(incident_id="i1", hypotheses=[HYP], status="verified")
MODELS = [
    S.ProvenanceRef(source_id="metropt3", real=True, source_ref="rows 1-2"),
    S.Evidence(
        evidence_id="ev_x_1",
        tool="query_telemetry",
        args={"asset_id": "UT-AIR"},
        summary={"mean": 6.1},
        provenance=[S.ProvenanceRef(source_id="synthetic", real=False)],
        produced_at=NOW,
    ),
    CIT,
    CLAIM,
    HYP,
    REPORT,
    S.ClaimVerdict(claim_id="cl1", verdict="fail", reason="off by 22%", measured_value=-14.0),
    S.VerifierVerdict(overall="FAIL", claims=[], iteration=1),
    S.WorkOrderStep(order=1, text="Lock valve", is_safety=True, citation=CIT),
    S.WorkOrder(
        wo_id="WO-1",
        incident_id="i1",
        asset_id="UT-AIR",
        cause_class=S.CauseClass.AIR_PRESSURE_DROP,
        steps=[],
        parts=[],
    ),
    GroundTruth(
        scenario_id="R002",
        seed=1,
        scenario_set="real_signal",
        truth_source="source_label",
        variant="clean",
        root_cause_class=S.CauseClass.AIR_PRESSURE_DROP,
        asset_id="UT-AIR",
        onset_ts=NOW,
        causal_chain=["UT-AIR", "ST20-WLD"],
        distractors=[],
        imperfections=["gap:ST30-WLD:air_pressure_bar"],
        stop_station="ST30",
        stop_ts=NOW,
    ),
]


def load_fixture() -> list[dict]:
    return [json.loads(line) for line in FIXTURE.read_text().splitlines() if line.strip()]


@pytest.mark.parametrize("model", MODELS, ids=lambda m: type(m).__name__)
def test_models_round_trip(model):
    again = type(model).model_validate_json(model.model_dump_json())
    assert again == model


def test_cause_classes_are_eleven_plus_no_fault():
    assert len(S.CauseClass) == 12 and S.CauseClass.NO_FAULT in S.CauseClass


def test_report_rejects_more_than_three_hypotheses():
    with pytest.raises(ValidationError):
        S.RCAReport(incident_id="i", hypotheses=[HYP] * 4, status="verified")


@pytest.mark.parametrize("conf", [-0.1, 1.1])
def test_confidence_bounds(conf):
    with pytest.raises(ValidationError):
        HYP.model_validate(HYP.model_dump() | {"confidence": conf})


def test_work_order_defaults_to_pending_approval():
    assert MODELS[9].status == "PENDING_APPROVAL"


@pytest.mark.parametrize("model", [S.RCAReport, S.WorkOrder])
def test_response_schema_models_export_json_schema(model):
    schema = model.model_json_schema()
    assert schema["type"] == "object"


# --- events ----------------------------------------------------------------------------------
def test_event_types_match_union():
    union_types = {
        typing.get_args(cls.model_fields["type"].annotation)[0]
        for cls in typing.get_args(typing.get_args(E.Event)[0])
    }
    assert union_types == set(E.EVENT_TYPES)


def test_every_event_round_trips_from_fixture():
    for raw in load_fixture():
        ev = E.parse_event(raw)
        assert E.parse_event(ev.model_dump_json()) == ev


def test_fixture_covers_every_non_error_event_type_and_is_ordered():
    events = load_fixture()
    assert {e["type"] for e in events} == set(E.EVENT_TYPES) - {"error"}
    seqs = [e["seq"] for e in events]
    assert seqs == list(range(len(events)))
    ts = [datetime.fromisoformat(e["ts"]) for e in events]
    assert ts == sorted(ts)
    assert events[0]["type"] == "incident_started" and events[-1]["type"] == "done"


def test_fixture_tells_the_demo_story():
    events = [E.parse_event(r) for r in load_fixture()]
    verdicts = [e.data.overall for e in events if e.type == "verifier_verdict"]
    assert verdicts == ["FAIL", "PASS"]
    real = [e for e in events if e.type == "tool_result" and any(p.real for p in e.data.provenance)]
    assert real and all(p.source_ref for e in real for p in e.data.provenance if p.real)
    wo = next(e for e in events if e.type == "work_order_draft").data
    assert wo.status == "PENDING_APPROVAL"
    assert all(s.citation and s.citation.quote == s.text for s in wo.steps if s.is_safety)


def test_error_event_parses():
    ev = E.parse_event(
        {
            "type": "error",
            "incident_id": "i",
            "seq": 0,
            "ts": NOW.isoformat(),
            "agent": None,
            "data": {"code": "budget_exhausted", "message": "daily budget hit", "retryable": False},
        }
    )
    assert ev.data.code == "budget_exhausted"


def test_unknown_event_type_rejected():
    with pytest.raises(ValidationError):
        E.parse_event(
            {"type": "nope", "incident_id": "i", "seq": 0, "ts": NOW.isoformat(), "data": {}}
        )


def test_encode_sse_frame():
    ev = E.parse_event(load_fixture()[0])
    frame = E.encode_sse(ev)
    assert frame.startswith("id: 0\nevent: incident_started\ndata: {")
    assert frame.endswith("\n\n") and frame.count("\n") == 4
    assert E.HEARTBEAT.startswith(":")


# --- TypeScript mirror -----------------------------------------------------------------------
def _ts_union(name: str) -> set[str]:
    src = TS_FILE.read_text()
    m = re.search(rf"export type {name} =(.*?);", src, re.S)
    assert m, name
    return set(re.findall(r'"([a-z_]+)"', m.group(1)))


def test_ts_contract_version_matches():
    assert f'CONTRACT_VERSION = "{S.CONTRACT_VERSION}"' in TS_FILE.read_text()


def test_ts_event_types_match():
    assert _ts_union("AndonEvent") == set(E.EVENT_TYPES)
    src = TS_FILE.read_text()
    arr = re.search(r"EVENT_TYPES: readonly EventType\[\] = \[(.*?)\]", src, re.S).group(1)
    assert re.findall(r'"([a-z_]+)"', arr) == list(E.EVENT_TYPES)


def test_ts_cause_classes_match():
    assert _ts_union("CauseClass") == {c.value for c in S.CauseClass}


@pytest.mark.parametrize(
    "py_model,ts_name",
    [
        (S.Claim, "Claim"),
        (S.Hypothesis, "Hypothesis"),
        (S.RCAReport, "RCAReport"),
        (S.WorkOrder, "WorkOrder"),
        (S.WorkOrderStep, "WorkOrderStep"),
        (S.ClaimVerdict, "ClaimVerdict"),
        (S.ProvenanceRef, "ProvenanceRef"),
        (E.ToolResultData, "ToolResultData"),
        (E.CostData, "CostData"),
        (E.IncidentStartedData, "IncidentStartedData"),
    ],
)
def test_ts_interface_fields_match(py_model, ts_name):
    src = TS_FILE.read_text()
    body = re.search(rf"export interface {ts_name} \{{(.*?)\n\}}", src, re.S).group(1)
    ts_fields = set(re.findall(r"^\s+(\w+):", body, re.M))
    assert ts_fields == set(py_model.model_fields)


def test_fixture_work_order_passes_the_drafter_safety_check():
    """The frontend builds against this fixture, so its WO must be one the real drafter would
    accept: verbatim LOTO quotes, and no unmarked step that reads like energy control."""
    from agents.verifier import check_safety_steps

    wo = next(E.parse_event(r) for r in load_fixture() if r["type"] == "work_order_draft").data
    assert check_safety_steps(wo) == []
