"""pair_workers.py — Per-pair Lightstreamer event-dispatch workers.

Refactor target: the Lightstreamer Python client uses a SINGLE shared
event-dispatch thread for every Subscription in the process (Issue #4 in
lightstreamer-lib-client-haxe). When a listener callback blocks (REST,
Telegram, IG confirm-loop), every other pair's ticks queue up behind it.

This module decouples the LS thread from the per-pair tick handler:

  LS thread → PriceListener.onItemUpdate
       │
       ▼
  PairWorker(symbol).enqueue_tick(payload)   ← <10ms, returns
       │
       ▼  (separate daemon thread per pair)
  drain queue → bot._on_ls_tick(*payload)    ← bulk of work runs here

Same ordering guarantee within a pair (queue is FIFO + single drainer).
Parallelism across pairs (4 workers, one per LS subscription).

Two queues per worker:
  - L1 tick queue: drop-OLDEST policy (a stale tick is acceptable; the
    next has the latest bid/ask). Sized 100 by default.
  - 5m close queue: drop-NONE policy (5m closes are infrequent and
    important; if the queue ever fills up we WARN and block briefly).

The 5m queue is drained FIRST on each loop iteration so a 5m close
never waits behind a backlog of L1 ticks.

Backward-compat: env LS_ASYNC_DISPATCH=0 disables the workers entirely
(callers fall through to synchronous dispatch). Default is 1 (async on).
"""
from __future__ import annotations

import logging
import os
import queue
import threading
import time
from collections import deque
from typing import Any, Callable, Deque, Dict, Optional, Tuple

logger = logging.getLogger("AutoBot")

# Backward-compat env flag, read once at module import.
LS_ASYNC_DISPATCH = (os.getenv("LS_ASYNC_DISPATCH", "1") or "1").strip() != "0"

# Queue-depth gauge cadence
_DEPTH_GAUGE_INTERVAL_S = float(os.getenv("LS_WORKER_DEPTH_GAUGE_S", "60") or 60)

# Producer-side block timeout when the 5m queue is full (drop-none policy).
# After this many seconds we WARN and drop anyway so the LS thread is never
# wedged forever — but in normal operation we expect this to never fire.
_FIVE_MIN_BLOCK_TIMEOUT_S = float(os.getenv("LS_WORKER_5M_BLOCK_TIMEOUT_S", "5") or 5)


class _TickPayload:
    """Lightweight wrapper for a tick. Tuple-equivalent shape:
       (symbol, epic, bid, ask, mid, ts, uts, umicro)."""
    __slots__ = ("args",)

    def __init__(self, args: tuple) -> None:
        self.args = args


class _FiveMinPayload:
    """Lightweight wrapper for a 5m close.
       (symbol, epic, candle_row)."""
    __slots__ = ("args",)

    def __init__(self, args: tuple) -> None:
        self.args = args


