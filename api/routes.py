"""HTTP routes. All error bodies are ``{"detail": {"code": str, "message": str, ...}}``."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
import re
import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import AliasChoices, BaseModel, ConfigDict, Field

import config
from agents.cmms import CMMSWriteError, WorkOrderAlreadyDecided
from agents.llm import BudgetExhaustedError
from agents.schemas import CONTRACT_VERSION, WorkOrder
from agents.verifier import check_safety_steps
from api import catalog
from api.audit import INCIDENT_ID_RE, AuditRecorder, public_view
from api.context import AppContext
from api.events import Event
from api.replay import RUN_ID_RE, ReplayNotFound, new_replay_incident_id, stream_replay
from api.sse import SSE_HEADERS, guarded, single_error_stream, sse_frames

log = logging.getLogger("andon.api")
SCENARIO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,32}$")


def err(status: int, code: str, message: str, headers: dict | None = None, **extra: Any):
    return HTTPException(status, {"code": code, "message": message, **extra}, headers=headers)


def client_ip(request: Request, hops: int) -> str:
    """The caller's IP. Cloud Run *appends* the real peer to ``X-Forwarded-For``, so the trusted
    entry is the one ``hops`` from the right; anything the client put before it is ignored."""
    parts = [p.strip() for p in request.headers.get("x-forwarded-for", "").split(",") if p.strip()]
    if parts and 1 <= hops <= len(parts):
        return parts[-hops]
    return request.client.host if request.client else "unknown"


class ApproveBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["approve", "reject"]
    rca_decision: Literal["accept", "edit", "reject"]
    ticked_safety_steps: list[int] = Field(
        default_factory=list,
        max_length=64,
        validation_alias=AliasChoices("ticked_safety_steps", "safety_steps_ticked"),
    )
    approver_name: str = Field(min_length=1, max_length=80)
    note: str = Field("", max_length=1000)
    edits: str | None = Field(None, max_length=4000)  # the human's RCA edit, kept in the audit


class SlotResponse(StreamingResponse):
    """StreamingResponse that always runs ``on_close`` when the ASGI call ends, even if the client
    vanished before the body generator started (its own ``finally`` would never run then)."""

    def __init__(self, *a: Any, on_close: Any = None, **kw: Any) -> None:
        super().__init__(*a, **kw)
        self._on_close = on_close

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        try:
            await super().__call__(scope, receive, send)
        finally:
            if self._on_close is not None:
                self._on_close()


def build_router(ctx: AppContext) -> APIRouter:
    st = ctx.settings
    r = APIRouter()

    # ---- helpers -------------------------------------------------------------------------
    def require_passcode(request: Request) -> None:
        if not st.demo_passcode:
            raise err(403, "live_disabled", "live mode is not enabled on this deployment")
        ip = client_ip(request, st.trusted_proxy_hops)
        wait = ctx.failures.blocked(ip)
        if wait:
            raise err(429, "too_many_attempts", "too many wrong passcodes", {"Retry-After": str(wait)})  # fmt: skip
        given = request.headers.get("x-demo-passcode", "")
        if not hmac.compare_digest(given.encode(), st.demo_passcode.encode()):
            ctx.failures.fail(ip)
            raise err(401, "passcode_required", "a valid X-Demo-Passcode header is required")

    # ---- health / config -----------------------------------------------------------------
    @r.get("/health")
    async def health() -> dict:
        return {
            "status": "ok",
            "version": config.APP_VERSION,
            "contract_version": CONTRACT_VERSION,
            "theme": config.THEME,
            "store_backend": st.store_backend,
            "models": {
                "flash": config.FLASH,
                "flash_lite": config.FLASH_LITE,
                "judge": config.JUDGE_MODEL,
                "judge_pro": config.PRO_JUDGE,
            },
        }

    @r.get("/api/config")
    async def get_config() -> dict:
        remaining = ctx.budget.remaining()
        exhausted = remaining <= 0
        return {
            "theme": config.THEME,
            "version": config.APP_VERSION,
            "contract_version": CONTRACT_VERSION,
            "badge": catalog.BADGE,
            "modes": {
                "replay": True,
                "live": st.live_enabled and not exhausted,
                "live_requires_passcode": True,
            },
            "budget": {
                "daily_usd": st.daily_budget_usd,
                "remaining_usd": round(remaining, 4),
                "exhausted": exhausted,
            },
            "limits": {
                "live_runs_per_day": st.live_runs_per_day,
                "live_runs_per_min_per_ip": st.live_runs_per_min_per_ip,
            },
            "replays_available": len(ctx.replays.list()),
        }

    # ---- catalogue -----------------------------------------------------------------------
    @r.get("/api/scenarios")
    async def scenarios() -> dict:
        return catalog.group_scenarios(await ctx.scenarios(), ctx.replays.list())

    @r.get("/api/replays")
    async def replays() -> dict:
        return {"replays": ctx.replays.list()}

    @r.get("/api/eval/latest")
    async def eval_latest() -> Any:
        data = catalog.load_eval_latest(st.eval_latest)
        if data is None:
            raise err(404, "no_eval_results", "no committed eval run yet")
        return data

    @r.get("/api/sources")
    async def sources() -> Any:
        data = catalog.load_sources(st.sources_md)
        if data is None:
            raise err(503, "sources_unavailable", "data/SOURCES.md is not available")
        return data

    # ---- investigate (SSE) ---------------------------------------------------------------
    @r.post("/api/incidents/{scenario_id}/investigate")
    async def investigate(
        scenario_id: str,
        request: Request,
        mode: Literal["live", "replay"] = "replay",
        run_id: str | None = Query(None, max_length=96),
        speed: float = Query(1.0, ge=1.0, le=4.0),
    ) -> StreamingResponse:
        if not SCENARIO_ID_RE.match(scenario_id) or scenario_id not in {
            s["scenario_id"] for s in await ctx.scenarios()
        }:
            raise err(404, "unknown_scenario", "unknown scenario")
        ip = client_ip(request, st.trusted_proxy_hops)
        ip_hash = hashlib.sha256(ip.encode()).hexdigest()[:16]
        meta: dict[str, Any] = {
            "scenario_id": scenario_id,
            "mode": mode,
            "ip_hash": ip_hash,
            "started_at": datetime.now(UTC).isoformat(),
            "version": config.APP_VERSION,
        }

        if mode == "replay":
            if run_id is not None and not (RUN_ID_RE.match(run_id) or run_id.startswith("audit:")):
                raise err(404, "unknown_replay", "unknown replay run")
            run_id = run_id or ctx.replays.default_for(scenario_id)
            if run_id is None:
                raise err(404, "no_replay", f"no recorded run for {scenario_id}")
            try:
                raw = await asyncio.to_thread(ctx.replays.load, run_id, scenario_id)
            except ReplayNotFound as exc:
                raise err(404, "unknown_replay", "unknown replay run") from exc
            incident_id = new_replay_incident_id(scenario_id)
            meta["run_id"] = run_id
            source = stream_replay(raw, incident_id, speed=speed, gap_cap_s=st.replay_gap_cap_s, sleep=ctx.sleep)  # fmt: skip
            recorder = AuditRecorder(ctx.audit, incident_id, meta, store_steps=False)

            async def stash_demo_wo(ev: Event) -> None:
                if ev.type == "work_order_draft":
                    wo = WorkOrder.model_validate(ev.data.model_dump())
                    await asyncio.to_thread(ctx.cmms_demo.create_draft, wo)

            return _respond(request, incident_id, guarded(source, incident_id, timeout_s=st.run_timeout_s), recorder, before_emit=stash_demo_wo)  # fmt: skip

        # ---- live ----
        require_passcode(request)
        if st.replay_only:
            raise err(403, "live_disabled", "live mode is disabled (replay only)")
        incident_id = f"inc_{scenario_id.lower()}_{uuid.uuid4().hex[:8]}"
        try:
            await ctx.budget.check_fresh()
        except BudgetExhaustedError as exc:
            log.warning("live refused (budget): %s", exc)
            return _respond(request, incident_id, single_error_stream(incident_id, "budget_exhausted", str(exc)[:300]), None)  # fmt: skip
        decision = await asyncio.to_thread(ctx.limiter.acquire, ip)
        if not decision.allowed:
            raise err(429, "rate_limited", f"live run limit reached ({decision.scope})",
                      {"Retry-After": str(decision.retry_after_s)}, scope=decision.scope)  # fmt: skip
        slot = ctx.acquire_live_slot()
        if slot is None:
            raise err(429, "busy", "too many live runs in progress; retry shortly", {"Retry-After": "30"})  # fmt: skip
        recorder = AuditRecorder(ctx.audit, incident_id, meta)
        source = guarded(ctx.live_runner(scenario_id, incident_id), incident_id, timeout_s=st.run_timeout_s)  # fmt: skip
        return _respond(
            request, incident_id, source, recorder, on_close=lambda: ctx.release_live_slot(slot)
        )

    def _respond(request, incident_id, events, recorder, *, before_emit=None, on_close=None):
        body = sse_frames(request, events, heartbeat_s=st.heartbeat_s, recorder=recorder,
                          before_emit=before_emit, on_close=on_close)  # fmt: skip
        return SlotResponse(
            body,
            on_close=on_close,
            media_type="text/event-stream",
            headers={**SSE_HEADERS, "X-Incident-Id": incident_id},
        )

    # ---- audit ---------------------------------------------------------------------------
    @r.get("/api/incidents/{incident_id}/audit")
    async def get_audit(incident_id: str) -> dict:
        if not INCIDENT_ID_RE.match(incident_id):
            raise err(404, "unknown_incident", "unknown incident")
        rec = await asyncio.to_thread(ctx.audit.get, incident_id)
        if rec is None:
            raise err(404, "unknown_incident", "unknown incident")
        view = public_view(rec)
        view["incident"] = {k: v for k, v in (view["incident"] or {}).items() if k != "ip_hash"}
        return view

    # ---- HITL ----------------------------------------------------------------------------
    @r.post("/api/incidents/{incident_id}/approve")
    async def approve(incident_id: str, body: ApproveBody, request: Request) -> dict:
        if not INCIDENT_ID_RE.match(incident_id):
            raise err(404, "unknown_incident", "unknown incident")
        rec = await asyncio.to_thread(ctx.audit.get, incident_id)
        if rec is None:
            raise err(404, "unknown_incident", "unknown incident")
        mode = (rec["incident"] or {}).get("mode")
        if mode == "live":
            require_passcode(request)
        link = rec["meta"].get("work_order")
        if not link:
            raise err(409, "no_work_order", "this incident produced no work order")
        cmms = ctx.cmms_live if mode == "live" else ctx.cmms_demo
        wo = await asyncio.to_thread(cmms.get, link["wo_id"])
        if wo is None:
            raise err(404, "unknown_work_order", "work order not found")
        if wo.status != "PENDING_APPROVAL":
            raise err(409, "already_decided", f"work order is already {wo.status}", current=wo.status)  # fmt: skip

        action = {
            "action": "decision",
            "decision": body.decision,
            "rca_decision": body.rca_decision,
            "ticked_safety_steps": sorted(set(body.ticked_safety_steps)),
            "approver_name": body.approver_name,
            "note": body.note,
            "edits": body.edits,
            "wo_id": wo.wo_id,
            "demo": mode != "live",
        }
        if body.decision == "approve":
            safety = {s.order for s in wo.steps if s.is_safety}
            unticked = sorted(safety - set(body.ticked_safety_steps))
            problem: HTTPException | None = None
            if unticked:
                problem = err(409, "safety_steps_unticked", "every safety step must be ticked before approval", unticked=unticked)  # fmt: skip
            elif body.rca_decision == "reject":
                problem = err(422, "rca_rejected", "a work order cannot be approved while the RCA is rejected")  # fmt: skip
            elif errs := check_safety_steps(wo):
                log.error("stored work order %s fails the safety re-check: %s", wo.wo_id, errs)
                problem = err(409, "safety_text_invalid", "a safety step is not a verbatim manual quote", errors=errs)  # fmt: skip
            if problem is not None:
                await asyncio.to_thread(ctx.audit.add_action, incident_id, {**action, "action": "approval_refused", "reason": problem.detail["code"]})  # fmt: skip
                raise problem
        status = "APPROVED" if body.decision == "approve" else "REJECTED"
        decided_at = datetime.now(UTC).isoformat()
        try:
            new = await asyncio.to_thread(cmms.decide, wo.wo_id, status, {
                "decided_at": decided_at, "approver_name": body.approver_name,
                "rca_decision": body.rca_decision, "note": body.note,
                "ticked_safety_steps": action["ticked_safety_steps"],
            })  # fmt: skip
        except WorkOrderAlreadyDecided as exc:
            raise err(409, "already_decided", str(exc)) from exc
        except CMMSWriteError as exc:
            raise err(409, "cmms_refused", str(exc)) from exc
        await asyncio.to_thread(ctx.audit.add_action, incident_id, {**action, "status": status})
        return {
            "incident_id": incident_id,
            "wo_id": new.wo_id,
            "status": new.status,
            "decided_at": decided_at,
            "demo": mode != "live",
            "collection": "work_orders" if mode == "live" else "demo_work_orders",
        }

    return r
