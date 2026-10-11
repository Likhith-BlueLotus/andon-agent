**S-set · synthetic line, injected truth** (95% Wilson intervals; failed runs count as misses)

| System | n | Top-1 [95% CI] | Top-3 | Unsupported claims | Median time (s) | $/run |
|---|---|---|---|---|---|---|
| S1 full pipeline (Flash judge) | 60 | 0.93 [0.84, 0.97] | 0.95 | 0.00 (0/453) | 99.8 | 0.112 |
| S2 no verifier (Flash judge) | 60 | 0.97 [0.89, 0.99] | 0.98 | 0.00 (0/452) | 91.1 | 0.108 |
| B1 single prompt | 60 | 0.92 [0.82, 0.96] | 0.95 | 0.08 (40/501) | 43.3 | 0.092 |
| B2 classical | 60 | 0.15 [0.08, 0.26] | 0.15 | n/a | 0.4 | 0.000 |

- S1 vs S2 top-1, exact McNemar: S1-only right 2, S2-only right 4, p = 0.688 (not significant)

- S1 vs B1 top-1, exact McNemar: S1-only right 5, B1-only right 4, p = 1.000 (not significant)

- S1 vs B2 top-1, exact McNemar: S1-only right 47, B2-only right 0, p = 0.000

**R-set · real signals on the synthetic line** (95% Wilson intervals; failed runs count as misses)

| System | n | Top-1 [95% CI] | Top-3 | Unsupported claims | Median time (s) | $/run |
|---|---|---|---|---|---|---|
| S1 full pipeline (Flash judge) | 17 | 0.59 [0.36, 0.78] | 0.82 | 0.01 (1/116) | 90.8 | 0.114 |
| S2 no verifier (Flash judge) | 17 | 0.71 [0.47, 0.87] | 0.94 | 0.03 (4/127) | 79.3 | 0.108 |
| B1 single prompt | 17 | 0.59 [0.36, 0.78] | 0.88 | 0.10 (14/144) | 55.0 | 0.097 |
| B2 classical | 17 | 0.24 [0.10, 0.47] | 0.24 | n/a | 0.4 | 0.000 |

- S1 vs S2 top-1, exact McNemar: S1-only right 0, S2-only right 2, p = 0.500 (not significant)

- S1 vs B1 top-1, exact McNemar: S1-only right 2, B1-only right 2, p = 1.000 (not significant)

- S1 vs B2 top-1, exact McNemar: S1-only right 8, B2-only right 2, p = 0.109 (not significant)

- S-set S1 vs S2: not significant (discordant 2/4, exact McNemar p = 0.688); do not claim a difference.
- S-set S1 vs B1: not significant (discordant 5/4, exact McNemar p = 1.000); do not claim a difference.
- R-set S1 vs S2: not significant (discordant 0/2, exact McNemar p = 0.500); do not claim a difference.
- R-set S1 vs B1: not significant (discordant 2/2, exact McNemar p = 1.000); do not claim a difference.
- R-set S1 vs B2: not significant (discordant 8/2, exact McNemar p = 0.109); do not claim a difference.
- S1: 2 failed run(s) counted as misses.
- S2: 1 failed run(s) counted as misses.
