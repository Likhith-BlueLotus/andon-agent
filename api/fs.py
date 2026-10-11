"""Lazy Firestore client: importing the API (and building the app) never touches the network or
needs credentials; the first real read/write creates the client."""

from __future__ import annotations

import threading
from typing import Any

import config


class LazyFirestore:
    """Duck-typed stand-in for ``google.cloud.firestore.Client``."""

    def __init__(self, factory: Any = None) -> None:
        self._factory = factory
        self._client: Any = None
        self._lock = threading.Lock()

    def _get(self) -> Any:
        with self._lock:
            if self._client is None:
                if self._factory is not None:
                    self._client = self._factory()
                else:  # pragma: no cover - needs ADC
                    from google.cloud import firestore

                    self._client = firestore.Client(project=config.PROJECT or None)
            return self._client

    def __getattr__(self, name: str) -> Any:
        return getattr(self._get(), name)


def ist_day(now: Any = None) -> str:
    """The kill-switch day (IST) as ``YYYY-MM-DD``."""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    tz = ZoneInfo(config.BUDGET_TIMEZONE)
    return (now or datetime.now(tz)).astimezone(tz).date().isoformat()
