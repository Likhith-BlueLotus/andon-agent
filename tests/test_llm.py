"""Offline tests for agents/llm.py: cost maths, kill switch, retry, fallback, pinned-model guard."""

import asyncio
from datetime import datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

import config
from agents.llm import (
    LLM,
    BudgetExhaustedError,
    SpendTracker,
    UnpinnedModelError,
    Usage,
    cost_usd,
)

IST = ZoneInfo("Asia/Kolkata")


def fake_response(prompt=1000, out=200, cached=0, thoughts=0):
    return SimpleNamespace(
        usage_metadata=SimpleNamespace(
            prompt_token_count=prompt,
            candidates_token_count=out,
            cached_content_token_count=cached,
            thoughts_token_count=thoughts,
        )
    )


class APIErr(Exception):
    def __init__(self, code):
        super().__init__(f"HTTP {code}")
        self.code = code


async def no_sleep(_):
    return None


# --- cost maths ------------------------------------------------------------------------------
def test_cost_flat_pricing():
    p = config.PRICES[config.FLASH]
    got = cost_usd(config.FLASH, input_tokens=1_000_000, output_tokens=1_000_000)
    assert got == pytest.approx(p.input + p.output)


def test_cost_cached_and_thinking():
    p = config.PRICES[config.FLASH]
    got = cost_usd(config.FLASH, 10_000, 500, cached_tokens=8_000, thinking_tokens=1_500)
    want = (2_000 * p.input + 8_000 * p.cached_input + 2_000 * p.output) / 1e6
    assert got == pytest.approx(want)


def test_cost_long_context_tier():
    p = config.PRICES[config.PRO_JUDGE]
    assert p.long_context_threshold is not None
    short = cost_usd(config.PRO_JUDGE, p.long_context_threshold, 0)
    long = cost_usd(config.PRO_JUDGE, p.long_context_threshold + 1, 0)
    assert short == pytest.approx(p.long_context_threshold * p.input / 1e6)
    assert long == pytest.approx((p.long_context_threshold + 1) * p.input_long / 1e6)


@pytest.mark.parametrize("kwargs", [{"input_tokens": -1}, {"cached_tokens": 5}])
def test_cost_rejects_bad_counts(kwargs):
    args = {"input_tokens": 1, "output_tokens": 0, "cached_tokens": 0} | kwargs
    with pytest.raises(ValueError):
        cost_usd(config.FLASH, **args)


def test_cost_unknown_model():
    with pytest.raises(KeyError):
        cost_usd("gemini-unknown", 1, 1)


def test_usage_from_response_handles_missing_fields():
    r = SimpleNamespace(usage_metadata=SimpleNamespace(prompt_token_count=10))
    u = Usage.from_response(config.FLASH, r)
    assert (u.input_tokens, u.output_tokens, u.cached_tokens, u.thinking_tokens) == (10, 0, 0, 0)


def test_every_pinned_model_has_a_price():
    assert set(config.PINNED_MODELS) <= set(config.PRICES)


# --- kill switch -----------------------------------------------------------------------------
def test_spend_tracker_blocks_and_rolls_over_at_ist_midnight():
    now = [datetime(2026, 10, 10, 23, 59, tzinfo=IST)]
    t = SpendTracker(daily_budget_usd=1.0, clock=lambda: now[0])
    t.add(0.6)
    t.check()
    t.add(0.4)
    with pytest.raises(BudgetExhaustedError):
        t.check()
    now[0] += timedelta(minutes=2)  # 00:01 IST next day
    assert t.spent_today() == 0.0
    t.check()


async def test_generate_refuses_when_budget_exhausted():
    calls = []

    async def transport(*a):
        calls.append(a)
        return fake_response()

    llm = LLM(transport=transport, spend=SpendTracker(daily_budget_usd=0.0))
    with pytest.raises(BudgetExhaustedError):
        await llm.generate(config.FLASH, "hi")
    assert calls == []


async def test_generate_accounts_cost_and_ledger():
    async def transport(model, contents, cfg):
        return fake_response(prompt=1000, out=100)

    llm = LLM(transport=transport, spend=SpendTracker(daily_budget_usd=5.0))
    res = await llm.generate(config.FLASH, "hi", agent="commander")
    assert res.model_id == config.FLASH and res.fallback_from is None
    assert llm.spend.spent_today() == pytest.approx(res.usage.usd)
    assert llm.ledger[-1]["agent"] == "commander"
    assert llm.ledger[-1]["usd"] == pytest.approx(res.usage.usd, abs=1e-6)


