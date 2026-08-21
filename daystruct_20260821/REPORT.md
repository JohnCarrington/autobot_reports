# GBPUSD Day-Structure Audit — 2026-08-21

**Investigate-only.** Tests the operator's stated market model against the
2026 archive. No code changes, no restarts.

---

## 0. Definitions (stated once, applied uniformly)

* **Prices:** candles are stored ×10 000 (e.g. `13471.5 = 1.34715`), so raw
  units = pips throughout. `1p = 0.0001`.
* **Trading day:** UTC `00:00` → `23:55` of the calendar date, using rows
  from that date's CSV. Partial files (mostly Sun-evening + Fri late close)
  are flagged and excluded from headline percentages.
* **Zigzag / swing method:** applied to **5-min closes only** (not H/L).
  Walking forward from the first close, maintain a running swing extreme.
  When the current close reverses from the running extreme by
  `REV_PIPS = 15 p`, the running extreme becomes a confirmed pivot and
  direction flips. Final running extreme is accepted as a tail pivot.
  Sensitivity checked at `REV_PIPS = 10 p` and `REV_PIPS = 20 p`.
* **Leg / run:** segment from one pivot to the next. Magnitude
  `= |close_end – close_start|` in pips. A leg qualifies as a **RUN** iff
  magnitude `≥ 40 p`.
* **Bounce / Continuation label:** at the run's start pivot, take the net
  move from that day's first 5-min close to the pivot price.
  * `net ≥ 20 p AGAINST run direction` → **BOUNCE**
  * `net ≥ 20 p WITH run direction` → **CONTINUATION**
  * otherwise → **AMBIGUOUS** (pivot close to day-open)
* **Grind test (per day):** `GRIND_DAY` iff
  `day_range ≥ 60 p` AND `|day_net_move| ≥ 0.70 × day_range`.
  A `GRIND_100` sub-flag is set when `|net| ≥ 100 p`.
* **Day classification:**
  * `QUIET_DAY` — 0 runs ≥ 40 p
  * `BOUNCE_DAY` — 1 or 2 runs, not a grind
  * `MULTI_DAY` — 3+ runs
  * `GRIND_DAY` — passes grind test (overrides BOUNCE)
* **News-class (Section 4):** a **BIG_NEWS** day is one containing a
  TIER1 event (NFP, FOMC/Fed decision, US CPI, US GDP, US PPI, US Retail,
  ISM Manf, ISM Svc, BoE Decision, UK CPI, UK GDP, UK Unemployment,
  UK Retail — exact Finnhub `event` strings listed in
  `section4b_calendar_tier1.json`). `PRE_BIG` = next weekday is BIG_NEWS,
  `POST_BIG` = prev weekday was, otherwise `CLEAR`.
* **Capture window (Section 5):** a signal counts against a run iff
  `timestamp_open ∈ [run.start_ts, run.end_ts]` AND signal direction
  matches run direction (`BUY↔up`, `SELL↔dn`).
* **Fires inside known-contaminated windows are NOT excluded** from
  capture stats — a run either got traded or it didn't (per instruction).

---

## Data coverage found

### Candles — `/opt/tradingbot/data/candles/GBPUSD/*.csv`

* **177 files**, 2026-01-01 → 2026-08-21.
* **Full-day files (≥ 200 rows): 139**. Partial: 38 (mostly 24 Sun-evening
  files that start 17:00, plus a few Fri late-close files and the
  currently-running 2026-08-21 partial).
* **17 missing weekdays**:
  `2026-03-02, 03-03, 03-04, 03-05, 03-06, 03-09, 03-10, 03-11, 03-12,
  03-13, 03-16, 03-17, 03-18, 03-19, 03-20, 05-15, 07-13`.
  The bulk is a 3-week March gap.
* Two timestamp formats observed (`"…space…+00:00"` vs `"…T…+00:00"`);
  parser handles both.

### News calendar — Finnhub cache `/opt/tradingbot/cache/news_state_finnhub_*.json`

* **196 unique dates** covered, 2026-01-01 → 2026-08-21. Every date in the
  full audit range has a cache file, except **6 weekdays missing**:
  `2026-06-04, 06-05, 07-13, 07-23, 07-30, 07-31`.
* Historical high-impact event backfill IS present back to January
  (`news_state_finnhub_backfill_*.json`, 136 files). So Section 4 covers
  the full window — no coverage caveat.

### signal_log

