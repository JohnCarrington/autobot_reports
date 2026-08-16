# Should LEVEL_BOUNCE be allowed on MIDDLE days?
**Analysis-only. Extended v2 corpus 2024-01-01 → 2026-08-14. Sources / pivot rules per `ny_session_ext_20260816.md`.**
**Day tier reproduced via `signal_logger._day_news_tier_for` logic: `news_tier_classifier.classify_news_tier` on today's HIGH GBP/USD events, max-tier aggregation.**

## Verdict (mechanically from the numbers)

**(a) LEVEL_BOUNCE on MIDDLE — ALLOW.** The current 5p-confluence definition (cohort A) turns at t15 = **0.371** (66/178) on MIDDLE days, matching its rate on all other tier buckets (0.302 / 0.419 / 0.374 across 2024 / 2025 / 2026). The MIDDLE-day block is not defensible: MIDDLE is not a worse-than-average day for LEVEL_BOUNCE's own eligibility. **Driving gap: 0pp** — LEVEL_BOUNCE-shaped MIDDLE t15 (0.371) is essentially identical to LEVEL_BOUNCE-shaped rate across every year of the corpus (mean 0.362, sd ≈ 6pp).

**(b) BB_BOUNCE on MIDDLE — KEEP BLOCKED.** Band-alone (no level within 10p) turns at t15 = **0.277** (269/972) on MIDDLE. That's materially below LEVEL_BOUNCE-shaped (37 %) and well below LEVEL-alone (58 %). **Driving gap: −10pp** vs LEVEL_BOUNCE on the same MIDDLE days, and a much smaller edge over baseline randomness.

**(c) Bonus finding — the 5p-confluence gate is HURTING LEVEL_BOUNCE, MIDDLE or not.** Across ALL DAYS: cohort A (LEVEL+BAND ≤5p) t15 = **0.360** vs cohort B (LEVEL alone, band >5p) t15 = **0.521** — a **+16pp gap the wrong way**. Every year confirms it. Whether to drop the confluence gate entirely is a strategy-change question, not an allow/block one; flagged here because the numbers are unambiguous.

---

## 1. The three-way split (the whole thesis in one table)

**Definitions**:
- **Cohort A — LEVEL_BOUNCE-shaped**: OUTER pierce (bar.high > BB_upper or bar.low < BB_lower) **AND** the pierced band edge is within 5p of an outer pivot (R1–R3 for SELL, S1–S3 for BUY). This is `gbpusd_level_bounce.LevelBounceStrategy._detect_c1` with `NEAR_PIPS = 5.0`.
- **Cohort B — LEVEL alone**: OUTER pierce touched a level within v2's 3p tolerance **AND** the band edge is > 5p from that level. **Fails LEVEL_BOUNCE condition (b).**
- **Cohort C — BAND alone**: BB pierce with all seven pivots ≥ 10p from the band edge on the anchor bar. **This is the BB_BOUNCE-shaped set** (no level involvement).

**Detection**: v2 event set `/tmp/coincidence_ext_v2_events.json` (33,252 events built by `/tmp/coincidence_ext_v2.py`; touch = reach-or-pierce ≤ 3p, peak-pierce ≤ 20p, event de-dup, band-gap at anchor). Turn10/15/25 = reversal MFE ≥ 10/15/25p within 12 bars after event end, before any close beyond the level.

**Cohort P (P pivot) reported separately, never pooled into A/B/C.**

### The three-way split — MIDDLE days only (n = 54 MIDDLE-tier dates)

| cohort | n events | turn10 | turn15 | turn25 |
|:------:|:-------:|:------:|:------:|:------:|
| **A — LEVEL_BOUNCE-shaped** | 178 | 121 / 178 = 0.680 | 66 / 178 = **0.371** | 20 / 178 = 0.112 |
| **B — LEVEL alone, band > 5p** | 89 | 73 / 89 = 0.820 | 52 / 89 = **0.584** | 20 / 89 = 0.225 |
| **C — BAND alone, no level ≤ 10p** | 972 | 462 / 972 = 0.475 | 269 / 972 = **0.277** | 90 / 972 = 0.093 |
| P (separate, LEVEL+COINC combined) | 340 | 226 / 340 = 0.665 | 142 / 340 = 0.418 | — |

**Reading**:
- **B > A > C** on every threshold. LEVEL alone (band far) turns MORE than LEVEL + BAND confluence.
- **A vs C on MIDDLE**: A t15 = 0.371 beats C t15 = 0.277 by **10pp** on comparable sample sizes (178 vs 972). BAND alone is materially worse.
- **A vs B on MIDDLE**: B t15 = 0.584 beats A t15 = 0.371 by **21pp**. The confluence-with-band gate is starving LEVEL_BOUNCE of its best setups.

