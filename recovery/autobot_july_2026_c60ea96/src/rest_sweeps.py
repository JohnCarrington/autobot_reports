"""rest_sweeps.py — Background REST sweep daemon.

Two periodic REST checks used to fire from inside `_on_ls_tick` on a
time-since-last-call gate. With per-pair workers running on independent
threads, time-gating those checks via the LS callback is no longer
appropriate (each pair-worker would think it's the one to fire it). And
even before this refactor, those REST calls were the largest blocking
contributor on the LS thread.

This module owns one daemon thread that loops with a small sleep and
fires each sweep on its own cadence:

  - Positions SYNC sweep (cadence: POSITIONS_SYNC_MIN_GAP, default 15s)
    Reconciles broker open positions with EPIC_STATE; closes orphans.

  - External-close sweep (cadence: IG_MONITOR_EVERY_S, default 10s)
    Detects IG-side closures (manual / SL / TP) and emits close events.

Each sweep is wrapped in a try/except so an exception on one cadence
cannot halt the daemon. Sweep durations are logged at INFO every N
invocations.

Backward-compat: if env LS_ASYNC_DISPATCH=0, the daemon is NOT started
(autobot main path will keep firing the sweeps inline as before).
"""
from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any, Callable, Optional

logger = logging.getLogger("AutoBot")

LS_ASYNC_DISPATCH = (os.getenv("LS_ASYNC_DISPATCH", "1") or "1").strip() != "0"

# Cadences (read once at module load — match the inline-path constants
# in autobot.py and trade_manager.py so the daemon-driven path is a
# 1-for-1 functional replacement).
POSITIONS_SYNC_GAP_S = max(5, int(float(os.getenv("POSITIONS_SYNC_SECONDS", "15") or 15)))
IG_MONITOR_GAP_S = float(os.getenv("IG_MONITOR_EVERY_S", "10") or 10.0)

# Daemon loop tick — small enough that cadence drift is < 1s.
_DAEMON_TICK_S = float(os.getenv("REST_SWEEP_DAEMON_TICK_S", "1.0") or 1.0)

# Log a duration line every N invocations of each sweep.
_LOG_DURATION_EVERY_N = int(float(os.getenv("REST_SWEEP_LOG_EVERY_N", "10") or 10))


