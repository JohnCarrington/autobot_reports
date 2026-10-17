# Phase 4 rerun — Mechanism C + exploratory D on authorised data

Generated: 2026-10-17T12:51:57.806750+00:00
n candidates (authorised): 7499  TRUE 3077  base TR 41.0%

## Prevalence (authorised coverage)

| mechanism | n hits | % of pool | TRUE rate | lift vs base |
|---|---:|---:|---:|---:|
| A | 5386 | 71.8% | 49.8% | ×1.21 |
| B | 529 | 7.1% | 47.8% | ×1.17 |
| C | 263 | 3.5% | 61.2% | ×1.49 |
| D | 4074 | 54.3% | 55.9% | ×1.36 |

## Overlap A vs D

| cell | n | n_true | TRUE rate |
|---|---:|---:|---:|
| A ∧ D | 4074 | 2278 | 55.9% |
| A ∧ ¬D | 1312 | 403 | 30.7% |
| ¬A ∧ D | 0 | 0 | 0.0% |
| ¬A ∧ ¬D | 2113 | 396 | 18.7% |

## Disjoint 4-bit cells

| cell (A,B,C,D) | n | n_true | TRUE rate | lift |
|---|---:|---:|---:|---:|
| `A__D` | 3756 | 2088 | 55.6% | ×1.35 |
| `____` | 1967 | 355 | 18.0% | ×0.44 |
| `A___` | 1247 | 381 | 30.6% | ×0.74 |
| `ABCD` | 244 | 156 | 63.9% | ×1.56 |
| `_B__` | 146 | 41 | 28.1% | ×0.68 |
| `AB_D` | 74 | 34 | 45.9% | ×1.12 |
| `AB__` | 46 | 17 | 37.0% | ×0.90 |
| `ABC_` | 19 | 5 | 26.3% | ×0.64 |
