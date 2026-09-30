#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
neural_meta_controller.py
-------------------------

Neural Meta-Controller (NMC)

Inputs:
    feature_sequence (np.ndarray): shape (T, FEATURE_DIM)

Outputs:
    {
        "signal": "BUY" | "SELL" | "NONE",
        "confidence": float 0–1,
        "size_mult": float,
        "weights": dict,
        "regime_now": str,
        "regime_future": str,
        "debug": dict
    }

The NMC does NOT place trades. It only produces structured
intelligence for AutoBot to act upon.
"""

import numpy as np
from causal_transformer import predict, softmax, SEQ_LEN, FEATURE_DIM


REGIMES = ["CALM", "RANGE", "TREND", "VOLATILE"]


# -----------------------------------------------------------
# 1. Safety helpers
# -----------------------------------------------------------
def _safe(x):
    return float(np.clip(x, -9999, 9999))


def _safe_conf(x):
    return float(np.clip(x, 0.0, 1.0))


def _safe_size(x):
    # size multiplier: 0.25 → 2.0
    return float(np.clip(x, 0.25, 2.0))


def _weights_dict(raw):
    """
    Convert 8 logits → dict of interpretable weights.
    """
    raw = np.array(raw, dtype=float)
    w = softmax(raw)

    return {
        "micro":  float(w[0]),
        "wick":   float(w[1]),
        "moment": float(w[2]),
    #   reserve future expansion
        "struct": float(w[3]),
        "htf":    float(w[4]),
        "meta1":  float(w[5]),
        "meta2":  float(w[6]),
        "meta3":  float(w[7]),
    }


# -----------------------------------------------------------
# 2. Main entry point
# -----------------------------------------------------------
def run_nmc(feature_sequence: np.ndarray):
    """
    Runs the Neural Meta-Controller on the last T steps of features.
    """
    try:
        seq = np.array(feature_sequence, dtype=float)
        if seq.ndim != 2:
            raise ValueError("feature_sequence must be 2D")

        # trim/pad to SEQ_LEN
        if len(seq) > SEQ_LEN:
            seq = seq[-SEQ_LEN:]
        elif len(seq) < SEQ_LEN:
            pad = np.zeros((SEQ_LEN - len(seq), FEATURE_DIM))
            seq = np.vstack([pad, seq])

    except Exception:
        return {
            "signal": "NONE",
            "confidence": 0.0,
            "size_mult": 1.0,
            "weights": {},
            "regime_now": "UNKNOWN",
            "regime_future": "UNKNOWN",
            "debug": {"error": "invalid feature sequence"}
        }

    # -------------------------------------------------------
    # Neural inference
    # -------------------------------------------------------
    out = predict(seq)

    # classification heads
    action_logits  = out["action_logits"]
    regime_logits  = out["regime_logits"]
    weight_logits  = out["weight_logits"]
    feature_future = out["features"]

    # -------------------------------------------------------
    # decode action
    # -------------------------------------------------------
    action_probs = softmax(action_logits)
    a_buy, a_sell, a_hold = action_probs

    if max(a_buy, a_sell) < 0.40:   # safety threshold
        signal = "NONE"
    else:
        signal = "BUY" if a_buy > a_sell else "SELL"

    confidence = _safe_conf(max(a_buy, a_sell))

    # size scaling from action confidence
    size_mult = _safe_size(0.25 + confidence * 1.75)

    # -------------------------------------------------------
    # decode regimes
    # -------------------------------------------------------
    regime_probs = softmax(regime_logits)
    regime_now = REGIMES[int(np.argmax(regime_probs))]
    regime_future = REGIMES[int(np.argmax(feature_future[:4]))] \
        if len(feature_future) >= 4 else regime_now

    # -------------------------------------------------------
    # weight head → PatternEngine weight override
    # -------------------------------------------------------
    weights = _weights_dict(weight_logits)

    # -------------------------------------------------------
    # Final structured output
    # -------------------------------------------------------
    return {
        "signal": signal,
        "confidence": confidence,
        "size_mult": size_mult,
        "weights": weights,
        "regime_now": regime_now,
        "regime_future": regime_future,
        "debug": {
            "action_logits": action_logits.tolist(),
            "action_probs": action_probs.tolist(),
            "regime_logits": regime_logits.tolist(),
            "regime_probs": regime_probs.tolist(),
            "weights_raw": weight_logits.tolist(),
        }
    }
