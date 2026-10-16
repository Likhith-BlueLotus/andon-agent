"""``listen``: Gemini listens to a machine clip; a classical MFCC baseline gives the Verifier a number.

    listen(asset_id, t0, t1) -> {evidence_id, summary, provenance}

Follows the tool contract in :mod:`agents.tools` (registered there in ``TOOL_REGISTRY``, so
``rerun`` and ``bind_tools`` pick it up). Steps:

1. **Find the clip.** The agent-visible clip index for ``ctx.scenario_id`` lists ts, asset,
   machine type/id, ``gs://`` URI and local file. It carries no normal/abnormal label, and this
   module copies only those whitelisted fields, so a label could not leak even if one were added
   upstream. The index comes from an injected resolver (:func:`set_index_resolver`), else
   ``data/scenarios/<id>/audio_index.json``, else ``gs://<bucket>/audio/<id>/audio_index.json``.
   The latest clip of the asset that starts in ``[t0, t1)`` is analysed.
2. **Reference set (an assumption, stated in every summary).** Clips of the same asset *and*
   machine id that end before ``t0`` are *presumed normal*: the incident window is where the agent
   suspects trouble, and history before it is the baseline. If there are none, clips that end at
   least 1 h before the queried clip are used instead (``reference_rule`` says which).
   Nothing checks that the references really are normal; a fault older than the window would
   shrink the distance.
3. **MFCC baseline** (:mod:`analytics.audio`): ``mfcc_distance`` (about 1.0 = like the
   references) and ``mfcc_z`` against the references' leave-one-out spread. Recomputed on every
   call, so it is deterministic.
4. **Gemini** (``config.FLASH``, thinking LOW, through :meth:`agents.llm.LLM.generate`): the
   fixed rubric ``agents/prompts/listen_rubric.md`` plus the newest reference clip and the queried
   clip as ``gs://`` parts. The output is structured ``{finding, abnormal, confidence,
   characteristics, recording_quality}``. The audio is untrusted content. Results are cached on
   disk by (query clip SHA-256, reference clip SHA-256, machine type, prompt version, model) under
   ``data/cache/listen/``, so reruns and the Verifier are free and reproduce the summary exactly.
   The MFCC number is never shown to Gemini, so the two opinions stay independent.

If Gemini fails (budget kill switch, outage, more than ``TOTAL_TIMEOUT_S``), the tool still
returns the MFCC part with ``gemini_status`` = ``unavailable`` / ``timeout`` / ``unparseable`` and
writes no cache entry. Gemini's verdict on the same clip is not stable across calls (seen live),
which is one more reason the first answer is cached and reused.

This module never reads ground truth; tests/test_guards.py and tests/test_tools.py enforce it.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import threading
from collections import OrderedDict
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, ValidationError

import config
from agents import prompts
from agents.schemas import ProvenanceRef
from analytics import audio as audio_mod
from analytics.series import iso, rnd, sig

if TYPE_CHECKING:
    from agents.tools import ToolContext

log = logging.getLogger("andon.listen")

ROOT = Path(__file__).resolve().parents[1]
SCENARIOS_DIR = ROOT / "data" / "scenarios"
CACHE_DIR = ROOT / "data" / "cache" / "listen"
INDEX_NAME = "audio_index.json"
BUCKET = config.GCS_BUCKET or "andon-511816-assets"
MODEL = config.FLASH
THINKING_LEVEL = "LOW"
PROMPT_NAME = "listen_rubric"
AGENT_NAME = "signal_analyst.listen"
CLIP_S_DEFAULT = 10
ATTEMPT_TIMEOUT_S = 25.0  # per Gemini attempt (a 2-clip call normally takes 4-5 s)
TOTAL_TIMEOUT_S = 45.0  # wall clock incl. retries; then the MFCC part is returned alone
FALLBACK_REF_GAP_S = 3600  # fallback references end at least this long before the queried clip
MAX_FINDING_CHARS = 300
MAX_CHARACTERISTICS = 8
INDEX_FIELDS = ("ts", "asset_id", "machine_type", "machine_id", "gs_uri", "local_file")
REFERENCE_ASSUMPTION = (
    "reference clips are earlier recordings of the same machine, presumed normal (not verified)"
)
_RESOLVER_KEY = "listen.index_resolver"
_INDEX_KEY = "listen.index"

IndexResolver = Callable[[str], dict | None]


# --- Structured output ------------------------------------------------------------------------
class GeminiFinding(BaseModel):
    """The response_schema sent to Gemini (no length constraints: we clamp after parsing)."""

    finding: str
    abnormal: bool
    confidence: float
    characteristics: list[str]
    recording_quality: Literal["clear", "noisy_but_audible", "masked"]


def _clamp(f: GeminiFinding) -> dict[str, Any]:
    text = " ".join(f.finding.split())
    if len(text) > MAX_FINDING_CHARS:
        text = text[: MAX_FINDING_CHARS - 3].rstrip() + "..."
    chars = [" ".join(c.split())[:80] for c in f.characteristics if c and c.strip()]
    return {
        "finding": text,
        "abnormal": bool(f.abnormal),
        "confidence": rnd(min(1.0, max(0.0, float(f.confidence))), 3),
        "characteristics": chars[:MAX_CHARACTERISTICS],
        "recording_quality": f.recording_quality,
    }


# --- Clip index -------------------------------------------------------------------------------
def set_index_resolver(ctx: ToolContext, resolver: IndexResolver) -> None:
    """Inject how the clip index is found (``scenario_id -> index dict | None``). Stored in the
    context's shared cache, so sibling contexts (``ctx.with_state``) see it too."""
    with ctx._lock:
        ctx._cache[_RESOLVER_KEY] = resolver
        ctx._cache.pop(_INDEX_KEY, None)


