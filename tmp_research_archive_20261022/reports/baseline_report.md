# Execution Latency Analysis

**Source:** `/tmp/signal_log_backfilled.jsonl`  
**Records:** 854  
**Generated:** 2026-05-08T16:48:52.087443+00:00

- **Natively instrumented:** 0  
- **Backfilled (timestamp_open → t_ig_confirm only):** 854  
- **Pre-instrumentation, no backfill:** 0


> Only backfilled data is present — derived deltas will all be null (only `t_ig_confirm_epoch_ms` is recoverable from pre-instrumentation logs).  Re-run once natively-instrumented data accumulates.


## Fire-path deltas

### Distribution

| field | count | mean | median | p90 | p99 | max |
|---|---|---|---|---|---|---|
| `decision_to_dispatch_ms` | 0 | None | None | None | None | None |
| `dispatch_to_ig_request_ms` | 0 | None | None | None | None | None |
| `ig_request_to_ack_ms` | 0 | None | None | None | None | None |
| `ack_to_confirm_ms` | 0 | None | None | None | None | None |
| `total_decision_to_confirm_ms` | 0 | None | None | None | None | None |

### Per-strategy — total `total_decision_to_confirm_ms` by `strategy`

| strategy | count | mean | median | p90 | p99 | max |
|---|---|---|---|---|---|---|
| 3CO | 0 | None | None | None | None | None |
| BB_REVERSAL | 0 | None | None | None | None | None |
| BRIEFING_EXECUTION | 0 | None | None | None | None | None |
| BRIEFING_HUNT | 0 | None | None | None | None | None |
| BRIEFING_LIQUIDITY | 0 | None | None | None | None | None |
| BRIEFING_SWEEP | 0 | None | None | None | None | None |
| CONTINUATION_SWEEP | 0 | None | None | None | None | None |
| DAILY_DOUBLE | 0 | None | None | None | None | None |
| EMA_PULLBACK | 0 | None | None | None | None | None |
| GBPUSD_BB_BOUNCE_L | 0 | None | None | None | None | None |
| GBPUSD_BB_BOUNCE_S | 0 | None | None | None | None | None |
| GBPUSD_BB_REV_PAT_L | 0 | None | None | None | None | None |
| GBPUSD_BB_REV_PAT_S | 0 | None | None | None | None | None |
| GBPUSD_TREND_CONT_L | 0 | None | None | None | None | None |
| GBPUSD_TREND_CONT_S | 0 | None | None | None | None | None |
| LIQUIDITY_SWEEP | 0 | None | None | None | None | None |
| NEWS_STRATEGY | 0 | None | None | None | None | None |
| NEWS_TICK | 0 | None | None | None | None | None |
| REVERSAL_SWEEP | 0 | None | None | None | None | None |
| WINDOW_SWEEP | 0 | None | None | None | None | None |

### Per-pair — total `total_decision_to_confirm_ms` by `pair`

| pair | count | mean | median | p90 | p99 | max |
|---|---|---|---|---|---|---|
| EURUSD | 0 | None | None | None | None | None |
| GBPJPY | 0 | None | None | None | None | None |
| GBPUSD | 0 | None | None | None | None | None |
| USDCAD | 0 | None | None | None | None | None |
| USDJPY | 0 | None | None | None | None | None |

### Time-of-day (UTC hour) — `total_decision_to_confirm_ms`

| hour_utc | count | mean | median | p90 | p99 | max |
|---|---|---|---|---|---|---|
| 00 | 0 | None | None | None | None | None |
| 02 | 0 | None | None | None | None | None |
| 03 | 0 | None | None | None | None | None |
| 04 | 0 | None | None | None | None | None |
| 05 | 0 | None | None | None | None | None |
| 06 | 0 | None | None | None | None | None |
| 07 | 0 | None | None | None | None | None |
| 08 | 0 | None | None | None | None | None |
| 09 | 0 | None | None | None | None | None |
| 10 | 0 | None | None | None | None | None |
| 11 | 0 | None | None | None | None | None |
| 12 | 0 | None | None | None | None | None |
| 13 | 0 | None | None | None | None | None |
| 14 | 0 | None | None | None | None | None |
| 15 | 0 | None | None | None | None | None |
| 16 | 0 | None | None | None | None | None |
| 17 | 0 | None | None | None | None | None |
| 18 | 0 | None | None | None | None | None |
| 19 | 0 | None | None | None | None | None |
| 20 | 0 | None | None | None | None | None |
| 21 | 0 | None | None | None | None | None |
| 22 | 0 | None | None | None | None | None |
| 23 | 0 | None | None | None | None | None |

### Pre/Post-refactor split

Only pre-refactor records present (n=854); skipping comparison.

Re-run after `LS_ASYNC_DISPATCH=1` has been live for at least 1 trading day to populate post-refactor distributions.


## Exit-path deltas

### Distribution

| field | count | mean | median | p90 | p99 | max |
|---|---|---|---|---|---|---|
| `trigger_to_dispatch_ms` | 0 | None | None | None | None | None |
| `dispatch_to_confirm_ms` | 0 | None | None | None | None | None |
| `total_trigger_to_confirm_ms` | 0 | None | None | None | None | None |

### Per-strategy — total `total_trigger_to_confirm_ms` by `strategy`

| strategy | count | mean | median | p90 | p99 | max |
|---|---|---|---|---|---|---|
| 3CO | 0 | None | None | None | None | None |
| BB_REVERSAL | 0 | None | None | None | None | None |
| BRIEFING_EXECUTION | 0 | None | None | None | None | None |
| BRIEFING_HUNT | 0 | None | None | None | None | None |
| BRIEFING_LIQUIDITY | 0 | None | None | None | None | None |
| BRIEFING_SWEEP | 0 | None | None | None | None | None |
| CONTINUATION_SWEEP | 0 | None | None | None | None | None |
| DAILY_DOUBLE | 0 | None | None | None | None | None |
| EMA_PULLBACK | 0 | None | None | None | None | None |
| GBPUSD_BB_BOUNCE_L | 0 | None | None | None | None | None |
| GBPUSD_BB_BOUNCE_S | 0 | None | None | None | None | None |
| GBPUSD_BB_REV_PAT_L | 0 | None | None | None | None | None |
| GBPUSD_BB_REV_PAT_S | 0 | None | None | None | None | None |
| GBPUSD_TREND_CONT_L | 0 | None | None | None | None | None |
| GBPUSD_TREND_CONT_S | 0 | None | None | None | None | None |
| LIQUIDITY_SWEEP | 0 | None | None | None | None | None |
| NEWS_STRATEGY | 0 | None | None | None | None | None |
| NEWS_TICK | 0 | None | None | None | None | None |
| REVERSAL_SWEEP | 0 | None | None | None | None | None |
| WINDOW_SWEEP | 0 | None | None | None | None | None |

### Per-pair — total `total_trigger_to_confirm_ms` by `pair`

| pair | count | mean | median | p90 | p99 | max |
|---|---|---|---|---|---|---|
| EURUSD | 0 | None | None | None | None | None |
| GBPJPY | 0 | None | None | None | None | None |
| GBPUSD | 0 | None | None | None | None | None |
| USDCAD | 0 | None | None | None | None | None |
| USDJPY | 0 | None | None | None | None | None |

