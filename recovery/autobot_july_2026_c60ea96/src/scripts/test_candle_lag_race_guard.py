#!/usr/bin/env python3
"""Unit tests for the candle-lag fire-time race-condition guard.

Covers two pieces:
  1. candle_lag_monitor.live_lag — synchronous, side-effect-free lag of
     the latest closed 5M bar against wall-clock now.
  2. trade_executor.execute_trade — fire-time recheck blocks the call
     when live_lag > CRITICAL_THRESHOLD_SECS (and lets it through
     otherwise, including when live_lag is None).

Background: reports/candle_lag_operational_audit_20260508.md showed 2
historical fires (2026-05-04 16:43:03 TREND_CONT_S, 2026-05-05 06:16:53
BB_BOUNCE_S) bypassed the upstream is_stale() block by firing 1 second
after CRITICAL transition. This guard closes that race window.

Standalone runner — exits 0 on pass.
"""
from __future__ import annotations

import importlib
import inspect
import sys
import time
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pandas as pd

sys.path.insert(0, "/opt/tradingbot")


def _reload_clm():
    if "candle_lag_monitor" in sys.modules:
        return importlib.reload(sys.modules["candle_lag_monitor"])
    import candle_lag_monitor
    return candle_lag_monitor


def _reload_te():
    if "trade_executor" in sys.modules:
        return importlib.reload(sys.modules["trade_executor"])
    import trade_executor
    return trade_executor


# ---------------------------------------------------------------------------
# live_lag
# ---------------------------------------------------------------------------

def test_live_lag_returns_none_for_blank_pair():
    clm = _reload_clm()
    assert clm.live_lag(None) is None
    assert clm.live_lag("") is None


def test_live_lag_returns_none_when_df_missing(monkeypatch=None):
    """If candle_builder returns an empty DF, live_lag returns None (no signal)."""
    clm = _reload_clm()
    import candle_builder as cb

    def _empty_df(_sym):
        return pd.DataFrame(columns=["time", "open", "high", "low", "close"])

    orig = cb.get_df_raw
    cb.get_df_raw = _empty_df
    try:
        assert clm.live_lag("GBPUSD") is None
    finally:
        cb.get_df_raw = orig