def _default_index(ctx: ToolContext) -> dict | None:
    local = SCENARIOS_DIR / ctx.scenario_id / INDEX_NAME
    if local.exists():
        return json.loads(local.read_text())
    uri = f"gs://{BUCKET}/audio/{ctx.scenario_id}/{INDEX_NAME}"
    try:
        return json.loads(ctx.blob_reader().read_bytes(uri))
    except Exception as exc:  # absent or unreachable: the caller reports a structured error
        log.info("no clip index at %s (%s)", uri, type(exc).__name__)
        return None


def _index(ctx: ToolContext) -> dict:
    from agents.tools import ToolArgError

    with ctx._lock:
        if _INDEX_KEY in ctx._cache:
            return ctx._cache[_INDEX_KEY]
        resolver = ctx._cache.get(_RESOLVER_KEY)
    raw = resolver(ctx.scenario_id) if resolver is not None else _default_index(ctx)
    if not raw:
        raise ToolArgError(
            "audio_unavailable", "no audio recordings are available for this incident"
        )
    if raw.get("scenario_id") not in (None, ctx.scenario_id):
        raise ToolArgError("audio_unavailable", "audio index belongs to another incident")
    clips = []
    for c in raw.get("clips") or []:
        clip = {k: c.get(k) for k in INDEX_FIELDS}  # whitelist: nothing else is ever read
        uri = str(clip.get("gs_uri") or "")
        if not uri.startswith("gs://") or f"/audio/{ctx.scenario_id}/" not in uri:
            continue
        clip["_t"] = _epoch_iso(str(clip["ts"]))
        clips.append(clip)
    idx = {
        "clip_duration_s": int(raw.get("clip_duration_s") or CLIP_S_DEFAULT),
        "sample_rate_hz": int(raw.get("sample_rate_hz") or audio_mod.SAMPLE_RATE_HZ),
        "clips": sorted(clips, key=lambda c: (c["_t"], c["asset_id"])),
    }
    with ctx._lock:
        ctx._cache[_INDEX_KEY] = idx
    return idx


def _epoch_iso(s: str) -> int:
    return int(datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(UTC).timestamp())


# --- Clip bytes and features -----------------------------------------------------------------
_FEATURES: OrderedDict[str, audio_mod.ClipFeatures] = OrderedDict()
_FEATURES_LOCK = threading.Lock()
_FEATURES_MAX = 256


