<!-- page 1 -->

# Plant Air System and Utilities - Operation and Maintenance Manual

**Document AM-CA-01 | Revision A | Issued 2026-10 | Line L1**

**Applies to:** UT-AIR (Plant air compressor and header)

> **IMPORTANT - FICTIONAL EQUIPMENT.** This manual describes fictional equipment created for the Andon Agent software demonstration (synthetic line L1). It is not a manufacturer's manual. Its energy control procedure is not a substitute for a site-specific energy control procedure prepared, approved and trained under 29 CFR 1910.147 or local regulation.

| Revision | Date | Change |
|---|---|---|
| A | 2026-10 | First issue |

**About this manual**

This manual serves operators, maintenance technicians, and reliability engineers responsible for plant air system UT-AIR and the associated process chiller. Plant personnel use this document to support reliable service across all production shifts.

The content is structured by chapters to facilitate fast technical reference. Chapter 1 introduces safety, while Chapter 2 and Chapter 3 present system descriptions and technical data. Chapter 4 outlines operation, and Chapter 5 details control parameters, cycle timers, and formal change control. Chapter 6 contains troubleshooting, which is organised entirely by symptom. Chapter 7 covers preventative maintenance tasks, and Chapter 8 provides the energy control procedure. Supplementary information appears in Appendix A for terms and Appendix B for the process chiller.

---
*AM-CA-01 Rev. A | Plant Air System and Utilities | Page 1 of 25 | Fictional equipment for demonstration only*

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
| Appendix B | Process chiller | 25 |

---
*AM-CA-01 Rev. A | Plant Air System and Utilities | Page 2 of 25 | Fictional equipment for demonstration only*

<!-- page 3 -->

# 1 Safety

## 1.1 General safety

Safe operation of the plant air system requires strict adherence to established operating standards. Only trained personnel may operate, inspect, or adjust the compressor, air distribution network, and related equipment. Safety guards, access covers, and mechanical interlocks are installed to prevent direct contact with rotating machinery, hot surfaces, and electrical elements. These protective devices must remain functional and must never be bypassed, altered, or defeated.

Any damage to air lines, electrical enclosures, or pressure components must be reported immediately to maintenance personnel. Hazards present on this equipment include stored air pressure inside the receiver, header, and drop legs, automatic compressor restarting, hot oil and surfaces at the oil separator and discharge pipework, compressor room noise, compressed air blast from open couplings, and electric shock from the motor or panel. Performing any maintenance inside guarded areas requires that personnel apply the energy control procedure in Chapter 8.

## 1.2 Signal words

**Table 1-1 Signal words used in this manual**

| Signal word | Meaning |
|---|---|
| DANGER | A hazardous situation that will cause death or serious injury if not avoided |
| WARNING | A hazardous situation that could cause death or serious injury if not avoided |
| CAUTION | A hazardous situation that could cause minor or moderate injury if not avoided |
| NOTICE | A situation that could damage the equipment or the product |

---
*AM-CA-01 Rev. A | Plant Air System and Utilities | Page 3 of 25 | Fictional equipment for demonstration only*

<!-- page 4 -->

## 1.3 Hazards and protective measures

**Table 1-2 Hazards**

| Hazard | Where | Protection |
|---|---|---|
| Stored air pressure | Receiver, header, drop legs | Isolate and bleed to zero (Chapter 8) |
| Automatic restart | Compressor | The compressor can start at any time when header pressure falls; lock out before work (Chapter 8) |
| Hot oil and surfaces | Oil separator, discharge pipework, cooler | Heat-resistant gloves; let parts cool |
| Noise | Compressor room | Hearing protection |
| Compressed air blast | Open couplings, blow guns | Never point air at a person; safety glasses |
| Electric shock | Motor and panel | Energy control procedure (Chapter 8) |

## 1.4 Personal protective equipment

- Safety glasses
- Hearing protection in the compressor room
- Heat-resistant gloves
- Safety shoes

**WARNING** Before any maintenance, cleaning or adjustment inside a guarded area, apply the energy control procedure in Chapter 8.

---
*AM-CA-01 Rev. A | Plant Air System and Utilities | Page 4 of 25 | Fictional equipment for demonstration only*

<!-- page 5 -->

# 2 Description

## 2.1 Overview

The plant air system, designated UT-AIR, provides clean compressed air to support line L1 during car body-in-white production. Line L1 runs 24 hours a day in three shifts, starting each shift with a planned changeover. Constant pneumatic energy is essential to maintain automated welding and clamping operations across the facility.

