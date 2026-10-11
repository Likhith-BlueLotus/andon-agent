"""Offline tests for the live serving store (ADR-021): simulator.publish -> GCS layout ->
agents.store_cache. GCS is replaced by an in-memory bucket; scenarios are generated small
(2.5-day history, template text, no LLM). Ground truth is read here only to prove it is never
published."""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import threading
import time
from datetime import timedelta
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from agents import store_cache as SC
from agents.schemas import CauseClass
from simulator import generate as gen_mod
from simulator import publish as P
from simulator.blobstore import SCENARIO_OBJECTS, STORE_PREFIX, MemoryBucket
from simulator.generate import Scenario, Slot, build, write_scenario
from simulator.load import TelemetryStore, load_duckdb
from simulator.text_artifacts import TextGen, build_work_orders

C = CauseClass
ROOT = Path(__file__).resolve().parents[1]
HIST = int(2.5 * 86400)
CASES = {"S951": (C.AIR_PRESSURE_DROP, "clean"), "S952": (C.WELD_TIP_WEAR, "red_herring")}


@pytest.fixture(scope="module")
def data_root(tmp_path_factory):
    root = tmp_path_factory.mktemp("pubdata")
    g = TextGen(mode="template")
    wos, labels = g.run(build_work_orders(g, 120, 7, Path("/nonexistent")))
    kinds = {lb["wo_id"]: lb["kind"] for lb in labels}
    pool = [w for w in wos if kinds[w["wo_id"]] == "normal"]
    truths = {}
    for sid, (cls, variant) in CASES.items():
        sc = Scenario(sid, 2026_900 + int(sid[1:]), Slot(cls, variant, 0), HIST)  # type: ignore[arg-type]
        b = build(sc, TextGen(mode="template"), pool)
        d = write_scenario(root / "scenarios", sid, b)
        truths[sid] = b["truth"]
        # what the audio step adds, plus decoys that must never be published
        (d / "audio_index.json").write_text(json.dumps({"scenario_id": sid, "clips": []}))
        (d / "audio_truth.json").write_text(json.dumps({"scenario_id": sid, "eval_only": True}))
        (d / "sim_meta.json").write_text(json.dumps({"seed": 1}))
        pq.write_table(pa.table({"wo_id": ["x"], "kind": ["fault"]}), d / "wo_labels.parquet")
        assert (d / "truth.json").exists()
    pq.write_table(gen_mod.wo_table(pool, None), root / "work_orders.parquet")
    return root, truths


@pytest.fixture()
def published(data_root):
    root, truths = data_root
    bucket = MemoryBucket()
    res = P.publish(root / "scenarios", bucket, log=lambda *_: None)
    return root, truths, bucket, res


def _cache(bucket, tmp_path, **kw) -> SC.StoreCache:
    return SC.StoreCache(bucket, cache_dir=tmp_path / "cache", manifest_ttl_s=3600, **kw)


# --- publish ---------------------------------------------------------------------------------
def test_publish_uploads_only_the_allow_list(published):
    _, _, bucket, res = published
    names = set(bucket.objects)
    for sid in CASES:
        mine = {n.rsplit("/", 1)[1] for n in names if n.startswith(f"{STORE_PREFIX}/{sid}/")}
        assert mine == set(SCENARIO_OBJECTS)
        assert set(res["denied"][sid]) == {
            "truth.json",
            "sim_meta.json",
            "audio_truth.json",
            "wo_labels.parquet",
        }
    assert not [n for n in names if P.is_denied(n.rsplit("/", 1)[1])]
    assert f"{STORE_PREFIX}/manifest.json" in names
    shared = {n for n in names if "/_shared/" in n}
    assert {n.rsplit("/", 1)[1] for n in shared} == {
        "work_orders.parquet",
        "assets.parquet",
        "spec_limits.parquet",
    }


