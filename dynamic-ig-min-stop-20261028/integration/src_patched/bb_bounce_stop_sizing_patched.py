"""
stop_sizing.py — Stop-loss level + stake calculation for BB Bounce.

Two modes:

  FIXED_12       Legacy. Stop at entry ± SL_PIPS; stake = TRADE_SIZE.
  STRUCTURAL_3   New. Stop at min(C1.low,C2.low) − BUFFER (BUY) /
                 max(C1.high,C2.high) + BUFFER (SELL). Stake reduced
                 if the structural stop is wider than SL_PIPS so that
                 initial cash risk ≤ REFERENCE_RISK_POUNDS. Trade is
                 REJECTED (no order submitted) if:
                   - structural distance < IG_MIN_STOP_PIPS, OR
                   - the reduced stake would be < IG_MIN_STAKE.

Returns a `StopPlan` with the full set of values needed to construct
the IG order AND the audit record. If `rejected` is True, the caller
must NOT submit an order.

Research-only in Test 12G/12H established that STRUCTURAL_3 at 3-pip
buffer (B3) is the least-bad stop configuration tested. Default remains
FIXED_12; the operator must flip BB_STOP_MODE explicitly.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

from config import (
    BB_STOP_MODE, STRUCTURAL_BUFFER_PIPS, IG_MIN_STOP_PIPS,
    IG_MIN_STAKE, IG_STAKE_INCREMENT, REFERENCE_RISK_POUNDS,
    SL_PIPS, TP_PIPS, TRADE_SIZE, EPIC,
)
from strategy import Dir


VALID_MODES = ("FIXED_12", "STRUCTURAL_3", "SHADOW")


@dataclass
class StopPlan:
    """Result of plan_stop(). If `rejected` is True, do NOT submit."""
    mode: str
    direction: str
    fill: float
    tp_level: float
    sl_level: float
    stop_distance_pips: float
    stake: float
    initial_cash_risk_pounds: float
    rejected: bool
    rejection_reason: str = ""
    # For audit — the inputs that drove the calculation
    structural_extreme: Optional[float] = None     # min(C1,C2) for BUY etc.
    buffer_pips: float = 0.0
    was_capped_to_reference_risk: bool = False


def _snap_stake(stake: float) -> float:
    """Snap stake DOWN to the IG stake increment (never round up)."""
    if IG_STAKE_INCREMENT <= 0:
        return stake
    # Floor to nearest multiple of IG_STAKE_INCREMENT
    n = math.floor(stake / IG_STAKE_INCREMENT + 1e-9)
    snapped = round(n * IG_STAKE_INCREMENT, 2)
    return max(0.0, snapped)


def plan_stop(
    direction: Dir,
    fill: float,
    c1_low: Optional[float] = None,
    c1_high: Optional[float] = None,
    c2_low: Optional[float] = None,
    c2_high: Optional[float] = None,
    mode: Optional[str] = None,
) -> StopPlan:
    """Compute SL/TP/stake for a given setup.

    Prices are in IG pip-units (same scale as fill, high, low — e.g.
    13216.00 for 1.32160 on GBPUSD). Pip distances are plain numbers
    (e.g. 12 for a 12-pip stop).

    For FIXED_12: C1/C2 extremes are not required.
    For STRUCTURAL_3: C1/C2 extremes ARE required.
    """
    mode = (mode or BB_STOP_MODE).upper()
    if mode not in VALID_MODES:
        raise ValueError(f"invalid BB_STOP_MODE={mode!r}; "
                          f"valid: {VALID_MODES}")

    dir_str = direction.value if isinstance(direction, Dir) else str(direction).upper()

    # --- FIXED_12 (default) ---
    if mode == "FIXED_12":
        if dir_str == "BUY":
            tp_level = fill + TP_PIPS
            sl_level = fill - SL_PIPS
        else:
            tp_level = fill - TP_PIPS
            sl_level = fill + SL_PIPS
        return StopPlan(
            mode="FIXED_12", direction=dir_str, fill=fill,
            tp_level=round(tp_level, 2), sl_level=round(sl_level, 2),
            stop_distance_pips=float(SL_PIPS),
            stake=float(TRADE_SIZE),
            initial_cash_risk_pounds=round(SL_PIPS * TRADE_SIZE, 2),
            rejected=False,
            buffer_pips=0.0,
        )

    # --- STRUCTURAL_3 (and SHADOW uses the same calculator) ---
    if dir_str == "BUY":
        if c1_low is None or c2_low is None:
            return StopPlan(
                mode=mode, direction=dir_str, fill=fill,
                tp_level=0.0, sl_level=0.0, stop_distance_pips=0.0,
                stake=0.0, initial_cash_risk_pounds=0.0,
                rejected=True,
                rejection_reason="MISSING_C1_C2_EXTREMES",
            )
        extreme = min(float(c1_low), float(c2_low))
        sl_level = extreme - STRUCTURAL_BUFFER_PIPS
        stop_distance = fill - sl_level
        tp_level = fill + TP_PIPS
    else:  # SELL
        if c1_high is None or c2_high is None:
            return StopPlan(
                mode=mode, direction=dir_str, fill=fill,
                tp_level=0.0, sl_level=0.0, stop_distance_pips=0.0,
                stake=0.0, initial_cash_risk_pounds=0.0,
                rejected=True,
                rejection_reason="MISSING_C1_C2_EXTREMES",
            )
        extreme = max(float(c1_high), float(c2_high))
        sl_level = extreme + STRUCTURAL_BUFFER_PIPS
        stop_distance = sl_level - fill
        tp_level = fill - TP_PIPS

    stop_distance = round(stop_distance, 2)

    # 2026-10-28 event-driven redesign: no pre-submit API call.
    # Consult only the last-known observation of IG's current minimum
    # (populated after a confirmed broker rejection).  When no
    # observation exists, we still reject sub-static-minimum stops via
    # the import-time IG_MIN_STOP_PIPS (preserves today's behaviour).
    _effective_min = float(IG_MIN_STOP_PIPS)
    _rule_source = "static"
    _obs = None
    try:
        from ig_dealing_rules import last_known_min as _dr_last_known
        _obs = _dr_last_known(EPIC)
        if _obs is not None:
            _effective_min = max(_effective_min, float(_obs.value_pips))
            _rule_source = "observed"
    except Exception:
        pass

    # Reject if below the effective floor.  Never silently widen.
    if stop_distance < _effective_min - 1e-6:
        return StopPlan(
            mode=mode, direction=dir_str, fill=fill,
            tp_level=round(tp_level, 2), sl_level=round(sl_level, 2),
            stop_distance_pips=stop_distance,
            stake=0.0, initial_cash_risk_pounds=0.0,
            rejected=True,
            rejection_reason=(
                f"STOP_TOO_TIGHT ({stop_distance} < {_effective_min}; "
                f"source={_rule_source})"
            ),
            structural_extreme=extreme, buffer_pips=STRUCTURAL_BUFFER_PIPS,
        )

    # Stake sizing: cap at REFERENCE_RISK / stop_distance; never increase.
    desired_stake = float(TRADE_SIZE)
    desired_risk = desired_stake * stop_distance
    was_capped = False
    if desired_risk > REFERENCE_RISK_POUNDS:
        desired_stake = REFERENCE_RISK_POUNDS / stop_distance
        was_capped = True
    stake = _snap_stake(desired_stake)

    # Reject if stake below IG minimum (never silently fall back to a
    # larger stake OR a tighter stop).
    if stake < IG_MIN_STAKE:
        return StopPlan(
            mode=mode, direction=dir_str, fill=fill,
            tp_level=round(tp_level, 2), sl_level=round(sl_level, 2),
            stop_distance_pips=stop_distance,
            stake=0.0, initial_cash_risk_pounds=0.0,
            rejected=True,
            rejection_reason=(
                f"STAKE_BELOW_MIN (desired={desired_stake:.2f}, "
                f"snapped={stake:.2f}, min={IG_MIN_STAKE})"
            ),
            structural_extreme=extreme, buffer_pips=STRUCTURAL_BUFFER_PIPS,
            was_capped_to_reference_risk=was_capped,
        )

    initial_cash_risk = round(stake * stop_distance, 2)
    return StopPlan(
        mode=mode, direction=dir_str, fill=fill,
        tp_level=round(tp_level, 2), sl_level=round(sl_level, 2),
        stop_distance_pips=stop_distance,
        stake=stake, initial_cash_risk_pounds=initial_cash_risk,
        rejected=False,
        structural_extreme=extreme, buffer_pips=STRUCTURAL_BUFFER_PIPS,
        was_capped_to_reference_risk=was_capped,
    )
