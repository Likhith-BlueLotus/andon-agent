<!-- page 1 -->

# Servo-Gun Spot Weld Cell - Operation and Maintenance Manual

**Document AM-WC-01 | Revision A | Issued 2026-10 | Line L1**

**Applies to:** ST20-WLD (ST20 Weld cell A), ST30-WLD (ST30 Weld cell B)

> **IMPORTANT - FICTIONAL EQUIPMENT.** This manual describes fictional equipment created for the Andon Agent software demonstration (synthetic line L1). It is not a manufacturer's manual. Its energy control procedure is not a substitute for a site-specific energy control procedure prepared, approved and trained under 29 CFR 1910.147 or local regulation.

| Revision | Date | Change |
|---|---|---|
| A | 2026-10 | First issue |

**About this manual**

This manual serves operators, maintenance technicians, and reliability engineers working on the resistance spot weld cells ST20-WLD and ST30-WLD on line L1.

The content is organized across eight chapters and an appendix. Chapter 1 introduces safety fundamentals, Chapter 2 outlines system description, and Chapter 3 provides technical data. Chapter 4 guides normal operation, while Chapter 5 addresses control parameters, cycle timers, and change control. Chapter 6 details troubleshooting, Chapter 7 establishes maintenance requirements, and Chapter 8 provides the energy control procedure. Appendix A supplies the glossary.

To expedite fault resolution, Chapter 6 organizes troubleshooting topics by symptom. Technical personnel can match observed line behavior directly to diagnostic signatures and targeted remedies.

---
*AM-WC-01 Rev. A | Servo-Gun Spot Weld Cell | Page 1 of 28 | Fictional equipment for demonstration only*

<!-- page 2 -->

# Contents

| Chapter | Title | Page |
|---|---|---|
| 1 | Safety | 3 |
| 2 | Description | 5 |
| 3 | Technical data | 7 |
| 4 | Operation | 10 |
| 5 | Control parameters: cycle timers and change control | 12 |
| 6 | Troubleshooting | 14 |
| 7 | Maintenance | 23 |
| 8 | Energy control procedure (lockout/tagout) | 24 |
| Appendix A | Glossary | 28 |

---
*AM-WC-01 Rev. A | Servo-Gun Spot Weld Cell | Page 2 of 28 | Fictional equipment for demonstration only*

<!-- page 3 -->

# 1 Safety

## 1.1 General safety

Only trained personnel may operate, inspect, or maintain the spot weld cells. Safety devices, fixed guards, and interlocks protect personnel from electric shock, mechanical crushing, burns, flying weld spatter, stored air pressure, and hot coolant.

Guards and safety interlocks must never be bypassed, modified, or defeated under any operational condition. Operating personnel must inspect the cell surroundings continuously and immediately report any damaged cabling, guard fencing, pipework, or mechanical components.

Entering the cell enclosure or undertaking any maintenance, cleaning, or mechanical repair inside guarded areas presents severe hazards from the servo drive DC bus, transformer primary, servo gun, and pneumatic clamps. All maintenance tasks inside guarded areas require technicians to apply the energy control procedure in Chapter 8 before proceeding.

## 1.2 Signal words

**Table 1-1 Signal words used in this manual**

| Signal word | Meaning |
|---|---|
| DANGER | A hazardous situation that will cause death or serious injury if not avoided |
| WARNING | A hazardous situation that could cause death or serious injury if not avoided |
| CAUTION | A hazardous situation that could cause minor or moderate injury if not avoided |
| NOTICE | A situation that could damage the equipment or the product |

---
*AM-WC-01 Rev. A | Servo-Gun Spot Weld Cell | Page 3 of 28 | Fictional equipment for demonstration only*

<!-- page 4 -->

## 1.3 Hazards and protective measures

**Table 1-2 Hazards**

| Hazard | Where | Protection |
|---|---|---|
| Electric shock | Controller, transformer primary, servo drive DC bus | Energy control procedure (Chapter 8); wait for DC bus discharge |
| Crushing between electrodes | Servo gun, clamp arms | Guards and interlocked cell door; never reach between electrodes |
| Burns | Electrodes, shanks, transformer, weld spatter | Heat-resistant gloves; let parts cool |
| Flying spatter and cutter chips | Weld zone, tip dresser | Safety glasses with side shields; face shield at the dresser |
| Stored air pressure | Clamp circuit, gun balancer | Bleed the cell air circuit (Chapter 8) |
| Hot coolant under pressure (ST30) | Gun hoses, manifold | Isolate and drain the coolant circuit (Chapter 8) |

## 1.4 Personal protective equipment

- Safety glasses with side shields
- Flame-resistant long-sleeve clothing
- Heat-resistant gloves
- Safety shoes
- Face shield at the tip dresser

**WARNING** Before any maintenance, cleaning or adjustment inside a guarded area, apply the energy control procedure in Chapter 8.

---
*AM-WC-01 Rev. A | Servo-Gun Spot Weld Cell | Page 4 of 28 | Fictional equipment for demonstration only*

<!-- page 5 -->

# 2 Description

## 2.1 Overview

The resistance spot weld cells ST20-WLD and ST30-WLD perform structural joining on car body-in-white assemblies on line L1. Line L1 operates 24 hours a day across three shifts, with each shift starting after a planned changeover.

Within the operational sequence, parts arrive at ST20-WLD from the ST10 press station. The cell fixtures clamp incoming sheet assemblies, verify alignment, and apply programmed resistance spot welds using the servo gun. Station ST30-WLD provides additional spot welding capability with an integrated coolant monitoring circuit.

Completed assemblies transfer downstream to subsequent stations including ST60, where finished weld quality and dimensions undergo verification. Reliable operation and steady cycle timing at ST20-WLD and ST30-WLD prevent part starvation and eliminate downstream assembly defects at ST60.

## 2.2 Main components

**Table 2-1 Main components**

