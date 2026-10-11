"""Replay: stream a stored run with its original relative timing. Never calls Gemini.

Sources of a run (``run_id``):

* ``data/replays/<run_id>.jsonl`` — committed event files, one contract event per line (what
  ``python -m agents.cli --json`` prints and what ``export`` below writes from a recorded live run);
* ``audit:<incident_id>`` — the Firestore (or local file) audit of a past live run.

A replay is re-stamped for the viewer: new ``incident_id`` (so each visitor approves their own
demo work order), ``incident_started.mode = "replay"``, ``ts`` = emission time, gaps between events
= the recorded gaps capped at ``gap_cap_s`` and divided by ``speed``. Run it as a module to export::

    uv run python -m api.replay export --incident inc_r002_ab12cd34 --out data/replays/r002-live-1.jsonl
"""

from __future__ import annotations

import argparse
import asyncio
import itertools
import json
import logging
import re
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from api.audit import AuditStore, entry_to_event
from api.events import Event, parse_event

log = logging.getLogger("andon.replay")

RUN_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,63}$")
AUDIT_PREFIX = "audit:"
INDEX_FILE = "index.json"  # optional sidecar: {run_id: {"label": "..."}}


class ReplayNotFound(LookupError):
    pass


# ---- parsing / describing ---------------------------------------------------------------------
def validate_events(raw: list[dict]) -> list[dict]:
    """Every event must satisfy the contract; the run must open with incident_started and end
    with done. Returns the (unchanged) dicts; raises ValueError."""
    if not raw:
        raise ValueError("empty run")
    for d in raw:
        parse_event(d)
    if raw[0]["type"] != "incident_started":
        raise ValueError("run does not start with incident_started")
    if raw[-1]["type"] != "done":
        raise ValueError("run does not end with done")
    return raw


def _ts(d: dict) -> datetime:
    return datetime.fromisoformat(str(d["ts"]).replace("Z", "+00:00"))


def describe(run_id: str, raw: list[dict], label: str | None = None) -> dict[str, Any]:
    started = raw[0]["data"]
    verdicts = [e["data"]["overall"] for e in raw if e["type"] == "verifier_verdict"]
    final = next((e["data"]["status"] for e in raw if e["type"] == "rca_final"), None)
    cost = next((e["data"]["usd"] for e in reversed(raw) if e["type"] == "cost"), None)
    fails = verdicts.count("FAIL")
    if label is None:
        if final == "insufficient_evidence":
            label = "Insufficient evidence: the agent declines to name a cause"
        elif fails:
            label = f"Verifier rejected a claim ({fails}x), then the revised RCA passed"
        elif final == "verified":
            label = "Verified root cause with a safety-gated work order"
        else:
            label = "Recorded investigation"
    return {
        "run_id": run_id,
        "scenario_id": started["scenario_id"],
        "label": label,
        "recorded_at": _ts(raw[0]).isoformat(),
        "duration_s": round((_ts(raw[-1]) - _ts(raw[0])).total_seconds(), 1),
        "cost_usd": cost,
        "final_status": final,
        "verifier_rejections": fails,
        "has_work_order": any(e["type"] == "work_order_draft" for e in raw),
        "source": "audit" if run_id.startswith(AUDIT_PREFIX) else "file",
    }


# ---- catalog ----------------------------------------------------------------------------------
class ReplayCatalog:
    def __init__(self, directory: Path, audit: AuditStore | None = None) -> None:
        self.dir = directory
        self.audit = audit
        self._cache: dict[str, tuple[float, list[dict]]] = {}

    def _index(self) -> dict[str, dict]:
        p = self.dir / INDEX_FILE
        try:
            return json.loads(p.read_text("utf-8")) if p.exists() else {}
        except (OSError, ValueError):
            log.warning("unreadable %s", p)
            return {}

    def _read_file(self, path: Path) -> list[dict]:
        mtime = path.stat().st_mtime
        hit = self._cache.get(path.name)
        if hit and hit[0] == mtime:
            return hit[1]
        raw = [json.loads(line) for line in path.read_text("utf-8").splitlines() if line.strip()]
        validate_events(raw)
        self._cache[path.name] = (mtime, raw)
        return raw

    def list(self) -> list[dict]:
        out, idx = [], self._index()
        for p in sorted(self.dir.glob("*.jsonl")) if self.dir.is_dir() else []:
            if not RUN_ID_RE.match(p.stem):
                continue
            try:
                out.append(
                    describe(p.stem, self._read_file(p), (idx.get(p.stem) or {}).get("label"))
                )
            except (ValueError, OSError, KeyError):
                log.warning("skipping invalid replay file %s", p.name, exc_info=True)
        return sorted(out, key=lambda r: r["recorded_at"], reverse=True)

    def default_for(self, scenario_id: str) -> str | None:
        runs = [r for r in self.list() if r["scenario_id"] == scenario_id]
        return runs[0]["run_id"] if runs else None

    def load(self, run_id: str, scenario_id: str | None = None) -> list[dict]:
        """Raw validated event dicts of a run; ``ReplayNotFound`` if unknown or for another
        scenario."""
        if run_id.startswith(AUDIT_PREFIX):
            raw = self._from_audit(run_id[len(AUDIT_PREFIX) :])
        else:
            path = self.dir / f"{run_id}.jsonl"
            if not RUN_ID_RE.match(run_id) or not path.is_file():
                raise ReplayNotFound(run_id)
            try:
                raw = self._read_file(path)
            except (ValueError, OSError) as exc:
                raise ReplayNotFound(f"{run_id}: {exc}") from exc
        if scenario_id and raw[0]["data"]["scenario_id"] != scenario_id:
            raise ReplayNotFound(f"{run_id} is not a run of {scenario_id}")
        return raw

    def _from_audit(self, incident_id: str) -> list[dict]:
        if self.audit is None:
            raise ReplayNotFound("no audit store")
        try:
            rec = self.audit.get(incident_id)
        except ValueError as exc:
            raise ReplayNotFound(str(exc)) from exc
        if rec is None or (rec["incident"] or {}).get("mode") != "live":
            raise ReplayNotFound(incident_id)
        summary = rec["meta"].get("summary") or {}
        if summary.get("status") != "completed":
            raise ReplayNotFound(f"{incident_id} did not complete")
        try:
            return validate_events([entry_to_event(s) for s in rec["steps"]])
        except (ValueError, KeyError) as exc:
            raise ReplayNotFound(f"{incident_id}: {exc}") from exc


