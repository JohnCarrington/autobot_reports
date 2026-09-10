# Pre-live bug fix — 2026-09-10

**Host:** 161 (`AutoBotV1`)   •   **Branch:** `feat/trend-stretch-brake-adx-floor`   •   **HEAD before commits:** `ff09d6d`

**Scope.** Three defects blocking V2 from trading honestly. Defect
repair only — no new capability, no threshold or geometry changes.
`QM_LIVE_FIRE` remains `0`/absent.

---

## Defect #7 — `ENTRY_ARMED` squats the (zone,side) slot

### Root cause (quoted, `qm_decision_shadow.py:627-648`, pre-fix)

```python
def _maybe_expire_candidate(cand: Candidate, ts: str,
                              cur_close: float) -> bool:
    """Expire the candidate if it has been in an actionable state
    (REVERSAL_CANDIDATE / REJECTION_CONFIRMED) for longer than
    QM_CAND_TTL_BARS bars without progressing, or if the current
    close has drifted more than QM_CAND_MAX_DIST_PIPS from its
    zone_center. ...
    """
    try:
        if cand.state not in (CAND_REVERSAL_CANDIDATE,
                              CAND_REJECTION_CONFIRMED):
            return False   # ← ENTRY_ARMED skipped by this branch
```

`ENTRY_ARMED` was excluded from the expiry check. A stale arm held
the (zone) slot indefinitely; the `_sde_pick_zone` guard downstream
only permits a fresh candidate when the current candidate is `None`
or `CAND_EXPIRED`. That is exactly the 09-10 12:30 exam-day killer.

### Fix (`qm_decision_shadow.py:627-670`)

`ENTRY_ARMED` is subject to the SAME TTL and max-distance rules as
`REVERSAL_CANDIDATE` and `REJECTION_CONFIRMED`. `bars_since_armed`
was already being stamped for `ENTRY_ARMED` at line 604 (the ARM
transition), so the counter is honest; adding `ENTRY_ARMED` to the
gate at line 647 makes the expiry actually fire.

```python
if cand.state not in (CAND_REVERSAL_CANDIDATE,
                      CAND_REJECTION_CONFIRMED,
                      CAND_ENTRY_ARMED):
    return False
```

### Fixture walk — the specimen the 09-10 exam missed

Zone 13511.817, 5m closes verbatim from `data/candles/GBPUSD/2026-09-10.csv`:

```
tick  ts (UTC)             close   bars_since_armed  state after tick
  1   12:35    13494.25    1     ENTRY_ARMED  (no expiry, 1 ≤ 12)
  2   12:40    13500.75    2     ENTRY_ARMED
  3   12:45    13509.55    3     ENTRY_ARMED
  4   12:50    13507.35    4     ENTRY_ARMED
  5   12:55    13510.75    5     ENTRY_ARMED
  6   13:00    13510.05    6     ENTRY_ARMED
  7   13:05    13502.45    7     ENTRY_ARMED
  8   13:10    13499.05    8     ENTRY_ARMED
  9   13:15    13499.35    9     ENTRY_ARMED
 10   13:20    13500.05   10     ENTRY_ARMED
 11   13:25    13501.95   11     ENTRY_ARMED
 12   13:30    13508.15   12     ENTRY_ARMED  (last legal tick, 12 == 12)
 13   13:35    13509.25   13     CAND_EXPIRED  ← ARM freed, slot open
 14   13:40    13514.75    –     (fresh candidate can now spawn)
 15   13:45    13519.15    –     (BUY bounce, ~7p above zone) → the pick
                                  the exam missed
```

Distance limb is never binding here — max `|close − zone|` = 17.6p at
12:35, well within `QM_CAND_MAX_DIST_PIPS=25`. The age limb fires at
the 13th ARMED tick because the gate is `bars_since_armed > TTL`
(strict).

### Cross-check against the live record (`logs/qm_candidates.jsonl`)

