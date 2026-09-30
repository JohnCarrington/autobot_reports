#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
causal_transformer.py — Hybrid AI Engine (SEQ_LEN = 128)
--------------------------------------------------------

Primary interface for AutoBot AI Brain.

If PyTorch model exists:
    • Loads transformer from: /opt/tradingbot/models/causal_transformer.pt
    • Runs full neural inference

Else:
    • Uses deterministic NumPy fallback
    • Ensures AutoBot never breaks

Public API:
    predict(features: np.ndarray) -> dict with keys:
        - action_logits
        - regime_logits
        - weight_logits
        - features
"""

import numpy as np
from pathlib import Path

MODEL_PATH = Path("/opt/tradingbot/models/causal_transformer.pt")

SEQ_LEN = 128        # <—— Your chosen context length
FEATURE_DIM = 64     # You may adjust later
USE_TORCH = False    # flipped to True if PyTorch is available


# ============================================================
# 1. Try loading PyTorch model
# ============================================================
try:
    import torch
    from torch import nn

    class CausalTransformer(nn.Module):
        def __init__(self, seq_len=128, feature_dim=64):
            super().__init__()
            self.seq_len = seq_len
            self.feature_dim = feature_dim

            self.embed = nn.Linear(feature_dim, 128)

            encoder_layer = nn.TransformerEncoderLayer(
                d_model=128,
                nhead=4,
                dim_feedforward=256,
                batch_first=True
            )
            self.encoder = nn.TransformerEncoder(encoder_layer, num_layers=4)

            self.head_action = nn.Linear(128, 3)    # BUY / SELL / HOLD
            self.head_regime = nn.Linear(128, 4)    # regimes
            self.head_weights = nn.Linear(128, 8)   # meta-weights
            self.head_features = nn.Linear(128, feature_dim)

        def forward(self, x):
            x = self.embed(x)
            x = self.encoder(x)
            last = x[:, -1, :]
            return {
                "action_logits": self.head_action(last),
                "regime_logits": self.head_regime(last),
                "weight_logits": self.head_weights(last),
                "features": self.head_features(last)
            }

    if MODEL_PATH.exists():
        model = CausalTransformer(SEQ_LEN, FEATURE_DIM)
        model.load_state_dict(torch.load(MODEL_PATH, map_location="cpu"))
        model.eval()
        USE_TORCH = True
        print("[AI] Loaded transformer model")
    else:
        model = None
        print("[AI] No transformer model found — fallback mode")

except Exception as e:
    print("[AI] PyTorch unavailable — fallback mode:", e)
    model = None
    USE_TORCH = False


# ============================================================
# 2. Softmax utility
# ============================================================
def softmax(x):
    x = np.array(x)
    e = np.exp(x - np.max(x))
    return e / (e.sum() + 1e-9)


# ============================================================
# 3. NumPy fallback model
# ============================================================
def _fallback_predict(seq):
    """
    Deterministic causal fallback — does NOT require PyTorch.
    Produces stable logits and next-step predictions.
    """

    # basic summary statistics
    mean = seq.mean(axis=0)
    std = seq.std(axis=0)
    last = seq[-1]

    # crude but usable "logits"
    action_logits = np.array([
        mean.sum(),
        -mean.sum(),
        std.sum() * 0.1
    ])

    # Divide feature vector into 4 equal chunks dynamically
    chunk = max(1, len(last) // 4)
    regime_logits = np.array([
        last[0          : chunk    ].sum(),
        last[chunk      : chunk * 2].sum(),
        last[chunk * 2  : chunk * 3].sum(),
        last[chunk * 3  :           ].sum(),
    ])

    weight_logits = np.tanh(last[:8]) * 2.0

    predicted_features = last + (mean * 0.05)

    return {
        "action_logits": action_logits,
        "regime_logits": regime_logits,
        "weight_logits": weight_logits,
        "features": predicted_features
    }


# ============================================================
# 4. Main Predict Function (Unified API)
# ============================================================
def predict(sequence):
    """
    Input:
        sequence: ndarray of shape (T, FEATURE_DIM)

    Output dict:
        {
            "action_logits": np.ndarray (3,)
            "regime_logits": np.ndarray (4,)
            "weight_logits": np.ndarray (8,)
            "features": np.ndarray (FEATURE_DIM,)
        }
    """

    seq = np.array(sequence, dtype=float)

    # pad or trim to SEQ_LEN
    if len(seq) < SEQ_LEN:
        pad = np.zeros((SEQ_LEN - len(seq), FEATURE_DIM))
        seq = np.vstack([pad, seq])
    else:
        seq = seq[-SEQ_LEN:]

    # PyTorch Mode
    if USE_TORCH and model:
        with torch.no_grad():
            tens = torch.tensor(seq, dtype=torch.float32).unsqueeze(0)
            out = model(tens)

        return {
            "action_logits": out["action_logits"].squeeze(0).numpy(),
            "regime_logits": out["regime_logits"].squeeze(0).numpy(),
            "weight_logits": out["weight_logits"].squeeze(0).numpy(),
            "features": out["features"].squeeze(0).numpy()
        }

    # NumPy fallback
    return _fallback_predict(seq)
