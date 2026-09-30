#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
levels_engine.py — Levels / Zones / No-Trade context (deterministic)

Consumes:
- Closed 5m candles (required)
- Optional H1 candles (reserved; debug only)

Produces:
- zones / targets / no-trade context for strategies
- NO trade entries/exits here (strict)

Non-negotiables:
- Deterministic: inputs -> outputs
- No I/O, no caching, no globals, no bot imports
- Prices remain in native IG units (points). NO normalization.
- Degrade gracefully (no exceptions escaping) — safe for live loop.

Snapshot Contract (stable keys/types)
-------------------------------------
LevelsSnapshot = dict[str, Any] with keys:
{
  "no_trade": bool,
  "no_trade_reason": str,
  "zones": list[dict[str, Any]],
  "no_trade_zone": list[dict[str, Any]],   # alias to match ecosystem consumers
  "targets": dict[str, float|None],
  "debug": dict[str, Any],
}

Zone object (minimal stable shape):
{
  "name": str,
  "type": "DEMAND"|"SUPPLY",
  "low": float,
  "high": float,
  "source": "SWING_5M",
}
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class LevelsConfig:
    min_candles: int = 20
    atr_period: int = 14

    # Compression gate
    compression_lookback: int = 20
    compression_mult: float = 0.8

    # Zone sizing
    zone_halfwidth_atr_mult: float = 0.5

    # Swing lookback
    swing_lookback: int = 50


def _empty_snapshot(reason: str, debug: Optional[Dict[str, Any]] = None, *, no_trade: bool = True) -> Dict[str, Any]:
    snap: Dict[str, Any] = {
        "no_trade": bool(no_trade),
        "no_trade_reason": str(reason or ""),
        "zones": [],
        "no_trade_zone": [],
        "targets": {"support": None, "resistance": None},
        "debug": debug or {},
    }
    return snap


def _as_float_series(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s, errors="coerce").astype(float)


def _standardize_df(df_5m_closed: pd.DataFrame) -> pd.DataFrame:
    """
    Light-touch standardization (deterministic, no indicator dependency):
    - Coerce OHLC to numeric
    - If time/timestamp exists, sort ascending
    """
    df = df_5m_closed.copy()

    if "time" in df.columns:
        t = pd.to_datetime(df["time"], errors="coerce", utc=True)
        df = df.assign(_time=t).dropna(subset=["_time"]).sort_values("_time").drop(columns=["_time"])
    elif "timestamp" in df.columns:
        t = pd.to_datetime(df["timestamp"], errors="coerce", utc=True)
        df = df.assign(_time=t).dropna(subset=["_time"]).sort_values("_time").drop(columns=["_time"])

    for c in ("open", "high", "low", "close"):
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")

    df = df.dropna(subset=[c for c in ("open", "high", "low", "close") if c in df.columns]).reset_index(drop=True)
    return df


def _require_ohlc_safe(df: Any) -> Tuple[bool, List[str]]:
    if df is None or not hasattr(df, "columns"):
        return False, ["open", "high", "low", "close"]
    missing = [c for c in ("open", "high", "low", "close") if c not in df.columns]
    return (len(missing) == 0), missing


def _true_range(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    h = _as_float_series(high)
    l = _as_float_series(low)
    c = _as_float_series(close)
    prev_close = c.shift(1)
    tr1 = (h - l).abs()
    tr2 = (h - prev_close).abs()
    tr3 = (l - prev_close).abs()
    return pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)


def _atr_wilder(df: pd.DataFrame, period: int) -> float:
    if len(df) < period + 1:
        return float("nan")
    tr = _true_range(df["high"], df["low"], df["close"])
    atr = tr.ewm(alpha=1.0 / float(period), adjust=False, min_periods=period).mean()
    return float(atr.iloc[-1])


def _swing_levels(df: pd.DataFrame, lookback: int) -> Tuple[Optional[float], Optional[float]]:
    if df is None or df.empty:
        return None, None
    n = min(int(lookback), int(len(df)))
    hi = float(_as_float_series(df["high"].iloc[-n:]).max())
    lo = float(_as_float_series(df["low"].iloc[-n:]).min())
    if not np.isfinite(hi) or not np.isfinite(lo):
        return None, None
    return lo, hi