* `/opt/tradingbot/logs/signal_log.jsonl` — 1 410 rows, dates
  **2026-03-30 → 2026-08-21** (98 unique dates). GBPUSD dominates (1 187 rows).
* `/opt/tradingbot/data/signal_log_backfill.jsonl` — 338 rows over
  19 dates (edges of the same period).
* Sections 5 and 6 are **restricted to 2026-03-30 → 2026-08-21** (~5 months).
  Everything before that has no bot-trade data.

Full recon JSON: `section0_recon.json`.

---

## Section 1 — Run detection per day

* **177 days analysed** (139 full + 38 partial).
* Row-count join: 177 candle files, 241 qualifying runs.

### Runs-per-day count histogram (full days only, n = 139)

| n_runs | days | % |
|-----:|-----:|-----:|
| 0 |  24 | 17.3% |
| 1 |  53 | 38.1% |
| 2 |  32 | 23.0% |
| 3 |  18 | 12.9% |
| 4 |   9 |  6.5% |
| 5 |   1 |  0.7% |
| 6 |   1 |  0.7% |
| 9 |   1 |  0.7% |

### Sensitivity of the count

At `REV_PIPS = 10 p` **50 / 177** days shift count; at `REV_PIPS = 20 p`
**32 / 177** shift. So the count is **not fragile in the 10–20 p reversal
band** but is somewhat sensitive at the extremes — expect ~±20 % shifts
in the tails if the reversal threshold moves.

### GRIND_100 days (net move ≥ 100 p, ratio ≥ 0.70)

| date | wd | net (p) | range (p) |
|:-----|:--:|-------:|-------:|
| 2026-01-05 | Mon | +130.8 | 144.8 |
| 2026-01-23 | Fri | +136.8 | 163.8 |
| 2026-04-07 | Tue | +169.9 | 199.0 |
| 2026-04-13 | Mon | +120.4 | 130.4 |
| 2026-04-30 | Thu | +111.9 | 158.9 |
| 2026-06-17 | Wed | −125.7 | 175.9 |
| 2026-06-18 | Thu | −110.7 | 131.9 |
| 2026-07-15 | Wed | +142.1 | 177.5 |

**8 grind-100 days in 139 full days = 5.8 %.**

Per-day full inventory (with run start times, directions, magnitudes,
labels): `section1_days.jsonl` (177 lines).

---

## Section 2 — Model fit

### (a) Runs-per-day distribution

Model says **mode = 1–2 runs**. Actual: **1-run days = 38.1 % (single
peak), 1-or-2 combined = 61.2 %**. Model confirmed as a modal claim;
BUT the tail is heavier than "sometimes ≥ 3" — 21.6 % of days have 3+ runs.

### (b) First-run and second-run start-time histogram

The naive first-run bucket is contaminated by the artificial `00:00`
day-start (28/115 first runs sit at 00:00, i.e. the zigzag's first pivot
is the day-open bar). Two versions reported:

* **naive** ("first run of the day"): see `section2_modelfit.json`
* **operator-relevant** ("first run whose start ≥ 06:00 UTC"): below.

**First-London-run 30-min bucket histogram** (n = 96 full days that have
a first-London-run):

| bucket | count |
|:------:|------:|
| 06:00 |  4 |
| 06:30 |  7 |
| 07:00 |  6 |
| 07:30 |  7 |
| 08:00 |  5 |
| **08:30** | **11** |
| 09:00 |  3 |
| **09:30** |  **9** |
| 10:00 |  3 |
| **10:30** |  **9** |
| 11:00 |  3 |
| 11:30 |  3 |
| 12:00 |  4 |
| 12:30 |  5 |
| 13:00 |  5 |
| 13:30 |  2 |

**Anchor test** vs the operator's model {08, 10, 11, 12} for first-London-run:

| tolerance | hits | pct |
|:---------:|:----:|:---:|
| ±15 min   | 26 / 96 | **27.1 %** |
| ±45 min   | 57 / 96 | **59.4 %** |

Baseline (uniform in 06:00–13:00, 4 anchors × 30-min windows) = 4/14 = 28.6 %.
**±15 min hit rate is at chance.** ±45 min covers ~71 % of the 06:00-13:00
window, so 59 % is BELOW the random baseline — the model's on-the-hour
anchors are **not evidence-supported**.

Actual peaks are **08:30, 09:30, 10:30** (the London half-hour open),
not the operator's stated on-the-hour anchors.

