"""Offline tests for agents/adk_budget.py: the ADK budget plugin, model factory and error mapping.

Unit tests drive the callbacks with real ``LlmRequest``/``LlmResponse`` objects and a fake callback
context; the integration tests run a real ADK ``Runner`` + ``App(plugins=[...])`` against a fake
``BaseLlm`` (no network) in SSE mode, which is how the API runs the graph.
"""

from __future__ import annotations

import warnings
from collections.abc import AsyncGenerator
from types import SimpleNamespace

import pytest
from google.adk.agents import LlmAgent, RunConfig
from google.adk.agents.run_config import StreamingMode
from google.adk.apps import App
from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

import config
from agents.adk_budget import (
    AndonBudgetPlugin,
    ModelPolicyError,
    PinnedGemini,
    make_model,
    normalise_model_id,
    run_error,
)
from agents.llm import LLM, BudgetExhaustedError, SpendTracker, UnpinnedModelError


def usage(prompt=1000, out=100, cached=0, thoughts=0):
    return types.GenerateContentResponseUsageMetadata(
        prompt_token_count=prompt,
        candidates_token_count=out,
        cached_content_token_count=cached,
        thoughts_token_count=thoughts,
    )


def ctx(agent="signal_analyst", inv="inv-1"):
    return SimpleNamespace(agent_name=agent, invocation_id=inv, actions=object())


def req(model=config.FLASH, **cfg):
    return LlmRequest(model=model, config=types.GenerateContentConfig(**cfg))


def resp(partial=None, um=None):
    return LlmResponse(
        content=types.Content(role="model", parts=[types.Part(text="ok")]),
        partial=partial,
        usage_metadata=um,
    )


class APIErr(Exception):
    def __init__(self, code):
        super().__init__(f"HTTP {code}")
        self.code = code


@pytest.fixture
def llm():
    return LLM(spend=SpendTracker(daily_budget_usd=5.0))


@pytest.fixture
def plugin(llm):
    return AndonBudgetPlugin(llm=llm)


# --- before_model ----------------------------------------------------------------------------
@pytest.mark.parametrize("model", ["gemini-2.5-flash", "gemini-flash-latest", ""])
async def test_before_model_rejects_unpinned(plugin, model):
    with pytest.raises(UnpinnedModelError):
        await plugin.before_model_callback(callback_context=ctx(), llm_request=req(model))


@pytest.mark.parametrize("knob", [{"temperature": 0.2}, {"top_p": 0.9}, {"top_k": 5}])
async def test_before_model_rejects_sampling_knobs(plugin, knob):
    with pytest.raises(ModelPolicyError):
        await plugin.before_model_callback(callback_context=ctx(), llm_request=req(**knob))


async def test_before_model_enforces_kill_switch():
    p = AndonBudgetPlugin(llm=LLM(spend=SpendTracker(daily_budget_usd=0.0)))
    with pytest.raises(BudgetExhaustedError):
        await p.before_model_callback(callback_context=ctx(), llm_request=req())


async def test_before_model_accepts_full_resource_name(plugin):
    name = f"projects/p/locations/global/publishers/google/models/{config.FLASH}"
    assert normalise_model_id(name) == config.FLASH
    assert await plugin.before_model_callback(callback_context=ctx(), llm_request=req(name)) is None


# --- after_model -----------------------------------------------------------------------------
async def test_partials_are_not_booked_final_is_booked_once(plugin, llm):
    c, r = ctx(), req()
    await plugin.before_model_callback(callback_context=c, llm_request=r)
    for _ in range(3):  # SSE chunks also carry usage_metadata
        await plugin.after_model_callback(
            callback_context=c, llm_response=resp(partial=True, um=usage())
        )
    assert llm.ledger == []
    await plugin.after_model_callback(callback_context=c, llm_response=resp(False, usage()))
    await plugin.after_model_callback(callback_context=c, llm_response=resp(False, usage()))
    assert len(llm.ledger) == 1
    row = llm.ledger[0]
    assert (row["model_id"], row["agent"], row["run_id"]) == (
        config.FLASH,
        "signal_analyst",
        "inv-1",
    )
    assert row["input_tokens"] == 1000 and row["usd"] > 0
    assert llm.spend.spent_today() == pytest.approx(row["usd"], abs=1e-6)


async def test_second_final_response_books_only_the_increase(plugin, llm):
    c = ctx()
    await plugin.before_model_callback(callback_context=c, llm_request=req())
    await plugin.after_model_callback(callback_context=c, llm_response=resp(None, usage(1000, 10)))
    await plugin.after_model_callback(callback_context=c, llm_response=resp(None, usage(1000, 50)))
    assert [(r["input_tokens"], r["output_tokens"]) for r in llm.ledger] == [(1000, 10), (0, 40)]
    m = llm.run_cost("inv-1").by_model[config.FLASH]
    assert (m.input_tokens, m.output_tokens) == (1000, 50)