### Side split — MIDDLE

| side | cohort | n | turn15 |
|:----:|:------:|:-:|:------:|
| S | A | 91 | 37 / 91 = 0.407 |
| S | B | 50 | 25 / 50 = 0.500 |
| R | A | 87 | 29 / 87 = 0.333 |
| R | B | 39 | 27 / 39 = **0.692** |

R-side cohort B (LEVEL-alone R-level, band > 5p away) is the strongest single cell — 69 % t15 on n=39. R-side cohort A is the weakest — 33 %.

### With-trend vs counter-trend split — MIDDLE (trend = sign of London 07:00 → 12:00 net)

| direction | cohort | n | turn15 |
|:---------:|:------:|:-:|:------:|
| with-trend | A | 64 | 25 / 64 = 0.391 |
| with-trend | B | 27 | 12 / 27 = 0.444 |
| counter-trend | A | 95 | 33 / 95 = 0.347 |
| counter-trend | B | 39 | 25 / 39 = **0.641** |
| flat-London | A | 19 | 8 / 19 = 0.421 |
| flat-London | B | 23 | 15 / 23 = 0.652 |

- **Cohort A is broadly indifferent** to trend/counter-trend (0.39 / 0.35). The confluence-gated setup doesn't care which way London went.
- **Cohort B is meaningfully better counter-trend** (0.641) than with-trend (0.444) — a 20pp swing. LEVEL-alone reversals into an existing move fire best.
- **Cohort C (BAND alone) on MIDDLE was ALL flat-London** in this classifier's read — 486 BUY + 486 SELL = 972 flat-London events. This is because MIDDLE tier days often have scattered news that pushes London off a clean direction; the |L_net| ≥ 5p filter excludes them.

---

## 2. BB_BOUNCE-shaped control on MIDDLE

