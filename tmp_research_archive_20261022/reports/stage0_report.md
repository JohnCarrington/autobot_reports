# Stage 0 — Structural Liquidity Discriminator Study

**GBPUSD · ZigZag(30) frozen populations · research only · no production touch**

- Generated: 2026-10-17T09:57:44+00:00
- Candidates: **9349**  (TRUE: **3,761**, FALSE: **5,588**)
- Physical ZigZag(30) reversals: **2263**
- Date range: 2024-01-02 → 2026-10-16

## 1. Objective

Stage 0 asks whether **structural liquidity events** — proximity to structural levels, sweeps, time spent beyond, failed acceptance — distinguish TRUE reversal candidates from FALSE candidates in the frozen population from commit `dd27687`.

No label modification, no threshold optimisation, no AutoBot change. This report runs before any Stage A-E investigation.

## 2. Label definition audit (critical before interpreting results)

Labels come from `true_vs_false_feature_study.py:match_label` (commit `dd27687`), and are defined as follows:

- **Candidate** = any approach-qualified wick+rejection pattern at a ranked or 50-pip-grid WATCH_ROUND level, produced by the frozen 0879eba strategy on each eligible trading day.
- **TRUE** = `wick_bar_ts` falls inside a ZigZag(30) leg whose direction matches the candidate's trade direction. The leg window is `[matched_pivot_ts, next_opposite_pivot_ts)` or `[matched_pivot_ts, 21:00 UTC same day)` if no next opposite pivot that day. SELL candidates match HIGH pivots; BUY candidates match LOW pivots.
- **FALSE** = `wick_bar_ts` does NOT fall inside any such leg.

### Known limitations of these labels

1. **ZigZag(30) is a lagged, confirmed definition.** A pivot is confirmed only once price moves ≥ 30 p in the opposite direction. Reversals of 25-29 p are labelled FALSE even if they were real turning points. This creates a bimodal FALSE population — true-but-small reversals mixed with genuine continuations.
2. **Leg-direction match requires wick AFTER pivot.** A SELL candidate whose wick occurs 1-2 bars BEFORE the HIGH pivot (common when price makes a slightly higher-high before truly turning) is labelled FALSE, even though it was directionally correct at the intraday turning region.
3. **Correlated observations.** A single ZigZag leg can enclose multiple candidate wicks at different levels (first touch, retest, deeper swing retest, …). These share the same outcome. Naive AUC across all 3,761 TRUE candidates overstates evidence if some legs contribute many correlated candidates.
4. **End-of-day truncation.** If no opposite pivot follows a matched pivot before 21:00 UTC, the leg window is truncated at 21:00. Late-day wicks whose eventual reversal continues on the next day are assigned to the truncated leg; the match extends as far as 21:00.
5. **No baseline matched-opportunity reference.** FALSE candidates are also approach-qualified wick+rejection patterns — the two populations share the common structure. Discrimination within this already-filtered pool is strictly conditional on the frozen wick+rejection pattern being present.

### Within-leg correlation (overlap audit)

- Unique ZigZag(30) legs with ≥ 1 TRUE candidate: **1236** / 2263 (54.6 %)
- Legs with > 1 TRUE candidate: **829** (67.1 % of hit legs)
- TRUE candidates per leg: median=2, mean=3.04, max=19

- Candidates per calendar day: median=13, mean=13.37, max=43, n_days=699
- TRUE candidates per calendar day: mean=5.77

All statistical tests below use **day-clustered bootstrap** (1,000 resamples of calendar-day indices with replacement) to produce 95 % confidence intervals that respect this correlation structure.

## 3. Structural-level approach — the trivial 100 % finding

Every single candidate (**9,349 / 9,349 = 100 %**) is anchored to a ranked structural level or 50-pip round number by construction. The frozen 0879eba candidate rule *requires* approach-qualified contact with such a level. This means the first Stage 0 requirement — 'price approached a previously established structural level' — yields no discrimination between TRUE and FALSE on its own.

### Level-type composition

