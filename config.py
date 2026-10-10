"""Single source of truth: pinned models, regions, budgets, limits. No secrets here.

Every value can be overridden by an environment variable of the same name (see .env.example).
"""

from __future__ import annotations

import os
from dataclasses import dataclass


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


APP_VERSION = "0.1.0"
THEME = "Manufacturing: Intelligent Operations & Industrial Efficiency"

# --- GCP -------------------------------------------------------------------------------------
PROJECT = _env("GOOGLE_CLOUD_PROJECT", "")
GEMINI_LOCATION = _env("GOOGLE_CLOUD_LOCATION", "global")
APP_REGION = _env("APP_REGION", "asia-south1")
RESIDENCY_REGION = "asia-south1"
BQ_DATASET = _env("BQ_DATASET", "andon")
GCS_BUCKET = _env("GCS_BUCKET", "")
STORE_BACKEND = _env("STORE_BACKEND", "duckdb")  # duckdb | bigquery

# --- Pinned models (CLAUDE.md table). Never 1.x/2.0/2.5, never *-latest. -----------------------
FLASH = "gemini-3.8-flash"  # tool loops, planning, drafting
FLASH_LITE = "gemini-3.1-flash-lite"  # bulk triage, simulator text, claim normalisation
PRO_JUDGE = "gemini-3.1-pro-preview"  # RCA Judge (global only)
RESIDENCY_FLASH = "gemini-3.5-flash"  # residency mode (pitch only), regional

PINNED_MODELS = frozenset({FLASH, FLASH_LITE, PRO_JUDGE, RESIDENCY_FLASH})

# Development default is Flash for the judge to save credits; set to PRO_JUDGE for eval/recording.
JUDGE_MODEL = _env("JUDGE_MODEL", FLASH)
JUDGE_FALLBACK_MODEL = FLASH
JUDGE_FALLBACK_AFTER_S = 60.0
RESIDENCY_MODE = _env("RESIDENCY_MODE", "")  # "asia-south1" switches all agents to RESIDENCY_FLASH
if JUDGE_MODEL not in PINNED_MODELS:
    raise ValueError(f"JUDGE_MODEL={JUDGE_MODEL!r} is not a pinned model")


def location_for(model_id: str) -> str:
    """Gemini calls go to `global`, except the residency model which is pinned to its region."""
    return RESIDENCY_REGION if model_id == RESIDENCY_FLASH else GEMINI_LOCATION


# --- Prices (USD per 1M tokens) --------------------------------------------------------------
@dataclass(frozen=True)
class Price:
    input: float
    output: float  # thinking tokens are billed as output
    cached_input: float
    # Some models bill a higher tier above a prompt-size threshold. None = flat pricing.
    long_context_threshold: int | None = None
    input_long: float | None = None
    output_long: float | None = None
    cached_input_long: float | None = None


# Source: https://cloud.google.com/gemini-enterprise-agent-platform/generative-ai/pricing
# (checked 2026-10-10; text/image input rates, `global` endpoint unless noted).
# 3.8 Flash rises to $1.50 / $7.50 / $0.15 on 2027-01-01 — after the Dec 4 finale.
# Flash-Lite audio input is $0.50 (cached $0.05); listen() runs on Flash, so not modelled here.
# Explicit cache *storage* ($/1M tok/hour) is billed separately; see CACHE_STORAGE_USD_PER_MTOK_HOUR.
PRICES: dict[str, Price] = {
    FLASH: Price(input=0.75, output=3.75, cached_input=0.075),
    FLASH_LITE: Price(input=0.25, output=1.50, cached_input=0.025),
    PRO_JUDGE: Price(
        input=2.00,
        output=12.00,
        cached_input=0.20,
        long_context_threshold=200_000,
        input_long=4.00,
        output_long=18.00,
        cached_input_long=0.40,
    ),
    # Residency mode calls the regional endpoint: non-global rate (+10%).
    RESIDENCY_FLASH: Price(input=1.65, output=9.90, cached_input=0.165),
}

# Gemini API page rates (Vertex page did not expose them; checked 2026-10-10). Upper-bound estimate.
CACHE_STORAGE_USD_PER_MTOK_HOUR = {FLASH: 0.50, FLASH_LITE: 1.00, PRO_JUDGE: 4.50}


def price_for(model_id: str) -> Price:
    if model_id not in PRICES:
        raise KeyError(f"no price for model {model_id!r}; add it to config.PRICES")
    return PRICES[model_id]


# --- Budgets and limits ----------------------------------------------------------------------
DAILY_BUDGET_USD = float(_env("DAILY_BUDGET_USD", "8"))
BUDGET_TIMEZONE = "Asia/Kolkata"  # the "day" for the kill switch is an IST day
MAX_LLM_CALLS = int(_env("MAX_LLM_CALLS", "40"))
LLM_MAX_RETRIES = 4
LLM_BACKOFF_BASE_S = 1.0
LLM_BACKOFF_MAX_S = 20.0
LLM_TIMEOUT_S = 120.0
RETRYABLE_HTTP_CODES = frozenset({429, 500, 502, 503, 504})

# Verifier tolerances (AGENTS_SPEC §5); tuned on the dev set only.
VERIFIER_NUMERIC_REL_TOL = 0.05
VERIFIER_TEMPORAL_TOL_S = 60
VERIFIER_MAX_ITERATIONS = 3

# --- Serving ---------------------------------------------------------------------------------
ALLOWED_ORIGINS = [o for o in _env("ALLOWED_ORIGINS", "http://localhost:5173").split(",") if o]
ENABLE_STRETCH = frozenset(s for s in _env("ENABLE_STRETCH", "").split(",") if s)
