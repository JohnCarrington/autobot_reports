"""Env-driven config for briefing.v5_pia. Mirrors the repo convention used by
briefing_execution.py — module-level constants resolved from os.getenv(). The
credentials-only config.py at repo root is intentionally untouched.
"""
from __future__ import annotations

import os
from pathlib import Path


def _env_bool(name: str, default: str) -> bool:
    return str(os.getenv(name, default)).strip().lower() in ("1", "true", "yes", "on")


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


# Phase 1: write parallel briefings alongside v4. No executor consumption yet.
BRIEFING_V5_ENABLED = _env_bool("BRIEFING_V5_ENABLED", "1")

# Parallel-mode flag: kept distinct from BRIEFING_V5_ENABLED so Phase 3 can
# flip executor consumption without flipping briefing generation.
BRIEFING_V5_PARALLEL_MODE = _env_bool("BRIEFING_V5_PARALLEL_MODE", "0")

# Min confidence required for state=ARMED. Below this → state=STAND_ASIDE.
# 70 = ARMED bucket lower bound per the scorer's spec.
BRIEFING_EXECUTION_MIN_CONFIDENCE = _env_int("BRIEFING_EXECUTION_MIN_CONFIDENCE", 70)

# Concurrency cap on Phase-3 execution legs. Read but unused in Phase 1.
BRIEFING_MAX_CONCURRENT_LEGS = _env_int("BRIEFING_MAX_CONCURRENT_LEGS", 2)

# Output directory. v5 deliberately writes to a separate tree from v4
# (LOG_DIR/briefing_*.json) so the two producers cannot collide.
BRIEFINGS_DIR = Path(os.getenv("BRIEFINGS_V5_DIR", "/opt/tradingbot/briefings/v5_pia"))

# Bucket boundaries (inclusive lower bound, exclusive upper bound).
BUCKET_THRESHOLDS = (
    ("STAND_ASIDE",     0,  50),
    ("WATCH",          50,  70),
    ("ARMED",          70,  85),
    ("HIGH_CONVICTION", 85, 101),
)


# ─────────────────────────────────────────────────────────────────────────────
# Swing-detection reversal threshold
# ─────────────────────────────────────────────────────────────────────────────
#
# `level_computation._swing_points(bars, lookback_n, min_reversal_pips)` uses
# this value to filter micro-pivots: a swing high (or low) is only accepted
# when price has reversed by at least `min_reversal_pips` since the previous
# accepted swing on the same side. Too tight → every wick becomes a "swing",
# too loose → real structure is filtered out.
#
# Default 5.0 pips is calibrated for the USD-major H4 envelope observed in
# Phase-1 dry-runs:
#   GBPUSD H4 ATR ≈ 42 pip   →  5p ≈ 12% of ATR
#   EURUSD H4 ATR ≈ 36 pip   →  5p ≈ 14% of ATR
#   USDCAD H4 ATR ≈ 25 pip   →  5p ≈ 20% of ATR
#
# JPY pairs trade at roughly twice the absolute pip range of USD majors at
# the same volatility, so a flat 5p value would over-filter their pivots.
# Per-pair override:
#   USDJPY H4 ATR ≈ 85 pip   →  8p ≈ 9% of ATR (matches USD-major proportion)
#
# Override priority (highest wins):
#   1. env: BRIEFING_V5_SWING_MIN_REVERSAL_PIPS_<PAIR>   e.g. _USDJPY=10
#   2. _SWING_PER_PAIR_DEFAULTS map below
#   3. env: BRIEFING_V5_SWING_MIN_REVERSAL_PIPS         (global default)
#   4. compiled-in 5.0
#
# Provisional Phase-1 values. Revisit once Phase-2 shadow data lets us see
# whether the chosen threshold matches what an analyst would call a swing
# on the actual chart — see PHASE1_README.md.
BRIEFING_V5_SWING_MIN_REVERSAL_PIPS = _env_float("BRIEFING_V5_SWING_MIN_REVERSAL_PIPS", 5.0)

_SWING_PER_PAIR_DEFAULTS: dict[str, float] = {
    "USDJPY": 8.0,
    "GBPJPY": 8.0,
}


def get_swing_min_reversal_pips(pair: str) -> float:
    """Return the swing reversal threshold for *pair* in pips.

    Resolution order: per-pair env override → per-pair default → global
    env override → compiled default. See module docstring above for the
    calibration reasoning.
    """
    p = (pair or "").upper()
    env_pp = os.getenv(f"BRIEFING_V5_SWING_MIN_REVERSAL_PIPS_{p}")
    if env_pp is not None:
        try:
            return float(env_pp)
        except (TypeError, ValueError):
            pass
    if p in _SWING_PER_PAIR_DEFAULTS:
        return _SWING_PER_PAIR_DEFAULTS[p]
    return BRIEFING_V5_SWING_MIN_REVERSAL_PIPS
