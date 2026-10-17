# Demo, deck, Q&A and submission

## Demo scenario (decided): a real-signal air leak
Use an R-set MetroPT-3 scenario (e.g. R002). Why: the **alarms fire at the weld cells (ST20/ST30)**, but the root cause is a leak in the **plant air system upstream** — the "alarm at the wrong station" story — and the root-cause signal is **real**, with ground truth from the operator's own failure report. The compressed-air manual's LOTO section (stored-energy release) makes the safety gate meaningful. Name the scenario in the README. Keep one S-set scenario (sealer pump cavitation, with audio) as the backup take.

## Video: target 2:50 (FAQ says "under 3 minutes"); rewritten 2026-10-12 against what is built and measured
Voiceover is about 354 words = 142 s at 150 wpm, inside a 170 s timeline (the slack is breathing room and UI motion). Motion segments (M) are built in `video/` (Remotion); exact text and numbers for them are in `video/SEGMENTS.md`. Screen segments (S) are recordings of https://andon-agent-b9c77.web.app.

| Time | Seg | On screen | Voiceover (read aloud) | Proves | Source of every number |
|---|---|---|---|---|---|
| 0:00-0:08 | M1 | Title card: exact theme string + "Andon Agent" | "Andon Agent. Built for Manufacturing: Intelligent Operations and Industrial Efficiency." | Theme alignment | none |
| 0:08-0:20 | M2 | Hook: "$2.3M / hour" + line of stations, ST20 red, arrow pointing upstream to UT-AIR; source line | "When an automotive line stops, a large plant can lose two point three million dollars an hour, says Siemens. And the alarm is often at the wrong station." | Sourced pain; the story | Siemens, The True Cost of Downtime 2024, p.2: "An hour's downtime in a large Automotive plant now costs $2.3 million an hour" (PDF opened and confirmed 2026-10-12) |
| 0:20-0:31 | S1 | Browser at the live URL (address bar visible). Console, R002 pre-selected, Mode = Replay, Replay banner visible. Click **Investigate stop** | "Live app. Weld cell A stopped. The signals are real compressor failure data from a public dataset, mapped onto our synthetic line. This is a recorded replay." | Deployed; honest data wording; replay banner | `data/scenarios/R002/stop_event.json` (stopped_station ST20-WLD); `data/replays/r002-cloud-1.jsonl` |
| 0:31-0:58 | S2 | R002 replay at 4x speed, trace scrolling: plan card, `detect_change_points` on UT-AIR current and header pressure, REAL provenance chips, `search_alarms`/`get_work_orders`, `cite_manual` card with cache-hit badge | "The commander plans checks that could prove it wrong. The signal analyst goes upstream, running change-point analysis on the plant air header and the compressor. The compressor is loaded one hundred percent of the time, and header pressure steps down. The librarian pulls alarms and work orders, and cites the compressed-air manual by page." | Agentic plan, tools, citations, provenance | r002-cloud-1: `loaded_fraction = 1` (claim h1c4), header_pressure change point 2026-09-19T17:37:59Z (h1c3) |
| 0:58-1:10 | M3 | Verifier explainer: claim card -> code re-runs the tool -> "measured -390,495 s" -> REJECTED | "The model proposes. Code disposes. Every claim is re-checked against the evidence, and a mismatch is rejected with the measured value. Here: three hundred ninety thousand seconds off." | Verification, in one picture | `data/replays/s014-cloud-1.jsonl` seq 52 and 59 (claim_verdict h1c1, measured_value -390495.0) |
| 1:10-1:30 | S3 | Console: scenario S014, Recorded run `s014-cloud-1`, 4x. Right pane: red "Verifier FAIL, revising", struck-through claim with measured value, then iteration 2 PASS and the root cause | "Same check in the app, on a synthetic sealer-pump failure. The judge says the sealer flow drop came first. The verifier measures the inspection rejects starting earlier, rejects the claim as reversed, and the judge must revise. Second pass: it passes. Root cause, a cavitating sealer pump." | Rejection then revision, real run | s014-cloud-1 seq 49, 52, 59, 65, 72; root cause `sealer_pump_cavitation` @ ST40-SLR |
| 1:30-1:53 | S4 | Back to R002 (replay `r002-cloud-1`, 4x, then finished). RCA pane: air_pressure_drop @ UT-AIR, 8 verified claims. Click **Accept**, scroll safety checklist (19 boxes, p.21 etc.), speed-ramp ticking, type approver name, **Approve** -> APPROVED | "Back to the air leak. Verified root cause: plant air upstream, not the weld cell. All eight claims pass. The draft work order has nineteen safety steps, quoted word for word from the manual, with page numbers. A human ticks every box, names themselves, and approves. Nothing touches the machine." | HITL, verbatim LOTO, one write tool | r002-cloud-1 verifier_verdict (8 claims, PASS); work_order_draft (23 steps, 19 `is_safety`) |
| 1:53-2:05 | S5 | Phone viewport 390 px at `/tech`: safety checklist, work-order language = Tamil, "Machine translation" note and translation block under the verbatim English step | "On a phone, the technician sees the same order in Tamil, with the original English safety text kept beside it, untouched." | Multilingual technician view, safety text not paraphrased | ADR-030; screenshot 53 (mock fixture, see flags) |
| 2:05-2:25 | M4 | Architecture: 6 agents on Gemini, GCP services row | "Six ADK agents: commander, signal analyst, evidence librarian, RCA judge, a deterministic verifier with no model in it, and an action drafter. Gemini 3.8 Flash reasons; 3.1 Flash-Lite handles volume. Agent Platform runs Gemini; Cloud Run, Firebase Hosting, Firestore, Cloud Storage, Secret Manager." | GCP and Gemini integration | `docs/ARCHITECTURE.md` section 2; `config.py` |
| 2:25-2:45 | M5 | Results: S-set (n=60) and R-set (n=17) shown as separate panels with intervals; "unsupported claims 1/586 vs 54/645"; "not significant on top-1"; "$0.11 / diagnosis" | "We tested sixty synthetic scenarios and seventeen real-signal ones against one long prompt. Top-1 accuracy is similar; the difference is not significant. The gain is grounding: one unsupported claim in 586, versus 54 in 645. About eleven cents a diagnosis." | Evidence, honesty, viability | `eval/results/final_v2/results_table.md` and `summary.json` (run id `final_v2`) |
| 2:45-2:50 | M6 | End card: theme string, live URL, repo URL, "Synthetic line, real signals marked" | "Andon Agent. Live at andon-agent-b9c77 dot web dot app." | Call to action | none |

