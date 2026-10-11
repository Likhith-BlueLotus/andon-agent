"""Deterministic Verifier (AGENTS_SPEC §5, CLAUDE.md hard rules 4 and 5).

Plain Python: no LLM, no network except what :func:`agents.tools.rerun` needs. Every claim of
every hypothesis in the Judge's ``RCAReport`` gets a :class:`ClaimVerdict`; the overall verdict
is ``PASS`` iff the *top* hypothesis has zero failed claims and at least
:data:`MIN_PASSING_CHECKABLE` distinct passing non-qualitative claims.

Checks applied to every claim, in order (the first failure wins):

1. **Duplicate claim id** -> fail (the UI keys verdicts by ``claim_id``; ids must be unique across
   the whole report).
2. **Unknown evidence id** -> fail. Every cited id must exist as ``state["evidence:<id>"]``.
3. **Provenance rule** -> fail if the text says the data is real / from the plant / field data
   (:data:`REAL_DATA_RE`, case-insensitive, negations such as "not real data" or "synthetic plant
   data" excluded) and none of the cited evidence has a ``ProvenanceRef`` with ``real: true``.
   Bare "measured" is *not* flagged: it is ordinary analytic language for any sensor value.
4. **Kind rule** (below).

Kind rules:

* ``numeric`` — each cited evidence is re-run (:func:`rerun`); a re-run summary that differs from
  the stored one fails the claim ("evidence not reproducible"). The asserted value is resolved
  against the numeric leaves of the re-run summary:

  - *Explicit path* (preferred; the Judge is told to use it): the claim text contains
    ``path: <field path>`` (or ``path=``), e.g. ``path: tags.header_pressure_bar.mean`` or
    ``path: change_points[0].magnitude_pct`` (``.0.`` and ``[0]`` are equivalent). Only that leaf
    is compared; a path that resolves in none of the cited evidence fails.
  - *Implicit*: otherwise every numeric leaf is a candidate, except catalogue spec limits
    (``normal_range``, ``normal_lo``, ``normal_hi``), which are not measurements.

  A leaf matches when ``abs(measured - asserted) / max(abs(measured), 1e-9) <= VERIFIER_NUMERIC_
  REL_TOL``. Two relaxations, both explicit: *percent vs fraction* (asserted x100 or /100) only if
  the text mentions ``%``/"percent" or the leaf name contains pct/percent/fraction/ratio; *sign*
  (asserted ``12`` vs leaf ``-12``) only if the text's direction words agree with the leaf's sign
  ("dropped 12 %" for ``-12``) and do not also contain the opposite direction. No match -> fail with
  ``measured_value`` = the closest leaf and a reason naming its evidence id and path.
* ``temporal`` — ``asserted_ts`` (naive = UTC) must lie within ``VERIFIER_TEMPORAL_TOL_S`` of an
  event timestamp in the re-run summary: change point ``ts``/``end_ts``, alarm ``ts``/
  ``first_ts``/``last_ts``, ``stop_ts``, anomaly ``peak_bin_start``, note/work-order times.
  Window bounds (``t0``/``t1``, ``history_*``, ``since``) are not events. ``measured_value`` is
  the signed offset in seconds (asserted minus closest event).
* ``citation`` — ``citation`` must be present and :func:`simulator.manuals.find_quote` true on the
  stated page (whitespace-normalised; quotes under 20 characters never pass). A quote found on a
  different page fails with the pages it is on.
* ``causal_order`` — assets are read from ``hypothesis.causal_chain`` (asset ids, or station codes
  such as ``ST30``); the root is ``hypothesis.asset_id`` (or the first chain asset). Onsets come
  from the claim's cited ``detect_change_points`` evidence (re-run): the earliest change point
  per asset that is not a data artefact. Root without onset evidence, or no downstream asset with
  onset evidence -> unverifiable (not fail). A downstream onset earlier than the root onset by more
  than ``VERIFIER_TEMPORAL_TOL_S`` -> fail ("reversed"). Downstream assets without evidence are
  named as unchecked in the reason.
* ``qualitative`` — ``pass`` if it cites >= 1 evidence id (all existing), else ``unverifiable``. A
  qualitative pass never counts toward the PASS threshold.

Data-artefact rule (numeric and temporal): a match inside a change point flagged ``data_issue``
(stuck value) or ``across_gap``, or whose onset lies inside a reported stuck period (the tool only
flags change points at the stuck *edges*), or a timestamp that only matches a data-quality gap /
stuck-period boundary, is not support -> fail. When a value matches both an artefact and a clean
leaf, the clean leaf wins.

Numeric or temporal claims citing no evidence fail (a number must come from a tool). A re-run
that hits a transient error (``tool_failed`` / ``raw_unavailable``) makes the claim unverifiable;
any other re-run error fails it.

The ADK side is :class:`Verifier` (a ``BaseAgent`` inside ``LoopAgent("rca_loop")``); see its
docstring for the state keys and events it writes.
"""

from __future__ import annotations

import asyncio
import json
import math
import re
from collections.abc import AsyncGenerator, Callable, Iterator, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from google.adk.agents import BaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event, EventActions
from pydantic import ConfigDict, ValidationError