def _clip_bytes(ctx: ToolContext, clip: dict) -> bytes:
    lf = clip.get("local_file")
    if lf:
        p = Path(lf)
        p = (ROOT / p).resolve() if not p.is_absolute() else p.resolve()
        if p.is_relative_to(ROOT / "data") and p.suffix == ".wav" and p.exists():
            return p.read_bytes()
    return ctx.blob_reader().read_bytes(clip["gs_uri"])


def _features(data: bytes) -> tuple[str, audio_mod.ClipFeatures]:
    sha = hashlib.sha256(data).hexdigest()
    with _FEATURES_LOCK:
        hit = _FEATURES.get(sha)
        if hit is not None:
            _FEATURES.move_to_end(sha)
            return sha, hit
    f = audio_mod.features_from_wav(data)
    with _FEATURES_LOCK:
        _FEATURES[sha] = f
        while len(_FEATURES) > _FEATURES_MAX:
            _FEATURES.popitem(last=False)
    return sha, f


# --- Gemini (cached) --------------------------------------------------------------------------
def cache_key(
    query_sha: str, ref_sha: str | None, machine_type: str, version: str, model: str
) -> str:
    raw = "|".join([query_sha, ref_sha or "-", machine_type, version, model])
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def _build_request(
    asset_id: str, machine_type: str, query: dict, ref: dict | None, rubric: str
) -> tuple[Any, Any]:
    from google.genai import types

    context = (
        f"\n\nContext: asset {asset_id}, machine type {machine_type}. "
        f"QUERY recorded at {query['ts']}."
        + (f" REFERENCE recorded at {ref['ts']}." if ref else " No REFERENCE is available.")
    )
    parts = [types.Part.from_text(text=rubric + context)]
    if ref is not None:
        parts += [
            types.Part.from_text(text="REFERENCE recording:"),
            types.Part.from_uri(file_uri=ref["gs_uri"], mime_type="audio/wav"),
        ]
    parts += [
        types.Part.from_text(text="QUERY recording:"),
        types.Part.from_uri(file_uri=query["gs_uri"], mime_type="audio/wav"),
    ]
    contents = [types.Content(role="user", parts=parts)]
    cfg = types.GenerateContentConfig(
        response_mime_type="application/json",
        response_schema=GeminiFinding,
        thinking_config=types.ThinkingConfig(thinking_level=types.ThinkingLevel(THINKING_LEVEL)),
    )
    return contents, cfg


def _parse(response: Any) -> GeminiFinding:
    parsed = getattr(response, "parsed", None)
    if isinstance(parsed, GeminiFinding):
        return parsed
    if isinstance(parsed, dict):
        return GeminiFinding.model_validate(parsed)
    return GeminiFinding.model_validate_json(getattr(response, "text", None) or "")


_POOL = ThreadPoolExecutor(max_workers=4, thread_name_prefix="listen-llm")