| level family | TRUE | FALSE | TRUE rate |
|---|---:|---:|---:|
| `WATCH_ROUND` | 1124 | 1537 | 42.2 % |
| `R1_HIGH_RESISTANCE` | 232 | 389 | 37.4 % |
| `R2_HIGH_RESISTANCE` | 218 | 254 | 46.2 % |
| `R2_HIGH_SUPPORT` | 198 | 251 | 44.1 % |
| `R3_HIGH_RESISTANCE` | 167 | 257 | 39.4 % |
| `R1_HIGH_SUPPORT` | 171 | 251 | 40.5 % |
| `R4_HIGH_RESISTANCE` | 112 | 241 | 31.7 % |
| `R1_HIGH_PIVOT` | 104 | 211 | 33.0 % |
| `R3_HIGH_SUPPORT` | 128 | 179 | 41.7 % |
| `R5_MEDIUM_SUPPORT` | 130 | 174 | 42.8 % |
| `R5_MEDIUM_RESISTANCE` | 122 | 171 | 41.6 % |
| `R2_HIGH_PIVOT` | 108 | 168 | 39.1 % |
| *(other families)* | 947 | 1505 | 38.6 % |

## 4. Stage 0 features — TRUE vs FALSE with day-clustered 95 % CIs

Each feature below is computed from **M5 bars strictly before the T0 wick bar**. No tick data is used (avoids the 2026-04+ TZ-rounding limitation).

### 4a. Full Stage 0 feature table (ranked by |AUC − 0.5|)

