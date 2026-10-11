"""Build the five manuals: ``python -m simulator.manuals.build [--mode cached|live]``.

Pipeline per manual:

1. Lay out pages from deterministic content (``content.py``), spec tables generated from
   ``simulator.plant`` and LOTO steps from ``loto.py``. Prose slots are placeholders.
2. Resolve cross-references (``{T:key}``, ``{S:key}``, ``{P:key}``, ``{T:doc/key}``) once every
   anchor has a page.
3. Fill prose slots with Gemini output (``config.FLASH`` through ``agents.llm``), validated
   (no numbers absent from the facts, no lockout wording, no brand names) and cached by content
   hash under ``data/cache/manuals/`` so reruns cost $0 and are byte-identical.
4. Write ``simulator/manuals/<doc>.md`` and ``docs/review/LOTO_REVIEW.md``.

Extra commands (live, near-free): ``--count-tokens`` (google-genai ``count_tokens`` on all five
manuals) and ``--cache-probe`` (create one explicit context cache with TTL 120 s, use it once
through ``agents.llm``, delete it).
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ValidationError

import config
from simulator import plant
from simulator.manuals import DOCS, MANUAL_DIR, parse_pages
from simulator.manuals import content as K
from simulator.manuals import loto as L

log = logging.getLogger("andon.sim.manuals")

ROOT = Path(__file__).resolve().parents[2]
PROMPT_PATH = ROOT / "simulator" / "prompts" / "manuals.md"
CACHE_DIR = ROOT / "data" / "cache" / "manuals"
REVIEW_PATH = ROOT / "docs" / "review" / "LOTO_REVIEW.md"
MODEL_ID = config.FLASH
REVISION = "A"
ISSUE = "2026-10"
Mode = Literal["cached", "live"]

DISCLAIMER = (
    "This manual describes fictional equipment created for the Andon Agent software "
    "demonstration (synthetic line L1). It is not a manufacturer's manual. Its energy control "
    "procedure is not a substitute for a site-specific energy control procedure prepared, approved "
    "and trained under 29 CFR 1910.147 or local regulation."
)

# Real equipment brands must never appear (generic, fictional equipment only). Lower-case match.
BANNED_BRANDS: tuple[str, ...] = (
    "siemens", "abb", "fanuc", "kuka", "yaskawa", "motoman", "bosch", "rexroth", "parker",
    "eaton", "vickers", "atlas copco", "ingersoll", "kaeser", "sullair", "graco", "nordson",
    "sames", "dürr", "durr", "obara", "nimak", "aro", "skf", "timken", "schaeffler", "fag",
    "nsk", "festo", "smc", "rockwell", "allen-bradley", "allen bradley", "schneider", "omron",
    "mitsubishi", "keyence", "cognex", "sew-eurodrive", "sew eurodrive", "danfoss", "hydac",
    "sun hydraulics", "moog", "daikin", "trane", "toyota", "volkswagen", "ford",
    "hyundai", "maruti", "tata", "mahindra", "honda", "general motors", "stellantis", "bmw",
)  # fmt: skip
BANNED_SAFETY_WORDS = re.compile(r"\b(lock\s*-?\s*out|tag\s*-?\s*out|loto)\b", re.IGNORECASE)
NUM_RE = re.compile(r"(?<![\w.])\d+(?:\.\d+)?")


def brand_hits(text: str) -> list[str]:
    t = text.lower()
    return [b for b in BANNED_BRANDS if re.search(rf"(?<![a-z]){re.escape(b)}(?![a-z])", t)]


# --- Layout ------------------------------------------------------------------------------------
@dataclass
class Layout:
    spec: K.ManualSpec
    pages: list[list[str]] = field(default_factory=lambda: [[]])
    anchors: dict[str, tuple[str, int]] = field(default_factory=dict)  # key -> (label, page)
    chapters: list[tuple[str, str, int]] = field(default_factory=list)  # (num, title, page)
    _ch: str = ""
    _sec: int = 0
    _tbl: int = 0

    @property
    def page_no(self) -> int:
        return len(self.pages)

    def page(self) -> None:
        if self.pages[-1]:
            self.pages.append([])

    def add(self, block: str) -> None:
        self.pages[-1].append(block)

    def anchor(self, key: str, label: str) -> None:
        if key in self.anchors:
            raise ValueError(f"{self.spec.doc}: duplicate anchor {key!r}")
        self.anchors[key] = (label, self.page_no)

    def chapter(self, num: str, title: str, key: str) -> None:
        self.page()
        self._ch, self._sec, self._tbl = num, 0, 0
        word = "Appendix" if num.isalpha() else "Chapter"
        heading = f"# {word} {num} {title}" if num.isalpha() else f"# {num} {title}"
        self.add(heading)
        self.anchor(key, f"{word} {num}")
        self.chapters.append((num, title, self.page_no))

    def section(self, key: str | None, title: str, *, new_page: bool = False) -> str:
        if new_page:
            self.page()
        self._sec += 1
        num = f"{self._ch}.{self._sec}"
        self.add(f"## {num} {title}")
        if key:
            self.anchor(key, f"Section {num}")
        return num

    def table(
        self, key: str | None, caption: str, header: tuple[str, ...], rows: list[tuple[str, ...]]
    ) -> str:
        self._tbl += 1
        label = f"Table {self._ch}-{self._tbl}"
        if key:
            self.anchor(key, label)
        for r in [header, *rows]:
            if len(r) != len(header):
                raise ValueError(f"{self.spec.doc}: row width mismatch in {caption!r}: {r}")
            if any("|" in c or "\n" in c for c in r):
                raise ValueError(f"{self.spec.doc}: '|' or newline in a cell of {caption!r}")
        lines = [
            f"**{label} {caption}**",
            "",
            "| " + " | ".join(header) + " |",
            "|" + "|".join("---" for _ in header) + "|",
        ]
        lines += ["| " + " | ".join(r) + " |" for r in rows]
        self.add("\n".join(lines))
        return label

    def prose(self, pid: str) -> None:
        self.add(f"{{PROSE:{pid}}}")


def _asset_label(aid: str) -> str:
    a = plant.asset(aid)
    return f"{aid} ({a.name})"


def spec_table_rows(asset_id: str) -> list[tuple[str, ...]]:
    """Rows of the generated 'Process values and limits' table (from plant.TAG_SPECS)."""
    rows = []
    for t in plant.asset(asset_id).tags:
        rows.append(
            (
                f"`{t.tag}`",
                t.description,
                t.unit,
                K.g(t.nominal),
                f"{K.g(t.normal_lo)} to {K.g(t.normal_hi)}",
                K.g(t.alarm_lo),
                K.g(t.alarm_hi),
                K.g(t.trip_lo),
                K.g(t.trip_hi),
                K.g(t.resolution),
            )
        )
    return rows


SPEC_HEADER = (
    "Tag",
    "Description",
    "Unit",
    "Nominal",
    "Normal range",
    "Alarm low",
    "Alarm high",
    "Trip low",
    "Trip high",
    "Resolution",
)
SPEC_CAPTION = "Process values and limits: {asset}"


def _spec_tables(lay: Layout, assets: tuple[str, ...]) -> None:
    for aid in assets:
        lay.table(
            f"spec_{aid}",
            SPEC_CAPTION.format(asset=_asset_label(aid)),
            SPEC_HEADER,
            spec_table_rows(aid),
        )


def _message_rows(
    events: tuple[tuple[str, str, str], ...], assets: tuple[str, ...]
) -> list[tuple[str, ...]]:
    rows: list[tuple[str, ...]] = []
    level_word = {"LO": "low", "HI": "high", "LL": "low-low", "HH": "high-high"}
    for aid in assets:
        for t in plant.asset(aid).tags:
            for lvl, lim in (
                ("LO", t.alarm_lo),
                ("HI", t.alarm_hi),
                ("LL", t.trip_lo),
                ("HH", t.trip_hi),
            ):
                if lim is None:
                    continue
                trip = lvl in ("LL", "HH")
                cmp = "below" if lvl in ("LO", "LL") else "above"
                rows.append(
                    (
                        plant.alarm_code(aid, t.tag, lvl),  # type: ignore[arg-type]
                        f"{plant.asset(aid).name}: {t.label} {level_word[lvl]}",
                        f"`{t.tag}` {cmp} {K.g(lim)} {t.unit}; "
                        + (
                            "trip: the station stops"
                            if trip
                            else "alarm: the station keeps running"
                        ),
                    )
                )
    rows += [tuple(e) for e in events]
    return rows


def _topic(lay: Layout, t: K.Topic, *, first: bool = False) -> None:
    lay.section(t.key, t.title, new_page=not first)
    lay.add(f"**Typical signature.** {t.signature}")
    for key, caption, header, rows in t.extra:
        lay.table(key, caption, header, list(rows))
    lay.add("**Diagnostic notes**\n\n" + "\n".join(f"- {n}" for n in t.notes))
    if t.page_break_before_table:
        lay.page()
    lay.table(
        f"ts_{t.key}",
        f"Troubleshooting: {t.title}",
        ("Symptom", "Probable cause", "Check", "Remedy"),
        [(r.symptom, r.cause, r.check, r.remedy) for r in t.rows],
    )
    if t.background:
        lay.add("**Background.**")
        lay.prose(t.background)


def _code_first_word(s: str) -> str:
    head, _, rest = s.partition(" ")
    return f"`{head}` {rest}".strip()


def _loto_rows(steps: list[tuple[int, L.LotoStep]]) -> list[tuple[str, ...]]:
    return [(str(i), s.text, s.cfr) for i, s in steps]


def layout(spec: K.ManualSpec) -> tuple[Layout, list[tuple[int, int, L.LotoStep]]]:
    """Lay out one manual. Returns the layout and [(page, step_no, step)] for the LOTO review."""
    lay = Layout(spec)
    proc = L.LOTO[spec.doc]
    has_cycle = any(
        t.tag == "cycle_time_s"
        for aid in (*spec.applies_to, *(spec.appendix.assets if spec.appendix else ()))
        for t in plant.asset(aid).tags
    )

    # p1 title
    lay.add(f"# {spec.title}")
    lay.add(
        f"**Document {spec.doc_no} | Revision {REVISION} | Issued {ISSUE} | Line {plant.LINE_ID}**"
    )
    lay.add("**Applies to:** " + ", ".join(_asset_label(a) for a in spec.applies_to))
    lay.add(f"> **IMPORTANT - FICTIONAL EQUIPMENT.** {DISCLAIMER}")
    lay.add(f"| Revision | Date | Change |\n|---|---|---|\n| {REVISION} | {ISSUE} | First issue |")
    lay.add("**About this manual**")
    lay.prose("about")
    # p2 contents (filled after layout)
    lay.page()
    lay.add("# Contents")
    lay.add("{CONTENTS}")

    # 1 Safety
    lay.chapter("1", "Safety", "ch1")
    lay.section(None, "General safety")
    lay.prose("safety_intro")
    lay.section(None, "Signal words")
    lay.table(
        None,
        "Signal words used in this manual",
        ("Signal word", "Meaning"),
        [
            (
                "DANGER",
                "A hazardous situation that will cause death or serious injury if not avoided",
            ),
            (
                "WARNING",
                "A hazardous situation that could cause death or serious injury if not avoided",
            ),
            (
                "CAUTION",
                "A hazardous situation that could cause minor or moderate injury if not avoided",
            ),
            ("NOTICE", "A situation that could damage the equipment or the product"),
        ],
    )
    lay.page()
    lay.section("sec_hazards", "Hazards and protective measures")
    lay.table(
        "hazards", "Hazards", ("Hazard", "Where", "Protection"), [tuple(h) for h in spec.hazards]
    )
    lay.section(None, "Personal protective equipment")
    lay.add("\n".join(f"- {p}" for p in spec.ppe))
    lay.add(
        "**WARNING** Before any maintenance, cleaning or adjustment inside a guarded area, apply "
        "the energy control procedure in Chapter 8."
    )

    # 2 Description
    lay.chapter("2", "Description", "ch2")
    lay.section(None, "Overview")
    lay.prose("overview")
    lay.section(None, "Main components")
    lay.table(
        "components",
        "Main components",
        ("Component", "Function"),
        [tuple(c) for c in spec.components],
    )
    lay.section(None, "Principle of operation", new_page=True)
    lay.prose("principle")

    # 3 Technical data
    lay.chapter("3", "Technical data", "ch3")
    lay.section("sec_spec", "Process values and limits")
    lay.add(
        "The normal range is the band the equipment stays in during normal production. An alarm "
        "limit raises a warning and the station keeps running; a trip limit stops the station. "
        "A dash means the limit is not used."
    )
    _spec_tables(lay, spec.applies_to)
    lay.section(None, "Operating parameters", new_page=True)
    lay.table(
        "params",
        "Operating parameters",
        ("Parameter", "Value", "Note"),
        [tuple(p) for p in spec.params],
    )
    for key, caption, header, rows in spec.ch3_extra:
        lay.table(key, caption, header, list(rows))
    lay.section("sec_messages", "Alarm and stop messages", new_page=True)
    lay.table(
        "messages",
        "Alarm and stop messages",
        ("Code", "Message", "Condition or meaning"),
        _message_rows(spec.events, spec.applies_to),
    )

    # 4 Operation
    lay.chapter("4", "Operation", "ch4")
    lay.section(None, "Start-up")
    lay.prose("startup")
    lay.section(None, "Normal operation")
    lay.prose("operation")
    lay.section(None, "Normal production stop", new_page=True)
    lay.prose("shutdown")
    if spec.changeover:
        lay.section("changeover_proc", "Product changeover")
        lay.add("\n".join(f"{i}. {s}" for i, s in enumerate(spec.changeover, 1)))

    # 5 Control parameters (MANUAL_TIMER topic)
    lay.chapter("5", K.TOPIC_TIMER, "ch5")
    lay.section(None, "Control parameters")
    lay.prose("controls_intro")
    lay.table(
        "timers",
        "Adjustable control parameters",
        ("Parameter", "Function", "May be changed by"),
        [tuple(t) for t in spec.timers],
    )
    lay.section("change_control", "Change control and diagnosis", new_page=True)
    lay.add("**Diagnostic notes**\n\n" + "\n".join(f"- {n}" for n in K.TIMER_NOTES))
    lay.add(
        f"Shifts start at {', '.join(f'{h:02d}:00' for h in plant.SHIFT_START_HOURS)} with a "
        f"{plant.CHANGEOVER_S // 60} min planned changeover; the first {plant.RAMP_UP_CYCLES} "
        "cycles after a changeover run slower than normal."
        if has_cycle
        else f"Shifts start at {', '.join(f'{h:02d}:00' for h in plant.SHIFT_START_HOURS)} "
        f"with a {plant.CHANGEOVER_S // 60} min planned changeover."
    )
    lay.table(
        "ts_timer",
        "Troubleshooting: control parameters",
        ("Symptom", "Probable cause", "Check", "Remedy"),
        [(r.symptom, r.cause, r.check, r.remedy) for r in spec.timer_rows],
    )

    # 6 Troubleshooting
    lay.chapter("6", "Troubleshooting", "ch6")
    lay.section(None, "Using this chapter")
    lay.prose("ts_intro")
    lay.add("{INDEX}")
    lay._tbl += 1  # Table 6-1 is the index, rendered after layout
    lay.anchor("index", f"Table {lay._ch}-1")
    for t in spec.topics:
        _topic(lay, t)
    lay.section("sensor", K.TOPIC_SENSOR, new_page=True)
    lay.add(
        "**Typical signature.** One monitored value trends slowly towards a limit, or jumps "
        "beyond it, while the signals that are physically linked to it stay normal."
    )
    lay.table(
        "correlates",
        "Physical correlates of monitored signals",
        ("Signal", "Physically related signals and checks"),
        [(_code_first_word(a), b) for a, b in spec.correlates],
    )
    lay.add("**Diagnostic notes**\n\n" + "\n".join(f"- {n}" for n in K.SENSOR_NOTES))
    lay.page()
    lay.table(
        "ts_sensor",
        "Troubleshooting: suspected sensor drift",
        ("Symptom", "Probable cause", "Check", "Remedy"),
        [(r.symptom, r.cause, r.check, r.remedy) for r in K.SENSOR_ROWS],
    )

    # 7 Maintenance
    lay.chapter("7", "Maintenance", "ch7")
    lay.section(None, "Preventive maintenance")
    lay.prose("maint_intro")
    lay.table(
        "maint",
        "Preventive maintenance intervals",
        ("Task", "Interval", "See"),
        [tuple(m) for m in spec.maintenance],
    )
    lay.section(None, "Recommended spare parts")
    lay.table(
        "spares",
        "Recommended spare parts",
        ("Part", "Quantity to stock"),
        [tuple(s) for s in spec.spares],
    )

    # 8 Energy control (LOTO) - verbatim from loto.py
    review: list[tuple[int, int, L.LotoStep]] = []
    lay.chapter("8", "Energy control procedure (lockout/tagout)", "ch8")
    lay.section("loto_scope", "Scope, purpose and authorisation")
    lay.add(f"> **IMPORTANT - FICTIONAL EQUIPMENT.** {DISCLAIMER}")
    lay.add(f"**Equipment.** {proc.equipment}. Applies to: {', '.join(proc.applies_to)}.")
    lay.add(f"**Purpose.** {proc.purpose}")
    lay.add(f"**Authorisation.** {proc.authorised}")
    lay.add(
        f"**Basis.** This procedure follows the energy control procedure requirements of "
        f"{L.CFR}(c)(4) and the sequence of {L.CFR}(d)(1) to (d)(6), with notification under "
        "(c)(9) and release from lockout or tagout under (e). Each step cites its paragraph. "
        "Steps are carried out in the order given. Steps marked ST30 apply to ST30 only."
        if spec.doc == "weld_controller"
        else f"**Basis.** This procedure follows the energy control procedure requirements of "
        f"{L.CFR}(c)(4) and the sequence of {L.CFR}(d)(1) to (d)(6), with notification under "
        "(c)(9) and release from lockout or tagout under (e). Each step cites its paragraph. "
        "Steps are carried out in the order given."
    )
    lay.section("sec_energy", "Energy sources")
    lay.table(
        "energy",
        "Hazardous energy sources and isolating devices",
        ("Energy", "Source and magnitude", "Isolating device", "Stored or residual energy"),
        [(e.kind, e.source, e.isolating_device, e.stored) for e in proc.energy],
    )
    groups = (
        ("loto_apply", "Preparation, shutdown, isolation and lockout", ("prepare", "shutdown", "isolate", "lock")),
        ("loto_stored", "Stored energy and verification of isolation", ("stored", "verify")),
        ("loto_release", "Release from lockout/tagout", ("release",)),
    )  # fmt: skip
    n = 0
    for key, title, phases in groups:
        lay.section(key, title, new_page=True)
        steps = [s for s in proc.steps if s.phase in phases]
        numbered = [(n + i + 1, s) for i, s in enumerate(steps)]
        n += len(steps)
        lay.table(f"t_{key}", title, ("Step", "Action", f"{L.CFR} paragraph"), _loto_rows(numbered))
        review += [(lay.page_no, i, s) for i, s in numbered]
    lay.add(
        f"**Testing or positioning.** If the equipment must be energised temporarily to test or "
        f"position it, follow {L.CFR}(f)(1): clear tools and materials, remove employees from the "
        "area, remove the locks and tags, energise and test, then de-energise and reapply every "
        "energy control measure in the order of this chapter before work continues."
    )
    if n != len(proc.steps):
        raise ValueError(f"{spec.doc}: LOTO steps not all placed")

    # Appendix A glossary, Appendix B ancillary equipment
    lay.chapter("A", "Glossary", "appx_glossary")
    lay.prose("glossary")
    if spec.appendix:
        ap = spec.appendix
        lay.chapter("B", ap.title, ap.key)
        lay.add(ap.intro)
        lay.section(None, "Process values and limits")
        _spec_tables(lay, ap.assets)
        lay.table(
            None,
            "Alarm and stop messages",
            ("Code", "Message", "Condition or meaning"),
            _message_rows((), ap.assets),
        )
        for i, t in enumerate(ap.topics):
            _topic(lay, t, first=i == 0)
    return lay, review


# --- Cross-references ---------------------------------------------------------------------------
REF_RE = re.compile(r"\{([TSP]):([\w./-]+)\}")


def resolve(text: str, doc: str, layouts: dict[str, Layout]) -> str:
    def sub(m: re.Match[str]) -> str:
        kind, key = m.group(1), m.group(2)
        other = None
        if "/" in key:
            other, key = key.split("/", 1)
        lay = layouts[other or doc]
        if key not in lay.anchors:
            raise KeyError(f"{doc}: unresolved reference {m.group(0)}")
        label, page = lay.anchors[key]
        out = f"page {page}" if kind == "P" else label
        if other:
            return f"{out} of {lay.spec.doc_no} ({lay.spec.title.split(' - ')[0]})"
        return out

    return REF_RE.sub(sub, text)


def _contents(lay: Layout) -> str:
    rows = [
        f"| {('Appendix ' + n) if n.isalpha() else n} | {t} | {p} |" for n, t, p in lay.chapters
    ]
    return "| Chapter | Title | Page |\n|---|---|---|\n" + "\n".join(rows)


def _index(lay: Layout) -> str:
    spec = lay.spec
    topics = [*spec.topics]
    rows = []
    for t in topics:
        label, page = lay.anchors[t.key]
        rows.append((t.rows[0].symptom, t.title, label.replace("Section ", ""), str(page)))
    label, page = lay.anchors["sensor"]
    rows.append(
        ("One signal trending with no change in related signals", K.TOPIC_SENSOR, label.replace("Section ", ""), str(page))
    )  # fmt: skip
    label, page = lay.anchors["ch5"]
    rows.append(
        ("Cycle time stepped at a shift start, process normal", K.TOPIC_TIMER, "5", str(page))
    )
    if spec.appendix:
        for t in spec.appendix.topics:
            label, page = lay.anchors[t.key]
            rows.append((t.rows[0].symptom, t.title, label.replace("Section ", ""), str(page)))
    lines = [
        f"**{lay.anchors['index'][0]} Symptom index**",
        "",
        "| First symptom | Topic | Section | Page |",
        "|---|---|---|---|",
    ]
    lines += ["| " + " | ".join(r) + " |" for r in rows]
    return "\n".join(lines)


# --- Prose (Gemini, cached) ---------------------------------------------------------------------
class ProseSection(BaseModel):
    id: str
    paragraphs: list[str]


class ProseBatch(BaseModel):
    sections: list[ProseSection]


def load_prompt() -> tuple[str, str]:
    raw = PROMPT_PATH.read_text(encoding="utf-8")
    m = re.search(r"version:\s*([\w.]+)", raw.splitlines()[0])
    if not m:
        raise ValueError("manuals prompt has no version header")
    return m.group(1), raw


def prose_specs(spec: K.ManualSpec) -> tuple[K.ProseSpec, ...]:
    return (*K.PROSE, *K.background_specs(spec))


def facts(spec: K.ManualSpec, lay: Layout, layouts: dict[str, Layout]) -> str:
    out = [
        f"Manual: {spec.title} ({spec.doc_no}).",
        f"Equipment: {spec.equipment}",
        "Applies to: " + "; ".join(_asset_label(a) for a in spec.applies_to) + ".",
        "Line L1 runs 24 hours a day in three shifts; each shift starts with a planned changeover.",
        "Chapters: "
        + "; ".join(
            f"{'Appendix ' + n if n.isalpha() else 'Chapter ' + n} {t}" for n, t, _ in lay.chapters
        )
        + ".",
        "Components:",
        *[f"- {c}: {f}" for c, f in spec.components],
        "Operating parameters:",
        *[f"- {p}: {v} ({n})" for p, v, n in spec.params],
        "Monitored signals (normal range; limits):",
    ]
    for aid in (*spec.applies_to, *(spec.appendix.assets if spec.appendix else ())):
        for t in plant.asset(aid).tags:
            lim = ", ".join(
                f"{name} {K.g(v)}"
                for name, v in (
                    ("alarm low", t.alarm_lo),
                    ("alarm high", t.alarm_hi),
                    ("trip low", t.trip_lo),
                    ("trip high", t.trip_hi),
                )
                if v is not None
            )
            out.append(
                f"- {aid} {t.tag}: {t.description}; {K.g(t.normal_lo)} to {K.g(t.normal_hi)} {t.unit}"
                + (f"; {lim} {t.unit}" if lim else "")
            )
    out.append("Troubleshooting topics and their typical signatures:")
    for t in (*spec.topics, *(spec.appendix.topics if spec.appendix else ())):
        sig = resolve(t.signature, spec.doc, layouts).replace("`", "")
        out.append(f"- {t.title}: {sig}")
    out.append(
        "Maintenance tasks: " + "; ".join(f"{a} ({b})" for a, b, _ in spec.maintenance) + "."
    )
    out.append("Hazards: " + "; ".join(f"{h} at {w}" for h, w, _ in spec.hazards) + ".")
    return "\n".join(out)


def sections_block(specs: tuple[K.ProseSpec, ...]) -> str:
    return "\n".join(
        json.dumps({"id": s.id, "title": s.title, "write": s.brief, "target_words": s.words})
        for s in specs
    )


def validate_prose(batch: ProseBatch, specs: tuple[K.ProseSpec, ...], facts_text: str) -> list[str]:
    """Problems with an LLM prose batch (empty list = accept)."""
    problems: list[str] = []
    allowed = set(NUM_RE.findall(facts_text))
    want = {s.id: s for s in specs}
    got = {s.id: s for s in batch.sections}
    missing = sorted(set(want) - set(got))
    if missing:
        problems.append(f"missing sections: {missing}")
    for sid, sec in got.items():
        if sid not in want:
            problems.append(f"unexpected section id {sid!r}")
            continue
        if not sec.paragraphs or not all(p.strip() for p in sec.paragraphs):
            problems.append(f"{sid}: empty paragraph")
        text = " ".join(sec.paragraphs)
        words = len(text.split())
        if not (0.4 * want[sid].words <= words <= 2.2 * want[sid].words):
            problems.append(f"{sid}: {words} words, target {want[sid].words}")
        bad_nums = sorted({n for n in NUM_RE.findall(text) if n not in allowed})
        if bad_nums:
            problems.append(f"{sid}: numbers not in the facts: {bad_nums}")
        if BANNED_SAFETY_WORDS.search(text):
            problems.append(f"{sid}: uses lockout/tagout wording")
        if brand_hits(text):
            problems.append(f"{sid}: names a brand: {brand_hits(text)}")
        if re.search(r"(^|\n)\s*(#|[-*] |\d+\. )|\|", "\n".join(sec.paragraphs)):
            problems.append(f"{sid}: contains Markdown structure")
    return problems


@dataclass
class ProseGen:
    mode: Mode = "cached"
    cache_dir: Path = CACHE_DIR
    llm: Any = None
    calls: int = 0
    cache_hits: int = 0
    usd: float = 0.0
    used_keys: set[str] = field(default_factory=set)

    def key(self, version: str, prompt: str) -> str:
        h = hashlib.sha256()
        for part in (
            MODEL_ID,
            version,
            json.dumps(ProseBatch.model_json_schema(), sort_keys=True),
            prompt,
        ):
            h.update(part.encode())
            h.update(b"\x00")
        return h.hexdigest()

    def _gen_config(self) -> Any:
        from google.genai import types

        return types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=ProseBatch,
            thinking_config=types.ThinkingConfig(thinking_level=types.ThinkingLevel.LOW),
        )

    async def get(
        self, doc: str, version: str, prompt: str, specs: tuple[K.ProseSpec, ...], facts_text: str
    ) -> dict[str, list[str]]:
        key = self.key(version, prompt)
        self.used_keys.add(key)
        path = self.cache_dir / f"{key}.json"
        if path.exists():
            self.cache_hits += 1
            batch = ProseBatch.model_validate(json.loads(path.read_text())["output"])
            problems = validate_prose(batch, specs, facts_text)
            if problems:
                raise ValueError(f"{doc}: cached prose no longer valid: {problems}")
            return {s.id: s.paragraphs for s in batch.sections}
        if self.mode != "live":
            raise FileNotFoundError(
                f"{doc}: no cached prose ({path.name}); run with --mode live (costs money)"
            )
        if self.llm is None:
            from agents.llm import LLM

            self.llm = LLM()
        attempt_prompt = prompt
        usage: list[dict[str, Any]] = []
        problems: list[str] = []
        for attempt in range(3):
            res = await self.llm.generate(
                MODEL_ID, attempt_prompt, self._gen_config(), agent="simulator.manuals"
            )
            self.calls += 1
            self.usd += res.usage.usd
            usage.append(
                {
                    "input_tokens": res.usage.input_tokens,
                    "output_tokens": res.usage.output_tokens,
                    "thinking_tokens": res.usage.thinking_tokens,
                    "usd": round(res.usage.usd, 6),
                }
            )
            try:
                batch = ProseBatch.model_validate_json(res.response.text)
                problems = validate_prose(batch, specs, facts_text)
            except (ValidationError, ValueError, TypeError) as exc:
                problems = [f"invalid JSON: {exc}"]
            if not problems:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(
                    json.dumps(
                        {
                            "doc": doc,
                            "prompt": "manuals",
                            "prompt_version": version,
                            "model_id": MODEL_ID,
                            "attempts": attempt + 1,
                            "usage": usage,
                            "output": batch.model_dump(),
                        },
                        indent=1,
                        sort_keys=True,
                    )
                    + "\n"
                )
                return {s.id: s.paragraphs for s in batch.sections}
            log.warning("%s: prose attempt %d rejected: %s", doc, attempt + 1, problems)
            attempt_prompt = (
                prompt
                + "\n\nYour previous answer was rejected for these reasons; fix all of them:\n"
                + "\n".join(f"- {p}" for p in problems)
            )
        raise RuntimeError(f"{doc}: prose rejected 3 times: {problems}")


# --- Render -------------------------------------------------------------------------------------
def render(lay: Layout, prose: dict[str, list[str]], layouts: dict[str, Layout]) -> str:
    spec = lay.spec
    total = len(lay.pages)
    short = spec.title.split(" - ")[0]
    out: list[str] = []
    for i, blocks in enumerate(lay.pages, 1):
        body: list[str] = []
        for b in blocks:
            if b == "{CONTENTS}":
                b = _contents(lay)
            elif b == "{INDEX}":
                b = _index(lay)
            m = re.fullmatch(r"\{PROSE:(\w+)\}", b)
            if m:
                body.append("\n\n".join(p.strip() for p in prose[m.group(1)]))
            else:
                body.append(resolve(b, spec.doc, layouts))
        footer = (
            f"*{spec.doc_no} Rev. {REVISION} | {short} | Page {i} of {total} | "
            "Fictional equipment for demonstration only*"
        )
        out.append(f"<!-- page {i} -->\n\n" + "\n\n".join(body) + f"\n\n---\n{footer}\n")
    return "\n".join(out)


def loto_review(reviews: dict[str, list[tuple[int, int, L.LotoStep]]]) -> str:
    digest = hashlib.sha256(
        json.dumps(
            {d: [(p, n, s.cfr, s.text) for p, n, s in r] for d, r in reviews.items()},
            sort_keys=True,
        ).encode()
    ).hexdigest()
    lines = [
        "# LOTO review: energy control procedures in the five manuals",
        "",
        "Generated by `uv run python -m simulator.manuals.build` from `simulator/manuals/loto.py`. "
        "Do not edit by hand; edit `loto.py`, rebuild, and review again.",
        "",
        "**Status: PENDING HUMAN REVIEW.** A human must read every step below and approve it "
        "verbatim before the manuals are used in a demo (CLAUDE.md hard rule 5). Record the "
        "approval (name, date, content hash) in `docs/DECISIONS.md`.",
        "",
        f"- Regulation: OSHA {L.CFR} (Control of Hazardous Energy). Paragraph numbers checked "
        f"against the eCFR text on {L.ECFR_CHECKED}: <{L.ECFR_URL}>",
        "- Steps were written by hand (not generated by an LLM). The equipment is fictional; each "
        "manual carries the disclaimer below.",
        f"- Content hash (sha256 of doc, page, step, citation, text): `{digest}`",
        "",
        f"> {DISCLAIMER}",
        "",
        "Review checklist: (1) every energy source in Table 8-1 is isolated, locked and its stored "
        "energy released; (2) the order follows (d)(1) to (d)(6) then (e); (3) notification "
        "before and after; (4) each step is one clear imperative sentence; (5) the CFR paragraph "
        "matches the action.",
        "",
    ]
    for doc, rows in reviews.items():
        lines += [
            f"## {doc}",
            "",
            "| Manual | Page | Step | Exact text | CFR citation | Approved |",
            "|---|---|---|---|---|---|",
        ]
        lines += [f"| {doc} | {p} | {n} | {s.text} | {s.citation} | [ ] |" for p, n, s in rows]
        lines.append("")
    return "\n".join(lines)


async def build_all(
    mode: Mode, out_dir: Path = MANUAL_DIR, review_path: Path = REVIEW_PATH
) -> ProseGen:
    version, template = load_prompt()
    layouts: dict[str, Layout] = {}
    reviews: dict[str, list[tuple[int, int, L.LotoStep]]] = {}
    for doc in DOCS:
        layouts[doc], reviews[doc] = layout(K.SPECS[doc])
    gen = ProseGen(mode=mode)
    jobs = []
    for doc in DOCS:
        spec = K.SPECS[doc]
        specs = prose_specs(spec)
        f = facts(spec, layouts[doc], layouts)
        prompt = template.replace("{facts}", f).replace("{sections}", sections_block(specs))
        jobs.append(gen.get(doc, version, prompt, specs, f))
    results = await asyncio.gather(*jobs)
    for doc, prose in zip(DOCS, results, strict=True):
        text = render(layouts[doc], prose, layouts)
        if re.search(r"\{(?:[TSP]|PROSE):|\{CONTENTS\}|\{INDEX\}", text):
            raise ValueError(f"{doc}: unresolved placeholder")
        parse_pages(text, doc)  # format check
        (out_dir / f"{doc}.md").write_text(text, encoding="utf-8")
    review_path.parent.mkdir(parents=True, exist_ok=True)
    review_path.write_text(loto_review(reviews), encoding="utf-8")
    return gen


# --- Live token count and cache probe ------------------------------------------------------------
def _client() -> Any:
    from google import genai

    return genai.Client(
        vertexai=True, project=config.PROJECT, location=config.location_for(MODEL_ID)
    )


def manuals_corpus() -> str:
    from simulator.manuals import full_text

    return "\n\n".join(f"=== MANUAL: {d} ===\n{full_text(d)}" for d in DOCS)


def count_tokens() -> int:
    client = _client()  # keep a reference: the client closes its HTTP pool when collected
    resp = client.models.count_tokens(model=MODEL_ID, contents=manuals_corpus())
    return int(resp.total_tokens or 0)


async def cache_probe() -> dict[str, Any]:
    """Create one explicit cache (TTL 120 s), use it once through agents.llm, delete it."""
    from google.genai import types

    from agents.llm import LLM

    client = _client()
    cache = client.caches.create(
        model=MODEL_ID,
        config=types.CreateCachedContentConfig(
            display_name="andon-manuals-probe",
            contents=[types.Content(role="user", parts=[types.Part(text=manuals_corpus())])],
            system_instruction="Answer only from the manuals.",
            ttl="120s",
        ),
    )
    out: dict[str, Any] = {
        "cache_name": cache.name,
        "cache_tokens": getattr(cache.usage_metadata, "total_token_count", None),
    }
    try:
        res = await LLM().generate(
            MODEL_ID,
            "Which table in the compressed_air manual lists the hazardous energy sources? Answer in 10 words.",
            types.GenerateContentConfig(
                cached_content=cache.name,
                thinking_config=types.ThinkingConfig(thinking_level=types.ThinkingLevel.LOW),
            ),
            agent="simulator.manuals.cache_probe",
        )
        out |= {
            "answer": res.response.text,
            "input_tokens": res.usage.input_tokens,
            "cached_tokens": res.usage.cached_tokens,
            "usd_generate": round(res.usage.usd, 6),
        }
    finally:
        client.caches.delete(name=cache.name)
        out["deleted"] = True
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--mode", choices=["cached", "live"], default="cached")
    ap.add_argument("--count-tokens", action="store_true")
    ap.add_argument("--cache-probe", action="store_true")
    ap.add_argument(
        "--prune", action="store_true", help="delete cache entries not used by this build"
    )
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    if not (args.count_tokens or args.cache_probe):
        gen = asyncio.run(build_all(args.mode))
        if args.prune:
            for f in CACHE_DIR.glob("*.json"):
                if f.stem not in gen.used_keys:
                    f.unlink()
        print(
            f"manuals: mode={args.mode} live_calls={gen.calls} cache_hits={gen.cache_hits} "
            f"cost=${gen.usd:.4f}"
        )
    if args.count_tokens:
        n = count_tokens()
        print(f"count_tokens({MODEL_ID}, 5 manuals) = {n}")
    if args.cache_probe:
        print(json.dumps(asyncio.run(cache_probe()), indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
