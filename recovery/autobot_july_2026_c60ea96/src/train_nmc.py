#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
train_nmc.py
------------

Training script for the Neural Meta-Controller (NMC).

Pulls experiences from:
    experience_buffer.jsonl

Trains:
    - Action policy head      (BUY / SELL / NONE)
    - Regime forecast head    (TREND / RANGE / VOLATILE / CALM)
    - Weight head             (PatternEngine weight deltas)

Uses:
    - causal_transformer.CausalTransformer
    - neural_meta_controller.NeuralMetaController
    - experience_buffer.sample_batch()

Outputs:
    /opt/tradingbot/ai/models/nmc_latest.pth
    /opt/tradingbot/ai/models/nmc_epoch_X.pth
"""

import time
import torch
import numpy as np
from pathlib import Path
import torch.nn.functional as F
from torch import optim

from experience_buffer import sample_batch, buffer_stats
# NeuralMetaController removed — training CausalTransformer directly
from causal_transformer import CausalTransformer


# -------------------------------------------------------------------
# Config
# -------------------------------------------------------------------

BASE = Path("/opt/tradingbot/ai")
MODEL_DIR = BASE / "models"
MODEL_DIR.mkdir(parents=True, exist_ok=True)

BATCH_SIZE = 64
EPOCHS = 50
LR = 1e-4
WARMUP_MIN_SIZE = 500       # Require at least 500 experiences
MAX_SEQ_LEN = 32            # Context length for causal transformer
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"

CHECKPOINT_EVERY = 5


# -------------------------------------------------------------------
# Helper: Convert weights dict to tensor
# -------------------------------------------------------------------

def weights_to_vec(weights_dict):
    if not weights_dict:
        return torch.zeros(8)   # default vec size
    vals = list(weights_dict.values())
    arr = np.array(vals, dtype=np.float32)
    return torch.tensor(arr)


# -------------------------------------------------------------------
# Prepare model
# -------------------------------------------------------------------

def create_model(feature_dim):
    """
    Feature dim is inferred from buffer samples.
    """
    # CausalTransformer only accepts seq_len and feature_dim
    model = CausalTransformer(
        seq_len=MAX_SEQ_LEN,
        feature_dim=feature_dim,
    )
    return model.to(DEVICE)


# -------------------------------------------------------------------
# Loss Function
# -------------------------------------------------------------------

def compute_loss(batch, model):
    """
    batch: list of experience dicts
    model: NMC instance
    """
    features = []
    actions = []
    rewards = []
    weights = []

    for exp in batch:
        features.append(exp.get("features", []))
        actions.append(exp.get("action", 2))
        rewards.append(exp.get("reward", 0.0))
        weights.append(exp.get("weights", {}))

    features = torch.tensor(features, dtype=torch.float32, device=DEVICE)
    actions = torch.tensor(actions, dtype=torch.long, device=DEVICE)
    rewards = torch.tensor(rewards, dtype=torch.float32, device=DEVICE)
    weight_vecs = torch.stack([weights_to_vec(w) for w in weights]).to(DEVICE)

    # Expand features to sequence (causal transformer expects 3D)
    seq = features.unsqueeze(1).repeat(1, MAX_SEQ_LEN, 1)

    out = model(seq)

    action_logits = out["action_logits"]
    regime_logits = out["regime_logits"]
    weight_pred   = out["weight_logits"]

    # Action loss (reinforcement via advantage == reward)
    action_loss = F.cross_entropy(action_logits, actions, reduction="none")
    action_loss = (action_loss * (1.0 + rewards)).mean()

    # Regime loss is unsupervised → zeroed (placeholder)
    regime_loss = 0.0 * regime_logits.sum()

    # Weight prediction loss (L2)
    weight_loss = F.mse_loss(weight_pred, weight_vecs)

    # Total
    total = action_loss + 0.1 * weight_loss + 0.0 * regime_loss

    return total, {
        "action_loss": float(action_loss.item()),
        "weight_loss": float(weight_loss.item()),
    }


# -------------------------------------------------------------------
# Training Loop
# -------------------------------------------------------------------

def train():
    print("\n🧠 Neural Meta-Controller Trainer Starting…")

    # Wait for enough experiences
    while True:
        stats = buffer_stats()
        if stats["size"] >= WARMUP_MIN_SIZE:
            break
        print(f"⏳ Waiting for buffer warmup ({stats['size']}/{WARMUP_MIN_SIZE})…")
        time.sleep(5)

    # Peek a batch to infer feature dim
    warm = sample_batch(10)
    sample = warm[0]
    feature_dim = len(sample.get("features", []))

    print(f"🔥 Feature dim detected: {feature_dim}")

    model = create_model(feature_dim)
    opt = optim.Adam(model.parameters(), lr=LR)

    # Training
    for epoch in range(1, EPOCHS + 1):
        batch = sample_batch(BATCH_SIZE)
        if not batch:
            print("⚠ empty batch — skipping")
            continue

        opt.zero_grad()
        loss, parts = compute_loss(batch, model)
        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
        opt.step()

        print(
            f"[Epoch {epoch}/{EPOCHS}] "
            f"loss={loss.item():.4f}  "
            f"a={parts['action_loss']:.4f}  "
            f"w={parts['weight_loss']:.4f}"
        )

        # checkpoint
        if epoch % CHECKPOINT_EVERY == 0:
            ck = MODEL_DIR / f"nmc_epoch_{epoch}.pth"
            torch.save(model.state_dict(), ck)
            print(f"💾 Saved checkpoint → {ck}")

    # Save final model
    final = MODEL_DIR / "nmc_latest.pth"
    torch.save(model.state_dict(), final)
    print(f"\n🎉 Training complete — saved {final}")


# -------------------------------------------------------------------
# CLI
# -------------------------------------------------------------------

if __name__ == "__main__":
    train()
