"""The ADK graph (AGENTS_SPEC "Graph"):

    andon_root = SequentialAgent([
        commander,                                            # LlmAgent, Flash MEDIUM, plan
        ParallelAgent("evidence", [signal_analyst, evidence_librarian]),
        LoopAgent("rca_loop", [rca_judge, verifier], max_iterations=3),
        action_drafter,                                       # LlmAgent, Flash LOW, the write
    ])
    App(name="andon", root_agent=andon_root, plugins=[AndonBudgetPlugin(...)])

:func:`build_app` builds it once per store; :func:`agents.events_map.run_incident` runs one
incident on it and yields ``api/events.py`` events. Tools are scoped per run through
``agents.runtime`` (the scenario comes from the incident, never from the model), and tool-call
budgets are enforced by ``before_tool_callback`` (refuse) plus ``before_model_callback`` (no tools
once the budget is used up) on every tool-using agent (ADR-027).
"""

from __future__ import annotations

import json
import warnings
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from google.adk.agents import LlmAgent, RunConfig
from google.adk.agents.run_config import StreamingMode
from google.adk.apps import App
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from pydantic import BaseModel, Field

import config
from agents import prompts
from agents import tools as T
from agents.adk_budget import AndonBudgetPlugin
from agents.cmms import CMMS, InMemoryCMMS
from agents.drafter import AGENT as DRAFTER
from agents.drafter import build_drafter
from agents.judge import AGENT as JUDGE
from agents.judge import build_judge
from agents.librarian import AGENT as LIBRARIAN
from agents.librarian import build_librarian
from agents.llm import LLM
from agents.runtime import RecorderPlugin, Runtime, agent_marks
from agents.untrusted import NOTICE
from simulator import plant
from simulator.load import TelemetryStore

APP_NAME = "andon"
COMMANDER = "commander"
ANALYST = "signal_analyst"
VERIFIER = "verifier"


class PlanOut(BaseModel):
    """Commander output (``state["plan"]``)."""

    steps: list[str] = Field(min_length=4, max_length=8)
    upstream_step: int = Field(description="index of a check on an upstream station or utility")
    sensor_step: int = Field(description="index of the 'is it a sensor/data problem?' check")
    suspects: list[str] = Field(default_factory=list, max_length=4, description="asset ids")


# --- instruction providers -------------------------------------------------------------------
def asset_catalogue() -> str:
    """Compact, static line catalogue (asset ids, types, flow, tags with normal ranges)."""
    lines = []
    for a in plant.ASSETS:
        where = f"position {a.position}" if a.position is not None else "utility"
        feeds = f", feeds {', '.join(a.feeds)}" if a.feeds else ""
        tags = "; ".join(
            f"{t.tag} [{t.unit}, normal {t.normal_lo:g}-{t.normal_hi:g}]" for t in a.tags
        )
        lines.append(f"- {a.asset_id} ({a.asset_type}, {where}{feeds}, manual {a.manual}): {tags}")
    return "Line L1 assets in flow order (utilities last):\n" + "\n".join(lines)


def _stop(state: Any) -> str:
    return "Stop record: " + json.dumps(state.get("stop_event") or {}, ensure_ascii=False)


def _plan(state: Any) -> str:
    plan = state.get("plan") or {}
    steps = "\n".join(f"{i}. {s}" for i, s in enumerate(plan.get("steps", [])))
    return f"Plan:\n{steps}\nSuspects: {plan.get('suspects', [])}"


def commander_instruction(ctx: Any) -> str:
    return "\n\n".join([prompts.text("commander"), prompts.GROUND_RULES, _stop(ctx.state)])


def analyst_instruction(ctx: Any) -> str:
    return "\n\n".join(
        [
            prompts.text("signal_analyst"),
            prompts.GROUND_RULES,
            _stop(ctx.state),
            _plan(ctx.state),
            asset_catalogue(),
        ]
    )


def librarian_instruction(ctx: Any) -> str:
    return "\n\n".join(
        [
            prompts.text("librarian"),
            prompts.GROUND_RULES,
            NOTICE,
            _stop(ctx.state),
            _plan(ctx.state),
        ]
    )


# --- agents ----------------------------------------------------------------------------------
def _bound(rt: Runtime, agent: str, names: tuple[str, ...]) -> list[Any]:
    """The agent's registry tools, scoped per run and run off the event loop in call order."""
    fns = T.bind_tools(rt.scoped_tools(), list(names), adk=True)  # type: ignore[arg-type]
    out = []
    for f in fns:
        g = rt.offload(agent, f)
        g.__andon_read_only__ = T.TOOL_REGISTRY[f.__name__].read_only  # type: ignore[attr-defined]
        out.append(g)
    return out


def signal_tool_names() -> tuple[str, ...]:
    """The Signal Analyst's tools; includes ``listen`` once it is registered."""
    extra = ("listen",) if "listen" in T.TOOL_REGISTRY else ()
    return (*T.SIGNAL_TOOLS, *extra)


def build_commander(rt: Runtime) -> LlmAgent:
    started, finished = agent_marks()
    return LlmAgent(
        name=COMMANDER,
        description="Reads the stop and plans competing checks.",
        model=rt.adk_model(COMMANDER, config.FLASH, "MEDIUM"),
        instruction=commander_instruction,
        tools=_bound(rt, COMMANDER, T.COMMANDER_TOOLS),
        output_schema=PlanOut,
        output_key="plan",
        before_agent_callback=started,
        after_agent_callback=finished,
        before_model_callback=rt.tool_gate(COMMANDER, PlanOut),
        before_tool_callback=rt.budget_guard(COMMANDER),
    )


