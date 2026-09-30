#!/usr/bin/env python3
"""Unit tests for rest_sweeps. Standalone runner.

Tests:
  1. timer fires both sweeps at correct intervals
  2. exception in a sweep does not stop the daemon
  3. shutdown stops the daemon cleanly
  4. LS_ASYNC_DISPATCH=0 makes start return None (rollback path)
"""
from __future__ import annotations

import importlib
import os
import sys
import threading
import time

sys.path.insert(0, "/opt/tradingbot")


def _reload_module():
    if "rest_sweeps" in sys.modules:
        return importlib.reload(sys.modules["rest_sweeps"])
    import rest_sweeps
    return rest_sweeps


def _reload_with_short_cadence():
    """Reload with tiny cadences so the test runs in a few seconds."""
    os.environ["LS_ASYNC_DISPATCH"] = "1"
    os.environ["POSITIONS_SYNC_SECONDS"] = "1"
    os.environ["IG_MONITOR_EVERY_S"] = "0.5"
    os.environ["REST_SWEEP_DAEMON_TICK_S"] = "0.05"
    os.environ["REST_SWEEP_LOG_EVERY_N"] = "100"
    rs = _reload_module()
    # Override the constants directly because POSITIONS_SYNC_GAP_S = max(5, ...)
    rs.POSITIONS_SYNC_GAP_S = 1
    rs.IG_MONITOR_GAP_S = 0.5
    return rs


def test_both_sweeps_fire():
    rs = _reload_with_short_cadence()
    sync_calls: list = []
    ext_calls: list = []

    def sync_fn():
        sync_calls.append(time.time())

    def ext_fn():
        ext_calls.append(time.time())

    daemon = rs.start_rest_sweep_daemon(sync_fn, ext_fn)
    assert daemon is not None
    time.sleep(1.6)
    rs.stop_rest_sweep_daemon(timeout=2.0)

    assert len(sync_calls) >= 1, f"sync sweep didn't fire (got {len(sync_calls)})"
    assert len(ext_calls) >= 2, f"external sweep didn't fire enough (got {len(ext_calls)})"
    print(f"OK: both sweeps fire (sync={len(sync_calls)}, ext={len(ext_calls)})")


def test_exception_does_not_kill_daemon():
    rs = _reload_with_short_cadence()
    ext_calls: list = []
    raised = threading.Event()

    def sync_boom():
        raised.set()
        raise RuntimeError("sync error")

    def ext_fn():
        ext_calls.append(time.time())

    daemon = rs.start_rest_sweep_daemon(sync_boom, ext_fn)
    time.sleep(1.6)
    rs.stop_rest_sweep_daemon(timeout=2.0)

    assert raised.is_set(), "sync sweep error not observed"
    assert len(ext_calls) >= 2, f"external sweep stopped after sync raised (got {len(ext_calls)})"
    assert daemon.sync_errors >= 1, "sync_errors counter not incremented"
    print(f"OK: exception swallowed (sync_errors={daemon.sync_errors}, ext_continued={len(ext_calls)})")


def test_shutdown_stops_daemon():
    rs = _reload_with_short_cadence()
    counter = [0]

    def fn():
        counter[0] += 1

    daemon = rs.start_rest_sweep_daemon(fn, fn)
    time.sleep(0.6)
    rs.stop_rest_sweep_daemon(timeout=2.0)
    snapshot = counter[0]
    time.sleep(0.6)
    assert counter[0] == snapshot, f"counter advanced after shutdown ({snapshot} -> {counter[0]})"
    print(f"OK: shutdown stops daemon (snapshot={snapshot})")


def test_disabled_returns_none():
    _saved = os.environ.get("LS_ASYNC_DISPATCH")
    os.environ["LS_ASYNC_DISPATCH"] = "0"
    try:
        rs = _reload_module()
        daemon = rs.start_rest_sweep_daemon(lambda: None, lambda: None)
        assert daemon is None, "start should return None when LS_ASYNC_DISPATCH=0"
        print("OK: LS_ASYNC_DISPATCH=0 returns None")
    finally:
        # Restore the env var so subsequent tests see the default async-on
        # behaviour. Without this, pytest test_telegram_async.py imports
        # land with LS_ASYNC_DISPATCH=0 and the first wait=False test fails.
        if _saved is None:
            os.environ.pop("LS_ASYNC_DISPATCH", None)
        else:
            os.environ["LS_ASYNC_DISPATCH"] = _saved


def main():
    tests = [
        test_both_sweeps_fire,
        test_exception_does_not_kill_daemon,
        test_shutdown_stops_daemon,
        test_disabled_returns_none,
    ]
    failures = 0
    for t in tests:
        try:
            t()
        except Exception as e:
            failures += 1
            print(f"FAIL: {t.__name__} — {type(e).__name__}: {e}")
            import traceback
            traceback.print_exc()
    print(f"\nResult: {len(tests) - failures}/{len(tests)} passed")
    sys.exit(failures)


if __name__ == "__main__":
    main()
