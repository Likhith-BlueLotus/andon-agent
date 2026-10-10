"""Generated text: shift notes and historical work orders (SYNTHETIC_DATA_SPEC §5).

Honesty rules enforced here:

* Text generators see **only visible symptoms** (alarms an operator saw, the stop message,
  changeovers). They never receive the cause class, the root asset or the onset.
* Generated text is validated (Pydantic schema + a banned-term check so no note names a cause);
  any slot that fails falls back to a fixed template.
* External text (MaintIE short texts) is wrapped as untrusted *style* exemplars only.
* Every Gemini call goes through ``agents.llm.LLM`` with ``gemini-3.1-flash-lite`` and structured
  output, and is cached on disk by content hash, so reruns cost $0 and are deterministic.

Three modes: ``template`` (no LLM), ``cached`` (cache only; template on a miss), ``live`` (call
Gemini on a miss, then cache).
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

import numpy as np
from pydantic import BaseModel, Field, ValidationError

import config
from agents.schemas import CauseClass
from simulator import plant
from simulator.alarms import Alarm
from simulator.imperfections import Note
from simulator.plant import Timeline

log = logging.getLogger("andon.sim.text")

PROMPT_DIR = Path(__file__).parent / "prompts"
DEFAULT_CACHE_DIR = Path("data/cache/text")
TextMode = Literal["template", "cached", "live"]
C = CauseClass

AUTHOR_ROLES = ("line_lead", "operator", "maintenance_tech", "quality_inspector")

# Words that would name a cause or a diagnosis. A note containing one is rejected.
BANNED_TERMS: tuple[str, ...] = (
    "cavitat", "tip wear", "worn tip", "tips worn", "tip worn", "bearing defect", "bearing fail",
    "bearing damage", "bad bearing", "leak", "drift", "timer", "misalign", "blockage", "blocked line",
    "clog", "choke", "recipe", "wrong setpoint", "setpoint wrong", "fan fail", "fan fault",
    "glitch", "false alarm", "spurious", "sensor fault", "faulty sensor", "root cause", "overheat",
    "weld_tip", "sealer_pump", "conveyor_bearing", "servo_overheat", "air_pressure_drop",
    "sensor_drift", "plc_timer", "coolant_blockage", "fixture_misalignment", "changeover_error",
    "no_fault",
)  # fmt: skip


def banned_hits(text: str) -> list[str]:
    t = text.lower()
    return [w for w in BANNED_TERMS if w in t]


def load_prompt(name: str) -> tuple[str, str]:
    """(version, template) of simulator/prompts/<name>.md; version comes from the header."""
    raw = (PROMPT_DIR / f"{name}.md").read_text()
    m = re.search(r"version:\s*([\w.]+)", raw.splitlines()[0])
    if not m:
        raise ValueError(f"prompt {name} has no version header")
    return m.group(1), raw


def _local(ts: datetime) -> datetime:
    return ts.astimezone(UTC) + timedelta(seconds=plant.PLANT_UTC_OFFSET_S)


def hhmm(ts: datetime) -> str:
    return _local(ts).strftime("%H:%M")


# --- Structured LLM text with cache ----------------------------------------------------------
class NoteText(BaseModel):
    slot: int
    text: str = Field(max_length=400)


class NoteBatch(BaseModel):
    notes: list[NoteText]


class WOText(BaseModel):
    row: int
    symptom: str = Field(max_length=200)
    action: str = Field(max_length=220)
    outcome: str = Field(max_length=200)


class WOBatch(BaseModel):
    rows: list[WOText]


@dataclass
class TextGen:
    """Structured-output text generation through agents.llm with a content-hash disk cache."""

    mode: TextMode = "template"
    llm: Any = None  # agents.llm.LLM; created lazily in live mode
    cache_dir: Path = DEFAULT_CACHE_DIR
    model_id: str = config.FLASH_LITE
    calls: int = 0
    cache_hits: int = 0
    misses_templated: int = 0
    usd: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    failures: list[str] = field(default_factory=list)
    _loop: Any = field(default=None, repr=False)
    used_keys: set[str] = field(default_factory=set)

    def prune(self) -> int:
        """Delete cache entries not used in this run (after a full regeneration). Returns count."""
        n = 0
        for f in self.cache_dir.rglob("*.json"):
            if f.stem not in self.used_keys:
                f.unlink()
                n += 1
        return n

    def run(self, coro: Any) -> Any:
        """Run a coroutine on one persistent event loop (the genai async client is bound to the
        loop it was first used on, so ``asyncio.run`` per call would break the second call)."""
        import asyncio

        if self._loop is None:
            self._loop = asyncio.new_event_loop()
        return self._loop.run_until_complete(coro)

    def key(self, prompt_version: str, prompt: str, schema: type[BaseModel]) -> str:
        h = hashlib.sha256()
        for part in (
            self.model_id,
            prompt_version,
            json.dumps(schema.model_json_schema(), sort_keys=True),
            prompt,
        ):
            h.update(part.encode())
            h.update(b"\x00")
        return h.hexdigest()

    def _path(self, key: str) -> Path:
        return self.cache_dir / key[:2] / f"{key}.json"

    def _gen_config(self, schema: type[BaseModel]) -> Any:
        from google.genai import types

        return types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=schema,
            thinking_config=types.ThinkingConfig(thinking_level=types.ThinkingLevel.MINIMAL),
        )

    async def structured(
        self, prompt_name: str, prompt_version: str, prompt: str, schema: type[BaseModel]
    ) -> BaseModel | None:
        if self.mode == "template":
            return None
        key = self.key(prompt_version, prompt, schema)
        self.used_keys.add(key)
        path = self._path(key)
        if path.exists():
            self.cache_hits += 1
            return schema.model_validate(json.loads(path.read_text())["output"])
        if self.mode != "live":
            self.misses_templated += 1
            return None
        if self.llm is None:
            from agents.llm import LLM

            self.llm = LLM()
        last_err: Exception | None = None
        for _attempt in range(2):  # one retry on a parse failure, then fall back to templates
            res = await self.llm.generate(
                self.model_id, prompt, self._gen_config(schema), agent=f"simulator.{prompt_name}"
            )
            self.calls += 1
            self.usd += res.usage.usd
            self.input_tokens += res.usage.input_tokens
            self.output_tokens += res.usage.output_tokens + res.usage.thinking_tokens
            try:
                out = schema.model_validate_json(res.response.text)
            except (ValidationError, ValueError, TypeError) as exc:
                last_err = exc
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(
                    {
                        "prompt": prompt_name,
                        "prompt_version": prompt_version,
                        "model_id": self.model_id,
                        "usage": {
                            "input_tokens": res.usage.input_tokens,
                            "output_tokens": res.usage.output_tokens,
                            "thinking_tokens": res.usage.thinking_tokens,
                            "usd": round(res.usage.usd, 6),
                        },
                        "output": out.model_dump(),
                    },
                    indent=1,
                    sort_keys=True,
                )
            )
            return out
        self.failures.append(f"{prompt_name}: {last_err!r}")
        return None

    def summary(self) -> str:
        return (
            f"text generation: mode={self.mode} live_calls={self.calls} cache_hits={self.cache_hits} "
            f"templated_misses={self.misses_templated} tokens_in={self.input_tokens} "
            f"tokens_out={self.output_tokens} cost=${self.usd:.4f}"
        )


# --- Shift notes -----------------------------------------------------------------------------
@dataclass
class NoteSlot:
    slot: int
    ts: datetime
    author_role: str
    language: Literal["english", "hinglish"]
    facts: list[str]


def _alarm_facts(alarms: list[Alarm], t0: datetime, t1: datetime, limit: int = 6) -> list[str]:
    seen: dict[str, tuple[datetime, int, str]] = {}
    for a in alarms:
        if t0 <= a.ts < t1 and a.severity != "info":
            first, cnt, text = seen.get(a.code, (a.ts, 0, a.text))
            seen[a.code] = (first, cnt + 1, text)
    ranked = sorted(seen.values(), key=lambda v: (-v[1], v[0]))[:limit]
    return [
        f"{hhmm(f)} alarm '{txt}'" + (f" x{c}" if c > 1 else "") for f, c, txt in sorted(ranked)
    ]


def note_slots(
    tl: Timeline, alarms: list[Alarm], stop_text: str, rng: np.random.Generator
) -> list[NoteSlot]:
    """2-6 note slots in the last 24 h: shift handovers, an optional mid-shift remark, and the
    stop note. Facts per slot are only what was visible before that slot's time."""
    slots: list[NoteSlot] = []
    stop = tl.stop
    starts = [int(i) for i in tl.shift_starts if tl.n - i <= 24 * 3600 and i < tl.n - 600]
    prev = stop - timedelta(hours=24)
    for i in starts[-3:]:
        k = list(tl.shift_starts).index(i)
        ts = tl.ts(i) + timedelta(minutes=int(rng.integers(16, 35)))
        if ts >= stop:
            continue
        before = tl.models[k - 1] if k > 0 else tl.first_model
        facts = _alarm_facts(alarms, prev, tl.ts(i))
        if not facts:
            facts = ["no major alarms in previous shift"]
        if tl.models[k] != before:
            facts.append(
                f"{hhmm(tl.ts(i))} changeover done, model {before} -> model {tl.models[k]}"
            )
        else:
            facts.append(f"{hhmm(tl.ts(i))} shift start, running model {tl.models[k]}")
        slots.append(NoteSlot(0, ts, "line_lead", "english", facts))
        prev = tl.ts(i)
    mid = stop - timedelta(minutes=int(rng.integers(45, 150)))
    mid_facts = _alarm_facts(alarms, mid - timedelta(hours=2), mid, limit=3)
    if mid_facts and rng.random() < 0.7:
        slots.append(
            NoteSlot(
                0, mid, str(rng.choice(["operator", "quality_inspector"])), "english", mid_facts
            )
        )
    stop_facts = [f"{hhmm(stop)} line stopped: {stop_text}"]
    stop_facts += _alarm_facts(alarms, stop - timedelta(minutes=30), stop, limit=4)
    stop_facts.append("maintenance called")
    slots.append(
        NoteSlot(
            0,
            stop + timedelta(minutes=int(rng.integers(3, 9))),
            "maintenance_tech",
            "english",
            stop_facts,
        )
    )
    slots.sort(key=lambda s: s.ts)
    slots = slots[-6:]
    if len(slots) < 2:
        slots.insert(0, NoteSlot(0, stop - timedelta(hours=3), "line_lead", "english",
                                 ["shift running, no issues reported"]))  # fmt: skip
    for j, s in enumerate(slots):
        s.slot = j + 1
        s.language = "hinglish" if rng.random() < 0.45 else "english"
    return slots