| Component | Function |
|---|---|
| Weld controller | Inverter and weld timer; stores weld schedules; runs the current stepper that raises weld current as the electrode tips wear; monitors weld current and dynamic resistance of every weld |
| Weld transformer and rectifier | Converts the controller output into the low-voltage, high-current secondary weld current |
| Servo gun | Electrode arms closed by a servo motor and roller screw; applies the programmed electrode force |
| Servo drive | Drives the gun servo motor; measures its own temperature and derates speed when hot |
| Electrode caps and shanks | Replaceable copper alloy caps on water-cooled shanks |
| Tip dresser | Motor-driven cutter that restores the electrode tip face between welds |
| Fixture | Locates the part on locating pins and net pads; pneumatic clamps hold it during welding; proximity switches confirm clamp positions |
| Cell air panel | Lockout valve, filter-regulator set to 5.6 bar and pressure transmitter for clamps and gun balancer |
| Coolant manifold (ST30) | Supply and return valves, strainer and flow transmitter for the gun and servo coolant circuit |
| Drive cabinet | Houses controller and servo drive; cooled by a filtered cabinet fan |

---
*AM-WC-01 Rev. A | Servo-Gun Spot Weld Cell | Page 5 of 28 | Fictional equipment for demonstration only*

<!-- page 6 -->

## 2.3 Principle of operation

A cycle begins when the part transfers into the fixture onto locating pins and net pads. Pneumatic clamps close to secure the part, and proximity switches confirm full clamp engagement before welding starts. Regulated gun air pressure feeds the cell at 5.6 bar, monitored within a normal range of 5.3 to 5.9 bar by the air pressure transmitter.

The servo drive energizes the servo gun motor and roller screw to close the water-cooled electrode arms against the part at the programmed electrode force. The weld controller executes the designated weld schedule, directing the weld transformer and rectifier to deliver the low-voltage, high-current secondary weld current. The controller measures secondary current, which remains between 9.8 and 11.2 kA in normal operation, while tracking dynamic tip resistance between 0.135 and 0.175 mOhm.

Between weld cycles, the controller current stepper raises weld current incrementally as the replaceable copper alloy caps wear. The motor-driven tip dresser cuts and restores the electrode tip face every 250 welds. On ST30-WLD, a coolant manifold and flow transmitter monitor gun and servo cooling, maintaining a nominal flow of 12 L/min within a normal range of 10 to 14 L/min.

The servo drive monitors internal drive temperature, operating normally between 35 and 65 degC. Filtered air from the cabinet fan cools the drive cabinet. After the weld sequence completes, the servo gun opens, pneumatic clamps release, and the part transfers out. The total nominal cycle time equals 50 s, with completed cycles measuring between 46 and 55 s.

---
*AM-WC-01 Rev. A | Servo-Gun Spot Weld Cell | Page 6 of 28 | Fictional equipment for demonstration only*

<!-- page 7 -->

# 3 Technical data

## 3.1 Process values and limits

The normal range is the band the equipment stays in during normal production. An alarm limit raises a warning and the station keeps running; a trip limit stops the station. A dash means the limit is not used.

**Table 3-1 Process values and limits: ST20-WLD (ST20 Weld cell A)**

| Tag | Description | Unit | Nominal | Normal range | Alarm low | Alarm high | Trip low | Trip high | Resolution |
|---|---|---|---|---|---|---|---|---|---|
| `weld_current_ka` | RMS secondary current of the last weld | kA | 10.5 | 9.8 to 11.2 | 9.5 | 11.6 | - | - | 0.01 |
| `tip_resistance_mohm` | Dynamic resistance of the last weld | mOhm | 0.15 | 0.135 to 0.175 | - | 0.185 | - | - | 0.001 |
| `servo_temp_c` | Servo-gun drive temperature | degC | 47 | 35 to 65 | - | 72 | - | 80 | 0.1 |
| `cycle_time_s` | Duration of the last completed cycle (incl. waiting) | s | 50 | 46 to 55 | - | 58 | - | - | 0.1 |
| `air_pressure_bar` | Regulated gun air pressure at the cell | bar | 5.6 | 5.3 to 5.9 | 5 | - | 4.6 | - | 0.01 |

**Table 3-2 Process values and limits: ST30-WLD (ST30 Weld cell B)**

| Tag | Description | Unit | Nominal | Normal range | Alarm low | Alarm high | Trip low | Trip high | Resolution |
|---|---|---|---|---|---|---|---|---|---|
| `weld_current_ka` | RMS secondary current of the last weld | kA | 10.5 | 9.8 to 11.2 | 9.5 | 11.6 | - | - | 0.01 |
| `tip_resistance_mohm` | Dynamic resistance of the last weld | mOhm | 0.15 | 0.135 to 0.175 | - | 0.185 | - | - | 0.001 |
| `servo_temp_c` | Servo-gun drive temperature | degC | 47 | 35 to 65 | - | 72 | - | 80 | 0.1 |
| `cycle_time_s` | Duration of the last completed cycle (incl. waiting) | s | 50 | 46 to 55 | - | 58 | - | - | 0.1 |
| `air_pressure_bar` | Regulated gun air pressure at the cell | bar | 5.6 | 5.3 to 5.9 | 5 | - | 4.6 | - | 0.01 |
| `coolant_flow_lpm` | Gun and servo coolant flow | L/min | 12 | 10 to 14 | 8 | - | - | - | 0.1 |

---
*AM-WC-01 Rev. A | Servo-Gun Spot Weld Cell | Page 7 of 28 | Fictional equipment for demonstration only*

<!-- page 8 -->

## 3.2 Operating parameters

**Table 3-3 Operating parameters**

| Parameter | Value | Note |
|---|---|---|
| Regulated gun and clamp air | 5.6 bar | Set at the cell filter-regulator; supplied from the plant air header |
| Servo derate start | 66 degC | Above this servo temperature the drive reduces speed |
| Cycle time added by derating | 0.8 s per degC | Above the derate start temperature |
| Servo over-temperature trip | 80 degC | Drive stops the cell |
| Nominal cycle time | 50 s | Including part transfer |
| Tip dressing interval | 250 welds | Set in the weld schedule |
| Cap change interval | 40 dressings | Or when the tip face cannot be restored |
| Coolant flow, nominal (ST30) | 12 L/min | Gun and servo circuit |

---
*AM-WC-01 Rev. A | Servo-Gun Spot Weld Cell | Page 8 of 28 | Fictional equipment for demonstration only*

<!-- page 9 -->

## 3.3 Alarm and stop messages

**Table 3-4 Alarm and stop messages**

