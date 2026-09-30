#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
pattern_engine_router.py
---------------------------------------------------
Routes incoming data to the correct PatternEngine
profile based on:
    • current regime (5m detection)
    • future regime (forecast)
    • confidence (ATR velocity, trend acceleration)
"""

import json
import pandas as pd
from pathlib import Path

from pattern_engine import PatternEngine
from regime_detector import detect_regime
from regime_forecaster import forecast_regime


# -------------------------------------------------------------
# Genome profile directory
# -------------------------------------------------------------
REGIME_DIR = Path("/opt/tradingbot/optimizer/regimes")

GENOME_MAP = {
    "TREND":    REGIME_DIR / "trend_genome.json",
    "RANGE":    REGIME_DIR / "range_genome.json",
    "VOLATILE": REGIME_DIR / "vol_genome.json",
    "CALM":     REGIME_DIR / "calm_genome.json",
}


# -------------------------------------------------------------
# Load genome profile for selected regime
# -------------------------------------------------------------
def load_regime_profile(regime: str):
    path = GENOME_MAP.get(regime)
    if not path or not path.exists():
        return {}
    with path.open() as f:
        return json.load(f)


# -------------------------------------------------------------
# PatternEngine Router
# -------------------------------------------------------------
def evaluate_with_regime(df1, df5, df1h, mid):
    """
    Returns:
        (pattern_output, selected_regime)
    """

    # 1. Detect live regime from 5m chart
    current_regime = detect_regime(df5)

    # 2. Forecast future regime (5–15m ahead)
    future_regime = forecast_regime(df5, horizon=3)

    regime = current_regime

    # 3. If different → consider switching
    if current_regime != future_regime:
        regime = future_regime

    # ---------------------------------------------------------
    # 4. Compute regime-shift confidence
    # ---------------------------------------------------------
    try:
        highs = df5["high"].values
        lows = df5["low"].values
        closes = df5["close"].values

        # ATR14 Velocity
        hl_range = pd.Series(highs - lows)
        atr_series = hl_range.rolling(14).mean()
        atr_now = atr_series.iloc[-1]
        atr_prev = atr_series.iloc[-4]  # ~15 minutes earlier
        atr_velocity = (atr_now - atr_prev) / (atr_prev + 1e-9)

        # Trend Acceleration (MA20–MA50)
        ma20 = pd.Series(closes).rolling(20).mean()
        ma50 = pd.Series(closes).rolling(50).mean()
        trend_now = ma20.iloc[-1] - ma50.iloc[-1]
        trend_prev = ma20.iloc[-4] - ma50.iloc[-4]
        trend_acceleration = trend_now - trend_prev

    except Exception:
        atr_velocity = 0.0
        trend_acceleration = 0.0

    # Confidence score
    confidence = 0.0

    if future_regime == "VOLATILE":
        confidence += abs(atr_velocity)

    if future_regime == "TREND":
        confidence += abs(trend_acceleration)

    if future_regime == "CALM":
        confidence += abs(atr_velocity) * 0.2

    # 5. High confidence → override regime
    if confidence > 0.30:
        regime = future_regime

    # Final selected regime
    selected_regime = regime

    # ---------------------------------------------------------
    # 6. Load regime-specific genome
    # ---------------------------------------------------------
    profile = load_regime_profile(selected_regime)

    # ---------------------------------------------------------
    # 7. Run PatternEngine with selected genome
    # ---------------------------------------------------------
    result = PatternEngine.evaluate(
        df_m1=df1,
        df_m5=df5,
        df_h1=df1h,
        mid=mid,
        override_profile=profile,
    )

    return result, selected_regime