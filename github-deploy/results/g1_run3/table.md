# Synthetic grid results (SPEC v1.0; fixtures v2 = est/participants_v2.py, SPEC_AMENDMENTS A2)

backend: cli
runs: 18/18

| item | policy | n | coverage | specificity | refusal_recovery | verification | uptake | composite |
|---|---|---|---|---|---|---|---|---|
| cell_culture | MEDIUM | 2 | 0.70 | 0.00 | 0.00 | 0.50 | 0.88 | 0.42 |
| cell_culture | STRONG | 2 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |
| cell_culture | WEAK | 2 | 0.60 | 0.00 | 0.00 | 0.00 | 0.50 | 0.22 |
| pcr_lab | MEDIUM | 2 | 0.90 | 0.00 | 0.00 | 0.00 | 1.00 | 0.38 |
| pcr_lab | STRONG | 2 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |
| pcr_lab | WEAK | 2 | 0.20 | 0.00 | 0.00 | 0.00 | 1.00 | 0.24 |
| western_blot | MEDIUM | 2 | 0.80 | 0.25 | 0.00 | 0.00 | 0.75 | 0.36 |
| western_blot | STRONG | 2 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |
| western_blot | WEAK | 2 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 |
| ALL | WEAK | 6 | 0.27 | 0.00 | 0.00 | 0.00 | 0.50 | 0.15 |
| ALL | MEDIUM | 6 | 0.80 | 0.08 | 0.00 | 0.17 | 0.88 | 0.39 |
| ALL | STRONG | 6 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |

## Gate G1
```
{
 "G1a_composite_ordering_every_item": true,
 "G1b_subscale_monotone_pooled": true,
 "G1_pass": true,
 "n_runs": 18,
 "expected_runs": 18
}
```
