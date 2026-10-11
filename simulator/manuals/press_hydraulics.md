<!-- page 1 -->

# Hydraulic Press and Power Unit - Operation and Maintenance Manual

**Document AM-PH-01 | Revision A | Issued 2026-10 | Line L1**

**Applies to:** ST10-PRS (ST10 Press)

> **IMPORTANT - FICTIONAL EQUIPMENT.** This manual describes fictional equipment created for the Andon Agent software demonstration (synthetic line L1). It is not a manufacturer's manual. Its energy control procedure is not a substitute for a site-specific energy control procedure prepared, approved and trained under 29 CFR 1910.147 or local regulation.

| Revision | Date | Change |
|---|---|---|
| A | 2026-10 | First issue |

**About this manual**

This manual serves operators, maintenance technicians, and reliability engineers working on the ST10-PRS hydraulic press and power unit. It provides operational instructions, technical specifications, and maintenance guidelines for line L1.

The manual is structured into numbered chapters. Chapter 1 addresses safety, Chapter 2 describes the equipment, and Chapter 3 presents technical data. Operational steps appear in Chapter 4, followed by Chapter 5 on control parameters, cycle timers, and change control. Chapter 6 contains troubleshooting assistance, Chapter 7 covers preventative maintenance tasks, and Chapter 8 details the energy control procedure. Supplementary definitions reside in Appendix A Glossary.

The troubleshooting material in Chapter 6 is organised by observed symptoms. This symptom-based structure allows rapid fault identification and systematic resolution during production.

---
*AM-PH-01 Rev. A | Hydraulic Press and Power Unit | Page 1 of 25 | Fictional equipment for demonstration only*

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
| 7 | Maintenance | 20 |
| 8 | Energy control procedure (lockout/tagout) | 21 |
| Appendix A | Glossary | 25 |

---
*AM-PH-01 Rev. A | Hydraulic Press and Power Unit | Page 2 of 25 | Fictional equipment for demonstration only*

<!-- page 3 -->

# 1 Safety

## 1.1 General safety

Only trained personnel may operate, inspect, or service the ST10-PRS equipment. Safety devices, fixed guards, and interlocks are installed to safeguard personnel from severe hazards, including high-pressure fluid injection, mechanical crushing around the slide and die area, burns from hot surfaces, and electric shock.

Guards and interlocks must never be bypassed, altered, or disabled under any circumstances. Operating personnel must verify that all protective enclosures and safety barriers are fully in place before initiating motion. If any guard, hose, electrical enclosure, or safety device shows signs of damage or wear, personnel must stop work and report the condition immediately.

A routine production stop leaves stored pressure in the accumulator and electrical potential in the motor circuit. All maintenance tasks inside guarded areas require that personnel apply the energy control procedure in Chapter 8 before touching any components.

## 1.2 Signal words

**Table 1-1 Signal words used in this manual**

| Signal word | Meaning |
|---|---|
| DANGER | A hazardous situation that will cause death or serious injury if not avoided |
| WARNING | A hazardous situation that could cause death or serious injury if not avoided |
| CAUTION | A hazardous situation that could cause minor or moderate injury if not avoided |
| NOTICE | A situation that could damage the equipment or the product |

---
*AM-PH-01 Rev. A | Hydraulic Press and Power Unit | Page 3 of 25 | Fictional equipment for demonstration only*

<!-- page 4 -->

## 1.3 Hazards and protective measures

**Table 1-2 Hazards**

| Hazard | Where | Protection |
|---|---|---|
| High-pressure oil injection | Hoses, fittings, accumulator | Relieve pressure before opening anything (Chapter 8) |
| Crushing | Die area, slide | Guards, light curtain, safety blocks under the slide (Chapter 8) |
| Stored energy in the accumulator | Accumulator and main circuit | Dump to tank (Chapter 8) |
| Burns | Hot oil, pump, cooler lines | Heat-resistant gloves and face shield |
| Electric shock | Motor and panel | Energy control procedure (Chapter 8) |
| Slips | Oil on the floor | Clean up leaks immediately |

## 1.4 Personal protective equipment

- Safety glasses
- Face shield when opening hydraulic lines
- Oil-resistant gloves
- Safety shoes

**WARNING** Before any maintenance, cleaning or adjustment inside a guarded area, apply the energy control procedure in Chapter 8.

---
*AM-PH-01 Rev. A | Hydraulic Press and Power Unit | Page 4 of 25 | Fictional equipment for demonstration only*

<!-- page 5 -->

# 2 Description

## 2.1 Overview

The ST10-PRS hydraulic press operates as a core forming station on line L1 of the demonstration car body-in-white assembly line. It shapes sheet metal body components by driving an upper die downward onto matched tooling. Line L1 operates 24 hours a day across three consecutive shifts, requiring steady throughput and continuous reliability.

