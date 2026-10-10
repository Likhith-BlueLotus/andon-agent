"""Fault injector: the 11 cause classes + no_fault (SYNTHETIC_DATA_SPEC §3).

Each class is a function that writes physical/measurement modifiers into ``plant.Modifiers`` and
returns a ``FaultInstance`` describing what it did: root asset, onset, causal chain (root first),
the signature tags with expected direction (used by tests), the stop it causes, which manual
documents it and whether it has an audio signature.

Causality is built in, not painted on: downstream symptoms are functions of the root deviation
delayed by a physical lag (part travel, buffer fill, thermal inertia, pneumatic lag), so the root
asset's first change always precedes every downstream change.

Ramp shapes: ``step``, ``linear``, ``exp`` and ``wear``. ``wear`` is a parametric health-index
curve (slow linear loss then an exponential knee) shaped like published C-MAPSS degradation
trajectories; no C-MAPSS rows are used or redistributed.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal

import numpy as np

from agents.schemas import CauseClass
from simulator import plant
from simulator.plant import Modifiers, TagKey, Timeline, first_order, shift_right

Shape = Literal["step", "linear", "exp", "wear"]
Direction = Literal[1, -1, 0]  # +1 up, -1 down, 0 = variance/oscillation up
C = CauseClass


@dataclass(frozen=True)
class ManualRef:
    """Where a fault is documented. Page numbers are assigned when the manuals are written."""

    doc: str  # simulator/manuals/<doc>.md
    topic: str  # troubleshooting-table row / section title the manual must contain
    symptoms: tuple[str, ...]


@dataclass(frozen=True)
class AudioHint:
    """Where an abnormal MIMII clip belongs (consumed by audio placement, Part D4)."""

    machine_type: Literal["pump", "fan", "slider", "valve"]
    asset_id: str
    from_idx: int  # abnormal clips only after this sample (fault audible)


@dataclass(frozen=True)
class StopSpec:
    station: str  # asset_id of the stopped station
    code: str
    text: str
    trigger: tuple[TagKey, ...] = ()  # tags whose excursion caused the stop (dual-fault guard)
    # The stop *is* the first crossing of this limit on trigger[0] (generate.py anchors the stop
    # there); None = the stop is a human/aggregate decision placed at the end of the window.
    limit: Literal["trip", "alarm"] | None = None


@dataclass(frozen=True)
class Signature:
    asset_id: str
    tag: str
    direction: Direction
    onset_idx: int  # expected first effect on this tag (physical lag included)
    downstream: bool = False


@dataclass
class FaultInstance:
    cause: CauseClass
    asset_id: str | None
    onset_idx: int | None
    chain: list[str]
    signature: list[Signature]
    touched: set[TagKey]
    stop: StopSpec | None
    manual: ManualRef | None
    detail: str | None = None
    audio: AudioHint | None = None
    asset_onsets: dict[str, int] = field(default_factory=dict)


def shifted(f: FaultInstance, a: int) -> FaultInstance:
    """Re-base every sample index of ``f`` after the timeline is cut to start at ``a``."""
    from dataclasses import replace

    sh = lambda i: None if i is None else int(i) - a  # noqa: E731
    return replace(
        f,
        onset_idx=sh(f.onset_idx),
        signature=[replace(s, onset_idx=int(s.onset_idx) - a) for s in f.signature],
        asset_onsets={k: int(v) - a for k, v in f.asset_onsets.items()},
        audio=None if f.audio is None else replace(f.audio, from_idx=int(f.audio.from_idx) - a),
    )


@dataclass
class FaultContext:
    tl: Timeline
    rng: np.random.Generator
    scale: float = 1.0  # 1.0 primary; ~0.5 secondary (dual_fault)
    primary: bool = True
    root: str | None = None  # force a root asset (optional)

    @property
    def n(self) -> int:
        return self.tl.n

    def lead(self, lo_h: float, hi_h: float) -> int:
        """Onset index for a lead time in [lo_h, hi_h] hours before the stop, clamped to the
        available history (onset always leaves ≥40 % of history as clean baseline)."""
        max_lead = int(0.6 * self.n)
        lo, hi = int(lo_h * 3600), int(hi_h * 3600)
        hi = max(min(hi, max_lead), 1200)
        lo = max(min(lo, hi - 600), 600)
        return self.n - int(self.rng.integers(lo, hi + 1))

    def shift_change_onset(self, lo_h: float, hi_h: float, need_model_change: bool = False) -> int:
        """Latest shift start between lo_h and hi_h hours before the stop (fallback: nearest)."""
        starts = self.tl.shift_starts
        if need_model_change:
            ok = [
                i
                for k, i in enumerate(starts)
                if k > 0 and self.tl.models[k] != self.tl.models[k - 1]
            ]
            if not ok and len(starts) and (self.tl.models[0] != self.tl.first_model):
                ok = [int(starts[0])]
            starts = np.asarray(ok or list(starts), dtype=np.int64)
        lo, hi = self.n - int(hi_h * 3600), self.n - int(lo_h * 3600)
        cand = [int(i) for i in starts if lo <= i <= hi and i >= int(0.4 * self.n)]
        if cand:
            return cand[-1]
        valid = [int(i) for i in starts if i < self.n - 1800]
        if not valid:
            raise ValueError("history too short for a shift-change fault")
        return valid[-1]


def ramp(n: int, onset: int, shape: Shape, k: float = 3.0, end: int | None = None) -> np.ndarray:
    """0 before onset, rising to 1 at ``end`` (default: the stop)."""
    end = n if end is None else end
    r = np.zeros(n)
    if onset >= n:
        return r
    tau = np.clip((np.arange(onset, n) - onset) / max(end - onset, 1), 0, None)
    if shape == "step":
        v = np.ones_like(tau)
    elif shape == "linear":
        v = tau
    elif shape == "exp":
        v = (np.exp(k * tau) - 1) / (np.exp(k) - 1)
    elif shape == "wear":
        v = 0.25 * tau + 0.75 * (np.exp(k * tau) - 1) / (np.exp(k) - 1)
    else:  # pragma: no cover
        raise ValueError(shape)
    r[onset:] = v
    return r


VISIBLE_CYCLE_EXCESS_S = 4.0  # a propagated slowdown smaller than this is not in the chain
VISIBLE_MIN_S = 900  # ...and it must last at least this long before the stop


def _travel_lag(src: str, dst: str) -> int:
    return plant.hops(src, dst) * plant.PART_TRAVEL_S_PER_HOP + 300


def _cycle_chain(root: str, magnitude_s: float) -> list[str]:
    """Series assets whose cycle_time visibly rises (>3 s) through blocking/starvation."""
    out: list[tuple[int, int, str]] = []
    rp = plant.asset(root).position
    if rp is None:
        return []
    for aid in plant.SERIES:
        if aid == root or ("cycle_time_s" not in [t.tag for t in plant.asset(aid).tags]):
            continue
        d = plant.hops(root, aid)
        if magnitude_s * plant.HOP_ATTENUATION**d > VISIBLE_CYCLE_EXCESS_S:
            pos = plant.asset(aid).position or 0
            out.append((d, 0 if pos < rp else 1, aid))
    return [a for _, _, a in sorted(out)]


def _cycle_signatures(root: str, onset: int, magnitude_s: float) -> list[Signature]:
    return [
        Signature(aid, "cycle_time_s", 1, onset + plant.HOP_LAG_S * plant.hops(root, aid), True)
        for aid in _cycle_chain(root, magnitude_s)
    ]


def _all_cycle_tags() -> set[TagKey]:
    return {k for k in plant.TAG_SPECS if k[1] == "cycle_time_s"}


def _reject_from(mods: Modifiers, dev: np.ndarray, lag: int, p_max: float) -> None:
    """Extra reject probability at ST60 from a normalised root deviation (0..1)."""
    mods.rejects()[:] += shift_right(np.clip(dev, 0, 1), lag) * p_max


def _events(mods: Modifiers, asset_id: str, code: str, rate: np.ndarray) -> None:
    mods.get("event_rate", (asset_id, code))[:] += rate


# --- Fault implementations -------------------------------------------------------------------
def weld_tip_wear(ctx: FaultContext, mods: Modifiers) -> FaultInstance:
    rng, n, s = ctx.rng, ctx.n, ctx.scale
    root = ctx.root or str(rng.choice(["ST20-WLD", "ST30-WLD"]))
    onset = ctx.lead(10, 40)
    r = ramp(n, onset, "linear")
    mods.get("add", (root, "tip_resistance_mohm"))[:] += s * rng.uniform(0.042, 0.055) * r
    mods.get("add", (root, "weld_current_ka"))[:] += s * rng.uniform(0.6, 0.85) * r  # stepper
    lag = _travel_lag(root, "ST60-VIS")
    dev = np.clip((r - 0.35) / 0.65, 0, 1) ** 1.3
    _reject_from(mods, dev, lag, s * rng.uniform(0.17, 0.24))
    stn = plant.asset(root).station
    _events(mods, root, f"A-{stn}-WLD-QA", s * (r**2) / 1500.0)
    rej_onset = onset + int(0.35 * (n - onset)) + lag
    return FaultInstance(
        C.WELD_TIP_WEAR, root, onset, [root, "ST60-VIS"],
        [Signature(root, "tip_resistance_mohm", 1, onset),
         Signature(root, "weld_current_ka", 1, onset),
         Signature("ST60-VIS", "reject_rate_pct", 1, rej_onset, True)],
        {(root, "tip_resistance_mohm"), (root, "weld_current_ka"), ("ST60-VIS", "reject_rate_pct")},
        StopSpec("ST60-VIS", "S-ST60-QSTOP", "Quality stop (QA hold): reject rate high on consecutive checks",
                 (("ST60-VIS", "reject_rate_pct"),)),
        MANUAL[C.WELD_TIP_WEAR],
        asset_onsets={root: onset, "ST60-VIS": rej_onset},
    )  # fmt: skip


def sealer_pump_cavitation(ctx: FaultContext, mods: Modifiers) -> FaultInstance:
    rng, n, s = ctx.rng, ctx.n, ctx.scale
    root = "ST40-SLR"
    onset = ctx.lead(6, 20)
    r = ramp(n, onset, "exp", k=2.5)
    mods.add_osc((root, "pump_pressure_bar"), plant.SEALER_STROKE_HZ, s * rng.uniform(6, 10) * r)
    mods.get("add", (root, "pump_pressure_bar"))[:] += -s * 6.0 * r
    mods.get("noise_mult", (root, "pump_pressure_bar"))[:] += 3.0 * s * r
    mods.get("spike_prob", (root, "pump_pressure_bar"))[:] += 0.01 * s * r
    mods.get("spike_mag", (root, "pump_pressure_bar"))[:] = -15.0
    mods.get("add", (root, "flow_rate_ccm"))[:] += -s * rng.uniform(48, 62) * r
    mods.get("add", (root, "motor_current_a"))[:] += -0.4 * s * r
    mods.get("noise_mult", (root, "motor_current_a"))[:] += 1.5 * s * r
    mods.get("noise_mult", (root, "bead_width_mm"))[:] += 2.5 * s * r
    lag = _travel_lag(root, "ST60-VIS")
    _reject_from(mods, np.clip((r - 0.1) / 0.5, 0, 1), lag, s * rng.uniform(0.18, 0.25))
    _events(mods, root, "A-ST40-BEAD-QA", s * (r**2) / 1200.0)
    rej_onset = int(np.searchsorted(r, 0.1)) + lag
    return FaultInstance(
        C.SEALER_PUMP_CAVITATION, root, onset, [root, "ST60-VIS"],
        [Signature(root, "flow_rate_ccm", -1, onset),
         Signature(root, "pump_pressure_bar", 0, onset),
         Signature(root, "bead_width_mm", -1, onset),
         Signature("ST60-VIS", "reject_rate_pct", 1, rej_onset, True)],
        {(root, t.tag) for t in plant.asset(root).tags} | {("ST60-VIS", "reject_rate_pct")},
        StopSpec("ST60-VIS", "S-ST60-QSTOP", "Quality stop (QA hold): reject rate high on consecutive checks",
                 (("ST60-VIS", "reject_rate_pct"),)),
        MANUAL[C.SEALER_PUMP_CAVITATION],
        audio=AudioHint("pump", root, onset + int(0.4 * (n - onset))),
        asset_onsets={root: onset, "ST60-VIS": rej_onset},
    )  # fmt: skip


def conveyor_bearing_defect(ctx: FaultContext, mods: Modifiers) -> FaultInstance:
    rng, n, s = ctx.rng, ctx.n, ctx.scale
    root = "ST50-CNV"
    onset = ctx.lead(12, 60)
    r = ramp(n, onset, "exp", k=4.0)
    mods.get("add", (root, "vibration_rms_mms"))[:] += s * rng.uniform(5.6, 6.4) * r
    mods.add_osc(
        (root, "vibration_rms_mms"), plant.CONVEYOR_ROTATION_HZ, s * rng.uniform(1.0, 1.6) * r
    )
    mods.get("add", (root, "bearing_temp_c"))[:] += s * rng.uniform(15, 22) * first_order(r, 1800)
    mods.get("add", (root, "motor_current_a"))[:] += s * 1.2 * r
    mods.get("add", (root, "speed_mpm"))[:] += -s * 0.4 * r**2
    mag = s * rng.uniform(7, 10)
    mods.get("cycle_excess", root)[:] += mag * r**2
    chain_cyc = _cycle_chain(root, mag)
    sigs = [Signature(root, "vibration_rms_mms", 1, onset),
            Signature(root, "bearing_temp_c", 1, onset + 600),
            Signature(root, "motor_current_a", 1, onset)]  # fmt: skip
    cyc_onset = onset + int(0.5 * (n - onset))
    sigs += _cycle_signatures(root, cyc_onset, mag)
    return FaultInstance(
        C.CONVEYOR_BEARING_DEFECT, root, onset, [root, *chain_cyc], sigs,
        {(root, t.tag) for t in plant.asset(root).tags} | _all_cycle_tags(),
        StopSpec(root, "S-ST50-VIB-HH", "Conveyor drive stopped: vibration high-high",
                 ((root, "vibration_rms_mms"),), "trip"),
        MANUAL[C.CONVEYOR_BEARING_DEFECT],
        audio=AudioHint("slider", root, onset + int(0.3 * (n - onset))),
        asset_onsets={root: onset, **{a: cyc_onset + plant.HOP_LAG_S * plant.hops(root, a) for a in chain_cyc}},
    )  # fmt: skip


def servo_overheat(ctx: FaultContext, mods: Modifiers) -> FaultInstance:
    rng, n, s = ctx.rng, ctx.n, ctx.scale
    root = ctx.root or str(rng.choice(["ST20-WLD", "ST30-WLD"]))
    onset = ctx.lead(2, 10)
    r = ramp(n, onset, "exp", k=2.0)
    heat = s * rng.uniform(39, 44)
    mods.get("servo_heat", root)[:] += heat * r
    # derating starts when the servo passes SERVO_DERATE_START_C (~19 degC above normal)
    frac = max(0.0, min(1.0, 19.0 / heat)) if heat > 0 else 1.0
    derate_idx = int(np.searchsorted(r, frac)) + 600
    mag = plant.SERVO_DERATE_S_PER_C * max(heat - 19.0, 0.0)
    chain_cyc = _cycle_chain(root, mag)
    stn = plant.asset(root).station
    sigs = [Signature(root, "servo_temp_c", 1, onset)]
    if mag > 3:
        sigs.append(Signature(root, "cycle_time_s", 1, derate_idx))
        sigs += _cycle_signatures(root, derate_idx, mag)
    return FaultInstance(
        C.SERVO_OVERHEAT, root, onset, [root, *chain_cyc], sigs,
        {(root, "servo_temp_c"), (root, "cycle_time_s")} | _all_cycle_tags(),
        StopSpec(root, f"S-{stn}-SRV-OT", f"{plant.asset(root).name}: servo drive over-temperature trip",
                 ((root, "servo_temp_c"),), "trip"),
        MANUAL[C.SERVO_OVERHEAT],
        audio=AudioHint("fan", root, onset + int(0.2 * (n - onset))),
        asset_onsets={root: onset, **{a: derate_idx + plant.HOP_LAG_S * plant.hops(root, a) for a in chain_cyc}},
    )  # fmt: skip


def air_pressure_drop(ctx: FaultContext, mods: Modifiers) -> FaultInstance:
    rng, n, s = ctx.rng, ctx.n, ctx.scale
    root = "UT-AIR"
    onset = ctx.lead(1.5, 8)
    r = ramp(n, onset, str(rng.choice(["linear", "exp"])), k=2.0)  # type: ignore[arg-type]
    mods.leak()[:] += s * rng.uniform(0.80, 0.92) * r
    # weld guns lose force once the cell air sags below ~5.2 bar
    stop_cell = (
        ctx.root
        if ctx.root in ("ST20-WLD", "ST30-WLD")
        else str(rng.choice(["ST20-WLD", "ST30-WLD"]))
    )
    for cell in ("ST20-WLD", "ST30-WLD"):
        stn = plant.asset(cell).station
        _events(mods, cell, f"A-{stn}-GUN-FRC", s * np.clip((r - 0.75) / 0.25, 0, 1) / 300.0)
    down_onset = onset + int(0.6 * (n - onset))
    return FaultInstance(
        C.AIR_PRESSURE_DROP, root, onset, [root, "ST20-WLD", "ST30-WLD"],
        [Signature(root, "compressor_current_a", 1, onset),
         Signature(root, "header_pressure_bar", -1, down_onset - 300),
         Signature("ST20-WLD", "air_pressure_bar", -1, down_onset, True),
         Signature("ST30-WLD", "air_pressure_bar", -1, down_onset, True)],
        {(root, t.tag) for t in plant.asset(root).tags}
        | {("ST20-WLD", "air_pressure_bar"), ("ST30-WLD", "air_pressure_bar")},
        StopSpec(stop_cell, f"S-{plant.asset(stop_cell).station}-AIR-LO",
                 f"{plant.asset(stop_cell).name}: gun air pressure low, cell stopped",
                 ((stop_cell, "air_pressure_bar"),), "alarm"),
        MANUAL[C.AIR_PRESSURE_DROP],
        audio=AudioHint("valve", root, onset + int(0.3 * (n - onset))),
        asset_onsets={root: onset, "ST20-WLD": down_onset, "ST30-WLD": down_onset},
    )  # fmt: skip


# Tags that may drift (sensor-only), with direction and the limit the drift ends beyond.
DRIFT_CANDIDATES: tuple[tuple[str, str, int], ...] = (
    ("ST10-PRS", "oil_temp_c", 1),
    ("ST20-WLD", "servo_temp_c", 1),
    ("ST30-WLD", "servo_temp_c", 1),
    ("ST30-WLD", "coolant_flow_lpm", -1),
    ("ST40-SLR", "pump_pressure_bar", 1),
    ("ST50-CNV", "bearing_temp_c", 1),
)


def sensor_drift(ctx: FaultContext, mods: Modifiers) -> FaultInstance:
    rng, n, s = ctx.rng, ctx.n, ctx.scale
    cands = [c for c in DRIFT_CANDIDATES if ctx.root in (None, c[0])] or list(DRIFT_CANDIDATES)
    aid, tag, d = cands[int(rng.integers(len(cands)))]
    spec = plant.tag_spec(aid, tag)
    onset = ctx.lead(12, 72)
    r = ramp(n, onset, "linear")
    limit = (spec.trip_hi or spec.alarm_hi) if d > 0 else (spec.trip_lo or spec.alarm_lo)
    assert limit is not None
    # The drift is relative to the tag's typical in-production value.
    total = abs(limit - spec.nominal) * rng.uniform(1.03, 1.10) + 2 * spec.noise_std
    mods.get("measurement", (aid, tag))[:] += d * s * total * r
    stn = plant.asset(aid).station
    lvl = ("HH" if spec.trip_hi else "HI") if d > 0 else ("LL" if spec.trip_lo else "LO")
    return FaultInstance(
        C.SENSOR_DRIFT, aid, onset, [aid],
        [Signature(aid, tag, d, onset)],  # type: ignore[arg-type]
        {(aid, tag)},
        StopSpec(aid, f"S-{stn}-{spec.abbr}-{lvl}",
                 f"{plant.asset(aid).name}: {spec.label} {'high' if d > 0 else 'low'} trip",
                 ((aid, tag),), "trip" if (spec.trip_hi if d > 0 else spec.trip_lo) is not None else "alarm"),
        MANUAL_SENSOR[plant.asset(aid).asset_type],
        detail=f"{aid}.{tag} drifts {'up' if d > 0 else 'down'}; no physical correlate",
        asset_onsets={aid: onset},
    )  # fmt: skip


def plc_timer_misconfig(ctx: FaultContext, mods: Modifiers) -> FaultInstance:
    rng, s = ctx.rng, ctx.scale
    choices = ["ST10-PRS", "ST20-WLD", "ST30-WLD", "ST60-VIS"]
    root = ctx.root if ctx.root in choices else str(rng.choice(choices))
    onset = ctx.shift_change_onset(1.0, 7.5)
    mag = s * rng.uniform(8.5, 11.0)
    # the parameter changes at the shift start; the first affected cycle is after the changeover
    mods.get("cycle_excess", root)[:] += mag * ramp(ctx.n, onset + plant.CHANGEOVER_S, "step")
    chain_cyc = _cycle_chain(root, mag)
    stn = plant.asset(root).station
    return FaultInstance(
        C.PLC_TIMER_MISCONFIG, root, onset, [root, *chain_cyc],
        [Signature(root, "cycle_time_s", 1, onset + plant.CHANGEOVER_S),
         *_cycle_signatures(root, onset + plant.CHANGEOVER_S, mag)],
        _all_cycle_tags(),
        StopSpec("ST60-VIS", "S-ST60-OUT-LO", "Line output below target for 60 min (takt loss)",
                 tuple(sorted(_all_cycle_tags()))),
        MANUAL_TIMER[plant.asset(root).asset_type],
        detail=f"{stn} cycle timer parameter changed at shift start",
        asset_onsets={root: onset, **{a: onset + plant.CHANGEOVER_S + plant.HOP_LAG_S * plant.hops(root, a)
                                      for a in chain_cyc}},
    )  # fmt: skip


def coolant_blockage(ctx: FaultContext, mods: Modifiers) -> FaultInstance:
    rng, n, s = ctx.rng, ctx.n, ctx.scale
    root = "ST30-WLD"
    onset = ctx.lead(3, 16)
    r = ramp(n, onset, str(rng.choice(["linear", "exp"])), k=2.0)  # type: ignore[arg-type]
    restr = s * rng.uniform(0.64, 0.7) * r
    mods.coolant_restriction[root] = mods.coolant_restriction.get(root, np.zeros(n)) + restr
    mods.get("noise_mult", (root, "weld_current_ka"))[:] += 1.0 * s * r
    _events(mods, root, "A-ST30-WLD-QA", s * np.clip((r - 0.5) / 0.5, 0, 1) / 900.0)
    thermal_idx = onset + 900
    heat_end = plant.COOLANT_HEAT_C * float(restr[-1])
    mag = plant.SERVO_DERATE_S_PER_C * max(heat_end - 19.0, 0.0)
    frac = 19.0 / heat_end if heat_end > 19 else 1.0
    derate_idx = int(np.searchsorted(restr / max(float(restr[-1]), 1e-9), frac)) + 900
    chain_cyc = _cycle_chain(root, mag) if mag > 3 else []
    sigs = [Signature(root, "coolant_flow_lpm", -1, onset),
            Signature(root, "servo_temp_c", 1, thermal_idx)]  # fmt: skip
    if mag > 3:
        sigs += _cycle_signatures(root, derate_idx, mag)
    return FaultInstance(
        C.COOLANT_BLOCKAGE, root, onset, [root, *chain_cyc], sigs,
        {(root, "coolant_flow_lpm"), (root, "servo_temp_c"), (root, "weld_current_ka")} | _all_cycle_tags(),
        StopSpec(root, "S-ST30-SRV-OT", "ST30 Weld cell B: servo drive over-temperature trip",
                 ((root, "servo_temp_c"), (root, "coolant_flow_lpm")), "trip"),
        MANUAL[C.COOLANT_BLOCKAGE],
        asset_onsets={root: onset, **{a: derate_idx + plant.HOP_LAG_S * plant.hops(root, a) for a in chain_cyc}},
    )  # fmt: skip


def fixture_misalignment(ctx: FaultContext, mods: Modifiers) -> FaultInstance:
    rng, n, s = ctx.rng, ctx.n, ctx.scale
    root = "ST20-WLD"
    onset = ctx.lead(2, 10)
    r = ramp(n, onset, "step")
    k = (root, "cycle_time_s")
    mods.get("noise_mult", k)[:] += s * rng.uniform(2.5, 4.0) * r
    mods.get("spike_prob", k)[:] += s * rng.uniform(0.12, 0.2) * r
    mods.get("spike_mag", k)[:] = rng.uniform(7, 13)
    lag = _travel_lag(root, "ST60-VIS")
    _reject_from(mods, r, lag, s * rng.uniform(0.13, 0.2))
    _events(mods, root, "A-ST20-CLAMP-RTY", s * r / 700.0)
    return FaultInstance(
        C.FIXTURE_MISALIGNMENT, root, onset, [root, "ST60-VIS"],
        [Signature(root, "cycle_time_s", 0, onset),
         Signature("ST60-VIS", "reject_rate_pct", 1, onset + lag, True)],
        {k, ("ST60-VIS", "reject_rate_pct")},
        StopSpec("ST60-VIS", "S-ST60-QSTOP", "Quality stop (QA hold): reject rate high on consecutive checks",
                 (("ST60-VIS", "reject_rate_pct"),)),
        MANUAL[C.FIXTURE_MISALIGNMENT],
        asset_onsets={root: onset, "ST60-VIS": onset + lag},
    )  # fmt: skip


def changeover_error(ctx: FaultContext, mods: Modifiers) -> FaultInstance:
    rng, s = ctx.rng, ctx.scale
    root = "ST10-PRS"
    onset = ctx.shift_change_onset(1.0, 6.0, need_model_change=True)
    r = ramp(ctx.n, onset, "step")
    mods.get("add", (root, "hyd_pressure_bar"))[:] += -s * rng.uniform(20, 27) * r
    lag = _travel_lag(root, "ST20-WLD") + plant.CHANGEOVER_S
    rd = shift_right(r, lag)
    mods.get("noise_mult", ("ST20-WLD", "weld_current_ka"))[:] += 1.5 * s * rd
    mods.get("noise_mult", ("ST20-WLD", "tip_resistance_mohm"))[:] += 2.0 * s * rd
    mods.get("add", ("ST20-WLD", "tip_resistance_mohm"))[:] += 0.01 * s * rd
    _events(mods, "ST20-WLD", "A-ST20-WLD-QA", s * rd / 500.0)
    _reject_from(
        mods, r, _travel_lag(root, "ST60-VIS") + plant.CHANGEOVER_S, s * rng.uniform(0.06, 0.1)
    )
    return FaultInstance(
        C.CHANGEOVER_ERROR, root, onset, [root, "ST20-WLD", "ST60-VIS"],
        [Signature(root, "hyd_pressure_bar", -1, onset),
         Signature("ST20-WLD", "tip_resistance_mohm", 1, onset + lag, True)],
        {(root, "hyd_pressure_bar"), (root, "motor_current_a"), ("ST20-WLD", "weld_current_ka"),
         ("ST20-WLD", "tip_resistance_mohm"), ("ST60-VIS", "reject_rate_pct")},
        StopSpec("ST20-WLD", "S-ST20-WLD-FLT", "ST20 Weld cell A: repeated weld faults, cell stopped",
                 (("ST20-WLD", "weld_current_ka"), ("ST20-WLD", "tip_resistance_mohm"))),
        MANUAL[C.CHANGEOVER_ERROR],
        detail=f"wrong press recipe after changeover to model {ctx.tl.model_at(onset)}",
        asset_onsets={root: onset, "ST20-WLD": onset + lag, "ST60-VIS": onset + lag + 300},
    )  # fmt: skip


HYDRAULIC_SUBTYPES = ("pump_leakage", "valve_lag", "accumulator_loss", "cooler_loss")


def hydraulic_degradation(ctx: FaultContext, mods: Modifiers) -> FaultInstance:
    rng, n, s = ctx.rng, ctx.n, ctx.scale
    root = "ST10-PRS"
    sub = str(rng.choice(HYDRAULIC_SUBTYPES))
    onset = ctx.lead(8, 48)
    r = ramp(n, onset, "wear", k=4.0)
    sigs: list[Signature] = []
    cyc = 0.0
    if sub == "pump_leakage":
        mods.get("add", (root, "hyd_pressure_bar"))[:] += -s * 14 * r
        mods.get("add", (root, "motor_current_a"))[:] += s * 6 * r
        mods.get("add", (root, "oil_temp_c"))[:] += s * 7 * first_order(r, 1800)
        cyc = s * 7
        sigs += [
            Signature(root, "hyd_pressure_bar", -1, onset),
            Signature(root, "motor_current_a", 1, onset),
        ]
    elif sub == "valve_lag":
        mods.get("noise_mult", (root, "hyd_pressure_bar"))[:] += 2.0 * s * r
        mods.get("add", (root, "vibration_rms_mms"))[:] += s * 1.2 * r
        mods.get("noise_mult", (root, "cycle_time_s"))[:] += 1.5 * s * r
        cyc = s * 9
        sigs += [Signature(root, "vibration_rms_mms", 1, onset)]
    elif sub == "accumulator_loss":
        mods.add_osc((root, "hyd_pressure_bar"), 0.05, s * 9 * r)
        mods.get("noise_mult", (root, "hyd_pressure_bar"))[:] += 3.0 * s * r
        mods.get("noise_mult", (root, "motor_current_a"))[:] += 2.0 * s * r
        cyc = s * 6
        sigs += [Signature(root, "hyd_pressure_bar", 0, onset)]
    else:  # cooler_loss
        mods.get("add", (root, "oil_temp_c"))[:] += s * 17 * first_order(r, 1200)
        cyc = s * 5
        sigs += [Signature(root, "oil_temp_c", 1, onset)]
    mods.get("cycle_excess", root)[:] += cyc * r
    cyc_onset = onset + int(0.3 * (n - onset))
    sigs.append(Signature(root, "cycle_time_s", 1, cyc_onset))
    chain_cyc = _cycle_chain(root, cyc)
    sigs += _cycle_signatures(root, cyc_onset, cyc)
    return FaultInstance(
        C.HYDRAULIC_DEGRADATION, root, onset, [root, *chain_cyc], sigs,
        {(root, t.tag) for t in plant.asset(root).tags} | _all_cycle_tags(),
        StopSpec(root, "S-ST10-HYD-FLT", "ST10 Press: hydraulic fault, press stopped",
                 ((root, "hyd_pressure_bar"), (root, "oil_temp_c"), (root, "cycle_time_s"))),
        MANUAL[C.HYDRAULIC_DEGRADATION],
        detail=sub,
        asset_onsets={root: onset, **{a: cyc_onset + plant.HOP_LAG_S * plant.hops(root, a) for a in chain_cyc}},
    )  # fmt: skip


# --- no_fault --------------------------------------------------------------------------------
GLITCH_KINDS = ("sensor_spike", "safety_trip", "comm_timeout")


def no_fault(ctx: FaultContext, mods: Modifiers, station: str) -> FaultInstance:
    """A benign glitch at ``station`` triggers a stop; nothing upstream is abnormal."""
    rng, n = ctx.rng, ctx.n
    stop_station = station if plant.asset(station).position is not None else "ST20-WLD"
    kinds = list(GLITCH_KINDS)
    spikeable = [
        t for t in plant.asset(station).tags if t.kind == "continuous" and (t.trip_hi or t.trip_lo)
    ]
    if not spikeable:
        kinds.remove("sensor_spike")
    kind = str(rng.choice(kinds))
    stn = plant.asset(stop_station).station
    name = plant.asset(stop_station).name
    if kind == "sensor_spike":
        t = spikeable[int(rng.integers(len(spikeable)))]
        up = t.trip_hi is not None
        lim = t.trip_hi if up else t.trip_lo
        assert lim is not None
        width = int(rng.integers(1, 4))
        arr = mods.get("measurement", (station, t.tag))
        excursion = (lim - t.nominal) + (1 if up else -1) * abs(lim - t.nominal) * 0.15
        arr[n - width - 1 : n - 1] += excursion
        lvl = "HH" if up else "LL"
        code = f"S-{stn}-{t.abbr}-{lvl}" if station == stop_station else f"S-{stn}-AIR-LO"
        text = (f"{name}: {t.label} {'high' if up else 'low'} trip"
                if station == stop_station else f"{name}: supply air low interlock")  # fmt: skip
        detail = f"single {width}s spike on {station}.{t.tag}"
    elif kind == "safety_trip":
        code, text = f"S-{stn}-LC-TRIP", f"{name}: light curtain interrupted, safety stop"
        detail = "light curtain interrupted (person/part in guarded zone)"
    else:
        code, text = f"S-{stn}-COMM-TO", f"{name}: fieldbus watchdog timeout"
        detail = "fieldbus watchdog timeout, recovered on reset"
    return FaultInstance(
        C.NO_FAULT, None, None, [], [], set(),
        StopSpec(stop_station, code, text), None,
        detail=f"{kind}: {detail}",
    )  # fmt: skip


# --- Registry --------------------------------------------------------------------------------
MANUAL: dict[CauseClass, ManualRef] = {
    C.WELD_TIP_WEAR: ManualRef("weld_controller", "Electrode tip wear and tip dressing",
                               ("tip resistance rising", "weld current stepping up", "weld quality alarms")),
    C.SEALER_PUMP_CAVITATION: ManualRef("sealer_pump", "Pump cavitation / starved inlet",
                                        ("pressure pulsation", "low flow", "narrow or broken bead")),
    C.CONVEYOR_BEARING_DEFECT: ManualRef("conveyor_drive", "Drive bearing defect",
                                         ("vibration rising", "1x pulley rotation peak", "bearing temperature rising")),
    C.SERVO_OVERHEAT: ManualRef("weld_controller", "Servo-gun drive over-temperature",
                                ("servo temperature rising", "cycle time rising (derating)", "cabinet fan noise")),
    C.AIR_PRESSURE_DROP: ManualRef("compressed_air", "Header pressure low / air leaks",
                                   ("header pressure falling", "compressor loaded more often", "gun force alarms")),
    C.COOLANT_BLOCKAGE: ManualRef("weld_controller", "Coolant flow low / blocked circuit",
                                  ("coolant flow falling", "servo temperature rising", "weld faults")),
    C.FIXTURE_MISALIGNMENT: ManualRef("weld_controller", "Fixture / clamp misalignment",
                                      ("cycle time scatter", "clamp retries", "rejects with normal weld current")),
    C.CHANGEOVER_ERROR: ManualRef("press_hydraulics", "Product changeover: recipe and pressure setpoint verification",
                                  ("pressure off setpoint after changeover", "weld faults downstream")),
    C.HYDRAULIC_DEGRADATION: ManualRef("press_hydraulics", "Hydraulic degradation: pump leakage, valve lag, accumulator, cooler",
                                       ("pressure loss", "oil temperature rising", "slow cycles")),
}  # fmt: skip
MANUAL_SENSOR: dict[str, ManualRef] = {
    at: ManualRef(doc, "Instrument verification: suspected sensor drift",
                  ("single tag trending with no correlated change in related tags",))
    for at, doc in (("press_hydraulics", "press_hydraulics"), ("weld_controller", "weld_controller"),
                    ("sealer_pump", "sealer_pump"), ("conveyor_drive", "conveyor_drive"),
                    ("compressed_air", "compressed_air"), ("vision", "conveyor_drive"),
                    ("chiller", "compressed_air"))
}  # fmt: skip
MANUAL_TIMER: dict[str, ManualRef] = {
    at: ManualRef(
        m.doc,
        "Control parameters: cycle timers and change control",
        ("cycle time step at shift start with no other change",),
    )
    for at, m in MANUAL_SENSOR.items()
}


@dataclass(frozen=True)
class FaultDef:
    cause: CauseClass
    inject: Callable[[FaultContext, Modifiers], FaultInstance]
    home_stations: tuple[str, ...]  # where the paired no_fault glitch happens
    static_touched: frozenset[TagKey]  # union over root choices (dual-fault compatibility)
    root_assets: tuple[str, ...]
    audio: str | None = None


def _tags(*pairs: tuple[str, str]) -> frozenset[TagKey]:
    return frozenset(pairs)


_ALL_ASSET_TAGS = {a.asset_id: {(a.asset_id, t.tag) for t in a.tags} for a in plant.ASSETS}
_CYC = frozenset(_all_cycle_tags())
_ANY = tuple(a.asset_id for a in plant.ASSETS)

FAULTS: dict[CauseClass, FaultDef] = {
    C.WELD_TIP_WEAR: FaultDef(C.WELD_TIP_WEAR, weld_tip_wear, ("ST20-WLD", "ST30-WLD"),
        _tags(*[(w, t) for w in ("ST20-WLD", "ST30-WLD") for t in ("tip_resistance_mohm", "weld_current_ka")],
              ("ST60-VIS", "reject_rate_pct")), ("ST20-WLD", "ST30-WLD")),
    C.SEALER_PUMP_CAVITATION: FaultDef(C.SEALER_PUMP_CAVITATION, sealer_pump_cavitation, ("ST40-SLR",),
        frozenset(_ALL_ASSET_TAGS["ST40-SLR"] | {("ST60-VIS", "reject_rate_pct")}), ("ST40-SLR",), "pump"),
    C.CONVEYOR_BEARING_DEFECT: FaultDef(C.CONVEYOR_BEARING_DEFECT, conveyor_bearing_defect, ("ST50-CNV",),
        frozenset(_ALL_ASSET_TAGS["ST50-CNV"]) | _CYC, ("ST50-CNV",), "slider"),
    C.SERVO_OVERHEAT: FaultDef(C.SERVO_OVERHEAT, servo_overheat, ("ST20-WLD", "ST30-WLD"),
        _tags(("ST20-WLD", "servo_temp_c"), ("ST30-WLD", "servo_temp_c")) | _CYC, ("ST20-WLD", "ST30-WLD"), "fan"),
    C.AIR_PRESSURE_DROP: FaultDef(C.AIR_PRESSURE_DROP, air_pressure_drop, ("UT-AIR",),
        frozenset(_ALL_ASSET_TAGS["UT-AIR"] | {("ST20-WLD", "air_pressure_bar"), ("ST30-WLD", "air_pressure_bar")}),
        ("UT-AIR",), "valve"),
    C.SENSOR_DRIFT: FaultDef(C.SENSOR_DRIFT, sensor_drift, tuple(sorted({c[0] for c in DRIFT_CANDIDATES})),
        frozenset((a, t) for a, t, _ in DRIFT_CANDIDATES), tuple(sorted({c[0] for c in DRIFT_CANDIDATES}))),
    C.PLC_TIMER_MISCONFIG: FaultDef(C.PLC_TIMER_MISCONFIG, plc_timer_misconfig, ("ST10-PRS", "ST20-WLD", "ST30-WLD", "ST60-VIS"),
        _CYC, ("ST10-PRS", "ST20-WLD", "ST30-WLD", "ST60-VIS")),
    C.COOLANT_BLOCKAGE: FaultDef(C.COOLANT_BLOCKAGE, coolant_blockage, ("ST30-WLD",),
        _tags(("ST30-WLD", "coolant_flow_lpm"), ("ST30-WLD", "servo_temp_c"), ("ST30-WLD", "weld_current_ka")) | _CYC,
        ("ST30-WLD",)),
    C.FIXTURE_MISALIGNMENT: FaultDef(C.FIXTURE_MISALIGNMENT, fixture_misalignment, ("ST20-WLD",),
        _tags(("ST20-WLD", "cycle_time_s"), ("ST60-VIS", "reject_rate_pct")) | _CYC, ("ST20-WLD",)),
    C.CHANGEOVER_ERROR: FaultDef(C.CHANGEOVER_ERROR, changeover_error, ("ST10-PRS",),
        _tags(("ST10-PRS", "hyd_pressure_bar"), ("ST10-PRS", "motor_current_a"), ("ST20-WLD", "weld_current_ka"),
              ("ST20-WLD", "tip_resistance_mohm"), ("ST60-VIS", "reject_rate_pct")), ("ST10-PRS",)),
    C.HYDRAULIC_DEGRADATION: FaultDef(C.HYDRAULIC_DEGRADATION, hydraulic_degradation, ("ST10-PRS",),
        frozenset(_ALL_ASSET_TAGS["ST10-PRS"]) | _CYC, ("ST10-PRS",)),
}  # fmt: skip

# S-set classes: all except hydraulic_degradation (that one is the R-set's UCI class).
S_SET_CLASSES: tuple[CauseClass, ...] = tuple(c for c in FAULTS if c is not C.HYDRAULIC_DEGRADATION)


def inject(cause: CauseClass, ctx: FaultContext, mods: Modifiers) -> FaultInstance:
    return FAULTS[cause].inject(ctx, mods)


def compatible_secondaries(primary: FaultInstance) -> list[CauseClass]:
    """Secondary classes for a dual_fault: different root asset and they must not touch any tag
    that triggered the primary's stop (truth must stay unambiguous)."""
    trig = set(primary.stop.trigger) if primary.stop else set()
    out = []
    for c in S_SET_CLASSES:
        if c is primary.cause:
            continue
        fd = FAULTS[c]
        if primary.asset_id in fd.root_assets and len(fd.root_assets) == 1:
            continue
        if fd.static_touched & trig:
            continue
        if fd.static_touched & primary.touched:
            continue
        out.append(c)
    return out


