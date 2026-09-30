import inspect

import pytest
import trade_manager
from trade_manager import TradeManager


def test_trade_manager_imports_successful_and_class_present():
    """Module and TradeManager class should import successfully."""
    assert trade_manager is not None
    assert hasattr(trade_manager, "TradeManager")
    assert isinstance(TradeManager, type)


def test_trade_manager_init_signature():
    """TradeManager.__init__ takes NO parameters (no telegram kwarg)."""
    sig = inspect.signature(TradeManager.__init__)
    params = [p for p in sig.parameters.values() if p.name != "self"]
    assert len(params) == 0, f"Expected no params, got {[p.name for p in params]}"


@pytest.fixture
def tm():
    """Provide a TradeManager instance."""
    return TradeManager()


def test_trade_manager_has_state(tm):
    """TradeManager uses self.state which references trade_executor.TRADE_STATE."""
    assert hasattr(tm, "state")


def test_trade_manager_public_methods_exist(tm):
    """Public methods must exist and be callable."""
    expected_methods = [
        "open_position",
        "close_position",
        "monitor_positions",
    ]
    for name in expected_methods:
        assert hasattr(tm, name), f"TradeManager missing {name}"
        assert callable(getattr(tm, name)), f"{name} should be callable"


def test_trade_manager_method_signatures(tm):
    """Check key method signatures match production."""
    sig_open = inspect.signature(tm.open_position)
    params_open = list(sig_open.parameters.keys())
    assert "direction" in params_open
    assert "size" in params_open

    sig_close = inspect.signature(tm.close_position)
    params_close = list(sig_close.parameters.keys())
    assert "epic" in params_close

    sig_monitor = inspect.signature(tm.monitor_positions)
    params_mon = list(sig_monitor.parameters.keys())
    assert "epic" in params_mon
    assert "mid_price" in params_mon