class RestSweepDaemon:
    """Owns the background sweep loop. Bound to an AutoBot instance for
    SYNC-sweep state, plus the trade_manager module for external-close
    state. One instance per process; created in autobot.main()."""

    def __init__(
        self,
        sync_sweep_fn: Callable[[], Any],
        external_close_sweep_fn: Callable[[], Any],
    ) -> None:
        self._sync_fn = sync_sweep_fn
        self._external_fn = external_close_sweep_fn
        self._stop_evt = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._started = False
        self._lock = threading.Lock()

        self._last_sync_ts: float = 0.0
        self._last_external_ts: float = 0.0

        # Counters / running totals
        self.sync_invocations: int = 0
        self.external_invocations: int = 0
        self.sync_errors: int = 0
        self.external_errors: int = 0
        self.sync_duration_total_s: float = 0.0
        self.external_duration_total_s: float = 0.0

    def start(self) -> None:
        with self._lock:
            if self._started:
                return
            self._stop_evt.clear()
            self._thread = threading.Thread(
                target=self._run,
                name="RestSweepDaemon",
                daemon=True,
            )
            self._thread.start()
            self._started = True
        logger.info(
            f"[REST-SWEEP] daemon started — sync_gap={POSITIONS_SYNC_GAP_S}s "
            f"external_gap={IG_MONITOR_GAP_S:.1f}s tick={_DAEMON_TICK_S}s"
        )

    def stop(self, timeout: float = 5.0) -> None:
        with self._lock:
            if not self._started:
                return
            self._stop_evt.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
        logger.info(
            f"[REST-SWEEP] daemon stopped — "
            f"sync_invocations={self.sync_invocations} "
            f"external_invocations={self.external_invocations} "
            f"sync_errors={self.sync_errors} external_errors={self.external_errors}"
        )
        self._started = False

    def _run(self) -> None:
        # Stagger initial dispatch so both sweeps don't fire on tick 1.
        self._last_sync_ts = time.time()
        self._last_external_ts = time.time() - (IG_MONITOR_GAP_S / 2.0)

        while not self._stop_evt.wait(_DAEMON_TICK_S):
            now = time.time()

            if (now - self._last_sync_ts) >= POSITIONS_SYNC_GAP_S:
                self._last_sync_ts = now
                self._invoke_sync()

            if (now - self._last_external_ts) >= IG_MONITOR_GAP_S:
                self._last_external_ts = now
                self._invoke_external()

    def _invoke_sync(self) -> None:
        t0 = time.time()
        try:
            self._sync_fn()
        except Exception as e:
            self.sync_errors += 1
            logger.error(
                f"[REST-SWEEP] positions-sync error: {type(e).__name__}: {e}",
                exc_info=True,
            )
            return
        finally:
            elapsed = time.time() - t0
            self.sync_invocations += 1
            self.sync_duration_total_s += elapsed

        if self.sync_invocations % max(1, _LOG_DURATION_EVERY_N) == 0:
            avg = self.sync_duration_total_s / max(1, self.sync_invocations)
            logger.info(
                f"[REST-SWEEP] positions-sync: invocations={self.sync_invocations} "
                f"last_dur={elapsed:.3f}s avg_dur={avg:.3f}s errors={self.sync_errors}"
            )

    def _invoke_external(self) -> None:
        t0 = time.time()
        try:
            self._external_fn()
        except Exception as e:
            self.external_errors += 1
            logger.error(
                f"[REST-SWEEP] external-close error: {type(e).__name__}: {e}",
                exc_info=True,
            )
            return
        finally:
            elapsed = time.time() - t0
            self.external_invocations += 1
            self.external_duration_total_s += elapsed

        if self.external_invocations % max(1, _LOG_DURATION_EVERY_N) == 0:
            avg = self.external_duration_total_s / max(1, self.external_invocations)
            logger.info(
                f"[REST-SWEEP] external-close: invocations={self.external_invocations} "
                f"last_dur={elapsed:.3f}s avg_dur={avg:.3f}s errors={self.external_errors}"
            )


# ----------------------------------------------------------------------
# Module-level singleton
# ----------------------------------------------------------------------

_DAEMON: Optional[RestSweepDaemon] = None
_DAEMON_LOCK = threading.Lock()


def start_rest_sweep_daemon(
    sync_sweep_fn: Callable[[], Any],
    external_close_sweep_fn: Callable[[], Any],
) -> Optional[RestSweepDaemon]:
    """Start (idempotently) the REST sweep daemon. Returns the instance.

    If LS_ASYNC_DISPATCH=0, returns None and does NOT start the daemon —
    the inline path in `_on_ls_tick` is the sweep driver in that mode.
    """
    if not LS_ASYNC_DISPATCH:
        logger.info(
            "[REST-SWEEP] LS_ASYNC_DISPATCH=0 — daemon NOT started; "
            "inline sweep path remains active"
        )
        return None

    global _DAEMON
    with _DAEMON_LOCK:
        if _DAEMON is not None and _DAEMON._started:
            return _DAEMON
        _DAEMON = RestSweepDaemon(sync_sweep_fn, external_close_sweep_fn)
        _DAEMON.start()
        return _DAEMON


def get_daemon() -> Optional[RestSweepDaemon]:
    return _DAEMON


def stop_rest_sweep_daemon(timeout: float = 5.0) -> None:
    global _DAEMON
    with _DAEMON_LOCK:
        if _DAEMON is None:
            return
        _DAEMON.stop(timeout=timeout)
        _DAEMON = None
