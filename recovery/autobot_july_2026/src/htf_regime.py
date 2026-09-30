"""htf_regime — Higher-timeframe regime layer (H1 / D1 / W1) + alignment.

Sits ABOVE the existing 5M regime engine and is purely additive: telemetry
only, no gating, no router integration, no strategy interaction. The 5M
regime engine (regime_engine.py) continues to run unchanged.

Outputs per classification (one row per 5M close, per active symbol):
    h1_state    — TRENDING_UP / TRENDING_DOWN / RANGE / COMPRESSION /
                  EXPANSION / EXHAUSTION
    h1_strength — 0.0..1.0 (meaningful only for TRENDING_*; None otherwise)
    d1_state    — UP / DOWN / SIDEWAYS / TURNING
    w1_state    — UP / DOWN / SIDEWAYS
    alignment   — ALIGNED_BULL / ALIGNED_BEAR / CONFLICTED / NEUTRAL
    debug       — raw inputs (BB width/percentile/slope, EMA fan, MACD)

Kill-switch: HTF_REGIME_ENABLED (default OFF). When OFF the classifier
still loads + classify()/emit() are callable, but emit() writes no row.

Telemetry: /opt/tradingbot/logs/htf_regime.jsonl, one JSON line per emit.
"""
from __future__ import annotations

import json
import logging
import math
import os
import statistics
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from indicators import bollinger_bands, ema, macd as macd_fn

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Env-tunable thresholds — all overridable at module import, safe defaults.
# ─────────────────────────────────────────────────────────────────────────────
ENABLED = str(os.getenv("HTF_REGIME_ENABLED", "0")).strip().lower() in ("1", "true", "yes")

# H1 trending fan + slope floors
H1_FAN_FLOOR_PIPS = float(os.getenv("HTF_H1_FAN_FLOOR_PIPS", "4.0"))
H1_SLOPE_FLAT_FLOOR = float(os.getenv("HTF_H1_SLOPE_FLAT_FLOOR", "0.5"))
H1_BB_PERIOD = int(float(os.getenv("HTF_H1_BB_PERIOD", "20")))
H1_BB_STD = float(os.getenv("HTF_H1_BB_STD", "2.0"))
H1_BB_PCTL_LOOKBACK = int(float(os.getenv("HTF_H1_BB_PCTL_LOOKBACK", "100")))
H1_BB_SLOPE_LOOKBACK = int(float(os.getenv("HTF_H1_BB_SLOPE_LOOKBACK", "10")))

# BB width percentiles for COMPRESSION / EXPANSION on H1
BBW_LOW_PCTL = float(os.getenv("HTF_REGIME_BBW_LOW_PCTL", "25.0"))
BBW_HIGH_PCTL = float(os.getenv("HTF_REGIME_BBW_HIGH_PCTL", "75.0"))
BBW_EXPANSION_DELTA_BARS = int(float(os.getenv("HTF_REGIME_BBW_DELTA_BARS", "5")))

# MACD cross-state detection
MACD_FAST = int(float(os.getenv("HTF_MACD_FAST", "12")))
MACD_SLOW = int(float(os.getenv("HTF_MACD_SLOW", "26")))
MACD_SIGNAL = int(float(os.getenv("HTF_MACD_SIGNAL", "9")))
MACD_JUST_CROSSED_BARS = int(float(os.getenv("HTF_MACD_JUST_CROSSED_BARS", "3")))

# Exhaustion: declining MACD histogram magnitude while price still extending
EXHAUSTION_HIST_DECLINE_BARS = int(float(os.getenv("HTF_EXHAUSTION_HIST_DECLINE_BARS", "5")))

# D1 classification
D1_UP_LOOKBACK = int(float(os.getenv("HTF_D1_UP_LOOKBACK", "5")))
D1_TURNING_BREAK_BARS = int(float(os.getenv("HTF_D1_TURNING_BREAK_BARS", "2")))
D1_EMA_PERIOD = int(float(os.getenv("HTF_D1_EMA_PERIOD", "21")))

# W1 classification (aggregated from D1 if no W1 cache exists)
W1_LOOKBACK = int(float(os.getenv("HTF_W1_LOOKBACK", "6")))
W1_EMA_PERIOD = int(float(os.getenv("HTF_W1_EMA_PERIOD", "8")))

# Telemetry path (mirrors regime_engine convention)
TELEMETRY_PATH = os.getenv("HTF_REGIME_TELEMETRY_PATH",
                           "/opt/tradingbot/logs/htf_regime.jsonl")


