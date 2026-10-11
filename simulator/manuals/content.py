"""Deterministic manual content: equipment, troubleshooting tables, diagnostic notes, maintenance.

Everything a verifier or an eval relies on is authored here, by hand, not by an LLM:

* troubleshooting topics (one per fault the simulator can inject, titled exactly as
  ``simulator.faults.MANUAL*`` topics) with a *typical signature* paragraph, diagnostic notes and a
  symptom -> probable cause -> check -> remedy table, all consistent with the physics in
  ``simulator/faults.py``;
* every number that is also a simulator number comes from ``simulator.plant`` (f-strings), so the
  manuals cannot drift from the simulation; numbers that exist only in the manuals (intervals,
  waiting times) are named in ``MANUAL_ONLY``.

Gemini drafts only descriptive prose (overview, principle of operation, background paragraphs);
see ``build.py``. Cross-references use placeholders resolved after page layout:
``{T:key}`` table, ``{S:key}`` section, ``{P:key}`` page, ``{T:doc/key}`` table in another manual.

All equipment is generic and fictional. No vendor names, model numbers, tag schemes or alarm
codes of any real company are used; alarm codes are the simulator's own generic codes.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from agents.schemas import CauseClass
from simulator import plant
from simulator.faults import MANUAL, MANUAL_SENSOR, MANUAL_TIMER

C = CauseClass

# Numbers that appear only in the manuals (not simulated). Kept in one place for review.
MANUAL_ONLY = {
    "tip_dress_welds": 250,  # welds between tip dressings
    "cap_change_dressings": 40,  # dressings before a cap change
    "drive_discharge_min": 5,  # DC bus discharge wait (also in loto.py text)
    "setpoint_tolerance_bar": 5.0,  # press main pressure vs recipe setpoint after changeover
    "header_hold_min": 15,  # leak-repair acceptance: header holds pressure with no demand
}

TOPIC_SENSOR = MANUAL_SENSOR["press_hydraulics"].topic
TOPIC_TIMER = MANUAL_TIMER["press_hydraulics"].topic


def T(asset_id: str, tag: str) -> plant.TagSpec:
    return plant.tag_spec(asset_id, tag)


def g(x: float | None) -> str:
    """Number format used in every manual (shortest exact form, e.g. 0.135, 180, 6.75)."""
    if x is None:
        return "-"
    return f"{x:g}"


def rng(asset_id: str, tag: str) -> str:
    t = T(asset_id, tag)
    return f"{g(t.normal_lo)} to {g(t.normal_hi)}"


@dataclass(frozen=True)
class Row:
    symptom: str
    cause: str
    check: str
    remedy: str


@dataclass(frozen=True)
class Topic:
    key: str
    title: str
    signature: str  # "Typical signature." paragraph
    notes: tuple[str, ...]  # "Diagnostic notes" bullets (quotable)
    rows: tuple[Row, ...]
    background: str | None = None  # id of the LLM prose section placed under the table
    extra: tuple[tuple[str, str, tuple[str, ...], tuple[tuple[str, ...], ...]], ...] = ()
    # extra tables: (key, caption, header, rows), rendered before the troubleshooting table
    page_break_before_table: bool = False


@dataclass(frozen=True)
class ProseSpec:
    id: str
    title: str
    brief: str  # what to write
    words: int


@dataclass(frozen=True)
class Appendix:
    key: str
    title: str
    intro: str
    assets: tuple[str, ...]
    topics: tuple[Topic, ...]


@dataclass(frozen=True)
class ManualSpec:
    doc: str
    title: str
    doc_no: str
    applies_to: tuple[str, ...]
    equipment: str  # one-line description (facts for the LLM)
    components: tuple[tuple[str, str], ...]
    hazards: tuple[tuple[str, str, str], ...]  # hazard, where, protection
    ppe: tuple[str, ...]
    params: tuple[tuple[str, str, str], ...]  # parameter, value, note
    events: tuple[tuple[str, str, str], ...]  # code, message, meaning
    changeover: tuple[str, ...]  # Ch.4 changeover steps (optional)
    timers: tuple[tuple[str, str, str], ...]  # parameter, function, changed by
    timer_rows: tuple[Row, ...]
    correlates: tuple[tuple[str, str], ...]  # tag -> physical correlates to check
    topics: tuple[Topic, ...]
    maintenance: tuple[tuple[str, str, str], ...]  # task, interval, reference
    spares: tuple[tuple[str, str], ...]
    appendix: Appendix | None = None
    ch3_extra: tuple[tuple[str, str, tuple[str, ...], tuple[tuple[str, ...], ...]], ...] = field(
        default=()
    )


# --- Shared text -------------------------------------------------------------------------------
SENSOR_NOTES: tuple[str, ...] = (
    "A real process change moves more than one signal; a single tag that trends steadily while every physically related tag stays normal points to the instrument, not the process.",
    "Do not replace process components on the evidence of one drifting tag; verify the instrument first against a calibrated reference at the measuring point.",
    "A reading that jumps beyond a trip limit for one to three seconds and then returns, with no change in related tags before or after, is a measurement spike; reset, record it and keep the station running.",
    "Gaps in a trend, a value that stays exactly constant for a long period (stuck value) and the same alarm repeating several times within a minute (alarm chatter) are data-quality effects of the instrument or the network; they are not process faults and are not evidence of a failure.",
)  # fmt: skip

SENSOR_ROWS: tuple[Row, ...] = (
    Row("One tag trends steadily towards a limit; all related tags in {T:correlates} stay normal",
        "Transmitter drift (ageing, contamination, loose terminal, moisture in the connector)",
        "Compare the reading with a calibrated handheld reference at the same point; inspect the connector and cable",
        "Recalibrate or replace the transmitter; record the as-found and as-left values in the calibration log"),
    Row("Station stopped on a high-high or low-low trip after a one- to three-second excursion",
        "Measurement spike (electrical noise, loose shield, vibration on the cable)",
        "Check the trend either side of the trip; check related tags; inspect cable shield and gland",
        "Reset and restart; if spikes repeat, re-terminate the shield and re-route the cable away from power cables"),
    Row("Value frozen at exactly the same number for a long period",
        "Stuck value: lost update between the transmitter and the controller or historian",
        "Check the transmitter display against the HMI; check the communication diagnostics",
        "Restore communication; do not use the frozen period as process evidence"),
    Row("Same alarm raised and cleared several times within a minute",
        "Alarm chatter: value hovering at the limit with too little deadband",
        "Check the trend at the limit; check the alarm deadband setting",
        "Treat as one event; request a deadband review through change control (see {S:ch5})"),
)  # fmt: skip

TIMER_NOTES: tuple[str, ...] = (
    "Parameter changes are made only under an approved change request and are recorded in the parameter log with the old value, the new value, the author and the time.",
    "Parameter changes are normally loaded at a shift start, during the changeover.",
    "A cycle time that steps up at a shift start and then stays constant, while every process signal of the station stays normal, points to a changed timer or recipe parameter, not to wear or a failing component.",
    "Compare the active parameter set with the last approved copy before replacing any hardware.",
)  # fmt: skip


def _timer_rows(station: str) -> tuple[Row, ...]:
    return (
        Row(f"{station} cycle time stepped up at a shift start and stays at the new level; process signals normal",
            "Timer or dwell parameter changed at the changeover (wrong value, wrong recipe, or a trial value left active)",
            "Compare the active parameter set with the last approved copy; check the parameter log for the shift start",
            "Restore the approved value under change control; record the deviation"),
        Row("Stations downstream starved and stations upstream blocked after a shift start",
            "A slower cycle at one station propagating along the line",
            "Find the first station whose cycle time changed; downstream starvation and upstream blocking are consequences",
            "Correct the parameter at the first station only"),
        Row("Cycle time slightly longer for the first parts after every changeover",
            "Normal ramp-up after a changeover",
            "Confirm that cycle time returns to the normal range within a few cycles",
            "No action"),
    )  # fmt: skip


def _flow_events(*stations: str) -> tuple[tuple[str, str, str], ...]:
    out: list[tuple[str, str, str]] = []
    for s in stations:
        a = plant.asset(s)
        out += [
            (f"A-{a.station}-STARVED", f"{a.name}: station starved (waiting for part)",
             "Consequence of a slow or stopped station upstream; not a fault at this station"),
            (f"A-{a.station}-BLOCKED", f"{a.name}: station blocked (outfeed full)",
             "Consequence of a slow or stopped station downstream; not a fault at this station"),
        ]  # fmt: skip
    return tuple(out)


_COMMON_EVENTS = (
    ("A-L1-ANDON", "Line L1 stopped: andon raised", "Information; follows any station stop"),
)

# ------------------------------------------------------------------------------------------------
# Weld controller
# ------------------------------------------------------------------------------------------------
_W = "ST20-WLD"
_W3 = "ST30-WLD"
_wcur, _tipr, _srv, _cyc, _air = (
    T(_W, "weld_current_ka"),
    T(_W, "tip_resistance_mohm"),
    T(_W, "servo_temp_c"),
    T(_W, "cycle_time_s"),
    T(_W, "air_pressure_bar"),
)
_clt = T(_W3, "coolant_flow_lpm")

WELD = ManualSpec(
    doc="weld_controller",
    title="Servo-Gun Spot Weld Cell - Operation and Maintenance Manual",
    doc_no="AM-WC-01",
    applies_to=(_W, _W3),
    equipment="Resistance spot weld cell with a servo-driven weld gun, a medium-frequency weld controller and transformer, an electrode tip dresser and a part fixture with pneumatic clamps. ST30 also has a monitored gun and servo coolant circuit.",
    components=(
        ("Weld controller", "Inverter and weld timer; stores weld schedules; runs the current stepper that raises weld current as the electrode tips wear; monitors weld current and dynamic resistance of every weld"),
        ("Weld transformer and rectifier", "Converts the controller output into the low-voltage, high-current secondary weld current"),
        ("Servo gun", "Electrode arms closed by a servo motor and roller screw; applies the programmed electrode force"),
        ("Servo drive", "Drives the gun servo motor; measures its own temperature and derates speed when hot"),
        ("Electrode caps and shanks", "Replaceable copper alloy caps on water-cooled shanks"),
        ("Tip dresser", "Motor-driven cutter that restores the electrode tip face between welds"),
        ("Fixture", "Locates the part on locating pins and net pads; pneumatic clamps hold it during welding; proximity switches confirm clamp positions"),
        ("Cell air panel", f"Lockout valve, filter-regulator set to {g(plant.AIR_REGULATOR_BAR)} bar and pressure transmitter for clamps and gun balancer"),
        ("Coolant manifold (ST30)", "Supply and return valves, strainer and flow transmitter for the gun and servo coolant circuit"),
        ("Drive cabinet", "Houses controller and servo drive; cooled by a filtered cabinet fan"),
    ),
    hazards=(
        ("Electric shock", "Controller, transformer primary, servo drive DC bus", "Energy control procedure (Chapter 8); wait for DC bus discharge"),
        ("Crushing between electrodes", "Servo gun, clamp arms", "Guards and interlocked cell door; never reach between electrodes"),
        ("Burns", "Electrodes, shanks, transformer, weld spatter", "Heat-resistant gloves; let parts cool"),
        ("Flying spatter and cutter chips", "Weld zone, tip dresser", "Safety glasses with side shields; face shield at the dresser"),
        ("Stored air pressure", "Clamp circuit, gun balancer", "Bleed the cell air circuit (Chapter 8)"),
        ("Hot coolant under pressure (ST30)", "Gun hoses, manifold", "Isolate and drain the coolant circuit (Chapter 8)"),
    ),
    ppe=("Safety glasses with side shields", "Flame-resistant long-sleeve clothing", "Heat-resistant gloves", "Safety shoes", "Face shield at the tip dresser"),
    params=(
        ("Regulated gun and clamp air", f"{g(plant.AIR_REGULATOR_BAR)} bar", "Set at the cell filter-regulator; supplied from the plant air header"),
        ("Servo derate start", f"{g(plant.SERVO_DERATE_START_C)} degC", "Above this servo temperature the drive reduces speed"),
        ("Cycle time added by derating", f"{g(plant.SERVO_DERATE_S_PER_C)} s per degC", "Above the derate start temperature"),
        ("Servo over-temperature trip", f"{g(_srv.trip_hi)} degC", "Drive stops the cell"),
        ("Nominal cycle time", f"{g(_cyc.nominal)} s", "Including part transfer"),
        ("Tip dressing interval", f"{MANUAL_ONLY['tip_dress_welds']} welds", "Set in the weld schedule"),
        ("Cap change interval", f"{MANUAL_ONLY['cap_change_dressings']} dressings", "Or when the tip face cannot be restored"),
        ("Coolant flow, nominal (ST30)", f"{g(_clt.nominal)} L/min", "Gun and servo circuit"),
    ),
    events=(
        ("A-ST20-WLD-QA / A-ST30-WLD-QA", "weld monitor: weld energy out of band", "Weld outside its current/resistance window; see {S:tip_wear}"),
        ("A-ST20-GUN-FRC / A-ST30-GUN-FRC", "gun force not reached", "Electrode force below target; see {S:gun_air}"),
        ("A-ST20-CLAMP-RTY", "clamp position retry", "Clamp did not reach position first time; see {S:fixture}"),
        ("S-ST20-SRV-OT / S-ST30-SRV-OT", "servo drive over-temperature trip", "Drive stopped the cell; see {S:servo_ot}"),
        ("S-ST20-AIR-LO / S-ST30-AIR-LO", "gun air pressure low, cell stopped", "Supply-air interlock; see {S:gun_air}"),
        ("S-ST20-WLD-FLT / S-ST30-WLD-FLT", "repeated weld faults, cell stopped", "Several weld faults in a row; see {S:changeover_weld} and {S:tip_wear}"),
        ("A-ST20-DOOR-OPN / A-ST30-DOOR-OPN", "cell door opened (key switch)", "Information"),
        *_flow_events(_W, _W3),
        *_COMMON_EVENTS,
    ),
    changeover=(),
    timers=(
        ("Weld schedule (per product model)", "Weld current, weld time and electrode force for each spot", "Weld engineer"),
        ("Clamp settle timer", "Delay between clamps closed and first weld", "Maintenance with change request"),
        ("Gun open dwell", "Delay before the part is released after the last weld", "Maintenance with change request"),
        ("Tip dressing interval", "Welds between dressings", "Weld engineer"),
        ("Current stepper curve", "Current increase per block of welds since the last dressing", "Weld engineer"),
    ),
    timer_rows=_timer_rows("ST20 or ST30"),
    correlates=(
        ("servo_temp_c", f"Cycle time (derating above {g(plant.SERVO_DERATE_START_C)} degC), coolant flow on ST30, cabinet fan sound, handheld reading at the drive heat sink"),
        ("coolant_flow_lpm (ST30)", "Servo temperature (rises some minutes after a real flow loss), strainer differential, flow at the drain"),
        ("tip_resistance_mohm", "Weld current stepper count, tip face condition, weld quality at ST60"),
        ("air_pressure_bar", "Plant air header pressure, the other weld cell's air pressure, the cell pressure gauge"),
        ("weld_current_ka", "Tip resistance, stepper count, weld monitor alarms"),
    ),
    topics=(
        Topic(
            "tip_wear", MANUAL[C.WELD_TIP_WEAR].topic,
            f"Tip resistance (`tip_resistance_mohm`) climbs steadily over hours from about {g(_tipr.nominal)} mOhm towards the {g(_tipr.alarm_hi)} mOhm alarm limit as the tip faces pick up coating material and oxide (which raises contact resistance) and lose their shape, while the current stepper raises weld current (`weld_current_ka`) to compensate. Rejects at ST60 follow later, once the weld nuggets become undersized. Servo temperature, gun air pressure and cycle time stay normal.",
            (
                "Tip resistance that rises in a straight line over several hours, together with a stepping weld current, is the signature of electrode tip wear, not of a controller fault.",
                "If tip resistance rises at one weld cell only, the tips or the tip dresser at that cell are the cause; if weld faults start at ST20 right after a press changeover, check the parts first (see {S:changeover_weld}).",
                "A tip dresser that runs but removes no material leaves tip resistance rising even though the dressing cycles are logged.",
            ),
            (
                Row(f"`tip_resistance_mohm` above {g(_tipr.normal_hi)} mOhm and still rising", "Electrode tips mushroomed; dressing interval too long for the current stepper curve", "Inspect the tip face with the tip gauge; compare the dresser counter with the dressing interval in {T:params}", "Dress the tips; if the face cannot be restored, change the caps (see {T:maint})"),
                Row("Weld current stepping up between dressings", "Current stepper compensating for tip face growth (normal up to the end of the stepper curve)", f"Compare `weld_current_ka` with the normal range {rng(_W, 'weld_current_ka')} kA in {{T:spec_{_W}}}", "Dress the tips and confirm that the stepper resets"),
                Row("Dresser cycle logged but tip resistance does not fall", "Dresser cutter blade worn or chipped; dresser motor not reaching speed", "Inspect the cutter blade and chip discharge; take a carbon imprint of the tip face", "Replace the cutter blade; verify the tip face with a new imprint"),
                Row("ST60 weld rejects rising, weld current inside the normal range", "Undersized nuggets from worn tips late in the dressing interval, or a non-weld cause", "Trend `tip_resistance_mohm` over the last shift; if it is flat, go to {S:fixture}", "Dress the tips; quarantine the parts produced since the last good destructive test"),
                Row("Weld monitor alarm A-ST20-WLD-QA or A-ST30-WLD-QA", "Weld outside its current or resistance window", "Check which spot and which signal left the window", "Follow the row above that matches the signal"),
            ),
            background="bg_tip_wear",
        ),
        Topic(
            "servo_ot", MANUAL[C.SERVO_OVERHEAT].topic,
            f"Servo-gun drive temperature (`servo_temp_c`) rises above its normal range of {rng(_W, 'servo_temp_c')} degC. Above {g(plant.SERVO_DERATE_START_C)} degC the drive derates its speed, adding about {g(plant.SERVO_DERATE_S_PER_C)} s to the cycle for every degree above that point, so the cell cycle time rises and stations downstream are starved. The {g(_srv.alarm_hi)} degC alarm comes before the {g(_srv.trip_hi)} degC trip. A failing cabinet fan is often audible before the trip.",
            (
                "On ST30, check coolant flow first: a servo temperature rise that follows a fall in coolant flow is a cooling-circuit problem (see {S:coolant}), not a drive problem.",
                "A servo temperature rise with normal coolant flow and a cabinet fan that is noisy, slow or stopped points to the cabinet cooling fan or a clogged cabinet filter.",
                "A servo temperature reading that climbs while cycle time, weld current and coolant flow stay normal may be an instrument problem; see {S:sensor}.",
            ),
            (
                Row(f"`servo_temp_c` above {g(_srv.normal_hi)} degC, cycle time normal", "Cabinet fan failing or filter mat clogged; high ambient temperature", "Listen to the cabinet fan; inspect the filter mat; compare cabinet and ambient temperature", "Clean or replace the filter mat; replace the fan (see {T:maint})"),
                Row(f"`servo_temp_c` above {g(plant.SERVO_DERATE_START_C)} degC and `cycle_time_s` rising", "Drive derating to protect itself", "Confirm the derate message on the drive display", "Remove the heat cause; do not raise the derate threshold"),
                Row(f"Trip S-ST20-SRV-OT or S-ST30-SRV-OT at {g(_srv.trip_hi)} degC", "Sustained overheating not corrected at the alarm stage", "Check coolant flow (ST30), the cabinet fan and the gun mechanics for binding", "Let the drive cool; restart only after the cause is found"),
                Row("Gun moves slowly or stalls while temperature rises", "Mechanical binding in the gun spindle or worn roller screw", "Move the gun by hand under energy control (Chapter 8); feel for tight spots", "Lubricate or replace the roller screw (see {T:maint})"),
            ),
            background="bg_servo_ot",
        ),
        Topic(
            "coolant", MANUAL[C.COOLANT_BLOCKAGE].topic,
            f"Coolant flow (`coolant_flow_lpm`, ST30 only) falls below its normal range of {rng(_W3, 'coolant_flow_lpm')} L/min and the {g(_clt.alarm_lo)} L/min low alarm follows. With less cooling, servo temperature starts to rise about 15 minutes later, then the drive derates (cycle time rises) and finally trips on over-temperature. Weld current becomes noisier as the electrodes run hot.",
            (
                "Falling coolant flow followed some minutes later by rising servo temperature identifies a restricted coolant circuit; a servo temperature rise without any flow change does not.",
                "Coolant flow that falls at ST30 while the chiller supply temperature stays normal points to a restriction inside the cell (strainer, kinked hose, scaled gun passages), not to the chiller.",
            ),
            (
                Row(f"`coolant_flow_lpm` below {g(_clt.normal_lo)} L/min", "Cell strainer clogged", "Read the strainer differential gauge; inspect the strainer basket", "Clean the strainer basket under energy control (Chapter 8)"),
                Row("Flow low on one gun circuit only", "Kinked or crushed hose in the gun dress pack", "Trace the hoses along the dress pack; look for flattened sections", "Replace the hose; re-secure the dress pack"),
                Row("Flow recovers after back-flushing but falls again within days", "Scale or debris in the gun cooling passages", "Inspect drained coolant for scale; check water treatment records", "Descale the gun passages; review water treatment with the utilities technician"),
                Row("Coolant flow low and chiller supply temperature high", "Chiller supply problem", "Check `supply_temp_c` against {T:compressed_air/spec_UT-CHL}", "Refer to the plant air and utilities manual, Appendix B"),
                Row(f"Alarm {plant.alarm_code(_W3, 'coolant_flow_lpm', 'LO')}", f"Coolant flow below {g(_clt.alarm_lo)} L/min", "Follow the first row of this table", "-"),
            ),
            background="bg_coolant",
        ),
        Topic(
            "fixture", MANUAL[C.FIXTURE_MISALIGNMENT].topic,
            "Cycle time (`cycle_time_s`) becomes erratic: most cycles are normal, but some take several seconds longer because a clamp has to retry (A-ST20-CLAMP-RTY). Weld current, tip resistance and servo temperature remain normal. ST60 rejects rise because welds are placed off-position or parts are not seated.",
            (
                "Rejects at ST60 with normal weld current and normal tip resistance point away from the weld process and towards part location: fixture, clamps or locating pins.",
                "Cycle-time scatter with clamp retries and no change in the weld signals is the signature of a misaligned fixture or a worn locating pin.",
            ),
            (
                Row("Clamp retry alarms (A-ST20-CLAMP-RTY) and cycle-time scatter", "Clamp proximity switch misadjusted or clamp arm bushings worn", "Watch several cycles; check the switch-to-target gap", "Adjust or replace the switch; replace worn bushings"),
                Row("Weld position rejects at ST60, weld signals normal", "Locating pin worn, or fixture moved after a collision", "Check pins with the go/no-go gauge; check the fixture against its reference marks", "Replace the pins; realign the fixture to the reference marks and record it in the fixture log"),
                Row("Part-not-seated detected intermittently", "Weld spatter or debris on locators or net pads", "Inspect the locators and net pads", "Clean the net pads every shift (see {T:maint})"),
            ),
            background="bg_fixture",
        ),
        Topic(
            "gun_air", "Gun air pressure low",
            f"Regulated gun air (`air_pressure_bar`) normally sits at {g(plant.AIR_REGULATOR_BAR)} bar within {rng(_W, 'air_pressure_bar')} bar. Below {g(_air.alarm_lo)} bar the cell raises a low-air alarm; at {g(_air.trip_lo)} bar the supply-air interlock stops the cell. Gun force alarms (A-ST20-GUN-FRC, A-ST30-GUN-FRC) can appear as the air falls.",
            (
                "When gun air pressure falls at ST20 and ST30 together, the cause is upstream in the plant air supply; check the header pressure (see {S:compressed_air/leak}) before working on either cell.",
                "When gun air falls at one cell only, check that cell's filter-regulator, drop-leg ball valve and quick couplings.",
            ),
            (
                Row("Gun air low at both ST20 and ST30", "Plant air header pressure low (leak or compressor problem)", "Check `header_pressure_bar` on UT-AIR", "Follow the plant air and utilities manual, Section 6"),
                Row("Gun air low at one cell only", "Filter-regulator element clogged, regulator drifted, or local leak", "Read the cell gauge; listen for leaks at the drop leg and couplings", "Replace the filter element; reset the regulator; repair the leak"),
                Row("Gun force alarm with normal gun air", "Servo gun force calibration out, or worn roller screw", "Run the force check with the calibrated force gauge", "Recalibrate the gun force; replace the roller screw if needed"),
            ),
        ),
        Topic(
            "changeover_weld", "Weld faults after a press changeover",
            "Weld quality alarms and a growing scatter in tip resistance at ST20 that start soon after a product changeover, with normal tip dressing records, often come from parts formed out of tolerance at the ST10 press.",
            (
                "Check the ST10 press main pressure against the recipe setpoint for the new model (see {T:press_hydraulics/setpoints}) before changing any weld schedule.",
            ),
            (
                Row("Weld faults at ST20 starting after a changeover", "Parts from ST10 formed with a wrong pressure setpoint", "Compare `hyd_pressure_bar` on ST10-PRS with the recipe setpoint", "Correct the press recipe (press manual, Section 6); quarantine affected parts"),
                Row("Weld faults after a changeover, press pressure correct", "Wrong weld schedule selected for the new model", "Check the active weld schedule number against the model", "Select the correct schedule under change control"),
            ),
        ),
    ),
    maintenance=(
        ("Clean fixture net pads and locators", "Every shift", "{S:fixture}"),
        ("Check tip face with the tip gauge", "Every shift", "{S:tip_wear}"),
        ("Inspect tip dresser cutter blade", "Weekly", "{S:tip_wear}"),
        ("Clean the coolant strainer (ST30)", "Weekly", "{S:coolant}"),
        ("Clean or replace the drive cabinet filter mat", "Monthly", "{S:servo_ot}"),
        ("Check the cabinet fan for noise and air flow", "Monthly", "{S:servo_ot}"),
        ("Replace the cell air filter element", "Quarterly", "{S:gun_air}"),
        ("Gun force calibration with the force gauge", "Quarterly", "{S:gun_air}"),
        ("Lubricate the gun roller screw", "Every 6 months", "{S:servo_ot}"),
        ("Calibration check of servo temperature, coolant flow and air pressure transmitters", "Yearly", "{S:sensor}"),
    ),
    spares=(
        ("Electrode caps", "Box of 50"), ("Tip dresser cutter blade", "2"), ("Cabinet fan and filter mats", "1 fan, 5 mats"),
        ("Coolant hose set for the gun dress pack", "1"), ("Clamp proximity switches", "2"), ("Locating pins", "1 set"),
    ),
)  # fmt: skip

# ------------------------------------------------------------------------------------------------
# Sealer pump
# ------------------------------------------------------------------------------------------------
_S = "ST40-SLR"
_sp, _sf, _sc, _sb = (
    T(_S, "pump_pressure_bar"),
    T(_S, "flow_rate_ccm"),
    T(_S, "motor_current_a"),
    T(_S, "bead_width_mm"),
)
_stroke_s = 1 / plant.SEALER_STROKE_HZ

SEALER = ManualSpec(
    doc="sealer_pump",
    title="Sealer Supply Pump and Dispense System - Operation and Maintenance Manual",
    doc_no="AM-SP-01",
    applies_to=(_S,),
    equipment="Electrically driven reciprocating piston pump on a drum unloader with a follower plate, feeding a high-viscosity body sealer through high-pressure hoses to a dispense nozzle that lays a bead on each part.",
    components=(
        ("Drum unloader", "Air-driven ram that pushes the follower plate down into the material drum"),
        ("Follower plate", "Plate with a wiper seal that keeps air out of the material and feeds the pump inlet"),
        ("Piston pump", "Double-acting reciprocating pump with an inlet (foot) check valve and a piston check valve"),
        ("Pump drive", "Electric gearmotor and crank driving the pump at a constant stroke rate"),
        ("Inlet strainer", "Protects the pump from skins and debris in the material"),
        ("Material hoses", "High-pressure hoses from the pump outlet to the dispense nozzle"),
        ("Dispense nozzle", "Air-operated valve and nozzle tip; lays the bead"),
        ("Pressure and flow transmitters", "Outlet pressure and volumetric flow to the controller"),
        ("Bead inspection sensor", "Measures the bead width on every part"),
        ("Material relief valve", "Releases material pressure to a waste container"),
    ),
    hazards=(
        ("Fluid injection", "Hoses, fittings, nozzle at full material pressure", "Never touch a leak; relieve pressure before opening anything (Chapter 8)"),
        ("Crushing", "Drum ram and follower plate", "Keep hands clear of the plate; lower the plate before reaching under it"),
        ("Skin and eye contact with sealer", "Nozzle, drum, waste container", "Nitrile gloves and safety glasses"),
        ("Electric shock", "Pump drive and panel", "Energy control procedure (Chapter 8)"),
        ("Stored air pressure", "Ram cylinder, nozzle valve", "Vent through the ram air lockout valve (Chapter 8)"),
    ),
    ppe=("Safety glasses with side shields", "Nitrile gloves", "Long sleeves", "Safety shoes"),
    params=(
        ("Pump stroke rate", f"{g(plant.SEALER_STROKE_HZ)} Hz", f"One stroke about every {_stroke_s:.1f} s"),
        ("Outlet pressure, nominal", f"{g(_sp.nominal)} bar", "At normal flow"),
        ("Flow, nominal", f"{g(_sf.nominal)} cc/min", "Volumetric"),
        ("Bead width, nominal", f"{g(_sb.nominal)} mm", "Measured on every part"),
        ("Drive motor current, nominal", f"{g(_sc.nominal)} A", "At normal flow"),
    ),
    events=(
        ("A-ST40-BEAD-QA", "bead inspection: bead width out of tolerance", "Bead narrow, wide or broken; see {S:cavitation} and {S:bead}"),
        ("A-ST40-NOZ-PRG", "nozzle purge requested", "Information; routine purge"),
        *_flow_events(_S),
        *_COMMON_EVENTS,
    ),
    changeover=(),
    timers=(
        ("Bead program (per product model)", "Nozzle open and close points along the part", "Process engineer"),
        ("Nozzle purge interval", "Time without dispensing before an automatic purge", "Maintenance with change request"),
        ("Dispense start delay", "Delay between nozzle open command and part motion", "Maintenance with change request"),
    ),
    timer_rows=_timer_rows("ST40"),
    correlates=(
        ("pump_pressure_bar", "Flow rate, drive motor current, bead width; a real pressure change moves at least one of them"),
        ("flow_rate_ccm", "Bead width, pump pressure, drum level"),
        ("bead_width_mm", "Flow rate, nozzle condition"),
    ),
    topics=(
        Topic(
            "cavitation", MANUAL[C.SEALER_PUMP_CAVITATION].topic,
            f"Outlet pressure (`pump_pressure_bar`) starts to pulse at the pump stroke rate ({g(plant.SEALER_STROKE_HZ)} Hz, one stroke about every {_stroke_s:.1f} s) and its mean falls. Flow (`flow_rate_ccm`) drops below its normal range of {rng(_S, 'flow_rate_ccm')} cc/min. Motor current falls slightly and becomes unsteady because the pump moves less material. The bead becomes narrow and uneven (A-ST40-BEAD-QA) and ST60 rejects rise. The pump sounds rough, with a knock on each stroke.",
            (
                "Pressure pulsing at the stroke rate together with falling flow means the pump is not filling on each stroke: a starved inlet or cavitation, not a blocked nozzle.",
                "A blocked nozzle raises outlet pressure and lowers flow; a starved inlet lowers both pressure and flow.",
                "Check the drum level and the follower plate seal before opening the pump.",
            ),
            (
                Row("Pressure pulsing at the stroke rate, flow low", "Drum empty, or follower plate not following the material", "Check the drum level indicator and the follower plate position", "Change the drum and bleed air from under the follower plate"),
                Row("Pulsing continues after a drum change", "Air drawn in past a worn follower plate wiper seal", "Inspect the wiper seal; look for air pockets at the bleed port", "Replace the wiper seal; bleed the pump"),
                Row("Flow low and pulsing worst at shift start", "Material too viscous (cold drum)", "Check the material temperature against the material data sheet", "Condition drums in the warm store before use"),
                Row("Flow low, pulsing, drum and seal good", "Inlet strainer clogged", "Check the strainer differential; inspect the basket", "Clean the strainer under energy control (Chapter 8)"),
                Row("Pressure drop on one stroke direction only", "Worn foot check valve or piston packing", "Watch the pressure trace stroke by stroke", "Repack the pump or replace the check valve (see {T:maint})"),
            ),
            background="bg_cavitation",
        ),
        Topic(
            "bead", "Bead width out of tolerance",
            f"Bead width (`bead_width_mm`) normally stays within {rng(_S, 'bead_width_mm')} mm. The {g(_sb.alarm_lo)} mm and {g(_sb.alarm_hi)} mm limits raise A-ST40-BEAD-QA.",
            (
                "A narrow bead with normal flow and pressure points to the nozzle or the bead program; a narrow bead with low flow points to the pump supply (see {S:cavitation}).",
            ),
            (
                Row("Bead narrow, flow and pressure normal", "Nozzle tip partly blocked with cured material", "Inspect the nozzle tip", "Clean or replace the nozzle tip"),
                Row("Bead wide or doubled at the start of a part", "Dispense start delay wrong", "Compare the active parameter with the approved copy", "Restore under change control (see {S:ch5})"),
                Row("Pressure high, flow low, no pulsing", "Hose or nozzle partly blocked", "Purge the nozzle; check the pressure drop along the hose", "Clean the nozzle; replace the hose if blocked"),
            ),
        ),
    ),
    maintenance=(
        ("Purge and wipe the nozzle tip", "Every shift", "{S:bead}"),
        ("Check the drum level and change drums", "As needed", "{S:cavitation}"),
        ("Inspect the follower plate wiper seal", "Weekly", "{S:cavitation}"),
        ("Clean the inlet strainer", "Weekly", "{S:cavitation}"),
        ("Inspect material hoses for wear and bulges", "Monthly", "{S:bead}"),
        ("Repack the pump and inspect the check valves", "Every 6 months", "{S:cavitation}"),
        ("Calibration check of pressure and flow transmitters", "Yearly", "{S:sensor}"),
    ),
    spares=(("Follower plate wiper seal", "2"), ("Pump packing kit", "1"), ("Foot check valve", "1"), ("Nozzle tips", "5"), ("Strainer basket", "1")),
)  # fmt: skip

# ------------------------------------------------------------------------------------------------
# Conveyor drive (+ Appendix B: ST60 vision check interface data)
# ------------------------------------------------------------------------------------------------
_K = "ST50-CNV"
_kv, _kt, _kc, _ks = (
    T(_K, "vibration_rms_mms"),
    T(_K, "bearing_temp_c"),
    T(_K, "motor_current_a"),
    T(_K, "speed_mpm"),
)
_rot_hz = float(plant.CONVEYOR_ROTATION_HZ)
_V = "ST60-VIS"

CONVEYOR = ManualSpec(
    doc="conveyor_drive",
    title="Chain Conveyor Drive Unit - Operation and Maintenance Manual",
    doc_no="AM-CD-01",
    applies_to=(_K,),
    equipment="Chain conveyor drive unit moving part carriers between the stations at a constant chain speed: inverter-fed brake gearmotor, drive shaft on two bearings, drive sprocket and pulley, and a spring take-up at the return end.",
    components=(
        ("Drive inverter", "Controls motor speed; holds the chain speed constant"),
        ("Brake gearmotor", "Motor with spring-applied brake and helical gearbox"),
        ("Drive shaft and bearings", "Drive-end and non-drive-end rolling bearings in housings; the drive-end housing carries the vibration and temperature sensors"),
        ("Drive sprocket and pulley", f"Pulley diameter {g(plant.CONVEYOR_PULLEY_DIAMETER_M)} m"),
        ("Chain and carriers", "Carriers move the parts between stations"),
        ("Spring take-up", "Keeps the chain under tension at the return end"),
        ("Vibration sensor", "Velocity RMS at the drive-end bearing housing; high-rate snapshots available for spectrum analysis"),
        ("Bearing temperature sensor", "Drive-end bearing housing temperature"),
    ),
    hazards=(
        ("Entanglement and crushing", "Chain, sprocket, carriers, take-up", "Guards in place; energy control before reaching in (Chapter 8)"),
        ("Unexpected chain movement", "Loaded carriers on inclines; take-up spring", "Chain lock; release spring tension only as described in Chapter 8"),
        ("Burns", "Bearing housings, gearbox", "Heat-resistant gloves"),
        ("Electric shock", "Inverter DC bus, motor terminals", "Energy control procedure (Chapter 8); wait for DC bus discharge"),
    ),
    ppe=("Safety glasses", "Close-fitting clothing, no loose sleeves", "Cut-resistant gloves", "Safety shoes"),
    params=(
        ("Chain speed, nominal", f"{g(_ks.nominal)} m/min", "Held by the inverter"),
        ("Pulley diameter", f"{g(plant.CONVEYOR_PULLEY_DIAMETER_M)} m", "Drive end"),
        ("Pulley rotation frequency (1x)", f"{_rot_hz:.3f} Hz", f"At {g(_ks.nominal)} m/min; one turn every {1 / _rot_hz:.1f} s"),
        ("Drive motor current, nominal", f"{g(_kc.nominal)} A", "Loaded chain"),
        ("Vibration alarm / trip", f"{g(_kv.alarm_hi)} / {g(_kv.trip_hi)} mm/s", "Velocity RMS, drive-end bearing"),
    ),
    events=(
        ("A-ST50-ESTOP-RST", "e-stop reset acknowledged", "Information"),
        ("S-ST50-VIB-HH", "Conveyor drive stopped: vibration high-high", "Trip; see {S:bearing}"),
        *_flow_events(_K),
        *_COMMON_EVENTS,
    ),
    changeover=(),
    timers=(
        ("Chain speed setpoint", "Inverter speed reference", "Maintenance with change request"),
        ("Acceleration and deceleration ramps", "Inverter ramps", "Maintenance with change request"),
        ("Transfer dwell", "Time a carrier waits at each station transfer", "Process engineer"),
    ),
    timer_rows=_timer_rows("ST50 or ST60"),
    correlates=(
        ("bearing_temp_c", "Vibration RMS, motor current, handheld temperature at the housing"),
        ("vibration_rms_mms", "Bearing temperature (rises some minutes later in a real defect), motor current, sound of the bearing"),
        ("speed_mpm", "Motor current, cycle times of the stations"),
    ),
    topics=(
        Topic(
            "bearing", MANUAL[C.CONVEYOR_BEARING_DEFECT].topic,
            f"Drive-end bearing vibration (`vibration_rms_mms`) rises out of its normal range of {rng(_K, 'vibration_rms_mms')} mm/s, slowly at first and then faster. The one-second RMS trend carries a ripple at the pulley rotation frequency (about {_rot_hz:.3f} Hz at {g(_ks.nominal)} m/min, one turn every {1 / _rot_hz:.1f} s). Bearing temperature (`bearing_temp_c`) follows some minutes later; motor current rises slightly and chain speed sags. The {g(_kv.alarm_hi)} mm/s alarm comes before the {g(_kv.trip_hi)} mm/s trip (S-ST50-VIB-HH). Stations upstream show rising cycle times because the slower conveyor blocks them. The bearing sounds rough, with a grinding or knocking that repeats with each pulley turn.",
            (
                "Vibration that grows in an accelerating curve, with a ripple at the pulley rotation frequency and a delayed rise in bearing temperature, indicates a drive-end bearing defect.",
                "In the high-rate vibration spectrum, a bearing defect shows peaks at the bearing defect frequencies and their harmonics; calculate them from the bearing geometry on the bearing data sheet.",
                "Rising cycle times at stations upstream of ST50 are a consequence of the conveyor slowing, not a fault at those stations.",
                "A bearing temperature rise without any vibration change is unlikely to be a bearing defect; verify the temperature sensor (see {S:sensor}).",
            ),
            (
                Row(f"`vibration_rms_mms` above {g(_kv.normal_hi)} mm/s and accelerating, ripple at 1x pulley rotation", "Drive-end bearing defect (race or rolling element damage)", "Spectrum of a high-rate snapshot; listen with a stethoscope; check the grease condition", "Plan a bearing replacement; reduce speed only under change control; replace at the next stop"),
                Row("Vibration high, steady, started after chain or sprocket work", "Shaft misalignment or loose bearing housing bolts", "Check the housing bolt torque and the shaft alignment", "Re-torque the bolts; realign the shaft"),
                Row(f"`bearing_temp_c` above {g(_kt.normal_hi)} degC with normal vibration", "Over-greasing or temperature sensor problem", "Check the grease log; compare with a handheld thermometer", "Purge excess grease; or see {S:sensor}"),
                Row("Motor current high and chain speed low", "Chain binding, carrier jammed, or take-up too tight", "Walk the chain path; check the take-up spring length", "Clear the jam; reset the take-up to the recorded length"),
                Row(f"Speed low alarm {plant.alarm_code(_K, 'speed_mpm', 'LO')}", f"Chain speed below {g(_ks.alarm_lo)} m/min", "Check motor current and the inverter fault log", "Follow the row above that matches"),
            ),
            background="bg_bearing",
        ),
    ),
    maintenance=(
        ("Listen to the drive-end bearing and check for oil leaks", "Every shift", "{S:bearing}"),
        ("Check chain tension at the take-up", "Weekly", "{S:bearing}"),
        ("Grease the drive shaft bearings", "Monthly", "{S:bearing}"),
        ("Take a high-rate vibration snapshot and review the spectrum", "Monthly", "{S:bearing}"),
        ("Check gearbox oil level", "Monthly", "{S:bearing}"),
        ("Replace gearbox oil", "Yearly", "{S:bearing}"),
        ("Calibration check of the vibration and bearing temperature sensors", "Yearly", "{S:sensor}"),
    ),
    spares=(("Drive-end bearing and housing seals", "1 set"), ("Chain links and pins", "10"), ("Take-up spring", "1"), ("Bearing grease", "2 cartridges")),
    appendix=Appendix(
        "appx_vis", "ST60 vision check: interface data",
        "The ST60 vision check inspects every part at the end of the line and is carried by this conveyor. It finds defects made upstream; it does not cause them. Its limits are listed here so that conveyor and line problems can be told apart from inspection problems.",
        (_V,),
        (
            Topic(
                "rejects", "Reject rate high at ST60",
                f"Reject rate (`reject_rate_pct`) is the share of rejects in the last 100 inspected parts; normal is {rng(_V, 'reject_rate_pct')} %. A rise above {g(T(_V, 'reject_rate_pct').alarm_hi)} % on consecutive checks causes a quality stop (S-ST60-QSTOP).",
                (
                    "ST60 detects defects but does not cause them; trace each reject type to the station that makes that feature.",
                    "Weld position or weld quality rejects point to ST20 or ST30; bead rejects point to ST40.",
                ),
                (
                    Row("Weld rejects rising", "Weld process or part location at ST20/ST30", "Check tip resistance and clamp retries at ST20/ST30", "See the weld cell manual, Section 6"),
                    Row("Bead rejects rising", "Sealer supply or nozzle at ST40", "Check sealer flow and pressure", "See the sealer manual, Section 6"),
                    Row("Rejects rising with no defect visible on re-inspection", "Camera dirty, lighting failed or camera communication retries (A-ST60-CAM-COMM)", "Re-inspect rejected parts by hand; clean the lens", "Clean the lens; replace the light"),
                ),
            ),
        ),
    ),
)  # fmt: skip

# ------------------------------------------------------------------------------------------------
# Press hydraulics
# ------------------------------------------------------------------------------------------------
_P = "ST10-PRS"
_pp, _pc, _pt, _pv, _py = (
    T(_P, "hyd_pressure_bar"),
    T(_P, "motor_current_a"),
    T(_P, "oil_temp_c"),
    T(_P, "vibration_rms_mms"),
    T(_P, "cycle_time_s"),
)
_sp_a = plant.PRODUCT_SETPOINTS["A"][(_P, "hyd_pressure_bar")]
_sp_b = plant.PRODUCT_SETPOINTS["B"][(_P, "hyd_pressure_bar")]

PRESS = ManualSpec(
    doc="press_hydraulics",
    title="Hydraulic Press and Power Unit - Operation and Maintenance Manual",
    doc_no="AM-PH-01",
    applies_to=(_P,),
    equipment="Hydraulic forming press with a separate power unit: electric motor and variable pump, proportional pressure valve, directional valves, bladder accumulator, oil cooler and tank. The main pressure setpoint is part of the product recipe.",
    components=(
        ("Pump motor", "Electric motor driving the hydraulic pump"),
        ("Hydraulic pump", "Variable displacement pump; internal leakage grows with wear"),
        ("Proportional pressure valve", "Sets the main system pressure from the active recipe"),
        ("Directional valves", "Switch oil to the press cylinder for each stroke"),
        ("Bladder accumulator", "Nitrogen-precharged; supplies peak flow during the stroke and smooths pressure"),
        ("Oil cooler", "Keeps the oil inside its temperature range"),
        ("Tank and filters", "Oil reservoir with return and pressure filters"),
        ("Press cylinder and slide", "Carries the upper die"),
        ("Sensors", "Main pressure, oil temperature, pump/motor vibration, motor current"),
    ),
    hazards=(
        ("High-pressure oil injection", "Hoses, fittings, accumulator", "Relieve pressure before opening anything (Chapter 8)"),
        ("Crushing", "Die area, slide", "Guards, light curtain, safety blocks under the slide (Chapter 8)"),
        ("Stored energy in the accumulator", "Accumulator and main circuit", "Dump to tank (Chapter 8)"),
        ("Burns", "Hot oil, pump, cooler lines", "Heat-resistant gloves and face shield"),
        ("Electric shock", "Motor and panel", "Energy control procedure (Chapter 8)"),
        ("Slips", "Oil on the floor", "Clean up leaks immediately"),
    ),
    ppe=("Safety glasses", "Face shield when opening hydraulic lines", "Oil-resistant gloves", "Safety shoes"),
    params=(
        ("Main pressure setpoint, product model A", f"{g(_sp_a)} bar", "Loaded with the model A recipe"),
        ("Main pressure setpoint, product model B", f"{g(_sp_b)} bar", "Loaded with the model B recipe"),
        ("Setpoint tolerance after changeover", f"+/- {g(MANUAL_ONLY['setpoint_tolerance_bar'])} bar", "Check before releasing the first part"),
        ("Nominal cycle time", f"{g(_py.nominal)} s", "One part"),
        ("Oil temperature alarm / trip", f"{g(_pt.alarm_hi)} / {g(_pt.trip_hi)} degC", "Tank"),
        ("Shift start times (changeover)", "06:00, 14:00, 22:00", f"{plant.CHANGEOVER_S // 60} min planned changeover at each shift start"),
    ),
    events=(
        ("S-ST10-HYD-FLT", "ST10 Press: hydraulic fault, press stopped", "Hydraulic protection; see {S:hyd}"),
        ("A-ST10-LUB-LOW", "way-lube reservoir low", "Information; refill"),
        *_flow_events(_P),
        *_COMMON_EVENTS,
    ),
    changeover=(
        "Select the recipe for the new product model at the operator panel.",
        "Confirm the recipe name on the panel matches the model on the production schedule.",
        "Run the first stroke and read the main pressure on the panel.",
        "Compare the main pressure with the setpoint for the model in {T:setpoints}.",
        "Release the first part only if the pressure is within the tolerance in {T:setpoints}.",
        "Record the model, recipe and pressure in the changeover log.",
    ),
    timers=(
        ("Main pressure setpoint (per product model)", "Proportional valve command from the recipe", "Process engineer"),
        ("Dwell at bottom of stroke", "Holding time under pressure", "Process engineer"),
        ("Decompression time", "Time to release pressure before the slide returns", "Maintenance with change request"),
    ),
    timer_rows=_timer_rows("ST10"),
    correlates=(
        ("oil_temp_c", "Cooler outlet temperature by hand, motor current, cycle time, handheld reading at the tank"),
        ("hyd_pressure_bar", "Motor current, cycle time, panel gauge"),
        ("vibration_rms_mms", "Motor current, pump sound, pressure stability"),
    ),
    topics=(
        Topic(
            "changeover", MANUAL[C.CHANGEOVER_ERROR].topic,
            f"Each product model has its own main pressure setpoint: model A {g(_sp_a)} bar and model B {g(_sp_b)} bar (see {{T:setpoints}}). If the recipe for the wrong model, or a wrong value, is loaded at a changeover, main pressure (`hyd_pressure_bar`) settles at the wrong level as a clean step right after the changeover and stays there. Parts are under-formed, and the ST20 weld cell downstream starts to show weld quality alarms and scatter in tip resistance.",
            (
                "A step change in main pressure that starts exactly at a changeover, with oil temperature and vibration unchanged, is a recipe or setpoint error, not hydraulic wear.",
                f"After every model change, compare the displayed main pressure with the setpoint for the model now running before releasing the first part; the tolerance is +/- {g(MANUAL_ONLY['setpoint_tolerance_bar'])} bar.",
                "Weld faults at ST20 that start after a press changeover are often caused by the press; check this section before changing weld schedules.",
            ),
            (
                Row("Main pressure off setpoint right after a changeover, then steady", "Wrong recipe loaded, or a wrong setpoint saved in the recipe", "Compare the active recipe and setpoint with {T:setpoints} and the production schedule", "Load the correct recipe; quarantine parts made since the changeover"),
                Row("Weld faults at ST20 after a press changeover", "Under-formed parts from a wrong press pressure", "Check `hyd_pressure_bar` against the setpoint for the model", "Correct the press recipe first; then re-check ST20"),
                Row("Pressure correct but parts under-formed after a changeover", "Wrong die or die height", "Check the die number and the shut height", "Correct the die setup"),
            ),
            background="bg_changeover",
        ),
        Topic(
            "hyd", MANUAL[C.HYDRAULIC_DEGRADATION].topic,
            "Hydraulic wear develops over hours to days, not at a changeover. Four failure modes are common: internal pump leakage, a sluggish (lagging) switching valve, loss of accumulator precharge, and loss of cooler efficiency. Each moves pressure, motor current, oil temperature, vibration and cycle time in its own pattern; use {T:hyd_pattern} to tell them apart. All four lengthen the press cycle, which starves the stations downstream.",
            (
                "Pressure sagging below setpoint while motor current rises and oil temperature creeps up indicates internal pump leakage.",
                "A ragged pressure trace with rising vibration and scattered cycle times indicates a lagging switching valve.",
                "A slow pressure swing with a period of about 20 s, with motor current fluctuating more than usual, indicates loss of accumulator precharge.",
                "Oil temperature rising steadily while pressure and vibration stay normal indicates loss of cooler efficiency.",
                "Longer cycle times at stations downstream of ST10 are a consequence of the slower press, not faults at those stations.",
            ),
            (
                Row(f"`hyd_pressure_bar` sagging below setpoint, `motor_current_a` above {g(_pc.normal_hi)} A, oil warming", "Internal pump leakage (worn pump)", "Case drain flow test; compare with the last test record", "Replace or overhaul the pump"),
                Row(f"Pressure trace ragged, `vibration_rms_mms` above {g(_pv.normal_hi)} mm/s, cycle times scattered", "Switching valve lag (contamination, worn spool, weak solenoid)", "Check valve switching time on the diagnostic screen; check oil cleanliness", "Clean or replace the valve; change filters"),
                Row("Slow pressure swing, motor current fluctuating", "Accumulator precharge low or bladder failed", "Check the nitrogen precharge with the charging kit under energy control (Chapter 8)", "Recharge with nitrogen; replace the bladder if it does not hold"),
                Row(f"`oil_temp_c` above {g(_pt.normal_hi)} degC, rising; pressure normal", "Cooler fouled, cooling water low, or cooler fan failed", "Check the cooler inlet and outlet temperatures and the cooling water flow", "Clean the cooler; restore cooling water flow"),
                Row(f"Oil temperature trip {plant.alarm_code(_P, 'oil_temp_c', 'HH')} at {g(_pt.trip_hi)} degC", "Any of the above not corrected", "Find the cause before restart", "Let the oil cool; correct the cause"),
            ),
            background="bg_hyd",
            extra=(
                ("hyd_pattern", "Hydraulic degradation patterns",
                 ("Failure mode", "Main pressure", "Motor current", "Oil temperature", "Vibration", "Cycle time"),
                 (("Internal pump leakage", "Sags below setpoint", "Rises", "Rises slowly", "Normal", "Longer"),
                  ("Switching valve lag", "Ragged, noisy", "Normal", "Normal", "Rises", "Longer and scattered"),
                  ("Accumulator precharge loss", "Slow swing (about 20 s period), noisy", "Fluctuates", "Normal", "Normal", "Longer"),
                  ("Cooler efficiency loss", "Normal", "Normal", "Rises steadily", "Normal", "Slightly longer"))),
            ),
            page_break_before_table=True,
        ),
    ),
    maintenance=(
        ("Check oil level and look for leaks", "Every shift", "{S:hyd}"),
        ("Check the way-lube reservoir", "Every shift", "-"),
        ("Check the filter clogging indicators", "Weekly", "{S:hyd}"),
        ("Clean the oil cooler", "Quarterly", "{S:hyd}"),
        ("Check the accumulator nitrogen precharge", "Quarterly", "{S:hyd}"),
        ("Oil sample for cleanliness and water", "Quarterly", "{S:hyd}"),
        ("Pump case drain flow test", "Every 6 months", "{S:hyd}"),
        ("Replace return and pressure filter elements", "Every 6 months", "{S:hyd}"),
        ("Calibration check of pressure and oil temperature transmitters", "Yearly", "{S:sensor}"),
    ),
    spares=(("Filter elements (return and pressure)", "2 sets"), ("Accumulator bladder", "1"), ("Directional valve solenoid", "1"), ("Hydraulic oil", "1 drum"), ("Seal kit, press cylinder", "1")),
    ch3_extra=(
        ("setpoints", "Main pressure setpoints by product model",
         ("Product model", "Main pressure setpoint (bar)", "Tolerance after changeover (bar)"),
         tuple((m, g(sp[(_P, "hyd_pressure_bar")]), f"+/- {g(MANUAL_ONLY['setpoint_tolerance_bar'])}")
               for m, sp in sorted(plant.PRODUCT_SETPOINTS.items()))),
    ),
)  # fmt: skip

# ------------------------------------------------------------------------------------------------
# Compressed air (+ Appendix B: process chiller)
# ------------------------------------------------------------------------------------------------
_A = "UT-AIR"
_ah, _ac, _ao = (T(_A, "header_pressure_bar"), T(_A, "compressor_current_a"), T(_A, "oil_temp_c"))
_H = "UT-CHL"

AIR = ManualSpec(
    doc="compressed_air",
    title="Plant Air System and Utilities - Operation and Maintenance Manual",
    doc_no="AM-CA-01",
    applies_to=(_A,),
    equipment="Plant air system: oil-injected rotary screw compressor with load/unload control, air receiver, refrigerated dryer, main header and drop legs to the ST20 and ST30 weld cells. Appendix B covers the process chiller that cools the weld cells.",
    components=(
        ("Screw compressor", "Oil-injected rotary screw air end driven by an electric motor"),
        ("Inlet valve and load/unload control", f"Loads the compressor when header pressure falls to the cut-in pressure ({g(plant.AIR_CUT_IN_BAR)} bar) and unloads it at the cut-out pressure ({g(plant.AIR_CUT_OUT_BAR)} bar)"),
        ("Oil separator and cooler", "Separates oil from the compressed air and cools the oil"),
        ("Air receiver", "Stores compressed air and evens out demand"),
        ("Refrigerated dryer", "Removes moisture"),
        ("Condensate drains", "Timed drains on the receiver and dryer"),
        ("Main header and drop legs", "Distribute air to the weld cells; each drop leg has a ball valve, filter-regulator and quick couplings"),
        ("Sensors", "Header pressure, compressor motor current, compressor oil temperature"),
    ),
    hazards=(
        ("Stored air pressure", "Receiver, header, drop legs", "Isolate and bleed to zero (Chapter 8)"),
        ("Automatic restart", "Compressor", "The compressor can start at any time when header pressure falls; lock out before work (Chapter 8)"),
        ("Hot oil and surfaces", "Oil separator, discharge pipework, cooler", "Heat-resistant gloves; let parts cool"),
        ("Noise", "Compressor room", "Hearing protection"),
        ("Compressed air blast", "Open couplings, blow guns", "Never point air at a person; safety glasses"),
        ("Electric shock", "Motor and panel", "Energy control procedure (Chapter 8)"),
    ),
    ppe=("Safety glasses", "Hearing protection in the compressor room", "Heat-resistant gloves", "Safety shoes"),
    params=(
        ("Cut-in (load) pressure", f"{g(plant.AIR_CUT_IN_BAR)} bar", "Compressor loads at or below this header pressure"),
        ("Cut-out (unload) pressure", f"{g(plant.AIR_CUT_OUT_BAR)} bar", "Compressor unloads at this header pressure"),
        ("Weld cell regulator setting", f"{g(plant.AIR_REGULATOR_BAR)} bar", "At each drop leg (ST20, ST30)"),
        ("Motor current, loaded", f"about {g(plant.AIR_LOADED_CURRENT_A)} A", "Compressor delivering air"),
        ("Motor current, unloaded", f"about {g(plant.AIR_UNLOADED_CURRENT_A)} A", "Running, inlet closed"),
        ("Load/unload cycle at normal demand", "about 2 min", "Varies with demand"),
        ("Leak repair acceptance", f"Header holds pressure for {MANUAL_ONLY['header_hold_min']} min", "With the weld cells stopped"),
    ),
    events=(
        ("A-UTAIR-DRN", "Plant air: condensate drain cycle", "Information; timed drain"),
        ("A-UTCHL-FLT-SVC", "Chiller: filter service due", "Information; see Appendix B"),
        ("A-ST20-GUN-FRC / A-ST30-GUN-FRC", "gun force not reached (weld cells)", "Often the first sign of low supply air at the cells; see {S:leak}"),
        ("S-ST20-AIR-LO / S-ST30-AIR-LO", "gun air pressure low, cell stopped (weld cells)", "Supply-air interlock at the cell; see {S:leak}"),
        *_COMMON_EVENTS,
    ),
    changeover=(),
    timers=(
        ("Cut-in and cut-out pressures", "Load/unload pressure band", "Utilities technician with change request"),
        ("Condensate drain interval and open time", "Timed drains", "Utilities technician"),
        ("Restart delay after power return", "Automatic restart timer", "Utilities technician with change request"),
    ),
    timer_rows=_timer_rows("ST20 or ST30"),
    correlates=(
        ("header_pressure_bar", "Compressor load duty (motor current), gun air pressure at ST20 and ST30, the header gauge"),
        ("compressor_current_a", "Load/unload pattern, header pressure"),
        ("supply_temp_c (chiller)", "ST30 servo temperature and coolant flow, handheld reading at the supply"),
    ),
    topics=(
        Topic(
            "leak", MANUAL[C.AIR_PRESSURE_DROP].topic,
            f"In normal service the compressor loads at {g(plant.AIR_CUT_IN_BAR)} bar and unloads at {g(plant.AIR_CUT_OUT_BAR)} bar, so header pressure (`header_pressure_bar`) saw-tooths inside its normal range of {rng(_A, 'header_pressure_bar')} bar and motor current (`compressor_current_a`) switches between about {g(plant.AIR_LOADED_CURRENT_A)} A loaded and about {g(plant.AIR_UNLOADED_CURRENT_A)} A unloaded, a load/unload cycle of roughly 2 minutes. A leak first shows as a longer loaded time: average motor current rises while header pressure still recovers. When leakage plus demand exceed what the compressor can deliver, the compressor stays loaded, header pressure falls below the cut-in pressure, and the {g(_ah.alarm_lo)} bar low alarm ({plant.alarm_code(_A, 'header_pressure_bar', 'LO')}) follows. The weld cells see their regulated gun air fall shortly after; gun force alarms follow, and when gun air reaches each cell's own low limit (see the weld cell manual) the supply-air interlock stops that cell. A leak is often audible as a hiss at the leak point.",
            (
                "A sustained fall in header pressure while the compressor runs loaded indicates demand exceeding supply, most often a distribution leak.",
                "Check drop-leg fittings and quick couplings at the weld cells first; they account for most leaks on this header.",
                "A fall in gun air pressure at ST20 and ST30 at the same time, after the header pressure has fallen, places the cause in the air supply, not in the weld cells.",
                "A header pressure reading that falls while compressor duty and the gun air pressures at both cells stay normal points to the header pressure transmitter; see {S:sensor}.",
            ),
            (
                Row("Header pressure falling, compressor loaded continuously", "Distribution leak (drop legs, couplings, hoses) or a new air user", "Ultrasonic leak survey of the header and the ST20/ST30 drop legs with the cells stopped", "Repair the leaks; confirm the header holds pressure (see {T:params})"),
                Row("Compressor loaded longer than usual, header pressure still normal", "Leak developing", "Compare load duty with last week's trend; walk the header listening for hiss", "Schedule a leak survey"),
                Row("Header pressure low, compressor current low (not loading)", "Inlet valve stuck closed, or load control fault", "Check the compressor display for load status and faults", "Repair the inlet valve or load control"),
                Row("Continuous hiss at a drain, header pressure low", "Condensate drain stuck open", "Listen at the receiver and dryer drains", "Clean or replace the drain valve"),
                Row("Gun air low at one cell only, header normal", "Local problem at that cell", "Check the cell filter-regulator", "See the weld cell manual, Section 6"),
            ),
            background="bg_leak",
        ),
        Topic(
            "oil_hot", "Compressor oil temperature high",
            f"Compressor oil temperature (`oil_temp_c`) normally stays within {rng(_A, 'oil_temp_c')} degC; the alarm is at {g(_ao.alarm_hi)} degC.",
            (
                "Oil temperature rising together with longer loaded time usually follows a leak or extra demand; oil temperature rising at normal duty points to the cooler or the oil.",
            ),
            (
                Row(f"`oil_temp_c` above {g(_ao.normal_hi)} degC at normal load duty", "Oil cooler fouled or cooling fan fault", "Inspect the cooler fins and the fan", "Clean the cooler; repair the fan"),
                Row("Oil temperature high, oil level low", "Oil loss through the separator or a leak", "Check the oil level and the separator differential", "Top up; replace the separator element"),
                Row("Oil temperature high with longer loaded time", "Compressor working harder because of a leak or extra demand", "See {S:leak}", "Repair the leak"),
            ),
        ),
    ),
    maintenance=(
        ("Check the compressor display and oil level", "Every shift", "{S:oil_hot}"),
        ("Check the condensate drains operate", "Daily", "{S:leak}"),
        ("Walk the header and drop legs listening for leaks", "Weekly", "{S:leak}"),
        ("Clean the oil cooler fins", "Monthly", "{S:oil_hot}"),
        ("Ultrasonic leak survey of header and drop legs", "Quarterly", "{S:leak}"),
        ("Replace the air intake filter", "Every 2000 running hours", "{S:oil_hot}"),
        ("Replace oil, oil filter and separator element", "Every 4000 running hours", "{S:oil_hot}"),
        ("Pressure vessel inspection of the receiver", "As required by local regulation", "-"),
        ("Calibration check of the header pressure transmitter", "Yearly", "{S:sensor}"),
    ),
    spares=(("Push-in fittings for drop legs", "10"), ("Quick couplings", "5"), ("Drain valve", "1"), ("Oil filter and separator element", "1 set"), ("Thread sealant", "1")),
    appendix=Appendix(
        "appx_chl", "Process chiller",
        "The process chiller supplies chilled water to the weld cell coolant circuits. Only its supply temperature is monitored by the line.",
        (_H,),
        (
            Topic(
                "chiller", "Chiller supply temperature high",
                f"Supply temperature (`supply_temp_c`) normally cycles within {rng(_H, 'supply_temp_c')} degC as the chiller compressor starts and stops; the alarm is at {g(T(_H, 'supply_temp_c').alarm_hi)} degC.",
                (
                    "A high supply temperature affects both weld cells; a cooling problem at one cell only is inside that cell.",
                ),
                (
                    Row("Supply temperature high", "Condenser fouled or chiller filter clogged (A-UTCHL-FLT-SVC)", "Check the chiller display and the filter", "Clean the condenser; service the filter"),
                    Row("Supply temperature normal, one cell overheating", "Restriction inside the cell", "See the weld cell manual, Section 6", "-"),
                ),
            ),
        ),
    ),
)  # fmt: skip

SPECS: dict[str, ManualSpec] = {m.doc: m for m in (WELD, SEALER, CONVEYOR, PRESS, AIR)}

# Common prose sections (Gemini drafts these; deterministic content never comes from here).
PROSE: tuple[ProseSpec, ...] = (
    ProseSpec("about", "About this manual", "Who the manual is for (operators, maintenance technicians, reliability engineers), how it is organised by chapter, and that the troubleshooting chapter is organised by symptom.", 110),
    ProseSpec("safety_intro", "General safety", "General safety principles for this equipment: trained personnel only, guards and interlocks must never be bypassed, report damage, and that all maintenance inside guarded areas requires the energy control procedure in Chapter 8. Do not describe any isolation step.", 140),
    ProseSpec("overview", "Overview", "What the equipment does in the line and how it interacts with the stations around it.", 150),
    ProseSpec("principle", "Principle of operation", "How the equipment works, step by step through one cycle, using the components listed in the facts. Explain what each monitored signal measures and how it behaves in normal operation.", 260),
    ProseSpec("startup", "Start-up", "Normal start-up at the beginning of a shift: pre-start checks (visual, levels, guards), start sequence, what normal readings look like.", 140),
    ProseSpec("operation", "Normal operation", "What the operator monitors during production and which deviations to report to maintenance.", 140),
    ProseSpec("shutdown", "Normal production stop", "Orderly stop at the end of production. State clearly that this is not an energy-isolated state and that maintenance requires Chapter 8.", 90),
    ProseSpec("controls_intro", "Control parameters", "What adjustable control parameters exist on this equipment, why uncontrolled changes are dangerous for quality and throughput, and why every change goes through change control.", 120),
    ProseSpec("ts_intro", "Using this chapter", "How to troubleshoot with this chapter: start from the symptom index, confirm the typical signature, rule out instrument problems, follow the check column before the remedy, and apply the energy control procedure before any hands-on work.", 120),
    ProseSpec("maint_intro", "Maintenance", "Why preventive maintenance at the listed intervals matters for this equipment and how to record completed tasks.", 100),
    ProseSpec("glossary", "Glossary", "Define 8 to 10 technical terms that appear in the facts, one per paragraph, in the form 'Term: definition.'", 220),
)  # fmt: skip


def background_specs(spec: ManualSpec) -> tuple[ProseSpec, ...]:
    out = []
    for t in spec.topics:
        if t.background:
            out.append(
                ProseSpec(
                    t.background,
                    f"Background: {t.title}",
                    f"Explain the physical mechanism behind '{t.title}' and why it produces the typical signature given in the facts. Do not repeat the troubleshooting table.",
                    150,
                )
            )
    return tuple(out)
