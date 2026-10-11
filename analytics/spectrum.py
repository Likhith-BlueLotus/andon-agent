"""Welch spectra with top-k peaks; envelope spectrum for high-rate bearing vibration.

* 1 Hz plant series (synthetic): Welch PSD on the contiguous runs of the window (gaps of <= 5 s
  bridged linearly, longer gaps split the series), runs averaged by segment count. Nyquist is
  0.5 Hz, so only slow mechanics show (conveyor pulley rotation ~0.255 Hz, sealer stroke 0.15 Hz).
* Raw 20 kHz accelerometer snapshots (IMS test 2, real): Welch PSD of each 1 s snapshot plus the
  **envelope spectrum** (band-pass 2-8 kHz, Hilbert magnitude, Welch). Bearing defects modulate
  the structural resonances, so their characteristic frequency (outer race ~230 Hz here) shows in
  the envelope, not in the plain spectrum (docs/data_inspection.md section 3).

``amplitude`` is the amplitude of a sinusoid that would produce the peak's PSD
(``sqrt(2 * PSD * ENBW * df)``, Hann ENBW = 1.5 bins), in the signal's own unit.
"""

from __future__ import annotations

import io

import numpy as np
import pandas as pd
from scipy import signal as sps

from analytics.series import Series, sig

HANN_ENBW = 1.5
MAX_BRIDGE_S = 5
TOP_K = 5


def _peaks(f: np.ndarray, p: np.ndarray, fmin: float, fmax: float, df: float) -> list[dict]:
    sel = (f >= fmin) & (f <= fmax)
    f, p = f[sel], p[sel]
    if len(p) < 3:
        return []
    idx, _ = sps.find_peaks(p)
    if len(idx) == 0:
        idx = np.array([int(np.argmax(p))])
    top = idx[np.argsort(-p[idx], kind="stable")][:TOP_K]
    return [
        {"freq_hz": sig(f[i], 4), "amplitude": sig(np.sqrt(2.0 * p[i] * HANN_ENBW * df), 4)}
        for i in top
    ]


def _runs(s: Series) -> list[np.ndarray]:
    """Contiguous 1 Hz runs; gaps of <= MAX_BRIDGE_S seconds are linearly bridged."""
    if len(s) < 2:
        return []
    out = []
    breaks = np.flatnonzero(np.diff(s.t) > MAX_BRIDGE_S + 1)
    for a, b in zip(np.r_[0, breaks + 1], np.r_[breaks + 1, len(s)], strict=True):
        t, v = s.t[a:b], s.v[a:b]
        if len(t) < 2:
            continue
        grid = np.arange(t[0], t[-1] + 1)
        out.append(np.interp(grid, t, v))
    return out


def spectrum_1hz(s: Series, nperseg_max: int = 1024) -> dict:
    runs = _runs(s)
    longest = max((len(r) for r in runs), default=0)
    if longest < 64:
        return {"status": "insufficient_data", "peaks": [], "fs_hz": 1.0}
    nper = int(min(nperseg_max, 2 ** int(np.floor(np.log2(longest)))))
    acc, wsum, n_used = None, 0.0, 0
    f = None
    for r in runs:
        if len(r) < nper:
            continue
        f, p = sps.welch(r, fs=1.0, window="hann", nperseg=nper, detrend="linear")
        nseg = 1 + (len(r) - nper) // (nper // 2)
        acc = p * nseg if acc is None else acc + p * nseg
        wsum += nseg
        n_used += len(r)
    assert acc is not None and f is not None
    psd = acc / wsum
    df = 1.0 / nper
    return {
        "status": "ok",
        "fs_hz": 1.0,
        "resolution_hz": sig(df, 4),
        "nperseg": nper,
        "n_segments": int(wsum),
        "samples_used": int(n_used),
        "peaks": _peaks(f, psd, 2 * df, 0.5, df),
    }


def parse_ims_snapshot(raw: bytes, channel: int = 0) -> np.ndarray:
    """IMS snapshot file: tab-separated text, 4 columns (bearings 1-4), 20,480 rows, in g."""
    df = pd.read_csv(io.BytesIO(raw), sep="\t", header=None, usecols=[channel], dtype=float)
    return df.to_numpy()[:, 0]


def spectrum_highrate(
    snaps: list[np.ndarray], fs: float, band: tuple[float, float] = (2000.0, 8000.0)
) -> dict:
    """Mean Welch PSD and mean envelope spectrum over several raw snapshots."""
    nper, nper_env = 4096, 8192
    sos = sps.butter(4, band, btype="bandpass", fs=fs, output="sos")
    p_acc = e_acc = None
    f = fe = None
    for x in snaps:
        x = x - np.mean(x)
        f, p = sps.welch(x, fs=fs, window="hann", nperseg=nper)
        env = np.abs(sps.hilbert(sps.sosfiltfilt(sos, x)))
        fe, pe = sps.welch(env - np.mean(env), fs=fs, window="hann", nperseg=nper_env)
        p_acc = p if p_acc is None else p_acc + p
        e_acc = pe if e_acc is None else e_acc + pe
    assert p_acc is not None and e_acc is not None and f is not None and fe is not None
    k = len(snaps)
    df, dfe = fs / nper, fs / nper_env
    rms = float(np.mean([np.sqrt(np.mean((x - x.mean()) ** 2)) for x in snaps]))
    return {
        "status": "ok",
        "fs_hz": fs,
        "resolution_hz": sig(df, 4),
        "peaks": _peaks(f, p_acc / k, 2 * df, fs / 2, df),
        "envelope_band_hz": [band[0], band[1]],
        "envelope_resolution_hz": sig(dfe, 4),
        "envelope_peaks": _peaks(fe, e_acc / k, 10.0, 1000.0, dfe),
        "rms": sig(rms, 4),
    }
