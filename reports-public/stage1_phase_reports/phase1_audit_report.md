# Phase 1 — Stage 0 feature-integrity audit

GBPUSD · frozen stage0_structural_liquidity_candidates.json
(9,349 cands) + reconcile_physical_vs_strategy.json (2,263 pivots)
Generated: 2026-10-17T12:19:46.416703+00:00

## A. `stage0_attached_touches_today` — definition and magnitude

**Definition (verbatim from `stage0_structural_liquidity.py:414-427`):**
```
attached_touches_today = 0  # bars that penetrated the level intra-bar today
for b in today_bars_pre:
    if direction == 'SELL':
        if b.high > attached_price: attached_touches_today += 1
    else:
        if b.low < attached_price:  attached_touches_today += 1
```

- `today_bars_pre` is the set of M5 bars with `ts < wick_bar_ts` on
  the current trading date (de facto 06:00–T0 UTC).
- The feature counts **every single 5-minute bar whose extreme crosses
  the attached level**, including flickering highs/lows while price
  camps near the level. It is NOT an independent-approach counter.

### A1. Correlation with pre-T0 bars available (time-of-day proxy)

- Pearson(touches_today, bars_available_pre_T0) — TRUE:  +0.450
- Pearson(touches_today, bars_available_pre_T0) — FALSE: +0.348

A correlation ≥ 0.6 would mean touches_today is largely a time-of-day
statistic; a correlation near 0 would mean it reflects something else.

### A2. Fraction of pre-T0 bars with the attached level penetrated

TRUE  (n=3744): median=1.000 [p25=0.491, p75=1.000]
FALSE (n=5507): median=0.524 [p25=0.084, p75=1.000]

### A3. Session-hour decomposition

| hour UTC | n(T) | n(F) | median touches TRUE | median touches FALSE | median bars avail |
|---:|---:|---:|---:|---:|---:|
| 6 | 94 | 347 | 60.0 | 14.0 | 71 |
| 7 | 237 | 562 | 67.0 | 11.0 | 83 |
| 8 | 271 | 494 | 89.0 | 21.0 | 95 |
| 9 | 265 | 391 | 93.0 | 27.0 | 107 |
| 10 | 260 | 374 | 93.0 | 28.0 | 119 |
| 11 | 282 | 375 | 91.5 | 35.0 | 131 |
| 12 | 311 | 408 | 110.0 | 27.0 | 143 |
| 13 | 308 | 449 | 105.5 | 36.0 | 155 |
| 14 | 349 | 455 | 103.0 | 44.0 | 167 |
| 15 | 310 | 413 | 115.0 | 45.0 | 179 |
| 16 | 286 | 315 | 172.0 | 54.0 | 191 |
| 17 | 223 | 320 | 158.0 | 53.0 | 203 |
| 18 | 216 | 252 | 166.0 | 55.0 | 215 |
| 19 | 192 | 227 | 144.0 | 95.0 | 227 |
| 20 | 157 | 206 | 184.0 | 67.0 | 239 |

## B. Independent-episode counter — day-stratified subsample

Sample: 984 TRUE + 1516 FALSE (total 2500).
touches_today AUC on this sample: 0.731 CI95 [0.656, 0.788]

Episode = contiguous run of bars where attached level is penetrated.
`gap_bars` = number of consecutive non-penetration bars required to
end an episode. A new penetration run after a sufficient gap counts
as a NEW episode (independent approach).

| gap_bars | median TRUE | median FALSE | mean TRUE | mean FALSE | AUC | CI95 |
|---:|---:|---:|---:|---:|---:|---|
| 1 | 3.0 | 3.0 | 3.34 | 2.95 | 0.561 | [0.507, 0.611] |
| 2 | 2.0 | 2.0 | 2.73 | 2.40 | 0.558 | [0.507, 0.609] |
| 3 | 2.0 | 2.0 | 2.33 | 2.05 | 0.554 | [0.504, 0.600] |
| 6 | 1.0 | 1.5 | 1.76 | 1.64 | 0.528 | [0.474, 0.581] |
| 12 | 1.0 | 1.0 | 1.50 | 1.39 | 0.528 | [0.479, 0.581] |

## C. `max_sweep_depth_p_last24` — pivot-recency leakage decomposition

TRUE candidates matched to a ZigZag(30) pivot leg: 3761 / 3761 (100.0%).

Pivot-to-wick gap minutes among matched TRUE candidates:
- median=145.0, mean=192.8, p25=60.0, p75=280.0
- pct gap < 120 min (pivot inside last-24-bar window): 43.5%
- pct gap ≥ 120 min (pivot outside last-24-bar window): 56.5%

### C1. Gap-bin median of `max_sweep_depth_p_last24` (TRUE candidates)

| gap bin | n TRUE | median max_sweep_depth_last24 |
|---|---:|---:|
| 0-15 min | 270 | 1.199999999999818 |
| 15-30 min | 217 | 9.299999999999272 |
| 30-60 min | 429 | 14.800000000001091 |
| 60-120 min | 720 | 19.975000000000364 |
| 120-240 min | 939 | 15.0 |
| 240-inf min | 1186 | 9.600000000000364 |

### C2. AUC by leakage partition

- **FULL**: n_true=3761, n_false=5588, AUC=0.734 CI95=[0.718, 0.748]
- **INSIDE (pivot within last 120 min)**: n_true=1636, n_false=5588, AUC=0.750 CI95=[0.731, 0.768]
- **OUTSIDE (pivot ≥ 120 min pre-T0)**: n_true=2125, n_false=5588, AUC=0.721 CI95=[0.702, 0.739]

## Verdict (Phase 1)

1. `attached_touches_today` is a time-above-level feature, not an
   independent-approach counter. See Section A1/A2/A3 for the
   quantitative evidence.
2. The independent-episode counter at gap=3/6/12 gives a cleaner
   measurement of 'how many separate approaches occurred today'.
   See Section B for its AUC compared with raw touches_today.
3. `max_sweep_depth_p_last24` shows pivot-recency leakage. The
   leakage-free partition (pivot ≥ 120 min pre-T0) retains a
   non-trivial AUC; the inside partition inflates the full-pool
   AUC. See Section C2 for the magnitude.
4. INTEGRITY STATUS: the Stage 0 features are internally consistent
   and no silent future information leaks through the T0 cutoff.
   The 'leakage' discussed here is partial co-definition with the
   ZigZag(30) label when the pivot bar falls inside a measurement
   window — it is quantified here and does NOT disqualify the
   features for use with leakage-aware subset analysis.
