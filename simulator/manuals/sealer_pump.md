<!-- page 1 -->

# Sealer Supply Pump and Dispense System - Operation and Maintenance Manual

**Document AM-SP-01 | Revision A | Issued 2026-10 | Line L1**

**Applies to:** ST40-SLR (ST40 Sealer)

> **IMPORTANT - FICTIONAL EQUIPMENT.** This manual describes fictional equipment created for the Andon Agent software demonstration (synthetic line L1). It is not a manufacturer's manual. Its energy control procedure is not a substitute for a site-specific energy control procedure prepared, approved and trained under 29 CFR 1910.147 or local regulation.

| Revision | Date | Change |
|---|---|---|
| A | 2026-10 | First issue |

**About this manual**

This manual AM-SP-01 provides instructions for operators, maintenance technicians, and reliability engineers working with the ST40-SLR sealer supply pump and dispense system. The document is divided into structured chapters covering safety, description, technical data, operation, control parameters, troubleshooting, maintenance, and energy control procedures. Appendix A provides a glossary of technical terms. The troubleshooting chapter is arranged directly by symptom to help personnel identify and resolve deviations efficiently.

---
*AM-SP-01 Rev. A | Sealer Supply Pump and Dispense System | Page 1 of 24 | Fictional equipment for demonstration only*

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
| 7 | Maintenance | 19 |
| 8 | Energy control procedure (lockout/tagout) | 20 |
| Appendix A | Glossary | 24 |

---
*AM-SP-01 Rev. A | Sealer Supply Pump and Dispense System | Page 2 of 24 | Fictional equipment for demonstration only*

<!-- page 3 -->

# 1 Safety

## 1.1 General safety

Only trained personnel may operate, inspect, or maintain the ST40-SLR equipment on line L1. Safe operation depends on strict adherence to all safety devices. Machine guards and interlocks protect against mechanical motion and pressurized material; personnel must never bypass or defeat them under any circumstances. Any damage to hoses, guards, electrical panels, or mechanical assemblies must be reported to supervision immediately. Whenever personnel must enter guarded areas to perform maintenance, inspections, or servicing, they must first apply the energy control procedure in Chapter 8. Fluid injection, mechanical crushing, stored pneumatic energy, and electrical hazards present severe risks if procedures are not followed.

## 1.2 Signal words

**Table 1-1 Signal words used in this manual**

| Signal word | Meaning |
|---|---|
| DANGER | A hazardous situation that will cause death or serious injury if not avoided |
| WARNING | A hazardous situation that could cause death or serious injury if not avoided |
| CAUTION | A hazardous situation that could cause minor or moderate injury if not avoided |
| NOTICE | A situation that could damage the equipment or the product |

---
*AM-SP-01 Rev. A | Sealer Supply Pump and Dispense System | Page 3 of 24 | Fictional equipment for demonstration only*

<!-- page 4 -->

## 1.3 Hazards and protective measures

**Table 1-2 Hazards**

| Hazard | Where | Protection |
|---|---|---|
| Fluid injection | Hoses, fittings, nozzle at full material pressure | Never touch a leak; relieve pressure before opening anything (Chapter 8) |
| Crushing | Drum ram and follower plate | Keep hands clear of the plate; lower the plate before reaching under it |
| Skin and eye contact with sealer | Nozzle, drum, waste container | Nitrile gloves and safety glasses |
| Electric shock | Pump drive and panel | Energy control procedure (Chapter 8) |
| Stored air pressure | Ram cylinder, nozzle valve | Vent through the ram air lockout valve (Chapter 8) |

## 1.4 Personal protective equipment

- Safety glasses with side shields
- Nitrile gloves
- Long sleeves
- Safety shoes

**WARNING** Before any maintenance, cleaning or adjustment inside a guarded area, apply the energy control procedure in Chapter 8.

---
*AM-SP-01 Rev. A | Sealer Supply Pump and Dispense System | Page 4 of 24 | Fictional equipment for demonstration only*

<!-- page 5 -->

# 2 Description

## 2.1 Overview

