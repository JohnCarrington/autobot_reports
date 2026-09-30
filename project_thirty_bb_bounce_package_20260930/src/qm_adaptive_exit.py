"""
qm_adaptive_exit.py — PART 2 (Quiet-Market Session B+)

Per §21.6 and §8.2 of docs/quiet_market_spec_v2.md.

Adaptive opposite-band exit rule for the six in-scope modes:
  GBPUSD_BB_BOUNCE_L, GBPUSD_BB_BOUNCE_S,
  GBPUSD_BB_REV_PAT_L, GBPUSD_BB_REV_PAT_S,
  GBPUSD_BB_REV_L,     GBPUSD_BB_REV_L_S

Pure decision logic — no I/O side effects, no broker calls, no mutation of
external state. Integration site in trade_manager consumes the returned
Decision and executes it (or forwards to legacy).

The rule (§21.6):
  a) On touch: DO NOT exit on touch. If the touch bar itself closes back
     inside the band, exit-on-close-inside (that IS the exit bar).
  b) While consecutive 5m closes remain beyond the band: HOLD
     (band-walk = continuation, §16).
  c) First 5m close back inside after any excursion: EXIT_CLOSE_INSIDE
     (reason = QM_BAND_CLOSE_INSIDE).
  d) QM_ACCEPT_CLOSES consecutive closes beyond + BB expanding →
     PROMOTE_TO_RUNNER (reason = QM_RUNNER_PROMOTED). QM hands exit
     authority to ratchet; QM stands down for the rest of the position.
  e) Kill-switch (QM_ADAPTIVE_EXIT_ENABLED=0) honoured mid-position:
     returns DISABLED_LEGACY so caller reverts to legacy touch-exit.

Single-authority invariants:
  * The RUNNER_PROMOTED state is sticky per position — once set, subsequent
    calls return HANDED_OFF (never re-take authority).
  * On DISABLED_LEGACY, no QM action is taken; caller runs legacy.
  * Original broker SL is NEVER modified by this module. Distance to SL is
    an input; the module returns a decision only.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional, Sequence, Tuple


# Decision enum (strings for JSON serializability)
D_HOLD = "HOLD"
D_EXIT_CLOSE_INSIDE = "EXIT_CLOSE_INSIDE"
D_PROMOTE_TO_RUNNER = "PROMOTE_TO_RUNNER"
D_DISABLED_LEGACY = "DISABLED_LEGACY"
D_HANDED_OFF = "HANDED_OFF"  # QM already handed off to runner; no further action
D_OUT_OF_SCOPE = "OUT_OF_SCOPE"  # mode not in IN_SCOPE_MODES

IN_SCOPE_MODES: Tuple[str, ...] = (
    "GBPUSD_BB_BOUNCE_L", "GBPUSD_BB_BOUNCE_S",
    "GBPUSD_BB_REV_PAT_L", "GBPUSD_BB_REV_PAT_S",
    "GBPUSD_BB_REV_L", "GBPUSD_BB_REV_L_S",
)


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name, "1" if default else "0")
    return str(raw).strip().lower() in ("1", "true", "yes", "on")


def is_in_scope(mode: str) -> bool:
    return str(mode) in IN_SCOPE_MODES


@dataclass
class QmPositionState:
    """Per-position QM state carried across evaluations.

    Owner MUST persist this on the position and pass it in on every eval.
    """
    pos_key: str
    mode: str
    direction: str
    entry_price: float
    # Progressive counters (updated by the caller from consecutive eval calls)
    touched_band: bool = False
    closes_beyond_count: int = 0
    consec_closes_beyond: int = 0
    last_bb_width: Optional[float] = None
    # Sticky handoff — set True the first time PROMOTE_TO_RUNNER fires
    runner_promoted: bool = False


@dataclass
class BarSnapshot:
    """A single 5m evaluation snapshot passed by the caller."""
    ts: str
    open: float
    high: float
    low: float
    close: float
    bb_upper: Optional[float]
    bb_lower: Optional[float]

    def band_price(self, direction: str) -> Optional[float]:
        if direction == "BUY":
            return self.bb_upper
        return self.bb_lower

    def bb_width(self) -> Optional[float]:
        if self.bb_upper is None or self.bb_lower is None:
            return None
        return float(self.bb_upper - self.bb_lower)


@dataclass
class Decision:
    action: str          # one of the D_* constants
    reason: str          # short machine token
    exit_price: Optional[float] = None
    state_after: Optional[QmPositionState] = None
    tags: Dict[str, Any] = field(default_factory=dict)


def _touch(direction: str, bar: BarSnapshot, tol_pips: float) -> bool:
    """Return True if the bar touched the opposite band (within tol_pips)."""
    band = bar.band_price(direction)
    if band is None:
        return False
    if direction == "BUY":
        # touch = high >= band - tol
        return float(bar.high) >= (float(band) - tol_pips)
    return float(bar.low) <= (float(band) + tol_pips)


def _closes_beyond(direction: str, bar: BarSnapshot) -> Optional[bool]:
    band = bar.band_price(direction)
    if band is None:
        return None
    if direction == "BUY":
        return float(bar.close) > float(band)
    return float(bar.close) < float(band)


def _closes_inside(direction: str, bar: BarSnapshot) -> Optional[bool]:
    """Strict: close is on the entry side of the band (or exactly at it)."""
    band = bar.band_price(direction)
    if band is None:
        return None
    if direction == "BUY":
        return float(bar.close) <= float(band)
    return float(bar.close) >= float(band)


def evaluate(state: QmPositionState, bar: BarSnapshot) -> Decision:
    """Compute the next-action decision for this position at this bar.

    Pure function. The caller updates state per the returned state_after
    and then persists it on the position.
    """
    # OUT_OF_SCOPE guard — asserted upstream too, but defensive here.
    if not is_in_scope(state.mode):
        return Decision(action=D_OUT_OF_SCOPE, reason=f"mode_not_in_scope:{state.mode}",
                        state_after=state)

    # Sticky handoff — once PROMOTE fired, QM never re-takes authority.
    if state.runner_promoted:
        return Decision(action=D_HANDED_OFF, reason="qm_stood_down_ratchet_owns",
                        state_after=state)

    # Kill-switch — per-decision read; no restart needed to flip.
    if not _env_flag("QM_ADAPTIVE_EXIT_ENABLED", default=False):
        return Decision(action=D_DISABLED_LEGACY, reason="QM_ADAPTIVE_EXIT_ENABLED=0",
                        state_after=state)

    direction = str(state.direction).upper()
    if direction not in ("BUY", "SELL"):
        return Decision(action=D_DISABLED_LEGACY, reason=f"bad_direction:{state.direction}",
                        state_after=state)

    tol = _env_float("QM_BAND_TOUCH_TOL_PIPS", 1.0)
    accept_n = _env_int("QM_ACCEPT_CLOSES", 2)

    band = bar.band_price(direction)
    if band is None:
        return Decision(action=D_HOLD, reason="no_band_data", state_after=state)

    new_state = QmPositionState(**asdict(state))  # shallow copy

    # Touch bookkeeping
    if not new_state.touched_band and _touch(direction, bar, tol):
        new_state.touched_band = True

    # If we haven't touched yet, nothing to decide.
    if not new_state.touched_band:
        new_state.last_bb_width = bar.bb_width()
        return Decision(action=D_HOLD, reason="pre_touch",
                        state_after=new_state)

    # We're at or past the touch. Look at this bar's close.
    beyond = _closes_beyond(direction, bar)
    inside = _closes_inside(direction, bar)

    # Track close-beyond counters
    if beyond is True:
        new_state.closes_beyond_count += 1
        new_state.consec_closes_beyond += 1
    elif inside is True:
        new_state.consec_closes_beyond = 0

    # PROMOTION check (§21.6.d): N consecutive closes beyond + BB expanding
    bb_now = bar.bb_width()
    bb_expanding = None
    if bb_now is not None and state.last_bb_width is not None:
        bb_expanding = bb_now > state.last_bb_width
    new_state.last_bb_width = bb_now

    if (new_state.consec_closes_beyond >= accept_n and bb_expanding is True):
        new_state.runner_promoted = True
        return Decision(
            action=D_PROMOTE_TO_RUNNER,
            reason="QM_RUNNER_PROMOTED",
            state_after=new_state,
            tags={
                "consec_closes_beyond": new_state.consec_closes_beyond,
                "bb_expanding": True,
                "accept_n": accept_n,
            },
        )

    # EXIT on first 5m close back inside (§21.6.c) — after touch, if this
    # bar closes inside, that's the exit. Applies to the touch bar itself
    # (§21.6.a: touch bar that closes inside IS the exit bar).
    if inside is True:
        return Decision(
            action=D_EXIT_CLOSE_INSIDE,
            reason="QM_BAND_CLOSE_INSIDE",
            exit_price=float(bar.close),
            state_after=new_state,
            tags={
                "band_price": band,
                "closes_beyond_count": new_state.closes_beyond_count,
            },
        )

    # Bar closed beyond → continuation; HOLD (§21.6.b)
    if beyond is True:
        return Decision(
            action=D_HOLD, reason="close_beyond_continuation",
            state_after=new_state,
            tags={
                "consec_closes_beyond": new_state.consec_closes_beyond,
                "bb_expanding": bb_expanding,
            },
        )

    # Fall-through (bar closed exactly at band, or band data glitch)
    return Decision(action=D_HOLD, reason="ambiguous_close_at_band",
                    state_after=new_state)


# ── Watchdog: broker invariant on in-scope open positions ─────────────
# Any in-scope open position MUST carry broker SL + a broker TP (band-level
# legacy OR catastrophic). Violation → returns a WATCHDOG_VIOLATION marker;
# caller must WARN and kill-switch that mode.

@dataclass
class WatchdogResult:
    ok: bool
    reason: str
    mode: Optional[str] = None
    pos_key: Optional[str] = None
    broker_sl: Optional[float] = None
    broker_tp: Optional[float] = None


def watchdog_check(pos_key: str, mode: str,
                   broker_sl: Optional[float],
                   broker_tp: Optional[float]) -> WatchdogResult:
    """Assert that an in-scope open position has both SL and TP at the broker.

    Fail-silent for OUT-OF-SCOPE modes (they never enter QM decision paths).
    """
    if not is_in_scope(mode):
        return WatchdogResult(ok=True, reason="out_of_scope",
                              mode=mode, pos_key=pos_key,
                              broker_sl=broker_sl, broker_tp=broker_tp)
    if broker_sl is None:
        return WatchdogResult(ok=False, reason="MISSING_BROKER_SL",
                              mode=mode, pos_key=pos_key,
                              broker_sl=broker_sl, broker_tp=broker_tp)
    if broker_tp is None:
        return WatchdogResult(ok=False, reason="MISSING_BROKER_TP",
                              mode=mode, pos_key=pos_key,
                              broker_sl=broker_sl, broker_tp=broker_tp)
    return WatchdogResult(ok=True, reason="ok",
                          mode=mode, pos_key=pos_key,
                          broker_sl=broker_sl, broker_tp=broker_tp)


# ── UM TP-strip-and-replace (dormant; only fires if band-level TP present) ─
# For arms that place a band-level broker TP (currently only BB_BOUNCE when
# BB_BOUNCE_RANGE_OPPOSITE_BAND_TP_ENABLED=1 AND RANGE_ROTATION regime).
# Given the audit finding that all 6 modes ship with broker TP == 100p today,
# this is a no-op. Retained as a correctness surface for a future flag flip.

def tp_strip_needed(mode: str, current_tp_pips: Optional[float]) -> bool:
    """Return True if we should strip the current broker TP and replace with
    the QM catastrophic TP. Fires only when:
      * mode is in scope
      * QM_ADAPTIVE_EXIT_ENABLED=1
      * current TP is set AND < QM_UM_CATASTROPHIC_TP_PIPS (i.e. band-level)
    """
    if not is_in_scope(mode):
        return False
    if not _env_flag("QM_ADAPTIVE_EXIT_ENABLED", default=False):
        return False
    if current_tp_pips is None:
        return False
    cat = _env_float("QM_UM_CATASTROPHIC_TP_PIPS", 100.0)
    return float(current_tp_pips) < cat


def catastrophic_tp_pips() -> float:
    return _env_float("QM_UM_CATASTROPHIC_TP_PIPS", 100.0)
