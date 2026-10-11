"""Action Drafter (AGENTS_SPEC §6) and ``draft_work_order``, the only write tool.

Safety text cannot be reworded because the model never writes it: the instruction lists the
asset manual's energy-control steps with ids (``<doc>:<step>``) and the model picks ids. Code
assembles each safety step from ``simulator.manuals.loto`` with its verbatim citation (doc, page
located in the built manual), orders them as the manual does (apply -> repair -> release), and
rejects the draft unless:

* every LOTO phase (prepare, shutdown, isolate, lock, stored, verify, release) is covered;
* no non-safety repair step contains energy-control wording;
* every safety step's quote is found verbatim on its cited page (own post-check), and
  ``agents.verifier.check_safety_steps`` returns no errors.

Only then is the WorkOrder written, as ``PENDING_APPROVAL``, to the CMMS. Nothing the model or any
untrusted text says can change that status: the tool has no status argument.
"""

from __future__ import annotations

import re
import uuid
from typing import Any

from google.adk.agents import LlmAgent
from google.adk.tools import ToolContext as AdkToolContext
from google.genai import types

import config
from agents import prompts
from agents.runtime import Runtime, agent_marks
from agents.schemas import CauseClass, Citation, RCAReport, WorkOrder, WorkOrderStep
from simulator import plant
from simulator.manuals import find_quote, locate_quote
from simulator.manuals import loto as L

AGENT = "action_drafter"
REQUIRED_PHASES = tuple(p for p, _ in L.PHASES)
# Energy-control wording that must never appear in a model-written (non-safety) step.
SAFETY_WORDS = re.compile(
    r"\b(lock\s*-?\s*out|tag\s*-?\s*out|loto|lock(s|ed)?\b|isolat\w*|de-?energi[sz]\w*|"
    r"bleed\w*|disconnect\w*|stored energy|zero energy|energy control|energi[sz]e\w*)",
    re.IGNORECASE,
)
MAX_REPAIR_STEPS = 8


# --- LOTO catalogue --------------------------------------------------------------------------
def loto_steps(doc: str) -> list[dict]:
    """``[{id, phase, step_no, text, page}]`` for one manual, numbered as in the manual."""
    proc = L.LOTO[doc]
    out = []
    for i, s in enumerate(proc.steps, start=1):
        pages = locate_quote(doc, s.text)
        out.append({"id": f"{doc}:{i}", "phase": s.phase, "step_no": i, "text": s.text,
                    "page": pages[0] if pages else None})  # fmt: skip
    return out


def manual_for(asset_id: str) -> str | None:
    a = plant.ASSET_BY_ID.get(asset_id)
    return a.manual if a is not None and a.manual in L.LOTO else None


def top_hypothesis(state: Any) -> tuple[RCAReport | None, str | None]:
    """The verified report and why there is nothing to draft (None if there is)."""
    raw = state.get("rca_final")
    if not raw:
        return None, "no final RCA report"
    rep = RCAReport.model_validate(raw)
    if rep.status != "verified" or not rep.hypotheses:
        return rep, "the root cause was not verified (insufficient evidence)"
    top = rep.hypotheses[0]
    if top.cause_class == CauseClass.NO_FAULT:
        return rep, "the verified finding is no_fault"
    if manual_for(top.asset_id) is None:
        return rep, f"no energy-control procedure for {top.asset_id} in the manuals"
    return rep, None


# --- post-checks -----------------------------------------------------------------------------
def own_safety_check(wo: WorkOrder) -> list[str]:
    """Every safety step is a verbatim quote on its cited page; text == quote."""
    errs = []
    for s in wo.steps:
        if not s.is_safety:
            continue
        c = s.citation
        if c is None:
            errs.append(f"step {s.order}: safety step without citation")
        elif s.text != c.quote:
            errs.append(f"step {s.order}: safety text differs from its quote")
        elif not find_quote(c.doc, c.page, c.quote):
            errs.append(f"step {s.order}: quote not found on {c.doc} p.{c.page}")
    if not any(s.is_safety for s in wo.steps):
        errs.append("work order has no safety steps")
    return errs


def verifier_safety_check(wo: WorkOrder) -> list[str]:
    from agents.verifier import check_safety_steps

    return list(check_safety_steps(wo))


