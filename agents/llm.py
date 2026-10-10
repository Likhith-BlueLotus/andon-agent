"""The only gateway to Gemini: pinned-model guard, retry/backoff, fallback, cost accounting,
and the daily spend kill switch.

v0 keeps the daily spend counter in memory (per process). Phase 3 persists it to Firestore so it
survives restarts and is shared across Cloud Run instances.
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
import time
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
        um = getattr(response, "usage_metadata", None)

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

    def _today(self) -> date:
        return self._clock().astimezone(self._tz).date()

    def _roll(self) -> None:
        today = self._today()
        if today != self._day:
            self._day, self._spent = today, 0.0

    def add(self, usd: float) -> None:
        self._roll()
        self._spent += usd

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


@dataclass
class LLM:
    transport: Transport | None = None
    spend: SpendTracker = field(default_factory=SpendTracker)
    max_retries: int = config.LLM_MAX_RETRIES
    backoff_base_s: float = config.LLM_BACKOFF_BASE_S
    backoff_max_s: float = config.LLM_BACKOFF_MAX_S
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep
    ledger: list[dict] = field(default_factory=list)
    _clients: dict[str, Any] = field(default_factory=dict, repr=False)

    # Real transport, created lazily so tests and imports never touch the network.
    async def _genai_transport(self, model_id: str, contents: Any, gen_config: Any) -> Any:
        from google import genai

        loc = config.location_for(model_id)
        if loc not in self._clients:
            self._clients[loc] = genai.Client(vertexai=True, project=config.PROJECT, location=loc)
        return await self._clients[loc].aio.models.generate_content(
            model=model_id, contents=contents, config=gen_config
        )

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
    ) -> LLMResult:
        """Call Gemini through every guard.

        With `fallback_model`, the primary gets one attempt (bounded by `primary_timeout_s`);
        a 429/5xx or timeout switches to the fallback, which gets the normal retry budget.
        """
        for m in (model_id, fallback_model):
            if m is not None and m not in config.PINNED_MODELS:
                raise UnpinnedModelError(f"{m!r} is not a pinned model (see config.py)")
        self.spend.check()

        used, fallback_from = model_id, None
        t0 = time.perf_counter()
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
                    if on_fallback:
                        on_fallback(model_id, fallback_model, reason)
                    used, fallback_from = fallback_model, model_id
                    response = await self._with_retry(
                        fallback_model, contents, gen_config, timeout_s, self.max_retries
                    )
        finally:
            latency_ms = int((time.perf_counter() - t0) * 1000)

        usage = Usage.from_response(used, response)
        usd = usage.usd
        self.spend.add(usd)
        entry = {
            "event": "llm_call",
            "agent": agent,
            "model_id": used,
            "fallback_from": fallback_from,
            "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens,
            "cached_tokens": usage.cached_tokens,
            "thinking_tokens": usage.thinking_tokens,
            "usd": round(usd, 6),
            "latency_ms": latency_ms,
            "spent_today_usd": round(self.spend.spent_today(), 6),
        }
        self.ledger.append(entry)
        log.info(json.dumps(entry))
        return LLMResult(response, usage, used, latency_ms, fallback_from)
