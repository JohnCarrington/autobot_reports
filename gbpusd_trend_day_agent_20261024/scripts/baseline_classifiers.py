#!/usr/bin/env python3
"""Baseline classifiers for the GBPUSD trend-day research.

These are self-contained, pure-function classifiers. Each one takes the full
day's M5 OHLC up to (and including) time t and returns a direction suggestion
('LONG' | 'SHORT' | None). We will run each one bar-by-bar for every census
weekday and record the earliest fire.

Classifiers:
  * ema_stack    — EMA(7,13,21) alignment with 2-bar persistence
  * ema_cross    — EMA(9) crosses EMA(21) with slope confirmation
  * bb_hug       — close within 20% of upper/lower BB(20,2) for 3 bars
  * macd         — MACD(12,26,9) histogram sign change for 2 bars
  * adx_dmi      — ADX(14) ≥ 20 and +DI vs -DI
  * structure    — HH+HL or LH+LL on last 2 confirmed fractal swings (N=3)
  * open_range   — close breaks N-bar opening-range + follow-through bar
  * displacement — close > open + 25 pips (BUY) or close < open - 25 (SELL) on a single bar

Each classifier returns:
  { 'first_long':  (ts, close) or None,
    'first_short': (ts, close) or None }
"""
from __future__ import annotations

from pathlib import Path
import sys

import numpy as np
import pandas as pd

sys.path.append(str(Path(__file__).parent))
from census import CANDLES_26, CANDLES_EXT, _load_day_file  # noqa: E402

OUT = Path("<research_workspace>/outputs/baseline_classifiers.csv")

# ─── Indicator helpers ────────────────────────────────────────────────
def _ema(series: np.ndarray, period: int) -> np.ndarray:
    k = 2.0 / (period + 1.0)
    out = np.empty_like(series, dtype=float)
    out[0] = series[0]
    for i in range(1, len(series)):
        out[i] = (series[i] - out[i - 1]) * k + out[i - 1]
    return out


def _bb(close: np.ndarray, period: int = 20, k: float = 2.0):
    s = pd.Series(close)
    mid = s.rolling(period, min_periods=period).mean().to_numpy()
    std = s.rolling(period, min_periods=period).std(ddof=0).to_numpy()
    return mid, mid + k * std, mid - k * std


def _macd(close: np.ndarray, fast: int = 12, slow: int = 26, sig: int = 9):
    ef = _ema(close, fast)
    es = _ema(close, slow)
    macd = ef - es
    signal = _ema(macd, sig)
    hist = macd - signal
    return macd, signal, hist


def _true_range(high, low, prev_close):
    return np.maximum.reduce([
        high - low,
        np.abs(high - prev_close),
        np.abs(low - prev_close),
    ])


def _wilder(x: np.ndarray, period: int) -> np.ndarray:
    out = np.full_like(x, np.nan, dtype=float)
    if len(x) < period:
        return out
    out[period - 1] = np.nanmean(x[:period])
    for i in range(period, len(x)):
        out[i] = out[i - 1] - out[i - 1] / period + x[i]
    return out


def _adx(high, low, close, period: int = 14):
    prev_close = np.concatenate(([close[0]], close[:-1]))
    tr = _true_range(high, low, prev_close)
    up = high - np.concatenate(([high[0]], high[:-1]))
    dn = np.concatenate(([low[0]], low[:-1])) - low
    plus_dm  = np.where((up > dn) & (up > 0),  up, 0.0)
    minus_dm = np.where((dn > up) & (dn > 0),  dn, 0.0)
    atr    = _wilder(tr, period)
    plus_di  = 100 * _wilder(plus_dm, period)  / np.where(atr == 0, np.nan, atr)
    minus_di = 100 * _wilder(minus_dm, period) / np.where(atr == 0, np.nan, atr)
    dx = 100 * np.abs(plus_di - minus_di) / np.where(
        (plus_di + minus_di) == 0, np.nan, (plus_di + minus_di))
    adx = _wilder(dx, period)
    return adx, plus_di, minus_di


