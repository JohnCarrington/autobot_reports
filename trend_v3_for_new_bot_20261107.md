# TREND_V3 — how it works, for rebuilding on a new bot

Audit host: **AutoBot REDACTED, REDACTED** · Mode: read-only · Snapshot date 2026-11-07 UTC.

Source of truth: `/opt/tradingbot/gbpusd_trend_v3.py` (102,749 bytes, 2,190 lines, mtime
2026-10-22 05:56 UTC); `/opt/tradingbot/.env` (host config); `/opt/tradingbot/logs/trend_v3.jsonl*`
(telemetry); `/opt/tradingbot/logs/signal_log*.jsonl*` (fills).

Everything below is quoted from the code; where a quote matters, the file and line are cited inline.

---

## 1. Where it lives and which service runs it

### Module files

| File | Role |
|---|---|
| `/opt/tradingbot/gbpusd_trend_v3.py` | The strategy itself. Entry gates (`GbpUsdTrendV3Strategy.evaluate` at line 1153), exit machine (`monitor_exits` at line 1890), SL/TP builder (`_resolve_target_and_sl` at line 738), ribbon-gate deferral (lines 191-509), open-position bookkeeping (lines 826-889). Two modes: `GBPUSD_TREND_V3_L / _S` (managed) and `GBPUSD_TREND_V3_UM_L / _S` (unmanaged, 12p/100p fixed geometry, EOD-flat) declared at lines 48-61. |
| `/opt/tradingbot/autobot.py` | Driver. Imports, the 5-minute-close callback wiring, `on_5m_close_gbpusd` around lines 9510-9619 (`evaluate()` call at 9607, `monitor_exits()` at 9588, SMA-cross UM-only exit at 9598). UM EOD-flat sweeper `_apply_trend_v3_um_eod_close` at 2955. UM SMA-cross close `_apply_trend_v3_um_sma_cross_close` at 3191. |
| `/opt/tradingbot/central_execution_gate.py` | Admission authority. Family map at 1427 (`("GBPUSD_TREND_V3", "TREND_V3")`), `_delegate_news_direction` call that runs the NMS session-trend direction rule for TREND_V3 at 2238, Stage-11 cutover allowlist at 2414-2417. |
| `/opt/tradingbot/nms_session_trend_direction.py` | The direction-authority function `permit_trend(symbol, side)` used by TREND_V3 when `DIRECTION_FROM_NMS_SESSION_TREND=1`. |
| `/opt/tradingbot/nms_second_gate.py` | Second NMS stand-aside gate. Called at `gbpusd_trend_v3.py:1255`. Default off; a no-op unless `NMS_SECOND_GATE_ENABLED=1`. |
| `/opt/tradingbot/regime_engine.py` | Supplies `latest_result(symbol)` (regime label, label_path, trend_subtype) consumed by `_latest_regime` at `gbpusd_trend_v3.py:575`. |
| `/opt/tradingbot/regime_matrix.py` | Supplies `regime_matrix.permits(symbol, mode)` called before TREND_V3's evaluate in `autobot.py:9552`. Default `REGIME_MATRIX_ENABLED=0` makes it a no-op that returns True unconditionally. |
| `/opt/tradingbot/ribbon_state.py` | EMA ribbon classifier (FANNED_UP / FANNED_DOWN / BRAIDED / TRANSITIONAL) + deferral store. Wired at `gbpusd_trend_v3.py:170-175`. |
| `/opt/tradingbot/runner_momentum.py` | MACD-hist contracting detector + `m1_aligned` — both delegated to from `gbpusd_trend_v3.py:641` and `:901`. |
| `/opt/tradingbot/market_structure.py` | 5m swing-high / swing-low detector used by `_swing_5m` at `gbpusd_trend_v3.py:714`. |
| `/opt/tradingbot/guards/range_gate.py` | Belt-and-braces range gate at `gbpusd_trend_v3.py:1660`. |
| `/opt/tradingbot/news_release_window.py` | `is_in_release_window(ts)` — pre/post news blackout read at `gbpusd_trend_v3.py:315`. |
| `/opt/tradingbot/trade_executor.py` | `close_position`, `EPIC_STATE`, `_pos_key`, `execute_trade`. `monitor_exits` closes via `close_position(reason="TREND_V3_<REASON>")` at line 2154. |
| `/opt/tradingbot/trade_manager.py` | Universal in-flight position management (scale-out, BE move, ladder/ratchet exit stack). `EXIT_STACK_GBPUSD_TREND_V3_L=TIERED_RATCHET` and `_S=TIERED_RATCHET` route managed TREND_V3 to TIERED_RATCHET in `exit_dress.resolve`. |
| `/opt/tradingbot/tiered_ratchet.py` | The TIERED_RATCHET exit stack (SL ladder + exhaustion-flat + session-flat). |
| `/opt/tradingbot/candle_archive.py` | Registers a 5m-close callback that appends mid-price OHLC to `/opt/tradingbot/data/candles/GBPUSD/<DATE>.csv` — the historical bar source TREND_V3 reads back for H4 structural target + 5m swing (via `TimeframeContext._d1_closed` / `.get_closed_candles`). |
| `/opt/tradingbot/logs/trend_v3.jsonl` (+ rotated `.gz`) | Per-event telemetry. Rows of kind `fire`, `open`, `block`, `exit`, `exh_mcheck`, `regime_off_streak`, `flip`, `revert`. Output path overridable by env `TREND_V3_LOG_PATH`. |
| `/opt/tradingbot/cache/gbpusd_trend_state.json` | TREND_V3 state cache written by autobot. |
| `/opt/tradingbot/tests/unit/test_trend_v3_fire_log_format.py` and `test_trend_v3_session_gate_widen.py` | Regression tests. |
| `/opt/tradingbot/reports-public/trend_v3_vs_nms_direction_disagreement_20260925.md` | Prior forensic on direction-mismatch. |

### Service

- **systemd unit:** `autobot.service` → `/etc/systemd/system/autobot.service`. ExecStart runs `/opt/tradingbot/venv/bin/python /opt/tradingbot/autobot.py`, env-file `/opt/tradingbot/.env`, user `autobot`, WorkingDirectory `/opt/tradingbot`. Drop-ins under `/etc/systemd/system/autobot.service.d/` (auth-suspension-guard, corpus-writer-production, env-drift, env-history, ownership-heal, service-context, shutdown-tuning).
- Current state at snapshot: `Active: inactive (dead) since Fri 2026-11-06 18:09:38 UTC`. Last PID was 4059058.
- `autobot.py` registers the TREND_V3 5m-close callback at boot — grep `[AUTOBOT] Registered TREND_V3 5M close callback (TREND_V3_ENABLED=1)` in the journal.

There is no stand-alone TREND_V3 service. It lives inside `autobot.service`.

---

## 2. The rules, step by step — BUY and SELL

### 2.0 When TREND_V3 is called

Driver seam at `autobot.py:9510-9619`. On every completed 5-minute bar for GBPUSD, after regime / HTF / structure_break / BB_BOUNCE / EMA_PB have already updated state for that bar, the driver:

1. Reads `GBPUSD`'s enriched 5m DataFrame (`df_5m`) — carries `ADX_14`, `MACD_HIST_35_45_30`, `ATR_14`.
2. Waits for the regime pool to publish THIS bar's label (`regime_matrix.wait_for_bar`).
3. Calls `regime_matrix.permits(symbol, GBPUSD_TREND_V3_L or _S)` — if neither mode is permitted the callback returns early (no-op when `REGIME_MATRIX_ENABLED=0`).
4. Runs `monitor_exits()` first (exit machine), then the UM-only SMA-cross close, then `evaluate()`.

