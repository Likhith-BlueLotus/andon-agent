"""Mock CMMS: the only place a work order is written (CLAUDE.md hard rule 3).

``draft_work_order`` (agents/drafter.py) is the only caller of :meth:`CMMS.create_draft`, and a
draft can only be created as ``PENDING_APPROVAL``. Approval is a human action in the API, never an
agent action, so this interface has no approve method.

Implementations behind one interface:

* :class:`InMemoryCMMS` — tests;
* :class:`JsonlCMMS` — local runs, append-only ``data/cmms/work_orders.jsonl``;
* :class:`FirestoreCMMS` — cloud, collection ``work_orders`` (create-only), selected by
  :func:`default_cmms` when ``STORE_BACKEND=bigquery`` or ``FIRESTORE`` is set.

Human decisions (APPROVED / REJECTED) are recorded by the API through :meth:`decide` on the
concrete classes (:class:`Decidable`), never through the agent-facing :class:`CMMS` protocol. A
decision is final: it is only accepted on a ``PENDING_APPROVAL`` work order, exactly once.
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any, Protocol

import config
from agents.schemas import WorkOrder

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_JSONL = ROOT / "data" / "cmms" / "work_orders.jsonl"
COLLECTION = "work_orders"


class CMMSWriteError(RuntimeError):
    """A write the mock CMMS refuses (wrong status, duplicate id)."""


class WorkOrderAlreadyDecided(CMMSWriteError):
    """The work order is not PENDING_APPROVAL (a second approve/reject)."""


class CMMS(Protocol):
    def create_draft(self, wo: WorkOrder) -> WorkOrder: ...
    def get(self, wo_id: str) -> WorkOrder | None: ...
    def list(self, incident_id: str | None = None) -> list[WorkOrder]: ...


class Decidable(CMMS, Protocol):
    def decide(self, wo_id: str, status: str, decision: dict) -> WorkOrder: ...


def _check_decision(status: str) -> None:
    if status not in ("APPROVED", "REJECTED"):
        raise CMMSWriteError(f"a decision must be APPROVED or REJECTED, got {status}")


def _check_new(wo: WorkOrder) -> None:
    if wo.status != "PENDING_APPROVAL":
        raise CMMSWriteError(f"agents may only create PENDING_APPROVAL drafts, got {wo.status}")


class InMemoryCMMS:
    def __init__(self) -> None:
        self._rows: dict[str, WorkOrder] = {}
        self.decisions: dict[str, dict] = {}
        self._lock = threading.Lock()

    def create_draft(self, wo: WorkOrder) -> WorkOrder:
        _check_new(wo)
        with self._lock:
            if wo.wo_id in self._rows:
                raise CMMSWriteError(f"work order {wo.wo_id} already exists")
            self._rows[wo.wo_id] = wo.model_copy(deep=True)
        return wo

    def get(self, wo_id: str) -> WorkOrder | None:
        return self._rows.get(wo_id)

    def list(self, incident_id: str | None = None) -> list[WorkOrder]:
        return [w for w in self._rows.values() if incident_id in (None, w.incident_id)]

    def decide(self, wo_id: str, status: str, decision: dict) -> WorkOrder:
        """Human decision, exactly once, only on a PENDING_APPROVAL work order."""
        _check_decision(status)
        with self._lock:
            wo = self._rows.get(wo_id)
            if wo is None:
                raise KeyError(wo_id)
            if wo.status != "PENDING_APPROVAL":
                raise WorkOrderAlreadyDecided(f"work order {wo_id} is already {wo.status}")
            self._rows[wo_id] = wo = wo.model_copy(update={"status": status})
            self.decisions[wo_id] = dict(decision)
            return wo


class JsonlCMMS(InMemoryCMMS):
    """Append-only JSONL file; reloaded on start so ids stay unique across runs."""

    def __init__(self, path: Path = DEFAULT_JSONL) -> None:
        super().__init__()
        self.path = path
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    wo = WorkOrder.model_validate_json(line)
                    self._rows[wo.wo_id] = wo

    def create_draft(self, wo: WorkOrder) -> WorkOrder:
        super().create_draft(wo)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock, self.path.open("a", encoding="utf-8") as f:
            f.write(wo.model_dump_json() + "\n")
        return wo

    def decide(self, wo_id: str, status: str, decision: dict) -> WorkOrder:
        wo = super().decide(wo_id, status, decision)
        with self._lock, self.path.open("a", encoding="utf-8") as f:  # later row wins on reload
            f.write(wo.model_dump_json() + "\n")
        return wo


class FirestoreCMMS:
    """``work_orders/{wo_id}``. Drafts are create-only; a decision is one atomic batch that
    creates ``work_orders/{wo_id}/decisions/final`` (fails if it exists, so a second decision
    cannot win) and flips ``status``. ``collection`` lets the API keep anonymous replay approvals
    in ``demo_work_orders`` instead of the CMMS."""

    def __init__(self, client: Any = None, collection: str = COLLECTION) -> None:
        if client is None:
            from google.cloud import firestore

            client = firestore.Client(project=config.PROJECT or None)
        self._client = client
        self._col = client.collection(collection)

    def create_draft(self, wo: WorkOrder) -> WorkOrder:
        _check_new(wo)
        # create() fails if the document exists: drafts are never overwritten
        self._col.document(wo.wo_id).create(json.loads(wo.model_dump_json()))
        return wo

    def get(self, wo_id: str) -> WorkOrder | None:
        snap = self._col.document(wo_id).get()
        return WorkOrder.model_validate(snap.to_dict()) if snap.exists else None

    def list(self, incident_id: str | None = None) -> list[WorkOrder]:
        q = self._col if incident_id is None else self._col.where("incident_id", "==", incident_id)
        return [WorkOrder.model_validate(d.to_dict()) for d in q.stream()]

    def decide(self, wo_id: str, status: str, decision: dict) -> WorkOrder:
        from google.api_core.exceptions import AlreadyExists, Conflict

        _check_decision(status)
        wo = self.get(wo_id)
        if wo is None:
            raise KeyError(wo_id)
        if wo.status != "PENDING_APPROVAL":
            raise WorkOrderAlreadyDecided(f"work order {wo_id} is already {wo.status}")
        ref = self._col.document(wo_id)
        batch = self._client.batch()
        batch.create(ref.collection("decisions").document("final"), {"status": status, **decision})
        batch.update(ref, {"status": status})
        try:
            batch.commit()
        except (AlreadyExists, Conflict) as exc:
            raise WorkOrderAlreadyDecided(f"work order {wo_id} was decided concurrently") from exc
        return wo.model_copy(update={"status": status})


def default_cmms() -> CMMS:
    if config.STORE_BACKEND == "bigquery" or os.environ.get("FIRESTORE"):
        return FirestoreCMMS()
    return JsonlCMMS()