| Code | Message | Condition or meaning |
|---|---|---|
| A-ST20-WCUR-LO | ST20 Weld cell A: weld current low | `weld_current_ka` below 9.5 kA; alarm: the station keeps running |
| A-ST20-WCUR-HI | ST20 Weld cell A: weld current high | `weld_current_ka` above 11.6 kA; alarm: the station keeps running |
| A-ST20-TIPR-HI | ST20 Weld cell A: tip resistance high | `tip_resistance_mohm` above 0.185 mOhm; alarm: the station keeps running |
| A-ST20-SRVT-HI | ST20 Weld cell A: servo temperature high | `servo_temp_c` above 72 degC; alarm: the station keeps running |
| A-ST20-SRVT-HH | ST20 Weld cell A: servo temperature high-high | `servo_temp_c` above 80 degC; trip: the station stops |
| A-ST20-CYC-HI | ST20 Weld cell A: cycle time high | `cycle_time_s` above 58 s; alarm: the station keeps running |
| A-ST20-AIR-LO | ST20 Weld cell A: gun air pressure low | `air_pressure_bar` below 5 bar; alarm: the station keeps running |
| A-ST20-AIR-LL | ST20 Weld cell A: gun air pressure low-low | `air_pressure_bar` below 4.6 bar; trip: the station stops |
| A-ST30-WCUR-LO | ST30 Weld cell B: weld current low | `weld_current_ka` below 9.5 kA; alarm: the station keeps running |
| A-ST30-WCUR-HI | ST30 Weld cell B: weld current high | `weld_current_ka` above 11.6 kA; alarm: the station keeps running |
| A-ST30-TIPR-HI | ST30 Weld cell B: tip resistance high | `tip_resistance_mohm` above 0.185 mOhm; alarm: the station keeps running |
| A-ST30-SRVT-HI | ST30 Weld cell B: servo temperature high | `servo_temp_c` above 72 degC; alarm: the station keeps running |
| A-ST30-SRVT-HH | ST30 Weld cell B: servo temperature high-high | `servo_temp_c` above 80 degC; trip: the station stops |
| A-ST30-CYC-HI | ST30 Weld cell B: cycle time high | `cycle_time_s` above 58 s; alarm: the station keeps running |
| A-ST30-AIR-LO | ST30 Weld cell B: gun air pressure low | `air_pressure_bar` below 5 bar; alarm: the station keeps running |
| A-ST30-AIR-LL | ST30 Weld cell B: gun air pressure low-low | `air_pressure_bar` below 4.6 bar; trip: the station stops |
| A-ST30-CLT-LO | ST30 Weld cell B: coolant flow low | `coolant_flow_lpm` below 8 L/min; alarm: the station keeps running |
| A-ST20-WLD-QA / A-ST30-WLD-QA | weld monitor: weld energy out of band | Weld outside its current/resistance window; see Section 6.2 |
| A-ST20-GUN-FRC / A-ST30-GUN-FRC | gun force not reached | Electrode force below target; see Section 6.6 |
| A-ST20-CLAMP-RTY | clamp position retry | Clamp did not reach position first time; see Section 6.5 |
| S-ST20-SRV-OT / S-ST30-SRV-OT | servo drive over-temperature trip | Drive stopped the cell; see Section 6.3 |
| S-ST20-AIR-LO / S-ST30-AIR-LO | gun air pressure low, cell stopped | Supply-air interlock; see Section 6.6 |
| S-ST20-WLD-FLT / S-ST30-WLD-FLT | repeated weld faults, cell stopped | Several weld faults in a row; see Section 6.7 and Section 6.2 |
| A-ST20-DOOR-OPN / A-ST30-DOOR-OPN | cell door opened (key switch) | Information |
| A-ST20-STARVED | ST20 Weld cell A: station starved (waiting for part) | Consequence of a slow or stopped station upstream; not a fault at this station |
| A-ST20-BLOCKED | ST20 Weld cell A: station blocked (outfeed full) | Consequence of a slow or stopped station downstream; not a fault at this station |
| A-ST30-STARVED | ST30 Weld cell B: station starved (waiting for part) | Consequence of a slow or stopped station upstream; not a fault at this station |
| A-ST30-BLOCKED | ST30 Weld cell B: station blocked (outfeed full) | Consequence of a slow or stopped station downstream; not a fault at this station |
| A-L1-ANDON | Line L1 stopped: andon raised | Information; follows any station stop |

---
*AM-WC-01 Rev. A | Servo-Gun Spot Weld Cell | Page 9 of 28 | Fictional equipment for demonstration only*

<!-- page 10 -->

# 4 Operation

## 4.1 Start-up

Shift start-up begins with thorough pre-start inspections following the planned changeover. Technicians clean fixture net pads and locators, check the electrode tip face using the tip gauge, and inspect the tip dresser cutter blade.

Personnel confirm all cell guards are closed, interlocks are active, and no fluid leaks or loose cables exist. The cell air panel filter-regulator must indicate regulated air pressure within the normal 5.3 to 5.9 bar window.

Upon powering the cell, operators confirm cabinet fan operation and check instrumentation. ST20-WLD and ST30-WLD must display normal baseline signals: servo drive temperature between 35 and 65 degC, regulated air near 5.6 bar, and on ST30-WLD, coolant flow between 10 and 14 L/min. Initial dry cycles must show completed cycle durations within 46 to 55 s.

## 4.2 Normal operation

During regular production, the operator monitors real-time cell signals to maintain joining stability across the nominal 50 s cycle. Normal welding displays secondary current between 9.8 and 11.2 kA and dynamic tip resistance between 0.135 and 0.175 mOhm. Servo drive temperature must remain within 35 to 65 degC, cycle time between 46 and 55 s, and air pressure between 5.3 to 5.9 bar.

On ST30-WLD, coolant flow must register between 10 and 14 L/min. Operators must report deviations promptly to maintenance. Key warning signs include tip resistance drifting toward the 0.185 mOhm alarm, servo temperature rising past 66 degC, air pressure dropping toward 5 bar, or coolant flow falling toward 8 L/min. Any recurring clamp retries or abnormal cabinet fan noise also require immediate reporting.

---
*AM-WC-01 Rev. A | Servo-Gun Spot Weld Cell | Page 10 of 28 | Fictional equipment for demonstration only*

<!-- page 11 -->

## 4.3 Normal production stop

A normal production stop concludes current cycles cleanly at the end of a shift or changeover. The operator initiates the stop command, allowing the weld controller to complete active welds, open the servo gun, unclamp the part, and return all mechanisms to home positions.

A normal production stop leaves pneumatic, electrical, and coolant systems fully pressurized. It is not an energy-isolated state. Before conducting any inspection, mechanical adjustment, cleaning, or repair inside guarded areas, maintenance personnel must apply the energy control procedure in Chapter 8.

