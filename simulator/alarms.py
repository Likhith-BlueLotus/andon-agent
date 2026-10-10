"""Deterministic alarm generation (SYNTHETIC_DATA_SPEC §5 "Alarms").

Alarms are derived from what the simulated sensors report, so an alarm always agrees with the
telemetry the agents can query:

* threshold alarms: a tag beyond its alarm/trip limit for ≥ ``PERSIST_S`` seconds, re-armed only
  after it has been back inside for ``REARM_S`` (suppressed during planned changeovers, as an HMI
  inhibits alarms in idle mode);
* event alarms: weld-monitor faults, clamp retries, starved/blocked … drawn from per-second rates
  set by the physics and the fault injector;
* nuisance alarms: benign, line-wide, a few per shift;
* the stop alarm at the stop timestamp and the post-stop flood (starved downstream, blocked
  upstream). Floods near the stop are capped to 5-30 alarms.

Codes are generic (``A-ST40-PRS-LO``, ``S-ST60-QSTOP``); no real vendor's alarm scheme is used.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta

import numpy as np

from simulator import plant
from simulator.faults import StopSpec
from simulator.plant import SimResult, Timeline, rng_for

PERSIST_S = 5
REARM_S = 120
CHANGEOVER_INHIBIT_S = plant.CHANGEOVER_S + 360  # incl. slow ramp-up cycles
FLOOD_WINDOW_S = 30 * 60
FLOOD_MAX = 30  # total incl. the post-stop flood
FLOOD_MAX_PRE = 22  # before the stop; the stop flood adds ~7
NUISANCE_PER_HOUR = 0.2

NUISANCE: tuple[tuple[str, str, str], ...] = (
    ("ST60-VIS", "A-ST60-CAM-COMM", "ST60 Vision check: camera communication retry"),
    ("ST20-WLD", "A-ST20-DOOR-OPN", "ST20 Weld cell A: cell door opened (key switch)"),
    ("ST30-WLD", "A-ST30-DOOR-OPN", "ST30 Weld cell B: cell door opened (key switch)"),
    ("ST40-SLR", "A-ST40-NOZ-PRG", "ST40 Sealer: nozzle purge requested"),
    ("ST50-CNV", "A-ST50-ESTOP-RST", "ST50 Conveyor: e-stop reset acknowledged"),
    ("UT-AIR", "A-UTAIR-DRN", "Plant air: condensate drain cycle"),
    ("UT-CHL", "A-UTCHL-FLT-SVC", "Chiller: filter service due"),
    ("ST10-PRS", "A-ST10-LUB-LOW", "ST10 Press: way-lube reservoir low"),
)

EVENT_TEXT: dict[str, str] = {
    "WLD-QA": "weld monitor: weld energy out of band",
    "BEAD-QA": "bead inspection: bead width out of tolerance",
    "GUN-FRC": "gun force not reached",
    "CLAMP-RTY": "clamp position retry",
    "STARVED": "station starved (waiting for part)",
    "BLOCKED": "station blocked (outfeed full)",
}


@dataclass(frozen=True)
class Alarm:
    ts: datetime
    asset_id: str
    code: str
    severity: str  # info | warning | alarm | trip | stop
    text: str

    @property
    def station(self) -> str:
        return plant.asset(self.asset_id).station


def _runs(mask: np.ndarray) -> list[tuple[int, int]]:
    """[start, end) of True runs."""
    if not mask.any():
        return []
    d = np.diff(np.concatenate([[0], mask.astype(np.int8), [0]]))
    return list(zip(np.flatnonzero(d == 1).tolist(), np.flatnonzero(d == -1).tolist(), strict=True))


def threshold_alarms(sim: SimResult, tl: Timeline) -> list[Alarm]:
    inhibit = np.zeros(tl.n, dtype=bool)
    for i in tl.shift_starts:
        inhibit[i : i + CHANGEOVER_INHIBIT_S] = True
    out: list[Alarm] = []
    for (aid, tag), spec in plant.TAG_SPECS.items():
        x = sim.values[(aid, tag)]
        a = plant.asset(aid)
        for lvl, lim, sev in (
            ("LO", spec.alarm_lo, "alarm"),
            ("HI", spec.alarm_hi, "alarm"),
            ("LL", spec.trip_lo, "trip"),
            ("HH", spec.trip_hi, "trip"),
        ):
            if lim is None:
                continue
            mask = (x < lim) if lvl in ("LO", "LL") else (x > lim)
            mask &= ~inhibit
            last_end = -(10**9)
            for s, e in _runs(mask):
                if e - s < PERSIST_S:
                    continue
                if s - last_end >= REARM_S:
                    word = "low" if lvl in ("LO", "LL") else "high"
                    if lvl in ("LL", "HH"):
                        word += "-" + word
                    out.append(
                        Alarm(
                            tl.ts(s + PERSIST_S - 1),
                            aid,
                            plant.alarm_code(aid, tag, lvl),
                            sev,
                            f"{a.name}: {spec.label} {word}",
                        )
                    )
                last_end = e
    return out


def first_crossing(sim: SimResult, tl: Timeline, key: tuple[str, str], level: str) -> int | None:
    """Sample index at which ``key``'s ``level`` ("trip" or "alarm") limit alarm would fire,
    using the same persistence/inhibit rule as ``threshold_alarms``."""
    spec = plant.TAG_SPECS[key]
    x = sim.values[key]
    inhibit = np.zeros(tl.n, dtype=bool)
    for i in tl.shift_starts:
        inhibit[i : i + CHANGEOVER_INHIBIT_S] = True
    lims = (spec.trip_lo, spec.trip_hi) if level == "trip" else (spec.alarm_lo, spec.alarm_hi)
    best: int | None = None
    for lim, low in zip(lims, (True, False), strict=True):
        if lim is None:
            continue
        mask = ((x < lim) if low else (x > lim)) & ~inhibit
        for s, e in _runs(mask):
            if e - s >= PERSIST_S:
                i = s + PERSIST_S - 1
                best = i if best is None else min(best, i)
                break
    return best


def event_alarms(sim: SimResult, tl: Timeline, seed: int) -> list[Alarm]:
    out: list[Alarm] = []
    for (aid, code), rate in sorted(sim.event_rate.items()):
        r = rng_for(seed, "events", aid, code)
        hits = np.flatnonzero(r.random(tl.n) < np.clip(rate, 0, 1))
        last = -(10**9)
        kind = code.split("-", 2)[2]
        for i in hits.tolist():
            if i - last < 60:  # same code at most once a minute (chatter is an imperfection)
                continue
            last = i
            sev = "warning" if kind in ("STARVED", "BLOCKED", "CLAMP-RTY") else "alarm"
            out.append(
                Alarm(tl.ts(i), aid, code, sev, f"{plant.asset(aid).name}: {EVENT_TEXT[kind]}")
            )
    return out


def nuisance_alarms(tl: Timeline, seed: int) -> list[Alarm]:
    r = rng_for(seed, "nuisance")
    k = int(r.poisson(NUISANCE_PER_HOUR * tl.n / 3600))
    idx = np.sort(r.integers(0, tl.n, k))
    which = r.integers(0, len(NUISANCE), k)
    return [
        Alarm(tl.ts(int(i)), NUISANCE[w][0], NUISANCE[w][1], "info", NUISANCE[w][2])
        for i, w in zip(idx.tolist(), which.tolist(), strict=True)
    ]


def stop_alarms(stop: StopSpec, tl: Timeline, seed: int) -> list[Alarm]:
    """The stop alarm plus the flood that follows a line stop."""
    r = rng_for(seed, "stopflood")
    t = tl.stop
    out = [
        Alarm(t, stop.station, stop.code, "stop", stop.text),
        Alarm(
            t + timedelta(seconds=2),
            stop.station,
            "A-L1-ANDON",
            "info",
            "Line L1 stopped: andon raised",
        ),
    ]
    pos = plant.asset(stop.station).position or 0
    for aid in plant.SERIES:
        p = plant.asset(aid).position or 0
        if aid == stop.station:
            continue
        kind = "STARVED" if p > pos else "BLOCKED"
        dt = int(r.integers(20, 50)) + 25 * abs(p - pos)
        out.append(
            Alarm(
                t + timedelta(seconds=dt),
                aid,
                f"A-{plant.asset(aid).station}-{kind}",
                "warning",
                f"{plant.asset(aid).name}: {EVENT_TEXT[kind]}",
            )
        )
    return out


def cap_flood(alarms: list[Alarm], tl: Timeline, seed: int) -> list[Alarm]:
    """Keep ≤ FLOOD_MAX_PRE alarms in the 30 min before the stop (+ the post-stop flood): thin
    repeated event alarms first, never the stop alarm or the first alarm of any code."""
    lo = tl.stop - timedelta(seconds=FLOOD_WINDOW_S)
    in_win = [a for a in alarms if a.ts >= lo]
    if len(in_win) <= FLOOD_MAX_PRE:
        return alarms
    seen: set[str] = set()
    keep_first: list[Alarm] = []
    repeats: list[Alarm] = []
    for a in sorted(in_win, key=lambda a: (a.ts, a.code)):
        if a.severity == "stop" or a.code not in seen:
            keep_first.append(a)
            seen.add(a.code)
        else:
            repeats.append(a)
    budget = max(FLOOD_MAX_PRE - len(keep_first), 0)
    r = rng_for(seed, "floodcap")
    chosen = (
        sorted(r.choice(len(repeats), size=min(budget, len(repeats)), replace=False).tolist())
        if repeats
        else []
    )
    kept = set(map(id, keep_first)) | {id(repeats[i]) for i in chosen}
    return [a for a in alarms if a.ts < lo or id(a) in kept]


def build_alarms(sim: SimResult, tl: Timeline, stop: StopSpec, seed: int) -> list[Alarm]:
    alarms = threshold_alarms(sim, tl) + event_alarms(sim, tl, seed) + nuisance_alarms(tl, seed)
    alarms = [a for a in alarms if a.ts < tl.stop]
    alarms = cap_flood(alarms, tl, seed)
    alarms += stop_alarms(stop, tl, seed)
    return sorted(alarms, key=lambda a: (a.ts, a.asset_id, a.code))


def skew(alarms: list[Alarm], asset_id: str, seconds: int) -> list[Alarm]:
    return [
        replace(a, ts=a.ts + timedelta(seconds=seconds)) if a.asset_id == asset_id else a
        for a in alarms
    ]
