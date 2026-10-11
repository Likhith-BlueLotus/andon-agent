"""Per-process runtime shared by the graph's agents: store, LLM gateway, CMMS, manuals cache and
one :class:`RunScope` per incident.

Why a scope: the ADK ``App`` is built once per store, but tools must be scoped to the incident that
is running (``scenario_id`` from the incident, never from the model). Session state carries
``andon_run`` (the scope key); tools, the verifier's ``ctx_factory`` and the judge resolve their
:class:`agents.tools.ToolContext` from it. The current scope is also published in a ``ContextVar``
so that the replay/record machinery (which only sees model requests) can find it.

Tool-call budgets (AGENTS_SPEC stop conditions) are enforced here (ADR-027), in three layers:

* ``before_tool_callback`` (:meth:`Runtime.budget_guard`): a call over budget is not executed and
  the model gets a structured ``budget_reached`` result instead;
* ``before_model_callback`` (:meth:`Runtime.tool_gate`): once an agent's budget is used up, its
  next model request carries no tools, so the model has to write its final output (live S009: the
  commander ignored 38 refusals in a row and burned ``max_llm_calls``);
* hard stop: an agent that still emits :data:`HARD_STOP_REFUSALS` calls after its tools were
  withdrawn has its turn ended (``skip_summarization`` on the refusal).

Replay mode: :class:`ReplayLlm` (ADK agents) and :class:`ReplayTransport` (``LLM.generate``)
replay a recording from ``tests/fixtures/llm/<scenario>/`` through the real graph and the real
tools, at $0. Record mode captures exactly those files from a live run.
"""

from __future__ import annotations

import asyncio
import contextvars
import inspect
import json
import logging
import os
import threading
import uuid
from collections import Counter
from collections.abc import AsyncGenerator, Callable
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# ADK 2.11 exposes these only via base_llm (re-exported from a private module); pin-checked by
# tests/test_graph.py through the replay run.
from google.adk.models.base_llm import BaseLlm, LlmCapabilities, gemini_output_schema_and_tools
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.adk.plugins.base_plugin import BasePlugin
from google.genai import types

import config
from agents.cache import CacheHandle, ManualsCache, shared_manuals_cache
from agents.cmms import CMMS, InMemoryCMMS
from agents.llm import LLM, get_llm
from agents.tools import ToolContext
from simulator.load import TelemetryStore

log = logging.getLogger("andon.runtime")

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "llm"
RUN_KEY = "andon_run"
EVENT_PREFIX = "andon_event:"  # state keys a tool writes to emit an SSE event (see events_map)
AGENT_MARK = "andon:agent:"  # state key prefix written by agent start/finish callbacks
# Per-run manuals cache lives for one diagnosis; deleted at the end (TTL only bounds a crash).
RUN_CACHE_TTL_S = 900

# Tool-call budgets per agent (AGENTS_SPEC §1-3, §6).
TOOL_BUDGETS: dict[str, int] = {
    "commander": 3,
    "signal_analyst": 12,
    "evidence_librarian": 8,
    "action_drafter": 2,
}

# Calls refused *after* the agent's tools were withdrawn that end the agent's turn (ADR-027).
HARD_STOP_REFUSALS = 3
TOOLS_WITHDRAWN_NOTE = (
    "Tool budget used up: answer now from the evidence you have. Do not call any tool."
)
# ADK's own structured-output tool (output_schema + tools on a model without native support):
# kept when tools are withdrawn, it is how such an agent returns its final answer.
_KEEP_TOOLS = frozenset({"set_model_response"})

Mode = str  # "live" | "replay" | "record"


class FixtureExhaustedError(RuntimeError):
    """Replay asked for more model responses than were recorded (the run diverged)."""


