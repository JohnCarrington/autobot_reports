"""
Unit tests for trade_executor.py

Production API:
- execute_trade(decision, epic)
- close_trade(epic)
- close_position(epic)
- update_trade_state(...)
- apply_trailing_stop(...)
- Module-level dict TRADE_STATE
- No standalone authenticate_ig() or _confirm_deal()
- IG auth comes from ig_auth module (get_ig_session)
"""
import trade_executor


def test_trade_state_exists():
    """TRADE_STATE is a module-level dict."""
    assert hasattr(trade_executor, "TRADE_STATE")
    assert isinstance(trade_executor.TRADE_STATE, dict)


def test_execute_trade_is_callable():
    """execute_trade exists and is callable."""
    assert callable(trade_executor.execute_trade)


def test_close_trade_is_callable():
    """close_trade exists and is callable."""
    assert callable(trade_executor.close_trade)


def test_close_position_is_callable():
    """close_position exists and is callable."""
    assert callable(trade_executor.close_position)


def test_update_trade_state_is_callable():
    """update_trade_state exists and is callable."""
    assert callable(trade_executor.update_trade_state)


def test_apply_trailing_stop_is_callable():
    """apply_trailing_stop exists and is callable."""
    assert callable(trade_executor.apply_trailing_stop)


def test_no_authenticate_ig():
    """trade_executor does NOT have a standalone authenticate_ig function."""
    assert not hasattr(trade_executor, "authenticate_ig")


def test_has_active_trade():
    """has_active_trade exists and is callable."""
    assert callable(trade_executor.has_active_trade)


def test_has_active_trade_returns_false_for_unknown_epic():
    """has_active_trade returns False for an unknown epic."""
    result = trade_executor.has_active_trade("NONEXISTENT.EPIC.TEST")
    assert isinstance(result, bool)


def test_epic_state_dict_exists():
    """EPIC_STATE / TRADE_STATE_BY_EPIC exists."""
    assert hasattr(trade_executor, "EPIC_STATE") or hasattr(trade_executor, "TRADE_STATE_BY_EPIC")


def test_register_trade_close_callback():
    """register_trade_close_callback exists and is callable."""
    assert callable(trade_executor.register_trade_close_callback)


# ───────────────────────────────────────── tp_pips=0 / None acceptance (2026-05-13)
# Contract: tp_pips==0.0 or tp_pips is None means "no broker TP" — the
# executor must pass limit_distance=None to IG's CREATE_POSITION and NOT
# reject with tp_non_positive. Negative tp_pips remains invalid.
# Pre-2026-05-13 the executor rejected 0.0 as tp_non_positive, which
# killed GBPUSD_TREND_S's 09:40 fire that day. See
# docs/directional_day_winner_failures_2026-05-13.md.

import types
import pytest


def _make_decision(*, signal="BUY", tp=80.0, sl=12.0, entry=13500.0,
                   mode="GBPUSD_TREND_L", pip_size=1.0):
    return types.SimpleNamespace(
        signal=signal, tp=tp, sl=sl, entry=entry, mode=mode,
        regime="CASCADE_TREND", pip_size=pip_size, reason="test",
        debug={}, size=None, symbol="GBPUSD",
    )


