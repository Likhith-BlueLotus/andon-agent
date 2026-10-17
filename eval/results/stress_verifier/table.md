# Verifier fault injection (offline, $0, no Gemini)

Source run: `final_v2` (77 S1 runs with a report, 2778 injected faults, seed 2026). Caught = the mutated claim's verdict is `fail` or `unverifiable` (struck through in the UI). 95% Wilson intervals; trials are clustered by run, so read the intervals as optimistic.

| Fault | n | Caught [95% CI] | fail | unverifiable | missed |
|---|---:|---|---:|---:|---:|
| Number off by ±10% | 488 | 100.0% [99.2, 100.0] | 488 | 0 | 0 |
| Number off by ±25% | 488 | 100.0% [99.2, 100.0] | 488 | 0 | 0 |
| Number sign flipped | 244 | 92.6% [88.6, 95.3] | 226 | 0 | 18 |
| Timestamp shifted ±15 min | 238 | 98.3% [95.8, 99.3] | 234 | 0 | 4 |
| Timestamp shifted ±2 h | 238 | 99.6% [97.7, 99.9] | 237 | 0 | 1 |
| Quote with one word altered | 80 | 100.0% [95.4, 100.0] | 80 | 0 | 0 |
| Quote cited on the wrong page | 80 | 100.0% [95.4, 100.0] | 80 | 0 | 0 |
| Quote from another manual | 65 | 100.0% [94.4, 100.0] | 65 | 0 | 0 |
| Causal order reversed | 10 | 100.0% [72.2, 100.0] | 10 | 0 | 0 |
| Claim cites a non-existent evidence id | 231 | 100.0% [98.4, 100.0] | 231 | 0 | 0 |
| Quote with false premise (by construction) | 616 | 90.6% [88.0, 92.7] | 319 | 239 | 58 |
| **All faults** | 2778 | **97.1% [96.4, 97.7]** | | | 81 |

False-alarm rate on the unmutated claims: 1.4% [0.7, 2.7] of all claims (8/586); 1.6% [0.8, 3.1] of checkable claims (8/498). Baseline verdicts equal `eval/checker.py` on 586/586 claims.

S2 comparison: S2 shows every claim as verified (verifier always PASS), so it strikes through none of the mutated claims: catch 0%. (0/2778 caught.)

Numeric detail (caught, explicit `path:` vs implicit search over all leaves):

- Number off by ±10%: explicit path 100.0% [99.2, 100.0] (n=486), implicit 100.0% [34.2, 100.0] (n=2)
- Number off by ±25%: explicit path 100.0% [99.2, 100.0] (n=486), implicit 100.0% [34.2, 100.0] (n=2)
- Number sign flipped: explicit path 92.6% [88.6, 95.3] (n=243), implicit 100.0% [20.6, 100.0] (n=1)

Why the misses passed (grouped, numbers and timestamps removed):

- Number sign flipped:
  - 4 x <ev>:tags.air_pressure_bar.min = # matches # (rel err #) (sign from direction words)
  - 3 x <ev>:tags.air_pressure_bar.mean = # matches # (rel err #) (sign from direction words)
  - 2 x <ev>:tags.header_pressure_bar.min = # matches # (rel err #) (sign from direction words)
  - 2 x <ev>:tags.hyd_pressure_bar.mean = # matches # (rel err #) (sign from direction words)
  - 2 x <ev>:tags.flow_rate_ccm.mean = # matches # (rel err #) (sign from direction words)
  - 2 x <ev>:tags.header_pressure_bar.mean = # matches # (rel err #) (sign from direction words)
  - 1 x <ev>:change_points[#].magnitude_pct = # matches # (rel err #) (sign from direction words)
  - 1 x <ev>:tags.air_pressure_bar.pct_outside_normal = # matches # (rel err #) (sign from direction words)
- Timestamp shifted ±15 min:
  - 3 x <ts> is +# s from <ev>:rows[#].ts (<ts>)
  - 1 x <ts> is # s from <ev>:rows[#].ts (<ts>)
- Timestamp shifted ±2 h:
  - 1 x <ts> is +# s from <ev>:change_points[#].end_ts (<ts>)
- Quote with false premise (by construction):
  - 37 x quote found verbatim in press_hydraulics p.#; premises met: ST#-PRS hyd_pressure_bar changes in a step
  - 7 x quote found verbatim in press_hydraulics p.#; premises met: ST#-PRS hyd_pressure_bar falls
  - 4 x quote found verbatim in compressed_air p.#; premises met: UT-AIR oil_temp_c rises
  - 2 x quote found verbatim in compressed_air p.#; premises met: UT-AIR compressor_current_a rises
  - 2 x quote found verbatim in sealer_pump p.#; premises met: ST#-SLR flow_rate_ccm falls
  - 1 x quote found verbatim in weld_controller p.#; premises met: ST#-WLD air_pressure_bar falls (<ev>: change point 
  - 1 x quote found verbatim in sealer_pump p.#; premises met: ST#-SLR flow_rate_ccm is below its normal range
  - 1 x quote found verbatim in compressed_air p.#; premises met: UT-AIR compressor_current_a runs loaded

Limitations: the faults are synthetic and one at a time; the real error distribution of the model differs. Only claims that pass at baseline are attacked. Premise-false citations are labelled false by construction (the passage diagnoses a different cause class on assets outside the true chain and not the asset the report blames). Faults alter the structured field the verifier reads (and, for the sign flip, the direction words in the text), not free text elsewhere.