### Click path for the recordings (1080p, captions on, three takes, best segments)
1. Open https://andon-agent-b9c77.web.app in a fresh window, dark theme, address bar in frame. Badge `SYNTHETIC LINE · REAL SIGNALS MARKED` and the footer theme string must be visible. No passcode is needed for replays, so do not record the passcode dialog.
2. S1/S2/S4 (R002): Scenario picker defaults to R002. Mode = Replay, Recorded run = `r002-cloud-1`, Replay speed = 4x, press **Investigate stop** (key `I`). Let it finish; the replay banner stays on screen throughout (it reads "Replay of run #r002-cloud-1 recorded ..."). For S4: Accept the root cause, Space through the 19 boxes (speed-ramp in the edit), type an approver name, **Approve**. Record this as one take and cut S1, S2, S4 out of it.
3. S3 (S014): pick S014, Recorded run = `s014-cloud-1`, 4x, **Investigate stop**. Cut tight on iteration 1 FAIL (struck-through claim with the measured value) and iteration 2 PASS.
4. S5: Chrome device toolbar 390 x 844, open `/tech`, scenario R002, Replay, step through to Safety, set Work order language = Tamil. Needs a live check (see flags); if the toggle is not enabled on the deployed build, drop S5 and give its 12 s to M5.
5. Fallback stills if a take fails (use only deployed shots, never mock ones): `22-deployed-desktop-replay-r002.jpg`, `23-deployed-evidence-drawer-real-metropt3.jpg`, `24-deployed-keyboard-approved.jpg`, `25-deployed-mobile-375-loto-approved.jpg`, `49-deployed-tech-root-cause.jpg`. Any replay still must keep the Replay banner in frame.