---
*AM-WC-01 Rev. A | Servo-Gun Spot Weld Cell | Page 11 of 28 | Fictional equipment for demonstration only*

<!-- page 12 -->

# 5 Control parameters: cycle timers and change control

## 5.1 Control parameters

The cell incorporates several adjustable control parameters, including weld schedules, current stepper profiles, electrode force values, cycle timers, pneumatic pressure settings, and tip dressing frequencies. The tip dressing interval is configured for 250 welds, while cap replacement occurs every 40 dressings.

Uncontrolled changes to these parameters compromise weld integrity and production throughput. Modifying weld current or force can cause undersized nuggets, excessive spatter, or premature electrode failure. Altering cycle timers or clamp sequence settings risks fixture misalignments and cycle delays.

To ensure product quality and operational stability, personnel must process every parameter adjustment through formal change control before implementing updates on ST20-WLD or ST30-WLD.

**Table 5-1 Adjustable control parameters**

| Parameter | Function | May be changed by |
|---|---|---|
| Weld schedule (per product model) | Weld current, weld time and electrode force for each spot | Weld engineer |
| Clamp settle timer | Delay between clamps closed and first weld | Maintenance with change request |
| Gun open dwell | Delay before the part is released after the last weld | Maintenance with change request |
| Tip dressing interval | Welds between dressings | Weld engineer |
| Current stepper curve | Current increase per block of welds since the last dressing | Weld engineer |

---
*AM-WC-01 Rev. A | Servo-Gun Spot Weld Cell | Page 12 of 28 | Fictional equipment for demonstration only*

<!-- page 13 -->

## 5.2 Change control and diagnosis

**Diagnostic notes**

- Parameter changes are made only under an approved change request and are recorded in the parameter log with the old value, the new value, the author and the time.
- Parameter changes are normally loaded at a shift start, during the changeover.
- A cycle time that steps up at a shift start and then stays constant, while every process signal of the station stays normal, points to a changed timer or recipe parameter, not to wear or a failing component.
- Compare the active parameter set with the last approved copy before replacing any hardware.

Shifts start at 06:00, 14:00, 22:00 with a 15 min planned changeover; the first 3 cycles after a changeover run slower than normal.

**Table 5-2 Troubleshooting: control parameters**

| Symptom | Probable cause | Check | Remedy |
|---|---|---|---|
| ST20 or ST30 cycle time stepped up at a shift start and stays at the new level; process signals normal | Timer or dwell parameter changed at the changeover (wrong value, wrong recipe, or a trial value left active) | Compare the active parameter set with the last approved copy; check the parameter log for the shift start | Restore the approved value under change control; record the deviation |
| Stations downstream starved and stations upstream blocked after a shift start | A slower cycle at one station propagating along the line | Find the first station whose cycle time changed; downstream starvation and upstream blocking are consequences | Correct the parameter at the first station only |
| Cycle time slightly longer for the first parts after every changeover | Normal ramp-up after a changeover | Confirm that cycle time returns to the normal range within a few cycles | No action |

---
*AM-WC-01 Rev. A | Servo-Gun Spot Weld Cell | Page 13 of 28 | Fictional equipment for demonstration only*

<!-- page 14 -->

# 6 Troubleshooting

## 6.1 Using this chapter

Chapter 6 provides structured troubleshooting for operational faults. When diagnosing an issue, begin at the symptom index to locate the relevant functional area.

Verify observed cell behavior against the documented typical signature, noting secondary current, tip resistance, servo drive temperature, air pressure, cycle time, and ST30-WLD coolant flow. Rule out instrument faults or loose sensor wiring before assuming mechanical failure. Follow the designated check steps before implementing any corrective remedy.

If investigation or component replacement requires entry into the cell or physical contact with equipment, personnel must apply the energy control procedure in Chapter 8 before performing any hands-on work.

**Table 6-1 Symptom index**

| First symptom | Topic | Section | Page |
|---|---|---|---|
| `tip_resistance_mohm` above 0.175 mOhm and still rising | Electrode tip wear and tip dressing | 6.2 | 15 |
| `servo_temp_c` above 65 degC, cycle time normal | Servo-gun drive over-temperature | 6.3 | 16 |
| `coolant_flow_lpm` below 10 L/min | Coolant flow low / blocked circuit | 6.4 | 17 |
| Clamp retry alarms (A-ST20-CLAMP-RTY) and cycle-time scatter | Fixture / clamp misalignment | 6.5 | 18 |
| Gun air low at both ST20 and ST30 | Gun air pressure low | 6.6 | 19 |
| Weld faults at ST20 starting after a changeover | Weld faults after a press changeover | 6.7 | 20 |
| One signal trending with no change in related signals | Instrument verification: suspected sensor drift | 6.8 | 21 |
| Cycle time stepped at a shift start, process normal | Control parameters: cycle timers and change control | 5 | 12 |

---
*AM-WC-01 Rev. A | Servo-Gun Spot Weld Cell | Page 14 of 28 | Fictional equipment for demonstration only*

<!-- page 15 -->

## 6.2 Electrode tip wear and tip dressing

**Typical signature.** Tip resistance (`tip_resistance_mohm`) climbs steadily over hours from about 0.15 mOhm towards the 0.185 mOhm alarm limit as the tip faces pick up coating material and oxide (which raises contact resistance) and lose their shape, while the current stepper raises weld current (`weld_current_ka`) to compensate. Rejects at ST60 follow later, once the weld nuggets become undersized. Servo temperature, gun air pressure and cycle time stay normal.

**Diagnostic notes**

- Tip resistance that rises in a straight line over several hours, together with a stepping weld current, is the signature of electrode tip wear, not of a controller fault.
- If tip resistance rises at one weld cell only, the tips or the tip dresser at that cell are the cause; if weld faults start at ST20 right after a press changeover, check the parts first (see Section 6.7).
- A tip dresser that runs but removes no material leaves tip resistance rising even though the dressing cycles are logged.

**Table 6-2 Troubleshooting: Electrode tip wear and tip dressing**

