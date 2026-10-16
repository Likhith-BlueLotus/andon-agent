"""API tests (offline): SSE framing, heartbeat, disconnect, errors, protection, HITL, replay,
catalogue, CORS, audit. Fakes only (tests/api_fakes.py); no Gemini, no network."""

from __future__ import annotations

import asyncio
import contextlib
import json
import time
from pathlib import Path

import httpx
import pytest

from agents.cmms import InMemoryCMMS
from agents.llm import BudgetExhaustedError, SpendTracker
from agents.schemas import CauseClass
from api.audit import AuditRecorder, MemoryAuditStore
from api.events import EVENT_TYPES, parse_event
from api.main import create_app
from tests.api_fakes import FakeFirestore, FakeProvider, FakeRunner, make_settings, sample_events

PASS = {"X-Demo-Passcode": "open-sesame"}


# ---- harness ----------------------------------------------------------------------------------
class Harness:
    def __init__(self, tmp: Path, runner: FakeRunner | None = None, **kw) -> None:
        self.tmp = tmp
        (tmp / "replays").mkdir(parents=True, exist_ok=True)
        (tmp / "replays" / "r002-sample.jsonl").write_text(
            "".join(json.dumps(e) + "\n" for e in sample_events()), "utf-8"
        )
        self.runner = runner or FakeRunner()
        self.audit = MemoryAuditStore()
        self.live_cmms, self.demo_cmms = InMemoryCMMS(), InMemoryCMMS()
        self.spend = SpendTracker(daily_budget_usd=5.0)
        self.sleeps: list[float] = []
        fs = kw.pop("firestore_client", None)
        fs_audit = kw.pop("fs_audit", False)
        self.settings = make_settings(tmp, firestore=fs is not None, **kw)

        async def fake_sleep(s: float) -> None:
            self.sleeps.append(s)

        self.app = create_app(
            self.settings,
            provider=FakeProvider(),
            live_runner=self.runner,
            audit=None if fs_audit else self.audit,
            cmms_live=None if fs_audit else self.live_cmms,
            cmms_demo=None if fs_audit else self.demo_cmms,
            spend=self.spend,
            firestore_client=fs,
        )
        self.app.state.ctx.sleep = fake_sleep
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=self.app), base_url="http://test"
        )

    async def post(self, url, **kw):
        return await self.client.post(url, **kw)

    async def run(self, sid="R002", mode="replay", headers=None, query="") -> list[dict]:
        r = await self.post(f"/api/incidents/{sid}/investigate?mode={mode}{query}", headers=headers)
        assert r.status_code == 200, r.text
        return parse_sse(r.text)

    async def close(self) -> None:
        await AuditRecorder.drain_all(5)
        self.app.state.ctx.budget.close()
        await self.client.aclose()


@pytest.fixture
async def h(tmp_path):
    hn = Harness(tmp_path)
    yield hn
    await hn.close()


def parse_sse(text: str) -> list[dict]:
    out = []
    for frame in text.split("\n\n"):
        if not frame.strip() or frame.startswith(":"):
            continue
        fields = dict(line.split(": ", 1) for line in frame.split("\n") if ": " in line)
        ev = json.loads(fields["data"])
        assert fields["event"] == ev["type"] and int(fields["id"]) == ev["seq"]
        out.append(ev)
    return out


class Stream:
    """Low-level ASGI driver: incremental chunks with arrival times, and client disconnect."""

    def __init__(self, app, path, headers=None, method="POST") -> None:
        self.app, self.path = app, path
        self.headers = headers or {}
        self.method = method
        self.chunks: list[tuple[float, str]] = []
        self.status = None
        self.resp_headers: dict[str, str] = {}
        self._disconnect = asyncio.Event()
        self._task: asyncio.Task | None = None
        self.t0 = time.perf_counter()

    async def _receive(self):
        if not getattr(self, "_sent_body", False):
            self._sent_body = True
            return {"type": "http.request", "body": b"", "more_body": False}
        await self._disconnect.wait()
        return {"type": "http.disconnect"}

    async def _send(self, msg):
        if msg["type"] == "http.response.start":
            self.status = msg["status"]
            self.resp_headers = {k.decode(): v.decode() for k, v in msg["headers"]}
        elif msg["type"] == "http.response.body" and msg.get("body"):
            self.chunks.append((time.perf_counter() - self.t0, msg["body"].decode()))

    def start(self):
        path, _, qs = self.path.partition("?")
        scope = {
            "type": "http", "asgi": {"version": "3.0", "spec_version": "2.4"},
            "http_version": "1.1", "method": self.method, "path": path, "raw_path": path.encode(),
            "query_string": qs.encode(), "scheme": "http", "server": ("test", 80),
            "client": ("203.0.113.9", 5555), "root_path": "",
            "headers": [(k.lower().encode(), v.encode()) for k, v in self.headers.items()],
        }  # fmt: skip
        self._task = asyncio.create_task(self.app(scope, self._receive, self._send))
        return self

    def disconnect(self):
        self._disconnect.set()

    async def wait(self, timeout=5):
        await asyncio.wait_for(self._task, timeout)

    @property
    def text(self) -> str:
        return "".join(c for _, c in self.chunks)


async def until(cond, timeout=3.0):
    t0 = time.perf_counter()
    while not cond():
        if time.perf_counter() - t0 > timeout:
            raise AssertionError("condition not met in time")
        await asyncio.sleep(0.01)