def _run_sync(factory: Callable[[], Any]) -> Any:
    """Run a coroutine from sync tool code. ADK calls sync tools on its event loop thread, so
    there the call goes to a worker thread with its own loop (LLM.client is per loop)."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(factory())
    return _POOL.submit(lambda: asyncio.run(factory())).result()


def _gemini(
    ctx: ToolContext, asset_id: str, machine_type: str, query: dict, q_sha: str,
    ref: dict | None, r_sha: str | None,
) -> tuple[dict | None, str, str]:  # fmt: skip
    """(clamped finding | None, status, prompt version). Reads the cache before any call."""
    from agents.llm import get_llm

    version, rubric = prompts.load(PROMPT_NAME)
    key = cache_key(q_sha, r_sha, machine_type, version, MODEL)
    path = CACHE_DIR / key[:2] / f"{key}.json"
    if path.exists():
        return json.loads(path.read_text())["result"], "ok", version
    contents, cfg = _build_request(asset_id, machine_type, query, ref, rubric)
    llm = ctx.llm or get_llm()  # the run's gateway: in replay it cannot reach Gemini
    run_id = getattr(ctx, "run_id", None)
    try:
        res = _run_sync(
            lambda: asyncio.wait_for(
                llm.generate(MODEL, contents, cfg, agent=AGENT_NAME, run_id=run_id,
                             timeout_s=ATTEMPT_TIMEOUT_S),
                TOTAL_TIMEOUT_S,
            )
        )  # fmt: skip
        finding = _clamp(_parse(res.response))
    except ValidationError as exc:
        log.warning("listen: unparseable Gemini output for %s: %s", query["gs_uri"], exc)
        return None, "unparseable", version
    except TimeoutError:
        log.warning(
            "listen: Gemini timed out after %.0f s for %s", TOTAL_TIMEOUT_S, query["gs_uri"]
        )
        return None, "timeout", version
    except Exception as exc:
        log.warning("listen: Gemini unavailable for %s: %r", query["gs_uri"], exc)
        return None, "unavailable", version
    entry = {
        "content_hash": key,  # sha256 of inputs (named so secret scanners do not misread it)
        "model": res.model_id,
        "prompt_version": version,
        "thinking_level": THINKING_LEVEL,
        "query_sha256": q_sha,
        "reference_sha256": r_sha,
        "machine_type": machine_type,
        "result": finding,
        "usage": {
            "input_tokens": res.usage.input_tokens,
            "output_tokens": res.usage.output_tokens,
            "thinking_tokens": res.usage.thinking_tokens,
            "usd": round(res.usage.usd, 6),
            "latency_ms": res.latency_ms,
        },
        "created_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f".{threading.get_ident()}.tmp")
    tmp.write_text(json.dumps(entry, indent=1, sort_keys=True) + "\n")
    tmp.replace(path)
    return finding, "ok", version


# --- Provenance -------------------------------------------------------------------------------
def _provenance(
    ctx: ToolContext, asset_id: str, query: dict, refs: list[dict], clip_s: int
) -> list[ProvenanceRef]:
    from agents.tools import _compact_refs, _dt
    from agents.tools import _provenance as store_prov

    t_lo = min([query["_t"], *(r["_t"] for r in refs)])
    df = store_prov(ctx, asset_id, ["audio"], t_lo, query["_t"] + clip_s)
    by_t: dict[int, str] = {}
    for r in df.itertuples() if not df.empty else []:
        by_t.setdefault(int(r.t0.timestamp()), str(r.source_ref))
    out = [
        ProvenanceRef(
            source_id="mimii",
            real=True,
            source_ref=f"audio {query['ts']}: "
            + by_t.get(query["_t"], f"{query['gs_uri']} (no provenance row in the store)"),
        )
    ]
    if refs:
        ref_refs = [by_t.get(r["_t"], r["gs_uri"]) for r in refs]
        out.append(
            ProvenanceRef(
                source_id="mimii",
                real=True,
                source_ref=f"audio references ({len(refs)}, {_dt(refs[0]['_t']):%Y-%m-%d} to "
                f"{_dt(refs[-1]['_t']):%Y-%m-%d}): " + _compact_refs(ref_refs),
            )
        )
    return out


# --- Tool implementation ----------------------------------------------------------------------
def _listen(ctx: ToolContext, asset_id: str, t0: str, t1: str) -> tuple[dict, list[ProvenanceRef]]:
    from agents.tools import ToolArgError, _asset, _window

    _asset(asset_id)
    a, b = _window(ctx, t0, t1)
    idx = _index(ctx)
    clip_s = idx["clip_duration_s"]
    mine = [c for c in idx["clips"] if c["asset_id"] == asset_id]
    if not mine:
        with_audio = sorted({c["asset_id"] for c in idx["clips"]})
        raise ToolArgError("no_audio", f"{asset_id} has no microphone recordings",
                           "assets with audio: " + ", ".join(with_audio))  # fmt: skip
    in_win = [c for c in mine if a <= c["_t"] < b]
    if not in_win:
        raise ToolArgError("no_clip_in_window", f"no {asset_id} recording starts in [{iso(a)}, {iso(b)})",
                           f"{asset_id} recordings at: " + ", ".join(c["ts"] for c in mine))  # fmt: skip
    query = in_win[-1]
    same = [c for c in mine if c["machine_id"] == query["machine_id"] and c is not query]
    refs = [c for c in same if c["_t"] + clip_s <= a]
    rule = "before_window"
    if not refs:
        refs = [c for c in same if c["_t"] + clip_s + FALLBACK_REF_GAP_S <= query["_t"]]
        rule = "earlier_than_clip_by_1h" if refs else "none"

    try:
        q_sha, q_feat = _features(_clip_bytes(ctx, query))
        ref_feats = [_features(_clip_bytes(ctx, r)) for r in refs]
    except Exception as exc:
        raise ToolArgError("clip_unreadable", f"audio clip unreadable ({type(exc).__name__})",
                           "retry later") from exc  # fmt: skip

    mfcc: dict[str, Any] = {"method": audio_mod.METHOD, "query_rms": sig(q_feat.rms, 4)}
    dist = z = None
    if ref_feats:
        cmp_ = audio_mod.compare(q_feat, [f for _, f in ref_feats])
        dist = sig(cmp_["mfcc_distance"], 4)
        z = None if cmp_["mfcc_z"] is None else rnd(cmp_["mfcc_z"], 3)
        for k in ("reference_loo_mean", "reference_loo_std"):
            mfcc[k] = None if cmp_[k] is None else sig(cmp_[k], 4)

    ref = refs[-1] if refs else None
    r_sha = ref_feats[-1][0] if ref_feats else None
    finding, status, version = _gemini(
        ctx, asset_id, query["machine_type"], query, q_sha, ref, r_sha
    )
    f = finding or {}
    conf = f.get("confidence")
    summary = {
        "asset_id": asset_id,
        "t0": iso(a),
        "t1": iso(b),
        "clip_uri": query["gs_uri"],
        "ts": query["ts"],
        "clip_duration_s": clip_s,
        "machine_type": query["machine_type"],
        "clips_in_window": len(in_win),
        "finding": f.get("finding"),
        "abnormal": f.get("abnormal"),
        "normal_vs_abnormal_confidence": conf,
        "p_abnormal": None if conf is None else rnd(conf if f["abnormal"] else 1.0 - conf, 3),
        "characteristics": f.get("characteristics", []),
        "recording_quality": f.get("recording_quality"),
        "gemini_status": status,
        "model": MODEL,
        "prompt_version": version,
        "reference_clip_for_gemini": ref["ts"] if ref else None,
        "mfcc_distance": dist,
        "mfcc_z": z,
        "n_reference_clips": len(refs),
        "reference_clips": [r["ts"] for r in refs],
        "reference_rule": rule,
        "reference_assumption": REFERENCE_ASSUMPTION,
        "mfcc": mfcc,
        "interpretation": "mfcc_distance ~1.0 = sounds like the references; mfcc_z = distance vs "
        "the references' own spread. finding/abnormal are Gemini's listening opinion (untrusted "
        "free text); mfcc_* are computed by code.",
        "untrusted_fields": ["finding", "characteristics"],
    }
    return summary, _provenance(ctx, asset_id, query, refs, clip_s)


def listen(ctx: ToolContext, asset_id: str, t0: str, t1: str) -> dict:
    """Listen to the latest microphone clip of an asset that starts in [t0, t1) (ISO 8601).
    Gemini describes the sound against a fixed rubric (healthy pump/fan/slider/valve) and an
    earlier recording of the same machine. It returns finding, abnormal, and
    normal_vs_abnormal_confidence (0-1). A code-computed MFCC baseline gives mfcc_distance (about
    1.0 = like the earlier recordings) and mfcc_z. Earlier clips are presumed normal. Only
    ST20-WLD, ST30-WLD, ST40-SLR, ST50-CNV and UT-AIR have microphones; recordings are sparse
    (a few per week), so use a window of a few hours before the stop."""
    from agents.tools import _run

    return _run("listen", ctx, {"asset_id": asset_id, "t0": t0, "t1": t1})


__all__ = ["CACHE_DIR", "GeminiFinding", "cache_key", "listen", "set_index_resolver"]
