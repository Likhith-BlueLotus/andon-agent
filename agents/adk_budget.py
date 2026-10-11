"""Budget, pinned-model and cost guard for every Gemini call that ADK makes (ADR-020, RISKS #22).

ADK agents call Gemini through their own model objects, not through :meth:`agents.llm.LLM.generate`.
:class:`AndonBudgetPlugin` sits on ``App(plugins=[...])`` and applies the same rules to them:

* ``before_model_callback`` — reject unpinned models and sampling knobs Gemini 3 must not get
  (temperature / top_p / top_k), then ``spend.check()``. Violations *raise*: ADK wraps the error in
  a ``RuntimeError`` (original chained) and the whole run stops. Returning an error ``LlmResponse``
  would not stop it — a ``SequentialAgent`` carries on with its next sub-agent, and
  ``end_invocation`` set from a model callback does not propagate to the parent (verified on ADK
  2.11.0). Use :func:`run_error` to turn the raised error into an SSE ``error`` code.
* ``after_model_callback`` — book ``usage_metadata`` through :meth:`LLM.record`, only for responses
  that are not ``partial``. Under ``StreamingMode.SSE`` the partial chunks carry usage too; the
  final aggregated response carries the turn's total. Should one call ever yield a second
  non-partial response (non-progressive SSE), only the increase over what was booked is added.
* ``on_model_error_callback`` — book a failed row (``usd=None``) classified as
  ``429`` / ``5xx`` / ``timeout`` / ``error``; the error then propagates.

Per-run totals are keyed by ADK ``invocation_id`` and read with :meth:`AndonBudgetPlugin.run_cost`
(``.to_cost_data()`` is the ``cost`` SSE payload). Direct ``LLM.generate(..., run_id=invocation_id)``
calls from tools land in the same totals.
"""

from __future__ import annotations

import logging
import os
import time
from collections import OrderedDict
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from typing import Any

from google.adk.agents.invocation_context import LlmCallsLimitExceededError
from google.adk.models import Gemini
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.adk.plugins.base_plugin import BasePlugin
from google.genai import types

import config
from agents.llm import (
    LLM,
    BudgetExhaustedError,
    RunCost,
    UnpinnedModelError,
    Usage,
    classify_error,
    get_llm,
)

log = logging.getLogger("andon.adk_budget")

PLUGIN_NAME = "andon_budget"
THINKING_LEVELS = frozenset({"MINIMAL", "LOW", "MEDIUM", "HIGH"})
_FORBIDDEN_SAMPLING = ("temperature", "top_p", "top_k")
_MAX_INFLIGHT = 1024


class ModelPolicyError(ValueError):
    """A request breaks the Gemini 3 rules (sampling knobs set, bad thinking level)."""


def normalise_model_id(name: str | None) -> str:
    """``projects/../publishers/google/models/gemini-3.8-flash`` -> ``gemini-3.8-flash``."""
    return (name or "").rsplit("/", 1)[-1]


# --- Model factory ---------------------------------------------------------------------------
class PinnedGemini(Gemini):
    """ADK ``Gemini`` that adds our thinking level and per-attempt timeout to every request.

    Thinking is a request setting, not a model setting, in ADK; carrying it on the model keeps
    each agent definition to one ``model=make_model(...)`` line. An agent that sets its own
    ``generate_content_config.thinking_config`` wins.
    """

    thinking_level: str | None = None
    timeout_s: float = config.LLM_TIMEOUT_S

    async def generate_content_async(
        self, llm_request: LlmRequest, stream: bool = False
    ) -> AsyncGenerator[LlmResponse, None]:
        cfg = llm_request.config = llm_request.config or types.GenerateContentConfig()
        if self.thinking_level and cfg.thinking_config is None:
            cfg.thinking_config = types.ThinkingConfig(
                thinking_level=types.ThinkingLevel(self.thinking_level)
            )
        cfg.http_options = cfg.http_options or types.HttpOptions()
        if cfg.http_options.timeout is None:
            cfg.http_options.timeout = int(self.timeout_s * 1000)  # milliseconds
        async for resp in super().generate_content_async(llm_request, stream=stream):
            yield resp


