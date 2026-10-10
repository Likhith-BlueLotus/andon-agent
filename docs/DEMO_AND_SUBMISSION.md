# Demo, deck, Q&A and submission

## Demo scenario (decided): a real-signal air leak
Use an R-set MetroPT-3 scenario (e.g. R002). Why: the **alarms fire at the weld cells (ST20/ST30)**, but the root cause is a leak in the **plant air system upstream** — the "alarm at the wrong station" story — and the root-cause signal is **real**, with ground truth from the operator's own failure report. The compressed-air manual's LOTO section (stored-energy release) makes the safety gate meaningful. Name the scenario in the README. Keep one S-set scenario (sealer pump cavitation, with audio) as the backup take.

## Video: target 2:50 (FAQ says "under 3 minutes")
| Time | On screen | Voiceover (draft — finalise with measured numbers) | Proves |
|---|---|---|---|
| 0:00–0:08 | Title: "Manufacturing: Intelligent Operations & Industrial Efficiency" + Andon Agent | "Andon Agent — built for the Manufacturing theme." | Theme alignment |
| 0:08–0:30 | Line mimic: weld cells red, cost counter ticking | "Siemens' True Cost of Downtime 2024 puts an hour of unplanned downtime in automotive at about $2.3 million. Here both weld cells are alarming — but the weld cells aren't the problem." | Sourced pain, the hook |
| 0:30–0:42 | Address bar with the live URL; scenario picker shows "Air leak · real compressor data (MetroPT-3)"; click Investigate | "This is the live app. The pressure signal here is real compressor failure data from a public dataset, mapped onto our line." | Deployed; honest realism |
| 0:42–1:12 | Plan card; parallel tool cards: change points on weld air pressure → upstream to `UT-AIR` header → compressor current; REAL provenance chips; `listen` on the valve; alarms by SQL | "The commander plans competing checks. The signal analyst works upstream with change-point analysis and listens to the air system. The librarian pulls alarms and work orders." | Agentic reasoning, function calling, multimodal |
| 1:12–1:30 | Manual citation: compressed-air manual page + cache badge + saved-$ | "Five manuals live in a context cache — whole documents, cross-references intact, at a fraction of the input price." | Long context + caching |
| 1:30–1:48 | Verifier strikes a claim ("pressure fell 30%" — measured 11%); judge revises (loop 2/3) | "Every claim is re-checked by code against the data. Here it caught a wrong number and forced a revision." | Verification |
| 1:48–2:00 | Verified RCA: plant air leak upstream, weld faults downstream; tick LOTO steps (incl. stored-air release); Approve → WO `PENDING_APPROVAL` | "A human approves, with lockout steps quoted word for word. Nothing touches the machine." | HITL, safety, structured output |
| 2:00–2:25 | Architecture diagram with Google Cloud services + capability strip | "ADK agents on Gemini: 3.8 Flash for tool loops, Flash-Lite for volume, 3.1 Pro for the final causal ranking — on Cloud Run, Firebase, BigQuery and Firestore." | GCP integration |
| 2:25–2:50 | Eval slide: S-set table with intervals, R-set table, $/diagnosis | "On 60 synthetic scenarios and 17 real-signal ones labelled by their sources, here's how we compare with a single big prompt and a classical baseline — at cents per diagnosis." | Evidence, honesty, viability |

Recording rules: Fri Oct 16, `infra/warm.sh on`, warm-up run 2 min before, Pro judge, three takes, best segments. If live fails, record replay **with its on-screen banner**. Captions on, 1080p, uploaded **public**.

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
| Why Pro preview in production? | "Only the final ranking uses it, with automatic fallback to GA Flash; residency mode drops it." |
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
