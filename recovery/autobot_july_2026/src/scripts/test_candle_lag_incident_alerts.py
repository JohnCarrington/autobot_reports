#!/usr/bin/env python3
"""Unit tests for candle-lag incident-tracked Telegram alerts.

Covers the new contract:
  - One alert when a pair transitions INTO CRITICAL (start)
  - One summary alert when the pair transitions back to NORMAL (resolved)
  - At most one prolonged alert per incident (env LAG_ALERT_PROLONGED_THRESHOLD_SECS)
  - Multi-pair incidents tracked independently
  - WARN transitions do NOT send Telegram
  - Re-entry into CRITICAL during an active incident does NOT re-alert

Standalone runner — exits 0 on pass.
"""
from __future__ import annotations

import importlib
import inspect
import os
import sys
import time
from datetime import datetime, timedelta, timezone

sys.path.insert(0, "/opt/tradingbot")


def _reload_clm(env=None):
    """Reload candle_lag_monitor with optional env vars set first."""
    if env:
        for k, v in env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = str(v)
    if "candle_lag_monitor" in sys.modules:
        return importlib.reload(sys.modules["candle_lag_monitor"])
    import candle_lag_monitor
    return candle_lag_monitor


def _patch_telegram(clm):
    """Replace _send_telegram with a capture list. Returns the list."""
    sent: list = []
    clm._send_telegram = lambda text: sent.append(text)
    return sent


def _ts_with_lag(lag_seconds: float) -> str:
    """Build a bar-open ISO timestamp such that
    now - (bar_open + 300) = lag_seconds."""
    bar_open = datetime.now(tz=timezone.utc) - timedelta(seconds=300 + lag_seconds)
    return bar_open.isoformat()


# ---------------------------------------------------------------------------
# Start alert
# ---------------------------------------------------------------------------

def test_critical_transition_sends_one_start_alert():
    clm = _reload_clm()
    sent = _patch_telegram(clm)

    clm.check_candle_lag("GBPUSD", _ts_with_lag(90))

    starts = [m for m in sent if "CRITICAL" in m]
    assert len(starts) == 1, f"expected 1 start alert, got {len(starts)}: {sent}"
    assert "GBPUSD" in starts[0]
    # Incident should be tracked
    assert "GBPUSD" in clm.active_incidents()


def test_warn_transition_does_not_telegram():
    clm = _reload_clm()
    sent = _patch_telegram(clm)

    # WARN range: 10s < lag < 60s
    clm.check_candle_lag("GBPUSD", _ts_with_lag(20))

    assert sent == [], f"WARN must not telegram: got {sent}"
    assert "GBPUSD" not in clm.active_incidents()


# ---------------------------------------------------------------------------
# Suppression during active incident
# ---------------------------------------------------------------------------

def test_repeated_critical_bars_dont_re_alert():
    """Subsequent CRITICAL bars during an active incident must be silent."""
    clm = _reload_clm()
    sent = _patch_telegram(clm)

    clm.check_candle_lag("GBPUSD", _ts_with_lag(90))   # start alert
    clm.check_candle_lag("GBPUSD", _ts_with_lag(120))  # silent
    clm.check_candle_lag("GBPUSD", _ts_with_lag(150))  # silent

    starts = [m for m in sent if "CRITICAL" in m and "Candle lag CRITICAL" in m]
    assert len(starts) == 1, f"expected 1 start alert across 3 critical bars, got {len(starts)}"


def test_critical_reentry_after_warn_drop_does_not_re_alert():
    """Bar 1: CRITICAL (start). Bar 2: WARN (drops below 60 but above 5,
    state goes WARN). Bar 3: CRITICAL again. Incident is still active —
    no second start alert."""
    clm = _reload_clm()
    sent = _patch_telegram(clm)

    clm.check_candle_lag("GBPUSD", _ts_with_lag(90))   # CRITICAL start
    # Note: state machine transitions on RESET (<5s), not on dropping below
    # CRITICAL. So a 30s lag stays in CRITICAL state — but to test the
    # re-entry logic we need to manually flip state to WARN.
    with clm._lock:
        clm._state["GBPUSD"] = clm._STATE_WARN
    clm.check_candle_lag("GBPUSD", _ts_with_lag(80))   # CRITICAL again — re-entry

    starts = [m for m in sent if "Candle lag CRITICAL" in m]
    assert len(starts) == 1, (
        f"re-entry into CRITICAL during active incident must not re-alert, got {len(starts)}: {sent}"
    )


# ---------------------------------------------------------------------------
# Resolution summary
# ---------------------------------------------------------------------------