def test_manifest_is_truth_free(published):
    _, truths, bucket, _ = published
    raw = bucket.objects[f"{STORE_PREFIX}/manifest.json"][0].decode()
    m = json.loads(raw)
    assert not P._walk_keys(m) & P.TRUTH_KEYS
    for c in CauseClass:
        assert c.value not in raw
    for word in ("truth", "variant", "red_herring", "dual_fault", "no_fault", "onset", "seed"):
        assert word not in raw.lower()
    for sid, t in truths.items():
        assert t.onset_ts is None or t.onset_ts.isoformat()[:19] not in raw
        e = m["scenarios"][sid]
        assert set(e) == {"set", "source_label", "sources", "line_id", "stopped_station",
                          "stop_ts", "objects"}  # fmt: skip
        assert e["set"] == "synthetic" and e["source_label"] == "Synthetic line"
        assert set(e["objects"]) == set(SCENARIO_OBJECTS)
        for meta in e["objects"].values():
            assert set(meta) == {"sha256", "bytes"} and len(meta["sha256"]) == 64


def test_published_bytes_contain_no_truth_fields(published):
    _, _, bucket, _ = published
    for name, (data, _, _) in bucket.objects.items():
        if name.endswith(".json"):
            assert not P._walk_keys(json.loads(data)) & P.TRUTH_KEYS, name
        else:
            cols = set(pq.read_schema(pa.BufferReader(data)).names)
            assert not cols & P.TRUTH_KEYS, name


def test_publish_refuses_truth_like_content(data_root, tmp_path):
    root, _ = data_root
    src = root / "scenarios" / "S951"
    bad_root = tmp_path / "d" / "scenarios"
    bad = bad_root / "S951"
    bad.mkdir(parents=True)
    for f in src.iterdir():
        (bad / f.name).write_bytes(f.read_bytes())
    (tmp_path / "d" / "work_orders.parquet").write_bytes(
        (root / "work_orders.parquet").read_bytes()
    )
    se = json.loads((bad / "stop_event.json").read_text())
    (bad / "stop_event.json").write_text(json.dumps({**se, "root_cause_class": "air_leak"}))
    with pytest.raises(P.PublishError, match="truth-like keys"):
        P.publish(bad_root, MemoryBucket(), log=lambda *_: None)
    (bad / "stop_event.json").write_text(json.dumps(se))
    t = pq.read_table(bad / "alarms.parquet")
    pq.write_table(
        t.append_column("variant", pa.array(["clean"] * t.num_rows)), bad / "alarms.parquet"
    )
    with pytest.raises(P.PublishError, match="truth-like columns"):
        P.publish(bad_root, MemoryBucket(), log=lambda *_: None)


def test_publish_is_idempotent_and_ids_merge(published):
    root, _, bucket, first = published
    n_writes = len(bucket.writes)
    again = P.publish(root / "scenarios", bucket, log=lambda *_: None)
    assert again["uploaded"] == 0 and again["skipped"] == first["objects"] - 1
    assert len(bucket.writes) == n_writes  # manifest not rewritten either
    one = P.publish(root / "scenarios", bucket, ids=["S952"], log=lambda *_: None)
    assert set(one["manifest"]["scenarios"]) == set(CASES)
    assert len(bucket.writes) == n_writes


# --- store_cache -----------------------------------------------------------------------------
def _same(a, b) -> None:
    if isinstance(a, pd.DataFrame):
        pd.testing.assert_frame_equal(a.reset_index(drop=True), b.reset_index(drop=True))
    else:
        assert a == b