import config
from agents import loto_policy
from agents.schemas import (
    Claim,
    ClaimVerdict,
    Evidence,
    Hypothesis,
    RCAReport,
    VerifierVerdict,
    WorkOrder,
)
from agents.tools import EVIDENCE_PREFIX, ToolContext, rerun
from simulator import plant
from simulator.manuals import DOCS, MIN_QUOTE_CHARS, find_quote, locate_quote, normalise

MIN_PASSING_CHECKABLE = 2  # distinct passing non-qualitative claims needed on the top hypothesis
TRANSIENT_RERUN_ERRORS = frozenset({"tool_failed", "raw_unavailable"})
SPEC_LIMIT_KEYS = frozenset({"normal_range", "normal_lo", "normal_hi"})
EVENT_TS_KEYS = frozenset(
    {
        "ts",
        "end_ts",
        "stop_ts",
        "first_ts",
        "last_ts",
        "peak_bin_start",
        "date",
        "first_snapshot",
        "last_snapshot",
    }
)
PCT_LEAF_HINTS = ("pct", "percent", "fraction", "ratio")

# --- provenance rule ------------------------------------------------------------------------
_DATA_NOUN = r"(?:data|signals?|telemetry|measurements?|readings?|recordings?|sensors?|values?|failures?|faults?)"
REAL_DATA_RE = re.compile(
    rf"""
      \breal(?:[-\s]world)?[-\s]+(?:(?:plant|field|sensor|machine|factory|production)[-\s]+)?{_DATA_NOUN}\b
    | \b(?:data|signals?|telemetry|readings?|measurements?)\s+(?:is|are|was|were)\s+(?:\w+\s+)?real\b
    | \bmeasured\s+(?:on|at|in|from)\s+(?:the\s+|a\s+|an\s+)?(?:real\s+|actual\s+)?
        (?:plant|line|shop[-\s]?floor|factory|machine|field|site)\b
    | \bfrom\s+(?:the|a|an)\s+(?:real\s+|actual\s+|operating\s+)?(?:plant|factory|shop[-\s]?floor)\b
    | \b(?:field|plant|factory|production)[-\s]+data\b
    | \bactual\s+(?:plant|field|production|factory)\b
    """,
    re.IGNORECASE | re.VERBOSE,
)
_NEGATION_BEFORE = re.compile(
    r"(?:\bnot|\bnon|\bno|\bnever|n't|\bsynthetic|\bsimulated|\bfake)[\s-]+(?:(?:a|an|the)\s+)?$",
    re.IGNORECASE,
)

# --- numeric helpers -------------------------------------------------------------------------
_PATH_RE = re.compile(r"\bpath\s*[:=]\s*`?([A-Za-z_][\w.\[\]\-]*[\w\]])`?", re.IGNORECASE)
_DOWN_RE = re.compile(
    r"\b(?:drop\w*|fell|fall\w*|decreas\w*|declin\w*|lower\w*|down|reduc\w*|sag\w*|lost|loss)\b",
    re.IGNORECASE,
)
_UP_RE = re.compile(
    r"\b(?:rise|rises|rising|rose|risen|increas\w*|higher|up|climb\w*|grew|grow\w*|gain\w*|jump\w*)\b",
    re.IGNORECASE,
)
_PCT_TEXT_RE = re.compile(r"%|\bpercent\b|\bper\s?cent\b", re.IGNORECASE)
_STATION_RE = re.compile(r"\b(ST\d{2}|UT-?[A-Z]{3})\b")
_CP_RE = re.compile(r"^(.*?change_points\[\d+\])")


# =============================================================================================
# Summary traversal
# =============================================================================================
def _leaves(obj: Any, path: str = "") -> Iterator[tuple[str, Any]]:
    """``(path, value)`` for every scalar leaf; paths look like ``tags.x.mean`` / ``rows[3].ts``."""
    if isinstance(obj, Mapping):
        for k, v in obj.items():
            yield from _leaves(v, f"{path}.{k}" if path else str(k))
    elif isinstance(obj, list | tuple):
        for i, v in enumerate(obj):
            yield from _leaves(v, f"{path}[{i}]")
    else:
        yield path, obj


def _canon(path: str) -> str:
    """``a[0].b`` and ``a.0.b`` compare equal."""
    return re.sub(r"\[(\d+)\]", r".\1", path).strip(".")


def _segments(path: str) -> list[str]:
    return _canon(path).split(".")


def _is_number(v: Any) -> bool:
    return isinstance(v, int | float) and not isinstance(v, bool) and math.isfinite(v)


def _get(obj: Any, path: str) -> Any:
    cur = obj
    for seg in _segments(path):
        if isinstance(cur, Mapping) and seg in cur:
            cur = cur[seg]
        elif isinstance(cur, list) and seg.isdigit() and int(seg) < len(cur):
            cur = cur[int(seg)]
        else:
            raise KeyError(path)
    return cur


def _parse_ts(v: Any) -> datetime | None:
    if isinstance(v, datetime):
        return v.replace(tzinfo=UTC) if v.tzinfo is None else v.astimezone(UTC)
    if not isinstance(v, str) or len(v) < 10 or not v[:4].isdigit():
        return None
    s = v.strip()
    if s.endswith(("Z", "z")):
        s = s[:-1] + "+00:00"
    try:
        d = datetime.fromisoformat(s)
    except ValueError:
        return None
    return d.replace(tzinfo=UTC) if d.tzinfo is None else d.astimezone(UTC)