def test_recovery_sends_summary_with_duration_and_peak():
    clm = _reload_clm()
    sent = _patch_telegram(clm)

    # Start the incident
    clm.check_candle_lag("GBPUSD", _ts_with_lag(90))   # peak 90
    clm.check_candle_lag("GBPUSD", _ts_with_lag(180))  # peak 180
    clm.check_candle_lag("GBPUSD", _ts_with_lag(120))  # peak still 180

    # Now resolve (lag < RESET_THRESHOLD_SECS=5)
    clm.check_candle_lag("GBPUSD", _ts_with_lag(2))

    resolveds = [m for m in sent if "resolved" in m.lower()]
    assert len(resolveds) == 1, f"expected 1 summary, got {len(resolveds)}: {sent}"
    body = resolveds[0]
    assert "GBPUSD" in body
    assert "Peak lag" in body
    assert "180.0s" in body, f"summary missing peak: {body}"
    assert "Duration" in body
    # Incident should be cleared
    assert "GBPUSD" not in clm.active_incidents()


def test_recovery_without_incident_sends_no_summary():
    """If a pair was never CRITICAL (only WARN), recovery must not summary."""
    clm = _reload_clm()
    sent = _patch_telegram(clm)

    clm.check_candle_lag("GBPUSD", _ts_with_lag(20))   # WARN (silent)
    clm.check_candle_lag("GBPUSD", _ts_with_lag(2))    # recovery (no incident → no summary)

    summaries = [m for m in sent if "resolved" in m.lower()]
    assert summaries == [], f"WARN-only recovery must not summary: {summaries}"


# ---------------------------------------------------------------------------
# Multi-pair independence
# ---------------------------------------------------------------------------

def test_two_pairs_get_independent_alerts():
    clm = _reload_clm()
    sent = _patch_telegram(clm)

    # Two pairs go CRITICAL simultaneously
    clm.check_candle_lag("GBPUSD", _ts_with_lag(90))
    clm.check_candle_lag("EURUSD", _ts_with_lag(95))

    starts = [m for m in sent if "Candle lag CRITICAL" in m]
    assert len(starts) == 2, f"expected 2 start alerts (one per pair), got {len(starts)}"
    assert any("GBPUSD" in m for m in starts)
    assert any("EURUSD" in m for m in starts)

    # GBPUSD recovers, EURUSD stays CRITICAL
    clm.check_candle_lag("GBPUSD", _ts_with_lag(2))

    # One summary fires for GBPUSD only
    summaries = [m for m in sent if "resolved" in m.lower()]
    assert len(summaries) == 1
    assert "GBPUSD" in summaries[0]
    # EURUSD incident still active
    assert "EURUSD" in clm.active_incidents()
    assert "GBPUSD" not in clm.active_incidents()


def test_four_pairs_simultaneous_produce_four_starts_four_summaries():
    """Reproduces the production pattern from the audit: 4 pairs go CRITICAL
    together, then all recover. Must produce exactly 4 starts + 4 summaries,
    nothing in between."""
    clm = _reload_clm()
    sent = _patch_telegram(clm)
    pairs = ["GBPUSD", "EURUSD", "AUDUSD", "USDJPY"]

    # All 4 enter CRITICAL — multiple bars each
    for _ in range(3):
        for p in pairs:
            clm.check_candle_lag(p, _ts_with_lag(90))

    starts = [m for m in sent if "Candle lag CRITICAL" in m]
    assert len(starts) == 4, f"expected 4 starts, got {len(starts)}"

    # All recover
    for p in pairs:
        clm.check_candle_lag(p, _ts_with_lag(2))

    summaries = [m for m in sent if "resolved" in m.lower()]
    assert len(summaries) == 4, f"expected 4 summaries, got {len(summaries)}"
    assert len(sent) == 8, f"expected exactly 8 messages total, got {len(sent)}: {sent}"


# ---------------------------------------------------------------------------
# Prolonged alert
# ---------------------------------------------------------------------------

def test_prolonged_alert_disabled_when_env_unset():
    clm = _reload_clm(env={"LAG_ALERT_PROLONGED_THRESHOLD_SECS": None})
    assert clm.LAG_ALERT_PROLONGED_THRESHOLD_SECS is None
    sent = _patch_telegram(clm)

    # Start incident, then 5 more CRITICAL bars over time — no prolonged alert.
    clm.check_candle_lag("GBPUSD", _ts_with_lag(90))
    # Manually back-date the incident start to fake a long-running incident
    with clm._lock:
        clm._incidents["GBPUSD"]["start_ts"] = time.time() - 900  # 15 min ago

    clm.check_candle_lag("GBPUSD", _ts_with_lag(100))

    prolonged = [m for m in sent if "still ongoing" in m.lower()]
    assert prolonged == [], f"prolonged disabled must not fire: {prolonged}"


