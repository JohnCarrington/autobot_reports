"""Composite-veto direction resolver for BRIEFING_EXECUTION.

Reads briefing["daily_bias"] — the DETERMINISTIC 9-check output (post
b8c05de; single source of truth, written by d1_direction.compute_d1_direction).
Does NOT read briefing["daily_bias_llm"] (LLM's pre-override value, retained
for audit only).
"""
from __future__ import annotations

from typing import Any, Dict


_DIRECTIONAL = ("BULLISH", "BEARISH")
_BIAS_TO_SIDE = {"BULLISH": "BUY", "BEARISH": "SELL"}


def resolve_briefing_direction(briefing: Dict[str, Any]) -> Dict[str, Any]:
    """Return {action, direction, bias, class, reason}.

    Truth table (daily_bias is the deterministic 9-check):
        daily=NEUTRAL & session=NEUTRAL    → STAND_DOWN (class=BOTH_NEUTRAL)
        daily=NEUTRAL & session directional→ STAND_DOWN (class=DAILY_NEUTRAL)
                                              — +34.5p abstention edge
        daily directional & session NEUTRAL→ TRADE daily (class=SESSION_NEUTRAL)
        daily directional & session AGREE  → TRADE daily (class=AGREE)
        daily directional & session DIFFER → TRADE daily (class=DISAGREE)
                                              — corrected: daily wins
    """
    session = str(briefing.get("session_bias") or "").upper()
    daily = str(briefing.get("daily_bias") or "").upper()

    if daily not in _DIRECTIONAL:
        klass = "BOTH_NEUTRAL" if session not in _DIRECTIONAL else "DAILY_NEUTRAL"
        return {
            "action": "STAND_DOWN",
            "direction": None,
            "bias": "NEUTRAL",
            "class": klass,
            "reason": f"daily_bias={daily or 'MISSING'}, session_bias={session or 'MISSING'}",
        }

    if session not in _DIRECTIONAL:
        klass = "SESSION_NEUTRAL"
    elif session == daily:
        klass = "AGREE"
    else:
        klass = "DISAGREE"

    return {
        "action": "TRADE",
        "direction": _BIAS_TO_SIDE[daily],
        "bias": daily,
        "class": klass,
        "reason": f"daily_bias={daily}, session_bias={session or 'MISSING'} → {klass}",
    }
