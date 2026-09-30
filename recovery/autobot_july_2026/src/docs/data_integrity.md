# Data integrity — 5-minute candle source of truth

**As of 2026-04-22: tick-built candles are authoritative. REST-RECONCILE is disabled.**

## Current state

- 5-minute candles are built locally from the IG Lightstreamer `L1:` tick stream by `candle_builder.py`.
- The previous REST-based reconcile step (which re-fetched closed bars from IG's historical-prices endpoint and overwrote the tick-built H/L) is **gated off by default** via `REST_RECONCILE_ENABLED=0`.
- The reconcile code path remains in `candle_builder.py:_reconcile_high_low_with_rest` and is fully reversible: setting `REST_RECONCILE_ENABLED=1` (or the legacy `LS_REST_RECONCILE_ENABLED=1`) restores the previous behaviour.

## Why reconcile was disabled

1. **Allowance exhaustion.** On IG demo the weekly historical-data allowance is 8,000 points. Reconcile alone was consuming ~9,396 pts/wk (~117% of cap), and the resulting 403 storms starved every other REST-consuming path (preload, HTF gap-fill) of budget.
2. **Silent data corruption.** On 2026-04-19 two GBPUSD bars (20:15 and 21:45 UTC) received `null` H/L from the REST endpoint. The reconcile write path had no `pd.isna()` guard, so `float(NaN)` propagated into the cache and those bars read as NaN thereafter.

A NaN guard has been added (2026-04-22) so that even if reconcile is re-enabled, a null REST response will be rejected with a warning instead of written to cache. The 2026-04-19 class of incident cannot recur.

## Known limitation of tick-built candles

Lightstreamer's client-side conflation can drop intermediate tick snapshots during spike bursts. Tick-built H/L only reflect the ticks the client actually sees, so a sub-second spike that doesn't land on a delivered snapshot is not captured in the bar's wick.

Observed gap size (retrospective): 0–10 pips on volatile bars; typically 0 on quiet ones.

## Evidence-gathering: is native-stream H/L different from tick-built H/L?

Hypothesis: IG's server-side CHART:5MINUTE aggregation sees every raw tick before conflation is applied, so CHART candles should preserve the full range that the conflated `L1:` stream can miss.

The `parallel-candle-compare.service` systemd unit (wrapping `scripts/parallel_candle_comparison.py`) subscribes to `CHART:{epic}:5MINUTE` for GBPUSD, EURUSD, USDJPY, USDCAD on a separate Lightstreamer session and writes one CSV row per `CONS_END=1` to `logs/parallel_native_candles_<YYYYMMDD>.csv`.

- Harness started: **2026-04-22 10:54 UTC**.
- Comparison run target: **T+24–48 h** via `scripts/compare_native_vs_tick.py`.
- Output: `logs/candle_comparison_<range>.txt` with per-bar H/L deltas, max-|Δ| sorting, news-adjacency flags, and summary stats.

## Decision pending

One of:

1. **Native > tick during spikes** → migrate to CHART:5MINUTE stream; remove reconcile permanently; refactor `candle_builder` to consume native candles instead of aggregating ticks client-side. Allowance pressure is structurally eliminated.
2. **Native == tick during spikes** → accept tick-built as authoritative permanently; leave reconcile disabled. Document the residual conflation limitation as a known behaviour. Allowance pressure remains eliminated because the decision is final.

No migration code is to be written before the comparison report is reviewed.

## Re-enabling reconcile (if ever needed)

```bash
# .env
REST_RECONCILE_ENABLED=1
```

Before re-enabling, resolve the root cause of the original allowance exhaustion:

- Reduce `LS_REST_RECONCILE_CADENCE` (currently default 3 — reconcile every 3rd close).
- Or raise the demo allowance budget by swapping to a different API key / account.
- Or accept tick-built as authoritative and keep reconcile off.

Simply flipping the flag back on without addressing the budget will reproduce the 403 storm within the first week.

## Pointers

| Thing | Where |
|---|---|
| Reconcile gate | `candle_builder.py` — `_REST_RECONCILE_ENABLED` |
| Reconcile function | `candle_builder.py:_reconcile_high_low_with_rest` |
| NaN guard | `candle_builder.py` — just after `rest_high_raw = highs.values[mask][0]` |
| Parallel harness | `scripts/parallel_candle_comparison.py` |
| Comparison analyser | `scripts/compare_native_vs_tick.py` |
| Systemd unit | `/etc/systemd/system/parallel-candle-compare.service` |
| Daily native CSV | `logs/parallel_native_candles_<YYYYMMDD>.csv` |
| Intra-bar DEBUG log | `logs/parallel_native_candles_intra_<YYYYMMDD>.log` |