_EN_TEMPLATES = (
    "{facts}. {tail}",
    "{facts} -- {tail}",
    "Shift log: {facts}. {tail}",
)
_HI_TAILS = ("next shift ko inform kiya", "maint ko bola", "dekh rahe hai", "QA ko inform kiya")
_EN_TAILS = ("informed next shift", "maint informed", "monitoring", "QA informed")


def template_note_text(slot: NoteSlot, rng: np.random.Generator) -> str:
    facts = "; ".join(f.replace(" alarm ", " ") for f in slot.facts[:4])
    if slot.language == "hinglish":
        return f"{facts}. {rng.choice(_HI_TAILS)}"
    return str(rng.choice(_EN_TEMPLATES)).format(facts=facts, tail=rng.choice(_EN_TAILS))


async def shift_notes(
    scenario_id: str, slots: list[NoteSlot], gen: TextGen, rng: np.random.Generator
) -> list[Note]:
    version, tmpl = load_prompt("shift_notes")
    payload = [
        {
            "slot": s.slot,
            "time": hhmm(s.ts),
            "author_role": s.author_role,
            "language": s.language,
            "facts": s.facts,
        }
        for s in slots
    ]
    prompt = tmpl.replace("{slots_json}", json.dumps(payload, indent=1))
    out = await gen.structured("shift_notes", version, prompt, NoteBatch)
    by_slot: dict[int, str] = {}
    if isinstance(out, NoteBatch):
        for nt in out.notes:
            text = " ".join(nt.text.split())
            if nt.slot in by_slot or not text or banned_hits(text):
                if banned_hits(text):
                    gen.failures.append(f"{scenario_id} slot {nt.slot}: banned {banned_hits(text)}")
                continue
            by_slot[nt.slot] = text
    notes = []
    for s in slots:
        text = by_slot.get(s.slot) or template_note_text(s, rng)
        notes.append(Note(s.ts, s.author_role, text, f"{scenario_id}-N{s.slot:02d}"))
    return notes


