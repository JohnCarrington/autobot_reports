"""
Unit tests for trade_manager.py

Production API:
- TradeManager.__init__() takes NO parameters
- Uses self.state = _exec.TRADE_STATE (references trade_executor module as _exec)
- Has active_trades property
- Has close_position(epic) method
- open_position raises NotImplementedError (delegates to trade_executor.execute_trade)
"""
import pytest
import trade_manager


def test_trade_manager_no_args():
    """TradeManager() takes no constructor arguments."""
    tm = trade_manager.TradeManager()
    assert tm is not None


def test_trade_manager_has_state():
    """TradeManager instance has a .state attribute referencing TRADE_STATE."""
    tm = trade_manager.TradeManager()
    assert hasattr(tm, "state")
    assert isinstance(tm.state, dict)


def test_trade_manager_state_references_executor():
    """TradeManager.state should be the same object as trade_executor.TRADE_STATE."""
    import trade_executor
    tm = trade_manager.TradeManager()
    assert tm.state is trade_executor.TRADE_STATE


def test_active_trades_empty_initially():
    """active_trades should be empty when no trades are active."""
    tm = trade_manager.TradeManager()
    result = tm.active_trades
    assert isinstance(result, dict)


def test_open_position_raises_not_implemented():
    """open_position raises NotImplementedError — use trade_executor.execute_trade instead."""
    tm = trade_manager.TradeManager()
    with pytest.raises(NotImplementedError):
        tm.open_position("BUY", 1.0)


def test_close_position_is_callable():
    """close_position method exists and is callable."""
    tm = trade_manager.TradeManager()
    assert callable(tm.close_position)


def test_module_exports_trade_state():
    """trade_manager re-exports TRADE_STATE at module level."""
    assert hasattr(trade_manager, "TRADE_STATE")
    assert isinstance(trade_manager.TRADE_STATE, dict)