# ─── Classifiers (bar-indexed) ────────────────────────────────────────
def ema_stack_signal(open_, high, low, close, ts) -> tuple[int | None, int | None]:
    e7 = _ema(close, 7)
    e13 = _ema(close, 13)
    e21 = _ema(close, 21)
    first_long = first_short = None
    streak_up = streak_dn = 0
    for i in range(len(close)):
        if i < 21:
            continue
        up = e7[i] > e13[i] > e21[i]
        dn = e7[i] < e13[i] < e21[i]
        streak_up = streak_up + 1 if up else 0
        streak_dn = streak_dn + 1 if dn else 0
        if streak_up >= 3 and first_long is None:
            first_long = i
        if streak_dn >= 3 and first_short is None:
            first_short = i
    return first_long, first_short


def bb_hug_signal(open_, high, low, close, ts) -> tuple[int | None, int | None]:
    mid, up, lo = _bb(close, 20, 2.0)
    first_long = first_short = None
    streak_u = streak_d = 0
    for i in range(len(close)):
        if np.isnan(up[i]):
            continue
        bw = up[i] - lo[i]
        if bw <= 0:
            continue
        frac_u = (up[i] - close[i]) / bw   # low = hugs upper
        frac_d = (close[i] - lo[i]) / bw   # low = hugs lower
        streak_u = streak_u + 1 if frac_u <= 0.20 else 0
        streak_d = streak_d + 1 if frac_d <= 0.20 else 0
        if streak_u >= 3 and first_long is None:
            first_long = i
        if streak_d >= 3 and first_short is None:
            first_short = i
    return first_long, first_short


def macd_signal(open_, high, low, close, ts) -> tuple[int | None, int | None]:
    _, _, hist = _macd(close)
    first_long = first_short = None
    pos_streak = neg_streak = 0
    for i in range(len(close)):
        if np.isnan(hist[i]):
            continue
        if hist[i] > 0:
            pos_streak += 1; neg_streak = 0
        elif hist[i] < 0:
            neg_streak += 1; pos_streak = 0
        if pos_streak >= 2 and first_long is None:
            first_long = i
        if neg_streak >= 2 and first_short is None:
            first_short = i
    return first_long, first_short


def adx_signal(open_, high, low, close, ts, adx_min=20.0) -> tuple[int | None, int | None]:
    adx, pdi, mdi = _adx(high, low, close)
    first_long = first_short = None
    for i in range(len(close)):
        if np.isnan(adx[i]):
            continue
        if adx[i] >= adx_min and pdi[i] > mdi[i] and first_long is None:
            first_long = i
        if adx[i] >= adx_min and mdi[i] > pdi[i] and first_short is None:
            first_short = i
    return first_long, first_short


def _fractal_swings(high: np.ndarray, low: np.ndarray, n: int = 3):
    """Return list of (index, 'H'/'L', price) for n-bar fractal swings."""
    out = []
    for i in range(n, len(high) - n):
        if high[i] == max(high[i - n: i + n + 1]):
            out.append((i, 'H', high[i]))
        if low[i] == min(low[i - n: i + n + 1]):
            out.append((i, 'L', low[i]))
    return sorted(out, key=lambda x: x[0])


def structure_signal(open_, high, low, close, ts) -> tuple[int | None, int | None]:
    """Fires LONG at first bar where last 2 highs AND last 2 lows are rising;
       SHORT when both are falling."""
    first_long = first_short = None
    n = 3
    # Compute confirmed swings progressively: a swing at bar i is confirmable
    # at bar i+n.
    all_swings = _fractal_swings(high, low, n=n)
    swing_by_index: dict[int, list[tuple]] = {}
    for idx, kind, price in all_swings:
        confirm_at = idx + n
        swing_by_index.setdefault(confirm_at, []).append((idx, kind, price))

    highs: list[tuple[int, float]] = []
    lows:  list[tuple[int, float]] = []
    for i in range(len(close)):
        for (idx, kind, price) in swing_by_index.get(i, []):
            if kind == 'H':
                highs.append((idx, price))
            else:
                lows.append((idx, price))
        if len(highs) >= 2 and len(lows) >= 2:
            hh = highs[-1][1] > highs[-2][1]
            hl = lows[-1][1] > lows[-2][1]
            lh = highs[-1][1] < highs[-2][1]
            ll = lows[-1][1] < lows[-2][1]
            if hh and hl and first_long is None:
                first_long = i
            if lh and ll and first_short is None:
                first_short = i
    return first_long, first_short