# ---- SSE framing, order, headers ---------------------------------------------------------------
async def test_live_stream_framing_headers_order(tmp_path):
    hn = Harness(tmp_path)
    s = Stream(hn.app, "/api/incidents/R002/investigate?mode=live", PASS).start()
    await s.wait()
    assert s.status == 200
    assert s.resp_headers["content-type"].startswith("text/event-stream")
    assert s.resp_headers["cache-control"] == "no-cache"
    assert s.resp_headers["x-accel-buffering"] == "no"
    assert s.chunks[0][1] == ": ping\n\n"  # opens the stream immediately
    events = parse_sse(s.text)
    assert events[0]["type"] == "incident_started" and events[0]["data"]["mode"] == "live"
    assert [e["type"] for e in events][-2:] == ["cost", "done"]
    assert [e["seq"] for e in events] == list(range(len(events)))
    assert {e["type"] for e in events} <= set(EVENT_TYPES)
    assert len({e["incident_id"] for e in events}) == 1
    assert s.resp_headers["x-incident-id"] == events[0]["incident_id"]
    # provenance survives the pipeline untouched
    tr = next(e for e in events if e["type"] == "tool_result")
    assert tr["data"]["provenance"]
    # one frame per chunk (flushed per event)
    assert all(c.endswith("\n\n") for _, c in s.chunks)
    await hn.close()


async def test_heartbeat_with_slow_runner(tmp_path):
    hn = Harness(tmp_path, FakeRunner(delay=0.12))
    s = Stream(hn.app, "/api/incidents/R002/investigate?mode=live", PASS).start()
    await until(lambda: len(s.chunks) > 8)
    s.disconnect()
    await s.wait()
    assert s.text.count(": ping\n\n") >= 3
    await hn.close()


async def test_incremental_arrival(tmp_path):
    hn = Harness(tmp_path, FakeRunner(delay=0.05))
    s = Stream(hn.app, "/api/incidents/R002/investigate?mode=live", PASS).start()
    await s.wait(timeout=10)
    data = [t for t, c in s.chunks if c.startswith("id:")]
    assert data[-1] - data[0] > 0.5 and len(set(round(t, 2) for t in data)) > 10
    await hn.close()


# ---- disconnect cancels the run ---------------------------------------------------------------
async def test_disconnect_cancels_runner_and_audits_cancelled(tmp_path):
    runner = FakeRunner(delay=0.05)
    hn = Harness(tmp_path, runner)
    s = Stream(hn.app, "/api/incidents/R002/investigate?mode=live", PASS).start()
    await until(lambda: runner.emitted >= 3)
    s.disconnect()
    await s.wait()
    await until(lambda: runner.cancelled)
    n = runner.emitted
    await asyncio.sleep(0.3)
    assert runner.emitted == n < len(sample_events()) and not runner.finished
    await AuditRecorder.drain_all(5)
    inc = next(iter(hn.audit._inc))
    assert hn.audit.get(inc)["meta"]["summary"]["status"] == "cancelled"
    assert hn.app.state.ctx.live_slots.active == 0  # slot released
    await hn.close()


@pytest.fixture(scope="module")
def adk_env(tmp_path_factory):
    from tests.llm_replay import build_store, materialise

    root = tmp_path_factory.mktemp("adk")
    store = build_store(root, "S801")
    out = root / "llm"
    materialise("S801_air", store, "S801", out)
    yield store, out
    store.close()


async def test_disconnect_stops_a_real_adk_run(tmp_path, monkeypatch, adk_env):
    """The real graph (fixture replay of S801, $0): after the client leaves, no further model call."""
    from agents.events_map import run_incident
    from agents.graph import build_app
    from agents.runtime import ReplayLlm

    store, root = adk_env
    calls = {"n": 0}
    orig = ReplayLlm.generate_content_async

    async def slow(self, llm_request, stream=False):
        calls["n"] += 1
        await asyncio.sleep(0.25)
        async for r in orig(self, llm_request, stream):
            yield r

    monkeypatch.setattr(ReplayLlm, "generate_content_async", slow)

    def runner(sid, incident_id):
        app = build_app(store, mode="replay", fixture_root=root, cmms=InMemoryCMMS())
        return run_incident(app, sid, "live", incident_id=incident_id)

    hn = Harness(tmp_path)
    hn.app.state.ctx.live_runner = runner
    hn.app.state.ctx.provider = FakeProvider([{"scenario_id": "S801", "stopped_station": "ST30"}])
    s = Stream(hn.app, "/api/incidents/S801/investigate?mode=live", PASS).start()
    await until(lambda: calls["n"] >= 1)
    s.disconnect()
    await s.wait()
    await asyncio.sleep(0.4)  # let cancellation unwind
    n = calls["n"]
    await asyncio.sleep(1.0)
    assert calls["n"] == n and n < 8, "model calls continued after the client disconnected"
    await hn.close()


# ---- errors become events ---------------------------------------------------------------------
async def test_exception_becomes_error_then_done(tmp_path):
    hn = Harness(tmp_path, FakeRunner(fail_after=5))
    events = await hn.run(mode="live", headers=PASS)
    types = [e["type"] for e in events]
    assert types[-2:] == ["error", "done"] and types.count("done") == 1
    err = events[-2]["data"]
    assert err["code"] == "internal" and "secret" not in err["message"]  # no internals on the wire
    assert [e["seq"] for e in events] == list(range(len(events)))
    await AuditRecorder.drain_all(5)
    inc = events[0]["incident_id"]
    assert hn.audit.get(inc)["meta"]["summary"]["status"] == "error"
    await hn.close()


async def test_budget_error_in_flight_maps_to_budget_exhausted(tmp_path):
    class Boom(FakeRunner):
        async def _run(self, sid, inc):
            async for ev in super()._run(sid, inc):
                yield ev
                if self.emitted == 4:
                    raise BudgetExhaustedError("daily budget $5.00 exhausted")

    hn = Harness(tmp_path, Boom())
    events = await hn.run(mode="live", headers=PASS)
    assert events[-2]["data"]["code"] == "budget_exhausted" and events[-1]["type"] == "done"
    await hn.close()


async def test_run_timeout(tmp_path):
    hn = Harness(tmp_path, FakeRunner(hang_after=3), run_timeout_s=0.3)
    events = await hn.run(mode="live", headers=PASS)
    assert events[-2]["data"]["code"] == "timeout" and events[-2]["data"]["retryable"]
    assert events[-1]["type"] == "done"
    await hn.close()


