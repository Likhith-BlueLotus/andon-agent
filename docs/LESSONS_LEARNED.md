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