The station relies on a dedicated hydraulic power unit that delivers pressurized oil to execute each press stroke. The output of the station directly feeds downstream operations, specifically the ST20 weld cell. Proper geometry and material forming at ST10-PRS are critical to overall line flow. If parts depart this station with incorrect dimensions, downstream assembly processes encounter immediate fit-up errors and operational faults. Maintaining nominal stroke timing and pressure consistency ensures balanced transfer across the entire body shop line.

## 2.2 Main components

**Table 2-1 Main components**

| Component | Function |
|---|---|
| Pump motor | Electric motor driving the hydraulic pump |
| Hydraulic pump | Variable displacement pump; internal leakage grows with wear |
| Proportional pressure valve | Sets the main system pressure from the active recipe |
| Directional valves | Switch oil to the press cylinder for each stroke |
| Bladder accumulator | Nitrogen-precharged; supplies peak flow during the stroke and smooths pressure |
| Oil cooler | Keeps the oil inside its temperature range |
| Tank and filters | Oil reservoir with return and pressure filters |
| Press cylinder and slide | Carries the upper die |
| Sensors | Main pressure, oil temperature, pump/motor vibration, motor current |

---
*AM-PH-01 Rev. A | Hydraulic Press and Power Unit | Page 5 of 25 | Fictional equipment for demonstration only*

<!-- page 6 -->

## 2.3 Principle of operation

The operating cycle begins when the electric pump motor drives the variable displacement hydraulic pump, drawing oil from the reservoir tank through suction filters. The proportional pressure valve regulates the main system pressure according to the active product recipe loaded for the run.

When the control system initiates a forming stroke, directional valves shift to route high-pressure hydraulic oil directly to the press cylinder. The nitrogen-precharged bladder accumulator discharges fluid into the main line, supplying peak flow during the stroke to smooth out pressure drops and accelerate slide motion. The cylinder advances the slide and upper die to form the part. After forming, the directional valves reverse fluid flow to retract the slide, and the returning oil passes through return filters and the oil cooler before entering the tank.

Throughout this sequence, multiple sensors monitor system health. The signal hyd_pressure_bar measures main system pressure, normally holding between 170 and 200 bar depending on the recipe. The signal motor_current_a monitors pump motor draw, staying within 34 to 50 A under typical load. Vibration velocity on the pump and motor assembly is tracked by vibration_rms_mms, which maintains a baseline of 1 to 4.5 mm/s. Tank temperature is registered by oil_temp_c, running between 35 and 55 degC as the oil cooler removes excess heat. Finally, cycle_time_s records the total duration of the completed press stroke, maintaining a nominal duration of 48 s within an acceptable range of 45 to 54 s.

---
*AM-PH-01 Rev. A | Hydraulic Press and Power Unit | Page 6 of 25 | Fictional equipment for demonstration only*

<!-- page 7 -->

# 3 Technical data

## 3.1 Process values and limits

The normal range is the band the equipment stays in during normal production. An alarm limit raises a warning and the station keeps running; a trip limit stops the station. A dash means the limit is not used.

**Table 3-1 Process values and limits: ST10-PRS (ST10 Press)**

| Tag | Description | Unit | Nominal | Normal range | Alarm low | Alarm high | Trip low | Trip high | Resolution |
|---|---|---|---|---|---|---|---|---|---|
| `motor_current_a` | Hydraulic pump motor current | A | 42 | 34 to 50 | - | 55 | - | 60 | 0.1 |
| `vibration_rms_mms` | Pump/motor vibration velocity RMS | mm/s | 2.2 | 1 to 4.5 | - | 7.1 | - | 11 | 0.01 |
| `hyd_pressure_bar` | Main system pressure (setpoint depends on product model) | bar | 180 | 170 to 200 | 165 | 205 | 155 | 215 | 0.1 |
| `oil_temp_c` | Hydraulic oil tank temperature | degC | 46 | 35 to 55 | - | 60 | - | 65 | 0.1 |
| `cycle_time_s` | Duration of the last completed press cycle | s | 48 | 45 to 54 | - | 58 | - | - | 0.1 |

---
*AM-PH-01 Rev. A | Hydraulic Press and Power Unit | Page 7 of 25 | Fictional equipment for demonstration only*

<!-- page 8 -->

## 3.2 Operating parameters

**Table 3-2 Operating parameters**

| Parameter | Value | Note |
|---|---|---|
| Main pressure setpoint, product model A | 180 bar | Loaded with the model A recipe |
| Main pressure setpoint, product model B | 190 bar | Loaded with the model B recipe |
| Setpoint tolerance after changeover | +/- 5 bar | Check before releasing the first part |
| Nominal cycle time | 48 s | One part |
| Oil temperature alarm / trip | 60 / 65 degC | Tank |
| Shift start times (changeover) | 06:00, 14:00, 22:00 | 15 min planned changeover at each shift start |

