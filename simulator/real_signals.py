"""R-set: real public signals mapped onto the synthetic line (SYNTHETIC_DATA_SPEC §4, §8).

    uv run python -m simulator.real_signals --out data/scenarios            # R001-R017
    uv run python -m simulator.real_signals --out data/scenarios --upload   # + GCS audio/vibration
    uv run python -m simulator.real_signals --set C --out data/scenarios    # C001-C010 (confirmation)

Honesty rule: the *root-cause signal* is real and its ground truth comes only from the source
(MetroPT-3 failure reports, UCI hydraulic cycle labels, IMS readme). Everything around it - the
other stations, alarms, shift notes, work orders - is the synthetic line, generated from visible
symptoms only with the same machinery as the S-set. Say "real signals mapped onto a synthetic
line", never "real plant data".

| IDs | Source | Real tags | Truth |
|---|---|---|---|
| R001-R004 | MetroPT-3 failure-report windows #1-#4 | UT-AIR header pressure (TP3), compressor current (Motor_current), oil temp | air_pressure_drop @ UT-AIR, onset = report start |
| R005-R008 | MetroPT-3 normal windows, far from failures and from unlabelled continuous-load episodes | same | no_fault (benign stop) |
| R009-R014 | UCI hydraulic: stable healthy cycles, then one labelled condition | ST10 pressure (PS1), motor current (EPS1), oil temp (TS1), vibration (VS1) | hydraulic_degradation + sub-type, onset = first labelled cycle; or no_fault |
| R015-R017 | IMS test 2, bearing 1 (outer race failure at end of test, readme) | ST50 vibration_rms_mms | no_fault (healthy window) / conveyor_bearing_defect |
| C001-C010 | Confirmation set (pre-registered, eval/preregistration_confirm.md): 5 MetroPT-3 normal windows disjoint from every R window + the 5 unused single-component UCI conditions; IDs are a seeded shuffle | as above | no_fault (benign stop) / hydraulic_degradation + sub-type |

Mapping rules (each is a fixed per-tag transform shared by every scenario; never per-segment
normalisation, so small real shifts survive):

* time: the source wall clock is read as plant local time (UTC+05:30) and shifted by whole days
  into the plant's Aug-Sep 2026 calendar; the shift is in every provenance row;
* MetroPT-3 is 0.1 Hz: upsampled to 1 Hz only *between* two real samples at most 20 s apart
  (linear for pressure/temperature, previous-value hold for motor current); longer source gaps
  stay gaps (no rows) and are listed in ``truth.imperfections`` as ``source_gap`` so the eval
  can check they are never blamed. Downstream weld-cell air is the existing regulator model
  driven by the mapped header (source gaps bridged by holding the last real value *for the
  physics only*);
* UCI 100 Hz -> 1 Hz mean per second; cycles placed back to back at 60 s. The plant has no
  per-second std/max tags, so only the mean is mapped (the 1 Hz mean still shows the valve-lag
  transient at the switching second);
* IMS: RMS of each 1 s / 20,480-sample snapshot (bearing 1 = channel 1), proportionally rescaled
  and held at 1 Hz until the next snapshot (10 min). Raw snapshot files go to
  ``gs://<bucket>/vibration/{scenario_id}/`` for ``spectrum()``; the bearing temperature and drive
  current follow the real vibration through the plant's thermal/load model.

Every real-sourced segment has a provenance row (rows/cycles/files + columns + transform).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

import numpy as np
import pandas as pd
import pyarrow as pa

from agents.schemas import CauseClass
from simulator import alarms as alarm_mod
from simulator import audio as audio_mod
from simulator import imperfections, plant, text_artifacts
from simulator.faults import StopSpec
from simulator.generate import (
    PRE_BUFFER_S,
    SIM_VERSION,
    TS,
    _iso,
    ensure_work_orders,
    write_scenario,
)
from simulator.imperfections import Imperfection
from simulator.plant import Modifiers, TagKey, rng_for
from simulator.text_artifacts import TextGen, TextMode
from simulator.truth_schema import GroundTruth

C = CauseClass
RAW = Path("data/raw")
HISTORY_S = 7 * 86400
MAX_BRIDGE_S = 20  # MetroPT-3: never interpolate between samples further apart than this
PLANT_DATE0 = date(2026, 8, 5)  # plant calendar for R stops: PLANT_DATE0 + 0..49 days
SEED_OFFSET = 100  # R seeds: seed*1000 + 100 + n (S seeds are seed*1000 + n, n <= 60)
SEED_OFFSET_C = 200  # C seeds: seed*1000 + 200 + n
WO_ID_BASE = {"R": 95000, "C": 97000}  # recent-WO ids per set (S uses 90000 + n*10)
SYNTH_TRANSFORM = (
    "simulated at 1 Hz; quantised to sensor resolution; data-quality imperfections applied"
)


# =============================================================================================
# Source facts (copied from the sources; see docs/data_inspection.md)
# =============================================================================================
@dataclass(frozen=True)
class FailureReport:
    """One row of the MetroPT-3 failure-report table (UCI #791 page), deduplicated numbering."""

    number: int
    page_label: str  # numbering as printed on the page (the page prints "#1" twice)
    start: datetime  # naive, source clock
    end: datetime
    failure: str
    severity: str
    report: str  # verbatim; "" when the page gives none


METROPT3_FAILURES: tuple[FailureReport, ...] = (
    FailureReport(1, "#1", datetime(2020, 4, 18, 0, 0), datetime(2020, 4, 18, 23, 59), "Air leak", "High stress", ""),
    FailureReport(2, "#1 (second row)", datetime(2020, 5, 29, 23, 30), datetime(2020, 5, 30, 6, 0), "Air Leak",
                  "High stress", "Maintenance on 30Apr at 12:00"),
    FailureReport(3, "#3", datetime(2020, 6, 5, 10, 0), datetime(2020, 6, 7, 14, 30), "Air Leak", "High stress",
                  "Maintenance on 8Jun at 16:00"),
    FailureReport(4, "#4", datetime(2020, 7, 15, 14, 30), datetime(2020, 7, 15, 19, 0), "Air Leak", "High stress",
                  "Maintenance on 16Jul at 00:00"),
)  # fmt: skip
# Normal windows: >= 3 weeks from any reported failure, and their 7-day history avoids the
# unlabelled continuous-load episodes found in the data (Mar 12, Mar 27/29, Apr 12, May 13,
# May 20, Jun 22) - see docs/data_inspection.md.
METROPT3_NORMAL_STOPS: tuple[datetime, ...] = (
    datetime(2020, 2, 20, 10, 15),
    datetime(2020, 3, 25, 14, 40),
    datetime(2020, 8, 10, 11, 30),
    datetime(2020, 8, 26, 16, 20),
)
# Confirmation-set normal windows (stop, history floor), source clock. Same rules as above (stop
# >= 3 weeks from any reported failure, history free of the continuous-load episodes) plus: no
# source row shared with any R window. One window per free interval left by R001-R008 and the
# episodes; where the interval is shorter than 7 days the history starts at the floor (as R015's
# starts at the first IMS snapshot). Mar 11 afternoon is avoided (8 h of gaps, then low pressure
# leading into the Mar 12 episode). docs/data_inspection/confirm_set.md.
METROPT3_CONFIRM_STOPS: tuple[tuple[datetime, datetime], ...] = (
    (datetime(2020, 2, 13, 8, 20), datetime(2020, 2, 1, 0, 0)),  # R005 history starts 02-13 10:15
    (datetime(2020, 3, 10, 16, 45), datetime(2020, 2, 20, 12, 0)),  # R005 stop 02-20 10:15; episode 03-12 04:04
    (datetime(2020, 3, 18, 12, 30), datetime(2020, 3, 12, 14, 0)),  # episode ends 03-12 12:04; R006 history 03-18 14:40
    (datetime(2020, 8, 19, 14, 10), datetime(2020, 8, 10, 13, 0)),  # R007 stop 08-10 11:30; R008 history 08-19 16:20
    (datetime(2020, 8, 31, 16, 40), datetime(2020, 8, 26, 18, 20)),  # R008 stop 08-26 16:20; data end 09-01 04:00
)  # fmt: skip
METROPT3_CSV = "MetroPT3(AirCompressor).csv"
# The operator's continuous-load rule used for the line-hold stop: trailing 4 h with the
# compressor loaded (Motor_current > 4.8 A, i.e. above the ~3-4 A unloaded-running band) in
# >= 95 % of samples and >= 50 % data coverage. Fires ~4 h after onset in windows #1-#3.
HOLD_WINDOW_S = 4 * 3600
HOLD_LOADED_A = 4.8
HOLD_FRACTION = 0.95
TRANSIENT_MAX_S = 180  # header below its alarm limit for <= 3 min outside the fault = restart dip

# UCI hydraulic: profile.txt columns = cooler %, valve %, pump leakage, accumulator bar, stable
# flag (0 = stable). Stable cycles with exactly one component off-nominal (data_inspection §2,
# re-derived from profile.txt).
UCI_HEALTHY = tuple(range(1787, 1797))  # 100/100/0/130, stable
UCI_CONDITIONS: dict[str, dict[str, Any]] = {
    "pump_leakage_severe": {"cycles": tuple(range(1705, 1715)), "label": (100, 100, 2, 130)},
    "valve_severe_lag": {"cycles": tuple(range(1767, 1777)), "label": (100, 80, 0, 130)},
    "accumulator_near_failure": {"cycles": tuple(range(2186, 2205)), "label": (100, 100, 0, 90)},
    # cooler 3 % ("close to total failure"): the rig's own warm-up at cooler 3 % with every other
    # component optimal (cycles 0-209, flag 1 = not yet static) then the stable cycles 323-332.
    # Using the real warm-up avoids an unphysical 20 degC step at the splice.
    "cooler_near_failure": {"cycles": tuple(range(0, 210)) + tuple(range(323, 333)), "label": (3, 100, 0, 130)},
    # Confirmation set: every other stable single-component condition in profile.txt, names from
    # the UCI documentation. Cooler 20 % (1055-1064) is excluded: its oil runs ~9 degC hotter than
    # the healthy cycles and the rig has no single-component warm-up into it, so the splice would
    # be an unphysical step (the reason R012 uses the cooler-3 % warm-up).
    "pump_leakage_weak": {"cycles": tuple(range(1746, 1756)), "label": (100, 100, 1, 130)},
    "valve_close_to_total_failure": {"cycles": tuple(range(1757, 1767)), "label": (100, 73, 0, 130)},
    "valve_small_lag": {"cycles": tuple(range(1777, 1787)), "label": (100, 90, 0, 130)},
    "accumulator_slightly_reduced": {"cycles": tuple(range(1920, 1930)), "label": (100, 100, 0, 115)},
    "accumulator_severely_reduced": {"cycles": tuple(range(2053, 2063)), "label": (100, 100, 0, 100)},
}  # fmt: skip

# IMS test 2 (readme): 4 bearings, 20 kHz, 20,480 points per 1 s snapshot every 10 min;
# "outer race failure occurred in bearing 1". Last 2 snapshots are dead (rig stopped).
IMS_DIR = "ims_bearings/2nd_test/2nd_test"
IMS_FS_HZ = 20_000  # readme: "Sampling rate is set at 20 kHz"
IMS_POINTS = 20_480
IMS_CHANNEL = 0  # bearing 1
IMS_DEAD_RMS_G = 0.01
IMS_DETAIL = "outer race failure in bearing 1 at end of test (IMS readme, set No. 2)"
IMS_R015_STOP = datetime(2004, 2, 15, 14, 7, 0)  # healthy window
IMS_R016_STOP = datetime(2004, 2, 18, 9, 0, 0)  # degrading (after the 02-17 07:00 step)


# =============================================================================================
# Fixed per-tag mappings
# =============================================================================================
@dataclass(frozen=True)
class TagMap:
    asset_id: str
    tag: str
    column: str
    scale: float
    offset: float
    interp: Literal["linear", "hold", "mean_per_s", "as_is", "snapshot_hold"]
    note: str

    @property
    def key(self) -> TagKey:
        return (self.asset_id, self.tag)

    def apply(self, x: np.ndarray) -> np.ndarray:
        return self.scale * np.asarray(x, dtype=float) + self.offset

    def describe(self) -> str:
        unit = plant.tag_spec(self.asset_id, self.tag).unit
        sign = "+" if self.offset >= 0 else "-"
        return (
            f"fixed affine y = {self.scale:g}*x {sign} {abs(self.offset):g} [{unit}] ({self.note})"
        )


METROPT3_MAPS: tuple[TagMap, ...] = (
    TagMap("UT-AIR", "header_pressure_bar", "TP3", 0.55, 6.2 - 0.55 * 8.0, "linear",
           "TP3 cut-in/cut-out band 8-10 bar -> plant 6.2-7.3 bar; the source's 7 bar low-pressure switch maps to the 5.6 bar alarm"),
    TagMap("UT-AIR", "compressor_current_a", "Motor_current", 11.5, 0.0, "hold",
           "proportional; source max 9.3 A -> 107 A stays under the 110 A alarm"),
    TagMap("UT-AIR", "oil_temp_c", "Oil_temperature", 1.0, 10.0, "linear",
           "median 62.7 degC -> 72.7 degC, the plant nominal 72 degC"),
)  # fmt: skip
UCI_MAPS: tuple[TagMap, ...] = (
    TagMap("ST10-PRS", "hyd_pressure_bar", "PS1", 0.6, 84.1, "mean_per_s",
           "baseline in-cycle range 146.5-191.4 bar -> 172-199 bar inside the 170-200 bar normal band"),
    TagMap("ST10-PRS", "motor_current_a", "EPS1", 0.0165, 0.0, "mean_per_s",
           "motor power W -> current A, proportional; baseline 2540 W -> 42 A nominal"),
    TagMap("ST10-PRS", "oil_temp_c", "TS1", 1.0, 9.7, "as_is", "baseline 36.3 degC -> 46 degC nominal"),
    TagMap("ST10-PRS", "vibration_rms_mms", "VS1", 4.0, 0.0, "as_is", "baseline 0.55 mm/s -> 2.2 mm/s nominal"),
)  # fmt: skip
IMS_MAP = TagMap("ST50-CNV", "vibration_rms_mms", "bearing 1 (channel 1)", 20.8, 0.0, "snapshot_hold",
                 "acceleration RMS g -> velocity-equivalent mm/s, proportional; baseline 0.077 g -> 1.6 mm/s nominal")  # fmt: skip
UCI_HZ = {"PS1": 100, "EPS1": 100, "TS1": 1, "VS1": 1}
# Physics coupling on ST50 from the real vibration (same gains as the S-set bearing fault:
# +15-22 degC and +1.2 A at +6 mm/s).
BRG_TEMP_C_PER_MMS = 3.0
BRG_TAU_S = 1800.0
DRIVE_A_PER_MMS = 0.2


# =============================================================================================
# Small helpers
# =============================================================================================
@dataclass(frozen=True)
class TimeMap:
    """Source naive clock -> plant UTC: the source wall clock becomes plant local time, then a
    whole number of days is added."""

    days: int

    @property
    def shift_s(self) -> int:
        return self.days * 86400 - plant.PLANT_UTC_OFFSET_S

    def to_plant(self, t: datetime) -> datetime:
        return (t.replace(tzinfo=UTC) + timedelta(seconds=self.shift_s)).replace(microsecond=0)

    def epoch(self, t: pd.Series | np.ndarray) -> np.ndarray:
        """Naive source datetimes -> plant epoch seconds (int64)."""
        s = pd.to_datetime(pd.Series(t)).astype("datetime64[s]").astype("int64").to_numpy()
        return s + self.shift_s

    def describe(self) -> str:
        return f"time-shifted +{self.days} d (source clock read as plant local time, UTC+05:30)"


def pick_timemap(seed: int, src_day: date) -> TimeMap:
    target = PLANT_DATE0 + timedelta(days=int(rng_for(seed, "dateshift").integers(0, 50)))
    return TimeMap((target - src_day).days)


def upsample(
    src_s: np.ndarray, x: np.ndarray, grid_s: np.ndarray, mode: Literal["linear", "hold"],
    max_bridge_s: int = MAX_BRIDGE_S,
) -> np.ndarray:  # fmt: skip
    """Irregular real samples -> values on the 1 Hz grid. A grid point gets a value only if it
    coincides with a real sample or lies between two real samples at most ``max_bridge_s``
    apart; everything else is NaN (a gap). Never extrapolates, never bridges a longer gap."""
    src_s = np.asarray(src_s, dtype=np.int64)
    x = np.asarray(x, dtype=float)
    out = np.full(len(grid_s), np.nan)
    if len(src_s) == 0:
        return out
    i = np.searchsorted(src_s, grid_s, side="right") - 1
    inside = (i >= 0) & (i < len(src_s))
    ic = np.clip(i, 0, len(src_s) - 1)
    exact = inside & (src_s[ic] == grid_s)
    nxt = np.clip(ic + 1, 0, len(src_s) - 1)
    has_next = inside & (ic + 1 < len(src_s))
    span = src_s[nxt] - src_s[ic]
    bridged = has_next & (span <= max_bridge_s) & (span > 0)
    out[exact] = x[ic[exact]]
    b = bridged & ~exact
    if mode == "hold":
        out[b] = x[ic[b]]
    else:
        w = (grid_s[b] - src_s[ic[b]]) / span[b]
        out[b] = x[ic[b]] + w * (x[nxt[b]] - x[ic[b]])
    return out


def runs(mask: np.ndarray) -> list[tuple[int, int]]:
    """[start, end) index runs where ``mask`` is True."""
    if not mask.any():
        return []
    d = np.diff(np.concatenate([[0], mask.astype(np.int8), [0]]))
    return list(zip(np.flatnonzero(d == 1).tolist(), np.flatnonzero(d == -1).tolist(), strict=True))


def hold_fill(x: np.ndarray, default: float) -> np.ndarray:
    """Physics driver only: carry the last real value across gaps (first value before data)."""
    s = pd.Series(x).ffill().bfill()
    return s.fillna(default).to_numpy(dtype=float)


def _dt(epoch: int) -> datetime:
    return datetime.fromtimestamp(int(epoch), tz=UTC)


# =============================================================================================
# Source loaders (cached per process)
# =============================================================================================
_CACHE: dict[str, Any] = {}


def load_metropt3(raw: Path = RAW) -> pd.DataFrame:
    if "metropt3" not in _CACHE:
        cols = ["Unnamed: 0", "timestamp", "TP3", "Motor_current", "Oil_temperature"]
        df = pd.read_csv(raw / "metropt3" / METROPT3_CSV, usecols=cols, parse_dates=["timestamp"])
        _CACHE["metropt3"] = df.rename(columns={"Unnamed: 0": "index"})
    return _CACHE["metropt3"]


def load_uci(raw: Path = RAW) -> dict[str, np.ndarray]:
    if "uci" not in _CACHE:
        d = raw / "uci_hydraulic"
        out = {
            c: pd.read_csv(d / f"{c}.txt", sep="\t", header=None).to_numpy(float) for c in UCI_HZ
        }
        out["profile"] = pd.read_csv(d / "profile.txt", sep="\t", header=None).to_numpy(int)
        _CACHE["uci"] = out
    return _CACHE["uci"]


@dataclass(frozen=True)
class Snapshot:
    name: str  # source file name = source timestamp
    t: datetime  # naive source time
    rms_g: float


def load_ims(raw: Path = RAW) -> list[Snapshot]:
    if "ims" not in _CACHE:
        d = raw / IMS_DIR
        snaps = []
        for p in sorted(d.iterdir()):
            if not p.is_file() or p.name.count(".") != 5:
                continue
            x = pd.read_csv(p, sep="\t", header=None, usecols=[IMS_CHANNEL]).to_numpy(float)[:, 0]
            snaps.append(Snapshot(p.name, datetime.strptime(p.name, "%Y.%m.%d.%H.%M.%S"),
                                  float(np.sqrt(np.mean(x**2)))))  # fmt: skip
        _CACHE["ims"] = snaps
    return _CACHE["ims"]


def live_snapshots(snaps: list[Snapshot]) -> list[Snapshot]:
    """Drop the dead tail (RMS ~0.002 g after the rig stopped; data_inspection §3)."""
    last = max(i for i, s in enumerate(snaps) if s.rms_g > IMS_DEAD_RMS_G)
    return snaps[: last + 1]


def first_crossing_after(sim: plant.SimResult, tl: plant.Timeline, key: TagKey, level: str,
                         after: int) -> int | None:  # fmt: skip
    """``alarms.first_crossing`` restricted to samples at or after ``after`` (same persistence
    and changeover-inhibit rule), so an earlier real transient cannot hide the fault's alarm."""
    spec = plant.TAG_SPECS[key]
    x = sim.values[key]
    ok = np.zeros(tl.n, dtype=bool)
    ok[max(after, 0) :] = True
    for i in tl.shift_starts:
        ok[i : i + alarm_mod.CHANGEOVER_INHIBIT_S] = False
    lims = (spec.trip_lo, spec.trip_hi) if level == "trip" else (spec.alarm_lo, spec.alarm_hi)
    best: int | None = None
    for lim, low in zip(lims, (True, False), strict=True):
        if lim is None:
            continue
        mask = ((x < lim) if low else (x > lim)) & ok
        for a, b in runs(mask):
            if b - a >= alarm_mod.PERSIST_S:
                i = a + alarm_mod.PERSIST_S - 1
                best = i if best is None else min(best, i)
                break
    return best


def hold_rule_fire(df: pd.DataFrame, after: datetime, until: datetime) -> datetime | None:
    """First time in [after, until] the continuous-load rule fires on the source samples."""
    s = df.set_index("timestamp")["Motor_current"]
    s = s.loc[after - timedelta(seconds=HOLD_WINDOW_S) : until]
    loaded = (s > HOLD_LOADED_A).astype(float)
    frac = loaded.rolling(f"{HOLD_WINDOW_S}s").mean()
    cnt = loaded.rolling(f"{HOLD_WINDOW_S}s").count()
    fire = (frac >= HOLD_FRACTION) & (cnt >= 0.5 * HOLD_WINDOW_S / 10)
    fire = fire[(fire.index >= after) & (fire.index <= until)]
    return fire.index[fire.to_numpy()][0].to_pydatetime() if fire.any() else None


# =============================================================================================
# Per-scenario specification
# =============================================================================================
Kind = Literal["metropt3_failure", "metropt3_normal", "uci", "ims"]


@dataclass(frozen=True)
class RSpec:
    sid: str
    kind: Kind
    report: FailureReport | None = None
    normal_stop: datetime | None = None
    condition: str | None = None  # UCI condition name (None = healthy)
    benign: tuple[str, str, str] | None = None  # (station asset, glitch kind, tag or "")
    ims_window: Literal["healthy", "degrading", "near_failure"] | None = None
    floor: datetime | None = None  # MetroPT-3 normal (C-set): no source row before this is used


R_SPECS: tuple[RSpec, ...] = (
    *(RSpec(f"R{k:03d}", "metropt3_failure", report=r) for k, r in enumerate(METROPT3_FAILURES, 1)),
    RSpec("R005", "metropt3_normal", normal_stop=METROPT3_NORMAL_STOPS[0], benign=("ST20-WLD", "sensor_spike", "air_pressure_bar")),
    RSpec("R006", "metropt3_normal", normal_stop=METROPT3_NORMAL_STOPS[1], benign=("ST30-WLD", "comm_timeout", "")),
    RSpec("R007", "metropt3_normal", normal_stop=METROPT3_NORMAL_STOPS[2], benign=("ST30-WLD", "sensor_spike", "air_pressure_bar")),
    RSpec("R008", "metropt3_normal", normal_stop=METROPT3_NORMAL_STOPS[3], benign=("ST20-WLD", "safety_trip", "")),
    RSpec("R009", "uci", condition="pump_leakage_severe"),
    RSpec("R010", "uci", condition="valve_severe_lag"),
    RSpec("R011", "uci", condition="accumulator_near_failure"),
    RSpec("R012", "uci", condition="cooler_near_failure"),
    RSpec("R013", "uci", benign=("ST10-PRS", "hpu_not_ready", "")),
    RSpec("R014", "uci", benign=("ST10-PRS", "safety_trip", "")),
    RSpec("R015", "ims", ims_window="healthy", benign=("ST50-CNV", "comm_timeout", "")),
    RSpec("R016", "ims", ims_window="degrading"),
    RSpec("R017", "ims", ims_window="near_failure"),
)  # fmt: skip


def _confirm_specs(seed: int = 2026) -> tuple[RSpec, ...]:
    """C-set (pre-registered in eval/preregistration_confirm.md): 5 MetroPT-3 normal windows with
    the R005-R008 stop mix (air-sounding glitches included) and the 5 unused UCI conditions. IDs
    are a seeded shuffle, so an ID never leaks its cause."""
    benign = (("ST20-WLD", "sensor_spike", "air_pressure_bar"), ("ST30-WLD", "comm_timeout", ""),
              ("ST30-WLD", "sensor_spike", "air_pressure_bar"), ("ST20-WLD", "safety_trip", ""),
              ("ST20-WLD", "sensor_spike", "air_pressure_bar"))  # fmt: skip
    base: list[dict[str, Any]] = [
        {"kind": "metropt3_normal", "normal_stop": stop, "floor": floor, "benign": b}
        for (stop, floor), b in zip(METROPT3_CONFIRM_STOPS, benign, strict=True)
    ]
    base += [{"kind": "uci", "condition": c} for c in CONFIRM_UCI_CONDITIONS]
    order = rng_for(seed, "confirm_ids").permutation(len(base))
    return tuple(RSpec(f"C{k:03d}", **base[int(j)]) for k, j in enumerate(order, 1))


CONFIRM_UCI_CONDITIONS = ("pump_leakage_weak", "valve_close_to_total_failure", "valve_small_lag",
                          "accumulator_slightly_reduced", "accumulator_severely_reduced")  # fmt: skip
C_SPECS: tuple[RSpec, ...] = _confirm_specs()
SPECS_BY_SET = {"R": R_SPECS, "C": C_SPECS}


@dataclass
class Real:
    """Real-mapped values on the simulation grid plus everything needed for provenance."""

    values: dict[TagKey, np.ndarray]  # NaN = no data
    source_id: str
    timemap: TimeMap | None
    pieces: list[tuple[TagKey, int, int, str, str]] = field(
        default_factory=list
    )  # key,e0,e1,ref,transform
    source_gaps: list[tuple[int, int]] = field(default_factory=list)  # epoch [t0, t1)
    segment_meta: list[dict[str, Any]] = field(default_factory=list)
    piece_fn: Callable[[int, int], list[tuple[TagKey, int, int, str, str]]] | None = None


# --- MetroPT-3 -------------------------------------------------------------------------------
def metropt3_real(df: pd.DataFrame, tm: TimeMap, grid_s: np.ndarray) -> Real:
    lo, hi = int(grid_s[0]) - 3600, int(grid_s[-1]) + 3600
    src_s = tm.epoch(df["timestamp"])
    sel = (src_s >= lo) & (src_s <= hi)
    s_s, sub = src_s[sel], df.loc[sel]
    vals = {
        m.key: m.apply(upsample(s_s, sub[m.column].to_numpy(float), grid_s, m.interp))  # type: ignore[arg-type]
        for m in METROPT3_MAPS
    }
    # quantise to sensor resolution (NaN stays NaN)
    vals = {
        k: np.round(v / plant.TAG_SPECS[k].resolution) * plant.TAG_SPECS[k].resolution
        for k, v in vals.items()
    }
    idx = sub["index"].to_numpy(np.int64)
    real = Real(vals, "metropt3", tm)
    full = dict(vals)  # the closure keeps the full-grid arrays (real.values gets sliced later)

    def pieces(e0: int, e1: int) -> list[tuple[TagKey, int, int, str, str]]:
        out = []
        g = (grid_s >= e0) & (grid_s < e1)
        for m in METROPT3_MAPS:
            ok = ~np.isnan(full[m.key]) & g
            for a, b in runs(ok):
                t0, t1 = int(grid_s[a]), int(grid_s[b - 1]) + 1
                j0 = int(np.searchsorted(s_s, t0, "left"))
                j1 = int(np.searchsorted(s_s, t1 - 1, "right")) - 1
                j1 = max(j1, j0)
                # row indices identify the source exactly; source dates are kept out of the
                # agent-visible text (they could be matched against the published failure table)
                ref = f"{METROPT3_CSV} rows index {idx[j0]}-{idx[j1]} ({j1 - j0 + 1} samples), column {m.column}"
                tr = (f"0.1 Hz -> 1 Hz ({'linear interpolation' if m.interp == 'linear' else 'previous-value hold'} "
                      f"only between samples <= {MAX_BRIDGE_S} s apart; no rows across longer source gaps); "
                      f"{m.describe()}; {tm.describe()}; quantised to {plant.TAG_SPECS[m.key].resolution:g}")  # fmt: skip
                out.append((m.key, t0, t1, ref, tr))
        return out

    real.piece_fn = pieces
    # source gaps (> MAX_BRIDGE_S) on the grid, as epoch ranges of the missing rows
    any_ok = ~np.isnan(full[METROPT3_MAPS[0].key])
    for a, b in runs(~any_ok):
        real.source_gaps.append((int(grid_s[a]), int(grid_s[b - 1]) + 1))
    return real


# --- UCI hydraulic ---------------------------------------------------------------------------
def uci_cycle_series(
    uci: dict[str, np.ndarray], cycles: tuple[int, ...]
) -> dict[TagKey, np.ndarray]:
    """Per-second mapped values for consecutive cycles (60 s each)."""
    out: dict[TagKey, np.ndarray] = {}
    for m in UCI_MAPS:
        x = uci[m.column][list(cycles)]
        hz = UCI_HZ[m.column]
        per_s = x.reshape(len(cycles), 60, hz).mean(axis=2) if hz > 1 else x
        v = m.apply(per_s.reshape(-1))
        res = plant.TAG_SPECS[m.key].resolution
        out[m.key] = np.round(v / res) * res
    return out


def uci_real(uci: dict[str, np.ndarray], condition: str | None, grid_s: np.ndarray,
             stop_epoch: int) -> tuple[Real, int | None]:  # fmt: skip
    """Healthy cycles looped from the grid start, then (optionally) the condition's cycles
    ending exactly at the stop. Returns (real, onset epoch or None)."""
    n = len(grid_s)
    healthy = uci_cycle_series(uci, UCI_HEALTHY)
    fault_cycles: tuple[int, ...] = UCI_CONDITIONS[condition]["cycles"] if condition else ()
    fault = uci_cycle_series(uci, fault_cycles) if condition else {}
    n_fault = 60 * len(fault_cycles)
    end_i = int(stop_epoch - grid_s[0])
    onset_i = end_i - n_fault
    vals: dict[TagKey, np.ndarray] = {}
    period = 60 * len(UCI_HEALTHY)
    for m in UCI_MAPS:
        v = np.full(n, np.nan)
        # loop healthy so the loop *ends* at a cycle boundary at the onset (seamless splice)
        k = (np.arange(onset_i) - onset_i) % period
        v[:onset_i] = healthy[m.key][k]
        if condition:
            v[onset_i:end_i] = fault[m.key]
        vals[m.key] = v
    real = Real(vals, "uci_hydraulic", None)
    prof = uci["profile"]

    def lab(c: int) -> str:  # hidden metadata only: labels never go into visible provenance
        p = prof[c]
        return f"cooler {p[0]}%, valve {p[1]}%, pump leakage {p[2]}, accumulator {p[3]} bar, stable flag {p[4]}"

    def tr(m: TagMap, reps: float) -> str:
        hz = UCI_HZ[m.column]
        rs = f"{hz} Hz -> 1 Hz mean per second; " if hz > 1 else "1 Hz as recorded; "
        return (f"{rs}cycles placed back to back at 60 s, in source order, x{reps:.1f}; {m.describe()}; "
                f"quantised to {plant.TAG_SPECS[m.key].resolution:g}")  # fmt: skip

    # The last real piece is always a separate row (the condition's cycles, or for a healthy
    # scenario its last 10 healthy cycles), so the provenance layout is the same either way.
    tail: list[list[int]] = _contiguous(fault_cycles) if condition else [list(UCI_HEALTHY)]

    def pieces(e0: int, e1: int) -> list[tuple[TagKey, int, int, str, str]]:
        out = []
        t_split = int(grid_s[0]) + end_i - 60 * sum(len(x) for x in tail)
        reps = (t_split - e0) / period
        for m in UCI_MAPS:
            cols = f"UCI hydraulic {m.column}.txt rows (cycles)"
            if e0 < t_split:
                out.append(
                    (m.key, e0, t_split, f"{cols} {UCI_HEALTHY[0]}-{UCI_HEALTHY[-1]}", tr(m, reps))
                )
            t = t_split
            for seg in tail:
                t1 = t + 60 * len(seg)
                out.append((m.key, t, t1, f"{cols} {seg[0]}-{seg[-1]}", tr(m, 1.0)))
                t = t1
        return out

    real.piece_fn = pieces
    real.segment_meta = [{"healthy_cycles": list(UCI_HEALTHY), "healthy_label": lab(UCI_HEALTHY[0]),
                          "condition": condition, "fault_cycles": list(fault_cycles),
                          "fault_labels": sorted({lab(c) for c in fault_cycles}),
                          "onset_epoch": int(grid_s[0]) + onset_i if condition else None}]  # fmt: skip
    return real, (int(grid_s[0]) + onset_i if condition else None)


def _contiguous(c: tuple[int, ...]) -> list[list[int]]:
    out: list[list[int]] = []
    for x in c:
        if out and x == out[-1][-1] + 1:
            out[-1].append(x)
        else:
            out.append([x])
    return out


# --- IMS -------------------------------------------------------------------------------------
def ims_real(snaps: list[Snapshot], tm: TimeMap, grid_s: np.ndarray, bucket: str, sid: str) -> Real:
    t_s = tm.epoch(np.array([s.t for s in snaps], dtype="datetime64[s]"))
    rms = np.array([s.rms_g for s in snaps])
    v = np.full(len(grid_s), np.nan)
    i = np.searchsorted(t_s, grid_s, side="right") - 1
    ok = (i >= 0) & (grid_s < t_s[-1] + 600)
    v[ok] = IMS_MAP.apply(rms[i[ok]])
    v = np.round(v / 0.01) * 0.01
    real = Real({IMS_MAP.key: v}, "ims_bearings", tm)

    def pieces(e0: int, e1: int) -> list[tuple[TagKey, int, int, str, str]]:
        out = []
        for k, s in enumerate(snaps):
            a = int(t_s[k])
            b = int(t_s[k + 1]) if k + 1 < len(snaps) else a + 600
            a, b = max(a, e0), min(b, e1)
            if a >= b:
                continue
            uri = f"gs://{bucket}/vibration/{sid}/{_dt(int(t_s[k])).strftime('%Y%m%dT%H%M%SZ')}.txt"
            out.append((IMS_MAP.key, a, b,
                        f"IMS 2nd_test/{s.name}, channel 1 (bearing 1) of 4, {IMS_POINTS} points",
                        f"RMS of the 1 s snapshot ({IMS_POINTS} samples at {IMS_FS_HZ // 1000} kHz, g); {IMS_MAP.describe()}; "
                        f"held at 1 Hz until the next snapshot (10 min); {tm.describe()}; raw snapshot (4 ch, unmodified) at {uri}"))  # fmt: skip
        return out

    real.piece_fn = pieces
    return real


# =============================================================================================
# Stops (benign glitches for no_fault, source-symptom stops for faults)
# =============================================================================================
def benign_stop(station: str, kind: str, tag: str, mods: Modifiers, n: int) -> tuple[StopSpec, str]:
    a = plant.asset(station)
    if kind == "sensor_spike":
        t = plant.tag_spec(station, tag)
        lim = t.trip_lo
        assert lim is not None
        excursion = (lim - t.nominal) - abs(lim - t.nominal) * 0.15
        mods.get("measurement", (station, tag))[n - 3 : n - 1] += excursion
        return (StopSpec(station, f"S-{a.station}-{t.abbr}-LL", f"{a.name}: {t.label} low-low trip"),
                f"sensor_spike: single 2s spike on {station}.{tag}")  # fmt: skip
    if kind == "comm_timeout":
        return (StopSpec(station, f"S-{a.station}-COMM-TO", f"{a.name}: fieldbus watchdog timeout"),
                "comm_timeout: fieldbus watchdog timeout, recovered on reset")  # fmt: skip
    if kind == "safety_trip":
        return (StopSpec(station, f"S-{a.station}-LC-TRIP", f"{a.name}: light curtain interrupted, safety stop"),
                "safety_trip: light curtain interrupted (person/part in guarded zone)")  # fmt: skip
    if kind == "hpu_not_ready":
        return (StopSpec(station, f"S-{a.station}-HPU-NRDY", f"{a.name}: hydraulic power unit not ready, press stopped"),
                "hpu_not_ready: HPU ready signal dropped for 2 s (I/O glitch), cleared on reset")  # fmt: skip
    raise ValueError(kind)


AIR_LO = {c: StopSpec(c, f"S-{plant.asset(c).station}-AIR-LO", f"{plant.asset(c).name}: gun air pressure low, cell stopped",
                      ((c, "air_pressure_bar"),), "alarm") for c in ("ST20-WLD", "ST30-WLD")}  # fmt: skip
AIR_HOLD = StopSpec("ST20-WLD", "S-ST20-AIR-HOLD",
                    "ST20 Weld cell A: line held by line lead, plant air compressor running loaded continuously (utilities check)",
                    (("UT-AIR", "compressor_current_a"),))  # fmt: skip
HYD_FLT = StopSpec("ST10-PRS", "S-ST10-HYD-FLT", "ST10 Press: hydraulic fault, press stopped",
                   (("ST10-PRS", "hyd_pressure_bar"), ("ST10-PRS", "oil_temp_c")))  # fmt: skip
VIB_HH = StopSpec("ST50-CNV", "S-ST50-VIB-HH", "Conveyor drive stopped: vibration high-high",
                  (("ST50-CNV", "vibration_rms_mms"),), "trip")  # fmt: skip
CM_WARN = StopSpec("ST50-CNV", "S-ST50-CM-WARN",
                   "ST50 Conveyor: condition-monitor vibration warning, conveyor stopped for inspection",
                   (("ST50-CNV", "vibration_rms_mms"),))  # fmt: skip


# =============================================================================================
# Build one R scenario
# =============================================================================================
@dataclass
class Plan:
    """Where the scenario sits in source and plant time, before simulation."""

    end: datetime  # provisional end of the simulated grid (plant UTC, exclusive)
    history_s: int
    timemap: TimeMap | None
    onset: datetime | None = None  # truth onset (plant) from the source label
    fixed_stop: bool = True  # False: the stop is the first limit crossing before `end`
    start_floor: datetime | None = None  # history may not start before this (IMS: first snapshot)


def _plant_time_of_day(seed: int, day: date, lo_h: float = 7.0, hi_h: float = 21.0) -> datetime:
    sec = int(rng_for(seed, "stop_tod").integers(int(lo_h * 3600), int(hi_h * 3600)))
    local = datetime(day.year, day.month, day.day, tzinfo=UTC) + timedelta(seconds=sec)
    return local - timedelta(seconds=plant.PLANT_UTC_OFFSET_S)


def build_r(spec: RSpec, seed: int, gen: TextGen, wo_pool: list[dict[str, Any]], raw: Path = RAW,
            bucket: str = audio_mod.DEFAULT_BUCKET) -> dict[str, Any]:  # fmt: skip
    sid = spec.sid
    real_tags: set[TagKey]
    coupled: dict[TagKey, str] = {}
    meta_real: dict[str, Any] = {"source": None}
    snaps: list[Snapshot] = []

    # ---- 1. place the window in source and plant time --------------------------------------
    if spec.kind == "metropt3_failure":
        r = spec.report
        assert r is not None
        df = load_metropt3(raw)
        tm = pick_timemap(seed, r.end.date())
        hold = hold_rule_fire(df, r.start, r.end)
        end_src = min(hold, r.end) if hold else r.end
        pl = Plan(tm.to_plant(end_src) + timedelta(seconds=1), HISTORY_S, tm, onset=tm.to_plant(r.start),
                  fixed_stop=False)  # fmt: skip
        meta_real.update(hold_rule_src=str(hold) if hold else None)
        real_tags = {m.key for m in METROPT3_MAPS}
    elif spec.kind == "metropt3_normal":
        df = load_metropt3(raw)
        assert spec.normal_stop is not None
        tm = pick_timemap(seed, spec.normal_stop.date())
        hist = HISTORY_S
        if spec.floor is not None:
            hist = min(HISTORY_S, int((spec.normal_stop - spec.floor).total_seconds()))
        pl = Plan(tm.to_plant(spec.normal_stop), hist, tm)
        real_tags = {m.key for m in METROPT3_MAPS}
    elif spec.kind == "uci":
        uci = load_uci(raw)
        day = PLANT_DATE0 + timedelta(days=int(rng_for(seed, "dateshift").integers(0, 50)))
        pl = Plan(_plant_time_of_day(seed, day), HISTORY_S, None)
        real_tags = {m.key for m in UCI_MAPS}
    else:
        snaps = live_snapshots(load_ims(raw))
        if spec.ims_window == "healthy":
            src_end, fixed = IMS_R015_STOP, True
        elif spec.ims_window == "degrading":
            src_end, fixed = IMS_R016_STOP, True
        else:
            src_end, fixed = snaps[-1].t + timedelta(seconds=1), False
        tm = pick_timemap(seed, src_end.date())
        first = tm.to_plant(snaps[0].t)
        pl = Plan(tm.to_plant(src_end), int((tm.to_plant(src_end) - first).total_seconds()), tm,
                  fixed_stop=fixed, start_floor=first)  # fmt: skip
        real_tags = {IMS_MAP.key}
        coupled = {
            ("ST50-CNV", "bearing_temp_c"): f"bearing temperature rises {BRG_TEMP_C_PER_MMS:g} degC per mm/s of real-mapped vibration above 1.6 mm/s (first-order lag {BRG_TAU_S / 60:.0f} min)",
            ("ST50-CNV", "motor_current_a"): f"drive current rises {DRIVE_A_PER_MMS:g} A per mm/s of real-mapped vibration above 1.6 mm/s",
        }  # fmt: skip

    # ---- 2. timeline + real values on the grid ---------------------------------------------
    sim_s = pl.history_s + PRE_BUFFER_S
    tl = plant.make_timeline(pl.end, sim_s, rng_for(seed, "timeline"))
    grid = tl.epoch_s()
    mods = Modifiers(tl.n)
    onset_epoch = int(pl.onset.timestamp()) if pl.onset else None
    if spec.kind.startswith("metropt3"):
        real = metropt3_real(df, tm, grid)
        if spec.floor is not None:
            # C-set: no source row before the history start, not even for the pre-buffer physics
            # (the regulator model is warmed up on the first real header value instead)
            cut = tl.n - pl.history_s
            for v in real.values.values():
                v[:cut] = np.nan
            real.source_gaps = [(a, b) for a, b in real.source_gaps if b > int(grid[cut])]
        hdr = real.values[("UT-AIR", "header_pressure_bar")]
        mods.header_override = hold_fill(hdr, 6.75)
        coupled = {(c, "air_pressure_bar"): "regulated gun air from the plant's regulator model min(5.6, header - 0.25) bar, "
                   "first-order lag 20 s, driven by the real-mapped UT-AIR header pressure (source gaps bridged by holding the last real value, for the physics only)"
                   for c in ("ST20-WLD", "ST30-WLD")}  # fmt: skip
    elif spec.kind == "uci":
        real, onset_epoch = uci_real(uci, spec.condition, grid, int(pl.end.timestamp()))
    else:
        real = ims_real(snaps, tm, grid, bucket, sid)
        vib = hold_fill(real.values[IMS_MAP.key], 1.6)
        excess = np.maximum(vib - 1.6, 0.0)
        mods.get("add", ("ST50-CNV", "bearing_temp_c"))[:] += (
            BRG_TEMP_C_PER_MMS * plant.first_order(excess, BRG_TAU_S)
        )
        mods.get("add", ("ST50-CNV", "motor_current_a"))[:] += DRIVE_A_PER_MMS * excess

    # benign glitch (no_fault) - placed at the very end of the grid, which is the stop
    detail: str | None = None
    if spec.benign:
        stop_spec, detail = benign_stop(*spec.benign, mods, tl.n)

    sim = plant.simulate(tl, mods, seed)
    for k, v in real.values.items():
        sim.values[k] = v.astype(np.float32)
        sim.underlying[k] = v

    # ---- 3. the stop -----------------------------------------------------------------------
    end = tl.n
    cause: CauseClass
    if spec.kind == "metropt3_failure":
        cause = C.AIR_PRESSURE_DROP
        on_i = onset_epoch - int(grid[0])  # type: ignore[operator]
        cross = []
        for c in ("ST20-WLD", "ST30-WLD"):
            ci = first_crossing_after(sim, tl, (c, "air_pressure_bar"), "alarm", on_i)
            if ci is not None:
                cross.append((ci, c))
        if cross:
            ci, cell = min(cross)
            end, stop_spec = ci + 1, AIR_LO[cell]
        else:
            stop_spec = AIR_HOLD  # continuous-load hold at the provisional end
        detail = f"MetroPT-3 failure report {spec.report.page_label}: {spec.report.failure}, severity {spec.report.severity}"  # type: ignore[union-attr]
    elif spec.kind == "metropt3_normal":
        cause = C.NO_FAULT
    elif spec.kind == "uci":
        if spec.condition:
            cause, stop_spec, detail = C.HYDRAULIC_DEGRADATION, HYD_FLT, spec.condition
        else:
            cause = C.NO_FAULT
    else:
        if spec.ims_window == "healthy":
            cause = C.NO_FAULT
        else:
            cause, detail = C.CONVEYOR_BEARING_DEFECT, f"{IMS_DETAIL}; window: {spec.ims_window}"
            if spec.ims_window == "degrading":
                stop_spec = CM_WARN
            else:
                ci = first_crossing_after(sim, tl, IMS_MAP.key, "trip", 0)
                assert ci is not None, "near-failure window must reach the vibration trip"
                end, stop_spec = ci + 1, VIB_HH
    if not pl.fixed_stop and end == tl.n and stop_spec is not AIR_HOLD:
        raise AssertionError(f"{sid}: no stop found")
    start = end - pl.history_s
    if pl.start_floor is not None:
        start = max(start, int((pl.start_floor - tl.start).total_seconds()))
    tl, sim = tl.slice(start, end), sim.slice(start, end)
    for k in list(real.values):
        real.values[k] = real.values[k][start:end]
    grid = grid[start:end]
    e0, e1 = int(grid[0]), int(grid[-1]) + 1
    onset_i = None if onset_epoch is None else onset_epoch - e0

    # ---- 4. causal chain + onsets (root from the source; downstream from the physics) ------
    root: str | None = None
    chain: list[str] = []
    asset_onsets: dict[str, int] = {}
    if cause is not C.NO_FAULT:
        root = {C.AIR_PRESSURE_DROP: "UT-AIR", C.HYDRAULIC_DEGRADATION: "ST10-PRS",
                C.CONVEYOR_BEARING_DEFECT: "ST50-CNV"}[cause]  # fmt: skip
        chain = [root]
        if cause is C.AIR_PRESSURE_DROP:
            asset_onsets[root] = int(onset_i)  # type: ignore[arg-type]
            for c in ("ST20-WLD", "ST30-WLD"):
                u = sim.underlying[(c, "air_pressure_bar")]
                low = np.flatnonzero(u[onset_i:] < plant.tag_spec(c, "air_pressure_bar").normal_lo)
                if len(low) >= 60:
                    chain.append(c)
                    asset_onsets[c] = int(onset_i + low[0])  # type: ignore[operator]
        elif onset_i is not None:
            asset_onsets[root] = int(onset_i)
    # IMS has no documented onset: protect imperfections around the first sustained rise
    audible_i: int | None = None
    if cause is C.CONVEYOR_BEARING_DEFECT:
        v = real.values[IMS_MAP.key]
        hi = np.nan_to_num(v, nan=0.0) > plant.tag_spec(*IMS_MAP.key).normal_hi
        rr = [(a, b) for a, b in runs(hi) if b - a >= 1800]
        audible_i = rr[0][0] if rr else int(0.9 * tl.n)
        asset_onsets[root] = audible_i  # type: ignore[index]

    # ---- 5. alarms, notes, WOs, imperfections ----------------------------------------------
    alarms = alarm_mod.build_alarms(sim, tl, stop_spec, seed)
    nrng = rng_for(seed, "notes")
    slots = text_artifacts.note_slots(tl, alarms, stop_spec.text, nrng)
    notes = gen.run(text_artifacts.shift_notes(sid, slots, gen, nrng))
    notes.sort(key=lambda x: x.ts)
    wrng = rng_for(seed, "recent_wos")
    wos = (
        text_artifacts.recent_wos(wo_pool, tl.stop, sid, wrng, int(wrng.integers(2, 6)))
        if wo_pool
        else []
    )
    wos = sorted(wos, key=lambda w: w["date"])
    for j, w in enumerate(wos):
        w["wo_id"] = f"WO-{w['date']:%y}{WO_ID_BASE[sid[0]] + int(sid[1:]) * 10 + j:05d}"
    touched = set(real_tags) | set(coupled)
    if spec.benign and spec.benign[2]:
        touched.add((spec.benign[0], spec.benign[2]))
    imp = imperfections.apply(
        tl, sim.values, alarms, notes, rng=rng_for(seed, "imperfections"), asset_onsets=asset_onsets,
        excluded_assets=set(chain) | {stop_spec.station}, excluded_tags=touched, real_tags=frozenset(real_tags),
    )  # fmt: skip
    for k in real_tags:
        imp.keep[k] = ~np.isnan(real.values[k])
        imp.values[k] = real.values[k].astype(np.float32)
    items = [i.to_str() for i in imp.items]
    for g0, g1 in real.source_gaps:
        g0, g1 = max(g0, e0), min(g1, e1)
        if g1 > g0:
            items.append(Imperfection("source_gap", "UT-AIR", "*", _dt(g0), _dt(g1),
                                      f"duration_s={g1 - g0};source=metropt3").to_str())  # fmt: skip
    if spec.kind.startswith("metropt3"):  # short real dips (compressor restarts after a gap)
        hdr = real.values[("UT-AIR", "header_pressure_bar")]
        lim = plant.tag_spec("UT-AIR", "header_pressure_bar").alarm_lo
        low = np.nan_to_num(hdr, nan=99.0) < lim
        if onset_i is not None:
            low[onset_i:] = False
        for a, b in runs(low):
            if b - a <= TRANSIENT_MAX_S:
                items.append(Imperfection("source_transient", "UT-AIR", "header_pressure_bar", tl.ts(a), tl.ts(b),
                                          f"min={float(np.nanmin(hdr[a:b])):.2f};source=metropt3").to_str())  # fmt: skip
    items.sort()

    # ---- 6. truth, stop event, provenance, meta --------------------------------------------
    variant = "no_fault" if cause is C.NO_FAULT else "clean"
    truth = GroundTruth(
        scenario_id=sid, seed=seed, scenario_set="real_signal", truth_source="source_label",
        variant=variant, root_cause_class=cause, asset_id=root,
        onset_ts=pl.onset if spec.kind == "metropt3_failure" else (_dt(onset_epoch) if spec.kind == "uci" and onset_epoch else None),
        detail=detail, causal_chain=chain, secondary_cause=None, distractors=[], imperfections=items,
        stop_station=stop_spec.station, stop_ts=tl.stop,
    )  # fmt: skip
    stop_event = {
        "scenario_id": sid, "line_id": plant.LINE_ID, "stop_ts": _iso(tl.stop),
        "stopped_station": stop_spec.station, "stop_code": stop_spec.code, "stop_text": stop_spec.text,
        "shift": tl.shift_at(tl.n - 1), "product_model": tl.model_at(tl.n - 1),
        "history_start": _iso(tl.start), "history_end": _iso(tl.stop), "plant_utc_offset": "+05:30",
    }  # fmt: skip
    prov = provenance_rows(sid, tl, real, real_tags, coupled, e0, e1)
    audio_hint = None
    if cause is C.AIR_PRESSURE_DROP:
        audio_hint = {"machine_type": "valve", "asset_id": "UT-AIR",
                      "abnormal_from": _iso(tl.ts(int(onset_i + 0.3 * (tl.n - onset_i))))}  # type: ignore[operator]  # fmt: skip
    elif cause is C.CONVEYOR_BEARING_DEFECT:
        audio_hint = {
            "machine_type": "slider",
            "asset_id": "ST50-CNV",
            "abnormal_from": _iso(tl.ts(audible_i)),
        }  # type: ignore[arg-type]
    meta = {
        "sim_version": SIM_VERSION,
        "set": sid[0],
        "source_kind": spec.kind,
        "primary": {
            "cause": cause.value, "asset_id": root, "onset_ts": _iso(truth.onset_ts) if truth.onset_ts else None,
            "chain": chain, "detail": detail,
            "asset_onsets": {a: _iso(tl.ts(i)) for a, i in sorted(asset_onsets.items())},
            "signature": [], "stop": {"station": stop_spec.station, "code": stop_spec.code,
                                      "trigger": [list(t) for t in stop_spec.trigger], "limit": stop_spec.limit},
            "manual": None, "audio": audio_hint,
        },
        "secondary": None,
        "real": {
            "source_id": real.source_id,
            "time_shift_days": real.timemap.days if real.timemap else None,
            "time_shift_s": real.timemap.shift_s if real.timemap else None,
            "real_tags": sorted(f"{a}.{t}" for a, t in real_tags),
            "coupled_tags": sorted(f"{a}.{t}" for a, t in coupled),
            "report": None if spec.report is None else {
                "number": spec.report.number, "page_label": spec.report.page_label,
                "start": str(spec.report.start), "end": str(spec.report.end), "report": spec.report.report},
            "normal_stop_src": str(spec.normal_stop) if spec.normal_stop else None,
            **({"history_floor_src": str(spec.floor)} if spec.floor else {}),  # R files unchanged
            "ims_window": spec.ims_window, "uci": real.segment_meta or None,
            **meta_real,
        },
    }  # fmt: skip
    return {"tl": tl, "imp": imp, "truth": truth, "stop_event": stop_event, "meta": meta, "wos": wos,
            "sim": sim, "provenance": prov, "real": real, "snaps": snaps, "e0": e0, "e1": e1}  # fmt: skip


def provenance_rows(sid: str, tl: plant.Timeline, real: Real, real_tags: set[TagKey],
                    coupled: dict[TagKey, str], e0: int, e1: int) -> pa.Table:  # fmt: skip
    ref = f"simulator {SIM_VERSION}"
    rows: list[tuple[Any, ...]] = []
    for aid, tag in sorted(plant.TAG_SPECS):
        k = (aid, tag)
        if k in real_tags:
            continue
        tr = SYNTH_TRANSFORM if k not in coupled else f"{SYNTH_TRANSFORM}; coupled: {coupled[k]}"
        rows.append((sid, aid, tag, tl.start, tl.stop, "synthetic", ref, tr))
    assert real.piece_fn is not None
    for k, t0, t1, sref, tr in real.piece_fn(e0, e1):
        rows.append((sid, k[0], k[1], _dt(t0), _dt(t1), real.source_id, sref, tr))
    rows += [
        (sid, "*", "alarms", tl.start, tl.stop + timedelta(minutes=10), "synthetic", ref,
         "derived deterministically from the telemetry (real-mapped and simulated) and events"),
        (sid, "*", "shift_notes", tl.start, tl.stop + timedelta(minutes=10), "synthetic", ref,
         "written from visible symptoms only (gemini-3.1-flash-lite or fixed templates)"),
        (sid, "*", "work_orders", tl.start - timedelta(days=30), tl.stop, "synthetic", ref,
         "historical work-order texts; MaintIE used as style exemplars only"),
    ]  # fmt: skip
    rows.sort(key=lambda r: (r[1], r[2], r[3]))
    names = ["scenario_id", "asset_id", "tag", "t0", "t1", "source_id", "source_ref", "transform"]
    cols = list(zip(*rows, strict=True))
    return pa.table({n: pa.array(list(c), TS if n in ("t0", "t1") else pa.string())
                     for n, c in zip(names, cols, strict=True)})  # fmt: skip


# =============================================================================================
# MetroPT-3 failure reports as historical work orders
# =============================================================================================
WO_TIMEMAP = TimeMap(5 * 365 + 2)  # 2020 -> 2025, inside the WO history (2024-09 .. 2026-07)


def metropt3_work_orders() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """The 4 failure reports rewritten as UT-AIR work orders (deterministic, no LLM). The source
    report text is kept verbatim (including report #2's "30Apr", probably a typo for 30 May)."""
    wos, labels = [], []
    for r in METROPT3_FAILURES:
        d = WO_TIMEMAP.to_plant(r.start)
        wid = f"WO-{d:%y}{9000 + r.number:05d}"
        dur_h = (r.end - r.start).total_seconds() / 3600
        wos.append({
            "wo_id": wid, "date": d, "asset_id": "UT-AIR",
            "symptom": f"{r.failure.lower()} - compressor {r.severity.lower()}, running loaded",
            "action": r.report if r.report else "no action recorded on report",
            "outcome": f"failure window closed after {dur_h:.1f} h",
            "technician_role": "maintenance_tech", "source_id": "metropt3",
        })  # fmt: skip
        labels.append({
            "wo_id": wid, "asset_id": "UT-AIR", "theme": "MetroPT-3 failure report " + r.page_label,
            "cause_class": C.AIR_PRESSURE_DROP.value, "kind": "source_report", "true_cause_class": None,
            "corrects_wo": None, "corrected_by": None, "text_source": "source_report",
        })  # fmt: skip
    return wos, labels


# =============================================================================================
# Vibration snapshots to GCS
# =============================================================================================
def vibration_index(
    sid: str, built: dict[str, Any], bucket: str, raw: Path
) -> list[dict[str, Any]]:
    snaps: list[Snapshot] = built["snaps"]
    tm: TimeMap = built["real"].timemap
    e0, e1 = built["e0"], built["e1"]
    out = []
    for s in snaps:
        t = tm.to_plant(s.t)
        if not (e0 <= int(t.timestamp()) < e1):
            continue
        name = f"vibration/{sid}/{t.strftime('%Y%m%dT%H%M%SZ')}.txt"
        out.append({"ts": _iso(t), "asset_id": "ST50-CNV", "gs_uri": f"gs://{bucket}/{name}",
                    "local_file": str(raw / IMS_DIR / s.name), "source_file": f"2nd_test/{s.name}",
                    "sample_rate_hz": IMS_FS_HZ, "points": IMS_POINTS, "channels": 4, "bearing_channel": 1,
                    "units": "g", "format": "tab-separated text, 4 columns (bearing 1-4)"})  # fmt: skip
    return out


def upload_vibration(sid: str, index: list[dict[str, Any]], bucket: str, scenario_dir: Path) -> int:
    from concurrent.futures import ThreadPoolExecutor

    from google.cloud import storage

    client = storage.Client()
    bkt = client.bucket(bucket)
    existing = {b.name: b.size for b in client.list_blobs(bucket, prefix=f"vibration/{sid}/")}
    jobs = []
    for v in index:
        name = v["gs_uri"].split(f"gs://{bucket}/", 1)[1]
        if existing.get(name) != Path(v["local_file"]).stat().st_size:
            jobs.append((Path(v["local_file"]), name, "text/plain"))
    jobs.append(
        (
            scenario_dir / "vibration_index.json",
            f"vibration/{sid}/vibration_index.json",
            "application/json",
        )
    )

    def one(j: tuple[Path, str, str]) -> None:
        b = bkt.blob(j[1])
        b.metadata = {"source": "IMS bearings test 2 (NASA PCoE), U.S. Government Works"}
        b.upload_from_filename(str(j[0]), content_type=j[2], timeout=600)

    with ThreadPoolExecutor(8) as ex:
        list(ex.map(one, jobs))
    return len(jobs)


# =============================================================================================
# Sanity plots
# =============================================================================================
def plot_scenario(scenario_dir: Path, out_dir: Path) -> Path:
    """Sanity plot from the *written* files: full history (left) and a zoom on the fault/stop
    (right) for every real-mapped tag (red) and every tag coupled to it (blue)."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    sid = scenario_dir.name
    truth = json.loads((scenario_dir / "truth.json").read_text())
    meta = json.loads((scenario_dir / "sim_meta.json").read_text())
    se = json.loads((scenario_dir / "stop_event.json").read_text())
    tel = pd.read_parquet(scenario_dir / "telemetry.parquet")
    real_tags = [tuple(x.split(".", 1)) for x in meta["real"]["real_tags"]]
    keys = real_tags + [tuple(x.split(".", 1)) for x in meta["real"]["coupled_tags"]]
    stop = pd.Timestamp(se["stop_ts"])
    onset = pd.Timestamp(truth["onset_ts"]) if truth["onset_ts"] else None
    z0 = (onset - pd.Timedelta(hours=1)) if onset is not None else stop - pd.Timedelta(hours=6)
    z0 = max(min(z0, stop - pd.Timedelta(minutes=40)), pd.Timestamp(se["history_start"]))
    fig, axes = plt.subplots(len(keys), 2, figsize=(15, 1.9 * len(keys) + 0.9),
                             gridspec_kw={"width_ratios": [2.2, 1]}, squeeze=False)  # fmt: skip
    for row, k in zip(axes, keys, strict=True):
        g = tel[(tel.asset_id == k[0]) & (tel.tag == k[1])].sort_values("ts")
        t = g.ts.to_numpy("datetime64[s]")
        v = g.value.to_numpy(float).copy()
        brk = np.flatnonzero(np.diff(t).astype(np.int64) > 1) + 1  # draw gaps as gaps
        t = np.insert(t, brk, t[brk - 1] + np.timedelta64(1, "s")) if len(brk) else t
        v = np.insert(v, brk, np.nan) if len(brk) else v
        spec = plant.TAG_SPECS[k]
        for ax, zoom in zip(row, (False, True), strict=True):
            m = (t >= np.datetime64(z0.tz_localize(None), "s")) if zoom else slice(None)
            ax.plot(
                t[m],
                v[m],
                lw=0.4 if not zoom else 0.6,
                color="tab:red" if k in real_tags else "tab:blue",
            )
            ax.axhspan(spec.normal_lo, spec.normal_hi, color="green", alpha=0.07)
            if onset is not None:
                ax.axvline(onset.tz_localize(None), color="k", ls="--", lw=0.8)
            ax.axvline(stop.tz_localize(None), color="purple", lw=0.8)
            ax.tick_params(labelsize=6)
        row[0].set_ylabel(f"{k[0]}\n{k[1]} [{spec.unit}]", fontsize=7)
    axes[0][0].set_title(
        f"{sid}  source={meta['real']['source_id']}  truth={truth['root_cause_class']}"
        f"{' / ' + truth['detail'] if truth['detail'] else ''}\nred = real-mapped, blue = synthetic coupled to it; "
        f"dashed = source-label onset; purple = stop ({se['stop_code']}); green = normal band", fontsize=8)  # fmt: skip
    axes[0][1].set_title(f"zoom from {z0:%m-%d %H:%M} UTC", fontsize=8)
    fig.tight_layout()
    out_dir.mkdir(parents=True, exist_ok=True)
    p = out_dir / f"{sid}.png"
    fig.savefig(p, dpi=85)
    plt.close(fig)
    return p


# =============================================================================================
# CLI
# =============================================================================================
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--out", type=Path, default=Path("data/scenarios"))
    ap.add_argument("--set", choices=sorted(SPECS_BY_SET), default="R",
                    help="R = R001-R017; C = C001-C010 confirmation set (pre-registered)")  # fmt: skip
    ap.add_argument("--ids", default="", help="comma-separated subset, e.g. R001,R015")
    ap.add_argument("--seed", type=int, default=2026)
    ap.add_argument("--raw", type=Path, default=RAW)
    ap.add_argument("--text", choices=["template", "cached", "live"], default="cached")
    ap.add_argument("--cache-dir", type=Path, default=text_artifacts.DEFAULT_CACHE_DIR)
    ap.add_argument("--bucket", default=audio_mod.DEFAULT_BUCKET)
    ap.add_argument("--plots", type=Path, default=None,
                    help="default docs/rset_inspection (R) or docs/data_inspection/confirm_set (C)")  # fmt: skip
    ap.add_argument("--no-audio", action="store_true")
    ap.add_argument("--plots-only", action="store_true", help="re-render docs/rset_inspection only")
    ap.add_argument(
        "--upload", action="store_true", help="upload audio clips + vibration snapshots to GCS"
    )
    args = ap.parse_args(argv)

    wanted = {s.strip() for s in args.ids.split(",") if s.strip()}
    specs = [s for s in SPECS_BY_SET[args.set] if not wanted or s.sid in wanted]
    if args.plots is None:
        args.plots = Path(
            "docs/rset_inspection" if args.set == "R" else "docs/data_inspection/confirm_set"
        )
    offset = SEED_OFFSET if args.set == "R" else SEED_OFFSET_C
    if args.plots_only:
        for spec in specs:
            print(plot_scenario(args.out / spec.sid, args.plots))
        return 0
    mode: TextMode = args.text
    gen = TextGen(mode=mode, cache_dir=args.cache_dir)
    t0 = time.time()
    pool = ensure_work_orders(args.out.parent, gen, args.seed)
    written = []
    for spec in specs:
        seed = args.seed * 1000 + offset + int(spec.sid[1:])
        built = build_r(spec, seed, gen, pool, args.raw, args.bucket)
        d = write_scenario(args.out, spec.sid, built)
        if spec.kind == "ims":
            idx = vibration_index(spec.sid, built, args.bucket, args.raw)
            vi = {"scenario_id": spec.sid, "snapshots": idx,
                  "source": "IMS bearings test 2 (NASA PCoE / Univ. of Cincinnati), real; mapped onto ST50-CNV"}  # fmt: skip
            (d / "vibration_index.json").write_text(json.dumps(vi, indent=1, sort_keys=True) + "\n")
            if args.upload:
                n_up = upload_vibration(spec.sid, idx, args.bucket, d)
                print(f"  {spec.sid}: uploaded {n_up} vibration objects", flush=True)
        plot_scenario(d, args.plots)
        written.append(d)
        mb = sum(f.stat().st_size for f in d.iterdir()) / 1e6
        tr = built["truth"]
        print(f"{spec.sid}  {mb:5.1f} MB  {tr.root_cause_class.value:24s} stop={_iso(tr.stop_ts)} "
              f"{built['stop_event']['stop_code']:16s} {time.time() - t0:6.1f}s", flush=True)  # fmt: skip
    if not args.no_audio:
        res = audio_mod.run(args.out, [d.name for d in written], args.raw / "mimii", args.bucket,
                            do_upload=args.upload)  # fmt: skip
        print(f"audio: {json.dumps(res)}")
    print(gen.summary())
    if gen.failures:
        print(f"text validation fallbacks: {len(gen.failures)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
