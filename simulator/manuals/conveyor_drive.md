<!-- page 1 -->

# Chain Conveyor Drive Unit - Operation and Maintenance Manual

**Document AM-CD-01 | Revision A | Issued 2026-10 | Line L1**

**Applies to:** ST50-CNV (ST50 Conveyor)

> **IMPORTANT - FICTIONAL EQUIPMENT.** This manual describes fictional equipment created for the Andon Agent software demonstration (synthetic line L1). It is not a manufacturer's manual. Its energy control procedure is not a substitute for a site-specific energy control procedure prepared, approved and trained under 29 CFR 1910.147 or local regulation.

| Revision | Date | Change |
|---|---|---|
| A | 2026-10 | First issue |

**About this manual**

This manual serves operators, maintenance technicians, and reliability engineers working with the chain conveyor drive unit on line L1. It provides instructions for operation, routine care, and mechanical assessment across all production shifts.

The content is structured by chapters to facilitate fast retrieval during routine work and technical interventions. Chapter 1 introduces safety fundamentals, while Chapter 2 and Chapter 3 outline unit descriptions and technical data. Chapter 4 and Chapter 5 cover operating procedures, control parameters, cycle timers, and change control. Chapter 6 details troubleshooting, arranged logically by observed symptom. Preventive schedules appear in Chapter 7, followed by Chapter 8 for the energy control procedure. Appendix A provides a technical glossary, and Appendix B details interface data for the ST60 vision check.

---
*AM-CD-01 Rev. A | Chain Conveyor Drive Unit | Page 1 of 24 | Fictional equipment for demonstration only*

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
| 7 | Maintenance | 18 |
| 8 | Energy control procedure (lockout/tagout) | 19 |
| Appendix A | Glossary | 23 |
| Appendix B | ST60 vision check: interface data | 24 |

---
*AM-CD-01 Rev. A | Chain Conveyor Drive Unit | Page 2 of 24 | Fictional equipment for demonstration only*

<!-- page 3 -->

# 1 Safety

## 1.1 General safety

Safe operation of the conveyor drive unit requires strict adherence to operating practices by authorized and trained personnel only. Personnel must recognize the operational risks associated with rotating assemblies, drive chains, and electrical cabinets. All guards and safety interlocks are fitted to prevent contact with moving components and high-voltage sections. These protective devices must never be bypassed, defeated, or modified during production or testing.

Operators and technical staff must inspect the machine envelope continuously and report any structural damage, missing fasteners, unusual noises, or loose guards to supervision without delay. Physical intervention inside guarded areas poses severe hazards from chain movement, spring tension, and hot surfaces. Whenever inspection, adjustment, cleaning, or maintenance must occur inside guarded perimeters, personnel must apply the energy control procedure in Chapter 8.

## 1.2 Signal words

**Table 1-1 Signal words used in this manual**

| Signal word | Meaning |
|---|---|
| DANGER | A hazardous situation that will cause death or serious injury if not avoided |
| WARNING | A hazardous situation that could cause death or serious injury if not avoided |
| CAUTION | A hazardous situation that could cause minor or moderate injury if not avoided |
| NOTICE | A situation that could damage the equipment or the product |

---
*AM-CD-01 Rev. A | Chain Conveyor Drive Unit | Page 3 of 24 | Fictional equipment for demonstration only*

<!-- page 4 -->

## 1.3 Hazards and protective measures

**Table 1-2 Hazards**

| Hazard | Where | Protection |
|---|---|---|
| Entanglement and crushing | Chain, sprocket, carriers, take-up | Guards in place; energy control before reaching in (Chapter 8) |
| Unexpected chain movement | Loaded carriers on inclines; take-up spring | Chain lock; release spring tension only as described in Chapter 8 |
| Burns | Bearing housings, gearbox | Heat-resistant gloves |
| Electric shock | Inverter DC bus, motor terminals | Energy control procedure (Chapter 8); wait for DC bus discharge |

## 1.4 Personal protective equipment

- Safety glasses
- Close-fitting clothing, no loose sleeves
- Cut-resistant gloves
- Safety shoes

**WARNING** Before any maintenance, cleaning or adjustment inside a guarded area, apply the energy control procedure in Chapter 8.

---
*AM-CD-01 Rev. A | Chain Conveyor Drive Unit | Page 4 of 24 | Fictional equipment for demonstration only*

<!-- page 5 -->

# 2 Description