The ST40-SLR equipment supplies and dispenses high-viscosity body sealer onto car bodies on line L1. The station receives parts, applies a consistent sealing bead, and passes assemblies downstream to subsequent production areas such as ST60. Reliable operation of the sealer system is essential to prevent defective parts from reaching downstream stations. Line L1 operates 24 hours a day across three shifts, with a planned changeover at the start of each shift. Proper material delivery at ST40 ensures that joint seams are sealed correctly before downstream operations commence.

## 2.2 Main components

**Table 2-1 Main components**

| Component | Function |
|---|---|
| Drum unloader | Air-driven ram that pushes the follower plate down into the material drum |
| Follower plate | Plate with a wiper seal that keeps air out of the material and feeds the pump inlet |
| Piston pump | Double-acting reciprocating pump with an inlet (foot) check valve and a piston check valve |
| Pump drive | Electric gearmotor and crank driving the pump at a constant stroke rate |
| Inlet strainer | Protects the pump from skins and debris in the material |
| Material hoses | High-pressure hoses from the pump outlet to the dispense nozzle |
| Dispense nozzle | Air-operated valve and nozzle tip; lays the bead |
| Pressure and flow transmitters | Outlet pressure and volumetric flow to the controller |
| Bead inspection sensor | Measures the bead width on every part |
| Material relief valve | Releases material pressure to a waste container |

---
*AM-SP-01 Rev. A | Sealer Supply Pump and Dispense System | Page 5 of 24 | Fictional equipment for demonstration only*

<!-- page 6 -->

## 2.3 Principle of operation

The system dispenses high-viscosity body sealer from a drum unloader. An air-driven ram forces the follower plate down into the drum, keeping air away from the material via a wiper seal and feeding the inlet of the double-acting reciprocating piston pump. An electric gearmotor and crank drive the pump at a constant stroke rate of 0.15 Hz, which equals one stroke about every 6.7 s. Material enters through an inlet strainer and foot check valve into the pump cylinder, passing through the piston check valve on the return stroke. High-pressure material hoses convey the sealer to the dispense nozzle. An air-operated valve opens the nozzle tip to lay a bead onto each passing part, while a material relief valve safeguards against overpressurization by venting to a waste container.

Continuous instrumentation monitors process stability during every cycle. The transmitter pump_pressure_bar records pump outlet pressure, which nominally reads 120 bar within an operating band of 105 to 135 bar. The transmitter flow_rate_ccm monitors volumetric delivery, operating at a nominal 300 cc/min within a standard range of 270 to 330 cc/min. The electrical drive sensor motor_current_a measures motor draw, running at a nominal 8.5 A within a 7 to 10 A window. A bead inspection sensor evaluates the finished bead width on every part, maintaining a nominal 4 mm width within acceptable boundaries of 3.6 to 4.4 mm.

---
*AM-SP-01 Rev. A | Sealer Supply Pump and Dispense System | Page 6 of 24 | Fictional equipment for demonstration only*

<!-- page 7 -->

# 3 Technical data

## 3.1 Process values and limits

The normal range is the band the equipment stays in during normal production. An alarm limit raises a warning and the station keeps running; a trip limit stops the station. A dash means the limit is not used.

**Table 3-1 Process values and limits: ST40-SLR (ST40 Sealer)**

| Tag | Description | Unit | Nominal | Normal range | Alarm low | Alarm high | Trip low | Trip high | Resolution |
|---|---|---|---|---|---|---|---|---|---|
| `pump_pressure_bar` | Sealer pump outlet pressure | bar | 120 | 105 to 135 | 100 | 145 | - | - | 0.1 |
| `flow_rate_ccm` | Sealer volumetric flow | cc/min | 300 | 270 to 330 | 255 | - | 230 | - | 1 |
| `motor_current_a` | Pump drive motor current | A | 8.5 | 7 to 10 | - | 11 | - | - | 0.01 |
| `bead_width_mm` | Bead width measured on the last part | mm | 4 | 3.6 to 4.4 | 3.4 | 4.6 | - | - | 0.01 |

