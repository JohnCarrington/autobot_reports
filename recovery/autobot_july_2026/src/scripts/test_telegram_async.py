#!/usr/bin/env python3
"""Unit tests for telegram_alerts async dispatch (LS-thread refactor stage 1).

Standalone runner — exits 0 on pass, 1 on any failure.

Tests:
  1. wait=False returns within 5ms even when the underlying send is slow
  2. wait=True waits for the underlying send to complete
  3. Exception in send is logged and does NOT propagate to the caller
  4. atexit drain delivers in-flight submissions before shutdown
  5. Module reload picks up cleanly (defensive — no env-gating in this PR)

Mocks `requests.post` so no network calls are made. The dummy
TELEGRAM_TOKEN/CHAT_ID below satisfy the import-time guard.
"""
from __future__ import annotations

import importlib
import inspect
import logging
import os
import sys
import threading
import time
from typing import Any
from unittest.mock import patch

# Provide non-empty creds so telegram_alerts.import succeeds without an .env
os.environ.setdefault("TELEGRAM_TOKEN", "test-token")
os.environ.setdefault("TELEGRAM_CHAT_ID", "test-chat-id")

# Resolve the repo root from this script's location so the test runs
# correctly in worktrees and CI alike (this file lives at
# `<repo>/scripts/test_telegram_async.py`).
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
sys.path.insert(0, _REPO_ROOT)


# ------------------------------------------------------------
# Helpers
# ------------------------------------------------------------
def _reload_module():
    """Force a fresh import so executor state doesn't leak between tests."""
    for mod_name in list(sys.modules):
        if mod_name == "telegram_alerts":
            del sys.modules[mod_name]
    import telegram_alerts  # noqa: PLC0415
    return telegram_alerts


class _FakeResponse:
    """Minimal stand-in for requests.Response."""

    def __init__(self, status_code: int = 200, text: str = "ok"):
        self.status_code = status_code
        self.text = text


def _slow_post(delay_s: float) -> Any:
    """Return a `requests.post`-shaped callable that sleeps then returns 200."""

    def _inner(*_args, **_kwargs):
        time.sleep(delay_s)
        return _FakeResponse(200, "ok")

    return _inner


# ------------------------------------------------------------
# Tests
# ------------------------------------------------------------
def test_wait_false_returns_fast_with_slow_send():
    """wait=False must return in well under 5ms even when the actual HTTP
    send sleeps 1s. This is the whole point of the refactor."""
    tg = _reload_module()

    with patch("telegram_alerts.requests.post", side_effect=_slow_post(1.0)):
        t0 = time.perf_counter()
        tg.send_telegram_message("hello async")
        elapsed_ms = (time.perf_counter() - t0) * 1000.0

        assert elapsed_ms < 50.0, (
            f"wait=False returned in {elapsed_ms:.2f}ms — expected sub-50ms "
            "(target sub-5ms; 50ms is generous to absorb CI jitter)"
        )

    # Drain so the worker doesn't hold a real-network reference during teardown.
    tg._drain_executor_atexit()


def test_wait_true_blocks_for_underlying_send():
    """wait=True must block until the underlying send actually completes —
    the previous synchronous semantics for the LEG-ORPHAN-DETECTED path."""
    tg = _reload_module()

    with patch("telegram_alerts.requests.post", side_effect=_slow_post(0.20)):
        t0 = time.perf_counter()
        tg.send_telegram_message("hello sync", wait=True)
        elapsed_s = time.perf_counter() - t0

        assert elapsed_s >= 0.20, (
            f"wait=True returned in {elapsed_s*1000:.1f}ms — expected ≥200ms "
            "to confirm it actually waited for the send"
        )
        # Generous upper bound — we're not testing scheduler precision.
        assert elapsed_s < 2.0, (
            f"wait=True took {elapsed_s:.2f}s — expected <2s "
            "(the mock sleeps 0.2s; >2s suggests retry loop spinning)"
        )

    tg._drain_executor_atexit()