async def test_response_without_usage_is_ignored(plugin, llm):
    c = ctx()
    await plugin.before_model_callback(callback_context=c, llm_request=req())
    await plugin.after_model_callback(callback_context=c, llm_response=resp(None, None))
    assert llm.ledger == []


async def test_fallback_model_rewrite_is_booked_under_the_model_used(plugin, llm):
    """ADK's FallbackModel rewrites llm_request.model to the delegate that answered."""
    c, r = ctx("rca_judge"), req(config.PRO_JUDGE)
    await plugin.before_model_callback(callback_context=c, llm_request=r)
    r.model = config.FLASH
    await plugin.after_model_callback(callback_context=c, llm_response=resp(None, usage()))
    row = llm.ledger[-1]
    assert (row["model_id"], row["fallback_from"]) == (config.FLASH, config.PRO_JUDGE)
    assert llm.run_cost("inv-1").fallbacks[0]["to_model"] == config.FLASH


async def test_cached_tokens_show_up_as_savings(plugin, llm):
    c = ctx()
    await plugin.before_model_callback(callback_context=c, llm_request=req())
    await plugin.after_model_callback(
        callback_context=c, llm_response=resp(None, usage(60_000, 100, cached=50_000))
    )
    rc = llm.run_cost("inv-1")
    assert rc.saved_usd > 0 and rc.to_cost_data()["cached_tokens"] == 50_000


async def test_untracked_response_falls_back_to_model_version(plugin, llm):
    r = resp(None, usage())
    r.model_version = config.FLASH_LITE
    await plugin.after_model_callback(callback_context=ctx(), llm_response=r)
    assert llm.ledger[-1]["model_id"] == config.FLASH_LITE


# --- on_model_error / after_run --------------------------------------------------------------
@pytest.mark.parametrize(("err", "outcome"), [(APIErr(429), "429"), (APIErr(503), "5xx")])
async def test_model_error_books_failed_row_and_propagates(plugin, llm, err, outcome):
    c, r = ctx(), req()
    await plugin.before_model_callback(callback_context=c, llm_request=r)
    out = await plugin.on_model_error_callback(callback_context=c, llm_request=r, error=err)
    assert out is None  # ADK re-raises
    assert (llm.ledger[-1]["outcome"], llm.ledger[-1]["usd"]) == (outcome, None)
    assert llm.spend.spent_today() == 0.0
    assert plugin._inflight == {}


async def test_after_run_drops_inflight_calls_of_that_run(plugin):
    a, b = ctx(inv="a"), ctx(inv="b")
    await plugin.before_model_callback(callback_context=a, llm_request=req())
    await plugin.before_model_callback(callback_context=b, llm_request=req())
    await plugin.after_run_callback(invocation_context=SimpleNamespace(invocation_id="a"))
    assert [c.run_id for c in plugin._inflight.values()] == ["b"]


# --- run_error -------------------------------------------------------------------------------
def _wrapped(e):
    try:
        try:
            raise e
        except Exception as inner:
            raise RuntimeError("Error in plugin 'andon_budget'") from inner
    except RuntimeError as outer:
        return outer


def test_run_error_codes():
    assert run_error(_wrapped(BudgetExhaustedError("x")))["code"] == "budget_exhausted"
    assert run_error(_wrapped(UnpinnedModelError("x")))["code"] == "internal"
    assert run_error(APIErr(429)) == {
        "code": "model_unavailable",
        "message": "HTTP 429",
        "retryable": True,
    }
    assert run_error(TimeoutError())["code"] == "model_timeout"
    assert run_error(ValueError("boom"))["retryable"] is False


# --- make_model ------------------------------------------------------------------------------
def test_make_model_location_and_retry():
    m = make_model(config.FLASH, "LOW")
    assert isinstance(m, PinnedGemini) and m.model == config.FLASH
    assert m.client_kwargs["location"] == config.GEMINI_LOCATION
    assert m.client_kwargs["vertexai"] is True
    assert m.retry_options.attempts == config.LLM_MAX_RETRIES + 1
    assert set(m.retry_options.http_status_codes) == set(config.RETRYABLE_HTTP_CODES)
    assert make_model(config.RESIDENCY_FLASH).client_kwargs["location"] == "asia-south1"
    assert make_model(config.PRO_JUDGE, "HIGH", retries=0).retry_options.attempts == 1


def test_make_model_guards():
    with pytest.raises(UnpinnedModelError):
        make_model("gemini-2.5-pro")
    with pytest.raises(ModelPolicyError):
        make_model(config.FLASH, "EXTREME")


class _FakeModels:
    def __init__(self):
        self.seen = []

    async def generate_content(self, *, model, contents, config):
        self.seen.append((model, config))
        return types.GenerateContentResponse(
            candidates=[
                types.Candidate(
                    content=types.Content(role="model", parts=[types.Part(text="hi")]),
                    finish_reason=types.FinishReason.STOP,
                )
            ],
            usage_metadata=usage(5, 1),
        )