---
*AM-SP-01 Rev. A | Sealer Supply Pump and Dispense System | Page 7 of 24 | Fictional equipment for demonstration only*

<!-- page 8 -->

## 3.2 Operating parameters

**Table 3-2 Operating parameters**

| Parameter | Value | Note |
|---|---|---|
| Pump stroke rate | 0.15 Hz | One stroke about every 6.7 s |
| Outlet pressure, nominal | 120 bar | At normal flow |
| Flow, nominal | 300 cc/min | Volumetric |
| Bead width, nominal | 4 mm | Measured on every part |
| Drive motor current, nominal | 8.5 A | At normal flow |

---
*AM-SP-01 Rev. A | Sealer Supply Pump and Dispense System | Page 8 of 24 | Fictional equipment for demonstration only*

<!-- page 9 -->

## 3.3 Alarm and stop messages

**Table 3-3 Alarm and stop messages**

| Code | Message | Condition or meaning |
|---|---|---|
| A-ST40-PRS-LO | ST40 Sealer: pump pressure low | `pump_pressure_bar` below 100 bar; alarm: the station keeps running |
| A-ST40-PRS-HI | ST40 Sealer: pump pressure high | `pump_pressure_bar` above 145 bar; alarm: the station keeps running |
| A-ST40-FLW-LO | ST40 Sealer: sealer flow low | `flow_rate_ccm` below 255 cc/min; alarm: the station keeps running |
| A-ST40-FLW-LL | ST40 Sealer: sealer flow low-low | `flow_rate_ccm` below 230 cc/min; trip: the station stops |
| A-ST40-CUR-HI | ST40 Sealer: motor current high | `motor_current_a` above 11 A; alarm: the station keeps running |
| A-ST40-BEAD-LO | ST40 Sealer: bead width low | `bead_width_mm` below 3.4 mm; alarm: the station keeps running |
| A-ST40-BEAD-HI | ST40 Sealer: bead width high | `bead_width_mm` above 4.6 mm; alarm: the station keeps running |
| A-ST40-BEAD-QA | bead inspection: bead width out of tolerance | Bead narrow, wide or broken; see Section 6.2 and Section 6.3 |
| A-ST40-NOZ-PRG | nozzle purge requested | Information; routine purge |
| A-ST40-STARVED | ST40 Sealer: station starved (waiting for part) | Consequence of a slow or stopped station upstream; not a fault at this station |
| A-ST40-BLOCKED | ST40 Sealer: station blocked (outfeed full) | Consequence of a slow or stopped station downstream; not a fault at this station |
| A-L1-ANDON | Line L1 stopped: andon raised | Information; follows any station stop |

---
*AM-SP-01 Rev. A | Sealer Supply Pump and Dispense System | Page 9 of 24 | Fictional equipment for demonstration only*

<!-- page 10 -->

# 4 Operation

## 4.1 Start-up

At the start of each shift, personnel conduct visual pre-start checks before operating the ST40-SLR. Verify that all guards are intact, drum levels are adequate, and no leaks appear on material hoses or fittings. Inspect the nozzle tip and follower plate wiper seal for buildup. Initiate the start sequence through the station controls. As the electric drive begins cycling the piston pump at 0.15 Hz, verify that process signals stabilize within normal limits. Outlet pressure should rise toward its nominal 120 bar within the 105 to 135 bar range. Volumetric flow must reach approximately 300 cc/min, motor current should stabilize around 8.5 A, and the bead inspection sensor should confirm an initial bead width close to 4 mm.

## 4.2 Normal operation

During continuous production, the operator oversees equipment signals and dispenses on line L1. Monitor ST40-SLR pump_pressure_bar to ensure pressure remains between 105 and 135 bar, avoiding the alarm low limit of 100 bar and alarm high limit of 145 bar. Ensure flow_rate_ccm remains between 270 and 330 cc/min; values dropping toward the alarm low of 255 cc/min or trip low of 230 cc/min require immediate intervention. Keep drive motor current within 7 to 10 A, below the alarm high of 11 A. Confirm bead width stays between 3.6 and 4.4 mm on every part. Report abnormal knocking sounds, pulses at 0.15 Hz, or warnings such as A-ST40-BEAD-QA to maintenance without delay.