def _stuck_intervals(summary: Mapping[str, Any]) -> list[tuple[float, float]]:
    dq = summary.get("data_quality") or {}
    out = []
    for p in dq.get("stuck_periods") or []:
        st = _parse_ts(p.get("start"))
        if st is not None:
            out.append((st.timestamp(), st.timestamp() + float(p.get("duration_s") or 0)))
    return out


def _cp_artefact(summary: Mapping[str, Any], cp: Mapping[str, Any]) -> str | None:
    """Why a change point is a data artefact rather than machine behaviour (None if it is not)."""
    if cp.get("data_issue"):
        return f"change point flagged data_issue={cp['data_issue']}"
    if cp.get("across_gap"):
        return "change point spans a data gap (across_gap)"
    ts = _parse_ts(cp.get("ts"))
    if ts is not None:
        slack = float(summary.get("bin_s") or 0)
        t = ts.timestamp()
        for a, b in _stuck_intervals(summary):
            if a - slack <= t <= b + slack:
                return "change point lies inside a stuck-value period"
    return None


def _leaf_artefact(summary: Mapping[str, Any], path: str) -> str | None:
    m = _CP_RE.match(path)
    if m:
        try:
            cp = _get(summary, m.group(1))
        except KeyError:
            return None
        if isinstance(cp, Mapping):
            return _cp_artefact(summary, cp)
    return None


# =============================================================================================
# Evidence access and re-runs
# =============================================================================================
@dataclass
class _Rerun:
    ok: bool
    summary: dict[str, Any] | None
    verdict: str  # "pass" (usable) | "fail" | "unverifiable"
    reason: str


class _EvidenceIndex:
    """Stored evidence (from ``state['evidence:<id>']``) plus a per-report re-run cache."""

    def __init__(self, ctx: ToolContext) -> None:
        self.ctx = ctx
        self._ev: dict[str, Evidence | None] = {}
        self._reruns: dict[str, _Rerun] = {}

    def get(self, evidence_id: str) -> Evidence | None:
        if evidence_id not in self._ev:
            key = EVIDENCE_PREFIX + evidence_id
            ev = None
            if isinstance(evidence_id, str) and key in self.ctx.state:
                v = self.ctx.state[key]
                try:
                    ev = v if isinstance(v, Evidence) else Evidence.model_validate(v)
                except ValidationError:
                    ev = None
            self._ev[evidence_id] = ev
        return self._ev[evidence_id]

    def rerun(self, evidence_id: str) -> _Rerun:
        if evidence_id in self._reruns:
            return self._reruns[evidence_id]
        ev = self.get(evidence_id)
        if ev is None:
            r = _Rerun(False, None, "fail", f"unknown evidence_id {evidence_id}")
        else:
            out = rerun(self.ctx, ev)
            if "error" in out:
                code = out["error"].get("code", "error")
                verdict = "unverifiable" if code in TRANSIENT_RERUN_ERRORS else "fail"
                r = _Rerun(False, None, verdict, f"{evidence_id} could not be re-run ({code})")
            elif _dump(out["summary"]) != _dump(ev.summary) or out["provenance"] != [
                p.model_dump(mode="json") for p in ev.provenance
            ]:
                r = _Rerun(False, None, "fail", f"evidence not reproducible: re-running {evidence_id} gave a different result")  # fmt: skip
            else:
                r = _Rerun(True, out["summary"], "pass", "")
        self._reruns[evidence_id] = r
        return r


def _dump(x: Any) -> str:
    return json.dumps(x, sort_keys=True, default=str)


# =============================================================================================
# Per-kind checks: each returns (verdict, reason, measured_value)
# =============================================================================================
Result = tuple[str, str, float | None]


def _fmt(v: float) -> str:
    return f"{v:.6g}"


def _direction_ok(text: str, measured: float) -> bool:
    down, up = bool(_DOWN_RE.search(text)), bool(_UP_RE.search(text))
    return (down and not up) if measured < 0 else (up and not down)


def _compare(asserted: float, measured: float, text: str, path: str) -> tuple[float, str]:
    """Smallest relative error over the allowed interpretations, and which one it was."""
    tol_den = max(abs(measured), 1e-9)
    leaf = _segments(path)[-1].lower() if path else ""
    variants: list[tuple[float, str]] = [(asserted, "")]
    if _PCT_TEXT_RE.search(text) or any(h in leaf for h in PCT_LEAF_HINTS):
        variants += [(asserted / 100.0, "percent read as fraction"),
                     (asserted * 100.0, "fraction read as percent")]  # fmt: skip
    best = (math.inf, "")
    for v, note in variants:
        best = min(best, (abs(measured - v) / tol_den, note))
        if v != 0 and measured != 0 and (v > 0) != (measured > 0) and _direction_ok(text, measured):
            n2 = (note + "; " if note else "") + "sign from direction words"
            best = min(best, (abs(abs(measured) - abs(v)) / tol_den, n2))
    return best


