"""The single mapping layer from ADK events to ``api/events.py`` events (the UI never sees ADK).

Sources, per ADK event (partial SSE chunks are skipped; only finals become trace events):

* ``state_delta["andon:agent:<name>"]`` = started/finished (written by agent callbacks) ->
  ``agent_started`` / ``agent_finished`` (works inside ParallelAgent branches);
* function-call parts -> ``tool_call``; function-response parts -> ``tool_result`` with the
  stored Evidence summary (raw, not the model's wrapped view), provenance and latency;
* ``state_delta["andon_event:<key>"]`` = ``{type, data}`` written by tools (``cache_hit``);
* ``custom_metadata`` = ``{"andon_event": <type>, "data": {...}}`` from our BaseAgents
  (``hypotheses``, ``model_fallback``, ``claim_verdict``, ``verifier_verdict``);
* ``state_delta["plan"]`` -> ``plan``; ``["rca_final"]`` -> ``rca_final``; ``["work_order"]`` ->
  ``work_order_draft``.

:func:`run_incident` wraps ``runner.run_async``: ``incident_started`` first; any exception ->
``error`` (code from :func:`agents.adk_budget.run_error`); always ``cost`` then ``done`` last.
Every event is validated against the contract (``api.events.parse_event``); ``seq`` is monotonic.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from google.genai import types

from agents import tools as T
from agents.adk_budget import error_data, run_error
from agents.graph import APP_NAME, AndonApp
from agents.judge import MODEL_KEY
from agents.runtime import AGENT_MARK, EVENT_PREFIX, RUN_KEY
from api.events import Event, parse_event

# ADK's structured-output tool (ADR-031): how an agent hands in its answer, not a tool card
INTERNAL_TOOLS = frozenset({"set_model_response"})
log = logging.getLogger("andon.events")

PASSTHROUGH = frozenset(
    {
        "hypotheses",
        "model_fallback",
        "claim_verdict",
        "verifier_verdict",
        "cache_hit",
        "rca_final",
        "work_order_draft",
    }
)


def _now() -> str:
    return datetime.now(UTC).isoformat()


class EventMapper:
    def __init__(self, incident_id: str, agent_models: dict[str, str | None]) -> None:
        self.incident_id = incident_id
        self.models = agent_models
        self.seq = 0
        self.open_agents: list[str] = []
        self.emitted: set[str] = set()  # one-shot types already sent (rca_final, ...)
        self._call_ts: dict[str, float] = {}
        self._used_model: dict[str, str] = {}

    # ---- construction --------------------------------------------------------------------
    def make(self, type_: str, data: dict, agent: str | None = None) -> Event:
        ev = parse_event(
            {
                "type": type_,
                "incident_id": self.incident_id,
                "seq": self.seq,
                "ts": _now(),
                "agent": agent,
                "data": data,
            }
        )
        self.seq += 1
        if type_ in ("rca_final", "work_order_draft", "plan"):
            self.emitted.add(type_)
        return ev

    def _safe(self, out: list[Event], type_: str, data: Any, agent: str | None) -> None:
        try:
            out.append(self.make(type_, data, agent))
        except Exception as exc:  # a malformed payload must not kill the stream
            log.error("dropping invalid %s event from %s: %s", type_, agent, exc)

    # ---- mapping -------------------------------------------------------------------------
    def map(self, ev: Any) -> list[Event]:
        if getattr(ev, "partial", None):
            return []
        out: list[Event] = []
        author = getattr(ev, "author", None)
        delta = dict(getattr(getattr(ev, "actions", None), "state_delta", None) or {})
        for k, v in delta.items():
            if k.startswith(MODEL_KEY) and isinstance(v, str):
                self._used_model[k[len(MODEL_KEY) :]] = v
        finished: list[str] = []
        for k, v in delta.items():
            if not k.startswith(AGENT_MARK):
                continue
            name = k[len(AGENT_MARK) :]
            if v == "started" and name not in self.open_agents:
                self.open_agents.append(name)
                self._safe(out, "agent_started", {"agent": name, "model_id": self.models.get(name)}, name)  # fmt: skip
            elif v == "finished":
                finished.append(name)

        parts = getattr(getattr(ev, "content", None), "parts", None) or []
        ts = float(getattr(ev, "timestamp", None) or time.time())
        for p in parts:
            fc = getattr(p, "function_call", None)
            if fc is not None and fc.name not in INTERNAL_TOOLS:
                cid = fc.id or f"call_{uuid.uuid4().hex[:8]}"
                self._call_ts[cid] = ts
                self._safe(out, "tool_call", {"call_id": cid, "tool": fc.name, "args": dict(fc.args or {})}, author)  # fmt: skip
        for k, v in delta.items():
            if k.startswith(EVENT_PREFIX) and isinstance(v, dict) and v.get("type") in PASSTHROUGH:
                self._safe(out, v["type"], v.get("data") or {}, author)
        for p in parts:
            fr = getattr(p, "function_response", None)
            if fr is not None and fr.name not in INTERNAL_TOOLS:
                self._safe(out, "tool_result", self._tool_result(fr, delta, ts), author)

        meta = getattr(ev, "custom_metadata", None) or {}
        kind = meta.get("andon_event")
        if isinstance(kind, dict):  # {"andon_event": {"type", "data"}} form
            kind, data = kind.get("type"), kind.get("data") or {}
        else:
            data = meta.get("data") or {}
        if kind in PASSTHROUGH:
            self._safe(out, kind, data, author)

        plan = _as_dict(delta.get("plan"))
        if plan is not None and "steps" in plan:
            self._safe(out, "plan", {"steps": list(plan["steps"])}, author)
        if isinstance(delta.get("rca_final"), dict):
            self._safe(out, "rca_final", delta["rca_final"], author)
        if isinstance(delta.get("work_order"), dict):
            self._safe(out, "work_order_draft", delta["work_order"], author)
        for name in finished:
            out.extend(self.finish_agent(name))
        return out

    def _tool_result(self, fr: Any, delta: dict, ts: float) -> dict:
        resp = dict(fr.response or {})
        cid = fr.id or ""
        t0 = self._call_ts.pop(cid, ts)
        eid = resp.get("evidence_id")
        stored = delta.get(T.EVIDENCE_PREFIX + eid) if isinstance(eid, str) else None
        if isinstance(stored, dict):
            summary, prov = stored.get("summary") or {}, stored.get("provenance") or []
        elif "summary" in resp:
            summary, prov = resp.get("summary") or {}, resp.get("provenance") or []
        else:  # errors, budget_reached, the work-order write
            summary = {k: v for k, v in resp.items() if k != "evidence_id"}
            prov = []
        return {"call_id": cid, "evidence_id": eid or "", "summary": summary,
                "provenance": prov, "latency_ms": max(int((ts - t0) * 1000), 0)}  # fmt: skip

    def finish_agent(self, name: str) -> list[Event]:
        if name not in self.open_agents:
            return []
        self.open_agents.remove(name)
        model = self._used_model.get(name, self.models.get(name))
        return [self.make("agent_finished", {"agent": name, "model_id": model}, name)]

    def close_all(self) -> list[Event]:
        out: list[Event] = []
        for name in list(self.open_agents):
            out.extend(self.finish_agent(name))
        return out


# =============================================================================================
async def run_incident(
    app: AndonApp,
    scenario_id: str,
    mode: str | None = None,
    *,
    force_bad_claim: bool = False,
    incident_id: str | None = None,
    record_dir: Path | None = None,
    user_id: str = "andon",
) -> AsyncIterator[Event]:
    """Run one incident on ``app`` and yield contract events. Never raises for run failures."""
    mode = mode or ("replay" if app.mode == "replay" else "live")
    incident_id = incident_id or f"inc_{scenario_id.lower()}_{uuid.uuid4().hex[:8]}"
    mapper = EventMapper(incident_id, app.agent_models)
    t_start = time.perf_counter()
    rt = app.rt
    invocation: str | None = None
    verdicts: list[str] = []
    scope = None
    token = None
    try:
        try:
            stop = rt.store.get_stop_event(scenario_id)
        except Exception as exc:
            log.warning("unknown scenario %s for %s: %r", scenario_id, incident_id, exc)
            yield mapper.make("error", error_data("unknown_scenario", False))
            yield mapper.make("done", {"duration_ms": int((time.perf_counter() - t_start) * 1000)})
            return
        yield mapper.make(
            "incident_started",
            {
                "scenario_id": scenario_id,
                "line_id": stop.get("line_id") or "L1",
                "stopped_station": stop.get("stopped_station") or "",
                "mode": mode,
            },
        )
        try:
            scope = rt.open_scope(incident_id, scenario_id, force_bad_claim=force_bad_claim)
        except Exception as exc:
            log.error("open_scope failed for %s: %r", incident_id, exc, exc_info=exc)
            yield mapper.make("error", error_data("replay_unavailable" if rt.mode == "replay" else "internal", False))  # fmt: skip
            yield mapper.make("done", {"duration_ms": int((time.perf_counter() - t_start) * 1000)})
            return
        token = rt.activate(scope)
        stop_summary, _ = T.TOOL_REGISTRY["get_stop_event"].impl(scope.ctx, line_id=stop["line_id"])
        state = {RUN_KEY: scope.key, "scenario_id": scenario_id, "incident_id": incident_id,
                 "stop_event": stop_summary, "force_bad_claim": scope.force_bad_claim}  # fmt: skip
        session = await app.sessions.create_session(app_name=APP_NAME, user_id=user_id, state=state)
        msg = types.Content(
            role="user",
            parts=[types.Part(text=(
                f"Investigate incident {incident_id}: line {stop_summary['line_id']} stopped at "
                f"{stop_summary['stopped_station']} ({stop_summary['stop_code']}) at "
                f"{stop_summary['stop_ts']}."))],
        )  # fmt: skip
        try:
            async for ev in app.runner.run_async(
                user_id=user_id, session_id=session.id, new_message=msg, run_config=app.run_config
            ):
                if invocation is None:
                    invocation = ev.invocation_id
                    scope.ctx.run_id = invocation  # tool-internal Gemini calls book to this run
                for out in mapper.map(ev):
                    if out.type == "verifier_verdict":
                        verdicts.append(out.data.overall)
                    yield out
        except Exception as exc:
            log.exception("run %s failed", incident_id)
            yield mapper.make("error", run_error(exc, incident_id))
        final = await app.sessions.get_session(
            app_name=APP_NAME, user_id=user_id, session_id=session.id
        )
        st = final.state if final is not None else {}
        for out in mapper.close_all():
            yield out
        if "rca_final" not in mapper.emitted and isinstance(st.get("rca_final"), dict):
            yield mapper.make("rca_final", st["rca_final"])
        if scope.recording is not None and rt.mode == "record" and record_dir is not None:
            final_status = (st.get("rca_final") or {}).get("status")
            scope.recording.meta.update({"incident_id": incident_id, "verdicts": verdicts,
                                         "final_status": final_status})  # fmt: skip
            if invocation:
                scope.recording.meta["cost"] = run_cost(app, invocation, pop=False)
            scope.recording.save(record_dir)
        await rt.close_scope(scope)
        scope = None
        cost = run_cost(app, invocation) if invocation else _zero_cost()
        yield mapper.make("cost", cost)
        yield mapper.make("done", {"duration_ms": int((time.perf_counter() - t_start) * 1000)})
    finally:
        if scope is not None:  # consumer went away mid-run: still release the manuals cache
            try:
                await rt.close_scope(scope)
            except Exception:
                log.exception("closing run scope failed")
        if token is not None:
            try:
                from agents.runtime import _SCOPE

                _SCOPE.reset(token)
            except ValueError:  # reset from another context (generator closed elsewhere)
                pass


def run_cost(app: AndonApp, invocation: str, *, pop: bool = True) -> dict:
    """The run's ``CostData``: the app's ledger plus any tool that booked to the process-wide
    LLM (``listen`` uses ``get_llm()``; in record/replay mode that is a different instance)."""
    from agents.llm import RunCost, get_llm

    books = [app.rt.llm] + ([get_llm()] if get_llm() is not app.rt.llm else [])
    total = RunCost()
    for llm in books:
        rc = llm.pop_run_cost(invocation) if pop else llm.run_cost(invocation)
        for model, m in rc.by_model.items():
            t = total.by_model.setdefault(model, type(m)())
            for f in ("calls", "failed_calls", "input_tokens", "output_tokens", "thinking_tokens",
                      "cached_tokens", "usd", "saved_usd"):  # fmt: skip
                setattr(t, f, getattr(t, f) + getattr(m, f))
        total.fallbacks.extend(rc.fallbacks)
    return total.to_cost_data()


def _zero_cost() -> dict:
    return {"input_tokens": 0, "output_tokens": 0, "cached_tokens": 0, "usd": 0.0, "by_model": {}}


def _as_dict(value: Any) -> dict | None:
    """An agent's ``output_key`` value as a dict: native structured output stores a dict, ADK's
    ``set_model_response`` path (ADR-031) can store a JSON string or a pydantic model."""
    if isinstance(value, dict):
        return value
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except ValueError:
            return None
        return parsed if isinstance(parsed, dict) else None
    return None