# ---- streaming --------------------------------------------------------------------------------
def restamp(raw: list[dict], incident_id: str) -> list[dict]:
    """Copy of ``raw`` for one viewer: fresh incident id and work-order id, mode = replay."""
    suffix = incident_id.rsplit("_", 1)[-1]
    out: list[dict] = []
    for e in raw:
        d = json.loads(json.dumps(e))
        d["incident_id"] = incident_id
        data = d["data"]
        if d["type"] == "incident_started":
            data["mode"] = "replay"
        elif d["type"] in ("hypotheses", "rca_final"):
            data["incident_id"] = incident_id
        elif d["type"] == "work_order_draft":
            data["incident_id"] = incident_id
            data["wo_id"] = f"{data['wo_id']}-{suffix}"
            data["status"] = "PENDING_APPROVAL"
        out.append(d)
    return out


def gap_schedule(raw: list[dict], cap_s: float, speed: float) -> list[float]:
    """Delay before each event: the recorded gap, capped, divided by ``speed``."""
    delays = [0.0]
    for prev, cur in itertools.pairwise(raw):
        gap = (_ts(cur) - _ts(prev)).total_seconds()
        delays.append(min(max(gap, 0.0), cap_s) / speed)
    return delays


async def stream_replay(
    raw: list[dict],
    incident_id: str,
    *,
    speed: float = 1.0,
    gap_cap_s: float = 3.0,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> AsyncIterator[Event]:
    """Yield the run's events with the recorded rhythm. Touches no model, ever."""
    evs = restamp(raw, incident_id)
    for d, delay in zip(evs, gap_schedule(raw, gap_cap_s, speed), strict=True):
        if delay > 0:
            await sleep(delay)
        d["ts"] = datetime.now(UTC).isoformat()
        yield parse_event(d)


def new_replay_incident_id(scenario_id: str) -> str:
    return f"rep_{scenario_id.lower()}_{uuid.uuid4().hex[:8]}"


# ---- export CLI -------------------------------------------------------------------------------
def export_run(store: AuditStore, incident_id: str, out: Path, *, force: bool = False,
               label: str | None = None) -> dict:  # fmt: skip
    rec = store.get(incident_id)
    if rec is None:
        raise SystemExit(f"no audit record for {incident_id}")
    status = (rec["meta"].get("summary") or {}).get("status")
    if (rec["incident"] or {}).get("mode") != "live":
        raise SystemExit("only live runs can be exported (a replay of a replay adds nothing)")
    if status != "completed" and not force:
        raise SystemExit(f"run status is {status!r}, not 'completed' (use --force to export anyway)")  # fmt: skip
    raw = validate_events([entry_to_event(s) for s in rec["steps"]])
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("".join(json.dumps(e, ensure_ascii=False) + "\n" for e in raw), "utf-8")
    if label:
        idx_path = out.parent / INDEX_FILE
        idx = json.loads(idx_path.read_text("utf-8")) if idx_path.exists() else {}
        idx[out.stem] = {"label": label}
        idx_path.write_text(json.dumps(idx, indent=1, sort_keys=True) + "\n", "utf-8")
    return describe(out.stem, raw, label)


def main(argv: list[str] | None = None) -> int:
    from api.audit import FileAuditStore, FirestoreAuditStore
    from api.fs import LazyFirestore
    from api.settings import Settings

    p = argparse.ArgumentParser(prog="python -m api.replay", description=__doc__.split("\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    ex = sub.add_parser("export", help="write a recorded live run as data/replays/<run_id>.jsonl")
    ex.add_argument("--incident", required=True)
    ex.add_argument("--out", required=True, type=Path)
    ex.add_argument("--label", default=None)
    ex.add_argument("--firestore", action="store_true", help="read the Firestore audit")
    ex.add_argument("--force", action="store_true")
    args = p.parse_args(argv)
    st = Settings.from_env()
    store: AuditStore = (
        FirestoreAuditStore(LazyFirestore()) if args.firestore else FileAuditStore(st.audit_dir)
    )
    info = export_run(store, args.incident, args.out, force=args.force, label=args.label)
    print(json.dumps(info, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
