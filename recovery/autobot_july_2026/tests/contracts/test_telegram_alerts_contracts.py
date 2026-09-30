import logging
import importlib
import inspect
import pytest


@pytest.fixture
def telegram_env(monkeypatch):
    monkeypatch.setenv("TELEGRAM_TOKEN", "dummy-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "123456")
    import telegram_alerts
    importlib.reload(telegram_alerts)
    return telegram_alerts


def test_telegram_alerts_imports_successful_and_logger(telegram_env):
    assert isinstance(telegram_env.logger, logging.Logger)
    assert telegram_env.logger.name == "AutoBot"


def test_telegram_alerts_env_constants_present(telegram_env):
    assert telegram_env.TELEGRAM_TOKEN == "dummy-token"
    assert telegram_env.TELEGRAM_CHAT_ID == "123456"


def test_telegram_alerts_no_class(telegram_env):
    """There is no TelegramBot class — only module-level functions."""
    assert not hasattr(telegram_env, "TelegramBot")


def test_telegram_alerts_module_functions_exist(telegram_env):
    """All public functions must exist and be callable at module level."""
    function_names = [
        "send_telegram_message", "send", "send_trade_open_alert",
        "send_trade_close_alert", "send_partial_exit_alert",
        "send_status_update", "send_error_alert", "send_daily_summary",
        "send_heartbeat", "send_bot_online_alert",
    ]
    for name in function_names:
        assert hasattr(telegram_env, name), f"Missing function {name}"
        assert callable(getattr(telegram_env, name)), f"{name} not callable"


def test_telegram_alerts_key_signatures(telegram_env):
    sig_send = inspect.signature(telegram_env.send_telegram_message)
    params = list(sig_send.parameters.keys())
    assert params[0] == "message"
    assert params[1] == "parse_mode"
    assert sig_send.parameters["parse_mode"].default == "HTML"

    sig_open = inspect.signature(telegram_env.send_trade_open_alert)
    assert "epic" in sig_open.parameters

    sig_partial = inspect.signature(telegram_env.send_partial_exit_alert)
    params_partial = list(sig_partial.parameters.keys())
    assert "epic" in params_partial
    assert "pct" in params_partial
    assert "pnl_pips" in params_partial

    sig_hb = inspect.signature(telegram_env.send_heartbeat)
    assert "text" in sig_hb.parameters

    sig_online = inspect.signature(telegram_env.send_bot_online_alert)
    assert len(sig_online.parameters) == 0
