# Test fixtures

- `sample_stream.jsonl` — a **hand-written** event stream for an R002-style real-signal air-leak
  incident, used by the frontend before the live API exists and by contract tests. Telemetry
  values are illustrative, not the output of a real run. The manual quotes are **verbatim** from
  `simulator/manuals/compressed_air.md` on the stated pages (diagnostic notes on p.15, LOTO steps
  on pp.21–22), so the verifier's citation rule passes on them; `tests/test_manuals.py` checks
  every citation in the stream with `simulator.manuals.find_quote`. If the manuals are rebuilt and
  a page moves, that test fails: update the pages here.

- `llm/<scenario>/` — **recorded** model responses of live runs (`uv run python -m agents.cli
  --scenario <id> --record`): `adk_<agent>.json` (final ADK model responses per agent, function-call
  ids stripped), `generate_<ResponseSchema>.json` (`LLM.generate` responses), `meta.json` (judge
  model, cost, verifier verdicts, final status). `--mode replay` and `tests/test_graph.py` replay
  them through the real graph and tools against `data/andon.duckdb` ($0). Re-record after a tool
  change that alters evidence (replay diverges otherwise).
- `llm/_templates/S801_air/` — **hand-written** fixture for the CI-safe end-to-end test. `$STOP-<s>`
  and `$EV{<evidence_id>:<path>}` placeholders are resolved by `tests/llm_replay.py` against a
  store built in tmp, so values always match the data.
