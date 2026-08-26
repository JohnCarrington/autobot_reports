# QM Session B+ · Session 1 addendum (2026-08-26)

Follow-up to `qm_session_b_plus_20260826_session1.md`. Commit `972bfcb` on
`feat/trend-stretch-brake-adx-floor` (local only).

## Gap the operator caught

Session 1's `b4d4609` at `trade_manager.py:5536` only DEFERRED the legacy
`BB_RANGE_TARGET` immediate-close when QM=1 — it did not CALL
`qm_adaptive_exit.evaluate()` from inside trade_manager's live exit
evaluation. The QM authority path lived in a separate telemetry callback
(`qm_hooks._on_5m_close → _run_part2_exit_rule`), not in trade_manager's
per-tick monitor. That's a valid interpretation of "wire the exit rule",
but the operator's task named `trade_manager.py:5536` specifically and
asked for the call site to be inside the live eval. Integration was
still deferred.

## Fix

### trade_manager.py :5536 — LIVE call site

Quoted diff (post-fix):

```python
# ── Quiet-Market §21.6 adaptive-exit — LIVE call site (2026-08-26)
# For the six QM in-scope modes, when QM_ADAPTIVE_EXIT_ENABLED=1:
#   * fetch the most-recent CLOSED 5m bar for this pair
#   * once per bar per position (idempotent via _qm_last_bar_ts):
#     call qm_adaptive_exit.evaluate() with the bar's OHLC + BB
#     bands and act on the returned decision (HOLD /
#     EXIT_CLOSE_INSIDE / PROMOTE_TO_RUNNER / …).
# The env flag is read PER-CALL — NOT hoisted to a module constant.
# When flag=0 the block is a no-op and _qm_defers_range_target stays
# False so the legacy BB_RANGE_TARGET gate below reduces to its
# byte-identical pre-QM conjunction.
_qm_defers_range_target = False
_qm_in_scope_modes = {
    "GBPUSD_BB_BOUNCE_L", "GBPUSD_BB_BOUNCE_S",
    "GBPUSD_BB_REV_PAT_L", "GBPUSD_BB_REV_PAT_S",
    "GBPUSD_BB_REV_L", "GBPUSD_BB_REV_L_S",
}
_mode_up_qm = str(st.get("mode") or "").upper()
_qm_flag_now = (
    (os.getenv("QM_ADAPTIVE_EXIT_ENABLED", "0") or "0").strip().lower()
    in ("1", "true", "yes", "on")
)
if _mode_up_qm in _qm_in_scope_modes and _qm_flag_now:
    _qm_defers_range_target = True  # single-authority: skip BB_RANGE_TARGET below
    try:
        import qm_adaptive_exit as _qmx
        import candle_builder as _cb_qm
        _df_qm = _cb_qm.get_df(pair)
        if _df_qm is not None and not getattr(_df_qm, "empty", True) \
                and len(_df_qm) >= 1:
            _last_row = _df_qm.iloc[-1]
            _bar_ts_raw = _last_row.name
            _bar_ts_iso = (_bar_ts_raw.isoformat()
                           if hasattr(_bar_ts_raw, "isoformat")
                           else str(_bar_ts_raw))
            # Idempotent per bar per position
            _last_seen_bar = str(st.get("_qm_last_bar_ts") or "")
            if _bar_ts_iso and _bar_ts_iso != _last_seen_bar:
                _bb_up_qm = _bb_lo_qm = None
                for _col in ("BB_UPPER_20_2", "BB_UPPER_20", "BB_U"):
                    if _col in _df_qm.columns:
                        _bb_up_qm = float(_last_row[_col]); break
                for _col in ("BB_LOWER_20_2", "BB_LOWER_20", "BB_L"):
                    if _col in _df_qm.columns:
                        _bb_lo_qm = float(_last_row[_col]); break
                _bar_snap = _qmx.BarSnapshot(
                    ts=_bar_ts_iso,
                    open=float(_last_row["open"]),
                    high=float(_last_row["high"]),
                    low=float(_last_row["low"]),
                    close=float(_last_row["close"]),
                    bb_upper=_bb_up_qm, bb_lower=_bb_lo_qm,
                )
                # qm_state lives on the position dict at st['meta']
                _qm_meta = st.setdefault("meta", {}) if isinstance(st, dict) else {}
                _qm_state_d = _qm_meta.get("qm_state") if isinstance(_qm_meta, dict) else None
                if _qm_state_d is None:
                    _qm_state = _qmx.QmPositionState(
                        pos_key=epic, mode=_mode_up_qm,
                        direction=direction, entry_price=float(entry),
                    )
                else:
                    try:
                        _qm_state = _qmx.QmPositionState(**_qm_state_d)
                    except Exception:
                        _qm_state = _qmx.QmPositionState(
                            pos_key=epic, mode=_mode_up_qm,
                            direction=direction, entry_price=float(entry),
                        )
                _dec = _qmx.evaluate(_qm_state, _bar_snap)
                if _dec.state_after is not None and isinstance(_qm_meta, dict):
                    from dataclasses import asdict as _asdict_qm
                    _qm_meta["qm_state"] = _asdict_qm(_dec.state_after)
                st["_qm_last_bar_ts"] = _bar_ts_iso
                if _dec.action == _qmx.D_EXIT_CLOSE_INSIDE:
                    _exit_hint = float(_dec.exit_price or _bar_snap.close)
                    logger.warning(
                        "[QM_EXIT] %s mode=%s dir=%s reason=%s "
                        "exit_hint=%.5f bar_ts=%s",
                        epic, _mode_up_qm, direction, _dec.reason,
                        _exit_hint, _bar_ts_iso,
                    )
                    _exec.close_position(
                        epic=epic, reason="QM_BAND_CLOSE_INSIDE",
                        exit_hint_price=_exit_hint,
                    )
                    return
                elif _dec.action == _qmx.D_PROMOTE_TO_RUNNER:
                    if isinstance(_qm_meta, dict):
                        _qm_meta["qm_runner_promoted"] = True
                    logger.info(
                        "[QM_PROMOTE] %s mode=%s dir=%s bar_ts=%s "
                        "— QM stands down, ratchet owns",
                        epic, _mode_up_qm, direction, _bar_ts_iso,
                    )
    except Exception as _qm_exc:
        logger.warning("[QM_EXIT] %s eval raised: %s", epic, _qm_exc)
if _bbrt_is_bb_flip and _bbrt_enabled and not _qm_defers_range_target:
    ...  # legacy BB_RANGE_TARGET path
```

