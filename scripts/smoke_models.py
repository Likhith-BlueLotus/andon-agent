"""Live smoke test: one tiny call to each pinned model through agents/llm.py. Costs < $0.01.

Usage: GOOGLE_CLOUD_PROJECT=<id> uv run python scripts/smoke_models.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from google.genai import types

import config
from agents.llm import LLM, SpendTracker

PROMPT = "Reply with the single word: ready"


async def main() -> int:
    if not config.PROJECT:
        print("set GOOGLE_CLOUD_PROJECT")
        return 2
    llm = LLM(spend=SpendTracker(daily_budget_usd=0.25), max_retries=1)
    # LOW thinking keeps it cheap; no temperature/top_p/top_k for Gemini 3.
    cfg = types.GenerateContentConfig(
        thinking_config=types.ThinkingConfig(thinking_level="LOW"), max_output_tokens=256
    )
    models = [config.FLASH, config.FLASH_LITE, config.PRO_JUDGE, config.RESIDENCY_FLASH]
    failed = 0
    print(
        f"{'model':28} {'location':12} {'ms':>6} {'in':>5} {'out':>5} {'think':>5} {'usd':>9}  text"
    )
    for m in models:
        try:
            r = await llm.generate(m, PROMPT, cfg, agent="smoke")
            u = r.usage
            text = (r.response.text or "").strip()[:20]
            print(
                f"{m:28} {config.location_for(m):12} {r.latency_ms:6d} {u.input_tokens:5d} "
                f"{u.output_tokens:5d} {u.thinking_tokens:5d} {u.usd:9.6f}  {text}"
            )
        except Exception as exc:
            failed += 1
            print(f"{m:28} {config.location_for(m):12} FAILED: {type(exc).__name__}: {exc}")
    print(f"total: ${llm.spend.spent_today():.6f}  failed: {failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