**Table 3-3 Main pressure setpoints by product model**

| Product model | Main pressure setpoint (bar) | Tolerance after changeover (bar) |
|---|---|---|
| A | 180 | +/- 5 |
| B | 190 | +/- 5 |

---
*AM-PH-01 Rev. A | Hydraulic Press and Power Unit | Page 8 of 25 | Fictional equipment for demonstration only*

<!-- page 9 -->

## 3.3 Alarm and stop messages

**Table 3-4 Alarm and stop messages**

| Code | Message | Condition or meaning |
|---|---|---|
| A-ST10-CUR-HI | ST10 Press: motor current high | `motor_current_a` above 55 A; alarm: the station keeps running |
| A-ST10-CUR-HH | ST10 Press: motor current high-high | `motor_current_a` above 60 A; trip: the station stops |
| A-ST10-VIB-HI | ST10 Press: vibration high | `vibration_rms_mms` above 7.1 mm/s; alarm: the station keeps running |
| A-ST10-VIB-HH | ST10 Press: vibration high-high | `vibration_rms_mms` above 11 mm/s; trip: the station stops |
| A-ST10-PRS-LO | ST10 Press: hydraulic pressure low | `hyd_pressure_bar` below 165 bar; alarm: the station keeps running |
| A-ST10-PRS-HI | ST10 Press: hydraulic pressure high | `hyd_pressure_bar` above 205 bar; alarm: the station keeps running |
| A-ST10-PRS-LL | ST10 Press: hydraulic pressure low-low | `hyd_pressure_bar` below 155 bar; trip: the station stops |
| A-ST10-PRS-HH | ST10 Press: hydraulic pressure high-high | `hyd_pressure_bar` above 215 bar; trip: the station stops |
| A-ST10-OILT-HI | ST10 Press: oil temperature high | `oil_temp_c` above 60 degC; alarm: the station keeps running |
| A-ST10-OILT-HH | ST10 Press: oil temperature high-high | `oil_temp_c` above 65 degC; trip: the station stops |
| A-ST10-CYC-HI | ST10 Press: cycle time high | `cycle_time_s` above 58 s; alarm: the station keeps running |
| S-ST10-HYD-FLT | ST10 Press: hydraulic fault, press stopped | Hydraulic protection; see Section 6.3 |
| A-ST10-LUB-LOW | way-lube reservoir low | Information; refill |
| A-ST10-STARVED | ST10 Press: station starved (waiting for part) | Consequence of a slow or stopped station upstream; not a fault at this station |
| A-ST10-BLOCKED | ST10 Press: station blocked (outfeed full) | Consequence of a slow or stopped station downstream; not a fault at this station |
| A-L1-ANDON | Line L1 stopped: andon raised | Information; follows any station stop |

---
*AM-PH-01 Rev. A | Hydraulic Press and Power Unit | Page 9 of 25 | Fictional equipment for demonstration only*

<!-- page 10 -->

# 4 Operation

## 4.1 Start-up

Shift start-up begins at the planned shift changeover times of 06:00, 14:00, or 22:00. Personnel conduct pre-start visual checks, verifying hydraulic oil levels in the main tank, inspecting the way-lube reservoir, checking filter clogging indicators, and ensuring that no oil leaks or puddles exist on the floor. Confirm all perimeter guards, doors, and interlocks are closed and secured.

Once pre-start inspections pass, the operator starts the pump motor. The motor current should settle within the normal range of 34 to 50 A. Main system pressure should rise and stabilize between 170 and 200 bar, matching the selected product recipe within the allowable setpoint tolerance of +/- 5 bar. Hydraulic oil temperature must be between 35 and 55 degC, and pump vibration must remain within 1 to 4.5 mm/s before releasing production.

## 4.2 Normal operation

During production, the operator oversees equipment performance by checking cycle consistency and monitoring live instrumentation on the operator interface. Key parameters must remain within normal limits, including motor current between 34 and 50 A, main pressure between 170 and 200 bar, oil temperature between 35 and 55 degC, and vibration velocity between 1 and 4.5 mm/s. The nominal cycle time should remain near 48 s.

Any operational deviation must be reported to maintenance immediately. Operators must log and escalate conditions where motor current exceeds the alarm threshold of 55 A, vibration exceeds 7.1 mm/s, oil temperature exceeds 60 degC, or cycle time exceeds 58 s. Likewise, if main pressure drifts past the alarm thresholds of 165 bar or 205 bar, or if fluid leaks appear, notify maintenance personnel without delay.

