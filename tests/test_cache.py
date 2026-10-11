"""Tests for agents/cache.py: the explicit context cache of the five manuals.

Offline tests use a fake ``client.aio.caches``. One live test (``-m live``, ~$0.04) creates a real
cache with a 120 s TTL, reuses it, uses it once and deletes it.
"""

from __future__ import annotations

import itertools
import os
import subprocess
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

import config
from agents.cache import (
    ManualsCache,
    cache_hit_data,
    content_hash,
    display_name_for,
    manuals_corpus,
    storage_usd,
)
from agents.llm import LLM, BudgetExhaustedError, SpendTracker, UnpinnedModelError, Usage

NOW = datetime(2026, 10, 11, 12, 0, tzinfo=UTC)
CORPUS = "=== MANUAL: weld_controller ===\n<!-- page 1 -->\nTest corpus."


class NotFound(Exception):
    code = 404


class FakePager:
    def __init__(self, items):
        self._items = list(items)

    def __aiter__(self):
        self._it = iter(self._items)
        return self

    async def __anext__(self):
        try:
            return next(self._it)
        except StopIteration:
            raise StopAsyncIteration from None


class FakeCaches:
    """In-memory stand-in for ``client.aio.caches`` (create/list/update/delete)."""

    def __init__(self, tokens=50_135):
        self.store: dict[str, SimpleNamespace] = {}
        self.calls: list[str] = []
        self.tokens = tokens
        self._ids = itertools.count(1)

    def _ttl(self, ttl):
        return NOW + timedelta(seconds=int(ttl.rstrip("s")))

    async def create(self, *, model, config):
        self.calls.append("create")
        name = f"projects/p/locations/global/cachedContents/{next(self._ids)}"
        c = SimpleNamespace(
            name=name,
            display_name=config.display_name,
            model=f"projects/p/locations/global/publishers/google/models/{model}",
            expire_time=self._ttl(config.ttl),
            usage_metadata=SimpleNamespace(total_token_count=self.tokens),
            system_instruction=config.system_instruction,
        )
        self.store[name] = c
        return c

    async def list(self, config=None):
        self.calls.append("list")
        return FakePager(self.store.values())

    async def update(self, *, name, config):
        self.calls.append("update")
        self.store[name].expire_time = self._ttl(config.ttl)
        return self.store[name]

    async def delete(self, *, name, config=None):
        self.calls.append("delete")
        if name not in self.store:
            raise NotFound(name)
        del self.store[name]


@pytest.fixture
def fake():
    return FakeCaches()


@pytest.fixture
def llm():
    return LLM(spend=SpendTracker(daily_budget_usd=5.0))


def make(fake, llm, **kw):
    client = SimpleNamespace(aio=SimpleNamespace(caches=fake))
    return ManualsCache(llm, client=client, corpus=CORPUS, clock=lambda: NOW, **kw)


# --- naming ----------------------------------------------------------------------------------
def test_display_name_tracks_content_and_instruction():
    a = content_hash(CORPUS)
    assert a == content_hash(CORPUS) and len(a) == 16
    assert a != content_hash(CORPUS + " ")  # any edit -> new cache
    assert a != content_hash(CORPUS, "Answer only from the manuals.")
    assert display_name_for(a).startswith(config.MANUALS_CACHE_PREFIX)
    assert len(display_name_for(a)) <= 128


def test_real_corpus_has_all_five_manuals_with_page_markers():
    corpus = manuals_corpus()
    for doc in ("weld_controller", "sealer_pump", "conveyor_drive", "press_hydraulics"):
        assert f"=== MANUAL: {doc} ===" in corpus
    assert "=== MANUAL: compressed_air ===" in corpus and "<!-- page 1 -->" in corpus


