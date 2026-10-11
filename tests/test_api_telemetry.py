"""GET /api/scenarios/{id}/telemetry (offline, DuckDB): shape, provenance, validation, caps."""

from __future__ import annotations

import contextlib
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import numpy as np
import pyarrow.parquet as pq
import pytest

from agents.schemas import CauseClass
from api import telemetry_view as tv
from api.main import create_app
from simulator import generate as gen_mod
from simulator.generate import Scenario, Slot, build, write_scenario
from simulator.load import DuckDBStore, load_duckdb
from simulator.text_artifacts import TextGen, build_work_orders
from tests.api_fakes import make_settings

ROOT = Path(__file__).resolve().parents[1]
REAL_DB = ROOT / "data" / "andon.duckdb"
HIST = 4 * 86400
ASSET, TAGS = "UT-AIR", "compressor_current_a"


class StoreProvider:
    def __init__(self, store, rows):
        self.store, self.rows = store, rows

    def list_scenarios(self):
        return list(self.rows)

    def open(self, scenario_id):
        return contextlib.nullcontext(self.store)


def _rows(store):
    out = []
    for sid in store.list_scenarios():
        se = store.get_stop_event(sid)
        out.append({"scenario_id": sid, "line_id": se["line_id"],
                    "stopped_station": se["stopped_station"], "stop_ts": str(se["stop_ts"]),
                    "sources": []})  # fmt: skip
    return out


@pytest.fixture(scope="module")
def synth(tmp_path_factory):
    root = tmp_path_factory.mktemp("telemetry_api")
    g = TextGen(mode="template")
    wos, labels = g.run(build_work_orders(g, 200, 7, Path("/nonexistent")))
    kinds = {lb["wo_id"]: lb["kind"] for lb in labels}
    pool = [w for w in wos if kinds[w["wo_id"]] == "normal"]
    b = build(Scenario("S801", 2026801, Slot(CauseClass.AIR_PRESSURE_DROP, "clean", 0), HIST),
              TextGen(mode="template"), pool)  # fmt: skip
    write_scenario(root / "scenarios", "S801", b)
    pq.write_table(gen_mod.wo_table(pool, None), root / "work_orders.parquet")
    store = load_duckdb(root / "scenarios", root / "andon.duckdb")
    yield store
    store.close()


def _client(tmp_path, store):
    app = create_app(make_settings(tmp_path), provider=StoreProvider(store, _rows(store)),
                     live_runner=lambda *a: None)  # fmt: skip
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


def _url(sid="S801", **q):
    q = {"asset_id": ASSET, "tags": TAGS, **q}
    return f"/api/scenarios/{sid}/telemetry?" + "&".join(f"{k}={v}" for k, v in q.items())


async def test_shape_default_window_and_cap(tmp_path, synth):
    stop = datetime.fromisoformat(
        str(synth.get_stop_event("S801")["stop_ts"]).replace("Z", "+00:00")
    )
    stop = stop if stop.tzinfo else stop.replace(tzinfo=UTC)
    async with _client(tmp_path, synth) as c:
        r = await c.get(_url(max_points=50))
    assert r.status_code == 200, r.text
    d = r.json()
    assert set(d) == {"scenario_id", "asset_id", "t0", "t1", "series", "provenance", "downsampled"}
    assert d["t1"] == stop.strftime("%Y-%m-%dT%H:%M:%SZ")
    assert d["t0"] == (stop - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
    s = d["series"][0]
    assert s["tag"] == TAGS and s["unit"] == "A"
    assert 0 < len(s["points"]) <= 50 and d["downsampled"] is True
    ts, v = s["points"][0]
    assert ts.endswith("Z") and (v is None or isinstance(v, float))
    assert {"source_id", "real", "source_ref"} <= set(d["provenance"][0])
    assert all(p["real"] is False for p in d["provenance"])


async def test_max_points_clamped(tmp_path, synth):
    async with _client(tmp_path, synth) as c:
        lo = (await c.get(_url(max_points=1))).json()["series"][0]["points"]
        hi = (await c.get(_url(max_points=10**6, t0="2026-01-01T00:00:00Z"))).status_code
    assert len(lo) <= 10
    assert hi == 400  # window > 7 d (and the clamp did not 500)


@pytest.mark.parametrize(
    "path,status,code",
    [
        (_url(sid="NOPE"), 404, "unknown_scenario"),
        (_url(asset_id="NOPE"), 404, "unknown_asset"),
        (_url(tags="nope"), 400, "unknown_tag"),
        (_url(tags=",".join(f"t{i}" for i in range(9))), 400, "too_many_tags"),
        (_url(t0="2026-01-02T00:00:00Z", t1="2026-01-01T00:00:00Z"), 400, "bad_window"),
        (_url(t0="2026-01-01T00:00:00Z", t1="2026-01-09T00:00:00Z"), 400, "window_too_long"),
        (_url(t0="garbage", t1="2026-01-09T00:00:00Z"), 400, "bad_time"),
    ],
)
async def test_validation_errors(tmp_path, synth, path, status, code):
    async with _client(tmp_path, synth) as c:
        r = await c.get(path)
    assert r.status_code == status
    assert r.json()["detail"]["code"] == code


async def test_rate_limited_per_ip(tmp_path, synth, monkeypatch):
    monkeypatch.setattr("api.context.TELEMETRY_READS_PER_MIN_PER_IP", 2)
    async with _client(tmp_path, synth) as c:
        codes = [(await c.get(_url(max_points=20))).status_code for _ in range(3)]
    assert codes == [200, 200, 429]


def test_downsample_keeps_gaps_as_null():
    ts = np.arange(0, 1000, dtype=np.int64)
    vals = np.ones(1000)
    vals[100:300] = np.nan
    ts2 = np.concatenate([ts[:500], ts[700:]])  # a hole with no samples at all
    vals2 = np.concatenate([vals[:500], vals[700:]])
    pts = tv.downsample(ts2, vals2, 0, 1000, 100)
    assert len(pts) == 100
    assert pts[15][1] is None and pts[55][1] is None  # NaN-only bucket, empty bucket
    assert pts[0][1] == 1.0


@pytest.mark.skipif(not REAL_DB.exists(), reason="real data/andon.duckdb absent")
async def test_real_scenario_provenance_marked_real(tmp_path):
    store = DuckDBStore(REAL_DB)
    try:
        async with _client(tmp_path, store) as c:
            u = "/api/scenarios/R002/telemetry?asset_id={}&tags={}&max_points=100"
            real = await c.get(u.format("UT-AIR", "header_pressure_bar,compressor_current_a"))
            synth_ = await c.get(u.format("ST20-WLD", "air_pressure_bar"))
        assert real.status_code == 200, real.text
        prov = real.json()["provenance"]
        assert prov and all(p["real"] and p["source_id"] == "metropt3" for p in prov)
        assert len(real.json()["series"]) == 2
        assert synth_.status_code == 200 and all(not p["real"] for p in synth_.json()["provenance"])
    finally:
        store.close()