| Symptom | Probable cause | Check | Remedy |
|---|---|---|---|
| `tip_resistance_mohm` above 0.175 mOhm and still rising | Electrode tips mushroomed; dressing interval too long for the current stepper curve | Inspect the tip face with the tip gauge; compare the dresser counter with the dressing interval in Table 3-3 | Dress the tips; if the face cannot be restored, change the caps (see Table 7-1) |
| Weld current stepping up between dressings | Current stepper compensating for tip face growth (normal up to the end of the stepper curve) | Compare `weld_current_ka` with the normal range 9.8 to 11.2 kA in Table 3-1 | Dress the tips and confirm that the stepper resets |
| Dresser cycle logged but tip resistance does not fall | Dresser cutter blade worn or chipped; dresser motor not reaching speed | Inspect the cutter blade and chip discharge; take a carbon imprint of the tip face | Replace the cutter blade; verify the tip face with a new imprint |
| ST60 weld rejects rising, weld current inside the normal range | Undersized nuggets from worn tips late in the dressing interval, or a non-weld cause | Trend `tip_resistance_mohm` over the last shift; if it is flat, go to Section 6.5 | Dress the tips; quarantine the parts produced since the last good destructive test |
| Weld monitor alarm A-ST20-WLD-QA or A-ST30-WLD-QA | Weld outside its current or resistance window | Check which spot and which signal left the window | Follow the row above that matches the signal |

**Background.**

Resistance spot welding subjects copper alloy electrode caps to severe thermal and mechanical stresses. Over hours of continuous production, electrode tip faces pick up oxide layers and metallic sheet coatings from the car body material. This surface accumulation increases electrical contact resistance across the weld interface.

Simultaneously, mechanical clamping force causes the cap faces to deform, mushroom, and lose their nominal shape. As contact resistance rises, dynamic tip resistance climbs from 0.15 mOhm toward the 0.185 mOhm alarm limit. To maintain heat input across the expanding contact surface, the weld controller current stepper raises secondary weld current within the 9.8 to 11.2 kA operating window.

Tip dressing restores cap geometry every 250 welds, while cap replacement occurs every 40 dressings. If caps exceed wear limits or miss dressing, dynamic tip resistance crosses the 0.185 mOhm threshold, leading to undersized weld nuggets and downstream part rejections at ST60 while servo temperature, air pressure, and cycle time remain normal.

---
*AM-WC-01 Rev. A | Servo-Gun Spot Weld Cell | Page 15 of 28 | Fictional equipment for demonstration only*

<!-- page 16 -->

## 6.3 Servo-gun drive over-temperature

**Typical signature.** Servo-gun drive temperature (`servo_temp_c`) rises above its normal range of 35 to 65 degC. Above 66 degC the drive derates its speed, adding about 0.8 s to the cycle for every degree above that point, so the cell cycle time rises and stations downstream are starved. The 72 degC alarm comes before the 80 degC trip. A failing cabinet fan is often audible before the trip.

**Diagnostic notes**

- On ST30, check coolant flow first: a servo temperature rise that follows a fall in coolant flow is a cooling-circuit problem (see Section 6.4), not a drive problem.
- A servo temperature rise with normal coolant flow and a cabinet fan that is noisy, slow or stopped points to the cabinet cooling fan or a clogged cabinet filter.
- A servo temperature reading that climbs while cycle time, weld current and coolant flow stay normal may be an instrument problem; see Section 6.8.

**Table 6-3 Troubleshooting: Servo-gun drive over-temperature**

| Symptom | Probable cause | Check | Remedy |
|---|---|---|---|
| `servo_temp_c` above 65 degC, cycle time normal | Cabinet fan failing or filter mat clogged; high ambient temperature | Listen to the cabinet fan; inspect the filter mat; compare cabinet and ambient temperature | Clean or replace the filter mat; replace the fan (see Table 7-1) |
| `servo_temp_c` above 66 degC and `cycle_time_s` rising | Drive derating to protect itself | Confirm the derate message on the drive display | Remove the heat cause; do not raise the derate threshold |
| Trip S-ST20-SRV-OT or S-ST30-SRV-OT at 80 degC | Sustained overheating not corrected at the alarm stage | Check coolant flow (ST30), the cabinet fan and the gun mechanics for binding | Let the drive cool; restart only after the cause is found |
| Gun moves slowly or stalls while temperature rises | Mechanical binding in the gun spindle or worn roller screw | Move the gun by hand under energy control (Chapter 8); feel for tight spots | Lubricate or replace the roller screw (see Table 7-1) |

**Background.**

The servo drive on ST20-WLD and ST30-WLD powers the gun roller screw to exert exact clamping force. Electrical and mechanical power losses generate heat within the drive enclosure. Filtered air from the drive cabinet fan maintains normal drive temperatures between 35 and 65 degC.

When cabinet airflow drops due to filter clogging or fan deterioration, heat accumulates in the power electronics. If servo drive temperature exceeds 66 degC, thermal protection activates and the drive automatically derates its operating speed.

This derating penalty adds 0.8 s to cycle duration for every degree Celsius above 66 degC. As speed falls, cell cycle time rises past the nominal 50 s standard, causing downstream starvation. If temperature reaches 72 degC, the cell issues an over-temperature alarm, followed by a total cell trip at 80 degC. An audible cabinet fan problem often precedes the trip.

---
*AM-WC-01 Rev. A | Servo-Gun Spot Weld Cell | Page 16 of 28 | Fictional equipment for demonstration only*

<!-- page 17 -->

## 6.4 Coolant flow low / blocked circuit

**Typical signature.** Coolant flow (`coolant_flow_lpm`, ST30 only) falls below its normal range of 10 to 14 L/min and the 8 L/min low alarm follows. With less cooling, servo temperature starts to rise about 15 minutes later, then the drive derates (cycle time rises) and finally trips on over-temperature. Weld current becomes noisier as the electrodes run hot.

**Diagnostic notes**

- Falling coolant flow followed some minutes later by rising servo temperature identifies a restricted coolant circuit; a servo temperature rise without any flow change does not.
- Coolant flow that falls at ST30 while the chiller supply temperature stays normal points to a restriction inside the cell (strainer, kinked hose, scaled gun passages), not to the chiller.

**Table 6-4 Troubleshooting: Coolant flow low / blocked circuit**

