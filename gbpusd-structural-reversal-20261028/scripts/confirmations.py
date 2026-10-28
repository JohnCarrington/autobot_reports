"""Six confirmation events for structural-level reversals.

The brief defines six confirmations:

  CF1 — First touch (bar reaches tolerance).  Entry at the event bar's
        close.
  CF2 — First rejection close: first bar after approach whose close
        is on the ORIGINAL side (BELOW the level for UPPER approach;
        ABOVE for LOWER).
  CF3 — First sweep-and-reclaim: a bar pierces the level by >
        MAX_WICK_PEN then a subsequent bar closes back on the
        original side.  Entry = reclaim bar's close.
  CF4 — First countertrend displacement: first bar after approach
        with body > 5 p in the reversal direction (BULL/UPPER-reject
        = red body; LOWER-reject = green body).  Entry = that bar's
        close.
  CF5 — First break of a nearby minor swing: entry when price breaks
        the previous confirmed M5 swing in the REVERSAL direction.
        Minor swing = fractal (K=2) swings younger than 2 hours.
  CF6 — First retest after rejection: after CF2 fires, price revisits
        within TOUCH_TOL_PIPS of the level again.  Entry = that bar's
        close.

Each returns ``(idx, close, dist_from_level, bars_from_event)`` or
``(None, …)`` if the event did not occur within RESPONSE_HORIZON_BARS.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from common import Bar
from events import (
    Event, TOUCH_TOL_PIPS, MAX_WICK_PENETRATION,
    RESPONSE_HORIZON_BARS, SESSION_START_UK, SESSION_END_UK,
)


MINOR_SWING_K = 2       # 2-bar left/right fractal for minor swings
MINOR_SWING_MAX_AGE_BARS = 24   # minor swing valid only within 2h

CF4_BODY_MIN_PTS = 5.0


def _dist_from_level(close: float, level: float, side: str) -> float:
    """Signed distance of close from level, positive on the reversal side."""
    if side == "UPPER":
        return level - close
    return close - level


def confirm_CF1(bars: list[Bar], ev: Event) -> tuple[int, float, float, int]:
    """First touch = the event bar itself."""
    i = ev.event_bar_idx
    close = bars[i].close
    return (i, close, _dist_from_level(close, ev.level_price, ev.approach_side), 0)


def confirm_CF2(bars, ev):
    i0 = ev.event_bar_idx
    end = min(i0 + RESPONSE_HORIZON_BARS, len(bars) - 1)
    for i in range(i0, end + 1):
        c = bars[i].close
        if ev.approach_side == "UPPER" and c < ev.level_price:
            return (i, c, _dist_from_level(c, ev.level_price, ev.approach_side), i - i0)
        if ev.approach_side == "LOWER" and c > ev.level_price:
            return (i, c, _dist_from_level(c, ev.level_price, ev.approach_side), i - i0)
    return (None, None, None, None)


def confirm_CF3(bars, ev):
    i0 = ev.event_bar_idx
    end = min(i0 + RESPONSE_HORIZON_BARS, len(bars) - 1)
    pierced_at: int | None = None
    for i in range(i0, end + 1):
        b = bars[i]
        if pierced_at is None:
            if ev.approach_side == "UPPER" and b.high > ev.level_price + MAX_WICK_PENETRATION:
                pierced_at = i
            elif ev.approach_side == "LOWER" and b.low < ev.level_price - MAX_WICK_PENETRATION:
                pierced_at = i
            continue
        # already pierced; look for reclaim close
        if ev.approach_side == "UPPER" and b.close < ev.level_price:
            return (i, b.close, _dist_from_level(b.close, ev.level_price, ev.approach_side), i - i0)
        if ev.approach_side == "LOWER" and b.close > ev.level_price:
            return (i, b.close, _dist_from_level(b.close, ev.level_price, ev.approach_side), i - i0)
    return (None, None, None, None)


def confirm_CF4(bars, ev):
    i0 = ev.event_bar_idx
    end = min(i0 + RESPONSE_HORIZON_BARS, len(bars) - 1)
    for i in range(i0 + 1, end + 1):
        b = bars[i]
        if ev.approach_side == "UPPER" and b.is_red and b.body > CF4_BODY_MIN_PTS:
            return (i, b.close, _dist_from_level(b.close, ev.level_price, ev.approach_side), i - i0)
        if ev.approach_side == "LOWER" and b.is_green and b.body > CF4_BODY_MIN_PTS:
            return (i, b.close, _dist_from_level(b.close, ev.level_price, ev.approach_side), i - i0)
    return (None, None, None, None)


def _minor_swings(bars, i_now):
    """Return list of (idx, 'H'|'L', price) of minor-fractal swings
    confirmed before i_now and younger than MINOR_SWING_MAX_AGE_BARS."""
    K = MINOR_SWING_K
    out = []
    lo = max(K, i_now - MINOR_SWING_MAX_AGE_BARS - K)
    for i in range(lo, i_now - K):
        is_sh = all(bars[j].high < bars[i].high for j in range(i - K, i)) \
            and all(bars[j].high < bars[i].high for j in range(i + 1, i + K + 1))
        is_sl = all(bars[j].low > bars[i].low for j in range(i - K, i)) \
            and all(bars[j].low > bars[i].low for j in range(i + 1, i + K + 1))
        confirmed_at = i + K
        if confirmed_at >= i_now:
            continue
        if is_sh:
            out.append((i, "H", bars[i].high))
        if is_sl:
            out.append((i, "L", bars[i].low))
    return out


def confirm_CF5(bars, ev):
    """First bar whose close breaks the most relevant recent minor-swing
    on the REVERSAL side.
       UPPER approach (resistance) → reversal = DOWN, we need close
       below a recent minor swing low (the "support" the pullback is
       trying to break).  Equivalent: for LOWER approach, break of
       recent minor swing high above.
    """
    i0 = ev.event_bar_idx
    end = min(i0 + RESPONSE_HORIZON_BARS, len(bars) - 1)
    swings = _minor_swings(bars, i0)
    if ev.approach_side == "UPPER":
        swing_lows = [s for s in swings if s[1] == "L"]
        if not swing_lows:
            return (None, None, None, None)
        target = max(swing_lows, key=lambda s: s[2])[2]  # closest below
        for i in range(i0 + 1, end + 1):
            if bars[i].close < target:
                return (i, bars[i].close,
                        _dist_from_level(bars[i].close, ev.level_price, ev.approach_side),
                        i - i0)
    else:
        swing_highs = [s for s in swings if s[1] == "H"]
        if not swing_highs:
            return (None, None, None, None)
        target = min(swing_highs, key=lambda s: s[2])[2]
        for i in range(i0 + 1, end + 1):
            if bars[i].close > target:
                return (i, bars[i].close,
                        _dist_from_level(bars[i].close, ev.level_price, ev.approach_side),
                        i - i0)
    return (None, None, None, None)


def confirm_CF6(bars, ev):
    """After CF2 fires, wait for the price to retest the level within
    TOUCH_TOL_PIPS again (same approach side), then entry at that
    bar's close."""
    cf2_i, cf2_c, _, _ = confirm_CF2(bars, ev)
    if cf2_i is None:
        return (None, None, None, None)
    end = min(ev.event_bar_idx + RESPONSE_HORIZON_BARS, len(bars) - 1)
    for i in range(cf2_i + 1, end + 1):
        b = bars[i]
        dist = min(abs(b.high - ev.level_price), abs(b.low - ev.level_price))
        if dist > TOUCH_TOL_PIPS:
            continue
        if ev.approach_side == "UPPER":
            prev_close = bars[i - 1].close
            if prev_close < ev.level_price:  # genuine new approach from below
                return (i, b.close, _dist_from_level(b.close, ev.level_price, ev.approach_side),
                        i - ev.event_bar_idx)
        else:
            prev_close = bars[i - 1].close
            if prev_close > ev.level_price:
                return (i, b.close, _dist_from_level(b.close, ev.level_price, ev.approach_side),
                        i - ev.event_bar_idx)
    return (None, None, None, None)


