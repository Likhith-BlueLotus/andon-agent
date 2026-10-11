"""The five equipment manuals: spec limits match the plant, every fault topic is documented, LOTO
text is verbatim and structured on 29 CFR 1910.147, quotes resolve, and the build is reproducible
from the committed prose cache (offline, $0)."""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path

import pytest

from simulator import plant
from simulator.faults import MANUAL, MANUAL_SENSOR, MANUAL_TIMER
from simulator.manuals import (
    DOCS,
    MIN_QUOTE_CHARS,
    ManualFormatError,
    find_quote,
    full_text,
    load_manuals,
    locate_quote,
    normalise,
    pages,
    parse_pages,
)
from simulator.manuals import build as B
from simulator.manuals import content as K
from simulator.manuals import loto as L

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "sample_stream.jsonl"


def _doc_for(a: plant.AssetSpec) -> str:
    """The manual that documents an asset (its own, or the one its sensor topic points to)."""
    return a.manual or MANUAL_SENSOR[a.asset_type].doc


def _num(cell: str) -> float | None:
    return None if cell.strip() == "-" else float(cell)


def _spec_rows(doc: str, asset_id: str) -> dict[str, list[str]]:
    lines = full_text(doc).splitlines()
    cap = [i for i, ln in enumerate(lines) if f"Process values and limits: {asset_id} (" in ln]
    assert len(cap) == 1, f"{doc}: expected one spec table for {asset_id}, found {len(cap)}"
    rows: dict[str, list[str]] = {}
    for ln in lines[cap[0] + 4 :]:
        if not ln.startswith("|"):
            break
        cells = [c.strip() for c in ln.strip("|").split("|")]
        rows[cells[0].strip("`")] = cells
    return rows


# --- Format ------------------------------------------------------------------------------------
def test_all_manuals_load_with_sequential_pages():
    m = load_manuals()
    assert set(m) == set(DOCS)
    for doc, pg in m.items():
        assert list(pg) == list(range(1, len(pg) + 1)), doc
        assert 15 <= len(pg) <= 60, doc
        assert all(text for text in pg.values()), doc


def test_parse_pages_rejects_bad_numbering():
    with pytest.raises(ManualFormatError):
        parse_pages("<!-- page 1 -->\na\n<!-- page 3 -->\nb")
    with pytest.raises(ManualFormatError):
        parse_pages("preamble\n<!-- page 1 -->\na")
    with pytest.raises(ManualFormatError):
        parse_pages("no markers")


def test_disclaimer_on_title_page_and_in_loto_chapter():
    for doc in DOCS:
        pg = pages(doc)
        assert find_quote(doc, 1, B.DISCLAIMER), doc
        loto_pages = locate_quote(doc, B.DISCLAIMER)
        assert len(loto_pages) >= 2 and any(
            "Energy control procedure (lockout/tagout)" in pg[p] for p in loto_pages
        ), doc


def test_no_unresolved_placeholders_brands_or_non_ascii():
    for doc in DOCS:
        text = full_text(doc)
        assert not re.search(r"\{(?:[TSP]|PROSE):|\{CONTENTS\}|\{INDEX\}", text), doc
        assert B.brand_hits(text) == [], doc
        assert text.isascii(), doc


def test_every_table_reference_exists():
    captions = {
        d: set(re.findall(r"^\*\*(Table [0-9A-Z]+-\d+) ", full_text(d), re.M)) for d in DOCS
    }
    by_no = {K.SPECS[d].doc_no: d for d in DOCS}
    for doc in DOCS:
        for m in re.finditer(r"(Table [0-9A-Z]+-\d+)(?: of (AM-[A-Z]{2}-\d\d))?", full_text(doc)):
            target = by_no[m.group(2)] if m.group(2) else doc
            assert m.group(1) in captions[target], f"{doc}: {m.group(0)} has no caption"


