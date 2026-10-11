"""The five systems of EVAL_PLAN §1 behind one entry point, :func:`run_system`.

* **S1** full Andon graph; **S2** the same graph with the verifier replaced by an always-PASS stub
  (:class:`AlwaysPassVerifier`); **S3** the same graph without ``listen`` and ``spectrum``
  (hooks in ``agents.graph.build_app``; this module only passes parameters).
* **B1** naive long-context: one ``gemini-3.8-flash`` call, the same ``RCAReport`` schema, no
  tools, no verifier. Its context is a fixed battery of the *same read-only tools* the agent
  has (run deterministically, no model involved) plus all five manuals; every evidence item has an
  id so the independent checker can grade B1's claims exactly like S1's.
* **B2** classical: the asset with the highest ``anomaly_score`` in the lookback window, labelled
  with the most frequent historical fault class of that asset *type* (background work-order
  history only; scenario-specific work orders are not used). No LLM.

None of these reads ground truth. A system returns one results row (see ``eval/records.py``).
"""

from __future__ import annotations

import asyncio
import json
import threading
import time
import uuid
from collections import Counter
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import config
from agents import tools as T
from agents.llm import LLM, get_llm
from agents.schemas import ClaimVerdict, RCAReport, VerifierVerdict
from agents.untrusted import NOTICE, wrap_summary
from eval import records
from simulator import plant

ROOT = Path(__file__).resolve().parents[1]
PROMPT_DIR = Path(__file__).parent / "prompts"
BASES = ("S1", "S2", "S3", "B1", "B2")
GRAPH_BASES = ("S1", "S2", "S3")
S3_EXCLUDED_TOOLS = frozenset({"listen", "spectrum"})
LOOKBACK_H = 12  # B1 context and B2 scoring window before the stop
NO_FAULT_SCORE = 0.5  # B2: below this the classical baseline says "no fault"
MAX_EVIDENCE_CHARS = 6000  # same cap the judge applies to one summary
B1_MODEL = config.FLASH


# =============================================================================================
# System specs
# =============================================================================================
@dataclass(frozen=True)
class SystemSpec:
    """``name`` is what appears in results (``S2@flash`` if the judge is pinned per system)."""

    name: str
    base: str
    judge_model: str | None  # graph systems only

    @property
    def uses_llm(self) -> bool:
        return self.base != "B2"


JUDGES = {"flash": config.FLASH, "pro": config.PRO_JUDGE}


def parse_system(token: str, default_judge: str) -> SystemSpec:
    """``S1`` | ``S2@flash`` | ``B1`` ... A ``@flash|@pro|@<pinned id>`` suffix pins the judge."""
    base, _, j = token.strip().partition("@")
    if base not in BASES:
        raise ValueError(f"unknown system {base!r}; choose from {BASES}")
    judge = None
    if base in GRAPH_BASES:
        judge = JUDGES.get(j, j) if j else default_judge
        if judge not in config.PINNED_MODELS:
            raise ValueError(f"judge {judge!r} is not a pinned model")
    elif j:
        raise ValueError(f"{base} has no judge to pin")
    return SystemSpec(token.strip(), base, judge)


@dataclass
class RunContext:
    scenario_id: str
    repeat: int
    store: Any
    lock: threading.RLock
    mode: str = "live"  # live | replay (replay = recorded fixtures, $0; used by --dry-run)
    fixture_root: Path | None = None
    llm: LLM | None = None  # B1's gateway (default: the process-wide one)
    history: HistoryPrior | None = None