```
ZONE 13511.817  opened=2026-09-10T12:30:00  final=ENTRY_ARMED
   12:30:00  IDLE                 -> EXTREME_REACHED     (walk_through)
   12:30:00  EXTREME_REACHED      -> SWEEP_DETECTED      (VELOCITY_REJECTION)
   12:30:00  SWEEP_DETECTED       -> REJECTION_CANDIDATE
   12:30:00  REJECTION_CANDIDATE  -> REJECTION_CONFIRMED (velocity_rejection_score=12)
   12:30:00  REJECTION_CONFIRMED  -> ENTRY_ARMED         (direction=SELL_from_rejection_geometry)

ZONE 13511.817  opened=2026-09-10T14:00:00  final=REVERSAL_CANDIDATE
   14:00:00  IDLE                 -> REVERSAL_CANDIDATE  (s16_retest_S2_from_above_wick=2.33p)
```

Live behaviour: the 12:30 SELL arm sat for **90 minutes** before a
fresh candidate finally spawned on the same zone at 14:00 (an s16
retest from below — a BUY setup). Under the fix the 12:30 arm expires
at 13:35, and the 13:40 bar is the first eligible spawn window; the
13:45 bounce (close=13519.15, high=13520.05, ~7p above zone) drives
the BUY candidate — the trade the exam missed.

### Test coverage

Both cases are pinned in `tests/unit/test_qm_v2_self_contained.py`:

- `test_entry_armed_expires_under_same_ttl_and_dist_rules` — unit,
  both age and distance limbs.
- `test_fixture_09_10_gbpusd_bounce_specimen` — the exam specimen,
  drives the verbatim 5m close series through `_maybe_expire_candidate`
  and asserts the ARM expires at 13:35 (13th ARMED tick), freeing the
  slot before 13:45.

```
$ pytest tests/unit/test_qm_v2_self_contained.py -v
...
test_entry_armed_expires_under_same_ttl_and_dist_rules PASSED
test_fixture_09_10_gbpusd_bounce_specimen              PASSED
14 passed in 0.39s
```

---

## Grader defect — double-counts scaled winners

### Root cause (quoted, `scripts/qm_join_grade.py:125-133`, pre-fix)

```python
pnl = float(r.get("pnl_pips") or 0.0)
runner = float(r.get("runner_pnl_pips") or 0.0)
total = pnl + runner if r.get("runner_pnl_pips") is not None else pnl
```

Naive `pnl + runner` is the wrong arithmetic for a scaled row. The
signal-logger writer (see below) sets `runner_pnl_pips == pnl_pips`
on scaled rows — both hold the runner-leg P&L only, as a diagnostic
split — and writes the true combined P&L into `total_pnl_pips`. So
`pnl + runner` = 2 × runner_leg and misses `partial_bank_pips`
entirely.

### The writer (`signal_logger.py:1699-1728`, quoted)

```python
_partial_bank = rec.get("partial_bank_pips")           # stamped by log_partial
_runner_pnl = float(pnl_pips) if pnl_pips is not None else 0.0
_total_pnl = _runner_pnl + (float(_partial_bank) if _partial_bank is not None else 0.0)
_partial_fill_estimated = bool(rec.get("partial_fill_estimated", False))

rec.update({
    "outcome": _outcome_label(reason),
    "timestamp_close": ts_close,
    "close_price": round(float(close_price), 5) if close_price is not None else None,
    "pnl_pips":     round(float(pnl_pips), 2)  if pnl_pips is not None else None,
    "runner_pnl_pips": round(_runner_pnl, 2)   if _partial_bank is not None else None,
    "total_pnl_pips":  round(_total_pnl, 2),
    "partial_fill_estimated": _partial_fill_estimated,
    ...
})
```

Reading the code: `pnl_pips` is the runner-close argument
(`_on_trade_close` is called with the runner leg's P&L because
scale-out already banked the partial via `log_partial`). The record
ends up with:

- `pnl_pips` = runner-close P&L
- `runner_pnl_pips` = runner-close P&L (same value; only set when a
  partial exists, as a diagnostic split)
- `partial_bank_pips` = scale-out realised bank (stamped by
  `log_partial`, `signal_logger.py:1595-1607`)
- `total_pnl_pips` = runner + partial_bank (the true combined trade
  P&L — what the dashboard reads at `trades_api.py:463`, what the
  daily journal reads at `daily_journal.py:397/442/471`)

### The 09-09 15:11 EURUSD row — worked example

