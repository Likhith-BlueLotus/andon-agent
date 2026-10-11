"""Citation applicability: does the cited passage's premise hold in this incident? (ADR-025)

The Verifier's citation rule used to stop at "the quote is verbatim on that page". A verbatim
quote whose premise is false is still misleading (R002: "a sustained fall in header pressure
while the compressor runs loaded..." while the header never fell). Passages that state a
measurable premise carry it as metadata (:mod:`simulator.manuals.premises`); this module checks
each premise deterministically, in plain Python, with the same read-only tools the agents use:

1. **Gathered evidence first.** Every ``detect_change_points`` / ``query_telemetry`` evidence of
   this incident on that asset and tag is re-run (the Verifier's reproducibility rule; a
   non-reproducible item is ignored here) and tested. Any item showing the premise -> met.
2. **Verifier probe.** Otherwise the Verifier runs the check itself on a fixed window ending at
   the stop (:data:`WINDOW_S` for change points; the last :data:`LEVEL_WINDOW_S` for levels and
   the loaded state, then the change points). The probe records
   nothing in session state. Met -> met; not shown -> not met (the gathered items, if any, are
   named in the reason too).
3. A probe that cannot run (no data, tool error), or a direction premise where no change point
   is detected at all, leaves the premise unknown (absence of a detected change is not proof of
   no change), unless gathered evidence already showed it contradicted. A change point in the
   *opposite* direction, or a measured level on the wrong side of the limit, is a contradiction.

A claim whose premises are all met passes; any premise not met fails it ("premise not met: ...",
``measured_value`` = what was measured); otherwise it is unverifiable (shown struck through,
never dropped). Being lenient on "met" (any evidence, either direction of a window choice) and
strict only when the deterministic probe agrees is deliberate: a false FAIL costs a revision
round, a false PASS puts an inapplicable manual passage in front of a human.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from agents import tools as T
from agents.schemas import Evidence
from simulator import plant
from simulator.manuals.premises import LOADED_MIN_FRACTION, Premise

WINDOW_S = 24 * 3600
LEVEL_WINDOW_S = 3600
CP_EXPECT = frozenset({"fall", "rise", "step"})
LEVEL_EXPECT = frozenset({"low", "high"})


@dataclass(frozen=True)
class Outcome:
    state: str  # "met" | "not_met" | "unknown"
    detail: str
    measured: float | None = None


def _iso(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def candidate_assets(p: Premise, doc: str, hyp_asset: str | None) -> list[str]:
    """Assets the premise is checked on (see ``simulator.manuals.premises``)."""
    if p.asset is not None:
        return [p.asset]
    have = [a.asset_id for a in plant.ASSETS
            if a.manual == doc and any(t.tag == p.tag for t in a.tags)]  # fmt: skip
    if hyp_asset in have:
        return [hyp_asset]  # type: ignore[list-item]
    return have


# --- evaluation of one summary ----------------------------------------------------------------
def threshold(p: Premise, asset: str) -> float | None:
    """The low/high limit a level premise is tested against (spec normal range by default)."""
    if p.value is not None:
        return p.value
    spec = plant.tag_spec(asset, p.tag)
    return spec.normal_lo if p.expect == "low" else spec.normal_hi


def _beyond(p: Premise, v: Any, lim: float) -> bool:
    return isinstance(v, int | float) and (v < lim if p.expect == "low" else v > lim)


def _cp_eval(p: Premise, asset: str, summary: Mapping[str, Any], artefact: Any) -> Outcome:
    cps = [cp for cp in summary.get("change_points") or [] if not artefact(summary, cp)]
    win = f"{summary.get('t0')}..{summary.get('t1')}"
    if p.expect in LEVEL_EXPECT or p.expect == "loaded":
        lim = LOADED_MIN_FRACTION if p.expect == "loaded" else threshold(p, asset)
        if lim is None:
            return Outcome("unknown", f"no {p.expect} limit for {p.tag}")
        side = ">=" if p.expect == "loaded" else "<" if p.expect == "low" else ">"
        for cp in cps:
            for key in ("after_mean", "peak_mean"):
                v = cp.get(key)
                ok = (
                    (isinstance(v, int | float) and v >= lim)
                    if p.expect == "loaded"
                    else _beyond(p, v, lim)
                )
                if ok:
                    return Outcome(
                        "met", f"change point {cp.get('ts')} to {key} {v} ({side} {lim:g})", v
                    )
        levels = [
            cp.get("after_mean") for cp in cps if isinstance(cp.get("after_mean"), int | float)
        ]
        if not levels:
            return Outcome("not_met", f"no change point in {win}", None)
        v = min(levels) if p.expect == "low" else max(levels)
        return Outcome("not_met", f"{len(cps)} change point(s) in {win}, new levels "
                                  f"{', '.join(f'{x:g}' for x in levels)} (needs {side} {lim:g})", v)  # fmt: skip
    want = {"fall": ("down",), "rise": ("up",), "step": ("up", "down")}[p.expect]
    hit = [cp for cp in cps if cp.get("direction") in want]
    if hit:
        cp = max(hit, key=lambda c: abs(c.get("magnitude_pct") or c.get("delta") or 0))
        return Outcome("met", f"change point {cp.get('ts')} {cp.get('direction')} "
                              f"{cp.get('magnitude_pct')}% ({cp.get('shape')})", cp.get("delta"))  # fmt: skip
    if cps:
        cp = max(cps, key=lambda c: abs(c.get("delta") or 0))
        return Outcome("not_met", f"{len(cps)} change point(s) in {win}, none {'falling' if p.expect == 'fall' else 'rising'}; "
                                  f"largest {cp.get('direction')} {cp.get('magnitude_pct')}% at {cp.get('ts')}", cp.get("delta"))  # fmt: skip
    # No change point at all is absence of evidence, not evidence of absence: the detector's
    # minimum effect size can miss short or small real changes (R009-R011: 10-19 min faults).
    return Outcome("unknown", f"no change point detected in {win}")


def _tag_eval(p: Premise, asset: str, summary: Mapping[str, Any]) -> Outcome | None:
    st = (summary.get("tags") or {}).get(p.tag)
    if not isinstance(st, Mapping) or st.get("status") != "ok":
        return None
    win = f"{summary.get('t0')}..{summary.get('t1')}"
    if p.expect == "loaded":
        lf = st.get("loaded_fraction")
        if lf is None:
            return None
        ok = lf >= LOADED_MIN_FRACTION
        return Outcome("met" if ok else "not_met", f"loaded_fraction {lf} in {win} (needs >= {LOADED_MIN_FRACTION})", lf)  # fmt: skip
    if p.expect in LEVEL_EXPECT:
        lim = threshold(p, asset)
        if lim is None or st.get("mean") is None:
            return None
        side = "<" if p.expect == "low" else ">"
        ok = _beyond(p, st["mean"], lim)
        return Outcome("met" if ok else "not_met", f"mean {st['mean']} {st.get('unit', '')} in {win} "
                       f"(min {st.get('min')}, max {st.get('max')}; needs mean {side} {lim:g})", st["mean"])  # fmt: skip
    return None


def _uses(p: Premise) -> tuple[str, ...]:
    if p.expect in CP_EXPECT:
        return ("detect_change_points",)
    return ("query_telemetry", "detect_change_points")  # low, high, loaded


def _eval_summary(p: Premise, asset: str, tool: str, summary: Mapping[str, Any],
                  artefact: Any) -> Outcome | None:  # fmt: skip
    if tool == "detect_change_points":
        return _cp_eval(p, asset, summary, artefact)
    if tool == "query_telemetry":
        return _tag_eval(p, asset, summary)
    return None


# --- one premise on one asset -----------------------------------------------------------------
def _gathered(evidence: Iterable[Evidence], p: Premise, asset: str) -> list[Evidence]:
    out = []
    for ev in evidence:
        if ev.tool not in _uses(p) or ev.args.get("asset_id") != asset:
            continue
        if ev.tool == "detect_change_points" and ev.args.get("tag") != p.tag:
            continue
        if ev.tool == "query_telemetry" and p.tag not in (ev.args.get("tags") or []):
            continue
        out.append(ev)
    return out


def _probe_args(ctx: T.ToolContext, p: Premise, asset: str) -> list[tuple[str, dict[str, Any]]]:
    stop = T.stop_epoch(ctx)
    t1, t0 = _iso(stop), _iso(stop - WINDOW_S)
    cp = ("detect_change_points", {"asset_id": asset, "tag": p.tag, "t0": t0, "t1": t1})
    if p.expect in CP_EXPECT:
        return [cp]
    last = ("query_telemetry", {"asset_id": asset, "tags": [p.tag],
                                "t0": _iso(stop - LEVEL_WINDOW_S), "t1": t1})  # fmt: skip
    return [last, cp]


def eval_on_asset(p: Premise, asset: str, idx: Any, artefact: Any) -> Outcome:
    """``idx`` is the Verifier's evidence index (``all_evidence()``, ``rerun(eid)``, ``probe``)."""
    seen: list[str] = []
    for ev in _gathered(idx.all_evidence(), p, asset):
        rr = idx.rerun(ev.evidence_id)
        if not rr.ok or rr.summary is None:
            continue
        o = _eval_summary(p, asset, ev.tool, rr.summary, artefact)
        if o is None or o.state == "unknown":
            continue
        if o.state == "met":
            return Outcome("met", f"{ev.evidence_id}: {o.detail}", o.measured)
        seen.append(f"{ev.evidence_id}: {o.detail}")
    outs: list[Outcome] = []
    try:
        probes = _probe_args(idx.ctx, p, asset)
    except Exception as exc:  # no stop event: nothing to anchor a probe on
        probes = []
        outs.append(Outcome("unknown", f"verifier check could not run ({type(exc).__name__})"))
    for tool, args in probes:
        res = idx.probe(tool, args)
        if "error" in res:
            outs.append(
                Outcome("unknown", f"verifier check {tool} failed ({res['error'].get('code')})")
            )
            continue
        o = _eval_summary(p, asset, tool, res["summary"], artefact)
        if o is None:
            outs.append(Outcome("unknown", f"verifier check {tool} returned no data for {p.tag}"))
            continue
        if o.state == "met":
            return Outcome("met", f"verifier check: {o.detail}", o.measured)
        outs.append(Outcome(o.state, f"verifier check: {o.detail}", o.measured))
    no = [o for o in outs if o.state == "not_met"]
    if no:
        detail = "; ".join(o.detail for o in no) + (
            f"; gathered: {' | '.join(seen)}" if seen else ""
        )
        return Outcome("not_met", detail, no[0].measured)
    if seen:  # probe unavailable, gathered evidence says no
        return Outcome("not_met", " | ".join(seen))
    return outs[-1] if outs else Outcome("unknown", "no evidence for this premise")


