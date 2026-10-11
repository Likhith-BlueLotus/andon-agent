"""One run = one row of ``results.jsonl``. Rows hold what the *system* produced (no ground truth).

``record_from_events`` folds a contract event stream (``api/events.py``) into a row: the final RCA
report, the evidence the report can cite (reconstructed from ``tool_call`` + ``tool_result`` so the
independent checker can re-execute it), the verifier's own verdicts (S1 only; the checker ignores
them), cost and timing.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

SCHEMA_VERSION = 1


def run_key(system: str, scenario_id: str, repeat: int) -> str:
    return f"{system}|{scenario_id}|{repeat}"


@dataclass
class EventFold:
    """Incremental fold of one incident's events."""

    calls: dict[str, tuple[str, dict]] = field(default_factory=dict)
    evidence: dict[str, dict] = field(default_factory=dict)
    verdicts_by_iter: dict[int, dict[str, str]] = field(default_factory=lambda: defaultdict(dict))
    iterations: int = 0
    report: dict | None = None
    work_order: dict | None = None
    cost: dict | None = None
    error: dict | None = None
    t_start: float | None = None
    t_final: float | None = None
    t_done: float | None = None
    fallbacks: list[dict] = field(default_factory=list)
    n_tool_calls: int = 0

    def add(self, ev: Any, now: float) -> None:
        d = ev.data.model_dump(mode="json") if hasattr(ev.data, "model_dump") else dict(ev.data)
        t = ev.type
        if t == "incident_started":
            self.t_start = now
        elif t == "tool_call":
            self.calls[d["call_id"]] = (d["tool"], d.get("args") or {})
            self.n_tool_calls += 1
        elif t == "tool_result" and d.get("evidence_id"):
            tool, args = self.calls.get(d["call_id"], ("", {}))
            self.evidence[d["evidence_id"]] = {
                "evidence_id": d["evidence_id"],
                "tool": tool,
                "args": args,
                "summary": d.get("summary") or {},
                "provenance": d.get("provenance") or [],
                "produced_at": getattr(ev, "ts", None) or datetime.now(UTC).isoformat(),
            }
        elif t == "verifier_verdict":  # carries every claim verdict of the iteration
            it = int(d.get("iteration") or 0)
            self.iterations = max(self.iterations, it)
            self.verdicts_by_iter[it] = {c["claim_id"]: c["verdict"] for c in d.get("claims") or []}
        elif t == "rca_final":
            self.report = d
            self.t_final = now
        elif t == "work_order_draft":
            self.work_order = d
        elif t == "model_fallback":
            self.fallbacks.append(d)
        elif t == "cost":
            self.cost = d
        elif t == "error":
            self.error = d
        elif t == "done":
            self.t_done = now

    # ---- derived ------------------------------------------------------------------------
    def verifier_summary(self) -> dict:
        """Catches = claims the verifier rejected in an iteration that was followed by another
        (the judge got to repair them); flagged_final = non-pass verdicts of the last iteration
        (kept in the report, shown struck through)."""
        its = sorted(self.verdicts_by_iter)
        if not its:
            return {
                "iterations": self.iterations,
                "catches": 0,
                "flagged_final": 0,
                "claim_verdicts": {},
            }
        last = its[-1]
        catches = sum(1 for i in its[:-1] for v in self.verdicts_by_iter[i].values() if v != "pass")
        flagged = sum(1 for v in self.verdicts_by_iter[last].values() if v != "pass")
        return {
            "iterations": self.iterations or len(its),
            "catches": catches,
            "flagged_final": flagged,
            "claim_verdicts": dict(self.verdicts_by_iter[last]),
        }


def record_from_fold(
    fold: EventFold,
    *,
    system: str,
    scenario_id: str,
    repeat: int,
    judge_model: str | None,
    mode: str,
    wall_s: float,
    extra: dict | None = None,
) -> dict:
    ok = fold.report is not None and fold.error is None
    if fold.report is not None and fold.error is not None:
        ok = False  # a run that errored after a report still counts as failed
    t0, t1 = fold.t_start, fold.t_final
    cost = fold.cost or {
        "usd": 0.0,
        "input_tokens": 0,
        "output_tokens": 0,
        "cached_tokens": 0,
        "by_model": {},
    }
    row = {
        "schema": SCHEMA_VERSION,
        "run_key": run_key(system, scenario_id, repeat),
        "system": system,
        "scenario_id": scenario_id,
        "repeat": repeat,
        "judge_model": judge_model,
        "mode": mode,
        "status": "ok" if ok else "error",
        "error": None if ok else (fold.error or {"code": "no_report", "message": "no rca_final"}),
        "report": fold.report,
        "evidence": list(fold.evidence.values()),
        "verifier": fold.verifier_summary(),
        "work_order": _wo(fold.work_order),
        "n_tool_calls": fold.n_tool_calls,
        "fallbacks": fold.fallbacks,
        "duration_s": round(t1 - t0, 3) if t0 is not None and t1 is not None else None,
        "wall_s": round(wall_s, 3),
        "cost": cost,
        "finished_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    row.update(extra or {})
    return row


def _wo(wo: dict | None) -> dict | None:
    if not wo:
        return None
    steps = wo.get("steps") or []
    return {
        "wo_id": wo.get("wo_id"),
        "status": wo.get("status"),
        "cause_class": wo.get("cause_class"),
        "asset_id": wo.get("asset_id"),
        "n_steps": len(steps),
        "n_safety_steps": sum(1 for s in steps if s.get("is_safety")),
    }


def error_row(
    *,
    system: str,
    scenario_id: str,
    repeat: int,
    judge_model: str | None,
    mode: str,
    code: str,
    message: str,
    wall_s: float = 0.0,
) -> dict:
    return {
        "schema": SCHEMA_VERSION,
        "run_key": run_key(system, scenario_id, repeat),
        "system": system,
        "scenario_id": scenario_id,
        "repeat": repeat,
        "judge_model": judge_model,
        "mode": mode,
        "status": "error",
        "error": {"code": code, "message": message[:500]},
        "report": None,
        "evidence": [],
        "verifier": {"iterations": 0, "catches": 0, "flagged_final": 0, "claim_verdicts": {}},
        "work_order": None,
        "n_tool_calls": 0,
        "fallbacks": [],
        "duration_s": None,
        "wall_s": round(wall_s, 3),
        "cost": {
            "usd": 0.0,
            "input_tokens": 0,
            "output_tokens": 0,
            "cached_tokens": 0,
            "by_model": {},
        },
        "finished_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }


def load_results(path) -> dict[str, dict]:
    """``{run_key: row}`` from a results.jsonl; later rows replace earlier ones (a retried error)."""
    import json
    from pathlib import Path

    rows: dict[str, dict] = {}
    p = Path(path)
    if p.exists():
        for line in p.read_text("utf-8").splitlines():
            line = line.strip()
            if line:
                try:
                    r = json.loads(line)
                except ValueError:  # a torn last line from a killed run
                    continue
                rows[r["run_key"]] = r
    return rows