def assemble(
    *,
    wo_id: str,
    incident_id: str,
    asset_id: str,
    cause_class: CauseClass,
    safety_step_ids: list[str],
    repair_steps: list[str],
    parts: list[str],
) -> tuple[WorkOrder | None, list[str]]:
    """Build the WorkOrder from step ids + repair text, or return the reasons it is refused."""
    doc = manual_for(asset_id)
    if doc is None:
        return None, [f"no energy-control procedure for {asset_id}"]
    catalogue = {s["id"]: s for s in loto_steps(doc)}
    errs: list[str] = []
    unknown = [i for i in safety_step_ids if i not in catalogue]
    if unknown:
        errs.append(f"unknown safety step ids {unknown}; valid ids are {doc}:1..{len(catalogue)}")
    chosen = sorted({catalogue[i]["step_no"]: catalogue[i] for i in safety_step_ids
                     if i in catalogue}.values(), key=lambda s: s["step_no"])  # fmt: skip
    missing = [p for p in REQUIRED_PHASES if p not in {s["phase"] for s in chosen}]
    if missing:
        errs.append(f"missing LOTO phases {missing}; pick at least one step from each")
    repairs = [r.strip() for r in repair_steps if isinstance(r, str) and r.strip()]
    if not repairs:
        errs.append("give at least one repair or inspection step")
    if len(repairs) > MAX_REPAIR_STEPS:
        errs.append(f"at most {MAX_REPAIR_STEPS} repair steps")
    bad = [r for r in repairs if SAFETY_WORDS.search(r)]
    if bad:
        errs.append(f"repair steps must not contain energy-control wording (code adds it): {bad}")
    if any(s["page"] is None for s in chosen):
        errs.append("a safety step could not be located in the built manual")
    if errs:
        return None, errs

    def safety(s: dict) -> WorkOrderStep:
        return WorkOrderStep(order=0, text=s["text"], is_safety=True,
                             citation=Citation(doc=doc, page=s["page"], quote=s["text"]))  # fmt: skip

    apply_ = [safety(s) for s in chosen if s["phase"] != "release"]
    release = [safety(s) for s in chosen if s["phase"] == "release"]
    work = [WorkOrderStep(order=0, text=r, is_safety=False) for r in repairs]
    steps = apply_ + work + release
    for i, s in enumerate(steps, start=1):
        s.order = i
    wo = WorkOrder(wo_id=wo_id, incident_id=incident_id, asset_id=asset_id,
                   cause_class=cause_class, steps=steps,
                   parts=[p.strip() for p in parts if isinstance(p, str) and p.strip()][:12])  # fmt: skip
    errs = own_safety_check(wo) + verifier_safety_check(wo)
    return (None, errs) if errs else (wo, [])


# --- the write tool --------------------------------------------------------------------------
def make_draft_work_order(rt: Runtime) -> Any:
    def draft_work_order(
        asset_id: str,
        cause_class: str,
        safety_step_ids: list[str],
        repair_steps: list[str],
        parts: list[str],
        tool_context: AdkToolContext = None,  # type: ignore[assignment]
    ) -> dict:
        """Create the draft maintenance work order (status PENDING_APPROVAL; a human approves
        it). safety_step_ids are ids from the energy-control step list; code inserts their
        verbatim manual text. repair_steps are short non-safety steps; parts may be empty."""
        state = tool_context.state
        scope = rt.scope_for(state)
        if state.get("work_order"):
            return {"error": {"code": "already_drafted",
                              "message": f"work order {state['work_order']['wo_id']} exists"}}  # fmt: skip
        rep, why_not = top_hypothesis(state)
        if why_not is not None or rep is None:
            return {"error": {"code": "nothing_to_draft", "message": why_not or "no report"}}
        top = rep.hypotheses[0]
        if asset_id != top.asset_id or cause_class != top.cause_class.value:
            return {"error": {"code": "not_the_verified_hypothesis",
                              "message": f"draft for {top.asset_id} / {top.cause_class.value}"}}  # fmt: skip
        wo_id = f"WO-DRAFT-{scope.scenario_id}-{uuid.uuid4().hex[:6].upper()}"
        wo, errs = assemble(wo_id=wo_id, incident_id=scope.incident_id, asset_id=asset_id,
                            cause_class=top.cause_class, safety_step_ids=list(safety_step_ids),
                            repair_steps=list(repair_steps), parts=list(parts))  # fmt: skip
        if wo is None:
            return {"error": {"code": "rejected", "message": "; ".join(errs)}}
        rt.cmms.create_draft(wo)
        state["work_order"] = wo.model_dump(mode="json")
        return {"wo_id": wo.wo_id, "status": wo.status, "steps": len(wo.steps),
                "safety_steps": sum(s.is_safety for s in wo.steps)}  # fmt: skip

    draft_work_order.__andon_read_only__ = False  # type: ignore[attr-defined]
    return draft_work_order


# --- agent -----------------------------------------------------------------------------------
def drafter_instruction(ctx: Any) -> str:
    state = ctx.state
    rep, _ = top_hypothesis(state)
    top = rep.hypotheses[0] if rep and rep.hypotheses else None
    lines = [prompts.text("drafter"), prompts.GROUND_RULES]
    if top is not None:
        lines.append(
            f"Verified top hypothesis: cause_class={top.cause_class.value} asset_id={top.asset_id} "
            f"causal_chain={top.causal_chain} next_check={top.next_check!r}"
        )
        claims = "\n".join(f"- {c.text}" for c in top.claims)
        lines.append("Verified claims:\n" + claims)
        doc = manual_for(top.asset_id)
        if doc:
            steps = "\n".join(f"{s['id']} [{s['phase']}] {s['text']}" for s in loto_steps(doc))
            lines.append(f"Energy-control steps of the {doc} manual (choose by id):\n{steps}")
    return "\n\n".join(lines)


def _skip_unless_verified(callback_context: Any) -> types.Content | None:
    """No draft when there is nothing verified to act on; the reason goes to the trace."""
    _, why_not = top_hypothesis(callback_context.state)
    if why_not is None:
        return None
    callback_context.state["work_order_skipped"] = why_not
    return types.Content(
        role="model", parts=[types.Part(text=f"No work order drafted: {why_not}.")]
    )


def build_drafter(rt: Runtime) -> LlmAgent:
    started, finished = agent_marks()

    def before(callback_context: Any) -> types.Content | None:
        started(callback_context)
        return _skip_unless_verified(callback_context)

    return LlmAgent(
        name=AGENT,
        description="Drafts a safety-gated work order for the verified root cause.",
        model=rt.adk_model(AGENT, config.FLASH, "LOW"),
        instruction=drafter_instruction,
        tools=[make_draft_work_order(rt)],
        include_contents="none",
        output_key="drafter_note",
        before_agent_callback=before,
        after_agent_callback=finished,
        before_tool_callback=rt.budget_guard(AGENT),
    )