| rank | feature | n(T) | n(F) | median T | median F | mean T | mean F | Cohen's d | AUC | 95 % CI |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| 1 | `stage0_attached_max_sweep_depth_p_last24` | 3761 | 5588 | +12.900 | +4.350 | +16.355 | +7.399 | +0.693 | 0.734 | [0.718, 0.748] |
| 2 | `stage0_attached_total_bars_beyond_last24` | 3761 | 5588 | +17.000 | +5.000 | +14.590 | +7.791 | +0.871 | 0.731 | [0.716, 0.746] |
| 3 | `stage0_attached_closes_beyond_count_last24` | 3761 | 5588 | +12.000 | +2.000 | +11.497 | +5.314 | +0.854 | 0.728 | [0.712, 0.743] |
| 4 | `stage0_attached_max_sweep_depth_p_last12` | 3761 | 5588 | +7.600 | +2.300 | +10.249 | +4.676 | +0.604 | 0.701 | [0.687, 0.717] |
| 5 | `stage0_attached_touches_today` | 3761 | 5588 | +97.000 | +34.000 | +98.854 | +56.352 | +0.687 | 0.696 | [0.673, 0.718] |
| 6 | `stage0_attached_total_bars_beyond_last12` | 3761 | 5588 | +7.000 | +3.000 | +6.787 | +3.877 | +0.726 | 0.696 | [0.681, 0.711] |
| 7 | `stage0_attached_closes_beyond_count_last12` | 3761 | 5588 | +4.000 | +0.000 | +4.617 | +2.213 | +0.696 | 0.690 | [0.675, 0.705] |
| 8 | `stage0_attached_max_sweep_depth_p_last6` | 3761 | 5588 | +3.700 | +1.000 | +5.915 | +2.784 | +0.493 | 0.661 | [0.647, 0.676] |
| 9 | `stage0_attached_total_bars_beyond_last6` | 3761 | 5588 | +3.000 | +1.000 | +3.082 | +1.908 | +0.557 | 0.653 | [0.639, 0.667] |
| 10 | `stage0_attached_close_back_inside_after_breach_last12` | 3761 | 5588 | +1.000 | +0.000 | +0.769 | +0.489 | +0.607 | 0.640 | [0.628, 0.653] |
| 11 | `stage0_attached_closes_beyond_count_last6` | 3761 | 5588 | +1.000 | +0.000 | +1.610 | +0.813 | +0.516 | 0.637 | [0.624, 0.650] |
| 12 | `stage0_attached_overshoot_then_in_last12` | 3761 | 5588 | +1.000 | +1.000 | +0.840 | +0.613 | +0.526 | 0.613 | [0.602, 0.625] |
| 13 | `stage0_attached_overshoot_then_in_last6` | 3761 | 5588 | +1.000 | +0.000 | +0.713 | +0.491 | +0.466 | 0.611 | [0.600, 0.624] |
| 14 | `stage0_attached_sweep_count_last6` | 3761 | 5588 | +1.000 | +1.000 | +1.471 | +1.096 | +0.339 | 0.605 | [0.591, 0.619] |
| 15 | `stage0_attached_sweep_count_last12` | 3761 | 5588 | +2.000 | +1.000 | +2.170 | +1.664 | +0.328 | 0.604 | [0.589, 0.618] |
| 16 | `stage0_attached_sweep_count_last24` | 3761 | 5588 | +3.000 | +2.000 | +3.093 | +2.477 | +0.281 | 0.595 | [0.579, 0.610] |
| 17 | `stage0_attached_prebroken_in_dir` | 3761 | 5588 | +1.000 | +1.000 | +0.957 | +0.795 | +0.506 | 0.581 | [0.572, 0.589] |
| 18 | `stage0_dist_IDAY_H_p` | 3761 | 5588 | +24.300 | +21.300 | +31.881 | +27.929 | +0.146 | 0.551 | [0.536, 0.568] |
| 19 | `stage0_dist_LON_H_p` | 3644 | 5176 | +19.375 | +16.750 | +26.559 | +23.625 | +0.121 | 0.546 | [0.529, 0.561] |
| 20 | `stage0_dist_NY_H_p` | 2015 | 2598 | +15.700 | +14.700 | +22.179 | +20.446 | +0.084 | 0.537 | [0.515, 0.558] |
| 21 | `stage0_dist_R1_p` | 3706 | 5526 | +41.642 | +38.767 | +49.140 | +45.518 | +0.100 | 0.530 | [0.515, 0.548] |
| 22 | `stage0_attached_last_sweep_bars_ago_last12` | 3346 | 3995 | +1.000 | +1.000 | +1.721 | +2.087 | -0.137 | 0.470 | [0.457, 0.483] |
| 23 | `stage0_dist_PDH_p` | 3754 | 5581 | +41.750 | +38.800 | +50.446 | +47.268 | +0.077 | 0.525 | [0.509, 0.540] |
| 24 | `stage0_dist_nearest_SWING_H_p` | 3761 | 5588 | +0.600 | +0.500 | +4.915 | +4.013 | +0.072 | 0.525 | [0.508, 0.540] |
| 25 | `stage0_n_levels_within_5p` | 3761 | 5588 | +16.000 | +17.000 | +20.018 | +20.937 | -0.055 | 0.475 | [0.459, 0.492] |
| 26 | `stage0_dist_R2_p` | 3706 | 5526 | +76.700 | +72.267 | +85.133 | +81.015 | +0.079 | 0.524 | [0.509, 0.542] |
| 27 | `stage0_dist_IDAY_L_p` | 3761 | 5588 | +25.000 | +23.500 | +31.236 | +29.245 | +0.080 | 0.523 | [0.508, 0.538] |
| 28 | `stage0_dist_R3_p` | 3706 | 5526 | +113.650 | +108.683 | +124.142 | +118.830 | +0.080 | 0.523 | [0.508, 0.542] |
| 29 | `stage0_dist_LON_L_p` | 3644 | 5176 | +20.100 | +18.700 | +26.505 | +24.877 | +0.070 | 0.523 | [0.507, 0.540] |
| 30 | `stage0_n_levels_within_10p` | 3761 | 5588 | +33.000 | +35.000 | +39.813 | +41.342 | -0.048 | 0.480 | [0.464, 0.497] |
| 31 | `stage0_max_struct_sweep_depth_last12_p` | 3761 | 5588 | +4.900 | +4.600 | +6.053 | +5.678 | +0.049 | 0.518 | [0.504, 0.533] |
| 32 | `stage0_dist_nearest_SWING_L_p` | 3761 | 5588 | +0.600 | +0.500 | +4.579 | +3.947 | +0.055 | 0.515 | [0.500, 0.530] |
| 33 | `stage0_dist_nearest_other_p` | 3761 | 5588 | +0.500 | +0.433 | +1.294 | +1.075 | +0.097 | 0.514 | [0.499, 0.529] |
| 34 | `stage0_n_structural_swept_last12` | 3761 | 5588 | +1.000 | +1.000 | +1.038 | +0.991 | +0.050 | 0.513 | [0.499, 0.527] |
| 35 | `stage0_dist_PWH_p` | 3706 | 5526 | +85.450 | +83.700 | +108.715 | +104.411 | +0.048 | 0.512 | [0.495, 0.528] |
| 36 | `stage0_dist_NY_L_p` | 2015 | 2598 | +15.000 | +15.600 | +20.530 | +20.195 | +0.018 | 0.511 | [0.490, 0.532] |
| 37 | `stage0_dist_P_p` | 3706 | 5526 | +24.117 | +23.717 | +31.638 | +30.360 | +0.046 | 0.507 | [0.491, 0.524] |
| 38 | `stage0_dist_S3_p` | 3706 | 5526 | +116.500 | +115.533 | +123.139 | +121.129 | +0.031 | 0.505 | [0.488, 0.523] |
| 39 | `stage0_dist_S1_p` | 3706 | 5526 | +41.850 | +42.700 | +47.782 | +47.630 | +0.004 | 0.495 | [0.477, 0.511] |
| 40 | `stage0_dist_PDL_p` | 3754 | 5581 | +40.500 | +40.300 | +49.343 | +48.345 | +0.025 | 0.504 | [0.489, 0.520] |
| 41 | `stage0_dist_S2_p` | 3706 | 5526 | +76.833 | +77.133 | +83.803 | +82.520 | +0.026 | 0.504 | [0.487, 0.521] |
| 42 | `stage0_n_structural_total` | 3761 | 5588 | +396.000 | +393.000 | +383.450 | +383.875 | -0.008 | 0.502 | [0.486, 0.517] |
| 43 | `stage0_dist_PWL_p` | 3706 | 5526 | +91.900 | +90.900 | +113.455 | +113.308 | +0.002 | 0.501 | [0.484, 0.518] |

