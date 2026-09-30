"""Ordering coverage: matrix update completes before strategy permits() reads
it, on the same 5M-close bar.

Bug (2026-07-09T07:30 GBPUSD): `transition_dwell` fired at :00.871130Z, 1ms
AFTER the six strategy suppressions logged at :00.844-.870Z. Strategy
callbacks ran on the main close chain; the engine emit + matrix.update()
ran on a dedicated ThreadPoolExecutor (_regime_engine_pool), so permits()
read pre-transition state. Fix: per-bar Event set by mark_bar_processed()
after matrix.update() completes; strategies call wait_for_bar() before
permits() with a bounded timeout, log WARN on timeout, and fall through
to the current (stale) state so nothing deadlocks.

Cases:
  (a) mark_bar_processed → wait_for_bar unblocks immediately.
  (b) wait_for_bar times out when nobody marks the bar; returns False and
      logs WARN.
  (c) Transition bar: mark AFTER matrix.update(); a waiter that started
      BEFORE the update sees the NEW effective_regime once unblocked.
  (d) Deadlock guard: emit-side exception path must still mark the bar,
      not just the happy path. Simulate by calling mark inside a finally
      block after raising.
  (e) Flag OFF: wait_for_bar returns True immediately, no state stored.
  (f) Bucket=None on either side is a no-op that returns True — never
      blocks (payload with a missing bucket_epoch must not stall the
      callback chain).
  (g) Event map is bounded: pushing more than REGIME_MATRIX_BAR_EVENT_KEEP
      buckets prunes older ones.
"""
from __future__ import annotations

import logging
import os
import sys
import threading
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))


@pytest.fixture
def matrix_on(monkeypatch, tmp_path):
    monkeypatch.setenv("REGIME_MATRIX_ENABLED", "1")
    monkeypatch.setenv("REGIME_MATRIX_DWELL_N", "3")
    monkeypatch.setenv("REGIME_MATRIX_WAIT_TIMEOUT_S", "1.0")
    monkeypatch.setenv("REGIME_MATRIX_BAR_EVENT_KEEP", "4")
    monkeypatch.setenv("REGIME_MATRIX_LOG_PATH",
                       str(tmp_path / "matrix_ordering.jsonl"))
    monkeypatch.delitem(sys.modules, "regime_matrix", raising=False)
    import regime_matrix
    regime_matrix._reset_state_for_tests()
    return regime_matrix


# ─── (a) mark → wait unblocks immediately ─────────────────────────────────
def test_wait_returns_true_when_already_marked(matrix_on):
    m = matrix_on
    m.mark_bar_processed("GBPUSD", 1_752_000_000)
    t0 = time.perf_counter()
    got = m.wait_for_bar("GBPUSD", 1_752_000_000, timeout=1.0)
    elapsed = time.perf_counter() - t0
    assert got is True
    assert elapsed < 0.05, f"already-set event took too long: {elapsed:.3f}s"


# ─── (b) wait times out and logs WARN ─────────────────────────────────────
def test_wait_times_out_and_logs_warn(matrix_on, caplog):
    m = matrix_on
    caplog.set_level(logging.WARNING, logger="regime_matrix")
    t0 = time.perf_counter()
    got = m.wait_for_bar("GBPUSD", 1_752_000_100, timeout=0.15)
    elapsed = time.perf_counter() - t0
    assert got is False
    assert 0.14 <= elapsed < 0.35, f"timeout diverged from budget: {elapsed:.3f}s"
    warned = [r for r in caplog.records if "did not complete within" in r.getMessage()]
    assert len(warned) == 1, f"expected one WARN, got {len(warned)}"
    assert "GBPUSD" in warned[0].getMessage()


# ─── (c) Transition bar — waiter sees NEW effective post-mark ─────────────
def test_transition_bar_waiter_reads_new_effective(matrix_on):
    m = matrix_on
    bucket = 1_752_000_200
    # Prime effective=STRONG_TREND_UP so the next STRONG bar is a no-op,
    # then walk to TREND_FORMING_UP over 3 bars — the promotion happens on
    # the 3rd update() call.
    for _ in range(3):
        m.update("GBPUSD", "STRONG_TREND_UP")
    assert m.effective_regime("GBPUSD") == "STRONG_TREND_UP"

    seen: dict = {}
    barrier = threading.Barrier(2)

    def waiter():
        barrier.wait()  # sync waiter start
        ok = m.wait_for_bar("GBPUSD", bucket, timeout=1.0)
        seen["got"] = ok
        seen["effective_after_wait"] = m.effective_regime("GBPUSD")

    th = threading.Thread(target=waiter, daemon=True)
    th.start()
    barrier.wait()
    # Give the waiter a moment to actually enter Event.wait().
    time.sleep(0.02)

    # Simulate the engine pool worker: two more FORMING updates to trip
    # dwell, then mark the bar processed.
    for _ in range(3):
        m.update("GBPUSD", "TREND_FORMING_UP")
    assert m.effective_regime("GBPUSD") == "TREND_FORMING_UP"
    m.mark_bar_processed("GBPUSD", bucket)

    th.join(timeout=1.0)
    assert not th.is_alive(), "waiter did not unblock after mark"
    assert seen.get("got") is True
    assert seen.get("effective_after_wait") == "TREND_FORMING_UP", (
        f"waiter read pre-transition effective: {seen}"
    )


