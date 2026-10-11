"""Live serving store: a per-incident DuckDB built from the scenario's published Parquet (ADR-021).

BigQuery tool queries take 7-16 s (RISKS #24); a local DuckDB over one scenario's ~10 MB of
Parquet answers in milliseconds. At incident start :func:`get_store` downloads that scenario's
objects from ``gs://<bucket>/store/v1/{scenario_id}/`` (and ``_shared/`` once), verifies every
sha256 against ``store/v1/manifest.json``, builds a DuckDB with :func:`simulator.load.load_duckdb`
(the same load path as the local store; no fork) and returns a store bound to that scenario.

    with get_store("R002") as store:          # TelemetryStore; also usable without ``with``
        store.query_telemetry("R002", "UT-AIR", ["header_pressure_bar"], t0, t1)
    await aget_store("R002")                  # same, from async code (build in a worker thread)
    list_published()                          # [{scenario_id, set, source_label, sources, ...}]
    open_store()                              # by STORE_BACKEND: duckdb | gcs | bigquery

Only agent-visible objects exist under ``store/v1`` (see ``simulator.publish``), and this module
refuses any object name outside the allow-list in :mod:`simulator.blobstore`.

Cache: ``STORE_CACHE_DIR`` (default ``/tmp/andon-store``; on Cloud Run that is in-memory tmpfs,
~10 MB per scenario), LRU of ``STORE_CACHE_MAX`` scenarios (default 8). Evicting closes the DuckDB
connection and deletes the files, but never while a ``with`` block holds the scenario. Two
incidents asking for the same scenario at once build it once (single flight, threads and asyncio).
A scenario whose manifest entry changes is rebuilt on its next use.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import threading
import time
import uuid
from collections import OrderedDict
from collections.abc import Callable, Sequence
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow.parquet as pq

import config
from simulator import plant
from simulator.blobstore import (
    MANIFEST_NAME,
    SCENARIO_ID_RE,
    SCENARIO_OBJECTS,
    SHARED_DIR,
    SHARED_OBJECTS,
    STORE_PREFIX,
    GcsBucket,
    ObjectReader,
    object_name,
    sha256_hex,
)
from simulator.load import DuckDBStore, TelemetryStore, TimeLike, load_duckdb

log = logging.getLogger(__name__)

STAMP = ".stamp.json"
DB_NAME = "store.duckdb"


class StoreIntegrityError(RuntimeError):
    """A downloaded object does not match the manifest's sha256 (or the manifest is unusable)."""


class UnknownScenarioError(KeyError):
    """The scenario is not in the published manifest."""


def _settings() -> tuple[Path, int, str, str, float]:
    return (
        Path(os.environ.get("STORE_CACHE_DIR", config.STORE_CACHE_DIR)),
        int(os.environ.get("STORE_CACHE_MAX", config.STORE_CACHE_MAX)),
        os.environ.get("STORE_BUCKET") or config.GCS_BUCKET or config.STORE_BUCKET,
        os.environ.get("STORE_PREFIX", STORE_PREFIX),
        float(os.environ.get("STORE_MANIFEST_TTL_S", config.STORE_MANIFEST_TTL_S)),
    )


class _LockedDuckDBStore(DuckDBStore):
    """One DuckDB connection must not run two queries at once; serialise per scenario."""

    def __init__(self, path: Path) -> None:
        super().__init__(path)
        self._qlock = threading.Lock()

    def _q(self, sql: str, params: dict[str, Any]) -> pd.DataFrame:
        with self._qlock:
            return super()._q(sql, params)


@dataclass
class _Entry:
    scenario_id: str
    path: Path
    store: _LockedDuckDBStore
    stamp: dict[str, Any]
    refs: int = 0
    bytes: int = 0
    build_s: float = 0.0


@dataclass
class BuildStats:
    builds: dict[str, int] = field(default_factory=dict)
    downloads: int = 0
    evictions: list[str] = field(default_factory=list)