def test_exception_in_send_does_not_propagate():
    """A raise inside the HTTP call must be swallowed and logged at WARNING.
    Caller never sees it — neither in wait=False nor wait=True mode."""
    tg = _reload_module()

    boom_count = {"n": 0}

    def _explode(*_args, **_kwargs):
        boom_count["n"] += 1
        raise RuntimeError("network exploded")

    with patch("telegram_alerts.requests.post", side_effect=_explode):
        # wait=False: errors happen on the worker thread, never raised.
        try:
            tg.send_telegram_message("boom-async")
        except Exception as e:  # noqa: BLE001
            raise AssertionError(f"wait=False propagated {type(e).__name__}: {e}")

        # wait=True: we wait for the future, but errors inside the worker
        # are caught by _do_send_blocking and logged — fut.result() should
        # NOT re-raise either.
        try:
            tg.send_telegram_message("boom-sync", wait=True)
        except Exception as e:  # noqa: BLE001
            raise AssertionError(f"wait=True propagated {type(e).__name__}: {e}")

    tg._drain_executor_atexit()
    # Both calls should have triggered all 3 retries before giving up.
    # 2 calls × 3 retries = 6 invocations. (Allow a small lower bound in
    # case wait=False's worker hasn't fully drained before assertion —
    # the drain above guarantees it has, but be robust.)
    assert boom_count["n"] >= 6, (
        f"expected ≥6 underlying calls (2 messages × 3 retries), got {boom_count['n']}"
    )


def test_atexit_drain_delivers_inflight_messages():
    """Submit several messages, then trigger the drain and verify all of
    them were processed before shutdown returns."""
    tg = _reload_module()

    delivered = []
    delivered_lock = threading.Lock()

    def _record(*_args, **kwargs):
        # Sleep briefly so messages are still in-flight when drain starts.
        time.sleep(0.05)
        with delivered_lock:
            delivered.append(kwargs.get("json", {}).get("text", ""))
        return _FakeResponse(200, "ok")

    with patch("telegram_alerts.requests.post", side_effect=_record):
        for i in range(5):
            tg.send_telegram_message(f"msg-{i}")

        # Trigger the drain (mimics atexit firing on process shutdown).
        tg._drain_executor_atexit()

    assert len(delivered) == 5, (
        f"atexit drain delivered {len(delivered)}/5 messages — drain did not "
        "wait for all in-flight sends"
    )
    assert sorted(delivered) == [f"msg-{i}" for i in range(5)], (
        f"atexit drain dropped or reordered messages: {sorted(delivered)}"
    )


def test_post_drain_falls_back_to_blocking():
    """After the atexit drain has run, subsequent sends must NOT raise
    (which they would if we tried to submit to a shut-down pool). They
    fall back to inline blocking sends — late shutdown alerts still ship."""
    tg = _reload_module()

    # Force a drain.
    tg._drain_executor_atexit()
    assert tg._executor_drained is True

    delivered = []

    def _record(*_args, **kwargs):
        delivered.append(kwargs.get("json", {}).get("text", ""))
        return _FakeResponse(200, "ok")

    with patch("telegram_alerts.requests.post", side_effect=_record):
        try:
            tg.send_telegram_message("late-shutdown-alert")
        except Exception as e:  # noqa: BLE001
            raise AssertionError(
                f"post-drain send raised {type(e).__name__}: {e}"
            )

    assert delivered == ["late-shutdown-alert"], (
        f"post-drain fallback did not deliver inline: {delivered}"
    )


def test_module_reload_resets_executor_state():
    """Reloading the module must yield a fresh, usable executor — no
    stale `_executor_drained` flag bleeds across reloads. Defensive
    test: there is no env-gating in this PR, but this verifies the
    module is safe to reimport in tests / REPLs."""
    tg = _reload_module()
    tg._drain_executor_atexit()
    assert tg._executor_drained is True

    tg2 = _reload_module()
    assert tg2._executor_drained is False, (
        "_executor_drained leaked across module reload"
    )
    assert tg2._executor is None, (
        "_executor should be None until first send (lazy init)"
    )

    delivered = []

    def _record(*_args, **kwargs):
        delivered.append(kwargs.get("json", {}).get("text", ""))
        return _FakeResponse(200, "ok")

    with patch("telegram_alerts.requests.post", side_effect=_record):
        tg2.send_telegram_message("after-reload")
        tg2._drain_executor_atexit()

    assert delivered == ["after-reload"], (
        f"send after reload did not deliver: {delivered}"
    )


# ------------------------------------------------------------
# Runner
# ------------------------------------------------------------
def main() -> int:
    # Tame logging noise during tests — we still want WARN visibility for
    # the dispatch-latency check, just not spam from the retry loop.
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s %(message)s")

    tests = [
        (name, fn) for name, fn in globals().items()
        if name.startswith("test_") and inspect.isfunction(fn)
    ]
    failed: list = []
    print(f"Running {len(tests)} tests for telegram_alerts async dispatch...")
    for name, fn in tests:
        try:
            fn()
            print(f"  ✓ {name}")
        except AssertionError as e:
            print(f"  ✗ {name}: {e}")
            failed.append((name, str(e)))
        except Exception as e:  # noqa: BLE001
            print(f"  ✗ {name}: unexpected {type(e).__name__}: {e}")
            failed.append((name, f"{type(e).__name__}: {e}"))
    print()
    print(f"{len(tests) - len(failed)}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