def open_range_breakout(open_, high, low, close, ts, or_bars: int = 3,
                        break_pips: float = 3.0) -> tuple[int | None, int | None]:
    """Classic Opening Range Breakout. OR = first `or_bars` London bars starting
    at 07:00 UK (approx 06:00 UTC during BST, 07:00 UTC during GMT). We
    approximate by using the first `or_bars` bars after 07:00 UTC (acceptable
    for a baseline). Fires on a bar closing > OR_high+3 or < OR_low-3 that is
    then followed by another bar closing in the same direction."""
    first_long = first_short = None
    # Determine first bar at or after 07:00 UTC
    london_bar = None
    for i, t in enumerate(ts):
        if t.hour >= 7:
            london_bar = i
            break
    if london_bar is None or london_bar + or_bars + 1 >= len(close):
        return None, None
    or_high = max(high[london_bar: london_bar + or_bars])
    or_low  = min(low[london_bar:  london_bar + or_bars])
    for i in range(london_bar + or_bars, len(close) - 1):
        up_break_now = close[i] > or_high + break_pips/10000  # pips → fraction
        dn_break_now = close[i] < or_low  - break_pips/10000
        up_break_next = close[i + 1] > or_high + break_pips/10000
        dn_break_next = close[i + 1] < or_low  - break_pips/10000
        if up_break_now and up_break_next and first_long is None:
            first_long = i + 1
        if dn_break_now and dn_break_next and first_short is None:
            first_short = i + 1
    return first_long, first_short


def displacement_signal(open_, high, low, close, ts, pips: float = 25.0
                        ) -> tuple[int | None, int | None]:
    """Fires on a single bar whose body is ≥ `pips` pips in one direction."""
    thr = pips / 10000
    first_long = first_short = None
    for i in range(len(close)):
        if close[i] - open_[i] >= thr and first_long is None:
            first_long = i
        if open_[i] - close[i] >= thr and first_short is None:
            first_short = i
    return first_long, first_short


# ─── Driver ───────────────────────────────────────────────────────────
CLASSIFIERS = {
    "ema_stack":    ema_stack_signal,
    "bb_hug":       bb_hug_signal,
    "macd":         macd_signal,
    "adx20":        adx_signal,
    "structure":    structure_signal,
    "or_breakout":  open_range_breakout,
    "displace25":   displacement_signal,
}


def run_day(path: Path, basis: str) -> dict | None:
    df = _load_day_file(path, basis)
    if df is None or len(df) < 40:
        return None
    date = df["ts"].iloc[0].date()
    if date.weekday() >= 5:
        return None
    o = df["open"].to_numpy(dtype=float) / 10000
    h = df["high"].to_numpy(dtype=float) / 10000
    l = df["low"].to_numpy(dtype=float) / 10000
    c = df["close"].to_numpy(dtype=float) / 10000
    ts = df["ts"].to_list()

    row = {"date": date.isoformat(), "basis": basis}
    for name, fn in CLASSIFIERS.items():
        try:
            long_i, short_i = fn(o, h, l, c, ts)
        except Exception as exc:  # noqa: BLE001
            row[f"{name}_err"] = str(exc)
            long_i = short_i = None
        row[f"{name}_first_long_ts"] = ts[long_i].isoformat() if long_i is not None else None
        row[f"{name}_first_long_px"] = round(c[long_i], 5) if long_i is not None else None
        row[f"{name}_first_short_ts"] = ts[short_i].isoformat() if short_i is not None else None
        row[f"{name}_first_short_px"] = round(c[short_i], 5) if short_i is not None else None
    return row


def main():
    rows = []
    for p in sorted(CANDLES_EXT.glob("*.csv")):
        r = run_day(p, "BID")
        if r:
            rows.append(r)
    for p in sorted(CANDLES_26.glob("*.csv")):
        r = run_day(p, "MID")
        if r:
            rows.append(r)
    df = pd.DataFrame(rows)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT, index=False)
    print(f"Wrote {len(df)} rows → {OUT}")


if __name__ == "__main__":
    main()
