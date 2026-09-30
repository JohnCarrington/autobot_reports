"""
sentinel_client.py — Lightweight HTTP client for the Sentinel scoring API.

Functions:
  get_sentinel_score() — fetch a confidence score for a pending signal
  push_trade_outcome() — push a completed trade to Sentinel's outcome store

Never raises. Returns safe fallbacks on any failure.
"""

import logging
import os

import requests

logger = logging.getLogger("AutoBot")

SENTINEL_BASE = os.getenv(
    "SENTINEL_API_BASE", "http://144.126.196.46:5001"
).rstrip("/")
SENTINEL_URL = os.getenv(
    "SENTINEL_SCORE_URL", f"{SENTINEL_BASE}/score"
)
SENTINEL_OUTCOME_URL = os.getenv(
    "SENTINEL_OUTCOME_URL", f"{SENTINEL_BASE}/outcome"
)
SENTINEL_TIMEOUT_S = float(os.getenv("SENTINEL_TIMEOUT_S", "0.5"))
SENTINEL_OUTCOME_TIMEOUT_S = float(os.getenv("SENTINEL_OUTCOME_TIMEOUT_S", "2.0"))

_FALLBACK = {
    "score": 1.0,
    "low_confidence": True,
    "sample_size": 0,
    "available": False,
}


def get_sentinel_score(
    strategy: str,
    direction: str,
    session: str,
    bb_width_pips: float = None,
    atr_pips: float = None,
) -> dict:
    """POST to Sentinel /score and return the response dict.

    On any failure (timeout, connection error, bad JSON, exception):
    returns a safe fallback with score=1.0 and logs a warning.
    """
    try:
        resp = requests.post(
            SENTINEL_URL,
            json={
                "strategy": strategy,
                "direction": direction,
                "session": session,
                "bb_width_pips": bb_width_pips,
                "atr_pips": atr_pips,
            },
            timeout=SENTINEL_TIMEOUT_S,
        )
        resp.raise_for_status()
        data = resp.json()
        data["available"] = True
        return data
    except requests.Timeout:
        logger.warning("[SENTINEL] score request timed out (%.1fs)", SENTINEL_TIMEOUT_S)
    except requests.ConnectionError:
        logger.warning("[SENTINEL] score endpoint unreachable (%s)", SENTINEL_URL)
    except Exception as e:
        logger.warning("[SENTINEL] score request failed: %s: %s", type(e).__name__, e)
    return dict(_FALLBACK)


def push_trade_outcome(trade: dict) -> bool:
    """POST a completed trade dict to Sentinel /outcome.

    Returns True on success, False on any failure. Never raises.
    Fire-and-forget — the next model rebuild will catch it from the
    local signal_log.jsonl if this call fails.
    """
    if os.getenv("SENTINEL_OUTCOME_PUSH_ENABLED", "1") != "1":
        return False
    try:
        resp = requests.post(
            SENTINEL_OUTCOME_URL,
            json=trade,
            timeout=SENTINEL_OUTCOME_TIMEOUT_S,
        )
        resp.raise_for_status()
        return True
    except requests.Timeout:
        logger.warning("[SENTINEL] outcome push timed out (%.1fs)", SENTINEL_OUTCOME_TIMEOUT_S)
    except requests.ConnectionError:
        logger.warning("[SENTINEL] outcome endpoint unreachable (%s)", SENTINEL_OUTCOME_URL)
    except Exception as e:
        logger.warning("[SENTINEL] outcome push failed: %s: %s", type(e).__name__, e)
    return False