---
*AM-PH-01 Rev. A | Hydraulic Press and Power Unit | Page 10 of 25 | Fictional equipment for demonstration only*

<!-- page 11 -->

## 4.3 Normal production stop

A normal production stop is executed from the control interface at the conclusion of a run or shift. Halting the station de-energizes the electric pump motor, centers the directional valves, and parks the press slide in its resting position.

Operating personnel must understand that a normal production stop does not establish an energy-isolated state. High electrical voltage remains present inside control enclosures, and pressurized hydraulic fluid stays stored within the bladder accumulator and main fluid circuits. Any maintenance, tooling adjustment, or intervention requires personnel to apply the energy control procedure in Chapter 8.

## 4.4 Product changeover

1. Select the recipe for the new product model at the operator panel.
2. Confirm the recipe name on the panel matches the model on the production schedule.
3. Run the first stroke and read the main pressure on the panel.
4. Compare the main pressure with the setpoint for the model in Table 3-3.
5. Release the first part only if the pressure is within the tolerance in Table 3-3.
6. Record the model, recipe and pressure in the changeover log.

---
*AM-PH-01 Rev. A | Hydraulic Press and Power Unit | Page 11 of 25 | Fictional equipment for demonstration only*

<!-- page 12 -->

# 5 Control parameters: cycle timers and change control

## 5.1 Control parameters

The ST10-PRS press relies on specific adjustable control parameters to ensure uniform mechanical operation. These parameters include product recipe pressure targets, directional valve switching intervals, and cycle timers that coordinate slide extension, dwell, and retraction. Each manufactured part requires defined force and timing to achieve proper structural dimensions.

Uncontrolled or unauthorized modifications to these settings introduce severe risks to both product quality and overall line throughput. Altering a pressure setpoint or cycle timer can result in under-formed metal panels, erratic press motion, and starved downstream operations. For these reasons, all operational modifications must adhere to formal change control procedures. Every parameter change must be reviewed, authorized, and validated against product specifications before release.

**Table 5-1 Adjustable control parameters**

| Parameter | Function | May be changed by |
|---|---|---|
| Main pressure setpoint (per product model) | Proportional valve command from the recipe | Process engineer |
| Dwell at bottom of stroke | Holding time under pressure | Process engineer |
| Decompression time | Time to release pressure before the slide returns | Maintenance with change request |

---
*AM-PH-01 Rev. A | Hydraulic Press and Power Unit | Page 12 of 25 | Fictional equipment for demonstration only*

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
| ST10 cycle time stepped up at a shift start and stays at the new level; process signals normal | Timer or dwell parameter changed at the changeover (wrong value, wrong recipe, or a trial value left active) | Compare the active parameter set with the last approved copy; check the parameter log for the shift start | Restore the approved value under change control; record the deviation |
| Stations downstream starved and stations upstream blocked after a shift start | A slower cycle at one station propagating along the line | Find the first station whose cycle time changed; downstream starvation and upstream blocking are consequences | Correct the parameter at the first station only |
| Cycle time slightly longer for the first parts after every changeover | Normal ramp-up after a changeover | Confirm that cycle time returns to the normal range within a few cycles | No action |

---
*AM-PH-01 Rev. A | Hydraulic Press and Power Unit | Page 13 of 25 | Fictional equipment for demonstration only*

<!-- page 14 -->

# 6 Troubleshooting

## 6.1 Using this chapter

When addressing an operational issue, technicians should begin by consulting the symptom index in Chapter 6. Match the observed operational anomaly with the corresponding entry to locate the relevant troubleshooting section.

Review the typical signal signature to evaluate system behavior across pressure, cycle time, motor current, oil temperature, and vibration. Always verify that sensors and instrumentation are functioning correctly to rule out false transmitter readings. Technicians must methodically perform the inspections detailed in the check column before executing any suggested remedy. If physical intervention, disassembly, or component adjustment is required, apply the energy control procedure in Chapter 8 before starting hands-on work.

**Table 6-1 Symptom index**

| First symptom | Topic | Section | Page |
|---|---|---|---|
| Main pressure off setpoint right after a changeover, then steady | Product changeover: recipe and pressure setpoint verification | 6.2 | 15 |
| `hyd_pressure_bar` sagging below setpoint, `motor_current_a` above 50 A, oil warming | Hydraulic degradation: pump leakage, valve lag, accumulator, cooler | 6.3 | 16 |
| One signal trending with no change in related signals | Instrument verification: suspected sensor drift | 6.4 | 18 |
| Cycle time stepped at a shift start, process normal | Control parameters: cycle timers and change control | 5 | 12 |

---
*AM-PH-01 Rev. A | Hydraulic Press and Power Unit | Page 14 of 25 | Fictional equipment for demonstration only*

