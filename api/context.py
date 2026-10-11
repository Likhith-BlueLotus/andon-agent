"""Everything the routes share, built once by :func:`api.main.create_app` and injectable in tests."""

from __future__ import annotations

import asyncio
import logging
import threading
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field

from agents.cmms import Decidable
from api.audit import AuditStore
from api.budget import BudgetGuard
from api.events import Event
from api.ratelimit import FailureLimiter, Limiter
from api.replay import ReplayCatalog
from api.settings import Settings
from api.stores import StoreProvider

log = logging.getLogger("andon.api")

# (scenario_id, incident_id) -> contract events of one live run
LiveRunner = Callable[[str, str], AsyncIterator[Event]]


@dataclass
class AppContext:
    settings: Settings
    provider: StoreProvider
    audit: AuditStore
    cmms_live: Decidable  # the mock CMMS (``work_orders``); the drafter writes here
    cmms_demo: Decidable  # anonymous replay approvals (``demo_work_orders``)
    replays: ReplayCatalog
    limiter: Limiter
    budget: BudgetGuard
    live_runner: LiveRunner
    failures: FailureLimiter = field(default_factory=FailureLimiter)
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep  # replay pacing (tests inject)
    lease_s: float = 0.0  # set in __post_init__ from the run timeout
    _slots: dict[str, float] = field(default_factory=dict, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _scenarios: tuple[float, list[dict]] | None = field(default=None, repr=False)

    # ---- concurrency slots (per instance) ------------------------------------------------
    # A slot is a lease: released when the response ends (always, see routes.SlotResponse) and, as
    # a backstop, expired after ``lease_s`` so no code path can hold a slot forever.
    def acquire_live_slot(self) -> str | None:
        now = time.monotonic()
        with self._lock:
            self._slots = {t: d for t, d in self._slots.items() if d > now}
            if len(self._slots) >= self.settings.max_concurrent_live:
                return None
            token = uuid.uuid4().hex
            self._slots[token] = now + self.lease_s
            return token

    def release_live_slot(self, token: str | None) -> None:
        with self._lock:
            self._slots.pop(token or "", None)

    @property
    def _live_active(self) -> int:
        now = time.monotonic()
        with self._lock:
            return sum(1 for d in self._slots.values() if d > now)

    # ---- published scenarios (cached 60 s) ------------------------------------------------
    async def scenarios(self) -> list[dict]:
        now = time.monotonic()
        if self._scenarios is None or now - self._scenarios[0] > 60:
            rows = await asyncio.to_thread(self.provider.list_scenarios)
            self._scenarios = (now, rows)
        return self._scenarios[1]

    def __post_init__(self) -> None:
        if not self.lease_s:
            self.lease_s = self.settings.run_timeout_s + 60.0
