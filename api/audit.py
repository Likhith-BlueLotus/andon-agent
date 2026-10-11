"""Append-only audit log (SECURITY "Audit", ARCHITECTURE §5).

Layout (Firestore; the file store mirrors it as one JSONL file per incident)::

    audit/{incident_id}                      incident start record (mode, scenario, ip hash, ...)
    audit/{incident_id}/steps/{seq:06d}      every forwarded contract event
    audit/{incident_id}/meta/{kind}          create-once facts: ``work_order`` link, run ``summary``
    audit/{incident_id}/actions/{ns}         human actions (approve / reject / refused attempts)

Step ``data`` is stored as a JSON string (``data_json``): Firestore refuses nested arrays and some
tool summaries contain them. The same records power replay (``api.replay``) and the eval.

Append-only is enforced **in code**: the stores expose ``create``-style methods only (no update,
no delete — ``tests/test_api_audit.py`` asserts the public surface), and Firestore ``create()``
fails if a document exists. Firestore security rules do not bind a server SDK, so the API's
service account *could* delete if the code were changed; code review and that test are the control.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import threading
import time
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, ClassVar, Protocol

from api.events import Event

log = logging.getLogger("andon.audit")

COLLECTION = "audit"
INCIDENT_ID_RE = re.compile(r"^[A-Za-z0-9_.-]{1,80}$")
META_KINDS = ("work_order", "summary")


def _now() -> str:
    return datetime.now(UTC).isoformat()


def check_id(incident_id: str) -> str:
    if not INCIDENT_ID_RE.match(incident_id) or incident_id in (".", ".."):
        raise ValueError(f"invalid incident id {incident_id!r}")
    return incident_id


def event_to_entry(ev: Event) -> dict:
    """One step record: ``type, seq, ts, agent, data`` (data JSON-encoded) + ``recorded_at``."""
    return {
        "incident_id": ev.incident_id,
        "seq": ev.seq,
        "type": ev.type,
        "ts": ev.ts.isoformat(),
        "agent": ev.agent,
        "data_json": json.dumps(ev.model_dump(mode="json")["data"], ensure_ascii=False),
        "recorded_at": _now(),
    }


def entry_to_event(entry: dict) -> dict:
    """Inverse of :func:`event_to_entry`: the contract envelope (feed to ``parse_event``)."""
    return {
        "type": entry["type"],
        "incident_id": entry["incident_id"],
        "seq": entry["seq"],
        "ts": entry["ts"],
        "agent": entry.get("agent"),
        "data": json.loads(entry["data_json"]),
    }


class AuditStore(Protocol):
    """Create-only. There is deliberately no update or delete."""

    def create_incident(self, incident_id: str, meta: dict) -> bool: ...
    def add_step(self, incident_id: str, seq: int, entry: dict) -> None: ...
    def add_once(self, incident_id: str, kind: str, data: dict) -> bool: ...
    def add_action(self, incident_id: str, entry: dict) -> str: ...
    def get(self, incident_id: str) -> dict | None: ...


def _assemble(incident: dict | None, steps: list[dict], meta: dict, actions: list[dict]) -> dict:
    return {
        "incident": incident,
        "steps": sorted(steps, key=lambda s: s["seq"]),
        "meta": meta,
        "actions": actions,
    }


class MemoryAuditStore:
    def __init__(self) -> None:
        self._inc: dict[str, dict] = {}
        self._steps: dict[str, dict[int, dict]] = defaultdict(dict)
        self._meta: dict[str, dict[str, dict]] = defaultdict(dict)
        self._actions: dict[str, list[dict]] = defaultdict(list)
        self._lock = threading.Lock()

    def create_incident(self, incident_id: str, meta: dict) -> bool:
        with self._lock:
            if incident_id in self._inc:
                return False
            self._inc[check_id(incident_id)] = {"incident_id": incident_id, **meta}
            return True

    def add_step(self, incident_id: str, seq: int, entry: dict) -> None:
        with self._lock:
            if seq in self._steps[incident_id]:
                raise FileExistsError(f"step {seq} of {incident_id} already exists")
            self._steps[incident_id][seq] = entry

    def add_once(self, incident_id: str, kind: str, data: dict) -> bool:
        with self._lock:
            if kind in self._meta[incident_id]:
                return False
            self._meta[incident_id][kind] = {**data, "recorded_at": _now()}
            return True

    def add_action(self, incident_id: str, entry: dict) -> str:
        with self._lock:
            self._actions[incident_id].append({**entry, "recorded_at": _now()})
            return f"{len(self._actions[incident_id]):06d}"

    def get(self, incident_id: str) -> dict | None:
        with self._lock:
            if incident_id not in self._inc:
                return None
            return _assemble(
                self._inc[incident_id],
                list(self._steps[incident_id].values()),
                dict(self._meta[incident_id]),
                list(self._actions[incident_id]),
            )


class FileAuditStore:
    """Local runs: one append-only JSONL file per incident (``data/audit/<id>.jsonl``)."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self._lock = threading.Lock()

    def _path(self, incident_id: str) -> Path:
        return self.root / f"{check_id(incident_id)}.jsonl"

    def _append(self, incident_id: str, rec: dict) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        with self._lock, self._path(incident_id).open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    def _read(self, incident_id: str) -> list[dict]:
        p = self._path(incident_id)
        if not p.exists():
            return []
        return [json.loads(line) for line in p.read_text("utf-8").splitlines() if line.strip()]

    def create_incident(self, incident_id: str, meta: dict) -> bool:
        if self._path(incident_id).exists():
            return False
        self._append(incident_id, {"kind": "incident", "incident_id": incident_id, **meta})
        return True

    def add_step(self, incident_id: str, seq: int, entry: dict) -> None:
        self._append(incident_id, {"kind": "step", **entry})

    def add_once(self, incident_id: str, kind: str, data: dict) -> bool:
        if any(r["kind"] == "meta" and r["name"] == kind for r in self._read(incident_id)):
            return False
        self._append(incident_id, {"kind": "meta", "name": kind, **data, "recorded_at": _now()})
        return True

    def add_action(self, incident_id: str, entry: dict) -> str:
        key = f"{time.time_ns()}"
        self._append(incident_id, {"kind": "action", **entry, "recorded_at": _now()})
        return key

    def get(self, incident_id: str) -> dict | None:
        rows = self._read(incident_id)
        inc = next((r for r in rows if r["kind"] == "incident"), None)
        if inc is None:
            return None
        meta = {r["name"]: {k: v for k, v in r.items() if k not in ("kind", "name")}
                for r in rows if r["kind"] == "meta"}  # fmt: skip
        return _assemble(
            {k: v for k, v in inc.items() if k != "kind"},
            [{k: v for k, v in r.items() if k != "kind"} for r in rows if r["kind"] == "step"],
            meta,
            [{k: v for k, v in r.items() if k != "kind"} for r in rows if r["kind"] == "action"],
        )