---
*AM-SP-01 Rev. A | Sealer Supply Pump and Dispense System | Page 10 of 24 | Fictional equipment for demonstration only*

<!-- page 11 -->

## 4.3 Normal production stop

To stop production, initiate an orderly production stop through the line control panel. The air-operated dispense nozzle valve closes, and the electric drive stops the piston pump. A normal production stop de-energizes operational run signals but leaves electrical power, pneumatic ram force, and high hydraulic material pressure stored within the system. This state is not an energy-isolated state. Whenever personnel perform maintenance, cleaning, or internal inspections, they must apply the energy control procedure in Chapter 8.

---
*AM-SP-01 Rev. A | Sealer Supply Pump and Dispense System | Page 11 of 24 | Fictional equipment for demonstration only*

<!-- page 12 -->

# 5 Control parameters: cycle timers and change control

## 5.1 Control parameters

The ST40-SLR system relies on defined control parameters to regulate material delivery, cycle timers, and dispense volume on line L1. Adjustable parameters control pump operation, valve actuation timing, and sensor evaluation thresholds. Uncontrolled alterations to these values present severe risks to production quality and station throughput. Incorrect settings cause pressure fluctuations, irregular flow rates, and out-of-specification bead dimensions that trigger line stoppages. Therefore, all modifications to control parameters and timers must follow formal change control procedures. Only authorized personnel may update parameters, ensuring every change is documented, reviewed, and validated against baseline operating requirements.

**Table 5-1 Adjustable control parameters**

| Parameter | Function | May be changed by |
|---|---|---|
| Bead program (per product model) | Nozzle open and close points along the part | Process engineer |
| Nozzle purge interval | Time without dispensing before an automatic purge | Maintenance with change request |
| Dispense start delay | Delay between nozzle open command and part motion | Maintenance with change request |

---
*AM-SP-01 Rev. A | Sealer Supply Pump and Dispense System | Page 12 of 24 | Fictional equipment for demonstration only*

<!-- page 13 -->

## 5.2 Change control and diagnosis

**Diagnostic notes**

- Parameter changes are made only under an approved change request and are recorded in the parameter log with the old value, the new value, the author and the time.
- Parameter changes are normally loaded at a shift start, during the changeover.
- A cycle time that steps up at a shift start and then stays constant, while every process signal of the station stays normal, points to a changed timer or recipe parameter, not to wear or a failing component.
- Compare the active parameter set with the last approved copy before replacing any hardware.

Shifts start at 06:00, 14:00, 22:00 with a 15 min planned changeover.

**Table 5-2 Troubleshooting: control parameters**

| Symptom | Probable cause | Check | Remedy |
|---|---|---|---|
| ST40 cycle time stepped up at a shift start and stays at the new level; process signals normal | Timer or dwell parameter changed at the changeover (wrong value, wrong recipe, or a trial value left active) | Compare the active parameter set with the last approved copy; check the parameter log for the shift start | Restore the approved value under change control; record the deviation |
| Stations downstream starved and stations upstream blocked after a shift start | A slower cycle at one station propagating along the line | Find the first station whose cycle time changed; downstream starvation and upstream blocking are consequences | Correct the parameter at the first station only |
| Cycle time slightly longer for the first parts after every changeover | Normal ramp-up after a changeover | Confirm that cycle time returns to the normal range within a few cycles | No action |

---
*AM-SP-01 Rev. A | Sealer Supply Pump and Dispense System | Page 13 of 24 | Fictional equipment for demonstration only*

<!-- page 14 -->

# 6 Troubleshooting

## 6.1 Using this chapter

When troubleshooting the ST40-SLR station, begin by referencing the symptom index in Chapter 6. Locate the matching symptom and compare current line observations with the described signature. Check operating variables, including pump pressure, volumetric flow, motor current, and bead width, to confirm the condition. Verify transmitter integrity to rule out instrument and sensor faults before assuming mechanical failure. Follow the diagnostic checks in the designated sequence before attempting any corrective remedy. Prior to executing hands-on adjustments, repairs, or component replacements on pressurized or powered equipment, always apply the energy control procedure in Chapter 8.

