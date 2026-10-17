"""Trade simulation: MFE/MAE + fixed 30/12 TP/SL outcomes.

Honours Stage 0 approved cost model: 0.9 pip spread + 0.5 pip adverse stop
slippage.  Intrabar same-bar TP/SL resolved adversely (SL first).

Entry rules per amendment A2:
  Primary (wick): fill at rejection extreme (bar.high for BUY, bar.low for SELL).
  Secondary (close): fill at confirmation-bar close.

The confirmation bar itself is INCLUDED in the TP/SL scan — if the confirmation
bar continued favorably it could hit TP in the same bar; if it reversed it
could hit SL.  Observation horizon: 288 M5 bars = 24 hours.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.data_io import M5Bar

# Stage 0 approved cost model
SPREAD_PIPS = 0.9
STOP_SLIP_PIPS = 0.5

# Observation horizon
OBSERVATION_BARS = 288   # 24 h of M5

# Model 1 (fixed) parameters per amendment A2 §7
MODEL1_TP_PIPS = 30.0
MODEL1_SL_PIPS = 12.0


@dataclass(frozen=True)
class TradeOutcome:
    exit_ts: Optional[datetime]
    exit_price: Optional[float]
    exit_reason: str          # "TP" | "SL" | "TIMEOUT"
    net_pnl_pips: float       # post-spread, post-slippage
    gross_pnl_pips: float     # pre-cost
    mfe_pips: float           # max favourable excursion (pre-cost)
    mae_pips: float           # max adverse excursion (pre-cost)
    time_to_mfe_min: Optional[float]
    time_to_mae_min: Optional[float]
    bars_held: int
    bars_to_mfe: Optional[int]
    bars_to_mae: Optional[int]
    reached_10p: bool
    reached_15p: bool
    reached_20p: bool
    reached_25p: bool
    reached_30p: bool
    reached_40p: bool
    adverse_before_10p_pips: Optional[float]
    adverse_before_15p_pips: Optional[float]
    adverse_before_20p_pips: Optional[float]
    adverse_before_25p_pips: Optional[float]
    adverse_before_30p_pips: Optional[float]
    adverse_before_40p_pips: Optional[float]


def _milestones() -> List[float]:
    return [10.0, 15.0, 20.0, 25.0, 30.0, 40.0]


def simulate_trade(
    *,
    entry_ts: datetime,
    entry_price: float,
    direction: str,     # "BUY" | "SELL"
    bars_after: List[M5Bar],   # must start at entry bar or later; sorted ascending
    tp_pips: float = MODEL1_TP_PIPS,
    sl_pips: float = MODEL1_SL_PIPS,
    spread_pips: float = SPREAD_PIPS,
    slip_pips: float = STOP_SLIP_PIPS,
    observation_bars: int = OBSERVATION_BARS,
) -> TradeOutcome:
    """Simulate one trade from `entry_ts` using the provided forward M5 bars.

    `bars_after` MUST contain bars with ts >= entry_ts.  The caller is
    responsible for passing enough bars to cover the observation horizon or
    accepting the implied TIMEOUT.
    """
    sign = 1 if direction == "BUY" else -1
    tp_level = entry_price + sign * tp_pips
    sl_level = entry_price - sign * sl_pips

    exit_ts: Optional[datetime] = None
    exit_price: Optional[float] = None
    exit_reason = "TIMEOUT"
    mfe = 0.0
    mae = 0.0
    bars_to_mfe: Optional[int] = None
    bars_to_mae: Optional[int] = None
    bars_held = 0

    reached: Dict[float, bool] = {m: False for m in _milestones()}
    adverse_before: Dict[float, Optional[float]] = {m: None for m in _milestones()}

    for i, bar in enumerate(bars_after[:observation_bars]):
        if bar.ts < entry_ts:
            continue
        bars_held = i + 1

        # Intra-bar favorable / adverse
        fav_touch = (bar.high - entry_price) * sign  # +ve for BUY if high above entry
        adv_touch = (entry_price - bar.low) * sign  # +ve for BUY if low below entry
        if sign == -1:
            # For SELL: fav = entry - bar.low; adv = bar.high - entry
            fav_touch = (entry_price - bar.low)
            adv_touch = (bar.high - entry_price)

        if fav_touch > mfe:
            mfe = fav_touch
            bars_to_mfe = i
        if adv_touch > mae:
            mae = adv_touch
            bars_to_mae = i

        # Track milestones (favourable extent crossed in this bar)
        for m in _milestones():
            if not reached[m] and fav_touch >= m:
                reached[m] = True
                # Record adverse excursion observed up to this bar
                adverse_before[m] = mae

        # Resolve TP / SL (adverse-first within same bar per Stage 0 default)
        if sign > 0:
            sl_hit = bar.low <= sl_level
            tp_hit = bar.high >= tp_level
        else:
            sl_hit = bar.high >= sl_level
            tp_hit = bar.low <= tp_level
        if sl_hit and tp_hit:
            # Both — adverse first
            exit_price = sl_level - sign * slip_pips  # worsen by slippage
            exit_ts = bar.ts
            exit_reason = "SL"
            break
        if sl_hit:
            exit_price = sl_level - sign * slip_pips
            exit_ts = bar.ts
            exit_reason = "SL"
            break
        if tp_hit:
            exit_price = tp_level
            exit_ts = bar.ts
            exit_reason = "TP"
            break

    if exit_price is None and bars_after:
        last = bars_after[min(len(bars_after), observation_bars) - 1]
        exit_price = last.close
        exit_ts = last.ts
        exit_reason = "TIMEOUT"

    if exit_price is None:
        return TradeOutcome(
            exit_ts=None, exit_price=None, exit_reason="NO_DATA",
            net_pnl_pips=0.0, gross_pnl_pips=0.0,
            mfe_pips=0.0, mae_pips=0.0,
            time_to_mfe_min=None, time_to_mae_min=None,
            bars_held=0, bars_to_mfe=None, bars_to_mae=None,
            reached_10p=False, reached_15p=False, reached_20p=False,
            reached_25p=False, reached_30p=False, reached_40p=False,
            adverse_before_10p_pips=None, adverse_before_15p_pips=None,
            adverse_before_20p_pips=None, adverse_before_25p_pips=None,
            adverse_before_30p_pips=None, adverse_before_40p_pips=None,
        )

    gross = (exit_price - entry_price) * sign
    net = gross - spread_pips  # spread is always applied

    return TradeOutcome(
        exit_ts=exit_ts, exit_price=exit_price, exit_reason=exit_reason,
        net_pnl_pips=net, gross_pnl_pips=gross,
        mfe_pips=mfe, mae_pips=mae,
        time_to_mfe_min=(bars_to_mfe * 5.0) if bars_to_mfe is not None else None,
        time_to_mae_min=(bars_to_mae * 5.0) if bars_to_mae is not None else None,
        bars_held=bars_held,
        bars_to_mfe=bars_to_mfe, bars_to_mae=bars_to_mae,
        reached_10p=reached[10.0], reached_15p=reached[15.0],
        reached_20p=reached[20.0], reached_25p=reached[25.0],
        reached_30p=reached[30.0], reached_40p=reached[40.0],
        adverse_before_10p_pips=adverse_before[10.0],
        adverse_before_15p_pips=adverse_before[15.0],
        adverse_before_20p_pips=adverse_before[20.0],
        adverse_before_25p_pips=adverse_before[25.0],
        adverse_before_30p_pips=adverse_before[30.0],
        adverse_before_40p_pips=adverse_before[40.0],
    )