# =============================================================================================
# Record / replay
# =============================================================================================
@dataclass
class Recording:
    """Model responses of one run: ADK agents by agent name, ``LLM.generate`` by schema name."""

    adk: dict[str, list[dict]] = field(default_factory=dict)
    generate: dict[str, list[dict]] = field(default_factory=dict)
    meta: dict[str, Any] = field(default_factory=dict)
    _pos: Counter[str] = field(default_factory=Counter, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    # ---- replay --------------------------------------------------------------------------
    def next(self, kind: str, key: str) -> dict:
        book = self.adk if kind == "adk" else self.generate
        with self._lock:
            items = book.get(key, [])
            i = self._pos[f"{kind}:{key}"]
            if i >= len(items):
                raise FixtureExhaustedError(
                    f"replay has no {kind} response #{i + 1} for {key!r} ({len(items)} recorded)"
                )
            self._pos[f"{kind}:{key}"] += 1
            return items[i]

    # ---- record --------------------------------------------------------------------------
    def add(self, kind: str, key: str, item: dict) -> None:
        book = self.adk if kind == "adk" else self.generate
        with self._lock:
            book.setdefault(key, []).append(item)

    def save(self, out: Path) -> None:
        out.mkdir(parents=True, exist_ok=True)
        for agent, items in self.adk.items():
            _dump(out / f"adk_{agent}.json", items)
        for schema, items in self.generate.items():
            _dump(out / f"generate_{schema}.json", items)
        _dump(out / "meta.json", self.meta)

    @classmethod
    def load(cls, path: Path) -> Recording:
        if not path.is_dir():
            raise FileNotFoundError(f"no LLM fixtures at {path}")
        rec = cls()
        for f in sorted(path.glob("adk_*.json")):
            rec.adk[f.stem[len("adk_") :]] = json.loads(f.read_text(encoding="utf-8"))
        for f in sorted(path.glob("generate_*.json")):
            rec.generate[f.stem[len("generate_") :]] = json.loads(f.read_text(encoding="utf-8"))
        meta = path / "meta.json"
        rec.meta = json.loads(meta.read_text(encoding="utf-8")) if meta.exists() else {}
        return rec


def _dump(path: Path, obj: Any) -> None:
    path.write_text(json.dumps(obj, indent=1, ensure_ascii=False, sort_keys=True) + "\n", "utf-8")


def _strip_ids(d: dict) -> dict:
    """Function-call ids are assigned per run by ADK; recordings must not pin them."""
    for part in (d.get("content") or {}).get("parts") or []:
        for k in ("function_call", "function_response"):
            if isinstance(part.get(k), dict):
                part[k].pop("id", None)
    return d


class ReplayLlm(BaseLlm):
    """ADK model that replays the current run's recording for one agent."""

    agent: str = ""

    @classmethod
    def supported_models(cls) -> list[str]:
        return [r"gemini-.*"]

    @property
    def capabilities(self) -> LlmCapabilities:
        # Declare what the live Gemini model reports for the same id, so a replay takes the same
        # output_schema + tools path as the recorded run (and ADK's name-based fallback, which
        # warns and is being removed, is never used).
        return LlmCapabilities(output_schema_and_tools=gemini_output_schema_and_tools(self.model))

    async def generate_content_async(
        self, llm_request: LlmRequest, stream: bool = False
    ) -> AsyncGenerator[LlmResponse, None]:
        scope = current_scope()
        if scope.recording is None:
            raise FixtureExhaustedError("replay mode without a recording")
        item = scope.recording.next("adk", self.agent)
        resp = LlmResponse.model_validate(item)
        resp.partial = False
        yield resp


class ReplayTransport:
    """``agents.llm.Transport`` replaying ``LLM.generate`` responses keyed by response schema."""

    async def __call__(self, model_id: str, contents: Any, gen_config: Any) -> Any:
        scope = current_scope()
        if scope.recording is None:
            raise FixtureExhaustedError("replay mode without a recording")
        item = scope.recording.next("generate", schema_key(gen_config))
        return types.GenerateContentResponse.model_validate(item["response"])


class RecordingTransport:
    """Wraps the real transport and records each response into the current run's recording."""

    def __init__(self, llm: LLM) -> None:
        self._llm = llm

    async def __call__(self, model_id: str, contents: Any, gen_config: Any) -> Any:
        resp = await self._llm._genai_transport(model_id, contents, gen_config)
        scope = _SCOPE.get(None)
        if scope is not None and scope.recording is not None:
            scope.recording.add(
                "generate",
                schema_key(gen_config),
                {"model_id": model_id, "response": resp.model_dump(mode="json", exclude_none=True)},
            )
        return resp


def schema_key(gen_config: Any) -> str:
    schema = getattr(gen_config, "response_schema", None)
    return getattr(schema, "__name__", None) or "text"


class RecorderPlugin(BasePlugin):
    """Records every final ADK model response per agent (record mode only)."""

    def __init__(self) -> None:
        super().__init__(name="andon_recorder")

    async def after_model_callback(
        self, *, callback_context: Any, llm_response: LlmResponse
    ) -> LlmResponse | None:
        if llm_response.partial:
            return None
        scope = _SCOPE.get(None)
        if scope is not None and scope.recording is not None:
            d = llm_response.model_dump(mode="json", exclude_none=True)
            scope.recording.add("adk", callback_context.agent_name, _strip_ids(d))
        return None


# =============================================================================================
# Run scope
# =============================================================================================
@dataclass
class RunScope:
    key: str
    incident_id: str
    scenario_id: str
    ctx: ToolContext
    force_bad_claim: bool = False
    recording: Recording | None = None
    tool_calls: Counter[str] = field(default_factory=Counter)
    tools_withdrawn: Counter[str] = field(default_factory=Counter)  # model calls made without tools
    ignored_refusals: Counter[str] = field(default_factory=Counter)  # refusals after withdrawal
    exit_stack: AsyncExitStack = field(default_factory=AsyncExitStack)
    manuals: CacheHandle | None = None
    manuals_failed: bool = False
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)
    _count_lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _agent_locks: dict[str, asyncio.Lock] = field(default_factory=dict, repr=False)

    def agent_lock(self, agent: str) -> asyncio.Lock:
        """FIFO lock per agent: parallel calls of one model turn run one at a time, in the order
        ADK dispatched them, so evidence ids are deterministic (replays depend on it)."""
        lk = self._agent_locks.get(agent)
        if lk is None:
            lk = self._agent_locks[agent] = asyncio.Lock()
        return lk

    def count_tool(self, agent: str) -> int:
        with self._count_lock:
            self.tool_calls[agent] += 1
            return self.tool_calls[agent]

    def used(self, agent: str) -> int:
        """Tool calls the agent has made (or attempted) so far, refusals included."""
        with self._count_lock:
            return self.tool_calls[agent]


