"""Every metric of EVAL_PLAN §3, computed from ``results.jsonl`` rows and ground truth.

Grading is a pure function of (row, truth, independent check): ``grade_run``. Aggregation is
``summarize``; paired tests are ``compare``; run-to-run spread is ``variance``. Conventions (all
stated again in the report footnote / README):

* **Failed runs are misses.** A row with ``status == "error"`` (or no report) counts as incorrect
  in every accuracy denominator and is reported as ``n_error``.
* **Top-1** = top hypothesis ``cause_class`` equals truth AND ``asset_id`` equals truth (truth
  ``asset_id`` is None only for ``no_fault``, then only the class must match). **Top-3** = any of
  the <= 3 hypotheses matches. For ``dual_fault`` the truth is the primary fault; finding the
  secondary class in the top 3 is reported separately.
* **Abstention** = status ``insufficient_evidence``, or no hypotheses, or the top hypothesis is
  ``no_fault`` / ``sensor_drift``. *Recall* = abstains on ``no_fault`` scenarios. *Precision* =
  of all abstentions, the share where the truth really is a non-machine case (``no_fault`` or
  ``sensor_drift``). *False abstention* = abstains although a machine fault was injected.
* **Imperfection false alarm** = top hypothesis is ``sensor_drift`` although the truth is a
  machine fault (the injected gaps/stuck values/chatter were blamed instead). Denominator: runs on
  machine-fault scenarios.
* **Unsupported claim** = a claim of the final report that the independent checker
  (``eval/checker.py``) does not grade ``pass`` (fail or unverifiable), pooled over claims; the
  run-level companion is the share of runs with at least one. Claims are clustered within runs, so
  the pooled Wilson interval is optimistic: read it together with the run-level rate.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Iterable, Sequence
from typing import Any

from eval import stats
from eval.sets import HELDOUT, set_of
from simulator import plant
from simulator.truth_schema import GroundTruth

NON_MACHINE = frozenset({"no_fault", "sensor_drift"})
ABSTAIN_CLASSES = NON_MACHINE
_ASSET_IDS = sorted((a.asset_id for a in plant.ASSETS), key=len, reverse=True)
_ASSET_RE = re.compile("|".join(re.escape(a) for a in _ASSET_IDS))
NON_CHECKABLE = frozenset({"qualitative"})


# --- helpers -----------------------------------------------------------------------------------
def _hyps(row: dict) -> list[dict]:
    rep = row.get("report") or {}
    return list(rep.get("hypotheses") or [])


def _cls(h: dict) -> str:
    c = h.get("cause_class")
    return getattr(c, "value", c) or ""


def matches(h: dict, truth: GroundTruth) -> bool:
    if _cls(h) != truth.root_cause_class.value:
        return False
    return truth.asset_id is None or h.get("asset_id") == truth.asset_id


def chain_assets(chain: Iterable[str]) -> list[str]:
    """Asset ids mentioned in a causal chain, in order, de-duplicated (asset-level chain)."""
    seen: list[str] = []
    for step in chain:
        for m in _ASSET_RE.findall(str(step)):
            if m not in seen:
                seen.append(m)
    return seen


def set_f1(pred: Sequence[str], truth: Sequence[str]) -> float:
    p, t = set(pred), set(truth)
    if not p and not t:
        return 1.0
    tp = len(p & t)
    if tp == 0:
        return 0.0
    prec, rec = tp / len(p), tp / len(t)
    return 2 * prec * rec / (prec + rec)


def abstained(row: dict) -> bool:
    rep = row.get("report")
    if rep is None:
        return False  # a failed run gave no answer at all; it is a miss, not an abstention
    hs = _hyps(row)
    return rep.get("status") == "insufficient_evidence" or not hs or _cls(hs[0]) in ABSTAIN_CLASSES


# --- one run -----------------------------------------------------------------------------------
def grade_run(row: dict, truth: GroundTruth, independent: dict | None = None) -> dict:
    """Flat dict of per-run outcomes (no aggregation). ``independent`` is the checker's output."""
    hs = _hyps(row)
    ok = row.get("status") == "ok" and row.get("report") is not None
    top = hs[0] if hs else None
    top1 = bool(ok and top and matches(top, truth))
    top3 = bool(ok and any(matches(h, truth) for h in hs[:3]))
    machine_fault = truth.root_cause_class.value not in NON_MACHINE
    truth_chain = list(truth.causal_chain)
    chain_f1 = None
    if ok and truth_chain:
        chain_f1 = set_f1(chain_assets(top.get("causal_chain") or []) if top else [], truth_chain)
    sec = truth.secondary_cause.value if truth.secondary_cause else None
    ab = abstained(row)
    indep = independent or row.get("independent") or {}
    claims = indep.get("claims") or []
    sys_verdicts = (row.get("verifier") or {}).get("claim_verdicts") or {}
    unsupported = [c for c in claims if c["verdict"] != "pass"]
    checkable = [c for c in claims if c.get("kind") not in NON_CHECKABLE]
    cost = row.get("cost") or {}
    ver = row.get("verifier") or {}
    return {
        "run_key": row["run_key"],
        "system": row["system"],
        "scenario_id": row["scenario_id"],
        "repeat": row.get("repeat", 0),
        "set": set_of(row["scenario_id"]),
        "heldout": row["scenario_id"] in HELDOUT,
        "variant": truth.variant,
        "truth_class": truth.root_cause_class.value,
        "truth_asset": truth.asset_id,
        "status": "ok" if ok else "error",
        "pred_class": _cls(top) if top else None,
        "pred_asset": top.get("asset_id") if top else None,
        "top1": top1,
        "top3": top3,
        "chain_f1": chain_f1,
        "secondary_in_top3": (any(_cls(h) == sec for h in hs[:3]) if (ok and sec) else None),
        "abstained": ab,
        "machine_fault": machine_fault,
        "imperfection_false_alarm": (
            bool(top and _cls(top) == "sensor_drift") if (ok and machine_fault) else None
        ),
        "confidence": (
            float(top["confidence"]) if top and top.get("confidence") is not None else None
        ),
        "n_claims": len(claims),
        "n_unsupported": len(unsupported),
        "n_checkable": len(checkable),
        "n_unsupported_checkable": sum(1 for c in checkable if c["verdict"] != "pass"),
        "n_sys_pass": sum(1 for c in claims if sys_verdicts.get(c["claim_id"]) == "pass"),
        "n_unflagged_unsupported": sum(
            1 for c in unsupported if sys_verdicts.get(c["claim_id"]) == "pass"
        ),
        "checker_error": indep.get("error"),
        "verifier_catches": ver.get("catches", 0),
        "verifier_flagged_final": ver.get("flagged_final", 0),
        "verifier_iterations": ver.get("iterations", 0),
        "duration_s": row.get("duration_s"),
        "cost_usd": cost.get("usd", 0.0),
    }


