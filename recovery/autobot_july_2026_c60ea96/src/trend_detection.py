"""
trend_detection.py — H1 clean-trend detection, shared across strategies.

A single trend signal serves two purposes:

  - Entry trigger for gbpusd_trend_continuation: fires WITH the trend on
    pullback + rejection (introduced 2026-04-28).
  - Suppression filter for mean-reversion strategies (BB_REVERSAL,
    GBPUSD_BB_REV_L): when a clean H1 trend is in play, a counter-trend
    pierce on the OPPOSITE side is suppressed (introduced 2026-04-28).

The same five gates determine "clean trend":
    1. last close on the trend side of EMA50
    2. EMA21 on the trend side of EMA50
    3. MACD line on the trend side of signal
    4. MACD histogram sign matches trend
    5. >= min_directional of last 10 H1 closes directional vs the close
       5 bars prior

Returns "UP", "DOWN", or "NONE". Asymmetric usage by callers:
    - trend_continuation: fires LONG only on UP, SHORT only on DOWN.
    - mean-reversion: suppresses LONG only on DOWN, SHORT only on UP.

Indicator parameters: MACD(12, 26, 9) and EMA(21) / EMA(50) — chosen
for H1-timeframe responsiveness rather than the bot's 5m MACD(35,45,30).
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger("trend_detection")

# Gate thresholds. Defaults match the v1 trend-continuation values.
DEFAULT_TREND_LOOKBACK   = 10
DEFAULT_TREND_OFFSET     = 5
DEFAULT_MIN_DIRECTIONAL  = 8

# H1 MACD — standard 12/26/9.
DEFAULT_MACD_FAST   = 12
DEFAULT_MACD_SLOW   = 26
DEFAULT_MACD_SIGNAL = 9

# Minimum H1 history for EMA50 + MACD to be meaningful.
MIN_H1_BARS = DEFAULT_MACD_SLOW + DEFAULT_MACD_SIGNAL + 5  # 40


def _ema(values: Sequence[float], period: int) -> List[float]:
    """Exponential moving average. Returns list aligned with input."""
    if not values:
        return []
    if period <= 1:
        return list(values)
    k = 2.0 / (period + 1.0)
    out: List[float] = []
    seed = sum(values[:period]) / period if len(values) >= period else values[0]
    for i, v in enumerate(values):
        if i == 0:
            out.append(seed)
        else:
            out.append(out[-1] + k * (v - out[-1]))
    return out


def _macd(closes: Sequence[float],
          fast: int = DEFAULT_MACD_FAST,
          slow: int = DEFAULT_MACD_SLOW,
          signal: int = DEFAULT_MACD_SIGNAL,
          ) -> Tuple[List[float], List[float], List[float]]:
    """Standard MACD. Returns (macd_line, signal_line, histogram)."""
    if len(closes) < slow + signal:
        return [], [], []
    ema_fast = _ema(closes, fast)
    ema_slow = _ema(closes, slow)
    macd_line = [f - s for f, s in zip(ema_fast, ema_slow)]
    signal_line = _ema(macd_line, signal)
    hist = [m - s for m, s in zip(macd_line, signal_line)]
    return macd_line, signal_line, hist


def _h1_directional_close_count(closes: Sequence[float],
                                 lookback: int = DEFAULT_TREND_LOOKBACK,
                                 offset: int = DEFAULT_TREND_OFFSET,
                                 ) -> Tuple[int, int]:
    """Of the last `lookback` H1 closes, count how many are higher / lower
    than the close `offset` bars prior. Returns (higher_count, lower_count).
    Returns (0, 0) if insufficient data."""
    needed = lookback + offset
    if len(closes) < needed:
        return 0, 0
    sample = list(closes[-needed:])
    higher = 0
    lower = 0
    for i in range(offset, needed):
        if sample[i] > sample[i - offset]:
            higher += 1
        elif sample[i] < sample[i - offset]:
            lower += 1
    return higher, lower


def is_clean_trend(symbol: str,
                   h1_candles: Optional[List[Dict[str, Any]]],
                   min_directional: int = DEFAULT_MIN_DIRECTIONAL,
                   fast_context: bool = False,
                   ) -> Tuple[str, Dict[str, Any]]:
    """Return ("UP" | "DOWN" | "NONE", details_dict).

    UP requires all five gates aligned bullish:
        last_close > ema50,
        ema21 > ema50            (default; "Version A — strict EMA stack")
          OR  last_close > ema21 (when fast_context=True; "Version C"),
        macd_line > macd_signal, macd_hist > 0,
        higher_close_count >= min_directional (default 8/10).
    DOWN mirrors. Otherwise NONE with `reasons` describing which gates
    failed in each direction.

    `fast_context`: when True, replaces the EMA21-vs-EMA50 stack gate
    with a price-vs-EMA21 gate. The slow EMA21/EMA50 cross lags trend
    starts by ~3 H1 bars in measurement; the price-vs-EMA21 gate flips
    earlier without firing in chop. Default False — backward-compatible
    for every existing caller; only gbpusd_trend currently passes True
    (gated by env GBPUSD_TREND_FAST_CONTEXT_ENABLED).

    Always returns a details dict (even on NONE) so callers can log the
    indicator values that drove the decision.

    `symbol` is currently informational — included so future per-pair
    overrides can land without changing the call signature.
    """
    base_details: Dict[str, Any] = {"symbol": symbol}

    if not h1_candles:
        base_details["reasons"] = ["no_h1_candles"]
        return "NONE", base_details
    if len(h1_candles) < MIN_H1_BARS:
        base_details["reasons"] = [
            f"insufficient_h1_history ({len(h1_candles)} < {MIN_H1_BARS})"
        ]
        return "NONE", base_details

    closes: List[float] = []
    for c in h1_candles:
        try:
            closes.append(float(c["close"]))
        except (KeyError, TypeError, ValueError):
            base_details["reasons"] = ["malformed_candle"]
            return "NONE", base_details

    if len(closes) < MIN_H1_BARS:
        base_details["reasons"] = [
            f"insufficient_h1_history ({len(closes)} < {MIN_H1_BARS})"
        ]
        return "NONE", base_details

    ema21 = _ema(closes, 21)
    ema50 = _ema(closes, 50)
    macd_line, signal_line, hist = _macd(closes)
    if not macd_line or not signal_line or not hist:
        base_details["reasons"] = ["macd_unavailable"]
        return "NONE", base_details

    last_close  = closes[-1]
    last_e21    = ema21[-1]
    last_e50    = ema50[-1]
    last_macd   = macd_line[-1]
    last_signal = signal_line[-1]
    last_hist   = hist[-1]
    higher, lower = _h1_directional_close_count(closes)

    details: Dict[str, Any] = {
        "symbol": symbol,
        "current_price":      last_close,
        "ema21":              last_e21,
        "ema50":              last_e50,
        "macd_line":          last_macd,
        "macd_signal":        last_signal,
        "macd_hist":          last_hist,
        "directional_higher": higher,
        "directional_lower":  lower,
        "lookback":           DEFAULT_TREND_LOOKBACK,
        "min_directional":    min_directional,
    }

    details["fast_context"] = bool(fast_context)

    up_failures: List[str] = []
    if not (last_close > last_e50):
        up_failures.append(f"price<=ema50 ({last_close:.2f}<={last_e50:.2f})")
    if fast_context:
        # Version C: price above the faster EMA21 (does not require slow stack cross).
        if not (last_close > last_e21):
            up_failures.append(f"price<=ema21 ({last_close:.2f}<={last_e21:.2f})")
    else:
        # Version A (default): full ema21>ema50 stack.
        if not (last_e21 > last_e50):
            up_failures.append(f"ema21<=ema50 ({last_e21:.2f}<={last_e50:.2f})")
    if not (last_macd > last_signal):
        up_failures.append("macd_line<=signal")
    if not (last_hist > 0):
        up_failures.append(f"macd_hist<=0 ({last_hist:.4f})")
    if not (higher >= min_directional):
        up_failures.append(f"higher_closes={higher}<{min_directional}")

    down_failures: List[str] = []
    if not (last_close < last_e50):
        down_failures.append(f"price>=ema50 ({last_close:.2f}>={last_e50:.2f})")
    if fast_context:
        if not (last_close < last_e21):
            down_failures.append(f"price>=ema21 ({last_close:.2f}>={last_e21:.2f})")
    else:
        if not (last_e21 < last_e50):
            down_failures.append(f"ema21>=ema50 ({last_e21:.2f}>={last_e50:.2f})")
    if not (last_macd < last_signal):
        down_failures.append("macd_line>=signal")
    if not (last_hist < 0):
        down_failures.append(f"macd_hist>=0 ({last_hist:.4f})")
    if not (lower >= min_directional):
        down_failures.append(f"lower_closes={lower}<{min_directional}")

    if not up_failures and down_failures:
        details["directional_count"] = higher
        return "UP", details
    if not down_failures and up_failures:
        details["directional_count"] = lower
        return "DOWN", details

    # Both sides have failures — no clean trend.
    details["reasons"] = {
        "up_failures":   up_failures,
        "down_failures": down_failures,
    }
    return "NONE", details


def h1_macd_agreement(symbol: str) -> Optional[str]:
    """Light H1 MACD(12,26,9) line-vs-signal check, extracted from
    is_clean_trend's gate 3 so a trend-following caller can use a single
    indicator agreement without the full 5-condition clean-trend chain.

    Returns:
        "BULLISH"  — H1 macd_line > signal_line on the latest H1 close
        "BEARISH"  — H1 macd_line < signal_line
        "NEUTRAL"  — exactly equal (rare; tied)
        None       — cache absent / insufficient data / parse failure

    Uses the same MACD(12,26,9) parameters and the same _macd helper that
    is_clean_trend uses, so behaviour stays consistent with the streak
    counter still maintained by gbpusd_trend._update_h1_streak.
    """
    candles = load_h1_candles_from_cache(symbol)
    if not candles or len(candles) < MIN_H1_BARS:
        return None
    closes: List[float] = []
    for c in candles:
        try:
            closes.append(float(c["close"]))
        except (KeyError, TypeError, ValueError):
            return None
    macd_line, signal_line, _ = _macd(closes)
    if not macd_line or not signal_line:
        return None
    m, s = macd_line[-1], signal_line[-1]
    if m > s:
        return "BULLISH"
    if m < s:
        return "BEARISH"
    return "NEUTRAL"


def load_h1_candles_from_cache(symbol: str) -> Optional[List[Dict[str, Any]]]:
    """Convenience wrapper. Loads the H1 candle list for `symbol` from
    htf_cache. Returns None on failure or if cache absent. Callers are
    free to skip this and pass candles directly to is_clean_trend().
    """
    try:
        from htf_cache import load_cached_candles
        cached = load_cached_candles(str(symbol).upper(), "H1") or {}
        candles = cached.get("candles")
        if isinstance(candles, list) and candles:
            return candles
        return None
    except Exception as exc:
        logger.warning("[trend_detection] H1 cache load failed for %s: %s",
                       symbol, exc)
        return None
