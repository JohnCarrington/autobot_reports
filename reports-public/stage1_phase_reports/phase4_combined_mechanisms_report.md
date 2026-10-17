# Phase 4 — Mechanism C (combined) + Mechanism D (exploratory)

Generated: 2026-10-17T12:28:44.843221+00:00
n candidates = 9349  (TRUE 3761, FALSE 5588)  base TRUE rate = 40.2%

## Pre-declared definitions

| name | definition |
|---|---|
| A (classical sweep) | `close_back_inside_after_breach_last24 == 1` |
| B (repeated independent) | `n_independent_episodes >= 2` (gap=6, dep=3p) |
| C (combined) | A AND B AND `prior_60m_eff < 0` AND `prior_60m_net_toward < 0` |
| D (exploratory sustained→fail) | `closes_beyond_count_last24 >= 4` AND `total_bars_beyond_last24 >= 8` AND `close_back_inside_after_breach_last24 == 1` AND `attached_prebroken_in_dir == 1` |

Mechanisms may overlap. UNEXPLAINED = none of A,B,C,D true.

## Prevalence and TRUE-rate lift

| mechanism | n hits | % of pool | TRUE rate | lift vs base |
|---|---:|---:|---:|---:|
| A | 6670 | 71.3% | 49.2% | ×1.22 |
| B | 457 | 4.9% | 40.5% | ×1.01 |
| C | 182 | 1.9% | 49.5% | ×1.23 |
| D | 5024 | 53.7% | 55.2% | ×1.37 |

## Overlap tables (both / only-1st / only-2nd / neither)

### A vs B

| cell | n | n_true | TRUE rate |
|---|---:|---:|---:|
| A ∧ B | 343 | 159 | 46.4% |
| A ∧ ¬B | 6327 | 3122 | 49.3% |
| ¬A ∧ B | 114 | 26 | 22.8% |
| ¬A ∧ ¬B | 2565 | 454 | 17.7% |

### A vs C

| cell | n | n_true | TRUE rate |
|---|---:|---:|---:|
| A ∧ C | 182 | 90 | 49.5% |
| A ∧ ¬C | 6488 | 3191 | 49.2% |
| ¬A ∧ C | 0 | 0 | 0.0% |
| ¬A ∧ ¬C | 2679 | 480 | 17.9% |

### A vs D

| cell | n | n_true | TRUE rate |
|---|---:|---:|---:|
| A ∧ D | 5018 | 2772 | 55.2% |
| A ∧ ¬D | 1652 | 509 | 30.8% |
| ¬A ∧ D | 6 | 0 | 0.0% |
| ¬A ∧ ¬D | 2673 | 480 | 18.0% |

### B vs D

| cell | n | n_true | TRUE rate |
|---|---:|---:|---:|
| B ∧ D | 225 | 110 | 48.9% |
| B ∧ ¬D | 232 | 75 | 32.3% |
| ¬B ∧ D | 4799 | 2662 | 55.5% |
| ¬B ∧ ¬D | 4093 | 914 | 22.3% |

## Disjoint-cell classification (A?B?C?D?)

Each candidate falls into exactly one 4-bit cell. The underscore
character means the mechanism is absent. Sorted by cell size.

| cell (A,B,C,D) | n | n_true | TRUE rate | lift vs base |
|---|---:|---:|---:|---:|
| `A__D` | 4794 | 2662 | 55.5% | ×1.38 |
| `____` | 2560 | 454 | 17.7% | ×0.44 |
| `A___` | 1533 | 460 | 30.0% | ×0.75 |
| `ABCD` | 167 | 84 | 50.3% | ×1.25 |
| `_B__` | 113 | 26 | 23.0% | ×0.57 |
| `AB__` | 104 | 43 | 41.3% | ×1.03 |
| `AB_D` | 57 | 26 | 45.6% | ×1.13 |
| `ABC_` | 15 | 6 | 40.0% | ×0.99 |
| `___D` | 5 | 0 | 0.0% | ×0.00 |
| `_B_D` | 1 | 0 | 0.0% | ×0.00 |

## Interpretation

- Mechanism A alone covers the majority of the candidate pool and
  shows a modest TRUE-rate lift.
- Mechanism B (two or more independent approaches with gap≥30 min
  and ≥3 p departure between them) is rare; this reflects the
  reality that most candidates fire inside a single running
  interaction episode on their day.
- Mechanism C (combined A ∧ B ∧ weakening-momentum) is a strict
  subset of A; its selectivity vs A alone is the key comparison.
- Mechanism D (exploratory: ≥4 closes beyond + ≥8 bars beyond +
  close-back-inside + today-prebroken) captures the SLOW
  failed-acceptance pattern — distinct from a single-bar sweep.
  Its TRUE-rate lift above is a hypothesis-generating signal,
  not a validated edge. Phase 8 will evaluate +30/-12 outcomes.
- UNEXPLAINED (cell `____`) is the subset of candidates in which
  none of the four tested mechanisms fire — see the row for its
  size and TRUE rate.
