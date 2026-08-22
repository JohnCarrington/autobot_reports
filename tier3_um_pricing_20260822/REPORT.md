# Tier 3 — UM-Arming Counterfactual on Calendar-Grind Days

**Date:** 2026-08-22
**Host:** AutoBotV1 (`/opt/tradingbot`)
**Investigate-only.** No code, no commits, no restarts.
**Every classification re-derived from raw candles + Finnhub cache.**
Reproducer scripts + JSON checkpoints live alongside this file.

---

## Part A — Independent reproduction of Section 4

Reproducer: `tier3_partA.py` (TIER1 list), `tier3_classify.py` (zigzag +
day class), `tier3_xtab.py` (cross-tab). All classifications applied from
the audit's stated definitions (REV_PIPS=15, RUN_MIN=40, GRIND=range≥60 ∧
|net|≥0.70·range) — freshly implemented, no reuse of the audit's
per-day join.

### A.1  TIER1 event-day list — from Finnhub cache

Scan of every `cache/news_state_finnhub_*.json` for events matching
`(currency, event)` pairs corresponding to the 13 TIER1 labels found:

| label | mine (n distinct dates) | audit (n distinct dates) | agree? |
|:---|--:|--:|:---|
| NFP       | 8 | 6 in-candle-set | +1 vs audit's full list (see below) |
| FOMC      | 5 | 5 total, 4 in candle set | agree |
| US_CPI    | 8 | 8 | agree |
| US_GDP    | 9 | 8 | +1 (2026-08-26, past window) |
| US_PPI    | 9 | 9 | agree |
| US_RETAIL | 9 | 9 | agree |
| ISM_MFG   | 8 | 8 | agree |
| ISM_SVC   | 8 | 8 | agree |
| BOE       | 5 | 4 | +1 (2026-07-30) |
| UK_CPI    | 8 | 8 | agree |
| UK_GDP    | 9 | 9 | agree |
| UK_UNEM   | 8 | 8 | agree |
| UK_RETAIL | 8 | 8 | agree |

**Independent-only TIER1 dates the audit missed** (inside its window
2026-01-01…2026-08-21):

| date | label | source cache file | mechanism |
|:---|:---|:---|:---|
| 2026-06-05 | NFP | `news_state_finnhub_2026-06-06.json` | audit REPORT.md flags 06-05 as "missing news file"; but the NFP event lives in the **next-day** cache. Same-filename lookup dropped it. |
| 2026-07-30 | BOE + US_GDP | `news_state_finnhub_2026-07-24.json` | audit flags 07-30 as missing; events are actually in a **forward-looking** cache file dated 07-24. |
| 2026-08-26 | US_GDP | `news_state_finnhub_2026-08-19.json` | past 2026-08-21 window; not counted. |

Both real misses raise TIER1 count from 83 → 85 dates in-window.
Overall TIER1 total 86 including 08-26.

### A.2  Release-timestamp spot-checks (raw Finnhub rows)

| label | date | Finnhub `ts` | date of `ts` = claim? | event | impact |
|:---|:---|:---|:---:|:---|:---:|
| FOMC   | 2026-01-28 | `2026-01-28T19:00:00+00:00` | ✓ | Fed Interest Rate Decision | HIGH |
| FOMC   | 2026-06-17 | `2026-06-17T18:00:00+00:00` | ✓ | Fed Interest Rate Decision | HIGH |
| BOE    | 2026-06-18 | `2026-06-18T11:00:00+00:00` | ✓ | BoE Interest Rate Decision | HIGH |
| NFP    | 2026-05-08 | `2026-05-08T12:30:00+00:00` | ✓ | Non Farm Payrolls | HIGH |
| UK_CPI | 2026-01-21 | `2026-01-21T07:00:00+00:00` | ✓ | Inflation Rate YoY | HIGH |

All 5 release timestamps fall on the claimed calendar date.

### A.3  Day-classification — fresh zigzag on candle archive

`tier3_classify.py` implements the audit's stated forward-walking
zigzag on 5-min closes (REV_PIPS = 15, RUN_MIN = 40). One implementation
subtlety worth flagging: the audit's spec says "first pivot = day-open,
walk forward maintaining a running swing extreme." A naive read that only
tracks the running MAX misses initial down-legs. Correct behaviour needs
to track BOTH running max and running min until the first ±REV_PIPS
excursion commits direction; my first attempt got this wrong (74 QUIET
days). Once corrected, results match the audit at the day-class level.