# --- aggregation -------------------------------------------------------------------------------
def _rate(rows: Sequence[dict], key: str, where: str | None = None) -> stats.Interval:
    sel = [r for r in rows if (where is None or r.get(where))]
    return stats.wilson(sum(1 for r in sel if r[key]), len(sel))


def _by(rows: Sequence[dict], key: str) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        out[str(r[key])].append(r)
    return dict(sorted(out.items()))


def summarize(rows: Sequence[dict], *, slices: bool = True) -> dict:
    """All EVAL_PLAN §3 metrics for one system on one scenario set (graded rows, one per run)."""
    n = len(rows)
    ok = [r for r in rows if r["status"] == "ok"]
    out: dict[str, Any] = {
        "n": n,
        "n_error": n - len(ok),
        "top1": stats.wilson(sum(r["top1"] for r in rows), n),
        "top3": stats.wilson(sum(r["top3"] for r in rows), n),
    }
    cf = [r["chain_f1"] for r in rows if r["chain_f1"] is not None]
    # failed runs have chain_f1 None; count them as 0 for scenarios that have a truth chain
    cf_all = [r["chain_f1"] if r["chain_f1"] is not None else 0.0 for r in rows if _has_chain(r)]
    out["chain_f1"] = {"mean": _mean(cf_all), "n": len(cf_all), "n_scored": len(cf)}
    nf = [r for r in rows if r["truth_class"] == "no_fault"]
    ab = [r for r in rows if r["abstained"]]
    mf = [r for r in rows if r["machine_fault"]]
    out["abstention"] = {
        "recall": stats.wilson(sum(r["abstained"] for r in nf), len(nf)),
        "precision": stats.wilson(sum(1 for r in ab if not r["machine_fault"]), len(ab)),
        "false_abstention": stats.wilson(sum(r["abstained"] for r in mf), len(mf)),
    }
    rh = [r for r in rows if r["variant"] == "red_herring"]
    out["red_herring_top1"] = stats.wilson(sum(r["top1"] for r in rh), len(rh))
    fa = [r for r in rows if r["imperfection_false_alarm"] is not None]
    out["imperfection_false_alarm"] = stats.wilson(
        sum(1 for r in fa if r["imperfection_false_alarm"]), len(fa)
    )
    claimed = [r for r in rows if r["n_claims"] > 0]
    nc, nu = sum(r["n_claims"] for r in rows), sum(r["n_unsupported"] for r in rows)
    nck, nuck = sum(r["n_checkable"] for r in rows), sum(r["n_unsupported_checkable"] for r in rows)
    out["unsupported_claim_rate"] = stats.wilson(nu, nc)
    out["unsupported_claim_rate_checkable"] = stats.wilson(nuck, nck)
    out["unsupported_run_rate"] = stats.wilson(
        sum(1 for r in claimed if r["n_unsupported"] > 0), len(claimed)
    )
    spass = sum(r["n_sys_pass"] for r in rows)
    out["unflagged_unsupported_rate"] = stats.wilson(
        sum(r["n_unflagged_unsupported"] for r in rows), spass
    )  # of claims the system's own verifier passed, how many the checker rejects (S1 only)
    out["claims"] = {
        "n_claims": nc,
        "n_unsupported": nu,
        "n_checkable": nck,
        "n_checker_errors": sum(1 for r in rows if r["checker_error"]),
    }
    out["verifier"] = {
        "catches_total": sum(r["verifier_catches"] for r in rows),
        "catches_mean_per_run": _mean([r["verifier_catches"] for r in rows]),
        "runs_with_catch": sum(1 for r in rows if r["verifier_catches"] > 0),
        "flagged_final_total": sum(r["verifier_flagged_final"] for r in rows),
        "iterations_mean": _mean([r["verifier_iterations"] for r in ok]),
    }
    cal = [(r["confidence"], r["top1"]) for r in ok if r["confidence"] is not None]
    conf, corr = [c for c, _ in cal], [o for _, o in cal]
    bins = stats.reliability_bins(conf, corr)
    out["calibration"] = {
        "n": len(cal),
        "brier": stats.brier(conf, corr),
        "bins": bins,
        "ece": stats.expected_calibration_error(bins),
        "n_without_confidence": len(ok) - len(cal),
    }
    times = [r["duration_s"] for r in ok if r["duration_s"] is not None]
    out["time_s"] = {
        "median": stats.median(times),
        "p95": stats.percentile(times, 95),
        "n": len(times),
    }
    costs = [r["cost_usd"] for r in rows]
    out["cost"] = {
        "mean_usd": _mean(costs),
        "total_usd": sum(costs),
        "median_usd": stats.median(costs),
    }
    sec = [r for r in rows if r["secondary_in_top3"] is not None]
    out["dual_fault_secondary_in_top3"] = stats.wilson(
        sum(1 for r in sec if r["secondary_in_top3"]), len(sec)
    )
    if slices:
        out["by_variant"] = {k: summarize(v, slices=False) for k, v in _by(rows, "variant").items()}
        out["by_cause"] = {k: _mini(v) for k, v in _by(rows, "truth_class").items()}
        out["by_heldout"] = {
            "heldout": _mini([r for r in rows if r["heldout"]]),
            "dev": _mini([r for r in rows if not r["heldout"]]),
        }
    return out


