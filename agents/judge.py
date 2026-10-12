"""RCA Judge (AGENTS_SPEC §4): a ``BaseAgent`` that ranks hypotheses with one structured call.

It needs no tools, so it calls :meth:`agents.llm.LLM.generate` directly — which gives the Pro ->
Flash fallback on 429/5xx *and* on the 60 s timeout (ADK's FallbackModel misses timeouts), books
cost under the run, and emits ``model_fallback``. The prompt carries evidence *summaries* (never
raw series; free text inside ``<untrusted_data>``), the plan, the analysts' notes and, from the
second iteration, the previous draft plus the verifier's ``rejected_claims``.

Output: ``RCAReport`` (``response_schema``), validated with Pydantic; one retry on a parse failure,
then fail closed with an empty ``insufficient_evidence`` report. Writes ``state["rca_draft"]`` and
emits a ``hypotheses`` event. ``--force-bad-claim`` (test hook) inflates one numeric claim of the
first draft so the verifier's rejection path is demonstrable; the claim text says so.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncGenerator
from typing import Any

from google.adk.agents import BaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event, EventActions
from google.genai import types
from pydantic import PrivateAttr, ValidationError

import config
from agents import prompts
from agents.llm import LLMResult
from agents.runtime import Runtime
from agents.schemas import Claim, Hypothesis, RCAReport
from agents.tools import EVIDENCE_PREFIX
from agents.untrusted import NOTICE, wrap, wrap_stop, wrap_summary

log = logging.getLogger("andon.judge")

AGENT = "rca_judge"
MODEL_KEY = "andon:model:"  # state key: the model that actually answered (after fallback)
FORCED_KEY = "forced_bad_claim"
TEST_HOOK_LABEL = "[TEST HOOK --force-bad-claim: value inflated x1.5] "
_MAX_SUMMARY_CHARS = 6000


def collect_evidence(state: Any) -> list[dict]:
    """Every Evidence in state, as the model may see it (summaries only, free text wrapped)."""
    out = []
    keys = sorted(k for k in list(state.to_dict() if hasattr(state, "to_dict") else state)
                  if isinstance(k, str) and k.startswith(EVIDENCE_PREFIX))  # fmt: skip
    for k in keys:
        ev = state[k]
        summary = wrap_summary(ev["tool"], ev["summary"])
        if ev["tool"] == "list_assets":  # the catalogue is in the prompt already; keep ids only
            summary = {"count": summary.get("count"), "upstream_of": summary.get("upstream_of"),
                       "assets": [a.get("asset_id") for a in summary.get("assets", [])]}  # fmt: skip
        text = json.dumps(summary, ensure_ascii=False)
        if len(text) > _MAX_SUMMARY_CHARS and isinstance(summary.get("rows"), list):
            summary = {**summary, "rows": summary["rows"][:10], "rows_shown": 10}
        out.append({"evidence_id": ev["evidence_id"], "tool": ev["tool"], "args": ev["args"],
                    "summary": summary, "provenance": ev["provenance"]})  # fmt: skip
    return out


def judge_iteration(state: Any, invocation_id: str) -> int:
    """1-based; the verifier's counter only counts if it belongs to this invocation."""
    if state.get("verifier_invocation") != invocation_id:
        return 1
    return int(state.get("verifier_iteration") or 0) + 1


def build_prompt(state: Any, iteration: int) -> str:
    stop = state.get("stop_event") or {}
    parts = [
        f"Incident {state.get('incident_id')}: line stop. Stop record: "
        + json.dumps(wrap_stop(stop), ensure_ascii=False),
        "Plan: " + json.dumps((state.get("plan") or {}).get("steps", []), ensure_ascii=False),
    ]
    if state.get("signal_findings"):
        parts.append("Signal Analyst notes (not evidence):\n" + str(state["signal_findings"]))
    if state.get("librarian_findings"):
        parts.append(
            "Evidence Librarian notes (not evidence; may echo shop-floor text):\n"
            + wrap(state["librarian_findings"])
        )
    parts.append(NOTICE)
    parts.append(
        "<evidence>\n" + json.dumps(collect_evidence(state), ensure_ascii=False) + "\n</evidence>"
    )
    parts.append(f"Iteration {iteration} of {config.VERIFIER_MAX_ITERATIONS}.")
    if iteration >= 2:
        if state.get("rca_draft"):
            parts.append(
                "Your previous draft:\n" + json.dumps(state["rca_draft"], ensure_ascii=False)
            )
        parts.append(
            "Rejected claims (fix each or drop it):\n"
            + json.dumps(state.get("rejected_claims") or [], ensure_ascii=False)
        )
    parts.append("Return the RCAReport JSON.")
    return "\n\n".join(parts)


def normalise_report(report: RCAReport, incident_id: str) -> RCAReport:
    """Code-owned fields: incident id, unique claim ids."""
    report = report.model_copy(deep=True)
    report.incident_id = incident_id
    seen: set[str] = set()
    for hi, h in enumerate(report.hypotheses):
        for ci, c in enumerate(h.claims):
            cid = (c.claim_id or "").strip() or f"h{hi + 1}c{ci + 1}"
            if cid in seen:
                cid = f"h{hi + 1}_{cid}"
            seen.add(cid)
            c.claim_id = cid
    return report