Inside `evaluate(symbol, epic, ts, bars, closes_ind, df_5m, has_open_long, has_open_short)`:

### 2.1 The only two things that stop the strategy before it even looks

Lines 1169-1176:
```python
if not ENABLED or str(symbol).upper() != "GBPUSD":
    return None
if ts.tzinfo is None:
    ts = ts.replace(tzinfo=timezone.utc)
else:
    ts = ts.astimezone(timezone.utc)
if not bars or len(bars) < 2:
    return None
```

`ENABLED` is `TREND_V3_ENABLED` from env, default `"0"` (line 85). The symbol is hard-coded to GBPUSD.

### 2.2 Prerequisites run on every bar, in order

Numbered the way the code runs them. All quoted line numbers are in `gbpusd_trend_v3.py` unless prefixed.

**Step A — Ribbon-deferral release (lines 1184-1196).** Only runs if both `RIBBON_GATE_ENABLED=1` and `RIBBON_GATE_TREND_V3=1`. If the previous bar armed a TRANSITIONAL-ribbon deferral, and this bar's close pushes beyond the deferred setup's extreme in the trade direction, a fire returns immediately (short-cuts the rest of the evaluation). See 2.6 for the full ribbon logic.

**Step B — Session window gate (lines 1199-1204).**
```python
if SESSION_GATE_ENABLED and not self._in_session(ts):
    logger.info("[TV3_SESSION] suppressed entry at %s", …)
    return None
```
`_in_session` (lines 1142-1151) returns False on Saturday / Sunday, otherwise `SESSION_START ≤ t < SESSION_END` (both UTC). Env-controlled, see §3.

**Step C — Dedup per epic per bar (lines 1207-1211).** The strategy evaluates at most once per `bars[-1].timestamp` per epic.

**Step D — Slot-occupancy latch bookkeeping (lines 1221-1248).** Detects "position was open last tick and is gone this tick" (broker TP/SL, IG_RECONCILE, external close) and synthesises a cooldown record so Step H sees the close. Also stamps a GRIND cooldown if the last arm on this (epic, direction) was via the GRIND path.

**Step E — NMS second-gate stand-aside (lines 1254-1278).** Calls `nms_second_gate.check(symbol, "GBPUSD_TREND_V3")`. If `allowed=False and bypassed=False` → block with reason `nms_second_gate_stand_aside`. Defaults to bypassed=True (no-op) unless `NMS_SECOND_GATE_ENABLED=1`.

**Step F — Direction authority: unified NMS session-trend (lines 1287-1346).** This is the authority currently in force on host REDACTED because `DIRECTION_FROM_NMS_SESSION_TREND=1` in `.env:1131`.
```python
_nms_direction_rule_on = (
    os.getenv("DIRECTION_FROM_NMS_SESSION_TREND", "0").strip()
    in ("1", "true", "yes", "on")
)
if _nms_direction_rule_on:
    import nms_session_trend_direction as _nmsd
    _buy_ok  = _nmsd.permit_trend(symbol, "BUY")
    _sell_ok = _nmsd.permit_trend(symbol, "SELL")
    …
    if _buy_ok.allowed:
        effective_dir = "UP"; direction = "LONG"; signal = "BUY"; mode = MODE_NAME_LONG
        if has_open_long:  self._log_block("slot_taken_long",  bar_ts=cur.timestamp); return None
    elif _sell_ok.allowed:
        effective_dir = "DOWN"; direction = "SHORT"; signal = "SELL"; mode = MODE_NAME_SHORT
        if has_open_short: self._log_block("slot_taken_short", bar_ts=cur.timestamp); return None
    else:
        self._log_block("nms_direction_blocked",
                        reason_buy=_buy_ok.reason,
                        reason_sell=_sell_ok.reason,
                        v3_state=_buy_ok.v3_state or _sell_ok.v3_state,
                        bar_ts=cur.timestamp)
        return None
    _nms_fast_path = True
else:
    _nms_fast_path = False
```
What `permit_trend` says (`nms_session_trend_direction.py` lines 240-250 docstring):

> STRONG_UP / EMERGING_UP → BUY only; STRONG_DOWN / EMERGING_DOWN → SELL only; RANGE / NORMAL / UNKNOWN → no trade; missing / stale → fail-closed (= UNKNOWN).

It reads `v3_state` from the GBPUSD session-trend snapshot at `/opt/tradingbot/cache/session_trend_GBPUSD.json` (same file EMA Pullback and BB Bounce use).

When `_nms_fast_path = True` the entire legacy block in steps G1-G3 below is **skipped**. The daily spine, regime read, intraday flip, label gate, GRIND widening and GRIND spine-deferral never run on host REDACTED.

**Step G (legacy path, currently inactive) — daily spine + regime + intraday flip + label gate + GRIND widening (lines 1356-1490).** Still in the code but gated out by DIRECTION_FROM_NMS_SESSION_TREND=1. See §7 (Broken/unused/contradictory).

**Step H — Ribbon-state arming gate (lines 1499-1507).** Only runs if both `RIBBON_GATE_ENABLED=1` and `RIBBON_GATE_TREND_V3=1`. Classifies the EMA ribbon on the last ~20 bars (via `ribbon_state.classify(closes, highs, lows)`). Matrix (from `_ribbon_gate_apply_at_arm_tv3`, lines 191-260):
- BRAIDED → return SUPPRESS → block.
- FANNED_UP → LONG passes; SHORT suppressed (counter-trend).
- FANNED_DOWN → SHORT passes; LONG suppressed.
- TRANSITIONAL → arms a deferral; returns "DEFER", strategy returns None for this bar. On a later bar, if close pushes beyond the setup bar's extreme in direction (`setup.setup_high` for LONG or `setup.setup_low` for SHORT) the deferral confirms and a fire returns in Step A above. Deferral expires after `ribbon_state.RIBBON_CONFIRM_EXPIRY_BARS` or on a close back through the stop-side price.
- UNKNOWN → PASS (fail-safe).

**Step I — Velocity/exhaustion JOIN gate (lines 1514-1539).** Only when `VELOCITY_GATE_ENABLED=1` and `len(bars) >= 20`. Classifies recent 3-bar / 12-bar velocity via `ribbon_state.velocity_state`. If the current trade direction matches the 12-bar move (a JOIN entry), AND
```
atr_mult >= VELOCITY_JOIN_ATRMULT_MAX (default 2.5) AND accel < VELOCITY_JOIN_ACCEL_MIN (default 0.9)
```
→ return None (spent-spike bucket).

**Step J — Re-entry cooldown (normal path) (lines 1544-1551).** Reads `_cooldown_bars_remaining(epic, direction, bar_ts)` — if last exit-machine close on this (epic, direction) is within `TREND_V3_REENTRY_COOLDOWN_BARS × 300 s` → block with reason `reentry_cooldown`. Default `REENTRY_COOLDOWN_BARS=2` (lines 868).

**Step K — GRIND-path re-entry cooldown (lines 1560-1572).** Only when `_grind_widening_active` (always False on host REDACTED under the NMS fast path). Separate map, `GRIND_REENTRY_COOLDOWN_BARS` default 6.

**Step L — ADX + ER gates (lines 1590-1608).** The core structural checks for a non-grind fire.
```python
adx = _adx_last(df_5m)          # df_5m["ADX_14"].iloc[-1]
er  = _kaufman_er(closes_ind, ER_BARS)   # 20-bar Kaufman efficiency ratio
if not _grind_widening_active:
    if adx is None or adx < ADX_MIN:
        self._log_block("adx_below_min", adx=adx, adx_min=ADX_MIN, …); return None
    if er is None or er < ER_MIN:
        self._log_block("er_below_min", er=er, er_min=ER_MIN, …); return None
```
Defaults: `ADX_MIN=25.0`, `ER_MIN=0.5`, `ER_BARS=20` (lines 88-90). Under the NMS fast path `_grind_widening_active` is pinned False, so these gates always run.