# =============================================================================================
# S2: always-PASS verifier
# =============================================================================================
def _stub_class() -> type:
    from google.adk.agents import BaseAgent
    from google.adk.events import Event, EventActions

    class AlwaysPassVerifier(BaseAgent):
        """Ablation S2: accepts the first draft unchecked. Same state/event contract as
        ``agents.verifier.Verifier`` (``rca_final`` verified, ``escalate``), no checks, no loop."""

        async def _run_async_impl(self, ctx: Any) -> AsyncGenerator[Any, None]:
            state = ctx.session.state
            raw = state.get("rca_draft")
            try:
                report = raw if isinstance(raw, RCAReport) else RCAReport.model_validate(raw)
            except Exception:
                inc = str(state.get("incident_id") or ctx.invocation_id)
                report = RCAReport(incident_id=inc, hypotheses=[], status="insufficient_evidence")
                final = report
            else:
                final = report.model_copy(update={"status": "verified"})
            verdicts = [
                ClaimVerdict(
                    claim_id=c.claim_id, verdict="pass", reason="S2 stub: claims are not checked"
                )
                for h in report.hypotheses
                for c in h.claims
            ]
            verdict = VerifierVerdict(overall="PASS", claims=verdicts, iteration=1)
            delta = {
                "verifier_verdict": verdict.model_dump(mode="json"),
                "rejected_claims": [],
                "verifier_iteration": 1,
                "verifier_invocation": ctx.invocation_id,
                "rca_final": final.model_dump(mode="json"),
                "rca_final_claims": [v.model_dump(mode="json") for v in verdicts],
            }
            yield Event(
                author=self.name,
                invocation_id=ctx.invocation_id,
                branch=ctx.branch,
                custom_metadata={
                    "andon_event": "verifier_verdict",
                    "data": verdict.model_dump(mode="json"),
                    "summary": "S2 stub: always PASS",
                },
                actions=EventActions(state_delta=delta, escalate=True),
            )

    return AlwaysPassVerifier


def always_pass_verifier(rt: Any) -> Any:
    from agents.graph import VERIFIER
    from agents.runtime import agent_marks

    started, finished = agent_marks()
    return _stub_class()(
        name=VERIFIER,
        description="S2 ablation: always PASS.",
        before_agent_callback=started,
        after_agent_callback=finished,
    )


# =============================================================================================
# S1 / S2 / S3
# =============================================================================================
async def run_graph_system(spec: SystemSpec, rc: RunContext) -> dict:
    from agents.cmms import InMemoryCMMS
    from agents.events_map import run_incident
    from agents.graph import build_app

    kw: dict[str, Any] = {}
    if spec.base == "S2":
        kw["verifier_factory"] = always_pass_verifier
    elif spec.base == "S3":
        kw["exclude_signal_tools"] = S3_EXCLUDED_TOOLS
    if rc.fixture_root is not None:
        kw["fixture_root"] = rc.fixture_root
    # eval work orders go to memory: the mock CMMS the UI shows is never touched by an eval
    app = build_app(rc.store, judge_model=spec.judge_model, mode=rc.mode, cmms=InMemoryCMMS(), **kw)
    # the store lock serialises DuckDB access across concurrent runs
    app.rt._store_lock = rc.lock
    fold = records.EventFold()
    t0 = time.perf_counter()
    async for ev in run_incident(app, rc.scenario_id):
        fold.add(ev, time.perf_counter())
    return records.record_from_fold(
        fold,
        system=spec.name,
        scenario_id=rc.scenario_id,
        repeat=rc.repeat,
        judge_model=spec.judge_model,
        mode=rc.mode,
        wall_s=time.perf_counter() - t0,
    )


# =============================================================================================
# B1: naive long-context
# =============================================================================================
def b1_prompt() -> tuple[str, str]:
    """``(version, text)`` of ``eval/prompts/b1.md`` (frozen for the eval: the baseline must not move)."""
    raw = (PROMPT_DIR / "b1.md").read_text("utf-8")
    head, _, body = raw.partition("\n")
    version = head.removeprefix("<!--").removesuffix("-->").strip().removeprefix("version:").strip()
    return version, body.strip()


