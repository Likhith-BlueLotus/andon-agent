"""1 Hz series helpers: per-tag signal definitions, robust binning, data quality, rounding.

A telemetry series is two aligned arrays: ``t`` (int64 epoch seconds, strictly increasing) and
``v`` (float64). Rows that are missing in the store are simply absent; nothing is interpolated.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

import numpy as np
import pandas as pd

from simulator import plant

# --- data quality thresholds -----------------------------------------------------------------
GAP_MIN_S = 10  # a run of >= 10 missing seconds is a gap (single dropped samples are not)
MAX_GAPS_LISTED = 10
MAX_STUCK_LISTED = 5
STUCK_MIN_S = {"continuous": 300, "per_cycle": 1200}  # per-cycle tags hold through changeovers
# Rolling % of the last 100 parts with ~1 % rejects: the value legitimately holds for an hour+.
STUCK_MIN_S_OVERRIDE = {"reject_rate_pct": 4 * 3600}

NICE_WIDTHS_S = (60, 120, 300, 600, 900, 1200, 1800, 3600, 7200)  # all divide one day
MAX_BINS = 1500

# Load/unload (or start/stop) compressor: the motor current is a square wave, so its mean says
# little; the share of time spent loaded is the physical quantity (a leak raises it). 55 A sits
# between unloaded (~35-46 A) and loaded (>= 63 A) for both the simulated and the real-mapped
# compressor (docs/data_inspection.md section 1).
DUTY_TAGS: dict[tuple[str, str], float] = {("UT-AIR", "compressor_current_a"): 55.0}

# Normal patterns that are not faults, and the smallest change worth reporting on such tags:
# * tip resistance: the tip-dress sawtooth (~0.008 mOhm every ~3 h) is normal wear and dressing;
# * reject rate: % of the last 100 parts, so one reject entering/leaving moves it by 1 point.
MIN_EFFECT: dict[str, float] = {"tip_resistance_mohm": 0.012, "reject_rate_pct": 2.0}
# Base bin width per tag where a known cycle must be averaged out (chiller: 15 min cycle).
BASE_WIDTH_S: dict[str, int] = {"supply_temp_c": 900, "reject_rate_pct": 600}


@dataclass(frozen=True)
class Series:
    t: np.ndarray  # int64 epoch seconds, increasing
    v: np.ndarray  # float64

    def __len__(self) -> int:
        return len(self.t)

    def window(self, a: int, b: int) -> Series:
        i, j = np.searchsorted(self.t, [a, b])
        return Series(self.t[i:j], self.v[i:j])


def series_from_frame(df: pd.DataFrame, tag: str) -> Series:
    """Extract one tag from a ``ts, tag, value`` frame (the store's telemetry shape)."""
    if df.empty:
        return Series(np.empty(0, np.int64), np.empty(0, np.float64))
    sub = df[df["tag"].astype(str) == tag]
    ts = pd.to_datetime(sub["ts"], utc=True)
    t = (ts.astype("int64") // _ns_per(ts)).to_numpy(np.int64)
    v = sub["value"].to_numpy(np.float64)
    order = np.argsort(t, kind="stable")
    t, v = t[order], v[order]
    keep = np.concatenate([[True], np.diff(t) > 0]) if len(t) else np.empty(0, bool)
    ok = keep & np.isfinite(v)
    return Series(t[ok], v[ok])


def _ns_per(ts: pd.Series) -> int:
    unit = getattr(ts.dtype, "unit", "ns")
    return {"s": 1, "ms": 1_000, "us": 1_000_000, "ns": 1_000_000_000}[unit]


# --- signal definitions ----------------------------------------------------------------------
SignalKind = Literal["duty_fraction", "mean", "median"]


@dataclass(frozen=True)
class SignalDef:
    kind: SignalKind
    base_width_s: int
    unit: str
    scale: float  # physical scale for effect sizes (normal span, or 1.0 for fractions)
    resolution: float
    threshold: float | None = None  # duty_fraction: loaded if value > threshold
    min_effect: float | None = None  # smallest change worth reporting (None: rel_min * scale)

    def label(self, width_s: int) -> str:
        w = f"{width_s // 60}min" if width_s % 60 == 0 else f"{width_s}s"
        return f"{self.kind}_{w}"


def signal_def(asset_id: str, tag: str) -> SignalDef:
    """How a tag is aggregated before change-point detection (robust aggregates per bin)."""
    spec = plant.tag_spec(asset_id, tag)
    span = float(spec.normal_hi - spec.normal_lo)
    floor = MIN_EFFECT.get(tag)
    if (asset_id, tag) in DUTY_TAGS:
        return SignalDef("duty_fraction", 600, "fraction of time loaded", 1.0, 1.0 / 600,
                         DUTY_TAGS[(asset_id, tag)])  # fmt: skip
    if asset_id == "UT-AIR" and tag == "header_pressure_bar":
        # load/unload sawtooth: average over whole cycles (~2-10 min), never sample it
        return SignalDef("mean", 600, spec.unit, span, spec.resolution)
    if tag == "reject_rate_pct":
        return SignalDef("mean", BASE_WIDTH_S[tag], spec.unit, span, spec.resolution,
                         min_effect=floor)  # fmt: skip
    if spec.kind == "per_cycle":
        return SignalDef("median", 300, spec.unit, span, spec.resolution, min_effect=floor)
    return SignalDef("median", BASE_WIDTH_S.get(tag, 60), spec.unit, span, spec.resolution,
                     min_effect=floor)  # fmt: skip


def pick_width(base_s: int, span_s: int, max_bins: int = MAX_BINS) -> int:
    need = max(base_s, math.ceil(span_s / max_bins))
    for w in NICE_WIDTHS_S:
        if w >= need:
            return w
    return NICE_WIDTHS_S[-1]


def transform_values(sd: SignalDef, v: np.ndarray) -> np.ndarray:
    """Per-sample transform before aggregation (duty: loaded indicator)."""
    if sd.kind == "duty_fraction":
        assert sd.threshold is not None
        return (v > sd.threshold).astype(np.float64)
    return v


def bin_series(
    s: Series, t0: int, t1: int, width: int, how: Literal["mean", "median"], min_cover: float = 0.5
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Fixed bins ``[t0 + k*w, t0 + (k+1)*w)``. Returns (bin start times, values, coverage).
    Bins with less than ``min_cover`` of their seconds present are NaN."""
    nb = max(int((t1 - t0) // width), 0)
    starts = t0 + width * np.arange(nb, dtype=np.int64)
    vals = np.full(nb, np.nan)
    cover = np.zeros(nb)
    if nb == 0 or len(s) == 0:
        return starts, vals, cover
    idx = (s.t - t0) // width
    ok = (idx >= 0) & (idx < nb)
    idx, v = idx[ok], s.v[ok]
    cnt = np.bincount(idx, minlength=nb).astype(float)
    cover = cnt / width
    if how == "mean":
        tot = np.bincount(idx, weights=v, minlength=nb)
        with np.errstate(invalid="ignore", divide="ignore"):
            vals = tot / cnt
    else:
        med = pd.Series(v).groupby(idx).median()
        vals[med.index.to_numpy()] = med.to_numpy()
    vals[cover < min_cover] = np.nan
    return starts, vals, cover


def changeover_intervals(t0: int, t1: int, tail_s: int = 600) -> list[tuple[int, int]]:
    """Planned changeovers (plant schedule: 15 min at every shift start, local UTC+05:30) plus
    ``tail_s`` of restart transient, as ``(start, end)`` epoch seconds overlapping [t0, t1)."""
    day = 86400
    off = plant.PLANT_UTC_OFFSET_S
    first_day = (t0 - day + off) // day * day - off
    out = []
    for d in range(first_day, t1 + day, day):
        for h in plant.SHIFT_START_HOURS:
            a = d + h * 3600
            b = a + plant.CHANGEOVER_S + tail_s
            if b > t0 and a < t1:
                out.append((a, b))
    return out


def changeover_mask(starts: np.ndarray, width: int, tail_s: int = 600) -> np.ndarray:
    """True for bins overlapping a planned changeover (+ restart tail): excluded from detection."""
    mask = np.zeros(len(starts), bool)
    if len(starts) == 0:
        return mask
    for a, b in changeover_intervals(int(starts[0]), int(starts[-1]) + width, tail_s):
        mask |= (starts < b) & (starts + width > a)
    return mask


# --- data quality ----------------------------------------------------------------------------
def stuck_min_s(asset_id: str, tag: str) -> int:
    if tag in STUCK_MIN_S_OVERRIDE:
        return STUCK_MIN_S_OVERRIDE[tag]
    return STUCK_MIN_S[plant.tag_spec(asset_id, tag).kind]


def stuck_floor(asset_id: str, tag: str) -> float | None:
    """Flat runs below this value are a machine state, not a stuck sensor (compressor motor off:
    a start/stop compressor reads ~0.5 A for hours while parked)."""
    thr = DUTY_TAGS.get((asset_id, tag))
    return 0.2 * thr if thr is not None else None


def data_quality(
    s: Series, t0: int, t1: int, stuck_min: int, stuck_floor: float | None = None
) -> dict:
    """``{n, missing_pct, gaps, stuck_periods}`` for one tag in ``[t0, t1)`` (1 Hz expected).
    A stuck period is a value unchanged for >= ``stuck_min`` seconds (above ``stuck_floor``)."""
    expected = max(t1 - t0, 1)
    n = len(s)
    gaps: list[tuple[int, int]] = []  # (start, duration_s)
    if n == 0:
        gaps.append((t0, t1 - t0))
    else:
        if s.t[0] - t0 >= GAP_MIN_S:
            gaps.append((t0, int(s.t[0] - t0)))
        d = np.diff(s.t) - 1
        for i in np.flatnonzero(d >= GAP_MIN_S):
            gaps.append((int(s.t[i]) + 1, int(d[i])))
        if t1 - 1 - s.t[-1] >= GAP_MIN_S:
            gaps.append((int(s.t[-1]) + 1, int(t1 - 1 - s.t[-1])))
    gap_total = int(sum(g[1] for g in gaps))
    listed = sorted(sorted(gaps, key=lambda g: (-g[1], g[0]))[:MAX_GAPS_LISTED])

    stuck: list[tuple[int, int, float]] = []
    if n >= 2:
        change = np.flatnonzero(np.diff(s.v) != 0)
        run_start = np.concatenate([[0], change + 1])
        run_end = np.concatenate([change, [n - 1]])
        dur = s.t[run_end] - s.t[run_start] + 1
        for k in np.flatnonzero(dur >= stuck_min):
            if stuck_floor is not None and s.v[run_start[k]] < stuck_floor:
                continue
            stuck.append((int(s.t[run_start[k]]), int(dur[k]), float(s.v[run_start[k]])))
    stuck_listed = sorted(sorted(stuck, key=lambda x: (-x[1], x[0]))[:MAX_STUCK_LISTED])
    return {
        "n": int(n),
        "missing_pct": rnd(max(0.0, 100.0 * (1 - n / expected)), 2),
        "gaps": [{"start": iso(a), "duration_s": d} for a, d in listed],
        "n_gaps": len(gaps),
        "gap_total_s": gap_total,
        "stuck_periods": [
            {"start": iso(a), "duration_s": d, "value": sig(v)} for a, d, v in stuck_listed
        ],
        "n_stuck_periods": len(stuck),
    }


def merge_quality(per_tag: dict[str, dict]) -> dict:
    """Asset-level view over several tags (gaps de-duplicated, stuck periods tagged)."""
    n = sum(q["n"] for q in per_tag.values())
    miss = [q["missing_pct"] for q in per_tag.values()]
    gaps = sorted({(g["start"], g["duration_s"]) for q in per_tag.values() for g in q["gaps"]})
    gaps = sorted(sorted(gaps, key=lambda g: (-g[1], g[0]))[:MAX_GAPS_LISTED])
    stuck = sorted(
        ({"tag": tag, **sp} for tag, q in per_tag.items() for sp in q["stuck_periods"]),
        key=lambda x: (x["start"], x["tag"]),
    )
    return {
        "n": n,
        "missing_pct": rnd(float(np.mean(miss)) if miss else 100.0, 2),
        "gaps": [{"start": a, "duration_s": d} for a, d in gaps],
        "n_gaps": max((q["n_gaps"] for q in per_tag.values()), default=0),
        "gap_total_s": max((q["gap_total_s"] for q in per_tag.values()), default=0),
        "stuck_periods": stuck,
        "n_stuck_periods": sum(q["n_stuck_periods"] for q in per_tag.values()),
    }


# --- formatting ------------------------------------------------------------------------------
def iso(epoch_s: float) -> str:
    return datetime.fromtimestamp(int(epoch_s), tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def rnd(x: float, nd: int) -> float:
    return float(round(float(x), nd)) + 0.0  # + 0.0 turns -0.0 into 0.0


def sig(x: float, digits: int = 5) -> float:
    """Round to ``digits`` significant digits (JSON-safe, deterministic)."""
    x = float(x)
    if not math.isfinite(x):
        raise ValueError("non-finite value in a summary")
    if x == 0:
        return 0.0
    return float(f"{x:.{digits}g}") + 0.0
