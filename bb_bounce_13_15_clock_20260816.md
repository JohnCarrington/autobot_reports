# Level-bounce clock check — 13:00 vs 15:00 UTC clustering
**Corpus: 2026-03-23 → 2026-08-14 (121 sessions, 5m archive)**
**Levels: `bb_pd_gate.compute_pivots_only` (Sunday-anchored D1 cache). BB: `gbpusd_level_bounce._bb_20_2`. Neither reimplemented.**
**Event set: `/tmp/bb_level_events.json` (14,717 events; produced by the acceptance-passed detector — see `bb_level_coincidence_acceptance_20260814.md`).**

## TL;DR
- The **13:00 UTC bounce cluster is real** in the turn-rate signal, but the count is thin (11 OUTER-COINC events in the 13:00 5-min bucket over 121 days; 6 turned ≥15p).
- The **15:00 UTC bounce cluster is not visible** in this measurement. The 14:45–15:15 half-hour has 18 OUTER-COINC events and 1 turn (5.6%) — below the whole-session median. The neighbouring 14:30 bucket runs ~31%; the visible spike is one bucket earlier than the operator flagged, not at 15:00.
- Only **5 distinct days** across the corpus produce a turning OUTER-COINC bounce in either window (4 at 13:00, 1 at 15:00, 0 in both). All 13:00 turns are BUY-off-S1/S2; the single 15:00 turn is SELL-off-R2.
- **News-slot hypothesis is not supported by the data available.** Of the 3 13:00 bounce days with a news cache, 1 had a 12:30 UTC US release (Current Account, MED), 0 had a 12:30 HIGH release; baseline is 50% (any) / 30% (HIGH) — bounce-day rate is *below* baseline. The single 15:00 bounce is a pre-cache-coverage day.

Sample sizes throughout are extremely thin. The 15-minute buckets average 9.5 OUTER-COINC events/bucket over 121 sessions. Read all rates as descriptive.

---

## 1. 15-min bucket histogram (07:00–20:55 UTC)

Definitions (from the detector — kept verbatim):
- **Touch**: bar extreme within 2p of the level.
- **COINC**: touch + band edge within 3p of the same level. Outer (R1–R3, S1–S3) and P are separate cohorts, never pooled.
- **turn15**: reversal MFE (level − low for SELL, high − level for BUY) ≥ 15p within the next 12 5m bars, before any bar closes past the level.

### OUTER cohort (R1–R3, S1–S3)
| bucket | n | turn15 | rate |
|:------:|:-:|:------:|:----:|
| 07:00 | 17 | 3 | 0.18 |
| 07:15 | 8 | 1 | 0.12 |
| 07:30 | 8 | 0 | 0.00 |
| 07:45 | 12 | 3 | 0.25 |
| 08:00 | 14 | 3 | 0.21 |
| 08:15 | 10 | 1 | 0.10 |
| 08:30 | 15 | 0 | 0.00 |
| 08:45 | 14 | 1 | 0.07 |
| 09:00 | 14 | 3 | 0.21 |
| 09:15 | 10 | 3 | 0.30 |
| 09:30 | 7 | 1 | 0.14 |
| 09:45 | 11 | 5 | **0.45** |
| 10:00 | 9 | 2 | 0.22 |
| 10:15 | 2 | 0 | 0.00 |
| 10:30 | 11 | 0 | 0.00 |
| 10:45 | 15 | 4 | 0.27 |
| 11:00 | 12 | 4 | 0.33 |
| 11:15 | 13 | 3 | 0.23 |
| 11:30 | 17 | 5 | 0.29 |
| 11:45 | 11 | 4 | 0.36 |
| 12:00 | 11 | 2 | 0.18 |
| 12:15 | 4 | 2 | 0.50 |
| 12:30 | 9 | 6 | **0.67** |
| **12:45** | 10 | 1 | 0.10 |
| **13:00** | 11 | 6 | **0.55** |
| **13:15** | 14 | 1 | 0.07 |
| 13:30 | 8 | 0 | 0.00 |
| 13:45 | 8 | 1 | 0.12 |
| 14:00 | 10 | 1 | 0.10 |
| 14:15 | 5 | 0 | 0.00 |
| 14:30 | 13 | 4 | 0.31 |
| **14:45** | 11 | 1 | 0.09 |
| **15:00** | 6 | 0 | 0.00 |
| **15:15** | 1 | 0 | 0.00 |
| 15:30 | 3 | 0 | 0.00 |
| 15:45 | 9 | 0 | 0.00 |
| 16:00 | 13 | 3 | 0.23 |
| 16:15 | 13 | 1 | 0.08 |
| 16:30 | 11 | 2 | 0.18 |
| 16:45 | 8 | 0 | 0.00 |
| 17:00 | 11 | 1 | 0.09 |
| 17:15 | 7 | 0 | 0.00 |
| 17:30 | 6 | 0 | 0.00 |
| 17:45 | 10 | 0 | 0.00 |
| 18:00 | 12 | 0 | 0.00 |
| 18:15 | 14 | 2 | 0.14 |
| 18:30 | 8 | 1 | 0.12 |
| 18:45 | 2 | 0 | 0.00 |
| 19:00 | 3 | 0 | 0.00 |
| 19:15 | 10 | 0 | 0.00 |
| 19:30 | 4 | 0 | 0.00 |
| 19:45 | 6 | 0 | 0.00 |
| 20:00 | 3 | 0 | 0.00 |
| 20:15 | 7 | 0 | 0.00 |
| 20:30 | 10 | 0 | 0.00 |
| 20:45 | 12 | 7 | **0.58** |

