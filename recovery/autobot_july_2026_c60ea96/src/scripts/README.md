# scripts/

Operational and diagnostic scripts. None of these are part of the live
trading pipeline; they are tools the operator runs by hand or via cron.

## Shadow-mode audit tooling

Two scripts support the shadow-mode rollout of
`BRIEFING_EXEC_TRIGGER_V2_MODE`. While `MODE=shadow` the executor logs
what `entry_trigger_v2` *would* have done without changing dispatch.
Use these tools to look at that record before flipping `MODE=live`.

### Quick check (any time during shadow)

```
bash scripts/shadow_quick_check.sh [hours=24]
```

Reads `journalctl -u autobot.service` over the last N hours and prints:

  1. Shadow log volume — total + by symbol + by entry_mode
  2. `would_block` distribution — true/false counts and block ratio
  3. Failed-condition breakdown (when `would_block=True`)
  4. Most recent 10 raw shadow log lines
  5. Sanity flags (no logs / all-allow / all-block)

It is a 30-second sanity check, not a decision tool. Run it whenever
you want to glance at v2's behaviour.

### Formal audit (after 24–48h shadow window)

```
python3 scripts/shadow_audit.py --since YYYY-MM-DD \
  [--until YYYY-MM-DD] \
  [--output text|json|csv] \
  [--ig-cross-check] \
  [--epic-filter EPIC]
```

Joins shadow log lines to `data/briefing_outcomes.jsonl` rows by
`(symbol, briefing_time)` and prints a confusion matrix, decision
metrics, per-condition contribution, per-symbol breakdown, and a
recommendation. With `--ig-cross-check`, additionally pulls
`/history/transactions` from IG and verifies the tracker's pnl
matches IG's record within ±0.1 pip; degrades gracefully on 403
(allowance exceeded).

Useful environment overrides for testing:

  - `SHADOW_LOG_FILE`         — read shadow lines from a file instead
                                of journalctl
  - `BRIEFING_OUTCOMES_FILE`  — point at a different outcomes file
  - `IG_TX_FIXTURE`           — JSON file (`{"transactions": [...]}`)
                                that stands in for IG REST

### Decision rule for flipping MODE=live

Hold off until `shadow_audit.py` reports:

  - `false_positive_rate == 0`
  - sample size ≥ 10 trades
  - `true_positive_rate > 60%` OR no would-block events
  - no IG cross-check drift

Any one of those failing means hold and investigate.

### Tests

```
python3 scripts/test_shadow_audit.py [--verbose]
```

Drives `shadow_audit.py` through five synthetic scenarios:

  - A: all v2 ALLOW + all wins → "Safe to consider live"
  - B: all v2 ALLOW + half lose → no recommendation triggers fire
  - C: mixed ALLOW/BLOCK with block-and-won → "Hold off on live"
  - D: empty window → short-circuit message
  - E: tracker/IG drift → "drift detected" recommendation
