"""
Point-in-time H4 / H1 / M5 direction classifiers for GBP/USD.

Design principles:
  - Use ONLY completed candles. The "state at timestamp T" is defined by
    the last candle whose timestamp + period <= T.
  - Reproducible across the full 2024-2026 archive without any live-state
    dependency (unlike production `regime_engine.latest_result` which
    reads an in-memory registry — unsafe for historical replay).
  - Mirror production spirit:
      H4 direction  ← EMA20/EMA50 position + slope on H4 closes
      H1 direction  ← EMA20/EMA50 position + slope on H1 closes
                       (production uses `indicators.h1_ema_direction`)
      M5 momentum   ← MACD(12,26,9) histogram sign on M5 closes
                       (production uses MACD hist in multiple places)

  States: BULLISH, BEARISH, NEUTRAL
  Strength: separation between EMAs (pips) + slope magnitude for H1/H4;
            |hist| for M5.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def _ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False, min_periods=1).mean()


def _macd(closes: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    ema_f = _ema(closes, fast)
    ema_s = _ema(closes, slow)
    macd_line = ema_f - ema_s
    sig = _ema(macd_line, signal)
    hist = macd_line - sig
    return macd_line, sig, hist


def classify_ema_direction(bars_tf: pd.DataFrame,
                           ema_fast: int = 20, ema_slow: int = 50,
                           sep_threshold_pips: float = 0.0,
                           slope_bars: int = 3) -> pd.DataFrame:
    """Binary direction classifier.

    direction = BULLISH if ema_fast > ema_slow, else BEARISH.
    strength  = |ema_fast - ema_slow| in pip-scale units.

    (NEUTRAL is retained only when both EMAs are literally equal — effectively
    never. We also store `strong` = separation >= sep_threshold_pips so the
    downstream analysis can further filter if required.)
    """
    out = bars_tf.copy()
    out[f"ema{ema_fast}"] = _ema(out["close"], ema_fast)
    out[f"ema{ema_slow}"] = _ema(out["close"], ema_slow)
    sep = out[f"ema{ema_fast}"] - out[f"ema{ema_slow}"]
    out["ema_sep_pips"] = sep
    out["ema_fast_slope"] = out[f"ema{ema_fast}"].diff(slope_bars)
    direction = np.where(sep > 0, "BULLISH", np.where(sep < 0, "BEARISH", "NEUTRAL"))
    out["direction"] = direction
    out["strength"] = sep.abs()
    out["strong"] = sep.abs() >= sep_threshold_pips
    return out


def classify_macd_m5(m5: pd.DataFrame, hist_threshold: float = 0.0) -> pd.DataFrame:
    """Binary M5 short-term direction classification.

    direction = BULLISH if close > EMA20, else BEARISH.
    (The function name is retained for backwards compatibility; it no longer
    uses MACD. The EMA20 position is a cleaner point-in-time indicator of
    short-term direction and does not go NEUTRAL during low-volume hours.)
    """
    out = m5.copy()
    ema20 = _ema(out["close"], 20)
    out["m5_ema20"] = ema20
    diff = out["close"] - ema20
    direction = np.where(diff > hist_threshold, "BULLISH",
                 np.where(diff < -hist_threshold, "BEARISH", "NEUTRAL"))
    out["direction"] = direction
    out["strength"] = diff.abs()
    return out


def alignment_state(h4_dir: str, h1_dir: str, m5_dir: str) -> str:
    """One-letter composite alignment state.

    Convention (reads H4-H1-M5 directions L/U/N for bear/bull/neutral):
      ALL_BULL         UUU
      ALL_BEAR         LLL
      H4H1BULL_M5BEAR  UUL   (Example B — short bearish correction in bull mkt)
      H4H1BEAR_M5BULL  LLU   (Example D's inverse)
      H4BULL_H1M5BEAR  ULL   (Example C — deeper correction in bull mkt)
      H4BEAR_H1M5BULL  LUU   (Example D — rally in bear mkt)
      MIXED            anything with a NEUTRAL
      OTHER            anything else
    """
    s = (h4_dir, h1_dir, m5_dir)
    if "NEUTRAL" in s: return "MIXED"
    sym = tuple({"BULLISH":"U","BEARISH":"L","NEUTRAL":"N"}[d] for d in s)
    key = "".join(sym)
    return {
        "UUU": "ALL_BULL",
        "LLL": "ALL_BEAR",
        "UUL": "H4H1BULL_M5BEAR",
        "LLU": "H4H1BEAR_M5BULL",
        "ULL": "H4BULL_H1M5BEAR",
        "LUU": "H4BEAR_H1M5BULL",
        "ULU": "H4BULL_H1BEAR_M5BULL",
        "LUL": "H4BEAR_H1BULL_M5BEAR",
    }.get(key, "OTHER")
