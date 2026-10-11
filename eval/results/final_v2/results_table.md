**S-set · synthetic line, injected truth** (95% Wilson intervals; failed runs count as misses)

| System | n | Top-1 [95% CI] | Top-3 | Unsupported claims | Median time (s) | $/run |
|---|---|---|---|---|---|---|
| S1 full pipeline (Flash judge) | 60 | 0.98 [0.91, 1.00] | 1.00 | 0.00 (1/456) | 81.0 | 0.107 |
| S2 no verifier (Flash judge) | 60 | 1.00 [0.94, 1.00] | 1.00 | 0.00 (2/473) | 81.6 | 0.107 |
| B1 single prompt | 60 | 0.92 [0.82, 0.96] | 0.95 | 0.08 (40/501) | 43.3 | 0.092 |
| B2 classical | 60 | 0.15 [0.08, 0.26] | 0.15 | n/a | 0.4 | 0.000 |

- S1 vs S2 top-1, exact McNemar: S1-only right 0, S2-only right 1, p = 1.000 (not significant)

- S1 vs B1 top-1, exact McNemar: S1-only right 5, B1-only right 1, p = 0.219 (not significant)

- S1 vs B2 top-1, exact McNemar: S1-only right 50, B2-only right 0, p = 0.000

**R-set · real signals on the synthetic line** (95% Wilson intervals; failed runs count as misses)

| System | n | Top-1 [95% CI] | Top-3 | Unsupported claims | Median time (s) | $/run |
|---|---|---|---|---|---|---|
| S1 full pipeline (Flash judge) | 17 | 0.76 [0.53, 0.90] | 1.00 | 0.00 (0/130) | 76.5 | 0.109 |
| S2 no verifier (Flash judge) | 17 | 0.76 [0.53, 0.90] | 1.00 | 0.01 (2/136) | 75.3 | 0.102 |
| B1 single prompt | 17 | 0.59 [0.36, 0.78] | 0.88 | 0.10 (14/144) | 55.0 | 0.097 |
| B2 classical | 17 | 0.24 [0.10, 0.47] | 0.24 | n/a | 0.4 | 0.000 |

- S1 vs S2 top-1, exact McNemar: S1-only right 1, S2-only right 1, p = 1.000 (not significant)

- S1 vs B1 top-1, exact McNemar: S1-only right 4, B1-only right 1, p = 0.375 (not significant)

- S1 vs B2 top-1, exact McNemar: S1-only right 9, B2-only right 0, p = 0.004

- S-set S1 vs S2: not significant (discordant 0/1, exact McNemar p = 1.000); do not claim a difference.
- S-set S1 vs B1: not significant (discordant 5/1, exact McNemar p = 0.219); do not claim a difference.
- R-set S1 vs S2: not significant (discordant 1/1, exact McNemar p = 1.000); do not claim a difference.
- R-set S1 vs B1: not significant (discordant 4/1, exact McNemar p = 0.375); do not claim a difference.
