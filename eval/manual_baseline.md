# Manual baseline kit (EVAL_PLAN §5) — indicative only

Purpose: a rough human reference for "how long, and how often right, does a person with an
engineering background take to find the cause from raw charts and logs, without the agent?"
It is **never a headline statistic**. Report it as "n = X people, Y diagnoses, indicative".

## Who
Each teammate plus 2-3 outside volunteers (friends or classmates with an engineering background).
No employer data is involved: everything shown is the synthetic line with marked real signals.
Nobody who built or tuned the scenarios diagnoses the same scenario they tuned on.

## What each person diagnoses
3 **held-out** scenarios each, drawn from S051-S060 (never the ones used for tuning). Assign so that
every scenario is diagnosed by at least two people where possible; rotate the order. Write the
assignment in the sheet below before starting. Do not tell the volunteer the variant (clean,
red herring, dual fault, no fault); a no-fault answer ("no machine fault, data issue") is allowed.

## The debug view (no agent)
Use the web app's raw views only: open the scenario, then use the **evidence drawer** and the
telemetry/alarms/notes/work-order panes to read charts and logs; do **not** open the agent trace,
RCA, or verdicts. If the plain mode is not obvious in the build you have, the minimal equivalent is:
per-asset telemetry charts for the 7-day history, the alarm list, shift notes and work-order history
for the stop window, and the five manuals as PDFs/Markdown. Nothing else (no model output).
`?mock` modes of the web app are for demos; do not use them for timing.

## Protocol
1. Read-out (30 s, same text for everyone): "A line stopped at <station> at <time>. Find the root
   cause class and asset. You may use the charts, alarms, notes, work orders and manuals. You have 10
   minutes. Say your answer aloud."
2. Start a stopwatch when they open the scenario. Stop at the spoken answer or at **10:00**
   (cap; record "no answer").
3. Record: cause class (from the 12 classes in `agents/schemas.py::CauseClass`, including
   `no_fault`), asset id, confidence 0-100, time in seconds. No hints, no answers to "is it X?".
4. Grade after the session against `truth.json` with the same rule as the eval (class AND asset).
   Timing is wall clock including reading; do not subtract anything.

## Sheet (copy per person)
| Person | Background (1 line) | Scenario | Start | Stop (s) | Answer class | Answer asset | Conf % | Correct (class+asset) | Hit 10-min cap |
|---|---|---|---|---|---|---|---|---|---|
|  |  |  |  |  |  |  |  |  |  |

## Reporting
- "n = X people, Y diagnoses; median time T s (range a-b); Z of Y correct (indicative, not
  comparable to the eval's intervals)". No p-values, no comparison table with S1.
- State the cap and that capped diagnoses count as incorrect and are timed at 600 s.
- Keep the filled sheet in `eval/results/manual_baseline.csv` (names replaced by P1..Pn).