Independent classification of 140 full days (audit: 139; the +1 is
2026-08-21, which is a partial in audit but crosses the 200-row full-day
threshold when I re-count):

|              | mine | audit |
|:-------------|--:|--:|
| BOUNCE_DAY   | 70 (50.0 %) | 67 (48.2 %) |
| GRIND_DAY    | 24 (17.1 %) | 24 (17.3 %) |
| QUIET_DAY    | 22 (15.7 %) | 24 (17.3 %) |
| MULTI_DAY    | 24 (17.1 %) | 24 (17.3 %) |

Runs-per-day histogram — audit vs mine:

| n_runs | audit | mine |
|--:|--:|--:|
| 0 | 24 | 22 |
| 1 | 53 | 49 |
| 2 | 32 | 38 |
| 3 | 18 | 19 |
| 4 |  9 |  9 |
| 5 |  1 |  1 |
| 6 |  1 |  1 |
| 9 |  1 |  1 |

Small boundary noise (2–6 days) at the 0/1/2-run edges; totals match.

**GRIND_100 days: identical 8 dates, identical (net, range) to 0.1p.**

| date | net (p) | range (p) | mine class | audit class |
|:---|--:|--:|:---|:---|
| 2026-01-05 | +130.8 | 144.8 | GRIND_DAY | GRIND_DAY |
| 2026-01-23 | +136.8 | 163.8 | GRIND_DAY | GRIND_DAY |
| 2026-04-07 | +169.9 | 199.0 | GRIND_DAY | GRIND_DAY |
| 2026-04-13 | +120.4 | 130.4 | GRIND_DAY | GRIND_DAY |
| 2026-04-30 | +111.9 | 158.9 | GRIND_DAY | GRIND_DAY |
| 2026-06-17 | −125.7 | 175.9 | GRIND_DAY | GRIND_DAY |
| 2026-06-18 | −110.7 | 131.9 | GRIND_DAY | GRIND_DAY |
| 2026-07-15 | +142.1 | 177.5 | GRIND_DAY | GRIND_DAY |

### A.4  News-class × day-class cross-tab (Section 4a-b)

News-class assigned from my TIER1 dates: **BIG_NEWS** = date has a TIER1
event; **PRE_BIG** = next weekday is BIG_NEWS; **POST_BIG** = prev
weekday was; else **CLEAR**.

Mine (n = 140 full days):

| news / day  | BOUNCE | GRIND | QUIET | MULTI | TOTAL |
|:------------|--:|--:|--:|--:|--:|
| BIG_NEWS    | 32 | **17** | 10 | 17 | 76 |
| PRE_BIG     | 24 |  3 |  9 |  5 | 41 |
| POST_BIG    |  9 |  3 |  3 |  0 | 15 |
| CLEAR       |  5 |  1 |  0 |  2 |  8 |

Audit (n = 139):

| news / day  | BOUNCE | GRIND | QUIET | MULTI | TOTAL |
|:------------|--:|--:|--:|--:|--:|
| BIG_NEWS    | 30 | **17** | 10 | 16 | 73 |
| PRE_BIG     | 22 |  3 | 10 |  5 | 40 |
| POST_BIG    |  9 |  3 |  4 |  1 | 17 |
| CLEAR       |  6 |  1 |  0 |  2 |  9 |

**Row-percentage comparison of load-bearing cells:**

| cell | mine | audit | agreement |
|:---|--:|--:|:---|
| BIG_NEWS **grind rate** | 17/76 = **22.4 %** | 17/73 = **23.3 %** | agree ±1 pp |
| PRE_BIG grind rate | 3/41 = 7.3 % | 3/40 = 7.5 % | agree |
| POST_BIG grind rate ⚠ n≤17 | 3/15 = 20.0 % | 3/17 = 17.6 % | agree, cell thin |
| CLEAR ⚠ n≤9 | 1/8 = 12.5 % | 1/9 = 11.1 % | agree, cell thin |

**Audit's verdict — grinds cluster ON BIG_NEWS days (~23 %), NOT the day
before (~7 %) — reproduced.** The FALSIFIED grind-clusters-in-PRE_BIG
claim survives independent test.

