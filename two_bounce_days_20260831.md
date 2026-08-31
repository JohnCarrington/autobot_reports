# Two-bounce days — GBPUSD extended corpus 2024-01-01 → 2026-08-14

**Read-only counting study.** No P&L simulation. No live-path changes.

## Definitions (verbatim, no silent choices)

**BOUNCE (episode, not event)**: price touches or pierces (≤3p tolerance, peak pierce ≤20p) a **tracked level**, then reverses **≥25.0 pips from the extreme reached**, within **36 five-minute bars (3 hours)** after that extreme, WITHOUT any bar close **≥5p beyond the outer anchor level** (close-beyond invalidates).

**Tracked levels**: R1 / R2 / R3 / S1 / S2 / S3 / P (classic-floor pivots from prior day D1) + PDH / PDL (prior D1 high/low) + BB(20,2) upper / lower + Round 00 (nearest ×100p, within 55p of bar open) + Round 50 (nearest ×50p offset, within 30p of bar open) + Session H / L for Asia / London / NY / Late (running, established ≥15 min prior to the touch bar). All levels are **known-at-time only** — pivots from prior close, session H/L as of the touch bar.

**Side rule**: R-family / PDH / SessionH / BB_U → SELL touches; S-family / PDL / SessionL / BB_L → BUY touches; P and Round 00/50 → approach side determined by `bar.open vs level`.

**Cluster rule**: touches on the **same side** whose bar-indices are ≤12 bars apart (60 min) collapse into ONE episode. Sweep through S1+PDL is ONE bounce, not two. **Opposite-side episodes are always distinct.** The episode's `extreme_price` is the deepest bar high (SELL) or lowest bar low (BUY) across all bars in the touch chain; the `outer_anchor` is the highest level (SELL) or lowest level (BUY) touched in the episode; MFE is measured from `extreme_price` in the ≥25p direction; close-beyond invalidates against `outer_anchor + 5p` (SELL) or `outer_anchor − 5p` (BUY).

**Corpus scope**: 681 full-session weekday days in the scan (any bar in 07:00 – 20:55 UTC). The audit's `day_structure_ext` count of **674** applies a stricter test (both London 07:00–11:59 AND NY 13:00–20:55 sub-windows non-empty); 7 days in this scan don't meet the stricter filter but have some intraday data. All rates below are on my 681 denominator; year splits and per-month counts translate cleanly.

**Caveats printed on every table**:
- **Bid vs mid**: 2024/2025 uses `data/candles_ext` (HistData rebuild, **bid**); 2026-01→04-06 uses `data/ohlc` (mid + spread cols, third-party); 2026-03-23→08-14 uses `data/candles` (IG mid). Systematic offset ~−0.5p bid vs mid per the provenance audit. **Day-level bounce counts are robust to this offset** (25p threshold vs 0.5p offset). Anchor-price precision is not.
- **DST (session tags)**: HistData +5h fixed-EST shift is empirically calibrated against a March 2026 week only; if the source ever observed DST, off-DST months would carry a ±1h session-tag error. Session H/L identity (Table 7) inherits this caveat. The touch/turn 25p logic does not depend on session labels.
- **2026-04-07..10** excluded (`data/ohlc` corrupt flat @ 13400/13500) per the audited detector's `BAD_OHLC_DATES`.

---

## Table 1 — Distribution of qualifying bounces per day

| bounces/day | n days | % of 681 |
|:-----------:|:------:|:-------------:|
| 0 | 16 | 2.35% |
| 1 | 70 | 10.28% |
| 2 | 147 | 21.59% |
| 3 | 166 | 24.38% |
| 4 | 126 | 18.50% |
| 5 | 94 | 13.80% |
| 6 | 39 | 5.73% |
| 7 | 9 | 1.32% |
| 8 | 8 | 1.17% |
| 9 | 2 | 0.29% |
| 10 | 4 | 0.59% |
| **≥2 (THE cohort)** | **595** | **87.37%** |
| ≥3 | 448 | 65.79% |

**Falsification note (per §43)**: the ≥2 cohort is **not a rare cohort — it is the modal case**. 87% of weekday days meet the definition. The operator's ~10-per-month hypothesis (§Table 8) is falsified — actual mean is 18.6/month. If the mental model was 'special days,' the level set + threshold that operationalise 'bounce' need tightening.

---

## Table 2 — The ≥2 cohort (full list, 595 rows)

Columns: date · wkday · day-range / net · session tags · bounce list (`hh:mm→hh:mm side [anchors] mfe=Np`). SELL = S-first-char; BUY = B-first-char. `[anchors]` lists all levels folded into the episode.

**Sample (first 30 rows)**:

| date | wd | day range/net | rel | bounces |
|------|:--:|:-------------:|:---:|---------|
| 2024-01-02 | Tue | 149p / -113p | none | 00:00→03:00 B [BB_L,P,PDL,S1,S2,SESS_L_ASIA] mfe=31p | 04:00→08:10 S [BB_U,P,PDH,R1,R2,R3,R50,SESS_H_ASIA,SESS_H_LON] mfe=92p | 06:55→16:40 B [BB_L,P,PDL,R00,R50,S1,S2,S3,SESS_L_LON,SESS_L_NY] mfe=26p | 12:40→12:40 S [R50,SESS_H_NY] mfe=38p |
| 2024-01-03 | Wed | 60p / +20p | none | 00:00→08:15 S [BB_U,R50,SESS_H_ASIA,SESS_H_LON] mfe=32p | 07:15→07:20 B [BB_L] mfe=28p | 09:10→14:10 B [BB_L,SESS_L_LON,SESS_L_NY] mfe=39p | 15:45→15:50 B [BB_L,SESS_L_NY] mfe=39p | 17:55→19:05 B [BB_L,P,R50,SESS_L_LATE] mfe=46p |
| 2024-01-04 | Thu | 65p / +5p | DAY_BEFORE | 04:50→05:40 B [BB_L] mfe=34p | 06:15→10:25 S [BB_U,PDH,R00,R1,R2,SESS_H_ASIA,SESS_H_LATE,SESS_H_LON,SESS_H_NY] mfe=47p | 08:35→08:35 B [BB_L,R00] mfe=47p | 11:00→14:20 B [BB_L,R00,SESS_L_LATE,SESS_L_NY] mfe=46p |
| 2024-01-05 | Fri | 160p / +50p | ON/NFP | 07:10→08:15 S [BB_U,P,SESS_H_LON] mfe=39p | 08:30→13:30 B [BB_L,P,PDL,R00,R50,S1,S2,SESS_L_LON,SESS_L_NY] mfe=160p | 11:35→15:40 S [BB_U,P,PDH,R00,R1,R2,R50,SESS_H_LATE,SESS_H_NY] mfe=61p |
| 2024-01-08 | Mon | 94p / +37p | none | 00:00→01:20 S [BB_U,P,PDH,R00,R1,R2,SESS_H_ASIA] mfe=32p | 02:00→09:35 B [BB_L,P,PDL,R00,S1,S2,S3,SESS_L_ASIA,SESS_L_LON] mfe=47p | 09:55→17:00 S [BB_U,P,PDH,R00,R1,R2,R3,R50,SESS_H_LATE,SESS_H_LON,SESS_H_NY] mfe=27p |
| 2024-01-09 | Tue | 62p / -31p | none | 00:00→02:20 S [BB_U,PDH,R50,SESS_H_ASIA] mfe=26p | 07:05→07:35 S [BB_U,R50,SESS_H_LON] mfe=29p | 08:05→16:05 B [BB_L,P,R00,S1,SESS_L_LON,SESS_L_NY] mfe=29p | 09:15→09:35 S [BB_U,P] mfe=32p | 12:20→13:15 S [BB_U,P] mfe=46p | 18:00→18:05 S [BB_U,R00,SESS_H_LATE] mfe=26p |
| 2024-01-10 | Wed | 57p / +47p | DAY_BEFORE | 00:35→06:50 B [BB_L,PDL,R00,SESS_L_ASIA,SESS_L_LON] mfe=43p | 09:15→14:45 B [BB_L,P,SESS_L_NY] mfe=28p |
| 2024-01-11 | Thu | 95p / -10p | ON/CPI_US | 00:00→13:30 S [BB_U,P,PDH,R00,R1,R2,R50,SESS_H_ASIA,SESS_H_LON,SESS_H_NY] mfe=95p | 03:45→10:05 B [BB_L,R50,SESS_L_LON] mfe=37p | 12:55→15:10 B [BB_L,P,R00,R50,S1,SESS_L_NY] mfe=46p |
| 2024-01-12 | Fri | 66p / -28p | DAY_AFTER | 02:55→08:00 B [BB_L,P,R50,SESS_L_ASIA,SESS_L_LON] mfe=26p | 05:05→06:55 S [BB_U] mfe=28p | 08:20→08:25 S [BB_U,SESS_H_LON] mfe=39p | 09:30→12:10 B [BB_L,P,R50,S1,SESS_L_LON] mfe=66p | 13:10→15:05 S [BB_U,P,PDH,R50,SESS_H_NY] mfe=53p |
| 2024-01-15 | Mon | 46p / -29p | HOL/none | 00:00→00:15 B [BB_L,P,PDL,R50,S1] mfe=36p | 04:00→14:50 B [BB_L,P,PDL,R50,S1,S2,S3,SESS_L_LATE,SESS_L_LON,SESS_L_NY] mfe=26p | 11:00→12:15 S [BB_U,P] mfe=26p |
| 2024-01-16 | Tue | 67p / -53p | DAY_BEFORE | 00:15→00:15 S [R00,SESS_H_ASIA] mfe=35p | 04:40→06:50 S [BB_U,SESS_H_LON] mfe=51p | 11:35→16:20 S [BB_U,R50,SESS_H_NY] mfe=60p |
| 2024-01-17 | Wed | 88p / +77p | ON/CPI_UK | 00:00→02:05 S [BB_U,SESS_H_ASIA] mfe=27p | 00:10→06:30 B [BB_L,P,PDL,R00,R50,S1,SESS_L_ASIA] mfe=80p | 06:30→10:15 S [BB_U,P,R00,R1,R50,SESS_H_LON] mfe=31p | 11:50→11:55 S [BB_U,R1,SESS_H_LON] mfe=55p | 12:35→15:00 B [BB_L,P,R50,SESS_L_NY] mfe=44p |
| 2024-01-18 | Thu | 54p / +1p | DAY_AFTER | 02:35→05:30 B [BB_L] mfe=27p | 05:20→06:55 S [BB_U,PDH,R00,SESS_H_ASIA,SESS_H_LON] mfe=31p | 11:25→11:30 S [BB_U,PDH] mfe=48p | 12:20→14:00 B [BB_L,P,R50,SESS_L_LON,SESS_L_NY] mfe=44p | 17:10→17:10 B [BB_L,SESS_L_LATE] mfe=29p |
| 2024-01-19 | Fri | 38p / +1p | none | 04:00→08:30 B [BB_L,P,R00,S1,SESS_L_ASIA,SESS_L_LON] mfe=25p | 05:55→06:15 S [P,R00] mfe=35p | 12:00→15:10 B [BB_L,P,R00,S1,SESS_L_LATE,SESS_L_NY] mfe=31p |
| 2024-01-22 | Mon | 46p / -6p | none | 00:00→17:20 S [BB_U,P,PDH,R00,R1,R2,SESS_H_ASIA,SESS_H_LATE,SESS_H_LON,SESS_H_NY] mfe=35p | 06:35→08:50 B [BB_L,P,R00,SESS_L_LON] mfe=28p |
| 2024-01-23 | Tue | 98p / -60p | none | 00:00→07:05 S [BB_U,P,PDH,R1,SESS_H_ASIA,SESS_H_LON] mfe=27p | 07:15→17:40 B [BB_L,P,PDL,R00,R50,S1,S2,SESS_L_LON,SESS_L_NY] mfe=38p | 11:25→13:20 S [BB_U,P,R00,SESS_H_NY] mfe=65p |
| 2024-01-24 | Wed | 75p / +13p | none | 03:10→14:30 S [BB_U,P,PDH,R00,R1,R50,SESS_H_ASIA,SESS_H_LON,SESS_H_NY] mfe=41p | 10:25→12:30 B [BB_L,R50] mfe=47p |
| 2024-01-25 | Thu | 61p / -18p | none | 03:30→05:05 B [BB_L,P,SESS_L_LON] mfe=30p | 06:00→10:35 S [BB_U,P,R00,SESS_H_ASIA,SESS_H_LATE,SESS_H_LON,SESS_H_NY] mfe=45p |
| 2024-01-26 | Fri | 83p / +5p | none | 00:00→07:50 B [BB_L,P,PDL,R00,S1,SESS_L_ASIA,SESS_L_LON] mfe=59p | 08:30→13:45 S [BB_U,P,PDH,R00,R1,R50,SESS_H_LON,SESS_H_NY] mfe=45p | 09:15→09:25 B [P,R00] mfe=44p |
| 2024-01-30 | Tue | 59p / +3p | DAY_BEFORE | 00:20→15:15 B [BB_L,P,PDL,R00,R50,S1,S2,SESS_L_ASIA,SESS_L_LON,SESS_L_NY] mfe=49p | 13:40→14:10 S [BB_U,R50,SESS_H_NY] mfe=48p |
| 2024-01-31 | Wed | 93p / +5p | ON/FOMC | 00:00→00:15 S [BB_U,R00,SESS_H_ASIA] mfe=28p | 03:45→08:45 S [BB_U,P,R00,SESS_H_LON] mfe=30p | 05:15→07:45 B [BB_L,P,SESS_L_ASIA,SESS_L_LON] mfe=31p | 11:10→15:00 S [BB_U,P,PDH,R00,R1,R50,SESS_H_LATE,SESS_H_NY] mfe=38p | 12:15→12:35 B [BB_L,P,R00] mfe=72p | 16:05→20:30 B [BB_L,P,R00,SESS_L_LATE] mfe=31p |
| 2024-02-01 | Thu | 130p / +84p | ON/BoE | 00:00→11:25 B [BB_L,P,PDL,R50,S1,SESS_L_ASIA,SESS_L_LON] mfe=60p | 02:05→02:40 S [BB_U,P,R00,SESS_H_ASIA] mfe=26p | 13:25→15:00 B [BB_L,P,PDL,R50,S1,SESS_L_NY] mfe=100p | 18:20→18:20 B [BB_L,R50,SESS_L_LATE] mfe=28p |
| 2024-02-05 | Mon | 111p / -74p | none | 00:00→00:05 S [P] mfe=28p | 00:00→15:55 B [BB_L,P,PDL,R00,R50,S1,S2,S3,SESS_L_ASIA,SESS_L_LON,SESS_L_NY] mfe=25p | 03:40→08:10 S [BB_U,P,SESS_H_LON] mfe=48p | 13:15→14:30 S [BB_U,R50,SESS_H_NY] mfe=43p |
| 2024-02-06 | Tue | 67p / +48p | none | 00:00→07:10 S [BB_U,P,R50,SESS_H_ASIA,SESS_H_LON] mfe=25p | 02:55→11:00 B [BB_L,P,R50,SESS_L_LON,SESS_L_NY] mfe=36p | 16:15→16:15 B [BB_L] mfe=27p |
| 2024-02-12 | Mon | 49p / -2p | DAY_BEFORE | 00:00→07:55 S [BB_U,P,PDH,R1,R2,R50,SESS_H_ASIA,SESS_H_LON] mfe=38p | 00:25→13:55 B [BB_L,P,PDL,S1,S2,S3,SESS_L_ASIA,SESS_L_LATE,SESS_L_LON,SESS_L_NY] mfe=27p |
| 2024-02-13 | Tue | 115p / -32p | ON/CPI_US | 00:00→04:00 B [BB_L,PDL,SESS_L_ASIA] mfe=32p | 03:40→13:30 S [BB_U,P,PDH,R00,R1,R2,R50,SESS_H_LON,SESS_H_NY] mfe=112p | 07:35→08:45 B [BB_L,R50] mfe=40p |
| 2024-02-14 | Wed | 71p / -40p | ON/CPI_UK | 00:15→06:50 S [BB_U,R00,SESS_H_ASIA] mfe=75p | 03:15→10:30 B [BB_L,PDL,R00,R50,S1,SESS_L_LATE,SESS_L_LON,SESS_L_NY] mfe=32p | 10:55→13:35 S [BB_U,R50,SESS_H_NY] mfe=28p |
| 2024-02-15 | Thu | 59p / +29p | DAY_AFTER | 03:40→13:25 B [BB_L,P,R50,SESS_L_ASIA,SESS_L_LON,SESS_L_NY] mfe=55p | 16:25→16:55 B [BB_L,P] mfe=27p |
| 2024-02-16 | Fri | 74p / +17p | none | 00:00→07:00 S [BB_U,P,PDH,R00,SESS_H_NY] mfe=32p | 02:45→04:20 B [BB_L,P,SESS_L_ASIA] mfe=29p | 08:05→09:00 B [BB_L,P,SESS_L_LON] mfe=26p | 12:35→13:35 B [BB_L,P,R00,R50,S1,SESS_L_LATE,SESS_L_NY] mfe=44p | 15:05→19:15 S [BB_U,P,PDH,R00,R1,SESS_H_LATE,SESS_H_NY] mfe=27p |
| 2024-02-21 | Wed | 39p / +10p | none | 11:20→11:30 B [BB_L] mfe=26p | 12:15→14:10 S [BB_U,P,SESS_H_NY] mfe=29p | 13:05→16:05 B [BB_L,P,SESS_L_NY] mfe=37p |

**Full list of all 595 dates appended at the end of this document** (Appendix A).

---

## Table 3 — Day character: ≥2 cohort vs rest

| metric | ≥2 cohort (n=595) | rest (n=86) |
|--------|:----:|:---:|
| range med (p25–p75) | 72.4 (56.6–93.7) | 46.6 (37.0–65.2) |
| range mean / min / max | 79.4 / 22.3 / 243.7 | 52.3 / 5.3 / 158.5 |
| net med (p25–p75) | 31.6 (14.4–57.2) | 21.1 (10.1–31.1) |
| net mean / min / max | 39.5 / 0.1 / 224.7 | 25.9 / 0.1 / 125.1 |
| eff med (p25–p75) | 0.5 (0.2–0.7) | 0.5 (0.2–0.7) |
| eff mean / min / max | 0.5 / 0.0 / 1.0 | 0.5 / 0.0 / 1.0 |

**Read**: ≥2-cohort days have a **~55% wider median range** (72p vs 47p) and larger |net| (32p vs 21p). Efficiency medians are identical (0.5) — the ≥2 cohort is **not rotation-heavy** on average; it splits between rotation and trend at the same ratio as everything else. Rotation vs trend does NOT separate the cohorts.

### 3b. Weekday distribution

| wd | ≥2 cohort | rest |
|----|:---------:|:----:|
| Mon | 107 (18.0%) | 28 (32.6%) |
| Tue | 124 (20.8%) | 13 (15.1%) |
| Wed | 121 (20.3%) | 15 (17.4%) |
| Thu | 123 (20.7%) | 14 (16.3%) |
| Fri | 120 (20.2%) | 16 (18.6%) |

**Read**: **Mondays are massively over-represented in the rest cohort** (33% of rest vs 18% of ≥2). If a day is 'too quiet for ≥2 bounces,' it's disproportionately a Monday. Tue-Fri are ~20% each in both cohorts.

---

## Table 4 — Day-of-month histogram (≥2 cohort)

| DOM | count | | DOM | count | | DOM | count |
|:---:|:-----:|-|:---:|:-----:|-|:---:|:-----:|
| 1 | 18 | | 11 | 20 | | 21 | 18 |
| 2 | 19 | | 12 | 24 | | 22 | 20 |
| 3 | 22 | | 13 | 19 | | 23 | 23 |
| 4 | 19 | | 14 | 16 | | 24 | 21 |
| 5 | 23 | | 15 | 16 | | 25 | 19 |
| 6 | 19 | | 16 | 19 | | 26 | 19 |
| 7 | 20 | | 17 | 19 | | 27 | 20 |
| 8 | 20 | | 18 | 17 | | 28 | 19 |
| 9 | 19 | | 19 | 19 | | 29 | 16 |
| 10 | 22 | | 20 | 19 | | 30 | 20 |
| 31 | 11 | | | | | | |

| bucket | n | % |
|--------|---|---|
| 1–10 | 201 | 33.78% |
| 11–20 | 188 | 31.60% |
| 21–31 | 206 | 34.62% |

**Read**: **No monthly clustering.** Range across DOM 1-30 is 16-24 hits; day-31 is 11 (only 7 months have a 31st). Bucket shares are 30 / 28 / 35 % — the ≥2 phenomenon is uniformly distributed through the month.

---

## Table 5 — News relation

Big-news set: NFP ∪ US CPI ∪ FOMC decision-day ∪ BoE decision-day ∪ UK CPI (schedules in Appendix B). Holidays: US NYSE ∪ UK bank (Appendix C).

| relation | ≥2 cohort (n=595) | rest (n=86) |
|----------|:----:|:---:|
| ON | 117 (19.7%) | 9 (10.5%) |
| DAY_BEFORE | 95 (16.0%) | 9 (10.5%) |
| DAY_AFTER | 64 (10.8%) | 7 (8.1%) |
| none | 319 (53.6%) | 61 (70.9%) |

