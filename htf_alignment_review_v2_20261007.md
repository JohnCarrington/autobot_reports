# HTF alignment review v2 — expanded universe + HTF-authority join

**Date:** 2026-10-07
**Repo HEAD:** `ce97bb6`
**Host:** 161 (161.35.168.61)
**v1:** `reports-public/htf_alignment_review_20261007.md` (sha `5d26893`) — byte-unchanged by this report.
**Scope widening vs v1:** adds every eod-review `signal_log.jsonl` snapshot 2026-07-21 → 2026-09-10, deduplicates against the current signal_log, and joins each trade with `htf_authority.jsonl` (shadow + rotated).

Research only. No deploys, no `.env` edits, no live-code edits. Research script at `/tmp/htf_align_v2/htf_bias_v2.py`.

---

## 1 — Trade-universe assembly

| source | rows loaded (≥ 2026-07-21) |
|---|---|
| `logs/signal_log.jsonl` (current) | 74 |
| `backups/eod-review/<date>/signal_log.jsonl` (52 dated snapshots) | 6290 |
| `logs/bounce_engine.jsonl` (OPENED events) | 5 |
| **Pre-dedup** (current + eod-review) | **6364** |
| Dedup collisions resolved | 5990 |
| **Post-dedup (signal_log family)** | **374** |
| Additions beyond current signal_log (eod-review coverage) | 300 |
| **Universe total** (signal_log family + bounce_engine) | **379** |

**Date range covered after merge:** `2026-07-21T06:55:01Z` → `2026-10-07T15:22:50Z` (inclusive).

**Dedup rule.** Key = `(deal_id|id, timestamp_open)`. Preferred record = row with `pnl_pips` populated → else row with the most non-null fields → else latest-mtime source file. 5990 duplicates collapsed to 374 unique records.

**eod-review snapshot behaviour.** The 52 snapshots each contain the *entire* signal_log as of that EOD, which is why the pre-dedup total is so large. The archive stops at `2026-09-10` (signal_log was then rotated — all later rows live only in the current file). Row-density evidence:
- `2026-07-21` snapshot has 13 in-scope rows (file begins before the 07-21 cutoff).
- `2026-09-03` snapshot has 300 in-scope rows (last snapshot containing the pre-rotation signal_log).
- `2026-09-04` → `2026-09-10` snapshots carry the new (post-rotation) 6–32 rows.

---

## 2 — HTF authority log coverage

| source | row count |
|---|---|
| `logs/htf_authority.jsonl` (current) | 238 |
| `logs/htf_authority.jsonl-20261006` | 1,885 |
| `logs/htf_authority.jsonl-20260918.gz` | 0 (empty after decompress — file carries no JSON lines) |
| **Total** | **2123** |

**Date range in HTF logs:** `2026-09-04T08:05:11Z` → `2026-10-07T15:22:49Z`.
**Rows with `enabled=True`:** **0** / 2123.
**Rows with `enforced=True`:** **0** / 2123.

**No live-enforcement rows exist in any available htf_authority log.** The memory note `project_r3_htf_veto_evidence.md` says the 2026-07-01 era `.env.bak` had `HTF_AUTHORITY_ENABLED=1`, so July trades should have had live verdicts logged — but there is **no July htf_authority log on disk**. The 19 KB `-20260918.gz` is empty. Earliest surviving HTF-authority telemetry starts 2026-09-04, by which time `HTF_AUTHORITY_ENABLED` had been unset. Zero rows carry `enabled=True` across the entire 2,123-row corpus.

**Join rule used.** `(symbol==pair) ∧ (direction==direction) ∧ (htf_ts within ±120 s of timestamp_open) ∧ mode-match`. Mode-match tries exact first, then a family map (BRIEFING_* / BOUNCE_A_* / NEWS_STRATEGY_* / GBPUSD_TREND_V3_*), then a shared-prefix with the strategy's base-name (strategy minus the trailing `_L`/`_S`). Closest-in-time wins when multiple candidates.

**UNMATCHED decomposition:**
- 300 UNMATCHED fall before 2026-09-04 — HTF logs do not cover that window.
- 3 UNMATCHED fall inside the HTF coverage window: three `GBPUSD_LEVEL_BOUNCE_S` rows at `2026-09-22T18:21:25-26Z` with `entry=1.335` (fallback encoding). No HTF-authority row was written for these fires on disk.

---

## 3 — Grouped results

Buckets:
- **briefing** = `BRIEFING_EXECUTION` + `BRIEFING_V5`
- **old strategy fleet** = everything else except `BOUNCE_ENGINE`/`BOUNCE_A_*`
- **bounce engine** = `BOUNCE_ENGINE` + `BOUNCE_A_L`/`BOUNCE_A_S`

### 3.1 Briefing (n = 39, pnl rows = 39, range 2026-07-23T12:50:04Z → 2026-10-07T13:06:04Z)

**Table A — HTF authority verdict**

| verdict | n | pnl_sum (p) | win_rate | median (p) |
|---|---|---|---|---|
| WOULD_BLOCK | 2 | +8.65 | 50.0% (1/2) | +21.85 |
| WOULD_PASS | 8 | +34.60 | 62.5% (5/8) | +14.40 |
| UNMATCHED | 29 | -14.10 | 44.8% (13/29) | -1.85 |

- Small-n flag: WOULD_BLOCK n=2 (n < 5).

**Table B — V5 D1/H4 alignment**

| alignment | n | pnl_sum (p) | win_rate | median (p) |
|---|---|---|---|---|
| AGREE_WITH_TRADE | 35 | +28.05 | 48.6% (17/35) | -0.70 |
| MIXED | 1 | +16.30 | 100.0% (1/1) | +16.30 |
| SKIPPED_NO_CANDLES | 3 | -15.20 | 33.3% (1/3) | -10.50 |

- Small-n flag: SKIPPED_NO_CANDLES n=3, MIXED n=1 (n < 5).

### 3.2 Old strategy fleet (n = 335, pnl rows = 332, range 2026-07-21T06:55:01Z → 2026-09-25T15:15:07Z)

**Table A — HTF authority verdict**

| verdict | n | pnl_sum (p) | win_rate | median (p) |
|---|---|---|---|---|
| WOULD_BLOCK | 27 | -54.60 | 44.4% (12/27) | -3.40 |
| WOULD_PASS | 34 | +24.55 | 50.0% (17/34) | +0.10 |
| UNMATCHED | 274 | -341.95 | 42.4% (115/271) | -1.45 |



**Table B — V5 D1/H4 alignment**

| alignment | n | pnl_sum (p) | win_rate | median (p) |
|---|---|---|---|---|
| AGREE_WITH_TRADE | 121 | -51.50 | 49.2% (58/118) | -0.10 |
| MIXED | 82 | +10.65 | 41.5% (34/82) | -1.70 |
| AGAINST_TRADE | 126 | -296.75 | 40.5% (51/126) | -3.30 |
| SKIPPED_NO_CANDLES | 6 | -34.40 | 16.7% (1/6) | -3.40 |



### 3.3 Bounce engine (n = 5, pnl rows = 0, range 2026-10-07T08:45:58.421407+00:00 → 2026-10-07T15:22:50.136140+00:00)

**Table A — HTF authority verdict**

| verdict | n | pnl_sum (p) | win_rate | median (p) |
|---|---|---|---|---|
| WOULD_BLOCK | 1 | +0.00 | — (0/0) | — |
| WOULD_PASS | 4 | +0.00 | — (0/0) | — |

- Small-n flag: WOULD_PASS n=4, WOULD_BLOCK n=1 (n < 5).

**Table B — V5 D1/H4 alignment**

| alignment | n | pnl_sum (p) | win_rate | median (p) |
|---|---|---|---|---|
| AGREE_WITH_TRADE | 1 | +0.00 | — (0/0) | — |
| AGAINST_TRADE | 4 | +0.00 | — (0/0) | — |

- Small-n flag: AGAINST_TRADE n=4, AGREE_WITH_TRADE n=1 (n < 5).

Note: all five bounce_engine fires are today (2026-10-07) and carry no `pnl_pips`.

---

## 4 — Overall sanity tables (not grouped)

**HTF would_ counts across the whole universe (379 trades):**

| verdict | n | pnl_sum (p) | win_rate | median (p) |
|---|---|---|---|---|
| WOULD_BLOCK | 30 | -45.95 | 44.8% (13/29) | -3.40 |
| WOULD_PASS | 46 | +59.15 | 52.4% (22/42) | +1.10 |
| UNMATCHED | 303 | -356.05 | 42.7% (128/300) | -1.45 |

**V5 alignment across the whole universe:**

| alignment | n | pnl_sum (p) | win_rate | median (p) |
|---|---|---|---|---|
| AGREE_WITH_TRADE | 157 | -23.45 | 49.0% (75/153) | -0.25 |
| MIXED | 83 | +26.95 | 42.2% (35/83) | -1.70 |
| AGAINST_TRADE | 130 | -296.75 | 40.5% (51/126) | -3.30 |
| SKIPPED_NO_CANDLES | 9 | -49.60 | 22.2% (2/9) | -5.30 |

---

## 5 — Judgement calls

- **Bucket assignment.** `BRIEFING_EXECUTION`, `BRIEFING_V5` → briefing. `BOUNCE_ENGINE` (bounce_engine log) + `BOUNCE_A_L`/`BOUNCE_A_S` (if ever seen) → bounce engine. Everything else that lives in signal_log is old strategy fleet, including the four `BRIEFING_SWEEP` family absent from the universe (not seen since 2026-07-21), the three `P2_*` rows, `FIFTY_PIP_BREAKOUT_USDCAD_V4`, `GBPUSD_H1_PIERCE_S`, `MACD_EXTREME_GBPUSD_LONG`, `RSI_FADE_GBPUSD_SHORT`, `GBPUSD_PIVOT_BREAK_*`, `GBPUSD_CONFIRMATION_FALLBACK_*`, `GBPUSD_LEVEL_BOUNCE_*`, `GBPUSD_STRUCTURE_BREAK_*`, `GBPUSD_EMA_PULLBACK_*`, `GBPUSD_TREND_V3_*`, `GBPUSD_TREND_V3_UM_*`, `GBPUSD_BB_BOUNCE_*`, `NEWS_STRATEGY_*`.
- **HTF join mode-match.** `GBPUSD_TREND_V3_UM_L/S` strategies map to htf_authority mode `GBPUSD_TREND_V3_L/S` via the shared-prefix pass (strategies are logged with the `_UM_` suffix in signal_log but the executor presents the base family label to htf_authority). `NEWS_STRATEGY_CONT` and `NEWS_STRATEGY_REVERSAL` exact-match. `BRIEFING_EXECUTION` / `BRIEFING_V5` exact-match. `BOUNCE_ENGINE` maps to `BOUNCE_A_L`/`BOUNCE_A_S` via the family map. Three LEVEL_BOUNCE fallback rows on 2026-09-22 at 18:21 have no HTF row to match — kept as UNMATCHED.
- **SKIPPED_NO_CANDLES.** Six old-fleet trades + three briefing fan-outs on 2026-07-23 → 2026-07-24 are on USDJPY and USDCAD. Both pairs are listed in the candle dirs but have a ~2-month gap in `data/candles/<pair>/` between 2026-05-19 and 2026-07-23 (USDJPY: 45 files total; USDCAD: 41 files total). D1 EMA20 requires 20 continuous daily bars; the gap breaks the warm-up chain inside the H4 bias window relevant to the entry. Per the operator spec listing only GBPUSD + EURUSD as covered pairs, those nine trades are flagged `SKIPPED_NO_CANDLES` and excluded from AGREE/MIXED/AGAINST counts.
- **FLAT tolerance.** ±0.5 pip. CSV encoding verified empirically: signal_log row `entry=13537.5, sl=13517.5, sl_pips=20` → 1 CSV unit = 1 pip (consistent with v1 parity on the 09-04 → 10-07 overlap).
- **Dedup priority.** `pnl_pips`-populated row wins over an open-at-snapshot copy of the same deal; otherwise the row with more non-null fields wins; last-resort tie-break is latest file-mtime (deterministic given the eod-review directory tree is static).
- **Live-enforced July trades.** Searched 2,123 htf_authority rows across all three log files; **zero** rows have `enabled=True` or `enforced=True`. The pre-09-04 trade window has no HTF-authority telemetry on disk. No live-enforced July rows are available to join.

---

## 6 — Row-level dump (all 379 in-scope trades, sorted by timestamp_open)

