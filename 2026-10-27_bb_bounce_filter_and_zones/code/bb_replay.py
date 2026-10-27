"""
BB Bounce signal replay — core 2-candle pierce + rejection pattern.

Faithfully reproduces the CORE entry pattern from
/opt/tradingbot/gbpusd_bb_bounce.py (lines 1139-1624):

  Setup bar N-1:
    - open INSIDE the band (open_inside_band=True)
    - LONG: bar.low <= bb_lower(N-1) - PIERCE_THRESH_PIPS   AND  bar.close < bb_lower(N-1)
    - SHORT: bar.high >= bb_upper(N-1) + PIERCE_THRESH_PIPS  AND  bar.close > bb_upper(N-1)

  Rejection fire bar N | N+1 | N+2 (REJECTION_WINDOW_BARS=3):
    - LONG: close >= bb_lower(fire_bar) - REJECTION_TOLERANCE_PIPS
            body_pips = abs(close - open) >= MIN_REJECTION_BODY_PIPS
            bullish bar (close > open)
    - SHORT: close <= bb_upper(fire_bar) + REJECTION_TOLERANCE_PIPS
             body_pips >= MIN_REJECTION_BODY_PIPS
             bearish bar

  Timing:
    - Weekdays (Mon-Fri UTC) only
    - WIN_START <= bar.time() < WIN_END  (defaults 06:00-17:00 UTC)
    - Dedup: at most one FIRE per setup

What we deliberately OMIT (research simplification — all documented):
  - adaptive body sizing (we use the static 1.5 p default)
  - near-touch secondary arm path
  - cascade / H1-counter / strong-trend / grind / pivot / PD / MACD gates
  - news blackout window
  - adaptive-body regime adjustment
  - arm-and-wait state machine (H1 MACD-drain)
  - 1 FIRE per epic-day cap (research keeps all FIREs)

Memory confirms the extra gates (cascade, H1 counter) have been disabled in
production .env since 2026-05-28. The CORE pattern IS production in
untouched form. Cross-validation against the pierce log (Oct 2026) confirms
match within reasonable tolerance.
"""

from __future__ import annotations

from datetime import time
from typing import Iterator

import numpy as np
import pandas as pd

BB_PERIOD = 20
BB_STD = 2.0
PIERCE_THRESH_PIPS = 2.0
REJECTION_WINDOW_BARS = 3
MIN_REJECTION_BODY_PIPS = 1.5
REJECTION_TOLERANCE_PIPS = 1.0

WIN_START = time(6, 0)   # UTC
WIN_END = time(17, 0)    # UTC


def compute_bb(bars: pd.DataFrame, period: int = BB_PERIOD, std: float = BB_STD) -> pd.DataFrame:
    """Bollinger bands computed on `close` series. Attaches bb_lower/mid/upper."""
    out = bars.copy()
    rolling = out["close"].rolling(period)
    mid = rolling.mean()
    sd = rolling.std(ddof=0)
    out["bb_mid"] = mid
    out["bb_upper"] = mid + std * sd
    out["bb_lower"] = mid - std * sd
    return out


def _in_window(ts: pd.Timestamp) -> bool:
    if ts.weekday() >= 5:
        return False
    t = ts.time()
    return WIN_START <= t < WIN_END