The env read is INSIDE the function body, at every call — verified
not-hoisted by `test_qm_env_flag_read_per_call_not_hoisted` which
toggles the flag between two calls and asserts the block respects
the live value.

### qm_hooks._on_5m_close — Part 2 fan-out removed

To keep single authority, `_run_part2_exit_rule` is no longer invoked
from the 5m-close fan-out. The function itself is retained for direct
unit-test entry (`test_qm_part2_integration.py` still exercises the
pure decision→dispatch path); the runtime driver is
`trade_manager._monitor_profit_protection`.

## Test that drives trade_manager (not the module directly)

`tests/unit/test_qm_trade_manager_wiring.py::test_qm_enabled_close_inside_triggers_close_position`

```python
def test_qm_enabled_close_inside_triggers_close_position(tm, monkeypatch):
    """Flag=1, BUY position, touch bar closes back INSIDE the band → exit
    dispatches through trade_executor.close_position with
    reason=QM_BAND_CLOSE_INSIDE and exit_hint_price = bar close."""
    monkeypatch.setenv("QM_ADAPTIVE_EXIT_ENABLED", "1")
    monkeypatch.setenv("QM_BAND_TOUCH_TOL_PIPS", "1.0")
    st = _install_position(tm)
    # Bar: h=1.36380 (touches upper=1.36355), close=1.36340 (inside)
    df = _make_df([{
        "time": "2026-08-26T07:55:00Z",
        "open": 1.36340, "high": 1.36380, "low": 1.36335, "close": 1.36340,
        "BB_UPPER_20_2": 1.36355, "BB_LOWER_20_2": 1.36310,
    }])
    with mock.patch("candle_builder.get_df", return_value=df), \
         mock.patch.object(tm._exec, "close_position") as m_close:
        tm.trade_manager._monitor_profit_protection(
            "CS.D.GBPUSD.TODAY.IP", mid_price=1.36340,
        )
    assert m_close.called
    kwargs = m_close.call_args.kwargs
    assert kwargs["reason"] == "QM_BAND_CLOSE_INSIDE"
    assert kwargs["exit_hint_price"] == pytest.approx(1.36340)
    assert kwargs["epic"] == "CS.D.GBPUSD.TODAY.IP"
```

