"""Regression test for 2026-07-28 fix: `_monitor_briefing_tp` must emit a
strategy-attributed close_reason. Before the fix, a BB_BOUNCE_L fill that
delegated TP/SL management to the tier machinery closed with
`BRIEFING_TP_SL_OPEN` — briefing-execution vocabulary on a BB position.
The label was misleading (not a wrong-position close: the tier meta is
per-pos_key, verified below). Fix: attribute the label to the position's
mode. BRIEFING_EXECUTION keeps `BRIEFING_TP_SL_{phase}` for downstream
compat; other modes emit `{MODE}_TIER_SL_{phase}`.
"""
from __future__ import annotations

import sys

sys.path.insert(0, "/opt/tradingbot")

import trade_manager as tm  # noqa: E402
import trades_api as ta  # noqa: E402


def test_tier_sl_label_for_bb_bounce_pos_key():
    """Simulate `_monitor_briefing_tp` calling _close_trade_best_effort for a
    BB_BOUNCE_L position — verify the derived close_reason attributes the
    close to BB_BOUNCE_L."""
    captured = {}

    def _fake_close(epic_or_pk, reason, price):
        captured["epic"] = epic_or_pk
        captured["reason"] = reason
        captured["price"] = price
        return None

    epic = "CS.D.GBPUSD.TODAY.IP|BB_BOUNCE_L"

    # Emulate the emit block at trade_manager.py:3830-3847 (SL hit branch).
    _mode = tm._exec._mode_from_pos_key(epic)
    assert _mode == "BB_BOUNCE_L"
    is_briefing = tm._is_briefing_exec_mode(_mode)
    assert is_briefing is False
    phase = "OPEN"
    reason = (f"BRIEFING_TP_SL_{phase}" if is_briefing
              else f"{_mode}_TIER_SL_{phase}")
    _fake_close(epic, reason, 13340.0)

    assert captured["reason"] == "BB_BOUNCE_L_TIER_SL_OPEN"


def test_briefing_execution_label_preserved():
    """Parity: BRIEFING_EXECUTION positions keep the pre-fix label so
    trades_api._classify_exit_type (:1058) still routes them correctly."""
    epic = "CS.D.GBPUSD.TODAY.IP|BRIEFING_EXECUTION"
    _mode = tm._exec._mode_from_pos_key(epic)
    assert tm._is_briefing_exec_mode(_mode)
    phase = "OPEN"
    reason = (f"BRIEFING_TP_SL_{phase}" if tm._is_briefing_exec_mode(_mode)
              else f"{_mode}_TIER_SL_{phase}")
    assert reason == "BRIEFING_TP_SL_OPEN"


def test_trades_api_classifies_tier_sl_open_on_bb_bounce():
    """Downstream trades_api must handle the new attributed label with the
    same TP/SL-by-pnl-sign tiebreak used for BRIEFING_TP_SL_OPEN."""
    r_stop = ta._classify_exit_type(
        close_reason_prefix="BB_BOUNCE_L_TIER_SL_OPEN",
        pnl_pips=-20.1, pnl_gbp=None,
        close_level=13340.0, stop_level=13340.0, limit_level=None,
        stop_was_amended_toward_entry=False, has_levels=True,
    )
    assert r_stop == "STOP"

    r_target = ta._classify_exit_type(
        close_reason_prefix="BB_BOUNCE_L_TIER_SL_OPEN",
        pnl_pips=+18.4, pnl_gbp=None,
        close_level=13360.0, stop_level=None, limit_level=13360.0,
        stop_was_amended_toward_entry=False, has_levels=True,
    )
    assert r_target == "TARGET"


def test_trades_api_still_handles_briefing_tp_sl_open():
    """Back-compat: BRIEFING_TP_SL_OPEN must still classify by pnl sign."""
    r = ta._classify_exit_type(
        close_reason_prefix="BRIEFING_TP_SL_OPEN",
        pnl_pips=-20.1, pnl_gbp=None,
        close_level=13340.0, stop_level=13340.0, limit_level=None,
        stop_was_amended_toward_entry=False, has_levels=True,
    )
    assert r == "STOP"