CONFIRMERS = [
    ("CF1_first_touch", confirm_CF1),
    ("CF2_rejection_close", confirm_CF2),
    ("CF3_sweep_reclaim", confirm_CF3),
    ("CF4_countertrend_body", confirm_CF4),
    ("CF5_minor_swing_break", confirm_CF5),
    ("CF6_retest_after_reject", confirm_CF6),
]


def measure_reach(bars: list[Bar], confirm_i: int, entry: float,
                  side: str, level_price: float) -> dict:
    """From a confirmation close, within the next RESPONSE_HORIZON_BARS,
    measure MFE/MAE and whether price reached +15 / +30 / +50 points
    before being stopped by moving back BEYOND the level (-5 p past
    level) in the ORIGINAL direction."""
    HORIZON = RESPONSE_HORIZON_BARS
    end = min(confirm_i + HORIZON, len(bars) - 1)
    r_15 = r_30 = r_50 = False
    stop_hit = False
    stop_price = level_price + 5.0 if side == "UPPER" else level_price - 5.0
    mfe = mae = 0.0
    t15 = t30 = t50 = None
    for i in range(confirm_i + 1, end + 1):
        bar = bars[i]
        if side == "UPPER":   # reversal direction is DOWN
            mfe_i = entry - bar.low
            mae_i = bar.high - entry
            hits_15 = bar.low <= entry - 15.0
            hits_30 = bar.low <= entry - 30.0
            hits_50 = bar.low <= entry - 50.0
            stopped = bar.high >= stop_price
        else:
            mfe_i = bar.high - entry
            mae_i = entry - bar.low
            hits_15 = bar.high >= entry + 15.0
            hits_30 = bar.high >= entry + 30.0
            hits_50 = bar.high >= entry + 50.0
            stopped = bar.low <= stop_price
        mfe = max(mfe, mfe_i)
        mae = max(mae, mae_i)
        if hits_15 and not r_15:
            r_15 = True; t15 = i - confirm_i
        if hits_30 and not r_30:
            r_30 = True; t30 = i - confirm_i
        if hits_50 and not r_50:
            r_50 = True; t50 = i - confirm_i
        if stopped and not (hits_50 or hits_30 or hits_15):
            stop_hit = True; break
        if hits_50:
            break
    return {
        "mfe_pts": round(mfe, 2),
        "mae_pts": round(mae, 2),
        "reached_15": r_15,
        "reached_30": r_30,
        "reached_50": r_50,
        "stopped_by_level": stop_hit,
        "bars_to_15": t15,
        "bars_to_30": t30,
        "bars_to_50": t50,
    }
