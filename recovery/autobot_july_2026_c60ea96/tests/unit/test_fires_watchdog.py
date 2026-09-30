"""Tests for scripts/fires_watchdog.py — ITEM 3."""

from __future__ import annotations

import importlib.util
import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

SCRIPT_PATH = Path("/opt/tradingbot/scripts/fires_watchdog.py")


def _load_module(monkeypatch, tmp_path, *, signal_log=None, log_file=None,
                 min_avg=None, trail_days=None):
    if min_avg is not None:
        monkeypatch.setenv("FIRES_WATCHDOG_MIN_AVG", str(min_avg))
    if trail_days is not None:
        monkeypatch.setenv("FIRES_WATCHDOG_TRAIL_DAYS", str(trail_days))
    spec = importlib.util.spec_from_file_location(
        "fires_watchdog_under_test", str(SCRIPT_PATH)
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    if signal_log is not None:
        monkeypatch.setattr(mod, "SIGNAL_LOG", Path(signal_log))
    if log_file is not None:
        monkeypatch.setattr(mod, "LOG_FILE", Path(log_file))
    for h in list(logging.getLogger("fires_watchdog").handlers):
        logging.getLogger("fires_watchdog").removeHandler(h)
    return mod


def _write_signal_log(path: Path, rows: list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")


def _fill(strategy: str, day: str, hour: int = 10) -> dict:
    ts = f"{day}T{hour:02d}:00:00Z"
    return {
        "id": f"{strategy}-{day}-{hour}",
        "strategy": strategy,
        "timestamp_open": ts,
        "pair": "GBPUSD",
    }


def test_digest_includes_5day_avg_zero_today(monkeypatch, tmp_path):
    # Reference "today" = Monday 2026-07-20; trailing weekdays = last 10 M-F.
    today = datetime(2026, 7, 20, 17, 30, tzinfo=timezone.utc)
    class _FakeDT(datetime):
        @classmethod
        def now(cls, tz=None):
            return today

    sig = tmp_path / "signal_log.jsonl"
    # 5 fills/day on trailing weekdays for BB_BOUNCE; today = 0
    rows = []
    trail_start = today - timedelta(days=1)
    d = trail_start
    while d > today - timedelta(days=25):
        if d.weekday() < 5:  # weekday
            iso = d.date().isoformat()
            for h in range(5):
                rows.append(_fill("BB_BOUNCE", iso, hour=8 + h))
        d = d - timedelta(days=1)
    # A low-avg strategy that should not fire (2/day)
    d = trail_start
    while d > today - timedelta(days=25):
        if d.weekday() < 5:
            iso = d.date().isoformat()
            for h in range(2):
                rows.append(_fill("EMA_PULLBACK", iso, hour=10 + h))
        d = d - timedelta(days=1)
    _write_signal_log(sig, rows)

    mod = _load_module(monkeypatch, tmp_path, signal_log=sig,
                       log_file=tmp_path / "logs" / "fires_watchdog.log",
                       min_avg=3.0, trail_days=10)
    monkeypatch.setattr(mod, "datetime", _FakeDT)
    monkeypatch.setattr(mod, "_discover_enabled_strategies",
                        lambda: (None, "undeterminable"))

    sent = []
    monkeypatch.setattr(mod, "_send_telegram",
                        lambda text, log: sent.append(text))
    assert mod.main() == 0
    assert len(sent) == 1, sent
    msg = sent[0]
    assert "BB_BOUNCE" in msg
    assert "EMA_PULLBACK" not in msg  # under the min-avg bar
    assert "avg 5.0/day" in msg or "avg 5" in msg


def test_low_avg_excluded_when_zero_today(monkeypatch, tmp_path):
    today = datetime(2026, 7, 20, 17, 30, tzinfo=timezone.utc)
    class _FakeDT(datetime):
        @classmethod
        def now(cls, tz=None):
            return today

    sig = tmp_path / "signal_log.jsonl"
    rows = []
    d = today - timedelta(days=1)
    while d > today - timedelta(days=25):
        if d.weekday() < 5:
            iso = d.date().isoformat()
            for h in range(2):  # 2/day avg
                rows.append(_fill("PHASE2_SCALP", iso, hour=10 + h))
        d = d - timedelta(days=1)
    _write_signal_log(sig, rows)

    mod = _load_module(monkeypatch, tmp_path, signal_log=sig,
                       log_file=tmp_path / "logs" / "fires_watchdog.log",
                       min_avg=3.0, trail_days=10)
    monkeypatch.setattr(mod, "datetime", _FakeDT)
    monkeypatch.setattr(mod, "_discover_enabled_strategies",
                        lambda: (None, "undeterminable"))
    # Disable the shadow ledger side of the run so this test stays focused
    # on the silent-digest logic. Ledger has its own dedicated tests.
    monkeypatch.setattr(mod, "_build_shadow_ledger",
                        lambda *a, **kw: ["SHADOW LEDGER"])
    sent = []
    monkeypatch.setattr(mod, "_send_telegram",
                        lambda text, log: sent.append(text))
    assert mod.main() == 0
    # 2/day is below min_avg=3.0 — no silent-today content anywhere.
    assert all("SILENT TODAY" not in m for m in sent)


def test_weekend_rows_excluded_from_average(monkeypatch, tmp_path):
    today = datetime(2026, 7, 20, 17, 30, tzinfo=timezone.utc)
    class _FakeDT(datetime):
        @classmethod
        def now(cls, tz=None):
            return today
    sig = tmp_path / "signal_log.jsonl"
    rows = []
    # Weekdays: 0 fills.
    # Weekends: 100 fills/day of BB_BOUNCE. These MUST NOT influence
    # the trailing average (which only considers weekdays).
    d = today - timedelta(days=1)
    while d > today - timedelta(days=25):
        if d.weekday() >= 5:  # Sat/Sun
            iso = d.date().isoformat()
            for h in range(100):
                rows.append(_fill("BB_BOUNCE", iso, hour=(h % 12) + 6))
        d = d - timedelta(days=1)
    _write_signal_log(sig, rows)

    mod = _load_module(monkeypatch, tmp_path, signal_log=sig,
                       log_file=tmp_path / "logs" / "fires_watchdog.log",
                       min_avg=3.0, trail_days=10)
    monkeypatch.setattr(mod, "datetime", _FakeDT)
    monkeypatch.setattr(mod, "_discover_enabled_strategies",
                        lambda: (None, "undeterminable"))
    monkeypatch.setattr(mod, "_build_shadow_ledger",
                        lambda *a, **kw: ["SHADOW LEDGER"])
    sent = []
    monkeypatch.setattr(mod, "_send_telegram",
                        lambda text, log: sent.append(text))
    assert mod.main() == 0
    # No weekday history at all => average across weekdays == 0
    # so the strategy is NOT included in the silent digest.
    assert all("SILENT TODAY" not in m for m in sent)


def test_estate_wide_zero_days_excluded_from_average(monkeypatch, tmp_path):
    today = datetime(2026, 7, 20, 17, 30, tzinfo=timezone.utc)
    class _FakeDT(datetime):
        @classmethod
        def now(cls, tz=None):
            return today

    sig = tmp_path / "signal_log.jsonl"
    rows = []
    # 3 weekdays with 10 fills each; 7 weekdays with 0 fills (outage).
    # If we averaged over all 10 -> 3.0/day (right at bar). Excluding
    # the outage days -> 10.0/day (well above). Test asserts outage
    # days are excluded from the divisor.
    weekdays = []
    d = today - timedelta(days=1)
    while len(weekdays) < 10:
        if d.weekday() < 5:
            weekdays.append(d)
        d = d - timedelta(days=1)
    fill_days = weekdays[:3]
    for wd in fill_days:
        iso = wd.date().isoformat()
        for h in range(10):
            rows.append(_fill("BB_BOUNCE", iso, hour=(h % 12) + 6))
    _write_signal_log(sig, rows)

    mod = _load_module(monkeypatch, tmp_path, signal_log=sig,
                       log_file=tmp_path / "logs" / "fires_watchdog.log",
                       min_avg=9.0, trail_days=10)
    monkeypatch.setattr(mod, "datetime", _FakeDT)
    monkeypatch.setattr(mod, "_discover_enabled_strategies",
                        lambda: (None, "undeterminable"))
    sent = []
    monkeypatch.setattr(mod, "_send_telegram",
                        lambda text, log: sent.append(text))
    assert mod.main() == 0
    assert len(sent) == 1
    assert "BB_BOUNCE" in sent[0]
    assert "avg 10.0/day" in sent[0] or "avg 10" in sent[0]


def test_footer_note_when_registry_undeterminable(monkeypatch, tmp_path):
    today = datetime(2026, 7, 20, 17, 30, tzinfo=timezone.utc)
    class _FakeDT(datetime):
        @classmethod
        def now(cls, tz=None):
            return today
    sig = tmp_path / "signal_log.jsonl"
    rows = []
    d = today - timedelta(days=1)
    while d > today - timedelta(days=25):
        if d.weekday() < 5:
            iso = d.date().isoformat()
            for h in range(5):
                rows.append(_fill("BB_BOUNCE", iso, hour=8 + h))
        d = d - timedelta(days=1)
    _write_signal_log(sig, rows)

    mod = _load_module(monkeypatch, tmp_path, signal_log=sig,
                       log_file=tmp_path / "logs" / "fires_watchdog.log",
                       min_avg=3.0, trail_days=10)
    monkeypatch.setattr(mod, "datetime", _FakeDT)
    monkeypatch.setattr(mod, "_discover_enabled_strategies",
                        lambda: (None, "undeterminable"))
    sent = []
    monkeypatch.setattr(mod, "_send_telegram",
                        lambda text, log: sent.append(text))
    assert mod.main() == 0
    assert "undeterminable" in sent[0].lower()


def test_registry_line_regex_matches_expected():
    """Confirm the enabled= line pattern would parse if someone emits it."""
    import re
    from importlib.util import spec_from_file_location, module_from_spec
    spec = spec_from_file_location("_fw", str(SCRIPT_PATH))
    mod = module_from_spec(spec)
    spec.loader.exec_module(mod)
    m = mod._REGISTRY_LINE_RE.search(
        "2026-07-25 10:00:00 [INFO] [STRATEGY-REGISTRY] enabled=[BB_BOUNCE,EMA_PULLBACK]"
    )
    assert m
    assert m.group(1).split(",") == ["BB_BOUNCE", "EMA_PULLBACK"]


def test_no_alert_when_all_strategies_have_fills(monkeypatch, tmp_path):
    today = datetime(2026, 7, 20, 17, 30, tzinfo=timezone.utc)
    class _FakeDT(datetime):
        @classmethod
        def now(cls, tz=None):
            return today
    sig = tmp_path / "signal_log.jsonl"
    rows = []
    # 5/day trailing + 3 fills today.
    d = today - timedelta(days=1)
    while d > today - timedelta(days=25):
        if d.weekday() < 5:
            iso = d.date().isoformat()
            for h in range(5):
                rows.append(_fill("BB_BOUNCE", iso, hour=8 + h))
        d = d - timedelta(days=1)
    for h in range(3):
        rows.append(_fill("BB_BOUNCE", today.date().isoformat(), hour=8 + h))
    _write_signal_log(sig, rows)

    mod = _load_module(monkeypatch, tmp_path, signal_log=sig,
                       log_file=tmp_path / "logs" / "fires_watchdog.log",
                       min_avg=3.0, trail_days=10)
    monkeypatch.setattr(mod, "datetime", _FakeDT)
    monkeypatch.setattr(mod, "_discover_enabled_strategies",
                        lambda: (None, "undeterminable"))
    monkeypatch.setattr(mod, "_build_shadow_ledger",
                        lambda *a, **kw: ["SHADOW LEDGER"])
    sent = []
    monkeypatch.setattr(mod, "_send_telegram",
                        lambda text, log: sent.append(text))
    assert mod.main() == 0
    assert all("SILENT TODAY" not in m for m in sent)