def check(premises: list[Premise], doc: str, hyp_asset: str | None, idx: Any,
          artefact: Any) -> tuple[str, str, float | None]:  # fmt: skip
    """``(verdict, reason, measured_value)`` for a citation whose quote carries ``premises``."""
    met: list[str] = []
    unknown: list[str] = []
    for p in premises:
        assets = candidate_assets(p, doc, hyp_asset)
        if not assets:
            unknown.append(f"{p.describe()}: no asset of the {doc} manual has tag {p.tag}")
            continue
        outs = [(a, eval_on_asset(p, a, idx, artefact)) for a in assets]
        hit = next(((a, o) for a, o in outs if o.state == "met"), None)
        if hit:
            met.append(f"{p.describe(hit[0])} ({hit[1].detail})")
            continue
        if all(o.state == "not_met" for _, o in outs):
            a, o = outs[0]
            return ("fail", f"premise not met: {p.negated(a if len(outs) == 1 else '/'.join(x for x, _ in outs))} "
                            f"(measured: {o.detail})", o.measured)  # fmt: skip
        a, o = next((a, o) for a, o in outs if o.state == "unknown")
        unknown.append(f"{p.describe(a)}: {o.detail}")
    if unknown:
        return "unverifiable", "premise could not be checked: " + "; ".join(unknown), None
    return "pass", "premises met: " + "; ".join(met), None