def _check_numeric(claim: Claim, idx: _EvidenceIndex) -> Result:
    if claim.asserted_value is None or not math.isfinite(claim.asserted_value):
        return "unverifiable", "numeric claim has no asserted_value", None
    if not claim.evidence_ids:
        return "fail", "numeric claim cites no evidence (numbers must come from a tool)", None
    asserted = float(claim.asserted_value)
    tol = config.VERIFIER_NUMERIC_REL_TOL
    explicit = _PATH_RE.search(claim.text)
    want = _canon(explicit.group(1)) if explicit else None
    clean: list[tuple[float, str, str, float, str]] = []  # (rel, eid, path, value, note)
    artefact: list[tuple[float, str, str, float, str, str]] = []
    closest: tuple[float, str, str, float] | None = None
    blocked: Result | None = None
    for eid in dict.fromkeys(claim.evidence_ids):
        rr = idx.rerun(eid)
        if not rr.ok:
            if rr.verdict == "fail":
                return "fail", rr.reason, None
            blocked = blocked or (rr.verdict, rr.reason, None)
            continue
        assert rr.summary is not None
        for path, v in _leaves(rr.summary):
            if not _is_number(v):
                continue
            if want is not None:
                if _canon(path) != want:
                    continue
            elif any(s in SPEC_LIMIT_KEYS for s in _segments(path)):
                continue
            rel, note = _compare(asserted, float(v), claim.text, path)
            if closest is None or rel < closest[0]:
                closest = (rel, eid, path, float(v))
            if rel <= tol:
                why = _leaf_artefact(rr.summary, path)
                if why:
                    artefact.append((rel, eid, path, float(v), note, why))
                else:
                    clean.append((rel, eid, path, float(v), note))
    if clean:
        rel, eid, path, v, note = min(clean)
        extra = f" ({note})" if note else ""
        return "pass", f"{eid}:{path} = {_fmt(v)} matches {_fmt(asserted)} (rel err {rel:.3f}){extra}", v  # fmt: skip
    if artefact:
        rel, eid, path, v, _, why = min(artefact)
        return "fail", f"{eid}:{path} = {_fmt(v)} matches, but {why}: a data artefact, not support", v  # fmt: skip
    if blocked:
        return blocked
    if closest is None:
        if want is not None:
            return "fail", f"path {want!r} is not a numeric field of the cited evidence", None
        return "fail", "cited evidence has no numeric fields", None
    rel, eid, path, v = closest
    return "fail", f"asserted {_fmt(asserted)} but closest measured value is {eid}:{path} = {_fmt(v)} (rel err {rel:.3f} > {tol})", v  # fmt: skip


def _event_times(summary: Mapping[str, Any]) -> Iterator[tuple[str, datetime, str | None]]:
    """``(path, ts, artefact_reason)`` for event timestamps and data-quality boundaries."""
    for path, v in _leaves(summary):
        segs = _segments(path)
        key = segs[-1]
        if "data_quality" in segs:
            if key == "start":
                ts = _parse_ts(v)
                if ts is None:
                    continue
                kind = "gap" if "gaps" in segs else "stuck-value period"
                yield path, ts, f"timestamp is a data-quality {kind} boundary"
                parent = _get(summary, path.rsplit(".", 1)[0])
                if isinstance(parent, Mapping) and _is_number(parent.get("duration_s")):
                    end = datetime.fromtimestamp(ts.timestamp() + parent["duration_s"], UTC)
                    yield path + "+duration_s", end, f"timestamp is a data-quality {kind} boundary"
            continue
        if key not in EVENT_TS_KEYS:
            continue
        ts = _parse_ts(v)
        if ts is not None:
            yield path, ts, _leaf_artefact(summary, path)


def _check_temporal(claim: Claim, idx: _EvidenceIndex) -> Result:
    if claim.asserted_ts is None:
        return "unverifiable", "temporal claim has no asserted_ts", None
    if not claim.evidence_ids:
        return "fail", "temporal claim cites no evidence", None
    at = _parse_ts(claim.asserted_ts)
    assert at is not None
    tol = config.VERIFIER_TEMPORAL_TOL_S
    best_clean: tuple[float, str, str, datetime] | None = None
    best_art: tuple[float, str, str, datetime, str] | None = None
    closest: tuple[float, float, str, str, datetime] | None = None
    blocked: Result | None = None
    for eid in dict.fromkeys(claim.evidence_ids):
        rr = idx.rerun(eid)
        if not rr.ok:
            if rr.verdict == "fail":
                return "fail", rr.reason, None
            blocked = blocked or (rr.verdict, rr.reason, None)
            continue
        assert rr.summary is not None
        for path, ts, why in _event_times(rr.summary):
            off = (at - ts).total_seconds()
            if closest is None or abs(off) < closest[0]:
                closest = (abs(off), off, eid, path, ts)
            if abs(off) <= tol:
                if why:
                    if best_art is None or abs(off) < best_art[0]:
                        best_art = (abs(off), eid, path, ts, why)
                elif best_clean is None or abs(off) < best_clean[0]:
                    best_clean = (abs(off), eid, path, ts)
    iso = at.strftime("%Y-%m-%dT%H:%M:%SZ")
    if best_clean:
        _, eid, path, ts = best_clean
        off = (at - ts).total_seconds()
        return "pass", f"{iso} is {off:+.0f} s from {eid}:{path} ({ts:%Y-%m-%dT%H:%M:%SZ})", off
    if best_art:
        _, eid, path, ts, why = best_art
        return "fail", f"{iso} matches {eid}:{path} but {why}: a data artefact, not support", (at - ts).total_seconds()  # fmt: skip
    if blocked:
        return blocked
    if closest is None:
        return "fail", "cited evidence contains no event timestamps", None
    _, off, eid, path, ts = closest
    return "fail", f"{iso} is {off:+.0f} s from the closest event {eid}:{path} ({ts:%Y-%m-%dT%H:%M:%SZ}); tolerance ±{tol} s", off  # fmt: skip