System equipment includes an oil-injected rotary screw compressor, an air receiver, a refrigerated dryer, and a main distribution header. The main header supplies air directly through dedicated drop legs to weld cell ST20 and weld cell ST30. Each drop leg incorporates a ball valve, filter-regulator, and quick couplings to feed the downstream tooling. In addition, Appendix B details the process chiller that circulates cooling water to cool the weld cells during ongoing assembly cycles.

## 2.2 Main components

**Table 2-1 Main components**

| Component | Function |
|---|---|
| Screw compressor | Oil-injected rotary screw air end driven by an electric motor |
| Inlet valve and load/unload control | Loads the compressor when header pressure falls to the cut-in pressure (6.2 bar) and unloads it at the cut-out pressure (7.3 bar) |
| Oil separator and cooler | Separates oil from the compressed air and cools the oil |
| Air receiver | Stores compressed air and evens out demand |
| Refrigerated dryer | Removes moisture |
| Condensate drains | Timed drains on the receiver and dryer |
| Main header and drop legs | Distribute air to the weld cells; each drop leg has a ball valve, filter-regulator and quick couplings |
| Sensors | Header pressure, compressor motor current, compressor oil temperature |

---
*AM-CA-01 Rev. A | Plant Air System and Utilities | Page 5 of 25 | Fictional equipment for demonstration only*

<!-- page 6 -->

## 2.3 Principle of operation

The rotary screw air end is driven by an electric motor, compressing ambient air using injected oil for lubrication, sealing, and cooling. The compressed air and oil mixture flows into the oil separator, which extracts the oil and sends it through a cooler before returning it to the air end. The compressed air exits the separator and enters the air receiver, which stores energy and stabilizes header flow. Air then passes through the refrigerated dryer to remove moisture before entering the main header. Timed condensate drains on the receiver and dryer automatically expel collected liquid. The main header conveys dry air to drop legs at ST20 and ST30, where filter-regulators establish the 5.6 bar supply pressure needed by the weld cells.

Operation relies on inlet valve load and unload control driven by the UT-AIR header_pressure_bar sensor. When line demand pulls header pressure down to the cut-in pressure of 6.2 bar, the inlet valve opens, loading the compressor. The compressor delivers air until header pressure rises to the cut-out pressure of 7.3 bar, at which point the inlet valve closes to unload the unit. Under normal demand, this load and unload cycle recurs roughly every 2 minutes. The signal header_pressure_bar oscillates within a normal band of 6 to 7.5 bar. Compressor motor current, measured by compressor_current_a, switches between about 92 A when loaded and about 38 A when unloaded, remaining within a 30 to 100 A range. Oil temperature, monitored by oil_temp_c, operates between 60 and 85 degC. The process chiller supply temperature, supply_temp_c, cycles between 10 and 14 degC.

---
*AM-CA-01 Rev. A | Plant Air System and Utilities | Page 6 of 25 | Fictional equipment for demonstration only*

<!-- page 7 -->

# 3 Technical data

## 3.1 Process values and limits

The normal range is the band the equipment stays in during normal production. An alarm limit raises a warning and the station keeps running; a trip limit stops the station. A dash means the limit is not used.

**Table 3-1 Process values and limits: UT-AIR (Plant air compressor and header)**

| Tag | Description | Unit | Nominal | Normal range | Alarm low | Alarm high | Trip low | Trip high | Resolution |
|---|---|---|---|---|---|---|---|---|---|
| `header_pressure_bar` | Main air header pressure (load/unload band) | bar | 6.75 | 6 to 7.5 | 5.6 | - | - | - | 0.01 |
| `compressor_current_a` | Compressor motor current (loaded ~92 A, unloaded ~38 A) | A | 60 | 30 to 100 | - | 110 | - | - | 0.1 |
| `oil_temp_c` | Compressor oil temperature | degC | 72 | 60 to 85 | - | 95 | - | - | 0.1 |

---
*AM-CA-01 Rev. A | Plant Air System and Utilities | Page 7 of 25 | Fictional equipment for demonstration only*

<!-- page 8 -->

## 3.2 Operating parameters

**Table 3-2 Operating parameters**

