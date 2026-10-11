"""Scenario sets and named subsets (EVAL_PLAN §2, §4) and the ground-truth loader (grader only).

* ``S``      S001-S060 (synthetic, injected truth); ``dev`` = S001-S050 (tuning allowed, but see
  ``DEV_TUNING``: day-to-day iteration uses S001-S020), ``heldout`` = S051-S060 (no tuning, ever).
* ``R``      R001-R017 (real signals, truth from the source dataset's own labels).
* ``variance15`` S001, S006, ..., S056 (12) + R002, R010, R016 (one per real source).
* ``audio`` scenarios with an abnormal MIMII clip or IMS vibration (the S3 ablation's population).

Ground truth is read **only** here and in the grader (``eval/metrics.py`` callers); ``agents/`` and
``api/`` never import ``eval`` (tests/test_guards.py).
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from pathlib import Path

from simulator.truth_schema import GroundTruth

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SCENARIOS = ROOT / "data" / "scenarios"

S_IDS = [f"S{i:03d}" for i in range(1, 61)]
R_IDS = [f"R{i:03d}" for i in range(1, 18)]
DEV_TUNING = [f"S{i:03d}" for i in range(1, 21)]  # EVAL_PLAN §7 dev iterations
DEV_IDS = [f"S{i:03d}" for i in range(1, 51)]
HELDOUT_IDS = [f"S{i:03d}" for i in range(51, 61)]
VARIANCE15 = [f"S{i:03d}" for i in range(1, 61, 5)] + ["R002", "R010", "R016"]
HELDOUT = frozenset(HELDOUT_IDS)
_ID = re.compile(r"^[SR]\d{3}$")

NAMED = {
    "S": S_IDS,
    "R": R_IDS,
    "dev": DEV_TUNING,
    "dev50": DEV_IDS,
    "heldout": HELDOUT_IDS,
    "variance15": VARIANCE15,
}


def set_of(scenario_id: str) -> str:
    """``S`` or ``R`` (the id prefix; the two sets are never merged in a headline)."""
    if not _ID.match(scenario_id):
        raise ValueError(f"not a scenario id: {scenario_id!r}")
    return scenario_id[0]


def resolve(spec: str, scenarios_dir: Path = DEFAULT_SCENARIOS) -> list[str]:
    """A comma list of named sets and/or ids/ranges (``S001-S010``) -> ordered unique ids."""
    out: list[str] = []
    for tok in (t.strip() for t in spec.split(",") if t.strip()):
        if tok in NAMED:
            ids: Iterable[str] = NAMED[tok]
        elif tok == "audio":
            ids = audio_signature_ids(scenarios_dir)
        elif m := re.fullmatch(r"([SR])(\d{3})-\1?(\d{3})", tok):
            ids = [f"{m[1]}{i:03d}" for i in range(int(m[2]), int(m[3]) + 1)]
        elif _ID.match(tok):
            ids = [tok]
        else:
            raise ValueError(f"unknown set or scenario {tok!r}; named sets: {sorted(NAMED)}, audio")
        out.extend(ids)
    return list(dict.fromkeys(out))


def audio_signature_ids(scenarios_dir: Path = DEFAULT_SCENARIOS) -> list[str]:
    """Scenarios with an audio/vibration signature, for the S3 ablation: an abnormal MIMII clip
    (``audio_truth.json`` is eval-only) or IMS bearing vibration (provenance source)."""
    out = []
    for sid in S_IDS + R_IDS:
        d = scenarios_dir / sid
        try:
            clips = json.loads((d / "audio_truth.json").read_text("utf-8")).get("clips", [])
        except (OSError, ValueError):
            clips = []
        if any(c.get("label") == "abnormal" for c in clips):
            out.append(sid)
            continue
        if sid.startswith("R") and (d / "provenance.parquet").exists():
            import pandas as pd

            if "ims_bearings" in set(pd.read_parquet(d / "provenance.parquet").source_id):
                out.append(sid)
    return out


def heldout_in(ids: Iterable[str]) -> list[str]:
    return [i for i in ids if i in HELDOUT]


# --- ground truth (grader only) ----------------------------------------------------------------
def load_truth(
    ids: Iterable[str], scenarios_dir: Path | str = DEFAULT_SCENARIOS
) -> dict[str, GroundTruth]:
    """``{scenario_id: GroundTruth}``. ``scenarios_dir`` is a local directory with
    ``<id>/truth.json`` (the Cloud Run job syncs it from ``gs://`` first, see eval/gcs_sync.py)."""
    root = Path(scenarios_dir)
    out: dict[str, GroundTruth] = {}
    for sid in ids:
        out[sid] = GroundTruth.model_validate_json((root / sid / "truth.json").read_text("utf-8"))
    return out