def _check_citation(claim: Claim) -> Result:
    c = claim.citation
    if c is None:
        return "fail", "citation claim has no citation", None
    if c.doc not in DOCS:
        return "fail", f"unknown manual {c.doc!r} (known: {', '.join(DOCS)})", None
    if len(normalise(c.quote)) < MIN_QUOTE_CHARS:
        return "fail", f"quote shorter than {MIN_QUOTE_CHARS} characters proves nothing", None
    if find_quote(c.doc, c.page, c.quote):
        return "pass", f"quote found verbatim in {c.doc} p.{c.page}", None
    elsewhere = locate_quote(c.doc, c.quote)
    if elsewhere:
        return "fail", f"quote is in {c.doc} on page(s) {elsewhere}, not page {c.page}", None
    return "fail", f"quote not found verbatim in {c.doc} (fabricated or reworded)", None


_STATION_TO_ASSET = {a.station.replace("-", ""): a.asset_id for a in plant.ASSETS}


def chain_assets(chain: list[str]) -> list[str]:
    """Known asset ids named in a causal chain, in order, deduplicated. Steps may name an asset
    id (``UT-AIR``) or a station code (``ST30``, ``UTAIR``); other words are ignored."""
    out: list[str] = []
    ids = sorted(plant.ASSET_BY_ID, key=len, reverse=True)
    for step in chain:
        found: list[tuple[int, str]] = []
        spans: list[tuple[int, int]] = []
        for aid in ids:
            for m in re.finditer(rf"(?<![\w-]){re.escape(aid)}(?![\w-])", step):
                found.append((m.start(), aid))
                spans.append(m.span())
        for m in _STATION_RE.finditer(step):
            if any(a <= m.start() < b for a, b in spans):
                continue  # part of a full asset id already matched
            aid = _STATION_TO_ASSET.get(m.group(1).replace("-", ""))
            if aid:
                found.append((m.start(), aid))
        for _, aid in sorted(found):
            if aid not in out:
                out.append(aid)
    return out


def _check_causal(claim: Claim, hyp: Hypothesis, idx: _EvidenceIndex) -> Result:
    assets = chain_assets(hyp.causal_chain)
    root = hyp.asset_id if hyp.asset_id in plant.ASSET_BY_ID else (assets[0] if assets else None)
    if root is None:
        return "unverifiable", "causal_chain names no known asset", None
    downstream = [a for a in assets if a != root]
    if not downstream:
        return "unverifiable", f"causal_chain has no asset downstream of {root}", None
    onsets: dict[str, tuple[datetime, str]] = {}
    blocked: Result | None = None
    for eid in dict.fromkeys(claim.evidence_ids):
        ev = idx.get(eid)
        if ev is None or ev.tool != "detect_change_points":
            continue
        rr = idx.rerun(eid)
        if not rr.ok:
            if rr.verdict == "fail":
                return "fail", rr.reason, None
            blocked = blocked or (rr.verdict, rr.reason, None)
            continue
        assert rr.summary is not None
        asset = str(ev.args.get("asset_id"))
        for cp in rr.summary.get("change_points") or []:
            ts = _parse_ts(cp.get("ts"))
            if ts is None or _cp_artefact(rr.summary, cp):
                continue
            if asset not in onsets or ts < onsets[asset][0]:
                onsets[asset] = (ts, f"{eid} ({ev.args.get('tag')})")
    if blocked and root not in onsets:
        return blocked
    if root not in onsets:
        return "unverifiable", f"no cited change-point evidence with an onset at root {root}", None
    checked = [a for a in downstream if a in onsets]
    unchecked = [a for a in downstream if a not in onsets]
    if not checked:
        return "unverifiable", f"no cited change-point evidence for downstream asset(s) {', '.join(downstream)}", None  # fmt: skip
    r_ts, r_src = onsets[root]
    tol = config.VERIFIER_TEMPORAL_TOL_S
    lines = []
    for a in checked:
        ts, src = onsets[a]
        lead = (ts - r_ts).total_seconds()
        if lead < -tol:
            return "fail", (f"reversed: {a} onset {ts:%Y-%m-%dT%H:%M:%SZ} [{src}] is {-lead:.0f} s "
                            f"before root {root} onset {r_ts:%Y-%m-%dT%H:%M:%SZ} [{r_src}]"), lead  # fmt: skip
        lines.append(f"{a} +{lead:.0f} s")
    note = f"; unchecked (no onset evidence): {', '.join(unchecked)}" if unchecked else ""
    return "pass", f"root {root} onset {r_ts:%Y-%m-%dT%H:%M:%SZ} precedes {', '.join(lines)}{note}", None  # fmt: skip