**By news category (share of that category's dates landing in the ≥2 cohort)**:

| category | in ≥2 / total-in-scope | rate |
|----------|:----:|:---:|
| NFP | 31/32 | 96.9% |
| CPI_US | 31/32 | 96.9% |
| FOMC | 21/21 | 100.0% |
| BoE | 19/21 | 90.5% |
| CPI_UK | 26/31 | 83.9% |

**Read**: **News days concentrate in the ≥2 cohort at near-ceiling rates.** 100% of FOMC decision days (21/21), 97% of NFPs (31/32), 97% of US CPIs (31/32), 90% of BoE, 84% of UK CPIs — all sit in the ≥2 cohort. This is what would be expected from ANY definition of 'active day.'

**Holidays**: 20 ≥2 days coincide with US or UK holidays; 16 rest days. **The rest cohort is enriched in holidays** (16/86 = 18.6% vs 3.4%). Rest-cohort holiday days: `2024-02-19, 2024-03-29, 2024-05-06, 2024-05-27, 2024-06-19, 2024-07-04, 2024-09-02, 2024-11-28, 2024-12-25, 2025-02-17, 2025-04-18, 2025-05-26, 2025-09-01, 2026-01-01, 2026-02-16, 2026-05-25`.

---

## Table 6 — Year split (stability check)

| year | n days | 0 | 1 | 2 | ≥3 | ≥2 rate |
|:----:|:------:|:-:|:-:|:-:|:--:|:-------:|
| 2024 | 261 | 8 | 41 | 72 | 140 | 81.2% |
| 2025 | 260 | 1 | 14 | 45 | 200 | 94.2% |
| 2026 | 160 | 7 | 15 | 30 | 108 | 86.2% |

**Read**: **≥2 rate is stable across years** at 81 / 94 / 86 %. 2025 was the peak (94.2%) — matches the audit's finding that 2025 had the widest median day range (75.9p) and highest trend-day share.

---

## Table 7 — Session timing (**DST caveat: HistData +5h fixed-EST shift; off-DST months carry ±1h session-tag uncertainty**)

Bounces in the ≥2 cohort, tagged by `session_of(first_touch_ts)`:

| session | UTC window | n bounces |
|---------|:----------:|:---------:|
| ASIA | 00:00-06:59 | 1069 |
| LON | 07:00-12:59 | 686 |
| NY | 13:00-17:59 | 340 |
| LATE | 18:00-23:59 | 90 |

**Days with specifically one-London-plus-one-NY**: **211** (35.5% of the ≥2 cohort).
- days with LON but no NY bounces: 245 (41.2%)
- days with NY but no LON bounces: 73 (12.3%)
- days with neither LON nor NY (only ASIA/LATE): 66 (11.1%)

**Read**: The ASIA count (1069) reflects that BB / Round 00/50 / Session H/L levels get tested overnight before London opens, and 25p reversals against those levels happen — but this is a low-liquidity regime the operator likely does not care about. If ASIA and LATE are excluded, London (686) leads NY (340) 2:1 by bounce count.

---

## Table 8 — Monthly frequency of ≥2 days

**Mean: 18.59 ≥2 days per calendar month.** Median 19, range 6 → 23.

**Operator hypothesis was ~10/month — falsified.** Actual mean is nearly 2× that. The floor (6) is 2026-08 partial-month (only 10 weekdays in scope through 08-14).

| year-month | ≥2 days | of n weekdays |
|:----------:|:-------:|:-------------:|
| 2024-01 | 21 | 22 |
| 2024-02 | 15 | 21 |
| 2024-03 | 14 | 21 |
| 2024-04 | 20 | 22 |
| 2024-05 | 14 | 23 |
| 2024-06 | 16 | 20 |
| 2024-07 | 16 | 23 |
| 2024-08 | 19 | 22 |
| 2024-09 | 18 | 21 |
| 2024-10 | 20 | 23 |
| 2024-11 | 18 | 21 |
| 2024-12 | 21 | 22 |
| 2025-01 | 22 | 22 |
| 2025-02 | 19 | 20 |
| 2025-03 | 19 | 21 |
| 2025-04 | 21 | 22 |
| 2025-05 | 21 | 22 |
| 2025-06 | 21 | 21 |
| 2025-07 | 23 | 23 |
| 2025-08 | 14 | 21 |
| 2025-09 | 21 | 22 |
| 2025-10 | 23 | 23 |
| 2025-11 | 20 | 20 |
| 2025-12 | 21 | 23 |
| 2026-01 | 19 | 22 |
| 2026-02 | 18 | 20 |
| 2026-03 | 22 | 22 |
| 2026-04 | 20 | 22 |
| 2026-05 | 16 | 20 |
| 2026-06 | 19 | 22 |
| 2026-07 | 18 | 22 |
| 2026-08 | 6 | 10 |

---

## Falsification framing (§43)

- **The ≥2 cohort is 87% of weekday days.** It is the modal case, not a special-day cohort. **The operator's implied 'two-bounce day' concept — as counted here — does not carve out an interesting subset.**
- **Monthly rate is 18.6 (mean), not ~10** as the operator hypothesised. Wrong by ~2×.
- **No monthly-DOM clustering.** Uniform across 1-30.
- **News days DO NOT distinguish the ≥2 cohort** in an informative way — they land in ≥2 at 90-100% rates, but so does everything else at 87%.
- **Weekday IS a discriminator**: Mondays are 33% of the rest cohort. Holidays account for 19% of rest.
- **What would tighten the definition to something closer to the operator's mental model?** Candidate levers: raise the reversal threshold (35p or 40p); require the outer anchor to be an OUTER pivot (R/S) not a round-number or BB; require both bounces to be within the London or NY session (excluding ASIA/LATE); require MFE window shorter than 36 bars. **This report does not do that re-scoping — it is a counting exercise against the definition as given.**

---

## Appendix A — Full ≥2 date list (595 rows)

`date | wd | day range/net | rel | bounce_1 || bounce_2 || bounce_3 …`

- `2024-01-02` Tue  range 149p net -113p  [none]  00:00→03:00 B [BB_L,P,PDL,S1,S2,SESS_L_ASIA] mfe=31p || 04:00→08:10 S [BB_U,P,PDH,R1,R2,R3,R50,SESS_H_ASIA,SESS_H_LON] mfe=92p || 06:55→16:40 B [BB_L,P,PDL,R00,R50,S1,S2,S3,SESS_L_LON,SESS_L_NY] mfe=26p || 12:40→12:40 S [R50,SESS_H_NY] mfe=38p
- `2024-01-03` Wed  range 60p net +20p  [none]  00:00→08:15 S [BB_U,R50,SESS_H_ASIA,SESS_H_LON] mfe=32p || 07:15→07:20 B [BB_L] mfe=28p || 09:10→14:10 B [BB_L,SESS_L_LON,SESS_L_NY] mfe=39p || 15:45→15:50 B [BB_L,SESS_L_NY] mfe=39p || 17:55→19:05 B [BB_L,P,R50,SESS_L_LATE] mfe=46p
- `2024-01-04` Thu  range 65p net +5p  [DAY_BEFORE]  04:50→05:40 B [BB_L] mfe=34p || 06:15→10:25 S [BB_U,PDH,R00,R1,R2,SESS_H_ASIA,SESS_H_LATE,SESS_H_LON,SESS_H_NY] mfe=47p || 08:35→08:35 B [BB_L,R00] mfe=47p || 11:00→14:20 B [BB_L,R00,SESS_L_LATE,SESS_L_NY] mfe=46p
- `2024-01-05` Fri  range 160p net +50p  [ON/NFP]  07:10→08:15 S [BB_U,P,SESS_H_LON] mfe=39p || 08:30→13:30 B [BB_L,P,PDL,R00,R50,S1,S2,SESS_L_LON,SESS_L_NY] mfe=160p || 11:35→15:40 S [BB_U,P,PDH,R00,R1,R2,R50,SESS_H_LATE,SESS_H_NY] mfe=61p
- `2024-01-08` Mon  range 94p net +37p  [none]  00:00→01:20 S [BB_U,P,PDH,R00,R1,R2,SESS_H_ASIA] mfe=32p || 02:00→09:35 B [BB_L,P,PDL,R00,S1,S2,S3,SESS_L_ASIA,SESS_L_LON] mfe=47p || 09:55→17:00 S [BB_U,P,PDH,R00,R1,R2,R3,R50,SESS_H_LATE,SESS_H_LON,SESS_H_NY] mfe=27p
- `2024-01-09` Tue  range 62p net -31p  [none]  00:00→02:20 S [BB_U,PDH,R50,SESS_H_ASIA] mfe=26p || 07:05→07:35 S [BB_U,R50,SESS_H_LON] mfe=29p || 08:05→16:05 B [BB_L,P,R00,S1,SESS_L_LON,SESS_L_NY] mfe=29p || 09:15→09:35 S [BB_U,P] mfe=32p || 12:20→13:15 S [BB_U,P] mfe=46p || 18:00→18:05 S [BB_U,R00,SESS_H_LATE] mfe=26p
- `2024-01-10` Wed  range 57p net +47p  [DAY_BEFORE]  00:35→06:50 B [BB_L,PDL,R00,SESS_L_ASIA,SESS_L_LON] mfe=43p || 09:15→14:45 B [BB_L,P,SESS_L_NY] mfe=28p
- `2024-01-11` Thu  range 95p net -10p  [ON/CPI_US]  00:00→13:30 S [BB_U,P,PDH,R00,R1,R2,R50,SESS_H_ASIA,SESS_H_LON,SESS_H_NY] mfe=95p || 03:45→10:05 B [BB_L,R50,SESS_L_LON] mfe=37p || 12:55→15:10 B [BB_L,P,R00,R50,S1,SESS_L_NY] mfe=46p
- `2024-01-12` Fri  range 66p net -28p  [DAY_AFTER]  02:55→08:00 B [BB_L,P,R50,SESS_L_ASIA,SESS_L_LON] mfe=26p || 05:05→06:55 S [BB_U] mfe=28p || 08:20→08:25 S [BB_U,SESS_H_LON] mfe=39p || 09:30→12:10 B [BB_L,P,R50,S1,SESS_L_LON] mfe=66p || 13:10→15:05 S [BB_U,P,PDH,R50,SESS_H_NY] mfe=53p
- `2024-01-15` Mon  range 46p net -29p  [HOL/none]  00:00→00:15 B [BB_L,P,PDL,R50,S1] mfe=36p || 04:00→14:50 B [BB_L,P,PDL,R50,S1,S2,S3,SESS_L_LATE,SESS_L_LON,SESS_L_NY] mfe=26p || 11:00→12:15 S [BB_U,P] mfe=26p
- `2024-01-16` Tue  range 67p net -53p  [DAY_BEFORE]  00:15→00:15 S [R00,SESS_H_ASIA] mfe=35p || 04:40→06:50 S [BB_U,SESS_H_LON] mfe=51p || 11:35→16:20 S [BB_U,R50,SESS_H_NY] mfe=60p
- `2024-01-17` Wed  range 88p net +77p  [ON/CPI_UK]  00:00→02:05 S [BB_U,SESS_H_ASIA] mfe=27p || 00:10→06:30 B [BB_L,P,PDL,R00,R50,S1,SESS_L_ASIA] mfe=80p || 06:30→10:15 S [BB_U,P,R00,R1,R50,SESS_H_LON] mfe=31p || 11:50→11:55 S [BB_U,R1,SESS_H_LON] mfe=55p || 12:35→15:00 B [BB_L,P,R50,SESS_L_NY] mfe=44p
- `2024-01-18` Thu  range 54p net +1p  [DAY_AFTER]  02:35→05:30 B [BB_L] mfe=27p || 05:20→06:55 S [BB_U,PDH,R00,SESS_H_ASIA,SESS_H_LON] mfe=31p || 11:25→11:30 S [BB_U,PDH] mfe=48p || 12:20→14:00 B [BB_L,P,R50,SESS_L_LON,SESS_L_NY] mfe=44p || 17:10→17:10 B [BB_L,SESS_L_LATE] mfe=29p
- `2024-01-19` Fri  range 38p net +1p  [none]  04:00→08:30 B [BB_L,P,R00,S1,SESS_L_ASIA,SESS_L_LON] mfe=25p || 05:55→06:15 S [P,R00] mfe=35p || 12:00→15:10 B [BB_L,P,R00,S1,SESS_L_LATE,SESS_L_NY] mfe=31p
- `2024-01-22` Mon  range 46p net -6p  [none]  00:00→17:20 S [BB_U,P,PDH,R00,R1,R2,SESS_H_ASIA,SESS_H_LATE,SESS_H_LON,SESS_H_NY] mfe=35p || 06:35→08:50 B [BB_L,P,R00,SESS_L_LON] mfe=28p
- `2024-01-23` Tue  range 98p net -60p  [none]  00:00→07:05 S [BB_U,P,PDH,R1,SESS_H_ASIA,SESS_H_LON] mfe=27p || 07:15→17:40 B [BB_L,P,PDL,R00,R50,S1,S2,SESS_L_LON,SESS_L_NY] mfe=38p || 11:25→13:20 S [BB_U,P,R00,SESS_H_NY] mfe=65p
- `2024-01-24` Wed  range 75p net +13p  [none]  03:10→14:30 S [BB_U,P,PDH,R00,R1,R50,SESS_H_ASIA,SESS_H_LON,SESS_H_NY] mfe=41p || 10:25→12:30 B [BB_L,R50] mfe=47p
- `2024-01-25` Thu  range 61p net -18p  [none]  03:30→05:05 B [BB_L,P,SESS_L_LON] mfe=30p || 06:00→10:35 S [BB_U,P,R00,SESS_H_ASIA,SESS_H_LATE,SESS_H_LON,SESS_H_NY] mfe=45p
- `2024-01-26` Fri  range 83p net +5p  [none]  00:00→07:50 B [BB_L,P,PDL,R00,S1,SESS_L_ASIA,SESS_L_LON] mfe=59p || 08:30→13:45 S [BB_U,P,PDH,R00,R1,R50,SESS_H_LON,SESS_H_NY] mfe=45p || 09:15→09:25 B [P,R00] mfe=44p
- `2024-01-30` Tue  range 59p net +3p  [DAY_BEFORE]  00:20→15:15 B [BB_L,P,PDL,R00,R50,S1,S2,SESS_L_ASIA,SESS_L_LON,SESS_L_NY] mfe=49p || 13:40→14:10 S [BB_U,R50,SESS_H_NY] mfe=48p
- `2024-01-31` Wed  range 93p net +5p  [ON/FOMC]  00:00→00:15 S [BB_U,R00,SESS_H_ASIA] mfe=28p || 03:45→08:45 S [BB_U,P,R00,SESS_H_LON] mfe=30p || 05:15→07:45 B [BB_L,P,SESS_L_ASIA,SESS_L_LON] mfe=31p || 11:10→15:00 S [BB_U,P,PDH,R00,R1,R50,SESS_H_LATE,SESS_H_NY] mfe=38p || 12:15→12:35 B [BB_L,P,R00] mfe=72p || 16:05→20:30 B [BB_L,P,R00,SESS_L_LATE] mfe=31p
- `2024-02-01` Thu  range 130p net +84p  [ON/BoE]  00:00→11:25 B [BB_L,P,PDL,R50,S1,SESS_L_ASIA,SESS_L_LON] mfe=60p || 02:05→02:40 S [BB_U,P,R00,SESS_H_ASIA] mfe=26p || 13:25→15:00 B [BB_L,P,PDL,R50,S1,SESS_L_NY] mfe=100p || 18:20→18:20 B [BB_L,R50,SESS_L_LATE] mfe=28p
- `2024-02-05` Mon  range 111p net -74p  [none]  00:00→00:05 S [P] mfe=28p || 00:00→15:55 B [BB_L,P,PDL,R00,R50,S1,S2,S3,SESS_L_ASIA,SESS_L_LON,SESS_L_NY] mfe=25p || 03:40→08:10 S [BB_U,P,SESS_H_LON] mfe=48p || 13:15→14:30 S [BB_U,R50,SESS_H_NY] mfe=43p
- `2024-02-06` Tue  range 67p net +48p  [none]  00:00→07:10 S [BB_U,P,R50,SESS_H_ASIA,SESS_H_LON] mfe=25p || 02:55→11:00 B [BB_L,P,R50,SESS_L_LON,SESS_L_NY] mfe=36p || 16:15→16:15 B [BB_L] mfe=27p
- `2024-02-12` Mon  range 49p net -2p  [DAY_BEFORE]  00:00→07:55 S [BB_U,P,PDH,R1,R2,R50,SESS_H_ASIA,SESS_H_LON] mfe=38p || 00:25→13:55 B [BB_L,P,PDL,S1,S2,S3,SESS_L_ASIA,SESS_L_LATE,SESS_L_LON,SESS_L_NY] mfe=27p
- `2024-02-13` Tue  range 115p net -32p  [ON/CPI_US]  00:00→04:00 B [BB_L,PDL,SESS_L_ASIA] mfe=32p || 03:40→13:30 S [BB_U,P,PDH,R00,R1,R2,R50,SESS_H_LON,SESS_H_NY] mfe=112p || 07:35→08:45 B [BB_L,R50] mfe=40p
- `2024-02-14` Wed  range 71p net -40p  [ON/CPI_UK]  00:15→06:50 S [BB_U,R00,SESS_H_ASIA] mfe=75p || 03:15→10:30 B [BB_L,PDL,R00,R50,S1,SESS_L_LATE,SESS_L_LON,SESS_L_NY] mfe=32p || 10:55→13:35 S [BB_U,R50,SESS_H_NY] mfe=28p
- `2024-02-15` Thu  range 59p net +29p  [DAY_AFTER]  03:40→13:25 B [BB_L,P,R50,SESS_L_ASIA,SESS_L_LON,SESS_L_NY] mfe=55p || 16:25→16:55 B [BB_L,P] mfe=27p
- `2024-02-16` Fri  range 74p net +17p  [none]  00:00→07:00 S [BB_U,P,PDH,R00,SESS_H_NY] mfe=32p || 02:45→04:20 B [BB_L,P,SESS_L_ASIA] mfe=29p || 08:05→09:00 B [BB_L,P,SESS_L_LON] mfe=26p || 12:35→13:35 B [BB_L,P,R00,R50,S1,SESS_L_LATE,SESS_L_NY] mfe=44p || 15:05→19:15 S [BB_U,P,PDH,R00,R1,SESS_H_LATE,SESS_H_NY] mfe=27p
- `2024-02-21` Wed  range 39p net +10p  [none]  11:20→11:30 B [BB_L] mfe=26p || 12:15→14:10 S [BB_U,P,SESS_H_NY] mfe=29p || 13:05→16:05 B [BB_L,P,SESS_L_NY] mfe=37p
- `2024-02-22` Thu  range 98p net +13p  [none]  00:00→08:25 S [BB_U,P,PDH,R00,R1,R2,R3,R50,SESS_H_ASIA,SESS_H_LATE] mfe=42p || 11:05→14:40 B [BB_L,P,R50,S1,SESS_L_NY] mfe=47p
- `2024-02-23` Fri  range 52p net +6p  [none]  00:00→12:55 S [BB_U,P,R00,R50,SESS_H_ASIA,SESS_H_LON,SESS_H_NY] mfe=34p || 08:45→09:45 B [BB_L,P,R50,SESS_L_LON] mfe=50p || 14:30→14:30 S [BB_U,R00,SESS_H_NY] mfe=34p
- `2024-02-26` Mon  range 34p net +19p  [none]  03:30→12:20 S [BB_U,P,PDH,R00,R1,R2,R3,SESS_H_ASIA,SESS_H_LATE,SESS_H_LON,SESS_H_NY] mfe=28p || 11:00→11:00 B [BB_L,P] mfe=26p
- `2024-02-27` Tue  range 36p net -0p  [none]  00:00→08:45 S [BB_U,P,PDH,SESS_H_ASIA,SESS_H_LON] mfe=25p || 12:40→15:40 B [BB_L,P,S1,SESS_L_LATE,SESS_L_NY] mfe=35p
- `2024-02-28` Wed  range 52p net +6p  [none]  00:00→10:00 B [BB_L,P,PDL,R50,S1,S2,S3,SESS_L_ASIA,SESS_L_LATE,SESS_L_LON] mfe=36p || 07:15→08:00 S [BB_U,R50,SESS_H_LON] mfe=40p
- `2024-02-29` Thu  range 69p net -40p  [none]  00:00→10:05 S [BB_U,P,SESS_H_ASIA,SESS_H_LON] mfe=39p || 09:25→13:00 B [BB_L,P,R50,SESS_L_LON,SESS_L_NY] mfe=46p || 11:30→15:05 S [BB_U,P,PDH,R50,SESS_H_NY] mfe=68p
- `2024-03-01` Fri  range 64p net +28p  [none]  03:15→10:20 B [BB_L,SESS_L_ASIA,SESS_L_LON] mfe=30p || 11:40→14:55 B [BB_L,P,PDL,R00,R50,S1,SESS_L_NY] mfe=60p
- `2024-03-06` Wed  range 58p net +34p  [none]  00:05→09:55 S [BB_U,P,R00,SESS_H_ASIA,SESS_H_LON] mfe=26p || 11:50→12:05 S [BB_U,SESS_H_LON] mfe=25p || 12:25→12:55 B [BB_L,P,SESS_L_LON] mfe=42p || 13:45→16:55 S [BB_U,PDH,R1,R50,SESS_H_LATE,SESS_H_NY] mfe=25p || 14:50→15:00 B [BB_L] mfe=45p
- `2024-03-07` Thu  range 82p net +68p  [DAY_BEFORE]  05:25→09:10 B [BB_L,P,R50,SESS_L_LON,SESS_L_NY] mfe=33p || 17:30→17:45 B [BB_L,R00] mfe=27p
- `2024-03-08` Fri  range 93p net +41p  [ON/NFP]  00:45→07:35 B [BB_L,R00,SESS_L_ASIA,SESS_L_LON] mfe=36p || 04:00→13:40 S [BB_U,PDH,R1,R2,R50,SESS_H_LATE,SESS_H_LON] mfe=46p || 11:35→11:40 B [BB_L] mfe=69p || 13:25→13:30 B [R50,SESS_L_NY] mfe=69p
- `2024-03-11` Mon  range 63p net -41p  [DAY_BEFORE]  09:35→11:40 S [BB_U,P,R50] mfe=45p || 13:30→13:35 S [SESS_H_NY] mfe=35p
- `2024-03-12` Tue  range 73p net -25p  [ON/CPI_US]  00:00→05:15 S [BB_U,P,SESS_H_ASIA] mfe=34p || 00:25→13:45 B [BB_L,PDL,R00,R50,S1,S2,SESS_L_ASIA,SESS_L_LATE,SESS_L_LON] mfe=43p || 09:40→12:40 S [BB_U,R00,R50] mfe=62p
- `2024-03-14` Thu  range 92p net -41p  [none]  04:55→10:15 S [BB_U,P,PDH,R00,R1,SESS_H_LON,SESS_H_NY] mfe=40p || 10:40→15:40 B [BB_L,P,PDL,R00,R50,S1,S2,S3,SESS_L_LATE,SESS_L_LON,SESS_L_NY] mfe=27p
- `2024-03-19` Tue  range 65p net +11p  [DAY_BEFORE]  02:00→03:15 S [BB_U,P,SESS_H_ASIA] mfe=27p || 03:35→09:55 B [BB_L,P,PDL,R00,S1,S2,S3,SESS_L_ASIA,SESS_L_LATE,SESS_L_LON,SESS_L_NY] mfe=41p || 07:15→07:20 S [BB_U,R00,SESS_H_LON] mfe=41p
- `2024-03-20` Wed  range 103p net +72p  [ON/FOMC,CPI_UK]  00:40→07:10 S [BB_U,SESS_H_ASIA] mfe=43p || 04:20→12:35 B [BB_L,P,R00,SESS_L_ASIA,SESS_L_LON,SESS_L_NY] mfe=27p || 17:30→17:35 B [BB_L] mfe=74p
- `2024-03-21` Thu  range 153p net -138p  [ON/BoE]  00:00→07:10 S [BB_U,PDH,R00,SESS_H_ASIA] mfe=41p || 10:05→10:15 S [BB_U] mfe=65p || 11:40→11:45 S [R50] mfe=62p || 14:30→14:55 S [R00] mfe=51p
- `2024-03-22` Fri  range 55p net -27p  [DAY_AFTER]  00:00→01:15 S [BB_U,R50,SESS_H_ASIA] mfe=41p || 01:35→10:10 B [BB_L,PDL,R00,R50,S1,SESS_L_ASIA,SESS_L_LON] mfe=46p || 04:20→05:10 S [BB_U] mfe=56p || 08:05→09:00 S [R00] mfe=27p || 11:10→14:00 S [BB_U,R00,SESS_H_NY] mfe=30p || 11:40→11:50 B [BB_L,R00,S1,SESS_L_LATE,SESS_L_LON,SESS_L_NY] mfe=47p
- `2024-03-25` Mon  range 57p net +30p  [none]  00:00→00:25 B [BB_L,P,PDL,R00,S1,SESS_L_ASIA] mfe=26p || 06:30→08:45 B [BB_L,P,R00,SESS_L_LON] mfe=39p
- `2024-03-27` Wed  range 36p net +19p  [none]  09:05→09:20 S [BB_U,P,SESS_H_LON] mfe=30p || 10:30→11:30 S [BB_U,P,SESS_H_LON] mfe=33p || 11:40→13:40 B [BB_L,PDL,S1,SESS_L_LATE,SESS_L_LON,SESS_L_NY] mfe=27p || 13:25→20:30 S [BB_U,P,SESS_H_LATE,SESS_H_NY] mfe=27p
- `2024-03-28` Thu  range 69p net -5p  [none]  00:20→05:40 S [BB_U,P,R1,SESS_H_ASIA] mfe=34p || 03:40→09:20 B [BB_L,P,PDL,R00,S1,S2,SESS_L_LON,SESS_L_NY] mfe=40p || 07:15→07:15 S [P] mfe=34p || 09:10→14:00 S [BB_U,P,PDH,R00,R1,R2,R50,SESS_H_LON,SESS_H_NY] mfe=33p
- `2024-04-01` Mon  range 92p net -80p  [HOL/none]  12:30→12:55 S [BB_U] mfe=58p || 14:05→14:05 S [R00,SESS_H_NY] mfe=74p
- `2024-04-02` Tue  range 38p net +35p  [none]  00:00→07:00 B [BB_L,PDL,R50,SESS_L_ASIA] mfe=28p || 11:25→14:05 B [BB_L,R50,SESS_L_NY] mfe=26p
- `2024-04-03` Wed  range 94p net +71p  [none]  05:45→08:35 B [BB_L,P,SESS_L_LON] mfe=26p || 13:15→14:20 B [BB_L,P,R00,SESS_L_NY] mfe=78p
- `2024-04-05` Fri  range 70p net +10p  [ON/NFP]  00:00→01:55 S [BB_U,R50,SESS_H_ASIA] mfe=27p || 00:00→14:10 B [BB_L,PDL,R00,S1,S2,S3,SESS_L_ASIA,SESS_L_LATE,SESS_L_LON,SESS_L_NY] mfe=60p || 11:30→13:25 S [BB_U,R00,SESS_H_LATE] mfe=70p
- `2024-04-08` Mon  range 51p net +24p  [none]  00:00→01:50 B [BB_L,P,PDL,S1,S2,SESS_L_ASIA] mfe=25p || 04:30→13:05 B [BB_L,P,PDL,S1,S2,SESS_L_LON,SESS_L_NY] mfe=38p
- `2024-04-09` Tue  range 60p net +18p  [DAY_BEFORE]  00:00→14:30 S [BB_U,PDH,R00,R1,R2,R50,SESS_H_ASIA,SESS_H_LATE,SESS_H_LON,SESS_H_NY] mfe=42p || 06:35→08:35 B [BB_L,R50,SESS_L_LON] mfe=42p
- `2024-04-10` Wed  range 188p net -134p  [ON/CPI_US]  00:00→13:25 S [BB_U,P,PDH,R00,R1,SESS_H_ASIA,SESS_H_LON] mfe=163p || 11:30→17:30 B [BB_L,R00,R50,S2,S3,SESS_L_NY] mfe=34p || 16:20→16:20 S [R50] mfe=33p || 18:15→18:30 S [BB_U,R50,SESS_H_LATE] mfe=28p
- `2024-04-11` Thu  range 68p net +17p  [DAY_AFTER]  00:00→09:20 S [BB_U,R50,SESS_H_ASIA,SESS_H_LON] mfe=40p || 03:40→07:55 B [BB_L,R50,SESS_L_LON] mfe=37p || 12:00→14:15 S [BB_U,R50,SESS_H_NY] mfe=68p || 14:55→16:30 B [BB_L,PDL,R50,SESS_L_NY] mfe=53p
- `2024-04-12` Fri  range 116p net -93p  [none]  00:00→15:50 B [BB_L,P,PDL,R00,R50,S1,S2,S3,SESS_L_ASIA,SESS_L_LATE,SESS_L_LON,SESS_L_NY] mfe=33p || 06:35→06:45 S [BB_U,SESS_H_LON] mfe=39p || 09:15→09:20 S [BB_U] mfe=59p || 10:30→10:55 S [R00] mfe=48p || 13:20→13:35 S [BB_U,SESS_H_NY] mfe=49p
- `2024-04-15` Mon  range 63p net -18p  [none]  00:15→12:10 S [BB_U,P,PDH,R00,R1,R2,R3,R50,SESS_H_ASIA,SESS_H_LON,SESS_H_NY] mfe=48p || 08:15→08:45 B [BB_L,SESS_L_LON] mfe=32p || 11:30→13:35 B [BB_L,P,R50,SESS_L_NY] mfe=45p
- `2024-04-16` Tue  range 66p net -5p  [DAY_BEFORE]  00:00→00:40 S [BB_U,R50,SESS_H_ASIA] mfe=29p || 00:15→18:30 B [BB_L,P,PDL,R50,S1,SESS_L_ASIA,SESS_L_LATE,SESS_L_NY] mfe=45p || 04:40→07:00 S [BB_U,R50] mfe=39p || 09:25→13:35 S [BB_U,P,R50,SESS_H_LON,SESS_H_NY] mfe=43p || 19:05→19:10 S [BB_U,R50,SESS_H_LATE] mfe=27p
- `2024-04-17` Wed  range 60p net +30p  [ON/CPI_UK]  00:00→06:40 B [BB_L,P,SESS_L_ASIA] mfe=65p || 07:00→09:40 S [BB_U,P,PDH,R1,R50,SESS_H_LATE,SESS_H_LON,SESS_H_NY] mfe=28p || 08:30→08:45 B [R50] mfe=31p || 10:55→17:20 B [BB_L,P,R50,SESS_L_NY] mfe=41p
- `2024-04-18` Thu  range 51p net -35p  [DAY_AFTER]  10:15→14:45 B [BB_L,P,R50,SESS_L_NY] mfe=30p || 13:35→14:05 S [BB_U,P,R50] mfe=32p
- `2024-04-19` Fri  range 102p net -40p  [none]  00:20→00:50 S [BB_U,SESS_H_ASIA] mfe=48p || 13:00→14:30 S [BB_U,P,R1,R50,SESS_H_NY] mfe=96p || 16:55→17:00 S [R00] mfe=35p || 18:15→18:20 S [SESS_H_LATE] mfe=25p
- `2024-04-23` Tue  range 127p net +106p  [none]  00:00→09:35 S [BB_U,P,R50,SESS_H_ASIA,SESS_H_LON] mfe=43p || 00:00→07:25 B [BB_L,P,R50,SESS_L_ASIA] mfe=57p || 10:35→11:50 B [BB_L,P,R00,R50,SESS_L_NY] mfe=91p
- `2024-04-24` Wed  range 47p net +10p  [none]  10:10→14:30 S [BB_U,R50,SESS_H_NY] mfe=29p || 12:45→16:45 B [BB_L,R50,SESS_L_NY] mfe=32p
- `2024-04-25` Thu  range 71p net +42p  [none]  04:10→04:35 B [BB_L] mfe=36p || 05:20→13:30 S [BB_U,PDH,R00,R1,R2,R3,SESS_H_ASIA,SESS_H_LATE,SESS_H_LON,SESS_H_NY] mfe=71p || 10:50→15:00 B [BB_L,R00,SESS_L_NY] mfe=64p
- `2024-04-26` Fri  range 92p net -7p  [none]  02:15→09:40 S [BB_U,P,PDH,R00,R1,SESS_H_ASIA,SESS_H_LON] mfe=34p || 07:25→08:20 B [BB_L,P,R00,SESS_L_LON] mfe=44p || 10:35→16:10 B [BB_L,P,PDL,R00,R50,S1,SESS_L_NY] mfe=49p || 12:05→13:30 S [BB_U,PDH,R00,R1,SESS_H_NY] mfe=91p || 15:10→15:10 S [P,R00] mfe=52p
- `2024-04-29` Mon  range 62p net +25p  [none]  09:40→10:10 B [BB_L,SESS_L_LON] mfe=36p || 13:35→14:40 B [BB_L,SESS_L_NY] mfe=55p
- `2024-04-30` Tue  range 61p net -39p  [DAY_BEFORE]  00:00→07:35 B [BB_L,P,R50,SESS_L_ASIA,SESS_L_LON] mfe=30p || 08:00→10:35 S [BB_U,P,R50,SESS_H_LON] mfe=52p || 15:05→15:15 S [BB_U,P] mfe=39p
- `2024-05-01` Wed  range 84p net +17p  [ON/FOMC]  00:00→07:55 B [BB_L,P,PDL,R00,S1,SESS_L_ASIA,SESS_L_LON,SESS_L_NY] mfe=32p || 18:20→19:55 S [BB_U,P,R00,R1,R50,SESS_H_LATE] mfe=61p
- `2024-05-02` Thu  range 73p net +2p  [DAY_BEFORE]  05:30→07:25 S [BB_U] mfe=32p || 08:35→08:40 S [BB_U,P,SESS_H_LON] mfe=37p || 09:10→15:15 B [BB_L,P,R00,S1,SESS_L_LATE,SESS_L_LON,SESS_L_NY] mfe=50p || 10:40→13:45 S [BB_U,P,R00,SESS_H_NY] mfe=61p
- `2024-05-03` Fri  range 105p net -1p  [ON/NFP]  00:15→01:25 B [BB_L,R50,SESS_L_ASIA,SESS_L_LON] mfe=26p || 11:00→15:25 B [BB_L,R00,R50,SESS_L_LATE,SESS_L_NY] mfe=32p
- `2024-05-07` Tue  range 64p net -31p  [none]  09:40→14:40 S [BB_U,P,R50,SESS_H_LON,SESS_H_NY] mfe=34p || 16:05→16:10 S [R50] mfe=48p
- `2024-05-08` Wed  range 37p net +9p  [DAY_BEFORE]  00:00→09:20 B [BB_L,PDL,R00,S1,SESS_L_ASIA,SESS_L_LATE,SESS_L_LON,SESS_L_NY] mfe=33p || 04:15→07:35 S [BB_U,SESS_H_LON] mfe=25p || 10:10→12:05 S [BB_U,R00,SESS_H_LON] mfe=28p
- `2024-05-14` Tue  range 84p net +37p  [DAY_BEFORE]  00:00→09:25 B [BB_L,P,PDL,R50,S1,SESS_L_ASIA,SESS_L_LON] mfe=50p || 06:30→07:15 S [BB_U,P,R50,SESS_H_LON] mfe=54p || 11:15→13:30 B [BB_L,P,PDL,R50,S1] mfe=72p
- `2024-05-15` Wed  range 97p net +84p  [ON/CPI_US]  05:15→07:40 B [BB_L,SESS_L_LON] mfe=34p || 11:40→12:00 B [BB_L,R00] mfe=68p || 13:15→13:25 B [BB_L,R50,SESS_L_NY] mfe=57p || 16:05→17:00 B [R50] mfe=34p
- `2024-05-21` Tue  range 40p net +3p  [DAY_BEFORE]  11:45→14:00 B [BB_L,P,PDL,R00,S1] mfe=40p || 12:45→15:50 S [BB_U,P,PDH,R00,R1,SESS_H_LATE,SESS_H_LON,SESS_H_NY] mfe=25p
- `2024-05-22` Wed  range 61p net +6p  [ON/CPI_UK]  04:10→06:15 B [BB_L,P,R50,SESS_L_ASIA] mfe=53p || 05:50→07:50 S [BB_U,P,PDH,R1,R2,R50,SESS_H_LON,SESS_H_NY] mfe=42p || 11:50→12:45 B [BB_L,P,R00,SESS_L_LON] mfe=48p || 15:30→16:15 B [BB_L] mfe=29p
- `2024-05-23` Thu  range 61p net -29p  [DAY_AFTER]  00:00→13:05 S [BB_U,P,SESS_H_ASIA,SESS_H_LON] mfe=40p || 04:45→10:20 B [BB_L,P,SESS_L_LON] mfe=40p || 14:20→14:35 S [BB_U,P,SESS_H_NY] mfe=41p || 16:45→17:00 S [BB_U,R00,SESS_H_LATE] mfe=37p
- `2024-05-24` Fri  range 75p net +50p  [none]  00:00→07:00 B [BB_L,P,PDL,R00,SESS_L_ASIA] mfe=32p || 12:45→13:30 B [BB_L,P] mfe=41p
- `2024-05-28` Tue  range 47p net -13p  [none]  04:15→09:40 B [BB_L,P,SESS_L_LON] mfe=27p || 10:40→14:25 S [BB_U,P,PDH,R00,R1,SESS_H_LON,SESS_H_NY] mfe=30p
- `2024-05-30` Thu  range 66p net +44p  [none]  00:00→07:50 B [BB_L,PDL,R00,SESS_L_ASIA,SESS_L_LON] mfe=38p || 11:10→11:15 B [BB_L] mfe=26p || 12:50→13:15 B [BB_L,P,SESS_L_NY] mfe=39p
- `2024-05-31` Fri  range 66p net +25p  [none]  00:00→08:35 B [BB_L,P,R00,SESS_L_ASIA,SESS_L_LON] mfe=27p || 09:15→15:05 S [BB_U,P,PDH,R1,R50,SESS_H_LON,SESS_H_NY] mfe=48p || 10:40→13:30 B [BB_L,P,SESS_L_NY] mfe=59p
- `2024-06-03` Mon  range 106p net +63p  [none]  00:00→10:15 B [BB_L,P,PDL,R00,R50,S1,S2,S3,SESS_L_ASIA,SESS_L_LON,SESS_L_NY] mfe=39p || 17:35→18:10 B [BB_L] mfe=27p
- `2024-06-04` Tue  range 61p net -30p  [none]  03:40→05:35 S [BB_U,PDH,R00,SESS_H_LON] mfe=26p || 05:00→11:45 B [BB_L,P,R00,R50,SESS_L_ASIA,SESS_L_LON] mfe=33p || 10:05→10:05 S [P] mfe=30p || 12:05→18:50 S [BB_U,P,R00,R50,SESS_H_LATE,SESS_H_NY] mfe=30p || 13:20→13:35 B [BB_L,P,SESS_L_NY] mfe=31p
- `2024-06-05` Wed  range 40p net +20p  [none]  12:35→14:05 S [BB_U,P,SESS_H_LATE,SESS_H_NY] mfe=40p || 14:45→15:55 B [BB_L,P,SESS_L_NY] mfe=29p
- `2024-06-07` Fri  range 100p net -64p  [ON/NFP]  00:00→13:30 S [BB_U,P,PDH,R00,R1,SESS_H_ASIA,SESS_H_LON,SESS_H_NY] mfe=100p || 15:35→15:40 S [BB_U] mfe=25p
- `2024-06-10` Mon  range 49p net +12p  [none]  00:00→11:30 B [BB_L,P,PDL,R00,S1,S2,S3,SESS_L_ASIA,SESS_L_LON,SESS_L_NY] mfe=42p || 06:25→09:25 S [BB_U,P,SESS_H_LON] mfe=37p || 10:50→13:30 S [BB_U,P,PDH,R00] mfe=25p
- `2024-06-11` Tue  range 46p net +6p  [DAY_BEFORE]  05:50→08:10 B [BB_L,P,SESS_L_LON] mfe=36p || 12:25→15:05 B [BB_L,P,SESS_L_LATE,SESS_L_NY] mfe=30p
- `2024-06-12` Wed  range 124p net +49p  [ON/CPI_US,FOMC]  08:45→14:30 S [BB_U,PDH,R1,R50,SESS_H_LON,SESS_H_NY] mfe=35p || 13:15→13:15 B [BB_L,R50,SESS_L_NY] mfe=103p
- `2024-06-13` Thu  range 69p net -14p  [DAY_AFTER]  07:00→10:00 S [BB_U,P,R00,SESS_H_LON] mfe=39p || 09:30→13:00 B [BB_L,P,R00,SESS_L_LON,SESS_L_NY] mfe=46p || 13:30→13:30 S [BB_U,P,R00] mfe=56p || 14:55→17:45 B [BB_L,R50,SESS_L_NY] mfe=29p
- `2024-06-14` Fri  range 88p net -54p  [none]  02:20→04:15 S [BB_U,SESS_H_ASIA] mfe=27p || 04:20→14:50 B [BB_L,PDL,R00,R50,S1,S2,S3,SESS_L_ASIA,SESS_L_LATE,SESS_L_LON,SESS_L_NY] mfe=32p || 05:45→06:25 S [BB_U,R50,SESS_H_LON] mfe=31p || 12:30→12:35 S [BB_U] mfe=60p
- `2024-06-18` Tue  range 52p net +14p  [DAY_BEFORE]  11:35→13:25 B [BB_L,P,R00,S1,SESS_L_LON,SESS_L_NY] mfe=52p || 13:30→15:25 S [BB_U,P,PDH,R00,SESS_H_LATE,SESS_H_NY] mfe=36p
- `2024-06-20` Thu  range 56p net -46p  [ON/BoE]  15:05→16:00 S [BB_U] mfe=28p || 18:15→19:25 S [BB_U,SESS_H_LATE] mfe=29p
- `2024-06-21` Fri  range 52p net -15p  [DAY_AFTER]  00:00→07:00 S [BB_U,P,R50,SESS_H_ASIA] mfe=43p || 12:50→14:00 S [BB_U,R50,SESS_H_NY] mfe=29p
- `2024-06-24` Mon  range 53p net +38p  [none]  07:05→08:25 B [BB_L,R50,SESS_L_LON] mfe=27p || 11:50→12:20 B [BB_L,SESS_L_NY] mfe=38p
- `2024-06-26` Wed  range 72p net -61p  [none]  10:25→10:45 S [BB_U] mfe=34p || 12:20→13:20 S [BB_U,R50,SESS_H_NY] mfe=45p || 15:15→15:15 S [BB_U,R50] mfe=32p
- `2024-06-27` Thu  range 44p net -0p  [none]  04:55→09:25 B [BB_L,P,R50,SESS_L_LATE,SESS_L_LON,SESS_L_NY] mfe=28p || 10:00→15:00 S [BB_U,P,R1,R50,SESS_H_LON,SESS_H_NY] mfe=27p
- `2024-06-28` Fri  range 44p net +9p  [none]  04:35→05:50 B [BB_L,SESS_L_ASIA] mfe=28p || 06:10→13:30 S [BB_U,P,R50,SESS_H_LON,SESS_H_NY] mfe=44p || 08:00→15:40 B [BB_L,P,R50,SESS_L_LATE,SESS_L_LON,SESS_L_NY] mfe=34p
- `2024-07-01` Mon  range 77p net -22p  [none]  00:00→15:00 S [BB_U,P,PDH,R00,R1,R2,R3,R50,SESS_H_ASIA,SESS_H_LATE,SESS_H_LON,SESS_H_NY] mfe=74p || 03:40→04:50 B [BB_L] mfe=35p
- `2024-07-05` Fri  range 56p net +47p  [ON/NFP]  05:45→08:05 B [BB_L,SESS_L_LON] mfe=26p || 12:20→13:30 B [BB_L,R00,SESS_L_LATE] mfe=53p
- `2024-07-08` Mon  range 46p net -0p  [none]  07:35→15:20 S [BB_U,P,PDH,R1,R2,SESS_H_LON,SESS_H_NY] mfe=28p || 10:20→10:25 B [BB_L] mfe=27p || 12:00→12:00 B [BB_L] mfe=30p
- `2024-07-09` Tue  range 48p net -20p  [none]  01:30→09:00 B [BB_L,PDL,R00,SESS_L_ASIA,SESS_L_LON] mfe=29p || 03:10→11:30 S [BB_U,P,R00,SESS_H_LON,SESS_H_NY] mfe=31p
- `2024-07-11` Thu  range 94p net +56p  [ON/CPI_US]  00:00→13:50 S [BB_U,PDH,R1,R3,R50,SESS_H_ASIA,SESS_H_LON,SESS_H_NY] mfe=46p || 11:30→13:25 B [BB_L] mfe=81p
- `2024-07-12` Fri  range 88p net +73p  [DAY_AFTER]  06:20→07:40 B [BB_L,P,R00,SESS_L_LON] mfe=48p || 13:10→13:30 B [BB_L,R50,SESS_L_NY] mfe=60p
- `2024-07-15` Mon  range 33p net -6p  [none]  00:00→15:00 S [BB_U,P,PDH,R1,R2,SESS_H_ASIA,SESS_H_LON,SESS_H_NY] mfe=29p || 10:35→13:30 B [BB_L,P,SESS_L_NY] mfe=28p
- `2024-07-16` Tue  range 42p net +17p  [DAY_BEFORE]  10:45→11:20 S [BB_U,P,SESS_H_LON] mfe=34p || 12:45→13:25 S [BB_U,P,R50,SESS_H_LON] mfe=42p
- `2024-07-17` Wed  range 74p net +36p  [ON/CPI_UK]  04:00→06:05 B [BB_L,P,SESS_L_ASIA,SESS_L_LON] mfe=49p || 08:45→08:45 B [R00] mfe=42p
- `2024-07-18` Thu  range 70p net -62p  [DAY_AFTER]  00:00→06:40 S [BB_U,P,R00,SESS_H_ASIA] mfe=29p || 17:30→17:30 S [BB_U,SESS_H_LATE] mfe=37p
- `2024-07-19` Fri  range 41p net -30p  [none]  00:00→11:05 B [BB_L,PDL,R00,R50,S1,SESS_L_ASIA,SESS_L_LATE,SESS_L_LON,SESS_L_NY] mfe=28p || 06:55→08:00 S [BB_U,SESS_H_LON] mfe=39p
- `2024-07-22` Mon  range 37p net +16p  [none]  00:00→00:30 S [PDH] mfe=28p || 07:30→12:00 S [BB_U,P,PDH,R1,SESS_H_LON,SESS_H_NY] mfe=28p
- `2024-07-23` Tue  range 41p net -24p  [none]  09:30→09:40 S [BB_U,P,SESS_H_LON] mfe=41p || 10:40→11:30 B [BB_L,PDL,R00,S1,S2,SESS_L_LATE,SESS_L_LON,SESS_L_NY] mfe=32p
- `2024-07-25` Thu  range 61p net -42p  [none]  05:20→08:15 B [BB_L,P,PDL,R00,S1,SESS_L_ASIA,SESS_L_LON] mfe=39p || 08:50→09:05 S [BB_U,P,R00,SESS_H_LON] mfe=43p || 11:10→11:20 S [BB_U] mfe=34p
- `2024-07-29` Mon  range 70p net -7p  [none]  00:00→01:00 B [BB_L,P,SESS_L_ASIA] mfe=25p || 04:00→10:05 B [BB_L,P,PDL,R50,S1,S2,S3,SESS_L_LATE,SESS_L_LON,SESS_L_NY] mfe=40p || 13:40→14:30 S [BB_U,R50,SESS_H_NY] mfe=31p
- `2024-07-31` Wed  range 43p net +9p  [ON/FOMC]  00:00→09:35 B [BB_L,P,PDL,R50,SESS_L_ASIA,SESS_L_LON] mfe=28p || 06:25→08:50 S [BB_U,P,R50,SESS_H_LON] mfe=26p || 10:35→14:20 S [BB_U,P,R50,SESS_H_LON,SESS_H_NY] mfe=26p || 12:00→19:00 B [BB_L,P,PDL,R50,SESS_L_LATE,SESS_L_NY] mfe=43p
- `2024-08-01` Thu  range 122p net -106p  [ON/BoE]  08:40→08:45 S [R00] mfe=46p || 11:25→15:05 S [BB_U,R00,SESS_H_NY] mfe=89p
- `2024-08-02` Fri  range 133p net +74p  [ON/NFP]  00:00→08:20 B [BB_L,PDL,SESS_L_ASIA,SESS_L_LON] mfe=38p || 03:55→07:40 S [BB_U,SESS_H_ASIA,SESS_H_LON] mfe=32p || 09:25→15:20 S [BB_U,P,R00,R1,R50,SESS_H_LATE,SESS_H_LON,SESS_H_NY] mfe=57p || 11:40→11:40 B [BB_L,R00,R50,SESS_L_NY] mfe=91p || 15:45→17:00 B [BB_L,R00] mfe=29p
- `2024-08-05` Mon  range 107p net +28p  [none]  00:00→07:05 B [BB_L,P,PDL,R00,R50,S1,S2,S3,SESS_L_ASIA,SESS_L_LATE,SESS_L_LON,SESS_L_NY] mfe=107p || 01:45→05:00 S [BB_U,P,R00,R1,SESS_H_ASIA] mfe=95p || 07:35→09:10 S [BB_U,P,PDH,R00,R1,R50,SESS_H_LON] mfe=90p || 11:15→14:45 S [BB_U,P,R50,SESS_H_NY] mfe=48p || 16:20→17:25 S [BB_U,R50] mfe=41p
- `2024-08-06` Tue  range 99p net -79p  [none]  00:00→02:00 S [BB_U,R00,SESS_H_ASIA] mfe=26p || 01:05→01:15 B [BB_L,R00,SESS_L_ASIA] mfe=25p || 03:50→13:30 B [BB_L,P,PDL,R00,R50,S1,SESS_L_ASIA,SESS_L_LON,SESS_L_NY] mfe=54p || 04:35→04:40 S [BB_U] mfe=36p || 06:20→06:20 S [BB_U,P,R50] mfe=48p || 09:30→09:30 S [R50] mfe=67p || 11:25→11:30 S [R00] mfe=34p || 14:30→15:20 S [BB_U,R00,SESS_H_LATE,SESS_H_NY] mfe=42p || 14:50→16:40 B [BB_L,PDL,R00,S1,SESS_L_LATE] mfe=28p
- `2024-08-07` Wed  range 52p net -14p  [none]  00:00→00:55 B [BB_L,R00] mfe=32p || 00:15→05:35 S [BB_U,R00,SESS_H_ASIA] mfe=31p || 05:45→08:30 B [BB_L,P,R00,SESS_L_LON,SESS_L_NY] mfe=28p || 07:15→12:30 S [BB_U,P,R00,SESS_H_LON,SESS_H_NY] mfe=28p
- `2024-08-08` Thu  range 87p net +50p  [none]  00:25→08:00 S [BB_U,P,R00,SESS_H_ASIA,SESS_H_LON] mfe=43p || 05:10→11:05 B [BB_L,P,PDL,R00,S1,SESS_L_LON] mfe=37p || 12:55→13:55 B [BB_L,P,PDL,R00,S1,SESS_L_NY] mfe=77p
- `2024-08-12` Mon  range 41p net +2p  [none]  00:00→16:10 S [BB_U,P,PDH,R1,R2,R3,R50,SESS_H_ASIA,SESS_H_LATE,SESS_H_LON,SESS_H_NY] mfe=39p || 03:40→04:55 B [BB_L,P] mfe=25p || 13:40→13:45 B [BB_L,SESS_L_NY] mfe=35p || 15:00→15:05 B [BB_L,SESS_L_NY] mfe=35p
- `2024-08-13` Tue  range 94p net +87p  [DAY_BEFORE]  06:40→06:50 B [BB_L,R00,SESS_L_LON] mfe=37p || 13:15→13:25 B [BB_L,R00] mfe=58p
- `2024-08-14` Wed  range 47p net -34p  [ON/CPI_US,CPI_UK]  00:15→07:00 B [BB_L,P,R50,SESS_L_ASIA,SESS_L_LATE,SESS_L_NY] mfe=30p || 04:45→07:00 S [BB_U,P,R50] mfe=40p || 12:35→15:40 S [BB_U,P,R50,SESS_H_NY] mfe=38p
- `2024-08-16` Fri  range 75p net +69p  [none]  07:40→08:30 B [BB_L,SESS_L_LON] mfe=39p || 10:55→15:45 B [BB_L,R00,SESS_L_NY] mfe=49p
- `2024-08-20` Tue  range 74p net +53p  [none]  00:00→06:45 B [BB_L,P,SESS_L_ASIA] mfe=39p || 05:10→15:50 S [BB_U,P,PDH,R00,R1,R2,R50,SESS_H_LATE,SESS_H_LON,SESS_H_NY] mfe=40p
- `2024-08-21` Wed  range 109p net +69p  [none]  00:00→08:45 B [BB_L,P,SESS_L_ASIA,SESS_L_LON] mfe=32p || 12:45→13:00 B [BB_L] mfe=42p || 13:20→19:25 S [BB_U,PDH,R00,R1,R2,R50,SESS_H_LATE,SESS_H_NY] mfe=35p || 15:00→15:00 B [BB_L,R50] mfe=57p || 18:25→18:25 B [SESS_L_LATE] mfe=29p
- `2024-08-22` Thu  range 54p net +1p  [none]  00:15→07:05 B [BB_L,SESS_L_ASIA] mfe=48p || 09:05→09:15 B [R00] mfe=36p || 13:25→14:25 S [BB_U,PDH,R00,SESS_H_LATE,SESS_H_NY] mfe=49p
- `2024-08-23` Fri  range 123p net +99p  [none]  00:00→16:15 S [BB_U,P,PDH,R00,R1,R3,SESS_H_ASIA,SESS_H_LATE,SESS_H_LON,SESS_H_NY] mfe=56p || 13:00→14:20 B [BB_L,R00,SESS_L_NY] mfe=122p
- `2024-08-26` Mon  range 30p net -16p  [HOL/none]  00:00→12:35 B [BB_L,P,PDL,R00,S1,S2,S3,SESS_L_ASIA,SESS_L_LATE,SESS_L_LON,SESS_L_NY] mfe=29p || 11:55→12:00 S [BB_U,R00] mfe=26p || 13:30→15:40 S [BB_U,P,R00,SESS_H_NY] mfe=29p || 17:35→18:10 S [BB_U,R00,SESS_H_LATE] mfe=26p
- `2024-08-27` Tue  range 72p net +66p  [none]  06:15→06:45 B [BB_L,P,R00,SESS_L_LON] mfe=32p || 11:20→13:30 B [BB_L,SESS_L_NY] mfe=38p || 16:30→16:30 B [BB_L] mfe=39p
- `2024-08-28` Wed  range 77p net -44p  [none]  07:35→08:30 S [BB_U,P,SESS_H_LON] mfe=31p || 12:10→15:50 S [BB_U,R00,SESS_H_NY] mfe=59p || 17:00→17:00 S [R00] mfe=32p
- `2024-08-29` Thu  range 82p net -50p  [none]  00:00→07:05 S [BB_U,P,R00,SESS_H_ASIA,SESS_H_LON] mfe=59p || 07:55→09:25 B [BB_L,P,PDL,R00,SESS_L_LON] mfe=34p || 10:30→10:35 S [BB_U,R00] mfe=47p || 10:40→14:40 B [BB_L,PDL,R00,R50,S1,SESS_L_NY] mfe=45p || 13:25→13:30 S [SESS_H_NY] mfe=39p || 16:10→17:30 S [BB_U,SESS_H_LATE,SESS_H_NY] mfe=27p
- `2024-08-30` Fri  range 90p net -38p  [none]  04:20→09:30 S [BB_U,P,R00,SESS_H_ASIA,SESS_H_LON] mfe=31p || 07:40→07:40 B [P,SESS_L_LON] mfe=30p || 11:15→13:15 S [BB_U,P,SESS_H_NY] mfe=57p || 14:55→15:40 S [BB_U,R50] mfe=54p
- `2024-09-03` Tue  range 59p net -16p  [none]  00:00→19:00 B [BB_L,P,PDL,R00,S1,S2,S3,SESS_L_ASIA,SESS_L_LATE,SESS_L_LON,SESS_L_NY] mfe=29p || 08:00→08:15 S [BB_U,P,SESS_H_LON] mfe=30p || 11:25→14:25 S [BB_U,P,R00,SESS_H_NY] mfe=58p
- `2024-09-04` Wed  range 74p net +32p  [none]  02:40→15:40 S [BB_U,P,PDH,R1,R2,R50,SESS_H_ASIA,SESS_H_LON,SESS_H_NY] mfe=43p || 05:55→08:00 B [BB_L,P,R00,SESS_L_LON] mfe=26p
- `2024-09-05` Thu  range 48p net +22p  [DAY_BEFORE]  00:00→08:05 B [BB_L,P,R50,SESS_L_ASIA,SESS_L_LON] mfe=34p || 10:50→11:15 B [BB_L] mfe=25p || 11:50→13:20 S [BB_U,PDH,R1,SESS_H_LON,SESS_H_NY] mfe=29p || 12:45→13:50 B [BB_L,SESS_L_NY] mfe=25p || 15:00→15:55 B [BB_L,R50,SESS_L_NY] mfe=29p
- `2024-09-06` Fri  range 129p net -45p  [ON/NFP]  00:00→08:10 S [BB_U,PDH,R1,SESS_H_ASIA,SESS_H_LON] mfe=33p || 10:05→13:30 S [BB_U,P,PDH,R00,R1,R2,R50,SESS_H_NY] mfe=106p || 11:55→17:50 B [BB_L,P,PDL,R00,R50,S1,S2,SESS_L_NY] mfe=29p
- `2024-09-09` Mon  range 51p net -42p  [none]  00:15→15:45 B [BB_L,P,PDL,R00,S1,S2,S3,SESS_L_ASIA,SESS_L_LATE,SESS_L_LON,SESS_L_NY] mfe=34p || 07:40→07:40 S [BB_U,R00,SESS_H_LON] mfe=34p || 10:20→10:30 S [BB_U,R00] mfe=27p || 12:35→14:45 S [BB_U,R00,SESS_H_NY] mfe=34p || 16:50→18:10 S [BB_U,R00] mfe=30p
- `2024-09-10` Tue  range 58p net +12p  [DAY_BEFORE]  02:25→08:20 S [BB_U,P,R00,SESS_H_ASIA,SESS_H_LON] mfe=29p || 06:10→06:55 B [BB_L,P,R00] mfe=34p || 10:30→12:05 S [BB_U,P,R00] mfe=52p
- `2024-09-11` Wed  range 104p net -62p  [ON/CPI_US]  00:00→06:20 S [BB_U,P,PDH,R00,R1,SESS_H_ASIA,SESS_H_LON] mfe=34p || 00:00→02:10 B [BB_L,P,SESS_L_ASIA] mfe=27p || 04:00→04:05 B [BB_L] mfe=27p || 13:15→15:45 B [BB_L,PDL,R00,R50,S1,S2,SESS_L_LATE,SESS_L_NY] mfe=46p || 14:35→14:35 S [R50] mfe=51p
- `2024-09-12` Thu  range 87p net +64p  [DAY_AFTER]  06:35→09:00 B [BB_L,P,R50,SESS_L_LON,SESS_L_NY] mfe=28p || 18:15→18:35 B [BB_L,R00,SESS_L_LATE] mfe=41p
- `2024-09-13` Fri  range 43p net -19p  [none]  00:00→10:25 S [BB_U,PDH,R50,SESS_H_ASIA,SESS_H_LON] mfe=38p || 02:45→08:15 B [BB_L,SESS_L_LON] mfe=28p || 10:10→13:05 B [BB_L,R50,SESS_L_LON] mfe=43p || 13:15→15:40 S [BB_U,PDH,R1,R50,SESS_H_LATE,SESS_H_NY] mfe=35p
- `2024-09-18` Wed  range 141p net +30p  [ON/FOMC,CPI_UK]  02:15→06:05 B [BB_L,P,SESS_L_ASIA] mfe=44p || 06:55→19:30 S [BB_U,P,PDH,R00,R1,R2,R3,R50,SESS_H_LATE,SESS_H_LON,SESS_H_NY] mfe=123p || 09:25→09:40 B [R00] mfe=25p || 11:55→20:50 B [BB_L,P,R00,R50,SESS_L_LATE,SESS_L_NY] mfe=43p
- `2024-09-19` Thu  range 94p net +58p  [ON/BoE]  00:00→00:00 S [BB_U,R00] mfe=63p || 00:15→02:30 B [BB_L,PDL,R00,R50,SESS_L_ASIA] mfe=60p || 04:25→04:25 B [R00] mfe=43p || 07:00→07:00 B [BB_L,P,R50] mfe=55p || 13:15→14:45 B [BB_L,P,R50,SESS_L_NY] mfe=69p
- `2024-09-20` Fri  range 72p net +23p  [DAY_AFTER]  04:40→06:25 B [BB_L,R00] mfe=54p || 06:50→08:15 S [BB_U,PDH,R00,SESS_H_LON] mfe=55p || 12:25→14:00 S [BB_U,PDH,R00,SESS_H_NY] mfe=55p || 14:20→16:20 B [BB_L,R00,SESS_L_NY] mfe=63p || 16:35→17:55 S [BB_U,PDH,R00,SESS_H_NY] mfe=25p
- `2024-09-23` Mon  range 111p net +30p  [none]  00:00→09:10 B [BB_L,P,PDL,R00,R50,S1,S2,S3,SESS_L_ASIA,SESS_L_LON] mfe=66p || 02:15→07:35 S [BB_U,P,PDH,R00,SESS_H_ASIA,SESS_H_LON] mfe=72p || 14:45→14:45 B [P] mfe=47p
- `2024-09-24` Tue  range 84p net +61p  [none]  00:10→03:20 B [BB_L,R50,SESS_L_ASIA] mfe=26p || 06:55→07:30 B [BB_L,R50] mfe=51p || 11:15→12:40 B [BB_L] mfe=40p || 14:40→14:50 B [BB_L,SESS_L_NY] mfe=26p || 16:20→16:45 B [BB_L,SESS_L_NY] mfe=33p || 18:15→18:15 B [SESS_L_LATE] mfe=28p
- `2024-09-25` Wed  range 101p net -94p  [none]  03:35→04:35 S [BB_U,PDH] mfe=30p || 07:25→07:30 S [P,R00] mfe=39p || 11:50→14:05 S [BB_U,P,R00,SESS_H_NY] mfe=78p || 16:40→16:40 S [R50] mfe=35p
- `2024-09-26` Thu  range 100p net +67p  [none]  00:00→16:55 S [BB_U,P,PDH,R00,R1,R50,SESS_H_ASIA,SESS_H_LATE,SESS_H_LON,SESS_H_NY] mfe=29p || 00:00→01:00 B [BB_L,PDL,SESS_L_ASIA] mfe=26p || 07:30→09:00 B [BB_L,P,R50,SESS_L_LON] mfe=47p || 13:00→14:20 B [BB_L,P,R00,R50,SESS_L_NY] mfe=84p
- `2024-09-27` Fri  range 68p net -6p  [none]  00:00→00:00 S [BB_U,P,R00,SESS_H_ASIA,SESS_H_LON] mfe=27p || 04:55→09:05 B [BB_L,P,SESS_L_ASIA,SESS_L_LON] mfe=38p || 09:40→14:10 S [BB_U,P,R00,SESS_H_LON,SESS_H_NY] mfe=43p || 11:25→13:25 B [BB_L,P,R00,SESS_L_NY] mfe=48p || 16:20→16:20 S [BB_U,P,R00,SESS_H_LATE] mfe=27p
- `2024-09-30` Mon  range 73p net -19p  [none]  00:00→09:45 S [BB_U,P,PDH,R00,R1,R2,R3,SESS_H_ASIA,SESS_H_LATE,SESS_H_LON,SESS_H_NY] mfe=37p || 07:00→08:30 B [BB_L,P,R00,SESS_L_LON] mfe=49p || 12:50→19:25 B [BB_L,P,PDL,R00,R50,S1,S2,S3,SESS_L_LATE,SESS_L_NY] mfe=32p
- `2024-10-01` Tue  range 148p net -92p  [none]  05:30→06:40 S [BB_U,P,R50,SESS_H_LON] mfe=58p || 06:45→18:20 B [BB_L,PDL,R00,R50,S1,S2,S3,SESS_L_LON,SESS_L_NY] mfe=53p || 12:05→12:05 S [BB_U,R00,SESS_H_NY] mfe=42p
- `2024-10-02` Wed  range 60p net -1p  [none]  00:15→03:05 S [BB_U,SESS_H_ASIA] mfe=31p || 03:35→06:40 B [BB_L,SESS_L_ASIA] mfe=45p || 07:20→09:30 S [BB_U,P,R00,SESS_H_LON] mfe=30p || 12:50→13:10 S [BB_U] mfe=50p || 13:40→16:00 B [BB_L,R50,SESS_L_NY] mfe=32p
- `2024-10-03` Thu  range 102p net -62p  [DAY_BEFORE]  03:30→03:30 S [BB_U,R50] mfe=82p || 11:05→12:35 B [BB_L,R00,SESS_L_LON] mfe=34p || 15:00→15:00 B [BB_L,R00,SESS_L_NY] mfe=39p
- `2024-10-04` Fri  range 105p net -11p  [ON/NFP]  04:05→05:45 B [BB_L,SESS_L_ASIA] mfe=32p || 05:05→13:05 S [BB_U,P,R00,R50,SESS_H_ASIA,SESS_H_LON] mfe=105p || 09:00→14:25 B [BB_L,P,PDL,R00,R50,SESS_L_NY] mfe=50p
- `2024-10-07` Mon  range 63p net -26p  [none]  03:40→12:05 B [BB_L,P,PDL,R00,S1,S2,SESS_L_ASIA,SESS_L_LATE,SESS_L_LON,SESS_L_NY] mfe=35p || 07:20→07:35 S [BB_U,P,PDH,R00,SESS_H_LON] mfe=57p || 14:10→14:15 S [BB_U,SESS_H_NY] mfe=26p || 15:55→18:40 S [BB_U,SESS_H_LATE,SESS_H_NY] mfe=28p
- `2024-10-08` Tue  range 49p net +9p  [none]  00:00→13:15 S [BB_U,P,R00,SESS_H_ASIA,SESS_H_LATE,SESS_H_LON,SESS_H_NY] mfe=26p || 00:25→08:25 B [BB_L,P,R00,SESS_L_ASIA,SESS_L_LON,SESS_L_NY] mfe=40p
- `2024-10-09` Wed  range 41p net -30p  [DAY_BEFORE]  00:00→08:10 B [BB_L,P,PDL,R00,S1,SESS_L_ASIA,SESS_L_LON] mfe=36p || 06:00→06:35 S [BB_U,P,R00,SESS_H_ASIA] mfe=46p || 10:45→12:15 S [BB_U,P,SESS_H_LON,SESS_H_NY] mfe=26p || 15:25→16:20 S [BB_U,SESS_H_NY] mfe=27p
- `2024-10-10` Thu  range 74p net -16p  [ON/CPI_US]  00:00→13:30 B [BB_L,P,PDL,R50,S1,S2,SESS_L_ASIA,SESS_L_LON] mfe=65p || 00:25→12:00 S [BB_U,P,R1,R50,SESS_H_ASIA,SESS_H_LATE,SESS_H_LON,SESS_H_NY] mfe=74p
- `2024-10-11` Fri  range 41p net +13p  [DAY_AFTER]  00:00→07:40 B [BB_L,P,R50,SESS_L_ASIA,SESS_L_LON] mfe=40p || 03:55→09:35 S [BB_U,P,R50,SESS_H_LON] mfe=30p || 10:45→12:25 B [BB_L,P,R50,SESS_L_NY] mfe=30p
- `2024-10-15` Tue  range 67p net +22p  [DAY_BEFORE]  00:00→14:20 S [BB_U,P,PDH,R00,R1,R2,R50,SESS_H_ASIA,SESS_H_LON,SESS_H_NY] mfe=26p || 00:20→07:00 B [BB_L,P,R50,S1,SESS_L_ASIA] mfe=51p || 10:40→10:45 B [BB_L] mfe=27p || 12:25→13:00 B [BB_L,SESS_L_NY] mfe=29p
- `2024-10-16` Wed  range 97p net -90p  [ON/CPI_UK]  00:00→04:10 S [BB_U,P,SESS_H_ASIA] mfe=72p || 12:45→13:25 S [BB_U,SESS_H_NY] mfe=36p || 16:50→18:00 S [BB_U,R00] mfe=29p
- `2024-10-17` Thu  range 49p net +26p  [DAY_AFTER]  10:40→13:15 S [BB_U,P,R00,SESS_H_LATE,SESS_H_LON] mfe=43p || 12:55→14:10 B [BB_L,P,PDL,R00,SESS_L_LATE,SESS_L_NY] mfe=39p
- `2024-10-18` Fri  range 51p net +18p  [none]  00:15→07:15 S [BB_U,PDH,R1,R2,R50,SESS_H_ASIA,SESS_H_LATE,SESS_H_NY] mfe=37p || 04:50→04:55 B [BB_L,R50] mfe=53p || 12:55→16:55 B [BB_L,R50,SESS_L_NY] mfe=26p
- `2024-10-22` Tue  range 71p net -14p  [none]  00:00→07:50 S [BB_U,P,R00,SESS_H_ASIA,SESS_H_LON] mfe=38p || 06:05→14:40 B [BB_L,P,PDL,R00,R50,S1,SESS_L_LATE,SESS_L_LON,SESS_L_NY] mfe=38p || 12:30→13:05 S [BB_U] mfe=40p
- `2024-10-23` Wed  range 88p net -62p  [none]  05:40→07:00 S [BB_U,P,SESS_H_ASIA] mfe=33p || 07:10→19:15 B [BB_L,P,PDL,R50,S1,S2,SESS_L_LATE,SESS_L_LON,SESS_L_NY] mfe=27p || 09:20→09:55 S [BB_U,P] mfe=39p || 13:05→14:50 S [BB_U,R50,SESS_H_NY] mfe=40p
- `2024-10-24` Thu  range 61p net +46p  [none]  00:15→15:10 S [BB_U,P,R1,R50,SESS_H_ASIA,SESS_H_LON,SESS_H_NY] mfe=40p || 09:30→09:30 B [BB_L,R50] mfe=33p || 13:30→17:15 B [BB_L,R50,SESS_L_NY] mfe=30p
- `2024-10-25` Fri  range 43p net -7p  [none]  05:55→14:30 S [BB_U,PDH,R00,SESS_H_LON,SESS_H_NY] mfe=27p || 07:20→08:00 B [BB_L,P,SESS_L_LON] mfe=28p
- `2024-10-28` Mon  range 44p net +13p  [none]  00:00→05:15 B [BB_L,P,PDL,R50,S1,S2,SESS_L_ASIA] mfe=33p || 03:00→14:50 S [BB_U,P,PDH,R00,R1,R2,R3,R50,SESS_H_LATE,SESS_H_LON,SESS_H_NY] mfe=26p || 10:25→10:30 B [BB_L] mfe=31p
- `2024-10-30` Wed  range 107p net -48p  [none]  03:20→09:05 S [BB_U,P,PDH,R00,SESS_H_LON] mfe=65p || 09:20→12:45 B [BB_L,P,PDL,R00,R50,S1,S2,SESS_L_LATE,SESS_L_LON] mfe=107p || 12:55→14:25 S [BB_U,P,PDH,R00,R1,R50,SESS_H_NY] mfe=58p || 18:35→18:35 S [SESS_H_LATE] mfe=26p
- `2024-10-31` Thu  range 156p net -75p  [DAY_BEFORE]  00:00→07:55 S [BB_U,P,R00,R50,SESS_H_ASIA,SESS_H_LON] mfe=42p || 08:15→09:40 B [BB_L,P,SESS_L_LON] mfe=42p || 09:05→10:25 S [BB_U,P,R00,SESS_H_LON] mfe=34p || 11:15→15:50 B [BB_L,P,PDL,R00,R50,S1,S2,SESS_L_NY] mfe=45p || 11:40→13:05 S [BB_U,P,R00] mfe=154p || 14:50→14:50 S [R00] mfe=60p
- `2024-11-01` Fri  range 92p net +21p  [ON/NFP]  04:55→05:45 B [BB_L,SESS_L_ASIA] mfe=34p || 07:30→08:00 B [BB_L,P,R00,R50,SESS_L_LON] mfe=30p || 16:30→16:55 S [R50] mfe=42p
- `2024-11-04` Mon  range 59p net -35p  [none]  00:00→00:00 B [BB_L,P,PDL,R50,SESS_L_ASIA] mfe=36p || 04:35→09:20 B [BB_L,P,PDL,R50,S1,SESS_L_LON] mfe=38p || 11:00→11:05 B [BB_L,P,PDL,R50] mfe=31p || 12:50→12:50 B [BB_L,P,SESS_L_NY] mfe=34p || 16:05→17:00 B [BB_L,P,PDL,R50,S1,S2,SESS_L_LATE,SESS_L_NY] mfe=27p
- `2024-11-05` Tue  range 72p net +62p  [none]  12:50→13:45 B [BB_L,R00,SESS_L_NY] mfe=42p || 18:30→20:00 B [BB_L,SESS_L_LATE] mfe=26p || 22:45→23:25 B [BB_L,SESS_L_LATE] mfe=30p
- `2024-11-06` Wed  range 90p net +25p  [DAY_BEFORE]  00:00→00:00 S [BB_U,P,R50] mfe=150p || 00:10→14:30 B [BB_L,P,PDL,R00,R50,S1,S2,S3,SESS_L_ASIA,SESS_L_LATE,SESS_L_LON,SESS_L_NY] mfe=75p || 02:10→02:20 S [BB_U,R00,R50] mfe=90p || 07:25→09:10 S [BB_U,R00,SESS_H_LON] mfe=73p || 12:35→18:20 S [BB_U,R00,R50,SESS_H_NY] mfe=34p
- `2024-11-07` Thu  range 112p net +51p  [ON/FOMC,BoE]  00:00→07:25 S [BB_U,P,R00,R50,SESS_H_ASIA] mfe=44p || 00:20→01:20 B [BB_L,R00,SESS_L_ASIA] mfe=50p || 07:00→12:00 B [BB_L,P,R00,R50,SESS_L_LON] mfe=100p || 12:00→15:30 S [BB_U,R00,R1,R50,SESS_H_LON,SESS_H_NY] mfe=49p || 15:30→20:00 B [BB_L,R00,SESS_L_LATE] mfe=31p
- `2024-11-08` Fri  range 93p net -48p  [DAY_AFTER]  05:00→07:10 S [BB_U,P,R50,SESS_H_LON] mfe=39p || 06:10→08:10 B [BB_L,P,R50,SESS_L_ASIA,SESS_L_LON] mfe=36p || 10:35→11:35 S [BB_U,P,R50,SESS_H_LON,SESS_H_NY] mfe=49p || 12:05→17:40 B [BB_L,P,R00,R50,S1,SESS_L_LATE,SESS_L_LON,SESS_L_NY] mfe=36p || 15:45→15:55 S [BB_U] mfe=63p
- `2024-11-12` Tue  range 112p net -78p  [DAY_BEFORE]  00:00→00:00 S [BB_U,SESS_H_ASIA] mfe=26p || 00:05→17:10 B [BB_L,PDL,R00,R50,S1,S2,S3,SESS_L_ASIA,SESS_L_LON,SESS_L_NY] mfe=27p || 01:45→01:45 S [BB_U,SESS_H_ASIA] mfe=36p || 02:50→03:10 S [R50] mfe=28p || 05:20→05:45 S [BB_U] mfe=50p || 11:05→11:20 S [BB_U,SESS_H_LON] mfe=34p || 13:20→13:30 S [BB_U,R00,SESS_H_NY] mfe=81p || 16:30→16:30 S [R50] mfe=29p
- `2024-11-13` Wed  range 83p net -39p  [ON/CPI_US]  00:00→07:15 B [BB_L,R50,SESS_L_ASIA,SESS_L_LON] mfe=26p || 09:35→15:05 B [BB_L,PDL,R00,R50,SESS_L_LATE,SESS_L_NY] mfe=40p || 11:45→13:30 S [BB_U,R00,R50,SESS_H_LON,SESS_H_NY] mfe=83p
- `2024-11-14` Thu  range 91p net -28p  [DAY_AFTER]  00:00→00:00 S [BB_U,R00,SESS_H_ASIA] mfe=27p || 00:10→10:35 B [BB_L,PDL,R00,R50,S1,S2,SESS_L_ASIA,SESS_L_LATE,SESS_L_LON,SESS_L_NY] mfe=50p || 05:30→06:10 S [BB_U,SESS_H_LON] mfe=34p || 11:35→16:20 S [BB_U,P,R00,R50,SESS_H_NY] mfe=36p || 19:50→19:55 S [BB_U,R50] mfe=46p
- `2024-11-15` Fri  range 100p net -76p  [none]  00:00→11:45 S [BB_U,P,R50,SESS_H_ASIA,SESS_H_LON,SESS_H_NY] mfe=68p || 00:15→00:45 B [BB_L,SESS_L_ASIA] mfe=26p || 02:25→09:55 B [BB_L,P,R50,SESS_L_LON] mfe=48p || 12:25→20:35 B [BB_L,P,PDL,R00,R50,S1,SESS_L_LATE,SESS_L_NY] mfe=25p || 16:00→16:25 S [BB_U] mfe=29p || 18:10→18:50 S [BB_U,SESS_H_LATE] mfe=35p
- `2024-11-19` Tue  range 72p net +0p  [DAY_BEFORE]  04:25→09:30 B [BB_L,P,PDL,R50,S1,SESS_L_ASIA,SESS_L_LON,SESS_L_NY] mfe=35p || 06:20→06:50 S [BB_U,P,SESS_H_LON] mfe=67p
- `2024-11-20` Wed  range 84p net -39p  [ON/CPI_UK]  00:30→04:05 B [BB_L,SESS_L_ASIA] mfe=35p || 04:45→07:20 S [BB_U,PDH,R00,SESS_H_ASIA,SESS_H_LON] mfe=51p || 05:50→16:35 B [BB_L,P,R00,R50,S1,SESS_L_ASIA,SESS_L_LATE,SESS_L_LON,SESS_L_NY] mfe=31p || 12:00→13:50 S [BB_U,P,R50,SESS_H_NY] mfe=45p
- `2024-11-21` Thu  range 81p net -57p  [DAY_AFTER]  04:40→17:05 B [BB_L,PDL,R00,R50,S1,S2,SESS_L_ASIA,SESS_L_LATE,SESS_L_LON,SESS_L_NY] mfe=29p || 05:40→06:15 S [BB_U,R50,SESS_H_ASIA,SESS_H_LON] mfe=28p || 13:15→13:35 S [BB_U,R50,SESS_H_NY] mfe=64p || 15:05→15:05 S [BB_U,R00,R50] mfe=77p
- `2024-11-22` Fri  range 95p net -40p  [none]  00:00→10:05 B [BB_L,PDL,R00,R50,S1,S2,SESS_L_ASIA,SESS_L_LATE,SESS_L_LON,SESS_L_NY] mfe=53p || 03:10→03:25 S [BB_U,SESS_H_ASIA] mfe=30p || 06:45→08:30 S [BB_U,SESS_H_LON] mfe=95p || 13:10→15:45 S [BB_U,SESS_H_NY] mfe=30p
- `2024-11-25` Mon  range 72p net -34p  [none]  00:00→08:40 B [BB_L,P,PDL,R00,R50,S1,S2,SESS_L_ASIA,SESS_L_LON] mfe=35p || 13:00→13:55 S [BB_U,P,PDH,R00,R1,SESS_H_NY] mfe=72p || 22:20→23:05 S [BB_U] mfe=43p
- `2024-11-26` Tue  range 92p net +12p  [none]  00:00→01:00 B [BB_L,PDL,SESS_L_ASIA] mfe=51p || 01:35→12:35 S [BB_U,P,PDH,R00,R1,R50,SESS_H_ASIA,SESS_H_LON] mfe=62p || 04:10→08:10 B [BB_L,P,R50,SESS_L_LON] mfe=55p || 12:00→18:35 B [BB_L,P,PDL,R00,R50,SESS_L_NY] mfe=44p || 20:45→20:50 B [R50] mfe=25p
- `2024-11-27` Wed  range 121p net +105p  [none]  00:00→16:45 S [BB_U,PDH,R00,R1,R2,R50,SESS_H_ASIA,SESS_H_LATE,SESS_H_LON,SESS_H_NY] mfe=26p || 00:15→05:55 B [BB_L,P,SESS_L_ASIA] mfe=50p || 13:25→13:25 B [BB_L,R50,SESS_L_NY] mfe=64p
- `2024-11-29` Fri  range 78p net +21p  [none]  00:00→07:25 S [BB_U,P,PDH,R00,R1,R2,R50,SESS_H_ASIA,SESS_H_LATE,SESS_H_NY] mfe=64p || 12:20→14:10 B [BB_L,P,SESS_L_LON,SESS_L_NY] mfe=42p
- `2024-12-02` Mon  range 106p net -50p  [none]  00:00→15:45 B [BB_L,P,PDL,R00,R50,S1,S2,S3,SESS_L_ASIA,SESS_L_LATE,SESS_L_LON,SESS_L_NY] mfe=37p || 03:15→07:00 S [BB_U,P,R00,SESS_H_ASIA] mfe=30p || 08:55→11:40 S [BB_U,P,R00,SESS_H_LON] mfe=68p
- `2024-12-03` Tue  range 63p net +22p  [none]  04:30→05:10 B [BB_L,P,R50,SESS_L_ASIA] mfe=36p || 05:35→09:00 S [BB_U,P,R50,SESS_H_LON] mfe=37p || 09:40→15:25 B [BB_L,P,R50,SESS_L_LATE,SESS_L_LON,SESS_L_NY] mfe=63p || 11:00→18:20 S [BB_U,P,R00,R50,SESS_H_LATE,SESS_H_NY] mfe=34p
- `2024-12-04` Wed  range 92p net +6p  [none]  00:00→03:30 B [BB_L,P,R50,SESS_L_ASIA] mfe=43p || 04:20→06:50 S [BB_U,P,PDH,R00,R1,SESS_H_ASIA] mfe=72p || 07:20→09:00 B [BB_L,P,PDL,R00,R50,S1,SESS_L_LON,SESS_L_NY] mfe=56p || 10:55→17:25 S [BB_U,P,PDH,R00,R1,SESS_H_LATE,SESS_H_NY] mfe=35p || 18:30→19:00 B [BB_L,R00] mfe=25p
- `2024-12-05` Thu  range 57p net +36p  [DAY_BEFORE]  00:05→14:40 S [BB_U,PDH,R00,R1,R50,SESS_H_ASIA,SESS_H_LATE,SESS_H_LON,SESS_H_NY] mfe=38p || 10:35→12:25 B [BB_L,SESS_L_LON] mfe=57p || 14:00→18:30 B [BB_L,R50] mfe=28p
- `2024-12-06` Fri  range 90p net -6p  [ON/NFP]  09:30→10:15 B [BB_L,R50] mfe=29p || 10:35→13:35 S [BB_U,P,PDH,R00,R1,R50,SESS_H_LON,SESS_H_NY] mfe=83p
- `2024-12-09` Mon  range 71p net +18p  [none]  00:00→05:55 B [BB_L,P,PDL,R50,S1,S2,SESS_L_ASIA] mfe=55p || 05:45→16:00 S [BB_U,P,PDH,R00,R1,R2,R3,R50,SESS_H_LATE,SESS_H_LON,SESS_H_NY] mfe=37p || 11:45→12:45 B [BB_L,R50,SESS_L_NY] mfe=47p
- `2024-12-10` Tue  range 54p net +12p  [DAY_BEFORE]  00:00→15:25 B [BB_L,P,R50,SESS_L_ASIA,SESS_L_LON,SESS_L_NY] mfe=37p || 16:50→18:00 B [BB_L,P,R50] mfe=33p
- `2024-12-11` Wed  range 68p net -22p  [ON/CPI_US]  00:25→10:10 B [BB_L,P,PDL,R50,S1,SESS_L_ASIA,SESS_L_LATE,SESS_L_LON,SESS_L_NY] mfe=36p || 05:55→07:00 S [BB_U,P,R50] mfe=47p || 11:20→13:45 S [BB_U,P,PDH,R50,SESS_H_LATE] mfe=48p
- `2024-12-12` Thu  range 120p net -102p  [DAY_AFTER]  02:05→05:30 B [BB_L,SESS_L_ASIA] mfe=27p || 03:15→07:15 S [BB_U,PDH,SESS_H_ASIA] mfe=32p || 10:00→10:05 S [BB_U,P,R50] mfe=44p || 13:30→13:40 S [BB_U,SESS_H_NY] mfe=73p || 15:15→17:10 S [BB_U,R00] mfe=51p
- `2024-12-13` Fri  range 60p net -45p  [none]  00:00→15:50 B [BB_L,PDL,R50,S1,SESS_L_ASIA,SESS_L_LATE,SESS_L_LON,SESS_L_NY] mfe=27p || 04:50→06:00 S [BB_U] mfe=47p || 09:00→12:45 S [BB_U,R50,SESS_H_LON,SESS_H_NY] mfe=53p
- `2024-12-16` Mon  range 69p net +49p  [none]  05:50→08:10 B [BB_L,SESS_L_LON] mfe=42p || 09:55→11:00 B [BB_L,R50] mfe=25p || 14:20→14:45 B [BB_L,R50,SESS_L_NY] mfe=63p
- `2024-12-17` Tue  range 58p net +37p  [DAY_BEFORE]  00:15→06:55 B [BB_L,P,R00,SESS_L_ASIA,SESS_L_LON] mfe=41p || 11:55→14:50 B [BB_L,R00,SESS_L_NY] mfe=45p
- `2024-12-18` Wed  range 164p net -137p  [ON/FOMC,CPI_UK]  00:00→08:20 B [BB_L,P,R00,SESS_L_ASIA,SESS_L_LON] mfe=43p || 03:20→07:00 S [BB_U,P,PDH,R00,SESS_H_ASIA] mfe=46p || 09:15→11:10 S [BB_U,P,R00] mfe=37p || 12:35→13:05 S [BB_U,P,R00] mfe=37p || 12:55→20:35 B [BB_L,P,PDL,R00,R50,S2,S3,SESS_L_LATE,SESS_L_NY] mfe=28p || 17:05→18:45 S [BB_U,P,R00,SESS_H_LATE] mfe=156p
- `2024-12-19` Thu  range 166p net -95p  [ON/BoE]  02:50→04:50 B [BB_L] mfe=32p || 05:00→09:50 S [BB_U,P,R00,R50,SESS_H_ASIA,SESS_H_LON] mfe=83p || 12:25→12:45 S [P,R00,SESS_H_NY] mfe=71p || 18:35→19:00 S [BB_U,SESS_H_LATE] mfe=36p
- `2024-12-20` Fri  range 123p net +69p  [DAY_AFTER]  04:55→17:25 S [BB_U,P,R00,R1,R50,SESS_H_ASIA,SESS_H_LATE,SESS_H_LON,SESS_H_NY] mfe=26p || 13:45→15:50 B [BB_L,P,R00,R50,SESS_L_LATE] mfe=77p
- `2024-12-23` Mon  range 74p net -32p  [none]  05:40→16:20 B [BB_L,P,PDL,R50,S1,S2,S3,SESS_L_ASIA,SESS_L_LATE,SESS_L_LON,SESS_L_NY] mfe=26p || 13:15→14:40 S [BB_U,SESS_H_NY] mfe=29p
- `2024-12-24` Tue  range 56p net -2p  [none]  04:00→14:30 S [BB_U,P,R1,R50,SESS_H_ASIA,SESS_H_LON,SESS_H_NY] mfe=53p || 05:30→10:30 B [BB_L,P,R50,SESS_L_LON,SESS_L_NY] mfe=38p || 18:20→21:25 S [BB_U,P,R50,SESS_H_LATE] mfe=35p
- `2024-12-26` Thu  range 40p net -12p  [HOL/none]  11:05→15:05 B [BB_L,PDL,R00,S1,S2,SESS_L_LATE,SESS_L_LON,SESS_L_NY] mfe=30p || 13:40→13:55 S [BB_U] mfe=26p
- `2024-12-27` Fri  range 88p net +56p  [none]  00:00→08:00 S [BB_U,P,SESS_H_ASIA,SESS_H_LON] mfe=30p || 00:00→09:30 B [BB_L,P,S1,SESS_L_ASIA,SESS_L_LON] mfe=62p || 10:40→15:50 S [BB_U,P,PDH,R1,R2,R50,SESS_H_LATE,SESS_H_LON,SESS_H_NY] mfe=37p || 11:00→11:05 B [BB_L,P,R50,SESS_L_NY] mfe=52p || 15:15→15:20 B [BB_L,SESS_L_NY] mfe=39p || 17:00→17:35 B [BB_L,SESS_L_LATE,SESS_L_NY] mfe=28p
- `2024-12-30` Mon  range 101p net -40p  [none]  03:40→11:35 S [BB_U,P,PDH,R00,R1,R2,R50,SESS_H_ASIA,SESS_H_LON] mfe=66p || 07:00→08:55 B [BB_L,P,PDL,S1,SESS_L_LON] mfe=46p || 11:25→15:50 B [BB_L,P,PDL,R00,R50,S1,S2,S3,SESS_L_LATE,SESS_L_NY] mfe=50p
- `2024-12-31` Tue  range 64p net -29p  [none]  00:00→09:40 S [BB_U,P,R50,SESS_H_ASIA,SESS_H_LON] mfe=38p || 10:55→15:10 S [BB_U,P,R50,SESS_H_NY] mfe=49p
- `2025-01-02` Thu  range 182p net -151p  [none]  00:00→00:30 B [BB_L,P,PDL,S1,SESS_L_ASIA] mfe=27p || 04:35→16:00 B [BB_L,P,PDL,R00,R50,S1,S2,S3,SESS_L_LATE,SESS_L_LON,SESS_L_NY] mfe=28p || 10:55→12:00 S [R50] mfe=69p || 14:35→14:45 S [R00] mfe=52p
- `2025-01-03` Fri  range 48p net +23p  [none]  00:00→09:30 S [BB_U,R00,SESS_H_ASIA,SESS_H_LON] mfe=30p || 06:55→10:25 B [BB_L,P,R00,SESS_L_LON,SESS_L_NY] mfe=30p
- `2025-01-06` Mon  range 113p net +76p  [none]  00:00→00:35 B [BB_L,P] mfe=25p || 00:15→12:00 S [BB_U,P,PDH,R00,R1,R2,R3,R50,SESS_H_ASIA,SESS_H_LON,SESS_H_NY] mfe=83p || 10:05→11:00 B [BB_L,R00] mfe=96p || 12:55→14:15 B [BB_L,R00,SESS_L_NY] mfe=67p
- `2025-01-07` Tue  range 97p net -57p  [none]  00:15→09:05 S [BB_U,PDH,R1,R50,SESS_H_ASIA,SESS_H_LON] mfe=42p || 05:05→05:05 B [BB_L] mfe=33p || 06:55→08:25 B [BB_L,R50,SESS_L_LON] mfe=44p || 13:30→13:35 S [BB_U,P,PDH,R00,R50,SESS_H_LATE] mfe=68p
- `2025-01-08` Wed  range 169p net -127p  [none]  05:00→06:45 S [BB_U,SESS_H_ASIA] mfe=54p || 06:55→12:30 B [BB_L,PDL,R00,R50,S1,S2,S3,SESS_L_LON,SESS_L_NY] mfe=46p || 08:30→08:40 S [BB_U,R00,R50,SESS_H_NY] mfe=132p || 16:20→19:25 S [BB_U,R50,SESS_H_LATE,SESS_H_NY] mfe=26p
- `2025-01-09` Thu  range 85p net +16p  [HOL/DAY_BEFORE]  00:20→02:20 S [BB_U,R50,SESS_H_ASIA] mfe=33p || 02:35→08:00 B [BB_L,PDL,R00,R50,S1,SESS_L_ASIA,SESS_L_LATE,SESS_L_LON,SESS_L_NY] mfe=66p || 07:00→07:05 S [R00,R50] mfe=70p || 09:15→09:25 S [BB_U,R00] mfe=53p || 13:05→13:30 S [BB_U,R00,SESS_H_LATE] mfe=34p
- `2025-01-10` Fri  range 130p net -59p  [ON/NFP]  00:00→06:55 B [BB_L,P,R00,SESS_L_ASIA] mfe=41p || 07:10→13:00 S [BB_U,P,R00,R50,SESS_H_LON,SESS_H_NY] mfe=130p || 13:25→13:30 B [BB_L,PDL,R00,R50,S1,SESS_L_LATE,SESS_L_NY] mfe=71p
- `2025-01-13` Mon  range 84p net +33p  [none]  00:00→01:25 S [BB_U,P,R00,SESS_H_ASIA] mfe=70p || 00:00→09:55 B [BB_L,P,PDL,R00,R50,S1,S2,S3,SESS_L_ASIA,SESS_L_LON] mfe=35p || 05:50→08:15 S [BB_U,R50,SESS_H_LON] mfe=70p || 11:50→12:10 B [BB_L,R00,SESS_L_LON] mfe=55p || 15:00→15:35 B [BB_L,P,PDL,R00,R50,S1,S2,S3,SESS_L_LATE] mfe=44p
- `2025-01-14` Tue  range 108p net -9p  [DAY_BEFORE]  00:30→02:40 B [BB_L,P,R00,SESS_L_ASIA] mfe=26p || 04:10→05:30 B [BB_L,R00] mfe=49p || 05:30→08:20 S [BB_U,P,R00,SESS_H_LON] mfe=72p || 11:05→11:10 S [BB_U,P] mfe=55p || 11:45→13:25 B [BB_L,P,R00,R50,S1,SESS_L_LON,SESS_L_NY] mfe=74p || 13:15→16:15 S [BB_U,P,R00,R50,SESS_H_NY] mfe=45p
- `2025-01-15` Wed  range 147p net +46p  [ON/CPI_US,CPI_UK]  00:00→07:00 B [BB_L,P,R00,SESS_L_ASIA] mfe=82p || 00:50→07:55 S [BB_U,P,R00,SESS_H_ASIA,SESS_H_LON] mfe=41p || 08:55→09:20 B [P,R00] mfe=30p || 09:45→10:10 S [BB_U] mfe=30p || 11:15→12:50 B [BB_L,P,R00] mfe=105p || 13:20→13:55 S [BB_U,PDH,R00,R1,R2,R50,SESS_H_NY] mfe=113p || 15:05→16:30 B [BB_L,P,R00,R50,SESS_L_NY] mfe=37p
- `2025-01-16` Thu  range 86p net +10p  [DAY_AFTER]  00:00→00:35 S [BB_U,P,R50,SESS_H_ASIA] mfe=29p || 00:10→13:30 B [BB_L,P,R00,R50,SESS_L_ASIA,SESS_L_LATE,SESS_L_LON,SESS_L_NY] mfe=72p || 03:40→04:05 S [BB_U] mfe=31p || 06:20→17:20 S [BB_U,P,R00,R50,SESS_H_LON,SESS_H_NY] mfe=33p
- `2025-01-17` Fri  range 67p net -45p  [none]  00:15→02:30 S [BB_U,SESS_H_ASIA] mfe=28p || 04:45→04:55 S [P] mfe=63p || 06:55→06:55 S [BB_U] mfe=57p || 08:30→11:30 S [BB_U,R00,SESS_H_LON] mfe=56p || 14:45→15:05 S [BB_U,P,R00,SESS_H_NY] mfe=62p
- `2025-01-20` Mon  range 179p net +112p  [HOL/none]  00:00→20:10 S [BB_U,P,PDH,R00,R1,R2,R3,SESS_H_ASIA,SESS_H_LATE,SESS_H_LON,SESS_H_NY] mfe=28p || 01:15→01:20 B [BB_L,SESS_L_ASIA] mfe=30p || 06:00→09:35 B [BB_L,P,R00,S1,SESS_L_LON] mfe=42p || 11:20→13:30 B [BB_L,R00,R50] mfe=143p || 14:55→17:25 B [BB_L,R00,SESS_L_LATE] mfe=88p
- `2025-01-21` Tue  range 111p net +77p  [none]  00:00→00:10 S [BB_U,P,PDH,R00,SESS_H_ASIA] mfe=97p || 00:35→00:55 B [BB_L,P,R50,SESS_L_ASIA] mfe=64p || 03:30→11:30 B [BB_L,P,R00,R50,SESS_L_LON] mfe=66p || 08:45→08:55 S [BB_U,R50] mfe=33p || 19:15→19:35 B [BB_L,SESS_L_LATE] mfe=37p || 20:35→21:50 S [BB_U,PDH,R50,SESS_H_LATE] mfe=38p
- `2025-01-22` Wed  range 69p net -5p  [none]  00:10→00:55 S [BB_U,R50,SESS_H_ASIA] mfe=25p || 03:15→05:50 S [BB_U,R50] mfe=36p || 05:25→07:25 B [BB_L,P,SESS_L_ASIA,SESS_L_LON] mfe=62p || 07:15→10:30 S [BB_U,PDH,R50,SESS_H_LON] mfe=31p || 09:30→09:30 B [R50] mfe=30p
- `2025-01-23` Thu  range 82p net +45p  [none]  03:15→05:00 S [BB_U,SESS_H_ASIA] mfe=26p || 05:05→08:45 B [BB_L,PDL,R00,SESS_L_LON] mfe=37p || 06:15→10:35 S [BB_U,P,R00,SESS_H_ASIA,SESS_H_LON] mfe=31p || 11:40→12:10 B [BB_L,PDL,R00] mfe=36p || 15:00→16:10 B [BB_L,P,PDL,R00,R50,SESS_L_LATE,SESS_L_NY] mfe=76p
- `2025-01-24` Fri  range 125p net +86p  [none]  00:00→00:00 B [BB_L,R50,SESS_L_ASIA] mfe=56p || 05:15→07:40 B [BB_L,R00,SESS_L_LON] mfe=71p || 11:10→12:10 B [BB_L,R00] mfe=62p || 15:10→15:15 B [R50] mfe=51p
- `2025-01-27` Mon  range 97p net +39p  [none]  00:00→13:05 S [BB_U,P,PDH,R00,R1,R2,R3,R50,SESS_H_ASIA,SESS_H_LATE,SESS_H_LON] mfe=54p || 00:00→08:00 B [BB_L,P,PDL,R00,R50,S1,S2,S3,SESS_L_ASIA,SESS_L_LATE,SESS_L_NY] mfe=82p || 22:00→23:35 B [BB_L,P,PDL,R50,S1,S2,S3,SESS_L_LATE] mfe=29p
- `2025-01-28` Tue  range 41p net +0p  [DAY_BEFORE]  00:15→01:55 S [BB_U,P,R50,SESS_H_ASIA] mfe=31p || 05:00→06:15 S [BB_U,R50] mfe=27p || 06:10→07:45 B [BB_L,PDL,R50,SESS_L_ASIA,SESS_L_LON] mfe=30p || 08:50→09:15 S [BB_U,R50,SESS_H_LON] mfe=38p || 10:40→13:50 B [BB_L,PDL,SESS_L_LATE,SESS_L_LON,SESS_L_NY] mfe=33p || 13:15→15:35 S [BB_U,SESS_H_NY] mfe=25p
- `2025-01-29` Wed  range 70p net -18p  [ON/FOMC]  00:00→07:20 S [BB_U,P,PDH,R1,R50,SESS_H_ASIA] mfe=52p || 00:00→13:35 B [BB_L,P,PDL,R00,R50,S1,SESS_L_ASIA,SESS_L_LON,SESS_L_NY] mfe=52p || 17:05→19:35 B [BB_L,P,PDL,R50,S1,SESS_L_LATE] mfe=46p
- `2025-01-30` Thu  range 69p net -6p  [DAY_AFTER]  00:00→12:20 B [BB_L,P,R50,SESS_L_ASIA,SESS_L_LON,SESS_L_NY] mfe=52p || 05:50→08:05 S [BB_U,P,PDH,R50,SESS_H_LON] mfe=37p || 10:50→15:40 S [BB_U,P,PDH,R50,SESS_H_NY] mfe=42p || 16:15→17:15 B [BB_L,P,R50] mfe=26p || 18:10→20:30 S [BB_U,P,PDH,R50,SESS_H_LATE] mfe=57p || 20:35→20:40 B [BB_L,P,S1,SESS_L_LATE] mfe=34p
- `2025-01-31` Fri  range 86p net -30p  [none]  04:45→07:35 S [BB_U,P,SESS_H_ASIA,SESS_H_LON] mfe=39p || 07:15→09:00 B [BB_L,P,PDL,R00,SESS_L_LON] mfe=26p || 12:20→17:25 S [BB_U,P,R00,R1,R50,SESS_H_NY] mfe=86p || 13:20→19:05 B [BB_L,P,PDL,R00,R50,S1,SESS_L_LATE,SESS_L_NY] mfe=25p
- `2025-02-03` Mon  range 164p net +115p  [none]  00:00→00:10 S [P,R00,R1] mfe=60p || 00:05→04:45 B [BB_L,P,PDL,R00,R50,S1,S2,SESS_L_ASIA,SESS_L_LON] mfe=51p || 05:50→21:45 S [BB_U,P,PDH,R00,R1,R2,R3,R50,SESS_H_LATE,SESS_H_LON,SESS_H_NY] mfe=31p || 11:30→11:30 B [BB_L,P,R00] mfe=74p || 13:40→15:15 B [BB_L,R00,R50,SESS_L_LATE,SESS_L_NY] mfe=101p
- `2025-02-04` Tue  range 98p net +79p  [none]  02:45→03:10 S [BB_U] mfe=48p || 03:30→05:10 B [BB_L,P,R00,SESS_L_ASIA,SESS_L_LON] mfe=42p || 05:05→09:10 S [BB_U,R00,SESS_H_LON] mfe=41p || 10:30→12:05 B [BB_L,R00,SESS_L_LON,SESS_L_NY] mfe=72p || 15:10→15:10 B [R50] mfe=40p
- `2025-02-05` Wed  range 78p net +26p  [DAY_BEFORE]  03:45→05:40 B [BB_L,SESS_L_ASIA] mfe=43p || 06:05→10:50 S [BB_U,PDH,R00,R1,R50,SESS_H_ASIA,SESS_H_LATE,SESS_H_LON] mfe=38p || 07:30→08:35 B [R00] mfe=62p
- `2025-02-06` Thu  range 126p net -45p  [ON/BoE]  06:30→06:35 S [BB_U] mfe=62p || 08:55→09:00 S [R50] mfe=94p
- `2025-02-07` Fri  range 117p net -19p  [ON/NFP]  00:05→06:00 B [BB_L,P,SESS_L_ASIA] mfe=49p || 10:05→17:15 B [BB_L,P,R00,R50,SESS_L_LATE,SESS_L_NY] mfe=46p || 10:50→13:30 S [BB_U,P,R00,R50,SESS_H_LATE] mfe=102p
- `2025-02-10` Mon  range 59p net -43p  [none]  02:55→11:05 S [BB_U,P,PDH,R00,R1,R2,SESS_H_ASIA,SESS_H_LON,SESS_H_NY] mfe=43p || 05:05→08:35 B [BB_L,R00,SESS_L_LON] mfe=31p
- `2025-02-11` Tue  range 122p net +87p  [DAY_BEFORE]  05:45→08:05 B [BB_L,PDL,R50,S1,SESS_L_LON] mfe=46p || 10:25→10:40 B [BB_L,PDL] mfe=37p || 11:15→19:40 S [BB_U,P,PDH,R00,R1,R2,R50,SESS_H_LATE,SESS_H_LON,SESS_H_NY] mfe=25p || 12:00→12:00 B [BB_L,P,R00] mfe=55p || 18:00→19:10 B [BB_L,SESS_L_LATE] mfe=34p
- `2025-02-12` Wed  range 110p net +2p  [ON/CPI_US]  00:00→13:30 B [BB_L,P,R00,R50,S1,SESS_L_ASIA,SESS_L_LON] mfe=75p || 01:30→08:15 S [BB_U,PDH,R50,SESS_H_ASIA,SESS_H_LON] mfe=30p || 10:00→17:55 S [BB_U,P,PDH,R00,R50,SESS_H_NY] mfe=43p
- `2025-02-13` Thu  range 115p net +73p  [DAY_AFTER]  00:00→07:05 S [BB_U,PDH,R00,R1,R50,SESS_H_ASIA,SESS_H_LON] mfe=45p || 00:00→01:00 B [BB_L,R50,SESS_L_ASIA] mfe=41p || 06:40→08:55 B [BB_L,R00,SESS_L_LON] mfe=33p || 10:15→13:30 B [BB_L,R00,R50,SESS_L_LON,SESS_L_NY] mfe=88p || 17:50→18:40 B [BB_L,R00] mfe=91p || 22:05→22:05 B [BB_L,R50] mfe=27p
- `2025-02-14` Fri  range 72p net +27p  [none]  02:25→05:35 B [BB_L,R50,SESS_L_ASIA] mfe=43p || 05:40→14:45 S [BB_U,PDH,R00,R1,R50,SESS_H_LATE,SESS_H_LON,SESS_H_NY] mfe=29p || 09:55→12:10 B [BB_L,R00] mfe=58p
- `2025-02-18` Tue  range 41p net +6p  [DAY_BEFORE]  00:00→13:10 B [BB_L,P,PDL,R00,S1,SESS_L_ASIA,SESS_L_LATE,SESS_L_LON] mfe=39p || 02:35→08:30 S [BB_U,P,R00,SESS_H_LON] mfe=32p || 13:20→15:45 S [BB_U,P,R00,SESS_H_NY] mfe=28p || 22:05→22:05 B [P] mfe=27p
- `2025-02-19` Wed  range 73p net -28p  [ON/CPI_UK]  00:15→07:00 S [BB_U,P,R00,SESS_H_ASIA] mfe=34p || 06:55→17:05 B [BB_L,P,PDL,R00,S1,SESS_L_LATE,SESS_L_LON,SESS_L_NY] mfe=27p || 12:50→15:30 S [BB_U,R00,SESS_H_NY] mfe=43p
- `2025-02-20` Thu  range 82p net +80p  [DAY_AFTER]  11:15→12:55 B [BB_L,P,R00] mfe=46p || 14:45→15:00 B [BB_L] mfe=55p
- `2025-02-21` Fri  range 54p net -30p  [none]  06:10→07:00 S [BB_U,PDH,SESS_H_LON] mfe=36p || 09:20→14:45 S [BB_U,P,R50,SESS_H_NY] mfe=37p
- `2025-02-24` Mon  range 59p net -43p  [none]  00:00→00:00 B [P,R50] mfe=46p || 12:00→14:50 B [BB_L,P,PDL,S1,S2,SESS_L_LATE,SESS_L_NY] mfe=37p || 16:05→18:15 S [BB_U,P,R50,SESS_H_LATE,SESS_H_NY] mfe=33p
- `2025-02-25` Tue  range 72p net +40p  [none]  00:30→06:05 S [BB_U,P,SESS_H_ASIA,SESS_H_LON] mfe=33p || 10:05→10:10 B [BB_L] mfe=50p || 10:40→13:40 S [BB_U,P,R1,R50,SESS_H_LON,SESS_H_NY] mfe=32p || 11:40→11:40 B [P,R50,SESS_L_NY] mfe=40p || 15:00→17:20 B [BB_L,P,R50,SESS_L_LATE,SESS_L_NY] mfe=35p
- `2025-02-26` Wed  range 76p net +26p  [none]  00:00→00:35 S [BB_U,PDH,SESS_H_ASIA] mfe=28p || 00:55→05:55 B [BB_L,P,R50,SESS_L_ASIA,SESS_L_LON] mfe=29p || 06:30→17:30 S [BB_U,P,PDH,R00,R1,R50,SESS_H_LATE,SESS_H_LON,SESS_H_NY] mfe=43p
- `2025-02-27` Thu  range 84p net -51p  [none]  05:40→11:10 S [BB_U,P,SESS_H_LON,SESS_H_NY] mfe=60p || 18:40→19:00 S [BB_U,SESS_H_LATE] mfe=32p
- `2025-02-28` Fri  range 62p net +2p  [none]  00:00→01:20 S [BB_U,R00,SESS_H_ASIA] mfe=29p || 04:20→15:35 S [BB_U,R00,SESS_H_LON,SESS_H_NY] mfe=59p
- `2025-03-03` Mon  range 142p net +100p  [none]  00:05→18:45 S [BB_U,P,PDH,R00,R1,R2,R3,R50,SESS_H_ASIA,SESS_H_LATE,SESS_H_LON,SESS_H_NY] mfe=44p || 02:30→08:40 B [BB_L,P,R00,S1,SESS_L_ASIA,SESS_L_LON] mfe=77p || 11:25→11:30 B [R50] mfe=48p || 13:55→14:10 B [BB_L,SESS_L_NY] mfe=42p || 18:25→20:35 B [BB_L,R00,SESS_L_LATE] mfe=30p
- `2025-03-04` Tue  range 108p net +86p  [none]  00:00→01:30 S [BB_U,R00,SESS_H_ASIA] mfe=30p || 00:00→04:00 B [BB_L,R00,SESS_L_ASIA,SESS_L_LON] mfe=25p || 10:20→10:25 B [BB_L] mfe=49p || 12:55→15:20 B [BB_L,R00,R50,SESS_L_NY] mfe=69p || 18:25→18:25 B [R50] mfe=46p
- `2025-03-05` Wed  range 105p net +104p  [none]  00:00→01:20 S [BB_U,SESS_H_ASIA] mfe=28p || 00:05→03:00 B [BB_L,SESS_L_ASIA] mfe=30p || 06:30→06:40 B [BB_L,R00,R50,SESS_L_LON] mfe=67p || 14:30→14:30 B [R50] mfe=28p || 16:55→16:55 B [BB_L] mfe=43p
- `2025-03-06` Thu  range 58p net -22p  [DAY_BEFORE]  00:00→02:00 S [BB_U,PDH,R00,SESS_H_ASIA] mfe=25p || 01:45→10:20 B [BB_L,R00,SESS_L_ASIA,SESS_L_LON] mfe=32p || 04:35→07:45 S [BB_U,PDH,R00,SESS_H_ASIA,SESS_H_LON] mfe=58p || 11:15→15:05 S [BB_U,PDH,R00,SESS_H_NY] mfe=37p || 19:40→19:50 S [BB_U,PDH,R00,SESS_H_LATE] mfe=33p
- `2025-03-07` Fri  range 53p net +27p  [ON/NFP]  03:20→06:00 B [BB_L,P,R00] mfe=48p || 05:30→09:55 S [BB_U,P,PDH,R00,R1,SESS_H_ASIA,SESS_H_LON] mfe=42p || 10:45→14:00 B [BB_L,R00,SESS_L_NY] mfe=35p || 15:35→17:15 B [BB_L,R00,SESS_L_LATE,SESS_L_NY] mfe=31p
- `2025-03-10` Mon  range 85p net -40p  [none]  00:05→01:00 S [BB_U,P,PDH,R1,SESS_H_ASIA] mfe=36p || 05:55→06:15 S [BB_U,P,R00] mfe=49p || 09:20→13:15 S [BB_U,P,PDH,R00,R1,SESS_H_LON,SESS_H_NY] mfe=50p || 16:20→16:20 S [R00] mfe=40p
- `2025-03-11` Tue  range 75p net +56p  [DAY_BEFORE]  03:15→05:45 B [BB_L,P,R00,SESS_L_ASIA] mfe=60p || 06:20→18:45 S [BB_U,P,PDH,R00,R1,R50,SESS_H_ASIA,SESS_H_LATE,SESS_H_LON,SESS_H_NY] mfe=36p || 10:20→11:05 B [BB_L] mfe=33p || 13:50→14:25 B [BB_L,SESS_L_NY] mfe=38p || 15:55→17:00 B [BB_L,R50] mfe=32p
- `2025-03-12` Wed  range 76p net +45p  [ON/CPI_US]  02:25→07:05 B [BB_L,P,SESS_L_ASIA] mfe=32p || 03:50→12:30 S [BB_U,P,PDH,R1,R50,SESS_H_LATE,SESS_H_LON,SESS_H_NY] mfe=64p || 10:35→14:20 B [BB_L,P,R50,SESS_L_NY] mfe=58p
- `2025-03-14` Fri  range 43p net -11p  [none]  03:15→05:55 S [BB_U,P,R50,SESS_H_LON] mfe=33p || 06:25→07:50 B [BB_L,P,PDL,R50,S1,SESS_L_ASIA,SESS_L_LON] mfe=37p
- `2025-03-17` Mon  range 70p net +62p  [none]  02:50→06:55 B [BB_L,P,SESS_L_ASIA,SESS_L_LON] mfe=30p || 09:40→09:55 B [R50] mfe=27p || 11:50→12:40 B [BB_L,SESS_L_NY] mfe=36p
- `2025-03-18` Tue  range 58p net +20p  [DAY_BEFORE]  00:00→06:25 B [BB_L,P,R00,SESS_L_ASIA,SESS_L_LON] mfe=37p || 09:50→12:35 B [BB_L,P,R00,R50,SESS_L_LON,SESS_L_NY] mfe=32p
- `2025-03-19` Wed  range 56p net +25p  [ON/FOMC]  00:00→10:40 B [BB_L,P,R00,S1,SESS_L_ASIA,SESS_L_LON] mfe=25p || 04:45→05:05 S [BB_U,P,SESS_H_LON] mfe=33p || 11:30→19:10 S [BB_U,P,PDH,R00,SESS_H_LON,SESS_H_NY] mfe=29p
- `2025-03-20` Thu  range 55p net -21p  [ON/BoE]  00:15→10:20 B [BB_L,P,PDL,R00,R50,S1,S2,SESS_L_ASIA,SESS_L_LATE,SESS_L_LON,SESS_L_NY] mfe=44p || 05:40→06:10 S [P,SESS_H_LON] mfe=34p || 09:30→12:00 S [BB_U,R50,SESS_H_NY] mfe=43p
- `2025-03-21` Fri  range 68p net -23p  [DAY_AFTER]  00:00→16:00 B [BB_L,PDL,R00,R50,S1,S2,SESS_L_ASIA,SESS_L_LATE,SESS_L_LON,SESS_L_NY] mfe=42p || 03:35→03:50 S [R50] mfe=25p || 06:40→12:05 S [BB_U,R50,SESS_H_LON] mfe=32p || 13:55→14:00 S [BB_U,R00,SESS_H_NY] mfe=52p
- `2025-03-24` Mon  range 79p net -22p  [none]  00:00→10:30 S [BB_U,P,PDH,R1,R2,R3,R50,SESS_H_ASIA,SESS_H_LATE,SESS_H_LON,SESS_H_NY] mfe=46p || 01:25→04:15 B [BB_L,P,SESS_L_ASIA] mfe=38p || 07:35→09:15 B [BB_L,R50,SESS_L_LON] mfe=35p || 11:15→16:40 B [BB_L,P,R00,R50,S1,SESS_L_LATE,SESS_L_LON,SESS_L_NY] mfe=35p
- `2025-03-25` Tue  range 65p net +29p  [DAY_BEFORE]  05:30→08:15 B [BB_L,R00,SESS_L_ASIA,SESS_L_LON] mfe=50p || 08:50→17:05 S [BB_U,P,R1,R50,SESS_H_LATE,SESS_H_LON,SESS_H_NY] mfe=27p || 10:15→14:15 B [BB_L,P,R50,SESS_L_NY] mfe=34p
- `2025-03-27` Thu  range 91p net +28p  [DAY_AFTER]  00:00→06:45 S [BB_U,P,R00,R1,SESS_H_ASIA,SESS_H_LON] mfe=28p || 01:50→01:50 B [P,R00] mfe=28p || 05:35→08:05 B [BB_L,R00,SESS_L_LON] mfe=40p || 08:35→15:45 S [BB_U,PDH,R1,R2,R50,SESS_H_LATE,SESS_H_LON,SESS_H_NY] mfe=45p || 10:10→10:30 B [BB_L] mfe=56p || 12:45→14:15 B [BB_L,R50,SESS_L_NY] mfe=70p
- `2025-03-28` Fri  range 47p net -3p  [none]  02:20→12:30 B [BB_L,P,R50,SESS_L_ASIA,SESS_L_LATE,SESS_L_LON,SESS_L_NY] mfe=46p || 05:15→07:30 S [BB_U,P,R50] mfe=28p || 12:30→14:20 S [BB_U,P,R50,SESS_H_LATE,SESS_H_NY] mfe=39p
- `2025-03-31` Mon  range 86p net -38p  [none]  01:00→08:05 S [BB_U,P,PDH,R1,R2,R3,R50,SESS_H_ASIA,SESS_H_LON] mfe=49p || 08:40→17:25 B [BB_L,P,PDL,R00,R50,S1,S2,S3,SESS_L_LATE,SESS_L_LON,SESS_L_NY] mfe=30p
- `2025-04-01` Tue  range 59p net +2p  [none]  00:00→05:50 S [BB_U,P,SESS_H_ASIA,SESS_H_LON] mfe=38p || 06:05→08:40 B [BB_L,P,R00,SESS_L_ASIA,SESS_L_LON] mfe=36p || 09:15→10:55 S [BB_U,P,R00,SESS_H_LON,SESS_H_NY] mfe=53p || 11:00→14:55 B [BB_L,P,PDL,R00,S1,SESS_L_LATE,SESS_L_LON,SESS_L_NY] mfe=50p
- `2025-04-02` Wed  range 86p net +66p  [none]  04:35→08:15 B [BB_L,P,R00,SESS_L_LON] mfe=49p || 06:05→21:15 S [BB_U,P,PDH,R00,R1,R2,R3,R50,SESS_H_LATE,SESS_H_LON,SESS_H_NY] mfe=72p || 13:45→15:25 B [BB_L,R50,SESS_L_NY] mfe=48p || 21:05→21:25 B [BB_L,R00,SESS_L_LATE] mfe=66p || 23:05→23:25 B [BB_L,R00] mfe=38p
- `2025-04-03` Thu  range 128p net -9p  [DAY_BEFORE]  00:00→11:10 S [BB_U,PDH,R00,R1,R2,R3,R50,SESS_H_ASIA,SESS_H_LON,SESS_H_NY] mfe=70p || 03:05→03:05 B [R50] mfe=28p || 05:35→05:55 B [BB_L] mfe=84p || 07:15→07:20 B [R00,R50,SESS_L_LON] mfe=100p || 11:50→12:05 B [BB_L,R50] mfe=59p || 13:30→20:55 B [BB_L,R00,R50,SESS_L_LATE,SESS_L_NY] mfe=29p
- `2025-04-04` Fri  range 244p net -225p  [ON/NFP]  00:00→21:30 B [BB_L,P,PDL,R00,R50,S1,S2,SESS_L_ASIA,SESS_L_LATE,SESS_L_LON,SESS_L_NY] mfe=48p || 01:35→02:50 S [BB_U,P,R00,SESS_H_ASIA] mfe=29p || 04:35→06:25 S [BB_U,P,R00,SESS_H_ASIA] mfe=132p || 08:20→08:25 S [R00,R50] mfe=94p || 13:05→13:30 S [BB_U,R00,R50] mfe=144p || 17:25→17:35 S [R00,SESS_H_LATE] mfe=63p
- `2025-04-07` Mon  range 224p net -210p  [none]  00:15→00:50 S [BB_U,PDH,R00,R1,SESS_H_ASIA] mfe=83p || 00:45→03:45 B [BB_L,P,R00,R50,SESS_L_ASIA] mfe=69p || 04:05→08:10 S [BB_U,P,PDH,R00,R1,R50,SESS_H_LON] mfe=103p || 07:30→21:00 B [BB_L,P,PDL,R00,R50,S1,S2,S3,SESS_L_LATE,SESS_L_LON,SESS_L_NY] mfe=30p || 13:40→13:50 S [BB_U,R00,R50,SESS_H_NY] mfe=128p || 18:00→18:45 S [BB_U,R50] mfe=70p
- `2025-04-08` Tue  range 90p net -9p  [none]  00:15→03:45 S [BB_U,P,R50,SESS_H_ASIA] mfe=28p || 00:55→00:55 B [BB_L,R50] mfe=60p || 05:15→05:20 S [BB_U,P,SESS_H_ASIA] mfe=28p || 06:05→10:25 B [BB_L,P,R50,SESS_L_LON] mfe=65p || 07:00→07:40 S [BB_U,P,SESS_H_LON] mfe=72p || 10:50→13:35 S [BB_U,P,R50,SESS_H_NY] mfe=52p || 11:35→11:55 B [R50] mfe=48p || 13:20→16:15 B [BB_L,P,R50,SESS_L_NY] mfe=53p || 17:25→19:30 S [BB_U,P,R00,SESS_H_LATE] mfe=65p || 18:20→22:30 B [BB_L,P,R50,SESS_L_LATE] mfe=37p
- `2025-04-09` Wed  range 121p net -36p  [DAY_BEFORE]  00:00→00:00 B [BB_L,P,R00,SESS_L_ASIA] mfe=71p || 00:20→07:55 S [BB_U,P,PDH,R00,R1,R2,R50,SESS_H_ASIA,SESS_H_LATE,SESS_H_LON,SESS_H_NY] mfe=78p || 03:35→09:00 B [BB_L,R00,R50,SESS_L_LON] mfe=51p || 11:20→19:05 B [BB_L,P,R00,R50,SESS_L_LATE,SESS_L_LON,SESS_L_NY] mfe=94p
- `2025-04-10` Thu  range 151p net +110p  [ON/CPI_US]  00:10→00:20 B [BB_L,P,SESS_L_ASIA] mfe=37p || 00:55→01:55 S [BB_U,SESS_H_ASIA] mfe=25p || 02:35→03:10 B [BB_L,R50] mfe=40p || 03:50→19:30 S [BB_U,PDH,R00,R1,R2,R3,R50,SESS_H_ASIA,SESS_H_LATE,SESS_H_LON,SESS_H_NY] mfe=58p || 05:25→05:25 B [R50] mfe=27p || 07:05→08:30 B [BB_L,R50,SESS_L_LON] mfe=73p || 10:25→10:35 B [BB_L] mfe=96p || 13:25→14:30 B [BB_L,R00,SESS_L_NY] mfe=87p || 16:00→17:30 B [BB_L,R50] mfe=71p || 20:10→20:45 B [BB_L,R50] mfe=50p
- `2025-04-11` Fri  range 160p net +72p  [DAY_AFTER]  00:40→01:40 S [BB_U,PDH,R00,R50,SESS_H_ASIA] mfe=54p || 01:25→02:15 B [R00] mfe=53p || 06:30→10:50 S [BB_U,PDH,R00,R1,R2,R50,SESS_H_LATE,SESS_H_LON,SESS_H_NY] mfe=89p || 06:35→07:40 B [BB_L,R00,R50,SESS_L_LON] mfe=149p || 10:00→11:40 B [BB_L,R00] mfe=78p || 13:20→17:25 B [BB_L,R00,R50,SESS_L_LATE,SESS_L_NY] mfe=53p || 21:35→21:35 B [BB_L] mfe=39p
- `2025-04-14` Mon  range 87p net +64p  [none]  00:00→00:35 B [P,R00] mfe=55p || 03:35→04:40 B [BB_L,R00] mfe=72p || 07:25→07:25 B [R50] mfe=51p || 11:45→12:20 S [BB_U,R00,R3,R50,SESS_H_LON,SESS_H_NY] mfe=78p || 12:55→14:10 B [BB_L,R50,SESS_L_NY] mfe=70p || 17:00→17:55 B [BB_L] mfe=34p
- `2025-04-15` Tue  range 68p net +23p  [DAY_BEFORE]  00:00→01:35 B [BB_L,SESS_L_ASIA] mfe=34p || 02:00→11:30 S [BB_U,PDH,R00,R1,R50,SESS_H_ASIA,SESS_H_LATE,SESS_H_LON,SESS_H_NY] mfe=37p || 06:50→07:40 B [BB_L,R00,SESS_L_LON] mfe=64p || 19:10→19:15 B [BB_L,SESS_L_LATE] mfe=28p
- `2025-04-16` Wed  range 80p net -48p  [ON/CPI_UK]  00:20→00:20 B [BB_L,R50,SESS_L_ASIA] mfe=30p || 00:35→10:00 S [BB_U,PDH,R1,R50,SESS_H_ASIA,SESS_H_LON,SESS_H_NY] mfe=34p || 06:25→06:30 B [BB_L] mfe=30p || 07:40→07:45 B [BB_L,SESS_L_LON] mfe=35p || 17:45→18:30 B [BB_L,P,SESS_L_LATE] mfe=38p
- `2025-04-17` Thu  range 70p net +56p  [DAY_AFTER]  00:15→00:35 S [BB_U,SESS_H_ASIA] mfe=40p || 00:15→02:30 B [BB_L,PDL,R00,S1,SESS_L_ASIA] mfe=27p || 03:00→03:40 S [BB_U] mfe=25p || 04:40→07:05 B [BB_L,PDL,S1,SESS_L_ASIA] mfe=44p || 06:05→09:10 S [BB_U,P,R50,SESS_H_LON] mfe=28p || 10:25→13:20 B [BB_L,P,R50] mfe=54p || 13:05→15:25 S [BB_U,P,R50,SESS_H_LATE,SESS_H_NY] mfe=46p || 20:55→22:10 B [BB_L,P,R50,SESS_L_LATE] mfe=25p
- `2025-04-21` Mon  range 59p net -19p  [HOL/none]  00:10→00:25 B [R00,SESS_L_ASIA] mfe=78p || 01:35→02:35 B [R50] mfe=44p || 05:05→05:05 B [BB_L] mfe=30p || 07:15→07:30 B [BB_L] mfe=50p || 08:20→10:20 S [BB_U,R00,SESS_H_LON,SESS_H_NY] mfe=43p
- `2025-04-22` Tue  range 90p net -86p  [none]  00:00→06:25 S [BB_U,P,PDH,R00,SESS_H_ASIA] mfe=53p || 00:15→01:50 B [BB_L,P,SESS_L_ASIA] mfe=48p || 04:05→13:25 B [BB_L,P,R00,SESS_L_LON,SESS_L_NY] mfe=36p || 10:05→15:40 S [BB_U,P,SESS_H_NY] mfe=51p || 16:55→23:35 B [BB_L,P,PDL,R00,R50,S1,S2,SESS_L_LATE,SESS_L_NY] mfe=28p || 21:10→21:15 S [BB_U] mfe=106p || 22:50→22:50 S [R00,R50] mfe=68p
- `2025-04-23` Wed  range 89p net -33p  [none]  00:00→00:00 B [R50] mfe=64p || 00:35→10:20 S [BB_U,P,R00,SESS_H_ASIA,SESS_H_LON,SESS_H_NY] mfe=48p || 02:00→04:35 B [BB_L,P,R00] mfe=30p || 08:40→09:30 B [BB_L,P,R00,SESS_L_LON] mfe=59p || 11:20→17:00 B [BB_L,P,R00,R50,SESS_L_NY] mfe=27p || 15:45→15:45 S [R00] mfe=49p || 18:20→18:55 S [BB_U,SESS_H_LATE] mfe=28p || 19:20→22:05 B [BB_L,R50,SESS_L_LATE] mfe=29p || 20:30→20:30 S [BB_U] mfe=26p
- `2025-04-24` Thu  range 79p net +70p  [none]  00:15→01:15 B [BB_L,SESS_L_ASIA] mfe=28p || 02:30→06:55 B [BB_L,P] mfe=45p || 08:15→08:25 B [BB_L,P,R00,SESS_L_NY] mfe=36p || 16:15→16:45 B [BB_L,R00,SESS_L_NY] mfe=44p || 18:35→19:25 B [BB_L,SESS_L_LATE] mfe=34p
- `2025-04-25` Fri  range 58p net +41p  [none]  00:00→00:05 S [BB_U] mfe=40p || 00:05→06:50 B [BB_L,P,R00,S1,SESS_L_ASIA] mfe=40p || 01:30→04:20 S [BB_U,P,R00] mfe=44p || 14:25→14:50 B [BB_L,P,R00,SESS_L_NY] mfe=34p || 18:35→20:35 S [BB_U,P,SESS_H_LATE] mfe=28p
- `2025-04-28` Mon  range 154p net +123p  [none]  00:00→00:45 S [BB_U,P,R00,R1,SESS_H_ASIA] mfe=26p || 00:00→03:10 B [BB_L,P,PDL,R00,S1,S2,SESS_L_ASIA] mfe=38p || 07:25→07:55 B [BB_L,P,PDL,R00,S1] mfe=67p || 10:40→12:20 B [BB_L,R50,SESS_L_NY] mfe=49p || 17:10→17:20 B [R00,SESS_L_LATE] mfe=40p
- `2025-04-29` Tue  range 46p net -4p  [none]  00:00→00:05 S [BB_U,PDH] mfe=26p || 00:00→05:55 B [BB_L,R00,SESS_L_ASIA] mfe=29p || 03:10→03:10 S [BB_U,PDH,SESS_H_ASIA] mfe=48p || 06:00→09:30 S [BB_U,R00,SESS_H_LON] mfe=46p || 10:10→11:55 B [BB_L,P,R00,SESS_L_LATE,SESS_L_LON] mfe=37p || 10:50→15:00 S [BB_U,P,R00,SESS_H_LATE,SESS_H_NY] mfe=33p
- `2025-04-30` Wed  range 97p net -72p  [none]  00:00→01:05 S [BB_U,P,R00,SESS_H_ASIA] mfe=27p || 04:30→07:45 S [BB_U,R00,SESS_H_LON] mfe=43p || 07:05→15:05 B [BB_L,PDL,R00,R50,S1,S2,S3,SESS_L_LATE,SESS_L_LON,SESS_L_NY] mfe=50p || 12:15→12:40 S [BB_U,R50,SESS_H_NY] mfe=60p || 15:50→15:55 S [BB_U,R50,SESS_H_LATE] mfe=36p
- `2025-05-01` Thu  range 85p net -10p  [DAY_BEFORE]  00:00→01:20 S [BB_U,SESS_H_ASIA] mfe=26p || 00:00→08:15 B [BB_L,PDL,R00,S1,SESS_L_ASIA,SESS_L_LON] mfe=58p || 03:30→04:00 S [BB_U,R00] mfe=38p || 10:40→11:00 B [BB_L,PDL] mfe=33p || 11:15→12:40 S [BB_U,SESS_H_LON,SESS_H_NY] mfe=55p || 12:50→19:00 B [BB_L,PDL,R00,S1,SESS_L_LATE,SESS_L_NY] mfe=26p || 14:50→14:50 S [BB_U,R00] mfe=65p
- `2025-05-02` Fri  range 70p net -35p  [ON/NFP]  00:25→01:50 B [BB_L,P,R00,SESS_L_ASIA] mfe=36p || 02:15→14:50 S [BB_U,P,R00,R1,SESS_H_ASIA,SESS_H_LATE,SESS_H_LON,SESS_H_NY] mfe=55p || 07:35→13:30 B [BB_L,P,PDL,R00,SESS_L_LON] mfe=70p
- `2025-05-05` Mon  range 66p net -1p  [HOL/none]  00:00→14:05 S [BB_U,P,PDH,R00,R1,R2,R3,SESS_H_ASIA,SESS_H_LON,SESS_H_NY] mfe=66p || 00:05→00:20 B [BB_L,P,PDL,SESS_L_ASIA] mfe=36p || 04:20→08:05 B [BB_L,R00,SESS_L_LON] mfe=31p || 14:30→17:05 B [BB_L,R00,SESS_L_NY] mfe=28p
- `2025-05-06` Tue  range 117p net +90p  [DAY_BEFORE]  00:00→02:30 B [BB_L,PDL,SESS_L_ASIA] mfe=45p || 00:15→00:45 S [BB_U,P,SESS_H_ASIA] mfe=34p || 05:10→07:05 B [BB_L,P,R00,SESS_L_LON] mfe=48p || 09:55→10:25 B [BB_L] mfe=73p || 11:05→13:55 S [BB_U,PDH,R00,R1,R2,R50,SESS_H_LATE,SESS_H_LON,SESS_H_NY] mfe=46p || 12:00→12:00 B [R50] mfe=54p || 15:00→17:05 B [BB_L,R50,SESS_L_NY] mfe=27p || 19:10→19:10 B [SESS_L_LATE] mfe=27p
- `2025-05-07` Wed  range 88p net -60p  [ON/FOMC]  00:00→15:45 S [BB_U,P,R00,R50,SESS_H_ASIA,SESS_H_LATE,SESS_H_LON,SESS_H_NY] mfe=48p || 00:20→10:20 B [BB_L,P,R50,SESS_L_ASIA,SESS_L_LON] mfe=35p || 12:20→12:40 B [R50] mfe=30p
- `2025-05-08` Thu  range 109p net -77p  [ON/BoE]  00:00→00:00 B [BB_L] mfe=64p || 00:30→04:10 S [BB_U,P,R00,R1,R50,SESS_H_ASIA] mfe=54p || 01:55→02:00 B [R00] mfe=62p || 04:10→12:00 B [BB_L,P,PDL,R00,R50,S1,SESS_L_LON,SESS_L_NY] mfe=103p || 11:15→14:55 S [BB_U,P,R00,SESS_H_LON,SESS_H_NY] mfe=83p || 18:35→19:15 S [BB_U,R50] mfe=26p
- `2025-05-09` Fri  range 88p net +70p  [DAY_AFTER]  00:00→00:00 S [BB_U,R50] mfe=31p || 00:00→03:10 B [BB_L,PDL,R50,SESS_L_ASIA,SESS_L_LON] mfe=30p || 11:55→11:55 B [BB_L,P,SESS_L_NY] mfe=33p || 15:45→16:15 B [R00] mfe=29p
- `2025-05-12` Mon  range 160p net -104p  [DAY_BEFORE]  06:50→07:30 S [BB_U,P,PDH,R00,R1,SESS_H_LON] mfe=140p || 09:50→16:05 S [BB_U,R00,R50,SESS_H_NY] mfe=51p || 10:50→11:55 B [BB_L,R00,R50,SESS_L_LON] mfe=74p
- `2025-05-13` Tue  range 119p net +107p  [ON/CPI_US]  01:45→01:50 B [BB_L,SESS_L_ASIA] mfe=27p || 06:00→07:25 B [BB_L,P,R00,SESS_L_LON,SESS_L_NY] mfe=29p || 14:55→14:55 B [BB_L,R50] mfe=73p || 18:40→18:40 B [BB_L,R00,SESS_L_LATE] mfe=27p
- `2025-05-14` Wed  range 107p net -41p  [DAY_AFTER]  04:20→10:25 S [BB_U,P,PDH,R00,R1,R50,SESS_H_LATE,SESS_H_LON,SESS_H_NY] mfe=44p || 05:50→07:05 B [BB_L,R00,SESS_L_ASIA] mfe=68p
- `2025-05-15` Thu  range 56p net +33p  [none]  05:15→06:40 B [BB_L,P,R00,SESS_L_LON] mfe=43p || 07:00→07:55 S [BB_U,P,R00] mfe=42p || 11:15→15:40 B [BB_L,P,R00,SESS_L_NY] mfe=37p || 13:30→14:15 S [BB_U,P,R00,SESS_H_LATE,SESS_H_NY] mfe=56p || 17:05→17:55 B [BB_L,P,R00,SESS_L_LATE] mfe=25p
- `2025-05-16` Fri  range 82p net -50p  [none]  04:25→07:20 S [BB_U,PDH,R1,SESS_H_ASIA,SESS_H_LON] mfe=33p || 10:50→12:10 S [BB_U,P,R00,SESS_H_NY] mfe=28p || 15:25→17:20 B [BB_L,PDL,R50,S1,SESS_L_LATE,SESS_L_NY] mfe=32p
- `2025-05-19` Mon  range 109p net +60p  [none]  00:05→11:50 S [BB_U,PDH,R00,R1,R2,R3,R50,SESS_H_ASIA,SESS_H_LON] mfe=43p || 08:30→08:30 B [R50] mfe=52p || 09:35→09:40 B [R50] mfe=56p || 13:40→13:40 S [BB_U,R3,R50,SESS_H_LATE,SESS_H_NY] mfe=28p
- `2025-05-20` Tue  range 60p net +11p  [DAY_BEFORE]  00:00→01:30 B [BB_L,P,R50,SESS_L_ASIA] mfe=29p || 00:15→02:15 S [BB_U,P,R50,SESS_H_ASIA] mfe=27p || 03:55→03:55 B [BB_L,P,R50,SESS_L_ASIA] mfe=36p || 04:10→08:55 S [BB_U,SESS_H_ASIA,SESS_H_LON] mfe=41p || 05:50→05:55 B [BB_L] mfe=33p || 07:25→08:00 B [BB_L,SESS_L_LON] mfe=29p || 12:25→12:25 S [BB_U,P,R50] mfe=37p || 13:05→14:00 B [BB_L,P,R50,SESS_L_NY] mfe=39p || 17:25→17:35 B [BB_L] mfe=30p || 22:00→22:05 B [BB_L,SESS_L_LATE] mfe=26p
- `2025-05-21` Wed  range 80p net -19p  [ON/CPI_UK]  00:05→07:25 S [BB_U,PDH,R00,R1,R2,R50,SESS_H_ASIA,SESS_H_LATE,SESS_H_LON,SESS_H_NY] mfe=80p || 00:15→00:35 B [BB_L,R00,SESS_L_ASIA] mfe=35p || 06:05→10:25 B [BB_L,R00,R50,SESS_L_LON] mfe=49p || 12:30→12:40 B [BB_L,R00,SESS_L_NY] mfe=47p
- `2025-05-22` Thu  range 50p net -12p  [DAY_AFTER]  00:00→00:00 B [BB_L,P] mfe=30p || 04:45→11:45 B [BB_L,P,PDL,R00,SESS_L_LATE,SESS_L_LON,SESS_L_NY] mfe=37p || 05:45→09:10 S [BB_U,P,R00,SESS_H_LATE,SESS_H_LON,SESS_H_NY] mfe=50p
- `2025-05-23` Fri  range 96p net +78p  [none]  00:15→01:00 B [BB_L,P,SESS_L_ASIA] mfe=30p || 05:35→07:30 B [BB_L,R50,SESS_L_LON] mfe=55p || 10:55→12:50 B [BB_L,R00] mfe=60p
- `2025-05-27` Tue  range 73p net -50p  [none]  02:40→08:55 B [BB_L,P,PDL,R50,S1,SESS_L_ASIA,SESS_L_LON] mfe=28p || 05:00→05:05 S [BB_U,P,R50] mfe=37p || 10:00→14:05 S [BB_U,P,R50,SESS_H_NY] mfe=65p || 11:05→11:15 B [BB_L,PDL,R50,S1] mfe=31p
- `2025-05-28` Wed  range 70p net -16p  [none]  00:00→01:45 S [BB_U,R00,SESS_H_ASIA] mfe=46p || 02:00→06:20 B [BB_L,PDL,R00,S1,SESS_L_ASIA] mfe=46p || 06:55→11:20 S [BB_U,R00,SESS_H_LON] mfe=56p || 11:30→14:40 B [BB_L,PDL,R00,R50,S1,SESS_L_LATE,SESS_L_NY] mfe=39p || 15:00→15:45 S [BB_U,SESS_H_NY] mfe=35p
- `2025-05-29` Thu  range 79p net +60p  [none]  00:00→00:40 B [BB_L,PDL,R50,S1] mfe=32p || 00:25→00:25 S [R50] mfe=38p || 09:25→09:25 B [BB_L] mfe=30p || 11:25→12:55 B [BB_L,P,R00,SESS_L_LATE] mfe=49p || 13:10→14:05 S [BB_U,P,R00,R1,SESS_H_NY] mfe=31p
- `2025-05-30` Fri  range 51p net -6p  [none]  00:15→02:20 S [BB_U,PDH,R00,SESS_H_ASIA] mfe=43p || 01:05→15:00 B [BB_L,P,R00,R50,SESS_L_ASIA,SESS_L_LATE,SESS_L_LON,SESS_L_NY] mfe=41p || 03:50→13:45 S [BB_U,P,R00,SESS_H_LATE,SESS_H_LON] mfe=51p
- `2025-06-02` Mon  range 61p net +45p  [none]  00:00→00:00 B [P,SESS_L_ASIA] mfe=43p || 03:50→04:35 B [BB_L] mfe=58p || 06:50→06:55 B [R00] mfe=61p || 14:05→19:00 B [BB_L,R50,SESS_L_LATE,SESS_L_NY] mfe=32p || 15:05→15:45 S [BB_U,R50,SESS_H_NY] mfe=42p
- `2025-06-03` Tue  range 46p net -8p  [none]  00:00→00:45 S [BB_U,PDH,R50,SESS_H_ASIA] mfe=40p || 05:35→07:20 S [BB_U,P,SESS_H_LON] mfe=32p || 10:10→10:35 S [BB_U,P] mfe=35p || 10:40→13:10 B [BB_L,P,R00,SESS_L_LATE,SESS_L_LON,SESS_L_NY] mfe=42p
- `2025-06-04` Wed  range 75p net +36p  [none]  00:00→02:35 S [BB_U,P,SESS_H_ASIA] mfe=32p || 03:30→06:30 B [BB_L,P,R00,SESS_L_ASIA] mfe=40p || 07:15→09:40 S [BB_U,P,SESS_H_LON] mfe=29p || 10:45→13:10 B [BB_L,P] mfe=69p || 15:15→15:20 B [R50] mfe=28p
- `2025-06-05` Thu  range 72p net +30p  [DAY_BEFORE]  09:50→10:50 B [BB_L] mfe=34p || 12:35→13:15 B [BB_L] mfe=50p || 13:15→14:25 S [BB_U,PDH,R00,R1,SESS_H_LATE,SESS_H_NY] mfe=41p
- `2025-06-06` Fri  range 60p net -34p  [ON/NFP]  04:25→05:50 S [BB_U,P] mfe=42p || 05:30→14:25 B [BB_L,PDL,R50,S1,SESS_L_ASIA,SESS_L_LATE,SESS_L_LON,SESS_L_NY] mfe=41p || 07:25→07:55 S [R50] mfe=26p || 11:10→13:30 S [BB_U,R50,SESS_H_NY] mfe=56p || 15:20→15:30 S [BB_U,R50] mfe=32p
- `2025-06-09` Mon  range 57p net +0p  [none]  00:00→10:05 S [BB_U,P,PDH,R1,R2,R3,R50,SESS_H_ASIA,SESS_H_LATE,SESS_H_LON,SESS_H_NY] mfe=37p || 00:20→01:20 B [BB_L,P,R50,S1,SESS_L_ASIA] mfe=38p || 04:25→06:35 B [BB_L,R50,SESS_L_LON] mfe=28p || 10:55→14:20 B [BB_L,P,R50,S1,SESS_L_LON,SESS_L_NY] mfe=40p
- `2025-06-10` Tue  range 83p net -37p  [DAY_BEFORE]  00:00→01:20 S [BB_U,P,R50,SESS_H_ASIA] mfe=45p || 00:00→03:05 B [BB_L,P,PDL,R50,S1,SESS_L_ASIA] mfe=25p || 04:20→06:35 S [BB_U] mfe=90p || 05:25→08:10 B [BB_L,PDL,R00,S1,S2,S3,SESS_L_LATE,SESS_L_LON,SESS_L_NY] mfe=41p || 10:55→14:50 S [BB_U,R00,SESS_H_NY] mfe=34p
- `2025-06-11` Wed  range 103p net +48p  [ON/CPI_US]  00:00→00:50 S [BB_U,P,R00,SESS_H_ASIA] mfe=35p || 00:00→08:10 B [BB_L,P,R00,SESS_L_ASIA,SESS_L_LON] mfe=41p || 10:35→12:25 B [BB_L,R00] mfe=65p || 13:10→13:35 S [BB_U,R00,R50] mfe=48p || 14:25→14:45 B [P,R00] mfe=56p || 15:15→19:05 S [BB_U,PDH,R1,R50,SESS_H_LATE,SESS_H_NY] mfe=31p || 16:40→20:55 B [BB_L,R50,SESS_L_LATE] mfe=32p || 22:00→22:00 B [BB_L,R50,SESS_L_LATE] mfe=31p
- `2025-06-12` Thu  range 101p net +15p  [DAY_AFTER]  00:00→14:05 S [BB_U,P,PDH,R00,R1,R50,SESS_H_ASIA,SESS_H_LATE,SESS_H_LON,SESS_H_NY] mfe=41p || 00:45→01:20 B [SESS_L_ASIA] mfe=31p || 06:00→08:45 B [BB_L,P,R50,SESS_L_LON] mfe=64p
- `2025-06-13` Fri  range 87p net +31p  [none]  00:10→01:05 S [BB_U,PDH,R00,SESS_H_ASIA] mfe=85p || 01:10→14:10 B [BB_L,P,PDL,R00,R50,S1,SESS_L_ASIA,SESS_L_LATE,SESS_L_LON,SESS_L_NY] mfe=87p || 04:15→04:55 S [R50] mfe=33p || 06:55→08:35 S [BB_U,R50,SESS_H_LON] mfe=39p || 14:50→16:40 S [BB_U,P,R00,R50,SESS_H_NY] mfe=44p
- `2025-06-16` Mon  range 64p net +3p  [none]  00:00→04:55 B [BB_L,P,PDL,R50,S1,SESS_L_ASIA] mfe=56p || 05:25→15:05 S [BB_U,P,PDH,R00,R1,R2,R3,R50,SESS_H_ASIA,SESS_H_LON,SESS_H_NY] mfe=33p || 07:25→07:25 B [SESS_L_LON] mfe=35p
- `2025-06-17` Tue  range 155p net -143p  [DAY_BEFORE]  05:05→10:55 B [BB_L,P,R50,SESS_L_LON] mfe=32p || 10:00→13:15 S [BB_U,P,R00,R50,SESS_H_LATE] mfe=78p || 13:25→22:00 B [BB_L,PDL,R00,R50,S1,S2,S3,SESS_L_LATE,SESS_L_NY] mfe=26p
- `2025-06-18` Wed  range 76p net -35p  [ON/FOMC,CPI_UK]  00:35→08:00 S [BB_U,P,R50,SESS_H_ASIA,SESS_H_LON] mfe=28p || 05:25→05:25 B [BB_L,P,R50] mfe=40p || 10:15→19:00 S [BB_U,P,R50,SESS_H_LATE,SESS_H_NY] mfe=76p || 11:30→20:25 B [BB_L,P,PDL,R00,R50,SESS_L_LATE,SESS_L_LON,SESS_L_NY] mfe=26p
- `2025-06-19` Thu  range 88p net +74p  [HOL/ON/BoE]  06:05→07:30 B [BB_L,PDL,R00,S1,SESS_L_ASIA,SESS_L_LON] mfe=52p || 11:25→12:05 B [BB_L,P,SESS_L_NY] mfe=45p || 17:00→17:05 B [BB_L,P,R50] mfe=39p || 21:55→22:05 B [BB_L,R50] mfe=26p
- `2025-06-20` Fri  range 66p net -50p  [DAY_AFTER]  00:00→13:40 S [BB_U,PDH,R00,R1,R50,SESS_H_ASIA,SESS_H_LATE,SESS_H_LON,SESS_H_NY] mfe=58p || 05:40→08:00 B [BB_L,SESS_L_LON] mfe=35p || 11:30→15:45 B [BB_L,R00,SESS_L_NY] mfe=27p
- `2025-06-23` Mon  range 161p net +95p  [none]  00:00→08:00 S [BB_U,P,PDH,R00,R1,R50,SESS_H_ASIA,SESS_H_LON] mfe=78p || 01:05→02:25 B [BB_L,P,R00,S1,SESS_L_ASIA] mfe=35p || 04:10→05:45 B [BB_L,P,S1,SESS_L_ASIA,SESS_L_LON] mfe=43p || 09:05→10:30 B [BB_L,P,PDL,R00,S1,S2,S3,SESS_L_LON,SESS_L_NY] mfe=27p || 16:30→17:35 B [BB_L,R00] mfe=61p || 21:40→22:05 B [BB_L] mfe=37p
- `2025-06-24` Tue  range 87p net +51p  [none]  00:40→03:05 B [BB_L,R50] mfe=37p || 06:40→06:45 B [BB_L] mfe=40p || 08:30→08:30 B [BB_L,SESS_L_LON] mfe=56p || 09:10→15:25 S [BB_U,R00,R1,R50,SESS_H_LON,SESS_H_NY] mfe=38p || 10:05→10:05 B [R00] mfe=26p || 13:15→14:15 B [BB_L,R00,SESS_L_NY] mfe=57p || 16:45→18:35 S [BB_U,R1,SESS_H_LATE] mfe=26p || 16:45→17:10 B [BB_L] mfe=29p
- `2025-06-25` Wed  range 81p net +43p  [none]  06:05→08:40 S [BB_U,SESS_H_LON] mfe=30p || 07:15→13:30 B [BB_L,P,R00,SESS_L_LON,SESS_L_NY] mfe=37p || 12:00→20:25 S [BB_U,P,PDH,R00,R1,R50,SESS_H_LATE,SESS_H_NY] mfe=26p || 18:15→18:15 B [BB_L,R50,SESS_L_LATE] mfe=34p
- `2025-06-26` Thu  range 72p net +23p  [none]  00:00→17:40 S [BB_U,PDH,R00,R1,R2,R50,SESS_H_ASIA,SESS_H_LATE,SESS_H_LON,SESS_H_NY] mfe=41p || 02:05→02:25 B [BB_L] mfe=48p || 05:05→06:05 B [BB_L,R00,SESS_L_LON] mfe=55p || 09:15→12:45 B [BB_L,R00,R50,SESS_L_LON,SESS_L_NY] mfe=54p
- `2025-06-27` Fri  range 70p net -19p  [none]  00:15→04:25 S [BB_U,R50,SESS_H_ASIA] mfe=29p || 02:05→02:20 B [BB_L] mfe=26p || 04:50→06:40 B [BB_L,P,SESS_L_ASIA] mfe=30p || 07:00→09:20 S [BB_U,R50,SESS_H_LON] mfe=29p || 09:35→11:40 B [BB_L,P,SESS_L_LON] mfe=31p || 12:45→13:40 S [BB_U,P,R50,SESS_H_NY] mfe=49p || 14:25→19:30 B [BB_L,P,R00,SESS_L_LATE,SESS_L_NY] mfe=39p
- `2025-06-30` Mon  range 64p net -3p  [none]  00:00→06:35 S [BB_U,P,PDH,R00,R1,SESS_H_ASIA,SESS_H_LON] mfe=47p || 07:15→15:00 B [BB_L,P,PDL,R00,S1,S2,S3,SESS_L_LATE,SESS_L_LON,SESS_L_NY] mfe=49p
- `2025-07-01` Tue  range 86p net -7p  [none]  03:55→11:10 S [BB_U,P,PDH,R1,R2,R50,SESS_H_ASIA,SESS_H_LATE,SESS_H_LON] mfe=55p || 05:35→08:00 B [BB_L,R50,SESS_L_LON] mfe=51p || 12:00→16:30 B [BB_L,P,R00,R50,SESS_L_NY] mfe=36p
- `2025-07-02` Wed  range 178p net -101p  [DAY_BEFORE]  00:00→15:15 B [BB_L,P,PDL,R00,R50,S1,S2,S3,SESS_L_ASIA,SESS_L_LON,SESS_L_NY] mfe=82p || 09:55→12:20 S [BB_U,R00,R50] mfe=151p || 18:20→21:05 B [BB_L,R50,S2,SESS_L_LATE] mfe=38p || 21:45→22:45 S [BB_U,R50,SESS_H_LATE] mfe=30p
- `2025-07-03` Thu  range 90p net +7p  [ON/NFP]  00:00→05:00 B [BB_L,P,R50,SESS_L_ASIA,SESS_L_LON] mfe=33p || 05:55→09:20 S [BB_U,P,R50,SESS_H_LON] mfe=30p || 10:00→13:30 B [BB_L,P,R00,R50] mfe=88p || 10:40→15:00 S [BB_U,P,R00,R50,SESS_H_LATE,SESS_H_NY] mfe=41p
- `2025-07-04` Fri  range 47p net -26p  [HOL/DAY_AFTER]  00:00→07:25 S [BB_U,PDH,R50,SESS_H_ASIA,SESS_H_LON] mfe=30p || 01:55→02:55 B [BB_L,R50,SESS_L_ASIA] mfe=29p
- `2025-07-07` Mon  range 72p net -13p  [none]  00:00→01:05 S [BB_U,P,PDH,R1,R50,SESS_H_ASIA] mfe=32p || 00:00→10:10 B [BB_L,P,PDL,R00,R50,S1,S2,S3,SESS_L_ASIA,SESS_L_LATE,SESS_L_LON,SESS_L_NY] mfe=46p || 06:50→07:00 S [BB_U,R00,SESS_H_LON] mfe=47p || 10:50→15:40 S [BB_U,P,R00,R50,SESS_H_NY] mfe=59p
- `2025-07-08` Tue  range 121p net -39p  [none]  07:25→08:50 S [BB_U,P,SESS_H_LON] mfe=70p || 09:20→15:20 B [BB_L,P,PDL,R00,R50,S1,S2,SESS_L_LATE,SESS_L_LON,SESS_L_NY] mfe=64p || 13:20→20:05 S [BB_U,R00,R50,SESS_H_LATE,SESS_H_NY] mfe=31p || 20:25→22:00 B [BB_L,PDL,S1,SESS_L_LATE] mfe=28p
- `2025-07-09` Wed  range 46p net +8p  [none]  00:20→04:15 B [BB_L,P,SESS_L_ASIA] mfe=32p || 05:10→14:15 S [BB_U,P,R00,SESS_H_ASIA,SESS_H_LATE,SESS_H_LON,SESS_H_NY] mfe=39p || 06:20→12:55 B [BB_L,P,R00,SESS_L_LON] mfe=46p
- `2025-07-10` Thu  range 86p net -34p  [none]  10:10→10:50 S [BB_U,P,R00,R1] mfe=59p || 11:10→15:25 B [BB_L,P,PDL,R00,R50,S1,S2,SESS_L_LATE,SESS_L_LON,SESS_L_NY] mfe=40p || 15:05→21:40 S [BB_U,R50,SESS_H_LATE] mfe=29p || 21:55→22:00 B [BB_L,PDL,S1,SESS_L_LATE] mfe=30p
- `2025-07-11` Fri  range 80p net -64p  [none]  00:20→00:25 S [BB_U,P,R50,SESS_H_ASIA] mfe=40p || 04:20→04:55 S [BB_U,R50] mfe=34p || 06:35→06:35 S [BB_U,R50] mfe=33p || 07:00→15:15 B [BB_L,PDL,R00,R50,S1,S2,SESS_L_LATE,SESS_L_LON,SESS_L_NY] mfe=35p || 10:25→10:40 S [BB_U,R50] mfe=57p || 13:10→14:40 S [BB_U,R00,SESS_H_LATE,SESS_H_NY] mfe=39p
- `2025-07-14` Mon  range 69p net -39p  [DAY_BEFORE]  00:00→01:30 S [BB_U,P,PDH,R00,R1,R2,SESS_H_ASIA] mfe=33p || 04:50→04:50 S [BB_U,P] mfe=34p || 08:10→11:25 S [BB_U,P,PDH,R1,SESS_H_LON] mfe=26p || 14:35→14:35 S [BB_U,P,R50] mfe=58p
- `2025-07-15` Tue  range 88p net -53p  [ON/CPI_US]  02:50→13:30 S [BB_U,P,R50,SESS_H_ASIA,SESS_H_LON] mfe=82p || 15:05→15:15 S [BB_U,R00] mfe=31p
- `2025-07-16` Wed  range 121p net +20p  [ON/CPI_UK]  03:00→04:45 B [BB_L,SESS_L_ASIA] mfe=34p || 04:30→07:40 S [BB_U,P,R00,SESS_H_ASIA,SESS_H_LON] mfe=33p || 07:10→10:15 B [BB_L,P,R00,SESS_L_LON] mfe=28p || 11:40→14:45 B [BB_L,P,PDL,R00,R50,SESS_L_NY] mfe=121p || 15:50→16:30 S [BB_U,P,PDH,R00,R1,R50,SESS_H_NY] mfe=90p || 18:45→18:45 S [BB_U,R1,SESS_H_LATE] mfe=36p
- `2025-07-17` Thu  range 46p net +26p  [DAY_AFTER]  00:15→00:20 S [BB_U,SESS_H_ASIA] mfe=28p || 06:55→07:35 B [BB_L,SESS_L_LON] mfe=40p || 09:45→13:30 B [BB_L,R00,SESS_L_NY] mfe=34p || 21:30→22:00 B [BB_L,P] mfe=26p
- `2025-07-18` Fri  range 67p net -3p  [none]  04:20→07:00 B [BB_L,P,SESS_L_ASIA] mfe=32p || 07:05→14:25 S [BB_U,P,PDH,R1,R2,R50,SESS_H_LATE,SESS_H_LON,SESS_H_NY] mfe=58p || 10:35→11:10 B [BB_L,R50,SESS_L_NY] mfe=37p
- `2025-07-21` Mon  range 90p net +61p  [none]  00:00→16:20 S [BB_U,P,PDH,R00,R1,R2,R3,R50,SESS_H_ASIA,SESS_H_LON,SESS_H_NY] mfe=27p || 07:15→07:20 B [SESS_L_LON] mfe=43p || 09:50→10:35 B [BB_L,R50] mfe=38p || 13:30→14:35 B [BB_L,SESS_L_NY] mfe=44p
- `2025-07-22` Tue  range 71p net +58p  [none]  00:00→08:50 B [BB_L,P,SESS_L_ASIA,SESS_L_LON] mfe=38p || 11:30→15:05 B [BB_L,R00,SESS_L_NY] mfe=62p
- `2025-07-23` Wed  range 68p net +59p  [none]  05:55→07:20 B [BB_L,SESS_L_ASIA] mfe=33p || 09:40→14:35 B [BB_L,R50,SESS_L_NY] mfe=53p || 18:25→18:50 B [BB_L,SESS_L_LATE] mfe=27p
- `2025-07-24` Thu  range 73p net -71p  [none]  06:00→06:25 S [BB_U] mfe=25p || 08:05→08:15 S [BB_U,P,R50] mfe=28p || 14:25→15:15 S [BB_U,P,R50,SESS_H_NY] mfe=58p || 18:40→18:45 S [BB_U,SESS_H_LATE] mfe=25p
- `2025-07-25` Fri  range 87p net -65p  [none]  00:00→14:15 B [BB_L,PDL,R00,R50,S1,S2,SESS_L_ASIA,SESS_L_LATE,SESS_L_LON,SESS_L_NY] mfe=27p || 06:25→06:55 S [BB_U,R00,SESS_H_LON] mfe=45p || 12:20→13:15 S [R50] mfe=38p || 15:00→15:05 S [BB_U] mfe=26p
- `2025-07-28` Mon  range 89p net -72p  [none]  09:35→09:35 S [BB_U,SESS_H_LON] mfe=26p || 11:55→14:05 S [BB_U,P,SESS_H_LON,SESS_H_NY] mfe=56p || 16:40→16:40 S [R00] mfe=47p
- `2025-07-29` Tue  range 56p net +8p  [DAY_BEFORE]  00:15→14:15 B [BB_L,PDL,R50,S1,SESS_L_ASIA,SESS_L_LATE,SESS_L_LON,SESS_L_NY] mfe=40p || 05:55→06:35 S [BB_U,R50] mfe=38p || 09:05→11:30 S [BB_U,R50,SESS_H_LON,SESS_H_NY] mfe=54p || 15:20→20:25 S [BB_U,R50,SESS_H_LATE,SESS_H_NY] mfe=33p
- `2025-07-30` Wed  range 158p net -104p  [ON/FOMC]  02:45→07:05 B [BB_L,P,R50,SESS_L_ASIA] mfe=37p || 05:55→11:05 S [BB_U,P,PDH,R00,R1,R50,SESS_H_LON] mfe=80p || 09:20→09:20 B [BB_L] mfe=27p || 13:15→22:00 B [BB_L,P,PDL,R00,R50,S1,S2,S3,SESS_L_LATE,SESS_L_NY] mfe=29p || 18:00→19:35 S [BB_U,R00,R50,SESS_H_LATE] mfe=87p
- `2025-07-31` Thu  range 97p net -58p  [DAY_BEFORE]  00:15→07:55 S [BB_U,R50,SESS_H_ASIA,SESS_H_LON] mfe=53p || 08:20→15:05 B [BB_L,PDL,R00,R50,S1,SESS_L_LATE,SESS_L_LON,SESS_L_NY] mfe=54p || 12:35→12:55 S [BB_U] mfe=56p || 14:30→15:55 S [BB_U,R00,SESS_H_NY] mfe=37p || 17:20→17:25 S [BB_U] mfe=38p || 19:35→20:40 S [BB_U,SESS_H_LATE] mfe=29p
- `2025-08-01` Fri  range 169p net +58p  [ON/NFP]  00:00→13:30 B [BB_L,PDL,R00,R50,S1,SESS_L_ASIA,SESS_L_LON,SESS_L_NY] mfe=169p || 13:35→14:35 S [BB_U,P,PDH,R00,R1,R50,SESS_H_LATE,SESS_H_NY] mfe=66p || 15:05→18:35 B [BB_L,P,R50,SESS_L_LATE] mfe=77p
- `2025-08-04` Mon  range 66p net +1p  [none]  00:00→01:00 S [BB_U,P,PDH,R1,R2,SESS_H_ASIA] mfe=40p || 00:00→02:25 B [BB_L,P,PDL,S1,S2,S3,SESS_L_ASIA] mfe=36p || 02:45→15:35 S [BB_U,P,PDH,R00,R1,R2,R3,SESS_H_LATE,SESS_H_LON,SESS_H_NY] mfe=54p || 05:35→08:30 B [BB_L,P,PDL,R00,S1,SESS_L_LATE,SESS_L_LON,SESS_L_NY] mfe=41p
- `2025-08-05` Tue  range 56p net +21p  [none]  00:00→08:50 B [BB_L,P,R00,SESS_L_ASIA,SESS_L_LON] mfe=36p || 07:20→08:20 S [BB_U,P,SESS_H_LON] mfe=36p || 10:10→11:05 S [BB_U,P,SESS_H_LON] mfe=29p || 11:05→12:35 B [BB_L,P,R00,SESS_L_NY] mfe=29p || 13:20→17:30 S [BB_U,P,R00,SESS_H_LATE,SESS_H_NY] mfe=27p
- `2025-08-06` Wed  range 87p net +52p  [DAY_BEFORE]  06:00→09:35 B [BB_L,P,R00,SESS_L_LON] mfe=49p || 13:05→13:15 B [BB_L,SESS_L_NY] mfe=39p || 16:50→17:45 B [R50] mfe=26p
- `2025-08-07` Thu  range 81p net +73p  [ON/BoE]  08:25→09:20 B [BB_L,R00,SESS_L_LON,SESS_L_NY] mfe=69p || 18:10→19:45 B [BB_L,SESS_L_LATE] mfe=45p
- `2025-08-08` Fri  range 41p net +24p  [DAY_AFTER]  04:05→06:55 B [BB_L,SESS_L_ASIA,SESS_L_LON] mfe=26p || 09:30→09:50 B [BB_L,SESS_L_LON] mfe=26p || 10:45→10:50 S [BB_U,PDH,R50,SESS_H_LON] mfe=34p || 11:35→13:55 B [BB_L,R50,SESS_L_NY] mfe=36p
- `2025-08-11` Mon  range 77p net -41p  [DAY_BEFORE]  00:00→01:45 B [BB_L,P,R50,SESS_L_ASIA] mfe=28p || 00:25→07:05 S [BB_U,P,PDH,R1,R2,R3,R50,SESS_H_ASIA,SESS_H_LON] mfe=29p || 10:30→15:50 B [BB_L,P,PDL,R00,R50,S1,S2,S3,SESS_L_LON,SESS_L_NY] mfe=31p || 14:40→14:45 S [BB_U] mfe=27p
- `2025-08-12` Tue  range 101p net +72p  [ON/CPI_US]  00:00→10:00 S [BB_U,P,R1,R50,SESS_H_ASIA,SESS_H_LON] mfe=26p || 00:15→06:55 B [BB_L,P,R50,SESS_L_ASIA] mfe=51p || 10:45→12:30 B [BB_L,R00,R50,SESS_L_NY] mfe=64p || 11:40→16:40 S [BB_U,PDH,R00,R1,R2,R50,SESS_H_LATE,SESS_H_NY] mfe=32p
- `2025-08-13` Wed  range 78p net +66p  [DAY_AFTER]  09:10→09:10 B [R50] mfe=28p || 11:35→14:00 B [BB_L,SESS_L_NY] mfe=31p
- `2025-08-14` Thu  range 74p net -35p  [none]  00:15→09:10 B [BB_L,SESS_L_ASIA,SESS_L_LON] mfe=32p || 05:00→11:25 S [BB_U,P,PDH,R50,SESS_H_LON] mfe=54p
- `2025-08-25` Mon  range 81p net -57p  [HOL/none]  00:00→00:00 S [P] mfe=28p || 03:35→07:25 S [BB_U,P,PDH,R00,R1,SESS_H_ASIA] mfe=34p || 14:40→14:45 S [BB_U,R00] mfe=28p
- `2025-08-26` Tue  range 58p net +13p  [none]  00:00→01:45 S [BB_U,P,SESS_H_ASIA] mfe=38p || 00:00→01:00 B [BB_L,P,PDL,R50,SESS_L_ASIA] mfe=42p || 06:20→08:20 B [BB_L,PDL,R50,SESS_L_LON] mfe=47p
- `2025-08-27` Wed  range 85p net +42p  [none]  00:00→12:00 B [BB_L,P,PDL,R50,S1,SESS_L_ASIA,SESS_L_LON] mfe=39p || 05:40→07:45 S [BB_U,R50,SESS_H_LON] mfe=35p || 10:20→10:20 S [R50] mfe=33p
- `2025-08-28` Thu  range 48p net +8p  [none]  04:40→09:20 B [BB_L,R00,SESS_L_ASIA,SESS_L_LON] mfe=43p || 12:45→14:30 B [BB_L,R00,SESS_L_NY] mfe=38p
- `2025-09-02` Tue  range 193p net -131p  [none]  00:15→00:50 S [BB_U,PDH,R50,SESS_H_ASIA] mfe=25p || 00:25→13:45 B [BB_L,P,R00,R50,S1,S2,S3,SESS_L_ASIA,SESS_L_LON,SESS_L_NY] mfe=78p || 07:30→07:35 S [BB_U,P,R00,R50,SESS_H_LON] mfe=158p || 13:00→15:05 S [BB_U,R00,R50,SESS_H_NY] mfe=44p
- `2025-09-03` Wed  range 125p net +76p  [none]  00:00→05:00 B [BB_L,SESS_L_ASIA] mfe=30p || 08:10→08:20 B [BB_L,PDL,R50,SESS_L_LON] mfe=84p || 10:25→11:50 B [BB_L,P,R00,SESS_L_NY] mfe=42p || 15:50→15:50 B [BB_L,P,R50,SESS_L_LATE] mfe=33p
- `2025-09-04` Thu  range 43p net +8p  [DAY_BEFORE]  00:00→08:20 B [BB_L,R50,SESS_L_ASIA,SESS_L_LON,SESS_L_NY] mfe=43p || 05:20→10:00 S [BB_U,PDH,R50,SESS_H_LON] mfe=34p || 13:10→13:15 S [BB_U,R50] mfe=38p
- `2025-09-05` Fri  range 105p net +42p  [ON/NFP]  00:00→15:00 S [BB_U,P,PDH,R1,R2,R3,R50,SESS_H_ASIA,SESS_H_LON,SESS_H_NY] mfe=50p || 12:00→13:00 B [BB_L,R00] mfe=97p || 15:05→15:35 B [BB_L,R50] mfe=39p
- `2025-09-08` Mon  range 60p net +54p  [none]  00:00→14:35 S [BB_U,P,PDH,R00,R1,R2,R3,R50,SESS_H_ASIA,SESS_H_LATE,SESS_H_LON,SESS_H_NY] mfe=26p || 06:30→06:55 B [BB_L,R00] mfe=30p || 09:25→11:00 B [BB_L,R00] mfe=47p || 13:25→13:25 B [SESS_L_NY] mfe=28p || 17:25→18:55 B [BB_L,R50,SESS_L_LATE,SESS_L_NY] mfe=28p
- `2025-09-09` Tue  range 72p net -60p  [none]  00:00→10:35 S [BB_U,P,PDH,R1,R50,SESS_H_ASIA,SESS_H_LATE,SESS_H_LON,SESS_H_NY] mfe=43p || 07:10→07:45 B [BB_L,SESS_L_LON] mfe=32p
- `2025-09-10` Wed  range 51p net -4p  [DAY_BEFORE]  01:45→07:20 S [BB_U,P,SESS_H_ASIA] mfe=31p || 06:45→08:00 B [BB_L,PDL,SESS_L_LON] mfe=33p || 11:55→13:50 B [BB_L,P,R50,SESS_L_LATE,SESS_L_NY] mfe=38p || 13:25→13:30 S [BB_U,P,R50,SESS_H_NY] mfe=41p
- `2025-09-11` Thu  range 91p net +61p  [ON/CPI_US]  00:20→13:30 B [BB_L,P,PDL,R00,R50,S1,SESS_L_ASIA,SESS_L_LON,SESS_L_NY] mfe=87p || 07:50→07:50 S [BB_U,SESS_H_LON] mfe=28p
- `2025-09-12` Fri  range 51p net +4p  [DAY_AFTER]  00:00→00:00 S [BB_U,PDH,SESS_H_ASIA] mfe=25p || 04:35→08:20 S [BB_U,P,R50,SESS_H_LON] mfe=45p || 09:05→13:40 B [BB_L,P,R50,SESS_L_LON,SESS_L_NY] mfe=46p || 10:50→12:00 S [BB_U,P,R50] mfe=39p || 15:40→17:05 B [BB_L,P,R50,SESS_L_LATE] mfe=30p
- `2025-09-15` Mon  range 66p net +47p  [none]  00:05→13:00 S [BB_U,P,PDH,R00,R1,R2,R3,R50,SESS_H_ASIA,SESS_H_LATE,SESS_H_LON,SESS_H_NY] mfe=35p || 05:50→07:25 B [BB_L,P,SESS_L_LON] mfe=46p
- `2025-09-16` Tue  range 52p net +31p  [DAY_BEFORE]  00:00→15:15 S [BB_U,PDH,R00,R1,R2,R50,SESS_H_ASIA,SESS_H_LATE,SESS_H_LON,SESS_H_NY] mfe=33p || 00:15→01:50 B [BB_L,R00,SESS_L_ASIA] mfe=27p || 05:40→05:40 B [BB_L] mfe=31p || 11:35→12:00 B [BB_L] mfe=35p || 13:30→13:30 B [BB_L,R50,SESS_L_LATE] mfe=47p
- `2025-09-17` Wed  range 102p net -11p  [ON/FOMC,CPI_UK]  00:05→08:20 B [BB_L,P,R50,SESS_L_ASIA,SESS_L_LON,SESS_L_NY] mfe=27p || 03:25→19:05 S [BB_U,P,PDH,R00,R1,R2,R50,SESS_H_LATE,SESS_H_LON,SESS_H_NY] mfe=110p || 16:05→16:05 B [BB_L] mfe=71p
- `2025-09-18` Thu  range 127p net -49p  [ON/BoE]  00:00→00:35 S [BB_U,SESS_H_ASIA] mfe=25p || 03:20→04:00 S [BB_U] mfe=39p || 04:40→07:10 B [BB_L,PDL,R00,S1,SESS_L_ASIA] mfe=62p || 06:50→12:00 S [BB_U,P,R00,R50,SESS_H_LON] mfe=127p || 11:50→14:55 B [BB_L,PDL,R00,R50,S1,S2,SESS_L_LATE,SESS_L_NY] mfe=38p || 13:15→13:15 S [R00,R50,SESS_H_NY] mfe=89p
- `2025-09-19` Fri  range 82p net -71p  [DAY_AFTER]  00:00→00:55 S [BB_U,R50,SESS_H_ASIA] mfe=26p || 00:00→13:45 B [BB_L,PDL,R00,R50,S1,SESS_L_ASIA,SESS_L_LATE,SESS_L_LON,SESS_L_NY] mfe=35p || 04:00→05:05 S [BB_U,R00,R50,SESS_H_ASIA,SESS_H_NY] mfe=75p
- `2025-09-22` Mon  range 50p net +44p  [none]  00:05→05:30 B [BB_L,P,PDL,R00,R50,S1,S2,SESS_L_ASIA,SESS_L_LON] mfe=30p || 10:45→13:25 B [BB_L,R00,SESS_L_LATE,SESS_L_NY] mfe=26p
- `2025-09-23` Tue  range 49p net +18p  [none]  06:25→09:25 S [BB_U,P,PDH,R00,SESS_H_LON] mfe=41p || 09:30→09:35 B [BB_L,P,R00,SESS_L_LON] mfe=33p || 11:10→14:05 S [BB_U,PDH,R1,SESS_H_LATE,SESS_H_NY] mfe=30p
- `2025-09-24` Wed  range 85p net -60p  [none]  00:35→14:30 B [BB_L,P,PDL,R00,R50,S1,S2,S3,SESS_L_ASIA,SESS_L_LATE,SESS_L_LON,SESS_L_NY] mfe=31p || 05:25→06:00 S [BB_U,R00] mfe=34p || 10:05→10:05 S [BB_U] mfe=32p || 13:15→13:20 S [BB_U,R50] mfe=44p
- `2025-09-25` Thu  range 143p net -118p  [none]  07:15→07:50 S [BB_U,P,R50,SESS_H_LON] mfe=33p || 16:00→17:10 S [BB_U,R50] mfe=34p
- `2025-09-26` Fri  range 70p net +54p  [none]  00:10→01:05 B [BB_L,SESS_L_ASIA] mfe=26p || 03:30→08:25 B [BB_L,R50,SESS_L_LON] mfe=26p || 10:25→11:55 B [BB_L,R50,SESS_L_LON] mfe=45p || 14:20→14:30 B [BB_L,P,R00,SESS_L_LATE] mfe=38p
- `2025-09-29` Mon  range 41p net -6p  [none]  00:00→13:55 S [BB_U,PDH,R1,R2,R3,R50,SESS_H_ASIA,SESS_H_LATE,SESS_H_LON,SESS_H_NY] mfe=41p || 00:20→00:20 B [SESS_L_ASIA] mfe=26p
- `2025-09-30` Tue  range 54p net +16p  [none]  00:00→09:50 S [BB_U,P,R50,SESS_H_ASIA,SESS_H_LON] mfe=27p || 06:55→14:25 B [BB_L,P,R50,SESS_L_LATE,SESS_L_LON,SESS_L_NY] mfe=54p || 12:10→15:50 S [BB_U,P,PDH,R1,R50,SESS_H_LATE,SESS_H_NY] mfe=31p
- `2025-10-01` Wed  range 74p net +24p  [none]  00:00→03:35 B [BB_L,P,R50,SESS_L_ASIA] mfe=37p || 00:05→14:35 S [BB_U,P,PDH,R00,R1,R2,R3,R50,SESS_H_ASIA,SESS_H_LATE,SESS_H_LON,SESS_H_NY] mfe=62p || 08:25→08:30 B [BB_L,SESS_L_LON] mfe=27p || 10:20→11:30 B [BB_L] mfe=67p || 13:10→13:10 B [BB_L,R00] mfe=58p
- `2025-10-02` Thu  range 109p net -32p  [DAY_BEFORE]  02:20→09:55 S [BB_U,P,R00,SESS_H_ASIA,SESS_H_LON] mfe=39p || 09:30→16:40 B [BB_L,P,PDL,R00,R50,S1,SESS_L_LATE,SESS_L_LON,SESS_L_NY] mfe=47p
- `2025-10-03` Fri  range 56p net +50p  [ON/NFP]  00:10→07:00 B [BB_L,P,R50,SESS_L_ASIA,SESS_L_NY] mfe=38p || 15:40→15:40 B [BB_L] mfe=28p
- `2025-10-06` Mon  range 74p net +38p  [none]  00:00→08:35 S [BB_U,P,PDH,R1,R2,R50,SESS_H_ASIA,SESS_H_LON] mfe=46p || 00:20→12:00 B [BB_L,P,PDL,R50,S1,SESS_L_ASIA,SESS_L_LON] mfe=50p
- `2025-10-07` Tue  range 68p net -39p  [none]  00:05→12:50 B [BB_L,P,PDL,R00,R50,S1,SESS_L_ASIA,SESS_L_LON] mfe=36p || 03:30→04:20 S [BB_U,P,R50] mfe=36p || 09:50→11:05 S [BB_U] mfe=52p
- `2025-10-08` Wed  range 68p net +8p  [none]  00:00→00:50 S [BB_U,SESS_H_ASIA] mfe=34p || 00:00→07:15 B [BB_L,PDL,R00,S1,SESS_L_ASIA,SESS_L_LON] mfe=42p || 07:00→09:20 S [BB_U,R00,SESS_H_LON] mfe=26p || 09:55→10:55 B [BB_L,R00] mfe=27p || 11:15→11:45 S [BB_U,SESS_H_LON] mfe=26p || 12:25→12:35 B [BB_L,R00,SESS_L_NY] mfe=38p || 13:25→15:30 S [BB_U,P,R00,SESS_H_NY] mfe=66p || 15:30→19:10 B [BB_L,P,PDL,R00,S1,SESS_L_LATE,SESS_L_NY] mfe=35p
- `2025-10-09` Thu  range 127p net -109p  [none]  05:25→09:35 B [BB_L,P,PDL,R00,R50,S1,SESS_L_LON] mfe=47p || 09:05→10:40 S [BB_U,R50] mfe=29p || 11:50→19:50 B [BB_L,PDL,R00,R50,S1,S2,S3,SESS_L_LATE,SESS_L_NY] mfe=26p || 13:25→14:05 S [BB_U,SESS_H_NY] mfe=104p || 16:30→17:00 S [BB_U,R00,SESS_H_LATE] mfe=35p
- `2025-10-10` Fri  range 110p net +43p  [none]  00:00→06:25 S [BB_U,R00,SESS_H_ASIA,SESS_H_LON] mfe=35p || 05:10→11:55 B [BB_L,P,PDL,R00,R50,SESS_L_LON,SESS_L_NY] mfe=26p || 15:05→16:05 S [BB_U,R00,R50,SESS_H_LATE,SESS_H_NY] mfe=39p
- `2025-10-13` Mon  range 51p net -17p  [none]  00:00→09:35 B [BB_L,P,PDL,R50,S1,S2,SESS_L_ASIA,SESS_L_LON] mfe=38p || 00:10→07:20 S [BB_U,P,PDH,R1,R2,R50,SESS_H_ASIA,SESS_H_LON] mfe=51p || 10:40→12:00 S [BB_U,P,PDH,R1,R50,SESS_H_NY] mfe=28p
- `2025-10-14` Tue  range 92p net -15p  [DAY_BEFORE]  00:00→13:45 B [BB_L,P,PDL,R00,R50,S1,S2,S3,SESS_L_ASIA,SESS_L_LON,SESS_L_NY] mfe=55p || 00:15→05:55 S [BB_U,P,R00,R50,SESS_H_ASIA] mfe=100p || 09:45→09:55 S [BB_U] mfe=26p
- `2025-10-15` Wed  range 68p net +41p  [ON/CPI_US]  00:15→16:45 S [BB_U,PDH,R00,R1,R50,SESS_H_ASIA,SESS_H_NY] mfe=33p || 03:55→10:05 B [BB_L,R50,SESS_L_LON] mfe=31p || 12:45→14:25 B [BB_L,R50,SESS_L_NY] mfe=68p || 17:50→19:05 B [BB_L,SESS_L_LATE] mfe=38p
- `2025-10-16` Thu  range 51p net +17p  [DAY_AFTER]  00:00→01:00 B [BB_L,R00,SESS_L_ASIA] mfe=42p || 00:15→14:15 S [BB_U,PDH,R1,R50,SESS_H_ASIA,SESS_H_LON,SESS_H_NY] mfe=43p || 04:00→07:50 B [BB_L,SESS_L_LON] mfe=39p || 10:35→12:30 B [BB_L] mfe=33p || 16:40→17:35 B [BB_L,SESS_L_NY] mfe=33p
- `2025-10-17` Fri  range 81p net -31p  [none]  00:15→03:05 B [BB_L,P,R50,SESS_L_ASIA] mfe=26p || 03:35→07:15 S [BB_U,P,PDH,R1,R50,SESS_H_ASIA,SESS_H_LON] mfe=61p || 07:20→16:00 B [BB_L,P,PDL,R00,R50,S1,SESS_L_LON,SESS_L_NY] mfe=40p || 09:40→12:05 S [BB_U,P] mfe=45p || 18:55→19:00 B [BB_L,P] mfe=25p
- `2025-10-20` Mon  range 40p net -34p  [none]  04:40→12:30 B [BB_L,P,PDL,R00,S1,S2,S3,SESS_L_LATE,SESS_L_LON,SESS_L_NY] mfe=30p || 13:15→13:55 S [BB_U,P,PDH,R1,SESS_H_NY] mfe=28p || 15:25→16:50 S [BB_U,P,PDH,SESS_H_NY] mfe=27p
- `2025-10-21` Tue  range 37p net -3p  [DAY_BEFORE]  00:15→01:50 S [BB_U,P,R00,SESS_H_ASIA] mfe=27p || 02:25→14:45 B [BB_L,PDL,R00,S1,S2,SESS_L_ASIA,SESS_L_LATE,SESS_L_LON,SESS_L_NY] mfe=37p || 10:30→10:30 S [BB_U] mfe=26p || 12:15→12:15 S [BB_U,SESS_H_LON] mfe=34p || 13:55→17:00 S [BB_U,R00,SESS_H_NY] mfe=33p
- `2025-10-22` Wed  range 79p net -27p  [ON/CPI_UK]  00:00→06:50 S [BB_U,P,R50,SESS_H_ASIA] mfe=74p || 04:15→11:30 B [BB_L,P,PDL,R50,S1,S2,SESS_L_LON,SESS_L_NY] mfe=35p
- `2025-10-23` Thu  range 49p net -24p  [DAY_AFTER]  00:00→05:00 B [BB_L,P,R50,SESS_L_ASIA] mfe=28p || 13:30→13:50 S [BB_U,P,R50,SESS_H_NY] mfe=39p
- `2025-10-24` Fri  range 85p net -6p  [none]  05:35→09:20 B [BB_L,P,PDL,R00,S1,SESS_L_ASIA,SESS_L_LON] mfe=26p || 07:00→07:35 S [BB_U,P,SESS_H_LON] mfe=33p || 13:15→13:30 S [BB_U,P,PDH,R00,R1,R50,SESS_H_LATE,SESS_H_NY] mfe=78p
- `2025-10-27` Mon  range 42p net +11p  [none]  00:00→07:20 B [BB_L,P,PDL,S1,S2,SESS_L_ASIA,SESS_L_LON] mfe=40p || 05:30→11:55 S [BB_U,P,PDH,R1,R2,R3,R50,SESS_H_ASIA,SESS_H_LATE,SESS_H_LON] mfe=28p
- `2025-10-28` Tue  range 105p net -83p  [DAY_BEFORE]  00:10→05:05 S [BB_U,P,PDH,R1,R50,SESS_H_ASIA,SESS_H_LON] mfe=41p || 05:40→13:45 B [BB_L,P,PDL,R00,R50,S1,S2,S3,SESS_L_LATE,SESS_L_LON] mfe=39p || 10:10→10:45 S [BB_U] mfe=81p || 12:20→12:20 S [R00] mfe=58p
- `2025-10-29` Wed  range 107p net -33p  [ON/FOMC]  00:30→18:40 B [BB_L,PDL,R00,R50,S1,S2,SESS_L_ASIA,SESS_L_LON,SESS_L_NY] mfe=61p || 05:10→05:10 S [R50] mfe=36p || 09:45→09:50 S [BB_U] mfe=32p || 11:05→15:55 S [BB_U,R00,R50,SESS_H_NY] mfe=107p
- `2025-10-30` Thu  range 96p net -53p  [DAY_AFTER]  00:15→05:00 S [BB_U,P,R00,SESS_H_ASIA,SESS_H_LON] mfe=26p || 05:55→13:10 B [BB_L,P,PDL,R00,R50,S1,SESS_L_LATE,SESS_L_LON] mfe=64p || 11:30→11:35 S [BB_U] mfe=74p || 13:25→14:25 S [BB_U,R50,SESS_H_NY] mfe=44p
- `2025-10-31` Fri  range 54p net +8p  [none]  00:30→07:10 B [BB_L,R50,SESS_L_ASIA] mfe=26p || 04:00→04:55 S [BB_U,R50,SESS_H_LON] mfe=32p || 08:50→13:45 B [BB_L,PDL,R00,S1,SESS_L_LON,SESS_L_NY] mfe=46p
- `2025-11-03` Mon  range 54p net -7p  [none]  00:00→06:30 S [BB_U,P,PDH,R1,R2,R50,SESS_H_ASIA,SESS_H_LON] mfe=32p || 03:30→14:45 B [BB_L,P,PDL,S1,S2,S3,SESS_L_LON,SESS_L_NY] mfe=54p || 15:05→17:15 S [BB_U,P,PDH,R1,R2,R3,R50,SESS_H_NY] mfe=28p
- `2025-11-04` Tue  range 129p net -105p  [none]  06:20→07:25 S [BB_U,P] mfe=80p || 13:15→13:20 S [BB_U,R50,SESS_H_NY] mfe=33p
- `2025-11-05` Wed  range 42p net +22p  [DAY_BEFORE]  00:15→09:05 S [BB_U,R50,SESS_H_ASIA,SESS_H_LON] mfe=42p || 05:55→07:20 B [BB_L,SESS_L_LON] mfe=34p || 09:40→11:10 B [BB_L,PDL,SESS_L_LON] mfe=35p || 11:55→13:05 S [BB_U] mfe=33p || 13:30→15:00 B [BB_L,SESS_L_NY] mfe=36p
- `2025-11-06` Thu  range 89p net +81p  [ON/BoE]  04:30→06:55 B [BB_L,R50,SESS_L_ASIA] mfe=37p || 10:30→12:05 B [BB_L] mfe=66p || 13:25→15:00 B [R00,SESS_L_NY] mfe=44p
- `2025-11-07` Fri  range 80p net +50p  [ON/NFP]  00:25→09:40 B [BB_L,P,R00,SESS_L_ASIA,SESS_L_LON] mfe=34p || 12:45→12:55 B [BB_L,P] mfe=65p || 15:40→15:55 B [R50] mfe=30p
- `2025-11-10` Mon  range 50p net +40p  [none]  00:00→13:20 S [BB_U,P,PDH,R1,R2,R3,R50,SESS_H_ASIA,SESS_H_LATE,SESS_H_LON] mfe=46p || 10:00→11:05 B [BB_L,R50] mfe=39p || 13:25→15:55 B [BB_L,P,R50,SESS_L_NY] mfe=39p
- `2025-11-11` Tue  range 68p net +7p  [none]  00:00→09:05 B [BB_L,P,PDL,R50,S1,SESS_L_ASIA,SESS_L_LATE,SESS_L_LON] mfe=36p || 09:30→14:45 S [BB_U,P,R50,SESS_H_LATE,SESS_H_LON,SESS_H_NY] mfe=26p
- `2025-11-12` Wed  range 71p net -11p  [DAY_BEFORE]  05:20→08:05 S [BB_U,P,R50,SESS_H_LON] mfe=45p || 06:15→10:25 B [BB_L,P,PDL,R50,S1,SESS_L_ASIA,SESS_L_LON] mfe=29p || 11:20→12:00 S [BB_U] mfe=55p || 12:30→14:25 B [BB_L,PDL,R00,S1,S2,SESS_L_LON,SESS_L_NY] mfe=55p
- `2025-11-13` Thu  range 115p net +64p  [ON/CPI_US]  00:00→07:05 B [BB_L,P,R00,SESS_L_ASIA] mfe=70p || 00:15→17:50 S [BB_U,P,PDH,R00,R1,R2,R50,SESS_H_ASIA,SESS_H_LATE,SESS_H_LON,SESS_H_NY] mfe=29p || 10:40→11:50 B [BB_L,R50] mfe=41p
- `2025-11-14` Fri  range 93p net +23p  [DAY_AFTER]  00:00→08:40 S [BB_U,P,R50,SESS_H_ASIA,SESS_H_LON] mfe=78p || 02:30→08:20 B [BB_L,P,R50,SESS_L_LON] mfe=93p || 12:10→12:55 S [BB_U,P,R50] mfe=56p || 12:30→15:40 B [BB_L,P,R50,SESS_L_NY] mfe=38p || 14:10→14:20 S [BB_U,P,R50,SESS_H_LATE,SESS_H_NY] mfe=53p
- `2025-11-17` Mon  range 48p net +6p  [none]  00:00→06:05 B [BB_L,P,PDL,R50,S1,SESS_L_ASIA] mfe=45p || 04:15→12:45 S [BB_U,P,PDH,R1,R2,R50,SESS_H_LON,SESS_H_NY] mfe=32p || 08:50→11:00 B [BB_L,P,R50,SESS_L_LON] mfe=44p
- `2025-11-18` Tue  range 43p net -3p  [DAY_BEFORE]  00:00→13:10 B [BB_L,P,PDL,R50,SESS_L_ASIA,SESS_L_LATE,SESS_L_LON,SESS_L_NY] mfe=37p || 00:05→08:10 S [BB_U,P,R50,SESS_H_ASIA,SESS_H_LON] mfe=34p || 12:05→15:30 S [BB_U,P,R50,SESS_H_NY] mfe=36p
- `2025-11-19` Wed  range 111p net -101p  [ON/CPI_UK]  03:15→06:55 S [BB_U,P,R50,SESS_H_ASIA,SESS_H_LON] mfe=37p || 13:15→13:20 S [BB_U] mfe=58p || 18:30→18:45 S [BB_U,R50,SESS_H_LATE] mfe=33p
- `2025-11-20` Thu  range 74p net +7p  [DAY_AFTER]  01:10→10:15 S [BB_U,P,R50,SESS_H_ASIA,SESS_H_LON] mfe=29p || 05:35→06:00 B [BB_L,R50] mfe=27p || 08:05→08:05 B [BB_L,SESS_L_LON] mfe=25p || 11:00→13:30 B [BB_L,P,R00,R50,SESS_L_LON,SESS_L_NY] mfe=74p || 13:15→14:30 S [BB_U,P,R00,SESS_H_NY] mfe=53p
- `2025-11-21` Fri  range 71p net +14p  [none]  00:00→08:45 S [BB_U,P,R00,SESS_H_ASIA,SESS_H_LON] mfe=52p || 05:55→12:20 B [BB_L,P,PDL,R00,R50,S1,SESS_L_LATE,SESS_L_LON,SESS_L_NY] mfe=61p
- `2025-11-24` Mon  range 38p net +9p  [none]  00:00→15:50 B [BB_L,P,PDL,R00,S1,S2,S3,SESS_L_ASIA,SESS_L_LATE,SESS_L_LON,SESS_L_NY] mfe=29p || 01:30→13:30 S [BB_U,P,PDH,R00,R1,R2,R3,SESS_H_ASIA,SESS_H_LATE,SESS_H_LON,SESS_H_NY] mfe=38p
- `2025-11-25` Tue  range 110p net +58p  [none]  02:25→05:30 B [BB_L,P,R00,SESS_L_ASIA] mfe=33p || 02:55→20:00 S [BB_U,P,PDH,R00,R1,R2,R3,R50,SESS_H_ASIA,SESS_H_LATE,SESS_H_LON,SESS_H_NY] mfe=61p || 08:40→09:00 B [BB_L] mfe=32p || 11:00→12:05 B [BB_L] mfe=75p
- `2025-11-26` Wed  range 118p net +46p  [none]  00:00→00:00 B [BB_L,P] mfe=36p || 04:25→12:10 B [BB_L,P,R00,R50,SESS_L_LON] mfe=101p || 05:45→06:25 S [BB_U,R00,SESS_H_ASIA] mfe=33p || 08:40→08:40 S [BB_U] mfe=37p || 14:55→14:55 B [R00] mfe=40p
- `2025-11-27` Thu  range 45p net -6p  [HOL/none]  00:00→05:35 S [BB_U,PDH,R50,SESS_H_ASIA] mfe=48p || 14:20→14:40 B [BB_L,SESS_L_NY] mfe=26p
- `2025-11-28` Fri  range 54p net +26p  [none]  00:00→12:00 B [BB_L,P,PDL,R00,S1,SESS_L_ASIA,SESS_L_LON,SESS_L_NY] mfe=30p || 09:10→09:40 S [BB_U,SESS_H_LON] mfe=27p || 11:30→15:55 S [BB_U,P,R50,SESS_H_LATE,SESS_H_NY] mfe=28p || 15:10→15:35 B [BB_L,P,PDL,R50,S1,SESS_L_NY] mfe=48p
- `2025-12-01` Mon  range 70p net -3p  [none]  04:45→08:35 B [BB_L,P,PDL,R50,S1,SESS_L_ASIA,SESS_L_LON] mfe=31p || 07:15→07:45 S [BB_U,P,SESS_H_LON] mfe=31p || 11:20→13:05 S [BB_U,P,PDH,R1,R2,R50,SESS_H_LON,SESS_H_NY] mfe=46p
- `2025-12-02` Tue  range 41p net -1p  [none]  04:55→17:10 B [BB_L,PDL,R00,S1,SESS_L_LATE,SESS_L_LON,SESS_L_NY] mfe=35p || 06:50→09:15 S [BB_U,R00,SESS_H_LON,SESS_H_NY] mfe=40p
- `2025-12-03` Wed  range 116p net +105p  [none]  07:20→08:25 B [BB_L,R50,SESS_L_LON] mfe=56p || 12:40→14:15 B [BB_L,R00,SESS_L_NY] mfe=55p
- `2025-12-04` Thu  range 64p net -9p  [DAY_BEFORE]  04:30→15:40 S [BB_U,PDH,R50,SESS_H_LATE,SESS_H_LON,SESS_H_NY] mfe=49p || 06:10→07:30 B [BB_L,R50,SESS_L_LON] mfe=27p || 10:40→13:30 B [BB_L,R50,SESS_L_NY] mfe=64p
- `2025-12-05` Fri  range 46p net -16p  [ON/NFP]  00:00→07:35 S [BB_U,P,R1,R50,SESS_H_ASIA,SESS_H_LON] mfe=30p || 02:20→03:35 B [BB_L] mfe=26p || 11:55→14:05 S [BB_U,P,R1,R50,SESS_H_NY] mfe=46p
- `2025-12-08` Mon  range 33p net -6p  [none]  00:00→06:00 S [BB_U,P,PDH,R1,R2,SESS_H_ASIA,SESS_H_LON] mfe=27p || 12:40→14:25 S [BB_U,P,PDH,R1,R2,SESS_H_NY] mfe=33p
- `2025-12-09` Tue  range 69p net -31p  [DAY_BEFORE]  00:00→15:10 B [BB_L,P,PDL,R00,R50,S1,S2,SESS_L_ASIA,SESS_L_LATE,SESS_L_LON,SESS_L_NY] mfe=32p || 03:15→09:20 S [BB_U,P,PDH,R1,R50,SESS_H_ASIA,SESS_H_LON] mfe=35p || 12:05→13:20 S [P] mfe=40p || 15:15→16:35 S [BB_U,R00] mfe=27p
- `2025-12-10` Wed  range 87p net +71p  [ON/CPI_US,FOMC]  07:35→11:45 B [BB_L,P,R00,SESS_L_LON] mfe=31p || 15:15→15:50 B [BB_L,P] mfe=33p || 18:35→19:00 B [BB_L,R50,SESS_L_LATE] mfe=62p
- `2025-12-11` Thu  range 84p net +24p  [DAY_AFTER]  06:40→16:00 S [BB_U,P,PDH,R00,R1,SESS_H_LATE,SESS_H_LON,SESS_H_NY] mfe=30p || 08:00→09:35 B [BB_L,P,SESS_L_LON] mfe=39p || 13:35→13:35 B [R00,SESS_L_NY] mfe=51p
- `2025-12-12` Fri  range 52p net -28p  [none]  00:15→16:40 B [BB_L,P,PDL,R50,S1,SESS_L_ASIA,SESS_L_LON,SESS_L_NY] mfe=35p || 11:50→13:05 S [BB_U,SESS_H_NY] mfe=31p
- `2025-12-16` Tue  range 94p net +60p  [DAY_BEFORE]  03:15→06:20 B [BB_L,P,PDL,R00,S1,SESS_L_ASIA,SESS_L_LON] mfe=47p || 06:55→13:30 S [BB_U,P,PDH,R00,R1,R2,R3,R50,SESS_H_LATE,SESS_H_LON,SESS_H_NY] mfe=52p || 15:15→15:25 B [BB_L,SESS_L_NY] mfe=37p || 17:50→19:25 B [BB_L,R00,SESS_L_LATE] mfe=36p
- `2025-12-17` Wed  range 95p net +3p  [ON/CPI_UK]  00:05→08:05 B [BB_L,P,PDL,R00,R50,S2,SESS_L_ASIA,SESS_L_LON] mfe=26p || 07:05→07:10 S [R50] mfe=40p || 09:05→16:00 S [BB_U,R00,R50,SESS_H_NY] mfe=33p || 09:45→10:20 B [BB_L] mfe=34p || 11:35→11:45 B [BB_L,PDL,R50,S1] mfe=44p
- `2025-12-18` Thu  range 106p net +11p  [ON/BoE]  00:00→09:25 B [BB_L,P,R50,SESS_L_ASIA,SESS_L_LON] mfe=54p || 04:40→14:05 S [BB_U,P,PDH,R00,R1,R50,SESS_H_LON,SESS_H_NY] mfe=72p
- `2025-12-19` Fri  range 37p net -9p  [DAY_AFTER]  10:35→13:20 B [BB_L] mfe=30p || 12:30→14:15 S [BB_U,SESS_H_NY] mfe=30p || 15:10→15:25 B [BB_L,SESS_L_NY] mfe=33p
- `2025-12-22` Mon  range 84p net +64p  [none]  05:15→06:35 B [BB_L,R00,SESS_L_LON] mfe=32p || 09:15→09:20 B [BB_L] mfe=32p || 11:35→12:35 B [BB_L,R50,SESS_L_NY] mfe=32p
- `2025-12-23` Tue  range 48p net +18p  [none]  05:50→06:55 B [BB_L,R00] mfe=39p || 17:10→17:55 B [BB_L,SESS_L_NY] mfe=30p
- `2025-12-24` Wed  range 36p net -21p  [none]  00:00→00:30 B [BB_L,SESS_L_ASIA] mfe=27p || 07:05→08:20 B [BB_L,P,R00,SESS_L_LON] mfe=26p
- `2025-12-25` Thu  range 22p net -15p  [HOL/none]  00:15→00:30 B [BB_L,P,PDL,R00,SESS_L_ASIA] mfe=27p || 05:40→07:00 S [BB_U,P,R1,SESS_H_ASIA,SESS_H_LATE] mfe=27p
- `2025-12-26` Fri  range 50p net +13p  [HOL/none]  10:25→13:45 S [BB_U,P,PDH,R00,R1,SESS_H_LON] mfe=45p || 15:05→15:10 S [BB_U,P,PDH,R00,R1,SESS_H_NY] mfe=44p
- `2025-12-30` Tue  range 81p net -52p  [none]  06:25→07:35 B [BB_L,P,R00,SESS_L_LON] mfe=30p || 08:25→10:40 S [BB_U,PDH,R1,SESS_H_LON] mfe=43p || 11:25→15:30 B [BB_L,P,PDL,R00,R50,S1,S2,SESS_L_LATE,SESS_L_LON,SESS_L_NY] mfe=34p || 12:50→12:50 S [P,R00,SESS_H_NY] mfe=51p
- `2025-12-31` Wed  range 80p net +23p  [none]  00:00→09:00 B [BB_L,PDL,R50,S1,SESS_L_ASIA,SESS_L_LON] mfe=34p || 10:30→13:20 S [BB_U,R50,SESS_H_LON,SESS_H_NY] mfe=75p || 13:25→15:15 B [BB_L,PDL,R00,R50,S1,S2,SESS_L_LATE,SESS_L_NY] mfe=58p
- `2026-01-02` Fri  range 66p net +16p  [none]  00:00→00:20 S [PDH,SESS_H_ASIA] mfe=29p || 00:00→06:25 B [BB_L,PDL,R50,SESS_L_ASIA,SESS_L_LON] mfe=32p || 04:20→10:55 S [BB_U,PDH,R00,R50,SESS_H_LON] mfe=56p
- `2026-01-05` Mon  range 123p net +87p  [none]  00:00→03:10 B [BB_L,P,PDL,R50,S1,SESS_L_ASIA,SESS_L_LON] mfe=48p || 11:00→11:00 B [R00] mfe=39p || 15:45→19:40 B [BB_L,SESS_L_LATE] mfe=34p
- `2026-01-06` Tue  range 43p net -15p  [none]  00:00→02:05 S [BB_U,PDH,R50,SESS_H_ASIA] mfe=38p || 08:05→09:05 S [BB_U,P,R00,SESS_H_LATE,SESS_H_LON,SESS_H_NY] mfe=43p
- `2026-01-07` Wed  range 49p net -44p  [none]  00:20→01:50 S [BB_U,R00,SESS_H_ASIA] mfe=32p || 08:40→10:00 S [BB_U,R00,SESS_H_LON] mfe=33p
- `2026-01-08` Thu  range 32p net -16p  [DAY_BEFORE]  00:00→08:50 B [BB_L,PDL,R50,S1,SESS_L_ASIA,SESS_L_LATE,SESS_L_LON,SESS_L_NY] mfe=31p || 00:35→01:55 S [BB_U,R50,SESS_H_ASIA] mfe=30p || 05:05→06:05 S [BB_U,R50,SESS_H_LON] mfe=35p
- `2026-01-09` Fri  range 58p net -10p  [ON/NFP]  00:00→10:15 B [BB_L,P,PDL,R00,S1,SESS_L_ASIA,SESS_L_LON,SESS_L_NY] mfe=30p || 01:50→01:50 S [BB_U] mfe=28p || 03:00→03:00 S [BB_U] mfe=30p || 06:10→08:40 S [BB_U,P,R50,SESS_H_LON] mfe=58p
- `2026-01-12` Mon  range 30p net +11p  [none]  03:05→03:25 B [R50] mfe=29p || 04:50→05:20 B [BB_L,R50] mfe=33p
- `2026-01-13` Tue  range 75p net -50p  [DAY_BEFORE]  06:55→08:30 S [BB_U,P,PDH,R50,SESS_H_LON] mfe=69p || 09:40→20:25 B [BB_L,P,R50,S1,SESS_L_LATE,SESS_L_LON,SESS_L_NY] mfe=28p
- `2026-01-15` Thu  range 58p net -38p  [DAY_AFTER]  00:05→04:35 S [BB_U,P,SESS_H_ASIA] mfe=32p || 03:40→09:40 B [BB_L,P,PDL,R00,S1,S2,S3,SESS_L_ASIA,SESS_L_LATE,SESS_L_LON,SESS_L_NY] mfe=31p || 08:05→08:10 S [R00] mfe=40p
- `2026-01-19` Mon  range 30p net +15p  [HOL/none]  00:25→02:45 B [BB_L,P,R00,SESS_L_ASIA] mfe=31p || 12:50→19:40 B [BB_L,SESS_L_NY] mfe=30p
- `2026-01-20` Tue  range 54p net -11p  [DAY_BEFORE]  00:00→03:10 S [BB_U,PDH,R1,R2,R50,SESS_H_ASIA,SESS_H_LATE,SESS_H_LON,SESS_H_NY] mfe=28p || 00:45→02:00 B [BB_L,SESS_L_ASIA] mfe=66p || 04:15→07:55 B [BB_L,R50,SESS_L_LON] mfe=40p || 13:30→15:00 B [BB_L,R50,SESS_L_NY] mfe=26p
- `2026-01-21` Wed  range 58p net +21p  [ON/CPI_UK]  00:00→02:25 S [BB_U,R50,SESS_H_ASIA] mfe=43p || 00:15→06:15 B [BB_L,PDL,R00,S1,SESS_L_ASIA] mfe=43p || 06:25→10:00 S [BB_U,P,R50,SESS_H_LON] mfe=43p || 12:20→12:25 S [BB_U,SESS_H_NY] mfe=28p
- `2026-01-22` Thu  range 100p net +77p  [DAY_AFTER]  00:00→03:35 B [BB_L,P,SESS_L_ASIA] mfe=43p || 06:05→06:15 B [BB_L,P,PDL,R00,R50,SESS_L_ASIA,SESS_L_LON] mfe=40p || 12:05→12:05 B [BB_L] mfe=29p
- `2026-01-23` Fri  range 128p net +117p  [none]  00:15→03:30 B [BB_L,R00,SESS_L_ASIA] mfe=54p || 08:50→09:00 B [BB_L,R50,SESS_L_LON] mfe=77p || 12:35→13:15 B [R00] mfe=51p
- `2026-01-26` Mon  range 70p net +14p  [none]  00:05→03:25 B [BB_L,PDL,R50,SESS_L_ASIA] mfe=34p || 00:15→11:00 S [BB_U,PDH,R00,R1,R50,SESS_H_ASIA,SESS_H_LON,SESS_H_NY] mfe=31p || 05:50→08:05 B [BB_L,PDL,R50,SESS_L_LON] mfe=70p || 16:10→20:00 B [BB_L,SESS_L_LATE,SESS_L_NY] mfe=30p || 17:30→21:40 S [BB_U,PDH,R00,R1,SESS_H_LATE] mfe=28p
- `2026-01-27` Tue  range 161p net +89p  [DAY_BEFORE]  00:15→03:40 B [BB_L,P,SESS_L_ASIA] mfe=45p || 00:20→01:40 S [BB_U,P,SESS_H_ASIA] mfe=26p || 04:25→10:20 S [BB_U,P,PDH,R00,R1,R2,R50,SESS_H_ASIA,SESS_H_LON] mfe=44p || 05:00→05:05 B [P,R00] mfe=65p || 08:50→08:50 B [BB_L] mfe=65p || 10:50→10:55 B [R50] mfe=44p || 13:35→14:20 B [BB_L,SESS_L_NY] mfe=95p || 14:40→15:45 S [BB_U,R3,R50,SESS_H_NY] mfe=47p
- `2026-01-28` Wed  range 85p net +34p  [ON/FOMC]  00:00→02:15 S [BB_U,P,R00,SESS_H_ASIA] mfe=56p || 00:00→00:10 B [BB_L,R00] mfe=42p || 02:30→10:15 B [BB_L,P,R00,R50,SESS_L_ASIA,SESS_L_LON,SESS_L_NY] mfe=44p || 15:55→16:00 B [BB_L,R00] mfe=33p || 18:10→19:35 S [BB_U,SESS_H_LATE] mfe=42p || 20:00→21:05 B [BB_L,R00,SESS_L_LATE] mfe=47p
- `2026-01-29` Thu  range 92p net -33p  [DAY_AFTER]  00:00→02:00 S [BB_U,PDH,R1,R50,SESS_H_ASIA] mfe=48p || 00:15→06:00 B [BB_L,P,R00,SESS_L_ASIA] mfe=38p || 05:20→09:40 S [BB_U,P,PDH,R00,R50,SESS_H_LATE,SESS_H_LON,SESS_H_NY] mfe=92p || 10:05→10:45 B [BB_L,P,PDL,R00,R50,S1,SESS_L_LON] mfe=65p || 12:05→21:20 B [BB_L,P,PDL,R00,R50,S1,SESS_L_LATE,SESS_L_NY] mfe=36p
- `2026-01-30` Fri  range 108p net -94p  [none]  00:15→07:00 S [BB_U,P,R50,SESS_H_ASIA,SESS_H_LON] mfe=68p || 04:05→04:50 B [BB_L,PDL,R50,SESS_L_ASIA] mfe=62p || 13:15→14:10 S [R00,SESS_H_NY] mfe=39p
- `2026-02-02` Mon  range 84p net -14p  [none]  00:00→00:50 B [BB_L,PDL,SESS_L_ASIA] mfe=41p || 01:55→05:15 S [BB_U,P,PDH,R00,SESS_H_ASIA] mfe=48p || 05:35→11:00 B [BB_L,PDL,R00,R50,S1,SESS_L_LON,SESS_L_NY] mfe=40p
- `2026-02-03` Tue  range 59p net +56p  [none]  00:20→02:40 S [BB_U,R00,SESS_H_ASIA] mfe=46p || 01:30→06:55 B [BB_L,P,R00,R50,SESS_L_ASIA] mfe=39p || 07:05→12:20 S [BB_U,P,R00,SESS_H_LON] mfe=34p || 11:00→14:05 B [BB_L,P,R00] mfe=29p
- `2026-02-04` Wed  range 87p net -61p  [DAY_BEFORE]  00:00→04:10 S [BB_U,P,PDH,R00,R1,R50,SESS_H_ASIA,SESS_H_LATE,SESS_H_LON,SESS_H_NY] mfe=38p || 04:25→05:25 B [BB_L,R00,SESS_L_ASIA] mfe=34p
- `2026-02-05` Thu  range 105p net -73p  [ON/BoE]  00:00→19:15 B [BB_L,PDL,R00,R50,S1,S2,SESS_L_ASIA,SESS_L_LATE,SESS_L_LON,SESS_L_NY] mfe=42p || 02:00→03:05 S [BB_U,SESS_H_ASIA] mfe=76p || 05:40→06:55 S [BB_U,R00,R50] mfe=82p || 08:35→08:35 S [BB_U,R50] mfe=77p || 17:40→17:50 S [BB_U] mfe=28p
- `2026-02-06` Fri  range 42p net +26p  [ON/NFP]  02:10→03:50 B [BB_L,P,SESS_L_ASIA] mfe=34p || 08:00→08:50 B [BB_L,R00,SESS_L_LON,SESS_L_NY] mfe=34p
- `2026-02-09` Mon  range 80p net +47p  [none]  00:00→17:00 S [BB_U,P,PDH,R00,R1,R2,R50,SESS_H_ASIA,SESS_H_LATE,SESS_H_LON,SESS_H_NY] mfe=29p || 01:20→03:30 B [BB_L,P,PDL,R00,SESS_L_ASIA] mfe=37p || 07:50→09:05 B [BB_L,R50,SESS_L_LON] mfe=70p || 13:20→13:20 B [BB_L,SESS_L_NY] mfe=36p
- `2026-02-10` Tue  range 65p net -19p  [DAY_BEFORE]  02:10→04:10 S [BB_U,SESS_H_ASIA] mfe=26p || 04:40→05:30 B [BB_L,P,SESS_L_ASIA] mfe=35p || 06:30→09:30 S [BB_U,P,R50,SESS_H_LON,SESS_H_NY] mfe=43p || 10:00→19:00 B [BB_L,P,R50,SESS_L_LATE,SESS_L_LON,SESS_L_NY] mfe=30p
- `2026-02-11` Wed  range 83p net -51p  [ON/CPI_US]  02:00→02:10 B [BB_L,P] mfe=35p || 02:25→05:55 S [BB_U,PDH,R00,R1,SESS_H_ASIA] mfe=103p || 05:15→08:30 B [BB_L,P,PDL,R00,R50,S1,SESS_L_LATE,SESS_L_LON,SESS_L_NY] mfe=61p || 08:25→08:25 S [BB_U,P,R1,R50,SESS_H_LON] mfe=81p
- `2026-02-12` Thu  range 67p net -32p  [DAY_AFTER]  00:00→01:35 B [BB_L,PDL,SESS_L_ASIA] mfe=49p || 04:25→07:55 B [BB_L,P,R50,SESS_L_LON] mfe=50p || 08:35→10:15 S [BB_U,P,R50,SESS_H_LON] mfe=65p
- `2026-02-13` Fri  range 60p net +53p  [none]  00:00→02:10 B [BB_L,PDL,R00,S1,SESS_L_ASIA] mfe=39p || 01:30→04:50 S [BB_U,P,R00,SESS_H_ASIA] mfe=31p || 05:05→07:10 B [BB_L,P,PDL,R00,R50,SESS_L_LON,SESS_L_NY] mfe=48p
- `2026-02-17` Tue  range 77p net -6p  [DAY_BEFORE]  00:00→01:25 S [BB_U,SESS_H_ASIA] mfe=63p || 00:00→10:50 B [BB_L,PDL,R00,R50,S1,S2,S3,SESS_L_ASIA,SESS_L_LATE,SESS_L_LON,SESS_L_NY] mfe=65p || 03:40→05:35 S [BB_U,R00] mfe=74p || 07:50→07:50 S [R50] mfe=57p
- `2026-02-19` Thu  range 40p net -19p  [DAY_AFTER]  00:00→00:15 B [BB_L,PDL,R00] mfe=34p || 00:15→04:10 S [BB_U,R00,SESS_H_ASIA] mfe=57p || 03:55→09:25 B [BB_L,PDL,R00,R50,S1,SESS_L_ASIA,SESS_L_LATE,SESS_L_LON,SESS_L_NY] mfe=40p || 07:25→07:30 S [SESS_H_LON] mfe=40p || 08:50→10:45 S [BB_U,R50,SESS_H_LON,SESS_H_NY] mfe=35p || 19:55→19:55 S [BB_U,R50] mfe=29p
- `2026-02-20` Fri  range 54p net +8p  [none]  00:00→00:05 B [BB_L,SESS_L_ASIA] mfe=30p || 00:15→10:30 S [BB_U,P,PDH,R00,R1,R50,SESS_H_ASIA,SESS_H_LON] mfe=40p || 02:50→03:10 B [BB_L,P,PDL,R00,R50,SESS_L_ASIA,SESS_L_LON,SESS_L_NY] mfe=47p || 13:20→13:45 S [BB_U,R00,R1,SESS_H_NY] mfe=25p
- `2026-02-23` Mon  range 49p net -0p  [none]  00:00→01:50 S [BB_U,PDH,R00,R1,SESS_H_ASIA,SESS_H_LON,SESS_H_NY] mfe=29p || 02:30→07:25 B [BB_L,P,PDL,R00,SESS_L_ASIA,SESS_L_LON] mfe=49p
- `2026-02-24` Tue  range 60p net +16p  [none]  02:05→03:05 B [BB_L,PDL,S1,SESS_L_ASIA] mfe=36p || 03:20→05:35 S [BB_U,P,R00,SESS_H_ASIA] mfe=28p || 04:35→08:50 B [BB_L,P,PDL,R00,SESS_L_LON] mfe=60p || 07:55→11:25 S [BB_U,P,PDH,R00,R1,SESS_H_LON] mfe=34p || 13:20→13:25 S [SESS_H_NY] mfe=27p
- `2026-02-25` Wed  range 70p net +68p  [none]  00:00→03:00 S [BB_U,PDH,R1,SESS_H_ASIA] mfe=28p || 02:15→06:30 B [BB_L,P,R00,SESS_L_ASIA] mfe=44p || 04:55→05:05 S [BB_U] mfe=30p || 06:35→08:15 S [BB_U,P,PDH,R00,R1,SESS_H_LON] mfe=29p || 09:00→09:00 B [BB_L] mfe=50p || 10:00→21:00 S [BB_U,PDH,R1,R2,R50,SESS_H_LATE,SESS_H_LON,SESS_H_NY] mfe=25p
- `2026-02-26` Thu  range 111p net -52p  [none]  00:10→01:15 S [BB_U,P,R50,SESS_H_ASIA] mfe=42p || 00:20→04:20 B [BB_L,P,R50,SESS_L_ASIA] mfe=26p || 04:40→08:20 S [BB_U,P,R50,SESS_H_LON] mfe=59p || 06:10→13:00 B [BB_L,P,PDL,R00,R50,S1,S2,SESS_L_LATE,SESS_L_LON] mfe=48p || 11:50→12:00 S [BB_U,R00,R50,SESS_H_NY] mfe=58p
- `2026-02-27` Fri  range 51p net +16p  [none]  00:00→01:55 B [BB_L,SESS_L_ASIA] mfe=41p || 02:45→03:05 S [BB_U,P,R00,SESS_H_ASIA] mfe=40p || 04:25→08:50 B [BB_L,PDL,R50,SESS_L_LON,SESS_L_NY] mfe=37p || 06:35→06:35 S [BB_U,SESS_H_LON] mfe=42p
- `2026-03-02` Mon  range 119p net +20p  [none]  00:00→08:35 B [BB_L,PDL,R00,R50,S1,S2,S3,SESS_L_ASIA,SESS_L_LATE,SESS_L_LON,SESS_L_NY] mfe=101p || 00:35→03:25 S [BB_U,PDH,R50,SESS_H_ASIA] mfe=74p || 06:20→06:20 S [R00] mfe=88p || 08:45→11:45 S [BB_U,R00,R50,SESS_H_LON,SESS_H_NY] mfe=52p || 18:35→19:45 S [BB_U,R00,SESS_H_LATE] mfe=46p
- `2026-03-03` Tue  range 117p net +0p  [none]  00:00→00:35 B [BB_L,R00,SESS_L_ASIA] mfe=28p || 00:40→01:25 S [BB_U,P,R00,SESS_H_ASIA] mfe=34p || 02:00→15:20 B [BB_L,P,PDL,R00,R50,S1,S2,SESS_L_ASIA,SESS_L_LON,SESS_L_NY] mfe=90p || 07:25→07:45 S [R50] mfe=70p || 11:50→12:20 S [BB_U,R00] mfe=75p || 22:00→22:00 S [BB_U,SESS_H_LATE] mfe=26p
- `2026-03-04` Wed  range 71p net +43p  [none]  00:00→01:30 B [BB_L,P,R00,R50,SESS_L_ASIA] mfe=39p || 00:10→00:15 S [P] mfe=44p || 02:40→04:05 S [BB_U,P] mfe=37p || 03:30→06:00 B [BB_L,SESS_L_ASIA] mfe=72p || 06:25→10:05 S [BB_U,P,R00,R50] mfe=52p || 07:15→09:00 B [BB_L,P,R50,SESS_L_LON] mfe=71p || 11:20→11:25 S [BB_U,R00,SESS_H_LON] mfe=55p || 11:25→12:55 B [BB_L,R00,R50] mfe=38p || 14:15→14:20 S [BB_U,SESS_H_NY] mfe=35p || 14:35→17:30 B [BB_L,R50,SESS_L_LATE,SESS_L_NY] mfe=32p
- `2026-03-05` Thu  range 80p net +24p  [DAY_BEFORE]  00:15→01:25 S [BB_U,SESS_H_ASIA] mfe=57p || 01:40→06:10 B [BB_L,P,PDL,R50,S1,SESS_L_ASIA] mfe=72p || 03:20→03:20 S [R50] mfe=45p || 07:40→16:25 B [BB_L,P,PDL,R00,R50,S1,SESS_L_LON,SESS_L_NY] mfe=43p || 09:05→09:05 S [BB_U,P,R50,SESS_H_LON] mfe=45p || 19:25→19:55 B [BB_L,P,R50,SESS_L_LATE] mfe=48p || 20:05→22:05 S [BB_U,P,R50,SESS_H_LATE] mfe=29p
- `2026-03-06` Fri  range 99p net +23p  [ON/NFP]  03:05→06:05 B [BB_L,R50,SESS_L_ASIA] mfe=28p || 06:40→08:40 S [BB_U,P,R50,SESS_H_LON] mfe=62p || 11:05→12:20 B [BB_L,P,R00,R50,SESS_L_LATE,SESS_L_LON,SESS_L_NY] mfe=80p || 20:20→20:35 B [BB_L,R00,SESS_L_LATE] mfe=42p
- `2026-03-09` Mon  range 146p net +127p  [none]  00:00→01:50 B [BB_L,P,PDL,R00,R50,S1,SESS_L_ASIA,SESS_L_LON,SESS_L_NY] mfe=28p || 00:30→06:10 S [BB_U,R00,SESS_H_ASIA] mfe=39p || 16:05→17:15 B [BB_L,R00] mfe=64p || 18:20→22:00 S [BB_U,R00,R1,R50,SESS_H_LATE] mfe=31p || 18:40→19:00 B [BB_L,SESS_L_LATE] mfe=68p
- `2026-03-10` Tue  range 72p net -33p  [DAY_BEFORE]  00:00→00:10 B [BB_L] mfe=27p || 00:15→00:40 S [BB_U,SESS_H_ASIA] mfe=27p || 01:30→03:50 B [BB_L,SESS_L_ASIA] mfe=45p || 04:30→08:00 S [BB_U,PDH,R1,R50,SESS_H_ASIA,SESS_H_LON,SESS_H_NY] mfe=46p || 06:40→06:50 B [R50] mfe=38p || 08:50→12:30 B [BB_L,R50,SESS_L_LON,SESS_L_NY] mfe=41p
- `2026-03-11` Wed  range 59p net -37p  [ON/CPI_US]  00:00→04:50 S [BB_U,P,R50,SESS_H_ASIA] mfe=29p || 01:20→12:50 B [BB_L,P,PDL,R00,R50,SESS_L_LON,SESS_L_NY] mfe=50p || 10:15→11:00 S [BB_U,P,R00,R50,SESS_H_LATE,SESS_H_LON] mfe=56p || 15:15→15:45 B [BB_L,PDL,R00,SESS_L_NY] mfe=25p || 21:40→22:00 S [BB_U,R00] mfe=42p
- `2026-03-12` Thu  range 72p net -38p  [DAY_AFTER]  00:00→00:15 B [BB_L,PDL] mfe=28p || 00:30→01:35 S [BB_U,R00,SESS_H_ASIA] mfe=33p || 02:20→04:55 B [BB_L,PDL,SESS_L_ASIA,SESS_L_LON] mfe=32p || 04:00→08:00 S [BB_U,R00,SESS_H_LON] mfe=28p || 09:40→11:45 S [BB_U,P,R00,SESS_H_LON] mfe=60p || 15:05→16:20 S [BB_U,R50,SESS_H_LATE] mfe=26p
- `2026-03-13` Fri  range 98p net -93p  [none]  00:00→01:10 S [BB_U,P,R50,SESS_H_ASIA] mfe=31p || 01:05→11:15 B [BB_L,P,PDL,R00,R50,S1,S2,S3,SESS_L_ASIA,SESS_L_LON] mfe=45p || 06:00→06:00 S [BB_U] mfe=80p || 07:10→07:10 S [R00] mfe=49p || 09:30→09:30 S [BB_U] mfe=36p || 12:25→13:55 S [BB_U,R50,SESS_H_LATE,SESS_H_NY] mfe=60p
- `2026-03-16` Mon  range 110p net +69p  [none]  01:20→07:35 B [BB_L,P,R50,SESS_L_ASIA] mfe=43p || 13:20→13:20 B [BB_L,R00,SESS_L_NY] mfe=38p
- `2026-03-17` Tue  range 78p net +65p  [DAY_BEFORE]  01:05→03:30 S [BB_U,R00,SESS_H_ASIA] mfe=42p || 04:45→09:30 S [BB_U,P,PDH,R00,SESS_H_ASIA,SESS_H_LON] mfe=28p || 05:40→06:05 B [BB_L,P,R00,SESS_L_ASIA,SESS_L_LON] mfe=62p || 10:15→12:00 B [BB_L] mfe=49p || 13:25→16:00 B [BB_L,R50,SESS_L_LATE,SESS_L_NY] mfe=32p
- `2026-03-18` Wed  range 120p net -108p  [ON/FOMC]  00:00→06:25 S [BB_U,PDH,R50,SESS_H_ASIA,SESS_H_LON] mfe=34p || 06:35→13:00 B [BB_L,P,R50,SESS_L_LON] mfe=27p || 13:20→18:00 S [BB_U,P,R50,SESS_H_NY] mfe=99p || 14:10→14:25 B [BB_L,P,R00,SESS_L_NY] mfe=35p
- `2026-03-19` Thu  range 222p net +165p  [ON/BoE]  00:00→02:35 S [BB_U,P,R00,SESS_H_ASIA] mfe=33p || 02:20→08:40 B [BB_L,P,PDL,R50,SESS_L_ASIA,SESS_L_LON] mfe=46p || 06:10→06:15 S [BB_U,SESS_H_LON] mfe=32p || 08:45→19:15 S [BB_U,P,PDH,R00,R1,R2,R3,R50,SESS_H_LATE,SESS_H_LON,SESS_H_NY] mfe=48p || 11:20→11:20 B [BB_L,P,R00,R50,SESS_L_NY] mfe=104p || 17:45→18:40 B [R00,R50,SESS_L_LATE] mfe=74p
- `2026-03-20` Fri  range 139p net -62p  [DAY_AFTER]  00:00→01:05 S [BB_U,SESS_H_ASIA] mfe=27p || 04:40→08:15 S [BB_U,SESS_H_LON] mfe=74p || 08:55→10:10 B [BB_L,P,R00,SESS_L_LON] mfe=47p || 09:40→12:10 S [BB_U,P,R00] mfe=105p || 12:10→15:55 B [BB_L,P,R00,R50,SESS_L_NY] mfe=56p || 14:05→14:05 S [R50] mfe=53p || 15:20→18:25 S [BB_U,R50] mfe=34p || 18:20→19:35 B [BB_L,SESS_L_LATE] mfe=29p
- `2026-03-23` Mon  range 222p net +138p  [none]  00:00→01:35 S [BB_U,PDH,SESS_H_ASIA] mfe=30p || 00:30→00:40 B [BB_L,SESS_L_ASIA] mfe=33p || 02:30→10:45 B [BB_L,P,PDL,R00,R50,S1,SESS_L_ASIA,SESS_L_LON,SESS_L_NY] mfe=177p || 11:05→14:30 S [BB_U,P,R00,R1,R50,SESS_H_LATE,SESS_H_NY] mfe=102p
- `2026-03-24` Tue  range 93p net +0p  [DAY_BEFORE]  00:00→05:05 B [BB_L,P,R00,SESS_L_ASIA] mfe=60p || 05:10→07:10 S [BB_U,P,R00] mfe=66p || 08:15→17:10 B [BB_L,P,R00,R50,SESS_L_LON,SESS_L_NY] mfe=43p || 08:55→20:25 S [BB_U,P,R00,SESS_H_LATE,SESS_H_NY] mfe=36p || 18:40→18:55 B [BB_L,P,R00] mfe=52p
- `2026-03-25` Wed  range 70p net -18p  [ON/CPI_UK]  00:00→00:35 S [BB_U,SESS_H_ASIA] mfe=38p || 01:40→05:55 B [BB_L,P,R00,SESS_L_ASIA] mfe=51p || 02:55→03:10 S [P,R00] mfe=34p || 06:50→12:05 S [BB_U,P,R00,SESS_H_LON] mfe=69p || 07:30→14:20 B [BB_L,P,R00,S1,SESS_L_LON,SESS_L_NY] mfe=33p || 15:00→15:00 S [BB_U] mfe=30p || 16:40→17:40 S [BB_U,SESS_H_LATE] mfe=34p
- `2026-03-26` Thu  range 68p net -36p  [DAY_AFTER]  05:00→20:00 B [BB_L,PDL,R50,S1,SESS_L_LATE,SESS_L_LON,SESS_L_NY] mfe=58p || 06:50→06:55 S [BB_U,R50,SESS_H_ASIA] mfe=32p || 13:05→14:40 S [BB_U,R50,SESS_H_NY] mfe=48p || 15:45→16:00 S [R50] mfe=35p || 17:35→17:35 S [BB_U,SESS_H_LATE] mfe=36p || 20:15→20:15 S [BB_U,R50] mfe=27p
- `2026-03-27` Fri  range 76p net -71p  [none]  00:00→05:10 S [BB_U,P,R50,SESS_H_ASIA] mfe=38p || 09:25→10:05 S [BB_U] mfe=46p || 13:20→15:30 S [BB_U,R00,SESS_H_NY] mfe=73p
- `2026-03-30` Mon  range 84p net -60p  [none]  09:00→22:20 B [BB_L,PDL,R00,S1,S2,SESS_L_LATE,SESS_L_LON,SESS_L_NY] mfe=27p || 09:15→12:25 S [BB_U,R50,SESS_H_LON,SESS_H_NY] mfe=81p || 15:45→15:55 S [BB_U,R00] mfe=32p || 18:00→18:45 S [BB_U,R00,SESS_H_LATE] mfe=28p
- `2026-03-31` Tue  range 94p net +34p  [none]  00:00→01:20 B [BB_L,P,PDL,R00,R50,SESS_L_ASIA,SESS_L_LON,SESS_L_NY] mfe=66p || 01:35→02:30 S [BB_U,P,R00,SESS_H_ASIA] mfe=27p || 05:45→15:30 S [BB_U,P,R00,R1,R50,SESS_H_LATE,SESS_H_LON,SESS_H_NY] mfe=94p || 20:55→21:05 S [BB_U] mfe=25p
- `2026-04-01` Wed  range 76p net +58p  [none]  00:00→01:30 S [BB_U,R50,SESS_H_ASIA] mfe=36p || 03:40→13:45 S [BB_U,PDH,R00,R1,R2,R50,SESS_H_ASIA,SESS_H_LON,SESS_H_NY] mfe=36p || 04:30→04:50 B [BB_L,R50] mfe=62p || 08:45→09:00 B [BB_L] mfe=58p || 11:15→12:00 B [R00] mfe=32p || 13:25→14:05 B [BB_L,R00,SESS_L_NY] mfe=33p
- `2026-04-02` Thu  range 68p net +6p  [DAY_BEFORE]  00:00→01:10 S [BB_U,PDH,R00,SESS_H_ASIA] mfe=92p || 00:00→11:10 B [BB_L,P,PDL,R00,R50,S1,SESS_L_ASIA,SESS_L_LON] mfe=41p || 02:35→02:55 S [R50] mfe=37p || 07:15→07:25 S [BB_U,SESS_H_LON] mfe=36p || 11:35→15:00 S [BB_U,R00,R50,SESS_H_NY] mfe=31p || 13:10→13:10 B [BB_L,PDL,R00,R50,S1,SESS_L_LATE] mfe=51p
- `2026-04-03` Fri  range 58p net -29p  [HOL/ON/NFP]  08:05→20:30 B [BB_L,PDL,R00,SESS_L_LATE,SESS_L_LON,SESS_L_NY] mfe=26p || 13:50→13:55 S [SESS_H_NY] mfe=30p || 15:20→15:20 S [BB_U,R00,SESS_H_LATE,SESS_H_NY] mfe=32p
- `2026-04-06` Mon  range 61p net +15p  [HOL/none]  00:35→14:30 S [BB_U,P,PDH,R00,R1,R2,R50,SESS_H_ASIA,SESS_H_LATE,SESS_H_LON,SESS_H_NY] mfe=53p || 00:35→01:55 B [BB_L,P,PDL,R00,SESS_L_ASIA] mfe=29p || 06:05→07:05 B [BB_L,P,R50,SESS_L_NY] mfe=51p || 17:00→17:15 B [BB_L,SESS_L_NY] mfe=28p
- `2026-04-07` Tue  range 76p net +48p  [none]  00:00→00:15 S [BB_U,P,SESS_H_ASIA] mfe=30p || 03:10→23:20 S [BB_U,P,PDH,R00,R1,R2,R3,R50,SESS_H_ASIA,SESS_H_LATE,SESS_H_LON,SESS_H_NY] mfe=30p || 04:50→05:40 B [BB_L,P,R50,SESS_L_LON] mfe=61p || 10:00→14:05 B [BB_L,R50,SESS_L_LATE,SESS_L_NY] mfe=32p || 21:10→21:10 B [BB_L,R00,R50] mfe=129p
- `2026-04-08` Wed  range 82p net -16p  [none]  00:00→12:45 S [BB_U,PDH,R00,R1,R2,R50,SESS_H_ASIA,SESS_H_LON] mfe=58p || 00:00→00:40 B [BB_L,R00,SESS_L_ASIA] mfe=38p || 07:05→08:40 B [BB_L,SESS_L_LON] mfe=73p
- `2026-04-09` Thu  range 79p net +40p  [none]  00:00→01:25 B [BB_L,P,PDL,R00,SESS_L_ASIA,SESS_L_LON,SESS_L_NY] mfe=28p || 00:15→04:05 S [BB_U,R00,SESS_H_ASIA] mfe=26p || 10:25→17:40 S [BB_U,P,R00,R50,SESS_H_LON,SESS_H_NY] mfe=31p
- `2026-04-10` Fri  range 71p net +54p  [none]  01:30→07:55 B [BB_L,P,SESS_L_ASIA,SESS_L_LON] mfe=36p || 02:30→14:25 S [BB_U,P,R1,R50,SESS_H_LATE,SESS_H_LON,SESS_H_NY] mfe=34p || 11:25→11:35 B [BB_L,R50,SESS_L_NY] mfe=43p
- `2026-04-13` Mon  range 106p net +100p  [DAY_BEFORE]  00:00→00:30 B [BB_L,PDL,R00,S1,SESS_L_ASIA,SESS_L_LON] mfe=27p || 12:50→13:00 B [BB_L,S1] mfe=50p || 14:40→15:05 B [BB_L,P,R50] mfe=38p
- `2026-04-14` Tue  range 78p net +48p  [ON/CPI_US]  06:15→06:35 B [BB_L,SESS_L_LON] mfe=29p || 11:15→11:15 B [R50] mfe=44p
- `2026-04-16` Thu  range 66p net -50p  [DAY_AFTER]  00:00→03:05 S [BB_U,R1,R2,SESS_H_ASIA] mfe=32p || 00:20→01:35 B [BB_L,P,SESS_L_ASIA] mfe=36p || 06:00→06:00 S [BB_U,P,R1,R50] mfe=40p || 10:50→13:35 S [BB_U,R50,SESS_H_NY] mfe=40p || 15:50→16:15 S [BB_U] mfe=25p
- `2026-04-17` Fri  range 95p net +16p  [none]  05:00→06:35 B [BB_L,SESS_L_ASIA] mfe=38p || 10:30→11:05 B [BB_L] mfe=82p || 11:40→13:10 S [BB_U,P,R00,R1,R50,SESS_H_LON] mfe=56p || 12:35→12:40 B [P,R50,SESS_L_NY] mfe=58p || 16:10→16:50 S [BB_U,P,R50,SESS_H_LATE] mfe=41p
- `2026-04-20` Mon  range 52p net +29p  [none]  00:00→00:00 B [BB_L,S1] mfe=28p || 00:10→03:40 S [BB_U,R00,SESS_H_ASIA] mfe=28p || 02:10→06:25 B [BB_L,R00,SESS_L_LON] mfe=38p || 12:00→12:10 B [BB_L] mfe=31p || 14:45→14:50 B [BB_L,P,SESS_L_LATE,SESS_L_NY] mfe=38p
- `2026-04-21` Tue  range 68p net -12p  [none]  00:00→08:10 B [BB_L,P,R00,S1,SESS_L_ASIA,SESS_L_LON] mfe=34p || 00:20→06:00 S [BB_U,P,R00,SESS_H_ASIA,SESS_H_LON] mfe=53p || 09:30→14:40 S [BB_U,P,R00,SESS_H_LON,SESS_H_NY] mfe=66p || 12:15→19:40 B [BB_L,P,R00,S1,SESS_L_LATE,SESS_L_NY] mfe=42p || 16:55→17:40 S [BB_U,P,R00,SESS_H_LATE] mfe=53p
- `2026-04-22` Wed  range 44p net -13p  [none]  02:25→05:20 S [BB_U,R1,SESS_H_ASIA] mfe=25p || 06:40→07:20 B [BB_L] mfe=25p || 07:35→09:10 S [BB_U,R1,SESS_H_LON] mfe=34p || 09:45→12:35 B [BB_L,P,R00,SESS_L_LON] mfe=33p || 11:55→14:20 S [BB_U,P,R00,SESS_H_LATE,SESS_H_NY] mfe=30p
- `2026-04-23` Thu  range 70p net -26p  [none]  00:00→01:00 S [BB_U,P,R00] mfe=28p || 00:00→17:45 B [BB_L,P,R00,R50,S1,S2,SESS_L_LATE,SESS_L_LON,SESS_L_NY] mfe=37p || 08:30→14:50 S [BB_U,P,R00,SESS_H_LON,SESS_H_NY] mfe=70p || 18:30→18:35 S [SESS_H_LATE] mfe=27p
- `2026-04-27` Mon  range 45p net -1p  [none]  00:00→03:45 S [BB_U,R50,SESS_H_ASIA] mfe=25p || 00:00→00:15 B [BB_L] mfe=32p || 04:35→06:15 B [BB_L,SESS_L_LON] mfe=34p || 06:50→12:15 S [BB_U,R1,R50,SESS_H_LON,SESS_H_NY] mfe=38p || 08:45→09:45 B [BB_L,R50] mfe=28p
- `2026-04-28` Tue  range 60p net +12p  [DAY_BEFORE]  04:55→11:50 B [BB_L,R00,S1,S2,SESS_L_ASIA,SESS_L_LON] mfe=43p || 07:35→08:30 S [BB_U,R00,SESS_H_LON] mfe=38p || 11:05→11:05 S [BB_U] mfe=28p
- `2026-04-29` Wed  range 56p net -24p  [ON/FOMC]  00:15→18:45 B [BB_L,P,R00,S1,SESS_L_ASIA,SESS_L_LATE,SESS_L_LON,SESS_L_NY] mfe=26p || 14:50→14:55 S [BB_U,R00] mfe=27p || 18:00→18:00 S [BB_U] mfe=35p
- `2026-04-30` Thu  range 140p net +131p  [DAY_BEFORE]  00:00→00:15 S [BB_U,P,SESS_H_ASIA] mfe=27p || 00:00→04:40 B [BB_L,P,SESS_L_ASIA] mfe=34p || 05:50→06:10 B [BB_L,SESS_L_ASIA] mfe=47p || 07:30→09:10 B [BB_L,P,R00] mfe=57p || 12:00→12:15 B [BB_L,R00] mfe=96p || 14:25→14:35 B [R50] mfe=56p || 16:25→16:35 B [BB_L] mfe=38p
- `2026-05-01` Fri  range 88p net -31p  [ON/NFP]  00:00→03:20 S [BB_U,R00,SESS_H_ASIA] mfe=25p || 00:00→06:20 B [BB_L,R00,SESS_L_ASIA,SESS_L_LON] mfe=36p || 13:55→14:20 S [BB_U,R1,R50,SESS_H_NY] mfe=62p || 17:00→17:05 S [R00] mfe=29p
- `2026-05-04` Mon  range 68p net -49p  [HOL/none]  05:15→16:15 B [BB_L,R50,S1,S2,SESS_L_ASIA,SESS_L_LATE,SESS_L_LON,SESS_L_NY] mfe=29p || 05:40→06:20 S [BB_U,P,R00,SESS_H_ASIA,SESS_H_LON] mfe=41p || 09:35→09:35 S [BB_U,R50] mfe=40p || 12:05→12:35 S [BB_U,R50] mfe=32p || 13:45→14:35 S [BB_U,SESS_H_NY] mfe=56p
- `2026-05-05` Tue  range 47p net +9p  [none]  03:00→05:00 B [BB_L,SESS_L_ASIA] mfe=33p || 04:20→15:45 S [BB_U,P,R50,SESS_H_ASIA,SESS_H_LON,SESS_H_NY] mfe=31p || 09:00→11:20 B [BB_L,P,R50,SESS_L_LON] mfe=37p || 16:30→21:55 B [BB_L,P,R50,SESS_L_LATE] mfe=43p
- `2026-05-06` Wed  range 65p net +5p  [DAY_BEFORE]  02:15→04:15 B [BB_L,SESS_L_ASIA] mfe=32p || 04:25→10:55 S [BB_U,R00,R1,R2,SESS_H_ASIA,SESS_H_LATE,SESS_H_LON,SESS_H_NY] mfe=42p || 06:05→06:30 B [BB_L,R00,SESS_L_LON] mfe=53p
- `2026-05-07` Thu  range 83p net -48p  [ON/BoE]  14:55→15:00 S [BB_U,P,R00,SESS_H_NY] mfe=63p || 18:15→18:35 S [BB_U,SESS_H_LATE] mfe=36p
- `2026-05-08` Fri  range 61p net +48p  [DAY_AFTER]  02:35→04:05 B [BB_L,P,R50,SESS_L_ASIA] mfe=40p || 07:30→07:30 B [BB_L,R00,SESS_L_LON] mfe=45p || 10:20→11:00 B [BB_L,R00] mfe=31p || 12:30→12:30 B [BB_L,R00] mfe=30p
- `2026-05-12` Tue  range 53p net -7p  [DAY_BEFORE]  00:00→15:25 B [BB_L,R00,R50,S1,S2,S3,SESS_L_ASIA,SESS_L_LON,SESS_L_NY] mfe=31p || 00:15→00:15 S [R00,SESS_H_ASIA] mfe=25p || 04:55→04:55 S [BB_U] mfe=72p || 06:55→07:00 S [R50] mfe=48p || 09:00→10:35 S [BB_U,R50,SESS_H_LON] mfe=40p || 12:50→12:50 S [BB_U] mfe=43p
- `2026-05-13` Wed  range 53p net -3p  [ON/CPI_US]  03:35→06:00 S [BB_U,P,R50,SESS_H_ASIA] mfe=35p || 06:05→12:30 B [BB_L,P,R00,S1,SESS_L_ASIA,SESS_L_LON,SESS_L_NY] mfe=42p || 08:25→08:55 S [BB_U] mfe=39p || 10:45→10:50 S [BB_U] mfe=36p
- `2026-05-18` Mon  range 103p net +64p  [none]  08:45→08:55 S [R1] mfe=39p || 10:20→10:55 B [BB_L,P,R50,SESS_L_LON] mfe=57p || 11:00→16:15 S [BB_U,R00,R1,R2,R50,SESS_H_LON,SESS_H_NY] mfe=49p || 13:30→13:40 B [BB_L,SESS_L_NY] mfe=68p || 17:50→19:00 B [BB_L,R00,SESS_L_LATE] mfe=39p
- `2026-05-19` Tue  range 41p net -4p  [DAY_BEFORE]  05:25→05:55 S [BB_U,P,R00,SESS_H_LON] mfe=29p || 06:45→14:25 B [BB_L,P,R00,SESS_L_ASIA,SESS_L_LON,SESS_L_NY] mfe=34p || 12:05→12:40 S [BB_U,P,R00,SESS_H_LATE,SESS_H_LON,SESS_H_NY] mfe=41p
- `2026-05-20` Wed  range 89p net +48p  [ON/CPI_UK]  00:00→01:35 B [BB_L,SESS_L_ASIA] mfe=28p || 02:20→06:25 S [BB_U,P,R00,SESS_H_ASIA,SESS_H_LON] mfe=32p || 03:40→06:00 B [BB_L,P,R00,SESS_L_ASIA] mfe=30p || 08:10→08:20 B [BB_L,SESS_L_LON] mfe=25p || 09:05→15:15 S [BB_U,P,R00,R1,R2,R50,SESS_H_LATE,SESS_H_LON,SESS_H_NY] mfe=31p || 09:45→09:45 B [BB_L] mfe=28p || 11:30→14:10 B [BB_L,P,R00,SESS_L_NY] mfe=81p
- `2026-05-21` Thu  range 57p net -1p  [DAY_AFTER]  00:15→17:50 S [BB_U,P,R00,R50,SESS_H_ASIA,SESS_H_LATE,SESS_H_LON,SESS_H_NY] mfe=29p || 01:50→07:25 B [BB_L,P,SESS_L_ASIA,SESS_L_LON] mfe=31p
- `2026-05-22` Fri  range 49p net +8p  [none]  00:00→13:10 S [BB_U,P,R1,R50,SESS_H_ASIA,SESS_H_LATE,SESS_H_LON] mfe=45p || 00:00→07:10 B [BB_L,P,R50,SESS_L_ASIA,SESS_L_LON,SESS_L_NY] mfe=25p
- `2026-05-26` Tue  range 56p net -31p  [none]  06:25→11:10 S [BB_U,SESS_H_LON] mfe=32p || 13:15→13:20 S [BB_U,R50,SESS_H_NY] mfe=36p
- `2026-05-28` Thu  range 64p net +42p  [none]  00:00→04:00 B [BB_L,P,R00,S1,S2,SESS_L_ASIA,SESS_L_LON,SESS_L_NY] mfe=42p || 00:35→00:35 S [SESS_H_ASIA] mfe=39p || 03:10→03:10 S [R00] mfe=32p || 05:05→14:10 S [BB_U,P,R00,R1,R50,SESS_H_LATE,SESS_H_LON,SESS_H_NY] mfe=26p
- `2026-05-29` Fri  range 76p net +13p  [none]  04:35→15:30 S [BB_U,P,R1,R50,SESS_H_NY] mfe=34p || 14:35→14:35 B [BB_L,R50,SESS_L_NY] mfe=55p
- `2026-06-01` Mon  range 68p net -18p  [none]  03:15→03:55 B [BB_L,P,R50] mfe=26p || 10:40→12:30 S [BB_U,P,R50] mfe=62p || 12:10→14:00 B [BB_L,P,R50,S1] mfe=56p || 15:35→16:15 B [P,R50] mfe=29p
- `2026-06-04` Thu  range 51p net -3p  [DAY_BEFORE]  04:30→12:00 S [BB_U,P,R1,R50,SESS_H_ASIA,SESS_H_LON,SESS_H_NY] mfe=27p || 06:55→07:40 B [BB_L,SESS_L_LON] mfe=31p
- `2026-06-05` Fri  range 153p net -98p  [ON/NFP]  00:00→10:30 S [BB_U,P,R00,R1,R2,R50,SESS_H_ASIA,SESS_H_LON,SESS_H_NY] mfe=83p || 08:15→08:15 B [R50] mfe=31p || 16:10→17:00 S [BB_U,R50,SESS_H_LATE] mfe=27p
- `2026-06-09` Tue  range 54p net +16p  [DAY_BEFORE]  00:25→13:45 S [BB_U,P,R00,R1,R2,R50,SESS_H_ASIA,SESS_H_LATE,SESS_H_LON,SESS_H_NY] mfe=53p || 07:05→07:05 B [BB_L] mfe=34p || 11:30→16:40 B [BB_L,R00,SESS_L_NY] mfe=33p
- `2026-06-10` Wed  range 57p net -16p  [ON/CPI_US]  12:25→13:45 S [BB_U,R00,R1,SESS_H_LON] mfe=53p || 16:35→16:35 S [BB_U,R00] mfe=26p || 20:10→21:20 S [BB_U,P] mfe=30p
- `2026-06-11` Thu  range 109p net +39p  [DAY_AFTER]  00:00→07:25 S [BB_U,P,SESS_H_ASIA] mfe=40p || 11:30→11:30 S [BB_U,R50,SESS_H_NY] mfe=39p || 12:10→15:00 B [BB_L,P,R00,R50,S1,SESS_L_LON,SESS_L_NY] mfe=80p || 17:25→19:30 S [BB_U,R00,R1,R50,SESS_H_LATE] mfe=25p
- `2026-06-12` Fri  range 42p net -2p  [none]  02:05→04:40 S [BB_U,SESS_H_ASIA] mfe=34p || 04:55→07:35 B [BB_L,P,R00,SESS_L_ASIA,SESS_L_LON] mfe=42p || 05:55→09:25 S [BB_U,P,R00,SESS_H_LON] mfe=36p || 10:20→12:30 B [BB_L,P,R00] mfe=34p
- `2026-06-15` Mon  range 39p net -28p  [none]  00:00→00:20 S [BB_U,R1,R2,R50,SESS_H_ASIA,SESS_H_NY] mfe=28p || 00:45→02:10 B [BB_L,R50,SESS_L_ASIA] mfe=28p || 04:50→12:20 B [BB_L,R50,SESS_L_ASIA,SESS_L_LON] mfe=28p
- `2026-06-16` Tue  range 40p net +21p  [DAY_BEFORE]  00:15→06:20 B [BB_L,R00,S1,SESS_L_ASIA] mfe=37p || 03:30→10:55 S [BB_U,P,R00,SESS_H_LON] mfe=26p || 09:00→14:30 B [BB_L,P,R00,SESS_L_NY] mfe=40p
- `2026-06-17` Wed  range 160p net -120p  [ON/FOMC,CPI_UK]  00:05→06:00 S [BB_U,P,SESS_H_ASIA,SESS_H_LON] mfe=30p || 12:25→13:20 S [BB_U,P] mfe=34p || 13:20→19:35 B [BB_L,R00,R50,S1,S2,S3,SESS_L_LATE,SESS_L_NY] mfe=41p || 14:50→17:55 S [BB_U,R00,R50] mfe=142p
- `2026-06-18` Thu  range 123p net -105p  [ON/BoE]  06:10→06:30 S [BB_U,R00,R50,SESS_H_ASIA] mfe=92p || 07:05→11:55 B [BB_L,R00,R50,S1,SESS_L_LON,SESS_L_NY] mfe=48p || 12:10→13:35 S [BB_U,R50,SESS_H_NY] mfe=38p || 14:50→15:00 S [BB_U,R50,SESS_H_NY] mfe=48p || 15:00→19:15 B [BB_L,R00,R50,S1,SESS_L_LATE,SESS_L_NY] mfe=27p || 17:20→17:20 S [BB_U] mfe=37p
- `2026-06-19` Fri  range 49p net +32p  [HOL/DAY_AFTER]  00:00→00:55 S [BB_U,R00,SESS_H_ASIA] mfe=26p || 00:00→05:25 B [BB_L,R00,SESS_L_ASIA] mfe=58p || 07:05→07:25 B [R00,SESS_L_LON] mfe=49p || 11:00→11:20 S [BB_U,P,SESS_H_LON] mfe=27p || 12:50→12:50 S [BB_U,P,SESS_H_LON] mfe=27p
- `2026-06-22` Mon  range 90p net +42p  [none]  00:00→01:05 S [BB_U,P,SESS_H_ASIA] mfe=26p || 02:50→12:40 S [BB_U,P,R00,R1,R50,SESS_H_LATE,SESS_H_LON,SESS_H_NY] mfe=36p || 03:30→08:15 B [BB_L,P,R00,S1,SESS_L_ASIA,SESS_L_LON] mfe=64p || 11:55→12:00 B [BB_L,R50,SESS_L_LATE,SESS_L_NY] mfe=39p
- `2026-06-23` Tue  range 67p net -30p  [none]  05:55→07:05 S [BB_U,P,R50,SESS_H_LON] mfe=37p || 09:30→10:00 S [BB_U,P] mfe=25p || 13:05→13:45 S [BB_U,R00,SESS_H_NY] mfe=38p
- `2026-06-24` Wed  range 58p net -19p  [none]  05:05→06:10 S [BB_U,P,R00,SESS_H_ASIA,SESS_H_LON] mfe=37p || 08:50→08:55 S [R00,SESS_H_LON] mfe=49p || 09:30→14:55 B [BB_L,R50,S1,S2,SESS_L_LATE,SESS_L_LON,SESS_L_NY] mfe=39p || 11:35→16:35 S [BB_U,R50,SESS_H_NY] mfe=26p
- `2026-06-25` Thu  range 68p net +19p  [none]  04:40→06:30 B [BB_L,P,SESS_L_LON] mfe=30p || 06:35→09:30 S [BB_U,P,R00,SESS_H_LON] mfe=46p || 09:40→11:55 B [BB_L,P,R50,SESS_L_LON] mfe=67p || 14:15→14:20 B [R00] mfe=28p
- `2026-06-26` Fri  range 41p net +2p  [none]  00:00→14:20 S [BB_U,P,R00,R1,SESS_H_ASIA,SESS_H_LON,SESS_H_NY] mfe=34p || 00:00→02:55 B [BB_L,P,R00,SESS_L_ASIA,SESS_L_LON] mfe=27p || 11:05→12:50 B [BB_L,R00,SESS_L_NY] mfe=31p || 14:50→14:55 B [BB_L,R00,SESS_L_NY] mfe=25p
- `2026-06-29` Mon  range 60p net +33p  [none]  00:00→07:35 S [BB_U,P,R00,R1,SESS_H_ASIA,SESS_H_LON] mfe=25p || 07:20→08:50 B [BB_L,P,SESS_L_LON] mfe=31p || 10:30→10:35 B [BB_L] mfe=36p || 13:15→14:45 B [BB_L,R50,SESS_L_LATE,SESS_L_NY] mfe=26p
- `2026-06-30` Tue  range 64p net +20p  [none]  06:20→07:05 S [BB_U,P,R50,SESS_H_LON] mfe=25p || 10:20→12:30 B [BB_L,P,S1,SESS_L_LON,SESS_L_NY] mfe=64p || 13:15→15:00 S [BB_U,P,R50,SESS_H_NY] mfe=28p
- `2026-07-01` Wed  range 73p net +34p  [DAY_BEFORE]  04:30→14:40 S [BB_U,P,R1,R50,SESS_H_LON,SESS_H_NY] mfe=26p || 06:05→13:10 B [BB_L,P,R50,S1,SESS_L_ASIA] mfe=73p || 15:40→15:40 B [BB_L] mfe=26p
- `2026-07-02` Thu  range 88p net +42p  [ON/NFP]  04:00→14:15 S [BB_U,R00,R1,R2,R3,R50,SESS_H_ASIA,SESS_H_LON,SESS_H_NY] mfe=40p || 05:30→05:30 B [BB_L] mfe=68p || 07:00→07:05 B [R00] mfe=66p || 08:15→12:15 B [BB_L,R00,R50,SESS_L_LON,SESS_L_NY] mfe=88p
- `2026-07-03` Fri  range 31p net -18p  [HOL/DAY_AFTER]  00:00→00:15 B [BB_L,P,R50,SESS_L_ASIA] mfe=32p || 04:10→06:35 S [BB_U,SESS_H_ASIA,SESS_H_LON] mfe=25p
- `2026-07-07` Tue  range 45p net -21p  [none]  06:50→11:20 S [BB_U,P,SESS_H_LATE,SESS_H_LON,SESS_H_NY] mfe=34p || 09:45→10:05 B [BB_L,P,SESS_L_LON] mfe=25p
- `2026-07-08` Wed  range 88p net +24p  [none]  07:05→09:10 B [BB_L,P,R50,S1,SESS_L_LON] mfe=35p || 10:35→11:35 B [BB_L,P,R00,R50,S1,SESS_L_LATE,SESS_L_NY] mfe=48p
- `2026-07-10` Fri  range 22p net -10p  [none]  00:00→02:50 S [BB_U,R1,R50,SESS_H_ASIA,SESS_H_LON] mfe=31p || 00:00→00:25 B [BB_L,P] mfe=44p
- `2026-07-15` Wed  range 178p net +125p  [ON/CPI_US]  04:30→18:20 S [BB_U,P,R00,R1,R2,R3,R50,SESS_H_ASIA,SESS_H_LON,SESS_H_NY] mfe=30p || 07:00→10:25 B [BB_L,P,R00,SESS_L_LON] mfe=56p
- `2026-07-16` Thu  range 83p net -62p  [DAY_AFTER]  00:05→00:10 S [BB_U] mfe=25p || 03:00→07:00 S [BB_U,SESS_H_LON] mfe=37p || 11:15→13:50 S [BB_U,P,R00,SESS_H_NY] mfe=51p
- `2026-07-17` Fri  range 55p net -20p  [none]  05:35→07:00 S [BB_U] mfe=45p || 07:20→10:50 B [BB_L,R50,S1,SESS_L_LATE,SESS_L_LON,SESS_L_NY] mfe=28p || 08:30→08:30 S [R50] mfe=27p
- `2026-07-20` Mon  range 68p net -26p  [none]  10:15→11:30 S [BB_U,P,R50,SESS_H_NY] mfe=33p || 11:45→16:40 B [BB_L,P,R50,S1,SESS_L_LATE,SESS_L_LON,SESS_L_NY] mfe=27p
- `2026-07-21` Tue  range 96p net -71p  [DAY_BEFORE]  00:00→07:05 S [BB_U,P,R50,SESS_H_ASIA] mfe=30p || 04:55→13:35 B [BB_L,P,R00,R50,S1,S2,SESS_L_LATE,SESS_L_LON,SESS_L_NY] mfe=40p || 10:10→10:10 S [BB_U] mfe=51p || 12:15→12:15 S [R00] mfe=40p || 14:10→14:10 S [BB_U,R00,SESS_H_NY] mfe=34p
- `2026-07-22` Wed  range 40p net -7p  [ON/CPI_UK]  01:30→12:55 B [BB_L,SESS_L_ASIA,SESS_L_LON] mfe=35p || 07:15→07:30 S [BB_U,P] mfe=29p || 10:20→14:10 S [BB_U,SESS_H_NY] mfe=25p
- `2026-07-23` Thu  range 79p net -52p  [DAY_AFTER]  09:30→15:35 B [BB_L,P,R00,R50,S1,S2,S3,SESS_L_LATE,SESS_L_LON,SESS_L_NY] mfe=27p || 09:35→09:40 S [BB_U,P,R50,SESS_H_LON,SESS_H_NY] mfe=41p
- `2026-07-24` Fri  range 43p net -3p  [none]  00:00→13:10 B [BB_L,S1,S2,S3,SESS_L_ASIA,SESS_L_LATE,SESS_L_LON] mfe=43p || 04:15→07:30 S [BB_U,SESS_H_ASIA] mfe=32p || 13:50→15:15 S [BB_U,R50,SESS_H_NY] mfe=27p
- `2026-07-27` Mon  range 68p net -59p  [none]  10:00→10:00 S [BB_U] mfe=32p || 16:15→16:25 S [BB_U] mfe=30p
- `2026-07-28` Tue  range 38p net -8p  [DAY_BEFORE]  00:00→10:10 B [BB_L,R00,SESS_L_ASIA,SESS_L_LON] mfe=30p || 06:25→08:20 S [BB_U,R00,SESS_H_ASIA,SESS_H_LON] mfe=32p || 13:10→14:50 B [BB_L,R00,SESS_L_NY] mfe=26p
- `2026-07-29` Wed  range 108p net +76p  [ON/FOMC]  00:00→19:15 S [BB_U,P,R00,R1,R2,R3,R50,SESS_H_ASIA,SESS_H_LATE,SESS_H_LON,SESS_H_NY] mfe=44p || 00:00→12:15 B [BB_L,P,R00,R50,SESS_L_ASIA,SESS_L_LON,SESS_L_NY] mfe=25p
- `2026-07-30` Thu  range 140p net +126p  [DAY_AFTER]  00:00→06:30 B [BB_L,P,R50,SESS_L_ASIA,SESS_L_LON] mfe=44p || 12:50→12:55 B [BB_L,R00,SESS_L_NY] mfe=96p || 15:35→15:35 B [R50] mfe=25p
- `2026-08-03` Mon  range 54p net -27p  [none]  00:25→00:40 S [BB_U,R00,SESS_H_ASIA] mfe=39p || 04:15→06:00 S [BB_U,P,R50,SESS_H_LON,SESS_H_NY] mfe=28p
- `2026-08-05` Wed  range 32p net -1p  [DAY_BEFORE]  00:00→14:20 S [BB_U,R1,R2,R50,SESS_H_ASIA,SESS_H_LATE,SESS_H_LON,SESS_H_NY] mfe=31p || 12:40→13:45 B [BB_L,SESS_L_NY] mfe=27p
- `2026-08-07` Fri  range 74p net +36p  [ON/NFP]  00:05→10:40 B [BB_L,R00,R50,S1,SESS_L_ASIA,SESS_L_LON,SESS_L_NY] mfe=74p || 11:00→13:25 S [BB_U,R00,R1,R2,R50,SESS_H_LATE,SESS_H_LON,SESS_H_NY] mfe=26p
- `2026-08-10` Mon  range 40p net +14p  [none]  00:00→14:45 S [BB_U,R00,R1,SESS_H_ASIA,SESS_H_LON,SESS_H_NY] mfe=25p || 07:00→12:40 B [BB_L,R00,SESS_L_LON] mfe=40p
- `2026-08-12` Wed  range 58p net -14p  [ON/CPI_US]  00:00→12:30 S [BB_U,P,R00,R1,R2,R3,SESS_H_ASIA,SESS_H_LATE,SESS_H_LON] mfe=44p || 10:45→10:45 B [BB_L] mfe=32p || 12:30→12:30 B [BB_L,P,SESS_L_LON] mfe=34p
- `2026-08-13` Thu  range 39p net +3p  [DAY_AFTER]  03:25→06:00 S [BB_U,R00,SESS_H_ASIA] mfe=26p || 12:30→14:15 S [BB_U,P,R00,SESS_H_LON,SESS_H_NY] mfe=33p

---

## Appendix B — Hardcoded public news schedules (2024-2026)

Sources: BLS (NFP, US CPI), Federal Reserve (FOMC), Bank of England (MPC), ONS (UK CPI). Convention notes:
- **NFP**: first-Friday convention; **2025-01 and 2026-01 both delayed a week** because first-Friday fell day-after New Year's holiday.
- **US CPI**: BLS monthly, typically Tue/Wed 08:30 ET.
- **FOMC**: day-2 of two-day meetings (press conference), 14:00 ET.
- **BoE MPC**: 'Super Thursday' 12:00 UK.
- **UK CPI**: ONS monthly, typically Wed 07:00 UK.

**NFP (32 dates)**: 2024-01-05, 2024-02-02, 2024-03-08, 2024-04-05, 2024-05-03, 2024-06-07, 2024-07-05, 2024-08-02, 2024-09-06, 2024-10-04, 2024-11-01, 2024-12-06, 2025-01-10, 2025-02-07, 2025-03-07, 2025-04-04, 2025-05-02, 2025-06-06, 2025-07-03, 2025-08-01, 2025-09-05, 2025-10-03, 2025-11-07, 2025-12-05, 2026-01-09, 2026-02-06, 2026-03-06, 2026-04-03, 2026-05-01, 2026-06-05, 2026-07-02, 2026-08-07

**US CPI (32 dates)**: 2024-01-11, 2024-02-13, 2024-03-12, 2024-04-10, 2024-05-15, 2024-06-12, 2024-07-11, 2024-08-14, 2024-09-11, 2024-10-10, 2024-11-13, 2024-12-11, 2025-01-15, 2025-02-12, 2025-03-12, 2025-04-10, 2025-05-13, 2025-06-11, 2025-07-15, 2025-08-12, 2025-09-11, 2025-10-15, 2025-11-13, 2025-12-10, 2026-01-14, 2026-02-11, 2026-03-11, 2026-04-14, 2026-05-13, 2026-06-10, 2026-07-15, 2026-08-12

**FOMC (21 dates)**: 2024-01-31, 2024-03-20, 2024-05-01, 2024-06-12, 2024-07-31, 2024-09-18, 2024-11-07, 2024-12-18, 2025-01-29, 2025-03-19, 2025-05-07, 2025-06-18, 2025-07-30, 2025-09-17, 2025-10-29, 2025-12-10, 2026-01-28, 2026-03-18, 2026-04-29, 2026-06-17, 2026-07-29

**BoE MPC (21 dates)**: 2024-02-01, 2024-03-21, 2024-05-09, 2024-06-20, 2024-08-01, 2024-09-19, 2024-11-07, 2024-12-19, 2025-02-06, 2025-03-20, 2025-05-08, 2025-06-19, 2025-08-07, 2025-09-18, 2025-11-06, 2025-12-18, 2026-02-05, 2026-03-19, 2026-05-07, 2026-06-18, 2026-08-06

**UK CPI (32 dates)**: 2024-01-17, 2024-02-14, 2024-03-20, 2024-04-17, 2024-05-22, 2024-06-19, 2024-07-17, 2024-08-14, 2024-09-18, 2024-10-16, 2024-11-20, 2024-12-18, 2025-01-15, 2025-02-19, 2025-03-26, 2025-04-16, 2025-05-21, 2025-06-18, 2025-07-16, 2025-08-20, 2025-09-17, 2025-10-22, 2025-11-19, 2025-12-17, 2026-01-21, 2026-02-18, 2026-03-25, 2026-04-15, 2026-05-20, 2026-06-17, 2026-07-22, 2026-08-19

**Caveat**: monthly CPI dates are per publicly-scheduled ONS/BLS calendars; individual releases within a month can slip ±1 business day for holiday-adjacent scheduling. FOMC/BoE dates are firm. NFP first-Friday exceptions noted above.

---

## Appendix C — Market holidays (2024-2026)

**US NYSE holidays (29 dates)**: 2024-01-01, 2024-01-15, 2024-02-19, 2024-03-29, 2024-05-27, 2024-06-19, 2024-07-04, 2024-09-02, 2024-11-28, 2024-12-25, 2025-01-01, 2025-01-09, 2025-01-20, 2025-02-17, 2025-04-18, 2025-05-26, 2025-06-19, 2025-07-04, 2025-09-01, 2025-11-27, 2025-12-25, 2026-01-01, 2026-01-19, 2026-02-16, 2026-04-03, 2026-05-25, 2026-06-19, 2026-07-03, 2026-07-04

**UK bank holidays (24 dates)**: 2024-01-01, 2024-03-29, 2024-04-01, 2024-05-06, 2024-05-27, 2024-08-26, 2024-12-25, 2024-12-26, 2025-01-01, 2025-04-18, 2025-04-21, 2025-05-05, 2025-05-26, 2025-08-25, 2025-12-25, 2025-12-26, 2026-01-01, 2026-04-03, 2026-04-06, 2026-05-04, 2026-05-25, 2026-08-31, 2026-12-25, 2026-12-28

---

## Appendix D — Scripts & artefacts

- `/tmp/two_bounce_days.py` — scanner (bar loader + level-set + episode grouper + qualifier)
- `/tmp/two_bounce_analyze.py`, `/tmp/two_bounce_news.py`, `/tmp/two_bounce_finalize.py` — analysis stages
- `/tmp/two_bounce_per_day.json` — raw per-day scan output (818 dates)
- `/tmp/two_bounce_ge2_records.json` — full ≥2 records with bounce details
- `/tmp/two_bounce_summary.json` — aggregated table inputs

Bar sources per date range unchanged from audited detector: `data/candles/GBPUSD` (IG live, mid, 2026-03-23 → 2026-08-14) → `data/ohlc/GBPUSD/5M` (mid+spread, 2026-01-01 → 2026-04-06 excl. 2026-04-07..10 corrupt) → `data/candles_ext/GBPUSD` (HistData tick rebuild, bid, 2024-01-01 → 2025-12-31). Pivots: `bb_pd_gate.compute_pivots_only` for 2026, classic-floor on `candles_ext/GBPUSD_D1.csv` prior-day OHLC for 2024-25.