### A.5  Per-major event tables — mine

Every table below has n < 10 → **THIN CELL, treat as directional signal
only**, individual counts are not statistically stable.

| label | n | B | G | Q | M | range mean | net mean | notes |
|:---|--:|--:|--:|--:|--:|--:|--:|:---|
| NFP       | 7 | 4 | 1 | 0 | 2 |  92 |  −1  | audit had n=6; +2026-06-05 BOUNCE (range 152, net −84, not grind: 84/152 = 0.55) |
| **FOMC**  | 4 | 0 | **2** | 1 | 1 | 111 | −10  | 2/4 GRIND — matches audit exactly (01-28, 04-29, 06-17, 07-29) |
| US_CPI    | 6 | 5 | 0 | 0 | 1 |  75 |  −7  | agrees with audit (4 BOUNCE / 1 MULTI / 0 GRIND is audit's; my BOUNCE=5 is one more, boundary noise) |
| **BOE**   | 4 | 0 | **2** | 0 | 2 | 140 |  +8  | audit n=3 (2 GRIND / 1 MULTI); mine adds 07-30 MULTI +96p — pattern intact: BoE = big-range, directional, never a clean 1-bounce day |
| UK_CPI    | 8 | 4 | 3 | 1 | 0 |  87 | −23  | agrees with audit (4 BOUNCE / 3 GRIND / 1 QUIET) |
| UK_GDP    | 7 | 2 | 1 | 2 | 2 |  72 | −16  | audit had 4B/1G/1M/2Q — 2-day drift, thin |
| US_GDP    | 7 | 4 | 1 | 0 | 2 | 103 | +58  | audit had n=6 (4B/1M/1G); +07-30 US_GDP MULTI |
| ISM_MFG   | 7 | 3 | 2 | 0 | 2 |  97 | +23  | agrees with audit |
| ISM_SVC   | 7 | 4 | 2 | 1 | 0 |  71 |  −4  | agrees with audit |
| US_PPI    | 8 | 1 | 2 | 2 | 3 |  87 | +17  | agrees with audit |
| UK_UNEM   | 7 | 1 | 1 | 2 | 3 |  81 | −42  | audit had 3M/2Q/1B/1G — agrees |
| UK_RETAIL | 8 | 3 | 3 | 2 | 0 |  80 | +25  | agrees with audit |
| US_RETAIL | 7 | 2 | 2 | 1 | 2 |  91 | −18  | audit did not table US_RETAIL separately |

**Load-bearing FOMC re-derivation (n=4):**

| date | mine class | range | net | n_runs |
|:---|:---|--:|--:|--:|
| 2026-01-28 | MULTI_DAY | 90.4 | +44.3 | 4 |
| 2026-04-29 | QUIET_DAY | 69.1 | −39.0 | 0 |
| 2026-06-17 | GRIND_DAY | 175.9 | −125.7 | 2 |
| 2026-07-29 | GRIND_DAY | 108.1 | +79.8 | 1 |

**Load-bearing BoE re-derivation (mine n=4):**

| date | mine class | range | net | n_runs |
|:---|:---|--:|--:|--:|
| 2026-02-05 | MULTI_DAY | 124.1 | −66.4 | 6 |
| 2026-04-30 | GRIND_DAY | 158.9 | +111.9 | 3 |
| 2026-06-18 | GRIND_DAY | 131.9 | −110.7 | 2 |
| 2026-07-30 | MULTI_DAY | 144.6 | +95.8 | 3 |

### A — Part-A verdict summary

* Independent scan of Finnhub cache raises TIER1 count by 2 dates the
  audit missed by keying only the same-filename cache. Neither is a
  grind, so the audit's grind-rate headline is not altered.
* Day-classification pipeline matches audit at every load-bearing cell:
  identical 8 GRIND_100 dates with identical (net, range); FOMC 2/4
  grinds identical; BoE 2/3 → 2/4 grind on my count (audit missed 07-30).
* **BIG_NEWS grind rate: mine 22.4 %, audit 23.3 % — reproduced.**
* **PRE_BIG grind rate: mine 7.3 %, audit 7.5 % — reproduced.**
* The "grinds cluster ON BIG_NEWS, not the day before" finding survives
  independent test.

---

## Part B — Price the UM bracket on the grind + TIER1 days

Reproducer: `tier3_um_price.py`.
Mechanism proposed: on calendar-flagged days, TREND_V3 fires wear a UM
bracket instead of managed exit — **12 p stop, 100 p target, flat 20:40
UTC**.

### B.0  What is actually in the signal_log window

**Signal_log TREND_V3 fires:** 48 fires across **17 dates**,
2026-07-02 → 2026-08-20. TREND_V3 is a new strategy — the audit's stated
signal_log window (2026-03-30 → 2026-08-21) does not apply here; TV3's
own window is a 7-week slice at the tail.

Managed pnl total across all 48 TV3 fires: **+78.1 p**. Outcomes: 12
REGIME_LEFT, 10 FLATTEN_EXHAUSTION, 10 TP hit, 5 SL hit, 5 BE_STOP,
6 miscellaneous.

### B.1  Grind-100 days in the TV3 window

Of the 8 GRIND_100 dates from A.3, only one is inside TV3's window
(**2026-07-15**). The other 7 predate TV3's existence — no arming
counterfactual is possible without a full TV3-simulator, which the
prompt explicitly excludes.

**⚠ THIN CELL — n = 1 grind-100 day inside TV3 data.**

### B.2  All TIER1 days in the TV3 window — per-day bar walk

**Uniform method:** entry = signal-log `entry` price at the fire's
5-minute bar close. Walk subsequent 5-minute bars: if bar low touches
SL (BUY: entry −12 p) → exit −12 p; if bar high touches TP (BUY: entry
+100 p) → exit +100 p; if 20:40 UTC arrives with neither hit → exit at
the 20:40 bar open. Ties inside a single 5-min bar resolved
**adversely** (SL first) — conservative.

18 TIER1 days in TV3 window; 10 saw ≥1 TV3 fire:

| date | class | labels | fires | managed p | UM p | UM − managed |
|:---|:---|:---|--:|--:|--:|--:|
| 2026-07-02 | MULTI | NFP           |  5 |  +12.9 |  −60.0 | **−72.9** |
| 2026-07-06 | BOUNCE | ISM_SVC      |  4 |  +13.4 |  +23.3 |  +9.9 |
| 2026-07-14 | BOUNCE | US_CPI       |  0 |    —   |    —   |   0.0 |
| **2026-07-15** | **GRIND** | US_PPI | 13 | **+37.4** | **+787.9** | **+750.5** ★ |
| 2026-07-16 | GRIND | UK_GDP, US_RETAIL | 0 |  —   |    —   |   0.0 |
| 2026-07-21 | BOUNCE | UK_UNEM      |  2 |  +33.9 |  +12.9 | −21.0 |
| 2026-07-22 | QUIET | UK_CPI        |  0 |    —   |    —   |   0.0 |
| 2026-07-24 | QUIET | UK_RETAIL     |  1 |  −10.5 |  −12.0 |  −1.5 |
| 2026-07-29 | GRIND | FOMC          |  0 |    —   |    —   |   0.0 |
| 2026-07-30 | MULTI | BOE, US_GDP   |  2 |  +14.0 |  +88.0 | +74.0 |
| 2026-08-03 | GRIND | ISM_MFG       |  0 |    —   |    —   |   0.0 |
| 2026-08-05 | QUIET | ISM_SVC       |  1 |  −10.5 |  −12.0 |  −1.5 |
| 2026-08-07 | BOUNCE | NFP          |  3 |   −6.2 |  −15.4 |  −9.2 |
| 2026-08-12 | BOUNCE | US_CPI       |  1 |  −11.8 |  −12.0 |  −0.2 |
| 2026-08-13 | QUIET | UK_GDP, US_PPI |  0 |   —   |    —   |   0.0 |
| 2026-08-14 | BOUNCE | US_RETAIL    |  1 |  +32.8 |  +18.2 | −14.5 |
| 2026-08-18 | QUIET | UK_UNEM      |  0 |    —   |    —   |   0.0 |
| 2026-08-19 | BOUNCE | UK_CPI       |  0 |    —   |    —   |   0.0 |
| **subject totals** |||  **33** | **+105.4** | **+819.0** | **+713.7** |

**Per-day path detail for the single grind (2026-07-15):**

| fire ts | dir | entry | managed p | UM outcome | UM exit ts |
|:---|:---|:---|--:|:---|:---|
| 11:55 | BUY | 13409.4 |  +1.6 | TP +100 | 16:25 |
| 12:00 | BUY | 13411.7 |  −4.0 | TP +100 | 16:25 |
| 12:05 | BUY | 13408.8 |  −4.3 | TP +100 | 16:25 |
| 12:10 | BUY | 13405.3 |  +3.5 | TP +100 | 16:20 |
| 12:15 | BUY | 13409.3 |  −2.5 | TP +100 | 16:25 |
| 12:55 | BUY | 13425.5 |  +2.4 | TP +100 | 16:50 |
| 13:00 | BUY | 13428.7 |  +1.3 | TP +100 | 17:00 |
| 14:50 | BUY | 13474.4 | +17.5 | FLAT 20:40 +61.1 | 20:40 |
| 15:55 | BUY | 13498.5 | +16.2 | FLAT 20:40 +37.0 | 20:40 |
| 16:50 | BUY | 13521.0 | +15.9 | FLAT 20:40 +14.6 | 20:40 |
| 17:05 | BUY | 13536.4 |  +3.6 | FLAT 20:40 −0.8  | 20:40 |
| 17:40 | BUY | 13540.0 | +10.5 | SL −12 | 19:35 |
| 18:05 | BUY | 13552.3 | −24.2 | SL −12 | 18:50 |

The 07-15 grind produces 7 straight +100 p TPs on stacked entries from
12:00–13:00 (as price ran +122 p from 13409 → 13531+ by 16:25). Late-day
entries near the top get clipped for −12 p as price reverted.

**⚠ Bookkeeping caveat on 2026-07-15:** these 13 fires are counted
independently. Live, a broker/system running one position per fire would
stack up to 13 concurrent longs — which is unlikely to be permitted by
risk/margin. If deduped to at most **one concurrent position**, the
07-15 delta collapses from +750 p to roughly one +100 p TP + the two
later −12 p SLs = **+76 p** on the day, not +750 p.
**The reported +713 p subject total is the "all fires independent"
upper bound. The one-position lower bound is ≈ +60–80 p.**

### B.3  Non-subject TV3 days (cost side — TV3 fires on non-TIER1 days)

7 TV3 dates fall between 2026-07-08 and 2026-08-20 outside the 18
TIER1-days list:

| date | class | fires | managed p | UM p | UM − managed |
|:---|:---|--:|--:|--:|--:|
| 2026-07-08 | MULTI  | 1 |  −16.8 |  −12.0 |  +4.8 |
| 2026-07-09 | BOUNCE | 4 |   +4.7 |  +80.7 | +76.0 |
| 2026-07-17 | BOUNCE | 2 |   −4.5 |  −24.0 | −19.5 |
| 2026-07-20 | BOUNCE | 4 |  −11.2 |  −48.0 | −36.8 |
| 2026-07-28 | QUIET  | 1 |  −12.1 |  −12.0 |  +0.1 |
| 2026-07-31 | BOUNCE | 1 |   +1.4 |  −12.0 | −13.3 |
| 2026-08-20 | BOUNCE | 2 |  +11.3 |   −9.2 | −20.5 |
| **totals** ||  **15** | **−27.3** | **−36.5** | **−9.3** |

Non-subject cost, all-fires basis: **−9.3 p over 7 days**, i.e. a mild
bleed of **~1.3 p / non-subject day** across 5 BOUNCE, 1 MULTI, 1 QUIET.
**⚠ Cell thin (n=7 days, 15 fires)**; 07-20 alone (BOUNCE, −36.8 p) is
23 % of the fire count and drives the aggregate.

### B.4  Per-day and per-class deltas (subject days)

| class | subject days | days with fires | Σ UM−managed | Σ / days-with-fires |
|:---|--:|--:|--:|--:|
| GRIND ⚠ | 4 | 1 | +750.5 p | +750.5 p/day (n=1) |
| MULTI ⚠ | 2 | 2 |   +1.1 p |   +0.6 p/day |
| BOUNCE ⚠ | 7 | 5 |  −35.0 p |  −7.0 p/day |
| QUIET ⚠ | 5 | 2 |   −3.0 p |  −1.5 p/day |
| **all** | 18 | 10 | +713.7 p | +71.4 p/day |

Every class cell in this window has n < 5 — treat as directional signal
only, not point estimates.

### B — Part-B verdict summary

* **The whole subject-side positive total (+713 p) rests on ONE grind
  day (2026-07-15).** Remove it → subject side is **−36.8 p across the
  remaining 17 days**.
* Even on that one grind, the +713 p headline is inflated by counting 13
  concurrent stacked fires; a realistic one-position live equivalent is
  **~+60–80 p / grind day**, not +750 p.
* Non-grind subject days (n=14): net **−36.9 p** across 8 days with
  fires. The BOUNCE + QUIET slate loses money under UM.
* Non-subject days (n=7): net **−9.3 p** — modest but not zero;
  a UM applied *unconditionally* still bleeds because chop dominates.
* TREND_V3 data window (2026-07-02 → 2026-08-20) is **7 weeks**. The 8
  audit-tabled GRIND_100 dates predate 07-02 for 7 of 8; only 07-15 is
  live-priceable. **Any number quoted here is a 1-grind-sample.**

---

## Part C — Selector false-positive rate + expected-value range

**Selector:** "day is TIER1 calendar → wear UM." What fraction of TIER1
days is the mechanism's *intended target* vs bleed?

### C.1  TIER1 day-class rates (TV3 window; n=18)

| class | count | share |
|:---|--:|--:|
| GRIND_DAY  | 4 | 22.2 % |
| MULTI_DAY  | 2 | 11.1 % |
| BOUNCE_DAY | 7 | 38.9 % |
| QUIET_DAY  | 5 | 27.8 % |

The 22.2 % TIER1 grind rate is within 1 pp of the audit's 23.3 % over
its wider n=73 window and my n=76 window (Part A) — the tail sample is
representative.

**Selector false-positive rate:**

| definition of "UM-wins" | UM-wins | selector FP-rate |
|:---|--:|--:|
| GRIND only        | 4/18 = 22.2 % | **77.8 %** |
| GRIND ∪ MULTI directional (|net|≥50 p) | 6/18 = 33.3 % | **66.7 %** |
| empirical (UM delta > 0 on fired days) | 3/10 fired days = 30.0 % | **70.0 %** |

**Selector FP range: 67 – 78 %** of TIER1 days are not UM-favourable.

### C.2  Expected-value range

Multiplying observed per-class deltas (Part B.4) by class rates in Part
C.1, all-fires basis:

| class | share | avg delta per subject-day | contribution / TIER1 day |
|:---|--:|--:|--:|
| GRIND ⚠ n=1 fired  | 22.2 % | +750.5 p → **or** +187.6 p (dividing by 4 grind days incl. zero-fire) → **or** +60–80 p (one-position live) | wide range |
| MULTI ⚠ n=2 | 11.1 % |  +0.6 p |  +0.07 p |
| BOUNCE ⚠ n=5 fired | 38.9 % |  −7.0 p |  −2.72 p |
| QUIET ⚠ n=2 fired  | 27.8 % |  −1.5 p |  −0.42 p |

**Expected UM − managed per TIER1 day** — three scenarios spanning the
bookkeeping uncertainty on the single grind day:

| grind treatment | grind contribution / TIER1 day | non-grind contribution | net expected / TIER1 day |
|:---|--:|--:|--:|
| **Upper — 07-15 fires stacked independently** | 22.2 % × +750 p = **+166.6** | −3.07 p | **+163 p / day** |
| **Middle — /days-in-class (0-fire grinds count as 0)** | 22.2 % × +187.6 = **+41.7** | −3.07 p | **+38.6 p / day** |
| **Lower — 07-15 as one-position (~+70 p)** | 22.2 % × +70 = **+15.5** | −3.07 p | **+12.4 p / day** |
| **Grind-drops-out sensitivity** (remove 07-15, keep everything else) | 0 | −3.07 p (still counting other classes) − shift | **−2.2 p / day** |

**Expected value range across scenarios: −2 p / TIER1 day → +163 p /
TIER1 day.**

Middle-case per-TIER1-day expected: **+13 → +40 p per TIER1 day** on
average, driven almost entirely by ability to catch grind days at scale.

### C.3  Sensitivity — what if 07-15 hadn't happened

Drop 07-15 entirely from the sample:

* Subject delta: +713.7 − 750.5 = **−36.8 p over 17 TIER1 days**
  = **−2.2 p / TIER1 day**.
* Non-subject delta: −9.3 p over 7 non-TIER1 TV3 days = **−1.3 p /
  non-TIER1 TV3 day**.

**Without a 07-15-scale grind in the sample, both the selector's
in-scope and out-of-scope days bleed.** The +713 p subject headline is
a one-day artefact.

---

## Consolidated verdict tables (for the operator)

### Contingency (independently rebuilt)

|                | audit  | mine   | agree? |
|:---|:---|:---|:---|
| Full days      | 139    | 140    | ~ (08-21 boundary) |
| GRIND_100 days | 8      | 8      | **identical** (same dates, same net/range) |
| FOMC grind rate | 2/4 (n=4 thin) | 2/4 (n=4 thin) | **exact match** |
| BoE grind rate | 2/3 (n=3 thin) | 2/4 (n=4 thin — audit missed 07-30) | pattern intact |
| **BIG_NEWS grind rate** | **17/73 = 23.3 %** | **17/76 = 22.4 %** | **reproduced** |
| PRE_BIG grind rate | 3/40 = 7.5 % | 3/41 = 7.3 % | reproduced |

### UM pricing on live data

|                                    | value | thin? |
|:---|--:|:---|
| TV3 fires priceable window | 2026-07-02 → 2026-08-20 (7 weeks) | **yes — narrow** |
| Grind-100 dates inside TV3 window | 1 (2026-07-15) | **⚠ n=1** |
| TIER1 dates inside TV3 window | 18 | thin per-class |
| Σ UM−managed on subject days (all-fires basis) | +713.7 p | 07-15 alone = +750 p |
| Σ UM−managed on subject days ex-07-15 | −36.8 p | 17 days |
| Σ UM−managed on non-subject TV3 days | −9.3 p | n=7 days |
| One-position live equivalent for 07-15 | +60–80 p | approx |

### Selector properties (TIER1 → wear UM)

|                                | value |
|:---|:---|
| TIER1 grind rate (mine, full window) | 17/76 = 22.4 % |
| TIER1 grind rate (TV3 sub-window)    | 4/18 = 22.2 % |
| False-positive rate (non-grind TIER1) | 66.7 – 77.8 % |
| Empirical UM-wins rate on TIER1 fired days | 3/10 = 30 % |
| Expected UM−managed per TIER1 day (range) | **−2 p to +163 p** |
| Expected value ex-07-15 shock | **≈ −2 p / day** |

---

## Every load-bearing thin-cell flag

| cell | n | flag |
|:---|--:|:---|
| FOMC n=4 in candle set | 4 | ⚠ thin |
| BoE n=3 audit / 4 mine | 3–4 | ⚠ thin |
| All Section 4c per-major tables | 4–8 | ⚠ thin |
| POST_BIG | 15–17 | ⚠ thin |
| CLEAR | 8–9 | ⚠ thin |
| Grind-100 days in TV3 window | **1** | ⚠⚠ **critical thinness** |
| TV3 fires per subject day | 0–13 | ⚠ variable |
| GRIND subject days with fires | 1 of 4 | ⚠ thin |
| MULTI subject days | 2 | ⚠ thin |
| BOUNCE subject days with fires | 5 of 7 | ⚠ thin |
| QUIET subject days with fires | 2 of 5 | ⚠ thin |
| Non-subject TV3 days | 7 | ⚠ thin |

Every downstream number in this report inherits at least one thin cell.
Verdict is the operator's from the tables.

---

## Artefacts

Under `/opt/tradingbot/reports-public/tier3_um_pricing_20260822/`:

* `tier3_partA.py` — TIER1-list rebuild from Finnhub cache.
* `tier3_classify.py` — fresh zigzag + day-classification.
* `tier3_xtab.py` — news × day cross-tab.
* `tier3_um_price.py` — UM-bracket bar-walk.
* `tier3_tier1_dates.json` — my TIER1 date map (per-date labels).
* `tier3_days_class.json` — my per-day classification (all 177 CSVs).
* `tier3_xtab.json` — mine vs audit cross-tab.
* `tier3_um_prices.json` — per-day, per-fire UM walks & deltas.
* This report: `REPORT.md`.
