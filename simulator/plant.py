"""Synthetic line L1: asset/tag catalogue, normal operating ranges, and the 1 Hz plant physics.

This module is the single source of truth for the plant model (SYNTHETIC_DATA_SPEC §1):

* ``ASSETS`` / ``TAG_SPECS`` / ``spec_limits()`` - asset ids, types, tags, units, normal operating
  ranges, alarm and trip limits. The manuals and the Signal Analyst reuse these numbers, so a
  manual's "normal range" always matches what the simulator produces.
* ``simulate()`` - turns a ``Timeline`` plus fault ``Modifiers`` into 1 Hz tag series.

Physics in one paragraph: the line runs 24/7 in three shifts (06/14/22 local). Each shift starts
with a 15-minute changeover (line idle, product model may change, first cycles slow). Continuous
tags (pressures, temperatures, currents, vibration, flow, speed) are a noise-free "underlying"
signal + AR(1) noise + rare benign spikes, quantised to the sensor resolution. Per-cycle tags
(cycle time, weld current, tip resistance, bead width, reject rate) update once per part and are
held between parts, as a PLC-to-historian link does. Couplings that faults exploit: plant-air
header -> weld-cell air; coolant flow -> servo temperature; servo temperature -> cycle-time
derating; a slow station -> blocking upstream / starvation downstream with a per-hop buffer lag;
quality faults -> per-part reject probability at ST60 (rolling 100 parts).

Everything is deterministic given the RNG streams passed in. No real company's names, tag scheme,
alarm codes or layout are used; all names here are generic.
"""

from __future__ import annotations

import zlib
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Literal

import numpy as np
from scipy.signal import lfilter

LINE_ID = "L1"
SAMPLE_RATE_HZ = 1
# The synthetic plant runs on a fixed UTC+05:30 local clock (no DST). Timestamps are stored in UTC.
PLANT_UTC_OFFSET_S = 5 * 3600 + 30 * 60
SHIFT_START_HOURS: tuple[int, ...] = (6, 14, 22)  # local time; shift letters A, B, C
SHIFT_NAMES: tuple[str, ...] = ("A", "B", "C")
CHANGEOVER_S = 15 * 60  # planned changeover at every shift start (line idle)
RAMP_UP_CYCLES = 3  # first cycles after a changeover run slow
PRODUCT_MODELS: tuple[str, ...] = ("A", "B")
MODEL_CHANGE_PROB = 0.4  # chance the product model changes at a shift start
HOP_LAG_S = 240  # buffer lag per station hop for blocking/starvation propagation
HOP_ATTENUATION = 0.7  # buffers absorb part of a slowdown at each hop
PART_TRAVEL_S_PER_HOP = 60  # transit time of a part between adjacent stations

TagKind = Literal["continuous", "per_cycle"]
TagKey = tuple[str, str]  # (asset_id, tag)


# --- Catalogue -------------------------------------------------------------------------------
@dataclass(frozen=True)
class TagSpec:
    """One tag: physical meaning, normal behaviour, and limits.

    ``normal_lo``/``normal_hi`` are the manual's normal operating range (spec limits). Alarm limits
    raise a warning alarm; trip limits stop the station. ``abbr`` builds generic alarm codes such
    as ``A-ST40-PRS-LO``.
    """

    tag: str
    unit: str
    description: str
    nominal: float
    noise_std: float
    resolution: float
    normal_lo: float
    normal_hi: float
    abbr: str
    kind: TagKind = "continuous"
    ar: float = 0.6  # AR(1) coefficient of the measurement noise (continuous tags)
    alarm_lo: float | None = None
    alarm_hi: float | None = None
    trip_lo: float | None = None
    trip_hi: float | None = None

    @property
    def label(self) -> str:
        """Short human label used in alarm texts, e.g. ``servo temperature``."""
        return TAG_LABELS.get(self.tag, self.tag.rsplit("_", 1)[0].replace("_", " "))


TAG_LABELS: dict[str, str] = {
    "motor_current_a": "motor current", "vibration_rms_mms": "vibration", "hyd_pressure_bar": "hydraulic pressure",
    "oil_temp_c": "oil temperature", "cycle_time_s": "cycle time", "weld_current_ka": "weld current",
    "tip_resistance_mohm": "tip resistance", "servo_temp_c": "servo temperature", "air_pressure_bar": "gun air pressure",
    "coolant_flow_lpm": "coolant flow", "pump_pressure_bar": "pump pressure", "flow_rate_ccm": "sealer flow",
    "bead_width_mm": "bead width", "speed_mpm": "chain speed", "bearing_temp_c": "bearing temperature",
    "reject_rate_pct": "reject rate", "header_pressure_bar": "header pressure",
    "compressor_current_a": "compressor current", "supply_temp_c": "supply temperature",
}  # fmt: skip


@dataclass(frozen=True)
class AssetSpec:
    asset_id: str
    station: str  # short station code used in alarm codes, e.g. "ST40", "UTAIR"
    name: str
    asset_type: str
    position: int | None  # 0..5 along the line; None for utilities
    tags: tuple[TagSpec, ...]
    manual: str | None  # manual doc id (simulator/manuals/<doc>.md), None if no manual
    feeds: tuple[str, ...] = ()  # utilities: assets they supply

    def tag(self, name: str) -> TagSpec:
        for t in self.tags:
            if t.tag == name:
                return t
        raise KeyError(f"{self.asset_id} has no tag {name!r}")


