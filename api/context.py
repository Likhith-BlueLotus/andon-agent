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
from api.ratelimit import FailureLimiter, Limiter, MemoryLimiter
from api.replay import ReplayCatalog
from api.settings import Settings
from api.stores import StoreProvider

log = logging.getLogger("andon.api")
TELEMETRY_READS_PER_MIN_PER_IP = 60

# (scenario_id, incident_id) -> contract events of one live run
LiveRunner = Callable[[str, str], AsyncIterator[Event]]


class SlotPool:
    """Concurrency slots as leases: released when the response ends (``routes.SlotResponse``
    always runs it) and, as a backstop, expired after ``lease_s``, so nothing can hold one
    forever."""

    def __init__(self, size: int, lease_s: float) -> None:
        self.size, self.lease_s = size, lease_s
        self._slots: dict[str, float] = {}
        self._lock = threading.Lock()

    def acquire(self) -> str | None:
        now = time.monotonic()
        with self._lock:
            self._slots = {t: d for t, d in self._slots.items() if d > now}
            if len(self._slots) >= self.size:
                return None
            token = uuid.uuid4().hex
            self._slots[token] = now + self.lease_s
            return token

    def release(self, token: str | None) -> None:
        with self._lock:
            self._slots.pop(token or "", None)

    @property
    def active(self) -> int:
        now = time.monotonic()
        with self._lock:
            return sum(1 for d in self._slots.values() if d > now)


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
    replay_limiter: Limiter | None = None
    telemetry_limiter: Limiter | None = None  # chart reads: per instance, per IP, memory only
    live_slots: SlotPool = field(init=False)
    replay_slots: SlotPool = field(init=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _scenarios: tuple[float, list[dict]] | None = field(default=None, repr=False)

    # ---- published scenarios (cached 60 s) ------------------------------------------------
    async def scenarios(self) -> list[dict]:
        now = time.monotonic()
        if self._scenarios is None or now - self._scenarios[0] > 60:
            rows = await asyncio.to_thread(self.provider.list_scenarios)
            self._scenarios = (now, rows)
        return self._scenarios[1]

    def __post_init__(self) -> None:
        lease = self.settings.run_timeout_s + 60.0
        self.live_slots = SlotPool(self.settings.max_concurrent_live, lease)
        self.replay_slots = SlotPool(self.settings.max_concurrent_replay, lease)
        if self.telemetry_limiter is None:
            self.telemetry_limiter = Limiter(MemoryLimiter(TELEMETRY_READS_PER_MIN_PER_IP, 10**9))
        if self.replay_limiter is None:
            self.replay_limiter = Limiter(
                MemoryLimiter(self.settings.replay_runs_per_min_per_ip, 10**9)
            )
