"""
pair_config — Shared pair configuration for all strategies and modules.

Single source of truth for points-per-pip, minimum SL, and helper functions.
Import from here instead of defining local copies.
"""
import os
from typing import Dict


# ---------------------------------------------------------------------------
# Supported pairs
# ---------------------------------------------------------------------------
PAIRS = ("GBPUSD", "EURUSD", "USDJPY", "USDCAD")

# ---------------------------------------------------------------------------
# Points-per-pip: all IG spread-bet FX pairs are 1 point = 1 pip.
# ---------------------------------------------------------------------------
POINTS_PER_PIP: Dict[str, float] = {
    "GBPUSD": 1.0, "EURUSD": 1.0, "USDJPY": 1.0, "USDCAD": 1.0, "GBPJPY": 1.0,
}
DEFAULT_PPP = 1.0


def get_ppp(epic_or_symbol: str) -> float:
    """Return IG points-per-pip for an epic or symbol string."""
    key = epic_or_symbol.upper()
    if key in POINTS_PER_PIP:
        return POINTS_PER_PIP[key]
    for sym, val in POINTS_PER_PIP.items():
        if sym in key:
            return val
    return DEFAULT_PPP


# ---------------------------------------------------------------------------
# Per-pair minimum SL floors (pips), env-overridable.
# ---------------------------------------------------------------------------
MIN_SL_PIPS: Dict[str, float] = {}
for _p in PAIRS:
    _e = os.getenv(f"{_p}_MIN_SL_PIPS")
    if _e is not None:
        MIN_SL_PIPS[_p] = float(_e)
MIN_SL_PIPS.setdefault("GBPUSD", 12.0)
MIN_SL_PIPS.setdefault("EURUSD", 10.0)
MIN_SL_PIPS.setdefault("USDJPY", 15.0)
MIN_SL_PIPS.setdefault("USDCAD", 10.0)
MIN_SL_PIPS.setdefault("GBPJPY", 12.0)


def pair_from_epic(epic: str) -> str:
    """Extract pair name from IG epic, e.g. 'CS.D.USDJPY.TODAY.IP' -> 'USDJPY'."""
    parts = epic.split(".")
    return parts[2] if len(parts) >= 3 else epic.upper()


# ---------------------------------------------------------------------------
# MACD histogram extraction — single implementation for all consumers.
# ---------------------------------------------------------------------------
_MACD_FAST = int(float(os.getenv("MACD_FAST", "35") or 35))
_MACD_SLOW = int(float(os.getenv("MACD_SLOW", "45") or 45))
_MACD_SIGNAL = int(float(os.getenv("MACD_SIGNAL", "30") or 30))

# All known column names for MACD histogram across the codebase
_MACD_HIST_KEYS = [
    f"MACD_HIST_{_MACD_FAST}_{_MACD_SLOW}_{_MACD_SIGNAL}",
    "MACD_HIST",
    "macd_hist",
    "MACDH",
    "macdh",
]


def _safe_float(v, default=None):
    if v is None:
        return default
    try:
        f = float(v)
        import math
        return f if math.isfinite(f) else default
    except (ValueError, TypeError):
        return default


def pick_macd_hist(row_or_dict) -> float | None:
    """Extract MACD histogram from a dict-like row (DataFrame row, dict, or Series).

    Searches all known column name variants. Returns float or None.
    """
    if row_or_dict is None:
        return None

    # Dict path (strategy_logic candle indicators)
    if isinstance(row_or_dict, dict):
        for k in _MACD_HIST_KEYS:
            v = row_or_dict.get(k)
            fv = _safe_float(v)
            if fv is not None:
                return fv
        # Prefix search for unexpected naming
        for k, val in row_or_dict.items():
            if isinstance(k, str) and k.startswith("MACD_HIST_"):
                fv = _safe_float(val)
                if fv is not None:
                    return fv
        return None

    # DataFrame row / Series path (has .get or .index)
    if hasattr(row_or_dict, "get"):
        for k in _MACD_HIST_KEYS:
            try:
                v = row_or_dict.get(k)
            except Exception:
                v = None
            fv = _safe_float(v)
            if fv is not None:
                return fv

    if hasattr(row_or_dict, "index"):
        for col in row_or_dict.index:
            if str(col).startswith("MACD_HIST"):
                fv = _safe_float(row_or_dict[col])
                if fv is not None:
                    return fv

    return None


def pick_macd_hist_pair(df) -> tuple:
    """Extract (current, previous) MACD histogram from last 2 rows of a DataFrame."""
    if df is None or len(df) < 2:
        return None, None
    try:
        return pick_macd_hist(df.iloc[-1]), pick_macd_hist(df.iloc[-2])
    except Exception:
        return None, None