**Second-run (any run whose start ≥ 13:00 UTC after the first-London-run)**
histogram (n = 30 days):

| bucket | 13:00 | 13:30 | **14:00** | 14:30 | 15:00 | 15:30 | 16:30 | 17:00 | 18:00 | 19:00 |
|:-----:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|
| count | 3 | 3 | 7 | 5 | 5 | 1 | 1 | 1 | 2 | 2 |

**PM-anchor {14, 15, 16} hit rates:** ±15 min 9/30 = **30 %**;
±45 min 22/30 = **73 %**. Both approximately at their uniform baselines
(29 % and 70 % respectively) — **the PM anchor also fails a strong test**.
14:00 is the modal bucket at 7 hits, so 14:00 as a **soft** anchor is real.

### (c) Magnitude distribution (241 qualifying runs, any-hour, full+partial)

| bin (pips) | count | % |
|:----------:|-----:|-----:|
|  40 – 49 | 93 | 38.6 % |
|  50 – 59 | 50 | 20.7 % |
|  60 – 69 | 40 | 16.6 % |
|  70 – 79 | 31 | 12.9 % |
|  80 – 99 | 16 |  6.6 % |
| 100 – 149 |  9 |  3.7 % |
| 150 +    |  2 |  0.8 % |

`p25 = 46.6 p, p50 = 54.5 p, p75 = 68.1 p, p90 = 81.0 p, max = 176.1 p`

**Median run = 54.5 p, IQR 47–68 p.** Operator's "40–60 p typical"
straddles the median — confirmed as the modal band. Runs > 80 p are
uncommon (~11 %); > 100 p rare (~4.5 %).

**Bounce vs Continuation labels (all 241 runs):** 86 BOUNCE, 26
CONTINUATION, 129 AMBIGUOUS. Where labelable: **bounces outnumber
continuations 3.3 : 1** — consistent with the operator's mean-revert
default.

### (d) Day classification (full days only, n = 139)

| day_class    | n  | %    |
|:-------------|--:|-----:|
| BOUNCE_DAY   | 67 | 48.2 % |
| GRIND_DAY    | 24 | 17.3 % |
| QUIET_DAY    | 24 | 17.3 % |
| MULTI_DAY    | 24 | 17.3 % |

Model claim "BOUNCE_DAY dominates" — **confirmed** but not overwhelming
(48 %, not > 60 %). Roughly one day in six is QUIET (below-40 p range) and
one day in six is a grind — the "1–2 bounce" playbook fits ~48 % of days
cleanly.

Section 2 checkpoints: `section2_modelfit.json`, `section2b_london_anchors.json`.

---

## Section 3 — Weekday cut

### Per-weekday summary (full days only)

| Day | n  | runs mean | runs median | range mean | range median | BOUNCE | GRIND | QUIET | MULTI |
|:---:|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| Mon | 25 | 1.72 | 1 | 82.3 p | 70.2 p | 14 | 6 | 3 | 2 |
| Tue | 29 | 1.62 | 1 | 77.3 p | 66.4 p | 12 | 2 | 8 | 7 |
| Wed | 29 | 1.52 | 1 | 83.9 p | 78.0 p | 13 | 7 | 4 | 5 |
| Thu | 28 | 1.96 | 2 | 87.7 p | 83.0 p | 14 | 4 | 3 | 7 |
| Fri | 28 | 1.36 | 1 | 76.3 p | 73.7 p | 14 | 5 | 6 | 3 |

Cell sizes all ≥ 25 — no thin cells.

**Signatures:**

* **Thursday** carries the biggest range (mean 88 p, median 83 p) and the
  most runs (median 2) — this is where the news calendar tends to live
  (BoE, US GDP, UK GDP all cluster on Thursdays in this window).
* **Friday** is the quietest at the median (runs median 1, range median
  74 p, but 6/28 = 21 % QUIET) — the "Friday afternoon dies" trope holds
  only mildly.
* **Wednesday** has the highest grind rate (7/29 = 24.1 %) — FOMC, UK CPI
  and US CPI/PPI cluster there.
* **Tuesday** is the weekday most likely to go QUIET (8/29 = 27.6 %).

### First-London-run 30-min bucket by weekday

