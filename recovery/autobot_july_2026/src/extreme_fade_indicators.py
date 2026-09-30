"""extreme_fade_indicators — RSI and MACD primitives shared by
rsi_extreme_fade.py and macd_extreme_fade.py.

These implementations are byte-equivalent to the ones used during the
full-search discovery pass at scripts/analysis/full_search/features.py.
Any divergence between production and search invalidates the EV estimates,
so this module is the single source of truth for both code paths.

EMA smoothing convention (used by both RSI Wilder and MACD line):
  pd.Series.ewm(span=N, adjust=False, min_periods=N).mean()           # MACD EMAs
  pd.Series.ewm(alpha=1.0/N, adjust=False, min_periods=N).mean()      # RSI Wilder

Price series: per-field-mid 5m close (the 'close' column from prod 5m bars,
matching the harness's per-field-mid construction).
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def rsi(close: pd.Series, n: int = 14) -> pd.Series:
    """Wilder's RSI on EWM smoothing — identical to
    scripts/analysis/full_search/features.py:rsi.

    Returns NaN for the first (n) bars (warm-up).
    """
    diff = close.diff()
    up = diff.clip(lower=0.0)
    dn = (-diff).clip(lower=0.0)
    avg_up = up.ewm(alpha=1.0 / n, adjust=False, min_periods=n).mean()
    avg_dn = dn.ewm(alpha=1.0 / n, adjust=False, min_periods=n).mean()
    rs = avg_up / avg_dn.replace(0.0, np.nan)
    return 100.0 - 100.0 / (1.0 + rs)


def macd_line(close: pd.Series, fast: int = 12, slow: int = 26) -> pd.Series:
    """MACD line = EMA(close, fast) - EMA(close, slow). Identical to
    the (line, signal, hist) tuple's first element from
    scripts/analysis/full_search/features.py:macd, with default fast=12, slow=26.

    Returns NaN until both EMAs are warm (first `slow` bars).
    """
    ef = close.ewm(span=fast, adjust=False, min_periods=fast).mean()
    es = close.ewm(span=slow, adjust=False, min_periods=slow).mean()
    return ef - es


# Optional helpers — exported for diagnostic / forensic use only. The
# production strategies do not consult signal/histogram for fire decisions
# (the search-time rule was on the LINE, not signal/histogram).
def macd_full(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    line = macd_line(close, fast, slow)
    sig = line.ewm(span=signal, adjust=False, min_periods=signal).mean()
    return line, sig, line - sig
