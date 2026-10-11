"""Offline fakes for the API tests: Firestore, store provider, live runner. No network."""

from __future__ import annotations

import asyncio
import contextlib
import copy
import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from google.api_core.exceptions import AlreadyExists, NotFound
from google.cloud import firestore

from api.events import Event, parse_event
from api.settings import Settings

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "tests" / "fixtures" / "sample_stream.jsonl"


def sample_events() -> list[dict]:
    return [json.loads(line) for line in SAMPLE.read_text().splitlines() if line.strip()]


# ---- Firestore --------------------------------------------------------------------------------
class FakeSnap:
    def __init__(self, id_: str, data: dict | None) -> None:
        self.id, self._d = id_, data

    @property
    def exists(self) -> bool:
        return self._d is not None

    def to_dict(self) -> dict | None:
        return copy.deepcopy(self._d)


class FakeDoc:
    def __init__(self, client: FakeFirestore, path: str) -> None:
        self.client, self.path = client, path
        self.id = path.rsplit("/", 1)[-1]

    def collection(self, name: str) -> FakeCol:
        return FakeCol(self.client, f"{self.path}/{name}")

    def get(self) -> FakeSnap:
        return FakeSnap(self.id, self.client.docs.get(self.path))

    def _apply(self, data: dict, merge: bool) -> None:
        cur = self.client.docs.get(self.path, {}) if merge else {}
        cur = copy.deepcopy(cur)
        for k, v in data.items():
            cur[k] = cur.get(k, 0) + v.value if isinstance(v, firestore.Increment) else v
        self.client.docs[self.path] = cur
        self.client.writes.append(("set", self.path))

    def set(self, data: dict, merge: bool = False) -> None:
        self._apply(data, merge)

    def create(self, data: dict) -> None:
        if self.path in self.client.docs:
            raise AlreadyExists(self.path)
        self.client.docs[self.path] = copy.deepcopy(data)
        self.client.writes.append(("create", self.path))

    def update(self, data: dict) -> None:
        if self.path not in self.client.docs:
            raise NotFound(self.path)
        self.client.docs[self.path].update(copy.deepcopy(data))
        self.client.writes.append(("update", self.path))


class FakeCol:
    def __init__(self, client: FakeFirestore, path: str) -> None:
        self.client, self.path = client, path
        self._filter: tuple[str, Any] | None = None

    def document(self, id_: str) -> FakeDoc:
        return FakeDoc(self.client, f"{self.path}/{id_}")

    def where(self, field: str, op: str, value: Any) -> FakeCol:
        assert op == "=="
        c = FakeCol(self.client, self.path)
        c._filter = (field, value)
        return c

    def order_by(self, field: str) -> FakeCol:
        return self

    def stream(self) -> list[FakeSnap]:
        prefix = self.path + "/"
        out = []
        for p, d in sorted(self.client.docs.items()):
            if p.startswith(prefix) and "/" not in p[len(prefix) :]:
                if self._filter and d.get(self._filter[0]) != self._filter[1]:
                    continue
                out.append(FakeSnap(p.rsplit("/", 1)[-1], d))
        return out


class FakeBatch:
    def __init__(self, client: FakeFirestore) -> None:
        self.client, self.ops = client, []

    def create(self, ref: FakeDoc, data: dict) -> None:
        self.ops.append(("create", ref, data))

    def update(self, ref: FakeDoc, data: dict) -> None:
        self.ops.append(("update", ref, data))

    def commit(self) -> None:
        snapshot = copy.deepcopy(self.client.docs)
        try:
            for kind, ref, data in self.ops:
                getattr(ref, kind)(data)
        except Exception:
            self.client.docs = snapshot  # atomic
            raise


class FakeFirestore:
    def __init__(self) -> None:
        self.docs: dict[str, dict] = {}
        self.writes: list[tuple[str, str]] = []

    def collection(self, name: str) -> FakeCol:
        return FakeCol(self, name)

    def batch(self) -> FakeBatch:
        return FakeBatch(self)

    def deletes(self) -> list[tuple[str, str]]:
        return [w for w in self.writes if w[0] == "delete"]


# ---- store provider ---------------------------------------------------------------------------
ROWS = [
    {"scenario_id": "S001", "line_id": "L1", "stopped_station": "ST60-VIS",
     "stop_ts": "2026-08-18T04:04:04+05:30", "sources": ["mimii", "synthetic"]},
    {"scenario_id": "R002", "line_id": "L1", "stopped_station": "ST20-WLD",
     "stop_ts": "2026-09-19T21:32:59Z", "sources": ["metropt3", "mimii", "synthetic"]},
]  # fmt: skip


class FakeProvider:
    def __init__(self, rows: list[dict] | None = None) -> None:
        self.rows = rows or ROWS
        self.opened: list[str] = []

    def list_scenarios(self) -> list[dict]:
        return list(self.rows)

    def open(self, scenario_id: str) -> contextlib.AbstractContextManager:
        self.opened.append(scenario_id)
        return contextlib.nullcontext(object())


# ---- live runner ------------------------------------------------------------------------------
class FakeRunner:
    """A live runner that replays the sample stream for any scenario. ``delay`` between events;
    ``stop_after`` / ``fail_after`` inject a hang or an exception; counters prove cancellation."""

    def __init__(self, delay: float = 0.0, fail_after: int | None = None,
                 hang_after: int | None = None) -> None:  # fmt: skip
        self.delay, self.fail_after, self.hang_after = delay, fail_after, hang_after
        self.started = 0
        self.emitted = 0
        self.cancelled = False
        self.finished = False

    def __call__(self, scenario_id: str, incident_id: str) -> AsyncIterator[Event]:
        return self._run(scenario_id, incident_id)

    async def _run(self, scenario_id: str, incident_id: str) -> AsyncIterator[Event]:
        self.started += 1
        try:
            for i, d in enumerate(sample_events()):
                if self.fail_after is not None and i >= self.fail_after:
                    raise RuntimeError("boom: /secret/path leaked?")
                if self.hang_after is not None and i >= self.hang_after:
                    await asyncio.sleep(3600)
                if self.delay:
                    await asyncio.sleep(self.delay)
                d = {**d, "incident_id": incident_id}
                if d["type"] == "incident_started":
                    d["data"] = {**d["data"], "scenario_id": scenario_id, "mode": "live"}
                if d["type"] in ("hypotheses", "rca_final", "work_order_draft"):
                    d["data"] = {**d["data"], "incident_id": incident_id}
                if d["type"] == "work_order_draft":
                    d["data"]["wo_id"] = f"WO-{incident_id}"
                self.emitted += 1
                yield parse_event(d)
            self.finished = True
        except asyncio.CancelledError:
            self.cancelled = True
            raise


def make_settings(tmp: Path, **kw: Any) -> Settings:
    base: dict[str, Any] = {
        "store_backend": "duckdb",
        "allowed_origins": ("http://localhost:5173",),
        "demo_passcode": "open-sesame",
        "replay_dir": tmp / "replays",
        "audit_dir": tmp / "audit",
        "cmms_path": tmp / "cmms.jsonl",
        "eval_latest": tmp / "latest.json",
        "sources_md": ROOT / "data" / "SOURCES.md",
        "daily_budget_usd": 5.0,
        "heartbeat_s": 0.05,
        "live_runs_per_min_per_ip": 100,
        "live_runs_per_day": 1000,
    }
    base.update(kw)
    return Settings(**base)
