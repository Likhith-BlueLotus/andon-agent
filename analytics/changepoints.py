"""Change points on robust per-bin aggregates: PELT (l2) + minimum effect size + CUSUM onset.

Pipeline for one tag in ``[t0, t1)``:

1. **Aggregate** each bin with the tag's signal definition (``series.signal_def``): loaded-time
   fraction for the load/unload compressor current (``duty_fraction``), whole-cycle mean for the
   header-pressure sawtooth and the reject rate, median elsewhere (robust to single-sample
   spikes). Bin width adapts to the window (<= 1500 bins, never below the signal's base width).
2. **Exclude** bins with < 50 % data (gaps) and planned changeover windows (plant schedule).
   A change found right after a changeover is flagged ``at_changeover`` (recipe/product change
   or restart), never hidden.
3. **Remove the daily pattern** (ambient temperature, day/night demand): a time-of-day median
   profile estimated on up to 7 days of history ending at ``t1``, after removing each day's own
   median level, so a fault that lasts hours or a few days is not absorbed into the profile.
4. **PELT** with an l2 cost on the robust-standardised series (``pelt_l2``: the same optimum as
   ``ruptures.Pelt(model="l2", jump=1)``, but O(1) segment costs from cumulative sums; ruptures'
   own implementation needs ~1 s for 1,000 points and ~23 s for 4,000).
5. **Minimum effect size**: a breakpoint survives only if its adjacent segment means differ by
   ``>= min_effect`` (physical: ``rel_min`` x normal span, or a per-tag floor) *and* by
   ``>= t_min`` standard errors; the weakest is merged first. Same-direction steps separated by
   plateaus shorter than ``ramp_join_s`` are reported as one ramp (``shape="ramp"``, ``end_ts``);
   a change that returns to its starting level within ``excursion_max_s`` is one transient
   (``shape="excursion"``, with ``peak_mean`` and ``end_ts``; ``delta`` is peak minus before).
6. **Onset**: each change's timestamp is refined on a 1-min series with a one-sided CUSUM
   against the local pre-change baseline (``argmin`` of the drift-corrected cumulative sum):
   the time the signal *started* to depart, which is what causal ordering needs. For a step the
   drift allowance is at least a quarter of the step (Page's reference value), so a short blip
   before a large step is not taken for its onset.

Constants were calibrated on synthetic normal data with ``scripts/calibrate_change_points.py``
(clean windows must return <= 1 change point; see ``tests/test_tools.py``).
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass
from datetime import UTC, datetime

import numpy as np
import pandas as pd

from analytics.series import (
    Series,
    SignalDef,
    bin_series,
    changeover_intervals,
    changeover_mask,
    iso,
    pick_width,
    sig,
    transform_values,
)
from simulator import plant

DAY = 86400
PROFILE_DAYS = 7
PROFILE_MIN_DAYS = 3


@dataclass(frozen=True)
class CPConfig:
    pen_beta: float = 3.0  # penalty = pen_beta * log(n) on the unit-variance series
    min_size: int = 3  # bins per segment
    t_min: float = 5.0  # minimum effect: two-sample t of adjacent segments (bin noise) ...
    rel_min: float = 0.08  # ... and at least rel_min * normal span (or the signal's own floor)
    ramp_join_s: int = 6 * 3600  # same-direction steps closer than this form one ramp
    excursion_max_s: int = 3 * 3600  # up-then-back (or down-then-back) within this: one excursion
    max_report: int = 8
    kappa: float = 0.5  # CUSUM drift allowance (in baseline sigmas)
    refine_back_s: int = 3 * 3600  # steps
    refine_back_ramp_s: int = 12 * 3600  # ramps start long before their first coarse step
    fine_width_s: int = 60


CONFIG = CPConfig()


# --- PELT ------------------------------------------------------------------------------------
def pelt_l2(y: np.ndarray, pen: float, min_size: int = 3) -> list[int]:
    """Optimal partition of ``y`` under the l2 (mean-shift) cost with a linear penalty.

    Returns the start index of every segment after the first (``ruptures`` breakpoints without
    the final ``n``). Killick et al. (2012) pruning with K = 0, which is exact for l2."""
    y = np.asarray(y, dtype=np.float64)
    n = len(y)
    if n < 2 * min_size:
        return []
    c1 = np.concatenate([[0.0], np.cumsum(y)])
    c2 = np.concatenate([[0.0], np.cumsum(y * y)])
    f = np.full(n + 1, np.inf)
    f[0] = -pen
    last = np.zeros(n + 1, dtype=np.int64)
    cand = np.array([0], dtype=np.int64)
    for t in range(min_size, n + 1):
        s_new = t - min_size
        if s_new >= min_size:
            cand = np.append(cand, s_new)
        length = t - cand
        seg = c1[t] - c1[cand]
        cost = (c2[t] - c2[cand]) - seg * seg / length
        tot = f[cand] + cost + pen
        k = int(np.argmin(tot))
        f[t] = tot[k]
        last[t] = cand[k]
        cand = cand[f[cand] + cost <= f[t]]
    bks: list[int] = []
    t = n
    while t > 0:
        s = int(last[t])
        if s > 0:
            bks.append(s)
        t = s
    return sorted(bks)


def robust_sigma(y: np.ndarray, floor: float) -> float:
    """Noise level from first differences (insensitive to steps and slow trends)."""
    if len(y) < 3:
        return floor
    d = np.diff(y)
    mad = float(np.median(np.abs(d - np.median(d))))
    return max(1.4826 * mad / np.sqrt(2.0), floor)


def merge_small(
    y: np.ndarray, bks: list[int], delta: float, sigma: float, t_min: float
) -> list[int]:
    """Drop the weakest breakpoint while any fails the minimum effect: adjacent segment means
    must differ by >= ``delta`` *and* by >= ``t_min`` standard errors (bin noise ``sigma``)."""
    bks = list(bks)
    c1 = np.concatenate([[0.0], np.cumsum(y)])
    while bks:
        edges = np.array([0, *bks, len(y)])
        lens = np.diff(edges).astype(float)
        means = (c1[edges[1:]] - c1[edges[:-1]]) / lens
        d = np.abs(np.diff(means))
        se = sigma * np.sqrt(1 / lens[:-1] + 1 / lens[1:])
        score = np.minimum(d / delta, d / se / t_min)
        k = int(np.argmin(score))
        if score[k] >= 1.0:
            break
        bks.pop(k)
    return bks


# --- daily pattern ---------------------------------------------------------------------------
def daily_profile(
    hist: Series, sd: SignalDef, t0: int, t1: int, width: int
) -> tuple[dict[int, float], int]:
    """Time-of-day profile ``{slot: offset}`` from the 7 days ending at ``t1`` (bins share the
    query's phase). Each local day's median is removed first; a slot needs >= 3 days."""
    how = "median" if sd.kind == "median" else "mean"
    p0 = t0 - ((t0 - (t1 - PROFILE_DAYS * DAY)) // width) * width
    if p0 > t0:
        p0 = t0
    xs = Series(hist.t, transform_values(sd, hist.v))
    st, v, _ = bin_series(xs, p0, t1, width, how)
    ok = np.isfinite(v) & ~changeover_mask(st, width)
    st, v = st[ok], v[ok]
    if len(v) == 0:
        return {}, 0
    off = plant.PLANT_UTC_OFFSET_S
    day = (st + off) // DAY
    slot = ((st + off) % DAY) // width
    df = pd.DataFrame({"day": day, "slot": slot, "v": v})
    per_day = df.groupby("day")["v"].agg(["median", "count"])
    full = per_day.index[per_day["count"] >= 0.5 * (DAY // width)]  # >= half a day of bins
    df = df[df["day"].isin(full)]
    n_days = len(full)
    if n_days < PROFILE_MIN_DAYS:
        return {}, n_days
    df = df.assign(r=df["v"] - df["day"].map(per_day["median"]))
    g = df.groupby("slot")["r"]
    prof = g.median()[g.count() >= PROFILE_MIN_DAYS]
    if prof.empty:
        return {}, n_days
    prof = prof - float(np.median(prof.to_numpy()))
    return {int(k): float(x) for k, x in prof.items()}, n_days


# --- main entry ------------------------------------------------------------------------------
def detect(
    s: Series,
    t0: int,
    t1: int,
    sd: SignalDef,
    history: Series | None = None,
    cfg: CPConfig = CONFIG,
) -> dict:
    """Change points of one tag in ``[t0, t1)``. ``history`` (default ``s``) should cover up to 7
    days ending at ``t1`` and is used only for the daily profile. Returns a JSON-safe summary
    without data quality (the caller adds it)."""
    span = t1 - t0
    width = pick_width(sd.base_width_s, span)
    how = "median" if sd.kind == "median" else "mean"
    xs = Series(s.t, transform_values(sd, s.v))
    starts, vals, _ = bin_series(xs, t0, t1, width, how)
    co = changeover_mask(starts, width)
    gap_bin = ~np.isfinite(vals)
    valid = ~gap_bin & ~co
    y, tt = vals[valid], starts[valid]
    delta = sd.min_effect if sd.min_effect is not None else cfg.rel_min * sd.scale
    out: dict = {
        "signal": sd.label(width),
        "signal_unit": sd.unit,
        "bin_s": width,
        "method": "pelt_l2+min_effect+cusum_onset",
        "min_effect": sig(delta),
        "changeover_excluded": True,
        "daily_profile_days": 0,
        "n_bins": len(y),
        "status": "ok",
        "change_points": [],
    }
    if len(y) < 4 * cfg.min_size:
        out["status"] = "insufficient_data"
        out["short_shift"] = {"status": "insufficient_data", "method": "tail_scan_z"}
        return out

    hs = history if history is not None else s
    prof, n_days = daily_profile(hs, sd, t0, t1, width)
    out["daily_profile_days"] = n_days if prof else 0
    off = plant.PLANT_UTC_OFFSET_S
    seas = np.array([prof.get(int(k), 0.0) for k in ((tt + off) % DAY) // width])
    ya = y - seas

    floor = max(sd.resolution * 0.5, 1e-6)
    sigma = robust_sigma(ya, floor)
    pen = cfg.pen_beta * np.log(len(ya))
    z = (ya - np.median(ya)) / sigma
    bks = merge_small(ya, pelt_l2(z, pen, cfg.min_size), delta, sigma, cfg.t_min)

    edges = [0, *bks, len(y)]
    means = [float(np.mean(ya[a:b])) for a, b in itertools.pairwise(edges)]
    raw_means = [float(np.mean(y[a:b])) for a, b in itertools.pairwise(edges)]
    groups: list[list[int]] = []  # indices into bks; same-direction runs become ramps
    for k in range(len(bks)):
        sign = np.sign(means[k + 1] - means[k])
        if groups:
            pk = groups[-1][-1]
            psign = np.sign(means[pk + 1] - means[pk])
            plateau_s = int(tt[bks[k]] - tt[bks[pk]])
            if (
                sign == psign
                and plateau_s <= cfg.ramp_join_s
                and not _between(gap_bin, starts, tt, bks[pk], bks[k])
            ):
                groups[-1].append(k)
                continue
        groups.append([k])

    fine = _fine_series(xs, sd, t0, t1, cfg.fine_width_s)
    if prof:  # same daily pattern removed from the 1-min series
        fs = np.array([prof.get(int(k), 0.0) for k in ((fine.t + off) % DAY) // width])
        fine = Series(fine.t, fine.v - fs)
    cps: list[dict] = []
    last_onset = t0
    for g in groups:
        k0, k1 = g[0], g[-1]
        i0 = bks[k0]
        before, after = raw_means[k0], raw_means[k1 + 1]
        direction = 1 if means[k1 + 1] > means[k0] else -1
        prev_t = max(int(tt[bks[k0 - 1]]) if k0 else t0, last_onset)
        across = _between(gap_bin, starts, tt, i0 - 1, i0)
        coarse = int(tt[i0])
        step = abs(means[k0 + 1] - means[k0]) if len(g) == 1 else 0.0
        back = cfg.refine_back_s if len(g) == 1 else cfg.refine_back_ramp_s
        onset = (
            coarse
            if across
            else _refine(fine, coarse, prev_t, width, direction, step / 4, back, cfg)
        )
        at_co = False
        if not across and _between(co, starts, tt, i0 - 1, i0):
            # a change that is already there when the line restarts began at the shift start
            last_co = [iv for iv in changeover_intervals(prev_t, coarse + 1) if iv[1] <= coarse]
            if last_co and last_co[-1][0] <= onset <= last_co[-1][1] + cfg.fine_width_s:
                onset = max(last_co[-1][0], prev_t)
                at_co = True
        last_onset = onset + cfg.fine_width_s
        denom = abs(before)
        # Report the direction of the reported (raw-mean) delta so the summary is self-consistent;
        # the robust direction only steers onset refinement and breaks a raw-mean tie.
        raw_delta = after - before
        reported_up = raw_delta > 0 if raw_delta != 0 else direction > 0
        cp = {
            "ts": iso(onset),
            "before_mean": sig(before),
            "after_mean": sig(after),
            "delta": sig(after - before),
            "magnitude_pct": sig(100.0 * (after - before) / denom, 4)
            if denom > 0.01 * sd.scale
            else None,
            "direction": "up" if reported_up else "down",
            "shape": "ramp" if len(g) > 1 else "step",
            "across_gap": bool(across),
            "at_changeover": at_co,
        }
        if len(g) > 1:
            cp["end_ts"] = iso(int(tt[bks[k1]]))
        cps.append(cp)
    cps = _excursions(cps, delta, cfg)
    if len(cps) > cfg.max_report:
        keep = sorted(range(len(cps)), key=lambda i: (-abs(cps[i]["delta"]), cps[i]["ts"]))
        cps = [cps[i] for i in sorted(keep[: cfg.max_report])]
        out["truncated"] = True
    out["change_points"] = cps
    out["short_shift"] = short_shift(hs, t0, t1, sd, SHORT)
    return out


@dataclass(frozen=True)
class ShortConfig:
    """End-anchored short-shift scan (ADR-033). A line stop is investigated with windows that end
    at the stop, and the fault that stopped the line is active at the stop. A 10-20 min step of
    0.3-6 % is many bin-sigmas but far below PELT's physical ``min_effect`` (8 % of the normal
    span, sized for multi-day windows with daily patterns), so ``merge_small`` removes it. This
    scan asks one narrower question: do the last ``L`` minutes of the window (``L`` in
    [``min_len_s``, ``scan_s``]) sit at a different level from the preceding baseline?"""

    scan_s: int = 3600  # longest tail tested (longer faults are PELT's job)
    min_len_s: int = 300  # shortest tail tested (and >= ``min_bins`` bins)
    min_bins: int = 3
    base_s: int = 4 * 3600  # baseline length before the scanned tail
    min_base_bins: int = 60  # and at least 2 x the tail length
    z_min: float = 8.0  # |z| against the baseline's own variability of L-bin means
    persist: float = 0.75  # share of tail bins on the shifted side of the baseline level
    rel_floor: float = 0.01  # ... and |delta| >= 1 % of the normal span and >= 2 x resolution
    max_ar: float = 0.95


SHORT = ShortConfig()


def short_shift(hist: Series, t0: int, t1: int, sd: SignalDef, cfg: ShortConfig = SHORT) -> dict:
    """End-anchored likelihood-ratio scan for a sustained level shift in the last <= ``scan_s``.

    ``hist`` is the raw 1 Hz history ending at ``t1`` (up to 7 days; the baseline may start
    before ``t0``, the tested tail always lies inside ``[t0, t1)``). Bins of ``max(60 s, signal
    base width)``; changeover bins and gaps removed; only data after the last planned changeover
    (no recipe change between baseline and tail). The daily pattern is removed with a 5-min
    profile estimated on whole local days before the tested tail (a fault is never absorbed into
    its own baseline), interpolated to the bins. For each tail length ``L`` the null spread of an
    L-bin mean comes from the baseline itself (max of an AR(1) long-run-variance model and the
    empirical spread of rolling L-means), inflated if the tail is noisier than the baseline (a
    noise increase is not a level shift). Decision: max ``|z|`` >= ``z_min``. Onset: the
    likelihood-ratio estimate ``argmax_L L (mean_L - mu)^2`` in the decided direction; the shift
    must persist over that tail and clear a physical floor."""
    width = max(60, sd.base_width_s)
    how = "median" if sd.kind == "median" else "mean"
    floor = sd.min_effect if sd.min_effect is not None else 0.0
    floor = max(floor, cfg.rel_floor * sd.scale, 2 * sd.resolution)
    out: dict = {"status": "none", "method": "tail_scan_z", "bin_s": width,
                 "z_min": cfg.z_min, "min_effect": sig(floor)}  # fmt: skip
    if width > 60:
        # Per-cycle / duty / chiller tags (5-15 min bins): a 10-20 min fault is 1-4 bins, and
        # on the S-set their short-term steps are mostly real slowdowns propagated through the
        # line's buffers from another station (ADR-033), so the scan would mislead causal order.
        out["status"] = "not_applicable"
        out["reason"] = "short scan runs on 1-min signals only"
        return out
    if len(hist) and int(hist.t[-1]) < t1 - 1:  # window runs past the history: end at its end
        t1 = int(hist.t[-1]) + 1
    l_min = max(cfg.min_bins, -(-cfg.min_len_s // width))
    l_max = max(min(cfg.scan_s, t1 - t0), 0) // width  # tested tail always lies in [t0, t1)
    if l_max < l_min:
        out["status"] = "insufficient_data"
        return out
    a = t1 - (cfg.base_s + l_max * width) // width * width
    co = [iv for iv in changeover_intervals(a, t1) if iv[1] <= t1]
    if co:  # only after the last planned changeover (+ restart tail) that ends before t1
        a = max(a, t1 - (t1 - co[-1][1]) // width * width)
    xs = Series(hist.t, transform_values(sd, hist.v))
    starts, vals, _ = bin_series(xs.window(a, t1), a, t1, width, how)
    ok = np.isfinite(vals) & ~changeover_mask(starts, width)
    tt, raw = starts[ok], vals[ok]
    # Profile from whole local days before the tested tail: every slot then rests on the same
    # days (a profile ending mid-day mixes 7-day and 6-day medians, and on a tag whose setpoint
    # follows the product model that alone puts a step at the cut).
    pw = max(300, width)
    off = plant.PLANT_UTC_OFFSET_S
    midnight = (t1 - l_max * width + off) // DAY * DAY - off
    prof, _ = daily_profile(hist.window(midnight - PROFILE_DAYS * DAY, midnight), sd,
                            midnight - pw, midnight, pw)  # fmt: skip
    y = raw - _interp_profile(prof, pw, tt + width // 2)
    n = len(y)
    min_base = cfg.min_base_bins
    if n < min_base + l_min:
        out["status"] = "insufficient_data"
        return out
    if t1 - (int(tt[-1]) + width) >= l_min * width:  # the window's end is a changeover or a gap
        out["status"] = "insufficient_data"
        out["reason"] = "no usable data at the end of the window (changeover or gap)"
        return out
    res_floor = max(sd.resolution * 0.5, 1e-9)
    nb = cfg.base_s // width
    best_z, best_abs, mu_by_l = 0.0, -1.0, {}
    for L in range(l_min, l_max + 1):
        base = y[: n - L][-nb:]
        if len(base) < max(min_base, 2 * L) or tt[n - L] < t0:
            break
        mu = float(np.median(base))
        sb = max(1.4826 * float(np.median(np.abs(base - mu))), res_floor)
        r = _ar1(base, cfg.max_ar)
        s_model = sb * np.sqrt((1 + r) / (1 - r) / L)
        rm = np.convolve(base, np.ones(L) / L, mode="valid")
        s_emp = 1.4826 * float(np.median(np.abs(rm - np.median(rm)))) if len(rm) >= 5 else 0.0
        tail = y[n - L :]
        st = 1.4826 * float(np.median(np.abs(tail - np.median(tail))))
        s_L = max(s_model, s_emp, res_floor / np.sqrt(L)) * max(1.0, st / sb)
        z = (float(np.mean(tail)) - mu) / s_L
        mu_by_l[L] = (mu, float(np.mean(tail)), len(base))
        if abs(z) > best_abs:
            best_abs, best_z = abs(z), z
    if not mu_by_l:
        out["status"] = "insufficient_data"
        return out
    out["max_abs_z"] = sig(best_abs, 3)
    if best_abs < cfg.z_min:
        return out
    sgn = 1.0 if best_z > 0 else -1.0
    L = max(mu_by_l, key=lambda k: (k * max(sgn * (mu_by_l[k][1] - mu_by_l[k][0]), 0.0) ** 2, -k))
    mu, m_tail, nbase = mu_by_l[L]
    d_adj = m_tail - mu
    tail = y[n - L :]
    if sgn * d_adj <= 0 or np.mean(sgn * (tail - mu) > 0) < cfg.persist or abs(d_adj) < floor:
        return out
    before = float(np.median(raw[: n - L][-nb:]))
    out.update(
        {
            "status": "found",
            "ts": iso(int(tt[n - L])),
            "end_ts": iso(int(tt[-1]) + width),
            "duration_s": int(tt[-1] + width - tt[n - L]),
            "before_mean": sig(before),
            "after_mean": sig(before + d_adj),
            "delta": sig(d_adj),
            "magnitude_pct": sig(100.0 * d_adj / abs(before), 4)
            if abs(before) > 0.01 * sd.scale
            else None,
            "direction": "up" if d_adj > 0 else "down",
            "z": sig(best_z, 3),
            "baseline": {
                "t0": iso(int(tt[: n - L][-nbase:][0])),
                "t1": iso(int(tt[n - L])),
                "n_bins": nbase,
            },
        }
    )
    return out


def _interp_profile(prof: dict[int, float], pw: int, t: np.ndarray) -> np.ndarray:
    """Daily profile (slots of ``pw`` s, local time) linearly interpolated at times ``t``."""
    if not prof:
        return np.zeros(len(t))
    k = np.array(sorted(prof), dtype=np.float64)
    v = np.array([prof[int(i)] for i in k])
    x = k * pw + pw / 2
    xp = np.concatenate([x - DAY, x, x + DAY])  # circular
    vp = np.concatenate([v, v, v])
    tl = ((t + plant.PLANT_UTC_OFFSET_S) % DAY).astype(np.float64)
    return np.interp(tl, xp, vp)


def _ar1(y: np.ndarray, cap: float) -> float:
    """Lag-1 autocorrelation of the baseline (clipped to [0, cap]): long-run variance factor."""
    if len(y) < 10:
        return 0.0
    d = y - np.median(y)
    den = float(np.dot(d, d))
    if den <= 0:
        return 0.0
    return float(min(max(np.dot(d[1:], d[:-1]) / den, 0.0), cap))


def _excursions(cps: list[dict], delta: float, cfg: CPConfig) -> list[dict]:
    """A change followed, within ``excursion_max_s``, by one in the opposite direction that comes
    back to within ``delta`` of the starting level is one transient (``shape="excursion"``)."""
    out: list[dict] = []
    i = 0
    while i < len(cps):
        a = cps[i]
        b = cps[i + 1] if i + 1 < len(cps) else None
        if (
            b is not None
            and a["direction"] != b["direction"]
            and not b["across_gap"]
            and _epoch(b["ts"]) - _epoch(a.get("end_ts", a["ts"])) <= cfg.excursion_max_s
            and abs(b["after_mean"] - a["before_mean"]) < delta
        ):
            ex = dict(a)
            ex["shape"] = "excursion"
            ex["peak_mean"] = a["after_mean"]
            ex["after_mean"] = b["after_mean"]
            ex["end_ts"] = b["ts"]
            ex["delta"] = sig(a["after_mean"] - a["before_mean"])
            out.append(ex)
            i += 2
            continue
        out.append(a)
        i += 1
    return out


def _epoch(ts: str) -> int:
    return int(datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC).timestamp())


def _between(mask: np.ndarray, starts: np.ndarray, tt: np.ndarray, i: int, j: int) -> bool:
    """Is any ``mask`` bin strictly between valid bins ``i`` and ``j`` (indices into ``tt``)?"""
    if i < 0 or j >= len(tt):
        return False
    a, b = np.searchsorted(starts, [tt[i], tt[j]])
    return bool(mask[a + 1 : b].any())


def _fine_series(xs: Series, sd: SignalDef, t0: int, t1: int, w: int) -> Series:
    """1-min aggregate for onset refinement, changeover (+ restart tail) samples removed."""
    how = "median" if sd.kind == "median" else "mean"
    st, v, _ = bin_series(xs, t0, t1, w, how)
    if sd.kind == "duty_fraction":  # one minute holds < 1 load/unload cycle: smooth to ~10 min
        v = pd.Series(v).rolling(11, center=True, min_periods=6).mean().to_numpy()
    ok = np.isfinite(v) & ~changeover_mask(st, w)
    return Series(st[ok] + w // 2, v[ok])


def _refine(
    fine: Series, coarse: int, prev_t: int, width: int, direction: int, k_abs: float,
    back_s: int, cfg: CPConfig,
) -> int:  # fmt: skip
    """One-sided CUSUM onset: the last minimum of the drift-corrected cumulative departure from
    the local baseline, searched between the previous change and one bin after ``coarse``."""
    ra = max(prev_t, coarse - back_s)
    rb = coarse + width
    reg = fine.window(ra, rb + 1)
    base = reg.v[reg.t < coarse - width]
    if len(base) < 10:
        return coarse
    mu = float(np.median(base))
    s0 = 1.4826 * float(np.median(np.abs(base - mu)))
    c = np.cumsum(direction * (reg.v - mu) - max(cfg.kappa * s0, k_abs, 1e-9))
    k = int(np.argmin(c))
    if k + 1 >= len(reg.t):
        return coarse
    return int(min(max(reg.t[k + 1] - cfg.fine_width_s // 2, ra), rb))