def _weld_tags(coolant: bool) -> tuple[TagSpec, ...]:
    tags = [
        TagSpec(
            "weld_current_ka",
            "kA",
            "RMS secondary current of the last weld",
            10.5,
            0.08,
            0.01,
            9.8,
            11.2,
            "WCUR",
            "per_cycle",
            alarm_lo=9.5,
            alarm_hi=11.6,
        ),
        TagSpec(
            "tip_resistance_mohm",
            "mOhm",
            "Dynamic resistance of the last weld",
            0.150,
            0.003,
            0.001,
            0.135,
            0.175,
            "TIPR",
            "per_cycle",
            alarm_hi=0.185,
        ),
        TagSpec(
            "servo_temp_c",
            "degC",
            "Servo-gun drive temperature",
            47.0,
            0.2,
            0.1,
            35.0,
            65.0,
            "SRVT",
            ar=0.9,
            alarm_hi=72.0,
            trip_hi=80.0,
        ),
        TagSpec(
            "cycle_time_s",
            "s",
            "Duration of the last completed cycle (incl. waiting)",
            50.0,
            0.4,
            0.1,
            46.0,
            55.0,
            "CYC",
            "per_cycle",
            alarm_hi=58.0,
        ),
        TagSpec(
            "air_pressure_bar",
            "bar",
            "Regulated gun air pressure at the cell",
            5.6,
            0.02,
            0.01,
            5.3,
            5.9,
            "AIR",
            ar=0.6,
            alarm_lo=5.0,
            trip_lo=4.6,
        ),
    ]
    if coolant:
        tags.append(
            TagSpec(
                "coolant_flow_lpm",
                "L/min",
                "Gun and servo coolant flow",
                12.0,
                0.15,
                0.1,
                10.0,
                14.0,
                "CLT",
                ar=0.7,
                alarm_lo=8.0,  # low-low is an alarm, not a trip: the cell trips on servo temperature
            )
        )
    return tuple(tags)


# fmt: off
ASSETS: tuple[AssetSpec, ...] = (
    AssetSpec("ST10-PRS", "ST10", "ST10 Press", "press_hydraulics", 0, (
        TagSpec("motor_current_a", "A", "Hydraulic pump motor current", 42.0, 0.8, 0.1, 34.0, 50.0,
                "CUR", ar=0.7, alarm_hi=55.0, trip_hi=60.0),
        TagSpec("vibration_rms_mms", "mm/s", "Pump/motor vibration velocity RMS", 2.2, 0.12, 0.01,
                1.0, 4.5, "VIB", ar=0.5, alarm_hi=7.1, trip_hi=11.0),
        TagSpec("hyd_pressure_bar", "bar", "Main system pressure (setpoint depends on product model)",
                180.0, 1.0, 0.1, 170.0, 200.0, "PRS", ar=0.6, alarm_lo=165.0, alarm_hi=205.0,
                trip_lo=155.0, trip_hi=215.0),
        TagSpec("oil_temp_c", "degC", "Hydraulic oil tank temperature", 46.0, 0.15, 0.1, 35.0, 55.0,
                "OILT", ar=0.9, alarm_hi=60.0, trip_hi=65.0),
        TagSpec("cycle_time_s", "s", "Duration of the last completed press cycle", 48.0, 0.5, 0.1,
                45.0, 54.0, "CYC", "per_cycle", alarm_hi=58.0),
    ), "press_hydraulics"),
    AssetSpec("ST20-WLD", "ST20", "ST20 Weld cell A", "weld_controller", 1, _weld_tags(False),
              "weld_controller"),
    AssetSpec("ST30-WLD", "ST30", "ST30 Weld cell B", "weld_controller", 2, _weld_tags(True),
              "weld_controller"),
    AssetSpec("ST40-SLR", "ST40", "ST40 Sealer", "sealer_pump", 3, (
        TagSpec("pump_pressure_bar", "bar", "Sealer pump outlet pressure", 120.0, 1.2, 0.1, 105.0,
                135.0, "PRS", ar=0.3, alarm_lo=100.0, alarm_hi=145.0),
        TagSpec("flow_rate_ccm", "cc/min", "Sealer volumetric flow", 300.0, 4.0, 1.0, 270.0, 330.0,
                "FLW", ar=0.6, alarm_lo=255.0, trip_lo=230.0),
        TagSpec("motor_current_a", "A", "Pump drive motor current", 8.5, 0.15, 0.01, 7.0, 10.0,
                "CUR", ar=0.6, alarm_hi=11.0),
        TagSpec("bead_width_mm", "mm", "Bead width measured on the last part", 4.0, 0.06, 0.01, 3.6,
                4.4, "BEAD", "per_cycle", alarm_lo=3.4, alarm_hi=4.6),
    ), "sealer_pump"),
    AssetSpec("ST50-CNV", "ST50", "ST50 Conveyor", "conveyor_drive", 4, (
        TagSpec("motor_current_a", "A", "Drive motor current", 15.0, 0.3, 0.1, 12.0, 18.0, "CUR",
                ar=0.7, alarm_hi=20.0),
        TagSpec("vibration_rms_mms", "mm/s", "Drive-end bearing vibration velocity RMS", 1.6, 0.1,
                0.01, 0.8, 2.8, "VIB", ar=0.4, alarm_hi=4.5, trip_hi=7.1),
        TagSpec("speed_mpm", "m/min", "Chain speed", 12.0, 0.05, 0.01, 11.5, 12.5, "SPD", ar=0.5,
                alarm_lo=11.0),
        TagSpec("bearing_temp_c", "degC", "Drive-end bearing housing temperature", 38.0, 0.15, 0.1,
                25.0, 55.0, "BRGT", ar=0.95, alarm_hi=65.0, trip_hi=75.0),
    ), "conveyor_drive"),
    AssetSpec("ST60-VIS", "ST60", "ST60 Vision check", "vision", 5, (
        TagSpec("reject_rate_pct", "%", "Rejects in the last 100 inspected parts", 1.0, 0.0, 1.0,
                0.0, 5.0, "REJ", "per_cycle", alarm_hi=6.0),
        TagSpec("cycle_time_s", "s", "Duration of the last completed inspection cycle", 46.0, 0.3,
                0.1, 43.0, 52.0, "CYC", "per_cycle", alarm_hi=56.0),
    ), None),
    AssetSpec("UT-AIR", "UTAIR", "Plant air compressor and header", "compressed_air", None, (
        TagSpec("header_pressure_bar", "bar", "Main air header pressure (load/unload band)", 6.75,
                0.02, 0.01, 6.0, 7.5, "HDR", ar=0.6, alarm_lo=5.6),
        TagSpec("compressor_current_a", "A", "Compressor motor current (loaded ~92 A, unloaded ~38 A)",
                60.0, 1.0, 0.1, 30.0, 100.0, "CUR", ar=0.5, alarm_hi=110.0),
        TagSpec("oil_temp_c", "degC", "Compressor oil temperature", 72.0, 0.2, 0.1, 60.0, 85.0,
                "OILT", ar=0.9, alarm_hi=95.0),
    ), "compressed_air", feeds=("ST20-WLD", "ST30-WLD")),
    AssetSpec("UT-CHL", "UTCHL", "Process chiller", "chiller", None, (
        TagSpec("supply_temp_c", "degC", "Chilled water supply temperature", 12.0, 0.05, 0.01, 10.0,
                14.0, "SUPT", ar=0.8, alarm_hi=15.0),
    ), None, feeds=("ST20-WLD", "ST30-WLD")),
)
# fmt: on

