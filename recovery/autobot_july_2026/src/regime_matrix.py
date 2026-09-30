"""Regime Matrix — single owner of strategy enablement per (symbol × effective_regime).

Phase 2. Consumes the Phase 1 engine's per-bar winning_regime (after ladder
and floor) and applies entry hysteresis: a raw label must hold for
REGIME_MATRIX_DWELL_N consecutive bars before effective_regime changes.
One fast lane: a confirmed range-break promotion (regime engine flags
range_break_promoted + range_exit_breakout on the same bar) updates
effective_regime immediately without waiting for the dwell counter.

Matrix decides WHETHER a strategy runs, never WHAT its setup is.
Gates NEW FIRES ONLY — open positions are never closed by an enablement
change (that is the exit path's concern; see trade_manager for the
range-scalp rework).

Master flag REGIME_MATRIX_ENABLED (env, default 0). When 0 the module is
a no-op: permits() returns True unconditionally, update() writes no state,
callbacks are not fired.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, timezone
from typing import Callable, Dict, FrozenSet, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ── Env constants ─────────────────────────────────────────────────────────

def _env_bool(name: str, default: str = "0") -> bool:
    return (os.getenv(name, default) or default).strip().lower() in ("1", "true", "yes", "on")


REGIME_MATRIX_ENABLED = _env_bool("REGIME_MATRIX_ENABLED", "0")
REGIME_MATRIX_DWELL_N = int(float(os.getenv("REGIME_MATRIX_DWELL_N", "3") or 3))
REGIME_MATRIX_LOG_PATH = os.getenv(
    "REGIME_MATRIX_LOG_PATH", "logs/regime_matrix.jsonl"
)
# Exhausted-trend fade window — HISTORICAL. Introduced b237921 to
# additionally permit BB_BOUNCE_L/S in the four trend regimes when the
# engine's hist_freshness_fail_count reached the streak floor OR raw label
# diverged from effective; extended 4ee95a9 with the h1_decel_streak
# disjunct. 2026-07-09 amendment REMOVED all three disjuncts from the
# permission path — BB_BOUNCE is now table-permitted unconditionally in
# the four trend regimes AND RANGE_ROTATION. The env flag survives so
# jsonl consumers keep seeing a stable schema; setting it to 0 has NO
# functional effect on permits() any more.
REGIME_MATRIX_EXHAUSTED_FADE_ENABLED = _env_bool(
    "REGIME_MATRIX_EXHAUSTED_FADE_ENABLED", "1"
)
REGIME_MATRIX_EXHAUST_STREAK_MIN = int(
    float(os.getenv("REGIME_MATRIX_EXHAUST_STREAK_MIN", "1") or 1)
)
# 2026-07-09 — decel disjunct. When the engine's h1_decel_streak reaches
# this floor the current trend regime is considered exhausted regardless
# of the ADX/DI streak or raw/effective divergence. Feeds the SAME
# exhausted() surface permits() reads to open BB_BOUNCE_L/S.
REGIME_MATRIX_EXHAUST_DECEL_MIN = int(
    float(os.getenv("REGIME_MATRIX_EXHAUST_DECEL_MIN", "2") or 2)
)
# Null-alarm streak floor (2026-07-09). If the engine hands us N consecutive
# null labels for a symbol, permits() is permanently fail-closed for that
# symbol — no strategy can fire. Fires ONCE at the crossing bar (streak==N)
# and then again every N bars while the streak stays above the floor; resets
# to 0 the first bar a real label arrives. Kept env-tunable so an ops override
# can silence it during an intentional stand-down, but the default (5) is
# tight enough that a contract regression like a8148ee screams within one
# 25-minute window instead of hiding in suppression rows.
REGIME_MATRIX_NULL_ALARM_N = int(
    float(os.getenv("REGIME_MATRIX_NULL_ALARM_N", "5") or 5)
)
# Per-bar wait timeout (seconds). Strategy callbacks call wait_for_bar()
# before permits() so they read fresh matrix state; if the engine pool
# hasn't finished the bar's update within this budget, they fall back to
# whatever state is present and a WARN is logged. Default 2.0s — 300× the
# measured mean cost of engine.emit() + matrix.update() (~6.6 ms), so this
# only trips on real pool congestion.
REGIME_MATRIX_WAIT_TIMEOUT_S = float(
    os.getenv("REGIME_MATRIX_WAIT_TIMEOUT_S", "2.0") or 2.0
)
# Bounded per-symbol event cache — how many recent bars to keep events for.
# Pruned on each event creation. 6 is generous (30 minutes at 5m cadence).
_BAR_EVENT_KEEP_N = int(
    float(os.getenv("REGIME_MATRIX_BAR_EVENT_KEEP", "6") or 6)
)

# ── Enablement table ─────────────────────────────────────────────────────
# Keyed by effective_regime string. Any regime not listed → empty (fail-closed).

_LONGS_TREND = frozenset({
    "GBPUSD_EMA_PULLBACK_L",
    "GBPUSD_TREND_V3_L",
    "GBPUSD_STRUCTURE_BREAK_L",
    "GBPUSD_CONFIRMATION_FALLBACK_L",
})
_SHORTS_TREND = frozenset({
    "GBPUSD_EMA_PULLBACK_S",
    "GBPUSD_TREND_V3_S",
    "GBPUSD_STRUCTURE_BREAK_S",
    "GBPUSD_CONFIRMATION_FALLBACK_S",
})
_RANGE_MODES = frozenset({
    "GBPUSD_BB_BOUNCE_L",
    "GBPUSD_BB_BOUNCE_S",
})

# 2026-07-09 amendment supersedes b237921 + 4ee95a9. Operator design:
# BB_BOUNCE is NEVER regime-gated except CHOP/UNKNOWN — the strategy's
# own geometry (band pierce + rejection + velocity guard + STRONG_TREND
# fade stand-down) already discriminates on trend context. The matrix
# selects EXIT MANAGEMENT only via the Phase 3 profile stamp
# (trade_executor._stamp_profile_at_fire :298-328) and the
# gbpusd_bb_bounce.py TP path RANGE_ROTATION branch (:1422-1517):
#   STRONG_TREND_*  → profile_id="STRONG"  (STRONG trail manager)
#   TREND_FORMING_* → profile_id="FORMING" (FORMING TP ladder)
#   RANGE_ROTATION  → profile_id="RANGE"   (opposite-band TP + range scalp)
#   CHOP / None     → profile_id="LEGACY"  (BB fire blocked here anyway)
# BB_BOUNCE_L/S therefore appear in the permitted set for all four trend
# regimes AND RANGE_ROTATION. Only CHOP + unknown remain empty
# (fail-closed).
_TREND_LONGS_WITH_BB = _LONGS_TREND | _RANGE_MODES
_TREND_SHORTS_WITH_BB = _SHORTS_TREND | _RANGE_MODES

MATRIX: Dict[str, FrozenSet[str]] = {
    "RANGE_ROTATION":    _RANGE_MODES,
    "TREND_FORMING_UP":  _TREND_LONGS_WITH_BB,
    "TREND_FORMING_DOWN":_TREND_SHORTS_WITH_BB,
    "STRONG_TREND_UP":   _TREND_LONGS_WITH_BB,
    "STRONG_TREND_DOWN": _TREND_SHORTS_WITH_BB,
}
_TREND_REGIMES = frozenset({
    "TREND_FORMING_UP", "TREND_FORMING_DOWN",
    "STRONG_TREND_UP",  "STRONG_TREND_DOWN",
})
_EMPTY: FrozenSet[str] = frozenset()

# ── Per-symbol state ─────────────────────────────────────────────────────
# `effective_regime` starts as None (never dispatched) — treated as
# fail-closed until the first update() call. Dwell counter tracks how many
# consecutive bars the `pending_raw` candidate has held; when it reaches
# REGIME_MATRIX_DWELL_N the pending value is promoted to effective.

_state_lock = threading.Lock()
_state: Dict[str, Dict[str, object]] = {}

# Per-symbol per-bar event registry (2026-07-09). The engine callback runs
# on a dedicated pool worker (_regime_engine_pool), while strategy callbacks
# run sequentially on the main 5M-close chain a few callbacks later. Before
# today the strategies raced the pool — permits() could read pre-transition
# state (see 2026-07-09T07:30 GBPUSD: transition_dwell fired at :00.871130Z,
# 1ms AFTER the six strategy suppressions at :00.844-.870). The event key is
# (symbol, bucket_epoch). mark_bar_processed() sets it after matrix.update()
# completes for that bar; wait_for_bar() blocks with a bounded timeout.
_bar_events_lock = threading.Lock()
_bar_events: Dict[str, Dict[int, threading.Event]] = {}

def _sym(symbol: Optional[str]) -> str:
    return str(symbol or "").upper() or "GBPUSD"

def _get_state(symbol: str) -> Dict[str, object]:
    return _state.setdefault(_sym(symbol), {
        "effective": None,           # str | None
        "pending_raw": None,         # str | None (dwell candidate)
        "dwell": 0,                  # int
        "last_raw": None,            # str | None
        "exhausted": False,          # bool (amendment: bar-current)
        "exhaust_streak": 0,         # int (last fail_count seen)
        "exhaust_raw_divergence": False,  # bool (raw != effective this bar)
        "exhaust_decel_streak": 0,   # int (last h1_decel_streak seen)
        "null_streak": 0,            # int (2026-07-09 alarm counter)
    })

# ── On-suppress callbacks ────────────────────────────────────────────────
# Fires when a mode leaves the permitted set on an effective_regime
# transition. CONFIRMATION_FALLBACK registers a disarm hook — see
# gbpusd_confirmation_fallback.py — so armed multi-bar setups do not
# survive across regimes in which the strategy no longer runs. Any
# strategy with cross-bar setup state may register the same way.

_on_suppress: Dict[str, List[Callable[[str], None]]] = {}

def register_on_suppress(mode: str, callback: Callable[[str], None]) -> None:
    """Register a callback to fire when `mode` leaves the permitted set on
    an effective-regime transition. Called with (symbol).

    Safe to call at any point; multiple callbacks per mode are supported.
    No-op when REGIME_MATRIX_ENABLED=0 (registration succeeds but callbacks
    never fire because update() is a no-op).
    """
    _on_suppress.setdefault(mode, []).append(callback)

def _fire_on_suppress(symbol: str, mode: str) -> None:
    for cb in _on_suppress.get(mode, ()):
        try:
            cb(symbol)
            _log({
                "event": "disarm_fired",
                "symbol": symbol,
                "mode": mode,
            })
        except Exception as exc:
            _log({
                "event": "disarm_callback_error",
                "symbol": symbol,
                "mode": mode,
                "error": repr(exc),
            })

# ── JSONL logging ────────────────────────────────────────────────────────

def _log(row: Dict[str, object]) -> None:
    row.setdefault("ts_utc", datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ"))
    try:
        os.makedirs(os.path.dirname(REGIME_MATRIX_LOG_PATH) or ".", exist_ok=True)
        with open(REGIME_MATRIX_LOG_PATH, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, default=str) + "\n")
    except Exception:
        # Telemetry must never break the trade path. Silent drop.
        pass

# ── Public API ───────────────────────────────────────────────────────────

def update(
    symbol: str,
    raw_regime: Optional[str],
    *,
    range_break_promoted: bool = False,
    range_exit_breakout: bool = False,
    regime_label_path: Optional[str] = None,
    hist_freshness_fail_count: int = 0,
    h1_decel_streak: int = 0,
) -> Optional[str]:
    """Apply per-bar hysteresis and return the current effective_regime.

    - No-op returning None when REGIME_MATRIX_ENABLED=0.
    - Fast lane: `range_break_promoted AND range_exit_breakout` promotes the
      raw label to effective_regime immediately (no dwell). This matches
      the Phase 1 engine's own promotion path and gates the fast lane
      behind BOTH signals so a stale flag on one side cannot trigger it.
    - Dwell: otherwise, the raw label must hold for REGIME_MATRIX_DWELL_N
      consecutive bars before it becomes effective.
    - Transition callbacks: on any effective change, any mode that leaves
      the permitted set fires its registered on-suppress callbacks.
    - Exhaustion (telemetry only, 2026-07-09): still computed per bar
      from hist_freshness_fail_count, raw-vs-effective divergence, and
      h1_decel_streak so calibration downstream can join on these signals.
      permits() no longer reads them — the b237921 fade window and the
      4ee95a9 decel disjunct are both SUPERSEDED by unconditional
      BB_BOUNCE_L/S in the four trend regimes.
    """
    if not REGIME_MATRIX_ENABLED:
        return None

    sym = _sym(symbol)
    raw = str(raw_regime or "").upper() or None
    streak = int(hist_freshness_fail_count or 0)
    decel_streak = int(h1_decel_streak or 0)

    with _state_lock:
        st = _get_state(sym)
        old_effective = st.get("effective")
        st["last_raw"] = raw

        # Null-alarm accounting (2026-07-09). raw==None means the engine
        # handed us nothing usable — that could be a legitimate warm-up bar
        # OR a broken emit→matrix contract like a8148ee. Reset on any real
        # label so a transient warm-up never trips the alarm; cross the
        # floor and we log at ERROR because permits() is permanently {}.
        if raw is None:
            st["null_streak"] = int(st.get("null_streak") or 0) + 1
            _ns = int(st["null_streak"])
            if REGIME_MATRIX_NULL_ALARM_N > 0 and _ns >= REGIME_MATRIX_NULL_ALARM_N \
                    and _ns % REGIME_MATRIX_NULL_ALARM_N == 0:
                logger.error(
                    "[REGIME_MATRIX] %s: %d consecutive null labels from "
                    "engine — matrix is fail-closed, no strategy can fire",
                    sym, _ns,
                )
                _log({
                    "event": "null_alarm",
                    "symbol": sym,
                    "null_streak": _ns,
                    "alarm_floor": REGIME_MATRIX_NULL_ALARM_N,
                })
        else:
            st["null_streak"] = 0

        event = "bar"
        transitioned = False

        # Fast lane — confirmed range-break promotion. Immediate update.
        fast_lane = bool(range_break_promoted and range_exit_breakout and raw)
        if fast_lane:
            st["effective"] = raw
            st["pending_raw"] = None
            st["dwell"] = 0
            event = "fast_lane"
            transitioned = True
        else:
            # Dwell path.
            if raw is None:
                st["pending_raw"] = None
                st["dwell"] = 0
            elif raw == old_effective:
                st["pending_raw"] = None
                st["dwell"] = 0
            elif raw == st.get("pending_raw"):
                st["dwell"] = int(st.get("dwell") or 0) + 1
                if int(st["dwell"]) >= REGIME_MATRIX_DWELL_N:
                    st["effective"] = raw
                    st["pending_raw"] = None
                    st["dwell"] = 0
                    event = "transition_dwell"
                    transitioned = True
            else:
                st["pending_raw"] = raw
                st["dwell"] = 1

        # Exhaustion — recomputed each bar against post-transition effective.
        # 2026-07-09: third disjunct — h1_decel_streak >=
        # REGIME_MATRIX_EXHAUST_DECEL_MIN. Opens BB_BOUNCE_S/L in permits()
        # via the same _RANGE_MODES escape hatch used by streak / divergence.
        new_effective = st.get("effective")
        eff_str = str(new_effective or "")
        raw_divergence = bool(raw is not None and eff_str and raw != eff_str)
        decel_open = bool(
            REGIME_MATRIX_EXHAUST_DECEL_MIN > 0
            and decel_streak >= REGIME_MATRIX_EXHAUST_DECEL_MIN
        )
        exhausted = bool(
            REGIME_MATRIX_EXHAUSTED_FADE_ENABLED
            and eff_str in _TREND_REGIMES
            and (streak >= REGIME_MATRIX_EXHAUST_STREAK_MIN
                 or raw_divergence
                 or decel_open)
        )
        st["exhausted"] = exhausted
        st["exhaust_streak"] = streak
        st["exhaust_raw_divergence"] = raw_divergence
        st["exhaust_decel_streak"] = decel_streak

        # Telemetry — one row per bar; event distinguishes transitions.
        row: Dict[str, object] = {
            "event": event,
            "symbol": sym,
            "raw": raw,
            "effective": new_effective,
            "pending_raw": st.get("pending_raw"),
            "dwell": st.get("dwell"),
            "regime_label_path": regime_label_path,
            "range_break_promoted": bool(range_break_promoted),
            "range_exit_breakout": bool(range_exit_breakout),
            "exhausted": exhausted,
            "exhaust_streak": streak,
            "exhaust_raw_divergence": raw_divergence,
            "exhaust_decel_streak": decel_streak,
        }
        if event == "fast_lane":
            row["old_effective"] = old_effective
            row["new_effective"] = new_effective
            row["reason"] = "range_break_promote_confirmed"
        elif event == "transition_dwell":
            row["old_effective"] = old_effective
            row["new_effective"] = new_effective
            row["dwell_n"] = REGIME_MATRIX_DWELL_N
        _log(row)

        if transitioned:
            _emit_transition_callbacks(sym, old_effective, new_effective)
        return new_effective

def _get_or_create_bar_event(symbol: str, bucket_epoch: int) -> threading.Event:
    """Return the Event for (symbol, bucket_epoch), creating it if absent.
    Prunes older-than-N buckets so the map stays bounded.
    """
    sym = _sym(symbol)
    with _bar_events_lock:
        d = _bar_events.setdefault(sym, {})
        ev = d.get(bucket_epoch)
        if ev is None:
            ev = threading.Event()
            d[bucket_epoch] = ev
            if len(d) > _BAR_EVENT_KEEP_N:
                keep = set(sorted(d.keys())[-_BAR_EVENT_KEEP_N:])
                for k in list(d.keys()):
                    if k not in keep:
                        d.pop(k, None)
        return ev


def mark_bar_processed(symbol: str, bucket_epoch: Optional[int]) -> None:
    """Signal that the matrix has finished processing the bar identified by
    `bucket_epoch` for `symbol`. Idempotent. MUST be called even on error
    paths (engine emit raises, update raises, engine callback bails early)
    so waiting strategy callbacks unblock instead of timing out every bar.

    No-op when REGIME_MATRIX_ENABLED=0 or bucket_epoch is None.
    """
    if not REGIME_MATRIX_ENABLED or bucket_epoch is None:
        return
    try:
        ev = _get_or_create_bar_event(symbol, int(bucket_epoch))
        ev.set()
    except Exception as exc:
        # Setting an Event should not fail, but if the map got trashed we
        # would rather log and let strategies fall through on timeout than
        # raise out of the pool worker.
        logger.warning("[REGIME_MATRIX] mark_bar_processed failed for %s "
                       "bucket=%s: %s", _sym(symbol), bucket_epoch, exc)


def wait_for_bar(symbol: str, bucket_epoch: Optional[int],
                 timeout: Optional[float] = None) -> bool:
    """Block until the matrix has processed the bar identified by
    `bucket_epoch` for `symbol`, or `timeout` seconds pass.

    Returns True if the bar was processed within the timeout, False if it
    timed out. On timeout a WARN is logged; the caller should proceed with
    the current (potentially stale) state rather than deadlock.

    No-op returning True when REGIME_MATRIX_ENABLED=0 or bucket_epoch is
    None — flag-off behaviour must remain byte-identical to pre-2026-07-09.
    """
    if not REGIME_MATRIX_ENABLED or bucket_epoch is None:
        return True
    t = float(timeout if timeout is not None else REGIME_MATRIX_WAIT_TIMEOUT_S)
    ev = _get_or_create_bar_event(symbol, int(bucket_epoch))
    got = ev.wait(timeout=t)
    if not got:
        logger.warning(
            "[REGIME_MATRIX] %s: bar %d update did not complete within %.2fs "
            "— strategy will read stale effective_regime for this bar",
            _sym(symbol), int(bucket_epoch), t,
        )
        _log({
            "event": "bar_wait_timeout",
            "symbol": _sym(symbol),
            "bucket_epoch": int(bucket_epoch),
            "timeout_s": t,
        })
    return got


def _emit_transition_callbacks(symbol: str, old_effective, new_effective) -> None:
    old_set = MATRIX.get(str(old_effective or ""), _EMPTY)
    new_set = MATRIX.get(str(new_effective or ""), _EMPTY)
    removed = old_set - new_set
    for mode in removed:
        _fire_on_suppress(symbol, mode)

def effective_regime(symbol: str) -> Optional[str]:
    """Return the current effective_regime for `symbol`, or None if the
    matrix has not seen a bar for it yet. No-op returning None when the
    flag is off.
    """
    if not REGIME_MATRIX_ENABLED:
        return None
    with _state_lock:
        st = _state.get(_sym(symbol))
        return None if st is None else st.get("effective")  # type: ignore[return-value]

def permits(symbol: str, mode: str) -> bool:
    """Return True iff `mode` is in the permitted set for `symbol`'s
    current effective_regime. Fail-closed on unknown regime (empty set).

    No-op returning True when REGIME_MATRIX_ENABLED=0, so call sites can
    unconditionally guard dispatch behind `if not permits(...): return`
    with byte-identical behaviour when the flag is off.

    2026-07-09 amendment — SUPERSEDES the b237921 exhausted-trend fade
    window and the 4ee95a9 decel disjunct. Both previously extended the
    permitted set with BB_BOUNCE_L/S when `st["exhausted"]` was true;
    that entire escape hatch is REMOVED. BB_BOUNCE is now table-permitted
    unconditionally in the four trend regimes AND RANGE_ROTATION — see
    the MATRIX comment above. Exhaustion telemetry
    (exhausted, exhaust_streak, exhaust_raw_divergence,
    exhaust_decel_streak) is still cached on state and written to the
    jsonl + suppression rows for calibration, but it GATES NOTHING.
    """
    if not REGIME_MATRIX_ENABLED:
        return True
    with _state_lock:
        st = _state.get(_sym(symbol))
        eff = None if st is None else st.get("effective")
    permitted = MATRIX.get(str(eff or ""), _EMPTY)
    return mode in permitted

def log_suppression(symbol: str, mode: str) -> None:
    """Record a dispatch suppression. Called from the six autobot.py choke
    points when permits() returns False. Cheap and safe (never raises).
    """
    if not REGIME_MATRIX_ENABLED:
        return
    with _state_lock:
        st = _state.get(_sym(symbol))
        eff = None if st is None else st.get("effective")
        exhausted = bool(st.get("exhausted")) if st else False
        streak = int(st.get("exhaust_streak") or 0) if st else 0
        decel = int(st.get("exhaust_decel_streak") or 0) if st else 0
    _log({
        "event": "dispatch_suppressed",
        "symbol": _sym(symbol),
        "mode": mode,
        "effective_regime": eff,
        "permitted_set": sorted(MATRIX.get(str(eff or ""), _EMPTY)),
        "exhausted": exhausted,
        "exhaust_streak": streak,
        "exhaust_decel_streak": decel,
    })

# ── Test-only helpers ────────────────────────────────────────────────────
# Not for production use; the state store is process-local and tests reset
# it between cases.

def _reset_state_for_tests() -> None:
    with _state_lock:
        _state.clear()
        _on_suppress.clear()
    with _bar_events_lock:
        _bar_events.clear()
