# Lessons learned (append-only)

Template — copy for each entry:

### YYYY-MM-DD HH:MM — <short title> (phase N, person A/B)
- **What happened:**
- **Root cause:**
- **Fix:**
- **Do differently / rule added:**
- **Cost (time / $):**

### 2026-10-10 23:40 — Latest fastapi conflicts with google-adk (phase 0, person A)
- **What happened:** `uv sync` failed: fastapi 0.143 needs opentelemetry-api ≥1.44, google-adk 2.11 pins ≤1.42.1.
- **Root cause:** pinning every package to "latest" ignores the framework's own upper bounds.
- **Fix:** fastapi floor at 0.133; resolver picked 0.141.1.
- **Do differently / rule added:** pin ADK + genai first, let them constrain the web stack.
- **Cost (time / $):** 5 min / $0.

### 2026-10-10 23:40 — Docs drift found in Phase 0 verification (phase 0, person A)
- **What happened:** genai env var renamed (`GOOGLE_GENAI_USE_ENTERPRISE`), real Flash/Flash-Lite prices higher than first guesses (Flash $0.75/$3.75, Flash-Lite $0.25/$1.50 per 1M), cache minimum wording ambiguous for 3.8 Flash.
- **Fix:** TECH_STACK.md + config.py updated; ADR-015.
- **Do differently / rule added:** budget maths only from `config.PRICES`, never from memory.
- **Cost (time / $):** 3 min agent research / $0.

### 2026-10-10 23:50 — ruff 0.17 reformatted Python blocks inside docs (phase 0, person A)
- **What happened:** `ruff format .` rewrote the contract code block in docs/ARCHITECTURE.md.
- **Root cause:** ruff ≥0.17 formats fenced Python in Markdown by default.
- **Fix:** reverted; `*.md` added to `extend-exclude` in ruff.toml.
- **Do differently / rule added:** after any formatter run, `git status docs/` before committing.
- **Cost (time / $):** 3 min / $0.

### 2026-10-11 00:00 — Budget create failed: INR billing account (phase 0, person A)
- **What happened:** `gcloud billing budgets create --budget-amount=300USD` → INVALID_ARGUMENT.
- **Root cause:** budget currency must match the billing account (INR). Also, default budgets net out credits, so alerts would never fire while the $300 credit lasts.
- **Fix:** ₹26,500 budget, `--credit-types-treatment=exclude-all-credits`, project *number* in the filter; bootstrap.sh now detects currency.
- **Do differently / rule added:** read `currencyCode` before any money config.
- **Cost (time / $):** 5 min / $0.

### 2026-10-11 00:30 — Cloud Run returned 404 for /healthz (phase 0, person A)
- **What happened:** first deploy served `/docs` fine but `/healthz` returned a Google-branded 404.
- **Root cause:** Cloud Run's front end reserves URL paths ending in `z` (`/healthz` never reaches the container).
- **Fix:** health endpoint is `/health`; all docs/commands updated. Also: new projects' default compute SA can't read the source bucket → dedicated `andon-build@` SA via `--build-service-account`.
- **Do differently / rule added:** no route may end in `z`.
- **Cost (time / $):** 10 min / ~$0.

### 2026-10-11 00:45 — Dataset fetch: throttled UCI connection, RAR-in-zip IMS, dead IMS tail (phase 1, data)
- **What happened:** the UCI hydraulic zip crawled at ~25 KB/s on one connection while fresh connections got >1.5 MB/s (UCI ignores HTTP Range, so no resume). NASA `IMS.zip` turned out to be a zip of per-test RARs. The last 2 snapshots of IMS test 2 are flat (rig stopped). MetroPT-3 is 0.1 Hz with ~18% gaps.
- **Root cause:** per-connection server throttling; archive layout not documented on the catalogue page; source data quirks.
- **Fix:** `download()` drops and reopens a connection under 64 KB/s for 60 s; IMS fetch range-extracts only `2nd_test.rar` (85.6 MB, not 1.07 GB) with `remotezip` and unpacks it with bsdtar; inspection uses the last *live* IMS snapshot. Details in `docs/data_inspection.md`.
- **Do differently / rule added:** list remote archives with `remotezip` before downloading anything big; never trust a dataset's last sample to be live.
- **Cost (time / $):** ~15 min / $0.

