"""Realistic data-quality imperfections (SYNTHETIC_DATA_SPEC §2), all recorded for the eval.

Injected per scenario, seeded:

* ``missing``  - 0.5-2 % of samples dropped per asset (independently per tag);
* ``gap``      - 1-3 comms gaps per day, 10-120 s, all tags of one asset;
* ``stuck``    - one healthy tag frozen at its last value for 10 min - 3 h;
* ``chatter``  - one alarm repeating 3-10x within a minute;
* ``clock_skew`` - one station's alarms offset by 3-9 s;
* ``duplicate_note`` - one shift note entered twice.

Hard rule: none of these may sit on the root asset's onset (nor on any causal-chain asset's
onset), and the stuck tag is never a tag the fault touches. Every imperfection is serialised as
``kind|asset_id|tag|t0|t1|detail`` (ISO-8601 UTC, ``*`` = all tags) into ``truth.imperfections``.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta

import numpy as np

from simulator import plant
from simulator.alarms import Alarm, skew
from simulator.plant import TagKey, Timeline

PROTECT_S = 30 * 60  # no imperfection within ±30 min of a causal-chain onset on that asset


@dataclass(frozen=True)
class Imperfection:
    kind: str
    asset_id: str
    tag: str
    t0: datetime
    t1: datetime
    detail: str = ""

    def to_str(self) -> str:
        f = "%Y-%m-%dT%H:%M:%SZ"
        return f"{self.kind}|{self.asset_id}|{self.tag}|{self.t0.strftime(f)}|{self.t1.strftime(f)}|{self.detail}"

    @staticmethod
    def parse(s: str) -> Imperfection:
        from datetime import UTC

        kind, aid, tag, t0, t1, detail = s.split("|", 5)
        p = "%Y-%m-%dT%H:%M:%SZ"
        return Imperfection(kind, aid, tag, datetime.strptime(t0, p).replace(tzinfo=UTC),
                            datetime.strptime(t1, p).replace(tzinfo=UTC), detail)  # fmt: skip


@dataclass
class Note:
    ts: datetime
    author_role: str
    text: str
    note_id: str = ""


@dataclass
class ImperfectionResult:
    keep: dict[TagKey, np.ndarray]  # bool mask of rows kept per tag
    values: dict[TagKey, np.ndarray]  # values after stuck periods
    alarms: list[Alarm]
    notes: list[Note]
    items: list[Imperfection] = field(default_factory=list)


def protected_windows(asset_onsets: dict[str, int]) -> dict[str, list[tuple[int, int]]]:
    out: dict[str, list[tuple[int, int]]] = {}
    for aid, i in asset_onsets.items():
        out.setdefault(aid, []).append((i - PROTECT_S, i + PROTECT_S))
    return out


def _overlaps(lo: int, hi: int, wins: list[tuple[int, int]]) -> bool:
    return any(lo < b and a < hi for a, b in wins)


def apply(
    tl: Timeline,
    values: dict[TagKey, np.ndarray],
    alarms: list[Alarm],
    notes: list[Note],
    *,
    rng: np.random.Generator,
    asset_onsets: dict[str, int],
    excluded_assets: set[str],
    excluded_tags: set[TagKey],
) -> ImperfectionResult:
    """``excluded_assets``: never host a stuck tag / skew / chatter (root + chain assets).
    ``excluded_tags``: tags touched by any fault or red herring (never stuck)."""
    n = tl.n
    prot = protected_windows(asset_onsets)
    keep = {k: np.ones(n, dtype=bool) for k in values}
    vals = {k: v.copy() for k, v in values.items()}
    items: list[Imperfection] = []
    assets = [a.asset_id for a in plant.ASSETS]

    # missing samples
    for aid in assets:
        pct = float(rng.uniform(0.5, 2.0))
        for t in plant.asset(aid).tags:
            drop = rng.random(n) < pct / 100.0
            for a, b in prot.get(aid, []):
                drop[max(a, 0) : max(b, 0)] = False
            keep[(aid, t.tag)] &= ~drop
        items.append(Imperfection("missing", aid, "*", tl.start, tl.stop, f"pct={pct:.2f}"))

    # comms gaps: 1-3 per day
    days = max(1, int(np.ceil(n / 86400)))
    for d in range(days):
        day_lo, day_hi = d * 86400, min((d + 1) * 86400, n)
        for _ in range(int(rng.integers(1, 4))):
            for _try in range(20):
                aid = assets[int(rng.integers(len(assets)))]
                dur = int(rng.integers(10, 121))
                if day_hi - dur - 1 <= day_lo:
                    break
                s = int(rng.integers(day_lo, day_hi - dur - 1))
                if s + dur >= n - 60 or _overlaps(s, s + dur, prot.get(aid, [])):
                    continue
                for t in plant.asset(aid).tags:
                    keep[(aid, t.tag)][s : s + dur] = False
                items.append(
                    Imperfection("gap", aid, "*", tl.ts(s), tl.ts(s + dur), f"duration_s={dur}")
                )
                break

    # one stuck value on a healthy tag
    healthy = sorted(k for k in values if k[0] not in excluded_assets and k not in excluded_tags)
    if healthy:
        key = healthy[int(rng.integers(len(healthy)))]
        dur = int(rng.integers(600, 3 * 3600 + 1))
        hi = max(n - dur - 3600, 1)
        s = int(rng.integers(0, hi))
        vals[key][s : s + dur] = vals[key][s]
        items.append(
            Imperfection(
                "stuck", key[0], key[1], tl.ts(s), tl.ts(s + dur), f"value={float(vals[key][s]):g}"
            )
        )

    # alarm chatter on a non-root alarm
    pool = [
        a
        for a in alarms
        if a.asset_id not in excluded_assets and a.severity != "stop" and a.ts < tl.stop
    ]
    if pool:
        base = pool[int(rng.integers(len(pool)))]
        reps = int(rng.integers(3, 11))
        offs = np.sort(rng.choice(np.arange(2, 60), size=reps, replace=False))
        extra = [replace(base, ts=base.ts + timedelta(seconds=int(o))) for o in offs]
        alarms = sorted(alarms + extra, key=lambda a: (a.ts, a.asset_id, a.code))
        items.append(Imperfection("chatter", base.asset_id, base.code, base.ts,
                                  base.ts + timedelta(seconds=int(offs[-1])), f"repeats={reps}"))  # fmt: skip

    # clock skew on one station's alarms
    skew_pool = sorted({a.asset_id for a in alarms} - excluded_assets)
    if skew_pool:
        aid = skew_pool[int(rng.integers(len(skew_pool)))]
        sec = int(rng.integers(3, 10)) * int(rng.choice([-1, 1]))
        alarms = sorted(skew(alarms, aid, sec), key=lambda a: (a.ts, a.asset_id, a.code))
        items.append(
            Imperfection("clock_skew", aid, "alarms", tl.start, tl.stop, f"offset_s={sec}")
        )

    # duplicate shift-note entry
    if notes:
        k = int(rng.integers(len(notes)))
        orig = notes[k]
        dup = replace(
            orig,
            ts=orig.ts + timedelta(seconds=int(rng.integers(0, 61))),
            note_id=orig.note_id + "d",
        )
        notes = sorted([*notes, dup], key=lambda x: x.ts)
        items.append(
            Imperfection(
                "duplicate_note", "*", "shift_notes", orig.ts, dup.ts, f"note_id={orig.note_id}"
            )
        )

    return ImperfectionResult(keep, vals, alarms, notes, items)