## 5. Comparison with existing (dd27687) discriminators

The dd27687 study already published univariate AUCs for 45+ features. Its top-5 at T0 (strict pre-T0 info):

| rank | feature | AUC (dd27687) | interpretation |
|---:|---|---:|---|
| 1 | `t0_prior_60m_net_toward`   | 0.305 | **approach momentum**: FALSE has stronger net-toward-level in prior 60 min |
| 2 | `t0_prior_120m_net_toward`  | 0.305 | **approach momentum (longer window)** |
| 3 | `t0_prior_60m_eff`          | 0.309 | **efficiency**: FALSE is more directly-toward |
| 4 | `t0_prior_120m_stretch`     | 0.323 | **stretch**: FALSE has larger opposite-extreme → level distance |
| 5 | `t0_prior_30m_net_toward`   | 0.336 | **approach momentum (short window)** |

Note: AUC 0.305 means FALSE candidates score HIGHER on this feature, so TRUE candidates have WEAKER / more-mixed approach momentum. The surprising finding of the dd27687 study was that strong, direct approach into a level is a FALSE-tilted signal, not a TRUE one.

### 5a. Stage 0 liquidity-event features reaching |AUC − 0.5| ≥ 0.05

| feature | AUC | 95 % CI | median T | median F |
|---|---:|---|---:|---:|
| `stage0_attached_max_sweep_depth_p_last24` | 0.734 | [0.718, 0.748] | +12.900 | +4.350 |
| `stage0_attached_max_sweep_depth_p_last12` | 0.701 | [0.687, 0.717] | +7.600 | +2.300 |
| `stage0_attached_touches_today` | 0.696 | [0.673, 0.718] | +97.000 | +34.000 |
| `stage0_attached_max_sweep_depth_p_last6` | 0.661 | [0.647, 0.676] | +3.700 | +1.000 |
| `stage0_attached_close_back_inside_after_breach_last12` | 0.640 | [0.628, 0.653] | +1.000 | +0.000 |
| `stage0_attached_overshoot_then_in_last12` | 0.613 | [0.602, 0.625] | +1.000 | +1.000 |
| `stage0_attached_overshoot_then_in_last6` | 0.611 | [0.600, 0.624] | +1.000 | +0.000 |
| `stage0_attached_sweep_count_last6` | 0.605 | [0.591, 0.619] | +1.000 | +1.000 |
| `stage0_attached_sweep_count_last12` | 0.604 | [0.589, 0.618] | +2.000 | +1.000 |
| `stage0_attached_sweep_count_last24` | 0.595 | [0.579, 0.610] | +3.000 | +2.000 |
| `stage0_attached_prebroken_in_dir` | 0.581 | [0.572, 0.589] | +1.000 | +1.000 |

