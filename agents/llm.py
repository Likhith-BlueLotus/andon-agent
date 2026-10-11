"""The only gateway to Gemini: pinned-model guard, retry/backoff, fallback, cost accounting,
and the daily spend kill switch.

Two ways in, one ledger:

* direct calls go through :meth:`LLM.generate` (tools such as ``cite_manual``, the eval, scripts);
* ADK agents call Gemini themselves, so ``agents/adk_budget.AndonBudgetPlugin`` guards them and
  books their usage through :meth:`LLM.record` (ADR-020).

Both use the process-wide default from :func:`get_llm`, so the API, the CLI and the plugin share one
daily spend counter. v0 keeps that counter in memory (per process; RISKS #23). Phase 3 persists it
to Firestore so it survives restarts and is shared across Cloud Run instances.
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
import threading
import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

import config

log = logging.getLogger("andon.llm")

# (model_id, contents, generation_config) -> google-genai GenerateContentResponse (or a fake).
Transport = Callable[[str, Any, Any], Awaitable[Any]]


class BudgetExhaustedError(RuntimeError):
    """Today's measured spend reached DAILY_BUDGET_USD; live runs must fall back to replay."""


class UnpinnedModelError(ValueError):
    """A model ID that is not in config.PINNED_MODELS was requested."""


# --- Cost maths ------------------------------------------------------------------------------
def cost_usd(
    model_id: str,
    input_tokens: int,
    output_tokens: int,
    cached_tokens: int = 0,
    thinking_tokens: int = 0,
) -> float:
    """USD for one call. `input_tokens` is the full prompt size *including* cached tokens."""
    if min(input_tokens, output_tokens, cached_tokens, thinking_tokens) < 0:
        raise ValueError("token counts must be non-negative")
    if cached_tokens > input_tokens:
        raise ValueError("cached_tokens cannot exceed input_tokens")
    p = config.price_for(model_id)
    long = p.long_context_threshold is not None and input_tokens > p.long_context_threshold
    in_rate = p.input_long if long and p.input_long is not None else p.input
    out_rate = p.output_long if long and p.output_long is not None else p.output
    cache_rate = p.cached_input_long if long and p.cached_input_long is not None else p.cached_input
    uncached = input_tokens - cached_tokens
    return (
        uncached * in_rate
        + cached_tokens * cache_rate
        + (output_tokens + thinking_tokens) * out_rate
    ) / 1_000_000


def cache_savings_usd(model_id: str, input_tokens: int, cached_tokens: int) -> float:
    """USD saved by billing ``cached_tokens`` of an ``input_tokens`` prompt at the cached rate."""
    return cost_usd(model_id, input_tokens, 0) - cost_usd(model_id, input_tokens, 0, cached_tokens)


@dataclass(frozen=True)
class Usage:
    model_id: str
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0
    thinking_tokens: int = 0

    @property
    def usd(self) -> float:
        return cost_usd(
            self.model_id,
            self.input_tokens,
            self.output_tokens,
            self.cached_tokens,
            self.thinking_tokens,
        )

    @classmethod
    def from_response(cls, model_id: str, response: Any) -> Usage:
        return cls.from_metadata(model_id, getattr(response, "usage_metadata", None))

    @classmethod
    def from_metadata(cls, model_id: str, um: Any) -> Usage:
        """From a ``GenerateContentResponseUsageMetadata`` (or anything with the same fields)."""

        def n(attr: str) -> int:
            return int(getattr(um, attr, None) or 0)

        return cls(
            model_id=model_id,
            input_tokens=n("prompt_token_count"),
            output_tokens=n("candidates_token_count"),
            cached_tokens=n("cached_content_token_count"),
            thinking_tokens=n("thoughts_token_count"),
        )


