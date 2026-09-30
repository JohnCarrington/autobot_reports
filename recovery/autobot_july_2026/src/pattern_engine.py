#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
pattern_engine.py — AI-driven Multi-Timeframe Pattern Engine
------------------------------------------------------------

This engine replaces static BB/EMA logic with a fully parametric
micro-structure, structural compression/expansion, and HTF slope model.

It loads optimised parameters from:
    /opt/tradingbot/optimizer/pattern_engine_profile.json
If the file does not exist, defaults are used.

Output:
    (signal, confidence, reason, debug)

Where:
    signal ∈ { "BUY", "SELL", "NONE" }
"""

import json
import numpy as np
from pathlib import Path


# ============================================================
# PARAMETER PROFILE LOADING
# ============================================================

PROFILE_PATH = Path("/opt/tradingbot/optimizer/pattern_engine_profile.json")

DEFAULT_PARAMS = {
    # Microstructure
    "M1_BODY_WEIGHT": 800,
    "M1_WICK_WEIGHT": 600,
    "M1_MOMENTUM_WEIGHT": 200,

    # Structure
    "M5_COMPRESSION_FACTOR": 0.5,
    "M5_EXPANSION_FACTOR": 2.0,

    # HTF
    "H1_SLOPE_THRESHOLD": 0.0010,

    # Confidence
    "CONF_MICRO": 1.0,
    "CONF_STRUCT": 1.0,
    "CONF_HTF": 1.0,

    # SL/TP
    "SL_PIPS": 30,
    "TP_PIPS": 50,
}

# Try loading optimiser-generated profile
def load_profile():
    try:
        with PROFILE_PATH.open() as f:
            return json.load(f)
    except:
        return {}

PROFILE = load_profile()

# ============================================================
# UTILITY FUNCTIONS
# ============================================================

def _slope(series):
    """Linear slope of a series (simple regression)."""
    if len(series) < 3:
        return 0
    y = np.array(series)
    x = np.arange(len(series))
    try:
        m = np.polyfit(x, y, 1)[0]
        return float(m)
    except Exception:
        return 0.0


def _candle_features(row):
    """Extract basic candle microstructure properties."""
    body = abs(row["close"] - row["open"])
    upper_wick = max(0, row["high"] - max(row["close"], row["open"]))
    lower_wick = max(0, min(row["close"], row["open"]) - row["low"])
    return body, upper_wick, lower_wick


# ============================================================
# PATTERNENGINE CLASS
# ============================================================

class PatternEngine:

    # ------------------------------------------------------------------
    # MAIN EVALUATION ENTRY POINT
    # ------------------------------------------------------------------

    @staticmethod
    def evaluate(df_m1, df_m5, df_h1, mid, override_profile=None):
        """
        df_m1 — last 5 or so 1m candles
        df_m5 — historical 5m candles up to now
        df_h1 — historical 1h candles up to now
        mid   — current mid price
        override_profile — optional dict to override DEFAULT_PARAMS
                           (used by regime router and meta-genome controller)

        Returns: (signal, confidence, reason, debug)
        """
        # Merge defaults with live profile, then apply any override
        live = load_profile()
        params = {**DEFAULT_PARAMS, **live}
        if override_profile:
            params.update(override_profile)

        # ---------------------------------------------------------------
        # 1) MICROSTRUCTURE (M1)
        # ---------------------------------------------------------------
        micro_score, micro_reason, micro_debug = PatternEngine._microstructure(df_m1, params)

        # ---------------------------------------------------------------
        # 2) STRUCTURAL (M5 compression/expansion)
        # ---------------------------------------------------------------
        struct_score, struct_reason, struct_debug = PatternEngine._structure(df_m5, params)

        # ---------------------------------------------------------------
        # 3) HTF REGIME (H1 slope)
        # ---------------------------------------------------------------
        htf_score, htf_reason, htf_debug = PatternEngine._htf(df_h1, params)

        # ---------------------------------------------------------------
        # 4) Combine scores into confidence
        # ---------------------------------------------------------------
        conf_buy = (
            micro_score.get("BUY", 0) * params["CONF_MICRO"]
            + struct_score.get("BUY", 0) * params["CONF_STRUCT"]
            + htf_score.get("BUY", 0) * params["CONF_HTF"]
        )

        conf_sell = (
            micro_score.get("SELL", 0) * params["CONF_MICRO"]
            + struct_score.get("SELL", 0) * params["CONF_STRUCT"]
            + htf_score.get("SELL", 0) * params["CONF_HTF"]
        )

        # Final confidence
        final_conf = conf_buy - conf_sell

        if abs(final_conf) < 0.001:
            return "NONE", 0, "low confidence", {
                "micro": micro_debug,
                "struct": struct_debug,
                "htf": htf_debug,
                "final_conf": final_conf,
            }

        # BUY
        if final_conf > 0:
            return "BUY", final_conf, f"{micro_reason} | {struct_reason} | {htf_reason}", {
                "micro": micro_debug,
                "struct": struct_debug,
                "htf": htf_debug,
                "final_conf": final_conf,
            }

        # SELL
        return "SELL", abs(final_conf), f"{micro_reason} | {struct_reason} | {htf_reason}", {
            "micro": micro_debug,
            "struct": struct_debug,
            "htf": htf_debug,
            "final_conf": final_conf,
        }

    # ================================================================
    # MICROSTRUCTURE ENGINE (M1)
    # ================================================================

    @staticmethod
    def _microstructure(df, p):
        """
        Measures microstructure strength of M1 candles.
        Weighted combination of body size, wicks, and momentum.
        """

        if len(df) < 2:
            return {"BUY": 0, "SELL": 0}, "m1 insufficient", {}

        last = df.iloc[-1]
        prev = df.iloc[-2]

        # Candle features
        body, up_wick, low_wick = _candle_features(last)

        body_score = body * p["M1_BODY_WEIGHT"]
        wick_score_up = up_wick * p["M1_WICK_WEIGHT"]
        wick_score_low = low_wick * p["M1_WICK_WEIGHT"]

        # Momentum
        momentum = (last["close"] - prev["close"]) * p["M1_MOMENTUM_WEIGHT"]

        buy_score = 0
        sell_score = 0
        reason = []

        # Bullish microstructure
        if last["close"] > last["open"]:
            buy_score += body_score + momentum + wick_score_low
            reason.append("m1 bullish micro")

        # Bearish microstructure
        if last["close"] < last["open"]:
            sell_score += body_score + (-momentum) + wick_score_up
            reason.append("m1 bearish micro")

        return (
            {"BUY": buy_score, "SELL": sell_score},
            " / ".join(reason),
            {
                "body": body,
                "up_wick": up_wick,
                "low_wick": low_wick,
                "momentum": momentum,
                "buy_score": buy_score,
                "sell_score": sell_score,
            }
        )

    # ================================================================
    # STRUCTURE ENGINE (M5)
    # ================================================================

    @staticmethod
    def _structure(df, p):
        if len(df) < 20:
            return {"BUY": 0, "SELL": 0}, "m5 insufficient", {}

        last20 = df.tail(20)
        rang = last20["high"].max() - last20["low"].min()

        # Compression = low range
        compression = rang * p["M5_COMPRESSION_FACTOR"]

        # Expansion = breakout energy
        expansion = rang * p["M5_EXPANSION_FACTOR"]

        last = df.iloc[-1]
        close = last["close"]

        # Detect breakout direction
        buy_score = 0
        sell_score = 0
        reason = []

        if close > last20["high"].max() - compression:
            buy_score += expansion
            reason.append("m5 upper expansion")

        if close < last20["low"].min() + compression:
            sell_score += expansion
            reason.append("m5 lower expansion")

        return (
            {"BUY": buy_score, "SELL": sell_score},
            " / ".join(reason),
            {
                "range": rang,
                "compression": compression,
                "expansion": expansion,
                "buy_score": buy_score,
                "sell_score": sell_score,
            }
        )

    # ================================================================
    # HTF ENGINE (H1)
    # ================================================================

    @staticmethod
    def _htf(df, p):
        if len(df) < 10:
            return {"BUY": 0, "SELL": 0}, "h1 insufficient", {}

        slope = _slope(df["close"].tail(20))

        buy_score = 0
        sell_score = 0
        reason = []

        if slope > p["H1_SLOPE_THRESHOLD"]:
            buy_score += slope * 10000
            reason.append("h1 bullish")

        elif slope < -p["H1_SLOPE_THRESHOLD"]:
            sell_score += (-slope) * 10000
            reason.append("h1 bearish")

        return (
            {"BUY": buy_score, "SELL": sell_score},
            " / ".join(reason),
            {"slope": slope, "buy_score": buy_score, "sell_score": sell_score}
        )