| Symptom | Probable cause | Check | Remedy |
|---|---|---|---|
| `coolant_flow_lpm` below 10 L/min | Cell strainer clogged | Read the strainer differential gauge; inspect the strainer basket | Clean the strainer basket under energy control (Chapter 8) |
| Flow low on one gun circuit only | Kinked or crushed hose in the gun dress pack | Trace the hoses along the dress pack; look for flattened sections | Replace the hose; re-secure the dress pack |
| Flow recovers after back-flushing but falls again within days | Scale or debris in the gun cooling passages | Inspect drained coolant for scale; check water treatment records | Descale the gun passages; review water treatment with the utilities technician |
| Coolant flow low and chiller supply temperature high | Chiller supply problem | Check `supply_temp_c` against Table B-1 of AM-CA-01 (Plant Air System and Utilities) | Refer to the plant air and utilities manual, Appendix B |
| Alarm A-ST30-CLT-LO | Coolant flow below 8 L/min | Follow the first row of this table | - |

**Background.**

Station ST30-WLD incorporates a dedicated coolant manifold to extract process heat from the servo drive and weld gun. Under normal operating conditions, coolant circulates through supply and return lines at a nominal rate of 12 L/min, with measured flow remaining between 10 and 14 L/min.

If debris restricts the manifold strainer or internal hoses pinch, coolant flow declines. When flow drops to 8 L/min, the flow transmitter triggers a low-coolant alarm. Because fluid flow removes thermal energy, reduced cooling causes heat to build inside the servo motor and drive components.

Roughly 15 minutes after cooling drops, servo drive temperature begins to climb above its normal range. The rising heat eventually causes drive derating, which elongates cycle time, and ultimately triggers an over-temperature trip at 80 degC. Additionally, hot running electrodes cause secondary weld current to exhibit electrical noise.

---
*AM-WC-01 Rev. A | Servo-Gun Spot Weld Cell | Page 17 of 28 | Fictional equipment for demonstration only*

<!-- page 18 -->

## 6.5 Fixture / clamp misalignment

**Typical signature.** Cycle time (`cycle_time_s`) becomes erratic: most cycles are normal, but some take several seconds longer because a clamp has to retry (A-ST20-CLAMP-RTY). Weld current, tip resistance and servo temperature remain normal. ST60 rejects rise because welds are placed off-position or parts are not seated.

**Diagnostic notes**

- Rejects at ST60 with normal weld current and normal tip resistance point away from the weld process and towards part location: fixture, clamps or locating pins.
- Cycle-time scatter with clamp retries and no change in the weld signals is the signature of a misaligned fixture or a worn locating pin.

**Table 6-5 Troubleshooting: Fixture / clamp misalignment**

| Symptom | Probable cause | Check | Remedy |
|---|---|---|---|
| Clamp retry alarms (A-ST20-CLAMP-RTY) and cycle-time scatter | Clamp proximity switch misadjusted or clamp arm bushings worn | Watch several cycles; check the switch-to-target gap | Adjust or replace the switch; replace worn bushings |
| Weld position rejects at ST60, weld signals normal | Locating pin worn, or fixture moved after a collision | Check pins with the go/no-go gauge; check the fixture against its reference marks | Replace the pins; realign the fixture to the reference marks and record it in the fixture log |
| Part-not-seated detected intermittently | Weld spatter or debris on locators or net pads | Inspect the locators and net pads | Clean the net pads every shift (see Table 7-1) |

**Background.**

The part fixture maintains spatial alignment between sheet metal stampings during spot welding. Parts rest on locating pins and net pads while pneumatic clamps secure them. Proximity switches verify that clamp arms have completed travel before the servo gun initiates welding.

When net pads accumulate weld spatter, locators wear, or sheet parts from the ST10 press carry geometric variations, clamps encounter mechanical resistance during closure. If a clamp fails to seat on its first attempt, the cell initiates an automatic retry sequence under alarm code A-ST20-CLAMP-RTY.

These clamp retries produce an erratic cycle time signature. Most cycles complete within the normal 46 to 55 s range, but retried cycles take several seconds longer. Secondary weld current, tip resistance, and servo temperature remain within standard operating limits. However, unseated stampings cause welds to be deposited off-location, resulting in elevated part rejections at downstream inspection station ST60.

---
*AM-WC-01 Rev. A | Servo-Gun Spot Weld Cell | Page 18 of 28 | Fictional equipment for demonstration only*

<!-- page 19 -->

## 6.6 Gun air pressure low

**Typical signature.** Regulated gun air (`air_pressure_bar`) normally sits at 5.6 bar within 5.3 to 5.9 bar. Below 5 bar the cell raises a low-air alarm; at 4.6 bar the supply-air interlock stops the cell. Gun force alarms (A-ST20-GUN-FRC, A-ST30-GUN-FRC) can appear as the air falls.

**Diagnostic notes**

- When gun air pressure falls at ST20 and ST30 together, the cause is upstream in the plant air supply; check the header pressure (see Section 6.2 of AM-CA-01 (Plant Air System and Utilities)) before working on either cell.
- When gun air falls at one cell only, check that cell's filter-regulator, drop-leg ball valve and quick couplings.

**Table 6-6 Troubleshooting: Gun air pressure low**

| Symptom | Probable cause | Check | Remedy |
|---|---|---|---|
| Gun air low at both ST20 and ST30 | Plant air header pressure low (leak or compressor problem) | Check `header_pressure_bar` on UT-AIR | Follow the plant air and utilities manual, Section 6 |
| Gun air low at one cell only | Filter-regulator element clogged, regulator drifted, or local leak | Read the cell gauge; listen for leaks at the drop leg and couplings | Replace the filter element; reset the regulator; repair the leak |
| Gun force alarm with normal gun air | Servo gun force calibration out, or worn roller screw | Run the force check with the calibrated force gauge | Recalibrate the gun force; replace the roller screw if needed |

---
*AM-WC-01 Rev. A | Servo-Gun Spot Weld Cell | Page 19 of 28 | Fictional equipment for demonstration only*

<!-- page 20 -->

## 6.7 Weld faults after a press changeover

**Typical signature.** Weld quality alarms and a growing scatter in tip resistance at ST20 that start soon after a product changeover, with normal tip dressing records, often come from parts formed out of tolerance at the ST10 press.

**Diagnostic notes**

- Check the ST10 press main pressure against the recipe setpoint for the new model (see Table 3-3 of AM-PH-01 (Hydraulic Press and Power Unit)) before changing any weld schedule.

**Table 6-7 Troubleshooting: Weld faults after a press changeover**

| Symptom | Probable cause | Check | Remedy |
|---|---|---|---|
| Weld faults at ST20 starting after a changeover | Parts from ST10 formed with a wrong pressure setpoint | Compare `hyd_pressure_bar` on ST10-PRS with the recipe setpoint | Correct the press recipe (press manual, Section 6); quarantine affected parts |
| Weld faults after a changeover, press pressure correct | Wrong weld schedule selected for the new model | Check the active weld schedule number against the model | Select the correct schedule under change control |

