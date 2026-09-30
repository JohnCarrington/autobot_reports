import inspect
import logging
import trade_executor


def test_trade_executor_imports_successful():
    assert trade_executor is not None


def test_trade_executor_logger_exists():
    assert hasattr(trade_executor, "logger")
    assert isinstance(trade_executor.logger, logging.Logger)
    assert trade_executor.logger.name == "AutoBot"


def test_trade_executor_public_functions_exist():
    """The current public API has these functions."""
    expected = ["execute_trade", "close_trade", "close_position",
                "update_trade_state", "apply_trailing_stop"]
    for name in expected:
        assert hasattr(trade_executor, name), f"Missing {name}"
        assert callable(getattr(trade_executor, name)), f"{name} not callable"


def test_trade_executor_no_removed_api():
    """authenticate_ig and open_position are not standalone public functions."""
    assert not hasattr(trade_executor, "authenticate_ig")
    assert not hasattr(trade_executor, "open_position")


def test_trade_executor_function_signatures():
    sig_exec = inspect.signature(trade_executor.execute_trade)
    params_exec = list(sig_exec.parameters.keys())
    assert "decision" in params_exec
    assert "epic" in params_exec

    sig_close_trade = inspect.signature(trade_executor.close_trade)
    params_ct = list(sig_close_trade.parameters.keys())
    assert "epic" in params_ct

    sig_close_pos = inspect.signature(trade_executor.close_position)
    params_cp = list(sig_close_pos.parameters.keys())
    assert "epic" in params_cp

    sig_update = inspect.signature(trade_executor.update_trade_state)
    params_u = list(sig_update.parameters.keys())
    assert "epic" in params_u
    assert "mid_price" in params_u

    sig_trail = inspect.signature(trade_executor.apply_trailing_stop)
    params_t = list(sig_trail.parameters.keys())
    assert "epic" in params_t
    assert "mid_price" in params_t


def test_trade_executor_has_trade_state():
    """TRADE_STATE dict must be exposed for use by trade_manager."""
    assert hasattr(trade_executor, "TRADE_STATE")
    assert isinstance(trade_executor.TRADE_STATE, dict)