**Step M — GRIND consolidation-break trigger (lines 1617-1648).** Grind-path only; inactive on host REDACTED.

**Step N — RANGE gate / belt-and-braces (lines 1659-1682).** Calls `guards.range_gate.evaluate(...)`. If blocked → log and return None. Fail-open on exception.

**Step O — Target and SL resolution (lines 1685-1695).** See §5 for the full algorithm. If either resolved tp_pips ≤ 0 or sl_pips ≤ 0 → block `non_positive_tp_or_sl`.

**Step P — Build decision + emit (lines 1697-1791).** Returns a `StrategyDecision` with `symbol=GBPUSD`, `regime=<regime label at fire>`, `signal=BUY|SELL`, `mode=GBPUSD_TREND_V3_L|GBPUSD_TREND_V3_S`, `entry=current_close`, `sl=<pips>`, `tp=<pips>`, `use_trailing_stop=False`, `size=None` (inherits `TRADE_SIZE` from env), `pip_size=1.0`. Writes a `fire` row to `trend_v3.jsonl` and tags whether it's a grind path.

The decision then passes to the shared autobot dispatch, which runs the central execution gate (§4) and, on approval, `trade_executor.execute_trade` to submit the broker order.

### 2.3 Exact entry moment and price for BUY

On host REDACTED today the sequence to fire a LONG is:

1. A completed 5m bar for GBPUSD closes.
2. The driver passes the frame to `TREND_V3.evaluate(…)`.
3. Steps A-C (ribbon release / session window / per-bar dedup) all clear.
4. **Direction gate.** `permit_trend("GBPUSD", "BUY")` returns `allowed=True` — this requires the session-trend v3_state to be `STRONG_UP` or `EMERGING_UP` and the snapshot to be fresh.
5. `has_open_long=False`.
6. Ribbon gate (if on): `classify(…).state ∈ {FANNED_UP, UNKNOWN}` or `TRANSITIONAL + a later confirming close`.
7. Velocity gate (if on): if JOIN and `atr_mult ≥ 2.5 AND accel < 0.9` → blocked. Otherwise pass.
8. Re-entry cooldown: no exit-machine LONG close in the last 2×5m (default) on this epic.
9. ADX: `df_5m["ADX_14"].iloc[-1] ≥ 25.0`.
10. ER: `_kaufman_er(closes, 20) ≥ 0.5` (Kaufman efficiency ratio on the last 20 closes).
11. `guards.range_gate.evaluate(..., direction="LONG", …)` not blocked.
12. `_resolve_target_and_sl("GBPUSD", "LONG", current_close, df_5m)` returns a target above entry and an SL below entry, both strictly positive in pips.
13. **Entry price** is `current_close` — i.e. the close of the just-completed 5m bar (line 1747: `entry=float(current_close)`).
14. The decision carries `use_trailing_stop=False`, broker SL/TP distances in pips; the broker fill is placed by `trade_executor.execute_trade` at market, so the actual fill price can differ from `current_close`.

### 2.4 Exact entry moment and price for SELL

Same chain as BUY except:
- Step 4 requires `permit_trend("GBPUSD", "SELL")` → `allowed=True` (requires v3_state `STRONG_DOWN` or `EMERGING_DOWN`, snapshot fresh).
- Slot check uses `has_open_short`.
- Ribbon gate: `state ∈ {FANNED_DOWN, UNKNOWN}` or TRANSITIONAL + confirming close below `setup.setup_low`.
- Entry price is still `current_close` of the just-completed 5m bar (line 1747 — identical for LONG and SHORT).

### 2.5 Everything that cancels a prospective fire

These are the explicit `return None` / `self._log_block(...); return None` sites inside `evaluate()`:

| Reason tag | Line | Condition |
|---|---|---|
| (not logged — early return) | 1169-1170 | `TREND_V3_ENABLED=0` or `symbol != "GBPUSD"` |
| (not logged — early return) | 1175-1176 | `len(bars) < 2` |
| `[TV3_SESSION] suppressed entry` | 1199-1204 | `SESSION_GATE_ENABLED=1` and `_in_session(ts) == False` (weekend or outside `SESSION_START..SESSION_END` UTC) |
| (not logged — early return) | 1207-1211 | Dedup: already evaluated this bar for this epic |
| `nms_second_gate_stand_aside` | 1257-1273 | Only if `NMS_SECOND_GATE_ENABLED=1` and the gate returns `allowed=False` |
| `nms_direction_rule_exc` | 1297-1300 | `permit_trend` raised an exception |
| `slot_taken_long` | 1327-1329 | NMS fast path admitted BUY but `has_open_long=True` |
| `slot_taken_short` | 1335-1337 | NMS fast path admitted SELL but `has_open_short=True` |
| `nms_direction_blocked` | 1339-1346 | Neither BUY nor SELL permitted by `permit_trend` (buy_reason + sell_reason recorded) |
| Legacy path only, inactive on 161: `daily_unavailable_or_flat` 1358-1361; `regime_not_strong_up` 1465-1470; `regime_not_strong_down` 1479-1484; `slot_taken_long` 1474-1476; `slot_taken_short` 1488-1490 |
| (unlogged) ribbon `SUPPRESS` or `DEFER` | 1499-1507 | `RIBBON_GATE_ENABLED=1` and `RIBBON_GATE_TREND_V3=1` and (BRAIDED, counter-trend FANNED, or TRANSITIONAL) |
| `[VELOCITY-GATE] TREND_V3 suppressed JOIN` | 1529-1537 | `VELOCITY_GATE_ENABLED=1`, JOIN direction, atr_mult ≥ 2.5 AND accel < 0.9 |
| `reentry_cooldown` | 1546-1551 | Same-direction exit-machine close within last `REENTRY_COOLDOWN_BARS × 5m` |
| `grind_reentry_cooldown` | 1565-1572 | GRIND path only — inactive on 161 |
| `adx_below_min` | 1593-1596 | `df_5m["ADX_14"].iloc[-1] < 25.0` (default) |
| `er_below_min` | 1597-1600 | 20-bar Kaufman ER < 0.5 (default) |
| `grind_consol_not_broken_up/dn`, `grind_consol_insufficient_history` | 1617-1648 | GRIND path only — inactive on 161 |
| `range_gate_suppress` | 1671-1676 | `guards.range_gate.evaluate` returns blocked |
| `non_positive_tp_or_sl` | 1692-1694 | Resolved tp_pips or sl_pips ≤ 0 |

### 2.6 Ribbon-deferral release (how a deferred setup becomes a fire)

`_ribbon_gate_check_release_tv3` at lines 263-509. Runs BEFORE the session-gate / dedup block. For each deferred setup on this epic:
- Invalidate if ribbon state is BRAIDED, or age ≥ `RIBBON_CONFIRM_EXPIRY_BARS`, or close back through the stop-side price. Drop.
- Fire condition: `LONG` → `cur_close > setup.setup_high`; `SHORT` → `cur_close < setup.setup_low` (lines 372-375).
- Re-check safety gates against fresh data (news-release window, `_in_session`, slot occupancy), and rebuild SL/TP via the strategy's own `_resolve_target_and_sl`.
- If every gate clears, return a `StrategyDecision` with `entry = float(cur_close)` (line 425) and the same SL/TP as the fire path.

---

## 3. Prices, timeframes, indicators and every setting

### Prices

