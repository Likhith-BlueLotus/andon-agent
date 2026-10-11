"""Server-Sent Events plumbing: turn any async source of contract events into a robust stream.

Guarantees (ARCHITECTURE §4.2, TECH_STACK "SSE gotchas", RISKS #9):

* every frame is ``encode_sse(event)`` (``id: <seq>``), flushed per event;
* a ``: ping`` comment every ``heartbeat_s`` while the source is quiet (merged via a queue, so a
  slow tool never starves the connection) and one immediately, to open the stream through proxies;
* an exception in the source becomes an ``error`` event, then ``done`` — never a dead stream;
* the stream ends with ``done`` whatever happens, except when the client went away;
* a client disconnect (``request.is_disconnected()`` or the ASGI cancel) cancels the producer task,
  which cancels the ADK run mid-flight so no further model call is made.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from agents.adk_budget import error_data, run_error
from api.audit import AuditRecorder
from api.events import HEARTBEAT, Event, encode_sse, parse_event

log = logging.getLogger("andon.sse")

SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "X-Accel-Buffering": "no",
}
_END = object()


def make_event(
    incident_id: str, seq: int, type_: str, data: dict, agent: str | None = None
) -> Event:
    return parse_event(
        {
            "type": type_,
            "incident_id": incident_id,
            "seq": seq,
            "ts": datetime.now(UTC).isoformat(),
            "agent": agent,
            "data": data,
        }
    )


async def single_error_stream(incident_id: str, code: str, message: str, retryable: bool = False):
    """``error`` then ``done``: how live requests refused after the stream started are answered
    (e.g. ``budget_exhausted``), so the UI can fall back to replay."""
    yield make_event(incident_id, 0, "error", {"code": code, "message": message, "retryable": retryable})  # fmt: skip
    yield make_event(incident_id, 1, "done", {"duration_ms": 0})


async def guarded(
    source: AsyncIterator[Event], incident_id: str, *, timeout_s: float
) -> AsyncIterator[Event]:
    """Make ``source`` contract-complete: errors -> ``error`` event, ``done`` always last, ``seq``
    continues monotonically. Cancellation passes straight through."""
    seq = 0
    t0 = time.perf_counter()
    done = errored = False
    err: dict | None = None
    try:
        async with asyncio.timeout(timeout_s):
            async for ev in source:
                seq = max(seq, ev.seq + 1)
                errored = errored or ev.type == "error"
                yield ev
                if ev.type == "done":
                    done = True
                    break
    except TimeoutError:
        log.error("run %s exceeded %.0f s", incident_id, timeout_s)
        err = error_data("timeout", True)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        err = run_error(exc, incident_id)  # fixed message per code; detail is logged there
    finally:
        with contextlib.suppress(Exception):
            await source.aclose()  # type: ignore[attr-defined]
    if done:
        return
    if err is not None:
        yield make_event(incident_id, seq, "error", err)
        seq += 1
    elif not errored:
        log.error("run %s ended without done or error", incident_id)
        yield make_event(incident_id, seq, "error", error_data("internal", False))
        seq += 1
    yield make_event(incident_id, seq, "done", {"duration_ms": int((time.perf_counter() - t0) * 1000)})  # fmt: skip


async def _pump(events: AsyncIterator[Event], q: asyncio.Queue) -> None:
    try:
        async for ev in events:
            q.put_nowait(ev)
    except asyncio.CancelledError:
        raise
    except Exception:  # guarded() already converts; belt and braces
        log.exception("pump failed")
    finally:
        q.put_nowait(_END)


def status_of(error: Event | None, last_type: str | None) -> str:
    """Audit summary status: ``completed`` | ``error`` | ``timeout`` | ``cancelled``."""
    if error is not None:
        return "timeout" if error.data.code == "timeout" else "error"
    return "completed" if last_type == "done" else "cancelled"


async def sse_frames(
    request: Any,
    events: AsyncIterator[Event],
    *,
    heartbeat_s: float,
    recorder: AuditRecorder | None = None,
    before_emit: Callable[[Event], Awaitable[None]] | None = None,
    on_close: Callable[[], None] | None = None,
) -> AsyncIterator[str]:
    """The response body generator. See module docstring for the guarantees."""
    t0 = time.perf_counter()
    q: asyncio.Queue = asyncio.Queue()
    error_ev: Event | None = None
    last_type: str | None = None
    pump: asyncio.Task | None = None
    try:
        if recorder is not None:
            recorder.start()
        pump = asyncio.get_running_loop().create_task(_pump(events, q))
        yield HEARTBEAT  # opens the stream through buffering proxies right away
        while True:
            try:
                item = await asyncio.wait_for(q.get(), timeout=heartbeat_s)
            except TimeoutError:
                if await request.is_disconnected():
                    return
                yield HEARTBEAT
                continue
            if item is _END:
                break
            if before_emit is not None:
                try:
                    await before_emit(item)
                except Exception:
                    log.exception("before_emit hook failed for %s", item.type)
            last_type = item.type
            if item.type == "error" and error_ev is None:
                error_ev = item
            if recorder is not None:
                recorder.record(item)
            yield encode_sse(item)
        # normal end: persist the summary before the response closes
        if recorder is not None:
            recorder.finish(status_of(error_ev, last_type), int((time.perf_counter() - t0) * 1000))
            with contextlib.suppress(Exception):
                await recorder.wait(5.0)
    finally:
        if pump is not None and not pump.done():
            pump.cancel()  # cancels the ADK run; do not await (we may be inside a cancel scope)
        if recorder is not None:
            recorder.finish("cancelled", int((time.perf_counter() - t0) * 1000))  # no-op if done
        if on_close is not None:
            on_close()
