"""
regime_router.py — Per-pair regime classification and strategy gating.

Reads regime from briefing (SWEEP, TREND, or NEWS) and controls which
strategies are active, their minimum probability thresholds, and sizing.

State persisted to cache/regime_state.json, updated on each briefing.
Telegram notification sent when regime changes for any pair.
"""

import json
import logging
import os
import time
from typing import Any, Dict, Optional

logger = logging.getLogger("AutoBot")

_STATE_FILE = "/opt/tradingbot/cache/regime_state.json"
_DEFAULT_REGIME = "SWEEP"
_VALID_REGIMES = {"SWEEP", "TREND", "NEWS"}

# ── Per-regime strategy configuration ─────────────────────────────────────
# Each strategy maps to: enabled (bool), min_probability (float), size_multiplier (float)
_REGIME_CONFIG: Dict[str, Dict[str, Dict[str, Any]]] = {
    "NEWS": {
        "NEWS_TICK":            {"enabled": True,  "min_probability": 0.0,  "size_multiplier": 1.0},
        "NEWS_STRATEGY":        {"enabled": True,  "min_probability": 0.0,  "size_multiplier": 1.0},
        "BRIEFING_EXECUTION":   {"enabled": True,  "min_probability": 0.70, "size_multiplier": 0.5},
        "WINDOW_SWEEP":         {"enabled": False, "min_probability": 0.0,  "size_multiplier": 0.0},
        "EMA_PULLBACK":         {"enabled": False, "min_probability": 0.0,  "size_multiplier": 0.0},
        "3CO":                  {"enabled": False, "min_probability": 0.0,  "size_multiplier": 0.0},
        "LONDON_PULLBACK":      {"enabled": False, "min_probability": 0.0,  "size_multiplier": 0.0},
        "BRIEFING_SWEEP":       {"enabled": False, "min_probability": 0.0,  "size_multiplier": 0.0},
        "LIQUIDITY_SWEEP":      {"enabled": False, "min_probability": 0.0,  "size_multiplier": 0.0},
        "BRIEFING_HUNT":        {"enabled": False, "min_probability": 0.0,  "size_multiplier": 0.0},
    },
    "TREND": {
        "NEWS_TICK":            {"enabled": True,  "min_probability": 0.0,  "size_multiplier": 1.0},
        "NEWS_STRATEGY":        {"enabled": True,  "min_probability": 0.0,  "size_multiplier": 1.0},
        "3CO":                  {"enabled": True,  "min_probability": 0.0,  "size_multiplier": 1.0},
        "EMA_PULLBACK":         {"enabled": True,  "min_probability": 0.0,  "size_multiplier": 1.0},
        "LONDON_PULLBACK":      {"enabled": True,  "min_probability": 0.0,  "size_multiplier": 1.0},
        "BRIEFING_EXECUTION":   {"enabled": True,  "min_probability": 0.70, "size_multiplier": 0.5},
        "WINDOW_SWEEP":         {"enabled": False, "min_probability": 0.0,  "size_multiplier": 0.0},
        "BRIEFING_SWEEP":       {"enabled": False, "min_probability": 0.0,  "size_multiplier": 0.0},
        "LIQUIDITY_SWEEP":      {"enabled": False, "min_probability": 0.0,  "size_multiplier": 0.0},
        "BRIEFING_HUNT":        {"enabled": True,  "min_probability": 0.0,  "size_multiplier": 1.0},
    },
    "SWEEP": {
        "NEWS_TICK":            {"enabled": True,  "min_probability": 0.0,  "size_multiplier": 1.0},
        "NEWS_STRATEGY":        {"enabled": True,  "min_probability": 0.0,  "size_multiplier": 1.0},
        "BRIEFING_EXECUTION":   {"enabled": True,  "min_probability": 0.50, "size_multiplier": 1.0},
        "BRIEFING_SWEEP":       {"enabled": True,  "min_probability": 0.0,  "size_multiplier": 1.0},
        "WINDOW_SWEEP":         {"enabled": True,  "min_probability": 0.0,  "size_multiplier": 1.0},
        "EMA_PULLBACK":         {"enabled": True,  "min_probability": 0.0,  "size_multiplier": 1.0},
        "LONDON_PULLBACK":      {"enabled": True,  "min_probability": 0.0,  "size_multiplier": 1.0},
        "LIQUIDITY_SWEEP":      {"enabled": True,  "min_probability": 0.0,  "size_multiplier": 1.0},
        "BRIEFING_HUNT":        {"enabled": True,  "min_probability": 0.0,  "size_multiplier": 1.0},
        "3CO":                  {"enabled": True,  "min_probability": 0.0,  "size_multiplier": 0.5},
    },
}