**OUTER baseline (all 56 buckets):** n median = 10.0, mean = 9.5. turn15 median = 1, mean = 1.57. Turn rate median across buckets ≈ 0.14.

### P cohort
| bucket | n | turn15 | rate |
|:------:|:-:|:------:|:----:|
| 07:00 | 11 | 3 | 0.27 |
| 07:15 | 13 | 2 | 0.15 |
| 07:30 | 15 | 0 | 0.00 |
| 07:45 | 18 | 0 | 0.00 |
| 08:00 | 17 | 4 | 0.24 |
| 08:15 | 8 | 0 | 0.00 |
| 08:30 | 10 | 0 | 0.00 |
| 08:45 | 17 | 1 | 0.06 |
| 09:00 | 13 | 0 | 0.00 |
| 09:15 | 11 | 1 | 0.09 |
| 09:30 | 7 | 1 | 0.14 |
| 09:45 | 11 | 3 | 0.27 |
| 10:00 | 12 | 1 | 0.08 |
| 10:15 | 16 | 1 | 0.06 |
| 10:30 | 14 | 2 | 0.14 |
| 10:45 | 7 | 2 | 0.29 |
| 11:00 | 14 | 5 | 0.36 |
| 11:15 | 13 | 1 | 0.08 |
| 11:30 | 9 | 0 | 0.00 |
| 11:45 | 8 | 0 | 0.00 |
| 12:00 | 5 | 0 | 0.00 |
| 12:15 | 6 | 2 | 0.33 |
| 12:30 | 3 | 1 | 0.33 |
| **12:45** | 2 | 2 | 1.00 |
| **13:00** | 5 | 0 | 0.00 |
| **13:15** | 5 | 1 | 0.20 |
| 13:30 | 2 | 0 | 0.00 |
| 13:45 | 4 | 0 | 0.00 |
| 14:00 | 4 | 0 | 0.00 |
| 14:15 | 5 | 0 | 0.00 |
| 14:30 | 7 | 1 | 0.14 |
| **14:45** | 13 | 3 | 0.23 |
| **15:00** | 6 | 0 | 0.00 |
| **15:15** | 6 | 0 | 0.00 |
| 15:30 | 0 | 0 | — |
| 15:45 | 4 | 0 | 0.00 |
| 16:00 | 3 | 0 | 0.00 |
| 16:15 | 3 | 0 | 0.00 |
| 16:30 | 4 | 0 | 0.00 |
| 16:45 | 4 | 0 | 0.00 |
| 17:00 | 2 | 0 | 0.00 |
| 17:15 | 7 | 0 | 0.00 |
| 17:30 | 7 | 0 | 0.00 |
| 17:45 | 4 | 1 | 0.25 |
| 18:00 | 2 | 1 | 0.50 |
| 18:15 | 3 | 0 | 0.00 |
| 18:30 | 8 | 3 | 0.38 |
| 18:45 | 7 | 1 | 0.14 |
| 19:00 | 9 | 2 | 0.22 |
| 19:15 | 9 | 0 | 0.00 |
| 19:30 | 6 | 0 | 0.00 |
| 19:45 | 8 | 0 | 0.00 |
| 20:00 | 3 | 1 | 0.33 |
| 20:15 | 6 | 0 | 0.00 |
| 20:30 | 10 | 0 | 0.00 |
| 20:45 | 8 | 0 | 0.00 |