## 2.1 Overview

The chain conveyor drive unit, designated ST50-CNV, operates within demonstration car body-in-white assembly line L1. Line L1 runs 24 hours a day across three shifts, with each shift starting with a planned changeover. The primary role of the drive unit is to advance mechanical transport fixtures holding car body parts between work cells at a steady rate.

The drive unit interacts directly with adjacent process stations along the line. Upstream workstations load body components onto the continuous handling chain, relying on uninterrupted movement to clear assembly fixtures within planned cycle durations. Downstream, the conveyor feeds assemblies into downstream inspection cells, including the ST60 vision station. If the conveyor chain changes velocity or halts, cycle timing upstream increases and part delivery to the vision cell ceases, making continuous drive operation vital for line throughput.

## 2.2 Main components

**Table 2-1 Main components**

| Component | Function |
|---|---|
| Drive inverter | Controls motor speed; holds the chain speed constant |
| Brake gearmotor | Motor with spring-applied brake and helical gearbox |
| Drive shaft and bearings | Drive-end and non-drive-end rolling bearings in housings; the drive-end housing carries the vibration and temperature sensors |
| Drive sprocket and pulley | Pulley diameter 0.25 m |
| Chain and carriers | Carriers move the parts between stations |
| Spring take-up | Keeps the chain under tension at the return end |
| Vibration sensor | Velocity RMS at the drive-end bearing housing; high-rate snapshots available for spectrum analysis |
| Bearing temperature sensor | Drive-end bearing housing temperature |

---
*AM-CD-01 Rev. A | Chain Conveyor Drive Unit | Page 5 of 24 | Fictional equipment for demonstration only*

<!-- page 6 -->

## 2.3 Principle of operation

The drive unit operates continuously to move transport fixtures between production stations. Power originates at the drive inverter, which feeds electrical power to the brake gearmotor. The brake gearmotor incorporates an integral spring-applied brake and a helical gearbox that delivers mechanical torque to the primary drive shaft. This drive shaft is supported by two rolling bearings: one at the drive end and one at the non-drive end. The shaft turns a drive sprocket and a drive pulley with a diameter of 0.25 m. Rotation of the drive sprocket pulls the continuous chain along its track, while a spring take-up at the return end maintains chain tension.

During steady operation, several instruments monitor drive performance. The chain speed signal, ST50-CNV speed_mpm, measures the linear rate of the chain; the drive inverter regulates this motion to hold the value within its normal range of 11.5 to 12.5 m/min. Motor current is measured by ST50-CNV motor_current_a, which shows the electrical draw of the loaded motor within a normal range of 12 to 18 A. At the drive-end bearing housing, a dedicated vibration sensor tracks ST50-CNV vibration_rms_mms, which indicates mechanical velocity root mean square within a baseline band of 0.8 to 2.8 mm/s. Temperature sensor ST50-CNV bearing_temp_c monitors the thermal state of the drive-end bearing housing, displaying normal operating readings from 25 to 55 degC. Downstream at the inspection stage, ST60-VIS cycle_time_s records the inspection cycle duration, typically 43 to 52 s, while ST60-VIS reject_rate_pct registers part quality, showing between 0 to 5 % rejects under normal conditions.

---
*AM-CD-01 Rev. A | Chain Conveyor Drive Unit | Page 6 of 24 | Fictional equipment for demonstration only*

<!-- page 7 -->

# 3 Technical data

## 3.1 Process values and limits

The normal range is the band the equipment stays in during normal production. An alarm limit raises a warning and the station keeps running; a trip limit stops the station. A dash means the limit is not used.

**Table 3-1 Process values and limits: ST50-CNV (ST50 Conveyor)**

| Tag | Description | Unit | Nominal | Normal range | Alarm low | Alarm high | Trip low | Trip high | Resolution |
|---|---|---|---|---|---|---|---|---|---|
| `motor_current_a` | Drive motor current | A | 15 | 12 to 18 | - | 20 | - | - | 0.1 |
| `vibration_rms_mms` | Drive-end bearing vibration velocity RMS | mm/s | 1.6 | 0.8 to 2.8 | - | 4.5 | - | 7.1 | 0.01 |
| `speed_mpm` | Chain speed | m/min | 12 | 11.5 to 12.5 | 11 | - | - | - | 0.01 |
| `bearing_temp_c` | Drive-end bearing housing temperature | degC | 38 | 25 to 55 | - | 65 | - | 75 | 0.1 |

