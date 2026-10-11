"""Cost estimate (printed before any paid run) and the DEVELOPMENT.md §7 eval ledger check.

Per-run prices start from the EVAL_PLAN §7 assumptions and are replaced by *observed* per-system
averages as soon as data exists (earlier non-dry runs in ``eval/results/*/cost.json``, or the
rows already in the output directory when resuming). B1 is priced from its prompt size with
``config.PRICES``. The estimate is deliberately on the high side of what has been observed so the
ledger check fails safe; after the first 20 runs re-read it (EVAL_PLAN §7: "validate after the
first 20 runs").
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import config
from eval.baselines import GRAPH_BASES, SystemSpec

ROOT = Path(__file__).resolve().parents[1]
RESULTS_ROOT = ROOT / "eval" / "results"

# DEVELOPMENT.md §7: "Eval (EVAL_PLAN §7)" allocation / hard stop.
EVAL_ALLOCATION_USD = 110.0
EVAL_HARD_STOP_USD = 120.0
CONFIRM_ABOVE_USD = 25.0

# EVAL_PLAN §7 per-run assumptions (S1 ~ $0.56 with the Pro judge, ~ $0.30 with Flash; B1 ~ $0.10).
PLAN_PER_RUN = {
    "S1": {config.PRO_JUDGE: 0.56, config.FLASH: 0.30},
    "S2": {config.PRO_JUDGE: 0.56, config.FLASH: 0.30},
    "S3": {config.PRO_JUDGE: 0.56, config.FLASH: 0.30},  # EVAL_PLAN: ~$8 / ~25 runs; kept = S1
    "B1": {None: 0.10},
    "B2": {None: 0.0},
}
B1_CHARS_PER_TOKEN = 3.5  # JSON-heavy prompt; deliberately below the ~4 of plain English
B1_OUTPUT_TOKENS = 8000  # answer + thinking (MEDIUM), billed as output


def b1_run_usd(prompt_chars: int) -> float:
    p = config.price_for(config.FLASH)
    toks = prompt_chars / B1_CHARS_PER_TOKEN
    return (toks * p.input + B1_OUTPUT_TOKENS * p.output) / 1_000_000


@dataclass
class Line:
    system: str
    runs: int
    per_run: float
    basis: str

    @property
    def usd(self) -> float:
        return self.runs * self.per_run


@dataclass
class Estimate:
    lines: list[Line] = field(default_factory=list)
    spent_before: float = 0.0  # eval spend already in the ledger (earlier non-dry runs)

    @property
    def total(self) -> float:
        return sum(ln.usd for ln in self.lines)

    @property
    def projected(self) -> float:
        return self.spent_before + self.total

    def render(self) -> str:
        w = max([len(ln.system) for ln in self.lines] + [6])
        out = [f"{'system':<{w}}  {'runs':>5}  {'$/run':>7}  {'est. $':>8}  basis"]
        for ln in self.lines:
            out.append(
                f"{ln.system:<{w}}  {ln.runs:>5}  {ln.per_run:>7.3f}  {ln.usd:>8.2f}  {ln.basis}"
            )
        out.append(
            f"{'TOTAL':<{w}}  {sum(x.runs for x in self.lines):>5}  {'':>7}  {self.total:>8.2f}"
        )
        out.append(
            f"ledger (DEVELOPMENT.md §7, Eval line): spent so far ${self.spent_before:.2f} + this "
            f"run ${self.total:.2f} = ${self.projected:.2f} of ${EVAL_ALLOCATION_USD:.0f} allocated "
            f"(hard stop ${EVAL_HARD_STOP_USD:.0f})"
        )
        return "\n".join(out)

    def to_dict(self) -> dict:
        return {
            "lines": [
                {
                    "system": x.system,
                    "runs": x.runs,
                    "per_run_usd": x.per_run,
                    "usd": round(x.usd, 4),
                    "basis": x.basis,
                }
                for x in self.lines
            ],
            "total_usd": round(self.total, 4),
            "spent_before_usd": round(self.spent_before, 4),
            "projected_usd": round(self.projected, 4),
        }


# --- observed data -----------------------------------------------------------------------------
def observed_per_run(results_root: Path = RESULTS_ROOT, extra: Iterable[Path] = ()) -> dict:
    """``{system: (runs, usd)}`` summed over earlier non-dry runs (their ``cost.json``)."""
    tot: dict[str, list[float]] = {}
    for p in [*sorted(results_root.glob("*/cost.json")), *extra]:
        try:
            c = json.loads(Path(p).read_text("utf-8"))
        except (OSError, ValueError):
            continue
        if c.get("dry_run"):
            continue
        for sysname, v in (c.get("by_system") or {}).items():
            t = tot.setdefault(sysname, [0, 0.0])
            t[0] += v.get("runs", 0)
            t[1] += v.get("usd", 0.0)
    return {k: (int(v[0]), v[1]) for k, v in tot.items()}


def ledger_spent(results_root: Path = RESULTS_ROOT, exclude: Path | None = None) -> float:
    """Eval dollars already spent: the sum of ``total_usd`` in every non-dry ``cost.json``."""
    total = 0.0
    for p in results_root.glob("*/cost.json"):
        if exclude is not None and p.parent.resolve() == exclude.resolve():
            continue
        try:
            c = json.loads(p.read_text("utf-8"))
        except (OSError, ValueError):
            continue
        if not c.get("dry_run"):
            total += float(c.get("total_usd", 0.0))
    return total


def fixture_flash_mean(fixture_root: Path = ROOT / "tests" / "fixtures" / "llm") -> float | None:
    """Mean recorded S1 cost (Flash judge) in the committed fixtures: informational only."""
    vals = []
    for m in fixture_root.glob("*/meta.json"):
        try:
            u = json.loads(m.read_text("utf-8")).get("cost", {}).get("usd")
        except (OSError, ValueError):
            continue
        if isinstance(u, int | float) and u > 0:
            vals.append(float(u))
    return sum(vals) / len(vals) if vals else None


def estimate(
    plan: Sequence[tuple[SystemSpec, int]],
    *,
    b1_prompt_chars: int | None = None,
    observed: dict | None = None,
    done: dict[str, int] | None = None,
    spent_before: float = 0.0,
    min_observed_runs: int = 10,
) -> Estimate:
    """``plan`` = ``[(spec, runs_still_to_do)]``. ``done`` (already completed rows, resume) is only
    informational. Observed averages replace the plan price once a system has
    ``min_observed_runs`` paid runs; the larger of the two is used until then."""
    observed = observed or {}
    est = Estimate(spent_before=spent_before)
    for spec, runs in plan:
        plan_p = PLAN_PER_RUN[spec.base].get(
            spec.judge_model if spec.base in GRAPH_BASES else None, 0.0
        )
        basis = "EVAL_PLAN §7 assumption"
        per = plan_p
        if spec.base == "B1" and b1_prompt_chars:
            per = max(b1_run_usd(b1_prompt_chars), 0.0)
            basis = f"{b1_prompt_chars:,} prompt chars at config.PRICES[{config.FLASH}]"
        n_obs, usd_obs = observed.get(spec.name, (0, 0.0))
        if n_obs >= min_observed_runs:
            per = usd_obs / n_obs
            basis = f"observed mean of {n_obs} earlier runs"
        elif n_obs:
            per = max(per, usd_obs / n_obs)
            basis += f"; {n_obs} earlier runs observed (max taken)"
        if spec.base == "B2":
            basis = "no LLM"
        est.lines.append(Line(spec.name, runs, per, basis))
    return est


@dataclass
class LedgerVerdict:
    ok: bool
    needs_confirmation: bool
    messages: list[str]


def check_ledger(est: Estimate) -> LedgerVerdict:
    """Hard stop -> not ok (needs ``--override-ledger``); over $25 -> confirmation required."""
    msgs: list[str] = []
    ok = True
    if est.projected > EVAL_HARD_STOP_USD:
        ok = False
        msgs.append(
            f"REFUSED: projected eval spend ${est.projected:.2f} exceeds the DEVELOPMENT.md §7 hard "
            f"stop of ${EVAL_HARD_STOP_USD:.0f}. The principal engineer decides what to cut "
            "(EVAL_PLAN §7: cut S3, then variance repeats to 2); use --override-ledger only then."
        )
    elif est.projected > EVAL_ALLOCATION_USD:
        msgs.append(
            f"WARNING: projected ${est.projected:.2f} is above the ${EVAL_ALLOCATION_USD:.0f} Eval allocation "
            f"(hard stop ${EVAL_HARD_STOP_USD:.0f})."
        )
    return LedgerVerdict(ok, est.total > CONFIRM_ABOVE_USD, msgs)