def real_data_phrase(text: str) -> str | None:
    """The phrase that asserts the data is real, or None (negated phrases are ignored)."""
    for m in REAL_DATA_RE.finditer(text):
        if not _NEGATION_BEFORE.search(text[max(0, m.start() - 16) : m.start()]):
            return m.group(0)
    return None


def _check_claim(claim: Claim, hyp: Hypothesis, idx: _EvidenceIndex) -> Result:
    unknown = [e for e in claim.evidence_ids if idx.get(e) is None]
    if unknown:
        return "fail", f"unknown evidence_id(s): {', '.join(unknown)}", None
    phrase = real_data_phrase(claim.text)
    if phrase is not None:
        evs = [idx.get(e) for e in claim.evidence_ids]
        if not any(p.real for ev in evs if ev is not None for p in ev.provenance):
            return "fail", (f"claim says the data is real ({phrase!r}) but none of the cited evidence "
                            "has real provenance; this line is synthetic unless marked real"), None  # fmt: skip
    if claim.kind == "numeric":
        return _check_numeric(claim, idx)
    if claim.kind == "temporal":
        return _check_temporal(claim, idx)
    if claim.kind == "citation":
        return _check_citation(claim)
    if claim.kind == "causal_order":
        return _check_causal(claim, hyp, idx)
    if claim.evidence_ids:
        return "pass", "qualitative: cites existing evidence (does not count toward PASS)", None
    return "unverifiable", "qualitative claim cites no evidence", None


# =============================================================================================
# Public API
# =============================================================================================
def _signature(c: Claim) -> tuple:
    """What makes two claims the same check (duplicates count once toward PASS)."""
    cit = (c.citation.doc, c.citation.page, normalise(c.citation.quote)) if c.citation else None
    ts = _parse_ts(c.asserted_ts) if c.asserted_ts else None
    return (c.kind, tuple(sorted(set(c.evidence_ids))), c.asserted_value, ts, cit)


def top_hypothesis_stats(report: RCAReport, verdicts: list[ClaimVerdict]) -> dict[str, int]:
    """``{passed_checkable, failed, unverifiable, qualitative_passed}`` for hypotheses[0]."""
    out = {"passed_checkable": 0, "failed": 0, "unverifiable": 0, "qualitative_passed": 0}
    if not report.hypotheses:
        return out
    n_top = len(report.hypotheses[0].claims)
    seen: set[tuple] = set()
    for claim, v in zip(report.hypotheses[0].claims, verdicts[:n_top], strict=True):
        if v.verdict == "fail":
            out["failed"] += 1
        elif v.verdict == "unverifiable":
            out["unverifiable"] += 1
        elif claim.kind == "qualitative":
            out["qualitative_passed"] += 1
        elif (sig := _signature(claim)) not in seen:
            seen.add(sig)
            out["passed_checkable"] += 1
    return out


def verify_report(
    report: RCAReport, ctx: ToolContext, iteration: int
) -> tuple[VerifierVerdict, list[ClaimVerdict]]:
    """Verdict for every claim of every hypothesis (report order) and the overall verdict.

    PASS iff the top hypothesis has zero failed claims and >= ``MIN_PASSING_CHECKABLE`` distinct
    passing non-qualitative claims. A report without hypotheses is FAIL. ``ctx.state`` must hold the
    ``evidence:<id>`` keys; re-runs use ``ctx.store`` and never write to state.
    """
    idx = _EvidenceIndex(ctx)
    verdicts: list[ClaimVerdict] = []
    seen_ids: set[str] = set()
    for hyp in report.hypotheses:
        for claim in hyp.claims:
            if claim.claim_id in seen_ids:
                res: Result = ("fail", f"duplicate claim_id {claim.claim_id!r}; claim ids must be unique across the report", None)  # fmt: skip
            else:
                try:
                    res = _check_claim(claim, hyp, idx)
                except Exception as exc:  # a verifier bug must never pass a claim
                    res = (
                        "unverifiable",
                        f"verifier error: {type(exc).__name__}: {exc}"[:300],
                        None,
                    )
            seen_ids.add(claim.claim_id)
            v, reason, measured = res
            verdicts.append(ClaimVerdict(claim_id=claim.claim_id, verdict=v, reason=reason,  # type: ignore[arg-type]
                                         measured_value=measured))  # fmt: skip
    st = top_hypothesis_stats(report, verdicts)
    ok = bool(report.hypotheses) and st["failed"] == 0
    ok = ok and st["passed_checkable"] >= MIN_PASSING_CHECKABLE
    overall = "PASS" if ok else "FAIL"
    return VerifierVerdict(overall=overall, claims=verdicts, iteration=iteration), verdicts


