"""CONTRACT — SSE event union consumed by the frontend (ARCHITECTURE §4.2).

Every event: {"type", "incident_id", "seq", "ts", "agent", "data"}. Heartbeats are SSE comments
(`: ping`), not events. Mirrored by web/src/types/events.ts; tests/test_contracts.py keeps the two
in sync. Change only with both humans' OK (bump agents.schemas.CONTRACT_VERSION).
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, TypeAdapter

from agents.schemas import (
    CONTRACT_VERSION,
    ClaimVerdict,
    ProvenanceRef,
    RCAReport,
    VerifierVerdict,
    WorkOrder,
)

__all__ = ["CONTRACT_VERSION", "EVENT_TYPES", "HEARTBEAT", "Event", "encode_sse", "parse_event"]

HEARTBEAT = ": ping\n\n"


# --- payloads --------------------------------------------------------------------------------
class IncidentStartedData(BaseModel):
    scenario_id: str
    line_id: str
    stopped_station: str
    mode: Literal["live", "replay"]


class PlanData(BaseModel):
    steps: list[str]


class AgentData(BaseModel):
    agent: str
    model_id: str | None  # None for the deterministic verifier


class ToolCallData(BaseModel):
    call_id: str
    tool: str
    args: dict[str, Any]


class ToolResultData(BaseModel):
    call_id: str
    evidence_id: str
    summary: dict[str, Any]
    provenance: list[ProvenanceRef]
    latency_ms: int


class CacheHitData(BaseModel):
    cache_name: str
    cached_tokens: int
    saved_usd: float


class ModelFallbackData(BaseModel):
    from_model: str
    to_model: str
    reason: str


class CostData(BaseModel):
    input_tokens: int
    output_tokens: int
    cached_tokens: int
    usd: float
    by_model: dict[str, float]  # model_id -> usd


class ErrorData(BaseModel):
    code: str  # e.g. "budget_exhausted", "model_unavailable", "internal"
    message: str
    retryable: bool


class DoneData(BaseModel):
    duration_ms: int


# --- envelope --------------------------------------------------------------------------------
class _Base(BaseModel):
    incident_id: str
    seq: int = Field(ge=0)
    ts: datetime
    agent: str | None = None


class IncidentStarted(_Base):
    type: Literal["incident_started"] = "incident_started"
    data: IncidentStartedData


class Plan(_Base):
    type: Literal["plan"] = "plan"
    data: PlanData


class AgentStarted(_Base):
    type: Literal["agent_started"] = "agent_started"
    data: AgentData


class AgentFinished(_Base):
    type: Literal["agent_finished"] = "agent_finished"
    data: AgentData


class ToolCall(_Base):
    type: Literal["tool_call"] = "tool_call"
    data: ToolCallData


class ToolResult(_Base):
    type: Literal["tool_result"] = "tool_result"
    data: ToolResultData


class CacheHit(_Base):
    type: Literal["cache_hit"] = "cache_hit"
    data: CacheHitData


class Hypotheses(_Base):
    type: Literal["hypotheses"] = "hypotheses"
    data: RCAReport  # draft


class ClaimVerdictEvent(_Base):
    type: Literal["claim_verdict"] = "claim_verdict"
    data: ClaimVerdict


class VerifierVerdictEvent(_Base):
    type: Literal["verifier_verdict"] = "verifier_verdict"
    data: VerifierVerdict


class ModelFallback(_Base):
    type: Literal["model_fallback"] = "model_fallback"
    data: ModelFallbackData


class RCAFinal(_Base):
    type: Literal["rca_final"] = "rca_final"
    data: RCAReport


class WorkOrderDraft(_Base):
    type: Literal["work_order_draft"] = "work_order_draft"
    data: WorkOrder


class Cost(_Base):
    type: Literal["cost"] = "cost"
    data: CostData


class Error(_Base):
    type: Literal["error"] = "error"
    data: ErrorData


class Done(_Base):
    type: Literal["done"] = "done"
    data: DoneData


Event = Annotated[
    IncidentStarted
    | Plan
    | AgentStarted
    | AgentFinished
    | ToolCall
    | ToolResult
    | CacheHit
    | Hypotheses
    | ClaimVerdictEvent
    | VerifierVerdictEvent
    | ModelFallback
    | RCAFinal
    | WorkOrderDraft
    | Cost
    | Error
    | Done,
    Field(discriminator="type"),
]

_ADAPTER: TypeAdapter[Event] = TypeAdapter(Event)

EVENT_TYPES: tuple[str, ...] = (
    "incident_started",
    "plan",
    "agent_started",
    "agent_finished",
    "tool_call",
    "tool_result",
    "cache_hit",
    "hypotheses",
    "claim_verdict",
    "verifier_verdict",
    "model_fallback",
    "rca_final",
    "work_order_draft",
    "cost",
    "error",
    "done",
)


def parse_event(raw: str | bytes | dict) -> Event:
    """Validate one event from JSON text or a dict."""
    if isinstance(raw, dict):
        return _ADAPTER.validate_python(raw)
    return _ADAPTER.validate_json(raw)


def encode_sse(event: Event) -> str:
    """One SSE frame. `id` = seq so a client can resume; payload is the full envelope as JSON."""
    return f"id: {event.seq}\nevent: {event.type}\ndata: {event.model_dump_json()}\n\n"
