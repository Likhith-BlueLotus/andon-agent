"""Andon Agent API (FastAPI + SSE). ``uvicorn api.main:app``.

Health lives at /health, not /healthz: Cloud Run's front end reserves paths ending in "z" — never
add a route ending in "z". Interactive docs are off on Cloud Run (``K_SERVICE`` is set there).

``create_app(settings, ...)`` wires the pieces (every one injectable for tests):

* live runs  -> ``agents.events_map.run_incident`` over an ADK graph on a per-incident store;
* replay     -> ``api.replay`` (stored runs, original timing, no model);
* protection -> passcode, per-IP / per-day limits, shared daily kill switch, CORS allow-list,
  request size cap;
* audit      -> ``api.audit`` (append-only, Firestore or local files);
* HITL       -> ``/approve`` into the mock CMMS (live) or ``demo_work_orders`` (replay).
"""

from __future__ import annotations

import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.types import ASGIApp, Message, Receive, Scope, Send

import config
from agents.cmms import Decidable, FirestoreCMMS, JsonlCMMS
from agents.llm import SpendTracker, get_spend
from api.audit import AuditRecorder, AuditStore, FileAuditStore, FirestoreAuditStore
from api.budget import BudgetGuard, FirestoreSpendStore, MemorySpendStore
from api.context import AppContext, LiveRunner
from api.events import Event
from api.fs import LazyFirestore
from api.ratelimit import FirestoreLimiter, Limiter, MemoryLimiter
from api.replay import ReplayCatalog
from api.routes import build_router
from api.settings import Settings
from api.stores import StoreProvider, make_provider

log = logging.getLogger("andon.api")
_ON_CLOUD_RUN = bool(os.environ.get("K_SERVICE"))


class RequestTooLarge(Exception):
    pass


class BodyLimitMiddleware:
    """Pure ASGI (no response buffering, safe for SSE): reject bodies over ``max_bytes`` with 413,
    by ``Content-Length`` up front and by counting streamed bytes."""

    def __init__(self, app: ASGIApp, max_bytes: int) -> None:
        self.app, self.max_bytes = app, max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        declared = dict(scope["headers"]).get(b"content-length")
        started = False
        total = 0

        async def reject() -> None:
            body = b'{"detail":{"code":"payload_too_large","message":"request body too large"}}'
            await send({"type": "http.response.start", "status": 413,
                        "headers": [(b"content-type", b"application/json"),
                                    (b"content-length", str(len(body)).encode())]})  # fmt: skip
            await send({"type": "http.response.body", "body": body})

        if declared is not None and declared.isdigit() and int(declared) > self.max_bytes:
            await reject()
            return

        async def counting_receive() -> Message:
            nonlocal total
            msg = await receive()
            if msg["type"] == "http.request":
                total += len(msg.get("body", b""))
                if total > self.max_bytes:
                    raise RequestTooLarge
            return msg

        async def tracking_send(msg: Message) -> None:
            nonlocal started
            started = started or msg["type"] == "http.response.start"
            await send(msg)

        try:
            await self.app(scope, counting_receive, tracking_send)
        except RequestTooLarge:
            if not started:
                await reject()


def default_live_runner(provider: StoreProvider, cmms: Decidable) -> LiveRunner:
    """Live: open the incident's store, build the ADK graph (Gemini via the shared, budget-guarded
    ``agents.llm`` gateway) and forward ``run_incident``'s contract events."""

    async def run(scenario_id: str, incident_id: str) -> AsyncIterator[Event]:
        import asyncio

        from agents.events_map import run_incident
        from agents.graph import build_app

        cm = await asyncio.to_thread(provider.open, scenario_id)
        store = await asyncio.to_thread(cm.__enter__)
        try:
            app = build_app(store, mode="live", cmms=cmms)
            async for ev in run_incident(app, scenario_id, "live", incident_id=incident_id):
                yield ev
        finally:
            with suppress(Exception):
                cm.__exit__(None, None, None)

    return run


def create_app(
    settings: Settings | None = None,
    *,
    provider: StoreProvider | None = None,
    live_runner: LiveRunner | None = None,
    audit: AuditStore | None = None,
    cmms_live: Decidable | None = None,
    cmms_demo: Decidable | None = None,
    spend: SpendTracker | None = None,
    firestore_client: Any = None,
) -> FastAPI:
    st = settings or Settings.from_env()
    fs = firestore_client or (LazyFirestore() if st.firestore else None)
    provider = provider or make_provider(st)
    if audit is None:
        audit = FirestoreAuditStore(fs) if fs is not None else FileAuditStore(st.audit_dir)
    if cmms_live is None:
        cmms_live = FirestoreCMMS(fs) if fs is not None else JsonlCMMS(st.cmms_path)
    if cmms_demo is None:
        # Anonymous replay approvals never touch the CMMS: separate collection / in-memory only.
        from agents.cmms import InMemoryCMMS

        cmms_demo = FirestoreCMMS(fs, "demo_work_orders") if fs is not None else InMemoryCMMS()
    budget = BudgetGuard(
        spend or get_spend(),
        FirestoreSpendStore(fs) if fs is not None else MemorySpendStore(),
        budget_usd=st.daily_budget_usd,
    )
    memory = MemoryLimiter(st.live_runs_per_min_per_ip, st.live_runs_per_day)
    shared = FirestoreLimiter(fs, st.live_runs_per_min_per_ip, st.live_runs_per_day) if fs is not None else None  # fmt: skip
    ctx = AppContext(
        settings=st,
        provider=provider,
        audit=audit,
        cmms_live=cmms_live,
        cmms_demo=cmms_demo,
        replays=ReplayCatalog(st.replay_dir, audit),
        limiter=Limiter(memory, shared),
        budget=budget,
        live_runner=live_runner or default_live_runner(provider, cmms_live),
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        await AuditRecorder.drain_all(10.0)  # let in-flight audit writes finish on SIGTERM
        budget.close()

    app = FastAPI(
        title="Andon Agent API",
        version=config.APP_VERSION,
        docs_url=None if _ON_CLOUD_RUN else "/docs",
        redoc_url=None,
        openapi_url=None if _ON_CLOUD_RUN else "/openapi.json",
        lifespan=lifespan,
    )
    app.state.ctx = ctx
    app.include_router(build_router(ctx))
    app.add_middleware(BodyLimitMiddleware, max_bytes=st.max_body_bytes)
    app.add_middleware(  # outermost, so 413/401 responses carry CORS headers too
        CORSMiddleware,
        allow_origins=list(st.allowed_origins),
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type", "X-Demo-Passcode", "Last-Event-ID"],
        expose_headers=["X-Incident-Id", "Retry-After"],
        max_age=600,
    )
    return app


app = create_app()