async def test_pinned_gemini_adds_thinking_level_and_timeout():
    fm = _FakeModels()
    m = make_model(config.FLASH, "MEDIUM", timeout_s=30)
    m.client = SimpleNamespace(vertexai=True, aio=SimpleNamespace(models=fm))
    r = LlmRequest(
        model=m.model, contents=[types.Content(role="user", parts=[types.Part(text="x")])]
    )
    out = [x async for x in m.generate_content_async(r)]
    model, cfg = fm.seen[0]
    assert model == config.FLASH and out[0].usage_metadata.prompt_token_count == 5
    assert cfg.thinking_config.thinking_level == types.ThinkingLevel.MEDIUM
    assert cfg.http_options.timeout == 30_000


async def test_pinned_gemini_keeps_agent_thinking_config():
    fm = _FakeModels()
    m = make_model(config.FLASH, "LOW")
    m.client = SimpleNamespace(vertexai=True, aio=SimpleNamespace(models=fm))
    r = LlmRequest(
        model=m.model,
        contents=[types.Content(role="user", parts=[types.Part(text="x")])],
        config=types.GenerateContentConfig(
            thinking_config=types.ThinkingConfig(thinking_level=types.ThinkingLevel.HIGH)
        ),
    )
    _ = [x async for x in m.generate_content_async(r)]
    assert fm.seen[0][1].thinking_config.thinking_level == types.ThinkingLevel.HIGH


# --- integration: real Runner + App(plugins) + fake model, SSE --------------------------------
class FakeStreamingLlm(BaseLlm):
    """Streams two usage-carrying partial chunks, then the aggregated final response."""

    model: str = config.FLASH

    @classmethod
    def supported_models(cls) -> list[str]:
        return [r"gemini-.*"]

    async def generate_content_async(
        self, llm_request: LlmRequest, stream: bool = False
    ) -> AsyncGenerator[LlmResponse, None]:
        if stream:
            for _ in range(2):
                yield LlmResponse(
                    content=types.Content(role="model", parts=[types.Part(text="pa")]),
                    partial=True,
                    usage_metadata=usage(2000, 5),
                )
        yield LlmResponse(
            content=types.Content(role="model", parts=[types.Part(text="final")]),
            partial=False,
            usage_metadata=usage(2000, 20, thoughts=30),
            finish_reason=types.FinishReason.STOP,
        )


def _runner(plugin, n_agents=2, model=None):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        from google.adk.agents import SequentialAgent

        agents = [
            LlmAgent(name=f"a{i}", model=model or FakeStreamingLlm(), output_key=f"out{i}")
            for i in range(n_agents)
        ]
        root = SequentialAgent(name="andon_root", sub_agents=agents)
    app = App(name="andon", root_agent=root, plugins=[plugin])
    svc = InMemorySessionService()
    return Runner(app=app, session_service=svc), svc


async def _run(runner, svc, max_llm_calls=40):
    s = await svc.create_session(app_name="andon", user_id="u")
    events = []
    msg = types.Content(role="user", parts=[types.Part(text="investigate")])
    rc = RunConfig(streaming_mode=StreamingMode.SSE, max_llm_calls=max_llm_calls)
    async for ev in runner.run_async(user_id="u", session_id=s.id, new_message=msg, run_config=rc):
        events.append(ev)
    return events


async def test_runner_books_each_streamed_call_once(plugin, llm):
    runner, svc = _runner(plugin)
    events = await _run(runner, svc)
    assert any(e.partial for e in events)  # streaming really happened
    assert [r["agent"] for r in llm.ledger] == ["a0", "a1"]
    inv = events[0].invocation_id
    data = plugin.run_cost(inv).to_cost_data()
    assert data["input_tokens"] == 4000 and data["output_tokens"] == 2 * (20 + 30)
    assert data["usd"] == pytest.approx(llm.spend.spent_today(), abs=1e-6)
    assert plugin._inflight == {}


async def test_runner_stops_when_budget_is_exhausted():
    llm = LLM(spend=SpendTracker(daily_budget_usd=0.0))
    runner, svc = _runner(AndonBudgetPlugin(llm=llm))
    with pytest.raises(Exception) as ei:  # ADK wraps it in RuntimeError
        await _run(runner, svc)
    assert run_error(ei.value)["code"] == "budget_exhausted"
    assert llm.ledger == []


async def test_runner_rejects_unpinned_model(plugin):
    class Unpinned(FakeStreamingLlm):
        model: str = "gemini-2.5-flash"

    runner, svc = _runner(plugin, n_agents=1, model=Unpinned())
    with pytest.raises(Exception) as ei:
        await _run(runner, svc)
    assert any(isinstance(e, UnpinnedModelError) for e in _causes(ei.value))


async def test_runner_max_llm_calls_maps_to_error_code(plugin):
    runner, svc = _runner(plugin, n_agents=2)
    with pytest.raises(Exception) as ei:
        await _run(runner, svc, max_llm_calls=1)
    assert run_error(ei.value)["code"] == "llm_call_limit"


def _causes(e):
    out = []
    while e is not None and e not in out:
        out.append(e)
        e = e.__cause__ or e.__context__
    return out
