#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
regime_forecaster.py — Predicts future market regime (5–30 minutes ahead)

Uses:
    • ATR velocity
    • Volatility compression/expansion
    • MA slope > MA slope lag
    • Momentum acceleration
    • Bollinger Band squeeze
    • Candle body-size ratio
"""

import numpy as np
import pandas as pd
from regime_detector import detect_regime


# -----------------------------------------------------------
# Helper: linear slope of a recent series segment
# -----------------------------------------------------------
def slope(series):
    series = np.asarray(series[-20:], dtype=float)
    if len(series) < 5:
        return 0.0

    x = np.arange(len(series))
    m = np.polyfit(x, series, 1)[0]
    return float(m)


# -----------------------------------------------------------
# Main Forecaster
# -----------------------------------------------------------
def forecast_regime(df_5m: pd.DataFrame, horizon=3):
    """
    Forecast regime horizon steps ahead.
    horizon=3 (default) = approx 15 minutes.

    df_5m: expects columns ['high','low','close']
    """

    # Safety: need minimum data length
    if len(df_5m) < max(60, horizon + 20):
        return detect_regime(df_5m)

    closes = df_5m["close"].values
    highs  = df_5m["high"].values
    lows   = df_5m["low"].values

    # -------------------------------------------------------
    # 1. Volatility Spike Prediction (ATR velocity)
    # -------------------------------------------------------
    hl_range = pd.Series(highs - lows)

    atr_series = hl_range.rolling(14).mean()
    atr14 = atr_series.iloc[-1]

    # Safe index for "horizon steps ago"
    idx = -(1 + horizon)
    if abs(idx) >= len(atr_series):
        return detect_regime(df_5m)

    atr14_prev = atr_series.iloc[idx]

    atr_velocity = (atr14 - atr14_prev) / (atr14_prev + 1e-9)

    # -------------------------------------------------------
    # 2. Bollinger Band Squeeze Prediction
    # -------------------------------------------------------
    roll_high = pd.Series(highs).rolling(20).max()
    roll_low  = pd.Series(lows).rolling(20).min()

    bb_width_now = (roll_high - roll_low).iloc[-1]
    bb_width_past = (roll_high - roll_low).iloc[idx]

    squeeze_pressure = bb_width_past - bb_width_now  # +ve = compression building

    # -------------------------------------------------------
    # 3. Trend Acceleration Prediction (MA20–MA50 cross)
    # -------------------------------------------------------
    ma20 = pd.Series(closes).rolling(20).mean()
    ma50 = pd.Series(closes).rolling(50).mean()

    trend_now  = ma20.iloc[-1]          - ma50.iloc[-1]
    trend_past = ma20.iloc[idx]         - ma50.iloc[idx]

    trend_acceleration = trend_now - trend_past

    # -------------------------------------------------------
    # 4. Decision Logic
    # -------------------------------------------------------

    # Incoming volatility spike
    if atr_velocity > 0.35 or squeeze_pressure > 0.25:
        return "VOLATILE"

    # Trend expansion forecast
    if trend_acceleration > abs(bb_width_now) * 0.25:
        return "TREND"

    # Volatility collapse → likely range or calm
    if atr_velocity < -0.25 and abs(trend_now) < abs(bb_width_now) * 0.15:
        return "CALM"

    # Final fallback (consistent behaviour)
    return detect_regime(df_5m)