---
*AM-CD-01 Rev. A | Chain Conveyor Drive Unit | Page 7 of 24 | Fictional equipment for demonstration only*

<!-- page 8 -->

## 3.2 Operating parameters

**Table 3-2 Operating parameters**

| Parameter | Value | Note |
|---|---|---|
| Chain speed, nominal | 12 m/min | Held by the inverter |
| Pulley diameter | 0.25 m | Drive end |
| Pulley rotation frequency (1x) | 0.255 Hz | At 12 m/min; one turn every 3.9 s |
| Drive motor current, nominal | 15 A | Loaded chain |
| Vibration alarm / trip | 4.5 / 7.1 mm/s | Velocity RMS, drive-end bearing |

---
*AM-CD-01 Rev. A | Chain Conveyor Drive Unit | Page 8 of 24 | Fictional equipment for demonstration only*

<!-- page 9 -->

## 3.3 Alarm and stop messages

**Table 3-3 Alarm and stop messages**

| Code | Message | Condition or meaning |
|---|---|---|
| A-ST50-CUR-HI | ST50 Conveyor: motor current high | `motor_current_a` above 20 A; alarm: the station keeps running |
| A-ST50-VIB-HI | ST50 Conveyor: vibration high | `vibration_rms_mms` above 4.5 mm/s; alarm: the station keeps running |
| A-ST50-VIB-HH | ST50 Conveyor: vibration high-high | `vibration_rms_mms` above 7.1 mm/s; trip: the station stops |
| A-ST50-SPD-LO | ST50 Conveyor: chain speed low | `speed_mpm` below 11 m/min; alarm: the station keeps running |
| A-ST50-BRGT-HI | ST50 Conveyor: bearing temperature high | `bearing_temp_c` above 65 degC; alarm: the station keeps running |
| A-ST50-BRGT-HH | ST50 Conveyor: bearing temperature high-high | `bearing_temp_c` above 75 degC; trip: the station stops |
| A-ST50-ESTOP-RST | e-stop reset acknowledged | Information |
| S-ST50-VIB-HH | Conveyor drive stopped: vibration high-high | Trip; see Section 6.2 |
| A-ST50-STARVED | ST50 Conveyor: station starved (waiting for part) | Consequence of a slow or stopped station upstream; not a fault at this station |
| A-ST50-BLOCKED | ST50 Conveyor: station blocked (outfeed full) | Consequence of a slow or stopped station downstream; not a fault at this station |
| A-L1-ANDON | Line L1 stopped: andon raised | Information; follows any station stop |

---
*AM-CD-01 Rev. A | Chain Conveyor Drive Unit | Page 9 of 24 | Fictional equipment for demonstration only*

<!-- page 10 -->

# 4 Operation

## 4.1 Start-up

Prior to starting the drive unit at the start of a shift, the operator must execute pre-start inspections. Verify that all mechanical perimeter guards surrounding the drive sprocket, chain line, take-up spring, and drive shaft are secured. Inspect the helical gearbox and bearing housings for visible lubricating oil leaks. Confirm that the travel path of the chain is free of loose tooling, parts, or foreign debris.

Once pre-start checks are complete, initiate the start sequence from the main control interface. The drive inverter ramps the brake gearmotor up to standard running speed, releasing the spring-applied brake. The operator must confirm that monitored variables stabilize in their normal zones: ST50-CNV speed_mpm reaches approximately 12 m/min, ST50-CNV motor_current_a settles between 12 and 18 A, vibration remains below 2.8 mm/s, and bearing temperature stays between 25 and 55 degC.

## 4.2 Normal operation

Throughout the production shift, operators monitor system behavior and instrumentation signals on the line human-machine interface. Consistent chain movement is confirmed by observing ST50-CNV speed_mpm within 11.5 to 12.5 m/min. Motor current should stay between 12 and 18 A on ST50-CNV motor_current_a. Drive-end housing vibration must remain within the 0.8 to 2.8 mm/s baseline on ST50-CNV vibration_rms_mms, and housing temperature must stay within 25 to 55 degC on ST50-CNV bearing_temp_c. Additionally, downstream quality signals from ST60-VIS must show reject rates under 6 % and cycle times under 56 s.

Any persistent operational irregularity must be reported to maintenance immediately. If motor current climbs toward the 20 A alarm high, if vibration approaches the 4.5 mm/s alarm high, if bearing temperature rises toward 65 degC, or if chain speed drops below 11 m/min, notify maintenance technicians for prompt diagnostic evaluation.

