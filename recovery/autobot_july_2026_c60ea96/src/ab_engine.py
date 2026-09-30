#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
ab_engine.py — A/B Genome Live Testing Framework
-------------------------------------------------
Runs two PatternEngine models in parallel (A = stable, B = challenger).
Thread-safe: all load/save pairs are protected by a module-level lock.
"""

import json
import threading
from pathlib import Path

OPT = Path("/opt/tradingbot/optimizer")

PROFILE_A = OPT / "pattern_engine_A.json"
PROFILE_B = OPT / "pattern_engine_B.json"
ACTIVE    = OPT / "pattern_engine_profile.json"
RESULTS   = OPT / "ab_results.json"

PROMOTION_THRESHOLD = 0.15
ROLLBACK_THRESHOLD  = -0.10
MIN_TRADES = 20

_lock = threading.Lock()


# ------------------------------------------------------------
# Helpers: Load / Save JSON
# ------------------------------------------------------------

def load_profile(path):
    if not path.exists():
        return {}
    with path.open() as f:
        return json.load(f)


def save_profile(path, data):
    with path.open("w") as f:
        json.dump(data, f, indent=4)


def load_results():
    if RESULTS.exists():
        try:
            with RESULTS.open() as f:
                data = json.load(f)
        except Exception:
            data = None
        if isinstance(data, dict):
            data.setdefault("A", {"pnl": 0, "trades": [], "drawdown": 0})
            data.setdefault("B", {"pnl": 0, "trades": [], "drawdown": 0})
            data.setdefault("last_eval", None)
            return data

    return {
        "A": {"pnl": 0, "trades": [], "drawdown": 0},
        "B": {"pnl": 0, "trades": [], "drawdown": 0},
        "last_eval": None,
    }


def save_results(r):
    with RESULTS.open("w") as f:
        json.dump(r, f, indent=4)


# ------------------------------------------------------------
# Record trade results  (thread-safe)
# ------------------------------------------------------------

def record_trade(model: str, profit: float):
    """
    Called by AutoBot after each trade closes.
    model = "A" or "B"
    profit = realised P/L in pips or currency
    """
    if model not in ("A", "B"):
        return

    with _lock:
        r = load_results()
        r[model]["trades"].append(profit)
        r[model]["pnl"] += profit
        cum = sum(r[model]["trades"])
        r[model]["drawdown"] = min(r[model]["drawdown"], cum)
        save_results(r)


# ------------------------------------------------------------
# Evaluation logic  (thread-safe)
# ------------------------------------------------------------

def evaluate():
    """
    Compares models A & B, decides:
        • Promote B → A  (B outperforms by PROMOTION_THRESHOLD)
        • Rollback B → A baseline  (B underperforms by ROLLBACK_THRESHOLD)
        • No change
    """
    with _lock:
        r = load_results()

        trades_A = r["A"]["trades"]
        trades_B = r["B"]["trades"]

        if len(trades_A) < MIN_TRADES or len(trades_B) < MIN_TRADES:
            return False, "Not enough trades yet"

        pnl_A = sum(trades_A)
        pnl_B = sum(trades_B)

        if pnl_A == 0:
            delta = 1 if pnl_B > 0 else -1
        else:
            delta = (pnl_B - pnl_A) / abs(pnl_A)

        if delta >= PROMOTION_THRESHOLD:
            new_profile = load_profile(PROFILE_B)
            save_profile(ACTIVE, new_profile)
            save_profile(PROFILE_A, new_profile)
            return True, f"Promoted B to A (delta={delta:.2f})"

        if delta <= ROLLBACK_THRESHOLD:
            stable = load_profile(PROFILE_A)
            save_profile(PROFILE_B, stable)
            return True, f"Rolled back B to A baseline (delta={delta:.2f})"

        return True, "No switch"


# ------------------------------------------------------------
# CLI
# ------------------------------------------------------------

if __name__ == "__main__":
    print(evaluate())