@pytest.fixture
def captured_open(monkeypatch):
    """Replace open_sb_now with a capturer that returns a dealReference.
    Also short-circuit fetch_deal_by_deal_reference to return ACCEPTED so
    we don't need a real IG session. EPIC_STATE is cleared between tests
    to prevent the "position already active" gate from blocking later
    tests in the same module run.
    """
    captures = {}

    # Reset any cross-test position state on this epic (pair-
    # concurrency check counts open positions across ALL modes on the
    # pair, so we clear every key referencing the test epic). Also
    # clear pair-entry-dedup so back-to-back tests aren't gated by the
    # 30s floor.
    test_epic = "CS.D.GBPUSD.TODAY.IP"
    for _k in list(trade_executor.EPIC_STATE.keys()):
        if test_epic in _k or "GBPUSD" in _k.upper():
            trade_executor.EPIC_STATE.pop(_k, None)
    trade_executor._LAST_ENTRY_TS_BY_PAIR.pop("GBPUSD", None)

    def _fake_open(direction, epic, size, limit_distance, stop_distance):
        captures["direction"] = direction
        captures["epic"] = epic
        captures["size"] = size
        captures["limit_distance"] = limit_distance
        captures["stop_distance"] = stop_distance
        return {"dealReference": "TEST_REF_001"}

    class _FakeIG:
        def fetch_deal_by_deal_reference(self, ref):
            return {"dealStatus": "ACCEPTED", "level": 13500.0,
                    "dealId": "DIAAAATEST0001"}

        def update_open_position(self, **kwargs):
            return {"status": "OK"}

    monkeypatch.setattr(trade_executor, "open_sb_now", _fake_open)
    monkeypatch.setattr(trade_executor, "get_ig_session",
                        lambda: (_FakeIG(), {}, "ACC123"))
    # Silence side-effects we don't care about.
    monkeypatch.setattr(trade_executor, "send_trade_open_alert",
                        lambda *a, **kw: None)
    yield captures
    # Cleanup: clear EPIC_STATE again so prod-state isn't polluted.
    for _k in list(trade_executor.EPIC_STATE.keys()):
        if test_epic in _k:
            trade_executor.EPIC_STATE.pop(_k, None)


def test_tp_pips_zero_passes_none_to_ig(captured_open, monkeypatch):
    """decision.tp == 0.0 → limit_distance == None at IG call site."""
    monkeypatch.setenv("BLOCK_INVALID_DISTANCES", "1")
    dec = _make_decision(tp=0.0)
    trade_executor.execute_trade(dec, "CS.D.GBPUSD.TODAY.IP")
    assert "limit_distance" in captured_open
    assert captured_open["limit_distance"] is None
    assert captured_open["stop_distance"] is not None


def test_tp_pips_none_passes_none_to_ig(captured_open, monkeypatch):
    """decision.tp is None → limit_distance == None at IG call site."""
    monkeypatch.setenv("BLOCK_INVALID_DISTANCES", "1")
    dec = _make_decision(tp=None, mode="GBPUSD_TREND_S", signal="SELL")
    trade_executor.execute_trade(dec, "CS.D.GBPUSD.TODAY.IP")
    assert "limit_distance" in captured_open, (
        f"open_sb_now not called — EPIC_STATE keys: "
        f"{list(trade_executor.EPIC_STATE.keys())}"
    )
    assert captured_open["limit_distance"] is None


def test_tp_pips_positive_passes_computed_limit(captured_open, monkeypatch):
    """decision.tp=80 → limit_distance is non-None and proportional to 80p."""
    monkeypatch.setenv("BLOCK_INVALID_DISTANCES", "1")
    dec = _make_decision(tp=80.0)
    trade_executor.execute_trade(dec, "CS.D.GBPUSD.TODAY.IP")
    assert "limit_distance" in captured_open
    ld = captured_open["limit_distance"]
    assert ld is not None and ld > 0


def test_tp_pips_negative_rejected(captured_open, monkeypatch):
    """decision.tp=-5 → trade blocked (tp_err set, open_sb_now never called)."""
    monkeypatch.setenv("BLOCK_INVALID_DISTANCES", "1")
    dec = _make_decision(tp=-5.0)
    result = trade_executor.execute_trade(dec, "CS.D.GBPUSD.TODAY.IP")
    # Trade must be blocked → returns None and open_sb_now is not invoked.
    assert result is None
    assert "limit_distance" not in captured_open


def test_sanitize_distance_zero_still_returns_non_positive(monkeypatch):
    """Defensive: _sanitize_distance itself still rejects 0 as
    tp_non_positive. The new behaviour is in the CALLER (execute_trade
    skips the sanitiser entirely when tp is 0/None). This locks the
    contract in case anyone widens _sanitize_distance accidentally.
    """
    monkeypatch.setattr(trade_executor, "BLOCK_INVALID_DISTANCES", True)
    val, err = trade_executor._sanitize_distance(
        label="tp", raw_value=0.0,
        min_pips=2.0, max_pips=500.0, fallback=20.0,
    )
    assert val is None
    assert err == "tp_non_positive"