- **Candles archive:** `/opt/tradingbot/data/candles/GBPUSD/<YYYY-MM-DD>.csv`, header `timestamp,open,high,low,close`. The archive is written by `candle_archive.py` from each completed 5-minute bar; `autobot.py:1819` records *"candle_archive (data/candles/{SYM}/YYYY-MM-DD.csv, canonical MID basis)"*. The 5m frame passed to `evaluate` (`df_5m`) therefore carries mid-price OHLC.
- The direction authority `permit_trend` reads `/opt/tradingbot/cache/session_trend_GBPUSD.json` (NMS session-trend v3_state). TREND_V3 does not call the live IG tick feed itself.

### Timeframes

- **5-minute (primary):** every evaluation runs on a completed 5m bar close. `df_5m` is the enriched frame with `ADX_14`, `MACD_HIST_35_45_30`, `ATR_14`, `close`. `closes_ind` is the plain list of 5m closes.
- **H4 (structural target):** `_h4_structural_target` reads `TimeframeContext.get_closed_candles("GBPUSD", "H4")` and looks at the last `H4_LOOKBACK_BARS` (default 12). LONG target = max H4 high strictly above `current_close`; SHORT target = min H4 low strictly below `current_close`.
- **D1 (legacy daily-spine; inactive on host REDACTED):** `_prior_daily_direction` reads `TimeframeContext._d1_closed` and compares the last closed D1's open vs close.

### Indicators and their settings

| Indicator | Where computed | Setting | Default | Current env (host REDACTED) |
|---|---|---|---|---|
| ADX_14 | pre-populated on `df_5m` by the regime layer; read at `gbpusd_trend_v3.py:650` | `TREND_V3_ADX_MIN` | 25.0 | not set in env — default 25.0 |
| Kaufman ER | `_kaufman_er(closes, n)` at line 618 | `TREND_V3_ER_MIN` / `TREND_V3_ER_BARS` | 0.5 / 20 | not set — defaults |
| MACD histogram | `MACD_HIST_35_45_30` column on `df_5m`; used in `monitor_exits` + `_m1_aligned` via `runner_momentum.macd_hist_last_and_contracting` | (periods fixed in the column name: fast 35, slow 45, signal 30) | — | — |
| ATR_14 | pre-populated on `df_5m`; read at line 658 | `TREND_V3_TP_FALLBACK_ATR_MULT` | 2.5 | not set — default 2.5 |
| Ribbon-state classifier | `ribbon_state.classify(closes, highs, lows)` | `RIBBON_GATE_ENABLED`, `RIBBON_GATE_TREND_V3` | 0, 0 | both 1 |
| Velocity classifier | `ribbon_state.velocity_state(closes, highs, lows)` | `VELOCITY_GATE_ENABLED`, `VELOCITY_JOIN_ATRMULT_MAX`, `VELOCITY_JOIN_ACCEL_MIN` | 0, 2.5, 0.9 | VELOCITY_GATE_ENABLED=1, VELOCITY_JOIN_ATRMULT_MAX=2.5, VELOCITY_JOIN_ACCEL_MIN=0.9 |
| 5m swings | `market_structure.analyze(highs, lows, closes)` — used for SL fallback + 5m-swing target fallback | — | — |
| 20-period SMA on closes | computed inline in `autobot.py:3216 _sma20 = sum(closes[-20:])/20.0` for UM SMA-cross exit | — | — |

### Every TREND_V3-affecting .env setting on host REDACTED

Values read from `/opt/tradingbot/.env` at snapshot:

| .env key | File line | Value on 161 | Effect |
|---|---|---|---|
| `TREND_V3_ENABLED` | 639 | `1` | Master enable. `evaluate` short-circuits when `0`. |
| `DIRECTION_FROM_NMS_SESSION_TREND` | 1131 | `1` | Switches direction authority to `nms_session_trend_direction.permit_trend`. **When on, the entire legacy daily-spine + regime-gate + intraday-flip + GRIND block is bypassed.** |
| `TREND_V3_SESSION_END_UTC` | 929 | `20:00` | End of entry window (UTC). |
| `TREND_V3_ADMIT` | 1079 | `1` | Central-execution-gate admits all four GBPUSD_TREND_V3 modes through the Stage-11 cutover (`central_execution_gate.py:2414`). |
| `RIBBON_GATE_ENABLED` | 241 | `1` | Master ribbon gate on. |
| `RIBBON_GATE_TREND_V3` | 244 | `1` | TREND_V3-specific arm. |
| `VELOCITY_GATE_ENABLED` | 255 | `1` | JOIN velocity gate on. |
| `VELOCITY_JOIN_ATRMULT_MAX` | 256 | `2.5` | Threshold for spent-spike suppression. |
| `VELOCITY_JOIN_ACCEL_MIN` | 257 | `0.9` | Threshold for spent-spike suppression. |
| `TRADE_SIZE` | 553 | `2.0` | Fleet size inherited by TREND_V3 fires (decision.size=None). |
| `LADDER_ENABLED` | 919 | `1` | Universal position-management ladder enabled. |
| `LADDER_MANAGED_MODES` | 920 | `GBPUSD_EMA_PULLBACK_L,GBPUSD_EMA_PULLBACK_S,GBPUSD_TREND_V3_L,GBPUSD_TREND_V3_S` | Only these four modes are "managed" by the universal ladder. UM modes are excluded by design. |
| `EXIT_STACK_GBPUSD_TREND_V3_L` | 942 | `TIERED_RATCHET` | Exit stack for managed LONG. |
| `EXIT_STACK_GBPUSD_TREND_V3_S` | 943 | `TIERED_RATCHET` | Exit stack for managed SHORT. |
| `NEWS_POST_LOCKOUT_ENABLED` | 105 | `1` | Post-release lockout honoured by central dispatch; prevents TREND_V3 fires in NEWS_POST_BLOCK_*_MIN after a classified release. |
| `NEWS_POST_BLOCK_TOP_MIN` | 106 | `30` | — |
| `NEWS_POST_BLOCK_MED_MIN` | 107 | `15` | — |
| `NEWS_POST_BLOCK_LOW_MIN` | 108 | `0` | — |

Settings the code uses that are **not set in .env** and therefore take their module defaults (defaults from `gbpusd_trend_v3.py`):

| Setting | Default | Code line |
|---|---|---|
| `TREND_V3_ADX_MIN` | 25.0 | 88 |
| `TREND_V3_ER_MIN` | 0.5 | 89 |
| `TREND_V3_ER_BARS` | 20 | 90 |
| `TREND_V3_GRIND_CONSOL_BARS` | 4 | 96 |
| `TREND_V3_FLATTEN_BARS` | 6 | 97 |
| `TREND_V3_SL_FALLBACK_PIPS` | 15.0 | 98 |
| `TREND_V3_SL_BUFFER_PIPS` | 2.0 | 99 |
| `TREND_V3_MAX_SL_PIPS` | 12 | 105-113 |
| `TREND_V3_TP_FALLBACK_ATR_MULT` | 2.5 | 115 |
| `TREND_V3_TP_FALLBACK_PIPS` | 30.0 | 116 |
| `TREND_V3_H4_LOOKBACK_BARS` | 12 | 117 |
| `TREND_V3_MIN_TARGET_PIPS` | 10.0 | 118 |
| `TREND_V3_MAX_TARGET_PIPS` | 200.0 | 119 |
| `TREND_V3_LOG_PATH` | `/opt/tradingbot/logs/trend_v3.jsonl` | 121 |
| `TREND_V3_MAX_HOLD_MIN` | 1440 | 124 |
| `TREND_V3_INTRADAY_FLIP_ENABLED` | 1 | 136 (legacy path, inactive on 161) |
| `TREND_V3_FLIP_CONFIRM_BARS` | 6 | 137 (legacy path, inactive on 161) |
| `TREND_V3_SESSION_GATE_ENABLED` | 1 | 153 |
| `TREND_V3_SESSION_START_UTC` | `07:00` | 154 |
| `TREND_V3_REENTRY_COOLDOWN_BARS` | 2 | 868 |
| `TREND_V3_GRIND_REENTRY_COOLDOWN_BARS` | 6 | 879 (inactive on 161) |
| `TREND_V3_REGIME_LEFT_PERSIST_BARS` | 2 | 983 |
| `EXH_MOMENTUM_CHECK_ENABLED` | 1 | 994 |
| `EXH_MOMENTUM_FLATTEN_BARS` | =`TREND_V3_FLATTEN_BARS`=6 | 995 |
| `REGIME_MATRIX_ENABLED` | 0 | module-level — inactive |
| `NMS_SECOND_GATE_ENABLED` | 0 | module-level — inactive |
| `TREND_V3_UM_EOD_CLOSE_ENABLED` | 1 | `autobot.py:2964` |
| `TREND_V3_UM_EOD_CLOSE_UTC` | not set → falls back to internal NY-close default | `autobot.py:2928` |