| Parameter | Value | Note |
|---|---|---|
| Cut-in (load) pressure | 6.2 bar | Compressor loads at or below this header pressure |
| Cut-out (unload) pressure | 7.3 bar | Compressor unloads at this header pressure |
| Weld cell regulator setting | 5.6 bar | At each drop leg (ST20, ST30) |
| Motor current, loaded | about 92 A | Compressor delivering air |
| Motor current, unloaded | about 38 A | Running, inlet closed |
| Load/unload cycle at normal demand | about 2 min | Varies with demand |
| Leak repair acceptance | Header holds pressure for 15 min | With the weld cells stopped |

---
*AM-CA-01 Rev. A | Plant Air System and Utilities | Page 8 of 25 | Fictional equipment for demonstration only*

<!-- page 9 -->

## 3.3 Alarm and stop messages

**Table 3-3 Alarm and stop messages**

| Code | Message | Condition or meaning |
|---|---|---|
| A-UTAIR-HDR-LO | Plant air compressor and header: header pressure low | `header_pressure_bar` below 5.6 bar; alarm: the station keeps running |
| A-UTAIR-CUR-HI | Plant air compressor and header: compressor current high | `compressor_current_a` above 110 A; alarm: the station keeps running |
| A-UTAIR-OILT-HI | Plant air compressor and header: oil temperature high | `oil_temp_c` above 95 degC; alarm: the station keeps running |
| A-UTAIR-DRN | Plant air: condensate drain cycle | Information; timed drain |
| A-UTCHL-FLT-SVC | Chiller: filter service due | Information; see Appendix B |
| A-ST20-GUN-FRC / A-ST30-GUN-FRC | gun force not reached (weld cells) | Often the first sign of low supply air at the cells; see Section 6.2 |
| S-ST20-AIR-LO / S-ST30-AIR-LO | gun air pressure low, cell stopped (weld cells) | Supply-air interlock at the cell; see Section 6.2 |
| A-L1-ANDON | Line L1 stopped: andon raised | Information; follows any station stop |

---
*AM-CA-01 Rev. A | Plant Air System and Utilities | Page 9 of 25 | Fictional equipment for demonstration only*

<!-- page 10 -->

# 4 Operation

## 4.1 Start-up

Start-up occurs at the start of each shift during the planned changeover. Operators begin with pre-start checks to confirm system integrity. Inspect the compressor, receiver, and pipework for physical damage or evidence of loose fittings. Check the compressor oil level and verify that all protective panels, covers, and electrical enclosure doors are closed and secure.

Initiate the compressor start sequence at the control panel. Confirm that the motor begins running and that the refrigerated dryer is active. Observe the monitored parameters as the system builds pressure. The signal header_pressure_bar must climb toward its cut-out pressure of 7.3 bar within the normal range of 6 to 7.5 bar. Compressor motor current, compressor_current_a, must track from about 92 A loaded down to about 38 A once unloaded. Check that oil_temp_c stays within 60 to 85 degC and chiller supply_temp_c remains within 10 to 14 degC.

## 4.2 Normal operation

During production, operators monitor control readouts to ensure consistent air delivery to weld cells ST20 and ST30. Observe the load and unload cycling of the compressor. The header pressure must cycle continuously between the 6.2 bar cut-in threshold and the 7.3 bar cut-out threshold, remaining inside the 6 to 7.5 bar operating band. Check that motor current alternates predictably between about 92 A loaded and about 38 A unloaded.

Any parameter deviation must be reported to maintenance immediately. Report any instance where header pressure approaches the 5.6 bar low alarm limit, which can impair weld gun clamping. Report excessive motor current nearing the 110 A high alarm limit or compressor oil temperature approaching the 95 degC limit. Operators must also inform maintenance if the process chiller supply temperature approaches the 15 degC alarm limit, if condensate drains fail to discharge, or if audible hissing indicates air leakage along the header or drop legs.

---
*AM-CA-01 Rev. A | Plant Air System and Utilities | Page 10 of 25 | Fictional equipment for demonstration only*

<!-- page 11 -->

## 4.3 Normal production stop

A normal production stop brings the compressed air system to an orderly idle or powered-down state at the end of scheduled production. Depress the stop control on the compressor panel, allowing the unit to complete its programmed stopping sequence. Turn off downstream isolation valves at the drop legs if required for line pauses.

A normal production stop is not an energy-isolated state. Stored air pressure remains trapped inside the receiver, header, and drop legs, and electrical supply circuits remain energised. When maintenance tasks or mechanical adjustments are required, apply the energy control procedure in Chapter 8.

---
*AM-CA-01 Rev. A | Plant Air System and Utilities | Page 11 of 25 | Fictional equipment for demonstration only*