def make_model(
    model_id: str,
    thinking_level: str | None = None,
    *,
    retries: int = config.LLM_MAX_RETRIES,
    timeout_s: float = config.LLM_TIMEOUT_S,
) -> PinnedGemini:
    """The ADK model object for a pinned model, on the right endpoint, with retry/backoff.

    * location from ``config.location_for`` (residency model -> asia-south1, else ``global``);
    * HTTP retry on ``config.RETRYABLE_HTTP_CODES`` with exponential backoff and jitter
      (``retries=0`` for a primary that should fail over fast, e.g. the judge);
    * ``thinking_level`` LOW/MEDIUM/HIGH (MINIMAL allowed); no temperature/top_p/top_k ever.

    Also sets ``GOOGLE_GENAI_USE_ENTERPRISE=true`` if unset: ADK decides from the *environment*
    (not ``client_kwargs``) whether ``output_schema`` may be combined with tools natively.
    """
    if model_id not in config.PINNED_MODELS:
        raise UnpinnedModelError(f"{model_id!r} is not a pinned model (see config.py)")
    if thinking_level is not None and thinking_level not in THINKING_LEVELS:
        raise ModelPolicyError(f"thinking_level must be one of {sorted(THINKING_LEVELS)}")
    os.environ.setdefault("GOOGLE_GENAI_USE_ENTERPRISE", "true")
    client_kwargs: dict[str, Any] = {
        "vertexai": True,
        "location": config.location_for(model_id),
    }
    if config.PROJECT:
        client_kwargs["project"] = config.PROJECT
    return PinnedGemini(
        model=model_id,
        thinking_level=thinking_level,
        timeout_s=timeout_s,
        client_kwargs=client_kwargs,
        retry_options=types.HttpRetryOptions(
            attempts=retries + 1,  # includes the first request
            initial_delay=config.LLM_BACKOFF_BASE_S,
            max_delay=config.LLM_BACKOFF_MAX_S,
            exp_base=2.0,
            jitter=0.5,
            http_status_codes=sorted(config.RETRYABLE_HTTP_CODES),
        ),
    )


# --- Errors -> SSE `error` codes -------------------------------------------------------------
def _chain(exc: BaseException) -> list[BaseException]:
    seen: list[BaseException] = []
    cur: BaseException | None = exc
    while cur is not None and cur not in seen:
        seen.append(cur)
        cur = cur.__cause__ or cur.__context__
    return seen


SAFE_MESSAGES = {
    "model_unavailable": "The model service is busy or unavailable. Please try again shortly.",
    "model_timeout": "The model took too long to answer. Please try again.",
    "llm_call_limit": "The investigation reached its model-call limit and was stopped.",
    "replay_unavailable": "This recorded run is not available.",
    "unknown_scenario": "Unknown scenario.",
    "timeout": "The investigation took too long and was stopped.",
    "internal": "Internal error. The incident has been logged.",
}


def error_data(code: str, retryable: bool, message: str | None = None) -> dict:
    """``ErrorData`` with a fixed, user-safe message per code. Exception text (project ids, model
    paths, URLs) never goes on the wire; callers log it server-side."""
    return {"code": code, "message": message or SAFE_MESSAGES[code], "retryable": retryable}


def run_error(exc: BaseException, incident_id: str | None = None) -> dict:
    """``ErrorData`` fields (``code``, ``message``, ``retryable``) for an exception out of a run.

    ADK re-raises plugin exceptions as ``RuntimeError`` with the original chained, so the whole
    cause chain is searched. Only ``budget_exhausted`` carries exception text (dollar amounts and a
    date); every other message is fixed per code and the detail is logged with ``incident_id``.
    """
    chain = _chain(exc)
    for e in chain:
        if isinstance(e, BudgetExhaustedError):
            return error_data("budget_exhausted", False, str(e)[:200])
    out = None
    for e in chain:
        if isinstance(e, (UnpinnedModelError, ModelPolicyError)):
            out = error_data("internal", False)
            break
        if isinstance(e, LlmCallsLimitExceededError):
            out = error_data("llm_call_limit", False)
            break
    if out is None:
        for e in chain:
            outcome = classify_error(e)
            if outcome in ("429", "5xx"):
                out = error_data("model_unavailable", True)
                break
            if outcome == "timeout":
                out = error_data("model_timeout", True)
                break
    out = out or error_data("internal", False)
    log.error("run error %s for %s: %r", out["code"], incident_id or "-", exc, exc_info=exc)
    return out


# --- Plugin ----------------------------------------------------------------------------------
@dataclass
class _Call:
    actions: Any  # strong ref so id() stays unique while tracked
    request: LlmRequest  # read again after the call: FallbackModel rewrites .model
    model_id: str
    agent: str | None
    run_id: str | None
    t0: float
    booked: Usage | None = None


def _minus(a: Usage, b: Usage | None) -> Usage:
    if b is None:
        return a
    return Usage(
        a.model_id,
        input_tokens=max(a.input_tokens - b.input_tokens, 0),
        output_tokens=max(a.output_tokens - b.output_tokens, 0),
        cached_tokens=max(a.cached_tokens - b.cached_tokens, 0),
        thinking_tokens=max(a.thinking_tokens - b.thinking_tokens, 0),
    )