---
*AM-CD-01 Rev. A | Chain Conveyor Drive Unit | Page 10 of 24 | Fictional equipment for demonstration only*

<!-- page 11 -->

## 4.3 Normal production stop

A normal production stop occurs at the conclusion of a production run or before planned changeover. The operator initiates the stop command via the control panel. The inverter ramps down motor frequency, brings the chain to a controlled rest, and engages the integral spring-applied brake on the gearmotor to secure the drive shaft.

Executing a normal stop command ceases line movement, but it does not remove electrical or stored mechanical energy from the drive unit. Hazards persist at the inverter bus, motor terminals, and take-up spring. All maintenance tasks require personnel to apply the energy control procedure in Chapter 8.

---
*AM-CD-01 Rev. A | Chain Conveyor Drive Unit | Page 11 of 24 | Fictional equipment for demonstration only*

<!-- page 12 -->

# 5 Control parameters: cycle timers and change control

## 5.1 Control parameters

The drive unit relies on specific control parameters to ensure steady part transfer between stations. Key parameters include the motor speed command setpoint within the inverter, which determines the chain velocity, as well as programmable delay timers and station interlock windows. These values govern the timing with which mechanical transport fixtures enter and exit assembly positions along line L1.

Modifying these parameters outside authorized protocols poses severe operational hazards. Altering inverter speed setpoints or timer values disrupts line balancing, causes upstream stations to accumulate excessive cycle times, and induces mechanical shock loading across the chain and take-up spring. To protect mechanical hardware, equipment uptime, and product assembly quality, all adjustments to control parameters must follow formal change control procedures.

**Table 5-1 Adjustable control parameters**

| Parameter | Function | May be changed by |
|---|---|---|
| Chain speed setpoint | Inverter speed reference | Maintenance with change request |
| Acceleration and deceleration ramps | Inverter ramps | Maintenance with change request |
| Transfer dwell | Time a carrier waits at each station transfer | Process engineer |

---
*AM-CD-01 Rev. A | Chain Conveyor Drive Unit | Page 12 of 24 | Fictional equipment for demonstration only*

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
| ST50 or ST60 cycle time stepped up at a shift start and stays at the new level; process signals normal | Timer or dwell parameter changed at the changeover (wrong value, wrong recipe, or a trial value left active) | Compare the active parameter set with the last approved copy; check the parameter log for the shift start | Restore the approved value under change control; record the deviation |
| Stations downstream starved and stations upstream blocked after a shift start | A slower cycle at one station propagating along the line | Find the first station whose cycle time changed; downstream starvation and upstream blocking are consequences | Correct the parameter at the first station only |
| Cycle time slightly longer for the first parts after every changeover | Normal ramp-up after a changeover | Confirm that cycle time returns to the normal range within a few cycles | No action |

---
*AM-CD-01 Rev. A | Chain Conveyor Drive Unit | Page 13 of 24 | Fictional equipment for demonstration only*

<!-- page 14 -->

# 6 Troubleshooting

## 6.1 Using this chapter

When diagnosing unexpected conditions on the drive unit, begin by consulting the symptom index in Chapter 6. Match observed machine conditions with the listed trouble profiles to pinpoint the underlying cause. Operators and technicians must correlate signal alarms with the physical signatures of the unit, verifying whether vibration, temperature, or motor load match the diagnostic profile.

Before performing physical adjustments or component replacements, inspect instrument cabling and sensor mountings to rule out faulty sensor data. Technicians must complete the diagnostic checks in the check column before executing any corrective action. Whenever troubleshooting tasks require physical interaction, removing protective shields, or touching drive components, personnel must apply the energy control procedure in Chapter 8.

**Table 6-1 Symptom index**

| First symptom | Topic | Section | Page |
|---|---|---|---|
| `vibration_rms_mms` above 2.8 mm/s and accelerating, ripple at 1x pulley rotation | Drive bearing defect | 6.2 | 15 |
| One signal trending with no change in related signals | Instrument verification: suspected sensor drift | 6.3 | 16 |
| Cycle time stepped at a shift start, process normal | Control parameters: cycle timers and change control | 5 | 12 |
| Weld rejects rising | Reject rate high at ST60 | B.2 | 24 |

---
*AM-CD-01 Rev. A | Chain Conveyor Drive Unit | Page 14 of 24 | Fictional equipment for demonstration only*