# --- create / reuse / extend -----------------------------------------------------------------
async def test_creates_then_reuses(fake, llm):
    mc = make(fake, llm)
    h1 = await mc.ensure(config.FLASH, run_id="r")
    h2 = await mc.ensure(config.FLASH, run_id="r")
    assert h1.created and not h2.created and h1.name == h2.name
    assert fake.calls == ["list", "create", "list"]
    assert h1.token_count == 50_135 and h1.display_name == mc.display_name()


async def test_creation_cost_and_storage_are_booked(fake, llm):
    mc = make(fake, llm, ttl_s=3600)
    await mc.ensure(config.FLASH, run_id="r")
    events = [(r["event"], r["usd"]) for r in llm.ledger]
    p = config.PRICES[config.FLASH]
    create_usd = 50_135 * p.input / 1e6
    store_usd = 50_135 * config.CACHE_STORAGE_USD_PER_MTOK_HOUR[config.FLASH] / 1e6
    assert events == [
        ("cache_create", pytest.approx(create_usd, abs=1e-6)),
        ("cache_storage_estimate", pytest.approx(store_usd, abs=1e-6)),
    ]
    assert llm.spend.spent_today() == pytest.approx(create_usd + store_usd, abs=1e-6)
    m = llm.run_cost("r").by_model[config.FLASH]
    assert m.calls == 0 and m.usd == pytest.approx(create_usd + store_usd, abs=1e-6)


async def test_other_model_or_content_is_not_reused(fake, llm):
    await make(fake, llm).ensure(config.FLASH)
    h = await make(fake, llm).ensure(config.FLASH_LITE)
    assert h.created
    other = ManualsCache(
        llm, client=SimpleNamespace(aio=SimpleNamespace(caches=fake)), corpus=CORPUS + "!"
    )
    other._clock = lambda: NOW
    assert (await other.ensure(config.FLASH)).created
    assert len(fake.store) == 3


async def test_expired_cache_is_not_reused(fake, llm):
    mc = make(fake, llm)
    h1 = await mc.ensure(config.FLASH)
    fake.store[h1.name].expire_time = NOW - timedelta(seconds=1)
    assert (await mc.ensure(config.FLASH)).created


async def test_nearly_expired_cache_gets_ttl_extended(fake, llm):
    mc = make(fake, llm, ttl_s=600)
    h1 = await mc.ensure(config.FLASH)
    fake.store[h1.name].expire_time = NOW + timedelta(seconds=30)
    h2 = await mc.ensure(config.FLASH)
    assert not h2.created and "update" in fake.calls
    assert h2.expire_time == NOW + timedelta(seconds=600)
    assert llm.ledger[-1]["event"] == "cache_storage_estimate"


async def test_guards(fake):
    mc = make(fake, LLM(spend=SpendTracker(daily_budget_usd=0.0)))
    with pytest.raises(UnpinnedModelError):
        await mc.ensure("gemini-2.5-flash")
    with pytest.raises(BudgetExhaustedError):
        await mc.ensure(config.FLASH)
    assert "create" not in fake.calls


# --- session scope, delete, GC ---------------------------------------------------------------
async def test_session_deletes_when_last_user_leaves(fake, llm):
    mc = make(fake, llm)
    async with mc.session(config.FLASH) as a:
        async with mc.session(config.FLASH) as b:
            assert a.name == b.name
        assert a.name in fake.store  # still in use by the outer session
    assert fake.store == {}


async def test_session_deletes_even_when_the_run_fails(fake, llm):
    mc = make(fake, llm)
    with pytest.raises(RuntimeError):
        async with mc.session(config.FLASH):
            raise RuntimeError("diagnosis failed")
    assert fake.store == {}


async def test_delete_of_missing_cache_is_ok(fake, llm):
    assert await make(fake, llm).delete("projects/p/locations/global/cachedContents/404")