async def test_source_ending_without_done_is_completed(tmp_path):
    class Short(FakeRunner):
        async def _run(self, sid, inc):
            async for ev in super()._run(sid, inc):
                if ev.type == "done":
                    return
                yield ev

    hn = Harness(tmp_path, Short())
    events = await hn.run(mode="live", headers=PASS)
    assert events[-1]["type"] == "done" and events[-2]["type"] == "error"
    await hn.close()


# ---- passcode, limits, budget -----------------------------------------------------------------
async def test_live_requires_passcode(h):
    r = await h.post("/api/incidents/R002/investigate?mode=live")
    assert r.status_code == 401 and r.headers["content-type"].startswith("application/json")
    assert r.json()["detail"]["code"] == "passcode_required"
    r = await h.post(
        "/api/incidents/R002/investigate?mode=live", headers={"X-Demo-Passcode": "nope"}
    )
    assert r.status_code == 401
    assert h.runner.started == 0
    assert len(await h.run(mode="live", headers=PASS)) > 10


async def test_live_disabled_without_configured_passcode(tmp_path):
    hn = Harness(tmp_path, demo_passcode="")
    r = await hn.post("/api/incidents/R002/investigate?mode=live", headers=PASS)
    assert r.status_code == 403 and r.json()["detail"]["code"] == "live_disabled"
    cfg = (await hn.client.get("/api/config")).json()
    assert cfg["modes"]["live"] is False and cfg["modes"]["replay"] is True
    await hn.close()


async def test_replay_only_flag(tmp_path):
    hn = Harness(tmp_path, replay_only=True)
    r = await hn.post("/api/incidents/R002/investigate?mode=live", headers=PASS)
    assert r.status_code == 403
    assert (await hn.run()) and hn.runner.started == 0
    await hn.close()


async def test_passcode_bruteforce_is_throttled(h):
    for _ in range(10):
        await h.post("/api/incidents/R002/investigate?mode=live", headers={"X-Demo-Passcode": "x"})
    r = await h.post("/api/incidents/R002/investigate?mode=live", headers=PASS)
    assert r.status_code == 429 and "retry-after" in r.headers


async def test_per_ip_per_minute_limit(tmp_path):
    hn = Harness(tmp_path, live_runs_per_min_per_ip=2)
    for _ in range(2):
        await hn.run(mode="live", headers=PASS)
    r = await hn.post("/api/incidents/R002/investigate?mode=live", headers=PASS)
    assert r.status_code == 429 and r.json()["detail"]["scope"] == "ip_minute"
    assert int(r.headers["retry-after"]) >= 1
    # another client IP (Cloud Run appends the real peer; spoofed leading hops are ignored)
    ok = await hn.post("/api/incidents/R002/investigate?mode=live",
                       headers={**PASS, "X-Forwarded-For": "6.6.6.6, 198.51.100.7"})  # fmt: skip
    assert ok.status_code == 200
    await hn.post("/api/incidents/R002/investigate?mode=live",
                  headers={**PASS, "X-Forwarded-For": "6.6.6.6, 198.51.100.7"})  # fmt: skip
    spoof = await hn.post("/api/incidents/R002/investigate?mode=live",
                          headers={**PASS, "X-Forwarded-For": "1.2.3.4, 198.51.100.7"})  # fmt: skip
    assert spoof.status_code == 429  # same real peer, different spoofed first hop
    await hn.close()


async def test_global_daily_limit(tmp_path):
    hn = Harness(tmp_path, live_runs_per_day=2)
    for i in range(2):
        r = await hn.post("/api/incidents/R002/investigate?mode=live",
                          headers={**PASS, "X-Forwarded-For": f"10.0.0.{i}"})  # fmt: skip
        assert r.status_code == 200
    r = await hn.post("/api/incidents/R002/investigate?mode=live",
                      headers={**PASS, "X-Forwarded-For": "10.0.0.99"})  # fmt: skip
    assert r.status_code == 429 and r.json()["detail"]["scope"] == "day"
    await hn.close()


async def test_limits_are_shared_through_firestore(tmp_path):
    fs = FakeFirestore()
    a = Harness(tmp_path / "a", live_runs_per_day=2, firestore_client=fs)
    b = Harness(tmp_path / "b", live_runs_per_day=2, firestore_client=fs)
    for hn, ip in ((a, "10.0.0.1"), (b, "10.0.0.2")):
        r = await hn.post("/api/incidents/R002/investigate?mode=live", headers={**PASS, "X-Forwarded-For": ip})  # fmt: skip
        assert r.status_code == 200
    r = await a.post("/api/incidents/R002/investigate?mode=live", headers={**PASS, "X-Forwarded-For": "10.0.0.3"})  # fmt: skip
    assert r.status_code == 429  # instance A sees instance B's run
    await a.close()
    await b.close()


async def test_concurrent_live_cap(tmp_path):
    hn = Harness(tmp_path, FakeRunner(delay=0.1), max_concurrent_live=1)
    s = Stream(hn.app, "/api/incidents/R002/investigate?mode=live", PASS).start()
    await until(lambda: hn.runner.emitted >= 1)
    r = await hn.post("/api/incidents/R002/investigate?mode=live", headers=PASS)
    assert r.status_code == 429 and r.json()["detail"]["code"] == "busy"
    s.disconnect()
    await s.wait()
    await hn.close()


async def test_budget_exhausted_is_an_error_event_and_no_run(h):
    h.spend.add(6.0)  # over the $5 budget
    events = await h.run(mode="live", headers=PASS)
    assert [e["type"] for e in events] == ["error", "done"]
    assert events[0]["data"]["code"] == "budget_exhausted" and not events[0]["data"]["retryable"]
    assert h.runner.started == 0
    assert (await h.client.get("/api/config")).json()["budget"]["exhausted"] is True
    assert len(await h.run(mode="replay")) > 10  # replay still works