# --- Spec limits match the plant ---------------------------------------------------------------
def test_every_plant_limit_appears_in_the_right_manual():
    fields = [
        ("nominal", 3),
        ("alarm_lo", 5),
        ("alarm_hi", 6),
        ("trip_lo", 7),
        ("trip_hi", 8),
        ("resolution", 9),
    ]
    for a in plant.ASSETS:
        doc = _doc_for(a)
        rows = _spec_rows(doc, a.asset_id)
        assert set(rows) == {t.tag for t in a.tags}, (doc, a.asset_id)
        for t in a.tags:
            cells = rows[t.tag]
            assert cells[2] == t.unit, (a.asset_id, t.tag)
            lo, hi = (float(x) for x in cells[4].split(" to "))
            assert (lo, hi) == (t.normal_lo, t.normal_hi), (a.asset_id, t.tag)
            for name, col in fields:
                assert _num(cells[col]) == getattr(t, name), (a.asset_id, t.tag, name)


def test_alarm_codes_listed_with_their_limits():
    for row in plant.spec_limits():
        a = plant.asset(str(row["asset_id"]))
        text = full_text(_doc_for(a))
        for code in row["alarm_codes"]:  # type: ignore[union-attr]
            assert f"| {code} |" in text, code


def test_plant_constants_documented():
    air = full_text("compressed_air")
    for v in (plant.AIR_CUT_IN_BAR, plant.AIR_CUT_OUT_BAR, plant.AIR_REGULATOR_BAR):
        assert f"{v:g} bar" in air
    assert (
        f"{plant.AIR_LOADED_CURRENT_A:g} A" in air and f"{plant.AIR_UNLOADED_CURRENT_A:g} A" in air
    )
    weld = full_text("weld_controller")
    assert f"{plant.SERVO_DERATE_START_C:g} degC" in weld
    assert f"{plant.SERVO_DERATE_S_PER_C:g} s per degC" in weld
    assert f"{plant.SEALER_STROKE_HZ:g} Hz" in full_text("sealer_pump")
    conv = full_text("conveyor_drive")
    assert f"{float(plant.CONVEYOR_ROTATION_HZ):.3f} Hz" in conv
    assert f"{plant.CONVEYOR_PULLEY_DIAMETER_M:g} m" in conv
    press = full_text("press_hydraulics")
    for sp in plant.PRODUCT_SETPOINTS.values():
        assert f"| {sp[('ST10-PRS', 'hyd_pressure_bar')]:g} |" in press


# --- Fault topics ------------------------------------------------------------------------------
def test_every_fault_topic_has_a_heading_in_its_manual():
    refs = [*MANUAL.values(), *MANUAL_SENSOR.values(), *MANUAL_TIMER.values()]
    for ref in refs:
        heads = re.findall(r"^#{1,2} \S+ (.+)$", full_text(ref.doc), re.M)
        assert ref.topic in heads, (ref.doc, ref.topic)


def test_every_topic_has_a_troubleshooting_table():
    layouts = {d: B.layout(K.SPECS[d])[0] for d in DOCS}
    for doc in DOCS:
        spec = K.SPECS[doc]
        topics = [*spec.topics, *(spec.appendix.topics if spec.appendix else ())]
        text = full_text(doc)
        for t in topics:
            assert f" Troubleshooting: {t.title}**" in text, (doc, t.title)
            assert len(t.rows) >= 2
            for note in t.notes:  # diagnostic notes are quotable, on the topic's own page
                note = B.resolve(note, doc, layouts)
                assert locate_quote(doc, note) == [layouts[doc].anchors[t.key][1]], note


# --- LOTO --------------------------------------------------------------------------------------
PHASE_ORDER = [p for p, _ in L.PHASES]


@pytest.mark.parametrize("doc", DOCS)
def test_loto_steps_verbatim_in_chapter_8_and_cfr_structured(doc):
    proc = L.LOTO[doc]
    pg = pages(doc)
    ch8 = next(n for n, t in pg.items() if "# 8 Energy control procedure (lockout/tagout)" in t)
    phases = [s.phase for s in proc.steps]
    assert phases == sorted(phases, key=PHASE_ORDER.index), "steps out of (d)/(e) order"
    assert set(phases) == set(PHASE_ORDER), "a (d)/(e) phase is missing"
    cfrs = [s.cfr for s in proc.steps]
    assert cfrs[0] == "(d)(1)" and "(c)(9)" in cfrs and cfrs[-1] == "(e)(2)(ii)"
    assert cfrs.index("(e)(3)") < cfrs.index("(e)(2)(ii)")
    for n, s in enumerate(proc.steps, 1):
        assert s.cfr in L.CFR_PARAGRAPHS and s.cfr in L.PHASE_CFR[s.phase], s
        assert s.text.endswith(".") and s.text.count(". ") == 0, s.text
        assert len(s.text.split()) <= 35 and s.text[0].isupper(), s.text
        found = locate_quote(doc, s.text)
        assert len(found) == 1 and found[0] >= ch8, (n, s.text, found)
        assert f"| {n} | {s.text} | {s.cfr} |" in pg[found[0]]
    for e in proc.energy:  # every energy source names its stored-energy control
        assert e.stored and e.isolating_device