async def test_gc_deletes_only_our_stale_caches(fake, llm):
    mc = make(fake, llm)
    current = await mc.ensure(config.FLASH)
    stale = await fake.create(
        model=config.FLASH,
        config=SimpleNamespace(
            display_name=display_name_for("0" * 16), ttl="600s", system_instruction=None
        ),
    )
    foreign = await fake.create(
        model=config.FLASH,
        config=SimpleNamespace(display_name="someone-else", ttl="600s", system_instruction=None),
    )
    assert await mc.gc_stale(config.FLASH) == [stale.name]
    assert set(fake.store) == {current.name, foreign.name}
    assert await mc.gc_stale(config.FLASH, all_ours=True) == [current.name]
    assert set(fake.store) == {foreign.name}


async def test_gc_spares_caches_in_use(fake, llm):
    mc = make(fake, llm)
    async with mc.session(config.FLASH) as h:
        assert await mc.gc_stale(config.FLASH, all_ours=True) == []
        assert h.name in fake.store


def test_cli_requires_an_action():
    from agents.cache import main

    with pytest.raises(SystemExit):
        main([])


# --- cache_hit payload -----------------------------------------------------------------------
def test_cache_hit_data_and_storage_estimate():
    u = Usage(config.FLASH, input_tokens=50_162, output_tokens=10, cached_tokens=50_142)
    d = cache_hit_data("projects/p/locations/global/cachedContents/1", config.FLASH, u)
    p = config.PRICES[config.FLASH]
    assert d["cached_tokens"] == 50_142
    assert d["saved_usd"] == pytest.approx(50_142 * (p.input - p.cached_input) / 1e6, abs=1e-6)
    assert cache_hit_data("x", config.FLASH, Usage(config.FLASH, input_tokens=10)) is None
    assert storage_usd(config.FLASH, 1_000_000, 1800) == pytest.approx(0.25)
    # residency model has no published storage rate -> the dearest known rate (upper bound)
    dearest = max(config.CACHE_STORAGE_USD_PER_MTOK_HOUR.values())
    assert storage_usd(config.RESIDENCY_FLASH, 1_000_000, 3600) == pytest.approx(dearest)


# --- live (costs ~$0.04) ---------------------------------------------------------------------
def _live_llm() -> LLM:
    """ADC by default; ANDON_GCLOUD_TOKEN=1 uses the active gcloud login instead."""
    creds = None
    if os.environ.get("ANDON_GCLOUD_TOKEN") == "1":
        from google.oauth2.credentials import Credentials

        token = subprocess.run(
            ["gcloud", "auth", "print-access-token"], check=True, capture_output=True, text=True
        ).stdout.strip()
        creds = Credentials(token=token)
    return LLM(spend=SpendTracker(daily_budget_usd=0.50), credentials=creds, max_retries=1)


@pytest.mark.live
async def test_live_create_reuse_use_delete():
    from google.genai import types

    if not config.PROJECT:
        pytest.skip("GOOGLE_CLOUD_PROJECT not set")
    llm = _live_llm()
    mc = ManualsCache(llm, ttl_s=120)
    model = config.FLASH
    async with mc.session(model, run_id="live-cache") as h:
        assert h.created and h.token_count > 6_144  # 3.8 Flash explicit-cache minimum
        again = await mc.ensure(model, run_id="live-cache")
        assert not again.created and again.name == h.name
        res = await llm.generate(
            model,
            "In which manual is the compressed-air energy source table? Answer with the doc id.",
            types.GenerateContentConfig(
                cached_content=h.name,
                thinking_config=types.ThinkingConfig(thinking_level=types.ThinkingLevel.LOW),
                max_output_tokens=64,
            ),
            agent="test_cache_live",
            run_id="live-cache",
        )
        hit = cache_hit_data(h.name, model, res.usage)
        assert hit is not None and hit["cached_tokens"] >= h.token_count - 50
        assert hit["saved_usd"] > 0
        name = h.name
    assert name not in [c.name for c in await mc._list(model)]
    rc = llm.run_cost("live-cache")
    print(
        f"\nlive cache: {h.token_count} tokens, hit {hit}, run usd {rc.usd:.4f}, "
        f"ledger {[(r['event'], r['usd']) for r in llm.ledger]}"
    )