class PairWorker:
    """Single-pair queue + drainer thread.

    Use `enqueue_tick(payload_args)` and `enqueue_5m_close(payload_args)`
    from the LS event thread. The callbacks `tick_callback` and
    `five_min_callback` are invoked inside the worker thread.
    """

    def __init__(
        self,
        symbol: str,
        tick_callback: Optional[Callable[..., Any]] = None,
        five_min_callback: Optional[Callable[..., Any]] = None,
        queue_size_ticks: int = 100,
        queue_size_5m: int = 10,
    ) -> None:
        self.symbol = str(symbol).upper()
        self._tick_cb = tick_callback
        self._five_min_cb = five_min_callback

        self._tick_q: queue.Queue = queue.Queue(maxsize=int(queue_size_ticks))
        self._five_min_q: queue.Queue = queue.Queue(maxsize=int(queue_size_5m))

        # drop-oldest needs a lock + manual drop because stdlib Queue
        # has no put-with-eviction primitive.
        self._tick_drop_lock = threading.Lock()

        self._stop_evt = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._started = False
        self._lock = threading.Lock()

        # Counters (read by the depth-gauge daemon and by tests)
        self.dropped_ticks: int = 0
        self.processed_ticks: int = 0
        self.processed_5m: int = 0
        self.tick_callback_errors: int = 0
        self.five_min_callback_errors: int = 0
        # Producer-side block warnings on the 5m queue
        self.five_min_block_warnings: int = 0

        # Rolling (timestamp_seconds, duration_ms) buffers for the
        # occupancy gauge. Bounded so high-tick-rate pairs can't grow
        # memory without bound; the gauge emits time-windowed stats
        # rather than count-windowed so a 2000-entry tick buffer covers
        # ~ 60s comfortably even at 30 ticks/sec.
        self._tick_durations: Deque[Tuple[float, float]] = deque(maxlen=2000)
        self._five_min_durations: Deque[Tuple[float, float]] = deque(maxlen=200)
        self._durations_lock = threading.Lock()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def start(self) -> None:
        with self._lock:
            if self._started:
                return
            self._stop_evt.clear()
            self._thread = threading.Thread(
                target=self._run,
                name=f"PairWorker-{self.symbol}",
                daemon=True,
            )
            self._thread.start()
            self._started = True
        logger.info(f"[LS-WORKER] {self.symbol} worker started")

    def shutdown(self, timeout: float = 5.0) -> None:
        with self._lock:
            if not self._started:
                return
            self._stop_evt.set()
        # Sentinel: enqueue a None to wake up the drainer if it's blocked
        try:
            self._tick_q.put_nowait(None)
        except Exception:
            pass
        try:
            self._five_min_q.put_nowait(None)
        except Exception:
            pass
        if self._thread is not None:
            self._thread.join(timeout=timeout)
        logger.info(
            f"[LS-WORKER] {self.symbol} worker stopped — "
            f"processed_ticks={self.processed_ticks} processed_5m={self.processed_5m} "
            f"dropped_ticks={self.dropped_ticks} cb_errors={self.tick_callback_errors}/{self.five_min_callback_errors}"
        )
        self._started = False

    # ------------------------------------------------------------------
    # Producer API (called from LS event thread)
    # ------------------------------------------------------------------
    def enqueue_tick(self, payload_args: tuple) -> bool:
        """Enqueue an L1 tick. Returns True if accepted, False if dropped.

        Drop-oldest policy: when the queue is full we lock, drain ONE old
        item, and put the new one. If that race fails we count a drop.
        """
        try:
            self._tick_q.put_nowait(_TickPayload(payload_args))
            return True
        except queue.Full:
            pass

        # Drop-oldest under lock so a concurrent enqueue can't double-evict.
        with self._tick_drop_lock:
            try:
                # Drop one stale tick.
                _ = self._tick_q.get_nowait()
            except queue.Empty:
                pass
            try:
                self._tick_q.put_nowait(_TickPayload(payload_args))
            except queue.Full:
                # Lost the race — count a drop and move on.
                self.dropped_ticks += 1
                return False

        self.dropped_ticks += 1
        # Periodic running-total log so a sustained drop pattern is visible.
        if self.dropped_ticks % 50 == 1:
            logger.warning(
                f"[LS-WORKER] {self.symbol} tick queue overflow — "
                f"running dropped_ticks={self.dropped_ticks} "
                f"depth={self._tick_q.qsize()}/{self._tick_q.maxsize}"
            )
        return True

    def enqueue_5m_close(self, payload_args: tuple) -> bool:
        """Enqueue a 5m-close payload. Drop-none policy: if the queue is
        full we WARN and block the producer briefly. Returns True if
        accepted, False if even the block timeout was hit (very rare)."""
        try:
            self._five_min_q.put_nowait(_FiveMinPayload(payload_args))
            return True
        except queue.Full:
            pass

        self.five_min_block_warnings += 1
        logger.warning(
            f"[LS-WORKER] {self.symbol} 5m queue full "
            f"({self._five_min_q.qsize()}/{self._five_min_q.maxsize}) — "
            f"blocking producer up to {_FIVE_MIN_BLOCK_TIMEOUT_S}s "
            f"(running block_warnings={self.five_min_block_warnings})"
        )
        try:
            self._five_min_q.put(_FiveMinPayload(payload_args), timeout=_FIVE_MIN_BLOCK_TIMEOUT_S)
            return True
        except queue.Full:
            logger.error(
                f"[LS-WORKER] {self.symbol} 5m queue still full after "
                f"{_FIVE_MIN_BLOCK_TIMEOUT_S}s — dropping 5m payload "
                f"(this should not happen in production)"
            )
            return False

    # ------------------------------------------------------------------
    # Observability
    # ------------------------------------------------------------------
    def queue_depth_snapshot(self) -> Dict[str, int]:
        return {
            "tick": self._tick_q.qsize(),
            "5m": self._five_min_q.qsize(),
            "dropped_ticks": self.dropped_ticks,
            "processed_ticks": self.processed_ticks,
            "processed_5m": self.processed_5m,
            "tick_cb_errors": self.tick_callback_errors,
            "5m_cb_errors": self.five_min_callback_errors,
            "5m_block_warnings": self.five_min_block_warnings,
        }

    # ------------------------------------------------------------------
    # Internal: drainer loop
    # ------------------------------------------------------------------
    def _run(self) -> None:
        # Drain priority: 5m-first, then ticks. A 5m close should never
        # wait behind a backlog of L1 ticks.
        while not self._stop_evt.is_set():
            handled_anything = False

            # 5m close: drain ALL pending closes first.
            while True:
                try:
                    item = self._five_min_q.get_nowait()
                except queue.Empty:
                    break
                if item is None:  # shutdown sentinel
                    return
                handled_anything = True
                self._dispatch_5m(item)

            # L1 tick: handle ONE per loop, then re-check the 5m queue.
            try:
                item = self._tick_q.get(timeout=0.05)
            except queue.Empty:
                item = None

            if item is None:
                if not handled_anything:
                    # idle wait — small to keep latency low without burning CPU
                    pass
                continue

            if isinstance(item, _TickPayload):
                self._dispatch_tick(item)

    def _dispatch_tick(self, item: _TickPayload) -> None:
        if self._tick_cb is None:
            return
        t0 = time.time()
        try:
            self._tick_cb(*item.args)
            self.processed_ticks += 1
        except Exception as e:
            self.tick_callback_errors += 1
            logger.error(
                f"[LS-WORKER] {self.symbol} tick callback raised: "
                f"{type(e).__name__}: {e}",
                exc_info=True,
            )
        finally:
            duration_ms = (time.time() - t0) * 1000.0
            with self._durations_lock:
                self._tick_durations.append((t0, duration_ms))

    def _dispatch_5m(self, item: _FiveMinPayload) -> None:
        if self._five_min_cb is None:
            return
        t0 = time.time()
        try:
            self._five_min_cb(*item.args)
            self.processed_5m += 1
        except Exception as e:
            self.five_min_callback_errors += 1
            logger.error(
                f"[LS-WORKER] {self.symbol} 5m callback raised: "
                f"{type(e).__name__}: {e}",
                exc_info=True,
            )
        finally:
            duration_ms = (time.time() - t0) * 1000.0
            with self._durations_lock:
                self._five_min_durations.append((t0, duration_ms))

    # ------------------------------------------------------------------
    # Occupancy gauge — windowed stats over recent callbacks
    # ------------------------------------------------------------------
    def callback_duration_window(self, window_s: float = 60.0) -> Dict[str, Any]:
        """Return invocation/duration stats over the most recent `window_s`
        seconds (default 60s).  Used by the LS-occupancy gauge.

        Empty windows return zeros so the gauge can emit a uniform log line
        regardless of activity.
        """
        cutoff = time.time() - float(window_s)
        with self._durations_lock:
            tick_d = [d for ts, d in self._tick_durations if ts >= cutoff]
            five_d = [d for ts, d in self._five_min_durations if ts >= cutoff]

        def _stats(samples: list) -> Dict[str, float]:
            n = len(samples)
            if n == 0:
                return {"invocations": 0, "total_ms": 0.0, "mean_ms": 0.0, "p99_ms": 0.0}
            total = sum(samples)
            samples_sorted = sorted(samples)
            # nearest-rank p99: index = ceil(0.99 * n) - 1, clamped
            p99_idx = max(0, min(n - 1, int(0.99 * n) - 1 if n >= 100 else n - 1))
            return {
                "invocations": n,
                "total_ms": total,
                "mean_ms": total / n,
                "p99_ms": samples_sorted[p99_idx],
            }

        return {
            "tick": _stats(tick_d),
            "5m": _stats(five_d),
            "window_s": float(window_s),
        }


