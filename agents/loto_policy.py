"""Which energy-control (LOTO) steps a work order must contain - decided by code (ADR-025).

The Action Drafter used to choose ``safety_step_ids`` and code only required one step per phase,
so a live R002 work order silently dropped "Test for absence of voltage at the compressor motor
terminals..." (an unconditional step). Now every step is **mandatory** unless the step text
itself states an explicit scope condition, recorded in :data:`CONDITIONAL_STEPS` below:

* ``asset`` - the step names the station it applies to ("On ST30, ..."). Code resolves it from
  the work order's asset: mandatory there, not applicable elsewhere.
* ``task`` - the step applies only to some jobs ("For work on the compressor or the receiver,
  ...", "Before removing the chain or the drive shaft, ..."). The drafter model may add it;
  nothing else is optional.

When in doubt a step is mandatory: precautions that only check or wait ("Confirm that the oil
separator pressure gauge reads zero before opening ...", "Wait at least 5 minutes ... before
opening the drive cabinet", "Let the ... cool before touching them") cost minutes and are always
included.

Each entry is pinned to the exact step text (sha256 prefix). If ``simulator/manuals/loto.py``
changes, the pinned hash no longer matches: the step is then treated as **mandatory** (fail-safe)
and ``tests/test_loto_policy.py`` fails until this table is reviewed again. The step texts
themselves are never edited here (ADR-019 content hash).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Literal

from simulator import plant
from simulator.manuals import loto as L

StepClass = Literal["mandatory", "conditional", "not_applicable"]


@dataclass(frozen=True)
class Condition:
    kind: Literal["task", "asset"]
    condition: str  # when the step applies, in plain words (shown to the drafter model)
    text_sha: str  # sha256(step text)[:16] - pins the classification to the reviewed text
    assets: tuple[str, ...] = ()  # kind "asset": the assets the step applies to


def text_sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


_ST30 = ("ST30-WLD",)

# Reviewed 2026-10-11 against the step texts of ADR-019 (content hash c5b39659...).
CONDITIONAL_STEPS: dict[str, dict[int, Condition]] = {
    "weld_controller": {
        7: Condition("asset", "ST30 only (coolant circuit)", "c3200de32e954c8f", _ST30),
        9: Condition("asset", "ST30 only (coolant circuit)", "e296a82f16238814", _ST30),
        12: Condition("asset", "ST30 only (coolant circuit)", "0319987afb579c6a", _ST30),
    },
    "sealer_pump": {},
    "conveyor_drive": {
        8: Condition("task", "only if the chain or the drive shaft is removed", "8814a59b1f9f473a"),
    },
    "press_hydraulics": {},
    "compressed_air": {
        7: Condition("task", "only for work on the compressor or the receiver", "cf7b68e6e267d684"),
        10: Condition(
            "task", "only for work on the compressor or the receiver", "3da09f4c7502b18a"
        ),
    },
}


def manual_for(asset_id: str) -> str | None:
    a = plant.ASSET_BY_ID.get(asset_id)
    return a.manual if a is not None and a.manual in L.LOTO else None


def condition(doc: str, step_no: int) -> Condition | None:
    """The reviewed condition of a step, or None (mandatory). A condition whose pinned text no
    longer matches the step is ignored: the step falls back to mandatory."""
    c = CONDITIONAL_STEPS.get(doc, {}).get(step_no)
    if c is None:
        return None
    steps = L.LOTO[doc].steps
    if not 1 <= step_no <= len(steps) or text_sha(steps[step_no - 1].text) != c.text_sha:
        return None
    return c


def step_class(doc: str, step_no: int, asset_id: str) -> StepClass:
    c = condition(doc, step_no)
    if c is None:
        return "mandatory"
    if c.kind == "asset":
        return "mandatory" if asset_id in c.assets else "not_applicable"
    return "conditional"


def classify(doc: str, asset_id: str) -> dict[int, StepClass]:
    """``{step_no: class}`` for every step of the manual's procedure, for this asset."""
    return {i: step_class(doc, i, asset_id) for i in range(1, len(L.LOTO[doc].steps) + 1)}


def mandatory_texts(asset_id: str) -> list[str]:
    """Verbatim texts of every mandatory step for the asset's manual (empty if no procedure)."""
    doc = manual_for(asset_id)
    if doc is None:
        return []
    steps = L.LOTO[doc].steps
    return [steps[i - 1].text for i, c in classify(doc, asset_id).items() if c == "mandatory"]
