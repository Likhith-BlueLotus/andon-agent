"""CONTRACT — ground truth format consumed by the eval (ARCHITECTURE §4.3).

Never imported or read from agents/ or api/ (guard test). Change only with both humans' OK.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from agents.schemas import CauseClass


class GroundTruth(BaseModel):
    scenario_id: str
    seed: int
    scenario_set: Literal["synthetic", "real_signal"]
    # source_label = from the dataset's own labels / failure reports
    truth_source: Literal["injected", "source_label"]
    variant: Literal["clean", "red_herring", "dual_fault", "no_fault"]
    root_cause_class: CauseClass
    asset_id: str | None
    onset_ts: datetime | None
    detail: str | None = None  # e.g. hydraulic sub-type "pump_leakage_severe"
    causal_chain: list[str]
    secondary_cause: CauseClass | None = None
    distractors: list[str]  # planted misleading artifacts
    # injected data-quality issues (gaps, stuck values, chatter, skew)
    imperfections: list[str] = []
    stop_station: str
    stop_ts: datetime