ASSET_BY_ID: dict[str, AssetSpec] = {a.asset_id: a for a in ASSETS}
SERIES: tuple[str, ...] = tuple(
    a.asset_id
    for a in sorted((a for a in ASSETS if a.position is not None), key=lambda a: a.position or 0)
)
TAG_SPECS: dict[TagKey, TagSpec] = {(a.asset_id, t.tag): t for a in ASSETS for t in a.tags}
ALL_TAGS: tuple[TagKey, ...] = tuple(TAG_SPECS)

# Product-model-dependent setpoints (the changeover_error class loads the wrong recipe).
PRODUCT_SETPOINTS: dict[str, dict[TagKey, float]] = {
    "A": {("ST10-PRS", "hyd_pressure_bar"): 180.0},
    "B": {("ST10-PRS", "hyd_pressure_bar"): 190.0},
}

# Mechanical constants used by the physics and documented in the conveyor/sealer manuals.
CONVEYOR_PULLEY_DIAMETER_M = 0.25
CONVEYOR_ROTATION_HZ = 12.0 / 60.0 / (np.pi * CONVEYOR_PULLEY_DIAMETER_M)  # ~0.255 Hz at 12 m/min
SEALER_STROKE_HZ = 0.15  # reciprocating sealer pump stroke rate
CHILLER_CYCLE_S = 900.0
AIR_CUT_IN_BAR = 6.2
AIR_CUT_OUT_BAR = 7.3
AIR_REGULATOR_BAR = 5.6
AIR_COMPRESSOR_CAPACITY = 1.0  # normalised free-air delivery
AIR_RECEIVER_CAPACITY = 27.0  # normalised; sets the load/unload period (~2 min)
AIR_LOADED_CURRENT_A = 92.0
AIR_UNLOADED_CURRENT_A = 38.0
SERVO_DERATE_START_C = 66.0  # above this the servo drive derates speed -> longer cycles
SERVO_DERATE_S_PER_C = 0.8
COOLANT_HEAT_C = 58.0  # servo target temperature rise at 100 % coolant flow loss (ST30)
BASE_REJECT_P = 0.01
REJECT_WINDOW_PARTS = 100


def asset(asset_id: str) -> AssetSpec:
    try:
        return ASSET_BY_ID[asset_id]
    except KeyError as exc:
        raise KeyError(f"unknown asset_id {asset_id!r}") from exc


def tag_spec(asset_id: str, tag: str) -> TagSpec:
    return asset(asset_id).tag(tag)


def alarm_code(asset_id: str, tag: str, level: Literal["LO", "HI", "LL", "HH"]) -> str:
    """Generic alarm code, e.g. ``A-ST40-PRS-LO``."""
    return f"A-{asset(asset_id).station}-{tag_spec(asset_id, tag).abbr}-{level}"


def upstream_of(asset_id: str) -> list[str]:
    """Assets upstream of ``asset_id`` along the line (nearest first), plus utilities feeding it."""
    out: list[str] = []
    a = asset(asset_id)
    if a.position is not None:
        out = list(reversed(SERIES[: a.position]))
    out += [u.asset_id for u in ASSETS if asset_id in u.feeds]
    return out


def downstream_of(asset_id: str) -> list[str]:
    a = asset(asset_id)
    if a.position is None:
        return list(a.feeds)
    return list(SERIES[a.position + 1 :])