### Flags (claims not sourced, or evidence gaps)
- **Mock-fixture screenshots must not appear in the video**: `04-verifier-fail-revising.png` shows "MOCK FIXTURE" with invented numbers (18% vs -14); `53-tech-safety-tamil-390.jpg` is also a mock fixture (its translation is "[mock]"). There is **no deployed screenshot of the s014 verifier rejection**; S3 must be recorded fresh.
- Siemens $2.3M/h was not in any repo doc before today (only in this draft and the UI cost counter). Verified in the Siemens PDF on 2026-10-12; the wording is "large Automotive plant". Add it to `data/SOURCES.md` or the README sources list so the figure is citable from the repo.
- The old draft said R002 uses the `listen` tool and shows a verifier strike of "pressure fell 30%, measured 11%"; neither is in the real replay (r002-cloud-1 has no `listen` call) and both are removed here.
- s014 rejection nuance (for Q&A): the rejected claim h1c1 was a causal-order claim ("ST40-SLR flow rate ramped down at 2026-09-13T20:04:00Z prior to ST60-VIS reject rate ramp beginning at 2026-09-13T23:15:45Z"). The verifier compared against ST60's first change point (2026-09-09T07:35:45Z), 390,495 s (about 108 h) before the sealer onset, and returned `reversed`. The revision restated the ST60 onset as 2026-09-13T23:15:45Z, which matched `change_points[1]`. The voiceover says "the inspection rejects starting earlier", which is what the code measured.
- "$0.11 per diagnosis" is the final_v2 `$/run` column (S1 0.107 S-set, 0.109 R-set); the replayed R002 run itself cost $0.153 and S014 $0.171. Say "about eleven cents" only with the eval on screen.
- BigQuery is on the architecture slide as the cloud telemetry store, but live diagnosis queries a per-incident DuckDB built from GCS Parquet (ADR-021). True, but do not say "queries BigQuery live".
- The R-set bar (0.76 vs 0.59, n=17, intervals overlap) is shown only on M5 with its own n and intervals; never merged with the S-set. Do not mention the post-hoc R002 repeat result or the Pro-judge result in the video; both stay in Q&A.
- `docs/ARCHITECTURE.md` and the deck outline still name 3.1 Pro as the RCA judge; the measured and deployed judge is 3.8 Flash (ADR-026). Fix before the deck is exported.

Recording rules: Fri Oct 16, warm-up run 2 min before, three takes, best segments. Every replay segment keeps its on-screen banner. Captions on, 1080p, uploaded **public**.

## Deck (12 slides, export PDF)
1. Title · exact theme · team · live URL · repo · video (Alignment)
2. The stopped line — sourced cost, "alarm at the wrong station" (Impact)
3. Who feels it — technician, supervisor, reliability engineer; today's workflow (Impact/UX)
4. Why current tools fail — dashboards, rule engines, RAG bots (Innovation)
5. Andon Agent in one picture — investigate → verify → approve (UX/Technical)
6. Agent design — roles, models, tools, stop conditions, cost routing (Technical)
7. Gemini capability matrix — ARCHITECTURE §7 as a table (Innovation)
8. The moat — verifier loop, cache-vs-SQL retrieval, multimodal fusion, "isn't this RAG?" (Technical/Innovation)
9. Data — hybrid: synthetic line + real signals with source labels; provenance; licences (Technical/Impact)
10. Eval — the results slide (Technical)
11. Responsible AI + scale path — no physical writes, verbatim LOTO (OSHA 1910.147), IAM, audit, residency mode; OPC UA/MQTT connectors, Dataproc ingestion, vector search past 1M WOs, Gemma 4 at the edge (Technical)
12. Viability & Singapore — pilot model (labelled assumption), JAPAC angle (multilingual technician view), what we'll show on Dec 4 (Impact)

