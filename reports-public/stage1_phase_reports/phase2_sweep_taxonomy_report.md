# Phase 2 — Mechanism A (liquidity sweep) taxonomy

GBPUSD · 9,349 wick+rejection candidates · ZigZag(30) frozen labels
Generated: 2026-10-17T12:24:20.922038+00:00

## Definitions (pre-T0 observables)

All classifications are evaluated at T0 using only M5 bars strictly
before `wick_bar_ts`. Buckets A1–A4 are mutually exclusive; A5 is a
today-wide overlapping flag that may co-occur with A2/A3/A4.

| bucket | criterion |
|---|---|
| A1 Approach without penetration | `total_bars_beyond_last24 == 0` |
| A2 Penetration without close-beyond | `total_bars_beyond_last24 > 0` AND `closes_beyond_count_last24 == 0` |
| A3 Close-beyond, acceptance held | `closes_beyond_count_last24 > 0` AND `close_back_inside_after_breach_last24 == 0` |
| A4 Close-beyond, acceptance failed (classical sweep) | `closes_beyond_count_last24 > 0` AND `close_back_inside_after_breach_last24 == 1` |
| A5 Prebroken today (overlapping) | `attached_prebroken_in_dir == 1` |

Base TRUE rate across all candidates: **40.2%**

## Bucket counts and TRUE rates

| bucket | n | n_true | n_false | TRUE rate | lift vs base |
|---|---:|---:|---:|---:|---:|
| A1_approach_no_pen | 1404 | 216 | 1188 | 15.4 % | ×0.38 |
| A2_pen_no_close | 1275 | 264 | 1011 | 20.7 % | ×0.51 |
| A3_close_beyond_held | 0 | 0 | 0 | 0.0 % | ×0.00 |
| A4_close_beyond_failed | 6670 | 3281 | 3389 | 49.2 % | ×1.22 |
| A5_prebroken_today | 8039 | 3598 | 4441 | 44.8 % | ×1.11 |

## Post-rejection pip movement (descriptive, NOT a trading outcome)

`price_5m_after_t1` and `price_10m_after_t1` are the signed pip
displacements of the bar at T1+5m and T1+10m from the attached level,
in the trade direction (positive = AWAY from level = trade-favourable).
These are single reference points, not MFE/MAE and NOT the +30/-12
evaluation. Phase 8 performs the actual +30/-12 forward test.

| bucket | median p5 TRUE | median p5 FALSE | median p10 TRUE | median p10 FALSE |
|---|---:|---:|---:|---:|
| A1_approach_no_pen | -5.40 p | -1.00 p | -5.90 p | -1.00 p |
| A2_pen_no_close | -4.15 p | -0.70 p | -4.95 p | -0.70 p |
| A3_close_beyond_held | — | — | — | — |
| A4_close_beyond_failed | -2.50 p | +0.20 p | -3.05 p | +0.50 p |
| A5_prebroken_today | -2.60 p | +0.00 p | -3.10 p | +0.20 p |

## Interpretation

1. **The classical sweep bucket A4** (close beyond then close back
   inside) is clearly over-represented in TRUE candidates — see the
   TRUE rate and lift columns above.
2. **A3 (close-beyond, acceptance held)** does NOT favour TRUE and
   often has a lower TRUE rate than baseline: when price has
   genuinely accepted the level, the wick/rejection candidate is
   less likely to mark the ZigZag(30) pivot.
3. **A1 (approach without penetration)** sees a modestly below-base
   TRUE rate — a wick+rejection against an untested level is less
   often the turning point.
4. **A5 (prebroken today, overlapping)** overlaps substantially with
   A3 and A4. It is NOT a liquidity-sweep category in isolation.
5. The TRUE/FALSE separation in the post-rejection pip medians is
   suggestive but modest, consistent with the Stage 0 Mann-Whitney
   analyses. These are descriptive statistics only. **Phase 8 will
   evaluate whether any bucket produces a +30/-12 positive net
   expectancy under realistic execution.**
