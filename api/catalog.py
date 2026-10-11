"""Read-only catalogue endpoints: scenarios, dataset sources, latest eval summary.

Scenario labels are derived from **published metadata only** (stop record + provenance source
ids). The cause class is never exposed, and no ground-truth file is read (guard test).
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

BADGE = "SYNTHETIC LINE · REAL SIGNALS MARKED"

SOURCE_LABELS = {
    "metropt3": "MetroPT-3 compressor",
    "uci_hydraulic": "UCI hydraulic rig",
    "ims_bearings": "IMS bearings",
    "mimii": "MIMII machine audio",
}
_AUDIO_ONLY = {"mimii"}


def real_sources(sources: list[str]) -> list[str]:
    """Real telemetry source ids (MIMII audio only counts when nothing else is real)."""
    real = [s for s in sources if s != "synthetic"]
    non_audio = [s for s in real if s not in _AUDIO_ONLY]
    return non_audio or real


def describe_scenario(row: dict[str, Any], replay_runs: list[str]) -> dict[str, Any]:
    sid, station = row["scenario_id"], row.get("stopped_station") or ""
    is_real = sid.upper().startswith("R")
    srcs = real_sources(list(row.get("sources") or [])) if is_real else []
    label = " + ".join(SOURCE_LABELS.get(s, s) for s in srcs) if srcs else "Synthetic line"
    title = f"{sid} · line stop at {station}" + (f" · {label}" if is_real else "")
    return {
        "id": sid,
        "title": title,
        "group": "real_signal" if is_real else "synthetic",
        "line_id": row.get("line_id") or "L1",
        "stopped_station": station,
        "stop_ts": row.get("stop_ts") or None,
        "source_label": label,
        "real_signal": is_real,
        "replay_run_ids": replay_runs,
    }


def group_scenarios(rows: list[dict[str, Any]], replays: list[dict]) -> dict[str, Any]:
    by_sid: dict[str, list[str]] = {}
    for r in replays:
        by_sid.setdefault(r["scenario_id"], []).append(r["run_id"])
    items = [describe_scenario(r, by_sid.get(r["scenario_id"], [])) for r in rows]
    return {
        "badge": BADGE,
        "groups": [
            {
                "id": "synthetic",
                "title": "Synthetic line (S-set)",
                "scenarios": [i for i in items if i["group"] == "synthetic"],
            },
            {
                "id": "real_signal",
                "title": "Real signals mapped onto a synthetic line (R-set)",
                "scenarios": [i for i in items if i["group"] == "real_signal"],
            },
        ],
    }


# ---- SOURCES.md -------------------------------------------------------------------------------
_SECTION = re.compile(r"^## `([\w-]+)` — (.+)$", re.M)
_FIELD = re.compile(r"^- \*\*([\w ]+):\*\* (.+)$", re.M)
_CITATION = re.compile(r"\*\*Citation[^\n]*\n+```\w*\n(.*?)\n```", re.S)


def parse_sources(text: str) -> dict[str, Any]:
    """Dataset attributions for the UI footer, parsed from the generated ``data/SOURCES.md``."""
    heads = list(_SECTION.finditer(text))
    out = []
    for i, m in enumerate(heads):
        body = text[m.end() : heads[i + 1].start() if i + 1 < len(heads) else len(text)]
        fields: dict[str, list[str]] = {}
        for f in _FIELD.finditer(body):
            fields.setdefault(f.group(1).lower().replace(" ", "_"), []).append(f.group(2).strip())
        cit = _CITATION.search(body)

        def first(k: str, fields: dict[str, list[str]] = fields) -> str | None:
            return (fields.get(k) or [None])[0]

        out.append(
            {
                "id": m.group(1),
                "name": m.group(2).strip(),
                "page": first("page"),
                "licence": first("licence"),
                "maps_to": first("maps_to"),
                "downloaded": first("downloaded"),
                "citation": cit.group(1).strip() if cit else None,
            }
        )
    return {
        "note": "Real signals are mapped onto a synthetic line; they are not real plant data.",
        "badge": BADGE,
        "datasets": out,
    }


def load_sources(path: Path) -> dict[str, Any] | None:
    try:
        return parse_sources(path.read_text("utf-8"))
    except OSError:
        return None


def load_eval_latest(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text("utf-8"))
    except (OSError, ValueError):
        return None