<!-- page 15 -->

## 6.2 Product changeover: recipe and pressure setpoint verification

**Typical signature.** Each product model has its own main pressure setpoint: model A 180 bar and model B 190 bar (see Table 3-3). If the recipe for the wrong model, or a wrong value, is loaded at a changeover, main pressure (`hyd_pressure_bar`) settles at the wrong level as a clean step right after the changeover and stays there. Parts are under-formed, and the ST20 weld cell downstream starts to show weld quality alarms and scatter in tip resistance.

**Diagnostic notes**

- A step change in main pressure that starts exactly at a changeover, with oil temperature and vibration unchanged, is a recipe or setpoint error, not hydraulic wear.
- After every model change, compare the displayed main pressure with the setpoint for the model now running before releasing the first part; the tolerance is +/- 5 bar.
- Weld faults at ST20 that start after a press changeover are often caused by the press; check this section before changing weld schedules.

**Table 6-2 Troubleshooting: Product changeover: recipe and pressure setpoint verification**

| Symptom | Probable cause | Check | Remedy |
|---|---|---|---|
| Main pressure off setpoint right after a changeover, then steady | Wrong recipe loaded, or a wrong setpoint saved in the recipe | Compare the active recipe and setpoint with Table 3-3 and the production schedule | Load the correct recipe; quarantine parts made since the changeover |
| Weld faults at ST20 after a press changeover | Under-formed parts from a wrong press pressure | Check `hyd_pressure_bar` against the setpoint for the model | Correct the press recipe first; then re-check ST20 |
| Pressure correct but parts under-formed after a changeover | Wrong die or die height | Check the die number and the shut height | Correct the die setup |

**Background.**

Line L1 incorporates planned 15 min changeovers at the start of each shift at 06:00, 14:00, and 22:00. Product forming relies on specific recipe data loaded into the machine controller. Each product variant demands a distinct main pressure setpoint to achieve required metal deformation: product model A requires 180 bar, whereas product model B requires 190 bar, as detailed in Table 3-3. The acceptable setpoint tolerance after a changeover is +/- 5 bar.

When an incorrect recipe or an erroneous pressure value is loaded during changeover, the proportional pressure valve responds immediately. The sensor signal hyd_pressure_bar reflects this setting by shifting cleanly to the wrong pressure value right after the changeover and holding steady at that incorrect level. Because this error originates purely in software configuration, it appears as an abrupt step rather than a gradual drift. When pressure remains at an improper low setpoint, parts exit under-formed. Downstream at the ST20 weld cell, mismatched part geometries cause poor mating fit-up, triggering weld quality alarms and scatter in tip resistance.

---
*AM-PH-01 Rev. A | Hydraulic Press and Power Unit | Page 15 of 25 | Fictional equipment for demonstration only*

<!-- page 16 -->

## 6.3 Hydraulic degradation: pump leakage, valve lag, accumulator, cooler

**Typical signature.** Hydraulic wear develops over hours to days, not at a changeover. Four failure modes are common: internal pump leakage, a sluggish (lagging) switching valve, loss of accumulator precharge, and loss of cooler efficiency. Each moves pressure, motor current, oil temperature, vibration and cycle time in its own pattern; use Table 6-3 to tell them apart. All four lengthen the press cycle, which starves the stations downstream.

**Table 6-3 Hydraulic degradation patterns**

| Failure mode | Main pressure | Motor current | Oil temperature | Vibration | Cycle time |
|---|---|---|---|---|---|
| Internal pump leakage | Sags below setpoint | Rises | Rises slowly | Normal | Longer |
| Switching valve lag | Ragged, noisy | Normal | Normal | Rises | Longer and scattered |
| Accumulator precharge loss | Slow swing (about 20 s period), noisy | Fluctuates | Normal | Normal | Longer |
| Cooler efficiency loss | Normal | Normal | Rises steadily | Normal | Slightly longer |

**Diagnostic notes**

- Pressure sagging below setpoint while motor current rises and oil temperature creeps up indicates internal pump leakage.
- A ragged pressure trace with rising vibration and scattered cycle times indicates a lagging switching valve.
- A slow pressure swing with a period of about 20 s, with motor current fluctuating more than usual, indicates loss of accumulator precharge.
- Oil temperature rising steadily while pressure and vibration stay normal indicates loss of cooler efficiency.
- Longer cycle times at stations downstream of ST10 are a consequence of the slower press, not faults at those stations.

---
*AM-PH-01 Rev. A | Hydraulic Press and Power Unit | Page 16 of 25 | Fictional equipment for demonstration only*

<!-- page 17 -->

**Table 6-4 Troubleshooting: Hydraulic degradation: pump leakage, valve lag, accumulator, cooler**

