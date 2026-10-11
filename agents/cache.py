"""Explicit Gemini context cache of the five equipment manuals (ADR-004, TECH_STACK cache row).

One cache per (model, manuals content, system instruction). Its ``display_name`` carries a content
hash, so an edited manual never reuses a stale cache:

* :meth:`ManualsCache.ensure` lists caches and reuses a live one with the same display name and
  model (extending its TTL when little life is left) before creating a new one;
* :meth:`ManualsCache.session` is the per-diagnosis scope: it refcounts the cache within this
  process and deletes it when the last session using it ends (TTL bounds the cost otherwise);
* :meth:`ManualsCache.gc_stale` deletes caches with our prefix whose hash is not current
  (``--all``: every one of ours) — ``uv run python -m agents.cache --gc``.

Creation is booked through :meth:`agents.llm.LLM.record` as two ledger rows: the cached tokens at
the model's input rate (``cache_create``) and a storage estimate for the TTL
(``cache_storage_estimate``, from ``config.CACHE_STORAGE_USD_PER_MTOK_HOUR``). A request that uses
the cache reports ``cached_content_token_count``; :func:`cache_hit_data` turns that into the
``cache_hit`` SSE payload with ``saved_usd`` from ``config.PRICES``.

Gemini rule (checked live 2026-10-11, see LESSONS_LEARNED): a request that sets ``cached_content``
must not also set ``system_instruction``, ``tools`` or ``tool_config`` — those belong in the cache.
So the cache is used by direct ``LLM.generate`` calls (``cite_manual``), not by tool-using ADK
agents.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import config
from agents.llm import LLM, Usage, cache_savings_usd, get_llm
from simulator.manuals import DOCS, full_text

log = logging.getLogger("andon.cache")

# Bump when the corpus layout below changes, so old caches are not reused.
CORPUS_FORMAT = "v1"


def manuals_corpus() -> str:
    """The text that goes into the cache: all five manuals, page markers kept for citations."""
    return "\n\n".join(f"=== MANUAL: {d} ===\n{full_text(d)}" for d in DOCS)


def content_hash(corpus: str, system_instruction: str | None = None) -> str:
    h = hashlib.sha256()
    for piece in (CORPUS_FORMAT, system_instruction or "", corpus):
        h.update(piece.encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()[:16]


def display_name_for(digest: str) -> str:
    return f"{config.MANUALS_CACHE_PREFIX}{digest}"


def storage_usd(model_id: str, tokens: int, ttl_s: float) -> float:
    """Upper-bound storage estimate for ``tokens`` cached for ``ttl_s`` seconds."""
    rates = config.CACHE_STORAGE_USD_PER_MTOK_HOUR
    rate = rates.get(model_id, max(rates.values()))  # unknown model: assume the dearest rate
    return tokens * rate * (ttl_s / 3600) / 1_000_000


def cache_hit_data(cache_name: str, model_id: str, usage: Usage) -> dict | None:
    """``CacheHitData`` fields for a call that used the cache, or None if nothing was cached."""
    if usage.cached_tokens <= 0:
        return None
    return {
        "cache_name": cache_name,
        "cached_tokens": usage.cached_tokens,
        "saved_usd": round(cache_savings_usd(model_id, usage.input_tokens, usage.cached_tokens), 6),
    }


@dataclass(frozen=True)
class CacheHandle:
    name: str  # projects/../cachedContents/<id>; pass as GenerateContentConfig.cached_content
    model_id: str
    display_name: str
    token_count: int
    expire_time: datetime | None
    created: bool  # False = reused an existing cache


def _model_of(cache: Any) -> str:
    return (getattr(cache, "model", None) or "").rsplit("/", 1)[-1]


def _aware(ts: datetime | None) -> datetime | None:
    if ts is None:
        return None
    return ts if ts.tzinfo else ts.replace(tzinfo=UTC)


class ManualsCache:
    """Create / reuse / release / GC the manuals cache. One instance per process is enough."""

    def __init__(
        self,
        llm: LLM | None = None,
        *,
        client: Any = None,
        ttl_s: int = config.MANUALS_CACHE_TTL_S,
        min_remaining_s: int = config.MANUALS_CACHE_MIN_REMAINING_S,
        corpus: str | None = None,
        clock: Any = None,
    ) -> None:
        self.llm = llm or get_llm()
        self._client = client  # tests inject a fake; otherwise llm.client(location)
        self.ttl_s = ttl_s
        # A fresh short-TTL cache (tests: 120 s) must not count as "nearly expired" on reuse.
        self.min_remaining_s = min(min_remaining_s, ttl_s // 2)
        self._corpus = corpus
        self._clock = clock or (lambda: datetime.now(UTC))
        self._refs: dict[str, int] = {}
        self._lock = asyncio.Lock()

    # ---- plumbing ------------------------------------------------------------------------
    def client(self, model_id: str) -> Any:
        return self._client or self.llm.client(config.location_for(model_id))

    @property
    def corpus(self) -> str:
        return self._corpus if self._corpus is not None else manuals_corpus()

    def display_name(self, system_instruction: str | None = None) -> str:
        return display_name_for(content_hash(self.corpus, system_instruction))

    async def _list(self, model_id: str) -> list[Any]:
        pager = await self.client(model_id).aio.caches.list()
        return [c async for c in pager]

    # ---- public API ----------------------------------------------------------------------
    async def find(self, model_id: str, system_instruction: str | None = None) -> Any | None:
        """A live cache for this model and content, or None."""
        want = self.display_name(system_instruction)
        now = self._clock()
        for c in await self._list(model_id):
            exp = _aware(getattr(c, "expire_time", None))
            if c.display_name == want and _model_of(c) == model_id and (exp is None or exp > now):
                return c
        return None

    async def ensure(
        self,
        model_id: str,
        *,
        system_instruction: str | None = None,
        run_id: str | None = None,
        agent: str = "manuals_cache",
    ) -> CacheHandle:
        """Reuse a live cache (extending its TTL if nearly expired) or create one."""
        if model_id not in config.PINNED_MODELS:
            from agents.llm import UnpinnedModelError

            raise UnpinnedModelError(f"{model_id!r} is not a pinned model (see config.py)")
        from google.genai import types

        client = self.client(model_id)
        hit = await self.find(model_id, system_instruction)
        if hit is not None:
            exp = _aware(hit.expire_time)
            if exp is not None and exp - self._clock() < timedelta(seconds=self.min_remaining_s):
                hit = await client.aio.caches.update(
                    name=hit.name, config=types.UpdateCachedContentConfig(ttl=f"{self.ttl_s}s")
                )
                tokens = int(getattr(hit.usage_metadata, "total_token_count", 0) or 0)
                self.llm.record(
                    None,
                    model_id=model_id,
                    agent=agent,
                    run_id=run_id,
                    event="cache_storage_estimate",
                    usd=storage_usd(model_id, tokens, self.ttl_s),
                )
            log.info("manuals cache reused %s", hit.name)
            return self._handle(hit, model_id, created=False)

        self.llm.spend.check()
        cache = await client.aio.caches.create(
            model=model_id,
            config=types.CreateCachedContentConfig(
                display_name=self.display_name(system_instruction),
                contents=[types.Content(role="user", parts=[types.Part(text=self.corpus)])],
                system_instruction=system_instruction,
                ttl=f"{self.ttl_s}s",
            ),
        )
        handle = self._handle(cache, model_id, created=True)
        # Creation bills the cached tokens once at the input rate; storage accrues per hour.
        self.llm.record(
            Usage(model_id, input_tokens=handle.token_count),
            agent=agent,
            run_id=run_id,
            event="cache_create",
        )
        self.llm.record(
            None,
            model_id=model_id,
            agent=agent,
            run_id=run_id,
            event="cache_storage_estimate",
            usd=storage_usd(model_id, handle.token_count, self.ttl_s),
        )
        log.info("manuals cache created %s (%d tokens)", cache.name, handle.token_count)
        return handle

    def _handle(self, cache: Any, model_id: str, *, created: bool) -> CacheHandle:
        return CacheHandle(
            name=cache.name,
            model_id=model_id,
            display_name=cache.display_name,
            token_count=int(getattr(cache.usage_metadata, "total_token_count", 0) or 0),
            expire_time=_aware(getattr(cache, "expire_time", None)),
            created=created,
        )

    async def delete(self, name: str, model_id: str = config.FLASH) -> bool:
        """Delete one cache. A cache that is already gone counts as deleted."""
        try:
            await self.client(model_id).aio.caches.delete(name=name)
        except Exception as exc:  # 404 = expired or deleted elsewhere
            if getattr(exc, "code", None) == 404:
                return True
            raise
        log.info("manuals cache deleted %s", name)
        return True

    @asynccontextmanager
    async def session(
        self,
        model_id: str,
        *,
        system_instruction: str | None = None,
        run_id: str | None = None,
    ) -> AsyncIterator[CacheHandle]:
        """Scope one diagnosis: ensure on entry, delete on exit when no other session uses it."""
        async with self._lock:
            handle = await self.ensure(
                model_id, system_instruction=system_instruction, run_id=run_id
            )
            self._refs[handle.name] = self._refs.get(handle.name, 0) + 1
        try:
            yield handle
        finally:
            async with self._lock:
                left = self._refs[handle.name] = self._refs[handle.name] - 1
                if left <= 0:
                    del self._refs[handle.name]
                    try:
                        await self.delete(handle.name, model_id)
                    except Exception:  # never mask the diagnosis' own outcome; TTL cleans up
                        log.exception("could not delete manuals cache %s", handle.name)

    async def gc_stale(self, model_id: str = config.FLASH, *, all_ours: bool = False) -> list[str]:
        """Delete our caches whose content hash is not current (or all of ours). Returns names."""
        current = self.display_name()
        deleted = []
        for c in await self._list(model_id):
            dn = c.display_name or ""
            if not dn.startswith(config.MANUALS_CACHE_PREFIX) or c.name in self._refs:
                continue
            if all_ours or dn != current:
                await self.delete(c.name, model_id)
                deleted.append(c.name)
        return deleted


# --- CLI -------------------------------------------------------------------------------------
def _gcloud_credentials() -> Any:
    import subprocess

    from google.oauth2.credentials import Credentials

    token = subprocess.run(
        ["gcloud", "auth", "print-access-token"], check=True, capture_output=True, text=True
    ).stdout.strip()
    return Credentials(token=token)


async def _main(args: argparse.Namespace) -> None:
    llm = get_llm()
    if args.gcloud_token:
        llm.credentials = _gcloud_credentials()
    mc = ManualsCache(llm)
    if args.list:
        for c in await mc._list(args.model):
            print(f"{c.name}  {c.display_name}  {_model_of(c)}  expires {c.expire_time}")
    if args.gc:
        gone = await mc.gc_stale(args.model, all_ours=args.all)
        print(f"deleted {len(gone)} cache(s)" + "".join(f"\n  {n}" for n in gone))


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="python -m agents.cache", description=__doc__.split("\n")[0])
    p.add_argument("--gc", action="store_true", help="delete our caches with a stale hash")
    p.add_argument("--all", action="store_true", help="with --gc: delete every cache of ours")
    p.add_argument("--list", action="store_true", help="list caches in the model's location")
    p.add_argument("--model", default=config.FLASH, choices=sorted(config.PINNED_MODELS))
    p.add_argument(
        "--gcloud-token", action="store_true", help="use the gcloud login instead of ADC"
    )
    args = p.parse_args(argv)
    if not (args.gc or args.list):
        p.error("nothing to do: pass --gc and/or --list")
    logging.basicConfig(level=logging.INFO)
    asyncio.run(_main(args))  # one loop for the whole command (genai aio client binds to it)


if __name__ == "__main__":
    main()