async def test_budget_is_shared_across_instances(tmp_path):
    fs = FakeFirestore()
    a = Harness(tmp_path / "a", firestore_client=fs)
    b = Harness(tmp_path / "b", firestore_client=fs)
    a.spend.add(5.5)  # instance A books the spend ...
    a.app.state.ctx.budget.drain()
    key = f"spend/{a.app.state.ctx.budget.day()}"
    assert fs.docs[key]["usd"] == pytest.approx(5.5)  # atomic Increment, one doc per IST day
    assert b.spend.spent_today() == 0
    events = await b.run(mode="live", headers=PASS)  # ... instance B refuses
    assert events[0]["data"]["code"] == "budget_exhausted" and b.runner.started == 0
    # and a run already in flight stops at the shared budget: SpendTracker.check() raises
    b.app.state.ctx.budget._set_remote(b.app.state.ctx.budget.day(), 5.5)
    with pytest.raises(BudgetExhaustedError):
        b.spend.check()
    await a.close()
    await b.close()


async def test_config_reports_the_shared_budget_on_a_fresh_instance(tmp_path):
    """Regression (found on Cloud Run): /api/config read the cached shared total, which a fresh
    instance had never refreshed, so it said 'live available' while the shared counter was
    already over budget."""
    fs = FakeFirestore()
    a = Harness(tmp_path / "a", firestore_client=fs)
    b = Harness(tmp_path / "b", firestore_client=fs)
    a.spend.add(5.5)
    a.app.state.ctx.budget.drain()
    cfg = (await b.client.get("/api/config")).json()  # B has made no live call yet
    assert cfg["budget"]["exhausted"] is True and cfg["modes"]["live"] is False
    await a.close()
    await b.close()


async def test_config_survives_an_unreadable_counter(h):
    def boom(day):
        raise OSError("firestore down")

    h.app.state.ctx.budget.store.read = boom
    r = await h.client.get("/api/config")
    assert r.status_code == 200


async def test_budget_fails_closed_when_counter_unreadable(h):
    def boom(day):
        raise OSError("firestore down")

    h.app.state.ctx.budget.store.read = boom
    events = await h.run(mode="live", headers=PASS)
    assert events[0]["data"]["code"] == "budget_exhausted"


# ---- replay -----------------------------------------------------------------------------------
async def test_replay_streams_with_capped_timing_and_flags(h):
    events = await h.run(mode="replay")
    assert events[0]["data"]["mode"] == "replay"
    assert events[0]["incident_id"].startswith("rep_r002_") and events[-1]["type"] == "done"
    assert all(e["incident_id"] == events[0]["incident_id"] for e in events)
    raw = sample_events()
    assert len(events) == len(raw) and [e["type"] for e in events] == [e["type"] for e in raw]
    assert len(h.sleeps) <= len(raw) - 1 and max(h.sleeps) <= 3.0
    assert h.runner.started == 0


async def test_replay_speed_divides_gaps(tmp_path):
    a, b = Harness(tmp_path / "a"), Harness(tmp_path / "b")
    await a.run(mode="replay")
    await b.run(mode="replay", query="&speed=4")
    assert sum(b.sleeps) == pytest.approx(sum(a.sleeps) / 4)
    for x in (a, b):
        await x.close()


async def test_replay_never_touches_gemini(tmp_path, monkeypatch):
    import google.genai as genai

    from agents import llm as llm_mod

    def forbidden(*a, **k):
        raise AssertionError("replay constructed an LLM client / transport")

    monkeypatch.setattr(genai, "Client", forbidden)
    monkeypatch.setattr(llm_mod.LLM, "__init__", forbidden)
    hn = Harness(tmp_path, runner=None)

    def no_live(*a, **k):
        raise AssertionError("live runner called in replay mode")

    hn.app.state.ctx.live_runner = no_live
    assert len(await hn.run(mode="replay")) > 10
    await hn.close()


async def test_replay_pacing_real_time(tmp_path):
    hn = Harness(tmp_path, replay_gap_cap_s=0.05)
    hn.app.state.ctx.sleep = asyncio.sleep
    s = Stream(hn.app, "/api/incidents/R002/investigate").start()  # mode defaults to replay
    await s.wait(timeout=10)
    assert s.status == 200 and parse_sse(s.text)[0]["data"]["mode"] == "replay"
    await hn.close()


async def test_replay_unknown_and_foreign_runs(h):
    r = await h.post("/api/incidents/R002/investigate?mode=replay&run_id=nope")
    assert r.status_code == 404
    r = await h.post("/api/incidents/S001/investigate?mode=replay")  # no replay for S001
    assert r.status_code == 404 and r.json()["detail"]["code"] == "no_replay"
    r = await h.post("/api/incidents/S001/investigate?mode=replay&run_id=r002-sample")
    assert r.status_code == 404  # a run of another scenario
    r = await h.post("/api/incidents/R002/investigate?mode=replay&run_id=../../etc/passwd")
    assert r.status_code == 404
    r = await h.post("/api/incidents/NOPE/investigate")
    assert r.status_code == 404 and r.json()["detail"]["code"] == "unknown_scenario"
    r = await h.post("/api/incidents/..%2Fx/investigate")
    assert r.status_code == 404


async def test_replays_list(h):
    runs = (await h.client.get("/api/replays")).json()["replays"]
    assert len(runs) == 1
    r = runs[0]
    assert r["run_id"] == "r002-sample" and r["scenario_id"] == "R002" and r["recorded_at"]
    assert "rejected" in r["label"].lower() and r["has_work_order"] and r["cost_usd"] is not None


