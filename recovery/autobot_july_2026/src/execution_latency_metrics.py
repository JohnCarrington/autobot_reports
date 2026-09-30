"""execution_latency_metrics.py — execution-path latency capture helpers.

Pure-additive instrumentation for the LS-thread refactor (PR
`fix/ls-thread-refactor-instrumentation`).  Strategies, the executor,
and the Telegram alert callsites use these helpers to capture
millisecond-epoch timestamps and emit per-trade latency lines that the
analysis script later distils into distributions.

This module is intentionally tiny and import-light — it is loaded inside
`trade_executor.py`, `autobot.py`, and the strategy modules and so must
not pull in heavy deps or perform any I/O at import time.

The LS-thread occupancy gauge is a deferred follow-up (depends on the
`pair_workers` module landing in PR (b)).  The stub here documents the
intended shape so the follow-up commit can fill it in without further
plumbing.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any, Dict, Optional

_log = logging.getLogger("AutoBot")


# ---------------------------------------------------------------------------
# Public timestamp helpers
# ---------------------------------------------------------------------------

def now_epoch_ms() -> int:
    """Wall-clock millisecond epoch.  Used for all latency timestamps.

    All instrumented callsites (decision, dispatch, IG request/ack/confirm,
    exit trigger/dispatch/confirm, telegram dispatch/complete) all live
    in the same Python process so a single monotonic clock isn't
    required — wall-clock ms is more useful in the persisted log because
    it can be correlated with broker logs, audit trails, etc.
    """
    return time.time_ns() // 1_000_000


def ls_async_dispatch_flag() -> int:
    """Read LS_ASYNC_DISPATCH at call time (not module load).

    The post-refactor flag has to be readable on every fire/exit without
    a redeploy of this instrumentation module — strategies will flip it
    on / off at runtime to A/B the new dispatcher.
    """
    raw = os.getenv("LS_ASYNC_DISPATCH", "0") or "0"
    try:
        return 1 if int(raw) else 0
    except (TypeError, ValueError):
        return 0


# ---------------------------------------------------------------------------
# Delta computation helpers (None-safe — any missing input → None delta)
# ---------------------------------------------------------------------------

def _delta_ms(start: Optional[int], end: Optional[int]) -> Optional[int]:
    """Return end-start when both are int-coercible; else None.

    Negative deltas (clock skew, out-of-order capture, etc.) are clamped
    to 0 so summary stats don't get poisoned by a single bad sample.
    """
    if start is None or end is None:
        return None
    try:
        d = int(end) - int(start)
    except (TypeError, ValueError):
        return None
    return max(0, d)


def fire_path_deltas(
    t_decision: Optional[int],
    t_dispatch: Optional[int],
    t_ig_request: Optional[int],
    t_ig_ack: Optional[int],
    t_ig_confirm: Optional[int],
) -> Dict[str, Optional[int]]:
    """Compute the five derived fire-path deltas in ms."""
    return {
        "decision_to_dispatch_ms": _delta_ms(t_decision, t_dispatch),
        "dispatch_to_ig_request_ms": _delta_ms(t_dispatch, t_ig_request),
        "ig_request_to_ack_ms": _delta_ms(t_ig_request, t_ig_ack),
        "ack_to_confirm_ms": _delta_ms(t_ig_ack, t_ig_confirm),
        "total_decision_to_confirm_ms": _delta_ms(t_decision, t_ig_confirm),
    }


def exit_path_deltas(
    t_exit_trigger: Optional[int],
    t_exit_dispatch: Optional[int],
    t_exit_confirm: Optional[int],
) -> Dict[str, Optional[int]]:
    """Compute the three derived exit-path deltas in ms."""
    return {
        "trigger_to_dispatch_ms": _delta_ms(t_exit_trigger, t_exit_dispatch),
        "dispatch_to_confirm_ms": _delta_ms(t_exit_dispatch, t_exit_confirm),
        "total_trigger_to_confirm_ms": _delta_ms(t_exit_trigger, t_exit_confirm),
    }


# ---------------------------------------------------------------------------
# Logging helpers — emit one INFO line per fire / exit / telegram event
# ---------------------------------------------------------------------------

def log_fire_latency(
    *,
    strategy: str,
    pair: str,
    deltas: Dict[str, Optional[int]],
    ls_async_dispatch: int,
) -> None:
    """Single-line FIRE-LATENCY summary for downstream tail-grepping."""
    try:
        _log.info(
            "[FIRE-LATENCY] strategy=%s pair=%s "
            "decision_to_dispatch=%sms dispatch_to_ig_request=%sms "
            "ig_request_to_ack=%sms ack_to_confirm=%sms total=%sms "
            "ls_async_dispatch=%d",
            strategy, pair,
            deltas.get("decision_to_dispatch_ms"),
            deltas.get("dispatch_to_ig_request_ms"),
            deltas.get("ig_request_to_ack_ms"),
            deltas.get("ack_to_confirm_ms"),
            deltas.get("total_decision_to_confirm_ms"),
            ls_async_dispatch,
        )
    except Exception:
        # Logging must never break the fire path.
        pass


def log_exit_latency(
    *,
    strategy: str,
    pair: str,
    deltas: Dict[str, Optional[int]],
    ls_async_dispatch: int,
) -> None:
    """Single-line EXIT-LATENCY summary."""
    try:
        _log.info(
            "[EXIT-LATENCY] strategy=%s pair=%s "
            "trigger_to_dispatch=%sms dispatch_to_confirm=%sms total=%sms "
            "ls_async_dispatch=%d",
            strategy, pair,
            deltas.get("trigger_to_dispatch_ms"),
            deltas.get("dispatch_to_confirm_ms"),
            deltas.get("total_trigger_to_confirm_ms"),
            ls_async_dispatch,
        )
    except Exception:
        pass


def log_tg_latency(
    *,
    event_kind: str,
    pair: str,
    t_event: Optional[int],
    t_dispatch: Optional[int],
    t_complete: Optional[int],
) -> None:
    """Single-line TG-LATENCY summary — log-only (no persistence today)."""
    try:
        _log.info(
            "[TG-LATENCY] event=%s pair=%s "
            "event_to_dispatch=%sms dispatch_to_complete=%sms",
            event_kind, pair,
            _delta_ms(t_event, t_dispatch),
            _delta_ms(t_dispatch, t_complete),
        )
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Schema field bundles — keeps signal_logger.log_open / log_close honest
# ---------------------------------------------------------------------------

FIRE_LATENCY_FIELDS = (
    "t_decision_epoch_ms",
    "t_dispatch_epoch_ms",
    "t_ig_request_epoch_ms",
    "t_ig_ack_epoch_ms",
    "t_ig_confirm_epoch_ms",
    "decision_to_dispatch_ms",
    "dispatch_to_ig_request_ms",
    "ig_request_to_ack_ms",
    "ack_to_confirm_ms",
    "total_decision_to_confirm_ms",
    "ls_async_dispatch",
)

EXIT_LATENCY_FIELDS = (
    "t_exit_trigger_epoch_ms",
    "t_exit_dispatch_epoch_ms",
    "t_exit_confirm_epoch_ms",
    "trigger_to_dispatch_ms",
    "dispatch_to_confirm_ms",
    "total_trigger_to_confirm_ms",
    "ls_async_dispatch",
)


def build_fire_latency_record(
    *,
    t_decision: Optional[int],
    t_dispatch: Optional[int],
    t_ig_request: Optional[int],
    t_ig_ack: Optional[int],
    t_ig_confirm: Optional[int],
    ls_async_dispatch: Optional[int] = None,
) -> Dict[str, Any]:
    """Bundle fire-path timestamps + derived deltas into a dict ready
    for signal_logger.log_open(...).  ls_async_dispatch defaults to the
    env value at call time so the persisted record always reflects the
    runtime mode the trade executed under.
    """
    deltas = fire_path_deltas(
        t_decision, t_dispatch, t_ig_request, t_ig_ack, t_ig_confirm,
    )
    rec: Dict[str, Any] = {
        "t_decision_epoch_ms": t_decision,
        "t_dispatch_epoch_ms": t_dispatch,
        "t_ig_request_epoch_ms": t_ig_request,
        "t_ig_ack_epoch_ms": t_ig_ack,
        "t_ig_confirm_epoch_ms": t_ig_confirm,
        "ls_async_dispatch": (
            int(ls_async_dispatch)
            if ls_async_dispatch is not None
            else ls_async_dispatch_flag()
        ),
    }
    rec.update(deltas)
    return rec


def build_exit_latency_record(
    *,
    t_exit_trigger: Optional[int],
    t_exit_dispatch: Optional[int],
    t_exit_confirm: Optional[int],
    ls_async_dispatch: Optional[int] = None,
) -> Dict[str, Any]:
    """Bundle exit-path timestamps + derived deltas for log_close(...)."""
    deltas = exit_path_deltas(t_exit_trigger, t_exit_dispatch, t_exit_confirm)
    rec: Dict[str, Any] = {
        "t_exit_trigger_epoch_ms": t_exit_trigger,
        "t_exit_dispatch_epoch_ms": t_exit_dispatch,
        "t_exit_confirm_epoch_ms": t_exit_confirm,
        "ls_async_dispatch": (
            int(ls_async_dispatch)
            if ls_async_dispatch is not None
            else ls_async_dispatch_flag()
        ),
    }
    rec.update(deltas)
    return rec


# ---------------------------------------------------------------------------
# LS-thread occupancy gauge — fills in the per-pair callback-duration stats
# now that pair_workers ships on main.
# ---------------------------------------------------------------------------

# Window the gauge looks back over. Match pair_workers' default 60s
# depth-gauge cadence so each emit covers exactly the prior interval.
LS_OCCUPANCY_WINDOW_S = float(os.getenv("LS_OCCUPANCY_WINDOW_S", "60") or 60.0)


def emit_ls_occupancy_gauge() -> None:
    """Emit per-pair LS-callback occupancy stats over the last
    LS_OCCUPANCY_WINDOW_S seconds (default 60).  Wired into the
    `pair_workers._depth_gauge_loop` 60s timer.

    Quiet mode: a pair with zero invocations in the window emits NO
    line — keeps the log clean during off-hours.  Pairs with activity
    emit one INFO line:

        [LS-OCCUPANCY] pair=GBPUSD tick_inv=N tick_total_ms=N
            tick_mean_ms=N tick_p99_ms=N
            5m_inv=N 5m_total_ms=N 5m_mean_ms=N 5m_p99_ms=N
            queue_tick=N queue_5m=N dropped=N
    """
    try:
        import pair_workers  # noqa: WPS433  (deferred import: avoids cycle on instrumentation-only deploys)
    except ImportError:
        return

    workers = pair_workers.all_workers()
    if not workers:
        return

    for sym, w in sorted(workers.items()):
        try:
            stats = w.callback_duration_window(window_s=LS_OCCUPANCY_WINDOW_S)
            depth = w.queue_depth_snapshot()
        except Exception as e:
            _log.warning("[LS-OCCUPANCY] %s: stats fetch failed: %s", sym, e)
            continue

        tick_n = stats["tick"]["invocations"]
        five_n = stats["5m"]["invocations"]
        if tick_n == 0 and five_n == 0:
            continue  # no activity in window — quiet mode

        _log.info(
            "[LS-OCCUPANCY] pair=%s "
            "tick_inv=%d tick_total_ms=%.1f tick_mean_ms=%.2f tick_p99_ms=%.2f "
            "5m_inv=%d 5m_total_ms=%.1f 5m_mean_ms=%.2f 5m_p99_ms=%.2f "
            "queue_tick=%d queue_5m=%d dropped=%d",
            sym,
            tick_n, stats["tick"]["total_ms"], stats["tick"]["mean_ms"], stats["tick"]["p99_ms"],
            five_n, stats["5m"]["total_ms"], stats["5m"]["mean_ms"], stats["5m"]["p99_ms"],
            depth["tick"], depth["5m"], depth["dropped_ticks"],
        )