**P baseline:** n median = 7, mean = 7.8. turn15 median = 0, mean = 0.82.

### Reading the peaks
- **OUTER 13:00**: 11 events, 6 turned = **0.55**. Neighbours 12:45 = 0.10 and 13:15 = 0.07. This *is* a genuine bucket peak; it also has neighbours (12:15 = 0.50, 12:30 = 0.67) which look like a broader ~12:15–13:00 window rather than a spike at exactly 13:00. Note only 6 turns; the pattern rests on ≤ 4 unique dates.
- **OUTER 14:45–15:15**: 11+6+1 = 18 events, 1+0+0 = 1 turn = **0.06**. There is no 15:00 peak in the OUTER cohort at this measurement's definitions. The nearby 14:30 shows 4/13 = 0.31 — the visible cluster on the tape sits one 15-min bucket earlier than the operator flagged.
- **P 12:45**: 2/2 = 1.00 (n=2, sample noise).
- **P 14:45**: 3/13 = 0.23 — mildly above the P baseline but not distinctly. **P 15:00 and 15:15**: 0/6 and 0/6.
- Also worth flagging (not asked): **OUTER 12:30 = 0.67** (post-12:30 US release settle) and **OUTER 20:45 = 0.58** (NY close settle). Both stand out more strongly than 15:00 in this measurement.

---

## 2. Bounce-day characterisation

**Criterion**: a bounce day = a session with ≥ 1 OUTER-COINC event that turned ≥ 15p in [12:45, 13:15) or [14:45, 15:15). Across the corpus, **5 distinct dates** qualify.

| date | window | T (UTC) | lvl | side | tier | subtype | release relation | London net (p) | London range (p) | London eff | regime-proxy | BB@ (p) | BB day-med (p) | BB ratio | dir vs London | news cache |
|------|:------:|:-------:|:---:|:----:|:----:|:-------:|:----------------:|:-------------:|:----------------:|:----------:|:------------:|:-------:|:--------------:|:-------:|:-------------:|:----------:|
| 2026-04-01 | 15:00 | 14:45 | R2 | SELL | n/a (no cache) | NORMAL | no-release | +2.4 | 39.6 | 0.061 | CHOP | 27.83 | 30.49 | 0.91 | FADE | no |
| 2026-05-13 | 13:00 | 13:00 | S1 | BUY | n/a (no cache) | NORMAL | no-release | −13.2 | 39.2 | 0.337 | STRONG_TREND_DOWN | 27.14 | 17.89 | 1.52 | FADE | no |
| 2026-06-24 | 13:00 | 13:05 | S2 | BUY | MIDDLE | MIDDLE | POST-release (12:30 US Current Account MED, +35 min) | −30.8 | 42.7 | 0.721 | STRONG_TREND_DOWN | 28.13 | 23.15 | 1.22 | FADE | yes |
| 2026-06-24 | 13:00 | 13:10 | S2 | BUY | MIDDLE | MIDDLE | POST-release (12:30 US Current Account MED, +40 min) | −30.8 | 42.7 | 0.721 | STRONG_TREND_DOWN | 29.85 | 23.15 | 1.29 | FADE | yes |
| 2026-06-30 | 13:00 | 13:00 | S1 | BUY | BIG | BIG | ON-release (13:00 US Case-Shiller MED) | +1.6 | 18.1 | 0.088 | CHOP | 16.32 | 18.11 | 0.90 | flat-London | yes |
| 2026-06-30 | 13:00 | 13:05 | S1 | BUY | BIG | BIG | POST-release (13:00 US Case-Shiller MED, +5 min) | +1.6 | 18.1 | 0.088 | CHOP | 15.79 | 18.11 | 0.87 | flat-London | yes |
| 2026-07-06 | 13:00 | 12:55 | S1 | BUY | BIG | BIG | no-release | −7.8 | 19.8 | 0.394 | CHOP | 12.82 | 15.39 | 0.83 | FADE | yes |
| 2026-07-06 | 13:00 | 13:00 | S1 | BUY | BIG | BIG | no-release | −7.8 | 19.8 | 0.394 | CHOP | 12.50 | 15.39 | 0.81 | FADE | yes |