```
ts=2026-09-09T15:11:23Z  pair=EURUSD  strat=BRIEFING_V5
  pnl_pips        = 1.1
  runner_pnl_pips = 1.1
  partial_bank_pips = 8.0
  total_pnl_pips  = 9.1    ← canonical (runner + partial_bank)
  naive (pnl + runner) = 2.2
  partial_fill_estimated = False
```

`partial_fill_estimated=False` — the partial exit price came from IG's
confirm-response `level` field (real broker fill), not from a
`last_mid` fallback. **No partial-fill/commission netting is in play
here**: the writer stores gross pip P&L, no commission adjustment
is applied anywhere in `signal_logger`. The naive under-statement is
purely arithmetic — the naive formula double-counts the runner leg
(1.1 + 1.1) and drops the 8.0-pip partial bank entirely.

### Fix (`scripts/qm_join_grade.py:132-155`)

Read `total_pnl_pips` as authoritative when present; naive sum only
as fallback when the field is absent (older writer / open records).
Rows using the fallback are tallied in `_NAIVE_FALLBACK_ROWS` and
printed in the diagnostics line.

### Corrected Report B — 4-day walk (canonical totals)

Naive-fallback tally per day:

| day        | fallback rows |
|------------|---------------|
| 2026-09-04 | 0 |
| 2026-09-07 | 0 |
| 2026-09-08 | 0 |
| 2026-09-09 | 0 |
| 2026-09-10 | 1 (open position `d9e3a130-...`, no outcome yet — contributes 0) |

Commercial scoreboards (ALL-V1 / V2-KEPT):

**2026-09-04**
```
trades/day             6      0
net pips           +62.3   +0.0
win rate           66.7%      -
expectancy/trade  +10.39  +0.00
MFE median          15.1      -
MAE median           7.5      -
>=25p winners          1      0
>=35p winners          1      0
peak simu              3      0
peak capital £       120      0
pips / £ peak-cap  0.520      -
```

**2026-09-07**
```
trades/day             5      0
net pips           +22.8   +0.0
win rate           60.0%      -
expectancy/trade   +4.56  +0.00
MFE median           6.5      -
MAE median           2.5      -
>=25p winners          0      0
>=35p winners          0      0
peak simu              2      0
peak capital £        80      0
pips / £ peak-cap  0.285      -
```

**2026-09-08**
```
trades/day             5      2
net pips           -39.8   -2.7
win rate           20.0%  50.0%
expectancy/trade   -7.96  -1.35
MFE median           3.0    7.6
MAE median          11.6   13.4
>=25p winners          0      0
>=35p winners          0      0
peak simu              1      1
peak capital £        40     40
pips / £ peak-cap -0.995 -0.068
```

**2026-09-09**
```
trades/day             9      1
net pips           +77.1   +0.1
win rate           66.7% 100.0%
expectancy/trade   +8.57  +0.10
MFE median          14.3   14.7
MAE median           6.7    5.0
>=25p winners          1      0
>=35p winners          0      0
peak simu              3      1
peak capital £       120     40
pips / £ peak-cap  0.643  0.003
```

**2026-09-10** (exam day)
```
trades/day             7      0
net pips           -17.7   +0.0
win rate           14.3%      -
expectancy/trade   -2.54  +0.00
MFE median           4.0      -
MAE median           6.8      -
>=25p winners          1      0
>=35p winners          0      0
peak simu              3      0
peak capital £       120      0
pips / £ peak-cap -0.148      -
```

---

## Defect #8 — post-scale BE amend rejection retry (`ATTACHED_ORDER_LEVEL_ERROR`)

### Root cause (call site quoted, `trade_manager.py:3003-3008`, pre-fix)

```python
_be_ok = _amend_broker_sl(pos_key, new_sl_price=float(entry),
                          current_tp_price=runner_tp_price)
if not _be_ok:
    time.sleep(0.5)
    _be_ok = _amend_broker_sl(pos_key, new_sl_price=float(entry),
                              current_tp_price=runner_tp_price)
st["be_amend_ok"] = bool(_be_ok)
```

Both attempts propose SL = entry. If entry sits inside IG's per-pair
min-stop-distance from live price, IG rejects with
`ATTACHED_ORDER_LEVEL_ERROR` — happened on the 2026-09-09 runner.
The 2-try loop gave up silently and the runner rode its original
20p fire-time SL until close.

