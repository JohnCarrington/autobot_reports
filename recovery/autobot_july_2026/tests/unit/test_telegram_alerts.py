"""
Unit tests for telegram_alerts.py

Production API:
- NO TelegramBot class. Only module-level functions:
  - send_telegram_message(message, parse_mode="HTML")
  - send(message) (alias)
  - send_trade_open_alert(epic, direction, size, entry, sl, tp, reason="", mode="")
  - send_trade_close_alert(epic, ...)
  - send_partial_exit_alert(epic, pct, pnl_pips, reason="")
  - send_status_update(text)
  - send_error_alert(text)
  - send_daily_summary(text)
  - send_heartbeat(text=...)
  - send_bot_online_alert()
- Module reads TELEGRAM_TOKEN and TELEGRAM_CHAT_ID from env at import time.
- Raises ValueError (not EnvironmentError) if env vars missing.
"""
import pytest
import importlib


@pytest.fixture(autouse=True)
def telegram_env(monkeypatch):
    monkeypatch.setenv("TELEGRAM_TOKEN", "dummy-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "123456")
    import telegram_alerts
    importlib.reload(telegram_alerts)
    return telegram_alerts


def test_no_telegram_bot_class(telegram_env):
    """telegram_alerts has NO TelegramBot class."""
    assert not hasattr(telegram_env, "TelegramBot")


def test_has_module_level_functions(telegram_env):
    """All expected module-level functions exist."""
    for fn_name in [
        "send_telegram_message",
        "send",
        "send_trade_open_alert",
        "send_trade_close_alert",
        "send_partial_exit_alert",
        "send_status_update",
        "send_error_alert",
        "send_daily_summary",
        "send_heartbeat",
        "send_bot_online_alert",
    ]:
        assert hasattr(telegram_env, fn_name), f"Missing function: {fn_name}"
        assert callable(getattr(telegram_env, fn_name))


def test_import_raises_if_env_missing(monkeypatch):
    monkeypatch.delenv("TELEGRAM_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    # Prevent _ensure_env_loaded from re-reading the .env file
    monkeypatch.setattr("dotenv.load_dotenv", lambda *a, **kw: None)
    import telegram_alerts
    with pytest.raises(ValueError):
        importlib.reload(telegram_alerts)


def test_send_telegram_message_payload(monkeypatch, telegram_env):
    captured = {}

    def fake_post(url, json=None, timeout=None, **kwargs):
        captured["url"] = url
        captured["json"] = json

        class Resp:
            status_code = 200
            text = "OK"
        return Resp()

    monkeypatch.setattr(telegram_env.requests, "post", fake_post)
    telegram_env.send_telegram_message("hello world")
    assert "dummy-token" in captured["url"]
    assert captured["json"]["chat_id"] == "123456"
    assert captured["json"]["text"] == "hello world"
    assert captured["json"]["parse_mode"] == "HTML"
    assert captured["json"]["disable_web_page_preview"] is True


def test_send_telegram_message_custom_parse(monkeypatch, telegram_env):
    captured = {}

    def fake_post(url, json=None, timeout=None, **kwargs):
        captured["json"] = json

        class Resp:
            status_code = 200
            text = "OK"
        return Resp()

    monkeypatch.setattr(telegram_env.requests, "post", fake_post)
    telegram_env.send_telegram_message("msg", parse_mode="Markdown")
    assert captured["json"]["parse_mode"] == "Markdown"


def test_send_alias(monkeypatch, telegram_env):
    called = {}

    def fake_post(url, json=None, timeout=None, **kwargs):
        called["json"] = json

        class Resp:
            status_code = 200
            text = "OK"
        return Resp()

    monkeypatch.setattr(telegram_env.requests, "post", fake_post)
    telegram_env.send("alias test")
    assert "alias test" in called["json"]["text"]


def test_send_trade_open_alert(monkeypatch, telegram_env):
    captured = {}

    def fake_post(url, json=None, timeout=None, **kwargs):
        captured["text"] = json["text"]

        class Resp:
            status_code = 200
            text = "OK"
        return Resp()

    monkeypatch.setattr(telegram_env.requests, "post", fake_post)
    telegram_env.send_trade_open_alert("EURUSD", "BUY", 1.5, 1.23456, 12.0, 30.0)
    msg = captured["text"]
    assert "EURUSD" in msg
    assert "BUY" in msg


def test_send_trade_close_alert(monkeypatch, telegram_env):
    captured = {}

    def fake_post(url, json=None, timeout=None, **kwargs):
        captured["text"] = json["text"]

        class Resp:
            status_code = 200
            text = "OK"
        return Resp()

    monkeypatch.setattr(telegram_env.requests, "post", fake_post)
    telegram_env.send_trade_close_alert("EURUSD", "BUY", 1.2000, 1.2100, 10.0)
    msg = captured["text"]
    assert "EURUSD" in msg
    assert "CLOSED" in msg


def test_send_partial_exit_alert(monkeypatch, telegram_env):
    captured = {}

    def fake_post(url, json=None, timeout=None, **kwargs):
        captured["text"] = json["text"]

        class Resp:
            status_code = 200
            text = "OK"
        return Resp()

    monkeypatch.setattr(telegram_env.requests, "post", fake_post)
    telegram_env.send_partial_exit_alert("EURUSD", 50, 10.5, reason="TP1 hit")
    msg = captured["text"]
    assert "EURUSD" in msg
    assert "PARTIAL" in msg


def test_send_status_update(monkeypatch, telegram_env):
    captured = {}

    def fake_post(url, json=None, timeout=None, **kwargs):
        captured["text"] = json["text"]

        class Resp:
            status_code = 200
            text = "OK"
        return Resp()

    monkeypatch.setattr(telegram_env.requests, "post", fake_post)
    telegram_env.send_status_update("all good")
    assert "all good" in captured["text"]


def test_send_error_alert(monkeypatch, telegram_env):
    captured = {}

    def fake_post(url, json=None, timeout=None, **kwargs):
        captured["text"] = json["text"]

        class Resp:
            status_code = 200
            text = "OK"
        return Resp()

    monkeypatch.setattr(telegram_env.requests, "post", fake_post)
    telegram_env.send_error_alert("something broke")
    assert "something broke" in captured["text"]


def test_send_daily_summary(monkeypatch, telegram_env):
    captured = {}

    def fake_post(url, json=None, timeout=None, **kwargs):
        captured["text"] = json["text"]

        class Resp:
            status_code = 200
            text = "OK"
        return Resp()

    monkeypatch.setattr(telegram_env.requests, "post", fake_post)
    telegram_env.send_daily_summary("PnL: +50 pips")
    assert "PnL: +50 pips" in captured["text"]


def test_send_heartbeat(monkeypatch, telegram_env):
    captured = {}

    def fake_post(url, json=None, timeout=None, **kwargs):
        captured["text"] = json["text"]

        class Resp:
            status_code = 200
            text = "OK"
        return Resp()

    monkeypatch.setattr(telegram_env.requests, "post", fake_post)
    telegram_env.send_heartbeat()
    assert "Heartbeat" in captured["text"]


def test_send_bot_online_alert(monkeypatch, telegram_env):
    captured = {}

    def fake_post(url, json=None, timeout=None, **kwargs):
        captured["text"] = json["text"]

        class Resp:
            status_code = 200
            text = "OK"
        return Resp()

    monkeypatch.setattr(telegram_env.requests, "post", fake_post)
    telegram_env.send_bot_online_alert()
    assert "online" in captured["text"]


# ---------------------------------------------------------------------------
# ALERT_HOST_LABEL — per-host prefix so operator can attribute messages when
# both droplets trade the same IG account with separate bots.
# ---------------------------------------------------------------------------


def _reload_with_label(monkeypatch, label_value):
    """Reload telegram_alerts with the given ALERT_HOST_LABEL env value.

    Passing None deletes the env var to exercise the unset path.
    """
    monkeypatch.setenv("TELEGRAM_TOKEN", "dummy-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "123456")
    if label_value is None:
        monkeypatch.delenv("ALERT_HOST_LABEL", raising=False)
    else:
        monkeypatch.setenv("ALERT_HOST_LABEL", label_value)
    import telegram_alerts
    importlib.reload(telegram_alerts)
    return telegram_alerts


def test_alert_host_label_prepended(monkeypatch):
    tg = _reload_with_label(monkeypatch, "HOST_A")
    captured = {}

    def fake_post(url, json=None, timeout=None, **kwargs):
        captured["json"] = json

        class Resp:
            status_code = 200
            text = "OK"
        return Resp()

    monkeypatch.setattr(tg.requests, "post", fake_post)
    tg._do_send_blocking("hello world")
    assert captured["json"]["text"] == "[HOST_A] hello world"


def test_alert_host_label_unset_byte_identical(monkeypatch):
    tg = _reload_with_label(monkeypatch, None)
    captured = {}

    def fake_post(url, json=None, timeout=None, **kwargs):
        captured["json"] = json

        class Resp:
            status_code = 200
            text = "OK"
        return Resp()

    monkeypatch.setattr(tg.requests, "post", fake_post)
    tg._do_send_blocking("hello world")
    # Byte-identical to pre-change payload: text field untouched.
    assert captured["json"]["text"] == "hello world"

    # Empty-string label also produces no prefix.
    tg2 = _reload_with_label(monkeypatch, "")
    captured2 = {}

    def fake_post2(url, json=None, timeout=None, **kwargs):
        captured2["json"] = json

        class Resp:
            status_code = 200
            text = "OK"
        return Resp()

    monkeypatch.setattr(tg2.requests, "post", fake_post2)
    tg2._do_send_blocking("hello world")
    assert captured2["json"]["text"] == "hello world"


def test_alert_host_label_html_escaped(monkeypatch):
    # A label containing HTML-special characters must not break HTML parse
    # mode. Escaped once at module load; brackets themselves are safe.
    tg = _reload_with_label(monkeypatch, "<host>&A")
    captured = {}

    def fake_post(url, json=None, timeout=None, **kwargs):
        captured["json"] = json

        class Resp:
            status_code = 200
            text = "OK"
        return Resp()

    monkeypatch.setattr(tg.requests, "post", fake_post)
    tg._do_send_blocking("hello world")
    text = captured["json"]["text"]
    assert text.startswith("[&lt;host&gt;&amp;A]")
    # Ensure the raw unescaped characters are not present anywhere in the
    # prefix — a Telegram HTML parser would reject them.
    assert "<host>" not in text
    assert "&A" not in text  # bare & would be caught by parser
    assert text.endswith(" hello world")


def test_alert_host_label_inline_fallback_path(monkeypatch):
    """The atexit-drained path (executor is None) must also apply the prefix.

    send_telegram_message falls back to inline _do_send_blocking when
    _get_executor() returns None. Simulate that state and assert.
    """
    tg = _reload_with_label(monkeypatch, "HOST_B")

    # Force the fallback path: pretend the executor has been drained.
    monkeypatch.setattr(tg, "_executor_drained", True)
    monkeypatch.setattr(tg, "_executor", None)

    captured = {}

    def fake_post(url, json=None, timeout=None, **kwargs):
        captured["json"] = json

        class Resp:
            status_code = 200
            text = "OK"
        return Resp()

    monkeypatch.setattr(tg.requests, "post", fake_post)
    # Sanity: _get_executor now returns None so send_telegram_message will
    # invoke _do_send_blocking inline on the caller thread.
    assert tg._get_executor() is None
    tg.send_telegram_message("payload")
    assert captured["json"]["text"] == "[HOST_B] payload"