| Symptom | Probable cause | Check | Remedy |
|---|---|---|---|
| `hyd_pressure_bar` sagging below setpoint, `motor_current_a` above 50 A, oil warming | Internal pump leakage (worn pump) | Case drain flow test; compare with the last test record | Replace or overhaul the pump |
| Pressure trace ragged, `vibration_rms_mms` above 4.5 mm/s, cycle times scattered | Switching valve lag (contamination, worn spool, weak solenoid) | Check valve switching time on the diagnostic screen; check oil cleanliness | Clean or replace the valve; change filters |
| Slow pressure swing, motor current fluctuating | Accumulator precharge low or bladder failed | Check the nitrogen precharge with the charging kit under energy control (Chapter 8) | Recharge with nitrogen; replace the bladder if it does not hold |
| `oil_temp_c` above 55 degC, rising; pressure normal | Cooler fouled, cooling water low, or cooler fan failed | Check the cooler inlet and outlet temperatures and the cooling water flow | Clean the cooler; restore cooling water flow |
| Oil temperature trip A-ST10-OILT-HH at 65 degC | Any of the above not corrected | Find the cause before restart | Let the oil cool; correct the cause |

**Background.**

Hydraulic component degradation develops slowly over hours or days of continuous production, contrasting sharply with immediate changeover parameter steps. Four primary physical mechanisms drive this wear: variable pump internal leakage, switching valve lag, loss of bladder accumulator nitrogen precharge, and reduced oil cooler efficiency. As internal clearances in the pump widen, slip flow returns directly to the tank instead of the main line, reducing available volume under load.

Each wear mechanism alters sensor signatures in a distinctive manner across motor current, vibration, pressure, oil temperature, and cycle time. For instance, pump leakage and valve lag delay cylinder motion, while depleted accumulator precharge eliminates supplemental peak flow, causing severe pressure dips during the stroke. Reduced cooling capacity permits tank temperatures to climb toward the alarm limit of 60 degC and trip limit of 65 degC. Regardless of the specific mechanism, hydraulic degradation inevitably lengthens cycle_time_s beyond the nominal 48 s value, eventually exceeding the 58 s alarm threshold and starving downstream stations such as the ST20 weld cell.

---
*AM-PH-01 Rev. A | Hydraulic Press and Power Unit | Page 17 of 25 | Fictional equipment for demonstration only*

<!-- page 18 -->

## 6.4 Instrument verification: suspected sensor drift

**Typical signature.** One monitored value trends slowly towards a limit, or jumps beyond it, while the signals that are physically linked to it stay normal.

**Table 6-5 Physical correlates of monitored signals**

| Signal | Physically related signals and checks |
|---|---|
| `oil_temp_c` | Cooler outlet temperature by hand, motor current, cycle time, handheld reading at the tank |
| `hyd_pressure_bar` | Motor current, cycle time, panel gauge |
| `vibration_rms_mms` | Motor current, pump sound, pressure stability |

**Diagnostic notes**

- A real process change moves more than one signal; a single tag that trends steadily while every physically related tag stays normal points to the instrument, not the process.
- Do not replace process components on the evidence of one drifting tag; verify the instrument first against a calibrated reference at the measuring point.
- A reading that jumps beyond a trip limit for one to three seconds and then returns, with no change in related tags before or after, is a measurement spike; reset, record it and keep the station running.
- Gaps in a trend, a value that stays exactly constant for a long period (stuck value) and the same alarm repeating several times within a minute (alarm chatter) are data-quality effects of the instrument or the network; they are not process faults and are not evidence of a failure.

---
*AM-PH-01 Rev. A | Hydraulic Press and Power Unit | Page 18 of 25 | Fictional equipment for demonstration only*

<!-- page 19 -->

**Table 6-6 Troubleshooting: suspected sensor drift**

| Symptom | Probable cause | Check | Remedy |
|---|---|---|---|
| One tag trends steadily towards a limit; all related tags in Table 6-5 stay normal | Transmitter drift (ageing, contamination, loose terminal, moisture in the connector) | Compare the reading with a calibrated handheld reference at the same point; inspect the connector and cable | Recalibrate or replace the transmitter; record the as-found and as-left values in the calibration log |
| Station stopped on a high-high or low-low trip after a one- to three-second excursion | Measurement spike (electrical noise, loose shield, vibration on the cable) | Check the trend either side of the trip; check related tags; inspect cable shield and gland | Reset and restart; if spikes repeat, re-terminate the shield and re-route the cable away from power cables |
| Value frozen at exactly the same number for a long period | Stuck value: lost update between the transmitter and the controller or historian | Check the transmitter display against the HMI; check the communication diagnostics | Restore communication; do not use the frozen period as process evidence |
| Same alarm raised and cleared several times within a minute | Alarm chatter: value hovering at the limit with too little deadband | Check the trend at the limit; check the alarm deadband setting | Treat as one event; request a deadband review through change control (see Chapter 5) |

