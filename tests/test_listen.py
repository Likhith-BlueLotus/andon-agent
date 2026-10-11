"""listen(): MFCC baseline, clip lookup, Gemini caching, no label leakage (offline; LLM faked)."""

from __future__ import annotations

import builtins
import io
import json
import pathlib
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
from scipy.io import wavfile

import agents.listen as L
import agents.tools as T
from agents.llm import LLM, set_default_llm
from analytics import audio as A

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCEN = ROOT / "data" / "scenarios"
REAL_DB = ROOT / "data" / "andon.duckdb"
SR = 16_000
SID = "S901"
STOP = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
START = STOP - timedelta(days=7)
BUCKET = "test-bucket"
MARK = "LEAKMARKER-abnormal-label"


def _iso(d: datetime) -> str:
    return d.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


# --- synthetic audio -------------------------------------------------------------------------
def _machine(seed: int, knocks: bool = False) -> np.ndarray:
    """A 'pump': 120 Hz hum + harmonics + broadband noise; abnormal adds irregular knocks and a
    2.5 kHz rattle band."""
    rng = np.random.default_rng(seed)
    t = np.arange(10 * SR) / SR
    y = 0.02 * np.sin(2 * np.pi * 120 * t) + 0.008 * np.sin(2 * np.pi * 240 * t + 1.0)
    y = y + 0.004 * rng.standard_normal(len(t))
    if knocks:
        for k in rng.uniform(0.2, 9.8, 25):
            i = int(k * SR)
            n = int(0.03 * SR)
            y[i : i + n] += (
                0.05 * np.exp(-np.arange(n) / 80) * np.sin(2 * np.pi * 2500 * np.arange(n) / SR)
            )
    return y


def _wav(y: np.ndarray) -> bytes:
    buf = io.BytesIO()
    wavfile.write(buf, SR, np.round(np.clip(y, -1, 1) * 32767).astype(np.int16))
    return buf.getvalue()


# --- fakes -----------------------------------------------------------------------------------
class FakeStore:
    """The two store calls listen makes, plus provenance rows like simulator.audio writes."""

    def __init__(self, clips: list[dict]) -> None:
        self.rows = [
            {
                "scenario_id": SID, "asset_id": c["asset_id"], "tag": "audio",
                "t0": pd.Timestamp(c["ts"]), "t1": pd.Timestamp(c["ts"]) + pd.Timedelta(seconds=10),
                "source_id": "mimii",
                "source_ref": f"MIMII 6_dB_pump.zip :: pump/id_00/<label withheld>/{i:08d}.wav (sha256 {i:016x})",
                "transform": "downmix",
            }
            for i, c in enumerate(clips)
        ]  # fmt: skip

    def get_stop_event(self, scenario_id: str) -> dict:
        assert scenario_id == SID
        return {"scenario_id": SID, "line_id": "L1", "stop_ts": STOP, "history_start": START,
                "history_end": STOP}  # fmt: skip

    def get_provenance(self, scenario_id, asset_id=None, tags=None, t0=None, t1=None):
        df = pd.DataFrame(self.rows)
        df = df[(df.scenario_id == scenario_id) & (df.asset_id == asset_id) & df.tag.isin(tags)]
        if t0 is not None:
            df = df[(df.t1 > pd.Timestamp(t0)) & (df.t0 < pd.Timestamp(t1))]
        return df.reset_index(drop=True)


class FakeGCS:
    def __init__(self, blobs: dict[str, bytes]) -> None:
        self.blobs, self.reads = blobs, []

    def read_bytes(self, uri: str) -> bytes:
        self.reads.append(uri)
        return self.blobs[uri]


class FakeTransport:
    def __init__(self, reply: dict | None = None, fail: Exception | None = None) -> None:
        self.calls: list[tuple[str, list, object]] = []
        self.reply = reply or {"finding": "Irregular knocking over the steady hum.", "abnormal": True,
                               "confidence": 0.8, "characteristics": ["knocking", "steady hum"],
                               "recording_quality": "clear"}  # fmt: skip
        self.fail = fail

    async def __call__(self, model, contents, cfg):
        self.calls.append((model, contents, cfg))
        if self.fail:
            raise self.fail
        um = SimpleNamespace(prompt_token_count=700, candidates_token_count=80,
                             thoughts_token_count=120, cached_content_token_count=0)  # fmt: skip
        return SimpleNamespace(text=json.dumps(self.reply), parsed=None, usage_metadata=um)


