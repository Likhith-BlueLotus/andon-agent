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