def failure_summary(report: RCAReport, verdicts: list[ClaimVerdict]) -> str:
    """One line on why the overall verdict is FAIL ("" on PASS-worthy stats)."""
    if not report.hypotheses:
        return "report has no hypotheses"
    st = top_hypothesis_stats(report, verdicts)
    parts = []
    if st["failed"]:
        parts.append(f"top hypothesis has {st['failed']} failed claim(s)")
    if st["passed_checkable"] < MIN_PASSING_CHECKABLE:
        parts.append(f"top hypothesis has {st['passed_checkable']} passing non-qualitative claim(s); "
                     f"needs {MIN_PASSING_CHECKABLE}")  # fmt: skip
    return "; ".join(parts)


def rejected_claims(verdicts: list[ClaimVerdict], report: RCAReport) -> list[dict[str, Any]]:
    """Feedback for the Judge's next iteration: every claim that did not pass (fail and
    unverifiable), in report order, plus a report-level entry (``claim_id="_report"``) when the
    top hypothesis lacks enough passing non-qualitative claims."""
    claims = [c for h in report.hypotheses for c in h.claims]
    out: list[dict[str, Any]] = []
    for c, v in zip(claims, verdicts, strict=True):
        if v.verdict == "pass":
            continue
        out.append({"claim_id": c.claim_id, "text": c.text, "kind": c.kind, "verdict": v.verdict,
                    "reason": v.reason, "measured_value": v.measured_value})  # fmt: skip
    st = top_hypothesis_stats(report, verdicts)
    if not report.hypotheses or st["passed_checkable"] < MIN_PASSING_CHECKABLE:
        out.append({"claim_id": "_report", "text": "", "kind": "report", "verdict": "fail",
                    "reason": failure_summary(report, verdicts), "measured_value": None})  # fmt: skip
    return out


_SAFETY_WORDS = re.compile(
    r"\b(?:lock\s*out|lockout|tag\s*out|tagout|loto|de-?energi[sz]\w*|isolat\w*|zero[-\s]energy|"
    r"bleed\w*\s+(?:to\s+)?zero|stored\s+energy|ppe)\b",
    re.IGNORECASE,
)


def check_safety_steps(work_order: WorkOrder) -> list[str]:
    """Drafter post-check (hard rule 5). Errors (empty list = OK) for:

    * a safety step (``is_safety``) without a citation;
    * a safety step whose text differs from ``citation.quote`` (whitespace / Markdown marks /
      typographic quotes normalised, wording, case and punctuation exact) — i.e. reworded;
    * a safety step whose quote is not verbatim on the cited page of the cited manual;
    * a step *not* marked safety whose text reads like an energy-control step (lockout, tagout,
      isolation, de-energise, stored energy, PPE) unless it is itself a verified verbatim quote —
      relabelling is not a way around the verbatim rule;
    * duplicate step order numbers;
    * a missing **mandatory** energy-control step of the asset's manual (``agents.loto_policy``,
      ADR-025): the drafter inserts them, this is defence in depth.
    """
    errs: list[str] = []
    orders = [s.order for s in work_order.steps]
    dup = sorted({o for o in orders if orders.count(o) > 1})
    if dup:
        errs.append(f"duplicate step order(s) {dup}")
    present = {normalise(s.text) for s in work_order.steps if s.is_safety}
    doc = loto_policy.manual_for(work_order.asset_id)
    for text in loto_policy.mandatory_texts(work_order.asset_id):
        if normalise(text) not in present:
            errs.append(f"mandatory {doc} energy-control step missing: {text!r}")
    for s in work_order.steps:
        c = s.citation
        verbatim = (
            c is not None
            and normalise(s.text) == normalise(c.quote)
            and c.doc in DOCS
            and find_quote(c.doc, c.page, c.quote)
        )
        if not s.is_safety:
            if _SAFETY_WORDS.search(s.text) and not verbatim:
                errs.append(f"step {s.order}: reads like a safety step but is not marked is_safety "
                            "with a verbatim manual citation")  # fmt: skip
            continue
        if c is None:
            errs.append(f"step {s.order}: safety step has no manual citation")
            continue
        if normalise(s.text) != normalise(c.quote):
            errs.append(f"step {s.order}: safety text differs from the cited quote (reworded)")
        if c.doc not in DOCS:
            errs.append(f"step {s.order}: unknown manual {c.doc!r}")
        elif not find_quote(c.doc, c.page, c.quote):
            pages = locate_quote(c.doc, c.quote)
            where = f"; it is on page(s) {pages}" if pages else ""
            errs.append(f"step {s.order}: quote not found verbatim on {c.doc} p.{c.page}{where}")
    return errs


# =============================================================================================
# ADK agent
# =============================================================================================
def _report_score(report: RCAReport, verdicts: list[ClaimVerdict], iteration: int) -> list[int]:
    st = top_hypothesis_stats(report, verdicts)
    return [st["passed_checkable"], -st["failed"], -st["unverifiable"], iteration]


def _parse_draft(raw: Any) -> RCAReport:
    if isinstance(raw, RCAReport):
        return raw
    if isinstance(raw, str | bytes):
        return RCAReport.model_validate_json(raw)
    if raw is None:
        raise ValueError("state['rca_draft'] is missing")
    return RCAReport.model_validate(raw)


