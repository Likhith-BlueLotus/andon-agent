"""IsolationForest anomaly score per asset type, trained on synthetic normal plant data.

    uv run python -m analytics.anomaly train        # writes data/models/iforest_<type>.joblib

Features (per 10-min bin, per tag of the asset type): ``level`` = (median - nominal) / normal
span (the loaded-time fraction for the load/unload compressor current) and ``spread`` =
log1p(std / sensor noise). Training data: ``TRAIN_SEEDS`` x ``TRAIN_DAYS`` of the simulator with
no fault and no imperfection (``simulator.plant``; nothing from any scenario, no ground truth).
Weld cells share one model: ST20 has no coolant tag, so its coolant features are imputed with
the training medians (as is any bin a data gap leaves incomplete), which makes them neutral.

Score: ``raw = -score_samples`` is mapped with a logistic centred on the training 99th
percentile (training median -> ~0.05, p99 -> 0.5), so 0-1 reads "how unusual vs normal
operation". A window's score is the maximum of a 3-bin (30 min) rolling median, so a single
odd bin cannot dominate. ``top_tags`` = tags with the largest robust z (vs training) in the
peak bins.

Known limit: the real-mapped MetroPT-3 compressor is start/stop with a much lower duty than the
simulated load/unload one, so UT-AIR on R001-R008 reads as unusual even when the source is
normal. The tool reports the score; it does not decide.
"""

from __future__ import annotations

import argparse
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd

from analytics.series import DUTY_TAGS, Series, bin_series, iso, rnd, sig
from simulator import plant

MODEL_VERSION = "iforest-1"
BIN_S = 600
TRAIN_SEEDS = (101, 202, 303, 404)
TRAIN_DAYS = 3
TRAIN_STOP = datetime(2026, 7, 20, 6, 0, tzinfo=UTC)  # before every scenario's history
DEFAULT_DIR = Path(__file__).resolve().parents[1] / "data" / "models"

_LOCK = threading.Lock()
_CACHE: dict[tuple[str, str], dict[str, Any]] = {}


def asset_types() -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for a in plant.ASSETS:
        out.setdefault(a.asset_type, []).append(a.asset_id)
    return out


def type_tags(asset_type: str) -> list[str]:
    tags: list[str] = []
    for aid in asset_types()[asset_type]:
        for t in plant.asset(aid).tags:
            if t.tag not in tags:
                tags.append(t.tag)
    return tags


def feature_names(asset_type: str) -> list[str]:
    return [f"{t}:{k}" for t in type_tags(asset_type) for k in ("level", "spread")]