| bucket | Mon | Tue | Wed | Thu | Fri |
|:------:|:-:|:-:|:-:|:-:|:-:|
| 06:00  | 1 | 0 | 1 | 1 | 1 |
| 06:30  | 1 | 1 | 0 | 4 | 1 |
| 07:00  | 1 | 1 | 0 | 1 | 3 |
| 07:30  | 1 | 1 | 4 | 1 | 0 |
| 08:00  | 3 | 1 | 0 | 1 | 0 |
| 08:30  | 2 | 4 | 1 | 3 | 1 |
| 09:00  | 0 | 1 | 1 | 0 | 1 |
| 09:30  | 2 | 1 | 3 | 1 | 2 |
| 10:00  | 0 | 0 | 3 | 0 | 0 |
| 10:30  | 1 | 2 | 1 | 1 | 4 |
| 11:00  | 0 | 1 | 1 | 0 | 1 |
| 11:30  | 1 | 1 | 0 | 1 | 0 |
| 12:00  | 0 | 3 | 1 | 0 | 0 |
| 12:30  | 1 | 0 | 1 | 1 | 2 |
| 13:00  | 1 | 2 | 1 | 1 | 0 |
| 13:30  | 0 | 0 | 1 | 1 | 0 |
| 14:00  | 0 | 1 | 1 | 0 | 0 |
| 14:30  | 2 | 0 | 0 | 3 | 0 |
| 16:30  | 0 | 0 | 1 | 0 | 0 |
| 17:00  | 0 | 0 | 0 | 1 | 0 |
| TOTAL  | 17 | 20 | 22 | 21 | 16 |

Individual cell sizes here are ≤ 4 — **any single bucket-day cell is thin**;
patterns should be read only where two adjacent cells reinforce each
other. Consistent signals:

* **Fri 07:00–07:30** cluster (3+0) and **Fri 10:30** (4) — Friday
  first-run tends to hit UK-open or the US pre-open block.
* **Wed 07:30 / 09:30 / 10:00** — Wed morning runs cluster off London-open
  through UK-data hour.
* **Thu 06:30** (4) — Thursday is disproportionately an early-start day.

Section 3 checkpoint: `section3_weekday.json`.

---

## Section 4 — Calendar mapping (Finnhub, TIER1 filter)

**Coverage:** 108 HIGH-impact GBP/USD event-days in the cache 2026-01-01…08-21,
83 of which contain a TIER1 event (list above). 73 of those fall inside our
full-day candle set. 4 full days are missing news files (`2026-06-04,
06-05, 07-30, 07-31`) — those are classified `CLEAR` by default and may be
mis-classified, though none of them appear in the majors tables below.

### (a-b) News-class × day-class cross-tab (full days, n = 139)

| news / day | BOUNCE_DAY | GRIND_DAY | QUIET_DAY | MULTI_DAY | TOTAL |
|:-----------|--:|--:|--:|--:|--:|
| BIG_NEWS   | 30 | 17 | 10 | 16 | 73 |
| PRE_BIG    | 22 |  3 | 10 |  5 | 40 |
| POST_BIG   |  9 |  3 |  4 |  1 | 17 |
| CLEAR      |  6 |  1 |  0 |  2 |  9 |

Row percentages (day-class within each news-class):

| news / day | BOUNCE | GRIND | QUIET | MULTI |
|:-----------|--:|--:|--:|--:|
| BIG_NEWS   | 41.1 % | **23.3 %** | 13.7 % | 21.9 % |
| PRE_BIG    | 55.0 % |  7.5 %     | 25.0 % | 12.5 % |
| POST_BIG   | 52.9 % | 17.6 %     | 23.5 % |  5.9 % |
| CLEAR      | 66.7 % | 11.1 %     |  0.0 % | 22.2 % |

**Mean day-range by news-class:** BIG_NEWS 84 p, PRE_BIG 75 p, POST_BIG
77 p, CLEAR 96 p. CLEAR n=9 is a thin cell — treat with caution.

**Model verdict on grind clustering in PRE_BIG:** **FALSIFIED**.
Grind rate is 23.3 % on BIG_NEWS days themselves, only 7.5 % on PRE_BIG
days. Model verdict on disrupted BIG_NEWS/POST_BIG: partially supported —
BIG_NEWS has elevated GRIND and MULTI (17 + 16 = 45 % non-bounce) but
POST_BIG looks closer to normal.

### (c) Per-major event tables

