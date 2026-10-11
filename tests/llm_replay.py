"""Offline helpers for graph tests: a small synthetic store built in tmp, and materialisation of
templated LLM fixtures (``tests/fixtures/llm/_templates/<name>/``).

Templates are recorded-format fixtures with two placeholders, resolved here so the same fixture
fits a store built on any machine:

* ``$STOP`` / ``$STOP-<seconds>`` -> ISO time relative to the scenario's stop;
* ``$EV{<evidence_id>:<dotted.path>}`` -> the value at that path of the evidence the fixture's own
  tool calls produce (re-executed here in file order on a scratch ToolContext, which yields the
  same ``ev_<tool>_<n>`` ids as the graph run).

Ground truth is never read.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

from agents import tools as T
from agents.schemas import CauseClass
from simulator import generate as gen_mod
from simulator.generate import Scenario, Slot, build, write_scenario
from simulator.load import load_duckdb
from simulator.text_artifacts import TextGen, build_work_orders

ROOT = Path(__file__).resolve().parent
TEMPLATES = ROOT / "fixtures" / "llm" / "_templates"
_STOP = re.compile(r"\$STOP([+-]\d+)?")
_EV = re.compile(r"\$EV\{([^:}]+):([^}]+)\}")
NOT_TOOLS = {"cite_manual", "draft_work_order", "listen"}


def build_store(root: Path, sid: str = "S801", cls: CauseClass = CauseClass.AIR_PRESSURE_DROP,
                seed: int = 2026801, notes_extra: list[dict] | None = None):  # fmt: skip
    g = TextGen(mode="template")
    wos, labels = g.run(build_work_orders(g, 200, 7, Path("/nonexistent")))
    kinds = {lb["wo_id"]: lb["kind"] for lb in labels}
    pool = [w for w in wos if kinds[w["wo_id"]] == "normal"]
    b = build(Scenario(sid, seed, Slot(cls, "clean", 0), 4 * 86400), TextGen(mode="template"), pool)
    write_scenario(root / "scenarios", sid, b)
    if notes_extra:
        import pyarrow as pa

        path = root / "scenarios" / sid / "shift_notes.parquet"
        tbl = pq.read_table(path)
        stop = datetime.fromisoformat(
            json.loads((root / "scenarios" / sid / "stop_event.json").read_text())[
                "stop_ts"
            ].replace("Z", "+00:00")
        )
        base = {**tbl.to_pylist()[-1], "ts": stop - timedelta(minutes=30)}
        rows = tbl.to_pylist() + [{**base, **n} for n in notes_extra]
        pq.write_table(pa.Table.from_pylist(rows, schema=tbl.schema), path)
    pq.write_table(gen_mod.wo_table(pool, None), root / "work_orders.parquet")
    return load_duckdb(root / "scenarios", root / "andon.duckdb")


def _iso(d: datetime) -> str:
    return d.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _get(obj: Any, path: str) -> Any:
    for seg in path.replace("[", ".").replace("]", "").split("."):
        if seg == "":
            continue
        obj = obj[int(seg)] if isinstance(obj, list) else obj[seg]
    return obj


def _subst(obj: Any, fn) -> Any:
    if isinstance(obj, dict):
        return {k: _subst(v, fn) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_subst(v, fn) for v in obj]
    if isinstance(obj, str):
        return fn(obj)
    return obj


def materialise(name: str, store: Any, scenario_id: str, out_root: Path) -> Path:
    """Resolve template ``name`` for ``scenario_id`` into ``out_root/<scenario_id>/``."""
    src = TEMPLATES / name
    stop = store.get_stop_event(scenario_id)["stop_ts"]
    stop = stop if isinstance(stop, datetime) else datetime.fromisoformat(str(stop))

    def stop_fn(s: str) -> str:
        return _STOP.sub(lambda m: _iso(stop + timedelta(seconds=int(m.group(1) or 0))), s)

    files = {f.name: _subst(json.loads(f.read_text()), stop_fn) for f in sorted(src.glob("*.json"))}
    ctx = T.ToolContext(store=store, scenario_id=scenario_id)
    order = ["adk_commander.json", "adk_signal_analyst.json", "adk_evidence_librarian.json"]
    for fname in order:
        for resp in files.get(fname, []):
            for part in resp.get("content", {}).get("parts", []):
                fc = part.get("function_call")
                if fc and fc["name"] not in NOT_TOOLS:
                    T.TOOL_REGISTRY[fc["name"]].fn(ctx, **fc["args"])

    def ev_value(eid: str, path: str) -> Any:
        return _get(ctx.evidence[eid].summary, path)

    def ev_fn(s: str) -> Any:
        m = _EV.fullmatch(s)
        if m:
            return ev_value(m.group(1), m.group(2))
        return _EV.sub(lambda m: str(ev_value(m.group(1), m.group(2))), s)

    def walk_text(obj: Any) -> Any:  # placeholders inside JSON text parts of generate fixtures
        if isinstance(obj, dict):
            if "text" in obj and isinstance(obj["text"], str) and obj["text"].startswith("{"):
                inner = _subst(json.loads(obj["text"]), ev_fn)
                return {**obj, "text": json.dumps(inner)}
            return {k: walk_text(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [walk_text(v) for v in obj]
        return obj

    out = out_root / scenario_id
    out.mkdir(parents=True, exist_ok=True)
    for fname, data in files.items():
        if fname.startswith("generate_"):
            data = walk_text(data)
        (out / fname).write_text(json.dumps(data, indent=1))
    return out
