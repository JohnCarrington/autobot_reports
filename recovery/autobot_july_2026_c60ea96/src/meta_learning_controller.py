#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
meta_learning_controller.py — Reinforcement Meta-Learner (Upgraded)
-------------------------------------------------------------------

This controller learns:
    • Q-values per regime (TREND, RANGE, VOLATILE, CALM)
    • Regime weights via softmax(Q * confidence)
    • Bayesian confidence adjustment
    • Temporal-difference update with λ-decay
    • Anti-overfitting safety clamping
    • Multi-horizon scoring

Inputs:
    perf_score   = short-term performance estimate (AI Brain)
    regime_used  = regime chosen by controller
    reward       = realised reward (+profit or -loss)

Outputs persisted to:
    /opt/tradingbot/optimizer/meta_learning_state.json
"""

import json
import os
from pathlib import Path
from math import exp
import logging

logger = logging.getLogger("AutoBot")

ML_STATE = Path("/opt/tradingbot/optimizer/meta_learning_state.json")

REGIMES = ["TREND", "RANGE", "VOLATILE", "CALM"]

# ---------------------------------------------------------
# Hyperparameters (Final Tuned)
# ---------------------------------------------------------
ALPHA = 0.10        # learning rate
GAMMA = 0.85        # discount factor
LAMBDA = 0.70       # TD(λ) trace decay
BETA = 0.20         # Bayesian confidence smoothing
DECAY = 0.995       # weight stabilisation
CONF_DECAY_ON_LOSS = 0.92

MIN_CONF = 0.05
MAX_CONF = 3.0

MAX_Q = 5.0
MIN_Q = -5.0


# ---------------------------------------------------------
# Load / Save State
# ---------------------------------------------------------

def _fresh_state():
    return {
        "Q": {r: 0.0 for r in REGIMES},
        "W": {r: 1.0 / len(REGIMES) for r in REGIMES},
        "C": {r: 1.0 for r in REGIMES},
        "eligibility": {r: 0.0 for r in REGIMES},
        "history": []
    }


def load_state():
    if ML_STATE.exists():
        try:
            with ML_STATE.open() as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning(
                f"[meta_learning] State file corrupt or unreadable ({exc}) — "
                f"discarding and starting fresh. Bad file: {ML_STATE}"
            )
            # Rename the corrupt file so it can be inspected later
            try:
                corrupt_path = ML_STATE.with_suffix(".json.corrupt")
                ML_STATE.rename(corrupt_path)
                logger.warning(f"[meta_learning] Corrupt state saved to {corrupt_path}")
            except Exception:
                pass
    return _fresh_state()


def save_state(s):
    tmp = ML_STATE.with_suffix(".json.tmp")
    try:
        with tmp.open("w") as f:
            json.dump(s, f, indent=4)
        os.replace(tmp, ML_STATE)
    except Exception as exc:
        logger.warning(f"[meta_learning] Failed to save state: {exc}")
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass


# ---------------------------------------------------------
# Softmax Helper
# ---------------------------------------------------------

def _softmax(d):
    xs = list(d.values())
    m = max(xs)
    ex = [exp(x - m) for x in xs]
    Z = sum(ex)
    return {k: ex[i] / Z for i, k in enumerate(d.keys())}


# ---------------------------------------------------------
# Update Routine (Main RL Logic)
# ---------------------------------------------------------

def update_meta_learning(perf_score, regime_used, reward):
    """
    perf_score: short-term performance signal (0–1)
    regime_used: regime chosen on the trade
    reward: realised trade outcome (PnL)
    """

    s = load_state()

    # -------------------------------------------------
    # 1. Eligibility Trace Update (TD-λ)
    # -------------------------------------------------
    for r in REGIMES:
        if r == regime_used:
            s["eligibility"][r] = 1.0
        else:
            s["eligibility"][r] *= LAMBDA

    # -------------------------------------------------
    # 2. TD Target
    # -------------------------------------------------
    Q_old = s["Q"][regime_used]
    target = reward + GAMMA * Q_old
    delta = target - Q_old

    # -------------------------------------------------
    # 3. Apply update to ALL regimes using eligibility
    # -------------------------------------------------
    for r in REGIMES:
        s["Q"][r] += ALPHA * delta * s["eligibility"][r]
        s["Q"][r] = max(MIN_Q, min(MAX_Q, s["Q"][r]))   # Safe clamp

    # -------------------------------------------------
    # 4. Bayesian Confidence Update
    # -------------------------------------------------
    for r in REGIMES:
        old_c = s["C"][r]
        if r == regime_used:
            # Better than expected increases confidence
            target_conf = 1.0 + max(0, reward)
        else:
            target_conf = 1.0

        new_c = (1 - BETA) * old_c + BETA * target_conf

        # Extra penalty for losers
        if r == regime_used and reward < 0:
            new_c *= CONF_DECAY_ON_LOSS

        # Clamp for safety
        new_c = max(MIN_CONF, min(MAX_CONF, new_c))
        s["C"][r] = new_c

    # -------------------------------------------------
    # 5. Convert Q-values × confidence → weights
    # -------------------------------------------------
    raw_scores = {r: s["Q"][r] * s["C"][r] for r in REGIMES}
    softmax_w = _softmax(raw_scores)

    for r in REGIMES:
        s["W"][r] = DECAY * s["W"][r] + (1 - DECAY) * softmax_w[r]

    # -------------------------------------------------
    # 6. Log history
    # -------------------------------------------------
    s["history"].append({
        "regime": regime_used,
        "reward": reward,
        "perf_score": perf_score,
        "Q": s["Q"],
        "C": s["C"],
        "W": s["W"]
    })

    # -------------------------------------------------
    # 7. Trim history to last 1000 entries, then save
    # -------------------------------------------------
    s["history"] = s["history"][-1000:]
    save_state(s)
    return s