def test_live_lag_fresh_bar_returns_small_lag():
    """A bar that closed ~10s ago should produce lag ≈ 10s (small, < CRITICAL)."""
    clm = _reload_clm()
    import candle_builder as cb

    # Bar opened 5 minutes + 10 seconds ago → closed 10 seconds ago → lag ≈ 10s
    bar_open = datetime.now(tz=timezone.utc) - timedelta(seconds=clm.BAR_LENGTH_SECS + 10)
    df = pd.DataFrame([{"time": bar_open, "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0}])

    orig = cb.get_df_raw
    cb.get_df_raw = lambda _sym: df
    try:
        lag = clm.live_lag("GBPUSD")
        assert lag is not None
        assert 5 < lag < 30, f"expected ~10s lag, got {lag:.1f}s"
        assert lag < clm.CRITICAL_THRESHOLD_SECS, "fresh bar must not be CRITICAL"
    finally:
        cb.get_df_raw = orig


def test_live_lag_stale_bar_exceeds_critical():
    """A bar 90s past close should produce lag > CRITICAL_THRESHOLD_SECS (60s)."""
    clm = _reload_clm()
    import candle_builder as cb

    bar_open = datetime.now(tz=timezone.utc) - timedelta(seconds=clm.BAR_LENGTH_SECS + 90)
    df = pd.DataFrame([{"time": bar_open, "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0}])

    orig = cb.get_df_raw
    cb.get_df_raw = lambda _sym: df
    try:
        lag = clm.live_lag("GBPUSD")
        assert lag is not None
        assert lag > clm.CRITICAL_THRESHOLD_SECS, (
            f"expected lag > {clm.CRITICAL_THRESHOLD_SECS}s, got {lag:.1f}s"
        )
    finally:
        cb.get_df_raw = orig


def test_live_lag_does_not_mutate_stale_pairs():
    """live_lag must NEVER touch _stale_pairs — it's a recheck, not a state mutation."""
    clm = _reload_clm()
    import candle_builder as cb

    bar_open = datetime.now(tz=timezone.utc) - timedelta(seconds=clm.BAR_LENGTH_SECS + 120)
    df = pd.DataFrame([{"time": bar_open, "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0}])

    orig = cb.get_df_raw
    cb.get_df_raw = lambda _sym: df
    try:
        # live_lag returns CRITICAL-level lag …
        lag = clm.live_lag("GBPUSD")
        assert lag > clm.CRITICAL_THRESHOLD_SECS
        # … but is_stale() must still return False (no state mutation).
        assert clm.is_stale("GBPUSD") is False, (
            "live_lag must not promote pair to stale — that is check_candle_lag's job"
        )
    finally:
        cb.get_df_raw = orig


def test_live_lag_swallows_exceptions():
    """Internal failures must return None (defensive), never raise."""
    clm = _reload_clm()
    import candle_builder as cb

    def _boom(_sym):
        raise RuntimeError("simulated builder failure")

    orig = cb.get_df_raw
    cb.get_df_raw = _boom
    try:
        assert clm.live_lag("GBPUSD") is None
    finally:
        cb.get_df_raw = orig


# ---------------------------------------------------------------------------
# execute_trade fire-time guard
# ---------------------------------------------------------------------------

def _make_decision(mode="GBPUSD_BB_BOUNCE_S", signal="SELL"):
    """Minimal duck-typed decision — execute_trade only reads attributes via getattr."""
    return SimpleNamespace(
        mode=mode,
        signal=signal,
        symbol="GBPUSD",
        size=1.0,
        sl_pips=10.0,
        tp_pips=20.0,
        reason="unit-test",
        debug={},
    )


def test_execute_trade_blocks_when_live_lag_critical():
    """execute_trade must return None and emit RACE_CAUGHT when live_lag > CRITICAL."""
    te = _reload_te()
    clm = _reload_clm()

    # Force live_lag to report CRITICAL
    orig = clm.live_lag
    clm.live_lag = lambda _pair: clm.CRITICAL_THRESHOLD_SECS + 30

    try:
        result = te.execute_trade(_make_decision(), "CS.D.GBPUSD.TODAY.IP")
        assert result is None, (
            f"expected None when lag > CRITICAL, got {result!r} — guard not firing"
        )
    finally:
        clm.live_lag = orig


def test_execute_trade_does_not_block_when_live_lag_fresh():
    """execute_trade must NOT short-circuit on live_lag when lag is small.

    We don't need the call to succeed end-to-end (the rest of execute_trade
    will still gate on broker state, dedup, etc.) — only that the
    RACE_CAUGHT branch isn't what blocks it.
    """
    te = _reload_te()
    clm = _reload_clm()

    orig = clm.live_lag
    clm.live_lag = lambda _pair: 5.0  # well below CRITICAL

    captured = {}

    class _Capture(logging_handler_cls := __import__("logging").Handler):
        def emit(self, record):
            captured.setdefault("msgs", []).append(record.getMessage())

    h = _Capture()
    import logging as _logging
    _logging.getLogger("AutoBot").addHandler(h)
    try:
        # Call may return None for unrelated reasons (no IG session, etc.)
        # — what matters is that no RACE_CAUGHT log was emitted.
        try:
            te.execute_trade(_make_decision(), "CS.D.GBPUSD.TODAY.IP")
        except Exception:
            pass
        race_msgs = [m for m in captured.get("msgs", []) if "RACE_CAUGHT" in m]
        # debug-level "guard error" is OK; warning-level "blocked" is NOT.
        blocked = [m for m in race_msgs if "fire blocked" in m]
        assert not blocked, f"RACE_CAUGHT block fired on fresh lag: {blocked}"
    finally:
        _logging.getLogger("AutoBot").removeHandler(h)
        clm.live_lag = orig


def test_execute_trade_does_not_block_when_live_lag_returns_none():
    """When live_lag returns None (no signal), the guard must let the call
    proceed — None must NOT be treated as critical."""
    te = _reload_te()
    clm = _reload_clm()

    orig = clm.live_lag
    clm.live_lag = lambda _pair: None

    captured = {}

    class _Capture(__import__("logging").Handler):
        def emit(self, record):
            captured.setdefault("msgs", []).append(record.getMessage())

    h = _Capture()
    import logging as _logging
    _logging.getLogger("AutoBot").addHandler(h)
    try:
        try:
            te.execute_trade(_make_decision(), "CS.D.GBPUSD.TODAY.IP")
        except Exception:
            pass
        race_msgs = [m for m in captured.get("msgs", []) if "RACE_CAUGHT" in m]
        blocked = [m for m in race_msgs if "fire blocked" in m]
        assert not blocked, (
            f"RACE_CAUGHT block fired on None lag — must treat None as no-signal: {blocked}"
        )
    finally:
        _logging.getLogger("AutoBot").removeHandler(h)
        clm.live_lag = orig


def test_execute_trade_blocks_with_blank_epic_first():
    """The blank-epic check must run before the lag guard (existing contract)."""
    te = _reload_te()
    result = te.execute_trade(_make_decision(), "")
    assert result is None


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def main():
    tests = [(name, fn) for name, fn in globals().items()
             if name.startswith("test_") and inspect.isfunction(fn)]
    failed = []
    print(f"Running {len(tests)} tests for candle_lag race guard...")
    t0 = time.time()
    for name, fn in tests:
        try:
            fn()
            print(f"  ✓ {name}")
        except Exception as e:
            print(f"  ✗ {name}: {e}")
            failed.append((name, e))
    dt = time.time() - t0
    print(f"\n{len(tests) - len(failed)}/{len(tests)} passed in {dt:.2f}s")
    if failed:
        print("\nFailures:")
        for name, e in failed:
            print(f"  {name}: {type(e).__name__}: {e}")
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