<!-- page 15 -->

## 6.2 Drive bearing defect

**Typical signature.** Drive-end bearing vibration (`vibration_rms_mms`) rises out of its normal range of 0.8 to 2.8 mm/s, slowly at first and then faster. The one-second RMS trend carries a ripple at the pulley rotation frequency (about 0.255 Hz at 12 m/min, one turn every 3.9 s). Bearing temperature (`bearing_temp_c`) follows some minutes later; motor current rises slightly and chain speed sags. The 4.5 mm/s alarm comes before the 7.1 mm/s trip (S-ST50-VIB-HH). Stations upstream show rising cycle times because the slower conveyor blocks them. The bearing sounds rough, with a grinding or knocking that repeats with each pulley turn.

**Diagnostic notes**

- Vibration that grows in an accelerating curve, with a ripple at the pulley rotation frequency and a delayed rise in bearing temperature, indicates a drive-end bearing defect.
- In the high-rate vibration spectrum, a bearing defect shows peaks at the bearing defect frequencies and their harmonics; calculate them from the bearing geometry on the bearing data sheet.
- Rising cycle times at stations upstream of ST50 are a consequence of the conveyor slowing, not a fault at those stations.
- A bearing temperature rise without any vibration change is unlikely to be a bearing defect; verify the temperature sensor (see Section 6.3).

**Table 6-2 Troubleshooting: Drive bearing defect**

| Symptom | Probable cause | Check | Remedy |
|---|---|---|---|
| `vibration_rms_mms` above 2.8 mm/s and accelerating, ripple at 1x pulley rotation | Drive-end bearing defect (race or rolling element damage) | Spectrum of a high-rate snapshot; listen with a stethoscope; check the grease condition | Plan a bearing replacement; reduce speed only under change control; replace at the next stop |
| Vibration high, steady, started after chain or sprocket work | Shaft misalignment or loose bearing housing bolts | Check the housing bolt torque and the shaft alignment | Re-torque the bolts; realign the shaft |
| `bearing_temp_c` above 55 degC with normal vibration | Over-greasing or temperature sensor problem | Check the grease log; compare with a handheld thermometer | Purge excess grease; or see Section 6.3 |
| Motor current high and chain speed low | Chain binding, carrier jammed, or take-up too tight | Walk the chain path; check the take-up spring length | Clear the jam; reset the take-up to the recorded length |
| Speed low alarm A-ST50-SPD-LO | Chain speed below 11 m/min | Check motor current and the inverter fault log | Follow the row above that matches |

**Background.**

A drive bearing defect develops as subsurface fatigue or surface degradation on the rolling elements or raceways of the drive-end bearing. As surface spalling initiates, the rolling elements pass over the localized defect during shaft rotation. This impact generates dynamic forces that manifest as rising velocity root mean square on sensor ST50-CNV vibration_rms_mms, progressing upward from the normal range of 0.8 to 2.8 mm/s. Because the 0.25 m diameter drive pulley rotates at 0.255 Hz at the nominal 12 m/min chain speed, completing one full turn every 3.9 s, the vibration trend exhibits a periodic ripple at this 0.255 Hz rotational frequency. The bearing sounds rough, producing a grinding or knocking sound that repeats with every pulley turn.

As internal friction inside the damaged bearing increases, thermal energy builds up within the metal housing, causing ST50-CNV bearing_temp_c to climb several minutes after the initial vibration rise. The added mechanical drag forces the brake gearmotor to draw higher current on ST50-CNV motor_current_a and can cause conveyor speed ST50-CNV speed_mpm to sag. The 4.5 mm/s alarm is triggered first, followed by the 7.1 mm/s trip if mechanical degradation continues unchecked, while upstream stations register elevated cycle times due to conveyor retarding.

---
*AM-CD-01 Rev. A | Chain Conveyor Drive Unit | Page 15 of 24 | Fictional equipment for demonstration only*

<!-- page 16 -->

## 6.3 Instrument verification: suspected sensor drift

**Typical signature.** One monitored value trends slowly towards a limit, or jumps beyond it, while the signals that are physically linked to it stay normal.

**Table 6-3 Physical correlates of monitored signals**

| Signal | Physically related signals and checks |
|---|---|
| `bearing_temp_c` | Vibration RMS, motor current, handheld temperature at the housing |
| `vibration_rms_mms` | Bearing temperature (rises some minutes later in a real defect), motor current, sound of the bearing |
| `speed_mpm` | Motor current, cycle times of the stations |