# ----------------------------------------------------------------------
# Module-level registry
# ----------------------------------------------------------------------

_REGISTRY: Dict[str, PairWorker] = {}
_REGISTRY_LOCK = threading.Lock()
_DEFAULT_TICK_CB: Optional[Callable[..., Any]] = None
_DEFAULT_5M_CB: Optional[Callable[..., Any]] = None


def configure_default_callbacks(
    tick_callback: Optional[Callable[..., Any]] = None,
    five_min_callback: Optional[Callable[..., Any]] = None,
) -> None:
    """Wire the default per-pair callbacks (typically once at startup).

    Workers created via `get_or_create_worker(symbol)` will use these
    callbacks unless they were already created with explicit ones.
    """
    global _DEFAULT_TICK_CB, _DEFAULT_5M_CB
    if tick_callback is not None:
        _DEFAULT_TICK_CB = tick_callback
    if five_min_callback is not None:
        _DEFAULT_5M_CB = five_min_callback


def get_or_create_worker(
    symbol: str,
    tick_callback: Optional[Callable[..., Any]] = None,
    five_min_callback: Optional[Callable[..., Any]] = None,
    queue_size_ticks: int = 100,
    queue_size_5m: int = 10,
) -> PairWorker:
    """Return the registered PairWorker for `symbol`, creating it if
    needed. Idempotent and thread-safe.
    """
    sym = str(symbol).upper()
    with _REGISTRY_LOCK:
        w = _REGISTRY.get(sym)
        if w is not None:
            return w
        w = PairWorker(
            symbol=sym,
            tick_callback=tick_callback or _DEFAULT_TICK_CB,
            five_min_callback=five_min_callback or _DEFAULT_5M_CB,
            queue_size_ticks=queue_size_ticks,
            queue_size_5m=queue_size_5m,
        )
        _REGISTRY[sym] = w
        w.start()
        return w


