"""Work-order language toggle (stretch item 3, ADR-030).

The stored work order is the controlling text. A translation is model output shown BESIDE the
original, labelled as machine translation (CLAUDE.md hard rule 5): ``original`` in the response is
always copied from the stored work order, never from the model, and a translation that fails
validation becomes ``null`` so the UI shows the original only. One Flash-Lite call per
(work order, language); repeats are served from a bounded in-memory cache at $0.
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
from collections import OrderedDict
from pathlib import Path
from typing import Any

from google.genai import types
from pydantic import BaseModel, Field

import config
from agents.schemas import WorkOrder
from agents.untrusted import NOTICE, wrap

LANGS = {
    "hi": "हिन्दी (Hindi)",
    "ta": "தமிழ் (Tamil)",
    "id": "Bahasa Indonesia (Indonesian)",
    "vi": "Tiếng Việt (Vietnamese)",
}
NOTICE_TEXT = (
    "Machine translation — not the controlling text. "
    "Safety steps are binding only in the original language."
)
PROMPT_FILE = Path(__file__).parent / "prompts" / "wo_translate.md"
CACHE_MAX = 256
_MARKUP = re.compile(r"</?[A-Za-z!][^>]*>|```|`|\]\(|\*\*|^\s*#{1,6}\s", re.M)
_CTRL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")


class StepT(BaseModel):
    order: int
    translation: str = ""


class PartT(BaseModel):
    index: int
    translation: str = ""


class LLMTranslation(BaseModel):
    steps: list[StepT] = Field(default_factory=list)
    parts: list[PartT] = Field(default_factory=list)


def _prompt() -> str:
    raw = PROMPT_FILE.read_text(encoding="utf-8")
    return re.sub(r"\A<!--.*?-->\s*", "", raw, flags=re.S).strip()


def content_hash(wo: WorkOrder) -> str:
    blob = json.dumps(
        {"steps": [[s.order, s.text] for s in wo.steps], "parts": wo.parts}, ensure_ascii=False
    )
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


def valid_translation(original: str, candidate: Any) -> str | None:
    """The cleaned translation, or None when it is empty, too long or carries markup."""
    if not isinstance(candidate, str):
        return None
    text = candidate.strip()
    if not text or len(text) > 3 * len(original) + 200:
        return None
    if _CTRL.search(text) or _MARKUP.search(text):
        return None
    return text


async def translate(wo: WorkOrder, lang: str, llm: Any) -> tuple[dict[int, str | None], dict[int, str | None], str, float]:  # fmt: skip
    """One Flash-Lite call. Returns (step order -> translation|None, part index -> translation|None,
    model_id, cost_usd). Raises on transport/parse failure (the route answers 502)."""
    payload = {
        "steps": [{"order": s.order, "text": s.text} for s in wo.steps],
        "parts": [{"index": i, "text": p} for i, p in enumerate(wo.parts)],
    }
    cfg = types.GenerateContentConfig(
        system_instruction=_prompt(),
        response_mime_type="application/json",
        response_schema=LLMTranslation,
        thinking_config=types.ThinkingConfig(thinking_level=types.ThinkingLevel.LOW),
    )
    contents = (
        f"{NOTICE}\nTarget language: {LANGS[lang]} (ISO code {lang}).\n"
        f"Work order to translate (JSON):\n{wrap(json.dumps(payload, ensure_ascii=False))}"
    )
    res = await llm.generate(config.FLASH_LITE, contents, cfg, agent="wo_translate", timeout_s=45.0)
    text = getattr(res.response, "text", None)
    if not text:
        raise ValueError("model returned no text")
    parsed = LLMTranslation.model_validate_json(text)
    by_step: dict[int, str] = {}
    for t in parsed.steps:
        by_step.setdefault(t.order, t.translation)  # first answer per order wins
    by_part: dict[int, str] = {}
    for t in parsed.parts:
        by_part.setdefault(t.index, t.translation)
    steps = {s.order: valid_translation(s.text, by_step.get(s.order)) for s in wo.steps}
    parts = {i: valid_translation(p, by_part.get(i)) for i, p in enumerate(wo.parts)}
    return steps, parts, res.model_id, round(float(res.usage.usd or 0.0), 6)


def build_response(incident_id: str, wo: WorkOrder, lang: str, steps: dict[int, str | None],
                   parts: dict[int, str | None], model_id: str, cost: float, *, cached: bool) -> dict[str, Any]:  # fmt: skip
    """``original`` fields are copied from the stored work order only."""
    return {
        "incident_id": incident_id,
        "wo_id": wo.wo_id,
        "lang": lang,
        "lang_name": LANGS[lang],
        "model_id": model_id,
        "cost_usd": 0.0 if cached else cost,
        "cached": cached,
        "notice": NOTICE_TEXT,
        "steps": [
            {
                "order": s.order,
                "is_safety": s.is_safety,
                "original": s.text,
                "translation": steps.get(s.order),
                "citation": s.citation.model_dump(mode="json") if s.citation else None,
            }
            for s in wo.steps
        ],
        "parts": [{"original": p, "translation": parts.get(i)} for i, p in enumerate(wo.parts)],
    }


class TranslationCache:
    """(wo_id, lang, content hash) -> (steps, parts, model_id, cost). Bounded LRU, per instance."""

    def __init__(self, max_items: int = CACHE_MAX) -> None:
        self.max_items = max_items
        self._d: OrderedDict[tuple[str, str, str], tuple] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: tuple[str, str, str]) -> tuple | None:
        with self._lock:
            if key in self._d:
                self._d.move_to_end(key)
                return self._d[key]
        return None

    def put(self, key: tuple[str, str, str], value: tuple) -> None:
        with self._lock:
            self._d[key] = value
            self._d.move_to_end(key)
            while len(self._d) > self.max_items:
                self._d.popitem(last=False)