def finalize(f: FaultInstance, sim: plant.SimResult) -> FaultInstance:
    """Derive the blocking/starvation part of the causal chain from the simulated physics.

    Injectors predict their direct symptoms; how far a slowdown propagates depends on the actual
    excess-cycle-time trajectory (buffers, derating, exponential ramps), so cycle-time links are
    recomputed here: an asset joins the chain if the slowdown it receives from the root exceeds
    ``VISIBLE_CYCLE_EXCESS_S`` for ≥ ``VISIBLE_MIN_S`` seconds; its expected onset is when that
    contribution first exceeds 1 s."""
    root = f.asset_id
    if root is None or plant.asset(root).position is None or (root, root) not in sim.cycle_contrib:
        return f
    keep = [s for s in f.signature if not (s.tag == "cycle_time_s" and s.direction == 1)]
    onsets = {a: i for a, i in f.asset_onsets.items() if a == root or a not in plant.SERIES or
              any(s.asset_id == a for s in keep)}  # fmt: skip
    found: list[tuple[int, str]] = []
    for aid in plant.SERIES:
        if (aid, "cycle_time_s") not in plant.TAG_SPECS or (aid, root) not in sim.cycle_contrib:
            continue
        ex = sim.cycle_contrib[(aid, root)]
        if (ex > VISIBLE_CYCLE_EXCESS_S).sum() < VISIBLE_MIN_S:
            continue
        first = int(np.argmax(ex > 1.0))
        keep.append(Signature(aid, "cycle_time_s", 1, first, aid != root))
        if aid != root:
            found.append((first, aid))
            onsets[aid] = first
    chain = [root] + [
        a
        for a in f.chain[1:]
        if a not in plant.SERIES or any(s.asset_id == a for s in keep if s.tag != "cycle_time_s")
    ]
    for _, aid in sorted(found):
        if aid not in chain:
            chain.append(aid)
    f.signature, f.chain, f.asset_onsets = keep, chain, onsets
    return f