# --- fixtures --------------------------------------------------------------------------------
def _clips() -> tuple[list[dict], dict[str, bytes]]:
    plan = [  # (ts, asset, abnormal?)
        (START + timedelta(days=1), "ST40-SLR", False),
        (START + timedelta(days=3), "ST40-SLR", False),
        (START + timedelta(days=5), "ST40-SLR", False),
        (STOP - timedelta(minutes=20), "ST40-SLR", True),
        (START + timedelta(days=2), "UT-AIR", False),
        (STOP - timedelta(minutes=30), "UT-AIR", False),
    ]
    clips, blobs = [], {}
    for i, (ts, aid, ab) in enumerate(plan):
        uri = f"gs://{BUCKET}/audio/{SID}/{aid}/{ts:%Y%m%dT%H%M%SZ}.wav"
        blobs[uri] = _wav(_machine(100 + i, knocks=ab))
        clips.append({"ts": _iso(ts), "asset_id": aid, "machine_type": "pump" if aid == "ST40-SLR" else "valve",
                      "machine_id": "id_00", "gs_uri": uri,
                      "label": MARK, "noisy_normal": MARK, "source_path": MARK})  # fmt: skip
    return clips, blobs


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(L, "CACHE_DIR", tmp_path / "cache")
    clips, blobs = _clips()
    index = {"scenario_id": SID, "clip_duration_s": 10, "sample_rate_hz": SR, "clips": clips}
    fake = FakeTransport()
    prev = set_default_llm(LLM(transport=fake))
    store, gcs = FakeStore(clips), FakeGCS(blobs)

    def make_ctx():
        ctx = T.ToolContext(store, SID, gcs=gcs, now=lambda: datetime(2026, 10, 11, tzinfo=UTC))
        L.set_index_resolver(ctx, lambda sid: index if sid == SID else None)
        return ctx

    yield SimpleNamespace(ctx=make_ctx, fake=fake, gcs=gcs, index=index, tmp=tmp_path)
    set_default_llm(prev)


W = (_iso(STOP - timedelta(hours=3)), _iso(STOP))