Notes:
- The 13:00 window contains 4 distinct dates (2026-05-13, 06-24, 06-30, 07-06); several rows repeat because consecutive 5m bars both cleared the touch/coinc thresholds. All 13:00-bucket qualifiers are **BUY off S1/S2**; there is no 13:00 R-fade in the corpus.
- The 15:00 window is a single date (2026-04-01) — SELL off R2 in a CHOP session with a very quiet London (efficiency 0.06). This single event may be tainted by data quality: the 2026-04-01 archive has 12 duplicated 5m timestamps, which can bias the forward MFE/close-beyond measurement. It clears turn15 in the detector but also carries closed_beyond=True and turn25=False.
- `tier`/`subtype` are reconstructed from `cache/news_state_finnhub_*.json` union (2026-06-04 → 2026-08-21 coverage). Days before 2026-06-04 have no calendar record here and are reported "n/a (no cache)".
- `regime-proxy` is **not** the production `regime_engine` label. It is a coarse H1 EMA20/50/200 alignment + ADX14 recomputation from raw 5m rollups, done because the production engine's H1 MACD path can't be historically replayed offline. Reported as a proxy — trust it directionally, not exactly.

Bounce direction rollup (n=5 days):
- 13:00 window: 4/4 days are BUY-S1/S2 (support fade). No R-side.
- 15:00 window: 1/1 day is SELL-R2 (resistance fade).
- London relation: 3/5 days FADE London (13:00: 05-13 down/BUY-S1, 06-24 down/BUY-S2, 07-06 down/BUY-S1; 15:00: 04-01 flat-up/SELL-R2 → FADE by the encoding). 2/5 are flat London (06-30, both 13:00 rows). None are pure continuation.

BB-width vs day median:
- 3/5 days sit above (05-13 ×1.52, 06-24 ×1.22–1.29, 04-01 ×0.91).
- 2/5 sit below (06-30 ×0.87–0.90, 07-06 ×0.81–0.83). No consistent "wide bands only" pattern.

---

## 3. Comparison against non-bounce days

Universe = 121 corpus dates. Bounce-any = 5. Non-bounce = 116 dates (a couple of days sit in both windows-sets? — no, overlap = 0, so non-bounce = 112 in the eligible archive; 4 dates have no bars/archive entry counted separately).

| group | n days | news-cache covered | tier BIG | tier MIDDLE | tier SMALL | tier n/a | subtype BIG | subtype MIDDLE | subtype PRE_BIG | subtype POST_BIG | subtype NORMAL | London eff median | London range median (p) | days with US 12:30 release | days with US 14:00–15:00 release |
|-------|:-----:|:-----------------:|:--------:|:-----------:|:----------:|:--------:|:-----------:|:--------------:|:----------------:|:---------------:|:--------------:|:----------------:|:----------------------:|:--------------------------:|:--------------------------------:|
| bounce 13:00 (4) | 4 | 3/4 | 2 | 1 | 0 | 1 | 2 | 1 | 0 | 0 | 1 | 0.366 | 29.5 | 1/4 | 3/4 |
| bounce 15:00 (1) | 1 | 0/1 | 0 | 0 | 0 | 1 | 0 | 0 | 0 | 0 | 1 | 0.061 | 39.6 | 0/1 | 0/1 |
| bounce ANY (5) | 5 | 3/5 | 2 | 1 | 0 | 2 | 2 | 1 | 0 | 0 | 2 | 0.337 | 39.2 | 1/5 | 3/5 |
| non-bounce | 112 | 47/112 | 33 | 14 | 3 | 62 | 33 | 14 | 4 | 1 | 60 | 0.437 | 24.88 | 29/112 | 28/112 |