**Table 6-1 Symptom index**

| First symptom | Topic | Section | Page |
|---|---|---|---|
| Pressure pulsing at the stroke rate, flow low | Pump cavitation / starved inlet | 6.2 | 15 |
| Bead narrow, flow and pressure normal | Bead width out of tolerance | 6.3 | 16 |
| One signal trending with no change in related signals | Instrument verification: suspected sensor drift | 6.4 | 17 |
| Cycle time stepped at a shift start, process normal | Control parameters: cycle timers and change control | 5 | 12 |

---
*AM-SP-01 Rev. A | Sealer Supply Pump and Dispense System | Page 14 of 24 | Fictional equipment for demonstration only*

<!-- page 15 -->

## 6.2 Pump cavitation / starved inlet

**Typical signature.** Outlet pressure (`pump_pressure_bar`) starts to pulse at the pump stroke rate (0.15 Hz, one stroke about every 6.7 s) and its mean falls. Flow (`flow_rate_ccm`) drops below its normal range of 270 to 330 cc/min. Motor current falls slightly and becomes unsteady because the pump moves less material. The bead becomes narrow and uneven (A-ST40-BEAD-QA) and ST60 rejects rise. The pump sounds rough, with a knock on each stroke.

**Diagnostic notes**

- Pressure pulsing at the stroke rate together with falling flow means the pump is not filling on each stroke: a starved inlet or cavitation, not a blocked nozzle.
- A blocked nozzle raises outlet pressure and lowers flow; a starved inlet lowers both pressure and flow.
- Check the drum level and the follower plate seal before opening the pump.

**Table 6-2 Troubleshooting: Pump cavitation / starved inlet**

| Symptom | Probable cause | Check | Remedy |
|---|---|---|---|
| Pressure pulsing at the stroke rate, flow low | Drum empty, or follower plate not following the material | Check the drum level indicator and the follower plate position | Change the drum and bleed air from under the follower plate |
| Pulsing continues after a drum change | Air drawn in past a worn follower plate wiper seal | Inspect the wiper seal; look for air pockets at the bleed port | Replace the wiper seal; bleed the pump |
| Flow low and pulsing worst at shift start | Material too viscous (cold drum) | Check the material temperature against the material data sheet | Condition drums in the warm store before use |
| Flow low, pulsing, drum and seal good | Inlet strainer clogged | Check the strainer differential; inspect the basket | Clean the strainer under energy control (Chapter 8) |
| Pressure drop on one stroke direction only | Worn foot check valve or piston packing | Watch the pressure trace stroke by stroke | Repack the pump or replace the check valve (see Table 7-1) |

**Background.**

Pump cavitation or starved inlet conditions occur when the double-acting piston pump cannot fill completely during an intake stroke. High-viscosity sealer fails to flow through the follower plate and inlet strainer at a rate matching piston displacement. This creates a partial void inside the pumping chamber. When the piston reverses direction, the trapped void collapses violently under mechanical compression, creating an audible mechanical knock on each stroke.

Because the pump displaces less dense material per cycle, mean delivery falls and the transmitter pump_pressure_bar begins to pulse cyclically at the fixed pump stroke rate of 0.15 Hz, which corresponds to one stroke about every 6.7 s. Volumetric delivery drops below the normal 270 to 330 cc/min range. The electric gearmotor experiences reduced mechanical resistance, causing motor_current_a to fall slightly and fluctuate. Insufficient volume at the dispense nozzle causes the applied bead width to shrink, triggering alarm A-ST40-BEAD-QA and raising downstream part reject counts at ST60.

---
*AM-SP-01 Rev. A | Sealer Supply Pump and Dispense System | Page 15 of 24 | Fictional equipment for demonstration only*

<!-- page 16 -->

## 6.3 Bead width out of tolerance