<!-- page 12 -->

# 5 Control parameters: cycle timers and change control

## 5.1 Control parameters

The plant air system incorporates defined control parameters that govern air generation and delivery. Key adjustable settings include the cut-in pressure of 6.2 bar, the cut-out pressure of 7.3 bar, and the weld cell regulator settings established at 5.6 bar on each drop leg to ST20 and ST30. Timed condensate drain intervals on the receiver and dryer also control moisture ejection cycles.

Uncontrolled adjustments to these parameters present severe operational hazards. Altering pressure thresholds can trigger high motor current, promote excessive thermal wear, and disrupt pneumatic weld gun forces, causing assembly defects or unplanned line stops. Consequently, personnel must never change control parameters or cycle timers without authorization. Every proposed adjustment must be reviewed and processed strictly through the formal change control procedure.

**Table 5-1 Adjustable control parameters**

| Parameter | Function | May be changed by |
|---|---|---|
| Cut-in and cut-out pressures | Load/unload pressure band | Utilities technician with change request |
| Condensate drain interval and open time | Timed drains | Utilities technician |
| Restart delay after power return | Automatic restart timer | Utilities technician with change request |

---
*AM-CA-01 Rev. A | Plant Air System and Utilities | Page 12 of 25 | Fictional equipment for demonstration only*

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
| ST20 or ST30 cycle time stepped up at a shift start and stays at the new level; process signals normal | Timer or dwell parameter changed at the changeover (wrong value, wrong recipe, or a trial value left active) | Compare the active parameter set with the last approved copy; check the parameter log for the shift start | Restore the approved value under change control; record the deviation |
| Stations downstream starved and stations upstream blocked after a shift start | A slower cycle at one station propagating along the line | Find the first station whose cycle time changed; downstream starvation and upstream blocking are consequences | Correct the parameter at the first station only |
| Cycle time slightly longer for the first parts after every changeover | Normal ramp-up after a changeover | Confirm that cycle time returns to the normal range within a few cycles | No action |

---
*AM-CA-01 Rev. A | Plant Air System and Utilities | Page 13 of 25 | Fictional equipment for demonstration only*

<!-- page 14 -->

# 6 Troubleshooting

## 6.1 Using this chapter

System troubleshooting follows an organized diagnostic approach. When a fault occurs, start from the symptom index in Chapter 6 to identify the corresponding failure mode. Compare the current equipment status against the documented typical signature to confirm that the observed behaviour matches the expected process trend.

Rule out sensor or instrument problems before undertaking component interventions. Verify that the monitored signals reflect true system conditions rather than faulty wiring or transmitter error. Follow the check column carefully to systematically verify physical causes before attempting any corrective remedy. If any inspection or repair requires physical interaction with mechanical, pneumatic, or electrical assemblies, apply the energy control procedure in Chapter 8 prior to beginning hands-on work.

**Table 6-1 Symptom index**

| First symptom | Topic | Section | Page |
|---|---|---|---|
| Header pressure falling, compressor loaded continuously | Header pressure low / air leaks | 6.2 | 15 |
| `oil_temp_c` above 85 degC at normal load duty | Compressor oil temperature high | 6.3 | 16 |
| One signal trending with no change in related signals | Instrument verification: suspected sensor drift | 6.4 | 17 |
| Cycle time stepped at a shift start, process normal | Control parameters: cycle timers and change control | 5 | 12 |
| Supply temperature high | Chiller supply temperature high | B.2 | 25 |

---
*AM-CA-01 Rev. A | Plant Air System and Utilities | Page 14 of 25 | Fictional equipment for demonstration only*

<!-- page 15 -->

## 6.2 Header pressure low / air leaks

**Typical signature.** In normal service the compressor loads at 6.2 bar and unloads at 7.3 bar, so header pressure (`header_pressure_bar`) saw-tooths inside its normal range of 6 to 7.5 bar and motor current (`compressor_current_a`) switches between about 92 A loaded and about 38 A unloaded, a load/unload cycle of roughly 2 minutes. A leak first shows as a longer loaded time: average motor current rises while header pressure still recovers. When leakage plus demand exceed what the compressor can deliver, the compressor stays loaded, header pressure falls below the cut-in pressure, and the 5.6 bar low alarm (A-UTAIR-HDR-LO) follows. The weld cells see their regulated gun air fall shortly after; gun force alarms follow, and when gun air reaches each cell's own low limit (see the weld cell manual) the supply-air interlock stops that cell. A leak is often audible as a hiss at the leak point.