async def test_replay_from_audit_of_a_live_run(h):
    live = await h.run(mode="live", headers=PASS)
    await AuditRecorder.drain_all(5)
    run_id = f"audit:{live[0]['incident_id']}"
    r = await h.post(f"/api/incidents/R002/investigate?mode=replay&run_id={run_id}")
    assert r.status_code == 401  # replaying a live audit needs the passcode
    events = await h.run(mode="replay", query=f"&run_id={run_id}", headers=PASS)
    assert events[0]["data"]["mode"] == "replay" and events[-1]["type"] == "done"
    assert events[0]["incident_id"] != live[0]["incident_id"]
    assert len(events) == len(live)


# ---- audit ------------------------------------------------------------------------------------
async def test_audit_records_every_event_and_is_readable(h):
    events = await h.run(mode="live", headers=PASS)
    inc = events[0]["incident_id"]
    assert (await h.client.get(f"/api/incidents/{inc}/audit")).status_code == 401  # live = private
    a = (await h.client.get(f"/api/incidents/{inc}/audit", headers=PASS)).json()
    assert [s["seq"] for s in a["steps"]] == [e["seq"] for e in events]
    assert [s["type"] for s in a["steps"]] == [e["type"] for e in events]
    assert a["steps"][0]["data"]["scenario_id"] == "R002" and a["steps"][0]["agent"] is None
    assert a["meta"]["summary"]["status"] == "completed"
    assert a["meta"]["summary"]["models"] and a["meta"]["summary"]["cost"]["usd"] > 0
    assert a["meta"]["work_order"]["wo_id"] == f"WO-{inc}"
    assert "ip_hash" not in a["incident"] and a["incident"]["mode"] == "live"
    assert (await h.client.get("/api/incidents/inc_zzz/audit")).status_code == 404
    assert (await h.client.get("/api/incidents/a%20b/audit")).status_code == 404


def test_audit_surface_has_no_update_or_delete():
    from api import audit as A

    for cls in (A.MemoryAuditStore, A.FileAuditStore, A.FirestoreAuditStore, A.AuditRecorder):
        public = [n for n in dir(cls) if not n.startswith("_")]
        bad = [n for n in public if any(w in n for w in ("delete", "update", "remove", "clear", "set", "drop", "overwrite"))]  # fmt: skip
        assert not bad, (cls.__name__, bad)
    assert not [n for n in dir(A) if any(w in n.lower() for w in ("delete", "remove_"))]


async def test_firestore_audit_is_create_only_and_layout(tmp_path):
    fs = FakeFirestore()
    hn = Harness(tmp_path, firestore_client=fs, fs_audit=True)
    events = await hn.run(mode="live", headers=PASS)
    inc = events[0]["incident_id"]
    await AuditRecorder.drain_all(5)
    assert f"audit/{inc}" in fs.docs
    assert f"audit/{inc}/steps/000000" in fs.docs and f"audit/{inc}/steps/{len(events) - 1:06d}" in fs.docs  # fmt: skip
    assert f"audit/{inc}/meta/summary" in fs.docs and f"audit/{inc}/meta/work_order" in fs.docs
    assert not fs.deletes() and {w[0] for w in fs.writes if "/audit/" in w[1] or w[1].startswith("audit/")} == {"create"}  # fmt: skip
    from api.audit import FirestoreAuditStore

    st = FirestoreAuditStore(fs)
    with pytest.raises(FileExistsError):
        st.add_step(inc, 0, {})  # steps are never overwritten
    assert st.add_once(inc, "summary", {"status": "x"}) is False
    assert fs.docs[f"audit/{inc}/meta/summary"]["status"] == "completed"
    # the work order the drafter wrote lives in the CMMS collection, replay ones do not exist
    await hn.close()


# ---- HITL -------------------------------------------------------------------------------------
def safety_orders() -> list[int]:
    wo = next(e for e in sample_events() if e["type"] == "work_order_draft")["data"]
    return [s["order"] for s in wo["steps"] if s["is_safety"]]


def body(**kw):
    b = {"decision": "approve", "rca_decision": "accept", "ticked_safety_steps": safety_orders(),
         "approver_name": "A. Technician", "note": "ok"}  # fmt: skip
    b.update(kw)
    return b


async def live_incident(h: Harness) -> str:
    events = await h.run(mode="live", headers=PASS)
    await AuditRecorder.drain_all(5)
    inc = events[0]["incident_id"]
    wo = next(e for e in events if e["type"] == "work_order_draft")["data"]
    # the real drafter writes the draft to the CMMS; the fake runner stands in for it
    from agents.schemas import WorkOrder

    h.live_cmms.create_draft(WorkOrder.model_validate(wo))
    return inc


async def test_approve_refuses_unticked_safety_steps(h):
    inc = await live_incident(h)
    ticks = safety_orders()[:-1]
    r = await h.post(
        f"/api/incidents/{inc}/approve", json=body(ticked_safety_steps=ticks), headers=PASS
    )
    assert r.status_code == 409 and r.json()["detail"]["code"] == "safety_steps_unticked"
    assert r.json()["detail"]["unticked"] == [safety_orders()[-1]]
    assert h.live_cmms.list(inc)[0].status == "PENDING_APPROVAL"
    a = h.audit.get(inc)
    assert a["actions"][-1]["action"] == "approval_refused"


async def test_approve_happy_path_writes_cmms_and_audit_once(h):
    inc = await live_incident(h)
    r = await h.post(f"/api/incidents/{inc}/approve", json=body(), headers=PASS)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["status"] == "APPROVED" and out["collection"] == "work_orders" and not out["demo"]
    assert h.live_cmms.list(inc)[0].status == "APPROVED"
    act = h.audit.get(inc)["actions"][-1]
    assert act["action"] == "decision" and act["approver_name"] == "A. Technician"
    assert act["status"] == "APPROVED" and act["ticked_safety_steps"] == safety_orders()
    # idempotent: a second decision is refused
    r2 = await h.post(f"/api/incidents/{inc}/approve", json=body(decision="reject"), headers=PASS)
    assert r2.status_code == 409 and r2.json()["detail"]["code"] == "already_decided"
    assert h.live_cmms.list(inc)[0].status == "APPROVED"