def bin_features(
    asset_id: str, series: dict[str, Series], t0: int, t1: int
) -> tuple[np.ndarray, np.ndarray]:
    """(bin starts, feature matrix with NaN where a tag is absent or its bin < 50 % covered)."""
    atype = plant.asset(asset_id).asset_type
    tags = type_tags(atype)
    nb = max((t1 - t0) // BIN_S, 0)
    starts = t0 + BIN_S * np.arange(nb, dtype=np.int64)
    x = np.full((nb, 2 * len(tags)), np.nan)
    for j, tag in enumerate(tags):
        s = series.get(tag)
        if s is None or (asset_id, tag) not in plant.TAG_SPECS:
            continue
        spec = plant.tag_spec(asset_id, tag)
        span = float(spec.normal_hi - spec.normal_lo)
        if (asset_id, tag) in DUTY_TAGS:
            ind = Series(s.t, (s.v > DUTY_TAGS[(asset_id, tag)]).astype(float))
            _, lvl, _ = bin_series(ind, t0, t1, BIN_S, "mean")
        else:
            _, med, _ = bin_series(s, t0, t1, BIN_S, "median")
            lvl = (med - spec.nominal) / span
        _, m1, _ = bin_series(s, t0, t1, BIN_S, "mean")
        _, m2, _ = bin_series(Series(s.t, s.v * s.v), t0, t1, BIN_S, "mean")
        std = np.sqrt(np.maximum(m2 - m1 * m1, 0.0))
        spread = np.log1p(std / max(spec.noise_std, spec.resolution))
        x[:, 2 * j] = lvl
        x[:, 2 * j + 1] = spread
    return starts, x


# --- training --------------------------------------------------------------------------------
def _normal_series(seed: int) -> tuple[dict[str, dict[str, Series]], int, int]:
    n = TRAIN_DAYS * 86400
    tl = plant.make_timeline(TRAIN_STOP, n, plant.rng_for(seed, "iforest", "timeline"))
    sim = plant.simulate(tl, plant.Modifiers(tl.n), seed)
    t = tl.epoch_s()
    per: dict[str, dict[str, Series]] = {}
    for (aid, tag), v in sim.values.items():
        per.setdefault(aid, {})[tag] = Series(t, v.astype(np.float64))
    return per, int(t[0]), int(t[-1]) + 1


def train(model_dir: Path = DEFAULT_DIR, seeds: tuple[int, ...] = TRAIN_SEEDS) -> list[Path]:
    from sklearn.ensemble import IsolationForest

    rows: dict[str, list[np.ndarray]] = {}
    for seed in seeds:
        per, t0, t1 = _normal_series(seed)
        for aid, ser in per.items():
            atype = plant.asset(aid).asset_type
            rows.setdefault(atype, []).append(bin_features(aid, ser, t0, t1)[1])
    model_dir.mkdir(parents=True, exist_ok=True)
    out = []
    for atype, mats in sorted(rows.items()):
        x = np.vstack(mats)
        med = np.nanmedian(x, axis=0)
        x = np.where(np.isnan(x), med, x)
        mad = 1.4826 * np.median(np.abs(x - med), axis=0)
        mad = np.maximum(mad, 1e-3)
        model = IsolationForest(n_estimators=200, random_state=0, n_jobs=1).fit(x)
        raw = -model.score_samples(x)
        p50, p99 = (float(v) for v in np.percentile(raw, [50, 99]))
        path = model_dir / f"iforest_{atype}.joblib"
        joblib.dump(
            {
                "version": MODEL_VERSION, "asset_type": atype, "model": model,
                "features": feature_names(atype), "median": med, "mad": mad,
                "p50": p50, "p99": p99, "n_train_bins": len(x),
                "trained_on": f"simulator.plant normal, seeds {list(seeds)}, {TRAIN_DAYS} d each",
            },
            path,
        )  # fmt: skip
        out.append(path)
    return out


def load(asset_type: str, model_dir: Path = DEFAULT_DIR) -> dict[str, Any]:
    """Lazy-load (training once, deterministically, if the file is missing)."""
    key = (str(model_dir), asset_type)
    with _LOCK:
        if key not in _CACHE:
            path = model_dir / f"iforest_{asset_type}.joblib"
            if not path.exists():
                train(model_dir)
            m = joblib.load(path)
            if m.get("version") != MODEL_VERSION:
                train(model_dir)
                m = joblib.load(path)
            _CACHE[key] = m
        return _CACHE[key]


# --- scoring ---------------------------------------------------------------------------------
def score(
    asset_id: str, series: dict[str, Series], t0: int, t1: int, model_dir: Path = DEFAULT_DIR
) -> dict:
    atype = plant.asset(asset_id).asset_type
    m = load(atype, model_dir)
    starts, x = bin_features(asset_id, series, t0, t1)
    out: dict[str, Any] = {"model": f"{MODEL_VERSION}:{atype}", "bin_s": BIN_S}
    tags = type_tags(atype)
    own = [plant.tag_spec(asset_id, t).tag for t in tags if (asset_id, t) in plant.TAG_SPECS]
    own_cols = [k for k, t in enumerate(tags) if t in own]
    cols = [c for k in own_cols for c in (2 * k, 2 * k + 1)]
    observed = ~np.isnan(x[:, cols]).any(axis=1) if len(x) else np.zeros(0, bool)
    out["n_bins"] = len(x)
    out["n_bins_complete"] = int(observed.sum())
    if not observed.any():
        out.update({"status": "insufficient_data", "score": None, "top_tags": []})
        return out
    xi = np.where(np.isnan(x), m["median"], x)
    raw = -m["model"].score_samples(xi)
    scale = max((m["p99"] - m["p50"]) / 3.0, 1e-6)
    s01 = 1.0 / (1.0 + np.exp(-(raw - m["p99"]) / scale))
    s01[~observed] = np.nan  # bins that are mostly a data gap are not scored
    roll = pd.Series(s01).rolling(3, center=True, min_periods=1).median().to_numpy()
    if np.all(np.isnan(roll)):
        roll = s01
    k = int(np.nanargmax(roll))
    lo, hi = max(k - 1, 0), min(k + 2, len(x))
    z = np.abs(xi[lo:hi] - m["median"]) / m["mad"]
    zmax = np.nanmax(z, axis=0)
    per_tag = []
    for j in own_cols:
        tag = tags[j]
        zl, zs = float(zmax[2 * j]), float(zmax[2 * j + 1])
        lvl = float(np.nanmean(xi[lo:hi, 2 * j]) - m["median"][2 * j])
        feat = "level" if zl >= zs else "spread"
        direction = ("high" if lvl > 0 else "low") if feat == "level" else "noisy"
        per_tag.append((max(zl, zs), tag, feat, direction))
    per_tag.sort(key=lambda r: (-r[0], r[1]))
    out.update(
        {
            "status": "ok",
            "score": rnd(float(roll[k]), 3),
            "peak_bin_start": iso(int(starts[k])),
            "fraction_bins_above_0_5": rnd(float(np.nanmean(roll > 0.5)), 3),
            "top_tags": [
                {"tag": t, "robust_z": sig(z_, 3), "feature": f, "direction": d}
                for z_, t, f, d in per_tag[:3]
            ],
        }
    )
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("cmd", choices=["train"])
    ap.add_argument("--model-dir", type=Path, default=DEFAULT_DIR)
    a = ap.parse_args(argv)
    for p in train(a.model_dir):
        m = joblib.load(p)
        print(f"{p}: {m['n_train_bins']} bins, p50 {m['p50']:.3f}, p99 {m['p99']:.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
