# Motion segments: exact text, numbers and sources

For the Remotion builder. Timeline and screen-recording segments live in `docs/DEMO_AND_SUBMISSION.md` (Video). Do not add numbers that are not on this page. Palette and badge follow the app (dark UI). Voiceover below is the read-aloud text; keep each segment inside its slot (voiceover is about 2.5 words per second).

Theme string (exact, no changes): `Manufacturing: Intelligent Operations & Industrial Efficiency`
Data wording (exact): "real compressor failure signals from a public dataset, mapped onto our synthetic line". Never "real plant data".

## M1 Title, 0:00-0:08
- On screen: `Andon Agent` (large); under it, the theme string above, exactly; small line: `Synthetic line, real signals marked`.
- Voiceover: "Andon Agent. Built for Manufacturing: Intelligent Operations and Industrial Efficiency." (10 words)

## M2 Hook, 0:08-0:20
- On screen: a stylised line of stations ST10 to ST60; ST20 turns red and pulses "ALARM"; an arrow runs back upstream to a block "UT-AIR plant air" that stays grey. Big number `$2.3M / hour`; caption `Large automotive plant, unplanned downtime`; source line, small but legible: `Siemens, The True Cost of Downtime 2024, p. 2`.
- Voiceover: "When an automotive line stops, a large plant can lose two point three million dollars an hour, says Siemens. And the alarm is often at the wrong station." (28 words)
- Source check: opened the Siemens PDF on 2026-10-12 (https://assets.new.siemens.com/siemens/assets/api/uuid:1b43afb5-2d07-47f7-9eb7-893fe7d0bc59/TCOD-2024_original.pdf). Text on p.2: "An hour's downtime in a large Automotive plant now costs $2.3 million an hour - or more than $600 a second." Do not show "$600 a second" or any other Siemens figure. NOT sourced inside the repo before today: flagged. The "alarm at the wrong station" line is our scenario (R002: stop at ST20-WLD, cause at UT-AIR), not a statistic; do not put a percentage on it.

## M3 Verifier explainer, 0:58-1:10 (12 s)
Real numbers from the recorded run `s014-cloud-1` (`data/replays/s014-cloud-1.jsonl`, claim_verdict seq 52, verifier_verdict seq 59, iteration 1; revision PASS seq 65/72, iteration 2).
- Beat 1 (0-3 s), card "Judge claim (causal order)": `ST40-SLR flow ramped down at 2026-09-13 20:04:00Z, before the ST60-VIS reject ramp`.
- Beat 2 (3-7 s), a "Verifier (code, no LLM)" box re-runs tools: `ev_detect_change_points_3` (flow_rate_ccm, ST40-SLR) and `ev_detect_change_points_1` (reject_rate_pct, ST60-VIS); the measured value counts up to `-390,495 s`.
- Beat 3 (7-10 s), claim card turns red, struck through, stamp `REJECTED: reversed`; under it the exact verifier reason, shortened: `ST60-VIS onset 2026-09-09T07:35:45Z is 390495 s before root ST40-SLR onset 2026-09-13T20:04:00Z`.
- Beat 4 (10-12 s), a green card `Revised claim: ST60-VIS reject onset 2026-09-13T23:15:45Z -> verified (+0 s)`, then label `Iteration 2 of 3: PASS`.
- Voiceover: "The model proposes. Code disposes. Every claim is re-checked against the evidence, and a mismatch is rejected with the measured value. Here: three hundred ninety thousand seconds off." (28 words)
- Footnote on screen, tiny: `Recorded run s014-cloud-1, synthetic scenario S014`. 390,495 s is about 108 hours; show seconds, as the verifier does.

## M4 Architecture, 2:05-2:25 (20 s)
Layout from `docs/ARCHITECTURE.md` section 2 (agent graph: Commander, then Parallel(Signal Analyst, Evidence Librarian), then Loop(RCA Judge <-> Verifier, max 3), then Action Drafter; human approval at the end). Build it as a left-to-right flow, not a copy of the Mermaid.
- Boxes, in order: `Incident Commander` -> `Signal Analyst` + `Evidence Librarian` (parallel) -> `RCA Judge` <-> `Deterministic Verifier (code, no LLM)` -> `Action Drafter` -> `Human approval` -> `Mock CMMS (PENDING_APPROVAL)`.
- Model labels: Commander, Signal Analyst, Evidence Librarian, RCA Judge: `Gemini 3.8 Flash` (Librarian also `Gemini 3.1 Flash-Lite` for bulk text). Verifier: no model. Do not show 3.1 Pro anywhere; the measured judge is Flash (ADR-026, `eval/results/final_pro/results_table.md` shows Pro was worse: S 0.90, R 0.71).
- Service strip along the bottom: `Agent Platform (Gemini)` `Cloud Run` `Firebase Hosting` `Firestore` `Cloud Storage` `Secret Manager` (all in `docs/ARCHITECTURE.md` section 2 and its table; also Vertex AI / Agent Platform for Gemini).
- Footer chip: `No physical writes. One write tool: draft_work_order`.
- Voiceover: "Six ADK agents: commander, signal analyst, evidence librarian, RCA judge, a deterministic verifier with no model in it, and an action drafter. Gemini 3.8 Flash reasons; 3.1 Flash-Lite handles volume. Agent Platform runs Gemini; Cloud Run, Firebase Hosting, Firestore, Cloud Storage, Secret Manager." (40 words)

## M5 Results, 2:25-2:45 (20 s)
All numbers from run id `final_v2`: `eval/results/final_v2/results_table.md` and `eval/results/final_v2/summary.json`. Two separate panels, never merged. Use 95% Wilson intervals as printed.

Panel A: `S-set: synthetic line, injected truth (n = 60)`
| System | Top-1 [95% CI] |
|---|---|
| Andon Agent (S1) | 0.98 [0.91, 1.00] |
| Single long prompt (B1) | 0.92 [0.82, 0.96] |
| Classical baseline (B2) | 0.15 [0.08, 0.26] |

Panel B: `R-set: real signals mapped onto the synthetic line (n = 17)`
| System | Top-1 [95% CI] |
|---|---|
| Andon Agent (S1) | 0.76 [0.53, 0.90] |
| Single long prompt (B1) | 0.59 [0.36, 0.78] |
| Classical baseline (B2) | 0.24 [0.10, 0.47] |

Center callout (the real claim): `Unsupported claims: 1 of 586 (Andon) vs 54 of 645 (single prompt)`. Sum check: S1 1/456 S-set + 0/130 R-set = 1/586; B1 40/501 + 14/144 = 54/645.
Honesty chip, always visible: `Top-1 difference vs single prompt: not significant (McNemar p = 0.219 S, 0.375 R). The win is grounding.`
Cost chip: `About $0.11 per diagnosis (measured, $/run 0.107 S-set, 0.109 R-set)`.
- Voiceover: "We tested sixty synthetic scenarios and seventeen real-signal ones against one long prompt. Top-1 accuracy is similar; the difference is not significant. The gain is grounding: one unsupported claim in 586, versus 54 in 645. About eleven cents a diagnosis." (40 words)
- Do not show: the S2 (no verifier) row, variance runs, the Pro-judge row, held-out numbers. Those are Q&A material.

## M6 End card, 2:45-2:50
- On screen: `Andon Agent`; the theme string above, exact; `https://andon-agent-b9c77.web.app`; `github.com/Likhith-BlueLotus/andon-agent`; small: `Synthetic line, real signals marked. No physical writes.`
- Voiceover: "Andon Agent. Live at andon-agent-b9c77 dot web dot app." (9 words)
- Do not show: employer names, team-member companies, anything not built during the hackathon.

## Sources not found / to confirm before render
- Siemens figure is verified against the PDF but absent from repo docs; add it to the README sources.
- The repo URL above is from `docs/HANDOFF.md`; confirm it is public at submission time.
- Everything in M3 comes from one recorded run; it is real model output on a synthetic scenario and must be labelled so (footnote above).
