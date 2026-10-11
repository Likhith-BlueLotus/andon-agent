"""Independent claim checker (EVAL_PLAN §3 "unsupported-claim rate").

Grades every claim of a *final* report with the verifier's published rules
(``agents.verifier.verify_report``) but on evidence this module rebuilds and re-executes itself:

* the evidence a report may cite is reconstructed from the run's own tool calls (tool name, exact
  args, recorded summary, provenance); a claim citing an id that was never produced is a fail;
* every cited evidence item is **re-run against the store from this process** (``verify_report``
  calls ``agents.tools.rerun`` on our ``ToolContext``), and compared with the recorded summary;
* the system's own verdicts (S1's ``claim_verdict`` events, S2's always-PASS stub) are never read.

The checker's LLM gateway refuses every call (zero budget), so grading can never spend money. The
``listen`` tool is the one non-pure tool: its re-run is served from the on-disk cache written by
the original run (``data/cache/listen``); on a machine without that cache such evidence is graded
``fail`` (not reproducible), which is the conservative direction.

Only the rule *functions* are imported from ``agents.verifier``; that file may change, so the
import is lazy and any failure is reported in ``error`` instead of silently passing claims.
"""

from __future__ import annotations

import threading
from typing import Any

from agents.llm import LLM, SpendTracker
from agents.schemas import RCAReport
from agents.tools import EVIDENCE_PREFIX, ToolContext


def no_spend_llm() -> LLM:
    """An LLM gateway whose kill switch is already tripped: any call raises BudgetExhaustedError."""
    return LLM(spend=SpendTracker(daily_budget_usd=0.0))


def check_report(
    report: dict | RCAReport | None,
    evidence: list[dict],
    store: Any,
    scenario_id: str,
    *,
    lock: threading.RLock | None = None,
) -> dict:
    """Independent verdict for every claim of every hypothesis, in report order.

    Returns ``{"overall", "claims": [{claim_id, hypothesis_index, kind, verdict, reason,
    measured_value}], "n_claims", "n_unsupported", "error"}``. ``overall`` is the verifier's rule
    applied to the top hypothesis. Never raises: a checker failure is ``error`` (and the claims are
    graded ``unverifiable``, which counts as unsupported).
    """
    if report is None:
        return _empty("no report")
    try:
        rep = report if isinstance(report, RCAReport) else RCAReport.model_validate(report)
    except Exception as exc:
        return _empty(f"report does not validate: {exc}"[:300])
    flat = [(hi, c) for hi, h in enumerate(rep.hypotheses) for c in h.claims]
    try:
        from agents.verifier import verify_report

        state = {EVIDENCE_PREFIX + e["evidence_id"]: _evidence(e) for e in evidence}
        extra: dict[str, Any] = {"_lock": lock} if lock is not None else {}
        ctx = ToolContext(
            store=store, scenario_id=scenario_id, state=state, llm=no_spend_llm(), **extra
        )
        verdict, verdicts = verify_report(rep, ctx, 0)
        if len(verdicts) != len(flat):
            raise RuntimeError(f"verifier returned {len(verdicts)} verdicts for {len(flat)} claims")
    except Exception as exc:
        out = _empty(f"checker error: {type(exc).__name__}: {exc}"[:300])
        out["claims"] = [
            {
                "claim_id": c.claim_id,
                "hypothesis_index": hi,
                "kind": c.kind,
                "verdict": "unverifiable",
                "reason": out["error"],
                "measured_value": None,
            }
            for hi, c in flat
        ]
        out["n_claims"] = len(flat)
        out["n_unsupported"] = len(flat)
        return out
    claims = [
        {
            "claim_id": c.claim_id,
            "hypothesis_index": hi,
            "kind": c.kind,
            "verdict": v.verdict,
            "reason": v.reason,
            "measured_value": v.measured_value,
        }
        for (hi, c), v in zip(flat, verdicts, strict=True)
    ]
    return {
        "overall": verdict.overall,
        "claims": claims,
        "n_claims": len(claims),
        "n_unsupported": sum(1 for c in claims if c["verdict"] != "pass"),
        "error": None,
    }


def _evidence(e: dict) -> dict:
    """A stored-evidence dict (the shape ``agents.tools`` keeps under ``evidence:<id>``)."""
    return {
        "evidence_id": e["evidence_id"],
        "tool": e["tool"],
        "args": e.get("args") or {},
        "summary": e.get("summary") or {},
        "provenance": e.get("provenance") or [],
        "produced_at": e.get("produced_at") or "1970-01-01T00:00:00Z",
    }


def _empty(error: str) -> dict:
    return {"overall": "FAIL", "claims": [], "n_claims": 0, "n_unsupported": 0, "error": error}