UM-variant constants are hard-coded (not env-tunable): `UM_SL_PIPS=12.0`, `UM_TP_PIPS=100.0` (lines 60-61).

---

## 4. Dependencies — what else TREND_V3 reads or is gated by

### Direct code imports

- `autobot._TF_CTX` — TimeframeContext for D1 (legacy spine) and H4 (structural target).
- `regime_engine.latest_result(symbol)` — supplies the regime label, confidence, directional bias, `label_path`, `trend_subtype`.
- `regime_matrix` — the admission check `permits(symbol, mode)` ahead of the TREND_V3 callback; a no-op when `REGIME_MATRIX_ENABLED=0`.
- `nms_session_trend_direction.permit_trend` — THE direction authority on host REDACTED (`DIRECTION_FROM_NMS_SESSION_TREND=1`). Reads the session-trend v3_state from `/opt/tradingbot/cache/session_trend_GBPUSD.json`.
- `nms_second_gate.check(symbol, "GBPUSD_TREND_V3")` — optional second NMS stand-aside gate (off by default).
- `ribbon_state.classify`, `ribbon_state.velocity_state`, `ribbon_state.RibbonDeferralStore` — ribbon gate + deferral + velocity gate.
- `runner_momentum.macd_hist_last_and_contracting`, `runner_momentum.m1_aligned` — shared MACD-hist helpers; locked by regression tests so TREND_V3's exit machine stays byte-identical to the universal trade_manager check.
- `market_structure.analyze` — for 5m last_swing_high / last_swing_low (fallback target + SL anchor).
- `guards.range_gate.evaluate` — belt-and-braces range suppressor.
- `news_release_window.is_in_release_window(ts)` — pre/post news blackout (only consulted in the ribbon-deferral release path).
- `strategy_logic.StrategyDecision` — the dataclass TREND_V3 returns.
- `trade_executor.EPIC_STATE`, `_pos_key`, `close_position` — for `monitor_exits` closes.

### Admission

Before any fire reaches the broker:

1. **`autobot.on_5m_close_gbpusd`** checks `regime_matrix.permits(symbol, GBPUSD_TREND_V3_L or _S)` and suppresses if neither is permitted. Because `REGIME_MATRIX_ENABLED=0`, `permits()` returns True for everything today, so this is a no-op.
2. **`strategy_services.dispatch(decision)`** hands the decision to **`central_execution_gate`** which:
   - Maps mode `GBPUSD_TREND_V3` → family `TREND_V3` (CEG line 1427).
   - Applies the family-direction / A10 matrix. For TREND_V3 under `DIRECTION_FROM_NMS_SESSION_TREND=1` the direction check is delegated to `permit_trend` at CEG line 2238 — the second check happens here even though evaluate already asked (fail-closed symmetry).
   - Applies `_apply_countertrend_continuation_veto`, `news_release_blackout`, `news_release_window`, `news_slot_ledger`, `NEWS_POST_LOCKOUT` (via trade_executor), plus the `TREND_V3_ADMIT=1` gate at CEG 2414.
3. **`trade_executor.execute_trade`** places the broker order. Post-fill, `on_open` is called back into `gbpusd_trend_v3.on_open` to seed the exit-machine state (`_OpenPos`).

### Session trend (the direction authority)

`/opt/tradingbot/cache/session_trend_GBPUSD.json`. Produced by the `nms_directional_authority` subsystem on 5m bar close. Fields consumed: `v3_state` (STRONG_UP, EMERGING_UP, STRONG_DOWN, EMERGING_DOWN, RANGE, NORMAL, UNKNOWN) and freshness (`max_age_s`). Stale or missing → `permit_trend` fails closed with reason `UNKNOWN` → both sides blocked.

---

## 5. SL, TP and exits

### Target and stop at entry — `_resolve_target_and_sl`, lines 738-823

**Target preference** (first non-None wins):
1. **H4 structural level** (`_h4_structural_target`, line 671). LONG: max H4 high strictly above `current_close` from the last 12 H4 bars. SHORT: min H4 low strictly below. If no qualifying H4 level, falls through.
2. **5m last swing** (`_swing_5m`, line 714). LONG: last swing high above current close. SHORT: last swing low below. If no qualifying swing, falls through.
3. **ATR fallback.** `dist_pips = TP_FALLBACK_ATR_MULT * ATR_14 / pip_size` (default 2.5 × ATR), or a flat `TP_FALLBACK_PIPS=30` if ATR is unavailable.

After selection, target distance is **clamped to `[MIN_TARGET_PIPS, MAX_TARGET_PIPS] = [10p, 200p]`**. On host REDACTED's live corpus (2026-08-11 → 2026-10-30, 918 fire rows) `target_source` distribution: `atr_fallback` 767, `h4` 143, `5m_swing_low` 5, `5m_swing_high` 3. In practice almost every fire uses the ATR fallback.

**Stop preference:**
1. **5m swing anchor.** LONG: `sl_px = last_swing_low - SL_BUFFER_PIPS` (2p). SHORT: `sl_px = last_swing_high + SL_BUFFER_PIPS`.
2. **Fixed fallback.** `SL_FALLBACK_PIPS = 15p` away from entry.

Then the hard cap: `MAX_SL_PIPS = 12` (resolved at line 105-113 — set `TREND_V3_MAX_SL_PIPS=0` or empty to disable). If the resolved SL distance exceeds 12p, it is clamped to 12p. Rationale in the code comment (lines 100-104): *"96 real TREND-family fills: only 3/96 winners ever exceeded 12p MAE."* Net effect on host REDACTED: TREND_V3 managed fires almost always ship with a **12-pip broker stop**.

Signal_log evidence (34 closed TREND_V3 trades over 2026-09-07 → 2026-10-27): every row carries `sl_pips=12.0`.

### In-flight management (managed modes `_L` / `_S`)

Routed to **TIERED_RATCHET** via `EXIT_STACK_GBPUSD_TREND_V3_L/S=TIERED_RATCHET` (.env:942-943). The ratchet contract (from the .env block at 937-942):
- Broker backstop: entry ± `RATCHET_INIT_SL_PIPS` (default 12p, guard permitting).
- Software tiers: `RATCHET_TIERS = 10:0, 30:15, 60:40, 100:75` — at every tier, the SL is tightened to the level in pips profit on the right-hand side of the colon when MFE reaches the left-hand side.
- Exhaustion flat: strictly beyond BE, `RATCHET_EXHAUST_BARS` flat (default 6).
- Session flat: `RATCHET_FLAT_HHMM` default 20:40 UTC.