### 2026-10-11 — S-set generator: Parquet size, async genai client, square-wave signals (phase 1, data)
- **What happened:** (1) first telemetry Parquet was 49 MB/scenario (≈3 GB for 60); 68% of it was the `ts` column. (2) The second Flash-Lite call in one process died with `RuntimeError: Event loop is closed`. (3) The simulator's own QA detector missed the air-leak root signature and fired on reject-rate noise.
- **Root cause:** (1) pyarrow defaults to PLAIN/dictionary for int64 timestamps; (2) the google-genai `aio` client binds to the event loop of its first call, so `asyncio.run()` per call breaks; (3) compressor current is a load/unload square wave and reject rate is a binomial rolling %, so 1-min bins and MAD sigma are wrong for both.
- **Fix:** `ts` written with `DELTA_BINARY_PACKED`, `value` dictionary-encoded (values are quantised to sensor resolution) → 9.9 MB/scenario. `TextGen.run()` keeps one persistent loop. `simulator/qa.py` uses per-signal bin widths (10 min for duty-cycle signals, 15 min for spread) and a sigma floor at the sensor resolution.
- **Do differently / rule added:** measure per-column Parquet sizes before choosing a layout; never call `asyncio.run` twice around one genai client; the change-point tool (Phase 2) must use duty-cycle aggregation for UT-AIR current/pressure, or it will miss leaks.
- **Cost (time / $):** ~30 min / $0.

### 2026-10-11 — Manuals: explicit cache on 3.8 Flash confirmed; genai client GC; prose guardrails (phase 1, data)
- **What happened:** (1) Explicit `caches.create` on `gemini-3.8-flash` (`global`, TTL 120 s) with the 5 manuals succeeded: 50,142 tokens cached; a follow-up `generateContent` with `cached_content` reported `cached_content_token_count=50,142` of 50,162 input tokens ($0.0038 for that call); cache deleted, `caches.list()` empty. `count_tokens` for the 5 manuals = 50,135. (2) `genai.Client(...).models.count_tokens(...)` written as one expression failed with `RuntimeError: Cannot send a request, as the client has been closed`. (3) First Gemini drafts of manual prose were rejected by our validator: a glossary used "lockout", one invented a number (50), and the brand filter flagged "carrier" (a conveyor part carrier, not the brand).
- **Root cause:** (1) docs wording for 3.8 Flash explicit caching was ambiguous; it works. (2) the Client closes its httpx pool when garbage-collected, which can happen before the request when no reference is held. (3) LLMs copy component names ("cell air lockout valve") and fill gaps with plausible numbers.
- **Fix:** keep a reference to the client; manual prose is validated (numbers must appear in the facts, no lockout/tagout wording, no brand names, no Markdown) with up to 3 attempts, and only accepted output is cached; "carrier" removed from the brand list. LOTO text never comes from an LLM (`simulator/manuals/loto.py`).
- **Do differently / rule added:** always bind `genai.Client` to a variable for its lifetime; validate generated text against the facts before caching it; keep generic engineering words out of brand deny-lists.
- **Cost (time / $):** ~15 min / $0.15 prose + ~$0.04 cache probe (creation billed as input; not visible to `agents/llm.py`).

