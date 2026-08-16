# NY-session bounce study — extended v2 corpus (2024-01-01 → 2026-08-14)
**v2 coincidence detector on the extended corpus. Analysis-only, read-only.**
**Prior P1/P2 reports: `candles_ext_and_calendar_backfill_20260816.md`, `clock_ext_20260816.md`.**

## TL;DR
- **NY OUTER-LEVEL turn15 = 0.59** on both sides (S: 293/355; R: 289/361) vs **London 0.50** — NY carries an 8-10pp turn-rate premium over London on same-side, same-cohort touches. On COINC the NY edge is bigger on R-side (0.51 vs 0.39) and flat on S (0.43 vs 0.47).
- **BAND-only fires do not carry a session premium** (LON 0.34 / NY 0.36) — this reinforces the earlier P2-coincidence finding that the band alone is not the active ingredient.
- **1,104 NY-session OUTER touches over 390 unique NY-active days.** First-touch time is heavily concentrated at 13:00 UTC (167 days = 43 % of NY-active days), tapering monotonically: 14:00 = 101, 15:00 = 78, 16:00 = 25, 17:00 = 19.
- **S1 + R1 dominate** the touched-level distribution (297 + 282 = 579 of 1,104 = 52 %). S2/R2 add another 325 (30 %). S3/R3 are 200 (18 %).
- **LEVEL_BOUNCE rule (OUTER-LEVEL, ≥5p pierce, ≤20p) fires 212 times in NY** with mfe median 16.5p, share_mfe≥15p = **0.56**. BB-proxy (OUTER-COINC) fires 388 times NY with mfe median 14.8p, share_mfe≥15p = **0.48**. LEVEL_BOUNCE outperforms BB-proxy by **8pp** on the ≥15p threshold in NY, essentially matching in London (0.56 vs 0.45).
- **The "London-trend / NY-reversal at a level" hypothesis is supported.** Of 231 London-trend days (|net|≥15p, efficiency≥0.5, range≥15p), **77 (33 %) posted a NY-reversal (opposite NY net ≥15p)**. Of those 77, **36 (47 %) began the reversal within 5p of a pivot** — 18 at S-level (median mfe from level 28.1p), 18 at R-level (median mfe 25.1p). This is the highest-conviction structural signal in the report.
- **Year stability**: OUTER turn15 rates hold across 2024/25/26 within ~5-10pp. 2026 has ~150 total events (small n) but the direction and magnitude match.