The universal LADDER (trade_manager) is also enabled for these modes (`LADDER_ENABLED=1`, `LADDER_MANAGED_MODES` includes both managed TREND_V3 modes), but `EXIT_STACK_*` in `exit_dress.resolve` is the highest precedence, so TREND_V3 managed fires follow TIERED_RATCHET.

### TREND_V3 exit machine — `monitor_exits`, lines 1890-2167

Runs on every 5m close for each active managed TREND_V3 position. Three close triggers, evaluated after updating `best_extreme_close` and `bars_since_new_extreme`:

1. **FLATTEN_EXHAUSTION.** `bars_since_new_extreme ≥ EXH_MOMENTUM_FLATTEN_BARS (6)` AND momentum_fade, where `momentum_fade = (current_20bar_ER < entry_ER) OR MACD_HIST contracting`. When `EXH_MOMENTUM_CHECK_ENABLED=1` (default on) the raw trigger does NOT flatten unconditionally; instead it runs the M1 check: if `sign(MACD_HIST) == direction` → HOLD (consume event until a new extreme), else EXIT with reason `TREND_V3_FLATTEN_EXHAUSTION`.
2. **STRUCTURAL_BREAK.** `close_now < sl_price` for LONG or `close_now > sl_price` for SHORT. Belt-and-braces — the broker SL usually fires first.
3. **REGIME_LEFT.** Regime `latest_result` is not `STRONG_TREND_UP` (for LONG) / `STRONG_TREND_DOWN` (for SHORT). Must persist for `REGIME_LEFT_PERSIST_BARS=2` consecutive 5m bars. If the regime returns at any point the streak resets. Same M1 gate as FLATTEN: aligned MACD-hist → HOLD; against → EXIT with reason `TREND_V3_REGIME_LEFT`.

On close, `close_position(pos_key=pk, reason=f"TREND_V3_{close_reason}", exit_hint_price=close_now)` is called and `_record_close_for_cooldown(epic, direction, ts)` stamps the re-entry cooldown.

### UM variant exits (unmanaged `_UM_L` / `_UM_S`)

Fixed 12p broker SL / 100p broker TP (`UM_SL_PIPS` / `UM_TP_PIPS` at lines 60-61). No `monitor_exits` participation, no BE amend, no scale-out, no trail, no `STRUCTURE_EXIT`, no `REGIME_MAX_HOLD`. Three ways out:

1. **Broker SL / TP** — 12p / 100p.
2. **GRIND_SMA_CROSS** — `_apply_trend_v3_um_sma_cross_close` (`autobot.py:3191`). On every 5m close: compute `SMA20 = mean(closes[-20:])`; a BUY UM closes when `bar_close < SMA20`, SELL UM closes when `bar_close > SMA20`. Reason tag `GRIND_SMA_CROSS` (mapped to EARLY by `trades_api._EXIT_TYPE_BY_CLOSE_REASON`).
3. **TREND_V3_UM_EOD** — `_apply_trend_v3_um_eod_close` (`autobot.py:2955`). Once per day at the resolved NY-close time (default 20:40 UTC per code, adjustable via `TREND_V3_UM_EOD_CLOSE_UTC`). Sweeps every open UM position. Reason tag `TREND_V3_UM_EOD`.

Universal +10p/50% scale-out and SL→BE auto run on the managed modes via `trade_manager` but are skipped for UM modes by `_TREND_V3_UM_MODES` filters.

### On the records

Of 34 closed TREND_V3 trades on host REDACTED, `close_reason` distribution:
`GRIND_SMA_CROSS` 14 · `STRUCTURE_EXIT:structure_flip_*` 6 · `IG_RECONCILE` 3 · `External close` 3 · `TREND_V3_REGIME_LEFT` 1 · `TREND_V3_FLATTEN_EXHAUSTION` 1 · `BE_STOP_POST_SCALEOUT` 2 · `SL hit` 1 · `TREND_V3_UM_EOD` 1 · (other) 2.

---

## 6. Real trades from the records

Source: `/opt/tradingbot/logs/signal_log.jsonl` (+ `.jsonl-20261023.gz`). 34 closed trades whose `strategy ∈ {GBPUSD_TREND_V3_L, GBPUSD_TREND_V3_S, GBPUSD_TREND_V3_UM_L, GBPUSD_TREND_V3_UM_S}`.

- Date range opened: **2026-09-07 07:05Z → 2026-10-27 09:35Z** (closes 09-07 11:05Z → 10-27 10:15Z).
- **34 trades · 10 wins · 24 losses · 0 flats · net −82.55 pips.**
- Wins +87.00p total; losses −169.55p total.

By mode:

| Mode | Trades | Wins | Losses | Net pips |
|---|---:|---:|---:|---:|
| `GBPUSD_TREND_V3_L` (managed LONG) | 7 | 3 | 4 | −14.45 |
| `GBPUSD_TREND_V3_S` (managed SHORT) | 7 | 2 | 5 | −13.40 |
| `GBPUSD_TREND_V3_UM_L` (unmanaged LONG, 12p/100p) | 13 | 3 | 10 | −35.20 |
| `GBPUSD_TREND_V3_UM_S` (unmanaged SHORT, 12p/100p) | 7 | 2 | 5 | −19.50 |

Every trade, oldest first (ts = open-time, UTC; entry / close in GBPUSD IG price points, 1 point = 1 pip):