| timestamp_open | pair | strategy | group | direction | entry | d1_bias | h4_bias | alignment | htf_join | htf_would_decision | htf_would_reason | htf_enabled | htf_enforced | pnl_pips |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2026-07-21T06:55:01Z | GBPUSD | GBPUSD_BB_BOUNCE_S | old | SELL | 13448.2 | BULL | BEAR | MIXED | UNMATCHED | — | — |  |  | -0.65 |
| 2026-07-21T07:50:01Z | GBPUSD | GBPUSD_STRUCTURE_BREAK_S | old | SELL | 13438.8 | BULL | BEAR | MIXED | UNMATCHED | — | — |  |  | +29.85 |
| 2026-07-21T09:20:01Z | GBPUSD | GBPUSD_CONFIRMATION_FALLBACK_L | old | BUY | 13428.1 | BULL | BEAR | MIXED | UNMATCHED | — | — |  |  | -0.50 |
| 2026-07-21T10:10:00Z | GBPUSD | GBPUSD_BB_BOUNCE_L | old | BUY | 13428.9 | BULL | BEAR | MIXED | UNMATCHED | — | — |  |  | -19.25 |
| 2026-07-21T10:30:00Z | GBPUSD | GBPUSD_EMA_PULLBACK_S | old | SELL | 13427.4 | BULL | BEAR | MIXED | UNMATCHED | — | — |  |  | +13.05 |
| 2026-07-21T11:40:01Z | GBPUSD | GBPUSD_BB_BOUNCE_L | old | BUY | 13415.1 | BULL | BEAR | MIXED | UNMATCHED | — | — |  |  | -19.85 |
| 2026-07-21T11:55:01Z | GBPUSD | GBPUSD_TREND_V3_S | old | SELL | 13403.4 | BULL | BEAR | MIXED | UNMATCHED | — | — |  |  | +12.05 |
| 2026-07-21T12:30:01Z | GBPUSD | GBPUSD_STRUCTURE_BREAK_S | old | SELL | 13384.8 | BULL | BEAR | MIXED | UNMATCHED | — | — |  |  | +19.15 |
| 2026-07-21T12:35:01Z | GBPUSD | GBPUSD_BB_BOUNCE_L | old | BUY | 13390.7 | BULL | BEAR | MIXED | UNMATCHED | — | — |  |  | -18.85 |
| 2026-07-21T12:45:02Z | GBPUSD | GBPUSD_TREND_V3_S | old | SELL | 13387.5 | BULL | BEAR | MIXED | UNMATCHED | — | — |  |  | +21.85 |
| 2026-07-21T13:50:01Z | GBPUSD | GBPUSD_BB_BOUNCE_L | old | BUY | 13378.1 | BULL | BEAR | MIXED | UNMATCHED | — | — |  |  | +13.45 |
| 2026-07-21T14:05:01Z | GBPUSD | GBPUSD_CONFIRMATION_FALLBACK_L | old | BUY | 13385.2 | BULL | BEAR | MIXED | UNMATCHED | — | — |  |  | +6.35 |
| 2026-07-21T16:25:01Z | GBPUSD | GBPUSD_BB_BOUNCE_L | old | BUY | 13373.2 | BULL | BEAR | MIXED | UNMATCHED | — | — |  |  | +8.35 |
| 2026-07-22T06:45:01Z | GBPUSD | GBPUSD_BB_BOUNCE_L | old | BUY | 13374.6 | BEAR | BEAR | AGAINST_TRADE | UNMATCHED | — | — |  |  | +12.65 |
| 2026-07-22T06:55:00Z | GBPUSD | NEWS_STRATEGY_REVERSAL | old | BUY | 13378.0 | BEAR | BEAR | AGAINST_TRADE | UNMATCHED | — | — |  |  | +9.25 |
| 2026-07-22T06:55:01Z | GBPUSD | GBPUSD_EMA_PULLBACK_S | old | SELL | 13376.9 | BEAR | BEAR | AGREE_WITH_TRADE | UNMATCHED | — | — |  |  | -11.45 |
| 2026-07-22T07:40:01Z | GBPUSD | GBPUSD_BB_BOUNCE_S | old | SELL | 13384.5 | BEAR | BEAR | AGREE_WITH_TRADE | UNMATCHED | — | — |  |  | +0.75 |
| 2026-07-22T07:40:02Z | GBPUSD | GBPUSD_CONFIRMATION_FALLBACK_S | old | SELL | 13384.4 | BEAR | BEAR | AGREE_WITH_TRADE | UNMATCHED | — | — |  |  | +0.05 |
| 2026-07-22T09:30:02Z | GBPUSD | GBPUSD_EMA_PULLBACK_S | old | SELL | 13369.7 | BEAR | BEAR | AGREE_WITH_TRADE | UNMATCHED | — | — |  |  | -11.65 |
| 2026-07-22T09:35:02Z | GBPUSD | GBPUSD_BB_BOUNCE_L | old | BUY | 13373.8 | BEAR | BEAR | AGAINST_TRADE | UNMATCHED | — | — |  |  | -0.15 |
| 2026-07-22T11:15:02Z | GBPUSD | GBPUSD_BB_BOUNCE_S | old | SELL | 13368.7 | BEAR | BEAR | AGREE_WITH_TRADE | UNMATCHED | — | — |  |  | -1.45 |
| 2026-07-22T13:50:02Z | GBPUSD | GBPUSD_BB_BOUNCE_S | old | SELL | 13381.9 | BEAR | BEAR | AGREE_WITH_TRADE | UNMATCHED | — | — |  |  | +5.00 |
| 2026-07-22T15:05:01Z | GBPUSD | GBPUSD_BB_BOUNCE_L | old | BUY | 13376.5 | BEAR | BEAR | AGAINST_TRADE | UNMATCHED | — | — |  |  | -8.30 |
| 2026-07-23T09:30:29Z | USDCAD | FIFTY_PIP_BREAKOUT_USDCAD_V4 | old | BUY | 14075.7 | — | — | SKIPPED_NO_CANDLES | UNMATCHED | — | — |  |  | +1.80 |
| 2026-07-23T10:55:01Z | GBPUSD | RSI_FADE_GBPUSD_SHORT | old | SELL | 13367.4 | BEAR | BEAR | AGREE_WITH_TRADE | UNMATCHED | — | — |  |  | +20.05 |
| 2026-07-23T12:50:04Z | GBPUSD | BRIEFING_EXECUTION | briefing | SELL | 13339.3 | BEAR | BEAR | AGREE_WITH_TRADE | UNMATCHED | — | — |  |  | +18.55 |
| 2026-07-23T13:10:04Z | GBPUSD | MACD_EXTREME_GBPUSD_LONG | old | BUY | 13331.6 | BEAR | BEAR | AGAINST_TRADE | UNMATCHED | — | — |  |  | +2.05 |
| 2026-07-23T14:15:02Z | EURUSD | P2_EURUSD_A | old | BUY | 11372.3 | BEAR | BEAR | AGAINST_TRADE | UNMATCHED | — | — |  |  | +0.50 |
| 2026-07-23T14:20:01Z | GBPUSD | MACD_EXTREME_GBPUSD_LONG | old | BUY | 13323.7 | BEAR | BEAR | AGAINST_TRADE | UNMATCHED | — | — |  |  | -10.60 |
| 2026-07-23T15:20:02Z | GBPUSD | MACD_EXTREME_GBPUSD_LONG | old | BUY | 13313.8 | BEAR | BEAR | AGAINST_TRADE | UNMATCHED | — | — |  |  | -11.70 |
| 2026-07-23T15:30:02Z | USDJPY | P2_USDJPY_B | old | BUY | 16387.7 | — | — | SKIPPED_NO_CANDLES | UNMATCHED | — | — |  |  | -13.00 |
| 2026-07-23T16:15:03Z | USDJPY | BRIEFING_EXECUTION | briefing | BUY | 16377.6 | — | — | SKIPPED_NO_CANDLES | UNMATCHED | — | — |  |  | +6.00 |
| 2026-07-23T19:10:02Z | USDJPY | P2_USDJPY_B | old | BUY | 16380.7 | — | — | SKIPPED_NO_CANDLES | UNMATCHED | — | — |  |  | -1.10 |
| 2026-07-23T20:55:26Z | USDCAD | FIFTY_PIP_BREAKOUT_USDCAD_V4 | old | BUY | 14075.7 | — | — | SKIPPED_NO_CANDLES | UNMATCHED | — | — |  |  | -5.30 |
| 2026-07-23T21:45:25Z | USDCAD | FIFTY_PIP_BREAKOUT_USDCAD_V4 | old | BUY | 14075.7 | — | — | SKIPPED_NO_CANDLES | UNMATCHED | — | — |  |  | -13.40 |
| 2026-07-24T07:05:03Z | USDJPY | BRIEFING_EXECUTION | briefing | BUY | 16374.3 | — | — | SKIPPED_NO_CANDLES | UNMATCHED | — | — |  |  | -10.50 |
| 2026-07-24T07:10:02Z | GBPUSD | GBPUSD_STRUCTURE_BREAK_L | old | BUY | 13334.3 | BEAR | BEAR | AGAINST_TRADE | UNMATCHED | — | — |  |  | -12.05 |
| 2026-07-24T07:15:03Z | GBPUSD | GBPUSD_TREND_V3_L | old | BUY | 13337.9 | BEAR | BEAR | AGAINST_TRADE | UNMATCHED | — | — |  |  | -10.50 |
| 2026-07-24T09:04:00Z | USDCAD | FIFTY_PIP_BREAKOUT_USDCAD_V4 | old | BUY | 14080.2 | — | — | SKIPPED_NO_CANDLES | UNMATCHED | — | — |  |  | -3.40 |
| 2026-07-24T09:50:02Z | USDCAD | BRIEFING_EXECUTION | briefing | BUY | 14086.3 | — | — | SKIPPED_NO_CANDLES | UNMATCHED | — | — |  |  | -10.70 |
| 2026-07-24T20:25:22Z | GBPUSD | BRIEFING_EXECUTION | briefing | SELL | 13319.6 | BEAR | BEAR | AGREE_WITH_TRADE | UNMATCHED | — | — |  |  | -14.10 |
| 2026-07-27T06:55:01Z | GBPUSD | GBPUSD_CONFIRMATION_FALLBACK_S | old | SELL | 13350.4 | BEAR | BEAR | AGREE_WITH_TRADE | UNMATCHED | — | — |  |  | +11.40 |
| 2026-07-27T07:15:01Z | GBPUSD | GBPUSD_BB_BOUNCE_L | old | BUY | 13348.9 | BEAR | BEAR | AGAINST_TRADE | UNMATCHED | — | — |  |  | -19.65 |
| 2026-07-27T10:45:01Z | GBPUSD | GBPUSD_BB_BOUNCE_L | old | BUY | 13331.6 | BEAR | BEAR | AGAINST_TRADE | UNMATCHED | — | — |  |  | -20.10 |
| 2026-07-27T10:45:04Z | EURUSD | BRIEFING_EXECUTION | briefing | SELL | 11400.4 | BEAR | BULL | MIXED | UNMATCHED | — | — |  |  | +16.30 |
| 2026-07-27T13:00:03Z | GBPUSD | GBPUSD_BB_BOUNCE_L | old | BUY | 13314.7 | BEAR | BEAR | AGAINST_TRADE | UNMATCHED | — | — |  |  | -12.10 |
| 2026-07-27T13:55:01Z | GBPUSD | GBPUSD_BB_BOUNCE_S | old | SELL | 13311.3 | BEAR | BEAR | AGREE_WITH_TRADE | UNMATCHED | — | — |  |  | -0.95 |
| 2026-07-27T16:40:02Z | GBPUSD | GBPUSD_BB_BOUNCE_S | old | SELL | 13308.6 | BEAR | BEAR | AGREE_WITH_TRADE | UNMATCHED | — | — |  |  | +18.25 |
| 2026-07-28T06:15:00Z | EURUSD | BRIEFING_EXECUTION | briefing | SELL | 11365.9 | BEAR | BEAR | AGREE_WITH_TRADE | UNMATCHED | — | — |  |  | +12.40 |
| 2026-07-28T06:35:05Z | GBPUSD | BRIEFING_EXECUTION | briefing | SELL | 13292.0 | BEAR | BEAR | AGREE_WITH_TRADE | UNMATCHED | — | — |  |  | +17.75 |
| 2026-07-28T06:50:02Z | GBPUSD | GBPUSD_BB_BOUNCE_S | old | SELL | 13291.9 | BEAR | BEAR | AGREE_WITH_TRADE | UNMATCHED | — | — |  |  | -11.95 |
| 2026-07-28T08:30:02Z | GBPUSD | GBPUSD_BB_BOUNCE_S | old | SELL | 13301.6 | BEAR | BEAR | AGREE_WITH_TRADE | UNMATCHED | — | — |  |  | +17.90 |
| 2026-07-28T11:45:02Z | GBPUSD | GBPUSD_BB_BOUNCE_S | old | SELL | 13279.9 | BEAR | BEAR | AGREE_WITH_TRADE | UNMATCHED | — | — |  |  | -11.95 |
| 2026-07-28T12:55:00Z | GBPUSD | GBPUSD_STRUCTURE_BREAK_L | old | BUY | 13296.4 | BEAR | BEAR | AGAINST_TRADE | UNMATCHED | — | — |  |  | +1.95 |
| 2026-07-28T13:10:02Z | GBPUSD | GBPUSD_TREND_V3_L | old | BUY | 13300.8 | BEAR | BEAR | AGAINST_TRADE | UNMATCHED | — | — |  |  | -12.05 |
| 2026-07-28T14:00:01Z | EURUSD | BRIEFING_EXECUTION | briefing | SELL | 11370.7 | BEAR | BEAR | AGREE_WITH_TRADE | UNMATCHED | — | — |  |  | -12.10 |
| 2026-07-28T14:30:01Z | GBPUSD | GBPUSD_BB_BOUNCE_L | old | BUY | 13296.3 | BEAR | BEAR | AGAINST_TRADE | UNMATCHED | — | — |  |  | +5.45 |
| 2026-07-29T17:49:27Z | GBPUSD | BRIEFING_V5 | briefing | SELL | 13305.8 | BEAR | BEAR | AGREE_WITH_TRADE | UNMATCHED | — | — |  |  | -14.30 |
| 2026-07-30T09:35:01Z | GBPUSD | GBPUSD_TREND_V3_L | old | BUY | 13373.8 | BULL | BULL | AGREE_WITH_TRADE | UNMATCHED | — | — |  |  | +14.25 |
| 2026-07-30T10:45:01Z | GBPUSD | GBPUSD_TREND_V3_L | old | BUY | 13398.6 | BULL | BULL | AGREE_WITH_TRADE | UNMATCHED | — | — |  |  | -0.25 |
| 2026-07-30T13:50:01Z | GBPUSD | GBPUSD_BB_BOUNCE_S | old | SELL | 13408.1 | BULL | BULL | AGAINST_TRADE | UNMATCHED | — | — |  |  | -20.20 |
| 2026-07-30T14:10:02Z | GBPUSD | GBPUSD_STRUCTURE_BREAK_L | old | BUY | 13429.35 | BULL | BULL | AGREE_WITH_TRADE | UNMATCHED | — | — |  |  | +0.05 |
| 2026-07-31T06:05:06Z | EURUSD | BRIEFING_EXECUTION | briefing | BUY | 11511.1 | BULL | BULL | AGREE_WITH_TRADE | UNMATCHED | — | — |  |  | +14.10 |
| 2026-07-31T06:15:01Z | GBPUSD | BRIEFING_EXECUTION | briefing | BUY | 13454.1 | BULL | BULL | AGREE_WITH_TRADE | UNMATCHED | — | — |  |  | -12.10 |
| 2026-07-31T07:00:01Z | GBPUSD | GBPUSD_BB_BOUNCE_S | old | SELL | 13451.1 | BULL | BULL | AGAINST_TRADE | UNMATCHED | — | — |  |  | +5.65 |
| 2026-07-31T08:05:02Z | GBPUSD | GBPUSD_CONFIRMATION_FALLBACK_S | old | SELL | 13450.0 | BULL | BULL | AGAINST_TRADE | UNMATCHED | — | — |  |  | +0.85 |
| 2026-07-31T08:20:01Z | GBPUSD | GBPUSD_BB_BOUNCE_L | old | BUY | 13447.6 | BULL | BULL | AGREE_WITH_TRADE | UNMATCHED | — | — |  |  | +14.25 |
| 2026-07-31T09:15:01Z | GBPUSD | GBPUSD_BB_BOUNCE_S | old | SELL | 13458.0 | BULL | BULL | AGAINST_TRADE | UNMATCHED | — | — |  |  | +8.65 |
| 2026-07-31T11:55:01Z | GBPUSD | GBPUSD_TREND_V3_S | old | SELL | 13419.0 | BULL | BULL | AGAINST_TRADE | UNMATCHED | — | — |  |  | +1.35 |
| 2026-07-31T13:15:02Z | EURUSD | BRIEFING_EXECUTION | briefing | BUY | 11488.4 | BULL | BULL | AGREE_WITH_TRADE | UNMATCHED | — | — |  |  | -28.40 |
| 2026-07-31T13:15:03Z | GBPUSD | BRIEFING_EXECUTION | briefing | BUY | 13415.4 | BULL | BULL | AGREE_WITH_TRADE | UNMATCHED | — | — |  |  | -12.90 |
| 2026-07-31T13:25:02Z | GBPUSD | GBPUSD_BB_BOUNCE_L | old | BUY | 13431.7 | BULL | BULL | AGREE_WITH_TRADE | UNMATCHED | — | — |  |  | -20.00 |
| 2026-07-31T13:35:01Z | GBPUSD | GBPUSD_BB_BOUNCE_S | old | SELL | 13420.2 | BULL | BULL | AGAINST_TRADE | UNMATCHED | — | — |  |  | +14.45 |
| 2026-07-31T13:40:02Z | EURUSD | BRIEFING_V5 | briefing | BUY | 11459.5 | BULL | BULL | AGREE_WITH_TRADE | UNMATCHED | — | — |  |  | +54.60 |
| 2026-08-03T06:05:02Z | GBPUSD | BRIEFING_EXECUTION | briefing | BUY | 13475.9 | BULL | BULL | AGREE_WITH_TRADE | UNMATCHED | — | — |  |  | -11.80 |
| 2026-08-03T06:10:01Z | GBPUSD | GBPUSD_BB_BOUNCE_S | old | SELL | 13473.0 | BULL | BULL | AGAINST_TRADE | UNMATCHED | — | — |  |  | +10.05 |
| 2026-08-03T07:20:00Z | GBPUSD | GBPUSD_EMA_PULLBACK_S | old | SELL | 13456.5 | BULL | BULL | AGAINST_TRADE | UNMATCHED | — | — |  |  | -11.25 |
| 2026-08-03T10:50:01Z | GBPUSD | GBPUSD_BB_BOUNCE_S | old | SELL | 13458.2 | BULL | BULL | AGAINST_TRADE | UNMATCHED | — | — |  |  | +5.55 |
| 2026-08-03T11:15:02Z | EURUSD | BRIEFING_EXECUTION | briefing | BUY | 11526.0 | BULL | BULL | AGREE_WITH_TRADE | UNMATCHED | — | — |  |  | -11.00 |
| 2026-08-03T14:15:01Z | GBPUSD | GBPUSD_EMA_PULLBACK_S | old | SELL | 13445.1 | BULL | BULL | AGAINST_TRADE | UNMATCHED | — | — |  |  | +16.05 |
| 2026-08-03T15:03:30Z | GBPUSD | BRIEFING_V5 | briefing | BUY | 13432.6 | BULL | BULL | AGREE_WITH_TRADE | UNMATCHED | — | — |  |  | -7.55 |
| 2026-08-03T20:27:00Z | GBPUSD | BRIEFING_V5 | briefing | BUY | 13430.0 | BULL | BULL | AGREE_WITH_TRADE | UNMATCHED | — | — |  |  | -0.70 |
| 2026-08-04T06:30:02Z | GBPUSD | GBPUSD_BB_BOUNCE_S | old | SELL | 13426.8 | BULL | BEAR | MIXED | UNMATCHED | — | — |  |  | -20.00 |
| 2026-08-04T13:15:01Z | GBPUSD | GBPUSD_BB_BOUNCE_L | old | BUY | 13442.2 | BULL | BULL | AGREE_WITH_TRADE | UNMATCHED | — | — |  |  | +0.25 |
| 2026-08-04T15:25:01Z | GBPUSD | GBPUSD_BB_BOUNCE_L | old | BUY | 13444.7 | BULL | BULL | AGREE_WITH_TRADE | UNMATCHED | — | — |  |  | +5.25 |
| 2026-08-04T16:25:02Z | GBPUSD | GBPUSD_BB_BOUNCE_S | old | SELL | 13450.1 | BULL | BULL | AGAINST_TRADE | UNMATCHED | — | — |  |  | -1.45 |
| 2026-08-05T06:25:01Z | GBPUSD | GBPUSD_BB_BOUNCE_L | old | BUY | 13454.9 | BULL | BULL | AGREE_WITH_TRADE | UNMATCHED | — | — |  |  | +8.45 |
| 2026-08-05T08:20:01Z | GBPUSD | GBPUSD_EMA_PULLBACK_L | old | BUY | 13467.5 | BULL | BULL | AGREE_WITH_TRADE | UNMATCHED | — | — |  |  | -10.40 |
| 2026-08-05T08:40:01Z | GBPUSD | GBPUSD_BB_BOUNCE_S | old | SELL | 13460.5 | BULL | BULL | AGAINST_TRADE | UNMATCHED | — | — |  |  | -20.00 |
| 2026-08-05T09:00:01Z | GBPUSD | GBPUSD_BB_BOUNCE_L | old | BUY | 13457.6 | BULL | BULL | AGREE_WITH_TRADE | UNMATCHED | — | — |  |  | +18.95 |
| 2026-08-05T12:05:01Z | GBPUSD | GBPUSD_TREND_V3_L | old | BUY | 13480.8 | BULL | BULL | AGREE_WITH_TRADE | UNMATCHED | — | — |  |  | -10.50 |
| 2026-08-05T14:45:01Z | GBPUSD | GBPUSD_EMA_PULLBACK_L | old | BUY | 13477.8 | BULL | BULL | AGREE_WITH_TRADE | UNMATCHED | — | — |  |  | -10.50 |
| 2026-08-06T06:10:01Z | GBPUSD | GBPUSD_BB_BOUNCE_S | old | SELL | 13461.9 | BULL | BULL | AGAINST_TRADE | UNMATCHED | — | — |  |  | -3.45 |
| 2026-08-06T08:05:05Z | EURUSD | BRIEFING_EXECUTION | briefing | BUY | 11542.5 | BULL | BULL | AGREE_WITH_TRADE | UNMATCHED | — | — |  |  | -10.30 |
| 2026-08-06T09:44:44Z | GBPUSD | BRIEFING_V5 | briefing | BUY | 13453.9 | BULL | BULL | AGREE_WITH_TRADE | UNMATCHED | — | — |  |  | +2.55 |
| 2026-08-06T11:15:01Z | GBPUSD | GBPUSD_BB_BOUNCE_S | old | SELL | 13462.6 | BULL | BULL | AGAINST_TRADE | UNMATCHED | — | — |  |  | -4.55 |
| 2026-08-06T13:25:02Z | GBPUSD | BRIEFING_EXECUTION | briefing | BUY | 13468.9 | BULL | BULL | AGREE_WITH_TRADE | UNMATCHED | — | — |  |  | -10.60 |
| 2026-08-06T14:15:01Z | GBPUSD | GBPUSD_BB_BOUNCE_S | old | SELL | 13466.3 | BULL | BULL | AGAINST_TRADE | UNMATCHED | — | — |  |  | +15.40 |
| 2026-08-07T04:50:01Z | GBPUSD | GBPUSD_BB_BOUNCE_S | old | SELL | 13453.2 | BULL | BEAR | MIXED | UNMATCHED | — | — |  |  | +12.80 |
| 2026-08-07T06:45:02Z | GBPUSD | GBPUSD_CONFIRMATION_FALLBACK_S | old | SELL | 13453.8 | BULL | BEAR | MIXED | UNMATCHED | — | — |  |  | +10.25 |
| 2026-08-07T08:45:01Z | GBPUSD | GBPUSD_BB_BOUNCE_L | old | BUY | 13448.7 | BULL | BEAR | MIXED | UNMATCHED | — | — |  |  | -7.30 |
| 2026-08-07T12:35:01Z | GBPUSD | GBPUSD_TREND_V3_S | old | SELL | 13494.7 | BULL | BEAR | MIXED | UNMATCHED | — | — |  |  | +3.05 |
| 2026-08-07T12:40:01Z | GBPUSD | GBPUSD_TREND_V3_S | old | SELL | 13494.3 | BULL | BEAR | MIXED | UNMATCHED | — | — |  |  | -11.15 |
| 2026-08-07T13:00:01Z | GBPUSD | GBPUSD_TREND_V3_S | old | SELL | 13499.8 | BULL | BEAR | MIXED | UNMATCHED | — | — |  |  | +1.90 |
| 2026-08-07T13:15:01Z | GBPUSD | GBPUSD_EMA_PULLBACK_L | old | BUY | 13503.4 | BULL | BEAR | MIXED | UNMATCHED | — | — |  |  | -11.85 |
| 2026-08-07T18:10:02Z | GBPUSD | GBPUSD_BB_BOUNCE_L | old | BUY | 13495.9 | BULL | BULL | AGREE_WITH_TRADE | UNMATCHED | — | — |  |  | +4.25 |
| 2026-08-10T05:00:02Z | GBPUSD | GBPUSD_BB_BOUNCE_S | old | SELL | 13487.5 | BULL | BULL | AGAINST_TRADE | UNMATCHED | — | — |  |  | -15.70 |
| 2026-08-10T08:10:01Z | GBPUSD | GBPUSD_EMA_PULLBACK_L | old | BUY | 13501.2 | BULL | BULL | AGREE_WITH_TRADE | UNMATCHED | — | — |  |  | -10.80 |
| 2026-08-10T10:10:01Z | GBPUSD | GBPUSD_BB_BOUNCE_L | old | BUY | 13496.7 | BULL | BULL | AGREE_WITH_TRADE | UNMATCHED | — | — |  |  | +10.00 |
| 2026-08-10T12:25:02Z | GBPUSD | GBPUSD_BB_BOUNCE_S | old | SELL | 13495.3 | BULL | BULL | AGAINST_TRADE | UNMATCHED | — | — |  |  | -9.40 |
| 2026-08-10T14:30:02Z | GBPUSD | GBPUSD_EMA_PULLBACK_L | old | BUY | 13518.6 | BULL | BULL | AGREE_WITH_TRADE | UNMATCHED | — | — |  |  | +0.25 |
| 2026-08-11T04:55:02Z | GBPUSD | GBPUSD_BB_BOUNCE_L | old | BUY | 13510.0 | BULL | BULL | AGREE_WITH_TRADE | UNMATCHED | — | — |  |  | -7.15 |
| 2026-08-11T05:50:01Z | GBPUSD | GBPUSD_BB_BOUNCE_S | old | SELL | 13512.3 | BULL | BULL | AGAINST_TRADE | UNMATCHED | — | — |  |  | +10.30 |
| 2026-08-11T07:40:01Z | GBPUSD | GBPUSD_EMA_PULLBACK_S | old | SELL | 13496.8 | BULL | BULL | AGAINST_TRADE | UNMATCHED | — | — |  |  | -8.70 |
| 2026-08-11T08:55:01Z | GBPUSD | GBPUSD_BB_BOUNCE_S | old | SELL | 13502.4 | BULL | BULL | AGAINST_TRADE | UNMATCHED | — | — |  |  | -13.60 |
| 2026-08-11T08:55:03Z | GBPUSD | GBPUSD_CONFIRMATION_FALLBACK_S | old | SELL | 13502.3 | BULL | BULL | AGAINST_TRADE | UNMATCHED | — | — |  |  | +0.65 |
| 2026-08-11T14:25:02Z | GBPUSD | BRIEFING_EXECUTION | briefing | BUY | 13504.6 | BULL | BULL | AGREE_WITH_TRADE | UNMATCHED | — | — |  |  | -1.85 |
| 2026-08-11T18:50:01Z | GBPUSD | BRIEFING_EXECUTION | briefing | BUY | 13503.7 | BULL | BULL | AGREE_WITH_TRADE | UNMATCHED | — | — |  |  | +1.10 |
| 2026-08-12T04:25:01Z | GBPUSD | GBPUSD_BB_BOUNCE_L | old | BUY | 13504.8 | BULL | BULL | AGREE_WITH_TRADE | UNMATCHED | — | — |  |  | +19.05 |
| 2026-08-12T06:55:01Z | GBPUSD | GBPUSD_BB_BOUNCE_S | old | SELL | 13504.5 | BULL | BULL | AGAINST_TRADE | UNMATCHED | — | — |  |  | -6.30 |
| 2026-08-12T09:25:01Z | GBPUSD | GBPUSD_TREND_V3_L | old | BUY | 13526.2 | BULL | BULL | AGREE_WITH_TRADE | UNMATCHED | — | — |  |  | -11.75 |
| 2026-08-12T13:25:01Z | GBPUSD | GBPUSD_CONFIRMATION_FALLBACK_S | old | SELL | 13525.2 | BULL | BULL | AGAINST_TRADE | UNMATCHED | — | — |  |  | -6.00 |
| 2026-08-12T15:30:06Z | GBPUSD | GBPUSD_EMA_PULLBACK_S | old | SELL | 13506.2 | BULL | BULL | AGAINST_TRADE | UNMATCHED | — | — |  |  | +5.25 |
| 2026-08-13T04:55:01Z | GBPUSD | GBPUSD_BB_BOUNCE_S | old | SELL | 13492.6 | BULL | BEAR | MIXED | UNMATCHED | — | — |  |  | +11.15 |
| 2026-08-13T07:10:01Z | GBPUSD | GBPUSD_EMA_PULLBACK_S | old | SELL | 13478.8 | BULL | BEAR | MIXED | UNMATCHED | — | — |  |  | -6.40 |
| 2026-08-13T09:20:01Z | GBPUSD | GBPUSD_BB_BOUNCE_L | old | BUY | 13483.2 | BULL | BEAR | MIXED | UNMATCHED | — | — |  |  | +11.45 |
| 2026-08-13T09:45:01Z | GBPUSD | GBPUSD_BB_BOUNCE_S | old | SELL | 13486.9 | BULL | BEAR | MIXED | UNMATCHED | — | — |  |  | -6.80 |
| 2026-08-13T10:25:01Z | GBPUSD | GBPUSD_BB_BOUNCE_S | old | SELL | 13495.9 | BULL | BEAR | MIXED | UNMATCHED | — | — |  |  | -2.00 |
| 2026-08-13T12:32:53Z | GBPUSD | NEWS_STRATEGY_CONT | old | BUY | 13487.5 | BULL | BEAR | MIXED | UNMATCHED | — | — |  |  | +17.05 |
| 2026-08-13T15:40:03Z | GBPUSD | GBPUSD_BB_BOUNCE_L | old | BUY | 13498.7 | BULL | BEAR | MIXED | UNMATCHED | — | — |  |  | -3.50 |
| 2026-08-13T17:00:02Z | GBPUSD | GBPUSD_H1_PIERCE_S | old | SELL | 13485.5 | BULL | BEAR | MIXED | UNMATCHED | — | — |  |  | -2.70 |
| 2026-08-13T18:50:01Z | GBPUSD | GBPUSD_BB_BOUNCE_S | old | SELL | 13484.9 | BULL | BEAR | MIXED | UNMATCHED | — | — |  |  | -4.10 |
| 2026-08-14T08:05:02Z | GBPUSD | GBPUSD_TREND_V3_L | old | BUY | 13516.3 | BULL | BULL | AGREE_WITH_TRADE | UNMATCHED | — | — |  |  | +32.75 |
| 2026-08-14T08:20:01Z | GBPUSD | GBPUSD_LEVEL_BOUNCE_S | old | SELL | 13515.4 | BULL | BULL | AGAINST_TRADE | UNMATCHED | — | — |  |  | -7.25 |
| 2026-08-14T15:00:01Z | GBPUSD | GBPUSD_H1_PIERCE_S | old | SELL | 13547.9 | BULL | BULL | AGAINST_TRADE | UNMATCHED | — | — |  |  | +12.45 |
| 2026-08-14T15:30:02Z | GBPUSD | GBPUSD_BB_BOUNCE_L | old | BUY | 13549.0 | BULL | BULL | AGREE_WITH_TRADE | UNMATCHED | — | — |  |  | -20.30 |
| 2026-08-14T17:30:01Z | GBPUSD | GBPUSD_BB_BOUNCE_L | old | BUY | 13530.9 | BULL | BULL | AGREE_WITH_TRADE | UNMATCHED | — | — |  |  | +3.75 |
| 2026-08-17T04:20:02Z | GBPUSD | GBPUSD_BB_BOUNCE_S | old | SELL | 13554.8 | BULL | BULL | AGAINST_TRADE | UNMATCHED | — | — |  |  | -7.60 |
| 2026-08-17T06:35:01Z | EURUSD | BRIEFING_EXECUTION | briefing | BUY | 11589.6 | BULL | BULL | AGREE_WITH_TRADE | UNMATCHED | — | — |  |  | +15.90 |
| 2026-08-17T09:00:02Z | GBPUSD | GBPUSD_BB_BOUNCE_L | old | BUY | 13554.2 | BULL | BULL | AGREE_WITH_TRADE | UNMATCHED | — | — |  |  | +5.55 |
| 2026-08-17T10:35:01Z | GBPUSD | GBPUSD_BB_BOUNCE_S | old | SELL | 13559.2 | BULL | BULL | AGAINST_TRADE | UNMATCHED | — | — |  |  | +2.30 |
| 2026-08-17T11:10:01Z | GBPUSD | GBPUSD_BB_BOUNCE_L | old | BUY | 13560.7 | BULL | BULL | AGREE_WITH_TRADE | UNMATCHED | — | — |  |  | -2.70 |
| 2026-08-17T12:20:01Z | GBPUSD | GBPUSD_BB_BOUNCE_S | old | SELL | 13557.4 | BULL | BULL | AGAINST_TRADE | UNMATCHED | — | — |  |  | +0.00 |
| 2026-08-17T13:15:02Z | GBPUSD | GBPUSD_CONFIRMATION_FALLBACK_S | old | SELL | 13560.9 | BULL | BULL | AGAINST_TRADE | UNMATCHED | — | — |  |  | -1.05 |
| 2026-08-17T14:00:03Z | GBPUSD | GBPUSD_BB_BOUNCE_L | old | BUY | 13560.0 | BULL | BULL | AGREE_WITH_TRADE | UNMATCHED | — | — |  |  | +6.50 |
| 2026-08-17T14:35:02Z | GBPUSD | GBPUSD_CONFIRMATION_FALLBACK_S | old | SELL | 13558.7 | BULL | BULL | AGAINST_TRADE | UNMATCHED | — | — |  |  | +15.30 |
| 2026-08-17T15:00:02Z | GBPUSD | GBPUSD_BB_BOUNCE_L | old | BUY | 13553.7 | BULL | BULL | AGREE_WITH_TRADE | UNMATCHED | — | — |  |  | +4.20 |
| 2026-08-17T17:30:01Z | GBPUSD | GBPUSD_BB_BOUNCE_L | old | BUY | 13555.1 | BULL | BULL | AGREE_WITH_TRADE | UNMATCHED | — | — |  |  | -15.00 |
| 2026-08-17T21:25:01Z | GBPUSD | GBPUSD_LEVEL_BOUNCE_S | old | SELL | 13544.15 | BULL | BULL | AGAINST_TRADE | UNMATCHED | — | — |  |  | -11.70 |
| 2026-08-18T00:00:04Z | GBPUSD | GBPUSD_LEVEL_BOUNCE_S | old | SELL | 13550.8 | BULL | BULL | AGAINST_TRADE | UNMATCHED | — | — |  |  | +18.90 |
| 2026-08-18T06:04:33Z | GBPUSD | NEWS_STRATEGY_FADE | old | BUY | 13524.1 | BULL | BULL | AGREE_WITH_TRADE | UNMATCHED | — | — |  |  | +0.35 |
| 2026-08-18T06:25:01Z | GBPUSD | GBPUSD_LEVEL_BOUNCE_L | old | BUY | 13530.3 | BULL | BULL | AGREE_WITH_TRADE | UNMATCHED | — | — |  |  | -7.00 |
| 2026-08-18T07:00:02Z | GBPUSD | NEWS_STRATEGY_REVERSAL | old | BUY | 13527.7 | BULL | BULL | AGREE_WITH_TRADE | UNMATCHED | — | — |  |  | +11.45 |
| 2026-08-18T07:05:02Z | GBPUSD | GBPUSD_LEVEL_BOUNCE_L | old | BUY | 13529.6 | BULL | BULL | AGREE_WITH_TRADE | UNMATCHED | — | — |  |  | -8.60 |
| 2026-08-18T09:05:01Z | GBPUSD | GBPUSD_BB_BOUNCE_S | old | SELL | 13530.0 | BULL | BEAR | MIXED | UNMATCHED | — | — |  |  | +0.30 |
| 2026-08-18T10:30:04Z | GBPUSD | GBPUSD_BB_BOUNCE_L | old | BUY | 13529.8 | BULL | BEAR | MIXED | UNMATCHED | — | — |  |  | -1.70 |
| 2026-08-18T10:30:05Z | GBPUSD | GBPUSD_LEVEL_BOUNCE_L | old | BUY | 13529.8 | BULL | BEAR | MIXED | UNMATCHED | — | — |  |  | -7.50 |
| 2026-08-18T11:15:01Z | GBPUSD | GBPUSD_LEVEL_BOUNCE_L | old | BUY | 13524.4 | BULL | BEAR | MIXED | UNMATCHED | — | — |  |  | +11.05 |
| 2026-08-18T17:20:02Z | GBPUSD | GBPUSD_BB_BOUNCE_L | old | BUY | 13536.2 | BULL | BULL | AGREE_WITH_TRADE | UNMATCHED | — | — |  |  | +0.40 |
| 2026-08-18T22:00:02Z | GBPUSD | GBPUSD_LEVEL_BOUNCE_L | old | BUY | 13531.05 | BULL | FLAT | MIXED | UNMATCHED | — | — |  |  | -18.70 |
| 2026-08-19T01:25:01Z | GBPUSD | GBPUSD_LEVEL_BOUNCE_L | old | BUY | 13527.5 | BULL | BULL | AGREE_WITH_TRADE | UNMATCHED | — | — |  |  | +20.35 |
| 2026-08-19T04:40:02Z | GBPUSD | GBPUSD_BB_BOUNCE_S | old | SELL | 13537.2 | BULL | BULL | AGAINST_TRADE | UNMATCHED | — | — |  |  | -6.50 |
| 2026-08-19T06:45:01Z | GBPUSD | GBPUSD_LEVEL_BOUNCE_S | old | SELL | 13550.8 | BULL | BULL | AGAINST_TRADE | UNMATCHED | — | — |  |  | -6.60 |
| 2026-08-19T08:30:03Z | GBPUSD | GBPUSD_LEVEL_BOUNCE_S | old | SELL | 13554.8 | BULL | BULL | AGAINST_TRADE | UNMATCHED | — | — |  |  | -6.20 |
| 2026-08-19T11:50:03Z | GBPUSD | GBPUSD_BB_BOUNCE_L | old | BUY | 13555.2 | BULL | BULL | AGREE_WITH_TRADE | UNMATCHED | — | — |  |  | +16.30 |
| 2026-08-19T12:30:01Z | GBPUSD | GBPUSD_BB_BOUNCE_S | old | SELL | 13560.4 | BULL | BULL | AGAINST_TRADE | UNMATCHED | — | — |  |  | -15.50 |
| 2026-08-19T15:15:01Z | GBPUSD | GBPUSD_BB_BOUNCE_L | old | BUY | 13614.1 | BULL | BULL | AGREE_WITH_TRADE | UNMATCHED | — | — |  |  | -11.10 |
| 2026-08-19T15:30:03Z | GBPUSD | GBPUSD_BB_BOUNCE_L | old | BUY | 13607.8 | BULL | BULL | AGREE_WITH_TRADE | UNMATCHED | — | — |  |  | -1.60 |
| 2026-08-19T17:00:02Z | GBPUSD | GBPUSD_BB_BOUNCE_S | old | SELL | 13609.1 | BULL | BULL | AGAINST_TRADE | UNMATCHED | — | — |  |  | +13.65 |
| 2026-08-20T05:05:02Z | GBPUSD | GBPUSD_BB_BOUNCE_L | old | BUY | 13609.8 | BULL | BULL | AGREE_WITH_TRADE | UNMATCHED | — | — |  |  | +1.90 |
| 2026-08-20T06:55:03Z | GBPUSD | GBPUSD_BB_BOUNCE_S | old | SELL | 13611.4 | BULL | BULL | AGAINST_TRADE | UNMATCHED | — | — |  |  | -19.35 |
| 2026-08-20T07:35:01Z | GBPUSD | GBPUSD_EMA_PULLBACK_L | old | BUY | 13621.2 | BULL | BULL | AGREE_WITH_TRADE | UNMATCHED | — | — |  |  | +0.75 |
| 2026-08-20T08:00:03Z | GBPUSD | GBPUSD_EMA_PULLBACK_L | old | BUY | 13624.8 | BULL | BULL | AGREE_WITH_TRADE | UNMATCHED | — | — |  |  | +4.75 |
| 2026-08-20T08:45:02Z | GBPUSD | GBPUSD_TREND_V3_L | old | BUY | 13633.2 | BULL | BULL | AGREE_WITH_TRADE | UNMATCHED | — | — |  |  | +10.45 |
| 2026-08-20T11:25:03Z | GBPUSD | GBPUSD_BB_BOUNCE_L | old | BUY | 13638.7 | BULL | BULL | AGREE_WITH_TRADE | UNMATCHED | — | — |  |  | -7.40 |
| 2026-08-20T12:10:02Z | GBPUSD | GBPUSD_TREND_V3_L | old | BUY | 13627.2 | BULL | BULL | AGREE_WITH_TRADE | UNMATCHED | — | — |  |  | +0.85 |
| 2026-08-20T12:15:03Z | GBPUSD | GBPUSD_BB_BOUNCE_L | old | BUY | 13633.8 | BULL | BULL | AGREE_WITH_TRADE | UNMATCHED | — | — |  |  | -7.20 |
| 2026-08-20T13:10:03Z | GBPUSD | GBPUSD_BB_BOUNCE_S | old | SELL | 13646.9 | BULL | BULL | AGAINST_TRADE | UNMATCHED | — | — |  |  | +5.85 |
| 2026-08-20T13:15:03Z | GBPUSD | GBPUSD_LEVEL_BOUNCE_S | old | SELL | 13644.5 | BULL | BULL | AGAINST_TRADE | UNMATCHED | — | — |  |  | +12.45 |
| 2026-08-20T14:25:02Z | GBPUSD | GBPUSD_BB_BOUNCE_L | old | BUY | 13634.4 | BULL | BULL | AGREE_WITH_TRADE | UNMATCHED | — | — |  |  | +6.65 |
| 2026-08-20T15:10:02Z | GBPUSD | GBPUSD_BB_BOUNCE_S | old | SELL | 13634.1 | BULL | BULL | AGAINST_TRADE | UNMATCHED | — | — |  |  | -8.00 |
| 2026-08-20T15:35:01Z | GBPUSD | GBPUSD_BB_BOUNCE_S | old | SELL | 13638.1 | BULL | BULL | AGAINST_TRADE | UNMATCHED | — | — |  |  | +5.65 |
| 2026-08-20T16:35:01Z | GBPUSD | GBPUSD_CONFIRMATION_FALLBACK_S | old | SELL | 13626.1 | BULL | BULL | AGAINST_TRADE | UNMATCHED | — | — |  |  | -7.40 |
| 2026-08-20T16:45:01Z | GBPUSD | GBPUSD_BB_BOUNCE_L | old | BUY | 13628.3 | BULL | BULL | AGREE_WITH_TRADE | UNMATCHED | — | — |  |  | +3.75 |
| 2026-08-21T00:10:02Z | GBPUSD | GBPUSD_LEVEL_BOUNCE_S | old | SELL | 13639.6 | BULL | BULL | AGAINST_TRADE | UNMATCHED | — | — |  |  | -6.70 |
| 2026-08-21T00:30:02Z | GBPUSD | GBPUSD_LEVEL_BOUNCE_S | old | SELL | 13641.4 | BULL | BULL | AGAINST_TRADE | UNMATCHED | — | — |  |  | -7.60 |
| 2026-08-21T01:45:02Z | GBPUSD | GBPUSD_LEVEL_BOUNCE_S | old | SELL | 13643.6 | BULL | BULL | AGAINST_TRADE | UNMATCHED | — | — |  |  | -7.10 |
| 2026-08-21T03:00:02Z | GBPUSD | GBPUSD_LEVEL_BOUNCE_S | old | SELL | 13648.0 | BULL | BULL | AGAINST_TRADE | UNMATCHED | — | — |  |  | -7.40 |
| 2026-08-21T08:38:22Z | GBPUSD | NEWS_STRATEGY_FADE | old | SELL | 13649.6 | BULL | BULL | AGAINST_TRADE | UNMATCHED | — | — |  |  | -10.65 |
| 2026-08-21T08:50:02Z | EURUSD | BRIEFING_EXECUTION | briefing | BUY | 11702.3 | BULL | BULL | AGREE_WITH_TRADE | UNMATCHED | — | — |  |  | -16.90 |
| 2026-08-21T13:10:02Z | GBPUSD | GBPUSD_EMA_PULLBACK_S | old | SELL | 13639.1 | BULL | BULL | AGAINST_TRADE | UNMATCHED | — | — |  |  | -6.90 |
| 2026-08-24T04:15:02Z | GBPUSD | GBPUSD_BB_BOUNCE_L | old | BUY | 13645.1 | BULL | BULL | AGREE_WITH_TRADE | UNMATCHED | — | — |  |  | -1.20 |
| 2026-08-24T07:00:02Z | GBPUSD | GBPUSD_BB_BOUNCE_S | old | SELL | 13642.7 | BULL | BULL | AGAINST_TRADE | UNMATCHED | — | — |  |  | +8.90 |
| 2026-08-24T08:59:52Z | GBPUSD | BRIEFING_V5 | briefing | BUY | 13622.2 | BULL | BULL | AGREE_WITH_TRADE | UNMATCHED | — | — |  |  | +9.75 |
| 2026-08-24T11:10:03Z | GBPUSD | GBPUSD_BB_BOUNCE_L | old | BUY | 13629.6 | BULL | BULL | AGREE_WITH_TRADE | UNMATCHED | — | — |  |  | +3.60 |
| 2026-08-24T12:05:03Z | GBPUSD | GBPUSD_BB_BOUNCE_S | old | SELL | 13634.8 | BULL | BULL | AGAINST_TRADE | UNMATCHED | — | — |  |  | -6.30 |
| 2026-08-24T14:15:01Z | GBPUSD | GBPUSD_BB_BOUNCE_L | old | BUY | 13640.2 | BULL | BULL | AGREE_WITH_TRADE | UNMATCHED | — | — |  |  | +1.60 |
| 2026-08-24T16:05:02Z | GBPUSD | GBPUSD_BB_BOUNCE_L | old | BUY | 13634.6 | BULL | BULL | AGREE_WITH_TRADE | UNMATCHED | — | — |  |  | -5.80 |
| 2026-08-24T17:47:42Z | GBPUSD | BRIEFING_V5 | briefing | BUY | 13625.9 | BULL | BULL | AGREE_WITH_TRADE | UNMATCHED | — | — |  |  | +0.45 |
| 2026-08-25T05:36:45Z | GBPUSD | BRIEFING_V5 | briefing | BUY | 13626.9 | BULL | BULL | AGREE_WITH_TRADE | UNMATCHED | — | — |  |  | +2.25 |
| 2026-08-25T11:50:02Z | GBPUSD | GBPUSD_TREND_V3_UM_L | old | BUY | 13636.1 | BULL | BULL | AGREE_WITH_TRADE | UNMATCHED | — | — |  |  | -3.90 |
| 2026-08-25T12:45:02Z | GBPUSD | GBPUSD_BB_BOUNCE_L | old | BUY | 13630.4 | BULL | BULL | AGREE_WITH_TRADE | UNMATCHED | — | — |  |  | +5.50 |
| 2026-08-25T13:00:03Z | GBPUSD | GBPUSD_TREND_V3_UM_L | old | BUY | 13636.5 | BULL | BULL | AGREE_WITH_TRADE | UNMATCHED | — | — |  |  | +1.00 |
| 2026-08-25T14:40:02Z | GBPUSD | GBPUSD_BB_BOUNCE_L | old | BUY | 13637.5 | BULL | BULL | AGREE_WITH_TRADE | UNMATCHED | — | — |  |  | +1.90 |
| 2026-08-25T16:10:02Z | GBPUSD | GBPUSD_BB_BOUNCE_S | old | SELL | 13636.0 | BULL | BULL | AGAINST_TRADE | UNMATCHED | — | — |  |  | -16.90 |
| 2026-08-25T16:45:03Z | GBPUSD | GBPUSD_CONFIRMATION_FALLBACK_S | old | SELL | 13636.5 | BULL | BULL | AGAINST_TRADE | UNMATCHED | — | — |  |  | -8.10 |
| 2026-08-25T16:55:02Z | GBPUSD | GBPUSD_TREND_V3_UM_S | old | SELL | 13632.6 | BULL | BULL | AGAINST_TRADE | UNMATCHED | — | — |  |  | -3.50 |
| 2026-08-25T19:00:02Z | GBPUSD | GBPUSD_TREND_V3_UM_L | old | BUY | 13646.7 | BULL | BULL | AGREE_WITH_TRADE | UNMATCHED | — | — |  |  | -2.30 |
| 2026-08-25T19:55:03Z | GBPUSD | GBPUSD_TREND_V3_UM_L | old | BUY | 13651.1 | BULL | BULL | AGREE_WITH_TRADE | UNMATCHED | — | — |  |  | -1.00 |
| 2026-08-26T04:35:02Z | GBPUSD | GBPUSD_LEVEL_BOUNCE_L | old | BUY | 13635.8 | BULL | BULL | AGREE_WITH_TRADE | UNMATCHED | — | — |  |  | -6.30 |
| 2026-08-26T05:25:01Z | GBPUSD | GBPUSD_LEVEL_BOUNCE_L | old | BUY | 13633.8 | BULL | BULL | AGREE_WITH_TRADE | UNMATCHED | — | — |  |  | -6.90 |
| 2026-08-26T07:20:01Z | GBPUSD | GBPUSD_BB_BOUNCE_S | old | SELL | 13636.7 | BULL | BULL | AGAINST_TRADE | UNMATCHED | — | — |  |  | +1.55 |
| 2026-08-26T09:05:02Z | GBPUSD | GBPUSD_LEVEL_BOUNCE_L | old | BUY | 13628.1 | BULL | BEAR | MIXED | UNMATCHED | — | — |  |  | -8.40 |
| 2026-08-26T09:10:03Z | GBPUSD | GBPUSD_EMA_PULLBACK_S | old | SELL | 13622.8 | BULL | BEAR | MIXED | UNMATCHED | — | — |  |  | -11.95 |
| 2026-08-26T09:10:04Z | GBPUSD | GBPUSD_TREND_V3_UM_S | old | SELL | 13622.6 | BULL | BEAR | MIXED | UNMATCHED | — | — |  |  | -3.00 |
| 2026-08-26T10:40:01Z | GBPUSD | GBPUSD_LEVEL_BOUNCE_L | old | BUY | 13621.9 | BULL | BEAR | MIXED | UNMATCHED | — | — |  |  | -29.05 |
| 2026-08-26T13:20:01Z | GBPUSD | GBPUSD_EMA_PULLBACK_S | old | SELL | 13607.3 | BULL | BEAR | MIXED | UNMATCHED | — | — |  |  | +16.15 |
| 2026-08-26T13:40:01Z | GBPUSD | GBPUSD_TREND_V3_S | old | SELL | 13601.4 | BULL | BEAR | MIXED | UNMATCHED | — | — |  |  | +7.00 |
| 2026-08-26T18:35:03Z | GBPUSD | GBPUSD_TREND_V3_UM_S | old | SELL | 13591.5 | BULL | BEAR | MIXED | UNMATCHED | — | — |  |  | +0.25 |
| 2026-08-26T18:50:02Z | GBPUSD | GBPUSD_BB_BOUNCE_L | old | BUY | 13592.5 | BULL | BEAR | MIXED | UNMATCHED | — | — |  |  | -1.75 |
| 2026-08-27T04:05:02Z | GBPUSD | GBPUSD_BB_BOUNCE_L | old | BUY | 13590.1 | BULL | BEAR | MIXED | UNMATCHED | — | — |  |  | +2.20 |
| 2026-08-27T07:20:06Z | GBPUSD | GBPUSD_BB_BOUNCE_S | old | SELL | 13592.4 | BULL | BEAR | MIXED | UNMATCHED | — | — |  |  | +7.70 |
| 2026-08-27T08:45:03Z | GBPUSD | GBPUSD_BB_BOUNCE_L | old | BUY | 13584.7 | BULL | BEAR | MIXED | UNMATCHED | — | — |  |  | +11.90 |
| 2026-08-27T09:00:02Z | GBPUSD | GBPUSD_TREND_V3_UM_S | old | SELL | 13579.4 | BULL | BEAR | MIXED | UNMATCHED | — | — |  |  | -1.70 |
| 2026-08-27T09:20:01Z | GBPUSD | GBPUSD_EMA_PULLBACK_S | old | SELL | 13576.6 | BULL | BEAR | MIXED | UNMATCHED | — | — |  |  | -8.90 |
| 2026-08-27T10:40:03Z | GBPUSD | GBPUSD_TREND_V3_UM_S | old | SELL | 13574.4 | BULL | BEAR | MIXED | UNMATCHED | — | — |  |  | -4.20 |
| 2026-08-27T11:40:04Z | GBPUSD | GBPUSD_TREND_V3_UM_S | old | SELL | 13576.3 | BULL | BEAR | MIXED | UNMATCHED | — | — |  |  | -3.00 |
| 2026-08-27T13:15:01Z | GBPUSD | GBPUSD_CONFIRMATION_FALLBACK_L | old | BUY | 13587.7 | BULL | BEAR | MIXED | UNMATCHED | — | — |  |  | +1.55 |
| 2026-08-27T13:40:04Z | GBPUSD | GBPUSD_BB_BOUNCE_S | old | SELL | 13596.5 | BULL | BEAR | MIXED | UNMATCHED | — | — |  |  | +10.80 |
| 2026-08-27T15:10:04Z | GBPUSD | GBPUSD_BB_BOUNCE_L | old | BUY | 13585.7 | BULL | BEAR | MIXED | UNMATCHED | — | — |  |  | +9.50 |
| 2026-08-27T16:10:03Z | GBPUSD | GBPUSD_BB_BOUNCE_S | old | SELL | 13594.6 | BULL | BEAR | MIXED | UNMATCHED | — | — |  |  | +1.65 |
| 2026-08-27T16:30:01Z | GBPUSD | GBPUSD_EMA_PULLBACK_L | old | BUY | 13600.4 | BULL | BEAR | MIXED | UNMATCHED | — | — |  |  | -7.50 |
| 2026-08-27T16:30:03Z | GBPUSD | GBPUSD_TREND_V3_UM_L | old | BUY | 13600.4 | BULL | BEAR | MIXED | UNMATCHED | — | — |  |  | -7.40 |
| 2026-08-28T06:20:02Z | GBPUSD | GBPUSD_BB_BOUNCE_S | old | SELL | 13588.8 | BULL | BEAR | MIXED | UNMATCHED | — | — |  |  | -5.40 |
| 2026-08-28T06:45:02Z | GBPUSD | GBPUSD_PIVOT_BREAK_L | old | BUY | 13594.0 | BULL | BEAR | MIXED | UNMATCHED | — | — |  |  | -5.50 |
| 2026-08-28T07:05:02Z | GBPUSD | GBPUSD_TREND_V3_UM_S | old | SELL | 13588.7 | BULL | BEAR | MIXED | UNMATCHED | — | — |  |  | -2.60 |
| 2026-08-28T07:35:01Z | GBPUSD | GBPUSD_BB_BOUNCE_L | old | BUY | 13587.9 | BULL | BEAR | MIXED | UNMATCHED | — | — |  |  | -6.10 |
| 2026-08-28T08:45:01Z | GBPUSD | GBPUSD_TREND_V3_UM_S | old | SELL | 13583.8 | BULL | BEAR | MIXED | UNMATCHED | — | — |  |  | -2.70 |
| 2026-08-28T10:00:06Z | GBPUSD | GBPUSD_TREND_V3_UM_S | old | SELL | 13580.9 | BULL | BEAR | MIXED | UNMATCHED | — | — |  |  | -4.30 |
| 2026-08-28T10:50:01Z | GBPUSD | GBPUSD_BB_BOUNCE_S | old | SELL | 13588.7 | BULL | BEAR | MIXED | UNMATCHED | — | — |  |  | +8.65 |
| 2026-08-28T11:20:03Z | GBPUSD | GBPUSD_TREND_V3_UM_S | old | SELL | 13586.5 | BULL | BEAR | MIXED | UNMATCHED | — | — |  |  | -0.90 |
| 2026-08-28T12:10:02Z | GBPUSD | GBPUSD_TREND_V3_UM_S | old | SELL | 13583.2 | BULL | BEAR | MIXED | UNMATCHED | — | — |  |  | -1.70 |
| 2026-08-28T12:30:01Z | GBPUSD | GBPUSD_PIVOT_BREAK_S | old | SELL | 13578.8 | BULL | BEAR | MIXED | UNMATCHED | — | — |  |  | -0.15 |
| 2026-08-28T12:50:01Z | GBPUSD | GBPUSD_LEVEL_BOUNCE_L | old | BUY | 13581.4 | BULL | BEAR | MIXED | UNMATCHED | — | — |  |  | -24.60 |
| 2026-08-28T13:25:01Z | GBPUSD | GBPUSD_TREND_V3_UM_S | old | SELL | 13576.1 | BULL | BEAR | MIXED | UNMATCHED | — | — |  |  | -4.60 |
| 2026-08-28T14:30:03Z | GBPUSD | GBPUSD_TREND_V3_S | old | SELL | 13538.2 | BULL | BEAR | MIXED | UNMATCHED | — | — |  |  | -11.45 |
| 2026-08-28T14:40:03Z | GBPUSD | GBPUSD_LEVEL_BOUNCE_L | old | BUY | 13548.15 | BULL | BEAR | MIXED | UNMATCHED | — | — |  |  | -7.80 |
| 2026-08-31T05:35:01Z | GBPUSD | GBPUSD_BB_BOUNCE_S | old | SELL | 13542.9 | BEAR | BEAR | AGREE_WITH_TRADE | UNMATCHED | — | — |  |  | -1.40 |
| 2026-08-31T07:05:02Z | GBPUSD | GBPUSD_PIVOT_BREAK_S | old | SELL | 13539.0 | BEAR | BEAR | AGREE_WITH_TRADE | UNMATCHED | — | — |  |  | -9.00 |
| 2026-08-31T07:10:02Z | GBPUSD | GBPUSD_BB_BOUNCE_L | old | BUY | 13540.9 | BEAR | BEAR | AGAINST_TRADE | UNMATCHED | — | — |  |  | +5.40 |
| 2026-08-31T08:15:02Z | GBPUSD | GBPUSD_BB_BOUNCE_S | old | SELL | 13545.1 | BEAR | BEAR | AGREE_WITH_TRADE | UNMATCHED | — | — |  |  | +4.20 |
| 2026-08-31T09:05:01Z | GBPUSD | GBPUSD_BB_BOUNCE_L | old | BUY | 13543.7 | BEAR | BEAR | AGAINST_TRADE | UNMATCHED | — | — |  |  | +1.10 |
| 2026-08-31T10:55:01Z | GBPUSD | GBPUSD_BB_BOUNCE_L | old | BUY | 13540.0 | BEAR | BEAR | AGAINST_TRADE | UNMATCHED | — | — |  |  | +1.60 |
| 2026-08-31T11:10:02Z | GBPUSD | GBPUSD_EMA_PULLBACK_S | old | SELL | 13537.3 | BEAR | BEAR | AGREE_WITH_TRADE | UNMATCHED | — | — |  |  | -7.00 |
| 2026-08-31T11:50:01Z | GBPUSD | GBPUSD_TREND_V3_UM_S | old | SELL | 13538.6 | BEAR | BEAR | AGREE_WITH_TRADE | UNMATCHED | — | — |  |  | -5.10 |
| 2026-08-31T12:20:01Z | GBPUSD | GBPUSD_CONFIRMATION_FALLBACK_L | old | BUY | 13545.7 | BEAR | BEAR | AGAINST_TRADE | UNMATCHED | — | — |  |  | -8.40 |
| 2026-08-31T12:25:01Z | GBPUSD | GBPUSD_BB_BOUNCE_S | old | SELL | 13541.1 | BEAR | BEAR | AGREE_WITH_TRADE | UNMATCHED | — | — |  |  | +3.00 |
| 2026-08-31T13:05:01Z | GBPUSD | GBPUSD_BB_BOUNCE_L | old | BUY | 13540.7 | BEAR | BEAR | AGAINST_TRADE | UNMATCHED | — | — |  |  | +1.10 |
| 2026-08-31T13:20:00Z | GBPUSD | GBPUSD_CONFIRMATION_FALLBACK_L | old | BUY | 13543.1 | BEAR | BEAR | AGAINST_TRADE | UNMATCHED | — | — |  |  | -6.40 |
| 2026-08-31T13:35:01Z | GBPUSD | GBPUSD_BB_BOUNCE_S | old | SELL | 13543.8 | BEAR | BEAR | AGREE_WITH_TRADE | UNMATCHED | — | — |  |  | +3.70 |
| 2026-08-31T14:50:01Z | GBPUSD | GBPUSD_CONFIRMATION_FALLBACK_L | old | BUY | 13545.0 | BEAR | BEAR | AGAINST_TRADE | UNMATCHED | — | — |  |  | +1.15 |
| 2026-08-31T15:00:01Z | GBPUSD | GBPUSD_BB_BOUNCE_S | old | SELL | 13554.4 | BEAR | BEAR | AGREE_WITH_TRADE | UNMATCHED | — | — |  |  | +7.00 |
| 2026-08-31T17:25:01Z | GBPUSD | GBPUSD_TREND_V3_UM_L | old | BUY | 13551.4 | BEAR | BEAR | AGAINST_TRADE | UNMATCHED | — | — |  |  | -3.10 |
| 2026-08-31T19:55:01Z | GBPUSD | GBPUSD_TREND_V3_UM_L | old | BUY | 13551.4 | BEAR | BEAR | AGAINST_TRADE | UNMATCHED | — | — |  |  | -4.70 |
| 2026-09-01T05:10:01Z | GBPUSD | GBPUSD_BB_BOUNCE_S | old | SELL | 13544.9 | BEAR | BEAR | AGREE_WITH_TRADE | UNMATCHED | — | — |  |  | +1.45 |
| 2026-09-01T06:35:01Z | GBPUSD | GBPUSD_BB_BOUNCE_L | old | BUY | 13539.8 | BEAR | BEAR | AGAINST_TRADE | UNMATCHED | — | — |  |  | -7.40 |
| 2026-09-01T07:30:02Z | GBPUSD | GBPUSD_TREND_V3_UM_S | old | SELL | 13534.7 | BEAR | BEAR | AGREE_WITH_TRADE | UNMATCHED | — | — |  |  | -2.10 |
| 2026-09-01T07:45:01Z | GBPUSD | GBPUSD_LEVEL_BOUNCE_L | old | BUY | 13532.9 | BEAR | BEAR | AGAINST_TRADE | UNMATCHED | — | — |  |  | -1.15 |
| 2026-09-01T08:00:01Z | GBPUSD | GBPUSD_CONFIRMATION_FALLBACK_L | old | BUY | 13537.2 | BEAR | BEAR | AGAINST_TRADE | UNMATCHED | — | — |  |  | -5.95 |
| 2026-09-01T08:20:01Z | GBPUSD | GBPUSD_BB_BOUNCE_L | old | BUY | 13534.5 | BEAR | BEAR | AGAINST_TRADE | UNMATCHED | — | — |  |  | -2.60 |
| 2026-09-01T08:25:01Z | GBPUSD | GBPUSD_LEVEL_BOUNCE_L | old | BUY | 13532.8 | BEAR | BEAR | AGAINST_TRADE | UNMATCHED | — | — |  |  | -1.00 |
| 2026-09-01T10:35:02Z | GBPUSD | GBPUSD_TREND_V3_UM_S | old | SELL | 13537.7 | BEAR | BEAR | AGREE_WITH_TRADE | UNMATCHED | — | — |  |  | -1.00 |
| 2026-09-01T11:00:01Z | GBPUSD | GBPUSD_BB_BOUNCE_L | old | BUY | 13534.7 | BEAR | BEAR | AGAINST_TRADE | UNMATCHED | — | — |  |  | -9.00 |
| 2026-09-01T11:00:03Z | GBPUSD | GBPUSD_CONFIRMATION_FALLBACK_L | old | BUY | 13534.6 | BEAR | BEAR | AGAINST_TRADE | UNMATCHED | — | — |  |  | -9.70 |
| 2026-09-01T11:05:00Z | GBPUSD | GBPUSD_EMA_PULLBACK_S | old | SELL | 13531.2 | BEAR | BEAR | AGREE_WITH_TRADE | UNMATCHED | — | — |  |  | -11.55 |
| 2026-09-01T11:55:02Z | GBPUSD | GBPUSD_TREND_V3_UM_S | old | SELL | 13534.1 | BEAR | BEAR | AGREE_WITH_TRADE | UNMATCHED | — | — |  |  | +0.60 |
| 2026-09-01T12:20:01Z | GBPUSD | GBPUSD_LEVEL_BOUNCE_L | old | BUY | 13534.0 | BEAR | BEAR | AGAINST_TRADE | UNMATCHED | — | — |  |  | -3.30 |
| 2026-09-01T15:10:01Z | GBPUSD | GBPUSD_BB_BOUNCE_L | old | BUY | 13534.7 | BEAR | BEAR | AGAINST_TRADE | UNMATCHED | — | — |  |  | -8.30 |
| 2026-09-01T15:15:01Z | GBPUSD | GBPUSD_LEVEL_BOUNCE_L | old | BUY | 13532.4 | BEAR | BEAR | AGAINST_TRADE | UNMATCHED | — | — |  |  | -2.40 |
| 2026-09-01T15:35:01Z | GBPUSD | GBPUSD_LEVEL_BOUNCE_L | old | BUY | 13528.2 | BEAR | BEAR | AGAINST_TRADE | UNMATCHED | — | — |  |  | -0.90 |
| 2026-09-01T18:30:03Z | GBPUSD | GBPUSD_TREND_V3_UM_S | old | SELL | 13508.9 | BEAR | BEAR | AGREE_WITH_TRADE | UNMATCHED | — | — |  |  | -4.60 |
| 2026-09-01T19:30:01Z | GBPUSD | GBPUSD_TREND_V3_UM_S | old | SELL | 13512.5 | BEAR | BEAR | AGREE_WITH_TRADE | UNMATCHED | — | — |  |  | -0.80 |
| 2026-09-02T05:40:03Z | GBPUSD | GBPUSD_BB_BOUNCE_S | old | SELL | 13499.9 | BEAR | BEAR | AGREE_WITH_TRADE | UNMATCHED | — | — |  |  | -0.10 |
| 2026-09-02T07:45:02Z | GBPUSD | GBPUSD_BB_BOUNCE_S | old | SELL | 13508.5 | BEAR | BEAR | AGREE_WITH_TRADE | UNMATCHED | — | — |  |  | +4.40 |
| 2026-09-02T09:05:08Z | GBPUSD | GBPUSD_BB_BOUNCE_L | old | BUY | 13505.0 | BEAR | BEAR | AGAINST_TRADE | UNMATCHED | — | — |  |  | -13.05 |
| 2026-09-02T09:55:01Z | GBPUSD | GBPUSD_TREND_V3_S | old | SELL | 13488.5 | BEAR | BEAR | AGREE_WITH_TRADE | UNMATCHED | — | — |  |  | -2.45 |
| 2026-09-02T10:10:01Z | GBPUSD | GBPUSD_STRUCTURE_BREAK_S | old | SELL | 13484.3 | BEAR | BEAR | AGREE_WITH_TRADE | UNMATCHED | — | — |  |  | -6.70 |
| 2026-09-02T12:00:02Z | GBPUSD | GBPUSD_BB_BOUNCE_S | old | SELL | 13484.8 | BEAR | BEAR | AGREE_WITH_TRADE | UNMATCHED | — | — |  |  | +6.50 |
| 2026-09-02T13:35:01Z | GBPUSD | GBPUSD_BB_BOUNCE_S | old | SELL | 13492.9 | BEAR | BEAR | AGREE_WITH_TRADE | UNMATCHED | — | — |  |  | -21.15 |
| 2026-09-02T14:10:01Z | GBPUSD | GBPUSD_BB_BOUNCE_S | old | SELL | 13501.8 | BEAR | BEAR | AGREE_WITH_TRADE | UNMATCHED | — | — |  |  | +0.70 |
| 2026-09-02T15:50:01Z | GBPUSD | GBPUSD_BB_BOUNCE_L | old | BUY | 13497.9 | BEAR | BEAR | AGAINST_TRADE | UNMATCHED | — | — |  |  | -12.55 |
| 2026-09-02T16:00:01Z | GBPUSD | GBPUSD_LEVEL_BOUNCE_L | old | BUY | 13502.5 | BEAR | BEAR | AGAINST_TRADE | UNMATCHED | — | — |  |  | -11.30 |
| 2026-09-02T19:50:02Z | GBPUSD | GBPUSD_TREND_V3_UM_S | old | SELL | 13483.8 | BEAR | BEAR | AGREE_WITH_TRADE | UNMATCHED | — | — |  |  | -5.10 |
| 2026-09-03T05:15:02Z | GBPUSD | GBPUSD_BB_BOUNCE_L | old | BUY | 13492.0 | BEAR | BEAR | AGAINST_TRADE | UNMATCHED | — | — |  |  | +2.45 |
| 2026-09-03T09:45:02Z | GBPUSD | GBPUSD_BB_BOUNCE_L | old | BUY | 13494.5 | BEAR | BEAR | AGAINST_TRADE | UNMATCHED | — | — |  |  | +5.45 |
| 2026-09-03T13:00:04Z | GBPUSD | GBPUSD_BB_BOUNCE_S | old | SELL | 13518.5 | BEAR | BEAR | AGREE_WITH_TRADE | UNMATCHED | — | — |  |  | +9.35 |
| 2026-09-03T14:50:02Z | GBPUSD | GBPUSD_BB_BOUNCE_L | old | BUY | 13507.5 | BEAR | BEAR | AGAINST_TRADE | UNMATCHED | — | — |  |  | +8.45 |
| 2026-09-03T15:30:02Z | GBPUSD | GBPUSD_LEVEL_BOUNCE_S | old | SELL | 13537.4 | BEAR | BEAR | AGREE_WITH_TRADE | UNMATCHED | — | — |  |  | -1.00 |
| 2026-09-03T18:05:01Z | GBPUSD | GBPUSD_BB_BOUNCE_L | old | BUY | 13541.6 | BEAR | BULL | MIXED | UNMATCHED | — | — |  |  | -16.00 |
| 2026-09-03T19:50:01Z | GBPUSD | GBPUSD_TREND_V3_UM_L | old | BUY | 13528.2 | BEAR | BULL | MIXED | UNMATCHED | — | — |  |  | -2.50 |
| 2026-09-04T08:05:12Z | GBPUSD | GBPUSD_BB_BOUNCE_L | old | BUY | 13537.5 | BEAR | BULL | MIXED | MATCHED | PASS | PASS:LONG_with_TREND_UP | False | False | -8.35 |
| 2026-09-04T11:00:01Z | GBPUSD | GBPUSD_BB_BOUNCE_S | old | SELL | 13530.9 | BEAR | BULL | MIXED | MATCHED | BLOCK | BLOCKED:SHORT_counter_TREND_UP | False | False | +41.40 |
| 2026-09-04T12:30:54Z | GBPUSD | NEWS_STRATEGY_CONT | old | BUY | 13500.05 | BEAR | BULL | MIXED | MATCHED | PASS | PASS:HTF_EXEMPT:NEWS_STRATEGY:NEWS_STRATEGY_CONT:dir=BUY:... | False | False | +19.60 |
| 2026-09-04T12:31:33Z | EURUSD | NEWS_STRATEGY_CONT | old | SELL | 11585.5 | BULL | BULL | AGAINST_TRADE | MATCHED | PASS | PASS:HTF_EXEMPT:NEWS_STRATEGY:NEWS_STRATEGY_CONT:dir=SELL... | False | False | -10.50 |
| 2026-09-04T13:20:01Z | EURUSD | NEWS_STRATEGY_REVERSAL | old | BUY | 11607.8 | BULL | BULL | AGREE_WITH_TRADE | MATCHED | PASS | PASS:TREND_direction_indeterminate | False | False | +1.60 |
| 2026-09-04T13:40:01Z | GBPUSD | GBPUSD_STRUCTURE_BREAK_L | old | BUY | 13508.7 | BEAR | BULL | MIXED | MATCHED | BLOCK | BLOCKED:RANGE_no_continuation:GBPUSD_STRUCTURE_BREAK_L | False | False | +5.20 |
| 2026-09-07T07:05:02Z | GBPUSD | GBPUSD_TREND_V3_L | old | BUY | 13529.0 | BEAR | BEAR | AGAINST_TRADE | MATCHED | BLOCK | BLOCKED:RANGE_no_continuation:GBPUSD_TREND_V3_L | False | False | +7.90 |
| 2026-09-07T12:10:01Z | GBPUSD | GBPUSD_BB_BOUNCE_L | old | BUY | 13531.6 | BEAR | BULL | MIXED | MATCHED | PASS | PASS:LONG_with_TREND_UP | False | False | +6.70 |
| 2026-09-07T12:25:01Z | GBPUSD | GBPUSD_TREND_V3_UM_L | old | BUY | 13534.5 | BEAR | BULL | MIXED | MATCHED | PASS | PASS:LONG_with_TREND_UP | False | False | +2.30 |
| 2026-09-07T14:15:02Z | GBPUSD | GBPUSD_TREND_V3_UM_L | old | BUY | 13540.9 | BEAR | BULL | MIXED | MATCHED | PASS | PASS:LONG_with_TREND_UP | False | False | -1.20 |
| 2026-09-07T16:30:01Z | GBPUSD | GBPUSD_TREND_V3_UM_L | old | BUY | 13543.5 | BEAR | BULL | MIXED | MATCHED | PASS | PASS:LONG_with_TREND_UP | False | False | -1.10 |
| 2026-09-08T08:05:01Z | GBPUSD | GBPUSD_BB_BOUNCE_L | old | BUY | 13534.3 | BULL | BULL | AGREE_WITH_TRADE | MATCHED | PASS | PASS:RANGE_reversal_allowed:GBPUSD_BB_BOUNCE_L | False | False | -6.20 |
| 2026-09-08T09:50:02Z | GBPUSD | GBPUSD_BB_BOUNCE_S | old | SELL | 13527.9 | BULL | BULL | AGAINST_TRADE | MATCHED | PASS | PASS:RANGE_reversal_allowed:GBPUSD_BB_BOUNCE_S | False | False | +4.50 |
| 2026-09-08T11:45:04Z | GBPUSD | GBPUSD_BB_BOUNCE_S | old | SELL | 13536.7 | BULL | BULL | AGAINST_TRADE | MATCHED | PASS | PASS:RANGE_reversal_allowed:GBPUSD_BB_BOUNCE_S | False | False | -19.65 |
| 2026-09-08T13:25:02Z | GBPUSD | GBPUSD_TREND_V3_L | old | BUY | 13558.7 | BULL | BULL | AGREE_WITH_TRADE | MATCHED | PASS | PASS:LONG_with_TREND_UP | False | False | -11.25 |
| 2026-09-08T14:20:07Z | GBPUSD | GBPUSD_BB_BOUNCE_L | old | BUY | 13546.8 | BULL | BULL | AGREE_WITH_TRADE | MATCHED | PASS | PASS:LONG_with_TREND_UP | False | False | -7.20 |
| 2026-09-09T07:25:01Z | GBPUSD | GBPUSD_LEVEL_BOUNCE_S | old | SELL | 13561.4 | BULL | BULL | AGAINST_TRADE | MATCHED | BLOCK | BLOCKED:SHORT_counter_TREND_UP | False | False | -0.80 |
| 2026-09-09T08:15:09Z | GBPUSD | GBPUSD_BB_BOUNCE_L | old | BUY | 13549.8 | BULL | BULL | AGREE_WITH_TRADE | MATCHED | PASS | PASS:LONG_with_TREND_UP | False | False | +10.70 |
| 2026-09-09T09:52:55Z | GBPUSD | BRIEFING_V5 | briefing | BUY | 13537.3 | BULL | BULL | AGREE_WITH_TRADE | MATCHED | BLOCK | BLOCKED:RANGE_no_continuation:BRIEFING_V5 | False | False | +21.85 |
| 2026-09-09T09:57:35Z | EURUSD | BRIEFING_V5 | briefing | BUY | 11623.9 | BULL | BULL | AGREE_WITH_TRADE | MATCHED | PASS | PASS:LONG_with_TREND_UP | False | False | +14.40 |
| 2026-09-09T11:40:04Z | GBPUSD | GBPUSD_BB_BOUNCE_S | old | SELL | 13559.9 | BULL | BULL | AGAINST_TRADE | MATCHED | PASS | PASS:RANGE_reversal_allowed:GBPUSD_BB_BOUNCE_S | False | False | +13.90 |
| 2026-09-09T11:45:02Z | GBPUSD | GBPUSD_LEVEL_BOUNCE_S | old | SELL | 13558.6 | BULL | BULL | AGAINST_TRADE | MATCHED | BLOCK | BLOCKED:RANGE_no_continuation:GBPUSD_LEVEL_BOUNCE_S | False | False | -3.40 |
| 2026-09-09T14:25:01Z | GBPUSD | GBPUSD_LEVEL_BOUNCE_S | old | SELL | 13558.3 | BULL | BULL | AGAINST_TRADE | MATCHED | BLOCK | BLOCKED:SHORT_counter_TREND_UP | False | False | -5.00 |
| 2026-09-09T15:11:23Z | EURUSD | BRIEFING_V5 | briefing | BUY | 11627.8 | BULL | BULL | AGREE_WITH_TRADE | MATCHED | PASS | PASS:LONG_with_TREND_UP | False | False | +1.10 |
| 2026-09-09T15:30:04Z | GBPUSD | GBPUSD_BB_BOUNCE_L | old | BUY | 13546.3 | BULL | BULL | AGREE_WITH_TRADE | MATCHED | PASS | PASS:LONG_with_TREND_UP | False | False | +0.10 |
| 2026-09-10T07:15:11Z | GBPUSD | GBPUSD_BB_BOUNCE_L | old | BUY | 13553.1 | BULL | BULL | AGREE_WITH_TRADE | MATCHED | PASS | PASS:RANGE_reversal_allowed:GBPUSD_BB_BOUNCE_L | False | False | -20.00 |
| 2026-09-10T08:20:01Z | GBPUSD | GBPUSD_CONFIRMATION_FALLBACK_L | old | BUY | 13551.4 | BULL | BULL | AGREE_WITH_TRADE | MATCHED | BLOCK | BLOCKED:RANGE_no_continuation:GBPUSD_CONFIRMATION_FALLBACK_L | False | False | -10.50 |
| 2026-09-10T09:00:01Z | GBPUSD | GBPUSD_TREND_V3_UM_L | old | BUY | 13557.5 | BULL | BULL | AGREE_WITH_TRADE | MATCHED | BLOCK | BLOCKED:RANGE_no_continuation:GBPUSD_TREND_V3_UM_L | False | False | -5.90 |
| 2026-09-10T10:31:24Z | EURUSD | BRIEFING_V5 | briefing | BUY | 11630.1 | BULL | BULL | AGREE_WITH_TRADE | MATCHED | BLOCK | BLOCKED:RANGE_no_continuation:BRIEFING_V5 | False | False | -13.20 |
| 2026-09-10T11:10:02Z | GBPUSD | GBPUSD_TREND_V3_S | old | SELL | 13531.8 | BULL | BULL | AGAINST_TRADE | MATCHED | PASS | PASS:TREND_direction_indeterminate | False | False | +25.45 |
| 2026-09-10T15:00:03Z | GBPUSD | GBPUSD_TREND_V3_S | old | SELL | 13529.2 | BULL | BEAR | MIXED | MATCHED | PASS | PASS:TREND_direction_indeterminate | False | False | -1.70 |
| 2026-09-10T15:30:03Z | GBPUSD | GBPUSD_BB_BOUNCE_S | old | SELL | 13528.1 | BULL | BEAR | MIXED | MATCHED | PASS | PASS:TREND_direction_indeterminate | False | False | +13.30 |
| 2026-09-11T08:25:01Z | GBPUSD | GBPUSD_BB_BOUNCE_L | old | BUY | 13514.6 | BEAR | BEAR | AGAINST_TRADE | MATCHED | BLOCK | BLOCKED:LONG_counter_TREND_DOWN | False | False | -4.90 |
| 2026-09-11T12:34:09Z | GBPUSD | NEWS_STRATEGY_CONT | old | BUY | 13501.1 | BEAR | BEAR | AGAINST_TRADE | MATCHED | PASS | PASS:HTF_EXEMPT:NEWS_STRATEGY:NEWS_STRATEGY_CONT:dir=BUY:... | False | False | +26.50 |
| 2026-09-11T12:36:10Z | EURUSD | NEWS_STRATEGY_CONT | old | BUY | 11588.1 | BEAR | BEAR | AGAINST_TRADE | MATCHED | PASS | PASS:HTF_EXEMPT:NEWS_STRATEGY:NEWS_STRATEGY_CONT:dir=BUY:... | False | False | +14.50 |
| 2026-09-11T16:00:01Z | GBPUSD | GBPUSD_BB_BOUNCE_L | old | BUY | 13521.4 | BEAR | BEAR | AGAINST_TRADE | MATCHED | PASS | PASS:RANGE_reversal_allowed:GBPUSD_BB_BOUNCE_L | False | False | +6.30 |
| 2026-09-11T16:50:01Z | GBPUSD | GBPUSD_CONFIRMATION_FALLBACK_L | old | BUY | 13523.2 | BEAR | BEAR | AGAINST_TRADE | MATCHED | BLOCK | BLOCKED:RANGE_no_continuation:GBPUSD_CONFIRMATION_FALLBACK_L | False | False | +4.30 |
| 2026-09-14T16:40:05Z | GBPUSD | GBPUSD_TREND_V3_L | old | BUY | 13498.6 | BEAR | BEAR | AGAINST_TRADE | MATCHED | BLOCK | BLOCKED:LONG_counter_TREND_DOWN | False | False | +10.35 |
| 2026-09-15T10:00:06Z | GBPUSD | GBPUSD_BB_BOUNCE_S | old | SELL | 13478.1 | BEAR | BEAR | AGREE_WITH_TRADE | MATCHED | PASS | PASS:RANGE_reversal_allowed:GBPUSD_BB_BOUNCE_S | False | False | -6.10 |
| 2026-09-15T11:00:03Z | GBPUSD | GBPUSD_TREND_V3_UM_S | old | SELL | 13474.4 | BEAR | BEAR | AGREE_WITH_TRADE | MATCHED | BLOCK | BLOCKED:RANGE_no_continuation:GBPUSD_TREND_V3_UM_S | False | False | -6.10 |
| 2026-09-15T13:40:02Z | GBPUSD | GBPUSD_BB_BOUNCE_L | old | BUY | 13485.1 | BEAR | BEAR | AGAINST_TRADE | MATCHED | BLOCK | BLOCKED:LONG_counter_TREND_DOWN | False | False | +3.90 |
| 2026-09-16T09:40:05Z | GBPUSD | GBPUSD_BB_BOUNCE_S | old | SELL | 13470.1 | BEAR | BEAR | AGREE_WITH_TRADE | MATCHED | PASS | PASS:RANGE_reversal_allowed:GBPUSD_BB_BOUNCE_S | False | False | +20.50 |
| 2026-09-16T10:00:03Z | GBPUSD | GBPUSD_TREND_V3_UM_S | old | SELL | 13466.9 | BEAR | BEAR | AGREE_WITH_TRADE | MATCHED | BLOCK | BLOCKED:RANGE_no_continuation:GBPUSD_TREND_V3_UM_S | False | False | -4.00 |
| 2026-09-16T11:10:07Z | GBPUSD | GBPUSD_TREND_V3_UM_S | old | SELL | 13463.9 | BEAR | BEAR | AGREE_WITH_TRADE | MATCHED | BLOCK | BLOCKED:RANGE_no_continuation:GBPUSD_TREND_V3_UM_S | False | False | +5.50 |
| 2026-09-16T13:10:02Z | GBPUSD | BRIEFING_EXECUTION | briefing | SELL | 13456.6 | BEAR | BEAR | AGREE_WITH_TRADE | MATCHED | PASS | PASS:SHORT_with_TREND_DOWN | False | False | +37.20 |
| 2026-09-16T14:05:04Z | GBPUSD | GBPUSD_TREND_V3_UM_S | old | SELL | 13448.2 | BEAR | BEAR | AGREE_WITH_TRADE | MATCHED | PASS | PASS:SHORT_with_TREND_DOWN | False | False | -8.10 |
| 2026-09-16T14:50:09Z | GBPUSD | GBPUSD_BB_BOUNCE_S | old | SELL | 13458.9 | BEAR | BEAR | AGREE_WITH_TRADE | MATCHED | PASS | PASS:SHORT_with_TREND_DOWN | False | False | +5.00 |
| 2026-09-17T15:45:05Z | GBPUSD | GBPUSD_TREND_V3_S | old | SELL | 13340.3 | BEAR | BEAR | AGREE_WITH_TRADE | MATCHED | PASS | PASS:SHORT_with_TREND_DOWN | False | False | -11.00 |
| 2026-09-18T07:45:04Z | GBPUSD | GBPUSD_BB_BOUNCE_L | old | BUY | 13369.6 | BEAR | BEAR | AGAINST_TRADE | MATCHED | BLOCK | BLOCKED:LONG_counter_TREND_DOWN | False | False | -20.30 |
| 2026-09-18T12:10:06Z | GBPUSD | GBPUSD_EMA_PULLBACK_S | old | SELL | 13342.9 | BEAR | BEAR | AGREE_WITH_TRADE | MATCHED | PASS | PASS:SHORT_with_TREND_DOWN | False | False | -12.05 |
| 2026-09-22T11:45:03Z | GBPUSD | GBPUSD_LEVEL_BOUNCE_L | old | BUY | 13358.7 | BEAR | BEAR | AGAINST_TRADE | MATCHED | BLOCK | BLOCKED:LONG_counter_TREND_DOWN | False | False | -34.35 |
| 2026-09-22T14:25:08Z | GBPUSD | GBPUSD_BB_BOUNCE_L | old | BUY | 13356.3 | BEAR | BEAR | AGAINST_TRADE | MATCHED | BLOCK | BLOCKED:LONG_counter_TREND_DOWN | False | False | -19.75 |
| 2026-09-22T16:10:07Z | GBPUSD | GBPUSD_TREND_V3_S | old | SELL | 13324.6 | BEAR | BEAR | AGREE_WITH_TRADE | MATCHED | PASS | PASS:SHORT_with_TREND_DOWN | False | False | -8.75 |
| 2026-09-22T18:00:14Z | GBPUSD | GBPUSD_BB_BOUNCE_S | old | SELL | 13331.8 | BEAR | BEAR | AGREE_WITH_TRADE | MATCHED | PASS | PASS:SHORT_with_TREND_DOWN | False | False | -15.40 |
| 2026-09-22T18:21:25Z | GBPUSD | GBPUSD_LEVEL_BOUNCE_S | old | SELL | 1.335 | BEAR | BEAR | AGREE_WITH_TRADE | UNMATCHED | — | — |  |  |  |
| 2026-09-22T18:21:25Z | GBPUSD | GBPUSD_LEVEL_BOUNCE_S | old | SELL | 1.335 | BEAR | BEAR | AGREE_WITH_TRADE | UNMATCHED | — | — |  |  |  |
| 2026-09-22T18:21:26Z | GBPUSD | GBPUSD_LEVEL_BOUNCE_S | old | SELL | 1.335 | BEAR | BEAR | AGREE_WITH_TRADE | UNMATCHED | — | — |  |  |  |
| 2026-09-23T06:00:02Z | GBPUSD | GBPUSD_LEVEL_BOUNCE_L | old | BUY | 13313.8 | BEAR | BEAR | AGAINST_TRADE | MATCHED | BLOCK | BLOCKED:LONG_counter_TREND_DOWN | False | False | -4.50 |
| 2026-09-23T06:25:02Z | GBPUSD | GBPUSD_LEVEL_BOUNCE_L | old | BUY | 13315.0 | BEAR | BEAR | AGAINST_TRADE | MATCHED | BLOCK | BLOCKED:LONG_counter_TREND_DOWN | False | False | -22.00 |
| 2026-09-24T06:05:07Z | GBPUSD | GBPUSD_BB_BOUNCE_L | old | BUY | 13238.7 | BEAR | BEAR | AGAINST_TRADE | MATCHED | BLOCK | BLOCKED:LONG_counter_TREND_DOWN | False | False | +8.10 |
| 2026-09-24T08:00:06Z | GBPUSD | GBPUSD_BB_BOUNCE_S | old | SELL | 13246.6 | BEAR | BEAR | AGREE_WITH_TRADE | MATCHED | PASS | PASS:SHORT_with_TREND_DOWN | False | False | +3.30 |
| 2026-09-24T09:00:05Z | GBPUSD | GBPUSD_BB_BOUNCE_L | old | BUY | 13237.5 | BEAR | BEAR | AGAINST_TRADE | MATCHED | BLOCK | BLOCKED:LONG_counter_TREND_DOWN | False | False | -19.65 |
| 2026-09-24T12:10:14Z | GBPUSD | GBPUSD_BB_BOUNCE_L | old | BUY | 13220.4 | BEAR | BEAR | AGAINST_TRADE | MATCHED | BLOCK | BLOCKED:LONG_counter_TREND_DOWN | False | False | +10.80 |
| 2026-09-24T13:05:24Z | GBPUSD | GBPUSD_BB_BOUNCE_S | old | SELL | 13226.0 | BEAR | BEAR | AGREE_WITH_TRADE | MATCHED | PASS | PASS:SHORT_with_TREND_DOWN | False | False | +10.60 |
| 2026-09-24T14:40:09Z | GBPUSD | GBPUSD_BB_BOUNCE_L | old | BUY | 13217.7 | BEAR | BEAR | AGAINST_TRADE | MATCHED | BLOCK | BLOCKED:LONG_counter_TREND_DOWN | False | False | +1.65 |
| 2026-09-24T18:10:05Z | GBPUSD | GBPUSD_BB_BOUNCE_L | old | BUY | 13213.3 | BEAR | BEAR | AGAINST_TRADE | MATCHED | BLOCK | BLOCKED:LONG_counter_TREND_DOWN | False | False | +5.70 |
| 2026-09-25T06:50:07Z | GBPUSD | GBPUSD_EMA_PULLBACK_L | old | BUY | 13227.5 | BEAR | BEAR | AGAINST_TRADE | MATCHED | BLOCK | BLOCKED:LONG_counter_TREND_DOWN | False | False | +7.65 |
| 2026-09-25T08:10:10Z | GBPUSD | GBPUSD_TREND_V3_UM_L | old | BUY | 13237.0 | BEAR | BEAR | AGAINST_TRADE | MATCHED | BLOCK | BLOCKED:LONG_counter_TREND_DOWN | False | False | -5.90 |
| 2026-09-25T15:15:07Z | GBPUSD | GBPUSD_STRUCTURE_BREAK_S | old | SELL | 13235.8 | BEAR | BEAR | AGREE_WITH_TRADE | MATCHED | PASS | PASS:TREND_direction_indeterminate | False | False | -11.75 |
| 2026-10-01T07:55:07Z | EURUSD | BRIEFING_EXECUTION | briefing | SELL | 11309.5 | BEAR | BEAR | AGREE_WITH_TRADE | MATCHED | PASS | PASS:SHORT_with_TREND_DOWN | False | False | +25.40 |
| 2026-10-01T11:50:06Z | EURUSD | BRIEFING_EXECUTION | briefing | SELL | 11303.1 | BEAR | BEAR | AGREE_WITH_TRADE | MATCHED | PASS | PASS:SHORT_with_TREND_DOWN | False | False | +17.90 |
| 2026-10-05T06:40:08Z | EURUSD | BRIEFING_EXECUTION | briefing | SELL | 11176.3 | BEAR | BEAR | AGREE_WITH_TRADE | MATCHED | PASS | PASS:SHORT_with_TREND_DOWN | False | False | -23.00 |
| 2026-10-05T12:05:14Z | EURUSD | BRIEFING_EXECUTION | briefing | SELL | 11203.8 | BEAR | BEAR | AGREE_WITH_TRADE | MATCHED | PASS | PASS:SHORT_with_TREND_DOWN | False | False | -22.90 |
| 2026-10-07T08:45:58Z | GBPUSD | BOUNCE_ENGINE | bounce | BUY | 13243.55 | BEAR | BEAR | AGAINST_TRADE | MATCHED | PASS | PASS:TREND_direction_indeterminate | False | False |  |
| 2026-10-07T09:46:58Z | GBPUSD | BOUNCE_ENGINE | bounce | BUY | 13230.849999999999 | BEAR | BEAR | AGAINST_TRADE | MATCHED | BLOCK | BLOCKED:RANGE_no_continuation:BOUNCE_A_L | False | False |  |
| 2026-10-07T11:58:44Z | GBPUSD | BOUNCE_ENGINE | bounce | BUY | 13210.349999999999 | BEAR | BEAR | AGAINST_TRADE | MATCHED | PASS | PASS:TREND_direction_indeterminate | False | False |  |
| 2026-10-07T12:35:25Z | GBPUSD | BOUNCE_ENGINE | bounce | BUY | 13200.45 | BEAR | BEAR | AGAINST_TRADE | MATCHED | PASS | PASS:TREND_direction_indeterminate | False | False |  |
| 2026-10-07T13:06:04Z | EURUSD | BRIEFING_EXECUTION | briefing | SELL | 11178.7 | BEAR | BEAR | AGREE_WITH_TRADE | MATCHED | PASS | PASS:TREND_direction_indeterminate | False | False | -15.50 |
| 2026-10-07T15:22:50Z | GBPUSD | BOUNCE_ENGINE | bounce | SELL | 13210.55 | BEAR | BEAR | AGREE_WITH_TRADE | MATCHED | PASS | PASS:TREND_direction_indeterminate | False | False |  |


---

**End of report.** No changes made under `/opt/tradingbot`. Research script at `/tmp/htf_align_v2/htf_bias_v2.py` (not committed to /opt/tradingbot).