_SCOPE: contextvars.ContextVar[RunScope] = contextvars.ContextVar("andon_scope")


def current_scope() -> RunScope:
    try:
        return _SCOPE.get()
    except LookupError:
        raise RuntimeError("no active Andon run scope (use events_map.run_incident)") from None


class _ScopedTools:
    """Duck-typed stand-in for a ToolContext in ``agents.tools.bind_tools``: each call resolves
    the incident's ToolContext from session state, so scoping never depends on model input."""

    def __init__(self, rt: Runtime) -> None:
        self._rt = rt

    def with_state(self, state: Any) -> ToolContext:
        return self._rt.ctx_factory(state)


@dataclass
class Runtime:
    store: TelemetryStore
    mode: Mode = "live"
    llm: LLM = field(default_factory=get_llm)
    cmms: CMMS = field(default_factory=InMemoryCMMS)
    judge_model: str = config.JUDGE_MODEL
    fixture_root: Path = FIXTURE_ROOT
    manuals_cache: ManualsCache | None = None
    scopes: dict[str, RunScope] = field(default_factory=dict)
    _store_lock: Any = field(default_factory=threading.RLock, repr=False)

    def __post_init__(self) -> None:
        if self.mode not in ("live", "replay", "record"):
            raise ValueError(f"mode must be live|replay|record, got {self.mode!r}")
        if self.judge_model not in config.PINNED_MODELS:
            raise ValueError(f"judge model {self.judge_model!r} is not pinned")
        if self.mode == "replay":
            # Replays book recorded usage to their own ledger, never to today's real spend.
            self.llm = LLM(transport=ReplayTransport())
        elif self.mode == "record":
            base = get_llm()
            rec = LLM(spend=base.spend, credentials=base.credentials)
            rec.transport = RecordingTransport(rec)
            self.llm = rec
        if self.manuals_cache is None and self.mode != "replay":
            self.manuals_cache = shared_manuals_cache(self.llm, RUN_CACHE_TTL_S)

    # ---- models ------------------------------------------------------------------------
    def model_id(self, default: str) -> str:
        """Residency mode moves every agent to the regional model (pitch only)."""
        return config.RESIDENCY_FLASH if config.RESIDENCY_MODE else default

    def adk_model(self, agent: str, model_id: str, thinking: str) -> Any:
        from agents.adk_budget import make_model

        mid = self.model_id(model_id)
        # Same output_schema handling as live (ADK reads this from the environment).
        os.environ.setdefault("GOOGLE_GENAI_USE_ENTERPRISE", "true")
        if self.mode == "replay":
            return ReplayLlm(model=mid, agent=agent)
        return make_model(mid, thinking)

    # ---- scopes ------------------------------------------------------------------------
    def open_scope(
        self, incident_id: str, scenario_id: str, *, force_bad_claim: bool = False
    ) -> RunScope:
        key = f"run_{uuid.uuid4().hex[:12]}"
        recording = None
        if self.mode == "replay":
            recording = Recording.load(self.fixture_root / scenario_id)
            force_bad_claim = force_bad_claim or bool(recording.meta.get("force_bad_claim"))
        elif self.mode == "record":
            recording = Recording(
                meta={
                    "scenario_id": scenario_id,
                    "recorded_at": datetime.now(UTC).isoformat(timespec="seconds"),
                    "force_bad_claim": force_bad_claim,
                    "judge_model": self.judge_model,
                }
            )
        scope = RunScope(
            key=key,
            incident_id=incident_id,
            scenario_id=scenario_id,
            # one lock per store: sync tools run in ADK's thread pool, and a DuckDB connection
            # must not run two queries at once (also across concurrent incidents)
            ctx=ToolContext(
                store=self.store, scenario_id=scenario_id, _lock=self._store_lock, llm=self.llm
            ),
            force_bad_claim=force_bad_claim,
            recording=recording,
        )
        self.scopes[key] = scope
        return scope

    def activate(self, scope: RunScope) -> contextvars.Token:
        return _SCOPE.set(scope)

    async def close_scope(self, scope: RunScope) -> None:
        try:
            await scope.exit_stack.aclose()  # deletes the per-run manuals cache
        finally:
            self.scopes.pop(scope.key, None)

    def scope_for(self, state: Any) -> RunScope:
        key = state.get(RUN_KEY) if hasattr(state, "get") else None
        if key is None or key not in self.scopes:
            raise RuntimeError("session state has no active andon_run scope")
        return self.scopes[key]

    def ctx_factory(self, state: Any) -> ToolContext:
        """The incident's ToolContext writing evidence to ``state`` (verifier ``ctx_factory``)."""
        return self.scope_for(state).ctx.with_state(state)

    def scoped_tools(self) -> _ScopedTools:
        return _ScopedTools(self)

    # ---- manuals cache -----------------------------------------------------------------
    async def manuals_handle(
        self, scope: RunScope, system_instruction: str, run_id: str | None
    ) -> CacheHandle | None:
        """The run's manuals cache, created lazily on the first ``cite_manual`` call.

        None in replay mode, or if creating it failed (the caller then sends the manuals inline).
        """
        if self.manuals_cache is None or scope.manuals_failed:
            return None
        async with scope._lock:
            if scope.manuals is None and not scope.manuals_failed:
                try:
                    scope.manuals = await scope.exit_stack.enter_async_context(
                        self.manuals_cache.session(
                            config.FLASH,
                            system_instruction=system_instruction,
                            run_id=run_id,
                        )
                    )
                except Exception as exc:
                    from agents.llm import BudgetExhaustedError

                    if isinstance(exc, BudgetExhaustedError):
                        raise
                    log.warning("manuals cache unavailable (%r); sending manuals inline", exc)
                    scope.manuals_failed = True
            return scope.manuals

    # ---- tool execution ----------------------------------------------------------------
    def offload(self, agent: str, fn: Callable[..., dict]) -> Callable[..., Any]:
        """An ``async`` twin of a sync ADK tool function (same name, docstring and explicit
        parameters, which ADK introspects) that runs it in a worker thread under the agent's
        FIFO lock. Slow tools (DuckDB, spectrum, listen) then never block the event loop, so the
        other ParallelAgent branch keeps working."""
        sig = inspect.signature(fn)
        ns: dict[str, Any] = {}
        params = []
        for i, (name, p) in enumerate(sig.parameters.items()):
            ns[f"_a{i}"] = p.annotation
            default = ""
            if p.default is not inspect.Parameter.empty:
                ns[f"_d{i}"] = p.default
                default = f" = _d{i}"
            params.append(f"{name}: _a{i}{default}")
        names = list(sig.parameters)
        rt = self

        async def _call(kwargs: dict[str, Any]) -> dict:
            tc = kwargs.get("tool_context")
            try:
                lock = rt.scope_for(tc.state).agent_lock(agent)
            except (RuntimeError, AttributeError):
                return await asyncio.to_thread(fn, **kwargs)
            async with lock:
                return await asyncio.to_thread(fn, **kwargs)

        ns["_call"] = _call
        body = ", ".join(f"{n!r}: {n}" for n in names)
        src = f"async def {fn.__name__}({', '.join(params)}) -> dict:\n    return await _call({{{body}}})\n"
        exec(compile(src, f"<offload {fn.__name__}>", "exec"), ns)  # fixed template, no input
        g = ns[fn.__name__]
        g.__doc__ = fn.__doc__
        g.__module__ = fn.__module__
        return g

    # ---- tool budgets ------------------------------------------------------------------
    def budget_guard(self, agent: str, limit: int | None = None) -> Callable[..., dict | None]:
        """``before_tool_callback`` that refuses calls over the agent's budget."""
        cap = limit if limit is not None else TOOL_BUDGETS[agent]

        def before_tool(tool: Any, args: dict[str, Any], tool_context: Any) -> dict | None:
            try:
                scope = self.scope_for(tool_context.state)
            except RuntimeError:
                return {"evidence_id": None, "error": {"code": "no_scope", "message": "no run"}}
            n = scope.count_tool(agent)
            if n > cap:
                if scope.tools_withdrawn[agent]:
                    # the model was asked without tools and still called one: count towards the
                    # hard stop. Refusals in the turn that overshot (parallel calls) do not.
                    scope.ignored_refusals[agent] += 1
                    if scope.ignored_refusals[agent] >= HARD_STOP_REFUSALS:
                        log.warning(
                            "%s ignored %d budget refusals with tools withdrawn; ending its turn",
                            agent,
                            scope.ignored_refusals[agent],
                        )
                        # a skip_summarization function response is a final response: ADK's
                        # flow loop ends this agent's turn instead of calling the model again
                        tool_context.actions.skip_summarization = True
                return {
                    "evidence_id": None,
                    "error": {
                        "code": "budget_reached",
                        "message": f"{agent} tool budget of {cap} calls is used up",
                        "hint": "stop calling tools and write your report from the evidence you have",
                    },
                }
            return None

        return before_tool

    def tool_gate(
        self, agent: str, output_schema: Any = None, limit: int | None = None
    ) -> Callable[..., None]:
        """``before_model_callback``: once ``agent`` has used its tool budget, send the request
        without tools (``config.tools`` and ``tool_config`` cleared, ADK's ``set_model_response``
        kept) plus :data:`TOOLS_WITHDRAWN_NOTE`, so the model must produce its final output.

        ``output_schema`` (the agent's) is set on the request if ADK had not set it natively, so a
        structured agent (the commander's plan) still answers in its schema. ``tools_dict`` is left
        alone: a stray call the model emits anyway is answered by :meth:`budget_guard`.
        """
        cap = limit if limit is not None else TOOL_BUDGETS[agent]

        def before_model(callback_context: Any, llm_request: LlmRequest) -> None:
            try:
                scope = self.scope_for(callback_context.state)
            except RuntimeError:
                return None
            if scope.used(agent) < cap:
                return None
            withdraw_tools(llm_request, output_schema)
            scope.tools_withdrawn[agent] += 1
            log.info("%s tool budget %d used up; model call without tools", agent, cap)
            return None

        return before_model