| open | strategy | dir | entry | close | pnl_pips | close_reason |
|---|---|---|---:|---:|---:|---|
| 2026-09-07T07:05 | GBPUSD_TREND_V3_L | BUY | 13529.00 | 13536.90 | +7.90 | TREND_V3_REGIME_LEFT |
| 2026-09-07T12:25 | GBPUSD_TREND_V3_UM_L | BUY | 13534.50 | 13536.80 | +2.30 | GRIND_SMA_CROSS |
| 2026-09-07T14:15 | GBPUSD_TREND_V3_UM_L | BUY | 13540.90 | 13539.70 | −1.20 | GRIND_SMA_CROSS |
| 2026-09-07T16:30 | GBPUSD_TREND_V3_UM_L | BUY | 13543.50 | 13542.40 | −1.10 | GRIND_SMA_CROSS |
| 2026-09-08T13:25 | GBPUSD_TREND_V3_L | BUY | 13558.70 | 13547.45 | −11.25 | STRUCTURE_EXIT:structure_flip_down |
| 2026-09-10T09:00 | GBPUSD_TREND_V3_UM_L | BUY | 13557.50 | 13551.60 | −5.90 | GRIND_SMA_CROSS |
| 2026-09-10T11:10 | GBPUSD_TREND_V3_S | SELL | 13531.80 | 13506.35 | +25.45 | BE_STOP_POST_SCALEOUT |
| 2026-09-10T15:00 | GBPUSD_TREND_V3_S | SELL | 13529.20 | 13530.90 | −1.70 | TREND_V3_FLATTEN_EXHAUSTION |
| 2026-09-14T16:40 | GBPUSD_TREND_V3_L | BUY | 13498.60 | 13508.95 | +10.35 | External close |
| 2026-09-15T11:00 | GBPUSD_TREND_V3_UM_S | SELL | 13474.40 | 13480.50 | −6.10 | GRIND_SMA_CROSS |
| 2026-09-16T10:00 | GBPUSD_TREND_V3_UM_S | SELL | 13466.90 | 13470.90 | −4.00 | GRIND_SMA_CROSS |
| 2026-09-16T11:10 | GBPUSD_TREND_V3_UM_S | SELL | 13463.90 | 13458.40 | +5.50 | GRIND_SMA_CROSS |
| 2026-09-16T14:05 | GBPUSD_TREND_V3_UM_S | SELL | 13448.20 | 13456.30 | −8.10 | GRIND_SMA_CROSS |
| 2026-09-17T15:45 | GBPUSD_TREND_V3_S | SELL | 13340.30 | 13351.30 | −11.00 | STRUCTURE_EXIT:structure_flip_up |
| 2026-09-22T16:10 | GBPUSD_TREND_V3_S | SELL | 13324.60 | 13333.35 | −8.75 | External close |
| 2026-09-25T08:10 | GBPUSD_TREND_V3_UM_L | BUY | 13237.00 | 13231.10 | −5.90 | GRIND_SMA_CROSS |
| 2026-10-09T12:20 | GBPUSD_TREND_V3_UM_S | SELL | 13216.60 | 13219.20 | −2.60 | GRIND_SMA_CROSS |
| 2026-10-09T18:00 | GBPUSD_TREND_V3_UM_L | BUY | 13235.70 | 13235.50 | −0.20 | TREND_V3_UM_EOD |
| 2026-10-12T15:25 | GBPUSD_TREND_V3_UM_S | SELL | 13210.90 | 13208.60 | +2.30 | GRIND_SMA_CROSS |
| 2026-10-13T10:05 | GBPUSD_TREND_V3_UM_L | BUY | 13240.50 | 13245.20 | +4.70 | IG_RECONCILE |
| 2026-10-13T13:25 | GBPUSD_TREND_V3_UM_L | BUY | 13253.80 | 13247.00 | −6.80 | GRIND_SMA_CROSS |
| 2026-10-13T18:10 | GBPUSD_TREND_V3_UM_L | BUY | 13257.00 | 13245.00 | −12.00 | IG_RECONCILE |
| 2026-10-14T14:00 | GBPUSD_TREND_V3_S | SELL | 13165.80 | 13156.25 | +9.55 | STRUCTURE_EXIT:structure_flip_up |
| 2026-10-15T09:40 | GBPUSD_TREND_V3_L | BUY | 13272.70 | 13262.85 | −9.85 | SL hit |
| 2026-10-15T19:40 | GBPUSD_TREND_V3_UM_L | BUY | 13274.20 | 13262.20 | −12.00 | IG_RECONCILE |
| 2026-10-16T07:15 | GBPUSD_TREND_V3_UM_L | BUY | 13316.60 | 13333.20 | +16.60 | GRIND_SMA_CROSS |
| 2026-10-16T14:35 | GBPUSD_TREND_V3_L | BUY | 13367.90 | 13357.20 | −10.70 | STRUCTURE_EXIT:structure_flip_down |
| 2026-10-16T16:40 | GBPUSD_TREND_V3_S | SELL | 13314.00 | 13331.55 | −17.55 | STRUCTURE_EXIT:structure_flip_up |
| 2026-10-19T17:10 | GBPUSD_TREND_V3_UM_S | SELL | 13299.40 | 13305.90 | −6.50 | GRIND_SMA_CROSS |
| 2026-10-20T08:50 | GBPUSD_TREND_V3_UM_L | BUY | 13356.40 | 13347.60 | −8.80 | GRIND_SMA_CROSS |
| 2026-10-20T13:25 | GBPUSD_TREND_V3_L | BUY | 13381.10 | 13383.45 | +2.35 | BE_STOP_POST_SCALEOUT |
| 2026-10-20T18:50 | GBPUSD_TREND_V3_UM_L | BUY | 13384.90 | 13380.00 | −4.90 | GRIND_SMA_CROSS |
| 2026-10-22T17:35 | GBPUSD_TREND_V3_L | BUY | 13406.30 | 13403.05 | −3.25 | External close |
| 2026-10-27T09:35 | GBPUSD_TREND_V3_S | SELL | 13309.00 | 13318.40 | −9.40 | STRUCTURE_EXIT:structure_flip_up |

### Thursday 5 and Friday 6 November 2026

**No TREND_V3 trades.** Zero fires in `trend_v3.jsonl` (134 bars on Nov 6, 114 on Nov 5 — every one logged a `block` row). Primary block reasons on those two days:
- `nms_direction_blocked` with `reason_buy/sell=unified:BLOCK_TREND_NO_ESTABLISHED_DIRECTION:side=…:state=RANGE` (v3_state in RANGE for most of both sessions), and briefly `unified:BLOCK_WATCH_AND_WAIT:watched_trend=UP trigger_direction=BUYING_EXHAUSTION triggered_at=2026-11-06T17:15Z`.
- `adx_below_min` with ADX between 12.7 and 14.1 (far below the 25 floor) in the 17:50-18:00Z window on Nov 6.

Note. Trades recorded on Nov 5 / 6 in the shared signal log carry mode `V3_BB_S` (2026-11-05 14:42Z SELL, entry 13457.6, −9.95p SL-hit) and `V3_EMA_L` (2026-11-06 17:10Z BUY, entry 13370.6, −5.95p external close). These **are not TREND_V3** — they are BB_BOUNCE / EMA_PULLBACK admitted via the V3 range-admission scheme (see `central_execution_gate.py:2345` — "Applies to V3_BB_L/_S, V3_EMA_L/_S, GBPUSD_TREND_V3_UM_L/_S only").

### Signal log coverage caveat

`trend_v3.jsonl` fire rows run **2026-08-11 → 2026-10-30** (918 rows total: 633 LONG, 285 SHORT, 861 tagged `grind_path=true`, 57 tagged `grind_path=false`). The signal_log on this host only covers the 34 reconciled trades listed above (2026-09-07 → 2026-10-27). The gap is explained by:
- Not every fire reaches the broker — the central execution gate rejects many.
- The fire log is kept per strategy; the signal_log is populated only at broker-close reconciliation.
- Earlier than 2026-08-11 fires, if any, are not in the rotated jsonl stash on this host (NOT FOUND).

---

## 7. Things that look broken, unused, switched off or contradictory

Reported, not fixed. These are observations from the code + current host env + logs only.

1. **The strategy's documented invariant is not what runs on host REDACTED.** The module docstring (lines 11-27) describes daily-spine authority, regime-gate STRONG_TREND requirement, intraday flip and GRIND widening as the entry logic. On host REDACTED `DIRECTION_FROM_NMS_SESSION_TREND=1` short-circuits this entire block (lines 1291-1354 take the NMS fast path; lines 1356-1490 are jumped). Direction authority is `nms_session_trend_direction.permit_trend` reading `/opt/tradingbot/cache/session_trend_GBPUSD.json`. The docstring was not updated. A rebuilder reading the docstring would implement the wrong gate.

2. **GRIND sub-path is dead on host REDACTED.** Because the NMS fast path pins `_grind_widening_active = False` (lines 1319-1321), the entire GRIND block (widening → spine deferral → consolidation-break trigger → grind re-entry cooldown → ADX+ER skip) at lines 1392-1648 cannot execute. All 861 "grind_path=true" fire rows in `trend_v3.jsonl` are **from before** DIRECTION_FROM_NMS_SESSION_TREND=1 was flipped on; current fires log `grind_path=false`.

3. **`_apply_trend_v3_um_sma_cross_close` fires even though UM modes are not admitted today.** `autobot.py:9598` calls the SMA-cross close unconditionally per bar; it closes any active UM position. The 34-trade sample includes 20 UM trades, so UM has fired historically. But under the NMS fast path there is no code branch that selects `MODE_NAME_UM_LONG/SHORT` — the fast path only assigns `MODE_NAME_LONG` or `MODE_NAME_SHORT` (lines 1326, 1334). The UM path's own GRIND / day_posture + trend_confirmed dispatcher is **gone** from the active path. Result: UM fires currently cannot be opened via TREND_V3 itself on host REDACTED (they can still be opened by whatever historically dispatched them, but the TREND_V3 strategy no longer admits UM). The SMA-cross exit still runs over any legacy UM position that happens to be open.

