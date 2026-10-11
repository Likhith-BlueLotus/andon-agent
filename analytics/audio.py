"""Classical audio baseline for ``listen``: MFCC features and a distance to normal reference clips.

Implemented with numpy/scipy only (no librosa): librosa pulls numba + llvmlite (~150 MB) into
the API image for ~40 lines of DSP. Textbook MFCC recipe (Davis & Mermelstein 1980; HTK mel):

    mono float -> 1024-pt Hann frames, hop 512 (64 ms / 32 ms at 16 kHz) -> power spectrum
    -> 64 triangular mel filters (50 Hz - 8 kHz) -> 10*log10 power -> DCT-II (ortho) -> c0..c19

Distance (:func:`compare`): fit one Gaussian to *all frames* of the reference clips (same asset,
same machine) and report the root-mean per-frame Mahalanobis distance of the queried clip's frames,
per sqrt(dimension). A clip that sounds like the references scores about 1.0 ("as typical as a
reference frame"); larger is further away. ``c0`` (log energy) is kept: comparing within one
machine is exactly where level is meaningful, and Mahalanobis is unsigned, so the sign flip of
the abnormal level change between MIMII machine ids (docs/data_inspection.md §4) does not hurt.

Spread: each reference clip's leave-one-out distance to the others; ``mfcc_z`` = (distance -
mean LOO) / max(std LOO, 0.05, 10% of mean LOO). The floor stops 2-3 near-identical references
from inflating z. With fewer than 2 reference clips there is no spread and ``mfcc_z`` is None.

Method choice (2026-10-11, dev scenarios S001-S050 + R001-R017 only, never S051-S060): of
{mean-vector, per-frame, mean+std, symmetric KL} x {c1..c19, c0..c19, log-mel}, per-frame on
c0..c19 separated best among MFCC variants (ROC AUC 0.79 overall; pump 0.97, fan 0.88, slider
0.62, valve 0.63). Valve and slider anomalies (timing of open/close, intermittent knocks) are
weakly visible to a time-averaged spectral baseline: the number is a check, not a verdict.

Everything is deterministic: fixed parameters, no randomness.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from functools import lru_cache

import numpy as np
from scipy.fft import dct
from scipy.io import wavfile
from scipy.signal import get_window

SAMPLE_RATE_HZ = 16_000
N_FFT = 1024
HOP = 512
N_MELS = 64
N_MFCC = 20
FMIN_HZ = 50.0
FMAX_HZ = 8_000.0
COV_RIDGE = 1e-3  # relative ridge on the reference covariance (keeps it invertible)
Z_STD_FLOOR = 0.05  # floor on the LOO spread so 2-3 near-identical references cannot explode z
METHOD = "mfcc-c0..c19-frame-mahalanobis-v1"


@dataclass(frozen=True)
class ClipFeatures:
    frames: np.ndarray  # (n_frames, N_MFCC) MFCC c0..c19
    rms: float  # full-scale RMS, for information only

    @property
    def n_frames(self) -> int:
        return len(self.frames)


def read_wav(data: bytes) -> np.ndarray:
    """16-bit (or float) wav bytes -> mono float64 in [-1, 1]. Multi-channel is averaged."""
    sr, x = wavfile.read(io.BytesIO(data))
    if sr != SAMPLE_RATE_HZ:
        raise ValueError(f"expected {SAMPLE_RATE_HZ} Hz audio, got {sr} Hz")
    if np.issubdtype(x.dtype, np.integer):
        x = x.astype(np.float64) / float(np.iinfo(x.dtype).max + 1)
    else:
        x = x.astype(np.float64)
    return x.mean(axis=1) if x.ndim == 2 else x


def _hz_to_mel(f: np.ndarray | float) -> np.ndarray:
    return 2595.0 * np.log10(1.0 + np.asarray(f, dtype=np.float64) / 700.0)


def _mel_to_hz(m: np.ndarray) -> np.ndarray:
    return 700.0 * (10.0 ** (m / 2595.0) - 1.0)


@lru_cache(maxsize=4)
def mel_filterbank(
    sr: int = SAMPLE_RATE_HZ, n_fft: int = N_FFT, n_mels: int = N_MELS
) -> np.ndarray:
    """(n_mels, n_fft//2+1) triangular filters, area-normalised (Slaney-style)."""
    freqs = np.fft.rfftfreq(n_fft, 1.0 / sr)
    pts = _mel_to_hz(np.linspace(_hz_to_mel(FMIN_HZ), _hz_to_mel(min(FMAX_HZ, sr / 2)), n_mels + 2))
    fb = np.zeros((n_mels, len(freqs)))
    for i in range(n_mels):
        lo, c, hi = pts[i], pts[i + 1], pts[i + 2]
        up = (freqs - lo) / (c - lo)
        down = (hi - freqs) / (hi - c)
        fb[i] = np.maximum(0.0, np.minimum(up, down)) * (2.0 / (hi - lo))
    fb.setflags(write=False)
    return fb


def mfcc(y: np.ndarray, sr: int = SAMPLE_RATE_HZ) -> np.ndarray:
    """(n_frames, N_MFCC) MFCC matrix of a mono signal."""
    if sr != SAMPLE_RATE_HZ:
        raise ValueError(f"expected {SAMPLE_RATE_HZ} Hz audio, got {sr} Hz")
    y = np.asarray(y, dtype=np.float64)
    if len(y) < N_FFT:
        raise ValueError(f"clip too short for MFCC: {len(y)} samples < {N_FFT}")
    n_frames = 1 + (len(y) - N_FFT) // HOP
    idx = np.arange(N_FFT)[None, :] + HOP * np.arange(n_frames)[:, None]
    frames = y[idx] * get_window("hann", N_FFT, fftbins=True)[None, :]
    power = np.abs(np.fft.rfft(frames, axis=1)) ** 2
    mel = power @ mel_filterbank(sr).T
    log_mel = 10.0 * np.log10(np.maximum(mel, 1e-12))
    return dct(log_mel, type=2, axis=1, norm="ortho")[:, :N_MFCC]


def features(y: np.ndarray, sr: int = SAMPLE_RATE_HZ) -> ClipFeatures:
    m = mfcc(y, sr)
    m.setflags(write=False)
    return ClipFeatures(frames=m, rms=float(np.sqrt(np.mean(np.square(y)))))


def features_from_wav(data: bytes) -> ClipFeatures:
    return features(read_wav(data))


def distance(query: ClipFeatures, refs: list[ClipFeatures]) -> float:
    """Root-mean per-frame Mahalanobis distance of ``query`` under the Gaussian of all reference
    frames, per sqrt(dimension) (about 1.0 for a clip like the references)."""
    if not refs:
        raise ValueError("need at least one reference clip")
    x = np.vstack([r.frames for r in refs])
    mu = x.mean(axis=0)
    d = len(mu)
    cov = np.cov(x, rowvar=False)
    cov = cov + COV_RIDGE * (np.trace(cov) / d) * np.eye(d)
    diff = query.frames - mu
    m2 = np.einsum("ij,ij->i", diff, np.linalg.solve(cov, diff.T).T)
    return float(np.sqrt(max(float(np.mean(m2)), 0.0) / d))


def compare(query: ClipFeatures, refs: list[ClipFeatures]) -> dict:
    """``{mfcc_distance, mfcc_z, reference_loo_mean, reference_loo_std, n_reference_clips,
    method}`` (floats unrounded; the caller rounds)."""
    dist = distance(query, refs)
    out: dict = {
        "mfcc_distance": dist,
        "mfcc_z": None,
        "reference_loo_mean": None,
        "reference_loo_std": None,
        "n_reference_clips": len(refs),
        "method": METHOD,
    }
    if len(refs) >= 2:
        loo = np.array([distance(r, refs[:i] + refs[i + 1 :]) for i, r in enumerate(refs)])
        mean, std = float(loo.mean()), float(loo.std())
        out.update(
            reference_loo_mean=mean,
            reference_loo_std=std,
            mfcc_z=(dist - mean) / max(std, Z_STD_FLOOR, 0.1 * mean),
        )
    return out