Strongest observable discriminators (with caveats):
- **Tier mix in the 13:00 group leans BIG (2/4) vs 30% BIG in the non-bounce cohort.** With n=4, the difference is one event either way; the point estimate is directional, not conclusive.
- **London range** on bounce days is higher (median 39.2p vs 24.9p on non-bounce). That is a Simpson's-paradox-adjacent artefact — one bounce day (06-24) has a 42.7p London and one (04-01) has 39.6p, dragging the median. Sample too small to trust.
- **London efficiency** is *lower* on bounce days (0.337 vs 0.437) — bounce days feature a wider but choppier London, not a cleaner one.
- **US 14:00–15:00 release presence** is 3/5 on bounce days vs 25% on non-bounce — but 2/3 of those bounces fired *before* 14:00, so the release is downstream of the bounce, not upstream.
- **US 12:30 release presence** is 1/5 on bounce days vs 26% on non-bounce — *lower* than the base rate; the 12:30 release hypothesis does not survive.
- **Regime-proxy** on 13:00 bounces splits STRONG_TREND_DOWN ×2 dates (05-13, 06-24) vs CHOP ×2 dates (06-30, 07-06). No single regime dominates.

---

## 4. News-slot hypothesis

The operator's specific split.

### 13:00-window bounces split by "had US 12:30 release"
Only 3 of the 4 dates have a news-cache record (05-13 predates the cache).

| date | 12:30 US any? | 12:30 US HIGH? | release name(s) |
|------|:-------------:|:--------------:|-----------------|
| 2026-05-13 | — no cache | — | n/a |
| 2026-06-24 | yes | no | Current Account (MED) |
| 2026-06-30 | no | no | (13:00 US Case-Shiller MED sits at 13:00 exactly, not 12:30) |
| 2026-07-06 | no | no | — |

**Result: 1 of 3 (33%) had a 12:30 US release; 0 of 3 had HIGH.** Baseline across the 50 cache-days in the corpus: 25/50 = 50% (any), 15/50 = 30% (HIGH). The bounce-day rate is *below* baseline for either impact class.

If the window is widened to "any US release in [12:00, 13:15) UTC": 2/3 bounce days (06-24 and 06-30) qualify vs a baseline that I did not compute for this window — no strong evidence either way at this n.

### 15:00-window bounces split by "had US 14:00–15:00 release"
Only 1 bounce (2026-04-01), which predates the news cache. **No data to run the split** on the cache-covered subset. Cannot state the ratio.

### Plain conclusion
On the cache-covered sample (n=3 for the 13:00 window), bounces do **not** concentrate on 12:30-release days. The 13:00-cluster cannot be attributed to a 12:30 news slot in this data. The 15:00-cluster is a single sample from a no-cache month; the news split is not testable.

---

## 5. Raw example days

### 5a. 13:00 bounce — 2026-06-24 (S2, POST-release)

Event line (from `/tmp/bb_level_events.json`):
```
13:05 COINC OUTER S2=13143.53 BUY   mfe=23.62p  mae=0.38p
                                     turn10=Y turn15=Y turn25=N  closed_beyond=N
13:10 COINC OUTER S2=13143.53 BUY   mfe=23.62p  mae=0.00p
                                     turn10=Y turn15=Y turn25=N  closed_beyond=N
```

Calendar (news_state_finnhub_2026-06-24.json — HIGH & MED GBP/USD only):
```
12:30  USD  MED  Current Account
14:00  USD  MED  New Home Sales
14:00  USD  MED  New Home Sales MoM
14:30  USD  MED  EIA Crude Oil Stocks Change
14:30  USD  MED  EIA Gasoline Stocks Change
```
(No HIGH-impact GBP or USD on this date.)

Regime-proxy at 13:05: **STRONG_TREND_DOWN**. BB width at bounce = 28.13p (day median 23.15p; ratio 1.22 — wider than typical).

5m bars around the bounce:
```
12:50  O 13146.15  H 13151.95  L 13145.25  C 13151.25
12:55  O 13151.15  H 13151.35  L 13147.65  C 13150.55
13:00  O 13150.65  H 13155.75  L 13148.15  C 13149.45
13:05  O 13149.35  H 13150.95  L 13144.05  C 13146.45   <-- COINC S2, low 13144.05 vs S2 13143.53 (td 0.52p)
13:10  O 13146.35  H 13147.15  L 13143.15  C 13144.35   <-- second COINC bar
13:15  O 13144.65  H 13152.15  L 13144.25  C 13151.95
13:20  O 13151.75  H 13157.45  L 13150.15  C 13157.05
13:25  O 13157.15  H 13166.15  L 13157.15  C 13165.15
13:30  O 13164.95  H 13167.15  L 13159.55  C 13160.85
13:35  O 13160.95  H 13162.15  L 13154.55  C 13157.45
```
Bounce fires +35–40 min after the 12:30 Current Account release. Reversal MFE = 13143.53 → 13167.15 = **23.62p** by 13:30; no bar closes below S2 within the forward window.

