"""Machine-readable premises of the diagnostic passages in the manuals (ADR-025).

A troubleshooting passage such as "A sustained fall in header pressure while the compressor runs
loaded indicates demand exceeding supply" is only evidence for a cause when its premise holds in
*this* incident. Quoting it verbatim is not enough (R002: the header never fell, yet the quote
passed). Each entry below pins one passage fragment, exactly as it is rendered in the built
manual, to the measurable conditions it states. The rendered manual text is unchanged: this is
metadata next to the manual source, read by ``cite_manual`` (shown with every citation) and by
the Verifier (checked against telemetry).

Rules for authoring an entry (hand-written and reviewed, never generated):

* ``text`` is a fragment of one page as rendered (a sentence, a clause or a table cell, at least
  ``MIN_QUOTE_CHARS`` characters, cross-references already resolved). ``tests/test_premises.py``
  fails if a fragment is no longer found verbatim in its manual.
* Encode only *positive*, measurable conditions the conclusion depends on. Negative conditions
  ("while the other signals stay normal") and shape words ("ripple", "scatter", "pulsing") are
  not encoded; such passages are verified for wording only.
* Notes that contrast two cases ("a blocked nozzle raises pressure; a starved inlet lowers
  both") carry only the premise the cases share.
* ``asset=None`` means the asset of the hypothesis the claim supports when the manual covers it,
  otherwise any asset the manual covers that has the tag.

Expectations (checked by ``agents.verifier`` with the deterministic tools):

* ``fall`` / ``rise`` - a change point on the tag in that direction (``detect_change_points``;
  data artefacts excluded). For the load/unload compressor current the analysed signal is the
  loaded-time fraction, so ``rise`` means the compressor loads for longer.
* ``step`` - any such change point.
* ``low`` / ``high`` - the tag *stays* beyond its normal range on that side (or beyond
  ``value``): a change point whose new level is beyond it, or a window mean beyond it. A single
  sample beyond the limit is not enough ("sustained", not a spike).
* ``loaded`` - the compressor runs loaded (loaded-time fraction at or above
  ``LOADED_MIN_FRACTION``).

Stdlib only: ``agents/`` and ``api/`` import it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from simulator.manuals import normalise, pages

Expect = Literal["fall", "rise", "step", "low", "high", "loaded"]
EXPECTATIONS: tuple[str, ...] = ("fall", "rise", "step", "low", "high", "loaded")
LOADED_MIN_FRACTION = 0.8

_VERB = {
    "fall": ("falls", "did not fall"),
    "rise": ("rises", "did not rise"),
    "step": ("changes in a step", "did not change"),
    "low": ("is below its normal range", "was not below its normal range"),
    "high": ("is above its normal range", "was not above its normal range"),
    "loaded": ("runs loaded", "did not run loaded"),
}


@dataclass(frozen=True)
class Premise:
    tag: str
    expect: Expect
    asset: str | None = None  # None: the hypothesis asset (see module docstring)
    value: float | None = None  # low/high threshold if not the tag's normal range

    def __post_init__(self) -> None:
        if self.expect not in EXPECTATIONS:
            raise ValueError(f"unknown expectation {self.expect!r}")
        if self.value is not None and self.expect not in ("low", "high"):
            raise ValueError("a threshold value only applies to low/high")

    def subject(self, asset: str | None = None) -> str:
        return f"{asset or self.asset or '<asset>'} {self.tag}"

    def describe(self, asset: str | None = None) -> str:
        if self.value is not None:
            side = "below" if self.expect == "low" else "above"
            return f"{self.subject(asset)} stays {side} {self.value:g}"
        return f"{self.subject(asset)} {_VERB[self.expect][0]}"

    def negated(self, asset: str | None = None) -> str:
        if self.value is not None:
            side = "below" if self.expect == "low" else "above"
            return f"{self.subject(asset)} did not stay {side} {self.value:g}"
        return f"{self.subject(asset)} {_VERB[self.expect][1]}"

    def as_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"asset": self.asset or "hypothesis asset", "tag": self.tag,
                             "expect": self.expect}  # fmt: skip
        if self.value is not None:
            d["value"] = self.value
        return d


@dataclass(frozen=True)
class Passage:
    doc: str
    topic: str  # cause class (or section key) the passage diagnoses; used by the calibration test
    text: str  # verbatim fragment as rendered
    premises: tuple[Premise, ...]


def P(tag: str, expect: Expect, asset: str | None = None, value: float | None = None) -> Premise:
    return Premise(tag, expect, asset, value)


_AIR, _CHL, _W20, _W30, _VIS = "UT-AIR", "UT-CHL", "ST20-WLD", "ST30-WLD", "ST60-VIS"
# The manual's "fall in header pressure" is the header losing its load/unload band: below the
# cut-in pressure (6.2 bar = plant.AIR_CUT_IN_BAR, pinned by a test). A shift of the saw-tooth
# mean inside the band while the compressor keeps up is not that fall (R001-R003, ADR-018).
AIR_CUT_IN_BAR = 6.2
_HDR_FALL = P("header_pressure_bar", "low", _AIR, AIR_CUT_IN_BAR)
_HDR_LOW = P("header_pressure_bar", "low", _AIR)
_LOADED = P("compressor_current_a", "loaded", _AIR)
_DUTY_UP = P("compressor_current_a", "rise", _AIR)

PASSAGES: tuple[Passage, ...] = (
    # --- compressed_air: 6.2 header pressure low / air leaks --------------------------------
    Passage("compressed_air", "air_pressure_drop",
            "A leak first shows as a longer loaded time: average motor current rises while header pressure still recovers.",
            (_DUTY_UP,)),
    Passage("compressed_air", "air_pressure_drop",
            "When leakage plus demand exceed what the compressor can deliver, the compressor stays loaded, header pressure falls below the cut-in pressure",
            (_LOADED, _HDR_FALL)),
    Passage("compressed_air", "air_pressure_drop",
            "The weld cells see their regulated gun air fall shortly after",
            (_HDR_FALL, P("air_pressure_bar", "fall", _W20), P("air_pressure_bar", "fall", _W30))),
    Passage("compressed_air", "air_pressure_drop",
            "A sustained fall in header pressure while the compressor runs loaded indicates demand exceeding supply, most often a distribution leak.",
            (_HDR_FALL, _LOADED)),
    Passage("compressed_air", "air_pressure_drop",
            "A fall in gun air pressure at ST20 and ST30 at the same time, after the header pressure has fallen, places the cause in the air supply, not in the weld cells.",
            (_HDR_FALL, P("air_pressure_bar", "fall", _W20), P("air_pressure_bar", "fall", _W30))),
    Passage("compressed_air", "sensor_drift",
            "A header pressure reading that falls while compressor duty and the gun air pressures at both cells stay normal points to the header pressure transmitter",
            (P("header_pressure_bar", "fall", _AIR),)),
    Passage("compressed_air", "air_pressure_drop",
            "Header pressure falling, compressor loaded continuously", (_HDR_FALL, _LOADED)),
    Passage("compressed_air", "air_pressure_drop",
            "Compressor loaded longer than usual, header pressure still normal", (_DUTY_UP,)),
    Passage("compressed_air", "air_pressure_drop",
            "Header pressure low, compressor current low (not loading)", (_HDR_LOW,)),
    Passage("compressed_air", "air_pressure_drop",
            "Continuous hiss at a drain, header pressure low", (_HDR_LOW,)),
    # background prose of 6.2 (drafted once by Gemini, cached; pinned by the same test)
    Passage("compressed_air", "air_pressure_drop",
            "the unit remains loaded continuously without reaching 7.3 bar", (_LOADED,)),
    Passage("compressed_air", "air_pressure_drop",
            "The header pressure drops below the 6.2 bar cut-in setting until it breaches the 5.6 bar low alarm limit",
            (_HDR_FALL,)),
    Passage("compressed_air", "air_pressure_drop",
            "Shortly after header pressure declines, downstream air to the weld guns drops below the 5.6 bar regulator setting.",
            (_HDR_FALL,)),
    # --- compressed_air: 6.3 compressor oil temperature high -------------------------------
    Passage("compressed_air", "oil_hot",
            "Oil temperature rising together with longer loaded time usually follows a leak or extra demand",
            (P("oil_temp_c", "rise", _AIR), _DUTY_UP)),
    Passage("compressed_air", "oil_hot",
            "oil temperature rising at normal duty points to the cooler or the oil",
            (P("oil_temp_c", "rise", _AIR),)),
    Passage("compressed_air", "oil_hot", "`oil_temp_c` above 85 degC at normal load duty",
            (P("oil_temp_c", "high", _AIR),)),
    Passage("compressed_air", "oil_hot", "Oil temperature high, oil level low",
            (P("oil_temp_c", "high", _AIR),)),
    Passage("compressed_air", "oil_hot", "Oil temperature high with longer loaded time",
            (P("oil_temp_c", "high", _AIR), _DUTY_UP)),
    # --- compressed_air: appendix B chiller --------------------------------------------------
    Passage("compressed_air", "chiller", "Condenser fouled or chiller filter clogged (A-UTCHL-FLT-SVC)",
            (P("supply_temp_c", "high", _CHL),)),
    # --- weld_controller: 6.2 tip wear -------------------------------------------------------
    Passage("weld_controller", "weld_tip_wear",
            "Tip resistance (`tip_resistance_mohm`) climbs steadily over hours",
            (P("tip_resistance_mohm", "rise"),)),
    Passage("weld_controller", "weld_tip_wear",
            "Tip resistance that rises in a straight line over several hours, together with a stepping weld current, is the signature of electrode tip wear",
            (P("tip_resistance_mohm", "rise"),)),
    Passage("weld_controller", "weld_tip_wear",
            "A tip dresser that runs but removes no material leaves tip resistance rising",
            (P("tip_resistance_mohm", "rise"),)),
    Passage("weld_controller", "weld_tip_wear", "`tip_resistance_mohm` above 0.175 mOhm and still rising",
            (P("tip_resistance_mohm", "high"), P("tip_resistance_mohm", "rise"))),
    # --- weld_controller: 6.3 servo over-temperature -----------------------------------------
    Passage("weld_controller", "servo_overheat",
            "Servo-gun drive temperature (`servo_temp_c`) rises above its normal range of 35 to 65 degC.",
            (P("servo_temp_c", "rise"), P("servo_temp_c", "high"))),
    Passage("weld_controller", "servo_overheat",
            "A servo temperature rise with normal coolant flow and a cabinet fan that is noisy, slow or stopped points to the cabinet cooling fan or a clogged cabinet filter.",
            (P("servo_temp_c", "rise"),)),
    Passage("weld_controller", "sensor_drift",
            "A servo temperature reading that climbs while cycle time, weld current and coolant flow stay normal may be an instrument problem",
            (P("servo_temp_c", "rise"),)),
    Passage("weld_controller", "servo_overheat", "`servo_temp_c` above 65 degC, cycle time normal",
            (P("servo_temp_c", "high"),)),
    Passage("weld_controller", "servo_overheat", "`servo_temp_c` above 66 degC and `cycle_time_s` rising",
            (P("servo_temp_c", "high"), P("cycle_time_s", "rise"))),
    Passage("weld_controller", "servo_overheat", "Gun moves slowly or stalls while temperature rises",
            (P("servo_temp_c", "rise"),)),
    # --- weld_controller: 6.4 coolant ---------------------------------------------------------
    Passage("weld_controller", "coolant_blockage",
            "Coolant flow (`coolant_flow_lpm`, ST30 only) falls below its normal range of 10 to 14 L/min",
            (P("coolant_flow_lpm", "fall", _W30),)),
    Passage("weld_controller", "coolant_blockage",
            "With less cooling, servo temperature starts to rise about 15 minutes later",
            (P("coolant_flow_lpm", "fall", _W30), P("servo_temp_c", "rise", _W30))),
    Passage("weld_controller", "coolant_blockage",
            "Falling coolant flow followed some minutes later by rising servo temperature identifies a restricted coolant circuit",
            (P("coolant_flow_lpm", "fall", _W30), P("servo_temp_c", "rise", _W30))),
    Passage("weld_controller", "coolant_blockage",
            "Coolant flow that falls at ST30 while the chiller supply temperature stays normal points to a restriction inside the cell",
            (P("coolant_flow_lpm", "fall", _W30),)),
    Passage("weld_controller", "coolant_blockage", "`coolant_flow_lpm` below 10 L/min",
            (P("coolant_flow_lpm", "low", _W30),)),
    Passage("weld_controller", "chiller", "Coolant flow low and chiller supply temperature high",
            (P("coolant_flow_lpm", "low", _W30), P("supply_temp_c", "high", _CHL))),
    # --- weld_controller: 6.6 gun air ---------------------------------------------------------
    Passage("weld_controller", "air_pressure_drop",
            "When gun air pressure falls at ST20 and ST30 together, the cause is upstream in the plant air supply",
            (P("air_pressure_bar", "fall", _W20), P("air_pressure_bar", "fall", _W30))),
    Passage("weld_controller", "gun_air",
            "When gun air falls at one cell only, check that cell's filter-regulator",
            (P("air_pressure_bar", "fall"),)),
    Passage("weld_controller", "air_pressure_drop",
            "Plant air header pressure low (leak or compressor problem)",
            (P("air_pressure_bar", "low", _W20), P("air_pressure_bar", "low", _W30))),
    # --- sealer_pump: 6.2 cavitation ----------------------------------------------------------
    Passage("sealer_pump", "sealer_pump_cavitation",
            "starts to pulse at the pump stroke rate (0.15 Hz, one stroke about every 6.7 s) and its mean falls",
            (P("pump_pressure_bar", "fall"),)),
    Passage("sealer_pump", "sealer_pump_cavitation",
            "Flow (`flow_rate_ccm`) drops below its normal range of 270 to 330 cc/min.",
            (P("flow_rate_ccm", "fall"),)),
    Passage("sealer_pump", "sealer_pump_cavitation",
            "Pressure pulsing at the stroke rate together with falling flow means the pump is not filling on each stroke",
            (P("flow_rate_ccm", "fall"),)),
    Passage("sealer_pump", "sealer_pump_cavitation",
            "A blocked nozzle raises outlet pressure and lowers flow; a starved inlet lowers both pressure and flow.",
            (P("flow_rate_ccm", "fall"),)),
    Passage("sealer_pump", "sealer_pump_cavitation", "Pressure pulsing at the stroke rate, flow low",
            (P("flow_rate_ccm", "low"),)),
    Passage("sealer_pump", "sealer_pump_cavitation", "Flow low and pulsing worst at shift start",
            (P("flow_rate_ccm", "low"),)),
    Passage("sealer_pump", "sealer_pump_cavitation", "Flow low, pulsing, drum and seal good",
            (P("flow_rate_ccm", "low"),)),
    Passage("sealer_pump", "bead", "Pressure high, flow low, no pulsing",
            (P("pump_pressure_bar", "high"), P("flow_rate_ccm", "low"))),
    # --- conveyor_drive: 6.2 bearing ----------------------------------------------------------
    Passage("conveyor_drive", "conveyor_bearing_defect",
            "Drive-end bearing vibration (`vibration_rms_mms`) rises out of its normal range of 0.8 to 2.8 mm/s",
            (P("vibration_rms_mms", "rise", "ST50-CNV"),)),
    Passage("conveyor_drive", "conveyor_bearing_defect",
            "Vibration that grows in an accelerating curve, with a ripple at the pulley rotation frequency and a delayed rise in bearing temperature, indicates a drive-end bearing defect.",
            (P("vibration_rms_mms", "rise", "ST50-CNV"),)),
    Passage("conveyor_drive", "sensor_drift",
            "A bearing temperature rise without any vibration change is unlikely to be a bearing defect",
            (P("bearing_temp_c", "rise", "ST50-CNV"),)),
    Passage("conveyor_drive", "conveyor_bearing_defect",
            "`vibration_rms_mms` above 2.8 mm/s and accelerating",
            (P("vibration_rms_mms", "high", "ST50-CNV"), P("vibration_rms_mms", "rise", "ST50-CNV"))),
    Passage("conveyor_drive", "conveyor_bearing_defect",
            "Vibration high, steady, started after chain or sprocket work",
            (P("vibration_rms_mms", "high", "ST50-CNV"),)),
    Passage("conveyor_drive", "bearing_temp", "`bearing_temp_c` above 55 degC with normal vibration",
            (P("bearing_temp_c", "high", "ST50-CNV"),)),
    Passage("conveyor_drive", "rejects", "A rise above 6 % on consecutive checks causes a quality stop",
            (P("reject_rate_pct", "high", _VIS),)),
    # --- press_hydraulics: 6.2 changeover / 6.3 degradation ----------------------------------
    Passage("press_hydraulics", "changeover_error",
            "settles at the wrong level as a clean step right after the changeover and stays there",
            (P("hyd_pressure_bar", "step", "ST10-PRS"),)),
    Passage("press_hydraulics", "changeover_error",
            "A step change in main pressure that starts exactly at a changeover",
            (P("hyd_pressure_bar", "step", "ST10-PRS"),)),
    Passage("press_hydraulics", "changeover_error",
            "Main pressure off setpoint right after a changeover, then steady",
            (P("hyd_pressure_bar", "step", "ST10-PRS"),)),
    Passage("press_hydraulics", "hydraulic_degradation",
            "Pressure sagging below setpoint while motor current rises and oil temperature creeps up indicates internal pump leakage.",
            (P("hyd_pressure_bar", "fall", "ST10-PRS"),)),
    Passage("press_hydraulics", "hydraulic_degradation",
            "A ragged pressure trace with rising vibration and scattered cycle times indicates a lagging switching valve.",
            (P("vibration_rms_mms", "rise", "ST10-PRS"),)),
    Passage("press_hydraulics", "hydraulic_degradation",
            "Oil temperature rising steadily while pressure and vibration stay normal indicates loss of cooler efficiency.",
            (P("oil_temp_c", "rise", "ST10-PRS"),)),
)  # fmt: skip


def _spans(hay: str, needle: str) -> list[tuple[int, int]]:
    out, i = [], hay.find(needle)
    while i >= 0:
        out.append((i, i + len(needle)))
        i = hay.find(needle, i + 1)
    return out


def passages_for(doc: str, page: int, quote: str) -> list[Passage]:
    """Premise-carrying passages that the quote (verbatim on ``doc`` p.``page``) overlaps."""
    text = pages(doc).get(page) if doc else None
    if not text:
        return []
    hay, q = normalise(text), normalise(quote)
    qs = _spans(hay, q)
    if not qs:
        return []
    out = []
    for p in PASSAGES:
        if p.doc != doc:
            continue
        for a, b in _spans(hay, normalise(p.text)):
            if any(a < qb and qa < b for qa, qb in qs):
                out.append(p)
                break
    return out


def premises_for(doc: str, page: int, quote: str) -> list[Premise]:
    """Distinct premises of every passage the quote overlaps, in registry order."""
    seen: dict[Premise, None] = {}
    for p in passages_for(doc, page, quote):
        for pr in p.premises:
            seen.setdefault(pr)
    return list(seen)
