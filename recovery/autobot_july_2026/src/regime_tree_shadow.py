# -*- coding: utf-8 -*-
"""
regime_tree_shadow.py — Composite regime tree (ER/CX/BB-width/H1-sign).

SHADOW ONLY — computes on every 5M close, logs tree label + features +
the live H1 engine label side by side. Drives NO strategy, gate, or
decision. The log is write-only Sentinel feedstock + operator comparison.

Kill-switch: REGIME_TREE_SHADOW_ENABLED (default "1" = logging on).
Flag off = doesn't compute, doesn't log.

Tree (first-match-wins, six labels):
  1. bb_w_pips < 10  AND er20 < 0.15             -> COMPRESSION
  2. er20 >= 0.30    AND cx20 <= 2 AND h1_sign!=0 -> STRONG_TREND_<sign>
  3. er20 >= 0.20    AND cx20 <= 4 AND h1_sign!=0 -> TREND_FORMING_<sign>
  4. er20 < 0.20     AND cx20 >= 5                -> RANGE_ROTATION
  5. bb_w_pips >= 35  AND er20 < 0.20             -> VOLATILITY_EXPANSION
  6. otherwise                                    -> CHOP

Dwell-time: raw label must hold 2 consecutive 5M bars to become emitted.
"""

import json
import logging
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np

logger = logging.getLogger(__name__)

# ── Configuration ────────────────────────────────────────────────────────────

_SHADOW_LOG = Path("/opt/tradingbot/logs/regime_tree_shadow.jsonl")

_ENABLED_KEY = "REGIME_TREE_SHADOW_ENABLED"
_ENABLED_DEFAULT = "1"

PIP_SIZE = 1.0  # IG GBPUSD: 1 price-point = 1 pip


def _is_enabled() -> bool:
    return (os.getenv(_ENABLED_KEY, _ENABLED_DEFAULT) or "").strip() in ("1", "true", "yes")


# ── Per-symbol dwell state (module-level, survives across calls) ─────────

class _DwellState:
    __slots__ = ("emitted", "pending", "count")

    def __init__(self):
        self.emitted: Optional[str] = None
        self.pending: Optional[str] = None
        self.count: int = 0

    def step(self, raw: str) -> str:
        """Apply 2-bar dwell. Returns the dwelled (emitted) label."""
        if self.emitted is None:
            self.emitted = raw
            self.pending = raw
            self.count = 1
            return raw

        if raw == self.pending:
            self.count += 1
        else:
            self.pending = raw
            self.count = 1

        if self.count >= 2 and self.pending != self.emitted:
            self.emitted = self.pending

        return self.emitted


_DWELL: Dict[str, _DwellState] = {}


def _dwell_for(symbol: str) -> _DwellState:
    s = symbol.upper()
    if s not in _DWELL:
        _DWELL[s] = _DwellState()
    return _DWELL[s]


# ── Feature computation ─────────────────────────────────────────────────────

def _efficiency_ratio(closes: List[float], n: int = 20) -> float:
    """Kaufman ER: |net|/sum(|bar-to-bar|). 1=trend, 0=chop."""
    if len(closes) < n + 1:
        return float("nan")
    w = closes[-(n + 1):]
    net = abs(w[-1] - w[0])
    path = sum(abs(w[i] - w[i - 1]) for i in range(1, len(w)))
    if path <= 0:
        return float("nan")
    return net / path


def _mid_crossings(closes: List[float], n: int = 20) -> int:
    """Count zero-crossings of (close - SMA) over last n bars."""
    if len(closes) < n + 1:
        return -1
    w = closes[-n:]
    mid = sum(w) / float(n)
    signs = [1 if c > mid else (-1 if c < mid else 0) for c in w]
    cx = 0
    last = 0
    for s in signs:
        if s == 0:
            continue
        if last != 0 and s != last:
            cx += 1
        last = s
    return cx


def _bb_width_pips(closes: List[float], n: int = 20) -> float:
    """BB(20,2) width in pips. Population stdev, matching codebase convention."""
    if len(closes) < n:
        return float("nan")
    w = closes[-n:]
    mid = sum(w) / float(n)
    var = sum((c - mid) ** 2 for c in w) / float(n)
    sd = math.sqrt(var)
    return (4.0 * sd) / PIP_SIZE  # width = upper - lower = 4*sd


# ── Tree classification ─────────────────────────────────────────────────────

