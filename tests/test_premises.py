"""The premise registry stays pinned to the rendered manuals (ADR-025)."""

from __future__ import annotations

from simulator import plant
from simulator.manuals import MIN_QUOTE_CHARS, locate_quote, normalise, pages
from simulator.manuals.premises import (
    AIR_CUT_IN_BAR,
    PASSAGES,
    passages_for,
    premises_for,
)


def test_every_passage_is_verbatim_in_its_manual():
    for p in PASSAGES:
        assert len(normalise(p.text)) >= MIN_QUOTE_CHARS, p.text
        assert locate_quote(p.doc, p.text), f"{p.doc}: {p.text!r} not found; manual rebuilt?"


def test_premises_name_real_tags_and_thresholds_match_the_plant():
    assert AIR_CUT_IN_BAR == plant.AIR_CUT_IN_BAR
    for p in PASSAGES:
        assert p.premises
        for pr in p.premises:
            if pr.asset is not None:
                assert any(t.tag == pr.tag for t in plant.asset(pr.asset).tags), (pr, p.text)
            else:
                assert any(a.manual == p.doc and any(t.tag == pr.tag for t in a.tags)
                           for a in plant.ASSETS), (pr, p.text)  # fmt: skip


def test_quote_overlap_selects_the_passage():
    q = "A sustained fall in header pressure while the compressor runs loaded indicates demand exceeding supply, most often a distribution leak."
    (pg,) = locate_quote("compressed_air", q)
    assert [p.text for p in passages_for("compressed_air", pg, q)] == [q]
    # a fragment of the passage and a quote spanning it both carry the premise
    assert premises_for("compressed_air", pg, "while the compressor runs loaded indicates demand")
    page = normalise(pages("compressed_air")[pg])
    i = page.index(q)
    assert premises_for("compressed_air", pg, page[i - 40 : i + 40])
    # a neighbouring note without premises carries none
    assert (
        premises_for(
            "compressed_air",
            pg,
            "Check drop-leg fittings and quick couplings at the weld cells first",
        )
        == []
    )
    d = premises_for("compressed_air", pg, q)[0].as_dict()
    assert d == {"asset": "UT-AIR", "tag": "header_pressure_bar", "expect": "low", "value": 6.2}
