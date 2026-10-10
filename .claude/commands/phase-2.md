---
description: Phase 2 — the agentic core (tools, ADK graph, verifier loop, context cache, CLI)
argument-hint: "[tools | graph | verifier | cache | judge | all]"
---

# Phase 2 — Agents (Sun Oct 11 → Tue Oct 13 morning)

Focus: $ARGUMENTS (default: next unfinished item in the order below).

Delegate to `staff-engineer-agents`; tool maths to `senior-data-ml-engineer`. docs/AGENTS_SPEC.md is the spec. Before coding against ADK, fetch adk.dev and confirm the current class names and RunConfig/streaming API; fix the spec if it drifted.

Order of work (each step ends with a passing test and a commit):
1. **Tools** (`agents/tools.py`): `get_stop_event`, `list_assets`, `query_telemetry`, `detect_change_points`, `spectrum`, `anomaly_score`, `search_alarms`, `get_work_orders`, `get_shift_notes`. Each returns `{evidence_id, summary, provenance}` with data-quality fields and stores full `Evidence` in session state. `spectrum` reads raw GCS snapshots for real-sourced vibration. Offline tests on DuckDB: change point near onset for an S-set scenario; add the same test for R002 (real MetroPT-3 signal) as soon as the R-set lands on Tue; gaps/stuck values reported, not hidden.
2. **Graph skeleton** (`agents/graph.py`): Commander + Signal Analyst only, Flash, run via `agents/cli.py --scenario S001 --verbose`. One live run; print cost.
3. **Verifier** (`agents/verifier.py`): all rules in AGENTS_SPEC §5. Tests: true claim passes; inflated number fails with measured value; wrong timestamp fails; fabricated quote fails; reversed causal order fails; unknown evidence_id fails; a "real data" claim on synthetic evidence fails.
4. **Evidence Librarian + context cache** (`agents/cache.py`): create/reuse/GC an explicit cache of the five manuals (<200K tokens); `cite_manual` with verbatim-quote post-check; untrusted-data wrapping; Flash-Lite triage for alarm floods. Emit `cache_hit` with saved $.
5. **RCA Judge + LoopAgent**: structured output into `RCAReport`, Pydantic validation, rejected claims fed back, escalate on PASS, `insufficient_evidence` after 3. Judge model from `JUDGE_MODEL` env; Pro→Flash fallback on 429/timeout emits `model_fallback`.
6. **`listen` tool**: Gemini audio on the `gs://` clip with `agents/prompts/listen_rubric.md` + MFCC baseline number. Only if steps 1–5 are done by end of Mon Oct 12; otherwise mark cut and move on.
7. **Action Drafter** with `draft_work_order` (only write tool), verbatim safety-step check.
8. **Event mapper** (`agents/events_map.py`): ADK events → `api/events.py` events, so the API just forwards.
9. Record LLM fixtures from 3 live runs into `tests/fixtures/llm/` and add an offline end-to-end graph test using a replaying fake LLM.

Exit criterion: `agents.cli --scenario R002` (the demo scenario) and one S-set scenario each print plan → tool calls with provenance → verdicts (including at least one rejection on a seeded test where you force a bad claim) → verified RCAReport → draft WO with verbatim LOTO → cost; offline graph test green. Report per-run cost and latency for 3 scenarios against the ledger, and update LESSONS_LEARNED.