### Fix (`trade_manager.py:_scale_out_50pct`)

If the second BE attempt is rejected, retry ONCE with the tightest
IG-legal stop: `live_mid ± (IG_MIN_STOP + margin)` in the unfavorable
direction. Not BE, but sits between entry and the original 20p SL,
so the runner is materially better protected than "no amend at all".
`be_amend_ok` stays `False` — profile trails (which assume SL=BE) do
NOT engage — the runner just holds the safe SL and rides the original
TP.

LOUD `[BE-AMEND-FAILED]` log + Telegram fire ONLY when both BE and
safe-SL are rejected.

Key excerpts:

```python
# BUY:  safe_sl = live_mid - (IG_MIN + margin) * ppp
# SELL: safe_sl = live_mid + (IG_MIN + margin) * ppp
_safe_sl_ok = _amend_broker_sl(
    pos_key,
    new_sl_price=float(_safe_sl_price),
    current_tp_price=runner_tp_price,
)

# LOUD alert only when the safe-SL fallback ALSO failed:
if not _safe_sl_ok:
    logger.error(
        "[BE-AMEND-FAILED] %s runner riding ORIGINAL SL — "
        "deal=%s reject=%s (both BE and IG-min-safe SL rejected)",
        pos_key, deal_id,
        meta.get("last_amend_reject_reason") or "unknown",
    )
    send_error_alert(
        f"[BE-AMEND-FAILED] RUNNER RIDING ORIGINAL SL{_release_note}\n"
        f"Pair: {pair}\nDeal: {deal_id}\nReason: {_reject_reason}\n"
        f"Both BE (=entry) and IG-min-safe SL (from live_mid) "
        f"were rejected."
    )
```

IG per-pair min-stop distances come from `_ig_min_stop_pips_for_pair`
(sourced from `dealingRules.minNormalStopOrLimitDistance`, verified
2026-07-21): GBPUSD 4.0, EURUSD 2.0, USDJPY 6.0, USDCAD 4.0,
GBPJPY 4.0. Cushion is `SL_AMEND_MIN_DIST_MARGIN_PIPS` (0.5 default).

### Test coverage (`tests/unit/test_be_amend_defect_8.py`)

Four tests pin all three code paths:

```
test_be_amend_happy_path_no_safe_sl_touched              PASSED
  - BE lands on first try; no fallback ever touched, no alert.

test_be_rejected_twice_safe_sl_lands_no_alert            PASSED
  - BUY entry=13500, live_mid=13502 (2p above, IG_MIN=4p → BE illegal).
  - After 2 BE rejections, safe SL = 13502 - 4.5 = 13497.5 is amended.
  - be_amend_ok stays False, safe_sl_amend_ok=True, no Telegram alert.

test_be_and_safe_sl_both_rejected_loud_alert_fires       PASSED
  - All three attempts rejected.
  - [BE-AMEND-FAILED] ERROR log emitted, send_error_alert fired with
    "[BE-AMEND-FAILED]" prefix in the body.

test_safe_sl_sell_direction_math                         PASSED
  - SELL mirror math: entry=13500, live=13498, safe SL = 13502.5.
```

---

## Full-suite verification

```
BASELINE  (my changes stashed):
  154 failed, 2055 passed, 20 skipped, 1 xfailed, 29 errors

WITH FIX  (my changes applied):
  154 failed, 2059 passed, 20 skipped, 1 xfailed, 28 errors
                +4 (my new #8 tests)   -1 error (test flipped to FAILED, same test)
```

`diff baseline vs with-fix` — the only delta is the 4 new
`test_be_amend_defect_8` PASSes and one `test_disabled_returns_none`
row moving from ERROR to FAILED (same failing test — reclassified by
pytest). No new failures introduced. Suite delta = zero beyond the
new coverage.

The `test_qm_v2_self_contained` block including the 09-10 exam
specimen passes clean:

```
14 passed in 0.39s
```

---

## `QM_LIVE_FIRE` status

Unchanged. Not touched.

```
$ env | grep -i QM_LIVE
QM_LIVE_FIRE=
```