async def test_reject_needs_no_ticks(h):
    inc = await live_incident(h)
    r = await h.post(f"/api/incidents/{inc}/approve",
                     json=body(decision="reject", rca_decision="reject", ticked_safety_steps=[]), headers=PASS)  # fmt: skip
    assert r.status_code == 200 and r.json()["status"] == "REJECTED"


async def test_cannot_approve_when_rca_rejected(h):
    inc = await live_incident(h)
    r = await h.post(
        f"/api/incidents/{inc}/approve", json=body(rca_decision="reject"), headers=PASS
    )
    assert r.status_code == 422


async def test_live_approval_requires_passcode(h):
    inc = await live_incident(h)
    r = await h.post(f"/api/incidents/{inc}/approve", json=body())
    assert r.status_code == 401
    assert h.live_cmms.list(inc)[0].status == "PENDING_APPROVAL"


async def test_replay_approval_goes_to_demo_collection_without_passcode(h):
    events = await h.run(mode="replay")
    inc = events[0]["incident_id"]
    wo_id = next(e for e in events if e["type"] == "work_order_draft")["data"]["wo_id"]
    assert wo_id.endswith(inc.rsplit("_", 1)[-1])  # per-viewer work order id
    r = await h.post(f"/api/incidents/{inc}/approve", json=body())
    assert (
        r.status_code == 200 and r.json()["demo"] and r.json()["collection"] == "demo_work_orders"
    )
    assert h.demo_cmms.get(wo_id).status == "APPROVED"
    assert h.live_cmms.list() == []  # the CMMS is untouched
    # a second visitor gets their own work order
    ev2 = await h.run(mode="replay")
    assert ev2[0]["incident_id"] != inc
    r = await h.post(f"/api/incidents/{ev2[0]['incident_id']}/approve", json=body())
    assert r.status_code == 200


async def test_approve_validation_and_unknown(h):
    assert (await h.post("/api/incidents/inc_nope/approve", json=body())).status_code == 404
    inc = await live_incident(h)
    for bad in ({"decision": "maybe"}, {"approver_name": ""}, {"extra": 1}, {"ticked_safety_steps": ["a"]}):  # fmt: skip
        r = await h.post(f"/api/incidents/{inc}/approve", json=body(**bad), headers=PASS)
        assert r.status_code == 422, bad
    legacy = body()
    legacy["safety_steps_ticked"] = legacy.pop("ticked_safety_steps")  # older field name accepted
    assert (await h.post(f"/api/incidents/{inc}/approve", json=legacy, headers=PASS)).status_code == 200  # fmt: skip


async def test_firestore_cmms_decision_is_atomic_and_final(tmp_path):
    from agents.cmms import FirestoreCMMS, WorkOrderAlreadyDecided
    from agents.schemas import WorkOrder

    fs = FakeFirestore()
    wo = WorkOrder.model_validate(next(e for e in sample_events() if e["type"] == "work_order_draft")["data"])  # fmt: skip
    cm = FirestoreCMMS(fs)
    cm.create_draft(wo)
    with pytest.raises(Exception):  # noqa: B017 - create-only
        cm.create_draft(wo)
    assert cm.decide(wo.wo_id, "APPROVED", {"approver_name": "x"}).status == "APPROVED"
    assert fs.docs[f"work_orders/{wo.wo_id}/decisions/final"]["approver_name"] == "x"
    with pytest.raises(WorkOrderAlreadyDecided):
        cm.decide(wo.wo_id, "REJECTED", {})
    assert cm.get(wo.wo_id).status == "APPROVED"
    assert not fs.deletes()


# ---- catalogue, config, CORS ------------------------------------------------------------------
async def test_scenarios_grouped_and_free_of_cause_classes(h):
    r = await h.client.get("/api/scenarios")
    body_ = r.json()
    ids = {g["id"]: [s["id"] for s in g["scenarios"]] for g in body_["groups"]}
    assert ids == {"synthetic": ["S001"], "real_signal": ["R002"]}
    real = body_["groups"][1]["scenarios"][0]
    assert "MetroPT-3" in real["source_label"] and real["replay_run_ids"] == ["r002-sample"]
    low = r.text.lower()
    for c in CauseClass:
        assert c.value not in low, c.value
    assert "SYNTHETIC LINE" in body_["badge"]


@pytest.mark.skipif(not Path("data/andon.duckdb").exists(), reason="local dataset not built")
async def test_scenarios_from_local_db_never_leak_truth(tmp_path):
    from api.stores import LocalDuckDBProvider

    prov = LocalDuckDBProvider(Path("data/andon.duckdb"))
    hn = Harness(tmp_path)
    hn.app.state.ctx.provider = prov
    text = (await hn.client.get("/api/scenarios")).text.lower()
    assert "r017" in text and "s012" in text
    banned = {c.value for c in CauseClass}
    for tf in Path("data/scenarios").glob("*/truth.json"):
        t = json.loads(tf.read_text())
        banned |= {str(v).lower() for k, v in t.items() if "cause" in k or "class" in k or ("fault" in k and isinstance(v, str))}  # fmt: skip
    assert not [b for b in banned if b and b in text], [b for b in banned if b and b in text]
    await hn.close()


async def test_health_config_eval_sources(h):
    hl = (await h.client.get("/health")).json()
    assert hl["status"] == "ok" and hl["contract_version"] and "models" in hl
    assert "git_sha" in hl  # proves which commit is deployed (release check)
    cfg = (await h.client.get("/api/config")).json()
    assert cfg["theme"].startswith("Manufacturing") and cfg["modes"]["live"] is True
    assert cfg["budget"]["remaining_usd"] == 5.0
    assert "passcode" not in json.dumps(cfg).lower().replace("live_requires_passcode", "")
    r = await h.client.get("/api/eval/latest")
    assert r.status_code == 404 and r.json()["detail"]["code"] == "no_eval_results"
    (h.tmp / "latest.json").write_text(json.dumps({"S": {"top1": 0.5}, "R": {"top1": 0.4}}))
    assert (await h.client.get("/api/eval/latest")).json()["R"]["top1"] == 0.4
    src = (await h.client.get("/api/sources")).json()
    ids = {d["id"] for d in src["datasets"]}
    assert {"metropt3", "mimii"} <= ids
    mimii = next(d for d in src["datasets"] if d["id"] == "mimii")
    assert "CC BY-SA" in mimii["licence"] and mimii["citation"]


