# Risk register

Review at 20:00 IST daily (`/status` reads this). P = probability, I = impact (H/M/L). A risk whose **trigger** fires gets its mitigation executed that day, not "tomorrow".

| # | Dimension | Risk | P | I | Mitigation (pre-planned) | Trigger | Owner |
|---|---|---|---|---|---|---|---|
| 1 | Eligibility | Team not registered by Oct 11 | M | H | Register tonight, screenshot confirmation | Not done by Oct 11 12:00 IST | Both |
| 2 | Eligibility | "Working professionals only" — apprentice/teammate status questioned | L | H | Email support+aibuildercup@hack2skill.com now; keep the reply | No reply by Oct 14 → follow up | A |
| 3 | Compliance | Freshness rule: reused code or employer/startup terminology spotted | L | H | Public repo created Oct 10, dated commits, `/data-audit` grep before freeze, no copied code from reference repo | Any grep hit | B |
| 4 | Licence | A dataset turns out non-commercial or unlicensed | L | M | DATA_SOURCES register checked today; re-check on download; R-set degrades gracefully if one source is dropped | Licence page differs from register | B |
| 5 | Data | MIMII/IMS downloads too large or slow | M | M | `remotezip` for MIMII; one IMS test set; start downloads Sat night | Not finished by Sun noon → drop IMS (R015–R017), keep MIMII subset | B |
| 6 | Data | R-set mapping looks contrived (units, rates) to an engineer-judge | M | M | Inspection report first; provenance chips show source rows and transforms; honest "mapped" wording | Judge-review flags it | B |
| 7 | Technical | Pinned model ID wrong or Pro preview unavailable / throttled | M | M | Phase 0 live check; Flash fallback built in; JUDGE_MODEL env switch | Smoke test fails or >20% 429s | A |
| 8 | Technical | ADK API differs from our spec | M | M | Fetch adk.dev before coding; event-mapper isolates UI from ADK internals | First ADK error that contradicts docs | A |
| 9 | Technical | SSE stream cut by proxy/timeout | M | H | 900 s timeout, 15 s heartbeats, direct Cloud Run URL (no Hosting rewrite), reconnect + replay offer | Any stream ends without `done` | A |
| 10 | Quality | S1 doesn't beat B1 (the naive single prompt) | M | H | Read failures by hand on Run 20; fix tools/verifier first, prompts last; if still not, reframe around unsupported-claim rate + R-set honesty | Run-20 top-1 S1 ≤ B1 | A |
| 11 | Quality | Verifier too strict → many `insufficient_evidence` | M | M | Tolerances in config; track abstention recall; tune on dev set only | Abstention recall < 0.7 on faulted dev scenarios | A |
| 12 | Cost | Spend overruns $300 before Dec 4 | M | H | Ledger (DEVELOPMENT §7), Flash judge in dev, replay default, kill switch, budget alerts $100/200/250 | Spend > ledger line for the day, or > $150 at freeze | A |
| 13 | Schedule | Frontend late → no live demo | M | H | Built against fixture stream from day 1; fallback = SPA served from FastAPI | Not streaming live by Wed 18:00 | B |
| 14 | Schedule | One person blocked/unavailable a day | M | M | Handoff notes; both full-stack; cut list | Missed handoff | Both |
| 15 | Demo | Live call fails while recording | M | M | min-instances 1, warm-up, 3 takes, labelled replay | Any failed take | B |
| 16 | Demo | Judges test the live URL during Oct 19–Nov 6 and it's cold, broken or out of budget | M | H | Replay default (no cost), passcode for live, judging-window runbook, daily URL check by alternating person | Any failed daily check | Both |
| 17 | Judging | Seen as "RAG/chatbot wrapper" | M | H | Trace of tool cards, visible verifier rejection, eval vs B1, capability matrix, rehearsed Q&A | `/judge-review` Technical < 30/40 | Both |
| 18 | Judging | "It's all synthetic" | H | M | R-set with source labels, provenance chips, MaintIE-style WOs, OSHA-based LOTO, BYO-CSV stretch | Always — lead with it | B |
| 19 | Safety/ethics | Model paraphrases a safety step or implies autonomous action | L | H | Verbatim LOTO check, only one write tool, approval gate, tests | Any test failure | A |
| 20 | Security | Leaked key / public endpoint abused | L | H | No keys (ADC), gitleaks pre-commit, passcode + rate limit, max-instances 3 | Unusual spend or traffic | A |
| 21 | Travel | A finalist can't travel to Singapore Dec 4 (visa/leave) | L | H | Check passport validity and leave now; only 2 travel anyway | — | Both |
| 22 | Cost | ADK's own Gemini calls bypass `agents/llm.py` → no pinned-model guard, no cost ledger, no kill switch | H | H | Phase 2: `AndonBudgetPlugin` (ADK `BasePlugin` on `App(plugins=[...])`): before = pinned + `spend.check()`, after = record usage only when `not partial`; test with fake `LlmResponse`; ADR. **Built 2026-10-11 (ADR-020, `agents/adk_budget.py`)**; the graph builder must add a test that the `App` carries it | Any ADK agent runs without the plugin | A |
| 23 | Cost | Spend counter is per-process; N instances = N× daily budget | M | M | `--max-instances 1` until counter is in Firestore (Phase 3) | Raising max-instances | A |
| 24 | Latency | BigQuery tool queries take 7–16 s each (81k rows, ~25 MB billed) → a live diagnosis with ~15 tool calls would take minutes | H | H | **Decided ADR-021:** per-incident DuckDB built from that scenario's published Parquet in GCS (`simulator.publish` → `agents/store_cache.py`, `STORE_BACKEND=gcs`); BigQuery stays the system of record for the eval/analytics. Dockerfile must copy `analytics/` + `simulator/` | Any live tool call > 2 s — **mitigated 2026-10-11 (ADR-021): GCS store, tools < 0.1 s warm** | A |
| 25 | Quality | Gemini audio verdicts unreliable (live: wrong on both test clips at 0.9 confidence; flips between identical calls); MFCC AUC 0.79 overall, ~chance on slider/valve | H | M | `finding` is qualitative only; numeric audio claims use `mfcc_distance`/`mfcc_z`; results cached so the verifier is deterministic; S3 ablation (with/without listen) in the eval; never present audio as decisive in the demo | Eval shows listen lowers top-1 | A |
