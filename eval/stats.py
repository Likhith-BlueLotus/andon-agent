"""Small-n statistics for the eval (EVAL_PLAN §4). Pure functions, no I/O, no numpy.

* :func:`wilson` — 95% Wilson score interval for a proportion.
* :func:`mcnemar_exact` — exact two-sided McNemar test from the discordant counts.
* :func:`brier`, :func:`reliability_bins` — calibration of ``confidence`` against correctness.
* :func:`median`, :func:`percentile`, :func:`spread` — summaries for times, costs and repeats.
"""

from __future__ import annotations

import math
from collections.abc import Hashable, Mapping, Sequence
from dataclasses import dataclass

Z95 = 1.959963984540054  # two-sided 95% normal quantile


@dataclass(frozen=True)
class Interval:
    """A proportion k/n with its 95% Wilson interval. ``p``/``lo``/``hi`` are None when n = 0."""

    k: int
    n: int
    p: float | None
    lo: float | None
    hi: float | None

    def to_dict(self) -> dict:
        return {"k": self.k, "n": self.n, "value": _r(self.p), "lo": _r(self.lo), "hi": _r(self.hi)}

    def __str__(self) -> str:
        if self.p is None:
            return "n/a"
        return f"{self.p:.2f} [{self.lo:.2f}, {self.hi:.2f}]"


def _r(x: float | None, nd: int = 4) -> float | None:
    return None if x is None else round(x, nd)


def wilson(k: int, n: int, z: float = Z95) -> Interval:
    """Wilson score interval for k successes in n trials."""
    if n < 0 or k < 0 or k > n:
        raise ValueError(f"need 0 <= k <= n, got k={k}, n={n}")
    if n == 0:
        return Interval(k, n, None, None, None)
    p = k / n
    z2 = z * z
    denom = 1 + z2 / n
    centre = (p + z2 / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z2 / (4 * n * n)) / denom
    return Interval(k, n, p, max(0.0, centre - half), min(1.0, centre + half))


def binom_cdf_half(k: int, n: int) -> float:
    """P[X <= k] for X ~ Binomial(n, 1/2), exact (integer arithmetic)."""
    if n == 0:
        return 1.0
    k = min(k, n)
    return sum(math.comb(n, i) for i in range(k + 1)) / 2**n


@dataclass(frozen=True)
class McNemar:
    a_only: int  # first system right, second wrong  (discordant count "b")
    b_only: int  # second system right, first wrong  (discordant count "c")
    both_right: int
    both_wrong: int
    p: float  # exact two-sided

    @property
    def n(self) -> int:
        return self.a_only + self.b_only + self.both_right + self.both_wrong

    def to_dict(self) -> dict:
        return {
            "a_only": self.a_only,
            "b_only": self.b_only,
            "both_right": self.both_right,
            "both_wrong": self.both_wrong,
            "n": self.n,
            "p": round(self.p, 6),
            "test": "exact McNemar (two-sided binomial on discordant pairs)",
        }


def mcnemar_exact(a_only: int, b_only: int, both_right: int = 0, both_wrong: int = 0) -> McNemar:
    """Exact McNemar: under H0 the discordant pairs split 50/50. p = min(1, 2 * P[X <= min(b, c)])."""
    if min(a_only, b_only, both_right, both_wrong) < 0:
        raise ValueError("counts must be non-negative")
    d = a_only + b_only
    p = 1.0 if d == 0 else min(1.0, 2 * binom_cdf_half(min(a_only, b_only), d))
    return McNemar(a_only, b_only, both_right, both_wrong, p)


def paired(a: Mapping[Hashable, bool], b: Mapping[Hashable, bool]) -> McNemar:
    """McNemar over the keys present in both mappings (e.g. per-scenario top-1 correctness)."""
    keys = a.keys() & b.keys()
    a_only = sum(1 for k in keys if a[k] and not b[k])
    b_only = sum(1 for k in keys if b[k] and not a[k])
    both = sum(1 for k in keys if a[k] and b[k])
    return mcnemar_exact(a_only, b_only, both, len(keys) - a_only - b_only - both)


# --- calibration -------------------------------------------------------------------------------
def brier(confidence: Sequence[float], correct: Sequence[bool]) -> float | None:
    """Mean squared error between stated confidence and the 0/1 outcome (lower is better)."""
    if len(confidence) != len(correct):
        raise ValueError("confidence and correct must have the same length")
    if not confidence:
        return None
    return sum((c - float(o)) ** 2 for c, o in zip(confidence, correct, strict=True)) / len(
        confidence
    )


def reliability_bins(
    confidence: Sequence[float], correct: Sequence[bool], n_bins: int = 5
) -> list[dict]:
    """Equal-width bins on [0, 1]; the last bin includes 1.0. Empty bins are kept (n = 0)."""
    if len(confidence) != len(correct):
        raise ValueError("confidence and correct must have the same length")
    bins: list[list[tuple[float, bool]]] = [[] for _ in range(n_bins)]
    for c, o in zip(confidence, correct, strict=True):
        if not 0.0 <= c <= 1.0:
            raise ValueError(f"confidence out of range: {c}")
        bins[min(int(c * n_bins), n_bins - 1)].append((c, bool(o)))
    out = []
    for i, items in enumerate(bins):
        n = len(items)
        out.append(
            {
                "bin": i,
                "lo": round(i / n_bins, 4),
                "hi": round((i + 1) / n_bins, 4),
                "n": n,
                "mean_confidence": _r(sum(c for c, _ in items) / n) if n else None,
                "accuracy": _r(sum(o for _, o in items) / n) if n else None,
            }
        )
    return out


def expected_calibration_error(bins: Sequence[Mapping]) -> float | None:
    total = sum(b["n"] for b in bins)
    if not total:
        return None
    return sum(b["n"] * abs(b["mean_confidence"] - b["accuracy"]) for b in bins if b["n"]) / total


# --- descriptive -------------------------------------------------------------------------------
def percentile(xs: Sequence[float], q: float) -> float | None:
    """Linear-interpolation percentile (numpy's default), q in [0, 100]."""
    if not xs:
        return None
    if not 0 <= q <= 100:
        raise ValueError("q must be in [0, 100]")
    s = sorted(xs)
    pos = (len(s) - 1) * q / 100
    lo, hi = math.floor(pos), math.ceil(pos)
    return s[lo] + (s[hi] - s[lo]) * (pos - lo)


def median(xs: Sequence[float]) -> float | None:
    return percentile(xs, 50)


def spread(xs: Sequence[float]) -> dict:
    """``{n, min, max, range, mean}`` of e.g. top-1 accuracy over repeats."""
    if not xs:
        return {"n": 0, "min": None, "max": None, "range": None, "mean": None}
    return {
        "n": len(xs),
        "min": min(xs),
        "max": max(xs),
        "range": max(xs) - min(xs),
        "mean": sum(xs) / len(xs),
    }
