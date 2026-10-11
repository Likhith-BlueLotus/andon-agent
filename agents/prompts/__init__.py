"""Versioned prompt files. Each ``<name>.md`` starts with ``<!-- version: <name> vN YYYY-MM-DD -->``.

Prompts stay short: schemas and tool docstrings carry the structure.
"""

from __future__ import annotations

import re
from functools import cache
from pathlib import Path

PROMPT_DIR = Path(__file__).parent
_HEADER = re.compile(r"\A<!--\s*version:\s*(?P<v>[^>]+?)\s*-->\s*\n")

# Appended to every LLM agent's instruction (AGENTS_SPEC "Prompts").
GROUND_RULES = (
    "You never see ground truth. You may not state a number you did not get from a tool. "
    "If evidence is insufficient, say so."
)


@cache
def _read(name: str, mtime_ns: int) -> tuple[str, str]:
    raw = (PROMPT_DIR / f"{name}.md").read_text(encoding="utf-8")
    m = _HEADER.match(raw)
    if not m:
        raise ValueError(f"prompt {name}.md has no '<!-- version: ... -->' header")
    return m.group("v"), raw[m.end() :].strip()


def load(name: str) -> tuple[str, str]:
    """``(version, text)`` of ``agents/prompts/<name>.md``."""
    p = PROMPT_DIR / f"{name}.md"
    return _read(name, p.stat().st_mtime_ns)


def text(name: str) -> str:
    return load(name)[1]


def version(name: str) -> str:
    return load(name)[0]
