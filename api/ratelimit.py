"""Live-run limits: per client IP per minute and a global per-day cap (SECURITY "Public surface").

* :class:`MemoryLimiter` — per process; always applied first so a flood never reaches Firestore.
* :class:`FirestoreLimiter` — counters shared across instances: ``ratelimit_ip/{sha(ip)}_{epoch
  minute}`` and ``ratelimit_day/{IST date}``, atomic ``Increment`` then read. A rejected attempt
  also counts (it can only over-reject, never under-reject). IPs are stored hashed. The per-IP
  documents carry ``expires_at`` for a Firestore TTL policy.

Only passcode-holders reach the limiter, so quota cannot be burnt by anonymous traffic.
"""

from __future__ import annotations

import hashlib
import math
import threading
import time
from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import config
from api.fs import ist_day


@dataclass(frozen=True)
class Decision:
    allowed: bool
    scope: str | None = None  # "ip_minute" | "day"
    retry_after_s: int = 0


ALLOW = Decision(True)


def _secs_to_next_minute(now: float) -> int:
    return max(1, math.ceil(60 - (now % 60)))


def _secs_to_next_day(now: float) -> int:
    """Seconds until the next IST midnight (the day the budget and the quota roll on)."""
    tz = ZoneInfo(config.BUDGET_TIMEZONE)
    at = datetime.fromtimestamp(now, tz)
    nxt = (at + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return max(1, int((nxt - at).total_seconds()))


class MemoryLimiter:
    def __init__(self, per_min: int, per_day: int, clock: Any = time.time) -> None:
        self.per_min, self.per_day = per_min, per_day
        self._clock = clock
        self._hits: dict[str, deque[float]] = {}
        self._day = ""
        self._day_n = 0
        self._lock = threading.Lock()

    def acquire(self, ip: str) -> Decision:
        now = self._clock()
        today = ist_day(datetime.fromtimestamp(now, UTC))
        with self._lock:
            if today != self._day:
                self._day, self._day_n = today, 0
            q = self._hits.setdefault(ip, deque())
            while q and now - q[0] >= 60:
                q.popleft()
            if len(q) >= self.per_min:
                return Decision(False, "ip_minute", max(1, math.ceil(60 - (now - q[0]))))
            if self._day_n >= self.per_day:
                return Decision(False, "day", _secs_to_next_day(now))
            q.append(now)
            self._day_n += 1
            if len(self._hits) > 4096:  # bound memory under an IP flood
                for k in [k for k, v in self._hits.items() if not v or now - v[-1] >= 60]:
                    del self._hits[k]
            return ALLOW


class FirestoreLimiter:
    def __init__(
        self,
        client: Any,
        per_min: int,
        per_day: int,
        clock: Any = time.time,
        *,
        ip_collection: str = "ratelimit_ip",
        day_collection: str | None = "ratelimit_day",  # None: no global daily cap (replays)
    ) -> None:
        self._ip = client.collection(ip_collection)
        self._day = client.collection(day_collection) if day_collection else None
        self.per_min, self.per_day = per_min, per_day
        self._clock = clock

    def _bump(self, ref: Any, extra: dict | None = None) -> int:
        from google.cloud import firestore

        ref.set({"n": firestore.Increment(1), **(extra or {})}, merge=True)
        return int((ref.get().to_dict() or {}).get("n", 0))

    def acquire(self, ip: str) -> Decision:
        now = self._clock()
        minute = int(now // 60)
        key = f"{hashlib.sha256(ip.encode()).hexdigest()[:24]}_{minute}"
        expires = datetime.fromtimestamp(now, UTC) + timedelta(minutes=10)
        if self._bump(self._ip.document(key), {"expires_at": expires}) > self.per_min:
            return Decision(False, "ip_minute", _secs_to_next_minute(now))
        if self._day is None:
            return ALLOW
        today = ist_day(datetime.fromtimestamp(now, UTC))
        if self._bump(self._day.document(today)) > self.per_day:
            return Decision(False, "day", _secs_to_next_day(now))
        return ALLOW


class Limiter:
    """Memory first, then the shared (Firestore) counters when configured."""

    def __init__(self, memory: MemoryLimiter, shared: FirestoreLimiter | None = None) -> None:
        self.memory, self.shared = memory, shared

    def acquire(self, ip: str) -> Decision:
        d = self.memory.acquire(ip)
        if not d.allowed or self.shared is None:
            return d
        return self.shared.acquire(ip)


class FailureLimiter:
    """Brute-force guard for the passcode: ``max_fail`` wrong attempts per IP per window."""

    def __init__(self, max_fail: int = 10, window_s: float = 300.0, clock: Any = time.time) -> None:
        self.max_fail, self.window_s, self._clock = max_fail, window_s, clock
        self._fails: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def _prune(self, ip: str, now: float) -> deque[float]:
        q = self._fails.setdefault(ip, deque())
        while q and now - q[0] >= self.window_s:
            q.popleft()
        return q

    def blocked(self, ip: str) -> int:
        """Seconds to wait, 0 if the IP may try."""
        now = self._clock()
        with self._lock:
            q = self._prune(ip, now)
            return math.ceil(self.window_s - (now - q[0])) if len(q) >= self.max_fail else 0

    def fail(self, ip: str) -> None:
        now = self._clock()
        with self._lock:
            self._prune(ip, now).append(now)
            if len(self._fails) > 4096:
                for k in [k for k, v in self._fails.items() if not v]:
                    del self._fails[k]
