"""Tests for log_redaction — verify secrets never reach handler output."""

import io
import logging

import pytest

import log_redaction


@pytest.fixture
def isolated_root(monkeypatch):
    """Give each test its own root logger snapshot so state doesn't leak."""
    root = logging.getLogger()
    prior_handlers = list(root.handlers)
    prior_level = root.level
    prior_marker = getattr(root, log_redaction._INSTALLED_ATTR, None)
    for h in prior_handlers:
        root.removeHandler(h)
    if prior_marker is not None:
        delattr(root, log_redaction._INSTALLED_ATTR)
    for name in log_redaction._HTTP_LOGGERS:
        lg = logging.getLogger(name)
        lg.filters = []

    buf = io.StringIO()
    handler = logging.StreamHandler(buf)
    handler.setLevel(logging.DEBUG)
    root.setLevel(logging.DEBUG)
    root.addHandler(handler)

    yield root, buf

    root.removeHandler(handler)
    root.setLevel(prior_level)
    for h in prior_handlers:
        root.addHandler(h)
    marker = getattr(root, log_redaction._INSTALLED_ATTR, None)
    if marker is not None:
        delattr(root, log_redaction._INSTALLED_ATTR)
    if prior_marker is not None:
        setattr(root, log_redaction._INSTALLED_ATTR, prior_marker)


def test_filter_redacts_telegram_bot_token_in_url_path():
    flt = log_redaction.SecretRedactingFilter()
    record = logging.LogRecord(
        name="urllib3.connectionpool", level=logging.DEBUG,
        pathname=__file__, lineno=1,
        msg='%s://%s:%s "%s %s HTTP/%s" %s %s',
        args=("https", "api.telegram.org", 443, "POST",
              "/bot8723229559:AAHUzfkPrJRNQQsv87_R5GxbVCsJKViymoQ/sendMessage",
              "1.1", 200, 0),
        exc_info=None,
    )
    flt.filter(record)
    formatted = record.getMessage()
    assert "AAHUzfkPrJRNQQsv87_R5GxbVCsJKViymoQ" not in formatted
    assert "/bot8723229559:***/sendMessage" in formatted


def test_filter_redacts_anthropic_api_key():
    flt = log_redaction.SecretRedactingFilter()
    record = logging.LogRecord(
        name="anthropic", level=logging.DEBUG,
        pathname=__file__, lineno=1,
        msg="request headers include x-api-key sk-ant-api03-ABCDEFGHIJKLMNOPQRSTUVWXYZ_boom",
        args=None, exc_info=None,
    )
    flt.filter(record)
    assert "sk-ant-api03-ABCDEFGHIJKLMNOPQRSTUVWXYZ_boom" not in record.getMessage()
    assert "sk-ant-***" in record.getMessage()


def test_filter_redacts_sendgrid_api_key():
    flt = log_redaction.SecretRedactingFilter()
    record = logging.LogRecord(
        name="sendgrid", level=logging.DEBUG,
        pathname=__file__, lineno=1,
        msg="bearer SG.abcdef1234567890.xyz9876543210zyxwvutsrqponml_ABC",
        args=None, exc_info=None,
    )
    flt.filter(record)
    assert "SG.abcdef1234567890.xyz9876543210zyxwvutsrqponml_ABC" not in record.getMessage()
    assert "SG.***" in record.getMessage()


def test_filter_redacts_literal_ig_api_key():
    flt = log_redaction.SecretRedactingFilter(extra_literals=["f7ebABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"])
    record = logging.LogRecord(
        name="urllib3", level=logging.DEBUG,
        pathname=__file__, lineno=1,
        msg="X-IG-API-KEY: f7ebABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 in request",
        args=None, exc_info=None,
    )
    flt.filter(record)
    assert "f7ebABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789" not in record.getMessage()
    assert "***" in record.getMessage()


def test_filter_leaves_non_matching_records_untouched():
    flt = log_redaction.SecretRedactingFilter()
    record = logging.LogRecord(
        name="AutoBot", level=logging.INFO,
        pathname=__file__, lineno=1,
        msg="[TELEGRAM] atexit drain complete — %d messages submitted",
        args=(7,), exc_info=None,
    )
    flt.filter(record)
    assert record.getMessage() == "[TELEGRAM] atexit drain complete — 7 messages submitted"


def test_install_default_captures_urllib3_debug_output(isolated_root, monkeypatch):
    """End-to-end: urllib3-style DEBUG line goes through the installed filter
    on the child logger and never reaches the handler with token intact."""
    root, buf = isolated_root

    token = "AAHUzfkPrJRNQQsv87_R5GxbVCsJKViymoQ"
    monkeypatch.setenv("IG_API_KEY", "")
    log_redaction.install_default(root)

    u3 = logging.getLogger("urllib3.connectionpool")
    u3.setLevel(logging.DEBUG)
    u3.debug(
        '%s://%s:%s "%s %s HTTP/%s" %s %s',
        "https", "api.telegram.org", 443, "POST",
        f"/bot8723229559:{token}/sendMessage", "1.1", 400, 73,
    )

    output = buf.getvalue()
    assert token not in output, f"token leaked into log output: {output!r}"
    assert "/bot8723229559:***/sendMessage" in output


def test_install_default_is_idempotent(isolated_root):
    root, _buf = isolated_root
    a = log_redaction.install_default(root)
    b = log_redaction.install_default(root)
    assert a is b
    u3 = logging.getLogger("urllib3.connectionpool")
    assert sum(1 for f in u3.filters if f is a) == 1