# ─── (d) Deadlock guard — mark still fires on error path ──────────────────
def test_error_path_still_unblocks_via_finally(matrix_on):
    """Emulate autobot._emit_then_route: emit raises, but the caller's
    finally block still calls mark_bar_processed so the waiter unblocks.
    """
    m = matrix_on
    bucket = 1_752_000_300

    def buggy_emit_then_route():
        # Mirror the pool-worker shape: an outer try swallows the exception
        # (in production, ThreadPoolExecutor stashes it on an un-awaited
        # future — same practical outcome). The FINALLY inside guarantees
        # mark_bar_processed runs regardless.
        try:
            try:
                raise RuntimeError("simulated emit failure")
            finally:
                m.mark_bar_processed("GBPUSD", bucket)
        except RuntimeError:
            pass

    t = threading.Thread(target=buggy_emit_then_route, daemon=True)
    t.start()
    t.join(timeout=1.0)
    got = m.wait_for_bar("GBPUSD", bucket, timeout=0.5)
    assert got is True, "waiter timed out despite finally-mark on error path"


# ─── (e) Flag OFF — wait is a no-op that returns True ─────────────────────
def test_wait_is_noop_when_flag_off(monkeypatch, tmp_path):
    monkeypatch.setenv("REGIME_MATRIX_ENABLED", "0")
    monkeypatch.setenv("REGIME_MATRIX_LOG_PATH",
                       str(tmp_path / "matrix_off.jsonl"))
    monkeypatch.delitem(sys.modules, "regime_matrix", raising=False)
    import regime_matrix
    regime_matrix._reset_state_for_tests()
    t0 = time.perf_counter()
    # Bucket never marked; must return True immediately anyway.
    got = regime_matrix.wait_for_bar("GBPUSD", 1_752_000_400, timeout=1.0)
    elapsed = time.perf_counter() - t0
    assert got is True
    assert elapsed < 0.05, "flag-off wait blocked; must be a no-op"
    # And mark should not create any state.
    regime_matrix.mark_bar_processed("GBPUSD", 1_752_000_400)
    # Nothing to assert on internal state because it's a no-op.


# ─── (f) Bucket=None is a no-op ───────────────────────────────────────────
def test_wait_with_none_bucket_returns_true(matrix_on):
    m = matrix_on
    t0 = time.perf_counter()
    got = m.wait_for_bar("GBPUSD", None, timeout=1.0)
    elapsed = time.perf_counter() - t0
    assert got is True
    assert elapsed < 0.05, "None bucket blocked; must be a no-op"


def test_mark_with_none_bucket_is_noop(matrix_on):
    m = matrix_on
    # Must not raise, must not create any state.
    m.mark_bar_processed("GBPUSD", None)


# ─── (g) Event map is bounded ─────────────────────────────────────────────
def test_event_map_is_pruned_to_keep_n(matrix_on):
    m = matrix_on
    # KEEP=4 per fixture env.
    for i in range(10):
        m.mark_bar_processed("GBPUSD", 1_752_100_000 + i)
    # Internal state is private; read via the accessor pattern used by
    # regime_matrix itself. Direct dict inspection is acceptable in a test
    # (module-internal, single process).
    with m._bar_events_lock:
        d = m._bar_events.get("GBPUSD", {})
        assert len(d) <= 4, f"event map not pruned: has {len(d)} entries"
        # Newest four must be retained.
        assert set(d.keys()) == {
            1_752_100_006, 1_752_100_007, 1_752_100_008, 1_752_100_009
        }


# ─── (h) mark_bar_processed is idempotent ─────────────────────────────────
def test_mark_is_idempotent(matrix_on):
    m = matrix_on
    bucket = 1_752_100_500
    m.mark_bar_processed("GBPUSD", bucket)
    m.mark_bar_processed("GBPUSD", bucket)  # second call must not raise
    assert m.wait_for_bar("GBPUSD", bucket, timeout=0.05) is True