async def test_cors_allow_list(h):
    ok = await h.client.options(
        "/api/incidents/R002/investigate",
        headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "POST",
                 "Access-Control-Request-Headers": "x-demo-passcode,content-type"},
    )  # fmt: skip
    assert ok.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert "x-demo-passcode" in ok.headers["access-control-allow-headers"].lower()
    bad = await h.client.options(
        "/api/incidents/R002/investigate",
        headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"},
    )
    assert "access-control-allow-origin" not in bad.headers
    r = await h.client.get("/health", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in r.headers
    r = await h.post("/api/incidents/R002/investigate?mode=live", headers={"Origin": "http://localhost:5173"})  # fmt: skip
    assert r.status_code == 401 and r.headers["access-control-allow-origin"] == "http://localhost:5173"  # fmt: skip


def test_wildcard_origin_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="explicit origins"):
        make_settings(tmp_path, allowed_origins=("*",))


async def test_request_size_limit(h):
    r = await h.post("/api/incidents/inc_x/approve", content=b"x" * 70_000,
                     headers={"content-type": "application/json"})  # fmt: skip
    assert r.status_code == 413


def test_no_route_ends_in_z(h_sync=None):
    from api.main import app

    assert not [r.path for r in app.routes if getattr(r, "path", "").rstrip("/").endswith("z")]


# ---- export -----------------------------------------------------------------------------------
async def test_export_a_live_run_as_a_replay_file(h, tmp_path):
    from api.replay import ReplayCatalog, export_run

    live = await h.run(mode="live", headers=PASS)
    await AuditRecorder.drain_all(5)
    out = tmp_path / "out" / "r002-live-9.jsonl"
    info = export_run(h.audit, live[0]["incident_id"], out, label="My label")
    assert info["scenario_id"] == "R002" and info["label"] == "My label"
    cat = ReplayCatalog(out.parent)
    assert [r["run_id"] for r in cat.list()] == ["r002-live-9"]
    raw = cat.load("r002-live-9", "R002")
    assert [parse_event(e).type for e in raw] == [e["type"] for e in live]
    # a replay incident is not exportable
    rep = await h.run(mode="replay")
    with pytest.raises(SystemExit):
        export_run(h.audit, rep[0]["incident_id"], tmp_path / "x.jsonl")


def test_invalid_replay_files_are_skipped(tmp_path):
    from api.replay import ReplayCatalog

    (tmp_path / "bad.jsonl").write_text('{"nope": 1}\n')
    (tmp_path / "trunc.jsonl").write_text(json.dumps(sample_events()[0]) + "\n")
    assert ReplayCatalog(tmp_path).list() == []


def test_timing_helpers():
    from api.replay import gap_schedule

    ev = lambda t: {"ts": f"2026-10-11T09:00:{t:02d}Z"}  # noqa: E731
    assert gap_schedule([ev(0), ev(1), ev(11), ev(11)], 3.0, 2.0) == [0.0, 0.5, 1.5, 0.0]


def test_sources_parser_handles_the_committed_file():
    from api.catalog import parse_sources

    d = parse_sources(Path("data/SOURCES.md").read_text())
    assert len(d["datasets"]) >= 5 and all(x["licence"] for x in d["datasets"])


def test_settings_from_env(tmp_path):
    from api.settings import Settings

    s = Settings.from_env({"STORE_BACKEND": "gcs", "DEMO_PASSCODE": "pw", "DAILY_BUDGET_USD": "1.5",
                           "ALLOWED_ORIGINS": "https://a.web.app, https://b.web.app"})  # fmt: skip
    assert s.firestore and s.live_enabled and s.daily_budget_usd == 1.5
    assert s.allowed_origins == ("https://a.web.app", "https://b.web.app")
    assert s.live_runs_per_day == 30 and s.live_runs_per_min_per_ip == 3 and s.heartbeat_s == 15
    assert "pw" not in repr(s)  # the passcode never reaches a log line
    local = Settings.from_env({"STORE_BACKEND": "duckdb"})
    assert not local.firestore and not local.live_enabled
    assert Settings.from_env({"FIRESTORE": "0", "STORE_BACKEND": "gcs"}).firestore is False
    assert Settings.from_env({"REPLAY_ONLY": "1", "DEMO_PASSCODE": "x"}).live_enabled is False


async def test_disconnect_before_first_byte_never_leaks_a_slot(tmp_path, monkeypatch):
    """Regression: a client that vanishes before the stream starts (page refresh) must not hold a
    concurrency slot."""
    from starlette.responses import StreamingResponse

    hn = Harness(tmp_path, FakeRunner(delay=0.05), max_concurrent_live=1)
    real = StreamingResponse.stream_response

    async def cancelled_before_first_iteration(self, send):
        raise asyncio.CancelledError  # the body generator is never started

    monkeypatch.setattr(StreamingResponse, "stream_response", cancelled_before_first_iteration)
    for _ in range(5):
        s = Stream(hn.app, "/api/incidents/R002/investigate?mode=live", PASS)
        s._sent_body = True  # the request body was read; the next receive is already a disconnect
        s.disconnect()
        s.start()
        with contextlib.suppress(BaseException):
            await s.wait()
    monkeypatch.setattr(StreamingResponse, "stream_response", real)
    assert hn.app.state.ctx.live_slots.active == 0
    r = await hn.post("/api/incidents/R002/investigate?mode=live", headers=PASS)
    assert r.status_code == 200
    await hn.close()