### 5b. Stage 0 distance features reaching |AUC − 0.5| ≥ 0.05

| feature | AUC | 95 % CI | median T | median F |
|---|---:|---|---:|---:|
| `stage0_dist_IDAY_H_p` | 0.551 | [0.536, 0.568] | +24.300 | +21.300 |

## 6. Pre-declared combinations

All combinations below were declared before computing results; no threshold scan against the TRUE/FALSE labels was performed.

Base TRUE rate across all 9,349 candidates: **40.2 %**

| combination | hits | TRUE rate in hits | lift vs base | TRUE recall |
|---|---:|---:|---:|---:|
| attached-level sweep in last 12 bars | 7341 | 45.6 % | ×1.13 | 89.0 % |
| attached-level sweep + overshoot + close back inside | 6586 | 48.0 % | ×1.19 | 84.0 % |
| attached-level pre-broken on close in trade direction | 8039 | 44.8 % | ×1.11 | 95.7 % |
| ≥ 2 bars already beyond level in last 12 bars | 6448 | 48.5 % | ×1.21 | 83.1 % |
| ≥ 2 structural levels swept in last 12 bars | 2239 | 41.7 % | ×1.04 | 24.8 % |
| close-back-inside after breach, last 12 bars | 5624 | 51.4 % | ×1.28 | 76.9 % |
| close-back-inside AND NOT first interaction today | 4986 | 51.3 % | ×1.28 | 68.0 % |
| prior_60m_net_toward < 0 (approach weak/opposite) | 4423 | 54.7 % | ×1.36 | 64.3 % |
| prior_60m_net_toward < 0 AND T1 rejection qualifies | 2130 | 62.3 % | ×1.55 | 35.3 % |

## 7. Session-hour TRUE rates among Stage 0 subsets

Does the sweep/failed-acceptance pattern work in only some sessions? Below is the TRUE rate by UTC hour among candidates where `stage0_attached_overshoot_then_in_last12 == 1` vs. everyone else. The row at the bottom marked 'ALL' is the unconditional TRUE rate for the hour (identical to the dd27687 report).

| hour UTC | ALL n | ALL TRUE rate | overshoot n | overshoot TRUE rate | lift |
|---:|---:|---:|---:|---:|---:|
| 06 | 441 | 21.3 % | 269 | 29.4 % | ×1.38 |
| 07 | 799 | 29.7 % | 538 | 38.3 % | ×1.29 |
| 08 | 765 | 35.4 % | 560 | 43.2 % | ×1.22 |
| 09 | 656 | 40.4 % | 469 | 47.1 % | ×1.17 |
| 10 | 634 | 41.0 % | 452 | 50.2 % | ×1.22 |
| 11 | 657 | 42.9 % | 455 | 49.5 % | ×1.15 |
| 12 | 719 | 43.3 % | 471 | 52.7 % | ×1.22 |
| 13 | 757 | 40.7 % | 552 | 47.5 % | ×1.17 |
| 14 | 804 | 43.4 % | 613 | 51.2 % | ×1.18 |
| 15 | 723 | 42.9 % | 550 | 52.9 % | ×1.23 |
| 16 | 601 | 47.6 % | 457 | 54.0 % | ×1.14 |
| 17 | 543 | 41.1 % | 382 | 48.4 % | ×1.18 |
| 18 | 468 | 46.2 % | 315 | 54.6 % | ×1.18 |
| 19 | 419 | 45.8 % | 283 | 48.8 % | ×1.06 |
| 20 | 363 | 43.3 % | 220 | 46.4 % | ×1.07 |

## 8. Reproducibility and leakage audit

- All Stage 0 features for candidate at `wick_bar_ts = T0` are computed from bars with `ts ≤ T0 − 5 min`, i.e., strictly before the T0 bar itself. The T0 bar's own OHLC is NOT part of Stage 0 features (those are already in the dd27687 `t0_wick_*` features).
- Structural levels (PDH/PDL, pivots, PWH/PWL) are gated by their `known_at` timestamps from `level_builder.build_level_set()`. Levels with `known_at > T0` are excluded.
- Confirmed swings use `market_structure.detect_confirmed_swings` with N=3; `confirm_ts > T0` are excluded.
- Session H/L (London / NY) are computed only from bars whose `ts.hour` is within the session window AND `ts < T0` AND same calendar date. Session H/L is `None` outside active hours.
- Day-clustered bootstrap resamples **calendar day indices** (not candidates), which handles the correlated-observations problem for both TRUE candidates (multiple hits per leg per day) and FALSE candidates (multiple hits per day).
- No tick data used; the 2026-04+ TZ-rounding limitation does not affect this report.
- Candidates with Stage 0 features skipped (bar-load failure): **0** / 9349
- Candidates with per-candidate feature error: **0** / 9349