# --- Red herrings ----------------------------------------------------------------------------
_HERRING_NOTES = (
    "{station} phir se awaaz kar raha hai, last week bhi same tha. shayad wahi problem hai, check karo",
    "operator says {station} acting up again since morning, pls check {name} first",
    "{name} ka behaviour theek nahi lag raha, kal bhi issue tha. maint ko dikhana",
    "{station} looks suspicious, saw it hesitate couple of times. probably the reason for today's trouble",
)
_HERRING_WO = (
    ("{station} intermittent fault, opr suspects cause of line issues", "chkd, minor adj made, monitor",
     "ok for now, recheck if recurs"),
    ("{station} unusual noise reported by opr", "insp done, nothing major found, cleaned + tightened",
     "running, keep under observation"),
    ("{station} hesitation during cycle", "chk wiring + sensors, reseated connector", "monitor"),
)  # fmt: skip


def red_herring_note(blamed: str, ts: datetime, scenario_id: str, rng: np.random.Generator) -> Note:
    a = plant.asset(blamed)
    text = str(rng.choice(_HERRING_NOTES)).format(station=a.station, name=a.name)
    return Note(ts, "operator", text, f"{scenario_id}-N90")


def red_herring_wo(
    blamed: str, date: datetime, wo_id: str, rng: np.random.Generator
) -> dict[str, Any]:
    a = plant.asset(blamed)
    sym, act, out = _HERRING_WO[int(rng.integers(len(_HERRING_WO)))]
    return {
        "wo_id": wo_id,
        "date": date,
        "asset_id": blamed,
        "symptom": sym.format(station=a.station),
        "action": act,
        "outcome": out,
        "technician_role": str(rng.choice(["maintenance_tech", "electrician"])),
    }