class StoreCache:
    """Downloads, verifies, builds and caches per-scenario DuckDB stores."""

    def __init__(
        self,
        reader: ObjectReader | None = None,
        *,
        cache_dir: Path | str | None = None,
        max_entries: int | None = None,
        prefix: str | None = None,
        manifest_ttl_s: float | None = None,
        bucket: str | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        d_dir, d_max, d_bucket, d_prefix, d_ttl = _settings()
        self.reader: ObjectReader = reader or GcsBucket(bucket or d_bucket)
        self.cache_dir = Path(cache_dir) if cache_dir is not None else d_dir
        self.max_entries = max(1, max_entries if max_entries is not None else d_max)
        self.prefix = (prefix or d_prefix).strip("/")
        self.manifest_ttl_s = manifest_ttl_s if manifest_ttl_s is not None else d_ttl
        self._clock = clock
        self._lock = threading.RLock()
        self._entries: OrderedDict[str, _Entry] = OrderedDict()
        self._building: dict[str, Future[_Entry]] = {}
        self._shared_lock = threading.Lock()
        self._manifest: dict[str, Any] | None = None
        self._manifest_at = -1e18
        self._manifest_lock = threading.Lock()
        self.stats = BuildStats()
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        for p in self.cache_dir.glob(".build-*"):  # leftovers of a crashed build
            shutil.rmtree(p, ignore_errors=True)

    # ---- manifest ----------------------------------------------------------------------
    def manifest(self, refresh: bool = False) -> dict[str, Any]:
        with self._manifest_lock:
            fresh = self._clock() - self._manifest_at < self.manifest_ttl_s
            if self._manifest is None or refresh or not fresh:
                try:
                    m = json.loads(self.reader.read(object_name(self.prefix, MANIFEST_NAME)))
                    self._validate_manifest(m)
                except Exception:
                    if self._manifest is None or refresh:
                        raise
                    # a TTL refresh must not fail a tool call mid-incident: keep the last good one
                    log.warning(
                        "manifest refresh failed; keeping the cached manifest", exc_info=True
                    )
                    self._manifest_at = self._clock()
                    return self._manifest
                self._manifest, self._manifest_at = m, self._clock()
            return self._manifest

    @staticmethod
    def _validate_manifest(m: dict[str, Any]) -> None:
        if not isinstance(m.get("scenarios"), dict) or not isinstance(m.get("shared"), dict):
            raise StoreIntegrityError("manifest lacks scenarios/shared")
        if set(m["shared"]) - set(SHARED_OBJECTS):
            raise StoreIntegrityError(f"manifest shared objects outside allow-list: {m['shared']}")
        for sid, e in m["scenarios"].items():
            if not SCENARIO_ID_RE.match(sid):
                raise StoreIntegrityError(f"manifest has bad scenario id {sid!r}")
            extra = set(e.get("objects", {})) - set(SCENARIO_OBJECTS)
            if extra:
                raise StoreIntegrityError(f"{sid}: objects outside allow-list {sorted(extra)}")

    def list_published(self) -> list[dict[str, Any]]:
        """Published scenarios with display metadata only (no objects, no truth)."""
        out = []
        for sid, e in sorted(self.manifest()["scenarios"].items()):
            row = {k: v for k, v in e.items() if k != "objects"}
            out.append({"scenario_id": sid, **row})
        return out

    def _entry_spec(self, sid: str) -> tuple[dict[str, Any], dict[str, Any]]:
        if not SCENARIO_ID_RE.match(sid):
            raise UnknownScenarioError(sid)
        m = self.manifest()
        if sid not in m["scenarios"]:
            m = self.manifest(refresh=True)
            if sid not in m["scenarios"]:
                raise UnknownScenarioError(sid)
        return m["scenarios"][sid]["objects"], m["shared"]

    def _expected_stamp(self, sid: str) -> dict[str, Any]:
        objs, shared = self._entry_spec(sid)
        return {
            "scenario_id": sid,
            "objects": {k: v["sha256"] for k, v in sorted(objs.items())},
            "shared": {k: v["sha256"] for k, v in sorted(shared.items())},
        }

    # ---- downloads ---------------------------------------------------------------------
    def _fetch(self, name: str, want_sha: str, dest: Path) -> int:
        data = self.reader.read(name)
        got = sha256_hex(data)
        if got != want_sha:
            raise StoreIntegrityError(f"{name}: sha256 {got[:12]}… != manifest {want_sha[:12]}…")
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_name(dest.name + f".{uuid.uuid4().hex[:8]}.part")
        tmp.write_bytes(data)
        tmp.replace(dest)
        with self._lock:
            self.stats.downloads += 1
        return len(data)

    @staticmethod
    def _file_ok(path: Path, sha: str) -> bool:
        return path.is_file() and sha256_hex(path.read_bytes()) == sha

    def _ensure_shared(self, shared: dict[str, Any]) -> Path:
        d = self.cache_dir / SHARED_DIR
        with self._shared_lock:
            for name, meta in shared.items():
                if not self._file_ok(d / name, meta["sha256"]):
                    self._fetch(
                        object_name(self.prefix, SHARED_DIR, name), meta["sha256"], d / name
                    )
        return d

    def _build(self, sid: str) -> _Entry:
        t0 = time.perf_counter()
        objs, shared = self._entry_spec(sid)
        stamp = self._expected_stamp(sid)
        final = self.cache_dir / sid
        adopted = self._adopt(final, stamp)
        if adopted is not None:
            return adopted
        try:
            return self._download_and_load(sid, objs, shared, stamp, final, t0)
        except StoreIntegrityError:
            # the publisher may have replaced objects after we read the manifest: retry once
            objs, shared = self._entry_spec_refreshed(sid)
            stamp = self._expected_stamp(sid)
            return self._download_and_load(sid, objs, shared, stamp, final, t0)

    def _entry_spec_refreshed(self, sid: str) -> tuple[dict[str, Any], dict[str, Any]]:
        self.manifest(refresh=True)
        return self._entry_spec(sid)

    def _adopt(self, final: Path, stamp: dict[str, Any]) -> _Entry | None:
        """Reuse a complete build left on disk (e.g. by an earlier process) if it still matches."""
        try:
            if json.loads((final / STAMP).read_text()) != stamp:
                return None
        except (OSError, ValueError):
            return None
        for name, sha in stamp["objects"].items():
            if not self._file_ok(final / "scenarios" / stamp["scenario_id"] / name, sha):
                return None
        self._ensure_shared({k: {"sha256": v} for k, v in stamp["shared"].items()})
        store = _LockedDuckDBStore(final / DB_NAME)
        return _Entry(stamp["scenario_id"], final, store, stamp, bytes=_du(final))

    def _download_and_load(
        self,
        sid: str,
        objs: dict[str, Any],
        shared: dict[str, Any],
        stamp: dict[str, Any],
        final: Path,
        t0: float,
    ) -> _Entry:
        shared_dir = self._ensure_shared(shared)
        work = self.cache_dir / f".build-{sid}-{uuid.uuid4().hex[:8]}"
        scen = work / "scenarios" / sid
        try:
            with ThreadPoolExecutor(max_workers=min(8, len(objs))) as pool:
                futs = [
                    pool.submit(
                        self._fetch, object_name(self.prefix, sid, n), m["sha256"], scen / n
                    )
                    for n, m in objs.items()
                ]
                for f in futs:
                    f.result()
            static = {
                "assets": pq.read_table(shared_dir / "assets.parquet"),
                "spec_limits": pq.read_table(shared_dir / "spec_limits.parquet"),
            }
            built = load_duckdb(
                work / "scenarios",
                work / DB_NAME,
                history=shared_dir / "work_orders.parquet",
                static=static,
            )
            built.close()
            (work / STAMP).write_text(json.dumps(stamp, sort_keys=True))
            with self._lock:
                if final.exists():
                    shutil.rmtree(final, ignore_errors=True)
                work.rename(final)
        except BaseException:
            shutil.rmtree(work, ignore_errors=True)
            raise
        store = _LockedDuckDBStore(final / DB_NAME)
        dt = time.perf_counter() - t0
        log.info("store %s built in %.2f s (%d bytes)", sid, dt, _du(final))
        return _Entry(sid, final, store, stamp, bytes=_du(final), build_s=dt)

    # ---- LRU + single flight -----------------------------------------------------------
    def acquire(self, sid: str) -> _Entry:
        """Take a reference (blocks while building). Pair with :meth:`release`."""
        expected = self._expected_stamp(sid)
        while True:
            with self._lock:
                e = self._entries.get(sid)
                if e is not None and e.stamp != expected and e.refs == 0:
                    self._drop_locked(sid)  # republished: rebuild
                    e = None
                if e is not None:
                    e.refs += 1
                    self._entries.move_to_end(sid)
                    return e
                fut = self._building.get(sid)
                builder = fut is None
                if builder:
                    fut = Future()
                    self._building[sid] = fut
            assert fut is not None
            if not builder:
                fut.result()  # re-raises the builder's error
                continue  # take the reference under the lock (it may have been evicted)
            try:
                e = self._build(sid)
            except BaseException as exc:
                with self._lock:
                    self._building.pop(sid, None)
                fut.set_exception(exc)
                raise
            with self._lock:
                self.stats.builds[sid] = self.stats.builds.get(sid, 0) + 1
                self._entries[sid] = e
                self._building.pop(sid, None)
                e.refs += 1
                self._evict_locked()
            fut.set_result(e)
            return e

    def release(self, entry: _Entry) -> None:
        with self._lock:
            entry.refs = max(0, entry.refs - 1)
            self._evict_locked()

    def _evict_locked(self) -> None:
        while len(self._entries) > self.max_entries:
            victim = next((s for s, e in self._entries.items() if e.refs == 0), None)
            if victim is None:  # everything is in use: stay over the cap until released
                log.warning("store cache over cap (%d > %d): all in use", len(self._entries),
                            self.max_entries)  # fmt: skip
                return
            self._drop_locked(victim)
            self.stats.evictions.append(victim)

    def _drop_locked(self, sid: str) -> None:
        e = self._entries.pop(sid)
        try:
            e.store.close()
        finally:
            shutil.rmtree(e.path, ignore_errors=True)

    def cached(self) -> list[str]:
        with self._lock:
            return list(self._entries)

    def clear(self) -> None:
        with self._lock:
            for sid in [s for s, e in self._entries.items() if e.refs == 0]:
                self._drop_locked(sid)

    # ---- public getters ----------------------------------------------------------------
    def get(self, scenario_id: str) -> ScenarioStore:
        """Build (or reuse) the scenario now and return a store bound to it."""
        self.release(self.acquire(scenario_id))
        return ScenarioStore(self, scenario_id)

    async def aget(self, scenario_id: str) -> ScenarioStore:
        return await asyncio.to_thread(self.get, scenario_id)


class ScenarioStore:
    """``TelemetryStore`` for one published scenario. Each call holds a reference for its
    duration (rebuilding transparently if the scenario was evicted); a ``with`` block holds one
    for the whole incident so the files cannot be evicted mid-run."""

    def __init__(self, cache: StoreCache, scenario_id: str) -> None:
        self.cache = cache
        self.scenario_id = scenario_id
        self._held: list[_Entry] = []
        self._held_lock = threading.Lock()

    def __enter__(self) -> ScenarioStore:
        e = self.cache.acquire(self.scenario_id)
        with self._held_lock:
            self._held.append(e)
        return self

    def __exit__(self, *exc: object) -> None:
        with self._held_lock:
            e = self._held.pop() if self._held else None
        if e is not None:
            self.cache.release(e)

    def close(self) -> None:
        while self._held:
            self.__exit__(None, None, None)

    @property
    def scenario_dir(self) -> Path:
        """Local dir holding this scenario's published files (e.g. ``audio_index.json``)."""
        return self.cache.cache_dir / self.scenario_id / "scenarios" / self.scenario_id

    def _call(self, sid: str | None, fn: Callable[[DuckDBStore], Any]) -> Any:
        if sid is not None and sid != self.scenario_id:
            raise KeyError(f"store is bound to {self.scenario_id!r}, not {sid!r}")
        e = self.cache.acquire(self.scenario_id)
        try:
            return fn(e.store)
        finally:
            self.cache.release(e)

    # TelemetryStore
    def list_scenarios(self) -> list[str]:
        return [self.scenario_id]

    def get_stop_event(self, scenario_id: str) -> dict[str, Any]:
        return self._call(scenario_id, lambda s: s.get_stop_event(scenario_id))

    def list_assets(
        self, line_id: str = plant.LINE_ID, upstream_of: str | None = None
    ) -> list[dict[str, Any]]:
        return self._call(None, lambda s: s.list_assets(line_id, upstream_of))

    def spec_limits(self, asset_id: str | None = None) -> list[dict[str, Any]]:
        return self._call(None, lambda s: s.spec_limits(asset_id))

    def query_telemetry(
        self, scenario_id: str, asset_id: str, tags: Sequence[str], t0: TimeLike, t1: TimeLike
    ) -> pd.DataFrame:
        return self._call(
            scenario_id, lambda s: s.query_telemetry(scenario_id, asset_id, tags, t0, t1)
        )

    def get_alarms(
        self, scenario_id: str, t0: TimeLike, t1: TimeLike, codes: Sequence[str] | None = None,
        asset_ids: Sequence[str] | None = None,
    ) -> pd.DataFrame:  # fmt: skip
        return self._call(
            scenario_id, lambda s: s.get_alarms(scenario_id, t0, t1, codes, asset_ids)
        )

    def get_shift_notes(self, scenario_id: str, t0: TimeLike, t1: TimeLike) -> pd.DataFrame:
        return self._call(scenario_id, lambda s: s.get_shift_notes(scenario_id, t0, t1))

    def get_work_orders(
        self, scenario_id: str, asset_id: str, since: TimeLike, limit: int | None = None
    ) -> pd.DataFrame:
        return self._call(
            scenario_id, lambda s: s.get_work_orders(scenario_id, asset_id, since, limit)
        )

    def get_provenance(
        self, scenario_id: str, asset_id: str | None = None, tags: Sequence[str] | None = None,
        t0: TimeLike | None = None, t1: TimeLike | None = None,
    ) -> pd.DataFrame:  # fmt: skip
        return self._call(
            scenario_id, lambda s: s.get_provenance(scenario_id, asset_id, tags, t0, t1)
        )


class PublishedStore:
    """``TelemetryStore`` over every published scenario: routes each call to that scenario's
    cached DuckDB (for a process-wide store, e.g. one ADK ``App``). ``prefetch`` at incident
    start keeps the cold build off the first tool call."""

    def __init__(self, cache: StoreCache | None = None) -> None:
        self.cache = cache or default_cache()

    def _s(self, sid: str) -> ScenarioStore:
        return ScenarioStore(self.cache, sid)

    def prefetch(self, scenario_id: str) -> None:
        self.cache.get(scenario_id)

    def list_scenarios(self) -> list[str]:
        return [r["scenario_id"] for r in self.cache.list_published()]

    def _any(self) -> ScenarioStore:
        cached = self.cache.cached()
        return self._s(cached[-1] if cached else self.list_scenarios()[0])

    def get_stop_event(self, scenario_id: str) -> dict[str, Any]:
        return self._s(scenario_id).get_stop_event(scenario_id)

    def list_assets(
        self, line_id: str = plant.LINE_ID, upstream_of: str | None = None
    ) -> list[dict[str, Any]]:
        return self._any().list_assets(line_id, upstream_of)

    def spec_limits(self, asset_id: str | None = None) -> list[dict[str, Any]]:
        return self._any().spec_limits(asset_id)

    def query_telemetry(self, scenario_id: str, *a: Any, **k: Any) -> pd.DataFrame:
        return self._s(scenario_id).query_telemetry(scenario_id, *a, **k)

    def get_alarms(self, scenario_id: str, *a: Any, **k: Any) -> pd.DataFrame:
        return self._s(scenario_id).get_alarms(scenario_id, *a, **k)

    def get_shift_notes(self, scenario_id: str, *a: Any, **k: Any) -> pd.DataFrame:
        return self._s(scenario_id).get_shift_notes(scenario_id, *a, **k)

    def get_work_orders(self, scenario_id: str, *a: Any, **k: Any) -> pd.DataFrame:
        return self._s(scenario_id).get_work_orders(scenario_id, *a, **k)

    def get_provenance(self, scenario_id: str, *a: Any, **k: Any) -> pd.DataFrame:
        return self._s(scenario_id).get_provenance(scenario_id, *a, **k)


def _du(path: Path) -> int:
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file())