## Judge Q&A prep (rehearse out loud; answers must match what's built)
| Question | Answer shape |
|---|---|
| Isn't this just RAG? | "RAG retrieves and paraphrases. We run analytics on signals and audio, form competing hypotheses, and code re-checks every claim before a human acts — measured against a single-prompt baseline." |
| Your data is synthetic. | "The line is synthetic; the root-cause signals in 17 scenarios are real — compressor failures, a hydraulic rig and bearing run-to-failure tests — graded against the sources' own labels. Results are reported separately." |
| Why not a classical model? | "Classical gives you *where* (B2 is that baseline). Plants lack labelled failures for *why*, and the evidence is in text, manuals and audio too." |
| What stops it hallucinating? | "Every claim cites evidence IDs; code re-runs the query. Unverifiable claims are shown struck through. Unsupported-claim rate is a reported metric." |
| What if it's wrong? | "It never acts. A human accepts the cause and ticks verbatim lockout steps before a work order is even approved. It can also abstain — we measure that." |
| How does it connect to a real plant? | "One `TelemetryStore` interface: today DuckDB/BigQuery; next a historian export/OPC UA adapter. [If built: here's a CSV upload doing it live.]" |
| Cost at scale? | Measured $/diagnosis × stops per month (labelled assumption for the stop rate). |
| Why not the Pro model as judge? | "We measured it: Pro judge scored S 0.90 and R 0.71 against Flash's 0.98 and 0.76 (eval/results/final_pro vs final_v2), at $0.16 vs $0.11 a run. Flash is the judge; Pro was not used." |
| Did you tune on the R-set? | "Prompts were fixed on a dev set (S001-S020) only; the held-out S051-S060 went 10/10. After the eval we made two changes, a judge rule because R002 was unstable and a short-shift detector, so everything measured after them is labelled post-hoc: S 0.97, R 0.82, C 0.50 (`eval/results/posthoc_v4`). We also pre-registered a fresh confirmation set before running it." |
| Your verifier barely changes the score vs S2. What's it for? | "In the eval the judge rarely makes checkable mistakes, so there is little to catch. We tested it directly: 2,778 injected faults, 97.1% caught vs 0% without it; weakest on rose-vs-fell sign flips (92.6%). It wrongly flagged 8 of 586 true claims. It also enforces verbatim LOTO steps and citation premises." |
| Did the pre-registered confirmation pass? | "No, and we published that. Our bar was top-1 ≥ 0.6; S1 scored 0.40 (n=10) and still beat the single prompt (0.20) with 0 unsupported claims vs 6. It misses short real hydraulic faults; a later detector fixed the false alarm (post-hoc 0.50) but not those faults. That's our main open weakness." |
| Is it significantly better than one big prompt? | "Not on top-1: 0.98 vs 0.92 (p = 0.219) and 0.76 vs 0.59 (p = 0.375). The measured gain is grounding: 1 unsupported claim in 586 vs 54 in 645." |
| Data residency for Indian/Singapore plants? | "Prototype on global endpoint with synthetic/public data; residency mode pins Gemini 3.5 Flash to asia-south1 / asia-southeast1." |
| What did you build in the hackathon window? | "Everything — dated public commits from Oct 10." |

## README (first lines, in this order)
1. `Theme: Manufacturing: Intelligent Operations & Industrial Efficiency`
2. Live URL · video · deck · (passcode note for live mode)
3. Problem + solution paragraph
4. Architecture diagram + Google Cloud services + capability matrix
5. Run locally; reproduce the eval
6. Results (S-set and R-set tables, with intervals)
7. Data: hybrid statement, dataset table with licences and citations (link `data/SOURCES.md`), attribution
8. Responsible AI notes; fresh-build statement; licence (MIT for code)

## Submission checklist (Sat Oct 17, done by 18:00 IST)
- [ ] Team registration confirmed (screenshot); eligibility email reply saved
- [ ] Live URL works in incognito on mobile and desktop; replay without passcode; live with passcode
- [ ] Video < 3:00, public, plays without login
- [ ] Deck PDF opens, all links work, 12 slides
- [ ] Public GitHub repo; README as above; `gitleaks detect` clean; `/data-audit` clean
- [ ] Theme named exactly in the form, slide 1, README line 1, video frame 1
- [ ] Judging-window runbook written (warm schedule, daily URL check owner, budget remaining)
- [ ] Submission confirmation screenshot saved
