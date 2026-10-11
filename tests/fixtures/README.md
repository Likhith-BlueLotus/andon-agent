# Test fixtures

- `sample_stream.jsonl` — a **hand-written** event stream for an R002-style real-signal air-leak
  incident, used by the frontend before the live API exists and by contract tests. Telemetry
  values are illustrative, not the output of a real run. The manual quotes are **verbatim** from
  `simulator/manuals/compressed_air.md` on the stated pages (diagnostic notes on p.15, LOTO steps
  on pp.21–22), so the verifier's citation rule passes on them; `tests/test_manuals.py` checks
  every citation in the stream with `simulator.manuals.find_quote`. If the manuals are rebuilt and
  a page moves, that test fails: update the pages here.