def compute_levels_snapshot(
    df_5m_closed: pd.DataFrame,
    mid_price: float,
    min_candles: Optional[int] = None,
    config: Optional[LevelsConfig] = None,
    df_h1_closed: Optional[pd.DataFrame] = None,
) -> Dict[str, Any]:

    cfg = config or LevelsConfig()
    effective_min_candles = int(min_candles) if min_candles is not None else int(cfg.min_candles)

    if not isinstance(df_5m_closed, pd.DataFrame):
        return _empty_snapshot(
            "bad_input_type",
            debug={"expected": "pandas.DataFrame", "got": type(df_5m_closed).__name__},
        )

    ok_ohlc, missing = _require_ohlc_safe(df_5m_closed)
    if not ok_ohlc:
        return _empty_snapshot(
            "missing_ohlc_cols",
            debug={"missing": missing},
        )

    df = _standardize_df(df_5m_closed)

    snap: Dict[str, Any] = {
        "no_trade": False,
        "no_trade_reason": "",
        "zones": [],
        "no_trade_zone": [],
        "targets": {"support": None, "resistance": None},
        "debug": {},
    }

    snap["debug"]["rows"] = int(len(df))
    snap["debug"]["min_candles"] = int(effective_min_candles)

    if len(df) < effective_min_candles:
        snap["no_trade"] = True
        snap["no_trade_reason"] = "insufficient_5m_candles"
        return snap

    atr14 = _atr_wilder(df, period=int(cfg.atr_period))
    snap["debug"]["atr_period"] = int(cfg.atr_period)
    snap["debug"]["atr14"] = float(atr14) if np.isfinite(atr14) else None

    lb = int(cfg.compression_lookback)
    lastn = df.iloc[-lb:] if len(df) >= lb else df

    range_n = float(_as_float_series(lastn["high"]).max() - _as_float_series(lastn["low"]).min())
    snap["debug"]["compression_lookback"] = int(cfg.compression_lookback)
    snap["debug"]["compression_mult"] = float(cfg.compression_mult)
    snap["debug"][f"range{len(lastn)}"] = float(range_n)

    compression_threshold = None
    if np.isfinite(atr14) and atr14 > 0:
        compression_threshold = float(cfg.compression_mult) * float(atr14)
        snap["debug"]["compression_threshold"] = float(compression_threshold)

        if range_n < compression_threshold:
            snap["no_trade"] = True
            snap["no_trade_reason"] = f"compression_range{len(lastn)}_lt_{cfg.compression_mult}_atr{cfg.atr_period}"
            return snap

    support, resistance = _swing_levels(df, lookback=int(cfg.swing_lookback))
    snap["targets"]["support"] = float(support) if support is not None else None
    snap["targets"]["resistance"] = float(resistance) if resistance is not None else None

    zone_half = 0.0
    if np.isfinite(atr14) and atr14 > 0:
        zone_half = float(cfg.zone_halfwidth_atr_mult) * float(atr14)

    zones: List[Dict[str, Any]] = []
    if support is not None:
        zones.append(
            {
                "name": "swing_low_zone",
                "type": "DEMAND",
                "low": float(support - zone_half),
                "high": float(support + zone_half),
                "source": "SWING_5M",
            }
        )
    if resistance is not None:
        zones.append(
            {
                "name": "swing_high_zone",
                "type": "SUPPLY",
                "low": float(resistance - zone_half),
                "high": float(resistance + zone_half),
                "source": "SWING_5M",
            }
        )

    snap["zones"] = zones
    snap["no_trade_zone"] = list(zones)  # alias copy

    try:
        mp = float(mid_price)
        mp = mp if np.isfinite(mp) else None
    except Exception:
        mp = None

    snap["debug"]["mid_price_ok"] = bool(mp is not None)

    if mp is not None:
        for z in zones:
            if float(z["low"]) <= mp <= float(z["high"]):
                snap["no_trade"] = True
                snap["no_trade_reason"] = f"inside_zone:{z['name']}"
                break

    if df_h1_closed is not None:
        snap["debug"]["h1_rows"] = int(len(df_h1_closed)) if isinstance(df_h1_closed, pd.DataFrame) else 0

    return snap
