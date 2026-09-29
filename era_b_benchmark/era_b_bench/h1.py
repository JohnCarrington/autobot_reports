"""H1 EMA(8) vs EMA(21) direction — analogue of indicators.h1_ema_direction
from AutoBot commit e8fc9dd.

Reconstructs H1 candles from the 5m stream (rather than reading htf_cache),
computes EMA(8) and EMA(21) on H1 closes, returns BULLISH / BEARISH / FLAT
with a strength scaled 0..1.

Threshold parameters match e8fc9dd:
  fast = 8, slow = 21
  full_strength_separation_pips = 15.0
  flat_threshold_pips = 0.5
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from .candles import Bar


@dataclass(frozen=True)
class H1Direction:
    direction: str                # "BULLISH" | "BEARISH" | "FLAT"
    separation_strength: float    # 0..1
    separation_pips: float        # signed (ema8 - ema21) in pips
    ema8: float
    ema21: float
    n_candles: int


def _ema(values: List[float], period: int) -> List[float]:
    """Wilder-style / simple exponential moving average, matching pandas
    default (adjust=True is close enough on stable series for a
    benchmark — no consumer needs bit-precision here)."""
    if not values or period <= 0:
        return []
    alpha = 2.0 / (period + 1.0)
    out: List[float] = []
    ema_prev = values[0]
    out.append(ema_prev)
    for v in values[1:]:
        ema_prev = alpha * v + (1.0 - alpha) * ema_prev
        out.append(ema_prev)
    return out


def _hour_bucket(ts: datetime) -> datetime:
    """Floor timestamp to the hour (bar open)."""
    return ts.replace(minute=0, second=0, microsecond=0)


def aggregate_5m_to_h1(bars_5m: List[Bar]) -> List[Bar]:
    """Aggregate 5m OHLC bars into H1 OHLC bars. Bar OPEN carries the
    hour timestamp; C = last 5m close in the hour; H/L = extremes.

    Only complete hours are included in the output — a partial trailing
    hour is dropped. (The live H1 cache in the trader is built the same
    way.)
    """
    if not bars_5m:
        return []
    by_hour: Dict[datetime, List[Bar]] = {}
    for b in bars_5m:
        h = _hour_bucket(b.ts)
        by_hour.setdefault(h, []).append(b)
    out: List[Bar] = []
    for h in sorted(by_hour):
        grp = sorted(by_hour[h], key=lambda x: x.ts)
        if len(grp) < 12:   # need all 12 five-minute slots in the hour
            continue
        out.append(Bar(
            ts    = h,
            open  = grp[0].open,
            high  = max(b.high for b in grp),
            low   = min(b.low for b in grp),
            close = grp[-1].close,
        ))
    return out


def h1_ema_direction_at(bars_5m_up_to: List[Bar],
                        pip_units: float = 1.0,
                        fast: int = 8,
                        slow: int = 21,
                        full_strength_separation_pips: float = 15.0,
                        flat_threshold_pips: float = 0.5) -> Optional[H1Direction]:
    """Return the H1 direction at the *end* of bars_5m_up_to.

    `bars_5m_up_to` is a chronologically-ordered slice of 5m bars ending
    at (or just before) the moment we want to query. Only completed
    H1 hours are used — matches the live trader which reads the htf
    cache (updated on every 5m close but only exposes complete hours).

    Returns None if fewer than max(fast, slow) + 5 = 26 complete H1
    candles are available.
    """
    if not bars_5m_up_to:
        return None
    h1 = aggregate_5m_to_h1(bars_5m_up_to)
    if len(h1) < max(fast, slow) + 5:
        return None
    closes = [b.close for b in h1]
    e_fast = _ema(closes, fast)
    e_slow = _ema(closes, slow)
    fv = e_fast[-1]
    sv = e_slow[-1]
    sep_pips = (fv - sv) / pip_units
    abs_sep = abs(sep_pips)
    if abs_sep < flat_threshold_pips:
        return H1Direction("FLAT", 0.0, sep_pips, fv, sv, len(h1))
    if full_strength_separation_pips > 0:
        strength = min(abs_sep / full_strength_separation_pips, 1.0)
    else:
        strength = 1.0
    direction = "BULLISH" if sep_pips > 0 else "BEARISH"
    return H1Direction(direction, strength, sep_pips, fv, sv, len(h1))


def counter_h1_ok_for_short(h1: Optional[H1Direction],
                            strength_floor: float = 0.0) -> bool:
    """Counter-H1 gate for a SHORT reversal (per e8fc9dd):
      - SHORT reversal fires WHEN H1 EMA-stack is BULLISH (we're fading
        an exhausting up-trend)
      - H1 FLAT or None → do NOT fire (no directional context)
      - H1 BEARISH → do NOT fire (same-direction; not a reversal)
      - strength_floor is a minimum on separation_strength (0..1). The
        env default was 0.0 (any non-FLAT counts).
    """
    if h1 is None:
        return False
    if h1.direction != "BULLISH":
        return False
    return h1.separation_strength >= strength_floor