# --- Historical work orders ------------------------------------------------------------------
@dataclass(frozen=True)
class Theme:
    name: str
    cause: CauseClass | None
    template: tuple[str, str, str]  # symptom, action, outcome (template mode / fallback)


THEMES: dict[str, tuple[Theme, ...]] = {
    "press_hydraulics": (
        Theme("hydraulic oil weeping at fitting / internal pump leakage", C.HYDRAULIC_DEGRADATION,
              ("press slow, pressure not reaching sp", "repl pump case seal, chk fittings", "pressure ok")),
        Theme("oil temp high, cooler fouled", C.HYDRAULIC_DEGRADATION,
              ("oil temp hi alarm", "cleaned cooler core, chkd fan", "temp back to normal")),
        Theme("proportional valve slow response", C.HYDRAULIC_DEGRADATION,
              ("press cycle slow", "valve spool cleaned, retuned", "cycle ok")),
        Theme("pressure setpoint not matching model after changeover", C.CHANGEOVER_ERROR,
              ("press pressure low after model chg", "corrected setpoint per model sheet", "ok")),
        Theme("filter element change pm", None, ("pm due", "repl return filter", "done")),
        Theme("pressure transducer reading off", C.SENSOR_DRIFT,
              ("pressure reading off vs gauge", "repl transducer", "reading matches gauge")),
        Theme("way lube refill", None, ("lube low alarm", "refilled lube tank", "ok")),
    ),
    "weld_controller": (
        Theme("electrode tips worn, tip dresser", C.WELD_TIP_WEAR,
              ("weld qa alarms, current stepping up", "tips changed, dresser cutter repl", "welds ok")),
        Theme("servo gun drive over temperature, cabinet fan", C.SERVO_OVERHEAT,
              ("servo temp hi alarm", "repl cabinet fan, cleaned filter", "temp normal")),
        Theme("low coolant flow to gun, strainer / hose", C.COOLANT_BLOCKAGE,
              ("coolant flow lo", "flushed line, cleaned strainer", "flow ok")),
        Theme("clamp / locator pin out of position", C.FIXTURE_MISALIGNMENT,
              ("clamp retry alarms", "realigned locator pin, chk clamp", "ok")),
        Theme("weld cable / shunt worn", None, ("weld current unstable", "repl secondary cable", "ok")),
        Theme("cycle timer parameter changed, restored", C.PLC_TIMER_MISCONFIG,
              ("cycle time longer than std", "restored timer param from backup", "ct normal")),
        Theme("servo temp sensor reading wrong", C.SENSOR_DRIFT,
              ("servo temp reading hi but drive cool", "repl temp sensor", "reading ok")),
        Theme("gun air regulator adjust", None, ("gun air low", "adj regulator", "ok")),
    ),
    "sealer_pump": (
        Theme("pump inlet starved / air in material line", C.SEALER_PUMP_CAVITATION,
              ("bead skipping, pressure pulsing", "drum chg, bled air from line", "bead ok")),
        Theme("nozzle partly blocked", None, ("bead thin", "cleaned nozzle", "ok")),
        Theme("heated hose fault", None, ("hose temp lo", "repl heater controller", "ok")),
        Theme("pump seal wear", None, ("material at pump rod", "repl seals", "ok")),
        Theme("pressure transducer calibration", C.SENSOR_DRIFT,
              ("pressure reading high vs gauge", "recal transducer", "ok")),
    ),
    "conveyor_drive": (
        Theme("drive end bearing noisy / rough", C.CONVEYOR_BEARING_DEFECT,
              ("conveyor noise, vib hi", "repl de bearing, aligned", "vib normal")),
        Theme("chain tension", None, ("chain slack", "adj tensioner", "ok")),
        Theme("gearbox oil top up", None, ("pm", "topped up gbx oil", "done")),
        Theme("bearing temperature sensor wrong", C.SENSOR_DRIFT,
              ("brg temp hi but housing cool", "repl rtd", "reading ok")),
        Theme("photo eye misaligned", None, ("part not detected", "realigned photo eye", "ok")),
    ),
    "vision": (
        Theme("camera lens dirty", None, ("false rejects", "cleaned lens + cover glass", "ok")),
        Theme("lighting module failing", None, ("image dark", "repl light module", "ok")),
        Theme("camera comm cable loose", None, ("cam comm retry alarms", "reseated cable", "ok")),
    ),
    "compressed_air": (
        Theme("air leak at quick coupling / hose", C.AIR_PRESSURE_DROP,
              ("header pressure low, comp running loaded", "fixed leak at coupling", "pressure ok")),
        Theme("condensate drain stuck open", C.AIR_PRESSURE_DROP,
              ("air hissing at drain", "repl drain valve", "ok")),
        Theme("compressor oil change pm", None, ("pm", "oil + filter chg", "done")),
        Theme("air dryer fault", None, ("dryer alarm", "reset dryer, chk fan", "ok")),
        Theme("intake filter change", None, ("pm", "repl intake filter", "done")),
    ),
    "chiller": (
        Theme("condenser coil dirty", None, ("supply temp creeping up", "cleaned condenser coil", "ok")),
        Theme("pump strainer clean", None, ("flow lo", "cleaned strainer", "ok")),
    ),
}  # fmt: skip