async def test_slot_lease_expires_as_a_backstop(tmp_path):
    hn = Harness(tmp_path, max_concurrent_live=1)
    ctx = hn.app.state.ctx
    ctx.live_slots.lease_s = 0.05
    assert ctx.live_slots.acquire() and not ctx.live_slots.acquire()
    await asyncio.sleep(0.1)
    assert ctx.live_slots.acquire()  # the abandoned lease expired
    await hn.close()


# ---- review fixes: replay limits, safe error text, private live audits ----------------------
async def test_replay_per_ip_limit_is_separate_from_live_quota(tmp_path):
    hn = Harness(tmp_path, replay_runs_per_min_per_ip=2, live_runs_per_day=1)
    await hn.run(mode="replay")
    await hn.run(mode="replay")
    r = await hn.post("/api/incidents/R002/investigate?mode=replay")
    assert r.status_code == 429 and "retry-after" in r.headers
    assert r.json()["detail"]["scope"] == "replay_ip_minute"
    assert len(await hn.run(mode="live", headers=PASS)) > 10  # the live quota was not touched
    await hn.close()


async def test_replay_limit_is_shared_via_firestore_without_a_day_counter(tmp_path):
    fs = FakeFirestore()
    a = Harness(tmp_path / "a", replay_runs_per_min_per_ip=1, firestore_client=fs)
    b = Harness(tmp_path / "b", replay_runs_per_min_per_ip=1, firestore_client=fs)
    assert (await a.post("/api/incidents/R002/investigate?mode=replay")).status_code == 200
    assert (await b.post("/api/incidents/R002/investigate?mode=replay")).status_code == 429
    assert any(k.startswith("ratelimit_replay/") for k in fs.docs)
    assert not any(k.startswith(("ratelimit_day/", "ratelimit_ip/")) for k in fs.docs)
    await a.close()
    await b.close()


async def test_concurrent_replay_cap_and_no_leak(tmp_path, monkeypatch):
    from starlette.responses import StreamingResponse

    hn = Harness(tmp_path, max_concurrent_replay=1)
    gate = asyncio.Event()

    async def slow(_s: float) -> None:
        await gate.wait()

    hn.app.state.ctx.sleep = slow
    s = Stream(hn.app, "/api/incidents/R002/investigate?mode=replay").start()
    await until(lambda: hn.app.state.ctx.replay_slots.active == 1)
    r = await hn.post("/api/incidents/R002/investigate?mode=replay")
    assert r.status_code == 429 and r.json()["detail"]["code"] == "busy"
    s.disconnect()
    await s.wait()
    assert hn.app.state.ctx.replay_slots.active == 0
    # a response that never starts its body still frees the slot
    real = StreamingResponse.stream_response

    async def never(self, send):
        raise asyncio.CancelledError

    monkeypatch.setattr(StreamingResponse, "stream_response", never)
    for _ in range(3):
        t = Stream(hn.app, "/api/incidents/R002/investigate?mode=replay")
        t._sent_body = True
        t.disconnect()
        t.start()
        with contextlib.suppress(BaseException):
            await t.wait()
    monkeypatch.setattr(StreamingResponse, "stream_response", real)
    assert hn.app.state.ctx.replay_slots.active == 0
    await hn.close()


class _ClientError(Exception):
    code = 503

    def __init__(self) -> None:
        super().__init__(
            "503 UNAVAILABLE. projects/andon-agent-511218/locations/global/publishers/google/"
            "models/gemini-3.8-flash: https://aiplatform.googleapis.com/v1/projects/andon-agent-511218"
        )


async def test_exception_text_never_reaches_the_stream_or_audit(tmp_path):
    hn = Harness(tmp_path)

    class Leaky(FakeRunner):
        async def _run(self, sid, inc):
            async for ev in super()._run(sid, inc):
                yield ev
                if self.emitted == 3:
                    raise _ClientError

    hn.app.state.ctx.live_runner = Leaky()
    r = await hn.post("/api/incidents/R002/investigate?mode=live", headers=PASS)
    await AuditRecorder.drain_all(5)
    events = parse_sse(r.text)
    err = events[-2]["data"]
    assert err["code"] == "model_unavailable" and err["retryable"] is True
    for needle in ("andon-agent-511218", "googleapis", "UNAVAILABLE", "publishers/google"):
        assert needle not in r.text
    assert "gemini" not in err["message"]
    steps = json.dumps(hn.audit.get(events[0]["incident_id"])["steps"])
    assert "andon-agent-511218" not in steps
    await hn.close()


def test_every_error_code_has_a_fixed_message():
    from agents.adk_budget import SAFE_MESSAGES, run_error

    assert run_error(TimeoutError("secret-host:443"))["message"] == SAFE_MESSAGES["model_timeout"]
    assert run_error(ValueError("/Users/x/secret"))["message"] == SAFE_MESSAGES["internal"]
    assert "$" in run_error(BudgetExhaustedError("daily budget $5.00 exhausted"))["message"]


async def test_live_audit_is_private_replay_audit_public(h):
    live = await h.run(mode="live", headers=PASS)
    rep = await h.run(mode="replay")
    await AuditRecorder.drain_all(5)
    assert (await h.client.get(f"/api/incidents/{live[0]['incident_id']}/audit")).status_code == 401
    ok = await h.client.get(f"/api/incidents/{rep[0]['incident_id']}/audit")
    assert ok.status_code == 200 and ok.json()["incident"]["mode"] == "replay"


async def test_incident_ids_have_128_bits(h):
    live = await h.run(mode="live", headers=PASS)
    rep = await h.run(mode="replay")
    for ev in (live[0], rep[0]):
        suffix = ev["incident_id"].rsplit("_", 1)[-1]
        assert len(suffix) == 32 and int(suffix, 16) >= 0