**Diagnostic notes**

- A real process change moves more than one signal; a single tag that trends steadily while every physically related tag stays normal points to the instrument, not the process.
- Do not replace process components on the evidence of one drifting tag; verify the instrument first against a calibrated reference at the measuring point.
- A reading that jumps beyond a trip limit for one to three seconds and then returns, with no change in related tags before or after, is a measurement spike; reset, record it and keep the station running.
- Gaps in a trend, a value that stays exactly constant for a long period (stuck value) and the same alarm repeating several times within a minute (alarm chatter) are data-quality effects of the instrument or the network; they are not process faults and are not evidence of a failure.

---
*AM-CD-01 Rev. A | Chain Conveyor Drive Unit | Page 16 of 24 | Fictional equipment for demonstration only*

<!-- page 17 -->

**Table 6-4 Troubleshooting: suspected sensor drift**

| Symptom | Probable cause | Check | Remedy |
|---|---|---|---|
| One tag trends steadily towards a limit; all related tags in Table 6-3 stay normal | Transmitter drift (ageing, contamination, loose terminal, moisture in the connector) | Compare the reading with a calibrated handheld reference at the same point; inspect the connector and cable | Recalibrate or replace the transmitter; record the as-found and as-left values in the calibration log |
| Station stopped on a high-high or low-low trip after a one- to three-second excursion | Measurement spike (electrical noise, loose shield, vibration on the cable) | Check the trend either side of the trip; check related tags; inspect cable shield and gland | Reset and restart; if spikes repeat, re-terminate the shield and re-route the cable away from power cables |
| Value frozen at exactly the same number for a long period | Stuck value: lost update between the transmitter and the controller or historian | Check the transmitter display against the HMI; check the communication diagnostics | Restore communication; do not use the frozen period as process evidence |
| Same alarm raised and cleared several times within a minute | Alarm chatter: value hovering at the limit with too little deadband | Check the trend at the limit; check the alarm deadband setting | Treat as one event; request a deadband review through change control (see Chapter 5) |

---
*AM-CD-01 Rev. A | Chain Conveyor Drive Unit | Page 17 of 24 | Fictional equipment for demonstration only*

<!-- page 18 -->

# 7 Maintenance

## 7.1 Preventive maintenance

Executing preventive maintenance according to prescribed intervals preserves machine reliability and prevents unpredicted downtime on line L1. Because the line operates continuously 24 hours a day across three shifts, drive components experience steady mechanical and thermal stress. Adhering strictly to shift, weekly, monthly, and yearly service routines protects rolling bearings, the helical gearbox, and the chain assembly from accelerated wear.

Technicians must record every completed maintenance action immediately in the equipment logbook. The record must include the date, current shift, specific tasks performed, and observed running conditions. Accurate maintenance records provide the baseline data required by reliability engineers to track mechanical trends over time.

**Table 7-1 Preventive maintenance intervals**

| Task | Interval | See |
|---|---|---|
| Listen to the drive-end bearing and check for oil leaks | Every shift | Section 6.2 |
| Check chain tension at the take-up | Weekly | Section 6.2 |
| Grease the drive shaft bearings | Monthly | Section 6.2 |
| Take a high-rate vibration snapshot and review the spectrum | Monthly | Section 6.2 |
| Check gearbox oil level | Monthly | Section 6.2 |
| Replace gearbox oil | Yearly | Section 6.2 |
| Calibration check of the vibration and bearing temperature sensors | Yearly | Section 6.3 |

## 7.2 Recommended spare parts

**Table 7-2 Recommended spare parts**

| Part | Quantity to stock |
|---|---|
| Drive-end bearing and housing seals | 1 set |
| Chain links and pins | 10 |
| Take-up spring | 1 |
| Bearing grease | 2 cartridges |

---
*AM-CD-01 Rev. A | Chain Conveyor Drive Unit | Page 18 of 24 | Fictional equipment for demonstration only*

<!-- page 19 -->

# 8 Energy control procedure (lockout/tagout)

## 8.1 Scope, purpose and authorisation

> **IMPORTANT - FICTIONAL EQUIPMENT.** This manual describes fictional equipment created for the Andon Agent software demonstration (synthetic line L1). It is not a manufacturer's manual. Its energy control procedure is not a substitute for a site-specific energy control procedure prepared, approved and trained under 29 CFR 1910.147 or local regulation.