### 5b. 15:00 bounce — 2026-04-01 (R2)

Event line:
```
14:45 COINC OUTER R2=13323.07 SELL  mfe=18.67p  mae=14.83p
                                     turn10=Y turn15=Y turn25=N  closed_beyond=Y
```

Calendar: **no news cache** for 2026-04-01 (cache begins 2026-06-04). The available finnhub-state files do not carry a snapshot for this date.

Regime-proxy at 14:45: **CHOP**. BB width at bounce = 27.83p (day median 30.49p; ratio 0.91 — slightly below).

5m bars around the bounce (source CSV has 12 duplicated timestamps for this date; below is the deduplicated series):
```
14:30  O 13312.95  H 13314.90  L 13304.60  C 13308.45
14:35  O 13308.65  H 13318.00  L 13303.00  C 13313.05
14:40  O 13313.15  H 13319.80  L 13303.40  C 13318.05
14:45  O 13318.55  H 13323.30  L 13309.50  C 13321.95   <-- COINC R2, high 13323.30 vs R2 13323.07 (td 0.23p)
14:50  O 13322.25  H 13336.30  L 13317.70  C 13331.25   <-- immediate close above R2 (closed_beyond=True)
14:55  O 13331.35  H 13337.30  L 13329.60  C 13334.45
15:00  O 13334.35  H 13337.90  L 13331.30  C 13334.15
15:05  O 13333.55  H 13334.40  L 13326.30  C 13327.45
15:10  O 13327.55  H 13330.70  L 13324.50  C 13328.35
15:15  O 13328.15  H 13331.10  L 13324.90  C 13328.25
```
The forward window records reversal MFE = 18.67p **and** MAE = 14.83p, close_beyond immediately on the 14:50 bar. Under the "≥15p MFE before any close beyond" rule, the classification depends on which bar posted the low that satisfied the 15p reversal — the raw walk suggests the reversal is only satisfied later in the 12-bar window (after 15:15 in the dedup series). Given the duplicated-bars issue in the source CSV, treat this single 15:00 event as low-confidence.

### 5c. 13:00 AND 15:00 same day — **none in the corpus**

No day in 2026-03-23 → 2026-08-14 produces a turning OUTER-COINC in *both* windows. The intersection set is empty. Presenting a proxy would require relaxing the turn threshold or the coincidence definition.

---

## Sample-size caveats

- Turning OUTER-COINC events in the target windows: **8 across 5 unique dates**. Any per-day characterisation column here is a description of those specific days, not an estimator of a population parameter.
- News cache coverage: **50/121 dates** (2026-06-04 → 2026-08-14 usable; 2026-03-23 → 2026-06-03 has no snapshot). Both the 15:00 bounce day and one of the four 13:00 bounce days sit outside the cache — the news-slot split runs on 3 of the 4 13:00 dates and 0 of the 1 15:00 date.
- The regime label is a proxy computation. The production `regime_engine.classify_regime()` uses H1 MACD(35/45/30) served live from an internal cache that cannot be replayed offline; the proxy uses H1 EMA20/50/200 + ADX14 recomputed from 5m→H1 rollups on the raw archive. Directions of tendency should agree; exact labels may differ.
- Definitions of "touch" (2p) and "coincidence" (3p) come from the acceptance-passed detector spec. Under a looser touch tolerance, several near-touches at S1 on 08-13 (2.98p) would enter the event set and could shift the 13:00 bucket rate.
- The 2026-04-01 archive has 12 duplicated 5m rows — the detector's forward-MFE evaluation for the single 15:00 bounce event was computed against a walk that includes those duplicates.

## Provenance

- Detector: `/tmp/bb_level_coincidence.py` (already run — acceptance verified 2026-08-14).
- Event set: `/tmp/bb_level_events.json` (14,717 events).
- This analysis: `/tmp/bb_cluster_analysis.py`; full stdout at `/tmp/bb_cluster_analysis.log`.
- News: union of `/opt/tradingbot/cache/news_state_finnhub_*.json` (63 unique dates from 54 snapshot files).
- Candles: `/opt/tradingbot/data/candles/GBPUSD/*.csv` (5m native, ×10000; PIP_SIZE = 1.0).
- No pivot or BB math re-implemented.