def iter_signals(bars_bb: pd.DataFrame) -> Iterator[dict]:
    """Yield one dict per confirmed BB-bounce signal.

    bars_bb: M5 OHLC with 'bb_lower', 'bb_mid', 'bb_upper' columns already
    computed. Must be sorted by timestamp.
    """
    # Convert to numpy once; iterate linearly
    ts = bars_bb["timestamp"].values
    o = bars_bb["open"].values
    h = bars_bb["high"].values
    l = bars_bb["low"].values
    c = bars_bb["close"].values
    bbu = bars_bb["bb_upper"].values
    bbl = bars_bb["bb_lower"].values
    bbm = bars_bb["bb_mid"].values

    n = len(bars_bb)
    # Armed setups: list of dicts awaiting fire within REJECTION_WINDOW_BARS
    #   {setup_idx, direction, bbu_setup, bbl_setup, setup_bar_time}
    armed: list[dict] = []

    for i in range(BB_PERIOD + 1, n):
        bar_ts = pd.Timestamp(ts[i])
        # Expire old armed setups (older than REJECTION_WINDOW_BARS from setup)
        armed = [a for a in armed if (i - a["setup_idx"]) < REJECTION_WINDOW_BARS]

        # Try to fire any armed setup on this bar
        new_armed = []
        for a in armed:
            if (i - a["setup_idx"]) == 0:
                # Can't fire on the same bar as the setup
                new_armed.append(a)
                continue
            # Window check: fire bar must be inside the trading window
            if not _in_window(bar_ts):
                new_armed.append(a)
                continue
            # Compute body
            body_pips = abs(c[i] - o[i])
            direction = a["direction"]
            bbl_fire = bbl[i]
            bbu_fire = bbu[i]
            if np.isnan(bbl_fire) or np.isnan(bbu_fire):
                new_armed.append(a); continue
            # Rejection check
            if direction == "LONG":
                # Price must close back above (or very close to) the lower band
                rejects = c[i] >= bbl_fire - REJECTION_TOLERANCE_PIPS and c[i] > o[i]
            else:  # SHORT
                rejects = c[i] <= bbu_fire + REJECTION_TOLERANCE_PIPS and c[i] < o[i]
            if rejects and body_pips >= MIN_REJECTION_BODY_PIPS:
                yield {
                    "setup_time": pd.Timestamp(ts[a["setup_idx"]]),
                    "fire_time": bar_ts,
                    "direction": direction,
                    "bars_from_setup": i - a["setup_idx"],
                    "fire_bar_open": float(o[i]),
                    "fire_bar_high": float(h[i]),
                    "fire_bar_low": float(l[i]),
                    "fire_bar_close": float(c[i]),
                    "fire_bar_body_pips": float(body_pips),
                    "bb_lower_fire": float(bbl_fire),
                    "bb_mid_fire": float(bbm[i]),
                    "bb_upper_fire": float(bbu_fire),
                    "bb_lower_setup": float(a["bbl_setup"]),
                    "bb_upper_setup": float(a["bbu_setup"]),
                    "setup_bar_open": float(a["setup_bar_open"]),
                    "setup_bar_high": float(a["setup_bar_high"]),
                    "setup_bar_low": float(a["setup_bar_low"]),
                    "setup_bar_close": float(a["setup_bar_close"]),
                }
                # Consumed — do NOT keep this armed setup
                continue
            new_armed.append(a)
        armed = new_armed

        # Try to arm from THIS bar as a setup
        if not _in_window(bar_ts):
            continue
        bbl_i = bbl[i]; bbu_i = bbu[i]
        if np.isnan(bbl_i) or np.isnan(bbu_i):
            continue
        # LONG setup
        if (o[i] > bbl_i) and (l[i] <= bbl_i - PIERCE_THRESH_PIPS) and (c[i] < bbl_i):
            armed.append({
                "setup_idx": i, "direction": "LONG",
                "bbl_setup": bbl_i, "bbu_setup": bbu_i,
                "setup_bar_open": o[i], "setup_bar_high": h[i],
                "setup_bar_low": l[i], "setup_bar_close": c[i],
            })
            continue
        # SHORT setup
        if (o[i] < bbu_i) and (h[i] >= bbu_i + PIERCE_THRESH_PIPS) and (c[i] > bbu_i):
            armed.append({
                "setup_idx": i, "direction": "SHORT",
                "bbl_setup": bbl_i, "bbu_setup": bbu_i,
                "setup_bar_open": o[i], "setup_bar_high": h[i],
                "setup_bar_low": l[i], "setup_bar_close": c[i],
            })


def replay_bb_signals(m5: pd.DataFrame) -> pd.DataFrame:
    bars_bb = compute_bb(m5)
    rows = list(iter_signals(bars_bb))
    df = pd.DataFrame(rows)
    return df