**Equipment.** Chain conveyor drive unit (inverter, brake gearmotor, drive sprocket and pulley, spring take-up). Applies to: ST50-CNV.

**Purpose.** This procedure controls hazardous energy when anyone works on the drive motor, the gearbox, the drive-end bearings, the chain, the take-up or the inverter, or reaches into the chain path.

**Authorisation.** Only authorised employees trained on this procedure may apply or remove locks and tags. Each authorised employee applies a personal lock and tag; a group lockout uses a lock box with one personal lock per employee.

**Basis.** This procedure follows the energy control procedure requirements of 29 CFR 1910.147(c)(4) and the sequence of 29 CFR 1910.147(d)(1) to (d)(6), with notification under (c)(9) and release from lockout or tagout under (e). Each step cites its paragraph. Steps are carried out in the order given.

## 8.2 Energy sources

**Table 8-1 Hazardous energy sources and isolating devices**

| Energy | Source and magnitude | Isolating device | Stored or residual energy |
|---|---|---|---|
| Electrical | 400 V AC three-phase supply to the drive inverter; 24 V DC control | Conveyor drive main disconnect switch | Inverter DC bus capacitors hold a charge after the disconnect is opened; wait for discharge |
| Gravity | Loaded carriers on inclined sections can pull the chain backwards when the brake is released | None (mechanical) | Fit the chain lock at the drive sprocket |
| Spring | Take-up spring holds the chain under tension | None (mechanical) | Back off the tensioner screw after the chain lock is fitted |
| Thermal | Drive-end bearing housing up to 75 degC before trip; gearbox oil | None | Allow to cool; heat-resistant gloves |

---
*AM-CD-01 Rev. A | Chain Conveyor Drive Unit | Page 19 of 24 | Fictional equipment for demonstration only*

<!-- page 20 -->

## 8.3 Preparation, shutdown, isolation and lockout

**Table 8-2 Preparation, shutdown, isolation and lockout**

| Step | Action | 29 CFR 1910.147 paragraph |
|---|---|---|
| 1 | Identify every energy source for the conveyor from Table 8-1 and collect one personal lock and tag for each isolating device. | (d)(1) |
| 2 | Notify the line lead and the operators at ST40, ST50 and ST60 that the conveyor will be shut down and locked out. | (c)(9) |
| 3 | Stop the conveyor with the conveyor stop push-button when no carrier is in a transfer, and wait until the chain has stopped. | (d)(2) |
| 4 | Switch the conveyor drive main disconnect switch to OFF. | (d)(3) |
| 5 | Fit a personal lock and tag to the conveyor drive main disconnect switch. | (d)(4) |

---
*AM-CD-01 Rev. A | Chain Conveyor Drive Unit | Page 20 of 24 | Fictional equipment for demonstration only*

<!-- page 21 -->

## 8.4 Stored energy and verification of isolation

**Table 8-3 Stored energy and verification of isolation**

| Step | Action | 29 CFR 1910.147 paragraph |
|---|---|---|
| 6 | Wait at least 5 minutes for the inverter DC bus to discharge before opening the drive cabinet. | (d)(5)(i) |
| 7 | Fit the chain lock at the drive sprocket so that loaded carriers cannot pull the chain backwards. | (d)(5)(i) |
| 8 | Before removing the chain or the drive shaft, record the take-up spring length and then back off the tensioner screw. | (d)(5)(i) |
| 9 | Let the drive-end bearing housing and the gearbox cool before touching them, and wear heat-resistant gloves. | (d)(5)(i) |
| 10 | Press the conveyor start push-button and the jog button to confirm that the chain does not move, then return both controls to off. | (d)(6) |
| 11 | Test for absence of voltage at the drive motor terminals with a tester proven on a known live source before and after the test. | (d)(6) |

---
*AM-CD-01 Rev. A | Chain Conveyor Drive Unit | Page 21 of 24 | Fictional equipment for demonstration only*

<!-- page 22 -->

## 8.5 Release from lockout/tagout

**Table 8-4 Release from lockout/tagout**

