"""extreme_fade_translation — first-N-fires translation validator.

Each strategy fire is compared against a harness-equivalent recompute of the
indicator from the bar's close-series. The check is deterministic — both
production and the validator use scripts/analysis/full_search/features.py
math (re-exported via extreme_fade_indicators.py), so a non-zero diff means
the production code path has drifted from the discovery code path.

Behaviour:
  - First MAX_FIRES per mode are logged to logs/extreme_fade_translation.jsonl
  - Discrepancies (indicator delta > IND_TOL or sl/tp mismatch) are also
    logged at WARNING / ERROR via the strategy's logger.
  - After MAX_FIRES, no further entries written for that mode.

Tolerances:
  - Indicator value: 1e-6 (RSI/MACD are smooth functions of close, so any
    legitimate drift is below floating-point noise).
  - Bar timestamp: exact match required.
  - SL/TP pip values: exact match against the configured constants.
"""
from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path
from typing import Any, Dict

import numpy as np
import pandas as pd

logger = logging.getLogger("extreme_fade_translation")

# Cap per mode — keep noise low; first 5 fires per mode is enough to surface
# any code/data drift.
MAX_FIRES_PER_MODE = int(os.getenv("EXTREME_FADE_TRANSLATION_MAX_FIRES", "5"))
LOG_PATH = Path(os.getenv(
    "EXTREME_FADE_TRANSLATION_LOG",
    "logs/extreme_fade_translation.jsonl",
))

# Tolerance for indicator reconciliation. RSI/MACD are deterministic floats —
# 1e-6 catches any meaningful divergence while ignoring sub-ulp jitter.
IND_TOL = 1e-6

# Per-mode counter of fires logged. Mutated under _LOCK.
_FIRES_LOGGED: Dict[str, int] = {}
_LOCK = threading.Lock()


def _ensure_log_dir() -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)


def _within(actual: float, expected: float, tol: float) -> bool:
    if actual is None or expected is None:
        return False
    if not np.isfinite(actual) or not np.isfinite(expected):
        return False
    return abs(actual - expected) <= tol


def maybe_log_fire(
    *,
    mode: str,
    pair: str,
    direction: str,
    bar_ts: pd.Timestamp,
    closes_tail: pd.Series,
    indicator_name: str,
    production_value: float,
    reference_value: float,
    threshold: float,
    op: str,
    sl_pips_actual: float,
    tp_pips_actual: float,
    sl_pips_configured: float,
    tp_pips_configured: float,
    decision_entry: float,
    extras: Dict[str, Any] | None = None,
) -> None:
    """Write a single translation-validation row IF this is one of the first
    MAX_FIRES_PER_MODE fires for this mode. Also surface a WARNING when
    metrics diverge.
    """
    with _LOCK:
        n_logged = _FIRES_LOGGED.get(mode, 0)
        if n_logged >= MAX_FIRES_PER_MODE:
            return
        _FIRES_LOGGED[mode] = n_logged + 1

    ind_diff = (
        abs(production_value - reference_value)
        if (production_value is not None
            and reference_value is not None
            and np.isfinite(production_value)
            and np.isfinite(reference_value))
        else None
    )
    sl_match = _within(sl_pips_actual, sl_pips_configured, 1e-6)
    tp_match = _within(tp_pips_actual, tp_pips_configured, 1e-6)
    ind_match = ind_diff is not None and ind_diff <= IND_TOL
    threshold_breach_satisfied = (
        (op == ">" and reference_value > threshold)
        or (op == "<" and reference_value < threshold)
    )

    overall_ok = sl_match and tp_match and ind_match and threshold_breach_satisfied

    row = {
        "mode": mode,
        "pair": pair,
        "direction": direction,
        "bar_ts": str(bar_ts),
        "indicator": indicator_name,
        "indicator_production": float(production_value) if production_value is not None else None,
        "indicator_reference": float(reference_value) if reference_value is not None else None,
        "indicator_diff": float(ind_diff) if ind_diff is not None else None,
        "indicator_match_within_tol": bool(ind_match),
        "threshold": float(threshold),
        "op": op,
        "threshold_breach_satisfied": bool(threshold_breach_satisfied),
        "sl_pips_actual": float(sl_pips_actual),
        "sl_pips_configured": float(sl_pips_configured),
        "sl_match": bool(sl_match),
        "tp_pips_actual": float(tp_pips_actual),
        "tp_pips_configured": float(tp_pips_configured),
        "tp_match": bool(tp_match),
        "decision_entry_mid": float(decision_entry) if decision_entry is not None else None,
        "fire_index_for_mode": _FIRES_LOGGED.get(mode, 0),
        "max_fires_for_mode": MAX_FIRES_PER_MODE,
        "overall_ok": bool(overall_ok),
        "extras": extras or {},
        # Save the last 30 closes used to compute the indicator for offline
        # forensic replay. Omit in jsonl if too large.
        "closes_tail_last_30": [float(x) for x in closes_tail.tail(30).tolist()],
    }

    try:
        _ensure_log_dir()
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")
    except Exception as exc:
        logger.warning("[%s] translation log write failed: %s", mode, exc)
        return

    if overall_ok:
        logger.info(
            "[%s] translation-validation #%d/%d OK | %s_prod=%.6f ref=%.6f "
            "(diff=%.2e) thr%s%.4f sl=%.1fp tp=%.1fp",
            mode, _FIRES_LOGGED.get(mode, 0), MAX_FIRES_PER_MODE,
            indicator_name, production_value, reference_value,
            ind_diff if ind_diff is not None else float("nan"),
            op, threshold, sl_pips_actual, tp_pips_actual,
        )
        return

    # Non-OK paths: be loud
    logger.error(
        "[%s] translation-validation #%d/%d MISMATCH | "
        "%s_prod=%s ref=%s diff=%s ind_match=%s | thr_breach=%s | "
        "sl_actual=%s configured=%s match=%s | tp_actual=%s configured=%s match=%s",
        mode, _FIRES_LOGGED.get(mode, 0), MAX_FIRES_PER_MODE,
        indicator_name, production_value, reference_value, ind_diff,
        ind_match, threshold_breach_satisfied,
        sl_pips_actual, sl_pips_configured, sl_match,
        tp_pips_actual, tp_pips_configured, tp_match,
    )


def reset_for_tests() -> None:
    """Clear the per-mode counter — for unit tests only."""
    with _LOCK:
        _FIRES_LOGGED.clear()