def test_cache_answers_like_load_duckdb(published, tmp_path):
    root, _, bucket, _ = published
    ref = load_duckdb(root / "scenarios", tmp_path / "ref.duckdb")
    cache = _cache(bucket, tmp_path)
    try:
        for sid in CASES:
            with cache.get(sid) as st:
                assert isinstance(st, TelemetryStore)
                assert st.list_scenarios() == [sid]
                stop = ref.get_stop_event(sid)
                _same(st.get_stop_event(sid), stop)
                t1 = stop["stop_ts"]
                t0 = t1 - timedelta(hours=6)
                _same(st.list_assets(), ref.list_assets())
                _same(
                    st.list_assets(upstream_of="ST20-WLD"), ref.list_assets(upstream_of="ST20-WLD")
                )
                _same(st.spec_limits("UT-AIR"), ref.spec_limits("UT-AIR"))
                tags = ["header_pressure_bar", "compressor_current_a"]
                df = st.query_telemetry(sid, "UT-AIR", tags, t0, t1)
                assert len(df) > 1000
                _same(df, ref.query_telemetry(sid, "UT-AIR", tags, t0, t1))
                h = stop["history_start"]
                _same(st.get_alarms(sid, h, t1), ref.get_alarms(sid, h, t1))
                _same(st.get_shift_notes(sid, h, t1), ref.get_shift_notes(sid, h, t1))
                since = t1 - timedelta(days=400)
                wo = st.get_work_orders(sid, "ST20-WLD", since, 50)
                _same(wo, ref.get_work_orders(sid, "ST20-WLD", since, 50))
                _same(st.get_provenance(sid, "UT-AIR"), ref.get_provenance(sid, "UT-AIR"))
                assert (st.scenario_dir / "audio_index.json").exists()
                with pytest.raises(KeyError):
                    st.get_stop_event("S951" if sid == "S952" else "S952")
        assert sorted(r["scenario_id"] for r in cache.list_published()) == sorted(CASES)
        assert all("objects" not in r for r in cache.list_published())
    finally:
        ref.close()


def test_published_store_routes_by_scenario_and_tools_run(published, tmp_path):
    from agents import tools as T

    _, _, bucket, _ = published
    store = SC.PublishedStore(_cache(bucket, tmp_path))
    assert store.list_scenarios() == sorted(CASES)
    for sid in CASES:
        store.prefetch(sid)
        assert store.get_stop_event(sid)["scenario_id"] == sid
        ctx = T.ToolContext(store, sid)
        out = T.get_stop_event(ctx, "L1")
        assert out.get("evidence_id") and "error" not in out, out
        out = T.list_assets(ctx, "L1", None) if "list_assets" in T.TOOL_REGISTRY else out
        assert "error" not in out, out


def test_sha_mismatch_is_an_error(published, tmp_path):
    _, _, bucket, _ = published
    name = f"{STORE_PREFIX}/S951/alarms.parquet"
    data, ct, sha = bucket.objects[name]
    bucket.objects[name] = (data + b"tampered", ct, sha)
    cache = _cache(bucket, tmp_path)
    with pytest.raises(SC.StoreIntegrityError, match="sha256"):
        cache.get("S951")
    assert not (tmp_path / "cache" / "S951").exists()
    assert not list((tmp_path / "cache").glob(".build-*"))
    cache.get("S952")  # other scenarios are unaffected


def test_manifest_outside_allow_list_is_refused(published, tmp_path):
    _, _, bucket, _ = published
    mname = f"{STORE_PREFIX}/manifest.json"
    m = json.loads(bucket.objects[mname][0])
    m["scenarios"]["S951"]["objects"]["truth" + ".json"] = {"sha256": "0" * 64, "bytes": 1}
    bucket.objects[mname] = (json.dumps(m).encode(), "application/json", "")
    with pytest.raises(SC.StoreIntegrityError, match="allow-list"):
        _cache(bucket, tmp_path).get("S952")


def test_unknown_scenario(published, tmp_path):
    _, _, bucket, _ = published
    cache = _cache(bucket, tmp_path)
    for sid in ("S999", "../x", "R0001"):
        with pytest.raises(SC.UnknownScenarioError):
            cache.get(sid)


