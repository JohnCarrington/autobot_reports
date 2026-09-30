#!/usr/bin/env python3
"""Unit tests for pair_workers. Standalone runner — exits 0 on pass.

Tests:
  1. enqueue/drain ordering within a single pair
  2. drop-oldest on tick overflow + counter increments
  3. drop-none + producer blocks on 5m overflow
  4. shutdown drains in-flight payloads
  5. queue_depth_snapshot returns expected keys
  6. two pairs run concurrently (parallelism)
  7. depth-gauge daemon starts/stops cleanly
  8. registry idempotence (get_or_create_worker is per-symbol singleton)
  9. integration: 200 ticks under slow callback, enqueue side stays <10ms
"""
from __future__ import annotations

import importlib
import os
import sys
import threading
import time

sys.path.insert(0, "/opt/tradingbot")


def _reload_module():
    if "pair_workers" in sys.modules:
        return importlib.reload(sys.modules["pair_workers"])
    import pair_workers
    return pair_workers


def _reset_module():
    """Reload pair_workers so module-level registry is fresh between tests."""
    pw = _reload_module()
    try:
        pw.shutdown_all(timeout=1.0)
    except Exception:
        pass
    return pw


def test_enqueue_drain_order():
    pw = _reset_module()
    received: list = []
    cv = threading.Event()

    def cb(*args):
        received.append(args[0])
        if len(received) >= 5:
            cv.set()

    w = pw.PairWorker("GBPUSD", tick_callback=cb, queue_size_ticks=10)
    w.start()
    for i in range(5):
        w.enqueue_tick((i, "epic", 1.0, 1.0, 1.0, 0.0, 0, 0))
    cv.wait(timeout=2.0)
    w.shutdown(timeout=2.0)

    assert received == [0, 1, 2, 3, 4], f"order broken: {received}"
    print("OK: enqueue/drain ordering")


def test_drop_oldest_overflow():
    pw = _reset_module()
    started = threading.Event()
    blocking = threading.Event()
    completed = threading.Event()

    def cb(*args):
        if not started.is_set():
            started.set()
            blocking.wait(timeout=5.0)
        if args[0] == "FINAL":
            completed.set()

    w = pw.PairWorker("EURUSD", tick_callback=cb, queue_size_ticks=3)
    w.start()
    w.enqueue_tick(("blocker", "epic", 1.0, 1.0, 1.0, 0.0, 0, 0))
    assert started.wait(timeout=2.0)

    for i in range(3):
        w.enqueue_tick((f"item-{i}", "epic", 1.0, 1.0, 1.0, 0.0, 0, 0))
    for i in range(5):
        w.enqueue_tick((f"drop-{i}", "epic", 1.0, 1.0, 1.0, 0.0, 0, 0))

    assert w.dropped_ticks >= 5, f"expected >=5 drops, got {w.dropped_ticks}"

    w.enqueue_tick(("FINAL", "epic", 1.0, 1.0, 1.0, 0.0, 0, 0))
    blocking.set()
    completed.wait(timeout=2.0)
    w.shutdown(timeout=2.0)

    assert completed.is_set(), "FINAL never observed; queue draining broken"
    print(f"OK: drop-oldest overflow (dropped_ticks={w.dropped_ticks})")


def test_5m_drop_none_and_block():
    pw = _reset_module()
    pw._FIVE_MIN_BLOCK_TIMEOUT_S = 0.5

    started = threading.Event()
    release = threading.Event()
    received: list = []

    def cb(symbol, epic, candle_row):
        if not started.is_set():
            started.set()
            release.wait(timeout=5.0)
        received.append(candle_row)

    w = pw.PairWorker("USDJPY", five_min_callback=cb, queue_size_5m=2)
    w.start()
    w.enqueue_5m_close(("USDJPY", "epic", {"close": 0}))
    assert started.wait(timeout=2.0)

    w.enqueue_5m_close(("USDJPY", "epic", {"close": 1}))
    w.enqueue_5m_close(("USDJPY", "epic", {"close": 2}))

    t0 = time.time()
    accepted = w.enqueue_5m_close(("USDJPY", "epic", {"close": 3}))
    elapsed = time.time() - t0
    assert not accepted, "expected producer block to time out"
    assert elapsed >= 0.4, f"producer should have blocked ~0.5s, got {elapsed:.2f}s"
    assert w.five_min_block_warnings >= 1, "block warning counter should increment"

    release.set()
    w.shutdown(timeout=2.0)
    print(f"OK: 5m drop-none producer block (elapsed={elapsed:.2f}s, warnings={w.five_min_block_warnings})")


