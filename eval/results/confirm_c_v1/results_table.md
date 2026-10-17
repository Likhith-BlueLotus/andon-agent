**C-set · pre-registered confirmation, real signals (unused source segments)** (95% Wilson intervals; failed runs count as misses)

| System | n | Top-1 [95% CI] | Top-3 | Unsupported claims | Median time (s) | $/run |
|---|---|---|---|---|---|---|
| S1 full pipeline (Flash judge) | 10 | 0.40 [0.17, 0.69] | 0.90 | 0.00 (0/80) | 130.7 | 0.131 |
| B1 single prompt | 10 | 0.20 [0.06, 0.51] | 0.70 | 0.07 (6/91) | 64.1 | 0.103 |
| B2 classical | 10 | 0.00 [0.00, 0.28] | 0.00 | n/a | 0.3 | 0.000 |

- S1 vs B1 top-1, exact McNemar: S1-only right 2, B1-only right 0, p = 0.500 (not significant)

- S1 vs B2 top-1, exact McNemar: S1-only right 4, B2-only right 0, p = 0.125 (not significant)

- C-set S1 vs B1: not significant (discordant 2/0, exact McNemar p = 0.500); do not claim a difference.
- C-set S1 vs B2: not significant (discordant 4/0, exact McNemar p = 0.125); do not claim a difference.
