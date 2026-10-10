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