def build_signal_analyst(rt: Runtime, exclude_tools: frozenset[str] = frozenset()) -> LlmAgent:
    """``exclude_tools`` removes tools from the analyst (eval ablation S3 drops ``listen`` and
    ``spectrum``); the default is the full tool set."""
    started, finished = agent_marks()
    return LlmAgent(
        name=ANALYST,
        description="Runs the numeric checks with telemetry tools.",
        model=rt.adk_model(ANALYST, config.FLASH, "LOW"),
        instruction=analyst_instruction,
        tools=_bound(rt, ANALYST, tuple(n for n in signal_tool_names() if n not in exclude_tools)),
        include_contents="none",
        output_key="signal_findings",
        before_agent_callback=started,
        after_agent_callback=finished,
        before_model_callback=rt.tool_gate(ANALYST),
        before_tool_callback=rt.budget_guard(ANALYST),
    )


def build_verifier(rt: Runtime) -> Any:
    from agents.verifier import Verifier

    started, finished = agent_marks()
    return Verifier(
        name=VERIFIER,
        description="Deterministic claim checks.",
        ctx_factory=rt.ctx_factory,
        before_agent_callback=started,
        after_agent_callback=finished,
    )


@dataclass
class AndonApp:
    rt: Runtime
    app: App
    runner: Runner
    sessions: InMemorySessionService
    plugin: AndonBudgetPlugin
    agent_models: dict[str, str | None] = field(default_factory=dict)
    run_config: RunConfig = field(
        default_factory=lambda: RunConfig(
            streaming_mode=StreamingMode.SSE,
            max_llm_calls=config.MAX_LLM_CALLS,
        )
    )

    @property
    def mode(self) -> str:
        return self.rt.mode


def build_app(
    store: TelemetryStore,
    *,
    judge_model: str | None = None,
    mode: str = "live",
    cmms: CMMS | None = None,
    llm: LLM | None = None,
    stages: tuple[str, ...] = ("commander", "evidence", "rca_loop", "drafter"),
    verifier_factory: Callable[[Runtime], Any] | None = None,
    exclude_signal_tools: frozenset[str] = frozenset(),
    **runtime_kw: Any,
) -> AndonApp:
    """Build the App for ``store``. ``mode`` is ``live`` (Gemini), ``replay`` (recorded fixtures,
    $0) or ``record`` (live, and capture fixtures). ``stages`` trims the graph (the skeleton run
    uses ``("commander", "evidence")``).

    Eval hooks (default: production behaviour): ``verifier_factory(rt)`` replaces the verifier
    agent (S2 ablation: an always-PASS stub); ``exclude_signal_tools`` removes tools from the
    Signal Analyst (S3 ablation)."""
    kw: dict[str, Any] = {
        "store": store,
        "mode": mode,
        "cmms": cmms or InMemoryCMMS(),
        **runtime_kw,
    }
    if judge_model is not None:
        kw["judge_model"] = judge_model
    if llm is not None:
        kw["llm"] = llm
    rt = Runtime(**kw)
    with warnings.catch_warnings():  # workflow agents are deprecated in ADK 2.x (ADR-003)
        warnings.simplefilter("ignore", DeprecationWarning)
        from google.adk.agents import LoopAgent, ParallelAgent, SequentialAgent

        parts: list[Any] = []
        if "commander" in stages:
            parts.append(build_commander(rt))
        if "evidence" in stages:
            parts.append(
                ParallelAgent(
                    name="evidence",
                    sub_agents=[
                        build_signal_analyst(rt, exclude_signal_tools),
                        build_librarian(rt, librarian_instruction),
                    ],
                )
            )
        if "rca_loop" in stages:
            parts.append(
                LoopAgent(
                    name="rca_loop",
                    sub_agents=[build_judge(rt), (verifier_factory or build_verifier)(rt)],
                    max_iterations=config.VERIFIER_MAX_ITERATIONS,
                )
            )
        if "drafter" in stages:
            parts.append(build_drafter(rt))
        root = SequentialAgent(name="andon_root", sub_agents=parts)
    plugin = AndonBudgetPlugin(llm=rt.llm)
    plugins: list[Any] = [plugin]
    if mode == "record":
        plugins.append(RecorderPlugin())
    app = App(name=APP_NAME, root_agent=root, plugins=plugins)
    sessions = InMemorySessionService()
    runner = Runner(app=app, session_service=sessions)
    judge = rt.model_id(rt.judge_model)
    flash = rt.model_id(config.FLASH)
    models: dict[str, str | None] = {
        COMMANDER: flash, ANALYST: flash, LIBRARIAN: flash, JUDGE: judge, VERIFIER: None,
        DRAFTER: flash,
    }  # fmt: skip
    return AndonApp(rt=rt, app=app, runner=runner, sessions=sessions, plugin=plugin,
                    agent_models=models)  # fmt: skip


def iter_agents(agent: Any) -> list[Any]:
    out = [agent]
    for sub in getattr(agent, "sub_agents", None) or []:
        out.extend(iter_agents(sub))
    return out


def all_tools(app: AndonApp) -> dict[str, list[Any]]:
    """``{agent name: [tool functions]}`` for every LLM agent in the app."""
    return {
        a.name: list(a.tools) for a in iter_agents(app.app.root_agent) if isinstance(a, LlmAgent)
    }