**Diagnostic notes**

- A sustained fall in header pressure while the compressor runs loaded indicates demand exceeding supply, most often a distribution leak.
- Check drop-leg fittings and quick couplings at the weld cells first; they account for most leaks on this header.
- A fall in gun air pressure at ST20 and ST30 at the same time, after the header pressure has fallen, places the cause in the air supply, not in the weld cells.
- A header pressure reading that falls while compressor duty and the gun air pressures at both cells stay normal points to the header pressure transmitter; see Section 6.4.

**Table 6-2 Troubleshooting: Header pressure low / air leaks**

| Symptom | Probable cause | Check | Remedy |
|---|---|---|---|
| Header pressure falling, compressor loaded continuously | Distribution leak (drop legs, couplings, hoses) or a new air user | Ultrasonic leak survey of the header and the ST20/ST30 drop legs with the cells stopped | Repair the leaks; confirm the header holds pressure (see Table 3-2) |
| Compressor loaded longer than usual, header pressure still normal | Leak developing | Compare load duty with last week's trend; walk the header listening for hiss | Schedule a leak survey |
| Header pressure low, compressor current low (not loading) | Inlet valve stuck closed, or load control fault | Check the compressor display for load status and faults | Repair the inlet valve or load control |
| Continuous hiss at a drain, header pressure low | Condensate drain stuck open | Listen at the receiver and dryer drains | Clean or replace the drain valve |
| Gun air low at one cell only, header normal | Local problem at that cell | Check the cell filter-regulator | See the weld cell manual, Section 6 |

**Background.**

In normal operation, the compressor inlet valve loads at 6.2 bar and unloads at 7.3 bar, causing header_pressure_bar to trace a steady saw-tooth profile within its normal range of 6 to 7.5 bar. During this routine cycle, compressor_current_a alternates between about 92 A loaded and about 38 A unloaded over a typical cycle of roughly 2 minutes.

When an air leak develops, compressed air escapes continuously, creating an additional baseline consumption. This added demand first shows as an extended loaded time; the compressor takes longer to reach the 7.3 bar cut-out threshold, which elevates the average motor current even while header pressure still recovers. If the combined total of line leakage and weld cell demand exceeds compressor output capacity, the unit remains loaded continuously without reaching 7.3 bar. The header pressure drops below the 6.2 bar cut-in setting until it breaches the 5.6 bar low alarm limit, triggering alarm A-UTAIR-HDR-LO. Shortly after header pressure declines, downstream air to the weld guns drops below the 5.6 bar regulator setting. Gun force alarms follow, and once gun pressure falls to the internal low limit of ST20 or ST30, the supply-air interlock halts cell operation. Escaping air can often be identified as an audible hiss at the leak point.

---
*AM-CA-01 Rev. A | Plant Air System and Utilities | Page 15 of 25 | Fictional equipment for demonstration only*

<!-- page 16 -->

## 6.3 Compressor oil temperature high

**Typical signature.** Compressor oil temperature (`oil_temp_c`) normally stays within 60 to 85 degC; the alarm is at 95 degC.

**Diagnostic notes**

- Oil temperature rising together with longer loaded time usually follows a leak or extra demand; oil temperature rising at normal duty points to the cooler or the oil.

**Table 6-3 Troubleshooting: Compressor oil temperature high**

| Symptom | Probable cause | Check | Remedy |
|---|---|---|---|
| `oil_temp_c` above 85 degC at normal load duty | Oil cooler fouled or cooling fan fault | Inspect the cooler fins and the fan | Clean the cooler; repair the fan |
| Oil temperature high, oil level low | Oil loss through the separator or a leak | Check the oil level and the separator differential | Top up; replace the separator element |
| Oil temperature high with longer loaded time | Compressor working harder because of a leak or extra demand | See Section 6.2 | Repair the leak |

---
*AM-CA-01 Rev. A | Plant Air System and Utilities | Page 16 of 25 | Fictional equipment for demonstration only*

<!-- page 17 -->

## 6.4 Instrument verification: suspected sensor drift

**Typical signature.** One monitored value trends slowly towards a limit, or jumps beyond it, while the signals that are physically linked to it stay normal.

**Table 6-4 Physical correlates of monitored signals**