def withdraw_tools(llm_request: LlmRequest, output_schema: Any = None) -> None:
    """Remove every callable tool from ``llm_request`` (in place) and add the answer-now note."""
    cfg = llm_request.config
    kept: list[types.Tool] = []
    for tool in cfg.tools or []:
        decls = [
            d for d in (getattr(tool, "function_declarations", None) or []) if d.name in _KEEP_TOOLS
        ]
        if decls:
            kept.append(types.Tool(function_declarations=decls))
    cfg.tools = kept or None
    cfg.tool_config = None
    if output_schema is not None and not kept and cfg.response_schema is None:
        llm_request.set_output_schema(output_schema)
    llm_request.append_instructions([TOOLS_WITHDRAWN_NOTE])


def agent_marks() -> tuple[Callable[..., None], Callable[..., None]]:
    """``before_agent_callback`` / ``after_agent_callback`` that write an ``andon:agent:<name>``
    state key, which makes ADK emit a state-only event the event mapper turns into
    ``agent_started`` / ``agent_finished`` (works inside ParallelAgent branches)."""

    def started(callback_context: Any) -> None:
        callback_context.state[AGENT_MARK + callback_context.agent_name] = "started"

    def finished(callback_context: Any) -> None:
        callback_context.state[AGENT_MARK + callback_context.agent_name] = "finished"

    return started, finished