def test_shutdown_drains_in_flight():
    pw = _reset_module()
    received: list = []

    def cb(*args):
        time.sleep(0.05)
        received.append(args[0])

    w = pw.PairWorker("USDCAD", tick_callback=cb, queue_size_ticks=20)
    w.start()
    for i in range(8):
        w.enqueue_tick((i, "epic", 1.0, 1.0, 1.0, 0.0, 0, 0))
    time.sleep(0.1)
    w.shutdown(timeout=5.0)
    assert len(received) >= 1, "shutdown should let the drainer finish at least one tick"
    print(f"OK: shutdown drains in-flight (processed={len(received)}/8)")


def test_queue_depth_snapshot_keys():
    pw = _reset_module()
    w = pw.PairWorker("GBPJPY", tick_callback=lambda *a: None)
    w.start()
    snap = w.queue_depth_snapshot()
    needed = {"tick", "5m", "dropped_ticks", "processed_ticks", "processed_5m",
              "tick_cb_errors", "5m_cb_errors", "5m_block_warnings"}
    assert needed <= set(snap.keys()), f"missing keys: {needed - set(snap.keys())}"
    w.shutdown(timeout=1.0)
    print("OK: queue_depth_snapshot keys")


def test_two_pairs_concurrent():
    pw = _reset_module()
    enter = {"a": threading.Event(), "b": threading.Event()}
    release = threading.Event()

    def cb_a(*args):
        enter["a"].set()
        release.wait(timeout=5.0)

    def cb_b(*args):
        enter["b"].set()
        release.wait(timeout=5.0)

    a = pw.PairWorker("PAIR_A", tick_callback=cb_a)
    b = pw.PairWorker("PAIR_B", tick_callback=cb_b)
    a.start()
    b.start()

    a.enqueue_tick(("a", "epic", 1, 1, 1, 0, 0, 0))
    b.enqueue_tick(("b", "epic", 1, 1, 1, 0, 0, 0))
    assert enter["a"].wait(timeout=2.0)
    assert enter["b"].wait(timeout=2.0)
    release.set()
    a.shutdown(timeout=2.0)
    b.shutdown(timeout=2.0)
    print("OK: two pairs run concurrently")


def test_registry_idempotent():
    pw = _reset_module()
    w1 = pw.get_or_create_worker("EURUSD", tick_callback=lambda *a: None)
    w2 = pw.get_or_create_worker("EURUSD")
    assert w1 is w2, "get_or_create_worker should be idempotent per-symbol"
    pw.shutdown_all(timeout=1.0)
    print("OK: registry idempotence")


def test_depth_gauge_starts_stops():
    pw = _reset_module()
    pw._DEPTH_GAUGE_INTERVAL_S = 0.05
    pw.start_depth_gauge()
    time.sleep(0.1)
    pw.stop_depth_gauge()
    pw._DEPTH_GAUGE_INTERVAL_S = 0.05
    pw.start_depth_gauge()
    time.sleep(0.1)
    pw.stop_depth_gauge()
    print("OK: depth gauge starts/stops cleanly")


def test_integration_high_throughput():
    """Regression test for the actual bug: simulate slow callbacks and
    verify the LS-thread side (enqueue) returns sub-ms throughout."""
    pw = _reset_module()

    def slow_cb(*args):
        time.sleep(0.1)

    w = pw.PairWorker("STRESS", tick_callback=slow_cb, queue_size_ticks=200)
    w.start()
    enqueue_durations = []
    for i in range(200):
        t0 = time.perf_counter()
        w.enqueue_tick((i, "epic", 1, 1, 1, 0, 0, 0))
        enqueue_durations.append((time.perf_counter() - t0) * 1000.0)
    max_ms = max(enqueue_durations)
    avg_ms = sum(enqueue_durations) / len(enqueue_durations)
    w.shutdown(timeout=2.0)
    assert max_ms < 10.0, f"max enqueue {max_ms:.2f}ms exceeded 10ms"
    print(f"OK: high-throughput enqueue (max={max_ms:.3f}ms avg={avg_ms:.3f}ms n=200)")


def main():
    tests = [
        test_enqueue_drain_order,
        test_drop_oldest_overflow,
        test_5m_drop_none_and_block,
        test_shutdown_drains_in_flight,
        test_queue_depth_snapshot_keys,
        test_two_pairs_concurrent,
        test_registry_idempotent,
        test_depth_gauge_starts_stops,
        test_integration_high_throughput,
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
