"""The five equipment manuals: page loader and verbatim-quote lookup (SYNTHETIC_DATA_SPEC §6).

Manuals live next to this file as ``<doc>.md`` with ``<!-- page N -->`` markers. They are built
by ``python -m simulator.manuals.build`` (spec tables from ``simulator.plant``, LOTO steps from
``simulator.manuals.loto``, prose drafted once by Gemini and cached).

The verifier's citation rule (AGENTS_SPEC §5) and ``cite_manual`` call :func:`find_quote`: a quote
passes only if it exists verbatim, after whitespace normalisation, on the stated page. The
normalisation is deliberately narrow (whitespace, Markdown emphasis/code marks, typographic quotes
and dashes); wording, case and punctuation must match exactly.

This module is light (stdlib only) so ``agents/`` and ``api/`` can import it.
"""

from __future__ import annotations

import re
import unicodedata
from functools import cache
from pathlib import Path

MANUAL_DIR = Path(__file__).parent
DOCS: tuple[str, ...] = (
    "weld_controller",
    "sealer_pump",
    "conveyor_drive",
    "press_hydraulics",
    "compressed_air",
)
# A quote shorter than this (after normalisation) proves nothing ("the pump") and never passes.
MIN_QUOTE_CHARS = 20

_PAGE_RE = re.compile(r"<!--\s*page\s+(\d+)\s*-->")
# typographic quotes, dashes, minus sign and no-break space -> ASCII
_TRANSLATE = str.maketrans(
    {chr(c): "'" for c in (0x2018, 0x2019)}
    | {chr(c): '"' for c in (0x201C, 0x201D)}
    | {chr(c): "-" for c in (0x2013, 0x2014, 0x2212)}
    | {chr(0x00A0): " "}
)


class ManualFormatError(ValueError):
    """A manual file is missing page markers or its pages are not numbered 1..N."""


def parse_pages(text: str, doc: str = "<text>") -> dict[int, str]:
    """Split a manual into ``{page: text}``. Pages must be numbered 1..N in order."""
    marks = list(_PAGE_RE.finditer(text))
    if not marks:
        raise ManualFormatError(f"{doc}: no <!-- page N --> markers")
    if text[: marks[0].start()].strip():
        raise ManualFormatError(f"{doc}: text before the first page marker")
    pages: dict[int, str] = {}
    for i, m in enumerate(marks):
        n = int(m.group(1))
        if n != i + 1:
            raise ManualFormatError(f"{doc}: page marker {n} found where {i + 1} was expected")
        end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        pages[n] = text[m.end() : end].strip()
    return pages


def manual_path(doc: str) -> Path:
    if doc not in DOCS:
        raise KeyError(f"unknown manual {doc!r}; expected one of {DOCS}")
    return MANUAL_DIR / f"{doc}.md"


@cache
def _load(doc: str, mtime_ns: int) -> dict[int, str]:
    return parse_pages(manual_path(doc).read_text(encoding="utf-8"), doc)


def pages(doc: str) -> dict[int, str]:
    """``{page: text}`` for one manual (cached; reloaded if the file changes)."""
    p = manual_path(doc)
    return _load(doc, p.stat().st_mtime_ns)


def load_manuals() -> dict[str, dict[int, str]]:
    """``{doc: {page: text}}`` for all five manuals."""
    return {d: pages(d) for d in DOCS}


def full_text(doc: str) -> str:
    """The raw Markdown of one manual (what goes into the Gemini context cache)."""
    return manual_path(doc).read_text(encoding="utf-8")


def normalise(text: str) -> str:
    """Whitespace-normalised comparison form. Keeps wording, case and punctuation."""
    t = unicodedata.normalize("NFKC", text).translate(_TRANSLATE)
    t = t.replace("**", "").replace("`", "")
    t = re.sub(r"(?<!\w)_(\S[^_]*?)_(?!\w)", r"\1", t)  # _emphasis_ but not snake_case tags
    return re.sub(r"\s+", " ", t).strip()


def find_quote(doc: str, page: int, quote: str) -> bool:
    """True iff ``quote`` exists verbatim (whitespace-normalised) on ``page`` of ``doc``.

    Unknown docs or pages, and quotes shorter than ``MIN_QUOTE_CHARS``, return False.
    """
    q = normalise(quote)
    if len(q) < MIN_QUOTE_CHARS or doc not in DOCS:
        return False
    text = pages(doc).get(page)
    return text is not None and q in normalise(text)


def locate_quote(doc: str, quote: str) -> list[int]:
    """Every page of ``doc`` on which ``quote`` appears (for verifier failure messages)."""
    q = normalise(quote)
    if len(q) < MIN_QUOTE_CHARS or doc not in DOCS:
        return []
    return [n for n, text in pages(doc).items() if q in normalise(text)]


def render_pdf(doc: str, out: Path) -> Path:  # pragma: no cover - optional, not needed yet
    """PDF rendering is deferred: the UI shows the Markdown page directly (page numbers match)."""
    raise NotImplementedError("PDF rendering is not implemented; display the Markdown pages")