class FirestoreAuditStore:
    def __init__(self, client: Any) -> None:
        self._col = client.collection(COLLECTION)

    @staticmethod
    def _already(exc: Exception) -> bool:
        from google.api_core.exceptions import AlreadyExists, Conflict

        return isinstance(exc, (AlreadyExists, Conflict))

    def _create(self, ref: Any, data: dict) -> bool:
        try:
            ref.create(data)
            return True
        except Exception as exc:
            if self._already(exc):
                return False
            raise

    def create_incident(self, incident_id: str, meta: dict) -> bool:
        return self._create(self._col.document(check_id(incident_id)), meta)

    def add_step(self, incident_id: str, seq: int, entry: dict) -> None:
        ref = self._col.document(check_id(incident_id)).collection("steps").document(f"{seq:06d}")
        if not self._create(ref, entry):
            raise FileExistsError(f"step {seq} of {incident_id} already exists")

    def add_once(self, incident_id: str, kind: str, data: dict) -> bool:
        ref = self._col.document(check_id(incident_id)).collection("meta").document(kind)
        return self._create(ref, {**data, "recorded_at": _now()})

    def add_action(self, incident_id: str, entry: dict) -> str:
        key = f"{time.time_ns()}"
        ref = self._col.document(check_id(incident_id)).collection("actions").document(key)
        self._create(ref, {**entry, "recorded_at": _now()})
        return key

    def get(self, incident_id: str) -> dict | None:
        doc = self._col.document(check_id(incident_id))
        snap = doc.get()
        if not snap.exists:
            return None
        steps = [d.to_dict() for d in doc.collection("steps").stream()]
        meta = {d.id: d.to_dict() for d in doc.collection("meta").stream()}
        actions = [d.to_dict() for d in doc.collection("actions").order_by("recorded_at").stream()]
        return _assemble(snap.to_dict(), steps, meta, actions)


