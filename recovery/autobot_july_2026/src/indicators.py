# =========================
# FILE: indicators.py
# =========================
"""
PURE indicator utilities for AutoBot.

Non-negotiables:
- No bot imports
- No I/O
- No globals / no caching
- Deterministic: inputs -> outputs

Indicators:
- EMA
- ATR (Wilder RMA)
- RSI (Wilder RMA) (+ flat-market + canonical extreme handling)
- Bollinger Bands (+ derived slope/width helpers)
- MACD (+ derived deltas/deceleration helpers)
- Aroon
- EMA stack state (4-EMA alignment enum; input to regime decision)
"""

from __future__ import annotations

import logging
import sys
from dataclasses import dataclass
from typing import Any, Dict, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger("AutoBot")

# Module-level de-dupe for "skipped because pip_size missing" warnings.
# The "no globals" principle in the module docstring is bent here intentionally:
# the alternative is log-per-bar spam for every replay/validator that hasn't
# plumbed pip_size yet. One-shot warn per unique caller per process is the
# minimum state needed to keep journalctl readable while still flagging
# missing plumbing.
_PRICE_VS_EMA50_SKIP_WARNED: set[str] = set()


def _warn_price_vs_ema50_skipped(caller_hint: Optional[str]) -> None:
    """Log once per caller when PRICE_VS_EMA50_PIPS is skipped for lack of pip_size."""
    # Resolve a stable caller identifier. Explicit hint wins. Else best-effort frame inspect.
    # The sentinel 'unknown' exists so even if frame inspection fails we still log exactly once.
    if caller_hint:
        key = str(caller_hint)
    else:
        try:
            # Skip the add_indicators frame (frame 2) and point at the original caller (frame 3+).
            frame = sys._getframe(2)
            key = f"{frame.f_code.co_filename}:{frame.f_code.co_name}"
        except Exception:
            key = "unknown"
    if key in _PRICE_VS_EMA50_SKIP_WARNED:
        return
    _PRICE_VS_EMA50_SKIP_WARNED.add(key)
    logger.warning(
        "[indicators] PRICE_VS_EMA50_PIPS skipped — pip_size not provided (caller=%s)",
        key,
    )

# Numerical tolerance used for "near zero" / "flat" checks.
# This is a constant (not caching/state) and keeps behavior consistent across indicators.
EPS = 1e-12


@dataclass(frozen=True)
class IndicatorsConfig:
    """
    Pure configuration container.

    Defaults are standard/common; strategy can override.
    """
    ema_period: int = 50

    atr_period: int = 14
    rsi_period: int = 3

    bb_period: int = 20
    bb_std: float = 2.0

    macd_fast: int = 35
    macd_slow: int = 45
    macd_signal: int = 30

    aroon_period: int = 14
    adx_period: int = 14

    # Swing structure (regime-decision input). flank = bars each side for a
    # local pivot; lookback = window over which the recent pivot sequence is
    # assessed for HH+HL / LL+LH / overlap.
    swing_pivot_flank: int = 3
    swing_lookback: int = 24

    # EMA stack (regime-decision input). Periods ordered fast -> slow.
    # Compression threshold: max gap between the four EMAs <= k * ATR(atr_period).
    # k = 0.3 is a working guess, not validated against historical regime data yet.
    # Revisit once a few weeks of regime-labelled data show whether COMPRESSED fires
    # at a useful rate and actually precedes breakouts.
    ema_stack_periods: tuple[int, ...] = (8, 13, 21, 50)
    ema_stack_compression_k: float = 0.3


# -------------------------
# Validation helpers (pure)
# -------------------------

def _require_columns(df: pd.DataFrame, cols: list[str]) -> None:
    missing = [c for c in cols if c not in df.columns]
    if missing:
        raise ValueError(f"DataFrame missing required columns: {missing}. Present: {list(df.columns)}")


def _to_float_series(s: pd.Series) -> pd.Series:
    """
    Deterministic conversion; preserves index.
    Also normalizes +/-inf -> NaN to prevent silent propagation through EWM/rolling ops.
    """
    out = pd.to_numeric(s, errors="coerce").astype(float)
    return out.replace([np.inf, -np.inf], np.nan)


# -------------------------
# Core indicator primitives
# -------------------------

def ema(series: pd.Series, period: int) -> pd.Series:
    """
    Exponential moving average (EMA).
    Uses pandas ewm with adjust=False (standard trading EMA).

    IMPORTANT:
    - min_periods=1 so EMA exists on TODAY (~20 bars) and CFD (~50 bars) windows.
      This prevents downstream logic collapsing due to NaN slopes on short windows.
    """
    if period <= 0:
        raise ValueError("EMA period must be > 0")
    s = _to_float_series(series)
    return s.ewm(span=period, adjust=False, min_periods=1).mean()


def _wilder_rma(series: pd.Series, period: int) -> pd.Series:
    """
    Wilder's smoothing (RMA) via EMA(alpha=1/period).
    Common for ATR and RSI.

    IMPORTANT:
    - min_periods=1 so RMA exists on short windows.
    """
    if period <= 0:
        raise ValueError("RMA period must be > 0")
    s = _to_float_series(series)
    alpha = 1.0 / float(period)
    return s.ewm(alpha=alpha, adjust=False, min_periods=1).mean()


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """
    Average True Range (ATR) using Wilder's RMA smoothing.
    Requires: high, low, close.
    """
    _require_columns(df, ["high", "low", "close"])
    if period <= 0:
        raise ValueError("ATR period must be > 0")

    high = _to_float_series(df["high"])
    low = _to_float_series(df["low"])
    close = _to_float_series(df["close"])

    prev_close = close.shift(1)

    tr1 = (high - low).abs()
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()

    true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return _wilder_rma(true_range, period).rename(f"ATR_{period}")


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """
    RSI using Wilder's method (RMA of gains/losses).

    Flat-market handling:
    - When avg_gain ~= 0 and avg_loss ~= 0 (no movement), RSI = 50.

    Canonical extreme handling:
    - When avg_loss ~= 0 and avg_gain > 0, RSI = 100.
    - When avg_gain ~= 0 and avg_loss > 0, RSI = 0.

    Uses EPS tolerance to avoid float-noise missing conditions.
    """
    if period <= 0:
        raise ValueError("RSI period must be > 0")

    s = _to_float_series(series)
    delta = s.diff()

    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)

    avg_gain = _wilder_rma(gain, period)
    avg_loss = _wilder_rma(loss, period)

    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    rsi_val = 100.0 - (100.0 / (1.0 + rs))

    ag = avg_gain.fillna(0.0).astype(float)
    al = avg_loss.fillna(0.0).astype(float)

    flat_mask = (ag.abs() < EPS) & (al.abs() < EPS)
    up_extreme_mask = (al.abs() < EPS) & (ag > EPS)
    down_extreme_mask = (ag.abs() < EPS) & (al > EPS)

    rsi_val = rsi_val.where(~flat_mask, 50.0)
    rsi_val = rsi_val.where(~up_extreme_mask, 100.0)
    rsi_val = rsi_val.where(~down_extreme_mask, 0.0)

    return rsi_val.rename(f"RSI_{period}")


def bollinger_bands(series: pd.Series, period: int = 20, std: float = 2.0) -> pd.DataFrame:
    """
    Bollinger Bands: mid = SMA, upper/lower = mid +/- std * stdev

    NOTE:
    - Uses min_periods=period (true BB): BB is NaN until fully warmed up.
    """
    if period <= 0:
        raise ValueError("BB period must be > 0")
    if std <= 0:
        raise ValueError("BB std must be > 0")

    s = _to_float_series(series)
    mid = s.rolling(window=period, min_periods=period).mean()
    stdev = s.rolling(window=period, min_periods=period).std(ddof=0)

    upper = mid + (std * stdev)
    lower = mid - (std * stdev)

    std_key = f"{std:g}"
    return pd.DataFrame(
        {
            f"BB_MID_{period}": mid,
            f"BB_UPPER_{period}_{std_key}": upper,
            f"BB_LOWER_{period}_{std_key}": lower,
        },
        index=s.index,
    )