def test_lru_eviction_deletes_files_but_never_a_held_store(published, tmp_path):
    _, _, bucket, _ = published
    cache = _cache(bucket, tmp_path, max_entries=1)
    a = cache.get("S951")
    assert (tmp_path / "cache" / "S951" / "store.duckdb").exists()
    cache.get("S952")
    assert cache.cached() == ["S952"] and cache.stats.evictions == ["S951"]
    assert not (tmp_path / "cache" / "S951").exists()
    # an evicted handle transparently rebuilds on its next call
    assert a.get_stop_event("S951")["scenario_id"] == "S951"
    assert cache.stats.builds["S951"] == 2
    with cache.get("S951") as held:
        cache.get("S952")  # over the cap, but S951 is held -> S951 survives
        assert "S951" in cache.cached()
        assert held.get_stop_event("S951")["scenario_id"] == "S951"
    cache.get("S952")
    assert cache.cached() == ["S952"]


def test_rebuild_from_disk_reuses_files(published, tmp_path):
    _, _, bucket, _ = published
    _cache(bucket, tmp_path).get("S951")
    n = sum(v for k, v in bucket.reads.items() if "/S951/" in k)
    fresh = _cache(bucket, tmp_path)
    assert fresh.get("S951").get_stop_event("S951")["scenario_id"] == "S951"
    assert sum(v for k, v in bucket.reads.items() if "/S951/" in k) == n  # nothing re-downloaded


def test_republished_scenario_is_rebuilt(published, tmp_path):
    root, _, bucket, _ = published
    cache = SC.StoreCache(bucket, cache_dir=tmp_path / "cache", manifest_ttl_s=0)
    cache.get("S951")
    mname = f"{STORE_PREFIX}/manifest.json"
    m = json.loads(bucket.objects[mname][0])
    obj = f"{STORE_PREFIX}/S951/shift_notes.parquet"
    t = pq.read_table(root / "scenarios" / "S951" / "shift_notes.parquet").slice(0, 1)
    buf = pa.BufferOutputStream()
    pq.write_table(t, buf)
    data = buf.getvalue().to_pybytes()
    bucket.objects[obj] = (data, "", P.sha256_hex(data))
    m["scenarios"]["S951"]["objects"]["shift_notes.parquet"]["sha256"] = P.sha256_hex(data)
    bucket.objects[mname] = (json.dumps(m).encode(), "application/json", "")
    st = cache.get("S951")
    stop = st.get_stop_event("S951")
    assert len(st.get_shift_notes("S951", stop["history_start"], stop["stop_ts"])) <= 1
    assert cache.stats.builds["S951"] == 2


class _SlowBucket(MemoryBucket):
    def read(self, name: str) -> bytes:
        if not name.endswith("manifest.json"):
            time.sleep(0.05)
        return super().read(name)


def test_concurrent_get_builds_once(published, tmp_path):
    _, _, src, _ = published
    bucket = _SlowBucket()
    bucket.objects = dict(src.objects)
    cache = _cache(bucket, tmp_path)
    barrier = threading.Barrier(6)
    out, errs = [], []

    def worker():
        try:
            barrier.wait()
            out.append(cache.get("S951").get_stop_event("S951")["scenario_id"])
        except Exception as exc:  # pragma: no cover - surfaced by the assert below
            errs.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errs and out == ["S951"] * 6

    async def many():
        return await asyncio.gather(*(cache.aget("S952") for _ in range(5)))

    stores = asyncio.run(many())
    assert {s.scenario_id for s in stores} == {"S952"}
    assert cache.stats.builds == {"S951": 1, "S952": 1}
    assert bucket.reads[f"{STORE_PREFIX}/S951/telemetry.parquet"] == 1


def test_open_store_backends(tmp_path, monkeypatch):
    assert isinstance(SC.open_store("gcs"), SC.PublishedStore)
    with pytest.raises(ValueError):
        SC.open_store("sqlite")


def test_store_cache_never_imports_truth_or_generator():
    code = (
        "import sys, agents.store_cache\n"
        "bad = [m for m in sys.modules if m.startswith(('simulator.generate', "
        "'simulator.truth_schema', 'simulator.publish', 'eval'))]\n"
        "assert not bad, bad\n"
    )
    subprocess.run([sys.executable, "-c", code], cwd=ROOT, check=True)
