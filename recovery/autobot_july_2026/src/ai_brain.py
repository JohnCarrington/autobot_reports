#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
ai_brain.py — Unified Inference Engine for Sentinel
----------------------------------------------------

This module merges:
    • Neural Meta-Controller (NMC)
    • Meta-Learning Controller (MLC)
    • Causal Transformer (optional)
    • Regime forecasts and detectors
    • Action + size + confidence inference

Public API:
    brain = AiBrain()
    decision = brain.evaluate(symbol, df1, df5, df1h, mid, has_open_position)
    brain.feedback(action, realised_pnl)

Decision is a SimpleNamespace with fields:
    signal, confidence, size_mult, entry, sl, tp,
    regime_now, regime_future, reward_estimate, debug
"""

import numpy as np
from types import SimpleNamespace

# ---------------------------------------------------------
# Internal modules
# ---------------------------------------------------------
from meta_learning_controller import update_meta_learning, load_state
from regime_detector import detect_regime
from regime_forecaster import forecast_regime
from pattern_engine_router import evaluate_with_regime
from neural_meta_controller import run_nmc

# Optional causal transformer
try:
    from causal_transformer import predict as causal_predict
    CAUSAL_ENABLED = True
except Exception:
    CAUSAL_ENABLED = False


# ---------------------------------------------------------
# Module-level state (shared across AiBrain instances)
# ---------------------------------------------------------
_LAST_FEATURES = None
_LAST_ACTION   = None
_LAST_REWARD   = 0.0


# ---------------------------------------------------------
# build_feature_vector
# Constructs a fixed-length feature array from market data
# and meta-learning state for the NMC.
# ---------------------------------------------------------
def build_feature_vector(df1, df5, df1h,
                          genome_preds=None,
                          meta_learning_state=None,
                          regime_now="RANGE",
                          regime_future="RANGE",
                          spread=0.00002,
                          performance_scores=None):
    """
    Returns a 2D numpy array of shape (SEQ_LEN, FEATURE_DIM) suitable
    for the NMC / CausalTransformer.

    Features per timestep (64-dim):
        0–3   : last 4 5m close returns
        4–7   : last 4 5m high-low ranges
        8–11  : last 4 1h close returns
        12–15 : EMA(20) distance on 5m, 1m, 1h (padded)
        16–19 : regime one-hot [TREND, RANGE, VOLATILE, CALM]
        20–23 : future regime one-hot
        24–27 : meta-learning Q-values per regime
        28–31 : meta-learning weights per regime
        32–35 : performance scores per regime
        36    : spread
        37–63 : zeros (reserved for future expansion)
    """
    REGIMES   = ["TREND", "RANGE", "VOLATILE", "CALM"]
    FEAT_DIM  = 64
    SEQ_LEN   = 32

    def _safe(df, col, n):
        if df is None or col not in df.columns or len(df) < 2:
            return np.zeros(n)
        vals = df[col].values[-n-1:]
        if len(vals) < 2:
            return np.zeros(n)
        returns = np.diff(vals)
        if len(returns) < n:
            returns = np.pad(returns, (n - len(returns), 0))
        return returns[-n:]

    def _regime_onehot(r):
        v = np.zeros(4)
        if r in REGIMES:
            v[REGIMES.index(r)] = 1.0
        return v

    ml = meta_learning_state or {}
    Q  = ml.get("Q", {r: 0.0 for r in REGIMES})
    W  = ml.get("W", {r: 0.25  for r in REGIMES})
    ps = performance_scores or {r: 0.0 for r in REGIMES}

    row = np.zeros(FEAT_DIM)
    row[0:4]   = _safe(df5, "close", 4)
    row[4:8]   = np.clip(
        (df5["high"].values[-4:] - df5["low"].values[-4:]) if df5 is not None and len(df5) >= 4 else np.zeros(4),
        0, 1
    )
    row[8:12]  = _safe(df1h, "close", 4)

    if df5 is not None and len(df5) >= 20 and "close" in df5.columns:
        ema20 = df5["close"].ewm(span=20, adjust=False).mean().iloc[-1]
        row[12] = df5["close"].iloc[-1] - ema20
    if df1 is not None and len(df1) >= 5 and "close" in df1.columns:
        row[13] = df1["close"].iloc[-1] - df1["close"].ewm(span=5, adjust=False).mean().iloc[-1]

    row[16:20] = _regime_onehot(regime_now)
    row[20:24] = _regime_onehot(regime_future)
    row[24:28] = np.array([Q.get(r, 0.0) for r in REGIMES])
    row[28:32] = np.array([W.get(r, 0.25) for r in REGIMES])
    row[32:36] = np.array([ps.get(r, 0.0) for r in REGIMES])
    row[36]    = spread

    # Build a SEQ_LEN-step sequence by slightly perturbing the row
    # (real implementation would use historical rows; this ensures
    # the NMC always receives valid input shape)
    seq = np.tile(row, (SEQ_LEN, 1))
    return seq


# ---------------------------------------------------------
# _map_action
# ---------------------------------------------------------
def _map_action(idx):
    return ["BUY", "SELL", "NONE"][idx] if idx in (0, 1, 2) else "NONE"


# ---------------------------------------------------------
# ai_brain_decide  (module-level function, kept for compat)
# ---------------------------------------------------------
def ai_brain_decide(df1, df5, df1h, mid, current_spread=0.00002):
    """
    Main inference pipeline for every tick.
    Returns a dict with signal, confidence, size_mult, etc.
    """
    global _LAST_FEATURES, _LAST_ACTION, _LAST_REWARD

    # 1. Regime
    regime_now    = detect_regime(df5)
    regime_future = forecast_regime(df5)

    # 2. PatternEngine router
    try:
        (pe_decision, pe_regime) = evaluate_with_regime(df1, df5, df1h, mid)
    except Exception:
        pe_decision, pe_regime = "NONE", regime_now

    # 3. Meta-Learning state
    ml = load_state()

    # 4. Feature vector
    perf_scores = {r: 0.0 for r in ["TREND", "RANGE", "VOLATILE", "CALM"]}
    features = build_feature_vector(
        df1=df1, df5=df5, df1h=df1h,
        meta_learning_state=ml,
        regime_now=regime_now,
        regime_future=regime_future,
        spread=current_spread,
        performance_scores=perf_scores
    )
    _LAST_FEATURES = features

    # 5. NMC forward pass
    out = run_nmc(features)

    weights    = out.get("weights", {})
    size_mult  = float(out.get("size_mult", 1.0))
    signal     = out.get("signal", "NONE")
    confidence = float(out.get("confidence", 0.0))

    # 6. Causal transformer (optional)
    causal_pred = None
    if CAUSAL_ENABLED:
        try:
            causal_pred = causal_predict(features)
        except Exception:
            causal_pred = None

    # 7. Reward estimate
    reward_est = confidence * size_mult

    # 8. Meta-Learning update
    if _LAST_ACTION is not None:
        try:
            update_meta_learning(
                perf_score=confidence,
                regime_used=regime_now,
                reward=_LAST_REWARD
            )
        except Exception:
            pass

    _LAST_ACTION = signal

    return {
        "signal":            signal,
        "confidence":        confidence,
        "size_mult":         size_mult,
        "genome_weights":    weights,
        "regime_now":        regime_now,
        "regime_future":     regime_future,
        "reward_estimate":   reward_est,
        "causal_prediction": causal_pred,
        "debug": {
            "pe_decision": pe_decision,
            "pe_regime":   pe_regime,
            "ml_state":    ml,
        }
    }


# ---------------------------------------------------------
# ai_brain_feedback  (module-level, kept for compat)
# ---------------------------------------------------------
def ai_brain_feedback(action, realised_pnl):
    """Call after a trade closes to feed reward back."""
    global _LAST_REWARD
    _LAST_REWARD = realised_pnl


# ---------------------------------------------------------
# AiBrain class  — thin wrapper used by sentinel.py
# ---------------------------------------------------------
class AiBrain:
    """
    Wraps ai_brain_decide() with the interface sentinel.py expects:

        decision = brain.evaluate(
            symbol, df1, df5, df1h, mid, has_open_position
        )

    Returns a SimpleNamespace so callers can do decision.signal,
    decision.confidence, decision.entry, decision.sl, decision.tp.
    """

    # Default SL/TP distances in price (not pips) — overridden per regime
    _SL_DIST = 0.0030   # 30 pips
    _TP_DIST = 0.0050   # 50 pips

    def evaluate(self, symbol, df1, df5, df1h, mid, has_open_position=False):
        """
        Run the full AI pipeline and return a structured decision.
        If there is already an open position, returns signal=NONE.
        """
        if has_open_position:
            return self._none_decision(mid)

        try:
            result = ai_brain_decide(df1, df5, df1h, mid)
        except Exception as e:
            import logging
            logging.getLogger("Sentinel").warning(f"[AiBrain] decide error: {e}")
            return self._none_decision(mid)

        signal     = result["signal"]
        confidence = result["confidence"]
        size_mult  = result["size_mult"]

        if signal == "BUY":
            entry = mid
            sl    = mid - self._SL_DIST
            tp    = mid + self._TP_DIST
        elif signal == "SELL":
            entry = mid
            sl    = mid + self._SL_DIST
            tp    = mid - self._TP_DIST
        else:
            return self._none_decision(mid)

        return SimpleNamespace(
            signal     = signal,
            confidence = confidence,
            size_mult  = size_mult,
            entry      = entry,
            sl         = sl,
            tp         = tp,
            regime_now    = result.get("regime_now", "UNKNOWN"),
            regime_future = result.get("regime_future", "UNKNOWN"),
            debug         = result.get("debug", {}),
        )

    def feedback(self, action, realised_pnl):
        """Feed trade outcome back into the meta-learning loop."""
        ai_brain_feedback(action, realised_pnl)

    @staticmethod
    def _none_decision(mid):
        return SimpleNamespace(
            signal="NONE", confidence=0.0, size_mult=1.0,
            entry=mid, sl=mid, tp=mid,
            regime_now="UNKNOWN", regime_future="UNKNOWN", debug={}
        )