# --- Daily kill switch -----------------------------------------------------------------------
class SpendTracker:
    def __init__(
        self,
        daily_budget_usd: float = config.DAILY_BUDGET_USD,
        tz: str = config.BUDGET_TIMEZONE,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.daily_budget_usd = daily_budget_usd
        self._tz = ZoneInfo(tz)
        self._clock = clock or (lambda: datetime.now(self._tz))
        self._day: date = self._today()
        self._spent = 0.0
        # Phase 3 hooks (api/budget.py): listeners see every booked amount (to persist it in a
        # counter shared across instances); guards run inside check() and may raise
        # BudgetExhaustedError, so a run already in flight stops at the shared budget too.
        self._listeners: list[Callable[[float], None]] = []
        self._guards: list[Callable[[], None]] = []

    def add_listener(self, fn: Callable[[float], None]) -> None:
        self._listeners.append(fn)

    def add_guard(self, fn: Callable[[], None]) -> None:
        self._guards.append(fn)

    def _today(self) -> date:
        return self._clock().astimezone(self._tz).date()

    def _roll(self) -> None:
        today = self._today()
        if today != self._day:
            self._day, self._spent = today, 0.0

    def add(self, usd: float) -> None:
        self._roll()
        self._spent += usd
        for fn in self._listeners:
            try:
                fn(usd)
            except Exception:  # a broken listener must never break a model call
                log.exception("spend listener failed")

    def spent_today(self) -> float:
        self._roll()
        return self._spent

    def remaining(self) -> float:
        return max(self.daily_budget_usd - self.spent_today(), 0.0)

    def check(self) -> None:
        if self.spent_today() >= self.daily_budget_usd:
            raise BudgetExhaustedError(
                f"daily budget ${self.daily_budget_usd:.2f} exhausted "
                f"(spent ${self._spent:.4f} on {self._day.isoformat()})"
            )
        for fn in self._guards:
            fn()


# --- Client ----------------------------------------------------------------------------------
def _is_timeout(exc: BaseException) -> bool:
    if isinstance(exc, TimeoutError):
        return True
    try:
        import httpx  # google-genai's transport raises its own timeout types
    except ImportError:  # pragma: no cover
        return False
    return isinstance(exc, httpx.TimeoutException)


def is_retryable(exc: BaseException) -> bool:
    if _is_timeout(exc):
        return True
    code = getattr(exc, "code", None) or getattr(exc, "status_code", None)
    return isinstance(code, int) and code in config.RETRYABLE_HTTP_CODES


def classify_error(exc: BaseException) -> str:
    """Ledger/SSE outcome for a failed call: ``timeout`` | ``429`` | ``5xx`` | ``error``."""
    if _is_timeout(exc):
        return "timeout"
    code = getattr(exc, "code", None) or getattr(exc, "status_code", None)
    if code == 429:
        return "429"
    if isinstance(code, int) and 500 <= code <= 599:
        return "5xx"
    return "error"


def _fallback_reason(exc: BaseException) -> str | None:
    """Why the judge should fall back, or None if the error is not transient."""
    if _is_timeout(exc):
        return "timeout"
    if is_retryable(exc):
        return str(getattr(exc, "code", None) or getattr(exc, "status_code", None))
    return None


@dataclass
class LLMResult:
    response: Any
    usage: Usage
    model_id: str
    latency_ms: int
    fallback_from: str | None = None


# --- Per-run totals (feed the `cost` SSE event) -----------------------------------------------
@dataclass
class ModelCost:
    calls: int = 0  # model calls (cache rows add cost, not calls)
    failed_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0  # candidates only
    thinking_tokens: int = 0
    cached_tokens: int = 0
    usd: float = 0.0
    saved_usd: float = 0.0  # what the cached tokens would have cost at the full input rate


@dataclass
class RunCost:
    """Everything one run (an ADK invocation, an eval case, a CLI diagnosis) spent, by model."""

    by_model: dict[str, ModelCost] = field(default_factory=dict)
    fallbacks: list[dict] = field(default_factory=list)  # {from_model, to_model, reason}

    def add(
        self, usage: Usage | None, usd: float | None, model_id: str, *, ok: bool, call: bool = True
    ) -> None:
        m = self.by_model.setdefault(model_id, ModelCost())
        if not ok:
            m.failed_calls += 1
            return
        m.calls += int(call)
        if usage is not None:
            m.input_tokens += usage.input_tokens
            m.output_tokens += usage.output_tokens
            m.thinking_tokens += usage.thinking_tokens
            m.cached_tokens += usage.cached_tokens
            if usage.cached_tokens and model_id in config.PRICES:
                m.saved_usd += cache_savings_usd(model_id, usage.input_tokens, usage.cached_tokens)
        m.usd += usd or 0.0

    @property
    def usd(self) -> float:
        return sum(m.usd for m in self.by_model.values())

    @property
    def saved_usd(self) -> float:
        return sum(m.saved_usd for m in self.by_model.values())

    def to_cost_data(self) -> dict:
        """Exactly the `CostData` fields of `api/events.py`. Thinking tokens count as output
        tokens here because they are billed as output."""
        ms = self.by_model.values()
        return {
            "input_tokens": sum(m.input_tokens for m in ms),
            "output_tokens": sum(m.output_tokens + m.thinking_tokens for m in ms),
            "cached_tokens": sum(m.cached_tokens for m in ms),
            "usd": round(self.usd, 6),
            "by_model": {k: round(m.usd, 6) for k, m in self.by_model.items()},
        }


# Runs kept in memory for the `cost` event; old ones are evicted (the ledger keeps everything).
MAX_TRACKED_RUNS = 512


@dataclass
class LLM:
    transport: Transport | None = None
    spend: SpendTracker = field(default_factory=SpendTracker)
    max_retries: int = config.LLM_MAX_RETRIES
    backoff_base_s: float = config.LLM_BACKOFF_BASE_S
    backoff_max_s: float = config.LLM_BACKOFF_MAX_S
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep
    ledger: list[dict] = field(default_factory=list)
    # None = Application Default Credentials. Scripts/live tests may pass gcloud-token credentials.
    credentials: Any = field(default=None, repr=False)
    _clients: dict[tuple[str, int], tuple[Any, Any]] = field(default_factory=dict, repr=False)
    _runs: OrderedDict[str, RunCost] = field(default_factory=OrderedDict, repr=False)

    # --- client -------------------------------------------------------------------------
    def client(self, location: str) -> Any:
        """The google-genai client for ``location``, one per event loop.

        The only place a raw client is built. The ``aio`` client binds to the loop of its first
        call (LESSONS 2026-10-11), so a client is reused only inside the loop that created it;
        the reference is held so its HTTP pool is not garbage-collected mid-request.
        """
        from google import genai

        try:
            loop: Any = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        key = (location, id(loop))
        hit = self._clients.get(key)
        if hit is None or hit[0] is not loop:
            client = genai.Client(
                vertexai=True,
                project=config.PROJECT or None,
                location=location,
                credentials=self.credentials,
            )
            self._clients[key] = (loop, client)
            return client
        return hit[1]

    # Real transport, created lazily so tests and imports never touch the network.
    async def _genai_transport(self, model_id: str, contents: Any, gen_config: Any) -> Any:
        client = self.client(config.location_for(model_id))
        return await client.aio.models.generate_content(
            model=model_id, contents=contents, config=gen_config
        )

    # --- accounting ---------------------------------------------------------------------
    def record(
        self,
        usage: Usage | None,
        *,
        agent: str | None = None,
        model_id: str | None = None,
        fallback_from: str | None = None,
        outcome: str = "ok",
        latency_ms: int | None = None,
        run_id: str | None = None,
        event: str = "llm_call",
        usd: float | None = None,
    ) -> dict:
        """Book one billable (or failed) call: spend counter, per-run totals, ledger, log line.

        ``usage=None`` with ``outcome != "ok"`` records a failed call (``usd`` stays None: Gemini
        does not bill failed requests). ``usd`` overrides the price computed from ``usage`` (used
        for cache-storage estimates).
        """
        model = model_id or (usage.model_id if usage else None)
        if model is None:
            raise ValueError("record() needs usage or model_id")
        ok = outcome == "ok"
        if usd is None and usage is not None and ok:
            usd = usage.usd
        if usd:
            self.spend.add(usd)
        if run_id is not None:
            self.run_cost(run_id).add(usage, usd, model, ok=ok, call=event == "llm_call")
        u = usage or Usage(model)
        entry = {
            "event": event,
            "agent": agent,
            "run_id": run_id,
            "model_id": model,
            "fallback_from": fallback_from,
            "outcome": outcome,
            "input_tokens": u.input_tokens,
            "output_tokens": u.output_tokens,
            "cached_tokens": u.cached_tokens,
            "thinking_tokens": u.thinking_tokens,
            "usd": None if usd is None else round(usd, 6),
            "latency_ms": latency_ms,
            "spent_today_usd": round(self.spend.spent_today(), 6),
        }
        self.ledger.append(entry)
        (log.info if ok else log.warning)(json.dumps(entry))
        return entry

    def run_cost(self, run_id: str) -> RunCost:
        """Totals for one run (created on first use; the oldest runs are evicted)."""
        rc = self._runs.get(run_id)
        if rc is None:
            rc = self._runs[run_id] = RunCost()
            while len(self._runs) > MAX_TRACKED_RUNS:
                self._runs.popitem(last=False)
        return rc

    def pop_run_cost(self, run_id: str) -> RunCost:
        return self._runs.pop(run_id, None) or RunCost()

    def note_fallback(
        self, run_id: str | None, from_model: str, to_model: str, reason: str
    ) -> None:
        if run_id is not None:
            self.run_cost(run_id).fallbacks.append(
                {"from_model": from_model, "to_model": to_model, "reason": reason}
            )

    # --- calls --------------------------------------------------------------------------
    async def _once(self, model_id: str, contents: Any, gen_config: Any, timeout_s: float) -> Any:
        transport = self.transport or self._genai_transport
        return await asyncio.wait_for(transport(model_id, contents, gen_config), timeout=timeout_s)

    async def _with_retry(
        self, model_id: str, contents: Any, gen_config: Any, timeout_s: float, retries: int
    ) -> Any:
        for attempt in range(retries + 1):
            try:
                return await self._once(model_id, contents, gen_config, timeout_s)
            except Exception as exc:
                if attempt >= retries or not is_retryable(exc):
                    raise
                delay = min(self.backoff_max_s, self.backoff_base_s * 2**attempt)
                delay *= 0.5 + random.random() / 2  # jitter
                log.warning("llm retry model=%s attempt=%d err=%r", model_id, attempt + 1, exc)
                await self.sleep(delay)
        raise AssertionError("unreachable")

    async def generate(
        self,
        model_id: str,
        contents: Any,
        gen_config: Any = None,
        *,
        agent: str | None = None,
        fallback_model: str | None = None,
        primary_timeout_s: float | None = None,
        timeout_s: float = config.LLM_TIMEOUT_S,
        on_fallback: Callable[[str, str, str], None] | None = None,
        run_id: str | None = None,
    ) -> LLMResult:
        """Call Gemini through every guard.

        With `fallback_model`, the primary gets one attempt (bounded by `primary_timeout_s`);
        a 429/5xx or timeout switches to the fallback, which gets the normal retry budget.
        Failed attempts are booked as ledger rows with ``usd=None``.
        """
        for m in (model_id, fallback_model):
            if m is not None and m not in config.PINNED_MODELS:
                raise UnpinnedModelError(f"{m!r} is not a pinned model (see config.py)")
        self.spend.check()

        used, fallback_from = model_id, None
        t0 = time.perf_counter()

        def ms() -> int:
            return int((time.perf_counter() - t0) * 1000)

        try:
            if fallback_model is None:
                response = await self._with_retry(
                    model_id, contents, gen_config, timeout_s, self.max_retries
                )
            else:
                try:
                    response = await self._once(
                        model_id, contents, gen_config, primary_timeout_s or timeout_s
                    )
                except Exception as exc:
                    reason = _fallback_reason(exc)
                    if reason is None:
                        raise
                    log.warning("llm fallback %s -> %s (%s)", model_id, fallback_model, reason)
                    self.record(
                        None,
                        agent=agent,
                        model_id=model_id,
                        outcome=classify_error(exc),
                        latency_ms=ms(),
                        run_id=run_id,
                    )
                    self.note_fallback(run_id, model_id, fallback_model, reason)
                    if on_fallback:
                        on_fallback(model_id, fallback_model, reason)
                    used, fallback_from = fallback_model, model_id
                    response = await self._with_retry(
                        fallback_model, contents, gen_config, timeout_s, self.max_retries
                    )
        except Exception as exc:
            # the ledger row has no message field; log it so failures are diagnosable
            log.warning("llm call failed (%s, %s): %s: %.300s", agent, used, type(exc).__name__, exc)
            self.record(
                None,
                agent=agent,
                model_id=used,
                fallback_from=fallback_from,
                outcome=classify_error(exc),
                latency_ms=ms(),
                run_id=run_id,
            )
            raise

        latency_ms = ms()
        usage = Usage.from_response(used, response)
        self.record(
            usage,
            agent=agent,
            fallback_from=fallback_from,
            latency_ms=latency_ms,
            run_id=run_id,
        )
        return LLMResult(response, usage, used, latency_ms, fallback_from)


# --- Process-wide default (one spend counter per process) -------------------------------------
_default_lock = threading.Lock()
_default_llm: LLM | None = None


def get_llm() -> LLM:
    """The shared :class:`LLM` used by the API, the CLI, tools and the ADK budget plugin."""
    global _default_llm
    with _default_lock:
        if _default_llm is None:
            _default_llm = LLM()
        return _default_llm


def get_spend() -> SpendTracker:
    """The shared daily spend counter (the kill switch)."""
    return get_llm().spend


def set_default_llm(llm: LLM | None) -> LLM | None:
    """Replace the shared instance (tests, eval with a custom budget). Returns the previous one."""
    global _default_llm
    with _default_lock:
        prev, _default_llm = _default_llm, llm
        return prev