# --- guards, retry, fallback -----------------------------------------------------------------
@pytest.mark.parametrize("model", ["gemini-2.5-flash", "gemini-flash-latest"])
async def test_unpinned_model_rejected(model):
    llm = LLM(transport=lambda *a: None)
    with pytest.raises(UnpinnedModelError):
        await llm.generate(model, "hi")


async def test_retries_retryable_errors_then_succeeds():
    attempts = []

    async def transport(model, contents, cfg):
        attempts.append(model)
        if len(attempts) < 3:
            raise APIErr(503)
        return fake_response()

    llm = LLM(transport=transport, sleep=no_sleep, spend=SpendTracker(5.0))
    res = await llm.generate(config.FLASH, "hi")
    assert len(attempts) == 3 and res.model_id == config.FLASH


async def test_non_retryable_error_raises_immediately():
    attempts = []

    async def transport(*a):
        attempts.append(1)
        raise APIErr(400)

    llm = LLM(transport=transport, sleep=no_sleep, spend=SpendTracker(5.0))
    with pytest.raises(APIErr):
        await llm.generate(config.FLASH, "hi")
    assert len(attempts) == 1


async def test_judge_falls_back_on_429():
    seen, fallbacks = [], []

    async def transport(model, contents, cfg):
        seen.append(model)
        if model == config.PRO_JUDGE:
            raise APIErr(429)
        return fake_response()

    llm = LLM(transport=transport, sleep=no_sleep, spend=SpendTracker(5.0))
    res = await llm.generate(
        config.PRO_JUDGE,
        "rank",
        fallback_model=config.FLASH,
        on_fallback=lambda a, b, r: fallbacks.append((a, b, r)),
    )
    assert seen == [config.PRO_JUDGE, config.FLASH]
    assert res.model_id == config.FLASH and res.fallback_from == config.PRO_JUDGE
    assert fallbacks == [(config.PRO_JUDGE, config.FLASH, "429")]


async def test_judge_falls_back_on_503():
    async def transport(model, contents, cfg):
        if model == config.PRO_JUDGE:
            raise APIErr(503)
        return fake_response()

    llm = LLM(transport=transport, sleep=no_sleep, spend=SpendTracker(5.0))
    res = await llm.generate(config.PRO_JUDGE, "rank", fallback_model=config.FLASH)
    assert res.fallback_from == config.PRO_JUDGE


async def test_judge_does_not_fall_back_on_400():
    async def transport(model, contents, cfg):
        raise APIErr(400)

    llm = LLM(transport=transport, sleep=no_sleep, spend=SpendTracker(5.0))
    with pytest.raises(APIErr):
        await llm.generate(config.PRO_JUDGE, "rank", fallback_model=config.FLASH)


def test_httpx_timeout_is_retryable():
    import httpx

    from agents.llm import is_retryable

    assert is_retryable(httpx.ReadTimeout("slow"))


async def test_judge_falls_back_on_timeout():
    async def transport(model, contents, cfg):
        if model == config.PRO_JUDGE:
            await asyncio.sleep(1)
        return fake_response()

    llm = LLM(transport=transport, sleep=no_sleep, spend=SpendTracker(5.0))
    res = await llm.generate(
        config.PRO_JUDGE, "rank", fallback_model=config.FLASH, primary_timeout_s=0.01
    )
    assert res.fallback_from == config.PRO_JUDGE


def test_residency_model_is_regional():
    assert config.location_for(config.RESIDENCY_FLASH) == "asia-south1"
    assert config.location_for(config.FLASH) == config.GEMINI_LOCATION


# --- record(), failed-call rows, per-run totals, shared default ------------------------------
def test_record_books_spend_ledger_and_run_totals():
    llm = LLM(spend=SpendTracker(5.0))
    u = Usage(config.FLASH, input_tokens=10_000, output_tokens=100, cached_tokens=8_000)
    row = llm.record(u, agent="judge", run_id="inv-1", latency_ms=12)
    assert row["usd"] == pytest.approx(u.usd, abs=1e-6) and row["outcome"] == "ok"
    assert llm.spend.spent_today() == pytest.approx(u.usd)
    rc = llm.run_cost("inv-1")
    m = rc.by_model[config.FLASH]
    assert (m.calls, m.input_tokens, m.cached_tokens) == (1, 10_000, 8_000)
    p = config.PRICES[config.FLASH]
    assert m.saved_usd == pytest.approx(8_000 * (p.input - p.cached_input) / 1e6)
    data = rc.to_cost_data()
    assert set(data) == {"input_tokens", "output_tokens", "cached_tokens", "usd", "by_model"}
    assert data["by_model"] == {config.FLASH: pytest.approx(u.usd, abs=1e-6)}