**Typical signature.** Bead width (`bead_width_mm`) normally stays within 3.6 to 4.4 mm. The 3.4 mm and 4.6 mm limits raise A-ST40-BEAD-QA.

**Diagnostic notes**

- A narrow bead with normal flow and pressure points to the nozzle or the bead program; a narrow bead with low flow points to the pump supply (see Section 6.2).

**Table 6-3 Troubleshooting: Bead width out of tolerance**

| Symptom | Probable cause | Check | Remedy |
|---|---|---|---|
| Bead narrow, flow and pressure normal | Nozzle tip partly blocked with cured material | Inspect the nozzle tip | Clean or replace the nozzle tip |
| Bead wide or doubled at the start of a part | Dispense start delay wrong | Compare the active parameter with the approved copy | Restore under change control (see Chapter 5) |
| Pressure high, flow low, no pulsing | Hose or nozzle partly blocked | Purge the nozzle; check the pressure drop along the hose | Clean the nozzle; replace the hose if blocked |

---
*AM-SP-01 Rev. A | Sealer Supply Pump and Dispense System | Page 16 of 24 | Fictional equipment for demonstration only*

<!-- page 17 -->

## 6.4 Instrument verification: suspected sensor drift

**Typical signature.** One monitored value trends slowly towards a limit, or jumps beyond it, while the signals that are physically linked to it stay normal.

**Table 6-4 Physical correlates of monitored signals**

| Signal | Physically related signals and checks |
|---|---|
| `pump_pressure_bar` | Flow rate, drive motor current, bead width; a real pressure change moves at least one of them |
| `flow_rate_ccm` | Bead width, pump pressure, drum level |
| `bead_width_mm` | Flow rate, nozzle condition |

**Diagnostic notes**

- A real process change moves more than one signal; a single tag that trends steadily while every physically related tag stays normal points to the instrument, not the process.
- Do not replace process components on the evidence of one drifting tag; verify the instrument first against a calibrated reference at the measuring point.
- A reading that jumps beyond a trip limit for one to three seconds and then returns, with no change in related tags before or after, is a measurement spike; reset, record it and keep the station running.
- Gaps in a trend, a value that stays exactly constant for a long period (stuck value) and the same alarm repeating several times within a minute (alarm chatter) are data-quality effects of the instrument or the network; they are not process faults and are not evidence of a failure.

---
*AM-SP-01 Rev. A | Sealer Supply Pump and Dispense System | Page 17 of 24 | Fictional equipment for demonstration only*

<!-- page 18 -->

**Table 6-5 Troubleshooting: suspected sensor drift**

| Symptom | Probable cause | Check | Remedy |
|---|---|---|---|
| One tag trends steadily towards a limit; all related tags in Table 6-4 stay normal | Transmitter drift (ageing, contamination, loose terminal, moisture in the connector) | Compare the reading with a calibrated handheld reference at the same point; inspect the connector and cable | Recalibrate or replace the transmitter; record the as-found and as-left values in the calibration log |
| Station stopped on a high-high or low-low trip after a one- to three-second excursion | Measurement spike (electrical noise, loose shield, vibration on the cable) | Check the trend either side of the trip; check related tags; inspect cable shield and gland | Reset and restart; if spikes repeat, re-terminate the shield and re-route the cable away from power cables |
| Value frozen at exactly the same number for a long period | Stuck value: lost update between the transmitter and the controller or historian | Check the transmitter display against the HMI; check the communication diagnostics | Restore communication; do not use the frozen period as process evidence |
| Same alarm raised and cleared several times within a minute | Alarm chatter: value hovering at the limit with too little deadband | Check the trend at the limit; check the alarm deadband setting | Treat as one event; request a deadband review through change control (see Chapter 5) |

---
*AM-SP-01 Rev. A | Sealer Supply Pump and Dispense System | Page 18 of 24 | Fictional equipment for demonstration only*

<!-- page 19 -->

# 7 Maintenance

## 7.1 Preventive maintenance

