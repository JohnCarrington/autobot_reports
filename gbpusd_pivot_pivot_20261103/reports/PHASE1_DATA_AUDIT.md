# Phase 1 — Data Audit and Pivot-Convention Cross-Check

**Branch:** `research/gbpusd-pivot-pivot-20261103` (autobot_reports)
**Date:** 2026-11-03 18:35 UTC
**Scope:** Read-only inventory of certified GBP/USD tick data, derived candle archives, prior pivot work, economic-news feed, and NMS modules.

## 1. Certified GBP/USD tick archive

- **Base paths**
  - Raw tick CSVs: `/mnt/volume_lon1_1778405456698/ticks/GBPUSD_ticks_{YYYY}.csv` (2024, 2025, 2026)
  - Daily cache (npy): `/opt/tradingbot/data/tick_cache_daily/GBPUSD/`
- **Certification manifest:** `/mnt/volume_lon1_1778405456698/derived/autobot_strategy_study/corpus_certification.json` (built 2026-09-18T12:57:36Z). GBPUSD verdict: `CERTIFIED_WITH_DOCUMENTED_GAPS` (:116).
- **Usable range (true-UTC after TZ shift):**
  - **Start:** 2024-01-01 22:00:00 UTC
  - **End:** 2026-03-31 23:59:59 UTC (2026-04-01+ unusable — mid rounded to 2 decimals)
- **Totals:** 196,030 M5 bars certified (:115); 819 / 845 expected weekday trading days present (96.68% complete, :112).
- **Documented gaps (:104-106, :122-123):** 26 weekday-gap days; largest contiguous run = **19 days 2026-03-01 → 2026-03-22** (DST boundary transition).
- **TZ map** — per `/opt/tradingbot/reports-public/2026-09-28_bb_pierce_rsi/tz.py:1-53`:
  | Period | Offset to apply to label |
  | --- | --- |
  | 2024 full year | +5h |
  | 2025 full year | +5h |
  | 2026-01-01 → 2026-03-07 | 0h (labels already UTC) |
  | 2026-03-08 → 2026-03-31 | +5h |
  | 2026-04-01+ | **UNUSABLE** (2-dp rounding) |

**Phase 2 certified window used downstream:** 2024-01-01 → 2025-12-31 + 2026-01-01 → 2026-02-28 → **1,313 trading days** (2026-03 and 2026-04+ excluded).

## 2. Derived candle archives

| Dir | Basis | Granularity | GBPUSD range |
| --- | --- | --- | --- |
| `data/candles/` | MID of bid/ask | M5 | 2026-01-01 → 2026-11-03 (238 files) |
| `data/candles_ext/` | BID | M5 | 2024-01-01 → 2025-12-31 (627 files) |
| `data/candles_enriched/` | MID + 30 indicators | M5 | 2026-01-01 → 2026-11-03 (238 files) |
| `data/candles_ext_v2/` | BID | M5 + D1 synthetic | mirrors `candles_ext` |

**Sample schemas**
- `candles/GBPUSD/2026-01-01.csv`: `timestamp,open,high,low,close` (4 cols, MID).
- `candles_ext/GBPUSD/2024-01-02.csv`: `timestamp,open,high,low,close` (4 cols, BID).
- `candles_enriched/GBPUSD/2026-01-01.csv`: 37 cols — OHLC + EMA_50, RSI_3, BB_20, MACD_35_45, ATR_14, AROON_14, etc.

**H1 / H4:** Not archived. Phase 2+ must aggregate from M5 at analysis time.

## 3. Prior pivot work — production code matches textbook formula

**Production module:** `/opt/tradingbot/ig_daily_pivots.py`

**Formula (`:183-192`)** — exactly matches the operator's cited textbook:
```python
P  = (H + L + C) / 3.0
R1 = 2 * P - L
S1 = 2 * P - H
R2 = P + (H - L)
S2 = P - (H - L)
R3 = H + 2 * (P - L)
S3 = L - 2 * (H - P)
```

**Previous-day bar selection (`:675-769`, commit `0ee81f4` Phase 4 integration):**
- Uses IG's own previous-day **ASK** bar via REST (`GBPUSD_D1_bid_ask.json`, :70).
- UK calendar day boundary (IG labels bars by London midnight, not UTC).
- Sunday-session Monday bar handled (commit `46bab65`; test fixture confirms Sun ranges 10.5-32p vs Fri 44-74p).
- Completed-only rule rejects in-progress today bars, future-dated bars, and unparseable timestamps (FAIL-CLOSED — no silent substitution).
- Sanity floor rejects bars outside 30% of 20-day rolling range (`:358-430`, Phase 4 T2).

**BID vs ASK:** Primary basis is ASK (`:195, :855`) because the operator's IG chart shows BUY side; BID pivots preserved as sub-fields for dual-basis analysis.

**DST handling (`:87-95`):** UK midnight is 23:00 UTC during BST (last Sun Mar → last Sun Oct), 00:00 UTC during GMT. Scheduler respects a one-hour grace window around UK midnight.