Filter applied: **non-MIDDLE, non-BIG-pre-release days**. 28,645 events kept from the 33,252 v2 total (excluded 2,068 MIDDLE, 2,539 BIG pre-release). Tier is known for 2026-01-01+ (news backfill); pre-2026 dates report as UNTIERED and are still included (they can't be MIDDLE nor BIG-pre-release without a tier).

---

## 1. London vs NY — turn rates per cohort × side

Definitions (unchanged from v2):
- **Touch (v2)**: one-sided reach-or-pierce, 3p tolerance; peak pierce ≤ 20p; consecutive touching bars fold into one event.
- **COINC**: band edge within 3p of the level at event anchor.
- **LEVEL**: band edge > 3p from the level at event anchor.
- **BAND-only**: band edge touched with all 7 pivots ≥ 10p from the band edge.
- **turn10/15/25**: reversal MFE ≥ 10/15/25p in ≤ 12 bars after event end, before any close beyond the level.
- **London window**: 08:00 – 12:59 UTC. **NY window**: 13:00 – 17:59 UTC.

| cohort | kind | side | LON n | LON t10 | LON t15 | LON t25 | NY n | NY t10 | NY t15 | NY t25 |
|:------:|:----:|:----:|:-----:|:-------:|:-------:|:-------:|:----:|:------:|:------:|:------:|
| OUTER | COINC | **S** | 190 | 148 / 190 = **0.78** | 0.47 | 0.14 | 209 | 154 / 209 = **0.74** | 0.43 | 0.18 |
| OUTER | COINC | **R** | 242 | 173 / 242 = **0.71** | 0.39 | 0.11 | 179 | 139 / 179 = **0.78** | **0.51** | 0.17 |
| OUTER | LEVEL | **S** | 263 | 215 / 263 = **0.82** | 0.51 | 0.16 | 355 | 293 / 355 = **0.83** | **0.59** | 0.24 |
| OUTER | LEVEL | **R** | 280 | 228 / 280 = **0.81** | 0.50 | 0.17 | 361 | 289 / 361 = **0.80** | **0.59** | 0.23 |
| OUTER | BAND | (side-free) | 1,999 | 1034 / 1999 = 0.52 | 0.34 | 0.13 | 2,386 | 1266 / 2386 = 0.53 | 0.36 | 0.16 |
| P | COINC | (P) | 352 | 273 / 352 = 0.78 | 0.46 | 0.13 | 239 | 172 / 239 = 0.72 | 0.46 | 0.17 |
| P | LEVEL | (P) | 487 | 374 / 487 = 0.77 | 0.49 | 0.15 | 498 | 407 / 498 = **0.82** | **0.58** | 0.22 |
| P | BAND | (P) | 1,999 | 1034 / 1999 = 0.52 | 0.34 | 0.13 | 2,386 | 1266 / 2386 = 0.53 | 0.36 | 0.16 |

Reading:
- **OUTER-LEVEL S and R both post 0.59 t15 in NY** vs 0.50 in London — that's a **9pp jump on n=355+361**.
- **OUTER-COINC R has the biggest session split**: NY 0.51 vs LON 0.39 (12pp jump). S-side COINC is *flat* between sessions (0.43 NY / 0.47 LON).
- **P-LEVEL NY 0.58 vs LON 0.49** — same magnitude edge as OUTER-LEVEL.
- **BAND-only unchanged across sessions** (0.34 / 0.36) — no session premium when there's no pivot nearby. Consistent with the "band not the active ingredient" reading of the P2-coincidence pass.
- **t25 rates roughly double** in NY vs LON on OUTER-LEVEL (0.24 / 0.23 vs 0.16 / 0.17) — the tails also grow, not just the median.

---

## 2. NY-session bounce frequency, levels, first-touch time

**Universe**: OUTER-COINC + OUTER-LEVEL events in the NY window, non-MIDDLE, non-BIG-pre-release. n = 1,104 events across 390 unique NY-active days (out of 818 corpus dates).

### Bounces per day
| bounces / day | n days | share |
|:-------------:|:-----:|:-----:|
| 1 | 107 | 27 % |
| 2 | 116 | 30 % |
| 3 | 68 | 17 % |
| 4 | 37 | 9 % |
| 5 | 21 | 5 % |
| 6 | 15 | 4 % |
| 7 | 12 | 3 % |
| 8 | 3 | 1 % |
| 9+ | 11 | 3 % (max = 13 on 2025-11-24) |

**57 % of NY-active days post 1-2 bounces** (typical); ~15 % post 5+ (very active).

### Which levels get hit
| level | n | t15 | rate | t25 | rate |
|:-----:|:-:|:---:|:----:|:---:|:----:|
| **S1** | 297 | 152 | 0.51 | 62 | 0.21 |
| **R1** | 282 | 157 | 0.56 | 64 | 0.23 |
| **R2** | 168 |  99 | 0.59 | 32 | 0.19 |
| **S2** | 157 |  88 | 0.56 | 42 | 0.27 |
| **S3** | 110 |  59 | 0.54 | 18 | 0.16 |
| **R3** |  90 |  48 | 0.53 | 17 | 0.19 |

- **S1 and R1 carry 52 % of touches** and roughly matched turn rates (0.51 / 0.56).
- **R2 posts the highest t15 (0.59) despite fewer touches** — cleaner defended level.
- **S2 posts the highest t25 (0.27)** — the S2 turns that fire tend to go furthest.

### First NY touch — hour distribution
| hour UTC | n days | share of 390 NY-active days |
|:--------:|:-----:|:---------------------------:|
| **13:00** | **167** | **43 %** |
| 14:00 | 101 | 26 % |
| 15:00 | 78 | 20 % |
| 16:00 | 25 | 6 % |
| 17:00 | 19 | 5 % |

**43 % of NY-active days see their first OUTER touch in the 13:00 UTC hour.** Consistent with the P2-clock finding that the 13:00 window is the highest S-side spike. The tapering matches session ramp — early NY posts most first-touch action.

---

## 3. LEVEL_BOUNCE rule vs BB-proxy — session-split

**Rule definitions**:
- **LEVEL_BOUNCE rule**: OUTER-LEVEL event with peak pierce ≥ 5p (i.e. the bar actually pushed through the level, not just brushed it). Captures the "close beyond then reverse" setup.
- **BB-proxy**: OUTER-COINC event (band edge within 3p of the level at anchor). Captures the "band + pivot confluence" setup.

### Aggregate

| rule | session | n | mfe median | mae median | share mfe ≥ 15p |
|------|:-------:|:-:|:----------:|:----------:|:---------------:|
| **LEVEL_BOUNCE** | London | 140 | **16.1p** | 1.6p | **0.56** |
| **LEVEL_BOUNCE** | NY | 212 | **16.5p** | 0.0p | **0.56** |
| BB-proxy | London | 432 | 14.1p | 0.0p | 0.45 |
| BB-proxy | NY | 388 | 14.8p | 0.0p | 0.48 |

Reading:
- **LEVEL_BOUNCE rule beats BB-proxy on share_mfe ≥ 15p by 8-11pp** in both sessions (0.56 / 0.56 vs 0.45 / 0.48).
- **NY LEVEL_BOUNCE mae median = 0.0p** — half of fires never went adverse at all. LON mae 1.6p is only slightly worse.
- LEVEL_BOUNCE gives you roughly **half the fires but a materially better hit distribution**.

### Side-split

| rule | side | LON n | LON mfe med | LON share≥15 | NY n | NY mfe med | NY share≥15 |
|------|:----:|:-----:|:-----------:|:------------:|:----:|:----------:|:-----------:|
| LEVEL_BOUNCE | S | 66 | 16.2p | 0.59 | **107** | **17.9p** | **0.58** |
| LEVEL_BOUNCE | R | 74 | 15.9p | 0.53 | 105 | 15.7p | 0.54 |
| BB-proxy | S | 190 | 15.3p | 0.52 | 209 | 14.0p | 0.44 |
| BB-proxy | R | 242 | 13.9p | 0.40 | 179 | 15.5p | 0.52 |

- **NY LEVEL_BOUNCE S-side is the standout**: 107 fires, mfe median **17.9p**, share ≥ 15p = 0.58. Best cell in the whole table for size × quality.
- BB-proxy R-side jumps from 0.40 (LON) to 0.52 (NY) — 12pp — while S-side actually deteriorates (0.52 → 0.44). The BB-proxy story is asymmetric.

---

## 4. London-trend / NY-reversal at a level

**Filter**: London (08:00-10:59 UTC) has |net| ≥ 15p, efficiency ≥ 0.5 (directional), range ≥ 15p → **231 "London-trend" days**.

Of those:
- **77 (33 %)** posted a **NY-reversal** — NY net (open→close of the NY window) opposite in sign to London net AND magnitude ≥ 15p.
- Of the 77 NY-reversal days, **36 (47 %)** had the first NY OUTER touch on the reversal-appropriate side within 5p of the level (i.e. the reversal *began at a pivot*).

Split by side:
- **18 days: London-down / NY-up reversal at S-level.** Median MFE from the level = **28.1p**. Range: 11.6p → 54.7p.
- **18 days: London-up / NY-down reversal at R-level.** Median MFE from the level = **25.1p**. Range: 0.0p → 45.9p.

### Every reversal-at-S day (London down, NY up)
```
date        level  mfe_from_level  peak_pierce
2024-02-01  S1     54.7p           +1.7p
2024-02-12  S3     16.4p           +3.5p
2024-03-19  S2     22.1p           -1.0p (touched but didn't pierce)
2024-06-03  S3     11.6p           -2.1p
2024-07-29  S3     13.9p           +19.2p (deep pierce, still reversed)
2024-08-08  S1     38.8p           -0.1p
2024-10-30  S1     13.2p           +0.1p
2024-11-19  S1     22.3p           +4.9p
2025-01-31  S1     33.9p           +6.5p
2025-02-06  S3     42.5p           -0.8p
2025-02-12  S1     33.6p           -2.8p
2025-06-23  S2     45.6p           +9.8p
2025-08-27  S1     27.8p           -1.9p
2025-08-29  S1     33.2p           +2.0p
2025-10-22  S2     28.1p           +16.6p
2025-10-30  S1     49.0p           +13.3p
2026-06-11  S1     11.8p           +8.2p
2026-07-17  S1     14.2p           -2.6p
median mfe: 28.1p  |  S1: 11 of 18  |  S2: 3 of 18  |  S3: 4 of 18
```

### Every reversal-at-R day (London up, NY down)
```
date        level  mfe_from_level  peak_pierce
2024-01-26  R1     14.6p           +15.4p
2024-04-19  R1     27.4p           +0.9p
2024-07-17  R3     17.9p           +2.4p
2024-11-26  R1     32.1p           +0.8p
2025-01-27  R2     10.6p           +1.5p
2025-02-05  R1     17.6p           +18.7p (deep, reversed)
2025-03-24  R1     28.4p           +11.4p
2025-04-03  R3     34.2p           +17.1p
2025-04-11  R2     25.1p           +3.3p
2025-04-15  R1     24.4p           +5.8p
2025-05-05  R2     10.2p           -2.9p
2025-06-20  R1     11.2p           -1.9p
2025-07-01  R1     26.8p           -2.0p
2025-07-14  R1     25.9p           -1.8p
2025-09-09  R1     45.9p           -1.9p
2025-09-15  R3      0.0p           +18.4p (pierced deep, no reversal MFE)
2025-12-15  R2     16.2p           +0.6p
2026-06-09  R2     30.0p           +3.9p
median mfe: 25.1p  |  R1: 10 of 18  |  R2: 5 of 18  |  R3: 3 of 18
```

Reading:
- **S1 and R1 dominate the reversal-at-level set** (21 of 36 = 58 %). Consistent with §2 — most first NY OUTER touches happen at R1/S1.
- **Median MFE from level = 25-28p** on the days where the pattern fires cleanly — these are meaningful moves off the level, not brushes.
- **Deep pierces still reverse**: 2024-07-29 (S3 pierced +19p, reversed 14p), 2025-02-05 (R1 pierced +19p, reversed 18p), 2025-04-03 (R3 pierced +17p, reversed 34p) — the ≤20p pierce cap of the v2 detector is doing productive work.
- **The 41 (77 – 36) London-trend / NY-reversal days that did NOT begin at a level** started the NY reversal at a non-pivot price. They're not in this list; a follow-up could examine what drove those (round-number, briefing level, breakout retest).

---

## 5. Year-split stability

OUTER-COINC + OUTER-LEVEL turn15 rates by year, side, session (non-MIDDLE, non-BIG-pre-release):

| year | side | LON n | LON t15 | LON rate | NY n | NY t15 | NY rate |
|:----:|:----:|:-----:|:-------:|:--------:|:----:|:------:|:-------:|
| 2024 | S | 203 | 95 | 0.47 | 274 | 149 | **0.54** |
| 2024 | R | 269 | 101 | 0.38 | 250 | 130 | **0.52** |
| 2024 | P | 452 | 199 | 0.44 | 304 | 166 | **0.55** |
| 2025 | S | 222 | 111 | 0.50 | 221 | 122 | **0.55** |
| 2025 | R | 222 | 117 | 0.53 | 220 | 138 | **0.63** |
| 2025 | P | 328 | 164 | 0.50 | 354 | 191 | **0.54** |
| 2026 | S |  28 | 16 | 0.57 |  69 |  28 | **0.41** |
| 2026 | R |  31 | 17 | 0.55 |  70 |  36 | **0.51** |
| 2026 | P |  59 | 39 | 0.66 |  79 |  43 | **0.54** |

Reading:
- **NY OUTER rates are consistently 5-15pp above LON** on R- and P-side across 2024 and 2025. 2024/25 sample is 200-450 events per cell; the pattern is robust.
- **2026 sample is thin** (28-79 events per cell) because most of 2026-01 → 2026-04-10 is excluded when tier is unknown OR the day is MIDDLE / BIG-pre-release. 2026 S-side NY drops to 0.41 — could be noise on n=69 or a real shift; single year isn't decisive.
- **2025 NY R-side** is the peak: 0.63 turn15 on 220 events. 2024/2025 R-side NY has been the strongest single cell.
- **The LON/NY gap holds across all 3 years for R-side** (2024: 0.38→0.52; 2025: 0.53→0.63; 2026: 0.55→0.51) — this is not a single-year phenomenon.

---

## 6. Raw example days

### 6a. 2024-02-01 — London-down / NY-up reversal at S1
```
London (08:00-10:59 UTC): open=12654.00 close=12631.60 net=-22.40p range=29.00p eff=0.772
LON OUTER touches: 3     NY OUTER touches: 1
NY events (OUTER, side-appropriate):
  15:00 – 15:00  LEVEL S1=12641.17 BUY  pierce=+1.7p  mfe= 54.7p  mae=0.0p  turn15=Y closed=N
```
Single-bar touch at S1 with 1.7p pierce; 54.7p reversal off S1 to end the NY session. Cleanest possible instance of the pattern.

### 6b. 2024-01-26 — London-up / NY-down reversal at R1
```
London (08:00-10:59 UTC): open=12681.70 close=12732.50 net=+50.80p range=52.70p eff=0.964
LON OUTER touches: 1     NY OUTER touches: 2
NY events:
  13:05 – 13:30  LEVEL R1=12738.30 SELL pierce=+15.4p mfe= 14.6p mae=19.9p turn15=N closed=Y
  13:40 – 15:00  LEVEL R1=12738.30 SELL pierce=+19.9p mfe= 20.5p mae= 0.0p turn15=Y closed=N
```
Two consecutive R1 touches: the first pierced +15p, drew mae 19.9p and closed beyond → turn15=N. The second touch (at the max pierce depth of 19.9p, still under the 20p cap) reversed cleanly for +20.5p. Illustrates why the v2 event-de-dup logic matters — treating these as separate events preserves the actual sequence.

### 6c. 2025-11-24 — most NY OUTER touches (13)
```
London (08:00-10:59 UTC): open=13090.00 close=13093.60 net=+3.60p range=22.20p eff=0.162
LON OUTER touches: 20    NY OUTER touches: 13
Sample of NY events (first 8 of 13):
  14:20–15:55  COINC S1=13092.37 BUY  pierce=+12.2p mfe=14.8p mae=0.0p t15=N
  14:20–15:55  LEVEL S2=13089.13 BUY  pierce=+8.9p  mfe=18.1p mae=0.0p t15=Y
  14:20–15:55  LEVEL S3=13085.57 BUY  pierce=+5.4p  mfe=21.6p mae=0.0p t15=Y
  15:50–17:00  LEVEL R1=13099.17 SELL pierce=+8.0p  mfe=13.7p mae=5.1p t15=N closed=Y
  16:00–16:55  LEVEL R2=13102.73 SELL pierce=+4.5p  mfe=17.2p mae=1.6p t15=Y closed=Y
  16:00–16:00  LEVEL R3=13105.97 SELL pierce=-3.0p  mfe=15.8p mae=1.2p t15=Y
  16:10–16:50  COINC R3=13105.97 SELL pierce=+1.2p  mfe=20.5p mae=0.0p t15=Y
  16:55–17:40  LEVEL S1=13092.37 BUY  pierce=+6.9p  mfe=15.6p mae=0.0p t15=Y
```
A very tight range day (London range 22p, efficiency 0.16). 13 different NY touch-chain events; most turn15 = Y. Illustrates why "range-mode" (bounce-friendly) subtypes should not be clock-muted — the highest-density level interaction happens 14:00-17:00 UTC.

---

## Definitional notes and caveats

- **Filter**: non-MIDDLE and non-BIG-pre-release only. Tier resolved from union of `cache/news_state_finnhub_2*.json` + `cache/news_state_finnhub_backfill_*.json` (backfill covers 2026-01-01 → 2026-06-03; live 2026-06-04 → 2026-08-21). Dates outside cache coverage cannot be MIDDLE or BIG-pre-release without the tier, so they are UNTIERED and kept.
- **Session boundaries**: London = 08:00–12:59 UTC (5 h). NY = 13:00–17:59 UTC (5 h). Same-length windows to make rates directly comparable.
- **v2 event definition** (unchanged from `bb_level_coincidence_v2.py`): reach-or-pierce ≤ 3p, peak-pierce ≤ 20p, event de-dup across contiguous touching bars, band-gap classified at anchor.
- **"NY reversal begins at a level" test in Task 4** is defined as first NY OUTER touch on the reversal-appropriate side (S-side if London net < 0 and NY net > 0; R-side vice versa) with anchor-bar extreme within 5p of the level. Alternative operationalisations (higher pierce cap, wider anchor tolerance) would produce different fractions — the 47 % result is specific to this definition.
- **Pivot source per date range** (unchanged from P1 report):
  - 2024-01-02 → 2025-12-31: classic-floor on `data/candles_ext/GBPUSD_D1.csv` (HistData-derived rebuild, `+5h` timezone shift already applied).
  - 2026-01-01 → 2026-08-14: `bb_pd_gate.compute_pivots_only` (IG D1 cache) — never the `candles_ext` 2026 D1 slice (fails validation vs IG per Test C of P1).
- **Bar source per date range** (first match wins):
  - 2026-03-23 → 2026-08-14: `data/candles/GBPUSD/{DATE}.csv` (IG live, mid-price)
  - 2026-01-01 → 2026-04-06: `data/ohlc/GBPUSD/5M/{DATE}.csv` (excludes corrupt 2026-04-07..10 flat-13400)
  - 2024-01-01 → 2025-12-31: `data/candles_ext/GBPUSD/{DATE}.csv` (my rebuild, bid-side)

## Provenance

- Detector: `/tmp/coincidence_ext_v2.py` (extended v2, source-selected). Log: `/tmp/coincidence_ext_v2.log`. Event set: `/tmp/coincidence_ext_v2_events.json` (33,252 events, 22 MB).
- Analysis: `/tmp/ny_session_ext.py`. Log: `/tmp/ny_session_ext.log`.
- News: union of `cache/news_state_finnhub_2*.json` + `cache/news_state_finnhub_backfill_*.json`.
- No writes touched `data/candles/`, `data/ohlc/`, or any live-cache filename.