| Signal | Physically related signals and checks |
|---|---|
| `header_pressure_bar` | Compressor load duty (motor current), gun air pressure at ST20 and ST30, the header gauge |
| `compressor_current_a` | Load/unload pattern, header pressure |
| `supply_temp_c` (chiller) | ST30 servo temperature and coolant flow, handheld reading at the supply |

**Diagnostic notes**

- A real process change moves more than one signal; a single tag that trends steadily while every physically related tag stays normal points to the instrument, not the process.
- Do not replace process components on the evidence of one drifting tag; verify the instrument first against a calibrated reference at the measuring point.
- A reading that jumps beyond a trip limit for one to three seconds and then returns, with no change in related tags before or after, is a measurement spike; reset, record it and keep the station running.
- Gaps in a trend, a value that stays exactly constant for a long period (stuck value) and the same alarm repeating several times within a minute (alarm chatter) are data-quality effects of the instrument or the network; they are not process faults and are not evidence of a failure.

---
*AM-CA-01 Rev. A | Plant Air System and Utilities | Page 17 of 25 | Fictional equipment for demonstration only*

<!-- page 18 -->

**Table 6-5 Troubleshooting: suspected sensor drift**

| Symptom | Probable cause | Check | Remedy |
|---|---|---|---|
| One tag trends steadily towards a limit; all related tags in Table 6-4 stay normal | Transmitter drift (ageing, contamination, loose terminal, moisture in the connector) | Compare the reading with a calibrated handheld reference at the same point; inspect the connector and cable | Recalibrate or replace the transmitter; record the as-found and as-left values in the calibration log |
| Station stopped on a high-high or low-low trip after a one- to three-second excursion | Measurement spike (electrical noise, loose shield, vibration on the cable) | Check the trend either side of the trip; check related tags; inspect cable shield and gland | Reset and restart; if spikes repeat, re-terminate the shield and re-route the cable away from power cables |
| Value frozen at exactly the same number for a long period | Stuck value: lost update between the transmitter and the controller or historian | Check the transmitter display against the HMI; check the communication diagnostics | Restore communication; do not use the frozen period as process evidence |
| Same alarm raised and cleared several times within a minute | Alarm chatter: value hovering at the limit with too little deadband | Check the trend at the limit; check the alarm deadband setting | Treat as one event; request a deadband review through change control (see Chapter 5) |

---
*AM-CA-01 Rev. A | Plant Air System and Utilities | Page 18 of 25 | Fictional equipment for demonstration only*

<!-- page 19 -->

# 7 Maintenance

## 7.1 Preventive maintenance

Rigorous preventative maintenance preserves operating efficiency, protects downstream tooling at ST20 and ST30, and prevents costly unplanned downtime on line L1. Completing service tasks at the prescribed intervals ensures that air quality remains dry, pressure levels stay stable, and rotating parts remain lubricated and cool.

Technicians must complete every assigned task according to schedule, including shift inspections, daily condensate checks, weekly walkarounds, monthly cooler cleaning, quarterly ultrasonic leak surveys, and major component overhauls. Whenever maintenance is performed, record the completed tasks, inspection findings, operating hours, and any replaced components within the computerized maintenance tracking log.

**Table 7-1 Preventive maintenance intervals**

| Task | Interval | See |
|---|---|---|
| Check the compressor display and oil level | Every shift | Section 6.3 |
| Check the condensate drains operate | Daily | Section 6.2 |
| Walk the header and drop legs listening for leaks | Weekly | Section 6.2 |
| Clean the oil cooler fins | Monthly | Section 6.3 |
| Ultrasonic leak survey of header and drop legs | Quarterly | Section 6.2 |
| Replace the air intake filter | Every 2000 running hours | Section 6.3 |
| Replace oil, oil filter and separator element | Every 4000 running hours | Section 6.3 |
| Pressure vessel inspection of the receiver | As required by local regulation | - |
| Calibration check of the header pressure transmitter | Yearly | Section 6.4 |

## 7.2 Recommended spare parts

**Table 7-2 Recommended spare parts**

| Part | Quantity to stock |
|---|---|
| Push-in fittings for drop legs | 10 |
| Quick couplings | 5 |
| Drain valve | 1 |
| Oil filter and separator element | 1 set |
| Thread sealant | 1 |

---
*AM-CA-01 Rev. A | Plant Air System and Utilities | Page 19 of 25 | Fictional equipment for demonstration only*

<!-- page 20 -->

# 8 Energy control procedure (lockout/tagout)

## 8.1 Scope, purpose and authorisation

