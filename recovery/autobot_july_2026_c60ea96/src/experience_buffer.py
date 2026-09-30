#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
experience_buffer.py
--------------------

Robust disk-backed replay buffer for the Neural Meta-Controller.

Used by:
    - train_nmc.py     for minibatch sampling
    - ai_brain.py      for pushing experiences
    - meta_learning_controller.py
"""

import json
import time
import random
import threading
from pathlib import Path


# -------------------------------------------------------------------
# Configuration
# -------------------------------------------------------------------

BASE_DIR = Path("/opt/tradingbot/ai")
BASE_DIR.mkdir(parents=True, exist_ok=True)

BUFFER_PATH = BASE_DIR / "experience_buffer.jsonl"
MAX_EXPERIENCES = 50_000

_lock = threading.Lock()
_line_count = 0          # in-memory estimate; avoids a full file read on every push
_TRIM_EVERY  = 500       # only do a disk trim check after this many new pushes
_push_count  = 0


# -------------------------------------------------------------------
# Internal helpers
# -------------------------------------------------------------------

def _safe_float(x):
    try:
        return float(x)
    except Exception:
        return 0.0


def _safe_list(x):
    try:
        return list(map(float, x))
    except Exception:
        return []


# -------------------------------------------------------------------
# Push experience (Append-Only)
# -------------------------------------------------------------------

def push_experience(features, action, reward, genome_weights=None):
    """
    Append one experience to buffer.
    Thread-safe. Trims to MAX_EXPERIENCES periodically (not on every push).
    """
    global _push_count, _line_count

    exp = {
        "timestamp": time.time(),
        "features":  _safe_list(features),
        "action":    int(action),
        "reward":    _safe_float(reward),
        "weights":   genome_weights if genome_weights else {},
    }

    with _lock:
        with BUFFER_PATH.open("a") as f:
            f.write(json.dumps(exp) + "\n")
        _line_count += 1
        _push_count += 1

        # Only do the expensive disk trim every _TRIM_EVERY pushes
        if _push_count >= _TRIM_EVERY:
            _push_count = 0
            _trim_if_needed()


# -------------------------------------------------------------------
# Load entire buffer (fast & safe)
# -------------------------------------------------------------------

def load_buffer():
    """
    Loads buffer contents safely.
    Corrupt lines are ignored.
    Returns: list of experience dicts
    """
    if not BUFFER_PATH.exists():
        return []

    out = []
    with _lock:
        with BUFFER_PATH.open() as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    exp = json.loads(line)
                    out.append(exp)
                except Exception:
                    continue

    return out


# -------------------------------------------------------------------
# Random minibatch sampling
# -------------------------------------------------------------------

def sample_batch(batch_size=32):
    """
    Returns a random batch of experiences.
    If insufficient size, returns empty list.
    """
    buf = load_buffer()
    if len(buf) < batch_size:
        return []

    return random.sample(buf, batch_size)


# -------------------------------------------------------------------
# Trim buffer (keep last MAX_EXPERIENCES)
# -------------------------------------------------------------------

def _trim_if_needed():
    """
    Ensures the buffer has <= MAX_EXPERIENCES lines.
    Implemented as a safe rewrite.
    """
    try:
        with BUFFER_PATH.open() as f:
            lines = f.readlines()

        if len(lines) <= MAX_EXPERIENCES:
            return

        keep = lines[-MAX_EXPERIENCES:]

        with BUFFER_PATH.open("w") as f:
            for line in keep:
                f.write(line)

    except Exception:
        pass


# -------------------------------------------------------------------
# Diagnostics
# -------------------------------------------------------------------

def buffer_stats():
    """
    Returns dict {size, oldest_ts, newest_ts}.
    """
    buf = load_buffer()
    if not buf:
        return {"size": 0, "oldest_ts": None, "newest_ts": None}

    ts = [e.get("timestamp", 0) for e in buf]
    return {
        "size": len(buf),
        "oldest_ts": float(min(ts)),
        "newest_ts": float(max(ts))
    }


# CLI runner
if __name__ == "__main__":
    print(buffer_stats())