def get_worker(symbol: str) -> Optional[PairWorker]:
    """Lookup-only — does not create."""
    return _REGISTRY.get(str(symbol).upper())


def all_workers() -> Dict[str, PairWorker]:
    with _REGISTRY_LOCK:
        return dict(_REGISTRY)


def shutdown_all(timeout: float = 5.0) -> None:
    with _REGISTRY_LOCK:
        items = list(_REGISTRY.items())
    for _sym, w in items:
        try:
            w.shutdown(timeout=timeout)
        except Exception as e:
            logger.warning(f"[LS-WORKER] {_sym} shutdown error: {e}")
    with _REGISTRY_LOCK:
        _REGISTRY.clear()


# ----------------------------------------------------------------------
# Depth-gauge daemon
# ----------------------------------------------------------------------

_DEPTH_GAUGE_THREAD: Optional[threading.Thread] = None
_DEPTH_GAUGE_STOP = threading.Event()


def _depth_gauge_loop() -> None:
    while not _DEPTH_GAUGE_STOP.wait(_DEPTH_GAUGE_INTERVAL_S):
        try:
            workers = all_workers()
            if not workers:
                continue
            # Only log queue-depth if there's any non-zero depth.
            non_zero = []
            for sym, w in sorted(workers.items()):
                snap = w.queue_depth_snapshot()
                if snap["tick"] > 0 or snap["5m"] > 0:
                    non_zero.append(f"{sym}=tick:{snap['tick']},5m:{snap['5m']}")
            if non_zero:
                logger.info(f"[LS-WORKER] depth gauge: {' '.join(non_zero)}")

            # Occupancy gauge — emits per-pair callback duration stats over
            # the last 60s. Routed through execution_latency_metrics so the
            # entry point is co-located with the rest of the latency
            # instrumentation (and any operator who greps that file finds
            # the wiring next to the timestamp helpers).
            try:
                from execution_latency_metrics import emit_ls_occupancy_gauge
                emit_ls_occupancy_gauge()
            except Exception as _occ_exc:
                logger.warning(
                    f"[LS-WORKER] occupancy gauge error: {_occ_exc}"
                )
        except Exception as e:
            logger.warning(f"[LS-WORKER] depth gauge error: {e}")


def start_depth_gauge() -> None:
    global _DEPTH_GAUGE_THREAD
    if _DEPTH_GAUGE_THREAD is not None and _DEPTH_GAUGE_THREAD.is_alive():
        return
    _DEPTH_GAUGE_STOP.clear()
    _DEPTH_GAUGE_THREAD = threading.Thread(
        target=_depth_gauge_loop,
        name="PairWorker-DepthGauge",
        daemon=True,
    )
    _DEPTH_GAUGE_THREAD.start()
    logger.info(
        f"[LS-WORKER] depth gauge started (interval={_DEPTH_GAUGE_INTERVAL_S:.0f}s)"
    )


def stop_depth_gauge() -> None:
    _DEPTH_GAUGE_STOP.set()