def _mini(rows: Sequence[dict]) -> dict:
    return {
        "n": len(rows),
        "top1": stats.wilson(sum(r["top1"] for r in rows), len(rows)),
        "top3": stats.wilson(sum(r["top3"] for r in rows), len(rows)),
    }


def _has_chain(r: dict) -> bool:
    return r["truth_class"] != "no_fault"  # truth chains are empty only for no_fault in practice


def _mean(xs: Sequence[float]) -> float | None:
    return sum(xs) / len(xs) if xs else None


# --- paired / repeats --------------------------------------------------------------------------
def headline(graded: Sequence[dict]) -> list[dict]:
    """One run per (system, scenario): the lowest repeat index. Repeats > 0 feed ``variance`` only."""
    best: dict[tuple[str, str], dict] = {}
    for r in graded:
        k = (r["system"], r["scenario_id"])
        if k not in best or r["repeat"] < best[k]["repeat"]:
            best[k] = r
    return list(best.values())


def compare(headline_rows: Sequence[dict], a: str, b: str, metric: str = "top1") -> dict | None:
    """Exact McNemar for systems ``a`` vs ``b`` over scenarios both ran. None if no overlap."""
    ra = {r["scenario_id"]: bool(r[metric]) for r in headline_rows if r["system"] == a}
    rb = {r["scenario_id"]: bool(r[metric]) for r in headline_rows if r["system"] == b}
    if not (ra.keys() & rb.keys()):
        return None
    m = stats.paired(ra, rb)
    d = m.to_dict()
    d.update(
        {
            "a": a,
            "b": b,
            "metric": metric,
            "a_rate": sum(ra[k] for k in ra.keys() & rb.keys()) / m.n,
            "b_rate": sum(rb[k] for k in ra.keys() & rb.keys()) / m.n,
            "significant_at_0.05": m.p < 0.05,
        }
    )
    return d


def variance(graded: Sequence[dict], system: str, ids: Iterable[str] | None = None) -> dict | None:
    """Spread of top-1 accuracy over repeats of ``system`` on the same scenarios."""
    sel = [r for r in graded if r["system"] == system and (ids is None or r["scenario_id"] in ids)]
    reps = sorted({r["repeat"] for r in sel})
    if len(reps) < 2:
        return None
    full = set.intersection(*({r["scenario_id"] for r in sel if r["repeat"] == k} for k in reps))
    per = {k: [r for r in sel if r["repeat"] == k and r["scenario_id"] in full] for k in reps}
    accs = [sum(r["top1"] for r in per[k]) / len(per[k]) for k in reps] if full else []
    unstable = sorted(
        s
        for s in full
        if len({next(r["top1"] for r in per[k] if r["scenario_id"] == s) for k in reps}) > 1
    )
    return {
        "system": system,
        "repeats": len(reps),
        "n_scenarios": len(full),
        "top1_by_repeat": [round(a, 4) for a in accs],
        "spread": stats.spread(accs),
        "unstable_scenarios": unstable,
    }
