## Pre-live-flip ticket for BRIEFING_EXEC_TRIGGER_V2_MODE

Before flipping BRIEFING_EXEC_TRIGGER_V2_MODE=live, verify:

1. news_calendar.get_events_today() strips unknown keys (only
   passes time/currency/event_name/impact/forecast/previous/
   date_utc through). If v2 vocabulary is extended to require
   actual/forecast deviation (like NEWS_TICK already uses), the
   helper must pass those fields through.

2. Shadow-mode evaluator coverage gap: v2 gate is only called
   at decision-emission sites (Phase 2, TREND_ENTRY), not at
   earlier gates (R:R rejection, levels-match advisory).
   Shadow logs miss trades rejected by other gates. Consider a
   shadow-only pre-emission evaluation pass for completeness.

3. Timeout-reconciliation callback coverage: Fix 1 Commit 2
   extended _fire_open_callbacks to the two reconciliation
   paths in trade_executor.py:988 and 1037. Confirm behaviour
   the first time a real confirmation timeout reconciles a
   BRIEFING_EXECUTION order in production.

## test_scenarios.py morning-gate ordering dependency

BS-1/2/8/9/10 currently pass via python test_scenarios.py only
because some earlier test in main()'s ordering leaks a
datetime/clock patch that bypasses BRIEFING_SWEEP_MIN_HOUR_UTC=7.
When invoked directly outside the runner sequence, all five
fail with briefing_sweep_morning_blocked.

Fix: _bs_run_eval() should explicitly stub the morning gate or
freeze time, removing the hidden ordering dependency. Discovered
during Cluster C audit on 2026-04-25.

## test_scenarios.py CI surfacing

On 2026-04-24, discovered test_scenarios.py had a dangling
reference (test_ema_1_valid_buy) that made it NameError on
import, silently disabling pre-deploy validation since
2026-04-07. Fixed in fix/test-scenarios-dangling-ema1-reference.

Action: add CI-level detection so a NameError in the test
runner is surfaced loudly on every push, not only when someone
runs it manually.

## EMA_PULLBACK in-trade invalidation loop

The 2026-05-01 EMA_PULLBACK redesign (feat/ema-pullback-redesign)
implements EMA-21-distance as the SL anchor at decision time, and
defers per-bar in-trade invalidation to this follow-up.

Spec: while a position is open, watch each new closed 5m bar for
a confirmed close beyond EMA-21 in the wrong direction (LONG: 5m
close < EMA-21; SHORT: 5m close > EMA-21). On confirmed cross,
close the position early — the broker SL is the backstop, the
EMA-21 cross is the thesis-broken signal.

Architectural choice deferred to implementation time:
- Option A: per-strategy hook in a briefing_execution-style tracker
- Option B: generic per-strategy invalidation registry (precedent:
  BRIEF_INVALIDATED exits)
- Option C: minimal in-strategy state with a callback from
  autobot's per-bar loop

EMA_PULLBACK_ENABLED stays at 0 until this ships. Re-enable plan
ties to Tuesday's strategy rationalisation deploy, after the
in-trade invalidation loop has landed and been reviewed.