def hops(a: str, b: str) -> int:
    """Station hops between two series assets (utilities count as 1 hop from what they feed)."""
    pa, pb = asset(a).position, asset(b).position
    if pa is None or pb is None:
        return 1
    return abs(pa - pb)


def spec_limits() -> list[dict[str, object]]:
    """Flat table of every tag's normal range and limits (for manuals, prompts and tools)."""
    rows: list[dict[str, object]] = []
    for a in ASSETS:
        for t in a.tags:
            rows.append(
                {
                    "asset_id": a.asset_id,
                    "asset_type": a.asset_type,
                    "manual": a.manual,
                    "tag": t.tag,
                    "unit": t.unit,
                    "description": t.description,
                    "nominal": t.nominal,
                    "normal_lo": t.normal_lo,
                    "normal_hi": t.normal_hi,
                    "alarm_lo": t.alarm_lo,
                    "alarm_hi": t.alarm_hi,
                    "trip_lo": t.trip_lo,
                    "trip_hi": t.trip_hi,
                    "resolution": t.resolution,
                    "alarm_codes": [
                        alarm_code(a.asset_id, t.tag, lvl)
                        for lvl, lim in (
                            ("LO", t.alarm_lo),
                            ("HI", t.alarm_hi),
                            ("LL", t.trip_lo),
                            ("HH", t.trip_hi),
                        )
                        if lim is not None
                    ],
                }
            )
    return rows


def assets_table() -> list[dict[str, object]]:
    """Asset rows for the store (what ``list_assets`` returns)."""
    return [
        {
            "line_id": LINE_ID,
            "asset_id": a.asset_id,
            "station": a.station,
            "name": a.name,
            "asset_type": a.asset_type,
            "position": a.position,
            "upstream": upstream_of(a.asset_id),
            "downstream": downstream_of(a.asset_id),
            "tags": [t.tag for t in a.tags],
            "units": [t.unit for t in a.tags],
            "manual": a.manual,
        }
        for a in ASSETS
    ]


# --- RNG streams -----------------------------------------------------------------------------
def rng_for(seed: int, *names: str | int) -> np.random.Generator:
    """Independent, named RNG stream: adding a new stream never shifts existing ones."""
    key = [seed, *(zlib.crc32(str(n).encode()) for n in names)]
    return np.random.default_rng(key)


