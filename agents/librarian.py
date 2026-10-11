"""Evidence Librarian (AGENTS_SPEC §3): alarms, work orders, shift notes and manual citations.

* ``search_alarms`` / ``get_work_orders`` / ``get_shift_notes`` are the read-only tools of
  ``agents.tools``; the model sees their free text only inside ``<untrusted_data>`` blocks
  (stored Evidence keeps the raw text). A flood (alarms > 30 rows, work orders truncated) gets a
  Flash-Lite triage note, labelled as a model summary, never as evidence.
* ``cite_manual(asset_type, symptom)`` asks Flash, with the manuals context cache, for candidate
  quotes as structured output; code keeps only quotes that :func:`simulator.manuals.find_quote`
  verifies verbatim (a quote found on another page gets that page), attaches the passage's
  measurable premises (``applies_if``, ADR-025), stores them as Evidence and
  emits a ``cache_hit`` event with the tokens and dollars the cache saved.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from google.adk.agents import LlmAgent
from google.adk.tools import ToolContext as AdkToolContext
from google.genai import types
from pydantic import BaseModel, Field, ValidationError

import config
from agents import prompts
from agents import tools as T
from agents.cache import cache_hit_data, manuals_corpus
from agents.llm import BudgetExhaustedError
from agents.runtime import EVENT_PREFIX, Runtime, agent_marks
from agents.schemas import Evidence, ProvenanceRef
from agents.untrusted import NOTICE, wrap, wrap_summary
from simulator.manuals import DOCS, find_quote, locate_quote
from simulator.manuals.premises import premises_for

log = logging.getLogger("andon.librarian")

AGENT = "evidence_librarian"
FLOOD_ROWS = T.MAX_ALARM_ROWS  # an alarm result with more rows than it can show is a flood
MAX_CITATIONS = 4
MANUALS_PROVENANCE = ProvenanceRef(
    source_id="synthetic",
    real=False,
    source_ref="manuals: fictional equipment manuals (simulator/manuals); quotes verified verbatim",
)


# --- structured outputs ----------------------------------------------------------------------
class CandidateCitation(BaseModel):
    doc: str
    page: int
    quote: str


class CitationCandidates(BaseModel):
    citations: list[CandidateCitation] = Field(default_factory=list, max_length=8)


class Triage(BaseModel):
    themes: list[str] = Field(default_factory=list, max_length=5)
    likely_relevant: list[str] = Field(default_factory=list, max_length=8)
    noise: list[str] = Field(default_factory=list, max_length=8)


def _cache_gone(exc: BaseException) -> bool:
    """A cached-content reference that no longer works (deleted, expired or mid-deletion)."""
    code = getattr(exc, "code", None)
    msg = str(exc).lower()
    return code in (400, 403, 404) and ("cache" in msg or "cachedcontent" in msg)


def _json(resp: Any) -> str:
    text = getattr(resp, "text", None)
    if text:
        return text
    raise ValueError("model returned no text")


def _err(code: str, message: str, hint: str | None = None) -> dict:
    e = {"code": code, "message": message}
    if hint:
        e["hint"] = hint
    return {"evidence_id": None, "error": e}


# --- triage ----------------------------------------------------------------------------------
TRIAGE_PROMPT = (
    "You triage a flood of shop-floor records for a reliability engineer. Group them into at "
    "most 5 themes (no numbers in themes), list up to 8 row references that most likely relate "
    "to the root cause, and up to 8 row references that look like noise or chatter. A row "
    "reference is a work-order id (WO-...) or 'ts code' for an alarm, copied exactly. "
)


def _row_refs(tool: str, summary: dict) -> list[str]:
    rows = summary.get("rows") or []
    if tool == "get_work_orders":
        return [str(r.get("wo_id")) for r in rows]
    return [f"{r.get('ts')} {r.get('code')}" for r in rows]


async def triage(rt: Runtime, tool: str, summary: dict, run_id: str | None) -> dict | None:
    """Flash-Lite summary of a flood, restricted to row references that exist."""
    model_view = wrap_summary(tool, summary)
    contents = (
        f"{TRIAGE_PROMPT}\n{NOTICE}\n\nRecords ({tool}, {summary.get('count')} total):\n"
        + json.dumps(model_view.get("rows", []), ensure_ascii=False)
    )
    cfg = types.GenerateContentConfig(
        response_mime_type="application/json",
        response_schema=Triage,
        thinking_config=types.ThinkingConfig(thinking_level=types.ThinkingLevel.LOW),
    )
    try:
        res = await rt.llm.generate(
            rt.model_id(config.FLASH_LITE), contents, cfg, agent=f"{AGENT}.triage", run_id=run_id
        )
        tri = Triage.model_validate_json(_json(res.response))
    except BudgetExhaustedError:
        raise
    except Exception as exc:  # triage is optional; the tool result stands without it
        log.warning("triage failed: %r", exc)
        return None
    refs = set(_row_refs(tool, summary))
    return {
        "by": res.model_id,
        "note": "model summary of untrusted rows; not evidence, cite evidence_id facts only",
        "themes": [wrap(t) for t in tri.themes],
        "likely_relevant": [r for r in tri.likely_relevant if r in refs],
        "noise": [r for r in tri.noise if r in refs],
    }


def _is_flood(tool: str, summary: dict) -> bool:
    if tool == "search_alarms":
        return int(summary.get("count") or 0) > FLOOD_ROWS
    if tool == "get_work_orders":
        return bool(summary.get("truncated"))
    return False


async def _record_tool(
    rt: Runtime, tool: str, args: dict[str, Any], tool_context: AdkToolContext
) -> dict:
    scope = rt.scope_for(tool_context.state)
    ctx = scope.ctx.with_state(tool_context.state)
    async with scope.agent_lock(AGENT):  # call order -> evidence ids (deterministic replays)
        res = await asyncio.to_thread(T.TOOL_REGISTRY[tool].fn, ctx, **args)
    if res.get("evidence_id") is None:
        return res
    out = dict(res)
    out["summary"] = wrap_summary(tool, res["summary"])
    if _is_flood(tool, res["summary"]):
        tri = await triage(rt, tool, res["summary"], tool_context.invocation_id)
        if tri is not None:
            out["triage"] = tri
    return out


def make_record_tools(rt: Runtime) -> list[Any]:
    async def search_alarms(
        line_id: str,
        t0: str,
        t1: str,
        codes: list[str] | None = None,
        tool_context: AdkToolContext = None,  # type: ignore[assignment]
    ) -> dict:
        args = {"line_id": line_id, "t0": t0, "t1": t1, "codes": codes}
        return await _record_tool(rt, "search_alarms", args, tool_context)

    async def get_work_orders(
        asset_id: str,
        since: str,
        tool_context: AdkToolContext = None,  # type: ignore[assignment]
    ) -> dict:
        args = {"asset_id": asset_id, "since": since}
        return await _record_tool(rt, "get_work_orders", args, tool_context)

    async def get_shift_notes(
        line_id: str,
        t0: str,
        t1: str,
        tool_context: AdkToolContext = None,  # type: ignore[assignment]
    ) -> dict:
        args = {"line_id": line_id, "t0": t0, "t1": t1}
        return await _record_tool(rt, "get_shift_notes", args, tool_context)

    fns = [search_alarms, get_work_orders, get_shift_notes]
    for f in fns:
        f.__doc__ = T.TOOL_REGISTRY[f.__name__].description + " " + NOTICE
        f.__andon_read_only__ = True  # type: ignore[attr-defined]
    return fns


# --- cite_manual -----------------------------------------------------------------------------
def verify_candidates(cands: list[CandidateCitation]) -> tuple[list[dict], int, int]:
    """Keep verbatim quotes only. Returns (citations, dropped, page_corrected)."""
    kept: list[dict] = []
    seen: set[tuple[str, str]] = set()
    dropped = corrected = 0
    for c in cands:
        if c.doc not in DOCS:
            dropped += 1
            continue
        page = c.page
        if not find_quote(c.doc, page, c.quote):
            pages = locate_quote(c.doc, c.quote)
            if not pages:
                dropped += 1
                continue
            page, corrected = pages[0], corrected + 1
        key = (c.doc, " ".join(c.quote.split()))
        if key in seen:
            continue
        seen.add(key)
        cit: dict[str, Any] = {"doc": c.doc, "page": page, "quote": c.quote.strip()}
        prem = premises_for(c.doc, page, c.quote)
        if prem:  # ADR-025: the Verifier checks these against this incident's telemetry
            cit["applies_if"] = [p.as_dict() for p in prem]
        kept.append(cit)
    return kept[:MAX_CITATIONS], dropped, corrected


def make_cite_manual(rt: Runtime) -> Any:
    system = prompts.text("cite_manual")

    async def cite_manual(
        asset_type: str,
        symptom: str,
        tool_context: AdkToolContext = None,  # type: ignore[assignment]
    ) -> dict:
        """Verbatim passages from the equipment manual for an asset type (weld_controller,
        sealer_pump, conveyor_drive, press_hydraulics, compressed_air) that match a symptom:
        diagnostic notes, causes and checks, alarm meanings. Each citation has doc, page and an
        exact quote checked by code; unverifiable quotes are dropped."""
        if asset_type not in DOCS:
            return _err("unknown_manual", f"no manual {asset_type!r}", "one of: " + ", ".join(DOCS))
        if not isinstance(symptom, str) or not symptom.strip():
            return _err("bad_symptom", "describe the symptom in a few words")
        scope = rt.scope_for(tool_context.state)
        ctx = scope.ctx.with_state(tool_context.state)
        run_id = tool_context.invocation_id
        eid = ctx.next_evidence_id("cite_manual")  # reserved before any await: call order
        question = (
            f"asset_type: {asset_type}\nsymptom (from the investigating agent): {symptom.strip()}\n"
            f"Return up to {MAX_CITATIONS} verbatim citations from the {asset_type} manual."
        )
        handle = await rt.manuals_handle(scope, system, run_id)
        cfg = types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=CitationCandidates,
            thinking_config=types.ThinkingConfig(thinking_level=types.ThinkingLevel.LOW),
        )
        if handle is not None:
            cfg.cached_content = handle.name
            contents: Any = question
        else:  # replay, or cache creation failed: same instruction, manuals inline
            cfg.system_instruction = system
            contents = question if rt.mode == "replay" else [manuals_corpus(), question]
        try:
            try:
                res = await rt.llm.generate(
                    rt.model_id(config.FLASH),
                    contents,
                    cfg,
                    agent=f"{AGENT}.cite_manual",
                    run_id=run_id,
                )
            except Exception as exc:
                if handle is None or not _cache_gone(exc):
                    raise
                # the shared cache was deleted or expired under us (another process): go inline
                log.warning(
                    "manuals cache %s unusable (%.120s); sending manuals inline", handle.name, exc
                )
                scope.manuals_failed = True
                handle = None
                cfg.cached_content = None
                cfg.system_instruction = system
                contents = [manuals_corpus(), question]
                res = await rt.llm.generate(
                    rt.model_id(config.FLASH),
                    contents,
                    cfg,
                    agent=f"{AGENT}.cite_manual",
                    run_id=run_id,
                )
            cands = CitationCandidates.model_validate_json(_json(res.response)).citations
        except BudgetExhaustedError:
            raise
        except (ValidationError, ValueError) as exc:
            return _err("bad_model_output", f"manual lookup returned no usable JSON ({exc!s:.120})")
        except Exception as exc:
            return {**_err("manual_lookup_failed", f"{type(exc).__name__}: {exc!s:.200}"),
                    "retryable": True}  # fmt: skip
        citations, dropped, corrected = verify_candidates(cands)
        summary = {
            "asset_type": asset_type,
            "symptom": symptom.strip(),
            "citations": citations,
            "n_candidates": len(cands),
            "dropped_unverified": dropped,
            "page_corrected": corrected,
        }
        ev = Evidence(evidence_id=eid, tool="cite_manual",
                      args={"asset_type": asset_type, "symptom": symptom.strip()},
                      summary=summary, provenance=[MANUALS_PROVENANCE], produced_at=ctx.now())  # fmt: skip
        ctx.evidence.put(ev)
        cache_name = handle.name if handle is not None else "manuals-replay"
        hit = cache_hit_data(cache_name, res.model_id, res.usage)
        if hit is not None:
            tool_context.state[f"{EVENT_PREFIX}cache_hit:{eid}"] = {
                "type": "cache_hit",
                "data": hit,
            }
        return {
            "evidence_id": eid,
            "summary": summary,
            "provenance": [MANUALS_PROVENANCE.model_dump(mode="json")],
        }

    cite_manual.__andon_read_only__ = True  # type: ignore[attr-defined]
    return cite_manual


# --- agent -----------------------------------------------------------------------------------
def build_librarian(rt: Runtime, instruction: Any) -> LlmAgent:
    started, finished = agent_marks()
    return LlmAgent(
        name=AGENT,
        description="Finds alarms, work orders, shift notes and manual citations.",
        model=rt.adk_model(AGENT, config.FLASH, "LOW"),
        instruction=instruction,
        tools=[*make_record_tools(rt), make_cite_manual(rt)],
        include_contents="none",
        output_key="librarian_findings",
        before_agent_callback=started,
        after_agent_callback=finished,
        before_tool_callback=rt.budget_guard(AGENT),
    )