### 2026-10-11 — R-set: label leaks through provenance, a wrong cycle table, slow pytest diffs (phase 1, data)
- **What happened:** (1) The first R-set provenance spelled out UCI cycle labels ("cooler 3 %…") and MIMII paths contain `normal/` / `abnormal/`; provenance is agent-visible, so it would have handed the agent the answer. (2) `docs/data_inspection.md` listed cycles 1664–1673 as the stable healthy UCI cycles; their stable flag is 1. (3) Two test runs hung for 10+ min. (4) `df.transform.str` raised `'function' object has no attribute 'str'`.
- **Root cause:** (1) "record the source exactly" and "never show the label" pull in opposite directions. (2) Hand-read table. (3) pytest's assertion rewriting renders a diff for `assert x not in huge_string` (and a test had an O(n²) `min(set)` inside a comprehension). (4) `transform` is a DataFrame method, so the column needs `df["transform"]`.
- **Fix:** visible provenance names rows/cycles/files plus a SHA-256 prefix and withholds labels and source dates; labels live in `sim_meta.json` / `audio_truth.json`; a test scans R visible files for cause names and source-label words. Cycle ranges are now asserted against `profile.txt` in a test. Leak tests compute hits first and assert on the list.
- **Do differently / rule added:** every new visible field gets a leak test; derive dataset facts in code and test them, not just in prose; never `assert a not in <MB-sized str>` in pytest.
- **Cost (time / $):** ~25 min / $0.009 Flash-Lite (18 note calls).