---
*AM-PH-01 Rev. A | Hydraulic Press and Power Unit | Page 19 of 25 | Fictional equipment for demonstration only*

<!-- page 20 -->

# 7 Maintenance

## 7.1 Preventive maintenance

Strict adherence to preventive maintenance schedules ensures the operational reliability, safety, and pressing precision of the ST10-PRS. Routine servicing maintains proper fluid cleanliness, preserves accumulator performance, detects mechanical wear, and prevents unpredicted line stoppages on line L1.

Maintenance intervals range from per-shift fluid checks to weekly indicator inspections, quarterly cooler and accumulator services, and semi-annual or annual component overhauls. Whenever a technician completes a maintenance task, all findings, measurements, component replacements, and test results must be recorded in the equipment logbook. Complete records provide essential baseline data for reliability tracking and equipment health assessments.

**Table 7-1 Preventive maintenance intervals**

| Task | Interval | See |
|---|---|---|
| Check oil level and look for leaks | Every shift | Section 6.3 |
| Check the way-lube reservoir | Every shift | - |
| Check the filter clogging indicators | Weekly | Section 6.3 |
| Clean the oil cooler | Quarterly | Section 6.3 |
| Check the accumulator nitrogen precharge | Quarterly | Section 6.3 |
| Oil sample for cleanliness and water | Quarterly | Section 6.3 |
| Pump case drain flow test | Every 6 months | Section 6.3 |
| Replace return and pressure filter elements | Every 6 months | Section 6.3 |
| Calibration check of pressure and oil temperature transmitters | Yearly | Section 6.4 |

## 7.2 Recommended spare parts

**Table 7-2 Recommended spare parts**

| Part | Quantity to stock |
|---|---|
| Filter elements (return and pressure) | 2 sets |
| Accumulator bladder | 1 |
| Directional valve solenoid | 1 |
| Hydraulic oil | 1 drum |
| Seal kit, press cylinder | 1 |

---
*AM-PH-01 Rev. A | Hydraulic Press and Power Unit | Page 20 of 25 | Fictional equipment for demonstration only*

<!-- page 21 -->

# 8 Energy control procedure (lockout/tagout)

## 8.1 Scope, purpose and authorisation

> **IMPORTANT - FICTIONAL EQUIPMENT.** This manual describes fictional equipment created for the Andon Agent software demonstration (synthetic line L1). It is not a manufacturer's manual. Its energy control procedure is not a substitute for a site-specific energy control procedure prepared, approved and trained under 29 CFR 1910.147 or local regulation.

**Equipment.** Hydraulic press with power unit (pump, motor, bladder accumulator, valves, cooler, tank). Applies to: ST10-PRS.

**Purpose.** This procedure controls hazardous energy when anyone changes or adjusts a die by hand, reaches into the die area, opens a hydraulic line, or works on the power unit, the accumulator, the valves or the cylinder.

**Authorisation.** Only authorised employees trained on this procedure may apply or remove locks and tags. Each authorised employee applies a personal lock and tag; a group lockout uses a lock box with one personal lock per employee.

**Basis.** This procedure follows the energy control procedure requirements of 29 CFR 1910.147(c)(4) and the sequence of 29 CFR 1910.147(d)(1) to (d)(6), with notification under (c)(9) and release from lockout or tagout under (e). Each step cites its paragraph. Steps are carried out in the order given.

## 8.2 Energy sources

**Table 8-1 Hazardous energy sources and isolating devices**

| Energy | Source and magnitude | Isolating device | Stored or residual energy |
|---|---|---|---|
| Electrical | 400 V AC three-phase supply to the pump motor; 24 V DC control | Hydraulic power unit main disconnect switch; press control power disconnect | None after isolation |
| Hydraulic | Main system pressure 170-200 bar (trip at 215 bar) | Pump stopped and isolated | Bladder accumulator holds oil at system pressure after the pump stops; dump to tank |
| Gravity | Slide and upper die can descend under their own weight | None (mechanical) | Insert both safety blocks between the bolster and the slide |
| Thermal | Hydraulic oil up to 65 degC before trip | None | Allow to cool; heat-resistant gloves and face shield |

---
*AM-PH-01 Rev. A | Hydraulic Press and Power Unit | Page 21 of 25 | Fictional equipment for demonstration only*

<!-- page 22 -->

## 8.3 Preparation, shutdown, isolation and lockout

**Table 8-2 Preparation, shutdown, isolation and lockout**