Adhering to preventive maintenance intervals is vital for the operational reliability of the ST40-SLR station. Line L1 operates continuously across three shifts, making regular component care necessary to avoid unexpected downtime and defective car bodies. Prescribed tasks preserve seal integrity, prevent fluid delivery restrictions, and maintain sensor accuracy across millions of dispense cycles. Maintenance technicians must log every completed task, recording inspection findings, component replacements, and service dates in the maintenance management system to maintain full traceability.

**Table 7-1 Preventive maintenance intervals**

| Task | Interval | See |
|---|---|---|
| Purge and wipe the nozzle tip | Every shift | Section 6.3 |
| Check the drum level and change drums | As needed | Section 6.2 |
| Inspect the follower plate wiper seal | Weekly | Section 6.2 |
| Clean the inlet strainer | Weekly | Section 6.2 |
| Inspect material hoses for wear and bulges | Monthly | Section 6.3 |
| Repack the pump and inspect the check valves | Every 6 months | Section 6.2 |
| Calibration check of pressure and flow transmitters | Yearly | Section 6.4 |

## 7.2 Recommended spare parts

**Table 7-2 Recommended spare parts**

| Part | Quantity to stock |
|---|---|
| Follower plate wiper seal | 2 |
| Pump packing kit | 1 |
| Foot check valve | 1 |
| Nozzle tips | 5 |
| Strainer basket | 1 |

---
*AM-SP-01 Rev. A | Sealer Supply Pump and Dispense System | Page 19 of 24 | Fictional equipment for demonstration only*

<!-- page 20 -->

# 8 Energy control procedure (lockout/tagout)

## 8.1 Scope, purpose and authorisation

> **IMPORTANT - FICTIONAL EQUIPMENT.** This manual describes fictional equipment created for the Andon Agent software demonstration (synthetic line L1). It is not a manufacturer's manual. Its energy control procedure is not a substitute for a site-specific energy control procedure prepared, approved and trained under 29 CFR 1910.147 or local regulation.

**Equipment.** Reciprocating sealer pump with drum follower plate, material hoses and dispense nozzle. Applies to: ST40-SLR.

**Purpose.** This procedure controls hazardous energy when anyone changes or cleans the nozzle, opens a material hose or fitting, works on the pump, the follower plate or the drum ram, or reaches into the dispense area.

**Authorisation.** Only authorised employees trained on this procedure may apply or remove locks and tags. Each authorised employee applies a personal lock and tag; a group lockout uses a lock box with one personal lock per employee.

**Basis.** This procedure follows the energy control procedure requirements of 29 CFR 1910.147(c)(4) and the sequence of 29 CFR 1910.147(d)(1) to (d)(6), with notification under (c)(9) and release from lockout or tagout under (e). Each step cites its paragraph. Steps are carried out in the order given.

## 8.2 Energy sources

**Table 8-1 Hazardous energy sources and isolating devices**

| Energy | Source and magnitude | Isolating device | Stored or residual energy |
|---|---|---|---|
| Electrical | 400 V AC three-phase supply to the pump drive motor; 24 V DC control | Sealer pump main disconnect switch | None after isolation |
| Material pressure | Sealer at up to 145 bar in the pump, hoses and nozzle (injection hazard) | Pump stopped and isolated | Pressure stays trapped in hoses after the pump stops; relieve through the relief valve |
| Pneumatic | Plant air to the drum ram and the nozzle valve | Ram air lockout valve (exhausting type) | Air trapped in the ram cylinder; vented by the lockout valve |
| Gravity | Raised drum ram and follower plate | None (mechanical) | Lower the plate onto the drum or rest the ram on its mechanical stop |

---
*AM-SP-01 Rev. A | Sealer Supply Pump and Dispense System | Page 20 of 24 | Fictional equipment for demonstration only*

<!-- page 21 -->

## 8.3 Preparation, shutdown, isolation and lockout

**Table 8-2 Preparation, shutdown, isolation and lockout**

