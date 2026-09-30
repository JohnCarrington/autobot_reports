#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
regime_detector.py — Detects real-time market regime.

Outputs one of:
    "TREND"
    "RANGE"
    "VOLATILE"
    "CALM"
"""

import pandas as pd


def detect_regime(df_5m: pd.DataFrame):
    """
    Detects current market regime using a combination of:
        • ATR ratio (volatility expansion/compression)
        • MA20–MA50 spread (trend strength)
        • Bollinger width (range vs trend breakout)
    
    df_5m must contain at least 60 candles.
    """

    if df_5m is None or len(df_5m) < 60:
        return "CALM"  # safest default

    closes = df_5m["close"].values
    highs = df_5m["high"].values
    lows = df_5m["low"].values

    # -----------------------------------------------------
    # 1. VOLATILITY CONDITIONS
    # -----------------------------------------------------
    hl_range = pd.Series(highs - lows)

    try:
        atr = hl_range.rolling(14).mean().iloc[-1]
        atr60 = hl_range.rolling(60).mean().iloc[-1]
    except Exception:
        return "CALM"

    vol_ratio = atr / (atr60 + 1e-9)  # expansion vs baseline

    # -----------------------------------------------------
    # 2. TREND CONDITIONS
    # -----------------------------------------------------
    ma20 = pd.Series(closes).rolling(20).mean().iloc[-1]
    ma50 = pd.Series(closes).rolling(50).mean().iloc[-1]
    trend_strength = abs(ma20 - ma50)

    # -----------------------------------------------------
    # 3. RANGE CONDITIONS — Bollinger Band Width
    # -----------------------------------------------------
    try:
        bb_high = pd.Series(highs).rolling(20).max().iloc[-1]
        bb_low = pd.Series(lows).rolling(20).min().iloc[-1]
    except Exception:
        return "RANGE"

    bb_width = bb_high - bb_low

    # -----------------------------------------------------
    # 4. Classification Logic
    # -----------------------------------------------------

    # High volatility expansion → volatile
    if vol_ratio > 1.8:
        return "VOLATILE"

    # Strong trend vs range width → trending
    if trend_strength > (bb_width * 0.5):
        return "TREND"

    # Low volatility + weak trend → calm
    if vol_ratio < 0.8 and trend_strength < (bb_width * 0.25):
        return "CALM"

    # Default fallback
    return "RANGE"