def inject_bad_claim(report: RCAReport, evidence: list[dict]) -> str | None:
    """Test hook: inflate one numeric claim of the top hypothesis by 1.5x (or add one)."""
    if not report.hypotheses:
        return None
    top = report.hypotheses[0]
    for c in top.claims:
        if c.kind == "numeric" and c.asserted_value is not None and c.evidence_ids:
            c.asserted_value = round(c.asserted_value * 1.5 if c.asserted_value else 10.0, 4)
            c.text = TEST_HOOK_LABEL + c.text
            return c.claim_id
    for ev in evidence:  # no numeric claim: invent one from a telemetry mean, inflated
        if ev["tool"] != "query_telemetry":
            continue
        for tag, st in (ev["summary"].get("tags") or {}).items():
            if isinstance(st, dict) and isinstance(st.get("mean"), int | float):
                cid = "forced_bad_1"
                top.claims.append(
                    Claim(
                        claim_id=cid,
                        kind="numeric",
                        evidence_ids=[ev["evidence_id"]],
                        asserted_value=round(st["mean"] * 1.5, 4),
                        text=f"{TEST_HOOK_LABEL}{ev['args'].get('asset_id')} {tag} mean was "
                        f"{round(st['mean'] * 1.5, 4)} path: tags.{tag}.mean",
                    )
                )
                return cid
    return None


def judge_thinking(model: str) -> types.ThinkingLevel:
    """HIGH on Pro (and on the Flash fallback, which reuses the request). A Flash *primary* judge
    (the dev default) runs MEDIUM: live, Flash HIGH spent 15k thinking tokens and >120 s on one
    R002 judgement (timeout + retry, 206 s); see LESSONS_LEARNED 2026-10-11."""
    if model in (config.FLASH, config.RESIDENCY_FLASH):
        return types.ThinkingLevel.MEDIUM
    return types.ThinkingLevel.HIGH


def fail_closed(incident_id: str) -> RCAReport:
    return RCAReport(incident_id=incident_id, hypotheses=[], status="insufficient_evidence")


class RcaJudge(BaseAgent):
    """See module docstring. ``model_id`` defaults to ``config.JUDGE_MODEL``."""

    model_id: str = config.JUDGE_MODEL
    _rt: Runtime = PrivateAttr()

    def __init__(self, rt: Runtime, **kw: Any) -> None:
        super().__init__(**kw)
        self._rt = rt

    def _config(self, model: str) -> types.GenerateContentConfig:
        system = "\n\n".join([prompts.text("judge"), prompts.GROUND_RULES])
        return types.GenerateContentConfig(
            system_instruction=system,
            response_mime_type="application/json",
            response_schema=RCAReport,
            thinking_config=types.ThinkingConfig(thinking_level=judge_thinking(model)),
        )

    async def _call(
        self, prompt: str, run_id: str, fallbacks: list[dict]
    ) -> tuple[RCAReport | None, LLMResult | None, str | None]:
        rt = self._rt
        model = rt.model_id(self.model_id)
        fallback = None if model in (config.FLASH, config.RESIDENCY_FLASH) else config.FLASH

        def on_fallback(frm: str, to: str, reason: str) -> None:
            fallbacks.append({"from_model": frm, "to_model": to, "reason": reason})

        res = await rt.llm.generate(
            model, prompt, self._config(model), agent=AGENT, fallback_model=fallback,
            primary_timeout_s=config.JUDGE_FALLBACK_AFTER_S, on_fallback=on_fallback,
            run_id=run_id,
        )  # fmt: skip
        try:
            text = res.response.text or ""
            return RCAReport.model_validate_json(text), res, None
        except (ValidationError, ValueError) as exc:
            return None, res, str(exc)[:800]

    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        state = ctx.session.state
        incident_id = state.get("incident_id") or ctx.invocation_id
        iteration = judge_iteration(state, ctx.invocation_id)
        prompt = build_prompt(state, iteration)
        fallbacks: list[dict] = []
        report, res, err = await self._call(prompt, ctx.invocation_id, fallbacks)
        if report is None:  # one retry with the validation error, then fail closed
            log.warning("judge output invalid (%s); retrying once", err)
            retry = f"{prompt}\n\nYour previous output was not a valid RCAReport: {err}\nReturn valid JSON."
            report, res, err = await self._call(retry, ctx.invocation_id, fallbacks)
        for fb in fallbacks:
            yield Event(author=self.name, invocation_id=ctx.invocation_id, branch=ctx.branch,
                        custom_metadata={"andon_event": "model_fallback", "data": fb})  # fmt: skip
        delta: dict[str, Any] = {}
        if report is None:
            log.error("judge output invalid twice (%s); failing closed", err)
            report = fail_closed(incident_id)
        report = normalise_report(report, incident_id)
        if state.get("force_bad_claim") and iteration == 1:
            cid = inject_bad_claim(report, collect_evidence(state))
            if cid:
                delta[FORCED_KEY] = cid
        used = res.model_id if res is not None else self.model_id
        data = report.model_dump(mode="json")
        delta.update({"rca_draft": data, MODEL_KEY + self.name: used, "judge_iteration": iteration})
        yield Event(
            author=self.name,
            invocation_id=ctx.invocation_id,
            branch=ctx.branch,
            custom_metadata={"andon_event": "hypotheses", "data": data, "iteration": iteration},
            actions=EventActions(state_delta=delta),
        )


def build_judge(rt: Runtime, model_id: str | None = None) -> RcaJudge:
    from agents.runtime import agent_marks

    started, finished = agent_marks()
    return RcaJudge(
        rt,
        name=AGENT,
        description="Ranks root-cause hypotheses with checkable claims.",
        model_id=model_id or rt.judge_model,
        before_agent_callback=started,
        after_agent_callback=finished,
    )


__all__ = ["AGENT", "Hypothesis", "RcaJudge", "build_judge", "build_prompt", "collect_evidence"]