WO_ASSET_WEIGHTS: dict[str, float] = {
    "ST10-PRS": 0.15, "ST20-WLD": 0.2, "ST30-WLD": 0.2, "ST40-SLR": 0.13, "ST50-CNV": 0.12,
    "ST60-VIS": 0.06, "UT-AIR": 0.1, "UT-CHL": 0.04,
}  # fmt: skip
TECH_ROLES = ("maintenance_tech", "electrician", "fitter", "controls_engineer")
WO_START = datetime(2024, 9, 1, tzinfo=UTC)
WO_END = datetime(2026, 7, 31, tzinfo=UTC)


def wo_skeleton(n: int, seed: int, wrong_first_frac: float = 0.05) -> list[dict[str, Any]]:
    """Deterministic structure of the WO history (texts are filled later). ``wrong_first_frac``
    of rows are wrong first diagnoses, each followed by a correction WO on the same asset."""
    rng = plant.rng_for(seed, "wo_skeleton")
    n_pairs = round(n * wrong_first_frac)
    n_normal = n - 2 * n_pairs
    assets = list(WO_ASSET_WEIGHTS)
    w = np.array([WO_ASSET_WEIGHTS[a] for a in assets])
    span = int((WO_END - WO_START).total_seconds())
    rows: list[dict[str, Any]] = []
    for _ in range(n_normal):
        aid = assets[int(rng.choice(len(assets), p=w / w.sum()))]
        themes = THEMES[plant.asset(aid).asset_type]
        th = themes[int(rng.integers(len(themes)))]
        rows.append({"asset_id": aid, "theme": th.name, "cause": th.cause, "kind": "normal",
                     "date": WO_START + timedelta(seconds=int(rng.integers(0, span)))})  # fmt: skip
    pair_assets = [a for a in assets if any(t.cause for t in THEMES[plant.asset(a).asset_type])]
    pw = np.array([WO_ASSET_WEIGHTS[a] for a in pair_assets])
    for _ in range(n_pairs):
        aid = pair_assets[int(rng.choice(len(pair_assets), p=pw / pw.sum()))]
        themes = THEMES[plant.asset(aid).asset_type]
        caused = [t for t in themes if t.cause is not None]
        right = caused[int(rng.integers(len(caused)))]
        wrong_opts = [t for t in themes if t.name != right.name]
        wrong = wrong_opts[int(rng.integers(len(wrong_opts)))]
        d0 = WO_START + timedelta(seconds=int(rng.integers(0, span - 12 * 86400)))
        d1 = d0 + timedelta(days=float(rng.uniform(0.5, 10)))
        rows.append({"asset_id": aid, "theme": wrong.name, "cause": wrong.cause, "kind": "wrong_first", "date": d0,
                     "true_theme": right.name, "true_cause": right.cause})  # fmt: skip
        rows.append({"asset_id": aid, "theme": right.name, "cause": right.cause, "kind": "correction", "date": d1,
                     "_pair_of": d0})  # fmt: skip
    rows.sort(key=lambda r: (r["date"], r["asset_id"]))
    # ids and correction references
    for i, r in enumerate(rows):
        r["wo_id"] = f"WO-{r['date']:%y}{i + 1:05d}"
        r["technician_role"] = TECH_ROLES[int(rng.integers(len(TECH_ROLES)))]
    by_key = {(r["asset_id"], r["date"]): r for r in rows if r["kind"] == "wrong_first"}
    for r in rows:
        if r["kind"] == "correction":
            first = by_key[(r["asset_id"], r.pop("_pair_of"))]
            r["ref"] = first["wo_id"]
            first["corrected_by"] = r["wo_id"]
    return rows