**Current production cache** (`/opt/tradingbot/cache/htf/daily_pivots.json`, snapshot 2026-11-03 03:00:21 UTC):
- Prior-day bar: 2026-11-02 — ASK H=1.34489, L=1.33800, C=1.34093.
- Ask pivots: **P=1.34127, R1=1.34455, R2=1.34816, R3=1.35144, S1=1.33766, S2=1.33438, S3=1.33077**.
- Sanity: PASS (range ratio 0.9858, 20 weekday priors).

**Key implication for Phase 1b:** because production uses IG's ASK day bar directly with the textbook formula, the pivots emitted by `ig_daily_pivots.py` **ARE** the IG-convention pivots. The textbook-vs-IG comparison therefore collapses to a formula check (passes) and a day-boundary check (UK calendar, Sunday bar — both honoured). No machine-readable IG-displayed-level CSV was found for independent ground-truthing; the only check against IG's screen comes from the manual operator review cited in commit `b956d11:10`.

**Commits touching pivot code** (all currently on branches, none merged to `main`):
- `b956d11` — IG day bars + ask-side pivots + Monday Sunday-session (2026-10-23)
- `46bab65` — Monday pivots from the Sunday session bar (2026-10-23)
- `0ee81f4` — Pivot integrity FINAL INTEGRATION (2026-10-17)
- `a7e97cf`, `2e5f870`, `8a5ce40` — Pivot integrity Phases 2–4 + READ-ONLY audit (2026-10-17)

## 4. Economic calendar for Phase 4

- **Live fetch:** `/opt/tradingbot/news_calendar.py:46` → `https://nfs.faireconomy.media/ff_calendar_thisweek.json`; backup `https://finnhub.io/api/v1/calendar/economic` (:54).
- **Historical cache:** `/opt/tradingbot/cache/news_calendar_cache.json` (populated by `refresh_news_calendar.py`).
- **Classifier log:** `/opt/tradingbot/logs/news_tier_classification.jsonl` (`news_tier_classifier.py:85-89`).
- **Date range:** No pre-computed historical dump; weekly refresh since production started. Phase 4 must either source an external historical calendar or restrict to the window where the production cache has been persisted.

## 5. NMS modules for Phase 6

| Module | Path | Role |
| --- | --- | --- |
| nms_v3_classifier | `/opt/tradingbot/nms_v3_classifier.py` | State machine NORMAL→RANGE→EMERGING→STRONG; 24-bar TTL; family-cap; 2-step OR breakout; 2-bar persistence; serialisable dict state for restart safety. |
| nms_directional_authority | `/opt/tradingbot/nms_directional_authority.py` | Returns authoritative `DirectionalDecision`; enforcement opt-in via `NMS_UNIFIED_DIRECTIONAL_AUTHORITY_ENABLED` (:59); consumed-decision watch at `cache/nms_directional_authority_watch_consumed/{sym}.json` (:300). |
| session_trend | `/opt/tradingbot/session_trend.py` | Session-window context for the classifier. |
| news_trend_classifier | `/opt/tradingbot/news_trend_classifier.py` | News-driven trend state (separate from nms_v3). |

No continuous historical decision log was found; Phase 6 will need to replay decisions on the certified candle set or extract from live production logs where the state was serialised.

## 6. Go / No-Go for Phase 2

**Conditional GO** on the 1,313-day window above. Blockers acknowledged:

1. 2026-03-01 → 2026-03-22 excluded (DST gap).
2. 2026-04-01+ unusable for tick-derived analysis (mid rounding).
3. H1/H4 must be aggregated from M5.
4. Live bid/ask for Oct–Nov 2026 is NOT in the certified corpus — Phase 5 execution-feasibility checks for the PIA dates are limited to MID-captured candles and production logs.

Formula validation, convention documentation, and dual-basis pivots are all in place. Production code at `ig_daily_pivots.py` is reusable as the reference implementation for Phase 2 event detection.

## Data-quality caveats

- Pivots use IG's ASK bar; our Phase 2 event detection must note which side (ASK, BID, or MID) each candle used so the comparison is apples-to-apples.
- The DST-boundary gap (19 weekday days) sits inside Q1 2026 and cannot be patched from certified ticks. Any statistic that mixes pre- and post-DST behaviour must either exclude it or flag reduced power.
- No machine-readable IG-screen snapshot was found; the IG-convention match is by code-review inspection + manual operator comparison (commit `b956d11:10`).

## References
- `/mnt/volume_lon1_1778405456698/derived/autobot_strategy_study/corpus_certification.json`
- `/opt/tradingbot/reports-public/2026-09-28_bb_pierce_rsi/tz.py`, `tz_verify.py`
- `/opt/tradingbot/ig_daily_pivots.py` (lines 183, 195, 220, 358-430, 675-769, 855)
- `/opt/tradingbot/cache/htf/daily_pivots.json` (production cache, 2026-11-03 03:00:21 UTC)