4. **`regime_engine` is imported and read (`_latest_regime`) on every bar, but its result is unused when the NMS fast path is on.** Lines 1306-1321 pin `regime=None`, `reg_dbg = {"source":"nms_direction_rule", ...}` and the only later consumer is the `fire` jsonl row (which carries `regime=None` on every current fire). The call to `regime_matrix.permits` in `autobot.py:9552` is a no-op because `REGIME_MATRIX_ENABLED=0`.

5. **Intraday-direction-flip counter is dead code on host REDACTED.** `_update_flip_state` (lines 1039-1140) is inside the legacy else-branch at line 1355; unreachable under NMS fast path. The ~50 lines of docstring explaining it + the per-epic `_flip_state` dict are kept but never updated.

6. **Target source is essentially the ATR fallback.** 767 / 918 fires (83.6%) have `target_source=atr_fallback`; 143 / 918 (15.6%) have `h4`; only 8 total have a 5m-swing target. The structural intent of the strategy ("Target is structural (H4 high/low or 5m swing)" — docstring line 14) is not what actually happens on live fires; in practice TP is `2.5 × ATR` or a flat 30p.

7. **The 12-pip SL cap flattens the "structural stop" spirit.** Every signal_log row carries `sl_pips=12.0` because `MAX_SL_PIPS=12` is on by default (line 114, no env override). The code comment at 100-104 is explicit about the trade-off: "96 real TREND-family fills: only 3/96 winners ever exceeded 12p MAE." A rebuilder should know the stop is almost always the 12p broker cap, not a swing-anchor.

8. **Mix of exit stacks.** `EXIT_STACK_GBPUSD_TREND_V3_L/S=TIERED_RATCHET` routes managed TREND_V3 to tiered-ratchet in `exit_dress.resolve`, and `LADDER_MANAGED_MODES` names the same modes. Because `EXIT_STACK_` is the highest-precedence resolver (noted in the .env comment at 937), the LADDER setting is overridden for TREND_V3. Not a bug — but it's a double-configured surface and the observed close_reasons mix `TIERED_RATCHET`-style `BE_STOP_POST_SCALEOUT`, raw TREND_V3 reasons (`REGIME_LEFT`, `FLATTEN_EXHAUSTION`), `STRUCTURE_EXIT:structure_flip_*` (from `trade_manager`), broker SL hits, external closes and IG_RECONCILE (broker-side closes reconciled post-facto). Which engine actually closed a given trade is a per-trade question, not "the strategy's exit".

9. **Fast-path TP assignment can log a false comparator.** The pre-fix line 1722-1726 comment says earlier code printed `ADX=14.7>=25.0 ER=0.23>=0.50` on GRIND fires (a fake pass). The fix at 1730-1735 only suppresses the string when `_grind_widening_active` is True. Under the NMS fast path grind_widening is always False, so the comparator always prints; but `adx` and `er` are still measured — this is fine on 161, flagged here only because the comment documents a known log-formatting defect.

10. **Session gate widening without upstream change.** `TREND_V3_SESSION_END_UTC=20:00` is set but `TREND_V3_SESSION_START_UTC` is not, so start defaults to 07:00 UTC. The widened window (07:00-20:00 UTC) overlaps the UM EOD close at 20:40 UTC and the universal ratchet session flat `RATCHET_FLAT_HHMM` default 20:40 UTC. Fires between 19:xx and 20:00 UTC can be opened and then immediately flattened by one of the 20:40 sweeps.

11. **`autobot.service` currently inactive.** `systemctl status autobot.service` reports "Active: inactive (dead) since Fri 2026-11-06 18:09:38 UTC". The last fire in `trend_v3.jsonl` is dated `2026-11-06T18:00:00+00:00` (an `adx_below_min` block). Nothing is evaluating TREND_V3 right now. Not a strategy issue — reported because any rebuild running the same `.env` would see zero fires until the service is started.

12. **`V3EMA_L` / `V3_BB_S` deal references look like TREND_V3 but are not.** The autobot journal on Nov 6 shows `dealReference=REDACTED` filling at 17:10:37 UTC. The `V3EMA_L` prefix is the V3 range-admission mode for EMA_PULLBACK — see `central_execution_gate.py:2345`: "Applies to V3_BB_L/_S, V3_EMA_L/_S, GBPUSD_TREND_V3_UM_L/_S only." A rebuilder reading the journal must not count these as TREND_V3 trades (they're EMA_PULLBACK / BB_BOUNCE admitted via the V3 scheme, not TREND_V3).

13. **`RATCHET_*` env values are code defaults, not explicitly set.** The .env comment at 937-941 documents the tiers (`RATCHET_INIT_SL_PIPS=12p`, `RATCHET_TIERS=10:0,30:15,60:40,100:75`, `RATCHET_EXHAUST_BARS=6`, `RATCHET_FLAT_HHMM=20:40`), but none of those keys is actually set. They are the module-level defaults in `tiered_ratchet.py`. A rebuilder reading only `.env` will miss them.

---

## Appendix — minimum rebuild checklist for a new bot

To faithfully reproduce today's behaviour on host REDACTED:

1. Indicator inputs: 5-minute mid-OHLC, ADX_14, Kaufman ER-20, ATR_14, MACD_HIST_35_45_30, EMA-ribbon (fast/mid/slow with cross-count + pitch + spread), 5m swing-high/low from zig-zag, H4 OHLC for structural target.
2. Direction authority: an external session-trend state machine that emits one of {STRONG_UP, EMERGING_UP, STRONG_DOWN, EMERGING_DOWN, RANGE, NORMAL, UNKNOWN} per 5m close and writes it to a JSON snapshot with a freshness timestamp. STRONG/EMERGING UP → BUY only; STRONG/EMERGING DOWN → SELL only; everything else → no trade; stale/missing → fail-closed.
3. Entry triggers per bar (in order): session window, dedup, slot-occupancy bookkeeping, NMS second-gate (optional), direction authority, slot check, ribbon gate (with TRANSITIONAL deferral + beyond-extreme release), velocity JOIN gate (optional), re-entry cooldown, ADX ≥ 25, ER-20 ≥ 0.5, range gate, SL/TP resolution.
4. SL/TP: target = max(H4 structural, 5m swing, 2.5×ATR or 30p flat), clamped to [10p, 200p]. Stop = 5m swing ± 2p buffer OR 15p fallback, capped to 12p.
5. Entry price = close of the just-completed 5m bar; broker order submitted at market immediately.
6. Exits: TIERED_RATCHET stack (initial broker SL at entry±12p; software tiers 10:0, 30:15, 60:40, 100:75; exhaustion flat at 6 bars; session flat 20:40 UTC) PLUS the TREND_V3 exit machine (6-bar no-new-extreme + momentum fade, M1 HOLD/EXIT; close past structural; regime-left with 2-bar persistence).
7. Position management: universal +10p / 50% scale-out + SL→BE handled by the shared trade-manager layer.
8. Telemetry: one JSONL file per event kind {fire, open, block, exit, exh_mcheck, regime_off_streak, flip, revert} — this is what makes forensic rebuilds possible.

Per-field line references given throughout §2-§5. The two files a rebuilder must actually read in full are `/opt/tradingbot/gbpusd_trend_v3.py` and `/opt/tradingbot/nms_session_trend_direction.py`; everything else is wiring.