| Step | Action | 29 CFR 1910.147 paragraph |
|---|---|---|
| 12 | Restore the take-up spring to its recorded length and refit all guards. | (e)(1) |
| 13 | Remove tools, the chain lock and nonessential items from the drive and the chain path. | (e)(1) |
| 14 | Check that all employees are clear of the drive and the chain path. | (e)(2)(i) |
| 15 | Each employee removes only the lock and tag that the employee applied. | (e)(3) |
| 16 | Notify the affected employees that the locks and tags have been removed before the conveyor is restarted. | (e)(2)(ii) |

**Testing or positioning.** If the equipment must be energised temporarily to test or position it, follow 29 CFR 1910.147(f)(1): clear tools and materials, remove employees from the area, remove the locks and tags, energise and test, then de-energise and reapply every energy control measure in the order of this chapter before work continues.

---
*AM-CD-01 Rev. A | Chain Conveyor Drive Unit | Page 22 of 24 | Fictional equipment for demonstration only*

<!-- page 23 -->

# Appendix A Glossary

Drive inverter: An electronic control device that regulates motor supply frequency to hold the conveyor chain speed constant.

Brake gearmotor: An integrated drive package consisting of an electric motor, an internal spring-applied brake, and a helical reduction gearbox.

Drive shaft and bearings: A mechanical shaft supported by rolling bearings inside housings that transmits rotational power to the drive pulley and sprocket.

Drive sprocket and pulley: A rotating wheel assembly with a pulley diameter of 0.25 m that engages and propels the continuous chain.

Part carriers: Fabricated mechanical support fixtures connected to the continuous chain that hold and transport car body assemblies between stations.

Spring take-up: A mechanical tensioning assembly located at the return end that maintains constant chain tension through spring force.

Vibration sensor: An instrument mounted on the drive-end bearing housing that monitors velocity root mean square and captures high-rate snapshots for spectrum analysis.

Bearing temperature sensor: A thermal measurement probe attached to the drive-end bearing housing to record operating metal temperatures.

---
*AM-CD-01 Rev. A | Chain Conveyor Drive Unit | Page 23 of 24 | Fictional equipment for demonstration only*

<!-- page 24 -->

# Appendix B ST60 vision check: interface data

The ST60 vision check inspects every part at the end of the line and is carried by this conveyor. It finds defects made upstream; it does not cause them. Its limits are listed here so that conveyor and line problems can be told apart from inspection problems.

## B.1 Process values and limits

**Table B-1 Process values and limits: ST60-VIS (ST60 Vision check)**

| Tag | Description | Unit | Nominal | Normal range | Alarm low | Alarm high | Trip low | Trip high | Resolution |
|---|---|---|---|---|---|---|---|---|---|
| `reject_rate_pct` | Rejects in the last 100 inspected parts | % | 1 | 0 to 5 | - | 6 | - | - | 1 |
| `cycle_time_s` | Duration of the last completed inspection cycle | s | 46 | 43 to 52 | - | 56 | - | - | 0.1 |

**Table B-2 Alarm and stop messages**

| Code | Message | Condition or meaning |
|---|---|---|
| A-ST60-REJ-HI | ST60 Vision check: reject rate high | `reject_rate_pct` above 6 %; alarm: the station keeps running |
| A-ST60-CYC-HI | ST60 Vision check: cycle time high | `cycle_time_s` above 56 s; alarm: the station keeps running |

## B.2 Reject rate high at ST60

**Typical signature.** Reject rate (`reject_rate_pct`) is the share of rejects in the last 100 inspected parts; normal is 0 to 5 %. A rise above 6 % on consecutive checks causes a quality stop (S-ST60-QSTOP).

**Diagnostic notes**

- ST60 detects defects but does not cause them; trace each reject type to the station that makes that feature.
- Weld position or weld quality rejects point to ST20 or ST30; bead rejects point to ST40.

**Table B-3 Troubleshooting: Reject rate high at ST60**

| Symptom | Probable cause | Check | Remedy |
|---|---|---|---|
| Weld rejects rising | Weld process or part location at ST20/ST30 | Check tip resistance and clamp retries at ST20/ST30 | See the weld cell manual, Section 6 |
| Bead rejects rising | Sealer supply or nozzle at ST40 | Check sealer flow and pressure | See the sealer manual, Section 6 |
| Rejects rising with no defect visible on re-inspection | Camera dirty, lighting failed or camera communication retries (A-ST60-CAM-COMM) | Re-inspect rejected parts by hand; clean the lens | Clean the lens; replace the light |

---
*AM-CD-01 Rev. A | Chain Conveyor Drive Unit | Page 24 of 24 | Fictional equipment for demonstration only*