**NFP** (n = 6):
| date | wd | class | range | net | n_runs |
|:-----|:--:|:------|--:|--:|--:|
| 2026-01-09 | Fri | BOUNCE_DAY | 58.4 | −33.5 | 1 |
| 2026-02-11 | Wed | MULTI_DAY | 102.9 | −33.8 | 3 |
| 2026-04-03 | Fri | BOUNCE_DAY | 58.1 | −30.0 | 1 |
| 2026-05-08 | Fri | GRIND_DAY | 90.0 | +78.8 | 1 |
| 2026-07-02 | Thu | MULTI_DAY | 110.6 | +59.3 | 4 |
| 2026-08-07 | Fri | BOUNCE_DAY | 74.5 | +36.3 | 1 |

NFP days average ~82 p range, split evenly between BOUNCE_DAY and
active (MULTI/GRIND).

**FOMC** (n = 4 in candle set):
| 2026-01-28 | Wed | MULTI_DAY | 90 | +44 | 4 |
| 2026-04-29 | Wed | QUIET_DAY | 69 | −39 | 0 |
| 2026-06-17 | Wed | **GRIND_DAY** | 176 | −126 | 2 |
| 2026-07-29 | Wed | **GRIND_DAY** | 108 | +80 | 1 |

Half FOMC days are grinds. Full 2026 range 69–176 p — a wide dispersion.
FOMC is not a reliable BOUNCE_DAY.

**US CPI** (n = 6): 4 BOUNCE_DAY, 1 MULTI_DAY, 0 GRIND. Average range 76 p —
US CPI looks more like a normal 1-run bounce day than a chaotic one.

**BoE** (n = 3): 1 MULTI, 2 GRIND. Ranges 124–159 p. BoE = big-range,
directional. Almost never a clean 1-bounce day.

**UK CPI** (n = 8): 4 BOUNCE, 3 GRIND, 1 QUIET. Range 40–176 p — bimodal:
either a decisive grind or a normal bounce.

**UK GDP** (n = 7): 4 BOUNCE, 1 MULTI, 1 GRIND, 2 QUIET. Least disruptive
of the majors.

**US GDP** (n = 6): 4 BOUNCE, 1 MULTI, 1 GRIND. Average net move +42 p —
US GDP tends to produce clean directional bounces.

**ISM_MFG** (n = 7): 3 BOUNCE, 2 MULTI, 2 GRIND. **ISM_SVC** (n = 7):
4 BOUNCE, 2 GRIND, 1 QUIET — decisive but usually contained.

**US_PPI** (n = 8): 2 QUIET, 2 GRIND, 3 MULTI, 1 BOUNCE. PPI is the
messiest majors category — often either dead or highly two-sided.

**UK_UNEM** (n = 7): 3 MULTI, 2 QUIET, 1 BOUNCE, 1 GRIND — clusters as
either an active MULTI or a QUIET.

**UK_RETAIL** (n = 7): 3 GRIND, 2 BOUNCE, 2 QUIET. Friday UK Retail is a
grind risk.

Section 4 checkpoint: `section4b_calendar_tier1.json` (has `tier1_days`
and `news_class_by_date` maps for downstream joins).

---

## Section 5 — Bot capture vs offered

**Window:** 2026-03-30 → 2026-08-21 (signal_log coverage).
**Row counts joined:** 1 326 GBPUSD signals (main + backfill, deduped by
`(ts_open, strategy, direction, entry)`) against **131 qualifying runs**
in the window.

**Note:** signal_log has 1 187 GBPUSD entries from the main jsonl; the
backfill adds ~139 to reach 1 326. This includes strategies not seen in
the first `top strategies` inventory (RANGE_REVERSION 80, LIQUIDITY_SWEEP
24, UNKNOWN 31, GBPUSD_TREND_CONT_L 13, GBPUSD_CONFIRMATION_FALLBACK_S 13).

### Headline

|  | value |
|:---|---:|
| Runs in scored window | 131 |
| Runs with ≥ 1 directional in-window fire | 62 (47.3 %) |
| Runs with **zero** directional fires | **69 (52.7 %)** |
| Total offered magnitude | 8 062 p |
| Total banked (directional in-window sum of `pnl_pips`) | **1 321 p** |
| Overall in-window capture ratio | **16.4 %** |

Capture-ratio percentiles (all 131 runs): p10 = 0, p25 = 0, p50 = 0,
p75 = 0.27, p90 = 0.52, max = 1.03.
(Restricted to the 51 captured & pnl-positive runs: p25 = 0.19,
p50 = 0.36, p75 = 0.54, p90 = 0.77 — so **when captured, the median run
banks about a third of its magnitude**.)

