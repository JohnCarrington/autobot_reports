"""
Measure M5 approach outcomes for each (level, tolerance) pair.

For a candidate BUY level L (from an UP-swing retrace):
  - Approach: first M5 bar whose range [low, high] intersects the tolerance
    band [L-tol, L+tol].
  - Entry: at the approach bar, we simulate a limit at L+tol (fill when bar
    low pierces the upper band). If the bar's open is already below L+tol,
    we use the open.
  - MFE (favorable, upward): max(bar.high) - entry across the window.
    MAE (adverse, downward): entry - min(bar.low) across the window.

For a candidate SELL level: mirror.

Outcomes per (fav, adv) ∈ FAV_TARGETS × ADV_TARGETS:
  - Compute first bar index where fav_px >= fav → k_fav
  - Compute first bar index where adv_px >= adv → k_adv
  - If both NaN: NEITHER
  - If k_fav < k_adv: WIN at k_fav
  - If k_adv < k_fav: LOSS at k_adv
  - If k_fav == k_adv (both on the same M5 bar): AMBIG — we cannot resolve
    intra-bar order from M5 OHLC alone.

Window: WINDOW_BARS M5 bars after `live_from`, truncated by `deadline` if
provided (we use the next same-TF swing confirmation as a deadline so a
retired structure is not credited beyond its lifetime).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

TOLERANCES_PIPS: list[float] = [0.0, 3.0, 5.0, 10.0]
FAV_TARGETS_PIPS: list[float] = [10.0, 15.0, 20.0, 30.0, 40.0, 50.0]
ADV_TARGETS_PIPS: list[float] = [10.0, 12.0, 15.0, 20.0, 30.0]
WINDOW_BARS: int = 288  # 24h on M5


def _first_idx_ge(arr: np.ndarray, thr: float) -> int:
    """Return first index k where arr[k] >= thr, or -1 if none."""
    hits = np.where(arr >= thr)[0]
    if hits.size == 0:
        return -1
    return int(hits[0])


def measure_approach(m5_ts: np.ndarray, m5_high: np.ndarray, m5_low: np.ndarray,
                     m5_open: np.ndarray,
                     level: float, tol: float, direction: str,
                     live_from: np.datetime64,
                     window_bars: int = WINDOW_BARS,
                     deadline: np.datetime64 | None = None) -> dict | None:
    """Vectorized approach + outcome measurement. Returns None if no approach."""
    live_idx = int(np.searchsorted(m5_ts, live_from, side="left"))
    if live_idx >= len(m5_ts):
        return None
    end_idx = min(live_idx + window_bars, len(m5_ts))
    if deadline is not None:
        dl_idx = int(np.searchsorted(m5_ts, deadline, side="left"))
        end_idx = min(end_idx, dl_idx)
    if end_idx <= live_idx:
        return None

    highs = m5_high[live_idx:end_idx]
    lows = m5_low[live_idx:end_idx]
    opens = m5_open[live_idx:end_idx]

    lo_band = level - tol
    hi_band = level + tol
    # Approach: bar whose [low, high] intersects [lo_band, hi_band]
    touched = (lows <= hi_band) & (highs >= lo_band)
    touched_idx = np.where(touched)[0]
    if touched_idx.size == 0:
        return None
    j = int(touched_idx[0])

    bl = lows[j]
    bh = highs[j]
    bo = opens[j]

    # Simulate entry at the limit if the band is pierced, else bar open
    if direction == "BUY":
        entry = min(bo, hi_band) if bl <= hi_band else bo
    else:
        entry = max(bo, lo_band) if bh >= lo_band else bo

    sub_highs = highs[j:]
    sub_lows = lows[j:]
    if direction == "BUY":
        fav_px = sub_highs - entry
        adv_px = entry - sub_lows
    else:
        fav_px = entry - sub_lows
        adv_px = sub_highs - entry

    mfe = float(np.max(fav_px))
    mae = float(np.max(adv_px))

    outcomes: dict[tuple[float, float], tuple[str, int]] = {}
    for fav in FAV_TARGETS_PIPS:
        k_fav = _first_idx_ge(fav_px, fav)
        for adv in ADV_TARGETS_PIPS:
            k_adv = _first_idx_ge(adv_px, adv)
            if k_fav == -1 and k_adv == -1:
                outcomes[(fav, adv)] = ("NEITHER", -1)
            elif k_fav == -1:
                outcomes[(fav, adv)] = ("LOSS", k_adv)
            elif k_adv == -1:
                outcomes[(fav, adv)] = ("WIN", k_fav)
            elif k_fav < k_adv:
                outcomes[(fav, adv)] = ("WIN", k_fav)
            elif k_adv < k_fav:
                outcomes[(fav, adv)] = ("LOSS", k_adv)
            else:
                outcomes[(fav, adv)] = ("AMBIG", k_fav)

    return {
        "approach_idx": live_idx + j,
        "approach_time": m5_ts[live_idx + j],
        "approach_entry": entry,
        "mfe_pips": mfe,
        "mae_pips": mae,
        "bars_in_window": end_idx - live_idx,
        "outcomes": outcomes,
    }
