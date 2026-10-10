"""CONTRACT — agent data model (ARCHITECTURE §4.1).

Change only with both humans' OK: bump CONTRACT_VERSION, update tests/test_contracts.py and
web/src/types/events.ts, and note it in docs/DECISIONS.md. Keep nesting ≤3 levels so these models
stay usable as Gemini `response_schema`.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field

CONTRACT_VERSION = "1.0.0"


class CauseClass(StrEnum):
    """Exactly the 11 simulator fault classes + NO_FAULT."""

    WELD_TIP_WEAR = "weld_tip_wear"
    SEALER_PUMP_CAVITATION = "sealer_pump_cavitation"
    CONVEYOR_BEARING_DEFECT = "conveyor_bearing_defect"
    SERVO_OVERHEAT = "servo_overheat"
    AIR_PRESSURE_DROP = "air_pressure_drop"
    SENSOR_DRIFT = "sensor_drift"
    PLC_TIMER_MISCONFIG = "plc_timer_misconfig"
    COOLANT_BLOCKAGE = "coolant_blockage"
    FIXTURE_MISALIGNMENT = "fixture_misalignment"
    CHANGEOVER_ERROR = "changeover_error"
    HYDRAULIC_DEGRADATION = "hydraulic_degradation"
    NO_FAULT = "no_fault"


class ProvenanceRef(BaseModel):
    source_id: str  # "synthetic" | "metropt3" | "uci_hydraulic" | "ims_bearings" | "mimii" | ...
    real: bool
    source_ref: str | None = None  # rows/files used, from the provenance table


class Evidence(BaseModel):
    evidence_id: str  # "ev_<tool>_<n>"
    tool: str  # tool name that produced it
    args: dict[str, Any]  # exact args, so the verifier can re-run it
    summary: dict[str, Any]  # numeric/structured result (no prose)
    provenance: list[ProvenanceRef]
    produced_at: datetime


class Citation(BaseModel):
    doc: str
    page: int
    quote: str  # must exist verbatim in cached manual text


class Claim(BaseModel):
    claim_id: str
    text: str  # human-readable
    kind: Literal["numeric", "temporal", "citation", "causal_order", "qualitative"]
    evidence_ids: list[str]
    asserted_value: float | None = None
    asserted_ts: datetime | None = None
    citation: Citation | None = None


class Hypothesis(BaseModel):
    cause_class: CauseClass
    asset_id: str
    confidence: float = Field(ge=0, le=1)
    causal_chain: list[str]  # asset/event steps, root first
    claims: list[Claim]
    refuting_evidence_ids: list[str] = []
    next_check: str | None = None


class RCAReport(BaseModel):
    incident_id: str
    hypotheses: list[Hypothesis] = Field(max_length=3)  # ranked
    status: Literal["verified", "insufficient_evidence"]


class ClaimVerdict(BaseModel):
    claim_id: str
    verdict: Literal["pass", "fail", "unverifiable"]
    reason: str
    measured_value: float | None = None


class VerifierVerdict(BaseModel):
    overall: Literal["PASS", "FAIL"]
    claims: list[ClaimVerdict]
    iteration: int


class WorkOrderStep(BaseModel):
    order: int
    text: str
    is_safety: bool
    citation: Citation | None = None


class WorkOrder(BaseModel):
    wo_id: str
    incident_id: str
    asset_id: str
    cause_class: CauseClass
    steps: list[WorkOrderStep]
    parts: list[str]
    status: Literal["PENDING_APPROVAL", "APPROVED", "REJECTED"] = "PENDING_APPROVAL"