def _classify(bb_w: float, er: float, cx: int, h1_sign: int) -> str:
    """Six-label first-match-wins tree."""
    if bb_w < 10 and er < 0.15:
        return "COMPRESSION"
    if er >= 0.30 and cx <= 2 and h1_sign != 0:
        return "STRONG_TREND_UP" if h1_sign > 0 else "STRONG_TREND_DOWN"
    if er >= 0.20 and cx <= 4 and h1_sign != 0:
        return "TREND_FORMING_UP" if h1_sign > 0 else "TREND_FORMING_DOWN"
    if er < 0.20 and cx >= 5:
        return "RANGE_ROTATION"
    if bb_w >= 35 and er < 0.20:
        return "VOLATILITY_EXPANSION"
    return "CHOP"


# ── h1_sign derivation (NaN→0 by construction) ──────────────────────────────

def _h1_sign(hist_value) -> int:
    """sign(hist), NaN/None → 0. A missing H1 bar can NEVER produce a trend label."""
    if hist_value is None:
        return 0
    try:
        h = float(hist_value)
    except (TypeError, ValueError):
        return 0
    if math.isnan(h):
        return 0
    if h > 0:
        return 1
    if h < 0:
        return -1
    return 0


# ── Shadow log writer ────────────────────────────────────────────────────────

def _write_row(row: Dict[str, Any]) -> None:
    """Append one JSON row to the shadow log. Best-effort, never raises."""
    try:
        _SHADOW_LOG.parent.mkdir(parents=True, exist_ok=True)
        with _SHADOW_LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, default=str) + "\n")
    except Exception:
        pass


# ── Public entry point (called from 5M close callback) ──────────────────────

def on_5m_close(symbol: str, df_5m, bar_ts: Optional[str] = None) -> None:
    """Compute the composite regime tree and log the shadow row.

    Parameters
    ----------
    symbol : str
        Trading pair (e.g. "GBPUSD").
    df_5m : pd.DataFrame
        The 5M candle buffer (must have 'close' column, >=21 rows).
    bar_ts : str, optional
        ISO timestamp of the just-closed bar.
    """
    if not _is_enabled():
        return

    sym = str(symbol or "").upper()
    if sym != "GBPUSD":
        return  # tree is GBPUSD-only for now

    try:
        import pandas as pd
    except ImportError:
        return

    if df_5m is None or not isinstance(df_5m, pd.DataFrame) or len(df_5m) < 21:
        return

    # ── Extract closes ───────────────────────────────────────────────
    try:
        closes = df_5m["close"].astype(float).tolist()
    except Exception:
        return

    close_price = closes[-1]

    # ── Compute features ─────────────────────────────────────────────
    bb_w = _bb_width_pips(closes)
    er = _efficiency_ratio(closes, 20)
    cx = _mid_crossings(closes, 20)

    # ── H1 sign from live regime engine (consume, don't recompute) ───
    h1_hist = None
    engine_label = None
    try:
        import regime_engine as _re
        result = _re.latest_result(sym)
        if isinstance(result, dict):
            h1_hist = result.get("h1_macd_hist")
            engine_label = result.get("winning_regime")
    except Exception as exc:
        logger.debug("[REGIME_TREE_SHADOW] regime_engine.latest_result failed: %s", exc)

    h1s = _h1_sign(h1_hist)

    # ── Guard: skip if features are invalid ──────────────────────────
    if math.isnan(bb_w) or math.isnan(er) or cx < 0:
        return

    # ── Classify ─────────────────────────────────────────────────────
    raw_label = _classify(bb_w, er, cx, h1s)
    dwelled_label = _dwell_for(sym).step(raw_label)

    # ── Write shadow row ─────────────────────────────────────────────
    row = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "bar_ts": bar_ts,
        "symbol": sym,
        "close": round(close_price, 2),
        "raw_label": raw_label,
        "dwelled_label": dwelled_label,
        "bb_w_pips": round(bb_w, 2),
        "er20": round(er, 4),
        "cx20": cx,
        "h1_macd_hist": round(h1_hist, 6) if h1_hist is not None else None,
        "h1_sign": h1s,
        "engine_label": engine_label,
    }
    _write_row(row)


def startup_banner() -> str:
    """One-line banner for registration log."""
    return (f"[REGIME_TREE_SHADOW] enabled={_is_enabled()} "
            f"log={_SHADOW_LOG} flag={_ENABLED_KEY}")
