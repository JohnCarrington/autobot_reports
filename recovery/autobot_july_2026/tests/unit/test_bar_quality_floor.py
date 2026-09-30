"""Tests for ITEM 2 — bar-quality floor in candle_builder."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest


@pytest.fixture
def cb(monkeypatch):
    """Pin bar-quality module state deterministically per test WITHOUT
    reloading candle_builder — reload would wipe _5M_CLOSE_CALLBACKS,
    which test_native_5m_source.test_candle_archive_callback_registered_after_import
    relies on."""
    monkeypatch.setenv("ALERT_HOST_LABEL", "TESTHOST")
    import candle_builder as _cb
    monkeypatch.setattr(_cb, "BAR_QUALITY_MIN_TICKS", 10)
    monkeypatch.setattr(_cb, "BAR_QUALITY_ALERT_CONSEC", 6)
    monkeypatch.setattr(_cb, "BAR_QUALITY_ALERT_COOLDOWN_MIN", 60.0)
    monkeypatch.setattr(_cb, "BAR_QUALITY_QUIET_UTC", "22-06")
    # Reset only the per-pair state dicts owned by this feature.
    _saved_consec = dict(_cb._bar_quality_consec)
    _saved_cool = dict(_cb._bar_quality_cooldown_until)
    _cb._bar_quality_consec.clear()
    _cb._bar_quality_cooldown_until.clear()
    yield _cb
    _cb._bar_quality_consec.clear()
    _cb._bar_quality_consec.update(_saved_consec)
    _cb._bar_quality_cooldown_until.clear()
    _cb._bar_quality_cooldown_until.update(_saved_cool)


def _mk_row(ticks, ts=None, high=1.10010, low=1.10000):
    return {
        "time": ts or datetime(2026, 7, 21, 10, 0, 0, tzinfo=timezone.utc),
        "open": (high + low) / 2,
        "high": high,
        "low": low,
        "close": (high + low) / 2,
        "tick_count": ticks,
    }


def test_five_starved_no_alert(cb, monkeypatch):
    sent = []
    monkeypatch.setattr(
        cb, "_try_send_bar_quality_alert",
        lambda sym, consec: sent.append((sym, consec)),
    )
    for i in range(5):
        cb._bar_quality_check("GBPUSD", _mk_row(2, ts=datetime(2026, 7, 21, 10, i * 5, tzinfo=timezone.utc)))
    assert sent == []
    assert cb._bar_quality_consec["GBPUSD"] == 5


def test_sixth_starved_fires_alert(cb, monkeypatch):
    sent = []
    monkeypatch.setattr(
        cb, "_try_send_bar_quality_alert",
        lambda sym, consec: sent.append((sym, consec)),
    )
    for i in range(6):
        cb._bar_quality_check("GBPUSD", _mk_row(1, ts=datetime(2026, 7, 21, 10, i * 5, tzinfo=timezone.utc)))
    assert sent == [("GBPUSD", 6)]
    # Post-alert: consec resets so the NEXT alert requires another 6.
    assert cb._bar_quality_consec["GBPUSD"] == 0


def test_seventh_starved_inside_cooldown_no_second_alert(cb, monkeypatch):
    sent = []
    monkeypatch.setattr(
        cb, "_try_send_bar_quality_alert",
        lambda sym, consec: sent.append((sym, consec)),
    )
    # Fire the first alert
    for i in range(6):
        cb._bar_quality_check("GBPUSD", _mk_row(1, ts=datetime(2026, 7, 21, 10, i * 5, tzinfo=timezone.utc)))
    # Cross the threshold again quickly — must be suppressed by cooldown
    for i in range(6):
        cb._bar_quality_check("GBPUSD", _mk_row(1, ts=datetime(2026, 7, 21, 11, i * 5, tzinfo=timezone.utc)))
    assert sent == [("GBPUSD", 6)]


def test_quiet_hours_bar_logs_only_no_alert(cb, monkeypatch):
    sent = []
    logs = []
    monkeypatch.setattr(
        cb, "_try_send_bar_quality_alert",
        lambda sym, consec: sent.append((sym, consec)),
    )
    # Attach a handler to capture warning logs
    class _H:
        def __init__(self):
            self.records = []
        def handle(self, record):
            self.records.append(record.getMessage())
        def createLock(self):
            self.lock = None
        def acquire(self):
            pass
        def release(self):
            pass
        def close(self):
            pass
        level = 0

    import logging
    handler = logging.Handler()
    handler.setLevel(logging.WARNING)
    handler.emit = lambda r: logs.append(r.getMessage())
    cb.logger.addHandler(handler)
    try:
        # 23:00 UTC is inside 22-06 quiet window
        for i in range(6):
            cb._bar_quality_check(
                "GBPUSD",
                _mk_row(1, ts=datetime(2026, 7, 21, 23, i * 5, tzinfo=timezone.utc)),
            )
    finally:
        cb.logger.removeHandler(handler)
    # No Telegram in quiet window
    assert sent == []
    # But per-bar WARNING log fired every starved bar
    assert sum("BAR-QUALITY" in m for m in logs) == 6


def test_weekend_fully_exempt(cb, monkeypatch):
    sent = []
    monkeypatch.setattr(
        cb, "_try_send_bar_quality_alert",
        lambda sym, consec: sent.append((sym, consec)),
    )
    # 2026-07-25 was a Saturday; force a weekend timestamp
    sat_noon = datetime(2026, 7, 25, 12, 0, 0, tzinfo=timezone.utc)
    assert sat_noon.weekday() == 5
    for i in range(6):
        cb._bar_quality_check("GBPUSD", _mk_row(1, ts=sat_noon + timedelta(minutes=5 * i)))
    assert sent == []


def test_alerter_raise_does_not_break_bar_close(cb, monkeypatch):
    def _boom(sym, consec):
        raise RuntimeError("simulated telegram outage")
    monkeypatch.setattr(cb, "_try_send_bar_quality_alert", _boom)
    # Should NOT raise despite alerter blowing up
    for i in range(6):
        cb._bar_quality_check(
            "GBPUSD",
            _mk_row(1, ts=datetime(2026, 7, 21, 10, i * 5, tzinfo=timezone.utc)),
        )
    # And the bar-quality state should still be sane
    assert "GBPUSD" in cb._bar_quality_consec


def test_healthy_bar_resets_consec(cb, monkeypatch):
    sent = []
    monkeypatch.setattr(
        cb, "_try_send_bar_quality_alert",
        lambda sym, consec: sent.append((sym, consec)),
    )
    for i in range(5):
        cb._bar_quality_check("GBPUSD", _mk_row(1, ts=datetime(2026, 7, 21, 10, i * 5, tzinfo=timezone.utc)))
    # Healthy bar clears the counter
    cb._bar_quality_check("GBPUSD", _mk_row(20, ts=datetime(2026, 7, 21, 10, 30, tzinfo=timezone.utc)))
    # Another 5 starved bars — still under threshold, no alert
    for i in range(5):
        cb._bar_quality_check("GBPUSD", _mk_row(1, ts=datetime(2026, 7, 21, 10, 35 + i * 5, tzinfo=timezone.utc)))
    assert sent == []
    assert cb._bar_quality_consec["GBPUSD"] == 5


def test_message_carries_variable_name_not_value(cb, monkeypatch):
    captured = {}
    def _capture(msg, parse_mode=""):
        captured["msg"] = msg
    class _tg:
        send_telegram_message = staticmethod(_capture)
    monkeypatch.setitem(__import__("sys").modules, "telegram_alerts", _tg)
    for i in range(6):
        cb._bar_quality_check("GBPUSD", _mk_row(1, ts=datetime(2026, 7, 21, 10, i * 5, tzinfo=timezone.utc)))
    assert "msg" in captured, captured
    msg = captured["msg"]
    # variable NAME must appear, not its numeric value
    assert "BAR_QUALITY_MIN_TICKS" in msg
    assert "10 ticks" not in msg  # value must not leak
    assert "[TESTHOST]" in msg