| Step | Action | 29 CFR 1910.147 paragraph |
|---|---|---|
| 1 | Identify every energy source for the sealer from Table 8-1 and collect one personal lock and tag for each isolating device. | (d)(1) |
| 2 | Notify the line lead and the ST40 operator that the sealer pump will be shut down and locked out. | (c)(9) |
| 3 | Finish the current bead, then stop the pump with the pump stop push-button on the sealer panel. | (d)(2) |
| 4 | Lower the follower plate onto the drum or rest the ram on its mechanical stop before the ram air is shut off. | (d)(2) |
| 5 | Switch the sealer pump main disconnect switch to OFF. | (d)(3) |
| 6 | Close the ram air lockout valve so that its exhaust port vents the ram and nozzle air circuit. | (d)(3) |
| 7 | Fit a personal lock and tag to the sealer pump main disconnect switch and to the ram air lockout valve. | (d)(4) |

---
*AM-SP-01 Rev. A | Sealer Supply Pump and Dispense System | Page 21 of 24 | Fictional equipment for demonstration only*

<!-- page 22 -->

## 8.4 Stored energy and verification of isolation

**Table 8-3 Stored energy and verification of isolation**

| Step | Action | 29 CFR 1910.147 paragraph |
|---|---|---|
| 8 | Point the nozzle into a waste container and open the material relief valve until the material pressure gauge reads zero. | (d)(5)(i) |
| 9 | Keep every material hose and fitting closed until the material pressure gauge reads zero. | (d)(5)(i) |
| 10 | Check the material pressure gauge again before each new task and reopen the relief valve if it reads above zero. | (d)(5)(ii) |
| 11 | Press the pump start push-button and the nozzle purge button to confirm that nothing starts, moves or dispenses, then return both controls to off. | (d)(6) |
| 12 | Test for absence of voltage at the pump motor terminals with a tester proven on a known live source before and after the test. | (d)(6) |

---
*AM-SP-01 Rev. A | Sealer Supply Pump and Dispense System | Page 22 of 24 | Fictional equipment for demonstration only*

<!-- page 23 -->

## 8.5 Release from lockout/tagout

**Table 8-4 Release from lockout/tagout**

| Step | Action | 29 CFR 1910.147 paragraph |
|---|---|---|
| 13 | Remove tools, waste containers and nonessential items, and confirm that every hose, fitting and the nozzle are tight and intact. | (e)(1) |
| 14 | Close the material relief valve. | (e)(1) |
| 15 | Check that all employees are clear of the pump, the drum ram and the dispense area. | (e)(2)(i) |
| 16 | Each employee removes only the lock and tag that the employee applied. | (e)(3) |
| 17 | Notify the affected employees that the locks and tags have been removed before the sealer pump is restarted. | (e)(2)(ii) |

**Testing or positioning.** If the equipment must be energised temporarily to test or position it, follow 29 CFR 1910.147(f)(1): clear tools and materials, remove employees from the area, remove the locks and tags, energise and test, then de-energise and reapply every energy control measure in the order of this chapter before work continues.

---
*AM-SP-01 Rev. A | Sealer Supply Pump and Dispense System | Page 23 of 24 | Fictional equipment for demonstration only*

<!-- page 24 -->

# Appendix A Glossary

Drum unloader: An air-driven ram assembly that pushes the follower plate down into the material drum to feed high-viscosity sealer.

Follower plate: A plate fitted with an elastomeric wiper seal that prevents air from contacting the sealer drum and channels material into the pump inlet.

Piston pump: A double-acting reciprocating displacement pump equipped with an inlet foot check valve and a piston check valve to pressurize sealer.

Inlet strainer: A mechanical filter screen positioned upstream of the pump to capture skins and particulate debris from the material supply.

Material hoses: High-pressure flexible lines that transfer pressurized sealer from the pump outlet to the dispense nozzle.

Dispense nozzle: An air-operated valve assembly and nozzle tip that applies the sealer bead onto parts.

Bead inspection sensor: An automated quality sensor that measures the bead width on every car body part processed at the station.

Material relief valve: A safety valve that opens to release excessive material pressure directly to an external waste container.

---
*AM-SP-01 Rev. A | Sealer Supply Pump and Dispense System | Page 24 of 24 | Fictional equipment for demonstration only*