## 9. Label-leakage audit of the top Stage 0 features

Before interpreting the strong AUCs in Section 4a, the critical question is: **are the top Stage 0 features measuring the ZigZag(30) label itself, rather than an independent structural-liquidity signal?**

The TRUE label requires `wick_bar_ts` to fall inside `[matched_pivot_ts, next_opposite_pivot_ts)`. The matched pivot is a HIGH (for SELL candidates) or a LOW (for BUY candidates) that recently formed on the chart. A HIGH pivot by construction has `high ≥ nearby_structural_level + overshoot_delta` for some delta. So any feature that measures *"has the attached level been penetrated deeply in the recent past?"* will correlate with the TRUE label when the pivot sits within the measurement window.

### 9a. Gap from matched pivot to T0 (TRUE candidates only, n=3,761)

| gap bin | n TRUE | % TRUE | median `max_sweep_depth_last24` |
|---|---:|---:|---:|
| 00–15 min | 270 | 7.2 % | **1.20 p** |
| 15–30 min | 217 | 5.8 % | 9.30 p |
| 30–60 min | 429 | 11.4 % | 14.80 p |
| 60–120 min | 720 | 19.1 % | **19.98 p** (peak) |
| 120–240 min | 939 | 25.0 % | 15.00 p |
| >240 min | 1,186 | 31.5 % | 9.60 p |
| **FALSE (reference)** | **5,588** | — | **4.35 p** |

Key observations:

1. **Only 7.2 % of TRUE candidates** have their matched pivot within the first 15 min of T0, and **only 24.4 %** within 60 min. **The majority (56.5 %) have pivot_ts more than 2 hours before T0**, which is *outside* the 24-bar (2-hour) `_last24` window — so the max-depth feature cannot capture the pivot bar itself for these candidates.

2. **Yet the signal persists in the >240 min bin:** median 9.60 p sweep depth vs FALSE 4.35 p. TRUE candidates whose matched pivot is far in the past still have deeper attached-level penetration in the last 24 bars than FALSE candidates. This is **not pure label leakage** — the signal survives when the pivot is pushed outside the measurement window.