def _iso(d: datetime) -> str:
    return d.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def b1_battery(ctx: T.ToolContext) -> list[tuple[str, dict]]:
    """The fixed, scenario-independent tool battery whose summaries B1 gets (deterministic)."""
    stop = T.TOOL_REGISTRY["get_stop_event"].fn(ctx, line_id=plant.LINE_ID)["summary"]
    t_stop = datetime.fromisoformat(stop["stop_ts"].replace("Z", "+00:00"))
    h0 = datetime.fromisoformat(stop["history_start"].replace("Z", "+00:00"))
    recent = (_iso(t_stop - timedelta(hours=LOOKBACK_H)), _iso(t_stop))
    mid = (
        _iso(t_stop - timedelta(hours=3 * LOOKBACK_H)),
        _iso(t_stop - timedelta(hours=LOOKBACK_H)),
    )
    base = (_iso(h0), _iso(h0 + timedelta(days=3)))
    day = (_iso(t_stop - timedelta(hours=24)), _iso(t_stop))
    calls: list[tuple[str, dict]] = [("list_assets", {"line_id": plant.LINE_ID})]
    for a in plant.ASSETS:
        tags = [t.tag for t in a.tags]
        for t0, t1 in (base, mid, recent):
            calls.append(
                ("query_telemetry", {"asset_id": a.asset_id, "tags": tags, "t0": t0, "t1": t1})
            )
        calls.append(("anomaly_score", {"asset_id": a.asset_id, "t0": recent[0], "t1": recent[1]}))
    calls.append(
        ("search_alarms", {"line_id": plant.LINE_ID, "t0": day[0], "t1": day[1], "codes": None})
    )
    calls.append(("get_shift_notes", {"line_id": plant.LINE_ID, "t0": day[0], "t1": day[1]}))
    since = _iso(t_stop - timedelta(days=30))
    for a in plant.ASSETS:
        calls.append(("get_work_orders", {"asset_id": a.asset_id, "since": since}))
    return calls


def b1_evidence(store: Any, scenario_id: str, lock: threading.RLock) -> list[dict]:
    """Run the battery; return the Evidence dicts in id order (errors are skipped)."""
    state: dict[str, Any] = {}
    ctx = T.ToolContext(store=store, scenario_id=scenario_id, state=state, _lock=lock)
    for name, args in b1_battery(ctx):
        T.TOOL_REGISTRY[name].fn(ctx, **args)
    out = []
    for k in sorted(state, key=_ev_sort):
        if k.startswith(T.EVIDENCE_PREFIX):
            out.append(state[k])
    return out


def _ev_sort(k: str) -> tuple:
    tail = k.rsplit("_", 1)
    return (tail[0], int(tail[1]) if tail[-1].isdigit() else 0)


def b1_user_prompt(scenario_id: str, evidence: list[dict]) -> str:
    from agents.cache import manuals_corpus

    stop = next((e["summary"] for e in evidence if e["tool"] == "get_stop_event"), {})
    shown = []
    for e in evidence:
        if e["tool"] == "get_stop_event":
            continue
        summ = wrap_summary(e["tool"], e["summary"])
        if e["tool"] == "list_assets":
            summ = {"count": summ.get("count"), "assets": [a["asset_id"] for a in summ["assets"]]}
        if len(json.dumps(summ, ensure_ascii=False)) > MAX_EVIDENCE_CHARS and isinstance(
            summ.get("rows"), list
        ):
            summ = {**summ, "rows": summ["rows"][:10], "rows_shown": 10}
        shown.append(
            {"evidence_id": e["evidence_id"], "tool": e["tool"], "args": e["args"], "summary": summ}
        )
    cat = "\n".join(
        f"- {a.asset_id} ({a.asset_type}, "
        + (f"position {a.position}" if a.position is not None else "utility")
        + (f", feeds {', '.join(a.feeds)}" if a.feeds else "")
        + "): "
        + "; ".join(f"{t.tag} [{t.unit}, normal {t.normal_lo:g}-{t.normal_hi:g}]" for t in a.tags)
        for a in plant.ASSETS
    )
    return "\n\n".join(
        [
            f"Incident for scenario {scenario_id}: line stop. Stop record: "
            + json.dumps(stop, ensure_ascii=False),
            "Line L1 assets in flow order (utilities last):\n" + cat,
            NOTICE,
            "<evidence>\n" + json.dumps(shown, ensure_ascii=False) + "\n</evidence>",
            "<manuals>\n" + manuals_corpus() + "\n</manuals>",
            "Return the RCAReport JSON.",
        ]
    )


def _normalise(report: RCAReport, incident_id: str) -> RCAReport:
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