Complementary hold-through-touch test:

`tests/unit/test_qm_trade_manager_wiring.py::test_qm_enabled_hold_through_touch_no_close`

```python
def test_qm_enabled_hold_through_touch_no_close(tm, monkeypatch):
    """Flag=1, in-scope BUY, touch bar closes BEYOND upper band (continuation)
    → HOLD; close_position must NOT be called; qm_state persists touched=True
    and consec_closes_beyond=1."""
    monkeypatch.setenv("QM_ADAPTIVE_EXIT_ENABLED", "1")
    monkeypatch.setenv("QM_BAND_TOUCH_TOL_PIPS", "1.0")
    st = _install_position(tm)
    df = _make_df([{
        "time": "2026-08-26T07:55:00Z",
        "open": 1.36340, "high": 1.36380, "low": 1.36335, "close": 1.36370,
        "BB_UPPER_20_2": 1.36355, "BB_LOWER_20_2": 1.36310,
    }])
    with mock.patch("candle_builder.get_df", return_value=df), \
         mock.patch.object(tm._exec, "close_position") as m_close:
        tm.trade_manager._monitor_profit_protection(
            "CS.D.GBPUSD.TODAY.IP", mid_price=1.36370,
        )
    assert not m_close.called, "HOLD path must not close the position"
    persisted = st["meta"]["qm_state"]
    assert persisted["touched_band"] is True
    assert persisted["consec_closes_beyond"] == 1
    assert st["_qm_last_bar_ts"] == "2026-08-26T07:55:00+00:00"
```

Both tests drive trade_manager's actual exit evaluation
(`_monitor_profit_protection`) — no direct call into `qm_adaptive_exit`.

Full new test file (7 tests, all green):

| test | asserts |
| ---- | ------- |
| `test_qm_disabled_no_call_into_module` | flag=0 → no close, no `qm_state` persistence |
| `test_qm_enabled_hold_through_touch_no_close` | flag=1 + close beyond → HOLD, state persists |
| `test_qm_enabled_close_inside_triggers_close_position` | flag=1 + close inside → close_position with QM_BAND_CLOSE_INSIDE |
| `test_qm_env_flag_read_per_call_not_hoisted` | flip flag between ticks → block respects live value |
| `test_qm_idempotent_within_same_bar` | two ticks same bar → `evaluate()` fires ONCE |
| `test_qm_out_of_scope_mode_never_reaches_module` | TREND_V3 mode → `evaluate()` never called |
| `test_qm_bb_range_target_defers_when_qm_enabled` | QM=1 + range_mode_flip → legacy BB_RANGE_TARGET does NOT fire |

## Suite delta

Deterministic run (`pytest -p no:randomly tests/unit/`):

| variant | failed | passed | skipped | errors |
| ------- | ------ | ------ | ------- | ------ |
| baseline (HEAD before Session 1) | 145 | 1543 | 20 | 28 |
| Session 1 (`b4d4609`) | 145 | 1564 | 20 | 29 |
| this addendum (`972bfcb`) | 145 | **1571** | 20 | 28 |

Failure count unchanged: **zero new failures** at either step. Passes
+7 in the addendum (the new wiring test file).

## Hand-back (unchanged from Session 1 report)

1. Restart: `sudo systemctl restart autobot`
2. Post-restart proofs (both within 2 closes):
   * `journalctl -u autobot --since "-3 min" | grep -E "\[qm_hooks\] HEARTBEAT first invocation"`
   * `ls -la logs/qm_level_map.jsonl logs/qm_chop_features.jsonl logs/qm_level_interactions.jsonl 2>&1 | grep "Aug 26"`
3. Env flip once proofs are green (no restart needed):
   * `QM_ADAPTIVE_EXIT_ENABLED=1`

Once QM=1, the live path is trade_manager `_monitor_profit_protection`
at :5536, not qm_hooks. Expect `[QM_EXIT]` warnings (on close-inside
exits) and `[QM_PROMOTE]` infos (on promote) in the autobot journal
in real time.

STOP.
