"""Daily spend kill switch shared across Cloud Run instances (RISKS #23, ADR-008).

``agents.llm.SpendTracker`` counts per process. :class:`BudgetGuard` hooks into it so that

* every booked call is added to the shared counter (Firestore ``spend/{IST date}``, atomic
  ``Increment``; in memory when Firestore is off), and
* ``SpendTracker.check()`` — called before every model call, including those of a run already in
  flight — also compares the *shared* total with the budget and raises ``BudgetExhaustedError``.

``check()`` is synchronous and must stay cheap, so it reads a cached shared total that is refreshed
in a worker thread (after each flush and at most every ``refresh_s``). Starting a live run does a
fresh read and fails closed: if the shared counter cannot be read, no new live run starts.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Any, Protocol
from zoneinfo import ZoneInfo

import config
from agents.llm import BudgetExhaustedError, SpendTracker
from api.fs import ist_day

log = logging.getLogger("andon.budget")
COLLECTION = "spend"


class SpendStore(Protocol):
    def add(self, day: str, usd: float) -> None: ...
    def read(self, day: str) -> float: ...


class MemorySpendStore:
    def __init__(self) -> None:
        self._d: dict[str, float] = {}
        self._lock = threading.Lock()

    def add(self, day: str, usd: float) -> None:
        with self._lock:
            self._d[day] = self._d.get(day, 0.0) + usd

    def read(self, day: str) -> float:
        return self._d.get(day, 0.0)


class FirestoreSpendStore:
    """``spend/{YYYY-MM-DD}`` -> ``{usd}``; the only writes are atomic increments."""

    def __init__(self, client: Any) -> None:
        self._col = client.collection(COLLECTION)

    def add(self, day: str, usd: float) -> None:
        from google.cloud import firestore

        self._col.document(day).set({"usd": firestore.Increment(usd)}, merge=True)

    def read(self, day: str) -> float:
        snap = self._col.document(day).get()
        return float((snap.to_dict() or {}).get("usd", 0.0)) if snap.exists else 0.0


class BudgetGuard:
    def __init__(
        self,
        tracker: SpendTracker,
        store: SpendStore | None = None,
        *,
        budget_usd: float | None = None,
        refresh_s: float = 15.0,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.tracker = tracker
        self.store: SpendStore = store or MemorySpendStore()
        self.budget_usd = tracker.daily_budget_usd if budget_usd is None else budget_usd
        tracker.daily_budget_usd = self.budget_usd
        self.refresh_s = refresh_s
        tz = ZoneInfo(config.BUDGET_TIMEZONE)
        self._clock = clock or (lambda: datetime.now(tz))
        self._exec = ThreadPoolExecutor(max_workers=1, thread_name_prefix="andon-spend")
        self._lock = threading.Lock()
        self._remote = 0.0
        self._remote_day = self.day()
        self._last_refresh = 0.0
        self._refreshing = False
        tracker.add_listener(self._on_spend)
        tracker.add_guard(self.check)

    def day(self) -> str:
        return ist_day(self._clock())

    # ---- shared total -------------------------------------------------------------------
    def _set_remote(self, day: str, usd: float) -> None:
        with self._lock:
            if day != self._remote_day:
                self._remote_day, self._remote = day, 0.0
            self._remote = max(self._remote, usd)
            self._last_refresh = time.monotonic()

    def _flush(self, day: str, usd: float) -> None:
        try:
            self.store.add(day, usd)
            self._set_remote(day, self.store.read(day))
        except Exception:
            log.exception("could not persist spend (%s, %.6f)", day, usd)

    def _on_spend(self, usd: float) -> None:
        self._exec.submit(self._flush, self.day(), usd)

    def _refresh(self) -> None:
        day = self.day()
        try:
            self._set_remote(day, self.store.read(day))
        except Exception:
            log.exception("could not refresh shared spend")
        finally:
            self._refreshing = False

    def spent_today(self) -> float:
        with self._lock:
            remote = self._remote if self._remote_day == self.day() else 0.0
        return max(self.tracker.spent_today(), remote)

    def remaining(self) -> float:
        return max(self.budget_usd - self.spent_today(), 0.0)

    # ---- guard (runs inside SpendTracker.check) -----------------------------------------
    def check(self) -> None:
        if time.monotonic() - self._last_refresh > self.refresh_s and not self._refreshing:
            self._refreshing = True
            self._exec.submit(self._refresh)
        spent = self.spent_today()
        if spent >= self.budget_usd:
            raise BudgetExhaustedError(
                f"daily budget ${self.budget_usd:.2f} exhausted (shared spend ${spent:.4f} on "
                f"{self.day()})"
            )

    async def check_fresh(self) -> None:
        """Before a live run: re-read the shared counter (blocking I/O off the loop) and fail
        closed. Raises ``BudgetExhaustedError``."""
        day = self.day()
        try:
            usd = await asyncio.to_thread(self.store.read, day)
        except Exception as exc:
            log.exception("shared spend unreadable; refusing live run")
            raise BudgetExhaustedError("budget state unavailable; live mode paused") from exc
        self._set_remote(day, usd)
        self.check()

    def drain(self, timeout_s: float = 5.0) -> None:
        """Wait for queued flushes (shutdown, tests)."""
        self._exec.submit(lambda: None).result(timeout=timeout_s)

    def close(self) -> None:
        self.drain()
        self._exec.shutdown(wait=False)