# ---- process-wide defaults -------------------------------------------------------------
_DEFAULT: StoreCache | None = None
_DEFAULT_LOCK = threading.Lock()


def default_cache() -> StoreCache:
    global _DEFAULT
    with _DEFAULT_LOCK:
        if _DEFAULT is None:
            _DEFAULT = StoreCache()
        return _DEFAULT


def set_default_cache(cache: StoreCache | None) -> None:
    """Tests / embedding: replace the process-wide cache (``None`` resets to env defaults)."""
    global _DEFAULT
    with _DEFAULT_LOCK:
        _DEFAULT = cache


def get_store(scenario_id: str) -> ScenarioStore:
    """Blocking (may download + build). Usable directly or as ``with get_store(sid) as s:``."""
    return default_cache().get(scenario_id)


async def aget_store(scenario_id: str) -> ScenarioStore:
    return await default_cache().aget(scenario_id)


def list_published() -> list[dict[str, Any]]:
    return default_cache().list_published()


def open_store(backend: str | None = None, db: Path | str | None = None) -> TelemetryStore:
    """Process-wide store by ``STORE_BACKEND``: ``duckdb`` (local ``data/andon.duckdb``),
    ``gcs`` (published Parquet -> per-scenario DuckDB, the live default in the cloud) or
    ``bigquery`` (system of record; eval and analytics, ADR-007)."""
    b = (backend or os.environ.get("STORE_BACKEND") or config.STORE_BACKEND).lower()
    if b == "duckdb":
        return DuckDBStore(db or Path(__file__).resolve().parents[1] / "data" / "andon.duckdb")
    if b == "gcs":
        return PublishedStore()
    if b == "bigquery":
        from simulator.load import BigQueryStore

        return BigQueryStore()
    raise ValueError(f"STORE_BACKEND must be duckdb|gcs|bigquery, got {b!r}")