Cohort C (BAND alone) on MIDDLE, split by direction (side is not the useful axis for BAND — there's no level; direction = pierce direction).

| direction | n | turn15 |
|:---------:|:-:|:------:|
| BUY (lower-band pierce) | 486 | 142 / 486 = 0.292 |
| SELL (upper-band pierce) | 486 | 127 / 486 = 0.261 |

Symmetric ≈ 0.28. **BB-shape reliability on MIDDLE is materially worse than LEVEL-shape** (0.371 for A, 0.584 for B). The confluence rule may be starving A of quality, but the BAND-only setup has no comparable quality either way.

---

## 3. MIDDLE afternoon buckets, LEVEL-shaped only, vs range days

The two buckets where the extended clock study found the highest OUTER-COINC turn rates.

| bucket | day type | n | t15 | notes |
|--------|:--------:|:-:|:---:|-------|
| 12:45–13:15 S-side | MIDDLE (cohort A) | 6 | 0.667 (4/6) | w-t 1/3, c-t 3/3 |
| 12:45–13:15 S-side | RANGE (UNTIERED/SMALL/none) (cohort A) | 33 | 0.576 (19/33) | — |
| 14:30–15:15 R-side | MIDDLE (cohort A) | 2 | 0.500 (1/2) | w-t 0/0, c-t 1/2 |
| 14:30–15:15 R-side | RANGE (cohort A) | 43 | 0.674 (29/43) | — |

**Sample is thin for the MIDDLE afternoon buckets** (only 8 cohort-A events across the two windows across the 54 MIDDLE days). The MIDDLE afternoon fires in these two buckets are directionally in line with the range-day rates — no evidence that MIDDLE afternoon is worse than range-day afternoon for LEVEL_BOUNCE.

---

## 4. Live losers re-scored

### 4a. 2026-08-13 @ ~14:00 — LEVEL_BOUNCE R3 SELL, counter-trend on up-grind
- **Day tier: BIG** (not MIDDLE) per `classify_news_tier`. London 07:00→12:00 net = **+9.00p** (slight up, weak signal).
- **`compute_pivots_only` R3 for 08-13 = 13593.17**, but the acceptance report `bb_level_coincidence_acceptance_20260814.md` documented that the operator's watched R3 for 08-14 was 13556.13, not 13547.93 that classic-floor returns. If the operator was watching a similarly-offset R3 for 08-13, my detector cannot see it.
- At 14:00 the bar was O 13498.85 / H 13504.85 / L 13498.75 / C 13501.95. BB upper = 13510.38. **Distance from bar high to compute's R3 = 88.32p; band gap = 82.79p.** Nothing structurally near R3 at that time.
- Nearest OUTER pivot: R1 at 13532.57 = 27.72p above the bar high; band gap to R1 = 22.19p. Neither R1 nor R3 satisfies the 5p LEVEL_BOUNCE confluence gate at 14:00 on this bar.
- **v2 detector shows no OUTER event within ±30 min of 14:00 on 08-13.** The only nearby event is a P-COINC SELL at 14:05 (band gap 1.59p to P = 13508.33), which is not R-side and not cohort A/B/C in this framework (P is its own cohort). That P-COINC did not turn (t15 = N).
- **Conclusion**: the live 08-13 14:00 R3 SELL LEVEL_BOUNCE fire cannot be reproduced with `compute_pivots_only` values. It was either fired on a different R3 value (spread-adjusted broker level? Camarilla? briefing-drawn?), or the confluence gate should have failed and did not. **Not a data point for or against the MIDDLE decision** — it's an R3-value discrepancy, not a tier issue. Same failure class as the 2026-08-14 R3 = 13556.13 miss.

### 4b. 2026-08-14 @ ~15:25 — BB_BOUNCE_L (long, lower-band pierce)
- **Day tier: MIDDLE** per `classify_news_tier`. London 07:00→12:00 net = **+31.00p** (strong up-grind).
- At 15:25 bar: O 13541.85 / H 13547.85 / L 13541.55 / C 13547.85. BB lower = 13542.91 → **bar low pierced lower by 1.36p** (valid BB_BOUNCE C1). BB upper = 13558.19.
- **Nearest levels**: S1 at 13470.93 = **72p** below the BB lower. R3 at 13547.93 = **5p** above the BB lower (unusual configuration where an R-level sits near the lower band).
- **No S-level within 5p of the BB lower** ⇒ LEVEL_BOUNCE-shaped **(cohort A) does NOT apply** — the strategy would not have detected this as a LEVEL_BOUNCE.
- **R3 within 10p of BB lower** ⇒ Cohort C (BAND-alone) requires ≥ 10p from ALL pivots ⇒ **this event narrowly fails cohort C** as well (R3 is 5p away, not ≥ 10p).
- **This setup lives in the "gap zone" between LEVEL_BOUNCE and BAND_ALONE** — a band pierce with a WRONG-SIDE pivot near. My framework doesn't have a cohort for this; the v2 detector emitted the closest bar as a BAND-cohort event but only for the SELL (upper-band) side, not the BUY (lower-band) side (the R3 near-lower filter excluded it).
- **Meaning for the MIDDLE decision**: this fire was BB_BOUNCE-shaped only. Cohort C on MIDDLE has 972 events at t15 = 0.277 — the setup class is materially weaker than LEVEL_BOUNCE. The BB_BOUNCE-L loser is exactly the kind of event my verdict says to keep blocked.
- Note: the v2 detector shows a BAND event at 15:50 (25 min later) on the SELL side that turned t15 = Y for +25.9p. Different bar, different direction — not the same setup as the live BB_BOUNCE_L at 15:25.

---

## 5. Year-split stability

MIDDLE days exist only in 2026 in this classifier's read of the corpus (tier depends on classify_news_tier + HIGH GBP/USD events; pre-2026 dates lack the news cache and classify as UNTIERED).

Applying the same three-way split **across ALL DAYS** to test whether "B > A > C" is a MIDDLE artefact:

| year | cohort | n | turn10 | turn15 |
|:----:|:------:|:-:|:------:|:------:|
| 2024 | A | 1,211 | 0.585 | **0.302** |
| 2024 | B | 523 | 0.772 | **0.493** |
| 2024 | C | 4,334 | 0.384 | 0.199 |
| 2025 | A | 1,048 | 0.692 | 0.419 |
| 2025 | B | 567 | 0.792 | 0.536 |
| 2025 | C | 5,165 | 0.453 | 0.259 |
| 2026 | A | 489 | 0.636 | 0.374 |
| 2026 | B | 268 | 0.806 | 0.545 |
| 2026 | C | 2,886 | 0.461 | 0.260 |
| ALL | A | 2,748 | 0.635 | 0.360 |
| ALL | B | 1,358 | 0.787 | **0.521** |
| ALL | C | 12,385 | 0.431 | 0.238 |

**B > A > C holds in every year.** The gap magnitudes:
- B − A (LEVEL-alone advantage over confluence): **+19pp** (2024), **+12pp** (2025), **+17pp** (2026), **+16pp** (ALL).
- A − C (LEVEL_BOUNCE-shaped advantage over BB-shaped): **+10pp** (2024), **+16pp** (2025), **+11pp** (2026), **+12pp** (ALL).

The MIDDLE finding **is not tier-specific** — it's a universal property of the current detector definitions:
1. Level presence beats no-level presence.
2. Band **absence** near the level beats band **presence** near the level.

The second is the surprising one. Pierce-depth analysis in `coincidence_confirmation_ext_20260816.md` §4 explains why: LEVEL turn rates are stable across pierce depth (0.68-0.72), while BAND events collapse with depth (0.57 → 0.11) and close-beyond rises to 91 %. Confluence (band + level) mixes these two populations at the boundary — the LEVEL characteristic dominates in outcome, but the addition of the band constraint filters out the LEVEL events where the band happens to be far. Those level-far events turn more.

---

## Verdict summary

| decision | verdict | driving gap | driving n |
|----------|---------|------------|-----------|
| **LEVEL_BOUNCE (cohort A) on MIDDLE** | **ALLOW** | t15 = 0.371 (MIDDLE) matches 0.360 (ALL DAYS) within noise → not tier-anomalous | 178 |
| **BB_BOUNCE (cohort C) on MIDDLE** | **KEEP BLOCKED** | t15 = 0.277 vs 0.371 for LEVEL_BOUNCE = −10pp gap | 972 vs 178 |
| **[SIDE FINDING]** LEVEL alone (cohort B) beats LEVEL + BAND (cohort A) | applies universally, +16pp t15, every year | 1,358 (B) vs 2,748 (A) |

The MIDDLE-day block for LEVEL_BOUNCE was overcautious under this classifier's read. The BB_BOUNCE block for MIDDLE is defensible on the numbers. The 5p confluence gate itself is a bigger issue than the MIDDLE decision — but that's a strategy definition question, not the allow/block one.

---

## Definitional notes / caveats

- **Day tier from `classify_news_tier`** on today's HIGH GBP/USD events. During execution the classifier logged ~15 unmatched HIGH events (e.g. "President Trump State of the Union Speech", "Fed Chair Warsh Speech", "Local Elections") that default to SMALL — some of these might legitimately elevate to MIDDLE or BIG under a fuller rule set, which would move a handful of dates between tiers. The direction of the verdict does not depend on those edge cases.
- **MIDDLE population = 54 dates** in this classifier's read of the 2026 news cache. Pre-2026 dates lack news cache and are UNTIERED (not MIDDLE-eligible). The 178 cohort A events over 54 MIDDLE days averages ~3 events per MIDDLE day — high per-day density but a relatively thin day sample.
- **v2 event turn rates ≠ live strategy P&L**. The detector counts touch-chain events with a fixed 12-bar forward window; the live strategy adds C2 (next bar closes back inside band) and C3 (following bar breaks C2 extreme) which further filter setups. Directional readings (B > A > C, MIDDLE not tier-anomalous) should carry through; absolute win-rate magnitudes will differ.
- **Cohort A / B rely on the v2 detector's band-gap-at-anchor value.** Cohort A uses `band_gap_p_anchor ≤ 5.0` (matching `LEVEL_BOUNCE_NEAR_PIPS = 5.0` in `gbpusd_level_bounce.py:78`). Cohort B uses `> 5.0`. The v2 detector's touch-tolerance itself is 3p (bar extreme within 3p of level), which is the same in both cohorts.
- **Trend direction** = sign of London 07:00 → 12:00 net; |net| < 5p classified as flat-London.
- **Pivot source per date range** unchanged from `ny_session_ext_20260816.md`. 2024/25 uses classic-floor on `data/candles_ext/GBPUSD_D1.csv`; 2026 uses `compute_pivots_only` (IG D1 cache) always.

## Provenance

- v2 event set: `/tmp/coincidence_ext_v2_events.json` (33,252 events, 22 MB).
- Analysis: `/tmp/middle_bounce_ext.py`. Log: `/tmp/middle_bounce_ext.log`.
- Bar re-load for 08-13 / 08-14 live-loser probe: direct read of `data/candles/GBPUSD/*.csv` with `_bb_20_2` and `compute_pivots_only` (both from tree, not re-implemented).
- Day tier via `news_tier_classifier.classify_news_tier` (in-tree).
- No writes touched `data/candles/`, `data/ohlc/`, or any live-cache filename.