async def run_b1(spec: SystemSpec, rc: RunContext) -> dict:
    from google.genai import types

    llm = rc.llm or get_llm()
    t0 = time.perf_counter()
    run_id = f"b1_{rc.scenario_id}_{rc.repeat}_{uuid.uuid4().hex[:6]}"
    version, system = b1_prompt()
    try:
        evidence = await asyncio.to_thread(b1_evidence, rc.store, rc.scenario_id, rc.lock)
        prompt = b1_user_prompt(rc.scenario_id, evidence)
        cfg = types.GenerateContentConfig(
            system_instruction=system,
            response_mime_type="application/json",
            response_schema=RCAReport,
            thinking_config=types.ThinkingConfig(thinking_level=types.ThinkingLevel.MEDIUM),
        )
        report: RCAReport | None = None
        err = ""
        for attempt in range(2):  # one retry on an unparseable answer, like the judge
            p = (
                prompt
                if attempt == 0
                else f"{prompt}\n\nYour previous output was invalid: {err}\nReturn valid JSON."
            )
            res = await llm.generate(B1_MODEL, p, cfg, agent="b1", run_id=run_id)
            try:
                report = RCAReport.model_validate_json(res.response.text or "")
                break
            except Exception as exc:
                err = str(exc)[:600]
        t1 = time.perf_counter()
        cost = llm.pop_run_cost(run_id).to_cost_data()
        extra = {"b1_prompt_version": version, "b1_context_chars": len(prompt)}
        if report is None:
            row = records.error_row(
                system=spec.name,
                scenario_id=rc.scenario_id,
                repeat=rc.repeat,
                judge_model=B1_MODEL,
                mode=rc.mode,
                code="unparseable",
                message=err,
                wall_s=t1 - t0,
            )
            row["cost"] = cost
            row.update(extra)
            return row
        report = _normalise(report, f"b1_{rc.scenario_id}")
        row = records.record_from_fold(
            records.EventFold(),
            system=spec.name,
            scenario_id=rc.scenario_id,
            repeat=rc.repeat,
            judge_model=B1_MODEL,
            mode=rc.mode,
            wall_s=t1 - t0,
            extra=extra,
        )
        row.update(
            {
                "status": "ok",
                "error": None,
                "report": report.model_dump(mode="json"),
                "evidence": evidence,
                "cost": cost,
                "duration_s": round(t1 - t0, 3),
            }
        )
        return row
    except Exception as exc:
        row = records.error_row(
            system=spec.name,
            scenario_id=rc.scenario_id,
            repeat=rc.repeat,
            judge_model=B1_MODEL,
            mode=rc.mode,
            code=type(exc).__name__,
            message=str(exc),
            wall_s=time.perf_counter() - t0,
        )
        row["cost"] = llm.pop_run_cost(run_id).to_cost_data()
        row["budget_exhausted"] = type(exc).__name__ == "BudgetExhaustedError"
        return row


# =============================================================================================
# B2: classical
# =============================================================================================
@dataclass
class HistoryPrior:
    """Fault-class counts per asset *type* from the background work-order history."""

    counts: dict[str, Counter[str]] = field(default_factory=dict)

    @classmethod
    def load(cls, data_dir: Path | str = ROOT / "data") -> HistoryPrior:
        import pandas as pd

        d = Path(data_dir)
        wo = pd.read_parquet(
            d / "work_orders.parquet", columns=["wo_id", "asset_id", "scenario_id"]
        )
        lab = pd.read_parquet(d / "work_orders_labels.parquet", columns=["wo_id", "cause_class"])
        df = wo.merge(lab, on="wo_id")
        df = df[df.scenario_id.isna() & df.cause_class.notna()]  # background history only
        counts: dict[str, Counter[str]] = {}
        for r in df.itertuples():
            atype = plant.asset(r.asset_id).asset_type
            counts.setdefault(atype, Counter())[r.cause_class] += 1
        return cls(counts)

    def ranked(self, asset_type: str, k: int = 3) -> list[tuple[str, float]]:
        c = self.counts.get(asset_type)
        if not c:
            return []
        total = sum(c.values())
        return [
            (cls_, n / total) for cls_, n in sorted(c.items(), key=lambda kv: (-kv[1], kv[0]))[:k]
        ]