def public_view(rec: dict) -> dict:
    """The API response for ``GET /api/incidents/{id}/audit``: steps with ``data`` decoded."""
    steps = []
    for s in rec["steps"]:
        out = {k: v for k, v in s.items() if k != "data_json"}
        out["data"] = json.loads(s["data_json"])
        steps.append(out)
    return {**rec, "steps": steps}


# =============================================================================================
class AuditRecorder:
    """Per-incident background writer.

    ``record`` never blocks the stream and never raises; writes happen in order on a task that is
    *not* part of the request's cancel scope, so a client disconnect cannot lose the ``cancelled``
    summary. ``wait`` drains it (shutdown, tests, export).
    """

    _tasks: ClassVar[set[asyncio.Task]] = set()

    def __init__(
        self, store: AuditStore, incident_id: str, meta: dict, *, store_steps: bool = True
    ) -> None:
        self.store = store
        self.store_steps = store_steps  # replays store only the incident, the WO link, the summary
        self.incident_id = incident_id
        self.meta = meta
        self.failed = 0
        self._q: asyncio.Queue[tuple | None] = asyncio.Queue()
        self._task: asyncio.Task | None = None
        self._models: set[str] = set()
        self._cost: dict | None = None
        self._error: dict | None = None
        self._count = 0
        self._last_seq = -1
        self._finished = False

    def start(self) -> None:
        self._q.put_nowait(("incident",))
        self._task = asyncio.get_running_loop().create_task(self._writer())
        AuditRecorder._tasks.add(self._task)
        self._task.add_done_callback(AuditRecorder._tasks.discard)

    def record(self, ev: Event) -> None:
        self._count += 1
        self._last_seq = ev.seq
        d = ev.data
        if ev.type in ("agent_started", "agent_finished") and getattr(d, "model_id", None):
            self._models.add(d.model_id)
        elif ev.type == "cost":
            self._cost = d.model_dump(mode="json")
            self._models.update(d.by_model)
        elif ev.type == "error":
            self._error = d.model_dump(mode="json")
        if self.store_steps:
            self._q.put_nowait(("step", ev.seq, event_to_entry(ev)))
        if ev.type == "work_order_draft":
            self._q.put_nowait(("once", "work_order", {"wo_id": d.wo_id, "incident_id": ev.incident_id}))  # fmt: skip

    def finish(self, status: str, duration_ms: int) -> None:
        """``completed`` | ``error`` | ``cancelled`` | ``timeout``. Idempotent."""
        if self._finished:
            return
        self._finished = True
        self._q.put_nowait(("once", "summary", {
            "status": status,
            "duration_ms": duration_ms,
            "events": self._count,
            "last_seq": self._last_seq,
            "models": sorted(self._models),
            "cost": self._cost,
            "error": self._error,
        }))  # fmt: skip
        self._q.put_nowait(None)

    async def _writer(self) -> None:
        while (op := await self._q.get()) is not None:
            try:
                if op[0] == "incident":
                    await asyncio.to_thread(self.store.create_incident, self.incident_id, self.meta)
                elif op[0] == "step":
                    await asyncio.to_thread(self.store.add_step, self.incident_id, op[1], op[2])
                else:
                    await asyncio.to_thread(self.store.add_once, self.incident_id, op[1], op[2])
            except Exception:
                self.failed += 1
                log.exception("audit write failed for %s (%s)", self.incident_id, op[0])

    async def wait(self, timeout_s: float = 10.0) -> None:
        if self._task is not None:
            await asyncio.wait_for(asyncio.shield(self._task), timeout_s)

    @classmethod
    async def drain_all(cls, timeout_s: float = 10.0) -> None:
        if cls._tasks:
            await asyncio.wait(list(cls._tasks), timeout=timeout_s)