def test_loto_review_file_matches_manuals():
    reviews = {d: B.layout(K.SPECS[d])[1] for d in DOCS}
    assert B.REVIEW_PATH.read_text(encoding="utf-8") == B.loto_review(reviews)
    for d, rows in reviews.items():
        for page, _, step in rows:
            assert find_quote(d, page, step.text)


# --- Reproducible build ------------------------------------------------------------------------
def test_build_from_cache_is_byte_identical(tmp_path):
    gen = asyncio.run(B.build_all("cached", out_dir=tmp_path, review_path=tmp_path / "r.md"))
    assert gen.calls == 0 and gen.usd == 0.0
    for doc in DOCS:
        assert (tmp_path / f"{doc}.md").read_text() == full_text(doc), doc


def test_prose_validator_rejects_bad_prose():
    specs = (K.ProseSpec("x", "X", "w", 10),)
    bad = B.ProseBatch(
        sections=[B.ProseSection(id="x", paragraphs=["Apply lockout at 99 bar now, ok."])]
    )
    problems = B.validate_prose(bad, specs, "facts 5 bar")
    assert any("numbers" in p for p in problems) and any("lockout" in p for p in problems)
    good = B.ProseBatch(
        sections=[B.ProseSection(id="x", paragraphs=["The pump runs at 5 bar normally."])]
    )
    assert B.validate_prose(good, specs, "facts 5 bar") == []


def test_manuals_fit_the_context_budget_offline_estimate():
    chars = sum(len(full_text(d)) for d in DOCS)
    assert 6_144 * 3 < chars < 200_000 * 3  # ~3-4 chars/token; the live count is recorded in docs


@pytest.mark.live
def test_manuals_token_count_live():
    n = B.count_tokens()
    assert 6_144 <= n < 200_000


# --- find_quote --------------------------------------------------------------------------------
def test_find_quote_normalises_whitespace_and_markup_only():
    doc = "compressed_air"
    q = "A sustained fall in header pressure while the compressor runs loaded indicates demand exceeding supply, most often a distribution leak."
    page = locate_quote(doc, q)[0]
    assert find_quote(doc, page, q)
    assert find_quote(doc, page, "  " + q.replace(" ", "\n   ") + " ")
    assert not find_quote(doc, page, q.lower())  # case matters
    assert not find_quote(doc, page, q.replace("most often", "usually"))  # wording matters
    assert not find_quote(doc, page + 1, q)  # page matters
    assert not find_quote("nope", page, q) and not find_quote(doc, 999, q)
    assert not find_quote(doc, page, "header pressure")  # too short to prove anything
    assert len(normalise("header pressure")) < MIN_QUOTE_CHARS
    # Markdown code marks around tags do not matter
    tagged = "header pressure (header_pressure_bar) saw-tooths inside its normal range"
    assert find_quote(doc, page, tagged)
    fancy = f"a {chr(0x2013)} b {chr(0x201C)}c{chr(0x201D)} **d**"
    assert normalise(fancy) == 'a - b "c" d'


def test_every_fixture_citation_is_found_verbatim():
    cites: list[dict] = []
    for line in FIXTURE.read_text().splitlines():
        ev = json.loads(line)
        data = ev["data"]
        if ev["type"] == "tool_result":
            cites += (data.get("summary") or {}).get("citations", [])
        if ev["type"] in ("hypotheses", "rca_final"):
            cites += [
                c["citation"] for h in data["hypotheses"] for c in h["claims"] if c["citation"]
            ]
        if ev["type"] == "work_order_draft":
            cites += [s["citation"] for s in data["steps"] if s["citation"]]
    assert len(cites) >= 7
    for c in cites:
        assert find_quote(c["doc"], c["page"], c["quote"]), c