def load_style_examples(path: Path, k: int, seed: int) -> list[str]:
    """k short MaintIE texts (untrusted, style only). Empty list if the dataset is absent."""
    f = path / "gold_release.json"
    if not f.exists():
        return []
    data = json.loads(f.read_text())
    texts = sorted({" ".join(str(d.get("text", "")).replace("<id>", "").split()) for d in data})
    texts = [t for t in texts if 8 <= len(t) <= 60 and "<" not in t and ">" not in t]
    rng = plant.rng_for(seed, "maintie")
    idx = rng.choice(len(texts), size=min(k, len(texts)), replace=False)
    return [texts[i] for i in sorted(idx.tolist())]


def _template_wo(r: dict[str, Any]) -> tuple[str, str, str]:
    th = next(t for t in THEMES[plant.asset(r["asset_id"]).asset_type] if t.name == r["theme"])
    sym, act, out = th.template
    if r["kind"] == "wrong_first":
        out = "not fixed, fault came back"
    elif r["kind"] == "correction":
        out = f"{out} - prev {r['ref']} did not fix"
    return sym, act, out


async def build_work_orders(
    gen: TextGen, n: int, seed: int, maintie_dir: Path, batch: int = 50
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Returns (work_order rows for the store, label rows kept out of the store)."""
    import asyncio

    rows = wo_skeleton(n, seed)
    version, tmpl = load_prompt("work_orders")
    sem = asyncio.Semaphore(4)

    async def one(b: int, chunk: list[dict[str, Any]]) -> dict[int, WOText]:
        ex = load_style_examples(maintie_dir, 25, seed * 1000 + b)
        rj = [
            {"row": i, "asset": f"{r['asset_id']} ({plant.asset(r['asset_id']).asset_type})", "theme": r["theme"],
             "kind": r["kind"], **({"ref": r["ref"]} if "ref" in r else {})}
            for i, r in enumerate(chunk)
        ]  # fmt: skip
        prompt = tmpl.replace("{examples}", "\n".join(f"- {e}" for e in ex) or "- (none available)")
        prompt = prompt.replace("{rows_json}", json.dumps(rj, indent=0))
        async with sem:
            out = await gen.structured("work_orders", version, prompt, WOBatch)
        res: dict[int, WOText] = {}
        if isinstance(out, WOBatch):
            for t in out.rows:
                if (
                    0 <= t.row < len(chunk)
                    and t.row not in res
                    and all(x.strip() for x in (t.symptom, t.action, t.outcome))
                ):
                    res[t.row] = t
        return res

    chunks = [rows[i : i + batch] for i in range(0, len(rows), batch)]
    results = await asyncio.gather(*(one(b, c) for b, c in enumerate(chunks)))
    wos: list[dict[str, Any]] = []
    labels: list[dict[str, Any]] = []
    for chunk, res in zip(chunks, results, strict=True):
        for i, r in enumerate(chunk):
            t = res.get(i)
            sym, act, out = (t.symptom, t.action, t.outcome) if t else _template_wo(r)
            wos.append({"wo_id": r["wo_id"], "date": r["date"], "asset_id": r["asset_id"],
                        "symptom": " ".join(sym.split()), "action": " ".join(act.split()),
                        "outcome": " ".join(out.split()), "technician_role": r["technician_role"]})  # fmt: skip
            labels.append({"wo_id": r["wo_id"], "asset_id": r["asset_id"], "theme": r["theme"],
                           "cause_class": r["cause"].value if r["cause"] else None, "kind": r["kind"],
                           "true_cause_class": r["true_cause"].value if r.get("true_cause") else None,
                           "corrects_wo": r.get("ref"), "corrected_by": r.get("corrected_by"),
                           "text_source": "llm" if t else "template"})  # fmt: skip
    return wos, labels


def recent_wos(
    pool: list[dict[str, Any]], stop: datetime, scenario_id: str, rng: np.random.Generator, k: int
) -> list[dict[str, Any]]:
    """k background WOs re-dated into the 30 days before the stop (so a planted red-herring WO is
    never the only recent one). Texts come from the historical pool, normal jobs only."""
    normal = [w for w in pool if not w["outcome"].lower().startswith("not fixed")]
    idx = rng.choice(len(normal), size=min(k, len(normal)), replace=False)
    out = []
    for j, i in enumerate(sorted(idx.tolist())):
        w = dict(normal[i])
        w["date"] = stop - timedelta(seconds=int(rng.integers(86400, 30 * 86400)))
        w["wo_id"] = f"WO-{w['date']:%y}{90000 + int(scenario_id[1:]) * 10 + j:05d}"
        out.append(w)
    return out