---
*AM-WC-01 Rev. A | Servo-Gun Spot Weld Cell | Page 20 of 28 | Fictional equipment for demonstration only*

<!-- page 21 -->

## 6.8 Instrument verification: suspected sensor drift

**Typical signature.** One monitored value trends slowly towards a limit, or jumps beyond it, while the signals that are physically linked to it stay normal.

**Table 6-8 Physical correlates of monitored signals**

| Signal | Physically related signals and checks |
|---|---|
| `servo_temp_c` | Cycle time (derating above 66 degC), coolant flow on ST30, cabinet fan sound, handheld reading at the drive heat sink |
| `coolant_flow_lpm` (ST30) | Servo temperature (rises some minutes after a real flow loss), strainer differential, flow at the drain |
| `tip_resistance_mohm` | Weld current stepper count, tip face condition, weld quality at ST60 |
| `air_pressure_bar` | Plant air header pressure, the other weld cell's air pressure, the cell pressure gauge |
| `weld_current_ka` | Tip resistance, stepper count, weld monitor alarms |

**Diagnostic notes**

- A real process change moves more than one signal; a single tag that trends steadily while every physically related tag stays normal points to the instrument, not the process.
- Do not replace process components on the evidence of one drifting tag; verify the instrument first against a calibrated reference at the measuring point.
- A reading that jumps beyond a trip limit for one to three seconds and then returns, with no change in related tags before or after, is a measurement spike; reset, record it and keep the station running.
- Gaps in a trend, a value that stays exactly constant for a long period (stuck value) and the same alarm repeating several times within a minute (alarm chatter) are data-quality effects of the instrument or the network; they are not process faults and are not evidence of a failure.

---
*AM-WC-01 Rev. A | Servo-Gun Spot Weld Cell | Page 21 of 28 | Fictional equipment for demonstration only*

<!-- page 22 -->

**Table 6-9 Troubleshooting: suspected sensor drift**

| Symptom | Probable cause | Check | Remedy |
|---|---|---|---|
| One tag trends steadily towards a limit; all related tags in Table 6-8 stay normal | Transmitter drift (ageing, contamination, loose terminal, moisture in the connector) | Compare the reading with a calibrated handheld reference at the same point; inspect the connector and cable | Recalibrate or replace the transmitter; record the as-found and as-left values in the calibration log |
| Station stopped on a high-high or low-low trip after a one- to three-second excursion | Measurement spike (electrical noise, loose shield, vibration on the cable) | Check the trend either side of the trip; check related tags; inspect cable shield and gland | Reset and restart; if spikes repeat, re-terminate the shield and re-route the cable away from power cables |
| Value frozen at exactly the same number for a long period | Stuck value: lost update between the transmitter and the controller or historian | Check the transmitter display against the HMI; check the communication diagnostics | Restore communication; do not use the frozen period as process evidence |
| Same alarm raised and cleared several times within a minute | Alarm chatter: value hovering at the limit with too little deadband | Check the trend at the limit; check the alarm deadband setting | Treat as one event; request a deadband review through change control (see Chapter 5) |

---
*AM-WC-01 Rev. A | Servo-Gun Spot Weld Cell | Page 22 of 28 | Fictional equipment for demonstration only*

<!-- page 23 -->

# 7 Maintenance

## 7.1 Preventive maintenance

Adhering to preventive maintenance intervals ensures process reliability, nugget quality, and prolonged component life across three daily production shifts. Scheduled maintenance prevents unexpected downtime caused by worn electrode caps, clogged coolant passages, dry roller screws, and drive overheating.

Technicians must perform shift, weekly, monthly, quarterly, semi-annual, and annual tasks exactly as scheduled. Following completion, personnel must record every maintenance action, inspection finding, and component replacement in the station logbook to preserve traceability across line L1.

**Table 7-1 Preventive maintenance intervals**

| Task | Interval | See |
|---|---|---|
| Clean fixture net pads and locators | Every shift | Section 6.5 |
| Check tip face with the tip gauge | Every shift | Section 6.2 |
| Inspect tip dresser cutter blade | Weekly | Section 6.2 |
| Clean the coolant strainer (ST30) | Weekly | Section 6.4 |
| Clean or replace the drive cabinet filter mat | Monthly | Section 6.3 |
| Check the cabinet fan for noise and air flow | Monthly | Section 6.3 |
| Replace the cell air filter element | Quarterly | Section 6.6 |
| Gun force calibration with the force gauge | Quarterly | Section 6.6 |
| Lubricate the gun roller screw | Every 6 months | Section 6.3 |
| Calibration check of servo temperature, coolant flow and air pressure transmitters | Yearly | Section 6.8 |

## 7.2 Recommended spare parts

**Table 7-2 Recommended spare parts**

| Part | Quantity to stock |
|---|---|
| Electrode caps | Box of 50 |
| Tip dresser cutter blade | 2 |
| Cabinet fan and filter mats | 1 fan, 5 mats |
| Coolant hose set for the gun dress pack | 1 |
| Clamp proximity switches | 2 |
| Locating pins | 1 set |

---
*AM-WC-01 Rev. A | Servo-Gun Spot Weld Cell | Page 23 of 28 | Fictional equipment for demonstration only*

<!-- page 24 -->

# 8 Energy control procedure (lockout/tagout)

## 8.1 Scope, purpose and authorisation

> **IMPORTANT - FICTIONAL EQUIPMENT.** This manual describes fictional equipment created for the Andon Agent software demonstration (synthetic line L1). It is not a manufacturer's manual. Its energy control procedure is not a substitute for a site-specific energy control procedure prepared, approved and trained under 29 CFR 1910.147 or local regulation.

**Equipment.** Servo-gun resistance spot weld cell (weld controller, weld transformer, servo gun, fixture). Applies to: ST20-WLD, ST30-WLD.

**Purpose.** This procedure controls hazardous energy when anyone dresses or changes electrodes by hand, works on the servo gun, the weld transformer, the fixture or the coolant circuit, or enters the cell for any task other than normal operation.

**Authorisation.** Only authorised employees trained on this procedure may apply or remove locks and tags. Each authorised employee applies a personal lock and tag; a group lockout uses a lock box with one personal lock per employee.