# --- Timeline --------------------------------------------------------------------------------
@dataclass
class Timeline:
    """Sample grid ``[start, stop)`` at 1 Hz plus shifts, changeovers and the product schedule."""

    start: datetime  # UTC, inclusive
    n: int
    shift_starts: np.ndarray  # sample indices of shift starts inside the window
    shift_labels: list[str]  # "A"/"B"/"C" per shift start
    models: list[str]  # product model run from each shift start
    first_model: str  # model running at sample 0
    changeover: np.ndarray  # bool mask, line idle
    shift_idx: np.ndarray  # int: which segment (-1 = before first shift start)
    model_idx: np.ndarray  # int index into PRODUCT_MODELS per sample
    local_hour: np.ndarray  # float hours 0..24 local
    night: np.ndarray  # bool, shift C

    @property
    def stop(self) -> datetime:
        return self.start + timedelta(seconds=self.n)

    def ts(self, i: int) -> datetime:
        return self.start + timedelta(seconds=int(i))

    def index(self, t: datetime) -> int:
        return int((t - self.start).total_seconds())

    def model_at(self, i: int) -> str:
        return PRODUCT_MODELS[int(self.model_idx[i])]

    def shift_at(self, i: int) -> str:
        h = (self.local_hour[i] - SHIFT_START_HOURS[0]) % 24
        return SHIFT_NAMES[int(h // 8)]

    def epoch_s(self) -> np.ndarray:
        return int(self.start.timestamp()) + np.arange(self.n, dtype=np.int64)

    def slice(self, a: int, b: int) -> Timeline:
        """Sub-window ``[a, b)`` as a new timeline (indices re-based to ``a``)."""
        keep = [(int(i), k) for k, i in enumerate(self.shift_starts) if a <= i < b]
        k0 = int(self.shift_idx[a])
        first = self.models[k0] if k0 >= 0 else self.first_model
        seg = self.shift_idx[a:b] - (keep[0][1] if keep else 0)
        return Timeline(
            self.start + timedelta(seconds=a), b - a,
            np.asarray([i - a for i, _ in keep], dtype=np.int64),
            [self.shift_labels[k] for _, k in keep], [self.models[k] for _, k in keep], first,
            self.changeover[a:b].copy(), seg, self.model_idx[a:b].copy(), self.local_hour[a:b].copy(),
            self.night[a:b].copy(),
        )  # fmt: skip


def make_timeline(
    stop: datetime,
    history_s: int,
    rng: np.random.Generator,
    force_model_change_at: int | None = None,
) -> Timeline:
    """Build the grid ending at ``stop`` (exclusive). ``force_model_change_at`` = shift-start index
    that must carry a product-model change (used by ``changeover_error``)."""
    if stop.tzinfo is None:
        raise ValueError("stop must be timezone-aware (UTC)")
    stop = stop.astimezone(UTC)
    start = stop - timedelta(seconds=history_s)
    n = history_s
    epoch = int(start.timestamp()) + np.arange(n, dtype=np.int64)
    local_s = (epoch + PLANT_UTC_OFFSET_S) % 86400
    local_hour = local_s / 3600.0
    is_start = np.isin(local_s, [h * 3600 for h in SHIFT_START_HOURS])
    shift_starts = np.flatnonzero(is_start)
    labels = [SHIFT_NAMES[SHIFT_START_HOURS.index(int(local_s[i] // 3600))] for i in shift_starts]
    first_model = PRODUCT_MODELS[int(rng.integers(len(PRODUCT_MODELS)))]
    models: list[str] = []
    current = first_model
    for i in shift_starts:
        change = rng.random() < MODEL_CHANGE_PROB
        if force_model_change_at is not None and int(i) == force_model_change_at:
            change = True
        if change:
            current = PRODUCT_MODELS[1 - PRODUCT_MODELS.index(current)]
        models.append(current)
    changeover = np.zeros(n, dtype=bool)
    for i in shift_starts:
        changeover[i : i + CHANGEOVER_S] = True
    seg = np.full(n, -1, dtype=np.int64)
    model_idx = np.full(n, PRODUCT_MODELS.index(first_model), dtype=np.int64)
    for k, i in enumerate(shift_starts):
        seg[i:] = k
        model_idx[i:] = PRODUCT_MODELS.index(models[k])
    night = ((local_hour - SHIFT_START_HOURS[0]) % 24) >= 16
    return Timeline(start, n, shift_starts, labels, models, first_model, changeover, seg,
                    model_idx, local_hour, night)  # fmt: skip


# --- Fault modifiers -------------------------------------------------------------------------
@dataclass
class Modifiers:
    """Everything a fault (or a red herring) may change, applied inside ``simulate``.

    Arrays are lazily created per key with ``get``. Physical modifiers act through the couplings;
    ``measurement`` acts only on what the sensor reports (sensor drift: no physical correlates).
    """

    n: int
    add: dict[TagKey, np.ndarray] = field(default_factory=dict)  # physical, additive
    measurement: dict[TagKey, np.ndarray] = field(default_factory=dict)  # sensor-only, additive
    noise_mult: dict[TagKey, np.ndarray] = field(default_factory=dict)  # extra multiplier - 1
    spike_prob: dict[TagKey, np.ndarray] = field(default_factory=dict)  # per sample / per cycle
    spike_mag: dict[TagKey, np.ndarray] = field(default_factory=dict)
    osc: dict[TagKey, list[tuple[float, np.ndarray]]] = field(default_factory=dict)
    air_leak: np.ndarray | None = None  # extra normalised air demand at the header
    coolant_restriction: dict[str, np.ndarray] = field(default_factory=dict)  # 0..1 flow loss
    servo_heat: dict[str, np.ndarray] = field(default_factory=dict)  # degC added to target
    cycle_excess: dict[str, np.ndarray] = field(default_factory=dict)  # s, propagates
    reject_p: np.ndarray | None = None  # extra per-part reject probability at ST60
    event_rate: dict[tuple[str, str], np.ndarray] = field(default_factory=dict)  # per second

    def get(self, which: str, key: object) -> np.ndarray:
        d: dict = getattr(self, which)
        if key not in d:
            d[key] = np.zeros(self.n)
        return d[key]

    def leak(self) -> np.ndarray:
        if self.air_leak is None:
            self.air_leak = np.zeros(self.n)
        return self.air_leak

    def rejects(self) -> np.ndarray:
        if self.reject_p is None:
            self.reject_p = np.zeros(self.n)
        return self.reject_p

    def add_osc(self, key: TagKey, freq_hz: float, amp: np.ndarray) -> None:
        self.osc.setdefault(key, []).append((freq_hz, amp))


# --- helpers ---------------------------------------------------------------------------------
def first_order(x: np.ndarray, tau_s: float) -> np.ndarray:
    """First-order lag (thermal/pneumatic inertia), initialised at steady state."""
    if tau_s <= 0:
        return x.copy()
    a = float(np.exp(-1.0 / tau_s))
    y, _ = lfilter([1 - a], [1, -a], x, zi=[x[0] * a])
    return np.asarray(y)


def shift_right(x: np.ndarray, lag: int) -> np.ndarray:
    """Delay a series by ``lag`` samples (fill with the first value)."""
    if lag <= 0:
        return x
    out = np.empty_like(x)
    out[:lag] = x[0]
    out[lag:] = x[:-lag]
    return out


def ar1_noise(rng: np.random.Generator, n: int, phi: float) -> np.ndarray:
    """Unit-variance AR(1) noise."""
    w = rng.standard_normal(n)
    y, _ = lfilter([np.sqrt(1 - phi * phi)], [1, -phi], w, zi=[0.0])
    return np.asarray(y)


def quantise(x: np.ndarray, res: float) -> np.ndarray:
    return (np.round(x / res) * res).astype(np.float32)


# --- Simulation ------------------------------------------------------------------------------
@dataclass
class SimResult:
    values: dict[TagKey, np.ndarray]  # float32, quantised, length n
    event_rate: dict[tuple[str, str], np.ndarray]  # (asset_id, code) -> per-second rate
    cycle_starts: dict[str, np.ndarray]  # per series asset: sample indices of part starts
    # (dst, src) -> cycle-time excess at dst caused by src (src == dst: own excess). Only sources
    # with a non-zero own excess are kept. Used to derive causal chains from the physics.
    cycle_contrib: dict[tuple[str, str], np.ndarray]
    underlying: dict[TagKey, np.ndarray]  # noise-free signals (QA/tests only, never written)

    def slice(self, a: int, b: int) -> SimResult:
        return SimResult(
            {k: v[a:b] for k, v in self.values.items()},
            {k: v[a:b] for k, v in self.event_rate.items()},
            {k: v[(v >= a) & (v < b)] - a for k, v in self.cycle_starts.items()},
            {k: v[a:b] for k, v in self.cycle_contrib.items()},
            {k: (v[a:b] if isinstance(v, np.ndarray) else v) for k, v in self.underlying.items()},
        )


def _air_system(tl: Timeline, activity: np.ndarray, leak: np.ndarray, rng: np.random.Generator):
    """Load/unload compressor with a receiver. Demand scales with header pressure (leaks and
    consumers flow less at lower pressure), so a large leak settles at a lower equilibrium."""
    n = tl.n
    base = np.where(tl.night, 0.50, 0.56) * (0.35 + 0.65 * activity)
    base = base * (1 + 0.05 * first_order(rng.standard_normal(n), 120))
    demand_ref = base + leak
    p = np.empty(n)
    loading = np.empty(n, dtype=bool)
    pc = AIR_CUT_IN_BAR + rng.random() * (AIR_CUT_OUT_BAR - AIR_CUT_IN_BAR)
    load = bool(rng.random() < 0.5)
    cap, c = AIR_COMPRESSOR_CAPACITY, AIR_RECEIVER_CAPACITY
    ref = 6.75
    for i in range(n):
        if pc <= AIR_CUT_IN_BAR:
            load = True
        elif pc >= AIR_CUT_OUT_BAR:
            load = False
        q_in = cap if load else 0.0
        pc += (q_in - demand_ref[i] * (pc / ref)) / c
        p[i] = pc
        loading[i] = load
    current = np.where(loading, AIR_LOADED_CURRENT_A, AIR_UNLOADED_CURRENT_A).astype(float)
    duty = first_order(loading.astype(float), 1200)
    oil = first_order(60.0 + 22.0 * duty, 900)
    return p, current, oil


def simulate(tl: Timeline, mods: Modifiers, seed: int) -> SimResult:
    """Produce all 1 Hz tag series for one scenario."""
    n = tl.n
    t = np.arange(n, dtype=float)
    activity = np.where(tl.changeover, 0.25, 1.0)
    ambient = 28.0 + 4.0 * np.sin(2 * np.pi * (tl.local_hour - 9.0) / 24.0)
    rng_phys = rng_for(seed, "physics")
    U: dict[TagKey, np.ndarray] = {}
    osc: dict[TagKey, list[tuple[float, np.ndarray]]] = {k: list(v) for k, v in mods.osc.items()}

    def add(key: TagKey) -> np.ndarray:
        return mods.add.get(key, 0.0)  # type: ignore[return-value]

    # Chiller
    k = ("UT-CHL", "supply_temp_c")
    U[k] = 12.0 + 0.3 * np.sin(2 * np.pi * t / CHILLER_CYCLE_S + rng_phys.random() * 6.28)
    U[k] = U[k] + 0.04 * (ambient - 28.0) + add(k)

    # Plant air
    p, cur, oil = _air_system(tl, activity, mods.leak(), rng_phys)
    U[("UT-AIR", "header_pressure_bar")] = p + add(("UT-AIR", "header_pressure_bar"))
    U[("UT-AIR", "compressor_current_a")] = cur + add(("UT-AIR", "compressor_current_a"))
    U[("UT-AIR", "oil_temp_c")] = oil + 0.3 * (ambient - 28.0) + add(("UT-AIR", "oil_temp_c"))
    header = U[("UT-AIR", "header_pressure_bar")]
    for wid in ("ST20-WLD", "ST30-WLD"):
        reg = np.minimum(AIR_REGULATOR_BAR, header - 0.25)
        k = (wid, "air_pressure_bar")
        U[k] = first_order(reg, 20.0) + add(k)

    # Coolant and servo temperatures
    for wid in ("ST20-WLD", "ST30-WLD"):
        restriction = mods.coolant_restriction.get(wid, np.zeros(n))
        if wid == "ST30-WLD":
            k = (wid, "coolant_flow_lpm")
            U[k] = 12.0 * (1.0 - restriction) + add(k)
        target = (
            U[("UT-CHL", "supply_temp_c")]
            + 0.25 * (ambient - 28.0)
            + 27.0
            + 8.0 * activity
            + COOLANT_HEAT_C * restriction
            + mods.servo_heat.get(wid, 0.0)
        )
        k = (wid, "servo_temp_c")
        U[k] = first_order(target, 600.0) + add(k)

    # Cycle times: own excess (faults + servo derating) then blocking/starvation propagation.
    own: dict[str, np.ndarray] = {}
    for aid in SERIES:
        e = np.array(mods.cycle_excess.get(aid, np.zeros(n)), dtype=float)
        if aid in ("ST20-WLD", "ST30-WLD"):
            e = e + SERVO_DERATE_S_PER_C * np.maximum(
                0.0, U[(aid, "servo_temp_c")] - SERVO_DERATE_START_C
            )
        ck = (aid, "cycle_time_s")
        if ck in mods.spike_prob:  # expected extra time from retries (fixture misalignment)
            e = e + mods.spike_prob[ck] * np.abs(mods.spike_mag.get(ck, 0.0))
        own[aid] = np.maximum(e, 0.0)
    total: dict[str, np.ndarray] = {}
    contrib: dict[tuple[str, str], np.ndarray] = {}
    active = [a for a in SERIES if own[a].any()]
    for src in active:
        contrib[(src, src)] = own[src]
    event_rate: dict[tuple[str, str], np.ndarray] = {
        k2: v.copy() for k2, v in mods.event_rate.items()
    }
    for j, aid in enumerate(SERIES):
        up = np.zeros(n)  # blocked by a slower station downstream
        down = np.zeros(n)  # starved by a slower station upstream
        for i, src in enumerate(SERIES):
            if i == j:
                continue
            d = abs(i - j)
            prop = HOP_ATTENUATION**d * shift_right(own[src], HOP_LAG_S * d)
            if src in active:
                contrib[(aid, src)] = prop
            if i > j:
                up = np.maximum(up, prop)
            else:
                down = np.maximum(down, prop)
        total[aid] = np.maximum(own[aid], np.maximum(up, down))
        stn = asset(aid).station
        for kind, arr in (("BLOCKED", up), ("STARVED", down)):
            excess = np.where(arr > own[aid] + 3.0, arr, 0.0)
            if excess.any():
                rate = np.clip(excess / 4.0, 0, 3) / 1800.0
                rate[tl.changeover] = 0.0
                event_rate[(aid, f"A-{stn}-{kind}")] = rate

    nominal_ct = {"ST10-PRS": 48.0, "ST20-WLD": 50.0, "ST30-WLD": 50.0, "ST40-SLR": 49.0,
                  "ST50-CNV": 45.0, "ST60-VIS": 46.0}  # fmt: skip
    ct_under = {aid: nominal_ct[aid] * np.where(tl.night, 1.02, 1.0) + total[aid] for aid in SERIES}

    # Press
    setpoint = np.where(
        tl.model_idx == PRODUCT_MODELS.index("A"),
        PRODUCT_SETPOINTS["A"][("ST10-PRS", "hyd_pressure_bar")],
        PRODUCT_SETPOINTS["B"][("ST10-PRS", "hyd_pressure_bar")],
    )
    k = ("ST10-PRS", "hyd_pressure_bar")
    U[k] = setpoint + add(k)
    k = ("ST10-PRS", "motor_current_a")
    U[k] = (
        42.0 * (0.4 + 0.6 * activity)
        + 0.08 * (U[("ST10-PRS", "hyd_pressure_bar")] - 180.0)
        + add(k)
    )
    k = ("ST10-PRS", "vibration_rms_mms")
    U[k] = 2.2 * (0.6 + 0.4 * activity) + add(k)
    k = ("ST10-PRS", "oil_temp_c")
    U[k] = first_order(ambient + 15.0 + 3.0 * activity, 1800.0) + add(k)

    # Weld cells (per-cycle quantities: underlying at the time the part is welded)
    rng_dress = rng_for(seed, "tipdress")
    for wid in ("ST20-WLD", "ST30-WLD"):
        k = (wid, "weld_current_ka")
        U[k] = np.full(n, 10.5) + add(k)
        period = 3 * 3600 + int(rng_dress.integers(0, 1800))
        phase = int(rng_dress.integers(0, period))
        saw = ((np.arange(n) + phase) % period) / period
        k = (wid, "tip_resistance_mohm")
        U[k] = 0.146 + 0.008 * saw + add(k)

    # Sealer
    k = ("ST40-SLR", "flow_rate_ccm")
    U[k] = 300.0 * (0.3 + 0.7 * activity) + add(k)
    flow_ratio = U[k] / 300.0
    k = ("ST40-SLR", "pump_pressure_bar")
    U[k] = 120.0 * (0.85 + 0.15 * activity) + add(k)
    osc.setdefault(k, []).append((SEALER_STROKE_HZ, np.full(n, 1.0)))
    k = ("ST40-SLR", "motor_current_a")
    U[k] = 8.5 * (0.5 + 0.5 * activity) + add(k)
    k = ("ST40-SLR", "bead_width_mm")
    U[k] = 4.0 * np.clip(flow_ratio, 0.0, 2.0) ** 0.5 + add(k)

    # Conveyor
    k = ("ST50-CNV", "speed_mpm")
    U[k] = 12.0 + add(k)
    speed = U[k]
    k = ("ST50-CNV", "motor_current_a")
    U[k] = 15.0 * (0.7 + 0.3 * activity) + add(k)
    k = ("ST50-CNV", "vibration_rms_mms")
    U[k] = 1.6 * (0.8 + 0.2 * activity) + add(k)
    k = ("ST50-CNV", "bearing_temp_c")
    U[k] = first_order(ambient + 9.0 + 1.5 * activity, 1800.0) + add(k)
    rot_amp = np.full(n, 0.08)
    osc.setdefault(("ST50-CNV", "vibration_rms_mms"), []).append((CONVEYOR_ROTATION_HZ, rot_amp))
    _ = speed  # rotation frequency held at nominal speed; speed deviations are < 5 %

    # Oscillations (stroke ripple, rotation modulation, fault-driven pulsation)
    rng_phase = rng_for(seed, "phase")
    for key, comps in sorted(osc.items()):
        for f, amp in comps:
            U[key] = U[key] + amp * np.sin(2 * np.pi * f * t + rng_phase.random() * 2 * np.pi)

    # Sensor-only errors (drift) are applied to what the sensor reports.
    for key, arr in mods.measurement.items():
        U[key] = U[key] + arr

    # --- Measured values: per-cycle sampling, noise, spikes, quantisation ---------------------
    values: dict[TagKey, np.ndarray] = {}
    cycle_starts: dict[str, np.ndarray] = {}
    rng_cyc = rng_for(seed, "cycles")
    for aid in SERIES:
        a = asset(aid)
        ck = (aid, "cycle_time_s")
        ct_std = TAG_SPECS[ck].noise_std if ck in TAG_SPECS else 0.4
        nm = mods.noise_mult.get(ck)
        sp = mods.spike_prob.get(ck)
        sm = mods.spike_mag.get(ck)
        starts: list[int] = []
        cts: list[float] = []
        i, since_co = 0, RAMP_UP_CYCLES
        co = tl.changeover
        while i < n:
            if co[i]:
                j = i
                while j < n and co[j]:
                    j += 1
                i, since_co = j, 0
                continue
            mult = 1.0 + (nm[i] if nm is not None else 0.0)
            ct = ct_under[aid][i] + rng_cyc.standard_normal() * ct_std * mult
            if since_co < RAMP_UP_CYCLES:
                ct *= 1.15
            if sp is not None and sp[i] > 0 and rng_cyc.random() < sp[i]:
                ct += abs(sm[i]) * (0.6 + 0.8 * rng_cyc.random()) if sm is not None else 0.0
            ct = max(ct, 10.0)
            starts.append(i)
            cts.append(ct)
            i += round(ct)
            since_co += 1
        st = np.asarray(starts, dtype=np.int64)
        cycle_starts[aid] = st
        bounds = np.append(st, n)
        reps = np.diff(bounds)
        # value shown during cycle k is the measurement of cycle k-1 (cycle time) or of the part
        # just processed (quality tags); before the first cycle, hold the first measurement.
        lead = int(st[0]) if len(st) else n
        for ts_ in a.tags:
            if ts_.kind != "per_cycle":
                continue
            key = (aid, ts_.tag)
            if ts_.tag == "cycle_time_s":
                per = np.asarray(cts)
                per = np.concatenate([[per[0]], per[:-1]])
            elif ts_.tag == "reject_rate_pct":
                per = _reject_rate(st, tl, mods, rng_for(seed, "rejects"))
            else:
                base = U[key][st]
                std = ts_.noise_std * (
                    1.0 + mods.noise_mult[key][st] if key in mods.noise_mult else 1.0
                )
                per = base + rng_for(seed, "pc", aid, ts_.tag).standard_normal(len(st)) * std
                if key in mods.spike_prob:
                    hit = (
                        rng_for(seed, "pcs", aid, ts_.tag).random(len(st))
                        < mods.spike_prob[key][st]
                    )
                    per = per + hit * mods.spike_mag[key][st]
                # benign outliers (~1 per 2 days)
                out = rng_for(seed, "pco", aid, ts_.tag).random(len(st)) < 1.0 / 3500
                per = per + out * 3.0 * ts_.noise_std * np.sign(
                    rng_for(seed, "pcos", aid, ts_.tag).standard_normal(len(st))
                )
            held = np.repeat(per, reps)
            full = np.empty(n)
            full[:lead] = per[0] if len(per) else ts_.nominal
            full[lead:] = held
            if ts_.tag == "cycle_time_s":
                U[key] = ct_under[aid]
            values[key] = quantise(full, ts_.resolution)

    for key, spec in TAG_SPECS.items():
        if spec.kind != "continuous":
            continue
        r = rng_for(seed, "noise", *key)
        noise = ar1_noise(r, n, spec.ar) * spec.noise_std
        if key in mods.noise_mult:
            noise = noise * (1.0 + mods.noise_mult[key])
        x = U[key] + noise
        # benign single-sample spikes, ~1.5 per day per tag
        n_sp = int(r.poisson(1.5 * n / 86400))
        if n_sp:
            pos = r.integers(0, n, n_sp)
            x[pos] += r.choice([-1.0, 1.0], n_sp) * r.uniform(4, 6, n_sp) * spec.noise_std
        if key in mods.spike_prob:
            hit = r.random(n) < mods.spike_prob[key]
            x = x + hit * mods.spike_mag[key] * r.uniform(0.6, 1.4, n)
        values[key] = quantise(x, spec.resolution)

    return SimResult(values, event_rate, cycle_starts, contrib, U)


def _reject_rate(
    st: np.ndarray, tl: Timeline, mods: Modifiers, rng: np.random.Generator
) -> np.ndarray:
    """Per-part reject decisions at ST60 -> % rejects over the last 100 parts."""
    p = np.full(len(st), BASE_REJECT_P)
    if mods.reject_p is not None:
        p = p + mods.reject_p[st]
    # first-off parts after a changeover reject a little more often
    after_co = np.zeros(len(st), dtype=bool)
    co_end = np.flatnonzero(np.diff(tl.changeover.astype(np.int8)) == -1) + 1
    for e in co_end:
        k = int(np.searchsorted(st, e))
        after_co[k : k + 5] = True
    p = np.clip(p + after_co * 0.03, 0, 1)
    prefill = rng.random(REJECT_WINDOW_PARTS) < BASE_REJECT_P
    rej = np.concatenate([prefill, rng.random(len(st)) < p]).astype(float)
    c = np.cumsum(rej)
    w = REJECT_WINDOW_PARTS
    rolling = c[w:] - c[:-w]
    return 100.0 * rolling / w
