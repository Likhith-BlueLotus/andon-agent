"""Chart data for the evidence drawer: a downsampled, read-only view of one asset's telemetry.

Plain REST (not part of the SSE contract). Reads through the same ``TelemetryStore`` the agent
tools use and labels provenance with the tools' own helper, so real-signal segments are marked
identically. Never touches the Gemini budget.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import numpy as np
import pandas as pd

from agents import tools as T
from simulator import plant

MAX_TAGS = 8
MIN_POINTS, MAX_POINTS = 10, 1000
DEFAULT_WINDOW_S = 2 * 3600


class ViewError(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def _iso(e: float) -> str:
    return datetime.fromtimestamp(e, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse(name: str, v: str) -> int:
    try:
        return T._parse_time(name, v)
    except T.ToolArgError as exc:
        raise ViewError(400, "bad_time", exc.message) from None


def parse_tags(asset_id: str, raw: str) -> tuple[plant.AssetSpec, list[str]]:
    if asset_id not in plant.ASSET_BY_ID:
        raise ViewError(404, "unknown_asset", f"unknown asset_id {asset_id!r}")
    spec = plant.asset(asset_id)
    tags = list(dict.fromkeys(t.strip() for t in raw.split(",") if t.strip()))
    if not tags:
        raise ViewError(400, "bad_tags", "tags must list at least one tag")
    if len(tags) > MAX_TAGS:
        raise ViewError(400, "too_many_tags", f"at most {MAX_TAGS} tags")
    valid = {t.tag for t in spec.tags}
    bad = [t for t in tags if t not in valid]
    if bad:
        raise ViewError(400, "unknown_tag", f"{asset_id} has no tag(s) {bad}")
    return spec, tags


def resolve_window(stop_ts: Any, t0: str | None, t1: str | None) -> tuple[int, int]:
    ts = pd.Timestamp(stop_ts)
    stop = int((ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")).timestamp())
    b = _parse("t1", t1) if t1 else stop
    a = _parse("t0", t0) if t0 else b - DEFAULT_WINDOW_S
    if b <= a:
        raise ViewError(400, "bad_window", "t1 must be after t0")
    if b - a > T.MAX_WINDOW_S:
        raise ViewError(400, "window_too_long", "window is longer than 7 days")
    return a, b


def downsample(ts: np.ndarray, vals: np.ndarray, a: int, b: int, cap: int) -> list[list]:
    """``[iso, value|None]`` points, at most ``cap``. Raw points when they fit; else bucket means
    over ``cap`` equal buckets, where a bucket with samples but no finite value, or with no
    samples at all, is a null (a visible gap, never an interpolated line)."""

    def val(x: float) -> float | None:
        return float(x) if np.isfinite(x) else None

    if len(ts) <= cap:
        return [[_iso(t), val(v)] for t, v in zip(ts, vals, strict=True)]
    width = (b - a) / cap
    idx = np.clip(((ts - a) / width).astype(np.int64), 0, cap - 1)
    out: list[list] = []
    for k in range(cap):
        m = idx == k
        if not m.any():
            out.append([_iso(a + k * width), None])
            continue
        v = vals[m]
        v = v[np.isfinite(v)]
        out.append([_iso(a + k * width), float(v.mean()) if len(v) else None])
    return out


def build_view(
    store: Any, scenario_id: str, asset_id: str, tags: list[str], a: int, b: int, cap: int
) -> dict:
    spec = plant.asset(asset_id)
    units = {t.tag: t.unit or None for t in spec.tags}
    df = store.query_telemetry(
        scenario_id, asset_id, tags, datetime.fromtimestamp(a, UTC), datetime.fromtimestamp(b, UTC)
    )
    series, down = [], False
    for tag in tags:
        sub = df[df["tag"].astype(str) == tag] if not df.empty else df
        if sub.empty:
            ts, vals = np.empty(0, np.int64), np.empty(0, np.float64)
        else:
            t = pd.to_datetime(sub["ts"], utc=True)
            ts = (t.astype("datetime64[s, UTC]").astype("int64")).to_numpy(np.int64)
            vals = sub["value"].to_numpy(np.float64)
            order = np.argsort(ts, kind="stable")
            ts, vals = ts[order], vals[order]
        down = down or len(ts) > cap
        series.append({"tag": tag, "unit": units[tag], "points": downsample(ts, vals, a, b, cap)})
    prov = T._prov_refs(
        store.get_provenance(
            scenario_id,
            asset_id,
            tags,
            datetime.fromtimestamp(a, UTC),
            datetime.fromtimestamp(b, UTC),
        ),
        label_tag=True,
    )
    return {
        "scenario_id": scenario_id, "asset_id": asset_id, "t0": _iso(a), "t1": _iso(b),
        "series": series, "provenance": [p.model_dump(mode="json") for p in prov],
        "downsampled": down,
    }  # fmt: skip