def b2_report(
    scores: dict[str, float | None], prior: HistoryPrior, incident_id: str, stopped: str
) -> RCAReport:
    """Pure part of B2 (unit-tested): argmax anomaly asset + historical class ranking."""
    valid = {a: s for a, s in scores.items() if s is not None}
    if not valid:
        return RCAReport(incident_id=incident_id, hypotheses=[], status="insufficient_evidence")
    best = max(sorted(valid), key=lambda a: valid[a])  # ties -> alphabetical asset id
    score = valid[best]
    from agents.schemas import CauseClass, Hypothesis

    if score < NO_FAULT_SCORE:
        h = Hypothesis(
            cause_class=CauseClass.NO_FAULT,
            asset_id=stopped,
            confidence=round(1 - score, 3),
            causal_chain=[],
            claims=[],
        )
        return RCAReport(incident_id=incident_id, hypotheses=[h], status="verified")
    ranked = prior.ranked(plant.asset(best).asset_type)
    hyps = [
        Hypothesis(
            cause_class=CauseClass(c),
            asset_id=best,
            confidence=round(score * share, 3),
            causal_chain=[best],
            claims=[],
        )
        for c, share in ranked
    ]
    if not hyps:
        return RCAReport(incident_id=incident_id, hypotheses=[], status="insufficient_evidence")
    return RCAReport(incident_id=incident_id, hypotheses=hyps, status="verified")


def b2_scores(store: Any, scenario_id: str, lock: threading.RLock) -> tuple[dict, dict]:
    ctx = T.ToolContext(store=store, scenario_id=scenario_id, state={}, _lock=lock)
    stop = T.TOOL_REGISTRY["get_stop_event"].fn(ctx, line_id=plant.LINE_ID)["summary"]
    t_stop = datetime.fromisoformat(stop["stop_ts"].replace("Z", "+00:00"))
    t0, t1 = _iso(t_stop - timedelta(hours=LOOKBACK_H)), _iso(t_stop)
    scores: dict[str, float | None] = {}
    for a in plant.ASSETS:
        r = T.TOOL_REGISTRY["anomaly_score"].fn(ctx, asset_id=a.asset_id, t0=t0, t1=t1)
        scores[a.asset_id] = (r.get("summary") or {}).get("score")
    return scores, stop


async def run_b2(spec: SystemSpec, rc: RunContext) -> dict:
    t0 = time.perf_counter()
    try:
        prior = rc.history or HistoryPrior.load()
        scores, stop = await asyncio.to_thread(b2_scores, rc.store, rc.scenario_id, rc.lock)
        report = b2_report(scores, prior, f"b2_{rc.scenario_id}", stop["stopped_station"])
    except Exception as exc:
        return records.error_row(
            system=spec.name,
            scenario_id=rc.scenario_id,
            repeat=rc.repeat,
            judge_model=None,
            mode=rc.mode,
            code=type(exc).__name__,
            message=str(exc),
            wall_s=time.perf_counter() - t0,
        )
    dt = time.perf_counter() - t0
    row = records.record_from_fold(
        records.EventFold(),
        system=spec.name,
        scenario_id=rc.scenario_id,
        repeat=rc.repeat,
        judge_model=None,
        mode=rc.mode,
        wall_s=dt,
        extra={
            "note": "B2 is classical: no LLM, no claims; 'status' is a placeholder",
            "b2_scores": scores,
        },
    )
    row.update(
        {
            "status": "ok",
            "error": None,
            "report": report.model_dump(mode="json"),
            "duration_s": round(dt, 3),
        }
    )
    return row


# =============================================================================================
async def run_system(spec: SystemSpec, rc: RunContext) -> dict:
    """Run one (system, scenario, repeat). Never raises for a failed run: returns an error row."""
    t0 = time.perf_counter()
    try:
        if spec.base in GRAPH_BASES:
            return await run_graph_system(spec, rc)
        if spec.base == "B1":
            return await run_b1(spec, rc)
        return await run_b2(spec, rc)
    except Exception as exc:  # BudgetExhaustedError is an error row too; run_eval stops on it
        row = records.error_row(
            system=spec.name,
            scenario_id=rc.scenario_id,
            repeat=rc.repeat,
            judge_model=spec.judge_model,
            mode=rc.mode,
            code=type(exc).__name__,
            message=str(exc),
            wall_s=time.perf_counter() - t0,
        )
        row["budget_exhausted"] = type(exc).__name__ == "BudgetExhaustedError"
        return row