# --- analytics.audio -------------------------------------------------------------------------
def test_mfcc_shape_and_determinism():
    y = _machine(1)
    m = A.mfcc(y)
    assert m.shape == (1 + (len(y) - A.N_FFT) // A.HOP, A.N_MFCC)
    assert np.array_equal(m, A.mfcc(y.copy()))
    assert np.isfinite(m).all()
    with pytest.raises(ValueError):
        A.mfcc(np.zeros(100))


def test_mfcc_distance_separates_synthetic_fault():
    refs = [A.features(_machine(s)) for s in (1, 2, 3)]
    normal = A.compare(A.features(_machine(4)), refs)
    abnormal = A.compare(A.features(_machine(5, knocks=True)), refs)
    assert 0.8 < normal["mfcc_distance"] < 1.3  # ~1.0 = like the references
    assert abnormal["mfcc_distance"] > 1.5 * normal["mfcc_distance"]
    assert abnormal["mfcc_z"] > 3 > normal["mfcc_z"]
    one = A.compare(A.features(_machine(4)), refs[:1])
    assert one["mfcc_z"] is None and one["n_reference_clips"] == 1


def test_read_wav_multichannel_and_rate():
    y = _machine(1)
    st = np.stack([y, y], axis=1)
    buf = io.BytesIO()
    wavfile.write(buf, SR, np.round(st * 32767).astype(np.int16))
    assert np.allclose(A.read_wav(buf.getvalue()), A.read_wav(_wav(y)), atol=1e-4)
    buf = io.BytesIO()
    wavfile.write(buf, 8000, np.zeros(8000, dtype=np.int16))
    with pytest.raises(ValueError):
        A.read_wav(buf.getvalue())


@pytest.mark.skipif(not (SCEN / "S014" / "audio_index.json").exists(), reason="local clips absent")
def test_mfcc_distance_larger_for_abnormal_on_local_mimii_clips():
    """Dev scenarios only (S001-S050; S051-S060 are held out). Uses the eval-only labels."""
    d = {"normal": [], "abnormal": []}
    for n in range(1, 51):
        sdir = SCEN / f"S{n:03d}"
        if not (sdir / "audio_index.json").exists():
            continue
        idx = json.loads((sdir / "audio_index.json").read_text())
        lab = {(c["asset_id"], c["ts"]): c["label"]
               for c in json.loads((sdir / "audio_truth.json").read_text())["clips"]}  # fmt: skip
        for aid in ("ST40-SLR", "ST20-WLD", "ST30-WLD"):  # pump + fans: the baseline's strong side
            cs = sorted((c for c in idx["clips"] if c["asset_id"] == aid), key=lambda c: c["ts"])
            if not all((ROOT / c["local_file"]).exists() for c in cs):
                pytest.skip("local clip files absent")
            f = [A.features_from_wav((ROOT / c["local_file"]).read_bytes()) for c in cs]
            d[lab[(aid, cs[-1]["ts"])]].append(A.compare(f[-1], f[:-1])["mfcc_distance"])
    assert len(d["abnormal"]) >= 5
    assert np.median(d["abnormal"]) > 1.3 * np.median(d["normal"])


# --- the tool ---------------------------------------------------------------------------------
def test_listen_summary_evidence_and_provenance(env):
    ctx = env.ctx()
    out = T.TOOL_REGISTRY["listen"].fn(ctx, asset_id="ST40-SLR", t0=W[0], t1=W[1])
    assert "error" not in out, out
    s = out["summary"]
    assert out["evidence_id"] == "ev_listen_1"
    assert s["clip_uri"].endswith(f"{STOP - timedelta(minutes=20):%Y%m%dT%H%M%SZ}.wav")
    assert s["abnormal"] is True and s["normal_vs_abnormal_confidence"] == 0.8
    assert s["p_abnormal"] == 0.8 and s["gemini_status"] == "ok"
    assert s["n_reference_clips"] == 3 and s["reference_rule"] == "before_window"
    assert s["mfcc_distance"] > 1.5 and s["mfcc_z"] > 3
    ev = ctx.evidence[out["evidence_id"]]
    assert ev.tool == "listen" and ev.args == {"asset_id": "ST40-SLR", "t0": W[0], "t1": W[1]}
    prov = out["provenance"]
    assert prov and all(p["source_id"] == "mimii" and p["real"] is True for p in prov)
    assert "sha256 0000000000000003" in prov[0]["source_ref"]  # the queried clip's row
    assert "<label withheld>" in prov[0]["source_ref"]
    json.dumps(out, allow_nan=False)
    # Gemini got the rubric, the newest reference and the query as gs:// audio parts
    (model, contents, cfg), = env.fake.calls  # fmt: skip
    assert model == L.MODEL == "gemini-3.8-flash"
    uris = [p.file_data.file_uri for p in contents[0].parts if p.file_data]
    assert uris == [env.index["clips"][2]["gs_uri"], env.index["clips"][3]["gs_uri"]]
    assert all(p.file_data.mime_type == "audio/wav" for p in contents[0].parts if p.file_data)
    assert cfg.response_schema is L.GeminiFinding and cfg.temperature is None
    assert "mfcc" not in contents[0].parts[0].text.lower()  # independent opinions


def test_normal_clip_scores_low(env):
    env.fake.reply = {"finding": "Steady.", "abnormal": False, "confidence": 0.7,
                      "characteristics": [], "recording_quality": "clear"}  # fmt: skip
    out = T.listen(env.ctx(), asset_id="UT-AIR", t0=W[0], t1=W[1])
    s = out["summary"]
    assert s["abnormal"] is False and s["p_abnormal"] == 0.3
    assert s["n_reference_clips"] == 1 and s["mfcc_z"] is None  # one reference: no spread
    assert 0.8 < s["mfcc_distance"] < 1.3


def test_rerun_reproduces_from_cache_without_llm_call(env):
    ctx = env.ctx()
    out = T.listen(ctx, asset_id="ST40-SLR", t0=W[0], t1=W[1])
    assert len(env.fake.calls) == 1
    files = list((env.tmp / "cache").rglob("*.json"))
    assert len(files) == 1
    entry = json.loads(files[0].read_text())
    assert entry["prompt_version"].startswith("listen_rubric v") and entry["model"] == L.MODEL
    again = T.rerun(env.ctx(), ctx.evidence[out["evidence_id"]])  # fresh ctx, as the verifier
    assert json.dumps(again["summary"], sort_keys=True) == json.dumps(
        out["summary"], sort_keys=True
    )
    assert again["provenance"] == out["provenance"]
    assert len(env.fake.calls) == 1  # LLM part from the cache; MFCC part recomputed


def test_no_label_leakage(env):
    """Index fields beyond the whitelist (labels, source paths) never reach Gemini or the
    summary."""
    ctx = env.ctx()
    out = T.listen(ctx, asset_id="ST40-SLR", t0=W[0], t1=W[1])
    blob = json.dumps(out) + json.dumps(dict(ctx.state))
    assert MARK not in blob
    for forbidden in ("label", "noisy_normal", "source_path", "source_sha256", "hints"):
        assert forbidden not in out["summary"]
    _, contents, _ = env.fake.calls[0]
    assert MARK not in str(contents)


@pytest.mark.skipif(not (REAL_DB.exists() and (SCEN / "S002" / "audio_index.json").exists()),
                    reason="real store / scenarios absent")  # fmt: skip
def test_listen_on_real_store_never_opens_truth_files(tmp_path, monkeypatch):
    from simulator.load import DuckDBStore

    monkeypatch.setattr(L, "CACHE_DIR", tmp_path / "cache")
    fake = FakeTransport()
    prev = set_default_llm(LLM(transport=fake))
    opened: list[str] = []
    real_open, real_rt, real_rb = builtins.open, pathlib.Path.read_text, pathlib.Path.read_bytes

    def check(p):
        name = str(p)
        opened.append(name)
        if "truth" in pathlib.Path(name).name or "sim_meta" in name:
            raise AssertionError(f"listen opened {name}")

    def g_open(f, *a, **k):
        check(f)
        return real_open(f, *a, **k)

    def g_rt(self, *a, **k):
        check(self)
        return real_rt(self, *a, **k)

    def g_rb(self, *a, **k):
        check(self)
        return real_rb(self, *a, **k)

    s = DuckDBStore(REAL_DB)
    try:
        se = s.get_stop_event("S002")
        t1 = _iso(se["stop_ts"])
        t0 = _iso(se["stop_ts"] - timedelta(hours=3))
        monkeypatch.setattr(builtins, "open", g_open)
        monkeypatch.setattr(pathlib.Path, "read_text", g_rt)
        monkeypatch.setattr(pathlib.Path, "read_bytes", g_rb)
        out = T.listen(T.ToolContext(s, "S002"), asset_id="UT-AIR", t0=t0, t1=t1)
    finally:
        monkeypatch.undo()
        s.close()
        set_default_llm(prev)
    assert "error" not in out, out
    assert any(n.endswith("audio_index.json") for n in opened)
    assert out["summary"]["n_reference_clips"] >= 1 and out["summary"]["mfcc_distance"] > 0
    assert all(p["real"] and p["source_id"] == "mimii" for p in out["provenance"])


@pytest.mark.parametrize(
    ("args", "code"),
    [
        ({"asset_id": "ST40-SLR", "t0": _iso(START + timedelta(hours=1)), "t1": _iso(START + timedelta(hours=2))}, "no_clip_in_window"),
        ({"asset_id": "ST10-PRS", "t0": W[0], "t1": W[1]}, "no_audio"),
        ({"asset_id": "NOPE", "t0": W[0], "t1": W[1]}, "unknown_asset"),
        ({"asset_id": "ST40-SLR", "t0": W[1], "t1": W[0]}, "bad_window"),
        ({"asset_id": "ST40-SLR", "t0": "yesterday", "t1": W[1]}, "bad_time"),
    ],
)  # fmt: skip
def test_structured_errors(env, args, code):
    out = T.listen(env.ctx(), **args)
    assert out["evidence_id"] is None and out["error"]["code"] == code, out
    if code == "no_clip_in_window":
        assert "recordings at" in out["error"]["hint"]
    assert not env.fake.calls


def test_index_unavailable_is_structured(env):
    ctx = env.ctx()
    L.set_index_resolver(ctx, lambda sid: None)
    out = T.listen(ctx, asset_id="ST40-SLR", t0=W[0], t1=W[1])
    assert out["error"]["code"] == "audio_unavailable"


def test_wide_window_falls_back_to_earlier_references(env):
    out = T.listen(env.ctx(), asset_id="ST40-SLR", t0=_iso(START), t1=_iso(STOP))
    s = out["summary"]
    assert s["clips_in_window"] == 4 and s["reference_rule"] == "earlier_than_clip_by_1h"
    assert s["n_reference_clips"] == 3


def test_gemini_failure_keeps_mfcc_and_writes_no_cache(env):
    env.fake.fail = RuntimeError("boom")
    out = T.listen(env.ctx(), asset_id="ST40-SLR", t0=W[0], t1=W[1])
    s = out["summary"]
    assert s["gemini_status"] == "unavailable" and s["finding"] is None and s["abnormal"] is None
    assert s["mfcc_distance"] > 1.5
    assert not (env.tmp / "cache").exists() or not list((env.tmp / "cache").rglob("*.json"))


def test_unparseable_and_out_of_range_output(env):
    env.fake.reply = {"finding": "x" * 900, "abnormal": False, "confidence": 1.7,
                      "characteristics": [f"c{i}" for i in range(20)], "recording_quality": "clear"}  # fmt: skip
    s = T.listen(env.ctx(), asset_id="ST40-SLR", t0=W[0], t1=W[1])["summary"]
    assert len(s["finding"]) <= L.MAX_FINDING_CHARS and s["normal_vs_abnormal_confidence"] == 1.0
    assert len(s["characteristics"]) == L.MAX_CHARACTERISTICS
    env.fake.reply = {"finding": "?"}
    L.CACHE_DIR = env.tmp / "cache2"
    s = T.listen(env.ctx(), asset_id="ST40-SLR", t0=W[0], t1=W[1])["summary"]
    assert s["gemini_status"] == "unparseable" and s["mfcc_distance"] is not None


async def test_works_inside_a_running_event_loop(env):
    """ADK calls sync tools on its event loop thread; the LLM call must not deadlock."""
    out = T.listen(env.ctx(), asset_id="ST40-SLR", t0=W[0], t1=W[1])
    assert out["summary"]["gemini_status"] == "ok"


def test_bound_for_adk_with_tool_context_state(env):
    ctx = env.ctx()
    (fn,) = T.bind_tools(ctx, ["listen"], adk=True)
    tc = SimpleNamespace(state={})
    out = fn(asset_id="ST40-SLR", t0=W[0], t1=W[1], tool_context=tc)
    assert f"evidence:{out['evidence_id']}" in tc.state and not ctx.state


def test_gemini_timeout_is_bounded(env, monkeypatch):
    import asyncio
    import time

    async def slow(model, contents, cfg):
        await asyncio.sleep(5)

    set_default_llm(LLM(transport=slow))
    monkeypatch.setattr(L, "ATTEMPT_TIMEOUT_S", 0.05)
    monkeypatch.setattr(L, "TOTAL_TIMEOUT_S", 0.3)
    t = time.perf_counter()
    s = T.listen(env.ctx(), asset_id="ST40-SLR", t0=W[0], t1=W[1])["summary"]
    assert time.perf_counter() - t < 3
    assert s["gemini_status"] == "timeout" and s["mfcc_distance"] is not None
