#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
meta_genome_controller.py
-------------------------

The Meta-Genome Controller evaluates all regime genomes and selects:
    • Best genome for current conditions
    • Blended weightings
    • Position size multiplier
    • Final signal + confidence
"""

import json
from pathlib import Path
from statistics import mean

# Regime utilities
from regime_detector import detect_regime
from regime_forecaster import forecast_regime
from meta_learning_controller import load_state

# Single PatternEngine — regime-specific behaviour via override_profile
from pattern_engine import PatternEngine

# Live A/B test performance
from ab_engine import load_results

# Neural Meta Controller
from neural_meta_controller import run_nmc
from ai_brain import build_feature_vector

REGIMES = ["TREND", "RANGE", "VOLATILE", "CALM"]
REG_DIR = Path("/opt/tradingbot/optimizer/regimes")


# =======================================================================
# Helpers
# =======================================================================

def load_genome(name):
    """Loads genome JSON for a regime."""
    path = REG_DIR / f"{name.lower()}_genome.json"
    if not path.exists():
        return {}
    with path.open() as f:
        return json.load(f)


# =======================================================================
# Main Meta-Genome Controller
# =======================================================================

def meta_controller(df1, df5, df1h, mid, current_spread):
    """
    Master controller:
        1) Detect + forecast regime
        2) Evaluate all PatternEngines
        3) Combine with Meta-Learning state
        4) Fuse signals with regime weights
        5) Yield final signal + size
    """

    # ----------------------------------------------------------
    # 1. Detect regime NOW and predicted NEXT
    # ----------------------------------------------------------
    regime_now = detect_regime(df5)
    regime_future = forecast_regime(df5)

    # ----------------------------------------------------------
    # 2. Evaluate all PatternEngines
    # ----------------------------------------------------------
    results = {}

    sig_tr, conf_tr, _, _ = PatternEngine.evaluate(df1, df5, df1h, mid, override_profile=load_genome("trend"))
    sig_rg, conf_rg, _, _ = PatternEngine.evaluate(df1, df5, df1h, mid, override_profile=load_genome("range"))
    sig_vo, conf_vo, _, _ = PatternEngine.evaluate(df1, df5, df1h, mid, override_profile=load_genome("volatile"))
    sig_ca, conf_ca, _, _ = PatternEngine.evaluate(df1, df5, df1h, mid, override_profile=load_genome("calm"))

    results["TREND"]    = {"sig": sig_tr, "conf": conf_tr}
    results["RANGE"]    = {"sig": sig_rg, "conf": conf_rg}
    results["VOLATILE"] = {"sig": sig_vo, "conf": conf_vo}
    results["CALM"]     = {"sig": sig_ca, "conf": conf_ca}

    # ----------------------------------------------------------
    # 3. Load performance stats + meta-learning weights
    # ----------------------------------------------------------
    perf = load_results() or {}
    ml_state = load_state()
    learned_weights = ml_state["W"]

    # Build 20-trade recent performance score
    perf_score = {}
    for r in REGIMES:
        key = r[0]  # A/B engine stores T/R/V/C
        trades = perf.get(key, {}).get("trades", [])
        last20 = trades[-20:] if trades else []
        pnl = sum(last20)
        hitrate = (sum(1 for t in last20 if t > 0) / max(1, len(last20))) if last20 else 0
        perf_score[r] = 0.7*pnl + 0.3*hitrate

    # ----------------------------------------------------------
    # 4. Build weighted regime mixture (NMC-enhanced)
    # ----------------------------------------------------------

    # Base weighting: actual regime + predicted regime
    weights = {r: 0.0 for r in REGIMES}

    weights[regime_future] += 0.40
    weights[regime_now]    += 0.30

    # Add meta-learning priors
    for r in REGIMES:
        weights[r] += 0.30 * learned_weights[r]

    # ----------------------------------------------------------
    # NMC-based refinement
    # ----------------------------------------------------------
    features = build_feature_vector(
        df1=df1,
        df5=df5,
        df1h=df1h,
        genome_preds=results,
        meta_learning_state=ml_state,
        regime_now=regime_now,
        regime_future=regime_future,
        spread=current_spread,
        performance_scores=perf_score
    )

    nmc_out = run_nmc(features)

    # NMC output: 4 genome weights
    import numpy as np
    action_probs = nmc_out.get("debug", {}).get("action_probs", [0.33, 0.33, 0.34])
    nm_weights = np.array(action_probs, dtype=float)
    nm_weights = nm_weights / max(1e-9, nm_weights.sum())

    # Blend NMC buy/sell/hold probs into regime weights (buy→trend, sell→range, hold→calm)
    nmc_blend = [nm_weights[0], nm_weights[1], 0.0, nm_weights[2]]  # TREND/RANGE/VOL/CALM
    for idx, r in enumerate(REGIMES):
        weights[r] += 0.25 * float(nmc_blend[idx])

    # Normalize final weighting
    total = sum(weights.values()) or 1
    for r in REGIMES:
        weights[r] /= total

    # ----------------------------------------------------------
    # 5. Weighted signal fusion
    # ----------------------------------------------------------
    tally = {"BUY": 0, "SELL": 0, "NONE": 0}
    conf_tally = {"BUY": [], "SELL": [], "NONE": []}

    for r, w in weights.items():
        sig = results[r]["sig"]
        cf = results[r]["conf"]
        tally[sig] += w
        conf_tally[sig].append(cf)

    final_signal = max(tally, key=tally.get)
    final_conf = mean(conf_tally[final_signal]) if conf_tally[final_signal] else 0.0

    # ----------------------------------------------------------
    # 6. Position sizing based on regime
    # ----------------------------------------------------------
    if regime_future == "TREND":
        size_mult = 1.2
    elif regime_future == "VOLATILE":
        size_mult = 0.7
    elif regime_future == "CALM":
        size_mult = 0.8
    else:
        size_mult = 1.0

    return {
        "signal": final_signal,
        "confidence": final_conf,
        "weights": weights,
        "size_mult": size_mult,
        "regime_now": regime_now,
        "regime_future": regime_future,
        "raw_results": results,
        "performance_scores": perf_score
    }