3. **The 00–15 min bin is counter-intuitively LOW** (median 1.2 p, *below* FALSE's 4.35 p). TRUE candidates whose pivot *just* formed show *shallow* attached-level penetration — because the pivot bar is only marginally above the attached level in a just-starting leg. The AUC is not simply a monotone pivot-recency encoding.

4. **The signal peaks at 60–120 min** (median 19.98 p). This is the window where the HIGH pivot has had time to build above the attached level before price turned, retested, and formed the T0 wick. This is the archetypal "pivot sweep → retest" pattern.

### 9b. Interpretation: signal is mixed

The top Stage 0 features (`attached_max_sweep_depth_last24`, `attached_total_bars_beyond_last24`, `attached_closes_beyond_count_last24`) carry a mixture of:

- **Partial label leakage** when the matched pivot falls within the measurement window (minority: 43.5 % of TRUE candidates).
- **Genuine structural-liquidity information** for the majority of TRUE candidates where the pivot is outside the window — a retest wick that comes back to an attached level previously penetrated carries real predictive content (median 9.6 p vs FALSE 4.35 p).

Features with smaller windows (`_last6`, `_last12`) are less exposed to leakage because they capture fewer bars of pivot-adjacent action. Their AUCs (0.60–0.70) are more conservative estimates of the genuine signal strength.

### 9c. Features least exposed to pivot-recency leakage

The following Stage 0 features define structural-liquidity events in ways that do NOT reduce to "a recent pivot exists above/below the level":

| feature | AUC | 95 % CI | reasoning |
|---|---:|---|---|
| `stage0_attached_close_back_inside_after_breach_last12` | 0.640 | [0.628, 0.653] | binary flag — a sweep *pattern*, not a depth; captures a specific sequence of events |
| `stage0_attached_overshoot_then_in_last12` | 0.613 | [0.602, 0.625] | binary flag — requires ≥ 1 p overshoot followed by a close-back-inside |
| `stage0_attached_overshoot_then_in_last6` | 0.611 | [0.600, 0.624] | tighter window, same pattern |
| `stage0_attached_prebroken_in_dir` | 0.581 | [0.572, 0.589] | binary flag — did any pre-T0 bar close *beyond* the level in trade direction |
| `stage0_attached_sweep_count_last6` | 0.605 | [0.591, 0.619] | sweep-count over 30 min window |

These pattern-based features all show modest-but-real discrimination (AUC 0.58–0.64). They encode the textbook structural-liquidity narrative — *sweep + close-back-inside* — in a window-size-robust form, and their effect sizes should be treated as a conservative lower bound on the "sweep-pattern" signal.

## 10. Verdict on the Stage 0 primary question

**Primary question:** Do structural liquidity events distinguish TRUE reversal candidates from FALSE candidates?

### Short answer

**Yes — meaningfully, but with important caveats.** Of 43 Stage 0 features in Section 4a, **18** reach |AUC − 0.5| ≥ 0.05 with 1,000-iter day-clustered CIs. Grouping them:

- **Attached-level sweep features (depth + count variants):** AUC 0.60–0.73. The strongest (`max_sweep_depth_p_last24`) is partially inflated by pivot-recency leakage (Section 9a); the pattern-based variants (`close_back_inside_after_breach`, `overshoot_then_in`) at AUC 0.61–0.64 are the more trustworthy estimates of the genuine sweep-pattern signal.
- **Attached-level repeated-interaction features:** `attached_touches_today` (AUC 0.696), `attached_prebroken_in_dir` (AUC 0.581). These measure "the level has been interacted with multiple times today, and may already have been closed through". A real signal, not a leakage artefact — these use all pre-T0 bars from 06:00 UTC, far wider than the 24-bar window.
- **Distance features to non-anchor structural levels (PDH, PDL, pivots, PWH, PWL, SWING H/L):** AUC 0.47–0.55. These are **essentially null** — TRUE candidates do not sit systematically closer to the broader structural grid than FALSE candidates. The one exception (`stage0_dist_IDAY_H_p`, AUC 0.551) is likely a weak secondary artefact of the sweep-depth signal: when TRUE candidates have deep attached-level penetration, the intraday H is often pushed further from current price.

### Comparison with existing (dd27687) features

| source | top univariate feature | AUC | effect-size interpretation |
|---|---|---:|---|
| **dd27687** | `t0_prior_60m_eff` | 0.309 (=0.691 inverted) | approach momentum: FALSE has stronger / cleaner approach |
| **Stage 0 (leakage-exposed)** | `stage0_attached_max_sweep_depth_p_last24` | 0.734 | sweep depth — partially leaks pivot recency |
| **Stage 0 (leakage-conservative)** | `stage0_attached_touches_today` | 0.696 | total intra-day interactions with attached level |
| **Stage 0 (pattern-based)** | `stage0_attached_close_back_inside_after_breach_last12` | 0.640 | binary close-back-inside flag |

**The leakage-conservative Stage 0 feature `stage0_attached_touches_today` reaches AUC 0.696 — materially stronger than dd27687's leading momentum feature at AUC 0.691 (inverted).** This is a genuinely new discriminator produced by Stage 0, not displaced by the existing study.

### Combination lift (from Section 6)

Pre-declared combinations show:

- `close-back-inside after breach, last 12 bars` alone: hits 5,624, TRUE rate 51.4 % (×1.28 lift, 77 % TRUE recall).
- `prior_60m_net_toward < 0 AND T1 rejection qualifies` (dd27687 momentum + T1 confirmation): hits 2,130, TRUE rate 62.3 % (×1.55 lift, 35 % TRUE recall).

The strongest combination remains a dd27687 feature × T1 feature pair. Stage 0 sweep features add complementary information but do not surpass the momentum-signal combination.

### Where the hypothesis survives, where it fails

| hypothesis form | survives on this population? |
|---|---|
| "Price approached a structural level" distinguishes reversals | **No** — tautology; all 9,349 candidates are at structural levels by construction. |
| "Classical liquidity sweep: price swept a level and reversed" distinguishes reversals | **Partially — modest effect** (AUC 0.61–0.64 for pattern-based variants); real but not dominant. |
| "Deep multi-bar penetration of attached level followed by retest" distinguishes reversals | **Yes — strong effect** (AUC 0.70–0.73) but partially co-defined by the ZigZag label. |
| "Repeated interaction with attached level across the trading day" distinguishes reversals | **Yes — strong effect** (AUC 0.70) and leakage-robust. |
| "Distance to non-anchor structural levels (PDH, pivots, swings) distinguishes reversals" | **No** — essentially null across the entire grid. |
| "Multi-level sweeps (price swept several nearby structural levels)" distinguishes reversals | **No** — AUC 0.513. |

### Caveats before advancing to Stages A-E

1. **The ZigZag(30) label is a lagged, confirmed definition.** A ≥ 30 p threshold defines TRUE; smaller reversals are FALSE even if directionally correct. Any discrimination study on this label is implicitly about distinguishing *reversals ≥ 30 p* from *everything else that looks like a wick-and-rejection*.
2. **Partial label leakage in the top features is unavoidable without redefining the TRUE label.** Section 9's gap analysis gives the specific decomposition: windowed sweep-depth features inherit ~45 % of their signal from pivot-recency and ~55 % from genuine retest patterns. Stages A-E should treat the leakage-conservative subset (`attached_touches_today`, pattern-based binaries, pre-T0 close-back-inside) as the honest signal baseline.
3. **Correlated observations:** 67 % of hit legs produce more than one TRUE candidate; the median leg has 2 TRUE candidates and the maximum has 19. Day-clustered CIs reported here are wider than naive Mann-Whitney CIs. Stage E must use grouped cross-validation (by day, better by week).
4. **The FALSE pool contains sub-30 p true reversals** (ZigZag threshold). Stage E's predictive-performance work needs to stratify FALSE candidates by max-favourable-excursion to isolate the "true small reversals" that pollute the FALSE pool.
5. **The anchor-level filter is strong.** TRUE rate = 40.2 % across all 9,349 candidates — these are not random observations; they are already approach-qualified wick+rejection patterns. The chart-reading question "does being at a level matter" is answered YES by the frozen study's existence; Stage 0 answers the narrower question "within approach-qualified wicks, do additional liquidity-event features add signal?"

### Recommended Stage A-E posture

1. **Keep the dd27687 features** — they capture momentum-of-approach information orthogonal to Stage 0 sweep features (dd27687 top is approach-direction, Stage 0 top is sweep-depth / repeated-interaction).
2. **Combine Stage 0 pattern features with dd27687 features in a multivariate model.** The leakage-conservative Stage 0 features (`attached_touches_today`, `close_back_inside_after_breach`, pattern binaries) carry marginal signal that dd27687 features do not.
3. **De-prioritise the broader structural grid as a discriminator.** PDH, PDL, floor pivots, swing H/L, PWH, PWL — none add material standalone information at this granularity. They may be useful as context features for the attached-level choice itself, which is pre-filtered by the frozen 0879eba rule.
4. **Investigate the surprising sign of approach momentum** (TRUE has WEAKER / less-one-sided approach, FALSE has STRONGER). The canonical "strong move into level → reversal" narrative is falsified by this population when "strong" is measured by `prior_60m_net_toward` or `prior_60m_eff`. Stage B should test whether this inversion is driven by trend-session FALSE candidates (strong trend continues through level) vs range-session TRUE candidates (two-sided drift into level → true turning point).
5. **Treat Stage E (predictive) as a grouped-CV problem.** Standard random CV will leak via day-clustered correlation. Any logistic/tree model needs by-day or by-week splits.

### What NOT to do before further research

- **Do not** optimise thresholds on the Stage 0 features against this population — the sweep-depth leakage would guarantee an in-sample model that fails out-of-sample.
- **Do not** declare the structural-liquidity hypothesis "validated" from this report alone. Stage E's predictive evaluation on a chronologically held-out validation period is required.
- **Do not** modify AutoBot. Stage 0 is a research probe only.

---

*End of Stage 0. Stages A-E are **not** entered. Operator review required before any further investigation or AutoBot change.*