class Verifier(BaseAgent):
    """Deterministic verifier step of ``LoopAgent("rca_loop", [rca_judge, verifier])``.

    Reads ``state["rca_draft"]`` (RCAReport dict or JSON) and the ``evidence:<id>`` keys. Re-runs
    use ``ctx_factory(state_snapshot) -> ToolContext`` (injected so the graph controls the store;
    the snapshot is a plain ``dict`` copy, so re-runs cannot write session state). Writes, in one
    final event's ``state_delta``:

    * ``verifier_verdict`` — ``VerifierVerdict`` dict; ``rejected_claims`` — :func:`rejected_claims`;
    * ``verifier_iteration`` — 1-based count for this invocation (``verifier_invocation`` holds
      the invocation id, so a new run in the same session starts again at 1);
    * ``verifier_best`` — ``{score, iteration, report, claims}`` of the best draft so far;
    * on PASS: ``rca_final`` (status ``verified``) + ``rca_final_claims``, ``escalate=True``;
    * on the ``max_iterations``-th FAIL: ``rca_final`` = the best draft so far with status
      ``insufficient_evidence`` (failed claims kept; the UI strikes them through) +
      ``rca_final_claims``, ``escalate=True``.

    Events (``custom_metadata["andon_event"]``, mapped to SSE by the event layer): one
    ``claim_verdict`` per claim (``data`` = ClaimVerdict, plus ``hypothesis_index``, ``iteration``)
    and one ``verifier_verdict`` (``data`` = VerifierVerdict, plus ``summary``) that carries the
    state delta. A missing or invalid draft is a FAIL with no claim verdicts.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    ctx_factory: Callable[[dict[str, Any]], ToolContext]
    max_iterations: int = config.VERIFIER_MAX_ITERATIONS

    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        state = ctx.session.state
        inv = ctx.invocation_id
        same_run = state.get("verifier_invocation") == inv
        iteration = int(state.get("verifier_iteration", 0) if same_run else 0) + 1
        best = state.get("verifier_best") if same_run else None
        raw = state.get("rca_draft")

        def event(
            kind: str, data: dict, actions: EventActions | None = None, **extra: Any
        ) -> Event:
            return Event(author=self.name, invocation_id=inv, branch=ctx.branch,
                         custom_metadata={"andon_event": kind, "data": data, **extra},
                         actions=actions or EventActions())  # fmt: skip

        report: RCAReport | None
        try:
            report = _parse_draft(raw)
        except (ValueError, ValidationError) as exc:
            report = None
            msg = f"rca_draft missing or invalid: {exc}"[:500]
            verdict = VerifierVerdict(overall="FAIL", claims=[], iteration=iteration)
            verdicts: list[ClaimVerdict] = []
            rejected = [{"claim_id": "_report", "text": "", "kind": "report", "verdict": "fail",
                         "reason": msg, "measured_value": None}]  # fmt: skip
            summary = msg
        else:
            snapshot = dict(state.items()) if hasattr(state, "items") else dict(state)
            tctx = self.ctx_factory(snapshot)
            verdict, verdicts = await asyncio.to_thread(verify_report, report, tctx, iteration)
            rejected = rejected_claims(verdicts, report)
            summary = "PASS" if verdict.overall == "PASS" else failure_summary(report, verdicts)
            i = 0
            for h_i, hyp in enumerate(report.hypotheses):
                for _ in hyp.claims:
                    yield event("claim_verdict", verdicts[i].model_dump(mode="json"),
                                hypothesis_index=h_i, iteration=iteration)  # fmt: skip
                    i += 1

        delta: dict[str, Any] = {
            "verifier_verdict": verdict.model_dump(mode="json"),
            "rejected_claims": rejected,
            "verifier_iteration": iteration,
            "verifier_invocation": inv,
        }
        if report is not None:
            score = _report_score(report, verdicts, iteration)
            if best is None or list(score) >= list(best["score"]):
                best = {"score": score, "iteration": iteration,
                        "report": report.model_dump(mode="json"),
                        "claims": [v.model_dump(mode="json") for v in verdicts]}  # fmt: skip
            delta["verifier_best"] = best
        escalate = False
        if verdict.overall == "PASS" and report is not None:
            final = report.model_copy(update={"status": "verified"})
            delta["rca_final"] = final.model_dump(mode="json")
            delta["rca_final_claims"] = [v.model_dump(mode="json") for v in verdicts]
            escalate = True
        elif iteration >= self.max_iterations:
            if best is not None:
                final_d = {**best["report"], "status": "insufficient_evidence"}
                claims = best["claims"]
            else:
                inc = raw.get("incident_id") if isinstance(raw, Mapping) else None
                final_d = {"incident_id": str(inc or state.get("incident_id") or "unknown"),
                           "hypotheses": [], "status": "insufficient_evidence"}  # fmt: skip
                claims = []
            delta["rca_final"] = RCAReport.model_validate(final_d).model_dump(mode="json")
            delta["rca_final_claims"] = claims
            escalate = True
        yield event("verifier_verdict", verdict.model_dump(mode="json"),
                    EventActions(state_delta=delta, escalate=escalate), summary=summary)  # fmt: skip


__all__ = [
    "MIN_PASSING_CHECKABLE", "REAL_DATA_RE", "Verifier", "chain_assets", "check_safety_steps",
    "failure_summary", "real_data_phrase", "rejected_claims", "top_hypothesis_stats",
    "verify_report",
]  # fmt: skip