> **IMPORTANT - FICTIONAL EQUIPMENT.** This manual describes fictional equipment created for the Andon Agent software demonstration (synthetic line L1). It is not a manufacturer's manual. Its energy control procedure is not a substitute for a site-specific energy control procedure prepared, approved and trained under 29 CFR 1910.147 or local regulation.

**Equipment.** Plant air system (oil-injected screw compressor, receiver, main header, drop legs to ST20 and ST30). Applies to: UT-AIR.

**Purpose.** This procedure controls hazardous energy when anyone repairs a leak, opens a fitting, valve or drop leg on the header, or works on the compressor, the oil separator, the receiver or the condensate drains.

**Authorisation.** Only authorised employees trained on this procedure may apply or remove locks and tags. Each authorised employee applies a personal lock and tag; a group lockout uses a lock box with one personal lock per employee.

**Basis.** This procedure follows the energy control procedure requirements of 29 CFR 1910.147(c)(4) and the sequence of 29 CFR 1910.147(d)(1) to (d)(6), with notification under (c)(9) and release from lockout or tagout under (e). Each step cites its paragraph. Steps are carried out in the order given.

## 8.2 Energy sources

**Table 8-1 Hazardous energy sources and isolating devices**

| Energy | Source and magnitude | Isolating device | Stored or residual energy |
|---|---|---|---|
| Electrical | 400 V AC three-phase supply to the compressor motor and cooling fan; 24 V DC control | Compressor main disconnect switch | The controller restarts the compressor automatically when header pressure falls to cut-in; the disconnect blocks this |
| Pneumatic | Receiver and header at up to 7.3 bar (unload pressure) | Header isolation valve; receiver outlet valve | Air stored in the receiver and the header; bleed to zero |
| Pressurised oil | Oil separator vessel under discharge pressure while running | Compressor stopped and isolated | Vents through the blow-down valve on stop; confirm the separator gauge reads zero |
| Thermal | Compressor oil at about 72 degC; hot discharge pipework | None | Allow to cool; heat-resistant gloves |

---
*AM-CA-01 Rev. A | Plant Air System and Utilities | Page 20 of 25 | Fictional equipment for demonstration only*

<!-- page 21 -->

## 8.3 Preparation, shutdown, isolation and lockout

**Table 8-2 Preparation, shutdown, isolation and lockout**

| Step | Action | 29 CFR 1910.147 paragraph |
|---|---|---|
| 1 | Identify every energy source for the compressor and the header from Table 8-1 and collect one personal lock and tag for each isolating device. | (d)(1) |
| 2 | Notify the line lead, the ST20 and ST30 operators and the utilities technician that the plant air system will be shut down and locked out. | (c)(9) |
| 3 | Stop the ST20 and ST30 weld cells at the end of a cycle before the air supply is shut off. | (d)(2) |
| 4 | Stop the compressor with the stop push-button on the compressor panel and wait until the unloaded run-down has finished. | (d)(2) |
| 5 | Switch the compressor main disconnect switch to OFF so that the automatic restart is blocked. | (d)(3) |
| 6 | Close the header isolation valve upstream of the work section. | (d)(3) |
| 7 | For work on the compressor or the receiver, also close the receiver outlet valve. | (d)(3) |
| 8 | Fit a personal lock and tag to the compressor main disconnect switch and to every valve closed for isolation. | (d)(4) |

---
*AM-CA-01 Rev. A | Plant Air System and Utilities | Page 21 of 25 | Fictional equipment for demonstration only*

<!-- page 22 -->

## 8.4 Stored energy and verification of isolation

**Table 8-3 Stored energy and verification of isolation**

| Step | Action | 29 CFR 1910.147 paragraph |
|---|---|---|
| 9 | Open the header bleed valve downstream of the isolation valve and wait until the header pressure gauge reads zero. | (d)(5)(i) |
| 10 | For work on the compressor or the receiver, open the receiver drain valve until the receiver pressure gauge reads zero. | (d)(5)(i) |
| 11 | Confirm that the oil separator pressure gauge reads zero before opening the separator or any discharge fitting. | (d)(5)(i) |
| 12 | Let the compressor oil and the discharge pipework cool before touching them, and wear heat-resistant gloves. | (d)(5)(i) |
| 13 | Leave the bleed valve open for the whole job so that a passing isolation valve cannot build up pressure again. | (d)(5)(ii) |
| 14 | Press the compressor start push-button to confirm that the compressor does not start, then return the control to off. | (d)(6) |
| 15 | Confirm that the header pressure gauge downstream of the isolation valve reads zero. | (d)(6) |
| 16 | Test for absence of voltage at the compressor motor terminals with a tester proven on a known live source before and after the test. | (d)(6) |