def test_prolonged_alert_disabled_when_env_empty():
    clm = _reload_clm(env={"LAG_ALERT_PROLONGED_THRESHOLD_SECS": ""})
    assert clm.LAG_ALERT_PROLONGED_THRESHOLD_SECS is None


def test_prolonged_alert_disabled_when_env_invalid():
    clm = _reload_clm(env={"LAG_ALERT_PROLONGED_THRESHOLD_SECS": "abc"})
    assert clm.LAG_ALERT_PROLONGED_THRESHOLD_SECS is None


def test_prolonged_alert_fires_once_when_threshold_crossed():
    """When env=600 and incident has been ongoing >600s, fire ONE prolonged alert."""
    clm = _reload_clm(env={"LAG_ALERT_PROLONGED_THRESHOLD_SECS": "600"})
    assert clm.LAG_ALERT_PROLONGED_THRESHOLD_SECS == 600.0
    sent = _patch_telegram(clm)

    clm.check_candle_lag("GBPUSD", _ts_with_lag(90))   # start alert
    # Back-date the incident start so the next bar crosses the threshold
    with clm._lock:
        clm._incidents["GBPUSD"]["start_ts"] = time.time() - 700  # 700s ago > 600

    # Three more bars during the prolonged incident
    clm.check_candle_lag("GBPUSD", _ts_with_lag(100))  # should fire prolonged
    clm.check_candle_lag("GBPUSD", _ts_with_lag(110))  # silent
    clm.check_candle_lag("GBPUSD", _ts_with_lag(120))  # silent

    prolonged = [m for m in sent if "still ongoing" in m.lower()]
    assert len(prolonged) == 1, (
        f"expected exactly 1 prolonged alert, got {len(prolonged)}: {prolonged}"
    )


def test_prolonged_alert_skipped_below_threshold():
    clm = _reload_clm(env={"LAG_ALERT_PROLONGED_THRESHOLD_SECS": "600"})
    sent = _patch_telegram(clm)

    clm.check_candle_lag("GBPUSD", _ts_with_lag(90))
    # Only 30s into the incident — below 600s threshold
    clm.check_candle_lag("GBPUSD", _ts_with_lag(95))

    prolonged = [m for m in sent if "still ongoing" in m.lower()]
    assert prolonged == []


def test_prolonged_then_resolution_both_fire():
    """A long incident should fire: 1 start + 1 prolonged + 1 summary = 3 alerts."""
    clm = _reload_clm(env={"LAG_ALERT_PROLONGED_THRESHOLD_SECS": "600"})
    sent = _patch_telegram(clm)

    clm.check_candle_lag("GBPUSD", _ts_with_lag(90))   # start
    with clm._lock:
        clm._incidents["GBPUSD"]["start_ts"] = time.time() - 700
    clm.check_candle_lag("GBPUSD", _ts_with_lag(100))  # prolonged
    clm.check_candle_lag("GBPUSD", _ts_with_lag(2))    # summary

    assert len(sent) == 3, f"expected 3 alerts (start/prolonged/summary), got {len(sent)}: {sent}"
    assert any("CRITICAL" in m for m in sent)
    assert any("still ongoing" in m.lower() for m in sent)
    assert any("resolved" in m.lower() for m in sent)


# ---------------------------------------------------------------------------
# Format helpers
# ---------------------------------------------------------------------------

def test_fmt_duration_seconds():
    clm = _reload_clm()
    assert clm._fmt_duration(0) == "0s"
    assert clm._fmt_duration(47) == "47s"


def test_fmt_duration_minutes():
    clm = _reload_clm()
    assert clm._fmt_duration(60) == "1m00s"
    assert clm._fmt_duration(192) == "3m12s"
    assert clm._fmt_duration(3599) == "59m59s"


def test_fmt_duration_hours():
    clm = _reload_clm()
    assert clm._fmt_duration(3600) == "1h00m"
    assert clm._fmt_duration(3840) == "1h04m"


def test_fmt_duration_negative_clamped():
    clm = _reload_clm()
    assert clm._fmt_duration(-5) == "0s"


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def main():
    tests = [(name, fn) for name, fn in globals().items()
             if name.startswith("test_") and inspect.isfunction(fn)]
    failed = []
    print(f"Running {len(tests)} incident-alert tests...")
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