### By mode family (dominant family of the fires in that run)

| family | runs | banked | offered | ratio |
|:------|--:|--:|--:|--:|
| trend  | 25 | 547.6 p | 1 688.5 p | 32.4 % |
| bounce | 19 | 499.5 p | 1 207.6 p | 41.4 % |
| other (RANGE_REVERSION / LIQUIDITY_SWEEP / UNKNOWN / …) | 12 | 233.2 p | 812.1 p | 28.7 % |
| news (BRIEFING_* / *_SWEEP) | 6 | 40.7 p | 381.6 p | **10.7 %** |

**Bounce family carries the highest per-run capture ratio**; the news
family fires heavily but banks almost nothing per run.

### By day-class

| day_class   | runs | captured | banked | offered | ratio |
|:------------|--:|--:|--:|--:|--:|
| BOUNCE_DAY  | 70 | 38 |   826.8 p | 4 116.1 p | 20.1 % |
| GRIND_DAY   | 25 | 13 |   308.0 p | 1 919.9 p | 16.0 % |
| MULTI_DAY   | 36 | 11 |   186.2 p | 2 026.0 p |  **9.2 %** |

MULTI_DAY (many runs) is where the bot loses relative to the opportunity —
9 % capture ratio despite the fires being available. On BOUNCE_DAY (the
target day-shape) capture is 20 %.

### By run-start 30-min UTC bucket (buckets with ≥ 3 runs shown)

| bucket | runs | captured | banked (p) | offered (p) | ratio |
|:------:|--:|--:|--:|--:|--:|
| 00:00 | 21 | 15 | 366.8 | 1 418.6 | **25.9 %** |
| 06:30 |  5 |  3 | 126.6 |   311.7 | **40.6 %** |
| 07:30 |  3 |  2 |  40.3 |   149.6 | 26.9 % |
| 08:30 |  7 |  4 |  53.2 |   357.6 | 14.9 % |
| 09:00 |  3 |  3 |  44.1 |   140.2 | 31.5 % |
| 09:30 |  4 |  3 |  46.1 |   221.8 | 20.8 % |
| 10:30 |  7 |  4 | 120.9 |   507.8 | 23.8 % |
| 11:00 |  3 |  1 |   0.0 |   194.3 |  0.0 % |
| 11:30 |  5 |  2 |  −1.3 |   261.3 | −0.5 % |
| 12:00 |  4 |  1 |  11.7 |   248.9 |  4.7 % |
| 12:30 |  4 |  3 |  15.3 |   223.1 |  6.9 % |
| 13:00 |  6 |  2 |  41.1 |   382.3 | 10.7 % |
| 13:30 |  4 |  2 |  −4.3 |   239.5 | −1.8 % |
| **14:00** |  6 |  1 |   0.3 |   345.7 |  **0.1 %** |
| 14:30 |  8 |  5 | 102.8 |   505.0 | 20.4 % |
| **15:00** |  7 |  1 |  29.8 |   465.0 |  **6.4 %** |
| 17:00 |  4 |  0 |   0.0 |   223.9 |  **0.0 %** |

**PM window pattern is explicit:** 11:00 – 14:00 UTC and again 17:00+
have near-zero capture ratios. The bot's afternoon coverage collapses
exactly where the operator's model puts the second-bounce anchor.

### Misses (zero-fire runs, n = 69)

* By day-class: BOUNCE_DAY 32, MULTI_DAY 25, GRIND_DAY 12.
* Average missed magnitude: **57.6 p**. Total missed: **3 972 p**.
* By start hour (top 6): **14 h (8), 13 h (6), 15 h (6), 11 h (5), 10 h (4),
  17 h (4)** — a clear PM-drought cluster in the 10:00–15:00 and 17:00+
  UTC windows. First-London-morning misses (06 h–09 h) are 9 total —
  low.

The miss profile is **not overnight and not global** — it's an
**afternoon-London / New-York-open coverage gap**.

Section 5 checkpoints: `section5_capture.json`, `section5_runs.jsonl`
(one JSON row per scored run).

---

## Section 6 — 60 % ladder-ride bound

If the bot had banked 60 % of every qualifying run's magnitude (a
generous but realistic ladder-ride, not a lookahead-perfect exit), the
monthly total vs what was actually banked:

