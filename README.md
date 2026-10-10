Theme: Manufacturing: Intelligent Operations & Industrial Efficiency

# Andon Agent

When an automotive assembly line stops, Andon Agent investigates like a reliability engineer: it plans checks, runs analytics on telemetry and machine sound, cites the manual, has code verify every claim, and hands a human a verified root cause plus a safety-gated draft work order.

> **Status:** under construction (AI Builder Cup 2026). Live URL, video and deck links land here by Oct 17.

**Data honesty:** synthetic assembly line with real public signals mapped onto it, each one marked with its provenance. This is not real plant data. Dataset licences and citations: `docs/DATA_SOURCES.md`, `data/SOURCES.md`.

## Run locally
```bash
uv sync
uv run pytest -q
uv run uvicorn api.main:app --reload --port 8080
```

Code licence: MIT.
