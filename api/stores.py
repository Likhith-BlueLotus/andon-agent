"""Where the API gets telemetry stores and the list of published scenarios.

* ``STORE_BACKEND=duckdb`` — the local ``data/andon.duckdb`` (dev, tests, the laptop live run);
  one read-only connection per run, so concurrent runs never share a DuckDB connection.
* anything else (``gcs``) — ``agents.store_cache`` (per-incident DuckDB from the scenario's Parquet in GCS):
  ``get_store(scenario_id)`` is a context manager yielding a ``TelemetryStore`` and
  ``list_published()`` lists the published scenarios.

Scenario metadata exposed here is **published metadata only** (stop record + provenance source
ids). Ground truth is never read by the API (guard test in tests/test_guards.py).
"""

from __future__ import annotations

import contextlib
import threading
from collections.abc import Iterator
from contextlib import AbstractContextManager
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

from api.settings import Settings
from simulator.load import DuckDBStore, TelemetryStore


def _iso(ts: Any) -> str:
    """DuckDB renders timestamptz as ``2026-08-25 01:33:39+00``; return ISO 8601."""
    try:
        return datetime.fromisoformat(str(ts)).isoformat()
    except ValueError:
        return str(ts)


class StoreProvider(Protocol):
    def list_scenarios(self) -> list[dict[str, Any]]:
        """``[{scenario_id, line_id, stopped_station, stop_ts, sources: [source_id, ...]}]``."""
        ...

    def open(self, scenario_id: str) -> AbstractContextManager[TelemetryStore]:
        """Blocking (may download); call from a worker thread."""
        ...


class LocalDuckDBProvider:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._cache: list[dict[str, Any]] | None = None
        self._lock = threading.Lock()

    def list_scenarios(self) -> list[dict[str, Any]]:
        with self._lock:
            if self._cache is None:
                store = DuckDBStore(self.path)
                try:
                    stops = store.con.execute(
                        "SELECT scenario_id, line_id, stopped_station, CAST(stop_ts AS VARCHAR) FROM stop_events "
                        "ORDER BY scenario_id"
                    ).fetchall()
                    prov: dict[str, list[str]] = {}
                    for sid, src in store.con.execute(
                        "SELECT DISTINCT scenario_id, source_id FROM provenance ORDER BY 1, 2"
                    ).fetchall():
                        prov.setdefault(sid, []).append(src)
                finally:
                    store.close()
                self._cache = [
                    {"scenario_id": sid, "line_id": line, "stopped_station": st,
                     "stop_ts": _iso(ts),
                     "sources": prov.get(sid, [])}
                    for sid, line, st, ts in stops
                ]  # fmt: skip
            return list(self._cache)

    @contextlib.contextmanager
    def open(self, scenario_id: str) -> Iterator[TelemetryStore]:
        store = DuckDBStore(self.path)
        try:
            yield store
        finally:
            store.close()


class PublishedProvider:  # pragma: no cover - needs GCS; thin adapter over agents.store_cache
    @property
    def _sc(self) -> Any:
        from agents import store_cache  # imported lazily: the module is owned by another task

        return store_cache

    def list_scenarios(self) -> list[dict[str, Any]]:
        out = []
        for r in self._sc.list_published():
            out.append(
                {
                    "scenario_id": r["scenario_id"],
                    "line_id": r.get("line_id") or "L1",
                    "stopped_station": r.get("stopped_station") or r.get("station") or "",
                    "stop_ts": str(r.get("stop_ts") or ""),
                    "sources": list(r.get("sources") or r.get("source_ids") or []),
                }
            )
        return sorted(out, key=lambda r: r["scenario_id"])

    def open(self, scenario_id: str) -> AbstractContextManager[TelemetryStore]:
        return self._sc.get_store(scenario_id)


def make_provider(settings: Settings) -> StoreProvider:
    if settings.store_backend == "duckdb":
        return LocalDuckDBProvider(settings.local_db)
    return PublishedProvider()
