# Source-to-extraction map

Trend Runner is a *narrow re-implementation* of production AutoBot's
infrastructure patterns. Nothing was copy-pasted; every module below
was rewritten to fit Trend Runner's contract (single strategy, single
symbol, execution disabled by default, DEMO only). This document maps
each Trend Runner module to the AutoBot source(s) that inspired it.

Working tree used for extraction:
* Repo: `/opt/tradingbot` (autobot main branch + `feat/trend-stretch-brake-adx-floor` tip)
* Reference commits at time of extraction:
  * `1a789c0 docs(project-thirty): BB_BOUNCE_S/_L code-retrieval bundle`
  * `3206a91 fix(gate): ONE_STRATEGY subjected to structural-opposition admission`
  * `2fb0488 fix(execution): close /confirms-404 + open-position exact-ref gap`
  * `40e2b6f fix(execution): durable IG pending-confirmation ledger`

| Trend Runner module | AutoBot source (file — patterns adopted) |
|---|---|
| `trend_runner/ig_auth.py` (placeholder – see execution.py) | `ig_auth.py` (session creation, token refresh, bounded retry). Not copied verbatim; the `IGExecutor` uses a caller-supplied `requests.Session` so tests can inject a mock. |
| `trend_runner/candle_source.py` | `candle_archive.py` — CSV rotation, per-day loader, chronological iterator. Trend Runner adds an H1 aggregator. |
| `trend_runner/recorder_source.py` | `price_streamer.py`, `bb_pierce_recorder.py`, `streamer_ls.py` — tail semantics, stale-tick detection, epic filtering. Trend Runner strictly disallows the Lightstreamer / requests / IG imports (verified by test). |
| `trend_runner/indicators.py` | `indicators.py` — Wilder ATR, EMA seeding, MACD and BB conventions. Streaming-only variants; no pandas dependency. |
| `trend_runner/market_structure.py` | `market_structure.py` — fractal HH/HL/LH/LL detection, invalidation boundary. |
| `trend_runner/regime.py` | `regime_engine.py` GRIND-family functions and `news_trend_classifier.py` state model. Trend Runner freezes the FAST + GRIND thresholds and drops the trend-classifier features not related to the FAST/GRIND label. |
| `trend_runner/pivots.py` | `gbpusd_pivot_break.py` and `timeframe_context.py` (daily-boundary heuristics). The 22:00 UTC roll and the minimum-coverage guard are documented explicitly. |
| `trend_runner/entry.py` | Bespoke — the pullback-reclaim (FAST) and pause-break (GRIND) contracts are Trend Runner's own. |
| `trend_runner/exit.py` | Bespoke — deliberately strict exit contract (5 reasons only). |
| `trend_runner/consolidation.py` | Draws on `regime_engine.py`'s slope/overlap heuristics but tightens confirmation persistence. |
| `trend_runner/ledger.py` | `pending_deal_ledger.py`, `one_strategy_event_ledger.py`, `v2_pick_bounce_ledger.py`. Reuses the JSONL + `_apply` reduction pattern. `atomic_write_json` copies the tempfile+rename idiom widely used across AutoBot state files. |
| `trend_runner/reconciliation.py` | `trade_executor.py` reconciliation helpers (own-deal identification by `dealReference`, `affectedDealId` linkage, `CLOSED_AWAITING_SETTLEMENT` semantics). |
| `trend_runner/execution.py` | `trade_executor.py` (open/close/amend). Narrow port with a `DisabledExecutor` default and a `MinDistanceError` for pre-submit validation. `IGExecutor` refuses any account_type other than `DEMO`. |
| `trend_runner/telegram.py` | `telegram_alerts.py` — persisted outbox pattern, distinct SIM vs BROKER prefixes, delivery only on ACK, bounded retry with GIVEN_UP terminal state. |
| `trend_runner/process_lock.py` | `bb_pierce_recorder.py` singleton semantics — `fcntl.flock`, one holder per file. |
| `trend_runner/time_utils.py` | `timeframe_context.py` (Europe/London handling, 22:00 UTC boundary). |
| `trend_runner/config.py` | AutoBot `.env` conventions with tightened defaults and LIVE-account rejection. |
| `trend_runner/strategy.py` | Wiring layer specific to Trend Runner. No import from AutoBot. |
| `trend_runner/replay.py` | Bespoke replay driver. |
| `trend_runner/observation_runner.py` | Bespoke recorder-tail runner. |

## What we deliberately did NOT copy

* `trade_executor.py` (5 700 LOC monolith) — too coupled to the current
  AutoBot dispatch, briefing and reconciliation stack. Adopted only the
  order lifecycle contract.
* `regime_engine.py` (2 600 LOC) — extracted only the two label-classes
  we need. The rest is domain-specific to the AutoBot briefings.
* `ig_auth.py` full re-login machinery — kept only the account-type
  guard and demo-URL default. A future revision may embed the full
  password-based login when the operator enables execution.
* Recorder-tail circular buffers, stale-heartbeat escalation and the
  streaming-side reconnect state machine — these belong to the AutoBot
  recorder, which we consume rather than replace.