---
*AM-CA-01 Rev. A | Plant Air System and Utilities | Page 22 of 25 | Fictional equipment for demonstration only*

<!-- page 23 -->

## 8.5 Release from lockout/tagout

**Table 8-4 Release from lockout/tagout**

| Step | Action | 29 CFR 1910.147 paragraph |
|---|---|---|
| 17 | Remove tools and nonessential items, and confirm that every fitting, drain and the oil filler cap is fitted and tight. | (e)(1) |
| 18 | Close the header bleed valve and the receiver drain valve. | (e)(1) |
| 19 | Check that all employees are clear of the compressor, the receiver and any opened header section. | (e)(2)(i) |
| 20 | Each employee removes only the lock and tag that the employee applied. | (e)(3) |
| 21 | Notify the affected employees that the locks and tags have been removed before the compressor is restarted. | (e)(2)(ii) |

**Testing or positioning.** If the equipment must be energised temporarily to test or position it, follow 29 CFR 1910.147(f)(1): clear tools and materials, remove employees from the area, remove the locks and tags, energise and test, then de-energise and reapply every energy control measure in the order of this chapter before work continues.

---
*AM-CA-01 Rev. A | Plant Air System and Utilities | Page 23 of 25 | Fictional equipment for demonstration only*

<!-- page 24 -->

# Appendix A Glossary

Air receiver: Sturdy vessel that stores compressed air and evens out demand fluctuations across the header.

Cut-in pressure: Fixed lower pressure setting of 6.2 bar at which the compressor loads and begins delivering air.

Cut-out pressure: Upper pressure setting of 7.3 bar at which the compressor unloads and closes its air intake.

Drop leg: Vertical piping assembly extending from the main header equipped with a ball valve, filter-regulator, and quick couplings to supply an individual weld cell.

Filter-regulator: Pneumatic device at a drop leg adjusted to 5.6 bar to filter air and stabilize working pressure for weld tooling.

Load/unload control: Control system that opens the inlet valve when air is needed and closes the inlet valve while keeping the motor running during low demand.

Oil separator: Internal element that separates injected cooling oil from the compressed air discharge stream.

Refrigerated dryer: Thermal processing unit that cools compressed air to condense and remove entrained moisture.

Timed condensate drain: Electrically actuated drain valve installed on the receiver and dryer that periodically opens to evacuate moisture.

---
*AM-CA-01 Rev. A | Plant Air System and Utilities | Page 24 of 25 | Fictional equipment for demonstration only*

<!-- page 25 -->

# Appendix B Process chiller

The process chiller supplies chilled water to the weld cell coolant circuits. Only its supply temperature is monitored by the line.

## B.1 Process values and limits

**Table B-1 Process values and limits: UT-CHL (Process chiller)**

| Tag | Description | Unit | Nominal | Normal range | Alarm low | Alarm high | Trip low | Trip high | Resolution |
|---|---|---|---|---|---|---|---|---|---|
| `supply_temp_c` | Chilled water supply temperature | degC | 12 | 10 to 14 | - | 15 | - | - | 0.01 |

**Table B-2 Alarm and stop messages**

| Code | Message | Condition or meaning |
|---|---|---|
| A-UTCHL-SUPT-HI | Process chiller: supply temperature high | `supply_temp_c` above 15 degC; alarm: the station keeps running |

## B.2 Chiller supply temperature high

**Typical signature.** Supply temperature (`supply_temp_c`) normally cycles within 10 to 14 degC as the chiller compressor starts and stops; the alarm is at 15 degC.

**Diagnostic notes**

- A high supply temperature affects both weld cells; a cooling problem at one cell only is inside that cell.

**Table B-3 Troubleshooting: Chiller supply temperature high**

| Symptom | Probable cause | Check | Remedy |
|---|---|---|---|
| Supply temperature high | Condenser fouled or chiller filter clogged (A-UTCHL-FLT-SVC) | Check the chiller display and the filter | Clean the condenser; service the filter |
| Supply temperature normal, one cell overheating | Restriction inside the cell | See the weld cell manual, Section 6 | - |

---
*AM-CA-01 Rev. A | Plant Air System and Utilities | Page 25 of 25 | Fictional equipment for demonstration only*