# ─────────────────────────────────────────────────────────────────────────────
# State labels
# ─────────────────────────────────────────────────────────────────────────────
H1_TRENDING_UP = "TRENDING_UP"
H1_TRENDING_DOWN = "TRENDING_DOWN"
H1_RANGE = "RANGE"
H1_COMPRESSION = "COMPRESSION"
H1_EXPANSION = "EXPANSION"
H1_EXHAUSTION = "EXHAUSTION"

D1_UP = "UP"
D1_DOWN = "DOWN"
D1_SIDEWAYS = "SIDEWAYS"
D1_TURNING = "TURNING"

W1_UP = "UP"
W1_DOWN = "DOWN"
W1_SIDEWAYS = "SIDEWAYS"

ALIGN_BULL = "ALIGNED_BULL"
ALIGN_BEAR = "ALIGNED_BEAR"
ALIGN_CONFLICT = "CONFLICTED"
ALIGN_NEUTRAL = "NEUTRAL"

MACD_NOT_CROSSED = "NOT_CROSSED"
MACD_ABOUT_TO_CROSS = "ABOUT_TO_CROSS"
MACD_JUST_CROSSED_UP = "JUST_CROSSED_UP"
MACD_JUST_CROSSED_DOWN = "JUST_CROSSED_DOWN"
MACD_EXTENDED_UP = "EXTENDED_UP"
MACD_EXTENDED_DOWN = "EXTENDED_DOWN"


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────
def _finite(v: Any) -> Optional[float]:
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if math.isnan(f) or math.isinf(f):
        return None
    return f


def _candles_to_df(candles: List[Dict[str, Any]]) -> pd.DataFrame:
    """Convert htf_cache candle dicts to a DataFrame with open/high/low/close
    columns + timestamp index. Returns empty DataFrame on bad input."""
    if not candles:
        return pd.DataFrame()
    try:
        df = pd.DataFrame(candles)
    except Exception:
        return pd.DataFrame()
    for c in ("open", "high", "low", "close"):
        if c not in df.columns:
            return pd.DataFrame()
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


def _pip_size(symbol: str) -> float:
    """All IG FX pairs in this codebase are 1 point = 1 pip (pair_config)."""
    try:
        from pair_config import get_ppp
        return float(get_ppp(symbol)) or 1.0
    except Exception:
        return 1.0


def _linreg_slope(values: List[float]) -> Optional[float]:
    """OLS slope of `values` vs index 0..n-1. None if <2 finite points."""
    xs, ys = [], []
    for i, v in enumerate(values):
        f = _finite(v)
        if f is not None:
            xs.append(i)
            ys.append(f)
    if len(ys) < 2:
        return None
    try:
        return float(np.polyfit(xs, ys, 1)[0])
    except Exception:
        return None


def _percentile_rank(value: float, sample: List[float]) -> Optional[float]:
    """Percentile rank of value within sample (0-100). None if sample empty."""
    pts = [v for v in sample if _finite(v) is not None]
    if not pts:
        return None
    below = sum(1 for v in pts if v < value)
    equal = sum(1 for v in pts if v == value)
    return 100.0 * (below + 0.5 * equal) / len(pts)


# ─────────────────────────────────────────────────────────────────────────────
# Candle loaders
# ─────────────────────────────────────────────────────────────────────────────
def _load_h1_candles(symbol: str) -> List[Dict[str, Any]]:
    try:
        from htf_cache import load_cached_candles
        cached = load_cached_candles(str(symbol).upper(), "H1") or {}
        cs = cached.get("candles") or []
        return cs if isinstance(cs, list) else []
    except Exception as exc:
        logger.warning("[htf_regime] H1 cache load failed for %s: %s", symbol, exc)
        return []


def _load_d1_candles(symbol: str) -> List[Dict[str, Any]]:
    try:
        from htf_cache import load_cached_candles
        cached = load_cached_candles(str(symbol).upper(), "D1") or {}
        cs = cached.get("candles") or []
        return cs if isinstance(cs, list) else []
    except Exception as exc:
        logger.warning("[htf_regime] D1 cache load failed for %s: %s", symbol, exc)
        return []