def macd(series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    """
    MACD: macd = EMA(fast) - EMA(slow)
    signal = EMA(macd, signal)
    hist = macd - signal

    IMPORTANT:
    - min_periods=1 so MACD exists on short windows.
    """
    if fast <= 0 or slow <= 0 or signal <= 0:
        raise ValueError("MACD periods must be > 0")
    if fast >= slow:
        raise ValueError("MACD requires fast < slow")

    s = _to_float_series(series)
    ema_fast = s.ewm(span=fast, adjust=False, min_periods=1).mean()
    ema_slow = s.ewm(span=slow, adjust=False, min_periods=1).mean()

    macd_line = (ema_fast - ema_slow).rename(f"MACD_{fast}_{slow}")
    signal_line = macd_line.ewm(span=signal, adjust=False, min_periods=1).mean().rename(
        f"MACD_SIGNAL_{fast}_{slow}_{signal}"
    )
    hist = (macd_line - signal_line).rename(f"MACD_HIST_{fast}_{slow}_{signal}")

    return pd.DataFrame(
        {macd_line.name: macd_line, signal_line.name: signal_line, hist.name: hist},
        index=s.index,
    )


def aroon(high: pd.Series, low: pd.Series, period: int = 14) -> pd.DataFrame:
    """
    Aroon indicator.

    Aroon Up = 100 * (period - periods_since_highest_high) / period
    Aroon Down = 100 * (period - periods_since_lowest_low) / period

    periods_since_* is counted from the most recent bar in the rolling window.
    """
    if period <= 0:
        raise ValueError("Aroon period must be > 0")

    h = _to_float_series(high)
    l = _to_float_series(low)

    def _aroon_up_window(x: np.ndarray) -> float:
        xr = x[::-1]
        since_high = int(np.argmax(xr))
        return 100.0 * (float(period) - float(since_high)) / float(period)

    def _aroon_down_window(x: np.ndarray) -> float:
        xr = x[::-1]
        since_low = int(np.argmin(xr))
        return 100.0 * (float(period) - float(since_low)) / float(period)

    up = h.rolling(window=period, min_periods=period).apply(_aroon_up_window, raw=True).rename(f"AROON_UP_{period}")
    down = l.rolling(window=period, min_periods=period).apply(_aroon_down_window, raw=True).rename(f"AROON_DOWN_{period}")
    return pd.DataFrame({up.name: up, down.name: down}, index=h.index)


def adx(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    """
    Average Directional Index (ADX) with +DI / -DI, Wilder's method.
    Requires: high, low, close.

    +DI / -DI measure directional movement strength (0-100); ADX measures
    trend strength regardless of direction (0-100). Standard Wilder smoothing
    (RMA) throughout: smoothed TR via atr(), smoothed +DM/-DM via _wilder_rma().
    """
    _require_columns(df, ["high", "low", "close"])
    if period <= 0:
        raise ValueError("ADX period must be > 0")

    high = _to_float_series(df["high"])
    low = _to_float_series(df["low"])

    # Smoothed true range — atr() already applies _wilder_rma(TR, period).
    smoothed_tr = atr(df, period)

    plus_dm_raw = high.diff()
    minus_dm_raw = -low.diff()

    # Keep +DM only where it dominates and is positive; otherwise 0. Same for -DM.
    plus_dm = plus_dm_raw.where((plus_dm_raw > minus_dm_raw) & (plus_dm_raw > 0.0), 0.0)
    minus_dm = minus_dm_raw.where((minus_dm_raw > plus_dm_raw) & (minus_dm_raw > 0.0), 0.0)

    smoothed_plus_dm = _wilder_rma(plus_dm, period)
    smoothed_minus_dm = _wilder_rma(minus_dm, period)

    # Guard divide-by-zero: zero smoothed TR -> NaN DI rather than inf.
    tr_safe = smoothed_tr.replace(0.0, np.nan)
    plus_di = 100.0 * smoothed_plus_dm / tr_safe
    minus_di = 100.0 * smoothed_minus_dm / tr_safe

    # Guard zero denom: +DI + -DI == 0 (no directional movement) -> NaN DX.
    di_sum = (plus_di + minus_di).replace(0.0, np.nan)
    dx = 100.0 * (plus_di - minus_di).abs() / di_sum

    adx_val = _wilder_rma(dx, period)

    return pd.DataFrame(
        {
            f"ADX_{period}": adx_val,
            f"PLUS_DI_{period}": plus_di,
            f"MINUS_DI_{period}": minus_di,
        },
        index=high.index,
    )


# Swing-structure labels (mirrors the EMA_STACK_* string-label convention).
SWING_STRUCTURE_BULLISH = "BULLISH"
SWING_STRUCTURE_BEARISH = "BEARISH"
SWING_STRUCTURE_OVERLAP = "OVERLAP"


def swing_structure(df: pd.DataFrame, flank: int = 3, lookback: int = 24) -> pd.Series:
    """
    Per-bar swing-structure label from pivot-high / pivot-low sequencing.

    A pivot high is a bar whose high strictly exceeds the highs of `flank`
    bars on each side; a pivot low is the mirror on lows. A pivot is only
    confirmable `flank` bars after it prints, so each bar's label uses ONLY
    pivots whose confirmation index has already passed (causal — no lookahead).

    For each bar the pivots inside the trailing `lookback` window are sequenced:
      BULLISH - most recent pivot highs rising AND pivot lows rising (HH + HL)
      BEARISH - most recent pivot highs falling AND pivot lows falling (LL + LH)
      OVERLAP - >=2 pivots of each type present but no clean sequence (chop);
                a positive classification, not a fallback.
      None    - insufficient confirmed pivots in the window (warmup).

    Returns a string-label Series (mirrors EMA_STACK_STATE convention).
    """
    _require_columns(df, ["high", "low", "close"])
    if flank <= 0:
        raise ValueError("swing_structure flank must be > 0")
    if lookback <= 0:
        raise ValueError("swing_structure lookback must be > 0")

    high = _to_float_series(df["high"])
    low = _to_float_series(df["low"])
    h = high.to_numpy(dtype=float)
    l = low.to_numpy(dtype=float)
    n = len(h)

    # Vectorised-ish pivot detection: bar i is a pivot high if its high
    # strictly exceeds every high in the `flank` bars on each side.
    is_ph = np.zeros(n, dtype=bool)
    is_pl = np.zeros(n, dtype=bool)
    for i in range(flank, n - flank):
        win_h = h[i - flank:i + flank + 1]
        if not np.isnan(win_h).any():
            hi = win_h[flank]
            if hi > win_h[:flank].max() and hi > win_h[flank + 1:].max():
                is_ph[i] = True
        win_l = l[i - flank:i + flank + 1]
        if not np.isnan(win_l).any():
            li = win_l[flank]
            if li < win_l[:flank].min() and li < win_l[flank + 1:].min():
                is_pl[i] = True

    ph_idx = np.flatnonzero(is_ph)
    pl_idx = np.flatnonzero(is_pl)

    labels = np.empty(n, dtype=object)
    labels[:] = None
    for t in range(n):
        # Pivots within the trailing lookback window AND already confirmable
        # by bar t (pivot index + flank <= t).
        lo_bound = t - lookback + 1
        hi_bound = t - flank
        ph_sel = ph_idx[(ph_idx >= lo_bound) & (ph_idx <= hi_bound)]
        pl_sel = pl_idx[(pl_idx >= lo_bound) & (pl_idx <= hi_bound)]
        if len(ph_sel) < 2 or len(pl_sel) < 2:
            continue  # None — warmup / insufficient pivots
        ph_vals = h[ph_sel]
        pl_vals = l[pl_sel]
        highs_rising = ph_vals[-1] > ph_vals[-2]
        highs_falling = ph_vals[-1] < ph_vals[-2]
        lows_rising = pl_vals[-1] > pl_vals[-2]
        lows_falling = pl_vals[-1] < pl_vals[-2]
        if highs_rising and lows_rising:
            labels[t] = SWING_STRUCTURE_BULLISH
        elif highs_falling and lows_falling:
            labels[t] = SWING_STRUCTURE_BEARISH
        else:
            labels[t] = SWING_STRUCTURE_OVERLAP

    return pd.Series(labels, index=df.index, name="SWING_STRUCTURE")


def candle_displacement(df: pd.DataFrame, atr_col: str = "ATR_14") -> pd.DataFrame:
    """
    Per-bar candle-displacement features (momentum / rejection quality).

    BODY_ATR_RATIO_14 - |close-open| / ATR: body size normalised by volatility.
    CLOSE_LOCATION    - (close-low)/(high-low): where the close sits in the bar.
    UPPER_WICK_RATIO  - (high-max(open,close))/(high-low): rejection from above.
    LOWER_WICK_RATIO  - (min(open,close)-low)/(high-low): rejection from below.

    Requires open/high/low/close and the ATR column `atr_col`. Degenerate
    bars yield NaN for the affected ratio: zero range (high==low) -> NaN for
    the three range-normalised ratios; zero ATR -> NaN for BODY_ATR_RATIO_14.
    """
    _require_columns(df, ["open", "high", "low", "close", atr_col])

    o = _to_float_series(df["open"])
    h = _to_float_series(df["high"])
    l = _to_float_series(df["low"])
    c = _to_float_series(df["close"])
    a = _to_float_series(df[atr_col])

    rng = h - l
    rng_safe = rng.where(rng > 0.0, np.nan)  # guard zero-range bars -> NaN
    atr_safe = a.where(a > 0.0, np.nan)      # guard zero/neg ATR -> NaN

    body = (c - o).abs()
    body_atr = body / atr_safe
    close_loc = (c - l) / rng_safe
    upper_wick = (h - np.maximum(o, c)) / rng_safe
    lower_wick = (np.minimum(o, c) - l) / rng_safe

    return pd.DataFrame(
        {
            "BODY_ATR_RATIO_14": body_atr,
            "CLOSE_LOCATION": close_loc,
            "UPPER_WICK_RATIO": upper_wick,
            "LOWER_WICK_RATIO": lower_wick,
        },
        index=df.index,
    )


def net_displacement(df: pd.DataFrame, pip_size: float,
                     periods: tuple[int, ...] = (6, 12, 24)) -> pd.DataFrame:
    """
    Net close-to-close displacement over each period, in pips.

    NET_DISP_{N} = (close - close.shift(N)) / pip_size

    (pip_size is positioned before `periods` because a required positional
    argument cannot follow a defaulted one.)
    """
    _require_columns(df, ["close"])
    if pip_size is None or float(pip_size) <= 0:
        raise ValueError("net_displacement: pip_size required and > 0")
    if any(p <= 0 for p in periods):
        raise ValueError("net_displacement periods must be > 0")

    close = _to_float_series(df["close"])
    ps = float(pip_size)
    cols = {f"NET_DISP_{n}": close.diff(n) / ps for n in periods}
    return pd.DataFrame(cols, index=df.index)


# -------------------------
# MACD trajectory primitives (chart-aligned 12/26/9 by default)
# -------------------------
# Defaults are 12/26/9 — what IG/TradingView shows on the chart and what
# the user reads. Distinct from `IndicatorsConfig.macd_*` (35/45/30) used
# elsewhere; these primitives are for the trajectory-snapshot/validator
# layer where alignment with the user's visual analysis matters.
#
# Magnitude trajectory uses |hist|, NOT signed hist. The existing
# MACD_HIST_..._DECREASING2 column in add_indicators() is signed and
# answers a different question (signed monotonic). Do not conflate.

MACD_DEFAULT_FAST = 12
MACD_DEFAULT_SLOW = 26
MACD_DEFAULT_SIGNAL = 9

# Composite-verdict thresholds — defaults from 2026-05-04 calibration.
# See project_macd_validation_calibration memory for iteration notes.
MACD_VALIDATE_PCTILE_HIGH = 70.0
MACD_VALIDATE_ESTABLISHED_PIPS = 0.5


def _macd_lines(df: pd.DataFrame, fast: int, slow: int, signal: int) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Internal helper: compute (line, signal, hist) Series from df['close'].

    Convention: pandas ewm(adjust=False, min_periods=1) — recursive from
    bar 0, no SMA seed. Matches indicators.macd() and the user's IG chart.
    """
    _require_columns(df, ["close"])
    if fast <= 0 or slow <= 0 or signal <= 0:
        raise ValueError("MACD periods must be > 0")
    if fast >= slow:
        raise ValueError("MACD requires fast < slow")
    s = _to_float_series(df["close"])
    ema_fast = s.ewm(span=fast, adjust=False, min_periods=1).mean()
    ema_slow = s.ewm(span=slow, adjust=False, min_periods=1).mean()
    line = ema_fast - ema_slow
    sig = line.ewm(span=signal, adjust=False, min_periods=1).mean()
    hist = line - sig
    return line, sig, hist


def macd_hist_magnitude_pips(df: pd.DataFrame, *,
                             fast: int = MACD_DEFAULT_FAST,
                             slow: int = MACD_DEFAULT_SLOW,
                             signal: int = MACD_DEFAULT_SIGNAL,
                             pip_size: float) -> pd.Series:
    """|hist| / pip_size as a Series. Pip_size REQUIRED."""
    if pip_size is None or float(pip_size) <= 0:
        raise ValueError("macd_hist_magnitude_pips: pip_size required and > 0")
    _, _, hist = _macd_lines(df, fast, slow, signal)
    return (hist.abs() / float(pip_size)).rename(
        f"MACD_HIST_MAG_PIPS_{fast}_{slow}_{signal}"
    )


def macd_hist_contracting_n(df: pd.DataFrame, *,
                            fast: int = MACD_DEFAULT_FAST,
                            slow: int = MACD_DEFAULT_SLOW,
                            signal: int = MACD_DEFAULT_SIGNAL,
                            n: int = 3) -> pd.Series:
    """Bool Series: |hist[i-(n-1)]| > |hist[i-(n-2)]| > ... > |hist[i]|.

    Strict monotonic decreasing in absolute value over n bars. The
    chart-aligned cousin of MACD_HIST_..._DECREASING2 (which is signed).
    True only when bars are getting smaller in MAGNITUDE.
    """
    if n < 2:
        raise ValueError("macd_hist_contracting_n: n must be >= 2")
    _, _, hist = _macd_lines(df, fast, slow, signal)
    a = hist.abs()
    cond = pd.Series(True, index=a.index)
    for k in range(n - 1):
        cond = cond & (a.shift(k + 1) > a.shift(k))
    return cond.rename(f"MACD_HIST_CONTRACTING_{n}_{fast}_{slow}_{signal}")


def macd_hist_expanding_n(df: pd.DataFrame, *,
                          fast: int = MACD_DEFAULT_FAST,
                          slow: int = MACD_DEFAULT_SLOW,
                          signal: int = MACD_DEFAULT_SIGNAL,
                          n: int = 3) -> pd.Series:
    """Bool Series: strict monotonic INCREASING in absolute value over n bars."""
    if n < 2:
        raise ValueError("macd_hist_expanding_n: n must be >= 2")
    _, _, hist = _macd_lines(df, fast, slow, signal)
    a = hist.abs()
    cond = pd.Series(True, index=a.index)
    for k in range(n - 1):
        cond = cond & (a.shift(k + 1) < a.shift(k))
    return cond.rename(f"MACD_HIST_EXPANDING_{n}_{fast}_{slow}_{signal}")


def macd_line_slope_n(df: pd.DataFrame, *,
                      fast: int = MACD_DEFAULT_FAST,
                      slow: int = MACD_DEFAULT_SLOW,
                      signal: int = MACD_DEFAULT_SIGNAL,
                      n: int = 5) -> pd.Series:
    """Signed N-bar line slope: line[i] - line[i-n] (price units)."""
    if n < 1:
        raise ValueError("macd_line_slope_n: n must be >= 1")
    line, _, _ = _macd_lines(df, fast, slow, signal)
    return (line - line.shift(n)).rename(
        f"MACD_LINE_SLOPE_{n}_{fast}_{slow}_{signal}"
    )


def macd_line_distance_from_signal_pips(df: pd.DataFrame, *,
                                        fast: int = MACD_DEFAULT_FAST,
                                        slow: int = MACD_DEFAULT_SLOW,
                                        signal: int = MACD_DEFAULT_SIGNAL,
                                        pip_size: float) -> pd.Series:
    """Signed (line - signal) / pip_size. Equals hist/pip_size by definition."""
    if pip_size is None or float(pip_size) <= 0:
        raise ValueError("macd_line_distance_from_signal_pips: pip_size required and > 0")
    line, sig, _ = _macd_lines(df, fast, slow, signal)
    return ((line - sig) / float(pip_size)).rename(
        f"MACD_LINE_VS_SIGNAL_PIPS_{fast}_{slow}_{signal}"
    )


def macd_line_distance_from_zero_pips(df: pd.DataFrame, *,
                                      fast: int = MACD_DEFAULT_FAST,
                                      slow: int = MACD_DEFAULT_SLOW,
                                      signal: int = MACD_DEFAULT_SIGNAL,
                                      pip_size: float) -> pd.Series:
    """Signed line / pip_size."""
    if pip_size is None or float(pip_size) <= 0:
        raise ValueError("macd_line_distance_from_zero_pips: pip_size required and > 0")
    line, _, _ = _macd_lines(df, fast, slow, signal)
    return (line / float(pip_size)).rename(
        f"MACD_LINE_VS_ZERO_PIPS_{fast}_{slow}_{signal}"
    )


def macd_state_snapshot(df: pd.DataFrame, *,
                        fast: int = MACD_DEFAULT_FAST,
                        slow: int = MACD_DEFAULT_SLOW,
                        signal: int = MACD_DEFAULT_SIGNAL,
                        pip_size: float,
                        n: int = 3,
                        pctile_window: int = 60,
                        slope_n: int = 5) -> Optional[dict]:
    """Snapshot of MACD trajectory state at the LAST row of df.

    Returns dict (or None if df is empty) with:
      magnitude_pips, magnitude_pctile_60bar, hist_contracting_n,
      hist_expanding_n, hist_sign ('bullish'|'bearish'|'zero'),
      line_slope_5bar, line_vs_signal_pips, line_vs_zero_pips,
      on_bull_side, on_bear_side.

    pctile is over a strict trailing `pctile_window` bars (None if
    insufficient history). slope is over `slope_n` bars (None if
    insufficient history).
    """
    if pip_size is None or float(pip_size) <= 0:
        raise ValueError("macd_state_snapshot: pip_size required and > 0")
    if df is None or len(df) == 0:
        return None
    line, sig, hist = _macd_lines(df, fast, slow, signal)
    abs_hist = hist.abs()
    last = len(df) - 1
    last_h = float(hist.iloc[last])
    last_line = float(line.iloc[last])
    last_sig = float(sig.iloc[last])
    ps = float(pip_size)

    magnitude_pips = abs(last_h) / ps

    pctile: Optional[float] = None
    if len(df) >= pctile_window:
        window = abs_hist.iloc[last - pctile_window + 1: last + 1]
        if int(window.notna().sum()) >= pctile_window:
            cur = float(abs_hist.iloc[last])
            rank = int((window <= cur).sum())
            pctile = 100.0 * rank / float(pctile_window)

    contracting = False
    expanding = False
    if len(df) >= n:
        win = [float(x) for x in abs_hist.iloc[last - n + 1: last + 1].tolist()]
        contracting = all(win[k - 1] > win[k] for k in range(1, n))
        expanding = all(win[k - 1] < win[k] for k in range(1, n))

    if abs(last_h) < EPS:
        hist_sign = "zero"
    elif last_h > 0:
        hist_sign = "bullish"
    else:
        hist_sign = "bearish"

    line_slope: Optional[float] = None
    if len(df) > slope_n:
        line_slope = float(last_line - float(line.iloc[last - slope_n]))

    return {
        "magnitude_pips": magnitude_pips,
        "magnitude_pctile_60bar": pctile,
        "hist_contracting_n": bool(contracting),
        "hist_expanding_n": bool(expanding),
        "hist_sign": hist_sign,
        "line_slope_5bar": line_slope,
        "line_vs_signal_pips": (last_line - last_sig) / ps,
        "line_vs_zero_pips": last_line / ps,
        "on_bull_side": (last_line > last_sig) and (last_h > 0),
        "on_bear_side": (last_line < last_sig) and (last_h < 0),
    }


def macd_validates_short(snapshot: Optional[dict], *,
                         established_pips: float = MACD_VALIDATE_ESTABLISHED_PIPS,
                         pctile_high: float = MACD_VALIDATE_PCTILE_HIGH) -> bool:
    """True if MACD context permits a SHORT entry.

    Path A composite (2026-05-04): permissive — only BLOCK on STRONG
    ESTABLISHED momentum. ALLOW small/ambiguous regardless of side.

    BLOCKS:
      - hist>0 AND pctile>HIGH AND expanding  (bull mid-move accelerating)
      - hist<0 AND pctile>HIGH AND expanding  (bear mid-move accelerating
        — fade is catching the falling knife / chasing)
      - hist<0 AND |hist|_pips > X            (bear established / chase)

    Snapshot=None returns False (insufficient data is not a permit).
    """
    if snapshot is None:
        return False
    sign = snapshot.get("hist_sign")
    pctile = snapshot.get("magnitude_pctile_60bar")
    mag = snapshot.get("magnitude_pips")
    expanding = bool(snapshot.get("hist_expanding_n", False))

    if sign == "bullish" and pctile is not None and pctile > pctile_high and expanding:
        return False
    if sign == "bearish" and pctile is not None and pctile > pctile_high and expanding:
        return False
    if sign == "bearish" and mag is not None and mag > established_pips:
        return False
    return True


def macd_validates_long(snapshot: Optional[dict], *,
                        established_pips: float = MACD_VALIDATE_ESTABLISHED_PIPS,
                        pctile_high: float = MACD_VALIDATE_PCTILE_HIGH) -> bool:
    """Mirror of macd_validates_short for LONG entries.

    BLOCKS:
      - hist<0 AND pctile>HIGH AND expanding  (bear mid-move against LONG)
      - hist>0 AND pctile>HIGH AND expanding  (bull mid-move accelerating
        — chasing an extended bull)
      - hist>0 AND |hist|_pips > X            (bull established / chase)
    """
    if snapshot is None:
        return False
    sign = snapshot.get("hist_sign")
    pctile = snapshot.get("magnitude_pctile_60bar")
    mag = snapshot.get("magnitude_pips")
    expanding = bool(snapshot.get("hist_expanding_n", False))

    if sign == "bearish" and pctile is not None and pctile > pctile_high and expanding:
        return False
    if sign == "bullish" and pctile is not None and pctile > pctile_high and expanding:
        return False
    if sign == "bullish" and mag is not None and mag > established_pips:
        return False
    return True


def macd_validates_setup_35_45_30(closes: pd.Series, direction: str) -> dict:
    """Single-axis MACD(35/45/30) crossover/imminent-cross validator.

    Computes MACD at the strategy's params (35/45/30, recursive ewm) on the
    LAST bar of `closes`. Reports raw line/signal/hist values, recent
    crossover status (within last 3 bars), and projected imminent crossover
    (gap closing for 2+ bars, zero crossing within ~2 bars at current rate).

    direction: 'LONG'/'SHORT' (or 'BUY'/'SELL', mapped).

    validates:
      LONG  → bullish_cross_recent_3bars OR imminent_bullish_cross
      SHORT → bearish_cross_recent_3bars OR imminent_bearish_cross

    Returns a dict with all fields. Insufficient history → all numeric
    fields None and validates=False.
    """
    d = (direction or "").upper()
    if d == "BUY":
        d = "LONG"
    elif d == "SELL":
        d = "SHORT"
    if d not in ("LONG", "SHORT"):
        raise ValueError(f"direction must be LONG/SHORT (or BUY/SELL); got {direction!r}")

    closes_s = _to_float_series(closes).reset_index(drop=True)
    out = {
        "line_value": None,
        "signal_value": None,
        "histogram_value": None,
        "line_above_signal": None,
        "line_signal_gap": None,
        "histogram_recent_3bars": None,
        "bullish_cross_recent_3bars": False,
        "bearish_cross_recent_3bars": False,
        "imminent_bullish_cross": False,
        "imminent_bearish_cross": False,
        "validates": False,
    }
    if len(closes_s) < 5:
        return out

    m = macd(closes_s, 35, 45, 30)
    line = m.iloc[:, 0]
    sig = m.iloc[:, 1]
    hist = m.iloc[:, 2]
    last = len(closes_s) - 1

    out["line_value"] = float(line.iloc[last])
    out["signal_value"] = float(sig.iloc[last])
    out["histogram_value"] = float(hist.iloc[last])
    out["line_above_signal"] = bool(out["line_value"] > out["signal_value"])
    out["line_signal_gap"] = out["line_value"] - out["signal_value"]

    if last >= 2:
        out["histogram_recent_3bars"] = [
            float(hist.iloc[last - 2]),
            float(hist.iloc[last - 1]),
            float(hist.iloc[last]),
        ]

    # Recent crossover within last 3 bars (k = last-2, last-1, last; needs k-1 valid)
    gap = line - sig
    bull_cross = False
    bear_cross = False
    for k in range(max(0, last - 2), last + 1):
        if k - 1 < 0:
            continue
        g_prev = float(gap.iloc[k - 1])
        g_cur = float(gap.iloc[k])
        if g_cur > 0 and g_prev <= 0:
            bull_cross = True
        if g_cur < 0 and g_prev >= 0:
            bear_cross = True
    out["bullish_cross_recent_3bars"] = bull_cross
    out["bearish_cross_recent_3bars"] = bear_cross

    # Imminent crossover: gap shrinking 2+ consecutive bars + projected zero within 2 bars
    if last >= 2:
        g0 = float(gap.iloc[last - 2])
        g1 = float(gap.iloc[last - 1])
        g2 = float(gap.iloc[last])
        contracting_abs = abs(g2) < abs(g1) < abs(g0)
        if contracting_abs:
            rate = (abs(g0) - abs(g2)) / 2.0
            if rate > 0 and (abs(g2) / rate) <= 2.0:
                if g2 > 0:
                    out["imminent_bearish_cross"] = True
                elif g2 < 0:
                    out["imminent_bullish_cross"] = True

    if d == "LONG":
        out["validates"] = bool(out["bullish_cross_recent_3bars"] or out["imminent_bullish_cross"])
    else:
        out["validates"] = bool(out["bearish_cross_recent_3bars"] or out["imminent_bearish_cross"])

    return out


# -------------------------
# Forensic fire snapshot (May 19 review data collection)
# -------------------------
# Exhaustive multi-axis snapshot intended for offline analysis. Captures
# 5m + H1 + H4 indicators, swing structure, briefing levels, session/news
# context, volatility — ~150 fields per record. NOT a strategy gate; NOT
# a filter; NOT consumed by live trading logic. Sole purpose is feeding
# the May 19 review with enough context to discover which fields actually
# discriminate winners from losers.
#
# Each axis is wrapped in safe(); a single bad axis populates the errors
# list rather than killing the whole snapshot.

def _ff_safe_float(v) -> Optional[float]:
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if not np.isfinite(f):
        return None
    return f


def _ff_tail(series: pd.Series, n: int) -> list:
    if series is None or len(series) == 0:
        return []
    lo = max(0, len(series) - n)
    return [_ff_safe_float(series.iloc[i]) for i in range(lo, len(series))]


def _ff_slope(series: pd.Series, last: int, n: int) -> Optional[float]:
    if last < n or last >= len(series):
        return None
    a = _ff_safe_float(series.iloc[last])
    b = _ff_safe_float(series.iloc[last - n])
    if a is None or b is None:
        return None
    return a - b


def _ff_pctile(series: pd.Series, last: int, window: int) -> Optional[float]:
    if last + 1 < window:
        return None
    win = series.iloc[last - window + 1: last + 1].dropna()
    if len(win) < window:
        return None
    cur = _ff_safe_float(series.iloc[last])
    if cur is None:
        return None
    return 100.0 * float((win <= cur).sum()) / float(window)


def macd_continuous_view(
    closes,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
    n_lookback: int = 10,
    pip_size: float = 1.0,
) -> dict:
    """Continuous MACD trajectory view at the latest close.

    Lifts the per-bar MACD axis logic out of forensic_fire_snapshot so
    strategies can call it at decision time. Returns the same dict shape
    that ``_ff_macd_axis`` emits — when called with ``n_lookback=10`` the
    output is bit-for-bit identical (forensic capture is the canonical
    consumer; that wrapper preserves its signature).

    Inputs:
      closes: pd.Series or list/sequence of float closes (most recent
        last). Coerced to a fresh-indexed float Series internally.
      fast/slow/signal: MACD parameters. 12/26/9 (this strategy default)
        and 35/45/30 (the codebase MACD shadow default) are both used in
        the forensic axes; either is acceptable here.
      n_lookback: tail length for the *_last_N arrays (line, signal,
        hist, gap, abs_gap, hist_sign). Default 10. The 24-bar cross
        scan window and 5-bar gap-rate window are FIXED (do not vary
        with n_lookback) — they have semantic meaning ("recent crosses"
        and "short-term gap derivative") that should not drift with the
        tail length.
      pip_size: price units per pip; controls only the
        ``line_distance_zero_pips`` / ``signal_distance_zero_pips``
        fields. Default 1.0 (raw price) is fine for GBPUSD on IG TODAY
        epics.

    Insufficient history (``len(closes) < slow + signal``) returns
    ``{"insufficient_history": True, "bars_available": ..., "needed": ...}``.

    NOT a strategy gate by itself — exposes the trajectory view so
    callers can build their own gates (see the
    ``macd_view_has_recent_*_cross`` and ``macd_view_hist_*``
    convenience predicates below). No state mutated; pure function.
    """
    # Accept Series or list/sequence — `_to_float_series` expects Series.
    if not isinstance(closes, pd.Series):
        closes = pd.Series(list(closes))
    s = _to_float_series(closes).reset_index(drop=True)
    if len(s) < slow + signal:
        return {"insufficient_history": True,
                "bars_available": int(len(s)), "needed": int(slow + signal)}
    ps = float(pip_size)
    last = len(s) - 1
    n = int(n_lookback)

    ema_fast = s.ewm(span=fast, adjust=False, min_periods=1).mean()
    ema_slow = s.ewm(span=slow, adjust=False, min_periods=1).mean()
    line = ema_fast - ema_slow
    sig = line.ewm(span=signal, adjust=False, min_periods=1).mean()
    hist = line - sig
    abs_hist = hist.abs()
    gap = line - sig
    abs_gap = gap.abs()

    line_n = _ff_tail(line, n)
    sig_n = _ff_tail(sig, n)
    hist_n = _ff_tail(hist, n)
    gap_n = _ff_tail(gap, n)
    absg_n = _ff_tail(abs_gap, n)
    sign_seq = []
    for h in hist_n:
        if h is None:
            sign_seq.append("nan")
        elif h > 0:
            sign_seq.append("+")
        elif h < 0:
            sign_seq.append("-")
        else:
            sign_seq.append("0")

    bars_since_bull: Optional[int] = None
    bars_since_bear: Optional[int] = None
    recent_crosses = []
    for k in range(last, max(0, last - 23) - 1, -1):
        if k - 1 < 0:
            break
        g_prev = _ff_safe_float(gap.iloc[k - 1])
        g_cur = _ff_safe_float(gap.iloc[k])
        if g_prev is None or g_cur is None:
            continue
        if g_cur > 0 and g_prev <= 0:
            off = last - k
            if bars_since_bull is None:
                bars_since_bull = off
            recent_crosses.append({"bar_offset": off, "direction": "bull"})
        if g_cur < 0 and g_prev >= 0:
            off = last - k
            if bars_since_bear is None:
                bars_since_bear = off
            recent_crosses.append({"bar_offset": off, "direction": "bear"})

    gap_rate_5: list = []
    for k in range(max(0, last - 4), last + 1):
        if k - 1 < 0:
            gap_rate_5.append(None)
        else:
            cur = _ff_safe_float(gap.iloc[k])
            prev = _ff_safe_float(gap.iloc[k - 1])
            gap_rate_5.append((cur - prev) if (cur is not None and prev is not None) else None)
    gap_accel_5: list = []
    for i in range(len(gap_rate_5)):
        if i == 0 or gap_rate_5[i] is None or gap_rate_5[i - 1] is None:
            gap_accel_5.append(None)
        else:
            gap_accel_5.append(gap_rate_5[i] - gap_rate_5[i - 1])

    cur_dir: Optional[str] = None
    shrinking_n = growing_n = flat_n = 0
    if last >= 1:
        for off in range(0, min(20, last)):
            if last - off - 1 < 0:
                break
            a = _ff_safe_float(abs_hist.iloc[last - off])
            b = _ff_safe_float(abs_hist.iloc[last - off - 1])
            if a is None or b is None:
                break
            if abs(a - b) < 1e-12:
                d = "flat"
            elif a < b:
                d = "shrinking"
            else:
                d = "growing"
            if cur_dir is None:
                cur_dir = d
            if d == cur_dir:
                if d == "shrinking":
                    shrinking_n += 1
                elif d == "growing":
                    growing_n += 1
                else:
                    flat_n += 1
            else:
                break

    line_slope_3 = _ff_slope(line, last, 3)
    line_slope_5 = _ff_slope(line, last, 5)
    line_slope_10 = _ff_slope(line, last, 10)
    signal_slope_3 = _ff_slope(sig, last, 3)
    signal_slope_5 = _ff_slope(sig, last, 5)
    signal_slope_10 = _ff_slope(sig, last, 10)

    lines_diverging: Optional[bool] = None
    lines_converging: Optional[bool] = None
    if last >= 5:
        cur_g = _ff_safe_float(abs_gap.iloc[last])
        prev_g = _ff_safe_float(abs_gap.iloc[last - 5])
        if cur_g is not None and prev_g is not None:
            lines_diverging = cur_g > prev_g
            lines_converging = cur_g < prev_g

    last_line = _ff_safe_float(line.iloc[last])
    last_sig = _ff_safe_float(sig.iloc[last])
    last_hist = _ff_safe_float(hist.iloc[last])

    abs_pct60 = _ff_pctile(abs_hist, last, 60)
    abs_pct240 = _ff_pctile(abs_hist, last, 240)

    max_abs_12 = None
    if last >= 11:
        win = abs_hist.iloc[last - 11: last + 1].dropna()
        if len(win):
            max_abs_12 = float(win.max())
    max_abs_60 = None
    if last >= 59:
        win = abs_hist.iloc[last - 59: last + 1].dropna()
        if len(win):
            max_abs_60 = float(win.max())

    hist_vs_peak_12 = None
    if max_abs_12 and max_abs_12 > 0 and last_hist is not None:
        hist_vs_peak_12 = abs(last_hist) / max_abs_12

    return {
        "params": [fast, slow, signal],
        "line": last_line,
        "signal": last_sig,
        "hist": last_hist,
        f"line_last_{n}": line_n,
        f"signal_last_{n}": sig_n,
        f"hist_last_{n}": hist_n,
        f"gap_last_{n}": gap_n,
        f"abs_gap_last_{n}": absg_n,
        f"hist_sign_last_{n}": sign_seq,
        "bars_since_bullish_cross_24bar": bars_since_bull,
        "bars_since_bearish_cross_24bar": bars_since_bear,
        "recent_crosses_24bar": recent_crosses,
        "gap_rate_last_5bar": gap_rate_5,
        "gap_acceleration_last_5bar": gap_accel_5,
        "abs_hist_traj_run": {
            "direction": cur_dir,
            "shrinking_n": shrinking_n,
            "growing_n": growing_n,
            "flat_n": flat_n,
        },
        "line_slope_3bar": line_slope_3,
        "line_slope_5bar": line_slope_5,
        "line_slope_10bar": line_slope_10,
        "signal_slope_3bar": signal_slope_3,
        "signal_slope_5bar": signal_slope_5,
        "signal_slope_10bar": signal_slope_10,
        "lines_diverging_5bar": lines_diverging,
        "lines_converging_5bar": lines_converging,
        "line_above_zero": (last_line > 0) if last_line is not None else None,
        "line_distance_zero_pips": (last_line / ps) if last_line is not None else None,
        "signal_above_zero": (last_sig > 0) if last_sig is not None else None,
        "signal_distance_zero_pips": (last_sig / ps) if last_sig is not None else None,
        "abs_hist_pctile_60bar": abs_pct60,
        "abs_hist_pctile_240bar": abs_pct240,
        "abs_hist_vs_peak_12bar": hist_vs_peak_12,
        "max_abs_hist_12bar": max_abs_12,
        "max_abs_hist_60bar": max_abs_60,
    }


def macd_view_35_45_30(closes, n_lookback: int = 10,
                       pip_size: float = 1.0) -> dict:
    """``macd_continuous_view`` with the codebase MACD-shadow defaults
    (35/45/30). Matches the params used by continuation_sweep,
    reversal_sweep, session_impulse_breakout, and the autobot
    MACD_HIST_35_45_30 column."""
    return macd_continuous_view(closes, 35, 45, 30, n_lookback, pip_size)


def macd_view_12_26_9(closes, n_lookback: int = 10,
                      pip_size: float = 1.0) -> dict:
    """``macd_continuous_view`` with the textbook MACD defaults
    (12/26/9). Faster response than 35/45/30; matches the second axis
    captured in ``forensic_fire_snapshot``."""
    return macd_continuous_view(closes, 12, 26, 9, n_lookback, pip_size)


# ─── MACD view predicates (read-only dict probes) ────────────────────────
# Strategies that want simple inline gates can use these against the
# ``macd_continuous_view`` output instead of indexing into the dict by
# hand. Each predicate is a pure boolean function, returning False
# whenever the underlying field is missing or None (e.g. on
# insufficient history) so the caller never has to special-case
# pre-warmup paths.
def macd_view_has_recent_bullish_cross(view: dict, within_bars: int = 3) -> bool:
    """True iff the most recent bullish (line crossed above signal)
    cross sits within the last ``within_bars`` closes. False on
    insufficient_history, no cross found, or cross older than
    ``within_bars``."""
    if not isinstance(view, dict):
        return False
    n = view.get("bars_since_bullish_cross_24bar")
    return isinstance(n, int) and 0 <= n <= int(within_bars)


def macd_view_has_recent_bearish_cross(view: dict, within_bars: int = 3) -> bool:
    """Mirror of the bullish predicate. True iff the most recent
    bearish cross is within ``within_bars`` closes."""
    if not isinstance(view, dict):
        return False
    n = view.get("bars_since_bearish_cross_24bar")
    return isinstance(n, int) and 0 <= n <= int(within_bars)


def macd_view_hist_contracting(view: dict, n: int = 3) -> bool:
    """True iff |hist| has been monotonically shrinking for at least
    ``n`` consecutive bars ending at the latest close. Reads
    ``abs_hist_traj_run`` from the view."""
    if not isinstance(view, dict):
        return False
    run = view.get("abs_hist_traj_run") or {}
    return run.get("direction") == "shrinking" and int(run.get("shrinking_n", 0)) >= int(n)


def macd_view_hist_expanding(view: dict, n: int = 3) -> bool:
    """True iff |hist| has been monotonically growing for at least
    ``n`` consecutive bars ending at the latest close."""
    if not isinstance(view, dict):
        return False
    run = view.get("abs_hist_traj_run") or {}
    return run.get("direction") == "growing" and int(run.get("growing_n", 0)) >= int(n)


def _ff_macd_axis(closes: pd.Series, fast: int, slow: int, signal: int,
                  pip_size: float) -> dict:
    """Forensic-snapshot MACD axis. Thin wrapper around
    ``macd_continuous_view`` pinned to ``n_lookback=10`` so the dict key
    layout (``..._last_10``) stays stable for downstream backfill /
    review tooling that grew up against the snapshot schema. Logic is
    one definition; this preserves the legacy field names."""
    return macd_continuous_view(closes, fast, slow, signal, 10, pip_size)


def _ff_bb(closes: pd.Series, highs: pd.Series, lows: pd.Series,
           pip_size: float) -> dict:
    s = _to_float_series(closes).reset_index(drop=True)
    h = _to_float_series(highs).reset_index(drop=True)
    l = _to_float_series(lows).reset_index(drop=True)
    if len(s) < 60:
        return {"insufficient_history": True, "bars": int(len(s))}
    ps = float(pip_size)
    last = len(s) - 1

    bb = bollinger_bands(s, 20, 2.0)
    bb_mid = bb.iloc[:, 0]
    bb_up = bb.iloc[:, 1]
    bb_lo = bb.iloc[:, 2]
    bb_w = bb_up - bb_lo

    cur_close = _ff_safe_float(s.iloc[last])
    cur_up = _ff_safe_float(bb_up.iloc[last])
    cur_lo = _ff_safe_float(bb_lo.iloc[last])
    cur_mid = _ff_safe_float(bb_mid.iloc[last])
    cur_w = _ff_safe_float(bb_w.iloc[last])

    pos = None
    if (cur_close is not None and cur_up is not None and cur_lo is not None
            and (cur_up - cur_lo) > EPS):
        pos = (cur_close - cur_lo) / (cur_up - cur_lo)

    walk_up: Optional[bool] = None
    walk_lower: Optional[bool] = None
    if last >= 2:
        rh = h.iloc[last - 2: last + 1]
        rl = l.iloc[last - 2: last + 1]
        ru = bb_up.iloc[last - 2: last + 1]
        rb = bb_lo.iloc[last - 2: last + 1]
        if rh.notna().all() and ru.notna().all():
            walk_up = bool((rh.values > ru.values).all())
        if rl.notna().all() and rb.notna().all():
            walk_lower = bool((rl.values < rb.values).all())

    bars_since_up: Optional[int] = None
    bars_since_lo: Optional[int] = None
    for k in range(last, max(0, last - 60) - 1, -1):
        if bars_since_up is None:
            uk = _ff_safe_float(bb_up.iloc[k])
            hk = _ff_safe_float(h.iloc[k])
            if uk is not None and hk is not None and hk >= uk:
                bars_since_up = last - k
        if bars_since_lo is None:
            lk = _ff_safe_float(bb_lo.iloc[k])
            lwk = _ff_safe_float(l.iloc[k])
            if lk is not None and lwk is not None and lwk <= lk:
                bars_since_lo = last - k
        if bars_since_up is not None and bars_since_lo is not None:
            break

    avg_w_60 = None
    if last >= 59:
        win = bb_w.iloc[last - 59: last + 1].dropna()
        if len(win):
            avg_w_60 = float(win.mean())
    width_ratio = (cur_w / avg_w_60) if (cur_w is not None and avg_w_60 and avg_w_60 > 0) else None

    return {
        "width_pips": (cur_w / ps) if cur_w is not None else None,
        "width_raw": cur_w,
        "mid": cur_mid,
        "upper": cur_up,
        "lower": cur_lo,
        "mid_slope_3bar": _ff_slope(bb_mid, last, 3),
        "mid_slope_5bar": _ff_slope(bb_mid, last, 5),
        "mid_slope_10bar": _ff_slope(bb_mid, last, 10),
        "upper_slope_5bar": _ff_slope(bb_up, last, 5),
        "lower_slope_5bar": _ff_slope(bb_lo, last, 5),
        "price_position_in_band": pos,
        "walking_upper_3bar": walk_up,
        "walking_lower_3bar": walk_lower,
        "bars_since_touch_upper_60bar": bars_since_up,
        "bars_since_touch_lower_60bar": bars_since_lo,
        "width_vs_60bar_avg_ratio": width_ratio,
        "is_squeezed_below_avg_70pct": (width_ratio is not None and width_ratio < 0.7),
        "is_expanding_above_avg_130pct": (width_ratio is not None and width_ratio > 1.3),
    }


def _ff_ema(closes: pd.Series, highs: pd.Series, lows: pd.Series,
            pip_size: float) -> dict:
    s = _to_float_series(closes).reset_index(drop=True)
    h = _to_float_series(highs).reset_index(drop=True)
    l = _to_float_series(lows).reset_index(drop=True)
    if len(s) < 50:
        return {"insufficient_history": True, "bars": int(len(s))}
    ps = float(pip_size)
    last = len(s) - 1
    cur_c = _ff_safe_float(s.iloc[last])

    periods = [8, 13, 21, 50, 200]
    emas = {p: ema(s, p) for p in periods}

    out: dict = {}
    for p in periods:
        e = emas[p]
        last_v = _ff_safe_float(e.iloc[last])
        out[f"ema{p}"] = last_v
        out[f"price_vs_ema{p}_pips"] = ((cur_c - last_v) / ps) if (cur_c is not None and last_v is not None) else None
        out[f"ema{p}_slope_3bar"] = _ff_slope(e, last, 3)
        out[f"ema{p}_slope_5bar"] = _ff_slope(e, last, 5)
        out[f"ema{p}_slope_10bar"] = _ff_slope(e, last, 10)
        bars_since_cross: Optional[int] = None
        for k in range(last, max(0, last - 60) - 1, -1):
            if k - 1 < 0:
                break
            ck = _ff_safe_float(s.iloc[k])
            ck_prev = _ff_safe_float(s.iloc[k - 1])
            ek = _ff_safe_float(e.iloc[k])
            ek_prev = _ff_safe_float(e.iloc[k - 1])
            if any(v is None for v in [ck, ck_prev, ek, ek_prev]):
                continue
            if (ck > ek and ck_prev <= ek_prev) or (ck < ek and ck_prev >= ek_prev):
                bars_since_cross = last - k
                break
        out[f"bars_since_cross_ema{p}"] = bars_since_cross

    e8, e13, e21 = out["ema8"], out["ema13"], out["ema21"]
    if all(v is not None for v in [e8, e13, e21]):
        out["cluster_8_13_21_pips"] = (max(e8, e13, e21) - min(e8, e13, e21)) / ps
    else:
        out["cluster_8_13_21_pips"] = None

    try:
        df_for_atr = pd.DataFrame({"high": h, "low": l, "close": s}).reset_index(drop=True)
        atr14 = atr(df_for_atr, 14)
        states = _ema_stack_state(
            [emas[8], emas[13], emas[21], emas[50]],
            atr14, k=0.3, warmup_bars=50,
        )
        v = states.iloc[last] if last < len(states) else None
        if v is None or (isinstance(v, float) and np.isnan(v)):
            out["stack_state"] = None
        else:
            out["stack_state"] = str(v)
    except Exception:
        out["stack_state"] = None
    return out


def _ff_rsi(closes: pd.Series) -> dict:
    s = _to_float_series(closes).reset_index(drop=True)
    if len(s) < 30:
        return {"insufficient_history": True, "bars": int(len(s))}
    last = len(s) - 1

    rsi3 = rsi(s, 3)
    rsi14 = rsi(s, 14)
    last_r3 = _ff_safe_float(rsi3.iloc[last])
    last_r14 = _ff_safe_float(rsi14.iloc[last])

    def _bars_since(series: pd.Series, threshold: float, op: str) -> Optional[int]:
        for k in range(last, max(0, last - 60) - 1, -1):
            v = _ff_safe_float(series.iloc[k])
            if v is None:
                continue
            if op == ">" and v > threshold:
                return last - k
            if op == "<" and v < threshold:
                return last - k
        return None

    return {
        "rsi3": last_r3,
        "rsi14": last_r14,
        "rsi3_overbought": (last_r3 > 70.0) if last_r3 is not None else None,
        "rsi3_oversold": (last_r3 < 30.0) if last_r3 is not None else None,
        "rsi14_overbought": (last_r14 > 70.0) if last_r14 is not None else None,
        "rsi14_oversold": (last_r14 < 30.0) if last_r14 is not None else None,
        "rsi3_slope_3bar": _ff_slope(rsi3, last, 3),
        "rsi3_slope_5bar": _ff_slope(rsi3, last, 5),
        "rsi14_slope_3bar": _ff_slope(rsi14, last, 3),
        "rsi14_slope_5bar": _ff_slope(rsi14, last, 5),
        "bars_since_rsi3_overbought": _bars_since(rsi3, 70.0, ">"),
        "bars_since_rsi3_oversold": _bars_since(rsi3, 30.0, "<"),
        "bars_since_rsi14_overbought": _bars_since(rsi14, 70.0, ">"),
        "bars_since_rsi14_oversold": _bars_since(rsi14, 30.0, "<"),
    }


def _ff_h1(closes_h1, highs_h1, lows_h1, pip_size: float) -> dict:
    if closes_h1 is None or len(closes_h1) < 50:
        return {"insufficient_history": True,
                "bars": int(len(closes_h1)) if closes_h1 is not None else 0}
    s = _to_float_series(closes_h1).reset_index(drop=True)
    h = _to_float_series(highs_h1).reset_index(drop=True)
    l = _to_float_series(lows_h1).reset_index(drop=True)
    last = len(s) - 1
    ps = float(pip_size)
    cur_c = float(s.iloc[last])

    e8 = ema(s, 8)
    e13 = ema(s, 13)
    e21 = ema(s, 21)
    e50 = ema(s, 50)

    df = pd.DataFrame({"high": h, "low": l, "close": s}).reset_index(drop=True)
    try:
        atr14 = atr(df, 14)
        states = _ema_stack_state([e8, e13, e21, e50], atr14, k=0.3, warmup_bars=50)
        stack = states.iloc[last] if last < len(states) else None
        stack = str(stack) if stack is not None and not (isinstance(stack, float) and np.isnan(stack)) else None
    except Exception:
        stack = None

    bb_width_pips = None
    bb_pos = None
    try:
        bb = bollinger_bands(s, 20, 2.0)
        denom = float(bb.iloc[last, 1]) - float(bb.iloc[last, 2])
        bb_width_pips = denom / ps
        bb_pos = ((cur_c - float(bb.iloc[last, 2])) / denom) if denom > EPS else None
    except Exception:
        pass

    m = macd(s, 12, 26, 9)
    m_line = float(m.iloc[last, 0])
    m_sig = float(m.iloc[last, 1])
    m_hist = float(m.iloc[last, 2])

    r14 = rsi(s, 14)
    last_r14 = float(r14.iloc[last])

    trend_6bar = "mixed"
    if last >= 5:
        recent_h = [float(x) for x in h.iloc[last - 5: last + 1].tolist()]
        recent_l = [float(x) for x in l.iloc[last - 5: last + 1].tolist()]
        hh = sum(1 for i in range(1, 6) if recent_h[i] > recent_h[i - 1])
        hl = sum(1 for i in range(1, 6) if recent_l[i] > recent_l[i - 1])
        lh = sum(1 for i in range(1, 6) if recent_h[i] < recent_h[i - 1])
        ll = sum(1 for i in range(1, 6) if recent_l[i] < recent_l[i - 1])
        if hh >= 4 and hl >= 4:
            trend_6bar = "uptrend"
        elif lh >= 4 and ll >= 4:
            trend_6bar = "downtrend"

    return {
        "last_bar": {"high": float(h.iloc[last]), "low": float(l.iloc[last]),
                     "close": float(s.iloc[last])},
        "ema8": float(e8.iloc[last]),
        "ema21": float(e21.iloc[last]),
        "ema50": float(e50.iloc[last]),
        "ema8_slope_5bar": _ff_slope(e8, last, 5),
        "ema21_slope_5bar": _ff_slope(e21, last, 5),
        "ema50_slope_5bar": _ff_slope(e50, last, 5),
        "stack_state": stack,
        "price_vs_ema50_pips": (cur_c - float(e50.iloc[last])) / ps,
        "trend_6bar": trend_6bar,
        "bb_width_pips": bb_width_pips,
        "bb_position_in_band": bb_pos,
        "macd_line": m_line,
        "macd_signal": m_sig,
        "macd_hist": m_hist,
        "macd_sign": "+" if m_hist > 0 else "-" if m_hist < 0 else "0",
        "macd_line_slope_3bar": _ff_slope(m.iloc[:, 0], last, 3),
        "rsi14": last_r14,
        "rsi14_slope_3bar": _ff_slope(r14, last, 3),
    }


def h1_location(symbol: str,
                pip_size: float = 1.0,
                near_band_threshold: float = 0.20,
                period: int = 20,
                std: float = 2.0) -> Optional[Dict[str, Any]]:
    """Raw H1 BB-location reader. NO regime interpretation — the caller (regime
    engine, future confirmation engine) decides fade-vs-follow from the
    regime context.

    Reads H1 candles from the htf cache (populated live by TimeframeContext
    on every 5m close + persisted to disk by htf_cache.save_cached_candles).
    Computes BB(20,2) on H1 closes and returns the latest bar's position.

    Returns:
        dict with keys:
            position        — BB%: (close - lower) / (upper - lower), 0..1
                              0 = at lower band, 1 = at upper band
            band_side       — "NEAR_LOWER" | "MID" | "NEAR_UPPER"
            raw_strength    — 0..1, how deep into the near-band zone
                              (NEAR_LOWER: 1.0 at lower band, 0.0 at threshold;
                               NEAR_UPPER: symmetric; MID: 0.0)
            distance_pips   — signed distance close-to-mid in pips
            bb_width_pips   — upper-lower in pips
            n_candles       — count of H1 candles read
        Or None if data insufficient / stale / cache missing.

    Reusable: regime_engine consumes (band_side, raw_strength) and interprets
    via regime; any future confirmation engine can use position/distance_pips
    directly.
    """
    try:
        from trend_detection import load_h1_candles_from_cache
    except Exception:
        return None
    candles = load_h1_candles_from_cache(symbol)
    if not candles or len(candles) < period + 1:
        return None
    try:
        closes = pd.Series([float(c["close"]) for c in candles])
    except (KeyError, TypeError, ValueError):
        return None
    if len(closes) < period:
        return None
    try:
        bb = bollinger_bands(closes, period, std)
        mid = float(bb.iloc[-1, 0])
        upper = float(bb.iloc[-1, 1])
        lower = float(bb.iloc[-1, 2])
    except Exception:
        return None
    denom = upper - lower
    if denom <= 0 or not np.isfinite(denom):
        return None
    cur = float(closes.iloc[-1])
    position = (cur - lower) / denom  # 0..1 (may exceed if outside band)
    # Clamp position for strength calc but keep raw position for telemetry
    pos_clamped = max(0.0, min(1.0, position))
    if pos_clamped <= near_band_threshold:
        band_side = "NEAR_LOWER"
        raw_strength = 1.0 - (pos_clamped / near_band_threshold)
    elif pos_clamped >= 1.0 - near_band_threshold:
        band_side = "NEAR_UPPER"
        raw_strength = (pos_clamped - (1.0 - near_band_threshold)) / near_band_threshold
    else:
        band_side = "MID"
        raw_strength = 0.0
    ps = float(pip_size) if pip_size and pip_size > 0 else 1.0
    return {
        "position": position,
        "band_side": band_side,
        "raw_strength": float(max(0.0, min(1.0, raw_strength))),
        "distance_pips": (cur - mid) / ps,
        "bb_width_pips": denom / ps,
        "n_candles": len(closes),
    }


def h1_ema_direction(symbol: str,
                     fast: int = 8,
                     slow: int = 21,
                     full_strength_separation_pips: float = 15.0,
                     flat_threshold_pips: float = 0.5,
                     pip_size: float = 1.0) -> Optional[Dict[str, Any]]:
    """Independent H1 directional vote from the H1 EMA stack alone.

    Reads H1 candles from the htf cache (populated by TimeframeContext on
    every 5m close + persisted by htf_cache), computes EMA-fast and EMA-slow
    on H1 closes, returns direction + a strength scaled by EMA separation.

    Direction is set entirely by the H1 EMA stack — it does NOT depend on
    the 5m regime, so the consuming regime engine can use it as a true
    independent input that can either agree with or oppose the 5m read.

    Strength: |ema_fast - ema_slow| in pips, normalised by
    `full_strength_separation_pips` (default 15 — full strength at 15+ pip
    separation, scaled linearly down to 0 at flat_threshold_pips).
    Returns FLAT when |separation| < flat_threshold_pips (~ EMAs crossing).

    Returns:
        dict with keys:
            direction            — "BULLISH" | "BEARISH" | "FLAT"
            separation_strength  — 0..1
            separation_pips      — signed (fast - slow) in pips
            ema8 / ema21         — raw EMA values (fast / slow)
            n_candles            — count of H1 candles used
        Or None if data insufficient / cache missing.
    """
    try:
        from trend_detection import load_h1_candles_from_cache
    except Exception:
        return None
    candles = load_h1_candles_from_cache(symbol)
    if not candles or len(candles) < max(fast, slow) + 5:
        return None
    try:
        closes = pd.Series([float(c["close"]) for c in candles])
    except (KeyError, TypeError, ValueError):
        return None
    try:
        e_fast = ema(closes, fast)
        e_slow = ema(closes, slow)
        fv = float(e_fast.iloc[-1])
        sv = float(e_slow.iloc[-1])
    except Exception:
        return None
    if not (np.isfinite(fv) and np.isfinite(sv)):
        return None
    ps = float(pip_size) if pip_size and pip_size > 0 else 1.0
    sep_pips = (fv - sv) / ps  # signed
    abs_sep = abs(sep_pips)
    if abs_sep < float(flat_threshold_pips):
        direction = "FLAT"
        strength = 0.0
    else:
        cap = float(full_strength_separation_pips)
        strength = min(abs_sep / cap, 1.0) if cap > 0 else 1.0
        direction = "BULLISH" if sep_pips > 0 else "BEARISH"
    return {
        "direction": direction,
        "separation_strength": float(max(0.0, min(1.0, strength))),
        "separation_pips": float(sep_pips),
        "ema8": fv,
        "ema21": sv,
        "n_candles": len(closes),
    }


def _ff_h4(closes_h4, highs_h4, lows_h4, pip_size: float) -> dict:
    if closes_h4 is None or len(closes_h4) < 50:
        return {"insufficient_history": True,
                "bars": int(len(closes_h4)) if closes_h4 is not None else 0}
    s = _to_float_series(closes_h4).reset_index(drop=True)
    h = _to_float_series(highs_h4).reset_index(drop=True)
    l = _to_float_series(lows_h4).reset_index(drop=True)
    last = len(s) - 1
    ps = float(pip_size)
    cur_c = float(s.iloc[last])

    e50 = ema(s, 50)
    e200 = ema(s, 200) if len(s) >= 200 else None

    trend_4bar = "mixed"
    if last >= 3:
        recent_h = [float(x) for x in h.iloc[last - 3: last + 1].tolist()]
        recent_l = [float(x) for x in l.iloc[last - 3: last + 1].tolist()]
        hh = sum(1 for i in range(1, 4) if recent_h[i] > recent_h[i - 1])
        ll = sum(1 for i in range(1, 4) if recent_l[i] < recent_l[i - 1])
        if hh >= 3:
            trend_4bar = "uptrend"
        elif ll >= 3:
            trend_4bar = "downtrend"

    return {
        "last_bar": {"high": float(h.iloc[last]), "low": float(l.iloc[last]), "close": cur_c},
        "ema50": float(e50.iloc[last]),
        "ema200": float(e200.iloc[last]) if e200 is not None else None,
        "price_vs_ema50_pips": (cur_c - float(e50.iloc[last])) / ps,
        "price_vs_ema200_pips": ((cur_c - float(e200.iloc[last])) / ps) if e200 is not None else None,
        "trend_4bar": trend_4bar,
    }


def _ff_swing(closes: pd.Series, highs: pd.Series, lows: pd.Series,
              pip_size: float) -> dict:
    s = _to_float_series(closes).reset_index(drop=True)
    h = _to_float_series(highs).reset_index(drop=True)
    l = _to_float_series(lows).reset_index(drop=True)
    if len(s) < 24:
        return {"insufficient_history": True, "bars": int(len(s))}
    last = len(s) - 1
    ps = float(pip_size)
    cur_c = float(s.iloc[last])

    win24_h = h.iloc[max(0, last - 23): last + 1]
    win24_l = l.iloc[max(0, last - 23): last + 1]
    swing_high = float(win24_h.max())
    swing_low = float(win24_l.min())
    bars_since_high = (len(win24_h) - 1) - int(win24_h.values.argmax())
    bars_since_low = (len(win24_l) - 1) - int(win24_l.values.argmin())

    broke_high_12: Optional[bool] = None
    broke_low_12: Optional[bool] = None
    if last >= 12:
        prior_h = float(h.iloc[last - 12: last].max())
        prior_l = float(l.iloc[last - 12: last].min())
        broke_high_12 = bool(float(h.iloc[last]) > prior_h)
        broke_low_12 = bool(float(l.iloc[last]) < prior_l)

    making_hh: Optional[bool] = None
    making_ll: Optional[bool] = None
    if last >= 23:
        windows_h = []
        windows_l = []
        for w in range(4):
            start = last - 23 + w * 6
            end = start + 6
            windows_h.append(float(h.iloc[start:end].max()))
            windows_l.append(float(l.iloc[start:end].min()))
        making_hh = all(windows_h[i] > windows_h[i - 1] for i in range(1, 4))
        making_ll = all(windows_l[i] < windows_l[i - 1] for i in range(1, 4))

    pdh = pdl = dist_pdh = dist_pdl = None
    if last >= 287:
        prior_window_start = max(0, last - 575)
        prior_window_end = last - 287
        if prior_window_end > prior_window_start:
            pdh = float(h.iloc[prior_window_start: prior_window_end].max())
            pdl = float(l.iloc[prior_window_start: prior_window_end].min())
            dist_pdh = (cur_c - pdh) / ps
            dist_pdl = (cur_c - pdl) / ps

    return {
        "recent_swing_high_24bar": swing_high,
        "recent_swing_low_24bar": swing_low,
        "swing_high_distance_pips": (swing_high - cur_c) / ps,
        "swing_low_distance_pips": (cur_c - swing_low) / ps,
        "bars_since_swing_high": bars_since_high,
        "bars_since_swing_low": bars_since_low,
        "broke_swing_high_12bar": broke_high_12,
        "broke_swing_low_12bar": broke_low_12,
        "making_higher_highs_4window": making_hh,
        "making_lower_lows_4window": making_ll,
        "prior_day_high": pdh,
        "prior_day_low": pdl,
        "distance_from_pdh_pips": dist_pdh,
        "distance_from_pdl_pips": dist_pdl,
    }


def _ff_levels(closes: pd.Series, briefing_levels, pip_size: float) -> dict:
    if briefing_levels is None or not briefing_levels:
        return {"available": False}
    s = _to_float_series(closes).reset_index(drop=True)
    last = len(s) - 1
    cur_c = float(s.iloc[last])
    ps = float(pip_size)

    above = [lv for lv in briefing_levels
             if lv.get("price") is not None and lv["price"] > cur_c]
    below = [lv for lv in briefing_levels
             if lv.get("price") is not None and lv["price"] < cur_c]
    nearest_above = min(above, key=lambda x: x["price"] - cur_c) if above else None
    nearest_below = max(below, key=lambda x: x["price"] - cur_c) if below else None

    return {
        "available": True,
        "level_count": len(briefing_levels),
        "nearest_above_pips": ((nearest_above["price"] - cur_c) / ps) if nearest_above else None,
        "nearest_above_type": nearest_above.get("type") if nearest_above else None,
        "nearest_above_confluence": nearest_above.get("confluence") if nearest_above else None,
        "nearest_below_pips": ((cur_c - nearest_below["price"]) / ps) if nearest_below else None,
        "nearest_below_type": nearest_below.get("type") if nearest_below else None,
        "nearest_below_confluence": nearest_below.get("confluence") if nearest_below else None,
    }


def _ff_volatility(highs_5m, lows_5m, closes_5m,
                   highs_h1, lows_h1, closes_h1, pip_size: float) -> dict:
    s = _to_float_series(closes_5m).reset_index(drop=True)
    h = _to_float_series(highs_5m).reset_index(drop=True)
    l = _to_float_series(lows_5m).reset_index(drop=True)
    if len(s) < 60:
        return {"insufficient_history": True, "bars": int(len(s))}
    last = len(s) - 1
    ps = float(pip_size)

    df5 = pd.DataFrame({"high": h, "low": l, "close": s}).reset_index(drop=True)
    atr5 = atr(df5, 14)
    last_atr5 = float(atr5.iloc[last])
    avg_atr_60 = float(atr5.iloc[last - 59: last + 1].dropna().mean()) if last >= 59 else None
    atr_ratio = (last_atr5 / avg_atr_60) if (avg_atr_60 and avg_atr_60 > 0) else None

    atr_h1 = None
    if closes_h1 is not None and len(closes_h1) >= 14:
        s_h1 = _to_float_series(closes_h1).reset_index(drop=True)
        h_h1 = _to_float_series(highs_h1).reset_index(drop=True)
        l_h1 = _to_float_series(lows_h1).reset_index(drop=True)
        df_h1 = pd.DataFrame({"high": h_h1, "low": l_h1, "close": s_h1}).reset_index(drop=True)
        atr_h1 = float(atr(df_h1, 14).iloc[len(s_h1) - 1])

    last_bar_range = float(h.iloc[last]) - float(l.iloc[last])
    last_bar_range_vs_atr = (last_bar_range / last_atr5) if last_atr5 > 0 else None

    rng_5: Optional[float] = None
    if last >= 4:
        rng_5 = float(h.iloc[last - 4: last + 1].max()) - float(l.iloc[last - 4: last + 1].min())
    last_5_vs_atr_5x = (rng_5 / (last_atr5 * 5)) if (rng_5 is not None and last_atr5 > 0) else None

    open_prev = float(s.iloc[last - 1]) if last >= 1 else None
    last_close = float(s.iloc[last])
    body = abs(last_close - open_prev) if open_prev is not None else None
    body_ratio = (body / last_bar_range) if (body is not None and last_bar_range > 0) else None

    return {
        "atr14_5m_pips": last_atr5 / ps,
        "atr14_5m_raw": last_atr5,
        "atr14_vs_60bar_avg_ratio": atr_ratio,
        "atr14_h1_pips": (atr_h1 / ps) if atr_h1 is not None else None,
        "last_bar_range_pips": last_bar_range / ps,
        "last_bar_range_vs_atr": last_bar_range_vs_atr,
        "last_5bar_total_range_pips": (rng_5 / ps) if rng_5 is not None else None,
        "last_5bar_range_vs_atr_5x": last_5_vs_atr_5x,
        "last_bar_body_range_ratio": body_ratio,
    }


def _ff_session(session_state, news_state) -> dict:
    if not session_state and not news_state:
        return {"available": False}
    out: dict = {"available": True}
    if session_state:
        out["session_name"] = session_state.get("name")
        out["minutes_since_session_open"] = session_state.get("minutes_since_open")
        out["minutes_until_session_close"] = session_state.get("minutes_until_close")
    if news_state:
        out["minutes_since_news"] = news_state.get("minutes_since_event")
        out["minutes_until_news"] = news_state.get("minutes_until_event")
        out["last_event"] = news_state.get("last_event")
        out["next_event"] = news_state.get("next_event")
    return out


def _ff_structure(closes: pd.Series, highs: pd.Series, lows: pd.Series,
                  pip_size: float) -> dict:
    s = _to_float_series(closes).reset_index(drop=True)
    h = _to_float_series(highs).reset_index(drop=True)
    l = _to_float_series(lows).reset_index(drop=True)
    if len(s) < 24:
        return {"insufficient_history": True, "bars": int(len(s))}
    last = len(s) - 1
    ps = float(pip_size)
    cur = float(s.iloc[last])

    last_12 = []
    for k in range(max(0, last - 11), last + 1):
        prev_close = float(s.iloc[k - 1]) if k - 1 >= 0 else float(s.iloc[k])
        last_12.append({
            "open_approx": prev_close,
            "high": float(h.iloc[k]),
            "low": float(l.iloc[k]),
            "close": float(s.iloc[k]),
        })

    def _disp(n: int) -> Optional[float]:
        if last < n:
            return None
        return (cur - float(s.iloc[last - n])) / ps

    biggest_range = None
    biggest_offset = None
    for k in range(max(0, last - 11), last + 1):
        rng = float(h.iloc[k]) - float(l.iloc[k])
        if biggest_range is None or rng > biggest_range:
            biggest_range = rng
            biggest_offset = last - k

    consec_n = 0
    consec_dir = "flat"
    if last >= 1:
        for k in range(last, max(0, last - 24) - 1, -1):
            if k - 1 < 0:
                break
            cur_c_k = float(s.iloc[k])
            prev_c = float(s.iloc[k - 1])
            d = "up" if cur_c_k > prev_c else "down" if cur_c_k < prev_c else "flat"
            if k == last:
                consec_dir = d
                if d != "flat":
                    consec_n = 1
            else:
                if d == consec_dir:
                    consec_n += 1
                else:
                    break

    touching_up: Optional[int] = 0
    touching_lo: Optional[int] = 0
    try:
        bb = bollinger_bands(s, 20, 2.0)
        bb_up = bb.iloc[:, 1]
        bb_lo = bb.iloc[:, 2]
        for k in range(max(0, last - 11), last + 1):
            ru = _ff_safe_float(bb_up.iloc[k])
            rb = _ff_safe_float(bb_lo.iloc[k])
            hk = _ff_safe_float(h.iloc[k])
            lk = _ff_safe_float(l.iloc[k])
            if ru is not None and hk is not None and hk >= ru:
                touching_up += 1
            if rb is not None and lk is not None and lk <= rb:
                touching_lo += 1
    except Exception:
        touching_up = touching_lo = None

    return {
        "last_12_bars": last_12,
        "net_displacement_6bar_pips": _disp(6),
        "net_displacement_12bar_pips": _disp(12),
        "net_displacement_24bar_pips": _disp(24),
        "biggest_bar_range_pips_12bar": (biggest_range / ps) if biggest_range else None,
        "biggest_bar_offset_12bar": biggest_offset,
        "consecutive_same_dir_bars": consec_n,
        "consecutive_dir": consec_dir,
        "bars_touching_upper_bb_12bar": touching_up,
        "bars_touching_lower_bb_12bar": touching_lo,
    }


def forensic_fire_snapshot(
    closes_5m: pd.Series,
    highs_5m: pd.Series,
    lows_5m: pd.Series,
    closes_h1: Optional[pd.Series] = None,
    highs_h1: Optional[pd.Series] = None,
    lows_h1: Optional[pd.Series] = None,
    closes_h4: Optional[pd.Series] = None,
    highs_h4: Optional[pd.Series] = None,
    lows_h4: Optional[pd.Series] = None,
    *,
    briefing_levels: Optional[list] = None,
    session_state: Optional[dict] = None,
    news_state: Optional[dict] = None,
    pip_size: float,
    n: int = 3,
) -> dict:
    """Exhaustive multi-axis forensic snapshot for offline review.

    Captures ~150 fields across MACD (35/45/30 + 12/26/9), Bollinger,
    EMA stack (8/13/21/50/200), RSI (3 + 14), H1, H4, swing structure,
    briefing levels, session/news context, volatility, and recent price
    structure. Each axis is wrapped so a single failure populates the
    `errors` list rather than killing the whole snapshot.

    Inputs:
      closes_5m / highs_5m / lows_5m: 5m bar Series for the instrument.
      closes_h1 / highs_h1 / lows_h1: H1 bar Series (optional).
      closes_h4 / highs_h4 / lows_h4: H4 bar Series (optional).
      briefing_levels: list of dicts with 'price' / 'type' / 'confluence'
        (optional).
      session_state: dict with 'name', 'minutes_since_open', 'minutes_until_close'
        (optional).
      news_state: dict with 'minutes_since_event', 'minutes_until_event',
        'last_event', 'next_event' (optional).
      pip_size: REQUIRED (price units per pip).
      n: trajectory window for MACD axis (kept for API parity).

    Returns: nested dict by axis, plus 'schema_version' and 'errors'.
    NOT a strategy gate — for May 19 review consumption only.
    """
    if pip_size is None or float(pip_size) <= 0:
        raise ValueError("forensic_fire_snapshot: pip_size required and > 0")
    if closes_5m is None or len(closes_5m) == 0:
        return {"error": "no_5m_data", "schema_version": 1, "errors": []}

    out: dict = {"schema_version": 1, "errors": []}

    def _safe(name: str, fn):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001
            out["errors"].append({"axis": name, "error": str(exc)})
            return {"error": str(exc)}

    out["macd_35_45_30"] = _safe("macd_35_45_30",
                                 lambda: _ff_macd_axis(closes_5m, 35, 45, 30, pip_size))
    out["macd_12_26_9"] = _safe("macd_12_26_9",
                                lambda: _ff_macd_axis(closes_5m, 12, 26, 9, pip_size))
    out["bb_5m"] = _safe("bb_5m", lambda: _ff_bb(closes_5m, highs_5m, lows_5m, pip_size))
    out["ema_5m"] = _safe("ema_5m", lambda: _ff_ema(closes_5m, highs_5m, lows_5m, pip_size))
    out["rsi_5m"] = _safe("rsi_5m", lambda: _ff_rsi(closes_5m))
    out["h1"] = _safe("h1", lambda: _ff_h1(closes_h1, highs_h1, lows_h1, pip_size))
    out["h4"] = _safe("h4", lambda: _ff_h4(closes_h4, highs_h4, lows_h4, pip_size))
    out["swing_5m"] = _safe("swing_5m",
                            lambda: _ff_swing(closes_5m, highs_5m, lows_5m, pip_size))
    out["levels"] = _safe("levels",
                          lambda: _ff_levels(closes_5m, briefing_levels, pip_size))
    out["volatility"] = _safe("volatility",
                              lambda: _ff_volatility(highs_5m, lows_5m, closes_5m,
                                                     highs_h1, lows_h1, closes_h1, pip_size))
    out["session"] = _safe("session", lambda: _ff_session(session_state, news_state))
    out["structure_5m"] = _safe("structure_5m",
                                lambda: _ff_structure(closes_5m, highs_5m, lows_5m, pip_size))
    return out


# -------------------------
# Comprehensive setup snapshot (multi-axis)
# -------------------------
# Single function that returns a flat dict across MACD (35/45/30 + 12/26/9),
# Bollinger Bands (20/2), EMA stack (8/13/21/50), RSI (3 + 14), and recent
# price structure. Deliberately exhaustive — Phase 2 will probe which axes
# discriminate winners from losers. None for fields that can't be computed
# (insufficient history, NaN propagation).

def _snap_at(series: pd.Series, i: int) -> Optional[float]:
    """Float value at index i, or None if out-of-range or NaN."""
    if i < 0 or i >= len(series):
        return None
    v = series.iloc[i]
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if not np.isfinite(f):
        return None
    return f


def _snap_slope(series: pd.Series, i: int, n: int) -> Optional[float]:
    """series[i] - series[i-n], or None if either point is missing."""
    cur = _snap_at(series, i)
    prev = _snap_at(series, i - n)
    if cur is None or prev is None:
        return None
    return cur - prev


def _snap_pctile(series: pd.Series, i: int, window: int) -> Optional[float]:
    """Percentile rank (0-100) of series[i] within trailing `window` bars
    (inclusive of i). None if insufficient non-NaN history."""
    if i + 1 < window:
        return None
    win = series.iloc[i - window + 1: i + 1]
    cur = _snap_at(series, i)
    if cur is None:
        return None
    win_clean = win.dropna()
    if len(win_clean) < window:
        return None
    return 100.0 * float((win_clean <= cur).sum()) / float(window)


def _macd_axis_snapshot(prefix: str,
                        line: pd.Series, sig: pd.Series, hist: pd.Series,
                        i: int, n: int, ps: float) -> dict:
    """Emit the 12 fields for one MACD axis (35/45/30 or 12/26/9)."""
    ln_v = _snap_at(line, i)
    sg_v = _snap_at(sig, i)
    ht_v = _snap_at(hist, i)
    abs_hist = hist.abs()

    contracting: Optional[bool] = None
    expanding: Optional[bool] = None
    if i + 1 >= n:
        win = [_snap_at(abs_hist, j) for j in range(i - n + 1, i + 1)]
        if all(x is not None for x in win):
            contracting = all(win[k - 1] > win[k] for k in range(1, n))
            expanding = all(win[k - 1] < win[k] for k in range(1, n))

    return {
        f"{prefix}_line": ln_v,
        f"{prefix}_signal": sg_v,
        f"{prefix}_hist": ht_v,
        f"{prefix}_line_above_signal": (ln_v is not None and sg_v is not None and ln_v > sg_v),
        f"{prefix}_line_above_zero": (ln_v is not None and ln_v > 0),
        f"{prefix}_signal_above_zero": (sg_v is not None and sg_v > 0),
        f"{prefix}_hist_size_pips": (abs(ht_v) / ps) if ht_v is not None else None,
        f"{prefix}_hist_size_pctile_60bar": _snap_pctile(abs_hist, i, 60),
        f"{prefix}_hist_contracting_n3": contracting,
        f"{prefix}_hist_expanding_n3": expanding,
        f"{prefix}_line_slope_5bar": _snap_slope(line, i, 5),
        f"{prefix}_signal_slope_5bar": _snap_slope(sig, i, 5),
        f"{prefix}_line_signal_gap_pips": ((ln_v - sg_v) / ps) if (ln_v is not None and sg_v is not None) else None,
        f"{prefix}_line_zero_distance_pips": (ln_v / ps) if ln_v is not None else None,
    }


def comprehensive_setup_snapshot(closes: pd.Series,
                                 highs: pd.Series,
                                 lows: pd.Series,
                                 *,
                                 pip_size: float,
                                 n: int = 3) -> Optional[dict]:
    """Multi-axis snapshot at the LAST bar of the supplied Series.

    Inputs: aligned closes/highs/lows Series for one instrument's 5m bars.
    pip_size REQUIRED (price units per pip; for IG points feed use 1.0).
    n: trajectory window for the macd_*_contracting_n3/expanding_n3 flags.

    Returns flat dict (or None if inputs empty/misaligned). All fields
    None on insufficient history / NaN.
    """
    if pip_size is None or float(pip_size) <= 0:
        raise ValueError("comprehensive_setup_snapshot: pip_size required and > 0")
    if closes is None or len(closes) == 0:
        return None
    if not (len(closes) == len(highs) == len(lows)):
        raise ValueError("comprehensive_setup_snapshot: closes/highs/lows lengths must align")

    ps = float(pip_size)
    closes_s = _to_float_series(closes).reset_index(drop=True)
    highs_s = _to_float_series(highs).reset_index(drop=True)
    lows_s = _to_float_series(lows).reset_index(drop=True)
    last = len(closes_s) - 1

    out: dict = {}

    # ── MACD 35/45/30 axis
    m35 = macd(closes_s, 35, 45, 30)
    out.update(_macd_axis_snapshot(
        "macd35",
        m35.iloc[:, 0], m35.iloc[:, 1], m35.iloc[:, 2],
        last, n, ps,
    ))

    # ── MACD 12/26/9 axis (chart-aligned)
    m12 = macd(closes_s, 12, 26, 9)
    out.update(_macd_axis_snapshot(
        "macd12",
        m12.iloc[:, 0], m12.iloc[:, 1], m12.iloc[:, 2],
        last, n, ps,
    ))

    # ── Bollinger Bands 20/2 axis
    bb = bollinger_bands(closes_s, 20, 2.0)
    bb_mid = bb.iloc[:, 0]
    bb_upper = bb.iloc[:, 1]
    bb_lower = bb.iloc[:, 2]
    bb_width = bb_upper - bb_lower

    cur_close = _snap_at(closes_s, last)
    cur_upper = _snap_at(bb_upper, last)
    cur_lower = _snap_at(bb_lower, last)
    cur_width = _snap_at(bb_width, last)

    out["bb_width_pips"] = (cur_width / ps) if cur_width is not None else None
    out["bb_mid_value"] = _snap_at(bb_mid, last)
    out["bb_mid_slope_5bar"] = _snap_slope(bb_mid, last, 5)
    out["bb_mid_slope_pctile_60bar"] = _snap_pctile(bb_mid.diff(5), last, 60)
    out["bb_upper_slope_5bar"] = _snap_slope(bb_upper, last, 5)
    out["bb_lower_slope_5bar"] = _snap_slope(bb_lower, last, 5)

    up_sl = out["bb_upper_slope_5bar"]
    lo_sl = out["bb_lower_slope_5bar"]
    out["bb_widening"] = (up_sl is not None and lo_sl is not None and up_sl > 0 and lo_sl < 0)
    out["bb_contracting"] = (up_sl is not None and lo_sl is not None and up_sl < 0 and lo_sl > 0)

    # walking the band: of last 3 bars (incl current), all highs > upper / lows < lower
    walk_n = 3
    if last >= walk_n - 1:
        rh = highs_s.iloc[last - walk_n + 1: last + 1]
        rl = lows_s.iloc[last - walk_n + 1: last + 1]
        ru = bb_upper.iloc[last - walk_n + 1: last + 1]
        rb = bb_lower.iloc[last - walk_n + 1: last + 1]
        if rh.notna().all() and ru.notna().all() and rl.notna().all() and rb.notna().all():
            out["bb_walking_upper"] = bool((rh.values > ru.values).all())
            out["bb_walking_lower"] = bool((rl.values < rb.values).all())
        else:
            out["bb_walking_upper"] = None
            out["bb_walking_lower"] = None
    else:
        out["bb_walking_upper"] = None
        out["bb_walking_lower"] = None

    if cur_close is not None and cur_upper is not None and cur_lower is not None and (cur_upper - cur_lower) > EPS:
        out["price_position_in_band"] = (cur_close - cur_lower) / (cur_upper - cur_lower)
    else:
        out["price_position_in_band"] = None

    # ── EMA axis (8 / 13 / 21 / 50 — 13 needed for ema_stack_state)
    ema8_s = ema(closes_s, 8)
    ema13_s = ema(closes_s, 13)
    ema21_s = ema(closes_s, 21)
    ema50_s = ema(closes_s, 50)

    out["ema8_value"] = _snap_at(ema8_s, last)
    out["ema21_value"] = _snap_at(ema21_s, last)
    out["ema50_value"] = _snap_at(ema50_s, last)
    out["ema8_slope_5bar"] = _snap_slope(ema8_s, last, 5)
    out["ema21_slope_5bar"] = _snap_slope(ema21_s, last, 5)
    out["ema50_slope_5bar"] = _snap_slope(ema50_s, last, 5)

    cur_ema50 = out["ema50_value"]
    if cur_close is not None and cur_ema50 is not None:
        out["price_above_ema50"] = bool(cur_close > cur_ema50)
        out["price_distance_from_ema50_pips"] = (cur_close - cur_ema50) / ps
    else:
        out["price_above_ema50"] = None
        out["price_distance_from_ema50_pips"] = None

    # ema_stack_state (needs ATR for compression check)
    df_for_atr = pd.DataFrame({
        "high": highs_s, "low": lows_s, "close": closes_s,
    }).reset_index(drop=True)
    try:
        atr14 = atr(df_for_atr, 14)
        states = _ema_stack_state(
            [ema8_s, ema13_s, ema21_s, ema50_s],
            atr14, k=0.3, warmup_bars=50,
        )
        v = states.iloc[last] if last < len(states) else None
        out["ema_stack_state"] = v if (v is not None and not (isinstance(v, float) and np.isnan(v))) else None
    except Exception:
        out["ema_stack_state"] = None

    # ── RSI axis
    rsi3_s = rsi(closes_s, 3)
    rsi14_s = rsi(closes_s, 14)
    r3 = _snap_at(rsi3_s, last)
    r14 = _snap_at(rsi14_s, last)
    out["rsi3_value"] = r3
    out["rsi3_overbought"] = (r3 is not None and r3 > 70.0)
    out["rsi3_oversold"] = (r3 is not None and r3 < 30.0)
    out["rsi3_slope_3bar"] = _snap_slope(rsi3_s, last, 3)
    out["rsi14_value"] = r14
    out["rsi14_overbought"] = (r14 is not None and r14 > 70.0)
    out["rsi14_oversold"] = (r14 is not None and r14 < 30.0)
    out["rsi14_slope_3bar"] = _snap_slope(rsi14_s, last, 3)

    # ── Price structure axis
    if last >= 11:
        last12_h = highs_s.iloc[last - 11: last + 1]
        last12_l = lows_s.iloc[last - 11: last + 1]
        out["recent_high_12bar"] = float(last12_h.max())
        out["recent_low_12bar"] = float(last12_l.min())
        # bars_since: 0 == current bar; argmax/argmin index within the 12-slice
        out["bars_since_recent_high"] = int(11 - int(last12_h.values.argmax()))
        out["bars_since_recent_low"] = int(11 - int(last12_l.values.argmin()))
    else:
        out["recent_high_12bar"] = None
        out["recent_low_12bar"] = None
        out["bars_since_recent_high"] = None
        out["bars_since_recent_low"] = None

    # making higher high / lower low: 12-bar window vs preceding 12-bar window
    if last >= 23:
        cur_h = float(highs_s.iloc[last - 11: last + 1].max())
        prev_h = float(highs_s.iloc[last - 23: last - 11].max())
        cur_l = float(lows_s.iloc[last - 11: last + 1].min())
        prev_l = float(lows_s.iloc[last - 23: last - 11].min())
        out["making_higher_high_12bar"] = bool(cur_h > prev_h)
        out["making_lower_low_12bar"] = bool(cur_l < prev_l)
    else:
        out["making_higher_high_12bar"] = None
        out["making_lower_low_12bar"] = None

    # net displacement: close[i] - close[i-12]
    if last >= 12 and cur_close is not None:
        prev_close = _snap_at(closes_s, last - 12)
        out["net_displacement_12bar_pips"] = ((cur_close - prev_close) / ps) if prev_close is not None else None
    else:
        out["net_displacement_12bar_pips"] = None

    return out


# -------------------------
# Derived regime features
# -------------------------

# EMA stack state enum values — strings so the column is human-readable in EOD reviews.
EMA_STACK_COMPRESSED   = "COMPRESSED"
EMA_STACK_BULL_ALIGNED = "BULL_ALIGNED"
EMA_STACK_BEAR_ALIGNED = "BEAR_ALIGNED"
EMA_STACK_BULL_PARTIAL = "BULL_PARTIAL"
EMA_STACK_BEAR_PARTIAL = "BEAR_PARTIAL"
EMA_STACK_MIXED        = "MIXED"


def _ema_stack_state(
    emas_fast_to_slow: list[pd.Series],
    atr_series: pd.Series,
    k: float,
    warmup_bars: int = 0,
) -> pd.Series:
    """
    Classify 4-EMA alignment per bar.

    Inputs are the four EMA series in fast->slow order (e.g. EMA_8, EMA_13, EMA_21, EMA_50)
    and the ATR series used for the compression threshold.

    Priority (first match wins):
      COMPRESSED    : (max - min) of the 4 EMAs <= k * ATR
      BULL_ALIGNED  : e_fast > ... > e_slow
      BEAR_ALIGNED  : e_fast < ... < e_slow
      BULL_PARTIAL  : first 3 aligned bullish, slowest EMA breaks alignment
      BEAR_PARTIAL  : first 3 aligned bearish, slowest EMA breaks alignment
      MIXED         : default

    NaN output during warmup (any EMA or ATR NaN, or bar index < warmup_bars).

    Warmup:
    - The EMA primitive uses min_periods=1 (deliberate — see ema() docstring), which
      means EMA values exist from bar 0 but are meaningless (all equal to the first
      close) until the slowest span has processed enough bars. On a fresh DataFrame
      this would label bar 0 COMPRESSED (gap/ATR == 0) even though that's a warmup
      artefact, not a real squeeze. warmup_bars forces NaN for the first N bars so
      partial-window analysis (EOD reviews, replay scripts, debug slices) cannot be
      contaminated. Caller should set warmup_bars = max(ema_periods).
    """
    if len(emas_fast_to_slow) != 4:
        raise ValueError("EMA stack state expects exactly 4 EMA series, fast->slow")

    index = emas_fast_to_slow[0].index
    mat = np.column_stack([s.to_numpy(dtype=float) for s in emas_fast_to_slow])
    atr_arr = atr_series.to_numpy(dtype=float)

    # Per-row gap (max - min of the 4 EMAs) compared against k * ATR
    gap_max = np.nanmax(mat, axis=1) - np.nanmin(mat, axis=1)
    thresh = k * atr_arr

    # Diffs along axis=1: mat[:, i+1] - mat[:, i]. Negative diff => slower EMA smaller => bullish.
    diffs = np.diff(mat, axis=1)
    bull_all          = np.all(diffs < 0, axis=1)
    bear_all          = np.all(diffs > 0, axis=1)
    bull_partial_fast = np.all(diffs[:, :-1] < 0, axis=1)  # fast three aligned bullish
    bear_partial_fast = np.all(diffs[:, :-1] > 0, axis=1)

    nan_mask = np.isnan(mat).any(axis=1) | np.isnan(atr_arr)

    labels = np.empty(mat.shape[0], dtype=object)
    labels[:] = EMA_STACK_MIXED
    labels[bull_partial_fast & ~bull_all] = EMA_STACK_BULL_PARTIAL
    labels[bear_partial_fast & ~bear_all] = EMA_STACK_BEAR_PARTIAL
    labels[bull_all] = EMA_STACK_BULL_ALIGNED
    labels[bear_all] = EMA_STACK_BEAR_ALIGNED
    # COMPRESSED overrides alignment — a tight stack is the regime signal we care about.
    labels[(~nan_mask) & (gap_max <= thresh)] = EMA_STACK_COMPRESSED
    labels[nan_mask] = None
    # Warmup last: overrides any label (including COMPRESSED) for the initial window.
    if warmup_bars > 0:
        labels[:min(warmup_bars, len(labels))] = None

    return pd.Series(labels, index=index, name="EMA_STACK_STATE")


# -------------------------
# Convenience wrapper (pure)
# -------------------------

def add_indicators(
    df: pd.DataFrame,
    config: Optional[IndicatorsConfig] = None,
    *,
    pip_size: Optional[float] = None,
    caller: Optional[str] = None,
) -> pd.DataFrame:
    """
    Return a NEW DataFrame with indicator columns appended.
    Does not mutate the input df.

    Required base columns for full set: high, low, close.
    Minimal for EMA/BB/MACD/RSI: close.

    pip_size: price units per 1 pip for the symbol whose candles are in df.
      For IG spread-bet FX data (prices in points, 1 point = 1 pip), use
      pair_config.get_ppp(symbol) which returns 1.0 for all supported pairs.
      When provided, the column PRICE_VS_EMA50_PIPS = (close - EMA_50) / pip_size
      is emitted. When None, that column is skipped and a one-shot WARNING is
      logged per caller (so unplumbed sites surface in journalctl without spam).

    caller: optional string identifying the caller, used in the "skipped"
      warning message. If not provided, the caller is inferred from the stack.
    """
    cfg = config or IndicatorsConfig()

    if not isinstance(df, pd.DataFrame):
        raise TypeError("df must be a pandas.DataFrame")

    out = df.copy()

    if "close" in out.columns:
        close = _to_float_series(out["close"])

        # EMA (+ slope helper)
        ema_col = f"EMA_{cfg.ema_period}"
        out[ema_col] = ema(close, cfg.ema_period)
        out[f"{ema_col}_SLOPE"] = _to_float_series(out[ema_col]).diff()

        # EMA stack (fast->slow). Always emit these four columns regardless of cfg.ema_period
        # so EMA_STACK_STATE has a stable input set. Reuses any already-computed EMA column.
        for _p in cfg.ema_stack_periods:
            _col = f"EMA_{_p}"
            if _col not in out.columns:
                out[_col] = ema(close, _p)

        # PRICE_VS_EMA50_PIPS (regime-decision input for trend strength).
        # Signed pips from close to EMA_50. Requires pip_size from the caller because
        # the DataFrame alone doesn't know the symbol's scale.
        if "EMA_50" in out.columns:
            if pip_size is not None and float(pip_size) > 0:
                _ps = float(pip_size)
                out["PRICE_VS_EMA50_PIPS"] = (close - _to_float_series(out["EMA_50"])) / _ps
            else:
                _warn_price_vs_ema50_skipped(caller)

        # RSI (+ delta helper)
        rsi_col = f"RSI_{cfg.rsi_period}"
        out[rsi_col] = rsi(close, cfg.rsi_period)
        out[f"{rsi_col}_DELTA"] = _to_float_series(out[rsi_col]).diff()

        # Bollinger Bands (+ width/slope/curvature helpers)
        bb = bollinger_bands(close, cfg.bb_period, cfg.bb_std)
        for c in bb.columns:
            out[c] = bb[c]

        std_key = f"{cfg.bb_std:g}"
        bb_mid_col = f"BB_MID_{cfg.bb_period}"
        bb_upper_col = f"BB_UPPER_{cfg.bb_period}_{std_key}"
        bb_lower_col = f"BB_LOWER_{cfg.bb_period}_{std_key}"

        try:
            if bb_upper_col in out.columns and bb_lower_col in out.columns:
                upper = _to_float_series(out[bb_upper_col])
                lower = _to_float_series(out[bb_lower_col])
                mid = _to_float_series(out[bb_mid_col]) if bb_mid_col in out.columns else None

                width = upper - lower
                width_col = f"BB_WIDTH_{cfg.bb_period}_{std_key}"
                width_delta = width.diff()
                width_delta_col = f"BB_WIDTH_DELTA_{cfg.bb_period}_{std_key}"

                out[width_col] = width
                out[width_delta_col] = width_delta

                out[f"BB_WIDTH_EXPANDING_{cfg.bb_period}_{std_key}"] = (width_delta > EPS)
                out[f"BB_WIDTH_CONTRACTING_{cfg.bb_period}_{std_key}"] = (width_delta < -EPS)
                out[f"BB_WIDTH_FLAT_{cfg.bb_period}_{std_key}"] = (width_delta.abs() <= EPS)

                # Band "angle" (slope) helpers
                up_slope = upper.diff()
                lo_slope = lower.diff()
                up_slope_col = f"BB_UPPER_SLOPE_{cfg.bb_period}_{std_key}"
                lo_slope_col = f"BB_LOWER_SLOPE_{cfg.bb_period}_{std_key}"

                out[up_slope_col] = up_slope
                out[lo_slope_col] = lo_slope
                if mid is not None:
                    out[f"BB_MID_SLOPE_{cfg.bb_period}"] = mid.diff()
                    # N-bar mid slope (regime input: trend strength over ~25min).
                    # (mid[t] - mid[t-N]) / N, raw price units per bar. No pip
                    # normalisation here — consumer normalises if needed.
                    # No std_key in the column name: mid = SMA(close, period) is
                    # mathematically independent of std, so naming mirrors the
                    # existing 1-bar BB_MID_SLOPE_{period} sibling rather than
                    # the std-bearing BB_WIDTH_PCTL_{period}_{std} family.
                    # QUOTE-CONVENTION TRAP: magnitude scale depends on the
                    # input feed. On IG spread-bet points (pip_size=1.0 for all
                    # pairs), GBPUSD and USDJPY both produce ~0.45/bar median
                    # |slope|. On native-decimal feeds, GBPUSD sits ~0.0001/bar
                    # and USDJPY ~0.01/bar — a 10000× gap. Any threshold tuned
                    # on IG data will misclassify on decimal feeds and vice
                    # versa. Consumers that threshold this column MUST normalise
                    # via pair_config.get_ppp() (or equivalent) before comparing
                    # against fixed values or cross-pair. Do not assume either
                    # convention.
                    out[f"BB_MID_SLOPE_5_{cfg.bb_period}"] = mid.diff(5) / 5.0

                # Curvature proxy: slope change
                out[f"{up_slope_col}_DELTA"] = _to_float_series(out[up_slope_col]).diff()
                out[f"{lo_slope_col}_DELTA"] = _to_float_series(out[lo_slope_col]).diff()

                # BB width percentile (regime input: compression vs expansion).
                # Relative width = (upper - lower) / mid normalises across pairs;
                # raw `width` is scale-dependent (GBPUSD pips vs USDJPY pips are
                # different orders of magnitude) and not comparable cross-pair.
                # 120-bar strict warmup: percentile needs a full window to mean
                # anything — no expanding-window fallback.
                # mid==0 guard: unlikely on FX 5m bars, but division blows up if
                # it ever happens (precedent: 2026-04-19 NaN write incident).
                if mid is not None:
                    mid_safe = mid.replace(0.0, np.nan)
                    rel_width = (upper - lower) / mid_safe
                    pctl_col = f"BB_WIDTH_PCTL_{cfg.bb_period}_{std_key}"
                    out[pctl_col] = (
                        rel_width.rolling(window=120, min_periods=120).rank(pct=True)
                        * 100.0
                    )
        except Exception:
            pass

        # MACD (+ deltas + decel helpers)
        m = macd(close, cfg.macd_fast, cfg.macd_slow, cfg.macd_signal)
        for c in m.columns:
            out[c] = m[c]

        try:
            macd_line_col = f"MACD_{cfg.macd_fast}_{cfg.macd_slow}"
            hist_col = f"MACD_HIST_{cfg.macd_fast}_{cfg.macd_slow}_{cfg.macd_signal}"

            if macd_line_col in out.columns:
                macd_line = _to_float_series(out[macd_line_col])
                out[f"{macd_line_col}_DELTA"] = macd_line.diff()

            if hist_col in out.columns:
                hist = _to_float_series(out[hist_col])
                d = hist.diff()

                out[f"{hist_col}_DELTA"] = d
                # DELTA-based decel: histogram delta negative two bars in a row
                out[f"{hist_col}_DECEL2"] = (d < 0.0) & (d.shift(1) < 0.0)
                # VALUE-based decreasing: hist[-3] > hist[-2] > hist[-1]
                out[f"{hist_col}_DECREASING2"] = (hist < hist.shift(1)) & (hist.shift(1) < hist.shift(2))
        except Exception:
            pass

    if all(c in out.columns for c in ["high", "low", "close"]):
        out[f"ATR_{cfg.atr_period}"] = atr(out, cfg.atr_period)

        # ATR percentile (regime input: volatility compression vs expansion).
        # Trailing 576-bar (48h on 5m) percentile rank of ATR, 0-100.
        # 576 bars ~ 2 full trading days: captures at least one full
        # session-cycle so Asian/London/NY each appear in the window.
        # Strict 576-bar min_periods — same policy as BB_WIDTH_PCTL_20_2 at
        # line 509: partial-window percentile is not meaningful, and the
        # v1 regime classifier should see NaN during warmup rather than
        # noisy values that look authoritative.
        # KNOWN BIAS (v1, accepted): since the 576-bar window always spans
        # all three sessions, a given bar's percentile is effectively ranked
        # against a mixed-session distribution. Asian-session bars (naturally
        # lower ATR on non-JPY pairs) will cluster at the low end of the
        # percentile distribution; London/NY bars at the high end. Session-
        # aware percentile (e.g. rank Asian vs Asian only) is overkill for
        # v1 — the regime classifier will handle session context separately.
        try:
            atr_series = _to_float_series(out[f"ATR_{cfg.atr_period}"])
            out[f"ATR_PCTL_{cfg.atr_period}"] = (
                atr_series.rolling(window=576, min_periods=576).rank(pct=True)
                * 100.0
            )
        except Exception:
            pass

        a = aroon(out["high"], out["low"], cfg.aroon_period)
        for c in a.columns:
            out[c] = a[c]

        # ADX / +DI / -DI (regime input: trend strength + direction).
        # Wilder's method; gated on cfg.adx_period so it can be disabled by
        # setting the field falsy. try/except so a malformed window degrades
        # to "columns absent" rather than aborting the indicator pass.
        if cfg.adx_period:
            try:
                adx_df = adx(out, cfg.adx_period)
                for c in adx_df.columns:
                    out[c] = adx_df[c]
            except Exception:
                pass

        # SWING_STRUCTURE (regime input: HH+HL / LL+LH / overlapping chop).
        # Needs only H/L/C. try/except so a malformed window degrades to
        # "column absent" rather than aborting the indicator pass.
        try:
            out["SWING_STRUCTURE"] = swing_structure(
                out, cfg.swing_pivot_flank, cfg.swing_lookback
            )
        except Exception:
            pass

        # NET_DISP_{6,12,24} (regime input: net close-to-close displacement).
        # Needs close + pip_size; skip gracefully when pip_size unplumbed.
        if pip_size is not None and pip_size > 0:
            try:
                nd = net_displacement(out, pip_size)
                for c in nd.columns:
                    out[c] = nd[c]
            except Exception:
                pass

        # Candle displacement (regime input: body/ATR, close-location, wicks).
        # Needs OPEN + the ATR column; add_indicators does not guarantee
        # `open`, so guard it explicitly and skip gracefully if either input
        # is absent. Same degrade-to-absent try/except style as ADX.
        _atr_col_cd = f"ATR_{cfg.atr_period}"
        if "open" in out.columns and _atr_col_cd in out.columns:
            try:
                cd = candle_displacement(out, _atr_col_cd)
                for c in cd.columns:
                    out[c] = cd[c]
            except Exception:
                pass

        # EMA_STACK_STATE — needs both the 4 EMAs and ATR. Emit only when all inputs present.
        _stack_ema_cols = [f"EMA_{p}" for p in cfg.ema_stack_periods]
        _atr_col = f"ATR_{cfg.atr_period}"
        if len(cfg.ema_stack_periods) == 4 and all(c in out.columns for c in _stack_ema_cols) and _atr_col in out.columns:
            try:
                out["EMA_STACK_STATE"] = _ema_stack_state(
                    [_to_float_series(out[c]) for c in _stack_ema_cols],
                    _to_float_series(out[_atr_col]),
                    cfg.ema_stack_compression_k,
                    warmup_bars=max(cfg.ema_stack_periods),
                )
            except Exception:
                pass

    return out
