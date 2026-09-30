# Architecture

## Flow at a glance

```
                +-------------------+       +-------------------+
Recorder tail --| M5 aggregator     |--bar->|                   |
   OR           +-------------------+       |                   |
Candle archive ---------- iter_m5_bars ---->|  TrendStrategy    |--> Ledger (append-only JSONL)
                                            |                   |--> Telegram outbox
                                            |                   |--> Position ↔ Reconciler
                                            +-------------------+
```

### Bar-close pipeline (per M5)

1. `M5IndicatorStack` updates EMA8/13/21/50, Wilder ATR14, MACD(35,45,30) and BB(20,2).
2. `SwingBuffer.push()` fractal-detects the swing that just became knowable
   (`half_window=3`, so it fires 3 bars after the pivot bar).
3. `SwingBuffer.direction()` yields (`Direction`, invalidation swing) in O(1).
4. `RegimeEngine.push()` classifies the bar as `TREND_*_FAST`, `TREND_*_GRIND`,
   `EMERGING_*`, `PULLBACK_*`, `RANGE`, `UNKNOWN` or `TRANSITION`, using only
   completed bars.
5. If a position is open, `ExitEngine.on_bar()` may close it (see
   [Exit contract](#exit-contract)).
6. If no position is open, `EntryEngine.on_bar_close()` may set a pending
   entry candidate.
7. On the next bar's open, `TrendStrategy.on_next_bar_open()` fills the
   candidate (if any) at that bar's open price.

### Recorder tail vs candle archive

Observation mode reads `logs/price_streamer.jsonl` — the AutoBot
recorder — as a growing file (rotate-aware). Ticks are aggregated into
completed M5 bars by `M5Aggregator`. No IG session is opened.

Offline replay reads local CSV candles instead (`data/candles/GBPUSD/*.csv`
and `data/candles_ext/GBPUSD/*.csv`). The strategy code path is identical.

### Ledger and reconciliation

`Ledger` is a single append-only JSONL file with two namespaces:
* `sim` – observation-mode simulated trades.
* `real` – broker-owned trades and settlements.

Ownership is asserted via a `deal_reference` we assign at submission.
Missing broker positions become `CLOSED_AWAITING_SETTLEMENT`; broker
activity with a matching `affectedDealId` transitions to `CLOSE_SETTLED`.
Foreign deals are never touched.

Execution-disabled builds continue to reconcile owned positions – the
disabled gate only blocks *new* order submissions.

### Session coexistence

The AutoBot recorder holds the live Lightstreamer session on the
destination droplet. Trend Runner in observation mode never subscribes.
Should the operator later enable `TREND_EXECUTION_ENABLED=1`, the
broker adapter uses REST (`POST /positions/otc`) with its own
`IG_USERNAME`/`IG_API_KEY`. The single order-owning process is
guaranteed by the ProcessLock on `TREND_LOCK_PATH` – no two Trend
Runner processes can be alive at once.

Any outstanding P30 reconciliation must be resolved by its owning
process; Trend Runner never imports P30 positions.

### Pivot day boundary

Daily pivots are computed from the previous *completed* FX day defined
by 22:00 UTC roll (Sunday 22:00 UTC → Monday 22:00 UTC = "Monday" for
Tuesday's London session). We reject the day if it has fewer than 240
M5 bars, or the first/last bar is more than 60 minutes away from the
respective roll boundary.

### Timestamps

All timestamps are UTC. Bars are labelled by *start* time; completion
is `start + 5m`. The ledger records `open_time`, `close_time`, and
event `ts` separately from bar times so decisions are traceable.

## Exit contract

Only five reasons exit a position:

| Reason | Trigger | Exit price |
|---|---|---|
| `R3_TARGET` | BUY: bar high ≥ R3 | `max(open, R3)` |
| `S3_TARGET` | SELL: bar low ≤ S3 | `min(open, S3)` |
| `PROTECTIVE_STOP` | BUY: bar low ≤ stop; SELL: bar high ≥ stop | stop (or worse on gap) |
| `CONSOLIDATION_EXIT` | Consolidation confirmed (`CONFIRM_BARS=3` bars) | bar close |
| `SESSION_END` | `time_utils.is_session_close(bar_ts)` | bar close |

Trailing stops, BE ratchets, scale-outs, CHoCH exits, briefing
tightening, discretionary exhaustion and 20p fixed targets are all
explicitly *absent* from the codebase.

## Restart parity

Replay-driven and observation-driven runs share identical strategy
code. Restart parity is guaranteed by:
* Deterministic re-aggregation of M5 bars.
* Ledger replay recomputes the same `TradeState` map without extra
  side-effects.
* Daily entry-cap is persisted to the ledger (entries counted by
  `open_time` prefix).