### 2026-10-11 — ADK 2.11 surprises: deprecated workflow agents, plugin errors, cached-content rules (phase 2, person A)
- **What happened:** (1) `SequentialAgent`, `ParallelAgent` and `LoopAgent` are `@deprecated` in ADK 2.11 "in favor of Workflow" (adk.dev: template workflows "superseded" by graph/dynamic workflows in Python and Go). They still work, with `DeprecationWarning`s. (2) A `before_model_callback` that returns an error `LlmResponse` does **not** stop a run: the `SequentialAgent` moves on to the next sub-agent (which then crashed on a missing `{plan}` state key); setting `end_invocation` in the callback doesn't propagate to the parent either. Raising does stop it — ADK logs the traceback and re-raises as `RuntimeError("Error in plugin ...")` with the original chained. (3) Under SSE, ADK's partial chunks carry `usage_metadata` too; only the final aggregated (non-partial) response has the turn total. The aggregated final in our fake had `partial=None`, the real aggregator sets `False` — test `if partial`, not `partial is False`. (4) Whether `output_schema` + `tools` work natively is decided from the **environment** (`GOOGLE_GENAI_USE_ENTERPRISE`), not from `Gemini(client_kwargs=...)`; without it ADK silently falls back to a `set_model_response` tool. (5) Live: a request with `cached_content` plus `system_instruction` or `tools` → `400 INVALID_ARGUMENT: Tool config, tools and system instruction should not be set in the request when using cached content.` (6) ADK ships an experimental `google.adk.models.FallbackModel` (429/5xx only, not timeouts); it rewrites `llm_request.model` to the delegate that answered. (7) Two `ParallelAgent` branches whose tools read-modify-write one `state["evidence"]` dict lose updates (only the Librarian's evidence survived in a fake-model run); flat keys `evidence:<id>` all survive. (8) Thinking level is a request setting in ADK (`generate_content_config.thinking_config` or a `BuiltInPlanner`), not a `Gemini` field.
- **Root cause:** ADK 2.0 moved orchestration to the `Workflow`/node runtime; the old agents are shims. Gemini's cached-content API requires instructions/tools to live in the cache.
- **Fix:** `AndonBudgetPlugin` raises (`run_error()` maps the chain to an SSE code); books only `not partial`; `make_model()` sets `GOOGLE_GENAI_USE_ENTERPRISE=true` if unset and carries the thinking level on a `PinnedGemini` subclass; the manuals cache is used only by direct `LLM.generate` calls (`cite_manual`), with any system instruction baked into the cache (it is part of the content hash). Explicit cache create → reuse → delete verified live on 3.8 Flash (50,135 tokens; next call billed all 50,135 as cached, `saved_usd` $0.0338).
- **Do differently / rule added:** spike ADK behaviour with a fake `BaseLlm` in a real `Runner` before designing around a callback; keep the graph on the deprecated workflow agents for the hackathon (stable, documented, matches ADR-003) and pin `google-adk<3`; never pass `system_instruction`/`tools` with `cached_content`; never share one mutable dict key across parallel branches.
- **Cost (time / $):** ~40 min / $0.043 live cache test + $0.003 restriction probe (Flash-Lite, one manual).

### 2026-10-11 — Analytics tools: slow ruptures, daily patterns, ADK declarations, BigQuery fetch (phase 2, data)
- **What happened:** (1) `ruptures.Pelt(model="l2")` took 1.2 s for 1,000 points and 23 s for 4,000. (2) First calibration: only 62–88 % of clean windows had ≤1 change point (day/night duty, ambient temperature, tip-dress sawtooth, recipe changes at shift start, reject-rate binomial steps); a two-pass "steps then daily profile" let the step model absorb the daily pattern. (3) R002's real continuous loading starts at 17:43Z, ~17 min before the failure report's 18:00Z; a MAD-based CUSUM put it at 17:14 because the motor-off baseline has MAD 0. (4) ADK 2.11 (JSON-schema declarations on) builds the declaration from the function's real parameters: a `**kwargs` closure with `__signature__` produced an empty schema. (5) BigQueryStore returned identical change points to DuckDB but needed 7.5 s for 81k rows and ~10 s for a 7-day tag (467k rows) over REST, scanning 24 MB per query (no `scenario_num` partition filter). (6) A scripted `s.replace(s[a:b], new)` with an empty slice (marker found earlier in the file than expected) inserted text between every character of a file.
- **Root cause:** pure-Python segment costs in ruptures; normal plant patterns are not faults but are real changes; zero-spread baselines; ADK introspects code objects, not `__signature__`; REST row paging without the Storage Read API; unchecked slice bounds.
- **Fix:** own PELT with cumulative sums (identical breakpoints to ruptures, tested), time-of-day profile from 7 days of history after removing each day's median, minimum effect (t ≥ 5 and ≥ 8 % of normal span, per-tag floors), excursion/ramp grouping, `at_changeover` flag, Page reference value (¼ step) in the CUSUM; 100 % / 100 % / 97.7 % of clean 6 h / 24 h / 7 d windows now give ≤1 change point (`scripts/calibrate_change_points.py`). Tool functions for ADK are generated with explicit typed parameters.
- **Do differently / rule added:** calibrate detectors on normal data before trusting them; assert slice bounds before replace-by-slice; for BigQuery at 1 Hz either add `google-cloud-bigquery-storage` (Arrow streaming) plus a `scenario_num` partition filter, or keep DuckDB over Parquet for the API.
- **Cost (time / $):** ~2 h / <$0.01 (BigQuery spot checks).

### 2026-10-11 — Verifier: stuck values inside change points, sign of change, parquet patching (phase 2, agents)
- **What happened:** (1) On S801 (seed 2026801) `detect_change_points(ST10-PRS, oil_temp_c)` reports two change points around a 2.6 h stuck value; only the one at the stuck *end* carries `data_issue`, the one ~70 min *inside* the stuck period (after_mean = the stuck value) is unflagged. (2) That same unflagged change point has `direction: "up"` with a negative `delta` (-1.11), so `direction` and the sign of `delta` can disagree. (3) Rewriting a scenario's `provenance.parquet` through pandas changed `string` to `large_string` and `load_duckdb`'s `concat_tables` refused to merge it.
- **Root cause:** the tool flags change points within one bin of stuck-period edges only; direction presumably comes from the de-seasonalised signal while the means are raw; pandas round-trips Arrow strings as large strings.
- **Fix:** the Verifier also treats a change point whose onset lies inside a reported stuck period as a data artefact; sign relaxation reads the claim's direction words against the *value's* sign, never against `direction`; the test writes the patched table back with the original Arrow schema.
- **Do differently / rule added:** claims about a change must cite the number (`delta`, `magnitude_pct`) with `path:`, not the `direction` label. (2) is worth a look by the analytics owner.
- **Cost (time / $):** ~0.5 h / $0.

### 2026-10-11 — Change point said "up" with a negative delta (phase 2, person A)
- **What happened:** the verifier agent saw `direction: "up"` with `delta < 0`.
- **Root cause:** PELT segments and the direction use the de-seasonalised series; `before/after_mean` and `delta` are raw. A step during a falling daily profile is "up vs normal" but "down" raw (53 of 69 cases in a sweep).
- **Fix:** reported direction follows the reported raw delta; robust direction only steers onset refinement. Unit test reproduces the case (fails before, passes after).
- **Do differently / rule added:** a regression test must be shown failing on the old code before the fix counts.
- **Cost (time / $):** 20 min / $0.

### 2026-10-11 — `listen`: Gemini cannot reliably hear MIMII 6 dB anomalies; MFCC can (phase 2, data/ML)
- **What happened:** live sanity check on two dev clips (S014 ST40-SLR, whose recent clip is abnormal; S002 ST40-SLR, normal). `gemini-3.8-flash` inverted both verdicts at confidence 0.9. A repeat of the S014 request said `abnormal: true`, so the verdict flips between identical calls. The MFCC baseline got both right (distance 2.41 / z 11.3 vs 1.23 / z -0.27). Latency was 41 s and 67 s for the first two calls, then 4-5 s for identical-size calls minutes later.
- **Root cause:** MIMII abnormal pump/slider/valve sounds at 6 dB SNR are subtle against factory noise (data_inspection §4); a general audio model describes "steady hum" either way. The latency spike looks transient on the service side: the same request took 4.5 s soon after, and gs:// vs inline bytes made no difference (3.7 s vs 5.4 s).
- **Fix:** `listen` caches the first answer per (clip SHA, reference SHA, machine type, prompt version, model) so reruns and the Verifier are deterministic. It always returns the code-computed `mfcc_distance`/`mfcc_z` next to Gemini's opinion. It bounds Gemini at 25 s per attempt and 45 s total, then returns the MFCC part alone (`gemini_status="timeout"`). The rubric was **not** tuned on labels (held-out discipline).
- **Do differently / rule added:** treat `listen.finding` as qualitative and unverified. Numeric audio claims must cite `mfcc_distance`/`mfcc_z`. Classical MFCC separation is strong for pump/fan (AUC 0.97/0.88 on S001-S050 + R) and near chance for slider/valve (0.62/0.63), so the Judge should weigh audio for those two lightly.
- **Cost (time / $):** ~2.5 h / ~$0.013 (6 Flash calls).

### 2026-10-11 — Phase 2 graph live: slow Flash-HIGH judge, loop-blocking tools, racing evidence ids (phase 2, agents)
- **What happened:** (1) First full R002 run took 332 s: the Flash judge at thinking HIGH spent 15k thinking tokens, hit the 120 s per-attempt timeout once and was retried (206 s for one judgement). (2) A sync tool that waits on Gemini (`listen`, 65 s) blocked the event loop, so the *other* ParallelAgent branch's Flash-Lite triage showed 74 s latency. (3) Turning on `RunConfig.tool_thread_pool_config` fixed the blocking but made parallel function calls of one model turn finish in random order, so `ev_<tool>_<n>` ids changed between runs and a replayed judge cited the wrong evidence (verifier FAIL in replay, PASS live). (4) In record/replay mode the run's `cost` missed `listen`'s Gemini call, which books to the process-wide `get_llm()`.
- **Root cause:** HIGH thinking on Flash over a ~16k-token evidence prompt; ADK runs sync function tools on the loop thread unless the thread pool is configured; evidence ids are assigned when a tool *finishes*; two LLM ledgers.
- **Fix:** a Flash *primary* judge runs MEDIUM (Pro stays HIGH) → judge ~30 s, full runs 78–95 s. Sync tools are wrapped as async twins that run in a worker thread under a per-agent FIFO lock (dispatch order → deterministic ids; the other branch keeps running); `cite_manual` reserves its id before awaiting. The `cost` event merges the app ledger and `get_llm()` for the invocation.
- **Do differently / rule added:** replay determinism is a requirement: anything that assigns ids must do it in dispatch order, never completion order; never enable ADK's tool thread pool in this graph; every tool that calls Gemini must take its LLM/run id from the run, not a global.
- **Cost (time / $):** ~1 h / $0.73 live (skeleton $0.10, R002 $0.17, S005 $0.15, S010 $0.15, R002 forced $0.19; Flash judge).

### 2026-10-11 — CI red for 4 pushes unnoticed (phase 2, person A)
- **What happened:** CI failed on edb20a3…74c5eb5: (1) a partial commit (`listen` imported the uncommitted `agents/prompts/__init__.py`); (2) gitleaks flagged `"key": "<sha256 prefix>"` in listen cache files; (3) one unformatted test.
- **Root cause:** committing one agent's files while another agent's shared module was still uncommitted; a content-hash field named `key`; not checking CI after each push.
- **Fix:** field renamed to `content_hash`; the 4 historical fingerprints (each inspected) in `.gitleaksignore`; full-history gitleaks clean (Docker `zricethezav/gitleaks:v8.24.3`).
- **Do differently / rule added:** before committing a subset, test it in a clean worktree (`git worktree add` + apply the staged diff); check `gh run list` after every push; never name a hash field `key`/`token`/`secret`.
- **Cost (time / $):** 25 min / $0.

### 2026-10-11 — API streaming and tests (phase 3, person A)
- **What happened:** `httpx.ASGITransport` and `TestClient` buffer the whole response, so they cannot show incremental SSE or a disconnect. Starlette cancels the response generator with an anyio cancel scope, where any `await` in `finally` is cancelled again, so an "audit the cancellation" write after a disconnect never ran.
- **Fix:** streaming and disconnect tests drive the ASGI app directly (`Stream` in `tests/test_api.py`: queue-based `send`, `http.disconnect` on demand); the audit writer is a background task outside the request scope, `finally` only enqueues and cancels the producer (no await).
- **Also:** the committed `tests/fixtures/sample_stream.jsonl` work order has a step ("release-from-lockout") that the drafter post-check rejects as an unmarked safety step; the API tests reword it. Person B's mocks should not show that text as a verified work order. DuckDB `fetchall()` on `timestamptz` needs `pytz`; cast to VARCHAR in SQL instead of adding a dependency.
- **Cost (time / $):** live R002 run through the API $0.148, 87 s.


### 2026-10-11 — Phase 3 deploy findings (phase 3, person A)
- **What happened:** (1) after a private redeploy, anonymous `/health` still returned 200 for ~1–2 min; (2) `smoke.sh` failed on the real API (assumed S001 had a replay; mis-counted `/api/scenarios`); (3) the kill-switch test on Cloud Run refused the live run correctly, but `/api/config` still said `exhausted: false` — a fresh instance had never refreshed the shared Firestore spend.
- **Root cause:** (1) Cloud Run IAM changes propagate asynchronously; (2) the script was written against a fake server; (3) `/api/config` read the cached shared total, refreshed only by live-run checks.
- **Fix:** (1) wait and re-check before trusting "private"; (2) smoke picks the first run from `/api/replays` and counts scenarios across groups; (3) `/api/config` calls `refresh_if_stale()` (30 s, off-loop, never raises); regression test failed first.
- **Do differently / rule added:** every exit criterion is tested against the deployed URL, not only locally; a script is "done" only after it has passed against the real service.
- **Cost (time / $):** 30 min / $0.33 (two live runs on Cloud Run).
