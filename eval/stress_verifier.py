"""Verifier fault injection (EVAL_PLAN §3b, ADR-032). Offline, $0, no Gemini.

Question: when a claim in a report is *wrong* in a checkable way, does the deterministic verifier
strike it through? The S1-vs-S2 ablation cannot answer that (the generator rarely errs on these
prompts, and S2 shows every claim as verified by construction), so we inject the errors ourselves.

Method. For every S1 run with a report in a results dir:

1. Rebuild the evidence the report may cite from the run's own tool calls (as ``eval/checker.py``
   does) and grade the **unmutated** report with ``agents.verifier.verify_report`` on a fresh
   ``ToolContext`` over the local store. The system's own verdicts are never read. These baseline
   verdicts give the false-alarm rate and select the claims that can be attacked: only claims
   that *pass* at baseline are mutated (a claim that already fails cannot be "caught" by a fault).
2. For each such claim create copies of the report with **exactly one** fault (table in
   ``FAULTS``), re-grade the whole mutated report and read the verdict of the mutated claim.
   *Caught* = ``fail`` or ``unverifiable`` (both are shown struck through in the UI); *missed* =
   ``pass``. ``fail`` and ``unverifiable`` are counted separately.
3. Injected claims (fabricated evidence id, premise-false citation) are appended to the top
   hypothesis under a ``zz_*`` claim id and judged the same way.

Everything is seeded (``--seed``, default 2026) and deterministic. Ground truth is read only to
label which premise-bearing manual passages are false for a scenario (grader side, never agents).
The injected faults are synthetic: the real error distribution of an LLM differs, so catch rates
here are a property of the safety net, not an estimate of how often the model errs.
"""

from __future__ import annotations

import argparse
import copy
import json
import re
import threading
import zlib
from collections import Counter, defaultdict
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from eval import checker, sets, stats
from eval.records import load_results

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RUN = ROOT / "eval" / "results" / "final_v2"
DEFAULT_OUT = ROOT / "eval" / "results" / "stress_verifier"
DEFAULT_DB = ROOT / "data" / "andon.duckdb"
FAKE_EVIDENCE_ID = "ev_nonexistent_999"

# fault id -> (family, human label). Table order = report order.
FAULTS: dict[str, tuple[str, str]] = {
    "num_10": ("numeric", "Number off by ±10%"),
    "num_25": ("numeric", "Number off by ±25%"),
    "num_sign": ("numeric", "Number sign flipped"),
    "ts_15m": ("temporal", "Timestamp shifted ±15 min"),
    "ts_2h": ("temporal", "Timestamp shifted ±2 h"),
    "cite_sentence": ("citation", "Quote with one word altered"),
    "cite_page": ("citation", "Quote cited on the wrong page"),
    "cite_doc": ("citation", "Quote from another manual"),
    "causal_reversed": ("causal_order", "Causal order reversed"),
    "fabricated_evidence": ("fabricated", "Claim cites a non-existent evidence id"),
    "premise_false": ("premise", "Quote with false premise (by construction)"),
}
CHECKED_KINDS = ("numeric", "temporal", "citation", "causal_order")

_SWAPS = [  # direction/meaning pairs; used for the sentence fault and the sign-flip text
    ("rises", "falls"),
    ("rise", "fall"),
    ("increases", "decreases"),
    ("increase", "decrease"),
    ("higher", "lower"),
    ("above", "below"),
    ("longer", "shorter"),
    ("upstream", "downstream"),
    ("before", "after"),
    ("raises", "lowers"),
    ("loaded", "unloaded"),
    ("exceeds", "stays under"),
]
_DIR_SWAPS = [
    ("dropped", "rose"),
    ("drops", "rises"),
    ("drop", "rise"),
    ("fell", "rose"),
    ("falls", "rises"),
    ("decreased", "increased"),
    ("decrease", "increase"),
    ("declined", "grew"),
    ("lower", "higher"),
    ("down", "up"),
]
_PATH_RE = re.compile(r"\bpath\s*[:=]", re.IGNORECASE)