**Basis.** This procedure follows the energy control procedure requirements of 29 CFR 1910.147(c)(4) and the sequence of 29 CFR 1910.147(d)(1) to (d)(6), with notification under (c)(9) and release from lockout or tagout under (e). Each step cites its paragraph. Steps are carried out in the order given. Steps marked ST30 apply to ST30 only.

## 8.2 Energy sources

**Table 8-1 Hazardous energy sources and isolating devices**

| Energy | Source and magnitude | Isolating device | Stored or residual energy |
|---|---|---|---|
| Electrical | 400 V AC three-phase supply to the weld controller and transformer; 24 V DC control | Cell main disconnect switch | Servo drive DC bus capacitors hold a charge after the disconnect is opened; wait for discharge |
| Pneumatic | Regulated cell air at 5.6 bar to the fixture clamps and the gun balancer | Cell air lockout valve (exhausting type) | Air trapped between the lockout valve and the clamps; bleed to zero |
| Gravity | Servo gun suspended on the balancer; open clamp arms | None (mechanical) | Rest the gun on its maintenance stand or lock the balancer |
| Coolant (ST30) | Gun and servo coolant at about 12 L/min under supply pressure | Coolant supply and return valves at the cell manifold | Pressure trapped in the gun hoses; drain to a container |
| Thermal | Electrodes, shanks and transformer are hot after welding | None | Allow to cool; heat-resistant gloves |

---
*AM-WC-01 Rev. A | Servo-Gun Spot Weld Cell | Page 24 of 28 | Fictional equipment for demonstration only*

<!-- page 25 -->

## 8.3 Preparation, shutdown, isolation and lockout

**Table 8-2 Preparation, shutdown, isolation and lockout**

| Step | Action | 29 CFR 1910.147 paragraph |
|---|---|---|
| 1 | Identify every energy source for the cell from Table 8-1 and collect one personal lock and tag for each isolating device. | (d)(1) |
| 2 | Notify the line lead and the operators of the affected cell that the weld cell will be shut down and locked out. | (c)(9) |
| 3 | Stop the cell at the end of a cycle with the cell stop push-button and wait until the gun is open and at its home position. | (d)(2) |
| 4 | Rest the servo gun on its maintenance stand or lock the balancer before the cell air is shut off. | (d)(2) |
| 5 | Switch the cell main disconnect switch to OFF. | (d)(3) |
| 6 | Close the cell air lockout valve so that its exhaust port vents the cell air circuit. | (d)(3) |
| 7 | On ST30, close the coolant supply valve and then the coolant return valve at the cell manifold. | (d)(3) |
| 8 | Fit a personal lock and tag to the cell main disconnect switch and to the cell air lockout valve. | (d)(4) |
| 9 | On ST30, fit a personal lock and tag to the coolant supply valve and to the coolant return valve. | (d)(4) |

---
*AM-WC-01 Rev. A | Servo-Gun Spot Weld Cell | Page 25 of 28 | Fictional equipment for demonstration only*

<!-- page 26 -->

## 8.4 Stored energy and verification of isolation

**Table 8-3 Stored energy and verification of isolation**

| Step | Action | 29 CFR 1910.147 paragraph |
|---|---|---|
| 10 | Wait at least 5 minutes for the servo drive DC bus to discharge before opening the drive cabinet. | (d)(5)(i) |
| 11 | Open the cell air bleed valve and confirm that the cell air pressure gauge reads zero. | (d)(5)(i) |
| 12 | On ST30, open the coolant drain valve into a container until the flow stops. | (d)(5)(i) |
| 13 | Let the electrodes, shanks and transformer cool before touching them, and wear heat-resistant gloves. | (d)(5)(i) |
| 14 | Press the cell start push-button and the gun jog button to confirm that nothing moves, then return both controls to off. | (d)(6) |
| 15 | Test for absence of voltage at the weld controller incoming terminals with a tester proven on a known live source before and after the test. | (d)(6) |

---
*AM-WC-01 Rev. A | Servo-Gun Spot Weld Cell | Page 26 of 28 | Fictional equipment for demonstration only*

<!-- page 27 -->

## 8.5 Release from lockout/tagout

**Table 8-4 Release from lockout/tagout**

| Step | Action | 29 CFR 1910.147 paragraph |
|---|---|---|
| 16 | Remove tools and nonessential items from the cell, and confirm that the guards, electrodes and hoses are fitted and intact. | (e)(1) |
| 17 | Close the cell air bleed valve and, on ST30, the coolant drain valve. | (e)(1) |
| 18 | Check that all employees are clear of the cell and of the gun travel path. | (e)(2)(i) |
| 19 | Each employee removes only the lock and tag that the employee applied. | (e)(3) |
| 20 | Notify the affected employees that the locks and tags have been removed before the cell is restarted. | (e)(2)(ii) |

**Testing or positioning.** If the equipment must be energised temporarily to test or position it, follow 29 CFR 1910.147(f)(1): clear tools and materials, remove employees from the area, remove the locks and tags, energise and test, then de-energise and reapply every energy control measure in the order of this chapter before work continues.

---
*AM-WC-01 Rev. A | Servo-Gun Spot Weld Cell | Page 27 of 28 | Fictional equipment for demonstration only*

<!-- page 28 -->

# Appendix A Glossary

Weld controller: Inverter and weld timer that stores weld schedules, drives the current stepper, and monitors weld current and dynamic resistance.

Weld transformer and rectifier: Unit that converts controller electrical output into low-voltage, high-current secondary weld current.

Servo gun: Welding gun whose electrode arms are driven by a servo motor and roller screw to apply programmed electrode force.

Servo drive: Electronic unit driving the gun servo motor that monitors internal temperature and derates operational speed when hot.

Electrode caps: Replaceable copper alloy contact caps mounted on water-cooled shanks that deliver current directly to the part.

Tip dresser: Motor-driven cutter unit that restores the contact surface geometry of electrode caps between welding cycles.

Fixture: Mechanical structure with locating pins, net pads, and pneumatic clamps that positions and secures parts during welding.

Current stepper: Weld controller function that increments secondary weld current as electrode caps wear over repeated cycles.

Energy control procedure: Documented procedure detailed in Chapter 8 for establishing zero energy states prior to performing maintenance.

---
*AM-WC-01 Rev. A | Servo-Gun Spot Weld Cell | Page 28 of 28 | Fictional equipment for demonstration only*