# ── Per-regime exit configuration ─────────────────────────────────────────
_REGIME_EXIT_CONFIG: Dict[str, Dict[str, Any]] = {
    "NEWS": {
        "trail_activate_pips": 15,
        "trail_distance_pips": 10,
        "be_trigger_pips": 8,
        # Increased 2026-04-28 from 30 → 60 after diagnostic showed news moves
        # often need 45+ minutes to develop fully. Combined with the new 12p
        # TP, longer hold gives trades a real chance to fill SL or TP.
        "max_hold_minutes": 60,
    },
    "TREND": {
        "trail_activate_pips": 25,
        "trail_distance_pips": 20,
        "be_trigger_pips": 15,
        "max_hold_minutes": 240,
    },
    "SWEEP": {
        "trail_activate_pips": 20,
        "trail_distance_pips": 15,
        "be_trigger_pips": 12,
        "max_hold_minutes": 120,
    },
}


# ── In-memory state ───────────────────────────────────────────────────────
# {symbol: {"regime": str, "confidence": float, "reasoning": str, "updated": float}}
_regime_state: Dict[str, Dict[str, Any]] = {}


def _load_state() -> None:
    global _regime_state
    try:
        with open(_STATE_FILE) as f:
            _regime_state = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        _regime_state = {}


def _save_state() -> None:
    try:
        os.makedirs(os.path.dirname(_STATE_FILE), exist_ok=True)
        with open(_STATE_FILE, "w") as f:
            json.dump(_regime_state, f)
    except Exception as e:
        logger.debug("[REGIME] State save failed: %s", e)


# Load on import
_load_state()


def update_regime(symbol: str, briefing: Dict[str, Any]) -> None:
    """Called when a new briefing is ingested. Updates regime state and notifies on change."""
    sym = symbol.upper()
    new_regime = str(briefing.get("regime", _DEFAULT_REGIME)).upper()
    if new_regime not in _VALID_REGIMES:
        new_regime = _DEFAULT_REGIME
    new_conf = float(briefing.get("regime_confidence", 0.0) or 0.0)
    new_reasoning = str(briefing.get("regime_reasoning", "") or "")

    old = _regime_state.get(sym, {})
    old_regime = old.get("regime", "")

    _regime_state[sym] = {
        "regime": new_regime,
        "confidence": new_conf,
        "reasoning": new_reasoning,
        "updated": time.time(),
    }
    _save_state()

    if old_regime and old_regime != new_regime:
        logger.info(
            "[REGIME] %s CHANGED: %s -> %s (conf=%.2f) %s",
            sym, old_regime, new_regime, new_conf, new_reasoning,
        )
        try:
            from telegram_alerts import send_telegram_message
            send_telegram_message(
                f"<b>Regime change:</b> {sym}\n"
                f"{old_regime} -> <b>{new_regime}</b> (conf={new_conf:.2f})\n"
                f"{new_reasoning}"
            )
        except Exception:
            pass
    else:
        logger.info(
            "[REGIME] %s = %s (conf=%.2f)",
            sym, new_regime, new_conf,
        )


def get_regime(pair: str) -> str:
    """Return current regime for a pair. Defaults to SWEEP."""
    sym = pair.upper()
    st = _regime_state.get(sym)
    if not st:
        return _DEFAULT_REGIME
    return st.get("regime", _DEFAULT_REGIME)


def get_strategy_config(pair: str, strategy: str) -> Dict[str, Any]:
    """Return {enabled, min_probability, size_multiplier, exit_config} for a strategy under current regime."""
    regime = get_regime(pair)
    regime_map = _REGIME_CONFIG.get(regime, _REGIME_CONFIG[_DEFAULT_REGIME])
    config = regime_map.get(strategy)
    if config is None:
        config = {"enabled": True, "min_probability": 0.0, "size_multiplier": 1.0}
    else:
        config = dict(config)
    config["exit_config"] = dict(_REGIME_EXIT_CONFIG.get(regime, _REGIME_EXIT_CONFIG[_DEFAULT_REGIME]))
    return config


def get_exit_config(pair: str) -> Dict[str, Any]:
    """Return exit config for the current regime of a pair."""
    regime = get_regime(pair)
    return dict(_REGIME_EXIT_CONFIG.get(regime, _REGIME_EXIT_CONFIG[_DEFAULT_REGIME]))