# --- small helpers --------------------------------------------------------------------------
def _rng_int(*parts: object, mod: int) -> int:
    """Deterministic pick that does not depend on PYTHONHASHSEED."""
    return zlib.crc32("|".join(map(str, parts)).encode()) % mod


def _swap_words(text: str, pairs: list[tuple[str, str]]) -> str:
    """Swap both directions of each pair (word-boundary, case-preserving for the first letter)."""
    out = text
    for a, b in pairs:
        for x, y in ((a, b), (b, a)):
            out = re.sub(
                rf"\b{re.escape(x)}\b",
                lambda m, y=y: y.capitalize() if m.group(0)[0].isupper() else y,
                out,
                count=1,
            )
            if out != text:
                return out
    return out


def alter_sentence(quote: str, seed: str) -> str:
    """One deliberate meaning-bearing alteration of a verbatim quote (never a no-op)."""
    for a, b in _SWAPS:
        new = re.sub(rf"\b{a}\b", b, quote, count=1)
        if new != quote:
            return new
        new = re.sub(rf"\b{b}\b", a, quote, count=1)
        if new != quote:
            return new
    m = re.search(r"\d+(?:\.\d+)?", quote)
    if m:
        return quote[: m.start()] + str(round(float(m.group(0)) * 2 + 1, 1)) + quote[m.end() :]
    words = quote.split()
    i = max(1, len(words) // 2)
    words[i] = "never" if words[i] != "never" else "always"
    return " ".join(words)


def _other_doc_quote(doc: str, seed: str) -> str | None:
    from simulator.manuals import DOCS, find_quote, normalise, pages

    others = [d for d in DOCS if d != doc]
    d = others[_rng_int(seed, "doc", mod=len(others))]
    cands = []
    for pg, text in sorted(pages(d).items()):
        for line in normalise(text).split(". "):
            line = line.strip().rstrip(".")
            if 60 <= len(line) <= 220 and "|" not in line and "#" not in line:
                cands.append((pg, line + "."))
    cands = [c for c in cands if find_quote(d, c[0], c[1])] or [
        c for c in cands if find_quote(d, c[0], c[1].rstrip("."))
    ]
    if not cands:
        return None
    pg, line = cands[_rng_int(seed, "line", mod=len(cands))]
    return line if find_quote(d, pg, line) else line.rstrip(".")


# --- mutations ------------------------------------------------------------------------------
Mutation = tuple[str, dict]  # (variant label, mutated report dict)


def _locate(rep: dict, claim_id: str) -> tuple[dict, dict]:
    for h in rep["hypotheses"]:
        for c in h["claims"]:
            if c["claim_id"] == claim_id:
                return h, c
    raise KeyError(claim_id)


def mutations_for(
    rep: dict, hi: int, claim: dict, baseline: dict, seed: str
) -> list[tuple[str, str, dict]]:
    """``[(fault_id, variant, mutated_report)]`` for one baseline-passing claim. Each mutated report
    differs from ``rep`` in exactly that one claim (or, for the causal fault, its hypothesis chain)."""
    out: list[tuple[str, str, dict]] = []

    def with_claim(**changes: Any) -> dict:
        r = copy.deepcopy(rep)
        _, c = _locate(r, claim["claim_id"])
        c.update(changes)
        return r

    kind = claim["kind"]
    if kind == "numeric" and claim.get("asserted_value") not in (None, 0):
        v = float(claim["asserted_value"])
        for fid, fr in (("num_10", 0.10), ("num_25", 0.25)):
            for sgn in (1, -1):
                out.append((fid, f"{sgn * fr:+.0%}", with_claim(asserted_value=v * (1 + sgn * fr))))
        m = baseline.get("measured")
        # skip when the claim only passed through the verifier's sign relaxation (asserted and
        # matched leaf have opposite signs): negating it would hit the leaf exactly, not a fault
        if m is not None and m * v > 0:
            out.append(
                (
                    "num_sign",
                    "sign",
                    with_claim(
                        asserted_value=-v, text=_swap_words(claim.get("text", ""), _DIR_SWAPS)
                    ),
                )
            )
    elif kind == "temporal" and claim.get("asserted_ts"):
        ts = datetime.fromisoformat(str(claim["asserted_ts"]).replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=UTC)
        for fid, dt in (("ts_15m", timedelta(minutes=15)), ("ts_2h", timedelta(hours=2))):
            for sgn in (1, -1):
                new = (ts + sgn * dt).astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
                out.append((fid, f"{'+' if sgn > 0 else '-'}{dt}", with_claim(asserted_ts=new)))
    elif kind == "citation" and claim.get("citation"):
        from simulator.manuals import find_quote, locate_quote, pages

        cit = claim["citation"]
        alt = alter_sentence(cit["quote"], seed)
        out.append(("cite_sentence", "word", with_claim(citation={**cit, "quote": alt})))
        pgs = sorted(pages(cit["doc"]))
        for cand in (cit["page"] + 1, cit["page"] - 1):
            if cand in pgs and not find_quote(cit["doc"], cand, cit["quote"]):
                out.append(("cite_page", f"p.{cand}", with_claim(citation={**cit, "page": cand})))
                break
        other = _other_doc_quote(cit["doc"], f"{seed}|{claim['claim_id']}")
        if other and not locate_quote(cit["doc"], other):
            out.append(("cite_doc", "other doc", with_claim(citation={**cit, "quote": other})))
    elif kind == "causal_order":
        from agents.verifier import chain_assets

        h = rep["hypotheses"][hi]
        assets = chain_assets(h["causal_chain"])
        if len(assets) >= 2:
            r = copy.deepcopy(rep)
            rh = r["hypotheses"][hi]
            rh["causal_chain"] = list(reversed(h["causal_chain"]))
            rh["asset_id"] = assets[-1]
            out.append(("causal_reversed", "reversed", r))
    return out


def injected_claims(rep: dict, truth: Any | None, seed: str) -> list[tuple[str, str, dict, str]]:
    """Report copies with one *added* claim: ``[(fault_id, variant, report, claim_id)]``."""
    out: list[tuple[str, str, dict, str]] = []
    if not rep["hypotheses"]:
        return out
    real_eid = next(
        (e for h in rep["hypotheses"] for c in h["claims"] for e in c["evidence_ids"]), None
    )

    def add(claim: dict) -> dict:
        r = copy.deepcopy(rep)
        r["hypotheses"][0]["claims"].append(claim)
        return r

    base = {"asserted_value": None, "asserted_ts": None, "citation": None}
    fakes = {
        "numeric": {
            **base,
            "kind": "numeric",
            "asserted_value": 42.0,
            "text": "Mean value was 42.0. path: tags.cycle_time_s.mean",
        },
        "temporal": {
            **base,
            "kind": "temporal",
            "asserted_ts": "2026-08-20T10:00:00Z",
            "text": "The step began at 2026-08-20T10:00:00Z.",
        },
        "qualitative": {**base, "kind": "qualitative", "text": "The trend looks abnormal."},
    }
    for k, c in fakes.items():
        cid = f"zz_fab_{k}"
        out.append(
            (
                "fabricated_evidence",
                k,
                add({**c, "claim_id": cid, "evidence_ids": [FAKE_EVIDENCE_ID]}),
                cid,
            )
        )
    if truth is not None and real_eid is not None:
        for j, (doc, page, text) in enumerate(
            _false_premise_passages(truth, seed, rep["hypotheses"][0]["asset_id"])
        ):
            cid = f"zz_premise_{j}"
            claim = {
                **base,
                "claim_id": cid,
                "kind": "citation",
                "evidence_ids": [real_eid],
                "text": "The manual describes this failure pattern.",
                "citation": {"doc": doc, "page": page, "quote": text},
            }
            out.append(("premise_false", f"{doc} p.{page}", add(claim), cid))
    return out


PREMISE_SAMPLE = 8  # false-premise passages tried per run (seeded sample)


def _false_premise_passages(truth: Any, seed: str, hyp_asset: str) -> list[tuple[str, int, str]]:
    """Premise-bearing manual passages that are false for this scenario by construction: the
    passage diagnoses a different cause class than the injected one and none of the assets its doc
    covers is the true asset, in the true causal chain, or the asset the report blames."""
    from simulator import plant
    from simulator.manuals import locate_quote
    from simulator.manuals.premises import PASSAGES

    true_cls = getattr(truth.root_cause_class, "value", str(truth.root_cause_class))
    involved = {hyp_asset, truth.asset_id, *getattr(truth, "causal_chain", [])}
    cands = []
    for p in PASSAGES:
        if p.topic == true_cls:
            continue
        doc_assets = {a.asset_id for a in plant.ASSETS if a.manual == p.doc}
        if doc_assets & involved:
            continue
        pgs = locate_quote(p.doc, p.text)
        if pgs:
            cands.append((p.doc, pgs[0], p.text))
    cands.sort()
    k = min(PREMISE_SAMPLE, len(cands))
    picked: list[tuple[str, int, str]] = []
    pool = list(cands)
    for i in range(k):
        picked.append(pool.pop(_rng_int(seed, "prem", i, mod=len(pool))))
    return picked


# --- grading --------------------------------------------------------------------------------
class RunGrader:
    """Verifier verdicts for report variants of one run, on a ``ToolContext`` we build ourselves."""

    def __init__(self, evidence: list[dict], store: Any, sid: str, lock: Any = None) -> None:
        from agents.tools import EVIDENCE_PREFIX, ToolContext

        state = {EVIDENCE_PREFIX + e["evidence_id"]: checker._evidence(e) for e in evidence}
        extra = {"_lock": lock} if lock is not None else {}
        self.ctx = ToolContext(
            store=store, scenario_id=sid, state=state, llm=checker.no_spend_llm(), **extra
        )

    def verdicts(self, rep: dict) -> dict[str, dict]:
        from agents.schemas import RCAReport
        from agents.verifier import verify_report

        r = RCAReport.model_validate(rep)
        _, vs = verify_report(r, self.ctx, 0)
        flat = [c for h in r.hypotheses for c in h.claims]
        assert len(flat) == len(vs)
        return {
            c.claim_id: {"verdict": v.verdict, "reason": v.reason, "measured": v.measured_value}
            for c, v in zip(flat, vs, strict=True)
        }


def stress_run(
    rep: dict,
    evidence: list[dict],
    store: Any,
    sid: str,
    *,
    truth: Any | None = None,
    seed: int = 2026,
    lock: Any = None,
    on_trial: Callable[[], None] | None = None,
) -> dict:
    """``{"baseline": {...}, "trials": [...]}`` for one report."""
    g = RunGrader(evidence, store, sid, lock)
    base = g.verdicts(rep)
    claims = [(hi, c) for hi, h in enumerate(rep["hypotheses"]) for c in h["claims"]]
    trials: list[dict] = []

    def record(fault, variant, cid, kind, mrep, base_verdict="pass"):
        v = g.verdicts(mrep)[cid]
        trials.append(
            {
                "fault": fault,
                "variant": variant,
                "claim_id": cid,
                "kind": kind,
                "explicit_path": bool(_PATH_RE.search(_locate(mrep, cid)[1].get("text", ""))),
                "verdict": v["verdict"],
                "caught": v["verdict"] != "pass",
                "reason": v["reason"][:160],
            }
        )
        if on_trial:
            on_trial()

    for hi, c in claims:
        if base[c["claim_id"]]["verdict"] != "pass":
            continue
        for fault, variant, mrep in mutations_for(
            rep, hi, c, base[c["claim_id"]], f"{seed}|{sid}|{c['claim_id']}"
        ):
            record(fault, variant, c["claim_id"], c["kind"], mrep)
    for fault, variant, mrep, cid in injected_claims(rep, truth, f"{seed}|{sid}"):
        record(fault, variant, cid, "injected", mrep)
    return {
        "baseline": [
            {"claim_id": c["claim_id"], "kind": c["kind"], **base[c["claim_id"]]} for _, c in claims
        ],
        "trials": trials,
    }


# --- aggregation ----------------------------------------------------------------------------
def _iv(k: int, n: int) -> dict:
    i = stats.wilson(k, n)
    return {
        "k": k,
        "n": n,
        "value": None if i.p is None else round(i.p, 4),
        "lo": None if i.lo is None else round(i.lo, 4),
        "hi": None if i.hi is None else round(i.hi, 4),
    }


def aggregate(per_run: dict[str, dict], agreement: dict) -> dict:
    trials = [dict(t, sid=sid) for sid, r in per_run.items() for t in r["trials"]]
    by: dict[str, list[dict]] = defaultdict(list)
    for t in trials:
        by[t["fault"]].append(t)
    faults = {}
    for fid, (family, label) in FAULTS.items():
        ts = by.get(fid, [])
        caught = [t for t in ts if t["caught"]]
        row = {
            "family": family,
            "label": label,
            "catch": _iv(len(caught), len(ts)),
            "caught_fail": sum(t["verdict"] == "fail" for t in ts),
            "caught_unverifiable": sum(t["verdict"] == "unverifiable" for t in ts),
            "missed": len(ts) - len(caught),
            "n_runs": len({t["sid"] for t in ts}),
        }
        if family == "numeric":
            for tag, flag in (("explicit_path", True), ("implicit", False)):
                sub = [t for t in ts if t["explicit_path"] is flag]
                row[tag] = _iv(sum(t["caught"] for t in sub), len(sub))
        vs = defaultdict(lambda: [0, 0])
        for t in ts:
            vs[t["variant"]][1] += 1
            vs[t["variant"]][0] += t["caught"]
        row["by_variant"] = {k: _iv(a, b) for k, (a, b) in sorted(vs.items())}
        faults[fid] = row
    n_all = len(trials)
    n_caught = sum(t["caught"] for t in trials)
    base = [b for r in per_run.values() for b in r["baseline"]]
    fa_all = sum(b["verdict"] != "pass" for b in base)
    chk = [b for b in base if b["kind"] in CHECKED_KINDS]
    fa_chk = sum(b["verdict"] != "pass" for b in chk)
    return {
        "faults": faults,
        "overall": _iv(n_caught, n_all),
        "false_alarm_all_claims": _iv(fa_all, len(base)),
        "false_alarm_checkable_claims": _iv(fa_chk, len(chk)),
        "baseline_agreement_with_checker": agreement,
        "s2": {
            "catch": _iv(0, n_all),
            "note": "S2 shows every claim as verified (verifier always PASS), so it strikes "
            "through none of the mutated claims: catch 0%.",
        },
        "miss_patterns": {
            fid: dict(
                Counter(_pattern(t["reason"]) for t in by[fid] if not t["caught"]).most_common(8)
            )
            for fid in FAULTS
            if any(not t["caught"] for t in by.get(fid, []))
        },
        "false_alarm_examples": [
            {
                "sid": sid,
                "claim_id": b["claim_id"],
                "kind": b["kind"],
                "verdict": b["verdict"],
                "reason": b["reason"][:200],
            }
            for sid, r in per_run.items()
            for b in r["baseline"]
            if b["verdict"] != "pass"
        ],
        "missed_examples": [
            {k: t[k] for k in ("sid", "fault", "variant", "claim_id", "reason")}
            for t in trials
            if not t["caught"]
        ][:300],
    }


# --- outputs --------------------------------------------------------------------------------
def _pct(iv: dict, ci: bool = True) -> str:
    if iv["n"] == 0:
        return "n/a"
    s = f"{100 * iv['value']:.1f}%"
    return s + (f" [{100 * iv['lo']:.1f}, {100 * iv['hi']:.1f}]" if ci else "")


def _floor_pct(iv: dict) -> str:
    """Whole percent, but never show 100% when something was missed."""
    v = 100 * iv["value"]
    return f"{v:.1f}%" if iv["k"] < iv["n"] and round(v) == 100 else f"{v:.0f}%"


def _pattern(reason: str) -> str:
    """A reason with numbers/timestamps/ids removed, so misses group by *why* they passed."""
    r = reason.split(" (verifier")[0]
    r = re.sub(r"ev_[a-z_]+_\d+", "<ev>", r)
    r = re.sub(r"\d{4}-\d\d-\d\dT[\d:]+Z", "<ts>", r)
    r = re.sub(r"-?\d+(?:\.\d+)?", "#", r)
    return r[:110]


def markdown(s: dict) -> str:
    L = [
        "# Verifier fault injection (offline, $0, no Gemini)",
        "",
        f"Source run: `{s['source_run']}` ({s['n_runs']} S1 runs with a report, "
        f"{s['n_trials']} injected faults, seed {s['seed']}). Caught = the mutated claim's verdict is "
        "`fail` or `unverifiable` (struck through in the UI). 95% Wilson intervals; trials are "
        "clustered by run, so read the intervals as optimistic.",
        "",
        "| Fault | n | Caught [95% CI] | fail | unverifiable | missed |",
        "|---|---:|---|---:|---:|---:|",
    ]
    for f in s["faults"].values():
        L.append(
            f"| {f['label']} | {f['catch']['n']} | {_pct(f['catch'])} | {f['caught_fail']} | "
            f"{f['caught_unverifiable']} | {f['missed']} |"
        )
    o = s["overall"]
    L.append(f"| **All faults** | {o['n']} | **{_pct(o)}** | | | {o['n'] - o['k']} |")
    L += [
        "",
        f"False-alarm rate on the unmutated claims: {_pct(s['false_alarm_all_claims'])} of all "
        f"claims ({s['false_alarm_all_claims']['k']}/{s['false_alarm_all_claims']['n']}); "
        f"{_pct(s['false_alarm_checkable_claims'])} of checkable claims "
        f"({s['false_alarm_checkable_claims']['k']}/{s['false_alarm_checkable_claims']['n']}). "
        f"Baseline verdicts equal `eval/checker.py` on {s['baseline_agreement_with_checker']['equal']}"
        f"/{s['baseline_agreement_with_checker']['total']} claims.",
        "",
        f"S2 comparison: {s['s2']['note']} ({s['s2']['catch']['k']}/{s['s2']['catch']['n']} "
        "caught.)",
        "",
        "Numeric detail (caught, explicit `path:` vs implicit search over all leaves):",
        "",
    ]
    for fid in ("num_10", "num_25", "num_sign"):
        f = s["faults"][fid]
        L.append(
            f"- {f['label']}: explicit path {_pct(f['explicit_path'])} (n={f['explicit_path']['n']}), "
            f"implicit {_pct(f['implicit'])} (n={f['implicit']['n']})"
        )
    L += ["", "Why the misses passed (grouped, numbers and timestamps removed):", ""]
    for fid, pats in s["miss_patterns"].items():
        L.append(f"- {s['faults'][fid]['label']}:")
        L += [f"  - {n} x {p}" for p, n in pats.items()]
    L += [
        "",
        "Limitations: the faults are synthetic and one at a time; the real error distribution of the "
        "model differs. Only claims that pass at baseline are attacked. Premise-false citations are "
        "labelled false by construction (the passage diagnoses a different cause class on assets "
        "outside the true chain and not the asset the report blames). Faults alter the structured field the verifier reads (and, for the "
        "sign flip, the direction words in the text), not free text elsewhere.",
        "",
    ]
    return "\n".join(L)


def render_png(s: dict, path: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle

    ink, muted, blue, red = "#16202a", "#5a6772", "#1f6feb", "#cc3300"
    fig = plt.figure(figsize=(19.2, 10.8), dpi=100, facecolor="white")
    fig.text(
        0.025,
        0.955,
        "Andon Agent: does the verifier catch a checkable error?",
        fontsize=27,
        fontweight="bold",
        color=ink,
        va="center",
    )
    fig.text(
        0.025,
        0.915,
        "Manufacturing: Intelligent Operations & Industrial Efficiency  ·  one injected fault at "
        "a time into real S1 reports; offline, $0",
        fontsize=15,
        color=muted,
        va="center",
    )
    ax = fig.add_axes((0.30, 0.20, 0.40, 0.64))
    rows = list(s["faults"].values())
    ys = list(range(len(rows)))[::-1]
    for y, f in zip(ys, rows, strict=True):
        iv = f["catch"]
        if iv["n"] == 0:
            continue
        v, lo, hi = 100 * iv["value"], 100 * iv["lo"], 100 * iv["hi"]
        ax.barh(y, v, color=blue if v >= 99.5 or v >= 90 else red, height=0.62)
        ax.errorbar(v, y, xerr=[[v - lo], [hi - v]], color=ink, capsize=5, lw=2)
    ax.set_yticks(ys)
    ax.set_yticklabels([f["label"] for f in rows], fontsize=15, color=ink)
    ax.set_xlim(0, 118)
    ax.set_xticks([0, 25, 50, 75, 100])
    ax.set_xticklabels(["0%", "25%", "50%", "75%", "100%"], fontsize=14)
    ax.set_xlabel("Injected faults struck through by the verifier (95% Wilson CI)", fontsize=15)
    ax.axvline(0, color=ink, lw=1)
    for sp in ("top", "right"):
        ax.spines[sp].set_visible(False)
    for y, f in zip(ys, rows, strict=True):
        iv = f["catch"]
        ax.text(
            101,
            y,
            "n/a" if iv["n"] == 0 else f"{_floor_pct(iv)}  ({iv['k']}/{iv['n']})",
            fontsize=14,
            va="center",
            color=ink,
        )
    ax.set_title("S1 verifier", loc="left", fontsize=17, fontweight="bold", color=ink)

    # right-hand panel
    panel = fig.add_axes((0.755, 0.20, 0.225, 0.64))
    panel.set_axis_off()
    panel.set_xlim(0, 1)
    panel.set_ylim(0, 1)
    o, fa = s["overall"], s["false_alarm_all_claims"]
    panel.add_patch(Rectangle((0, 0.62), 1, 0.38, color="#eaf2ff", zorder=0))
    panel.text(0.04, 0.95, "Overall catch rate", fontsize=15, color=muted, va="top")
    panel.text(0.04, 0.88, f"{100 * o['value']:.1f}%", fontsize=44, fontweight="bold",
               color=blue, va="top")  # fmt: skip
    panel.text(0.04, 0.70, f"[{100 * o['lo']:.1f}, {100 * o['hi']:.1f}]  n = {o['n']}",
               fontsize=15, color=ink, va="top")  # fmt: skip
    panel.add_patch(Rectangle((0, 0.34), 1, 0.24, color="#f1f4f8", zorder=0))
    panel.text(0.04, 0.565, "False alarms on unmutated claims", fontsize=14, color=muted, va="top")
    panel.text(0.04, 0.50, f"{100 * fa['value']:.1f}%  ({fa['k']}/{fa['n']})", fontsize=24,
               fontweight="bold", color=ink, va="top")  # fmt: skip
    panel.add_patch(Rectangle((0, 0.04), 1, 0.26, color="#fdecea", zorder=0))
    panel.text(0.04, 0.285, "S2 (no verifier)", fontsize=14, color=muted, va="top")
    panel.text(0.04, 0.225, "shows all mutated claims\nas verified: catch 0%", fontsize=18,
               fontweight="bold", color=red, va="top", linespacing=1.3)  # fmt: skip
    fig.text(
        0.025,
        0.075,
        "Caught = claim verdict fail or unverifiable (struck through). Faults are synthetic, one per "
        "report, injected into claims that passed re-check; the model's real error distribution "
        "differs. Not tuned.",
        fontsize=13,
        color=muted,
        va="center",
    )
    fig.text(
        0.025,
        0.045,
        f"Source: {s['source_run']} S1 runs ({s['n_runs']}), seed {s['seed']}. 95% Wilson intervals, "
        "trials clustered by run. Real signals mapped onto a synthetic line.",
        fontsize=13,
        color=muted,
        va="center",
    )
    fig.savefig(path, dpi=100, facecolor="white")
    plt.close(fig)


# --- driver ---------------------------------------------------------------------------------
def run(run_dir: Path, db: Path, seed: int, out: Path, scenarios_dir: Path, limit: int | None,
        progress: bool = True) -> dict:  # fmt: skip
    from simulator.load import DuckDBStore

    rows = [
        r
        for r in load_results(run_dir / "results.jsonl").values()
        if r["system"] == "S1"
        and r.get("status") == "ok"
        and (r.get("report") or {}).get("hypotheses")
    ]
    rows.sort(key=lambda r: (r["scenario_id"], r["repeat"]))
    if limit:
        rows = rows[:limit]
    truths = sets.load_truth([r["scenario_id"] for r in rows], scenarios_dir)
    per_run: dict[str, dict] = {}
    equal = total = 0
    for i, r in enumerate(rows, 1):
        sid = r["scenario_id"]
        store = _open_store(DuckDBStore, db)
        try:
            lock = threading.RLock()
            res = stress_run(r["report"], r["evidence"], store, sid, truth=truths[sid], seed=seed,
                             lock=lock)  # fmt: skip
            ind = checker.check_report(r["report"], r["evidence"], store, sid, lock=lock)
        finally:
            store.close()
        b = {x["claim_id"]: x["verdict"] for x in res["baseline"]}
        for c in ind["claims"]:
            total += 1
            equal += b.get(c["claim_id"]) == c["verdict"]
        per_run[f"{sid}|{r['repeat']}"] = res
        if progress:
            print(
                f"[{i}/{len(rows)}] {sid} r{r['repeat']}: {len(res['trials'])} faults", flush=True
            )
    summary = aggregate(per_run, {"equal": equal, "total": total})
    summary.update(
        source_run=run_dir.name,
        seed=seed,
        n_runs=len(per_run),
        n_trials=summary["overall"]["n"],
        git_sha=_git_sha(),
        git_dirty_paths=_git_dirty(),
    )
    out.mkdir(parents=True, exist_ok=True)
    (out / "summary.json").write_text(json.dumps(summary, indent=1) + "\n", "utf-8")
    (out / "table.md").write_text(markdown(summary), "utf-8")
    render_png(summary, out / "stress.png")
    return summary


def _open_store(cls: Any, db: Path, tries: int = 6) -> Any:
    """Open the local DuckDB; it globs data/scenarios, which another process may be rewriting."""
    import time

    for i in range(tries):
        try:
            return cls(str(db))
        except Exception:
            if i == tries - 1:
                raise
            time.sleep(10)


def _git_dirty() -> list[str]:
    import subprocess

    try:
        out = subprocess.run(["git", "status", "--short", "agents", "analytics", "simulator"],
                             cwd=ROOT, capture_output=True, text=True, timeout=10).stdout  # fmt: skip
        return [ln[3:] for ln in out.splitlines()]
    except Exception:
        return []


def _git_sha() -> str | None:
    import subprocess

    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True,
                              text=True, timeout=10).stdout.strip() or None  # fmt: skip
    except Exception:
        return None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="python -m eval.stress_verifier", description=__doc__.split("\n\n")[0]
    )
    ap.add_argument("--run", default=str(DEFAULT_RUN))
    ap.add_argument("--db", default=str(DEFAULT_DB))
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--scenarios-dir", default=str(sets.DEFAULT_SCENARIOS))
    ap.add_argument("--seed", type=int, default=2026)
    ap.add_argument("--limit", type=int, default=None, help="first N runs only (smoke test)")
    a = ap.parse_args(argv)
    s = run(Path(a.run), Path(a.db), a.seed, Path(a.out), Path(a.scenarios_dir), a.limit)
    print(markdown(s))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
