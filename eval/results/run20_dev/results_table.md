**S-set · synthetic line, injected truth** (95% Wilson intervals; failed runs count as misses)

| System | n | Top-1 [95% CI] | Top-3 | Unsupported claims | Median time (s) | $/run |
|---|---|---|---|---|---|---|
| S1 full pipeline (Flash judge) | 20 | 0.70 [0.48, 0.85] | 0.85 | 0.00 (0/155) | 93.5 | 0.129 |
| B1 single prompt | 20 | 0.90 [0.70, 0.97] | 0.90 | 0.09 (16/177) | 40.3 | 0.093 |
| B2 classical | 20 | 0.20 [0.08, 0.42] | 0.20 | n/a | 0.4 | 0.000 |

- S1 vs B1 top-1, exact McNemar: S1-only right 0, B1-only right 4, p = 0.125 (not significant)

- S1 vs B2 top-1, exact McNemar: S1-only right 11, B2-only right 1, p = 0.006

- S-set S1 vs B1: not significant (discordant 0/4, exact McNemar p = 0.125); do not claim a difference.
- S1 does not beat B1 on S-set top-1: stop and fix before freeze, or say so plainly (EVAL_PLAN §9).