def test_record_failed_call_has_no_usd_and_no_spend():
    llm = LLM(spend=SpendTracker(5.0))
    row = llm.record(None, model_id=config.PRO_JUDGE, outcome="429", run_id="r")
    assert row["usd"] is None and row["outcome"] == "429"
    assert llm.spend.spent_today() == 0.0
    m = llm.run_cost("r").by_model[config.PRO_JUDGE]
    assert (m.calls, m.failed_calls) == (0, 1)


def test_record_needs_a_model():
    with pytest.raises(ValueError):
        LLM().record(None)


def test_record_usd_override_is_cost_not_a_call():
    llm = LLM(spend=SpendTracker(5.0))
    llm.record(None, model_id=config.FLASH, usd=0.01, run_id="r", event="cache_storage_estimate")
    m = llm.run_cost("r").by_model[config.FLASH]
    assert m.calls == 0 and m.usd == pytest.approx(0.01)
    assert llm.spend.spent_today() == pytest.approx(0.01)


async def test_generate_books_failed_call_row_then_raises():
    async def transport(*a):
        raise APIErr(400)

    llm = LLM(transport=transport, sleep=no_sleep, spend=SpendTracker(5.0))
    with pytest.raises(APIErr):
        await llm.generate(config.FLASH, "hi", agent="x", run_id="r")
    assert [(r["outcome"], r["usd"]) for r in llm.ledger] == [("error", None)]


async def test_fallback_books_primary_failure_and_fallback_success():
    async def transport(model, contents, cfg):
        if model == config.PRO_JUDGE:
            raise APIErr(429)
        return fake_response()

    llm = LLM(transport=transport, sleep=no_sleep, spend=SpendTracker(5.0))
    await llm.generate(config.PRO_JUDGE, "rank", fallback_model=config.FLASH, run_id="r")
    assert [(r["model_id"], r["outcome"]) for r in llm.ledger] == [
        (config.PRO_JUDGE, "429"),
        (config.FLASH, "ok"),
    ]
    assert llm.ledger[-1]["fallback_from"] == config.PRO_JUDGE
    rc = llm.run_cost("r")
    assert rc.fallbacks == [
        {"from_model": config.PRO_JUDGE, "to_model": config.FLASH, "reason": "429"}
    ]
    assert rc.by_model[config.PRO_JUDGE].failed_calls == 1


def test_run_costs_are_bounded_and_poppable(monkeypatch):
    import agents.llm as llm_mod

    monkeypatch.setattr(llm_mod, "MAX_TRACKED_RUNS", 2)
    llm = LLM()
    for r in ("a", "b", "c"):
        llm.run_cost(r)
    assert list(llm._runs) == ["b", "c"]
    assert llm.pop_run_cost("c") is not None and "c" not in llm._runs
    assert llm.pop_run_cost("missing").usd == 0.0


def test_shared_default_llm_is_one_instance():
    from agents.llm import get_llm, get_spend, set_default_llm

    mine = LLM(spend=SpendTracker(1.0))
    prev = set_default_llm(mine)
    try:
        assert get_llm() is mine and get_llm() is get_llm()
        assert get_spend() is mine.spend
    finally:
        set_default_llm(prev)


def test_cache_savings_usd_uses_the_cached_rate():
    from agents.llm import cache_savings_usd

    p = config.PRICES[config.FLASH]
    assert cache_savings_usd(config.FLASH, 60_000, 50_000) == pytest.approx(
        50_000 * (p.input - p.cached_input) / 1e6
    )
    assert cache_savings_usd(config.FLASH, 1_000, 0) == 0.0


@pytest.mark.parametrize(
    ("exc", "want"),
    [
        (APIErr(429), "429"),
        (APIErr(503), "5xx"),
        (TimeoutError(), "timeout"),
        (APIErr(400), "error"),
    ],
)
def test_classify_error(exc, want):
    from agents.llm import classify_error

    assert classify_error(exc) == want


async def test_client_is_per_event_loop(monkeypatch):
    """The aio client binds to its first loop, so a new loop must get a new client."""
    from google import genai

    made = []

    class FakeClient:
        def __init__(self, **kw):
            made.append(kw)

    monkeypatch.setattr(genai, "Client", FakeClient)
    llm = LLM()
    a = llm.client("global")
    assert llm.client("global") is a  # same loop -> reused
    assert made[0]["location"] == "global" and made[0]["vertexai"] is True

    async def in_loop():
        return llm.client("global")

    def other_loop():
        return asyncio.run(in_loop())

    b = await asyncio.to_thread(other_loop)
    assert b is not a and len(made) == 2