| Step | Action | 29 CFR 1910.147 paragraph |
|---|---|---|
| 1 | Identify every energy source for the press from Table 8-1 and collect one personal lock and tag for each isolating device. | (d)(1) |
| 2 | Notify the line lead and the ST10 and ST20 operators that the press will be shut down and locked out. | (c)(9) |
| 3 | Complete the current stroke, stop the slide at top dead centre with the cycle stop push-button, then stop the hydraulic pump at the operator panel. | (d)(2) |
| 4 | Switch the hydraulic power unit main disconnect switch to OFF. | (d)(3) |
| 5 | Switch the press control power disconnect to OFF. | (d)(3) |
| 6 | Fit a personal lock and tag to the hydraulic power unit main disconnect switch and to the press control power disconnect. | (d)(4) |

---
*AM-PH-01 Rev. A | Hydraulic Press and Power Unit | Page 22 of 25 | Fictional equipment for demonstration only*

<!-- page 23 -->

## 8.4 Stored energy and verification of isolation

**Table 8-3 Stored energy and verification of isolation**

| Step | Action | 29 CFR 1910.147 paragraph |
|---|---|---|
| 7 | Insert both safety blocks between the bolster and the slide before any part of the body enters the die area. | (d)(5)(i) |
| 8 | Open the accumulator dump valve and watch the system pressure gauge fall to zero. | (d)(5)(i) |
| 9 | Open the main circuit bleed valve to release pressure trapped between the directional valves and the cylinder. | (d)(5)(i) |
| 10 | Do not open a hydraulic line or the tank while the oil temperature reads above 50 degC, and wear heat-resistant gloves and a face shield. | (d)(5)(i) |
| 11 | Keep the accumulator dump valve open for the whole job and check the system pressure gauge again before each new task. | (d)(5)(ii) |
| 12 | Press the pump start push-button and the slide jog buttons to confirm that nothing starts or moves, then return the controls to off. | (d)(6) |
| 13 | Confirm that the system pressure gauge and the accumulator gauge both read zero. | (d)(6) |
| 14 | Test for absence of voltage at the pump motor terminals with a tester proven on a known live source before and after the test. | (d)(6) |

---
*AM-PH-01 Rev. A | Hydraulic Press and Power Unit | Page 23 of 25 | Fictional equipment for demonstration only*

<!-- page 24 -->

## 8.5 Release from lockout/tagout

**Table 8-4 Release from lockout/tagout**

| Step | Action | 29 CFR 1910.147 paragraph |
|---|---|---|
| 15 | Remove both safety blocks, tools and nonessential items from the press, and confirm that every hydraulic fitting and guard is fitted and tight. | (e)(1) |
| 16 | Close the main circuit bleed valve and the accumulator dump valve. | (e)(1) |
| 17 | Check that all employees are clear of the press and the die area. | (e)(2)(i) |
| 18 | Each employee removes only the lock and tag that the employee applied. | (e)(3) |
| 19 | Notify the affected employees that the locks and tags have been removed before the press is restarted. | (e)(2)(ii) |

**Testing or positioning.** If the equipment must be energised temporarily to test or position it, follow 29 CFR 1910.147(f)(1): clear tools and materials, remove employees from the area, remove the locks and tags, energise and test, then de-energise and reapply every energy control measure in the order of this chapter before work continues.

---
*AM-PH-01 Rev. A | Hydraulic Press and Power Unit | Page 24 of 25 | Fictional equipment for demonstration only*

<!-- page 25 -->

# Appendix A Glossary

Pump motor: An electric motor that supplies mechanical rotational energy to drive the hydraulic pump.

Hydraulic pump: A variable displacement pump that converts mechanical input into hydraulic fluid flow, developing increased internal leakage as mechanical wear accumulates.

Proportional pressure valve: An electrically commanded hydraulic valve that establishes the main circuit operating pressure based on the active product recipe.

Directional valves: Hydraulic spool valves that route pressurized oil to alternate sides of the press cylinder to execute stroke extension and retraction.

Bladder accumulator: A nitrogen-precharged hydraulic vessel that stores fluid under pressure to supply peak volume during the press stroke and smooth pressure spikes.

Oil cooler: A heat exchange device that extracts thermal energy from the hydraulic fluid to keep operating temperatures within specified limits.

Press cylinder and slide: The hydraulic actuator and structural ram assembly that carries the upper die downward to form sheet metal components.

Return and pressure filters: Porous filtration elements located in the supply and return lines that capture contaminants to preserve oil cleanliness.

Changeover: A 15 min planned operational window scheduled at shift start times 06:00, 14:00, and 22:00 to configure tooling, parameters, and recipes.

---
*AM-PH-01 Rev. A | Hydraulic Press and Power Unit | Page 25 of 25 | Fictional equipment for demonstration only*