def _aggregate_w1_from_d1(d1: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Build weekly bars from a D1 candle list. Buckets by ISO week starting
    Monday. Each weekly bar = open of first D1 in week, max(high), min(low),
    close of last D1 in week, timestamp = first day of week."""
    if not d1:
        return []
    buckets: Dict[Tuple[int, int], List[Dict[str, Any]]] = {}
    for c in d1:
        ts = c.get("timestamp")
        if not ts:
            continue
        try:
            t = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        except Exception:
            continue
        iso = t.isocalendar()
        key = (iso[0], iso[1])
        buckets.setdefault(key, []).append((t, c))
    weeks: List[Dict[str, Any]] = []
    for key in sorted(buckets):
        rows = sorted(buckets[key], key=lambda r: r[0])
        first_t, first_c = rows[0]
        _, last_c = rows[-1]
        try:
            o = float(first_c["open"]); cl = float(last_c["close"])
            hi = max(float(r[1]["high"]) for r in rows)
            lo = min(float(r[1]["low"]) for r in rows)
        except (KeyError, ValueError, TypeError):
            continue
        weeks.append({
            "timeframe": "W1",
            "timestamp": first_t.isoformat(),
            "open": o, "high": hi, "low": lo, "close": cl,
            "n_daily": len(rows),
        })
    return weeks


# ─────────────────────────────────────────────────────────────────────────────
# MACD cross-state
# ─────────────────────────────────────────────────────────────────────────────
def _macd_state(macd_line: pd.Series, signal_line: pd.Series) -> Tuple[str, Dict[str, Any]]:
    """Classify MACD line vs signal line state on the most recent bar."""
    debug: Dict[str, Any] = {
        "macd_now": None, "signal_now": None, "hist_now": None,
        "diff_now": None, "diff_prev": None, "diff_slope": None,
        "bars_since_cross": None, "last_cross_dir": None,
    }
    n = min(len(macd_line), len(signal_line))
    if n < 2:
        return MACD_NOT_CROSSED, debug
    m = macd_line.dropna().reset_index(drop=True)
    s = signal_line.dropna().reset_index(drop=True)
    n = min(len(m), len(s))
    if n < 2:
        return MACD_NOT_CROSSED, debug
    m = m.iloc[-n:].reset_index(drop=True)
    s = s.iloc[-n:].reset_index(drop=True)
    diff = (m - s).tolist()
    debug["macd_now"] = float(m.iloc[-1])
    debug["signal_now"] = float(s.iloc[-1])
    debug["hist_now"] = float(diff[-1])
    debug["diff_now"] = float(diff[-1])
    debug["diff_prev"] = float(diff[-2])
    # Recent slope of (macd - signal) — convergence/divergence
    lookback = min(5, n)
    slope = _linreg_slope(diff[-lookback:])
    debug["diff_slope"] = slope

    # Walk backward for most-recent sign change
    bars_since_cross = None
    last_dir = None
    sign_now = 1 if diff[-1] > 0 else (-1 if diff[-1] < 0 else 0)
    for i in range(n - 2, -1, -1):
        sign_i = 1 if diff[i] > 0 else (-1 if diff[i] < 0 else 0)
        if sign_now != 0 and sign_i != 0 and sign_now != sign_i:
            bars_since_cross = (n - 1) - i
            last_dir = "UP" if sign_now > 0 else "DOWN"
            break
    debug["bars_since_cross"] = bars_since_cross
    debug["last_cross_dir"] = last_dir

    # Classify
    if bars_since_cross is not None:
        if bars_since_cross <= MACD_JUST_CROSSED_BARS:
            return (MACD_JUST_CROSSED_UP if last_dir == "UP" else MACD_JUST_CROSSED_DOWN), debug
        return (MACD_EXTENDED_UP if last_dir == "UP" else MACD_EXTENDED_DOWN), debug

    # No cross found in the available history.
    # ABOUT_TO_CROSS: lines converging (|diff| shrinking) AND |diff| small
    # enough that one more bar at current slope would flip the sign.
    if slope is not None and diff[-1] != 0:
        # Project one bar ahead at the linear slope.
        projected = diff[-1] + slope
        narrowing = abs(diff[-1]) < abs(diff[-2]) if len(diff) >= 2 else False
        if narrowing and ((diff[-1] > 0 and projected <= 0)
                          or (diff[-1] < 0 and projected >= 0)):
            return MACD_ABOUT_TO_CROSS, debug
    return MACD_NOT_CROSSED, debug


# ─────────────────────────────────────────────────────────────────────────────
# H1 feature extraction + classification
# ─────────────────────────────────────────────────────────────────────────────
def _compute_h1_features(candles: List[Dict[str, Any]], pip_size: float) -> Dict[str, Any]:
    df = _candles_to_df(candles)
    feat: Dict[str, Any] = {
        "n_bars": int(len(df)),
        "close": None, "bb_upper": None, "bb_lower": None, "bb_mid": None,
        "bb_width_pips": None, "bb_width_pctl": None,
        "bb_mid_slope_pips_per_bar": None,
        "ema8": None, "ema13": None, "ema21": None, "ema50": None,
        "ema_order": None, "ema_fan_pips": None, "ema8_50_pips": None,
        "macd": None, "signal": None, "hist": None,
        "macd_cross_state": MACD_NOT_CROSSED, "macd_debug": {},
        "hist_decline_bars": 0,
        "atr_pct_proxy": None,
    }
    if df.empty or len(df) < max(H1_BB_PERIOD, MACD_SLOW + MACD_SIGNAL, 50) + 2:
        return feat

    closes = df["close"]
    feat["close"] = float(closes.iloc[-1])

    # Bollinger bands on H1 closes
    bb = bollinger_bands(closes, period=H1_BB_PERIOD, std=H1_BB_STD)
    upper = bb["upper"] if "upper" in bb.columns else bb.iloc[:, 0]
    lower = bb["lower"] if "lower" in bb.columns else bb.iloc[:, 2]
    mid = bb["mid"] if "mid" in bb.columns else bb.iloc[:, 1]
    feat["bb_upper"] = float(upper.iloc[-1])
    feat["bb_lower"] = float(lower.iloc[-1])
    feat["bb_mid"] = float(mid.iloc[-1])
    feat["bb_width_pips"] = (feat["bb_upper"] - feat["bb_lower"]) / max(pip_size, 1e-9)

    # BB width percentile vs last H1_BB_PCTL_LOOKBACK bars
    width_series = (upper - lower).dropna().tolist()
    if len(width_series) >= 5:
        sample = width_series[-H1_BB_PCTL_LOOKBACK:]
        feat["bb_width_pctl"] = _percentile_rank(width_series[-1], sample)

    # Linear-regression slope of bb_mid over last H1_BB_SLOPE_LOOKBACK bars (pips/bar)
    mid_tail = mid.dropna().tolist()[-H1_BB_SLOPE_LOOKBACK:]
    slope_raw = _linreg_slope(mid_tail)
    if slope_raw is not None:
        feat["bb_mid_slope_pips_per_bar"] = slope_raw / max(pip_size, 1e-9)

    # EMA stack
    e8 = ema(closes, 8); e13 = ema(closes, 13)
    e21 = ema(closes, 21); e50 = ema(closes, 50)
    feat["ema8"] = float(e8.iloc[-1])
    feat["ema13"] = float(e13.iloc[-1])
    feat["ema21"] = float(e21.iloc[-1])
    feat["ema50"] = float(e50.iloc[-1])
    vals = [feat["ema8"], feat["ema13"], feat["ema21"], feat["ema50"]]
    if vals[0] > vals[1] > vals[2] > vals[3]:
        feat["ema_order"] = "DESC_BULL"   # ema8 highest -> bullish stack
    elif vals[0] < vals[1] < vals[2] < vals[3]:
        feat["ema_order"] = "ASC_BEAR"    # ema8 lowest  -> bearish stack
    else:
        feat["ema_order"] = "MIXED"
    feat["ema_fan_pips"] = (max(vals) - min(vals)) / max(pip_size, 1e-9)
    feat["ema8_50_pips"] = (feat["ema8"] - feat["ema50"]) / max(pip_size, 1e-9)

    # MACD
    md = macd_fn(closes, fast=MACD_FAST, slow=MACD_SLOW, signal=MACD_SIGNAL)
    mline = md["macd"] if "macd" in md.columns else md.iloc[:, 0]
    sline = md["signal"] if "signal" in md.columns else md.iloc[:, 1]
    hline = md["hist"] if "hist" in md.columns else (mline - sline)
    feat["macd"] = float(mline.iloc[-1])
    feat["signal"] = float(sline.iloc[-1])
    feat["hist"] = float(hline.iloc[-1])
    state, mdebug = _macd_state(mline, sline)
    feat["macd_cross_state"] = state
    feat["macd_debug"] = mdebug

    # Histogram decline streak (count consecutive bars where |hist| has fallen
    # from the prior bar). Used by EXHAUSTION.
    hist_tail = hline.dropna().tolist()
    decline = 0
    for i in range(len(hist_tail) - 1, 0, -1):
        if abs(hist_tail[i]) < abs(hist_tail[i - 1]):
            decline += 1
        else:
            break
    feat["hist_decline_bars"] = decline

    # Simple ATR proxy: mean of (high - low) over last 14 bars in pips.
    try:
        tr = (df["high"] - df["low"]).dropna().tail(14)
        if len(tr) >= 5:
            feat["atr_pct_proxy"] = float(tr.mean()) / max(pip_size, 1e-9)
    except Exception:
        pass

    return feat


def _classify_h1(feat: Dict[str, Any]) -> Tuple[str, Optional[float], Dict[str, Any]]:
    """Pick one of the 6 H1 states. Returns (state, strength, reason_debug)."""
    reason: Dict[str, Any] = {}
    if feat.get("n_bars", 0) < 50 or feat["close"] is None:
        reason["why"] = "insufficient_h1_history"
        return H1_RANGE, None, reason

    fan = feat["ema_fan_pips"] or 0.0
    e8_50 = feat["ema8_50_pips"] or 0.0
    slope = feat["bb_mid_slope_pips_per_bar"] or 0.0
    pctl = feat["bb_width_pctl"]
    macd_state = feat["macd_cross_state"]
    hist_now = feat["hist"] or 0.0
    decline = feat["hist_decline_bars"]

    bull_macd = (hist_now > 0 or macd_state in (MACD_JUST_CROSSED_UP, MACD_EXTENDED_UP))
    bear_macd = (hist_now < 0 or macd_state in (MACD_JUST_CROSSED_DOWN, MACD_EXTENDED_DOWN))
    bunched = abs(fan) < H1_FAN_FLOOR_PIPS
    sloped_up = slope > H1_SLOPE_FLAT_FLOOR
    sloped_dn = slope < -H1_SLOPE_FLAT_FLOOR
    flat_slope = abs(slope) < H1_SLOPE_FLAT_FLOOR

    # EXPANSION first — BB width has jumped and is now in high percentile.
    if pctl is not None and pctl > BBW_HIGH_PCTL:
        # Check that BB width has grown recently. Approximate via the BB-mid
        # slope: a flat mid with widening bands -> expansion (vol spike).
        # We don't store raw BB widths per-bar here, but high percentile is
        # itself the primary criterion; refine when we add a width series.
        reason.update(width_pctl=pctl, why="bbw_high_pctl")
        return H1_EXPANSION, None, reason

    # COMPRESSION — low BB width percentile, bunched EMAs, low vol.
    if (pctl is not None and pctl < BBW_LOW_PCTL
            and bunched and flat_slope):
        reason.update(width_pctl=pctl, fan=fan, slope=slope, why="bbw_low+bunched+flat")
        return H1_COMPRESSION, None, reason

    # TRENDING_UP — ascending stack + fan above floor + slope up + bullish MACD.
    if (feat["ema_order"] == "DESC_BULL"
            and e8_50 >= H1_FAN_FLOOR_PIPS
            and slope > H1_SLOPE_FLAT_FLOOR
            and bull_macd):
        # EXHAUSTION variant: still trending geometry but hist magnitude
        # has been declining for a stretch (early-warning divergence).
        if decline >= EXHAUSTION_HIST_DECLINE_BARS:
            reason.update(fan=fan, e8_50=e8_50, slope=slope,
                          hist_decline=decline, base="TRENDING_UP",
                          why="trending_up_with_hist_decline")
            return H1_EXHAUSTION, None, reason
        strength = _h1_strength(fan, slope, abs(hist_now))
        reason.update(fan=fan, e8_50=e8_50, slope=slope, hist=hist_now,
                      why="ascending_stack+fanned+sloped_up+bull_macd")
        return H1_TRENDING_UP, strength, reason

    # TRENDING_DOWN — mirror.
    if (feat["ema_order"] == "ASC_BEAR"
            and e8_50 <= -H1_FAN_FLOOR_PIPS
            and slope < -H1_SLOPE_FLAT_FLOOR
            and bear_macd):
        if decline >= EXHAUSTION_HIST_DECLINE_BARS:
            reason.update(fan=fan, e8_50=e8_50, slope=slope,
                          hist_decline=decline, base="TRENDING_DOWN",
                          why="trending_down_with_hist_decline")
            return H1_EXHAUSTION, None, reason
        strength = _h1_strength(fan, abs(slope), abs(hist_now))
        reason.update(fan=fan, e8_50=e8_50, slope=slope, hist=hist_now,
                      why="descending_stack+fanned+sloped_dn+bear_macd")
        return H1_TRENDING_DOWN, strength, reason

    # RANGE — bunched EMAs + flat BB slope + BB width not unusually narrow.
    if (bunched and flat_slope
            and (pctl is None or pctl >= BBW_LOW_PCTL)):
        reason.update(fan=fan, slope=slope, width_pctl=pctl,
                      why="bunched+flat_slope")
        return H1_RANGE, None, reason

    # Fallback: closer to range than to trending if criteria mostly miss.
    reason.update(fan=fan, slope=slope, width_pctl=pctl,
                  ema_order=feat["ema_order"], why="fallback")
    return H1_RANGE, None, reason


def _h1_strength(fan_pips: float, slope_abs: float, hist_abs: float) -> float:
    """Loose 0..1 strength score. Each factor 0..1, averaged."""
    fan_n = min(fan_pips / max(H1_FAN_FLOOR_PIPS * 4.0, 1e-9), 1.0)
    slope_n = min(slope_abs / max(H1_SLOPE_FLAT_FLOOR * 6.0, 1e-9), 1.0)
    hist_n = min(hist_abs / 5.0, 1.0)  # rough — hist scale varies by pair
    score = (fan_n + slope_n + hist_n) / 3.0
    return round(max(0.0, min(score, 1.0)), 4)


# ─────────────────────────────────────────────────────────────────────────────
# D1 feature extraction + classification
# ─────────────────────────────────────────────────────────────────────────────
def _compute_d1_features(candles: List[Dict[str, Any]]) -> Dict[str, Any]:
    df = _candles_to_df(candles)
    feat: Dict[str, Any] = {
        "n_bars": int(len(df)),
        "close": None, "ema": None, "ema_slope": None,
        "closes_tail": [], "highs_tail": [], "lows_tail": [],
    }
    if df.empty or len(df) < max(D1_EMA_PERIOD + 2, D1_UP_LOOKBACK + 2):
        return feat
    closes = df["close"]
    feat["close"] = float(closes.iloc[-1])
    e = ema(closes, D1_EMA_PERIOD)
    feat["ema"] = float(e.iloc[-1])
    if len(e.dropna()) >= 5:
        tail = e.dropna().tolist()[-5:]
        feat["ema_slope"] = _linreg_slope(tail)
    n_show = max(D1_UP_LOOKBACK + 1, D1_TURNING_BREAK_BARS + 3)
    feat["closes_tail"] = [float(x) for x in closes.tail(n_show).tolist()]
    feat["highs_tail"] = [float(x) for x in df["high"].tail(n_show).tolist()]
    feat["lows_tail"] = [float(x) for x in df["low"].tail(n_show).tolist()]
    return feat


def _classify_d1(feat: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
    reason: Dict[str, Any] = {}
    if feat["close"] is None or feat["ema"] is None:
        reason["why"] = "insufficient_d1_history"
        return D1_SIDEWAYS, reason

    closes = feat["closes_tail"]
    highs = feat["highs_tail"]
    lows = feat["lows_tail"]

    # TURNING — directional break of the prior structure.
    if (len(closes) >= D1_TURNING_BREAK_BARS + 2
            and len(highs) >= D1_TURNING_BREAK_BARS + 2):
        prior_hh = max(highs[:-D1_TURNING_BREAK_BARS])
        prior_ll = min(lows[:-D1_TURNING_BREAK_BARS])
        recent_lows = lows[-D1_TURNING_BREAK_BARS:]
        recent_highs = highs[-D1_TURNING_BREAK_BARS:]
        recent_close = closes[-1]
        prior_trend_up = closes[-D1_TURNING_BREAK_BARS - 1] > closes[0]
        prior_trend_down = closes[-D1_TURNING_BREAK_BARS - 1] < closes[0]
        if prior_trend_up and min(recent_lows) < prior_ll and recent_close < closes[-D1_TURNING_BREAK_BARS - 1]:
            reason.update(why="up_then_lower_low+lower_close",
                          prior_hh=prior_hh, prior_ll=prior_ll, close=recent_close)
            return D1_TURNING, reason
        if prior_trend_down and max(recent_highs) > prior_hh and recent_close > closes[-D1_TURNING_BREAK_BARS - 1]:
            reason.update(why="down_then_higher_high+higher_close",
                          prior_hh=prior_hh, prior_ll=prior_ll, close=recent_close)
            return D1_TURNING, reason

    # UP — recent closes higher AND close > EMA with rising slope.
    if len(closes) >= D1_UP_LOOKBACK + 1:
        recent = closes[-D1_UP_LOOKBACK - 1:]
        ups = sum(1 for i in range(1, len(recent)) if recent[i] > recent[i - 1])
        downs = sum(1 for i in range(1, len(recent)) if recent[i] < recent[i - 1])
        ema_up = feat["ema_slope"] is not None and feat["ema_slope"] > 0
        if (ups >= max(3, int(D1_UP_LOOKBACK * 0.6))
                or (feat["close"] > feat["ema"] and ema_up)):
            reason.update(why="rising_closes_or_above_ema_rising",
                          ups=ups, downs=downs, close=feat["close"],
                          ema=feat["ema"], ema_slope=feat["ema_slope"])
            return D1_UP, reason
        if (downs >= max(3, int(D1_UP_LOOKBACK * 0.6))
                or (feat["close"] < feat["ema"] and feat["ema_slope"] is not None
                    and feat["ema_slope"] < 0)):
            reason.update(why="falling_closes_or_below_ema_falling",
                          ups=ups, downs=downs, close=feat["close"],
                          ema=feat["ema"], ema_slope=feat["ema_slope"])
            return D1_DOWN, reason

    reason.update(why="no_clear_direction",
                  close=feat["close"], ema=feat["ema"],
                  ema_slope=feat["ema_slope"])
    return D1_SIDEWAYS, reason


# ─────────────────────────────────────────────────────────────────────────────
# W1 feature extraction + classification
# ─────────────────────────────────────────────────────────────────────────────
def _compute_w1_features(candles: List[Dict[str, Any]]) -> Dict[str, Any]:
    df = _candles_to_df(candles)
    feat: Dict[str, Any] = {
        "n_bars": int(len(df)),
        "close": None, "ema": None,
        "closes_tail": [],
    }
    if df.empty or len(df) < max(W1_EMA_PERIOD + 1, W1_LOOKBACK):
        return feat
    closes = df["close"]
    feat["close"] = float(closes.iloc[-1])
    e = ema(closes, W1_EMA_PERIOD)
    feat["ema"] = float(e.iloc[-1])
    feat["closes_tail"] = [float(x) for x in closes.tail(W1_LOOKBACK).tolist()]
    return feat


def _classify_w1(feat: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
    reason: Dict[str, Any] = {}
    if feat["close"] is None or feat["ema"] is None:
        reason["why"] = "insufficient_w1_history"
        return W1_SIDEWAYS, reason
    closes = feat["closes_tail"]
    if len(closes) < 3:
        reason["why"] = "too_few_weekly_bars"
        return W1_SIDEWAYS, reason
    ups = sum(1 for i in range(1, len(closes)) if closes[i] > closes[i - 1])
    downs = sum(1 for i in range(1, len(closes)) if closes[i] < closes[i - 1])
    above_ema = feat["close"] > feat["ema"]
    if ups >= max(3, int(len(closes) * 0.6)) or (above_ema and ups > downs):
        reason.update(why="weekly_closes_rising_or_above_ema", ups=ups, downs=downs)
        return W1_UP, reason
    if downs >= max(3, int(len(closes) * 0.6)) or ((not above_ema) and downs > ups):
        reason.update(why="weekly_closes_falling_or_below_ema", ups=ups, downs=downs)
        return W1_DOWN, reason
    reason.update(why="no_clear_weekly_direction", ups=ups, downs=downs)
    return W1_SIDEWAYS, reason


# ─────────────────────────────────────────────────────────────────────────────
# Alignment
# ─────────────────────────────────────────────────────────────────────────────
def _compute_alignment(h1_state: str, d1_state: str, w1_state: str,
                       h1_debug: Dict[str, Any]) -> str:
    h1_dir_up = h1_state in (H1_TRENDING_UP,) or (
        h1_state == H1_EXHAUSTION and h1_debug.get("base") == "TRENDING_UP")
    h1_dir_dn = h1_state in (H1_TRENDING_DOWN,) or (
        h1_state == H1_EXHAUSTION and h1_debug.get("base") == "TRENDING_DOWN")
    # EXPANSION can be either side — read direction from bb slope sign captured
    # in debug.
    if h1_state == H1_EXPANSION:
        # use BB mid slope sign if present
        slope = h1_debug.get("slope")
        if slope is not None and slope > 0:
            h1_dir_up = True
        elif slope is not None and slope < 0:
            h1_dir_dn = True

    if w1_state == W1_UP and d1_state == D1_UP and h1_dir_up:
        return ALIGN_BULL
    if w1_state == W1_DOWN and d1_state == D1_DOWN and h1_dir_dn:
        return ALIGN_BEAR
    if (w1_state == W1_UP and d1_state == D1_DOWN) or \
       (w1_state == W1_DOWN and d1_state == D1_UP):
        return ALIGN_CONFLICT
    if d1_state == D1_UP and h1_dir_dn:
        return ALIGN_CONFLICT
    if d1_state == D1_DOWN and h1_dir_up:
        return ALIGN_CONFLICT
    return ALIGN_NEUTRAL


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────
def classify(symbol: str) -> Dict[str, Any]:
    """Run the H1 / D1 / W1 classifiers + alignment. Pure: no telemetry write.

    Returns a dict with output fields + debug; safe to call regardless of the
    HTF_REGIME_ENABLED kill-switch (the switch only gates telemetry emission).
    """
    sym = str(symbol).upper()
    pip_size = _pip_size(sym)

    h1_candles = _load_h1_candles(sym)
    d1_candles = _load_d1_candles(sym)
    w1_candles = _aggregate_w1_from_d1(d1_candles)

    h1_feat = _compute_h1_features(h1_candles, pip_size)
    h1_state, h1_strength, h1_reason = _classify_h1(h1_feat)

    d1_feat = _compute_d1_features(d1_candles)
    d1_state, d1_reason = _classify_d1(d1_feat)

    w1_feat = _compute_w1_features(w1_candles)
    w1_state, w1_reason = _classify_w1(w1_feat)

    alignment = _compute_alignment(h1_state, d1_state, w1_state, h1_reason)

    return {
        "symbol": sym,
        "h1_state": h1_state,
        "h1_strength": h1_strength,
        "d1_state": d1_state,
        "w1_state": w1_state,
        "alignment": alignment,
        "debug": {
            "pip_size": pip_size,
            "h1_features": h1_feat,
            "h1_reason": h1_reason,
            "d1_features": d1_feat,
            "d1_reason": d1_reason,
            "w1_features": w1_feat,
            "w1_reason": w1_reason,
            "thresholds": {
                "H1_FAN_FLOOR_PIPS": H1_FAN_FLOOR_PIPS,
                "H1_SLOPE_FLAT_FLOOR": H1_SLOPE_FLAT_FLOOR,
                "BBW_LOW_PCTL": BBW_LOW_PCTL,
                "BBW_HIGH_PCTL": BBW_HIGH_PCTL,
                "EXHAUSTION_HIST_DECLINE_BARS": EXHAUSTION_HIST_DECLINE_BARS,
                "D1_UP_LOOKBACK": D1_UP_LOOKBACK,
                "D1_TURNING_BREAK_BARS": D1_TURNING_BREAK_BARS,
                "W1_LOOKBACK": W1_LOOKBACK,
                "MACD_JUST_CROSSED_BARS": MACD_JUST_CROSSED_BARS,
            },
        },
    }


def _telemetry_record(result: Dict[str, Any], bar_ts: Optional[str]) -> Dict[str, Any]:
    return {
        "timestamp": bar_ts or datetime.now(timezone.utc).isoformat(),
        "symbol": result["symbol"],
        "h1_state": result["h1_state"],
        "h1_strength": result["h1_strength"],
        "d1_state": result["d1_state"],
        "w1_state": result["w1_state"],
        "alignment": result["alignment"],
        "debug": result["debug"],
    }


def emit(symbol: str, bar_ts: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Live entry point: classify + append one JSONL row. No-op (returns
    classification but writes nothing) when HTF_REGIME_ENABLED is OFF."""
    result = classify(symbol)
    if not ENABLED:
        return result
    try:
        rec = _telemetry_record(result, bar_ts)
        _dir = os.path.dirname(TELEMETRY_PATH)
        if _dir:
            os.makedirs(_dir, exist_ok=True)
        with open(TELEMETRY_PATH, "a") as fh:
            fh.write(json.dumps(rec, default=str) + "\n")
    except Exception as exc:
        logger.warning("[htf_regime] telemetry write failed (%s): %s",
                       TELEMETRY_PATH, exc)
    return result


def startup_banner() -> str:
    """One-line banner suitable for logger.info at autobot startup."""
    return (
        f"[HTF-REGIME] enabled={ENABLED} "
        f"H1_FAN_FLOOR={H1_FAN_FLOOR_PIPS}p H1_SLOPE_FLOOR={H1_SLOPE_FLAT_FLOOR}p/bar "
        f"BBW_LOW_PCTL={BBW_LOW_PCTL} BBW_HIGH_PCTL={BBW_HIGH_PCTL} "
        f"EXHAUSTION_HIST_DECLINE_BARS={EXHAUSTION_HIST_DECLINE_BARS} "
        f"D1_UP_LOOKBACK={D1_UP_LOOKBACK} D1_TURNING_BREAK_BARS={D1_TURNING_BREAK_BARS} "
        f"W1_LOOKBACK={W1_LOOKBACK} MACD_JUST_CROSSED_BARS={MACD_JUST_CROSSED_BARS} "
        f"telemetry={TELEMETRY_PATH}"
    )