class AndonBudgetPlugin(BasePlugin):
    """Register once on the ``App``: ``App(name=..., root_agent=..., plugins=[AndonBudgetPlugin()])``."""

    def __init__(self, llm: LLM | None = None, name: str = PLUGIN_NAME) -> None:
        super().__init__(name=name)
        self.llm = llm or get_llm()
        self._inflight: OrderedDict[int, _Call] = OrderedDict()

    # ---- helpers -------------------------------------------------------------------------
    @staticmethod
    def _ids(ctx: Any) -> tuple[str | None, str | None]:
        return getattr(ctx, "agent_name", None), getattr(ctx, "invocation_id", None)

    def _key(self, ctx: Any) -> int:
        return id(getattr(ctx, "actions", ctx))

    def _track(self, ctx: Any, call: _Call) -> None:
        self._inflight[self._key(ctx)] = call
        while len(self._inflight) > _MAX_INFLIGHT:
            self._inflight.popitem(last=False)

    def _lookup(self, ctx: Any) -> _Call | None:
        call = self._inflight.get(self._key(ctx))
        if call is not None and call.actions is not getattr(ctx, "actions", ctx):
            return None
        return call

    def run_cost(self, invocation_id: str) -> RunCost:
        return self.llm.run_cost(invocation_id)

    def pop_run_cost(self, invocation_id: str) -> RunCost:
        return self.llm.pop_run_cost(invocation_id)

    # ---- callbacks -----------------------------------------------------------------------
    async def before_model_callback(
        self, *, callback_context: Any, llm_request: LlmRequest
    ) -> LlmResponse | None:
        agent, run_id = self._ids(callback_context)
        model_id = normalise_model_id(llm_request.model)
        if model_id not in config.PINNED_MODELS:
            raise UnpinnedModelError(
                f"agent {agent!r} asked for {llm_request.model!r}, which is not pinned"
            )
        cfg = llm_request.config
        bad = [k for k in _FORBIDDEN_SAMPLING if cfg is not None and getattr(cfg, k) is not None]
        if bad:
            raise ModelPolicyError(f"agent {agent!r} sets {bad}; Gemini 3 takes a thinking level")
        self.llm.spend.check()  # raises BudgetExhaustedError -> run stops
        self._track(
            callback_context,
            _Call(
                actions=getattr(callback_context, "actions", callback_context),
                request=llm_request,
                model_id=model_id,
                agent=agent,
                run_id=run_id,
                t0=time.perf_counter(),
            ),
        )
        return None

    async def after_model_callback(
        self, *, callback_context: Any, llm_response: LlmResponse
    ) -> LlmResponse | None:
        if llm_response.partial:  # streamed chunk; the aggregated final response is booked
            return None
        um = llm_response.usage_metadata
        if um is None:
            return None
        call = self._lookup(callback_context)
        agent, run_id = self._ids(callback_context)
        if call is None:  # no before_model seen (should not happen); book what the response says
            model_id = normalise_model_id(llm_response.model_version)
            if model_id not in config.PRICES:
                log.error("unattributed usage from %r (agent %s); not booked", model_id, agent)
                return None
            self.llm.record(Usage.from_metadata(model_id, um), agent=agent, run_id=run_id)
            return None
        used = normalise_model_id(call.request.model) or call.model_id
        if used not in config.PRICES:
            used = call.model_id
        fallback_from = call.model_id if used != call.model_id else None
        if fallback_from:
            self.llm.note_fallback(call.run_id, call.model_id, used, "fallback_model")
        usage = Usage.from_metadata(used, um)
        delta = _minus(usage, call.booked)
        if call.booked is not None and delta == Usage(used):
            return None  # same usage reported twice for one call
        self.llm.record(
            delta,
            agent=call.agent,
            fallback_from=fallback_from,
            latency_ms=int((time.perf_counter() - call.t0) * 1000),
            run_id=call.run_id,
        )
        call.booked = usage
        return None

    async def on_model_error_callback(
        self, *, callback_context: Any, llm_request: LlmRequest, error: Exception
    ) -> LlmResponse | None:
        call = self._lookup(callback_context)
        agent, run_id = self._ids(callback_context)
        model_id = normalise_model_id(llm_request.model) or (call.model_id if call else "")
        if model_id not in config.PINNED_MODELS and call is not None:
            model_id = call.model_id
        self.llm.record(
            None,
            agent=agent,
            model_id=model_id or "unknown",
            outcome=classify_error(error),
            latency_ms=int((time.perf_counter() - call.t0) * 1000) if call else None,
            run_id=run_id,
        )
        self._inflight.pop(self._key(callback_context), None)
        return None  # let ADK raise; the API maps it with run_error()

    async def after_run_callback(self, *, invocation_context: Any) -> None:
        inv = getattr(invocation_context, "invocation_id", None)
        for k in [k for k, c in self._inflight.items() if c.run_id == inv]:
            del self._inflight[k]