| Month | Days | Runs | Offered (p) | 60 % bound (p) | Banked (p) | **Gap (p)** |
|:-----|--:|--:|--:|--:|--:|--:|
| 2026-03 |   2 |   5 |   318.2 |   190.9 |     0.0 |   190.9 |
| 2026-04 |  29 |  38 | 2 315.1 | 1 389.1 | −168.2 | 1 557.2 |
| 2026-05 |  23 |  27 | 1 527.8 |   916.7 |    2.3 |   914.4 |
| 2026-06 |  25 |  28 | 1 733.1 | 1 039.9 | −111.6 | 1 151.4 |
| 2026-07 |  25 |  26 | 1 721.6 | 1 033.0 |  −67.3 | 1 100.3 |
| 2026-08 |  18 |   7 |   446.2 |   267.7 |  −92.5 |   360.2 |
| **TOTAL** | **122** | **131** | **8 062.0** | **4 837.2** | **−437.2** | **5 274.4** |

**Prize size:** the exit-stack / afternoon-coverage gap represents
**≈ 5 274 p over 122 trading days (~ 1 060 p / month) at the 60 % bound**.
Actual banked is negative (−437 p) — the bot is not just missing runs,
its cumulative pnl on the runs it DOES touch is < 0 across the window.

Section 6 checkpoint: `section6_bound.json`.

---

## Model verdict — one paragraph per claim

* **"Most days deliver 1–2 bounces of 40–60 p"** — **CONFIRMED as modal**.
  61.2 % of full days are 1-or-2-run days; median run is 54.5 p; IQR 47–68 p.
  Not overwhelming (48 % strictly BOUNCE_DAY, 17 % MULTI, 17 % QUIET, 17 % GRIND).
* **"First run at ~08:00 / 10:00 / 11:00 / 12:00 UTC anchors"** —
  **not supported by a strong test.** At ±15 min, hit rate 27 % ≈ uniform
  baseline 29 %. Actual peaks are the London half-hours (08:30, 09:30,
  10:30), not the on-the-hour anchors. Widening to ±45 min still
  under-performs the coverage-size baseline.
* **"Second run at ~14:00 / 15:00 / 16:00"** — 14:00 is the empirical
  modal PM bucket (7 hits), but the anchor test at ±15 min (30 %) is at
  the ~29 % chance baseline. Soft evidence for 14:00; no evidence for
  15:00 or 16:00 as anchors.
* **"Slow-grind days ~ ahead of big news"** — **FALSIFIED**. Grind rate
  is 23 % on BIG_NEWS days themselves vs 7.5 % on PRE_BIG. Grinds
  cluster ON the news day, not the day before.
* **"Big-news days are disrupted"** — partially supported. BIG_NEWS days
  are 23 % GRIND + 22 % MULTI = 45 % non-clean-bounce, vs 20 % on PRE_BIG.
* **"Post-big-news days sometimes still disrupted"** — weak: POST_BIG
  matches BIG_NEWS on GRIND rate (17.6 vs 23.3 %) but has only 6 % MULTI.

### Weekday signatures worth naming

* Thursday is the most active weekday (mean 2 runs, mean range 88 p) —
  news-heavy day.
* Wednesday is the most grind-prone (24 % grind rate).
* Tuesday is the most likely to go QUIET (28 %).
* Friday medians look normal but tail probability of QUIET (21 %) is
  the second-highest.

### Bot capture — headline gap

* **69 / 131 = 53 % of qualifying runs got zero directional fires.**
* Where fires DID land, median in-window capture ratio was **35.6 %**.
* Total exit-stack gap at 60 % ladder-ride: **~ 5 274 p over 122
  days = ~ 1 060 p / month**.
* The gap is concentrated in the PM window (11:00 – 15:00 UTC and
  17:00 +) and on MULTI_DAY (multi-run days).

---

## Artefacts

All under `/opt/tradingbot/reports-public/daystruct_20260821/`:

* `section0_recon.json` — data coverage
* `section1_days.jsonl` — one JSON per day (177 rows), including full
  `runs[]` array
* `section2_modelfit.json` + `section2b_london_anchors.json`
* `section3_weekday.json`
* `section4b_calendar_tier1.json` (also `section4_calendar.json` for
  the untightened HIGH-impact-only version)
* `section5_capture.json` + `section5_runs.jsonl` (per-run capture detail)
* `section6_bound.json`
* This report: `REPORT.md`
