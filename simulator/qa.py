"""Simulator QA helpers: robust onset detection on binned series (tests + sanity reports).

Not the agents' change-point tool (that lives with the tools, Phase 2). This is a deliberately
simple, transparent detector used to prove the generated data has the properties the verifier
relies on: a signature appears after onset and not before, and the root asset changes first.
"""

from __future__ import annotations

import numpy as np

from simulator import plant
from simulator.plant import TagKey, Timeline


def residual(key: TagKey, x: np.ndarray, tl: Timeline) -> np.ndarray:
    """Remove known operating-point changes (product-model setpoints) before detection."""
    sp = [plant.PRODUCT_SETPOINTS[m].get(key) for m in plant.PRODUCT_MODELS]
    if all(v is not None for v in sp):
        return x - np.asarray(sp, dtype=float)[tl.model_idx]
    return x.astype(float)


def detect_params(key: TagKey, direction: int) -> dict[str, float]:
    """Bin width / threshold suited to each kind of signal.

    * load/unload compressor current and the header sawtooth: 10-min bins (duty, not cycles);
    * reject rate (rolling % of 100 parts, binomial): higher threshold;
    * spread (direction 0): 15-min bins so each bin holds ~18 cycles.
    """
    if key[0] == "UT-AIR":
        return {"width": 600, "k": 4.0, "persist": 2}
    if direction == 0:
        return {"width": 900, "k": 4.0, "persist": 2}
    if key[1] == "reject_rate_pct":
        return {"width": 300, "k": 6.0, "persist": 2}
    return {"width": 60, "k": 4.0, "persist": 3}


def detect(key: TagKey, x: np.ndarray, tl: Timeline, direction: int, ref: tuple[int, int],
           search: tuple[int, int]) -> int | None:  # fmt: skip
    """``detect_onset`` on the setpoint-corrected series with the preset for ``key``."""
    p = detect_params(key, direction)
    return detect_onset(residual(key, x, tl), tl, direction, ref, search, width=int(p["width"]),
                        k=p["k"], persist=int(p["persist"]), sd_floor=plant.TAG_SPECS[key].resolution)  # fmt: skip


def _bins(x: np.ndarray, width: int, stat: str) -> np.ndarray:
    m = len(x) // width
    b = x[: m * width].reshape(m, width)
    if stat == "mean":
        return np.nanmean(b, axis=1)
    return np.nanstd(b - np.nanmean(b, axis=1, keepdims=True), axis=1)


def detect_onset(
    x: np.ndarray,
    tl: Timeline,
    direction: int,
    ref: tuple[int, int],
    search: tuple[int, int],
    *,
    width: int = 60,
    k: float = 4.0,
    persist: int = 3,
    sd_floor: float = 0.0,
) -> int | None:
    """First sample index in ``search`` where the binned series departs from the reference window
    by > k robust sigmas in ``direction`` (+1 up, -1 down, 0 = spread up) for ``persist``
    consecutive bins. Bins touching a changeover (+10 min) are ignored."""
    stat = "std" if direction == 0 else "mean"
    b = _bins(x.astype(float), width, stat)
    co = tl.changeover.copy()
    for i in tl.shift_starts:
        co[i : i + plant.CHANGEOVER_S + 600] = True
    bad = _bins(co.astype(float), width, "mean") > 0
    r0, r1 = max(ref[0] // width, 0), max(ref[1] // width, 1)
    refb = b[r0:r1][~bad[r0:r1]]
    if direction == 0:
        refb = np.log(refb + 1e-9)
    mu = float(np.median(refb))
    sd = float(1.4826 * np.median(np.abs(refb - mu))) or float(np.std(refb)) or 1e-9
    if direction != 0:
        sd = max(sd, sd_floor)
    vals = np.log(b + 1e-9) if direction == 0 else b
    score = (vals - mu) / sd * (1 if direction == 0 else direction)
    s0, s1 = max(search[0] // width, 0), min(search[1] // width, len(b))
    run = 0
    for i in range(s0, s1):
        if bad[i]:
            continue
        run = run + 1 if score[i] > k else 0
        if run >= persist:
            return (i - persist + 1) * width
    return None
