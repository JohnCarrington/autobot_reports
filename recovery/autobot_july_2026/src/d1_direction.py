"""Deterministic 9-check D1 direction scoring.

Single source of truth for the briefing's `daily_bias` field and the
`d1_veto` trade gate. Bug 1 of `docs/briefing_producer_audit_2026-05-11.md`.

The 9 checks (each contributing +1 / 0 / -1 to the score):
  1. EMA stack order            (8 > 13 > 21 > 50)
  2. EMA fan width              (|ema8 - ema50| > pair_minimum_fan_pips)
  3. EMA-8 slope over 5 bars    (delta > pair_minimum_slope_pips)
  4. MACD histogram sign
  5. MACD histogram direction   (strictly rising/falling over 3 bars)
  6. Price vs EMA-50 + ATR buffer
  7. Last 3 closes same side of EMA-50
  8. Higher highs + higher lows (now vs t-5)
  9. Close direction over 5 bars (3+ of 5 higher/lower than predecessor)

Score >= +6 → strong BULL  | <= -6 → strong BEAR
Score >= +4 → moderate BULL | <= -4 → moderate BEAR
-3..+3 → NEUTRAL

Cache units: HTF cache stores prices as rate × 10000 (4-dp pairs) or
rate × 100 (JPY pairs). `pair_config.POINTS_PER_PIP` is 1.0 for every
pair, so 1 pip == 1 cache unit and thresholds in the YAML are in pips
without per-pair conversion.
"""
from __future__ import annotations

import json
import logging
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

CONFIG_PATH = Path("/opt/tradingbot/config/d1_direction.yaml")
HTF_CACHE_DIR = Path("/opt/tradingbot/cache/htf")
STALE_HOURS = 48.0

MIN_CANDLES = 50
SLOPE_LOOKBACK = 5
RANGE_LOOKBACK = 5
CONSEC_CLOSES = 3
HIST_TREND_BARS = 3
EMA_PERIODS = (8, 13, 21, 50)
ATR_PERIOD = 14

_DEFAULTS = {
    "pair_minimum_fan_pips": 30.0,
    "pair_minimum_slope_pips": 15.0,
    "atr_buffer_multiplier": 0.3,
    "macd_fast": 12,
    "macd_slow": 26,
    "macd_signal": 9,
}


# ─────────────────────────────────────────────────────────────────────────────
# Tiny flat-YAML parser (avoids adding PyYAML as a dependency)
# ─────────────────────────────────────────────────────────────────────────────

def _parse_yaml(text: str) -> Dict[str, Any]:
    """Two-level "key: value" with 2-space indents — sufficient for our schema."""
    root: Dict[str, Any] = {}
    stack: List[Tuple[int, Dict[str, Any]]] = [(0, root)]
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip(" "))
        while stack and indent < stack[-1][0]:
            stack.pop()
        if not stack:
            stack = [(0, root)]
        parent = stack[-1][1]
        if ":" not in line:
            continue
        key, _, value = line.lstrip().partition(":")
        key = key.strip()
        value = value.strip()
        if not value:
            child: Dict[str, Any] = {}
            parent[key] = child
            stack.append((indent + 2, child))
            continue
        try:
            parent[key] = float(value) if "." in value else int(value)
        except ValueError:
            parent[key] = value.strip('"').strip("'")
    return root


def load_config(path: Optional[Path] = None) -> Dict[str, Any]:
    """Load the YAML config; missing/unparseable falls back silently to defaults."""
    p = Path(path) if path else CONFIG_PATH
    if not p.exists():
        return {"defaults": dict(_DEFAULTS), "pairs": {}}
    try:
        parsed = _parse_yaml(p.read_text())
    except Exception as exc:
        logger.warning("[d1_direction] config parse failed (%s) — using defaults", exc)
        return {"defaults": dict(_DEFAULTS), "pairs": {}}
    defaults = dict(_DEFAULTS)
    defaults.update(parsed.get("defaults") or {})
    pairs = parsed.get("pairs") or {}
    return {"defaults": defaults, "pairs": pairs}


def _pair_thresholds(pair: str, config: Optional[Dict[str, Any]]) -> Dict[str, float]:
    cfg = config or load_config()
    out = dict(cfg.get("defaults") or _DEFAULTS)
    overrides = (cfg.get("pairs") or {}).get(pair.upper()) or {}
    out.update(overrides)
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Indicators
# ─────────────────────────────────────────────────────────────────────────────

def _ema_series(values: List[float], period: int) -> List[Optional[float]]:
    """Return EMA aligned to input length. Pre-warmup positions are None."""
    if period <= 0 or not values:
        return [None] * len(values)
    out: List[Optional[float]] = [None] * len(values)
    if len(values) < period:
        return out
    seed = sum(values[:period]) / period
    out[period - 1] = seed
    k = 2.0 / (period + 1)
    e = seed
    for i in range(period, len(values)):
        e = e + k * (values[i] - e)
        out[i] = e
    return out


def _macd_histogram_series(
    closes: List[float], fast: int, slow: int, signal: int,
) -> List[Optional[float]]:
    """MACD histogram aligned to closes length. None until fully warmed up."""
    n = len(closes)
    out: List[Optional[float]] = [None] * n
    ef = _ema_series(closes, fast)
    es = _ema_series(closes, slow)
    macd_line: List[Optional[float]] = [
        (ef[i] - es[i]) if (ef[i] is not None and es[i] is not None) else None
        for i in range(n)
    ]
    first_valid = next((i for i, v in enumerate(macd_line) if v is not None), None)
    if first_valid is None or n - first_valid < signal:
        return out
    macd_valid = [v for v in macd_line[first_valid:] if v is not None]
    sig_series = _ema_series(macd_valid, signal)
    for offset, sv in enumerate(sig_series):
        idx = first_valid + offset
        if sv is not None and macd_line[idx] is not None:
            out[idx] = macd_line[idx] - sv
    return out


def _atr(candles: List[Dict[str, Any]], period: int = ATR_PERIOD) -> Optional[float]:
    """Wilder ATR over `period` D1 bars; needs `period + 1` candles."""
    if len(candles) < period + 1:
        return None
    trs: List[float] = []
    prev_close = float(candles[0]["close"])
    for c in candles[1:]:
        hi = float(c["high"])
        lo = float(c["low"])
        cl = float(c["close"])
        tr = max(hi - lo, abs(hi - prev_close), abs(lo - prev_close))
        trs.append(tr)
        prev_close = cl
    if len(trs) < period:
        return None
    atr = sum(trs[:period]) / period
    for tr in trs[period:]:
        atr = (atr * (period - 1) + tr) / period
    return atr


def compute_indicators_from_candles(
    d1_candles: List[Dict[str, Any]],
    config: Optional[Dict[str, Any]] = None,
) -> Tuple[Dict[int, List[Optional[float]]], Dict[str, List[Optional[float]]], Optional[float]]:
    """Derive EMA series, MACD histogram series, and current ATR from raw D1 candles."""
    cfg = config or load_config()
    defaults = cfg.get("defaults") or _DEFAULTS
    closes = [float(c["close"]) for c in d1_candles]
    emas = {p: _ema_series(closes, p) for p in EMA_PERIODS}
    macd_hist = _macd_histogram_series(
        closes,
        fast=int(defaults.get("macd_fast", 12)),
        slow=int(defaults.get("macd_slow", 26)),
        signal=int(defaults.get("macd_signal", 9)),
    )
    atr_val = _atr(d1_candles, ATR_PERIOD)
    return emas, {"histogram": macd_hist}, atr_val


# ─────────────────────────────────────────────────────────────────────────────
# 9 checks
# ─────────────────────────────────────────────────────────────────────────────

def _verdict_value(v: Optional[Any]) -> Optional[float]:
    if v is None:
        return None
    try:
        f = float(v)
        return f if math.isfinite(f) else None
    except (TypeError, ValueError):
        return None


def _ck_ema_stack(emas: Dict[int, List[Optional[float]]]) -> Tuple[str, Any]:
    last = {p: emas[p][-1] for p in EMA_PERIODS if emas.get(p)}
    if any(v is None for v in last.values()) or len(last) < 4:
        return "NEUTRAL", {"reason": "missing_ema"}
    e8, e13, e21, e50 = last[8], last[13], last[21], last[50]
    if e8 > e13 > e21 > e50:
        return "BULL", {"ema_8": e8, "ema_13": e13, "ema_21": e21, "ema_50": e50}
    if e8 < e13 < e21 < e50:
        return "BEAR", {"ema_8": e8, "ema_13": e13, "ema_21": e21, "ema_50": e50}
    return "NEUTRAL", {"ema_8": e8, "ema_13": e13, "ema_21": e21, "ema_50": e50}


def _ck_ema_fan(emas: Dict[int, List[Optional[float]]], min_fan: float) -> Tuple[str, Any]:
    e8 = emas[8][-1] if emas.get(8) else None
    e50 = emas[50][-1] if emas.get(50) else None
    if e8 is None or e50 is None:
        return "NEUTRAL", {"reason": "missing_ema"}
    fan = e8 - e50
    if fan > min_fan:
        return "BULL", {"fan_pips": round(fan, 2)}
    if -fan > min_fan:
        return "BEAR", {"fan_pips": round(fan, 2)}
    return "NEUTRAL", {"fan_pips": round(fan, 2)}


def _ck_ema8_slope(emas: Dict[int, List[Optional[float]]], min_slope: float) -> Tuple[str, Any]:
    series = emas.get(8) or []
    if len(series) < SLOPE_LOOKBACK + 1:
        return "NEUTRAL", {"reason": "insufficient_history"}
    now_v = series[-1]
    prev_v = series[-1 - SLOPE_LOOKBACK]
    if now_v is None or prev_v is None:
        return "NEUTRAL", {"reason": "missing_ema"}
    delta = now_v - prev_v
    if delta > min_slope:
        return "BULL", {"slope_pips": round(delta, 2)}
    if -delta > min_slope:
        return "BEAR", {"slope_pips": round(delta, 2)}
    return "NEUTRAL", {"slope_pips": round(delta, 2)}


def _ck_macd_sign(hist_series: List[Optional[float]]) -> Tuple[str, Any]:
    if not hist_series or hist_series[-1] is None:
        return "NEUTRAL", {"reason": "missing_macd"}
    h = hist_series[-1]
    if h > 0:
        return "BULL", {"histogram": round(h, 6)}
    if h < 0:
        return "BEAR", {"histogram": round(h, 6)}
    return "NEUTRAL", {"histogram": 0.0}


def _ck_macd_trend(hist_series: List[Optional[float]]) -> Tuple[str, Any]:
    if len(hist_series) < HIST_TREND_BARS:
        return "NEUTRAL", {"reason": "insufficient_history"}
    tail = hist_series[-HIST_TREND_BARS:]
    if any(v is None for v in tail):
        return "NEUTRAL", {"reason": "missing_macd"}
    if all(tail[i] < tail[i + 1] for i in range(HIST_TREND_BARS - 1)):
        return "BULL", {"tail": [round(v, 6) for v in tail]}
    if all(tail[i] > tail[i + 1] for i in range(HIST_TREND_BARS - 1)):
        return "BEAR", {"tail": [round(v, 6) for v in tail]}
    return "NEUTRAL", {"tail": [round(v, 6) for v in tail]}


def _ck_price_vs_ema50(
    candles: List[Dict[str, Any]],
    emas: Dict[int, List[Optional[float]]],
    atr_d1: Optional[float],
    buf_mult: float,
) -> Tuple[str, Any]:
    if not candles or not emas.get(50) or emas[50][-1] is None or atr_d1 is None:
        return "NEUTRAL", {"reason": "missing_inputs"}
    close = float(candles[-1]["close"])
    e50 = emas[50][-1]
    buf = buf_mult * atr_d1
    if close > e50 + buf:
        return "BULL", {"close": close, "ema_50": e50, "buf": round(buf, 2)}
    if close < e50 - buf:
        return "BEAR", {"close": close, "ema_50": e50, "buf": round(buf, 2)}
    return "NEUTRAL", {"close": close, "ema_50": e50, "buf": round(buf, 2)}


def _ck_consec_closes_vs_ema50(
    candles: List[Dict[str, Any]],
    emas: Dict[int, List[Optional[float]]],
) -> Tuple[str, Any]:
    series = emas.get(50) or []
    if len(candles) < CONSEC_CLOSES or len(series) < CONSEC_CLOSES:
        return "NEUTRAL", {"reason": "insufficient_history"}
    pairs: List[Tuple[float, Optional[float]]] = []
    for i in range(-CONSEC_CLOSES, 0):
        c = float(candles[i]["close"])
        e = series[i]
        pairs.append((c, e))
    if any(e is None for _, e in pairs):
        return "NEUTRAL", {"reason": "missing_ema"}
    if all(c > e for c, e in pairs):  # type: ignore[operator]
        return "BULL", {"closes_vs_ema50": [(round(c, 2), round(e, 2)) for c, e in pairs]}  # type: ignore[arg-type]
    if all(c < e for c, e in pairs):  # type: ignore[operator]
        return "BEAR", {"closes_vs_ema50": [(round(c, 2), round(e, 2)) for c, e in pairs]}  # type: ignore[arg-type]
    return "NEUTRAL", {"closes_vs_ema50": [(round(c, 2), round(e, 2)) for c, e in pairs]}  # type: ignore[arg-type]


def _ck_higher_highs_lows(candles: List[Dict[str, Any]]) -> Tuple[str, Any]:
    if len(candles) < RANGE_LOOKBACK + 1:
        return "NEUTRAL", {"reason": "insufficient_history"}
    now = candles[-1]
    prev = candles[-1 - RANGE_LOOKBACK]
    hi_n, lo_n = float(now["high"]), float(now["low"])
    hi_p, lo_p = float(prev["high"]), float(prev["low"])
    payload = {"high_now": hi_n, "low_now": lo_n, "high_prev": hi_p, "low_prev": lo_p}
    if hi_n > hi_p and lo_n > lo_p:
        return "BULL", payload
    if hi_n < hi_p and lo_n < lo_p:
        return "BEAR", payload
    return "NEUTRAL", payload


def _ck_close_direction(candles: List[Dict[str, Any]]) -> Tuple[str, Any]:
    if len(candles) < RANGE_LOOKBACK + 1:
        return "NEUTRAL", {"reason": "insufficient_history"}
    closes = [float(c["close"]) for c in candles[-(RANGE_LOOKBACK + 1):]]
    up = sum(1 for i in range(1, len(closes)) if closes[i] > closes[i - 1])
    dn = sum(1 for i in range(1, len(closes)) if closes[i] < closes[i - 1])
    payload = {"up": up, "down": dn, "of": RANGE_LOOKBACK}
    if up >= 3:
        return "BULL", payload
    if dn >= 3:
        return "BEAR", payload
    return "NEUTRAL", payload


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def _verdict_to_score(v: str) -> int:
    return {"BULL": 1, "BEAR": -1}.get(v, 0)


def _aggregate(score: int) -> Tuple[str, str]:
    if score >= 6:
        return "BULL", "strong"
    if score >= 4:
        return "BULL", "moderate"
    if score <= -6:
        return "BEAR", "strong"
    if score <= -4:
        return "BEAR", "moderate"
    return "NEUTRAL", "neutral"


def _empty_result(reason: str) -> Dict[str, Any]:
    return {
        "direction": "NEUTRAL",
        "confidence": "neutral",
        "score": 0,
        "checks": {},
        "reason": reason,
    }


def compute_d1_direction(
    pair: str,
    d1_candles: List[Dict[str, Any]],
    d1_emas: Dict[int, List[Optional[float]]],
    macd_data: Dict[str, List[Optional[float]]],
    atr_d1: Optional[float],
    config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Nine-check daily direction with scoring (see module docstring)."""
    if not d1_candles or len(d1_candles) < MIN_CANDLES:
        return _empty_result("insufficient_d1_history")

    th = _pair_thresholds(pair, config)
    min_fan = float(th.get("pair_minimum_fan_pips", _DEFAULTS["pair_minimum_fan_pips"]))
    min_slope = float(th.get("pair_minimum_slope_pips", _DEFAULTS["pair_minimum_slope_pips"]))
    buf_mult = float(th.get("atr_buffer_multiplier", _DEFAULTS["atr_buffer_multiplier"]))

    hist_series = (macd_data or {}).get("histogram") or []

    checks: Dict[str, Tuple[str, Any]] = {}
    checks["ema_stack"]            = _ck_ema_stack(d1_emas)
    checks["ema_fan"]              = _ck_ema_fan(d1_emas, min_fan)
    checks["ema8_slope"]           = _ck_ema8_slope(d1_emas, min_slope)
    checks["macd_sign"]            = _ck_macd_sign(hist_series)
    checks["macd_trend"]           = _ck_macd_trend(hist_series)
    checks["price_vs_ema50"]       = _ck_price_vs_ema50(d1_candles, d1_emas, atr_d1, buf_mult)
    checks["consec_closes_ema50"]  = _ck_consec_closes_vs_ema50(d1_candles, d1_emas)
    checks["higher_highs_lows"]    = _ck_higher_highs_lows(d1_candles)
    checks["close_direction"]      = _ck_close_direction(d1_candles)

    score = sum(_verdict_to_score(v) for v, _ in checks.values())
    direction, confidence = _aggregate(score)

    dissenters = [
        name for name, (v, _) in checks.items()
        if (direction == "BULL" and v == "BEAR")
        or (direction == "BEAR" and v == "BULL")
    ]
    if direction == "NEUTRAL":
        reason = f"score={score} (no majority)"
    else:
        reason = f"{direction} {confidence} (score {score:+d}/9)"
        if dissenters:
            reason += f"; dissenters: {','.join(dissenters)}"

    return {
        "direction": direction,
        "confidence": confidence,
        "score": score,
        "checks": {k: {"verdict": v, "value": s} for k, (v, s) in checks.items()},
        "reason": reason,
        "thresholds": {
            "pair_minimum_fan_pips": min_fan,
            "pair_minimum_slope_pips": min_slope,
            "atr_buffer_multiplier": buf_mult,
        },
    }


def compute_d1_direction_from_candles(
    pair: str,
    d1_candles: List[Dict[str, Any]],
    config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Derive indicators from raw D1 candles, then run the 9-check."""
    if not d1_candles or len(d1_candles) < MIN_CANDLES:
        return _empty_result("insufficient_d1_history")
    cfg = config or load_config()
    emas, macd, atr = compute_indicators_from_candles(d1_candles, cfg)
    return compute_d1_direction(pair, d1_candles, emas, macd, atr, cfg)


def compute_d1_direction_from_cache(
    pair: str,
    now_utc: Optional[datetime] = None,
    cache_dir: Optional[Path] = None,
    config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Load HTF cache and run the 9-check. Returns the standard result dict
    plus a ``cache`` block describing the load (age, stale, n_candles)."""
    now_utc = now_utc or datetime.now(timezone.utc)
    cache_dir = cache_dir or HTF_CACHE_DIR
    path = cache_dir / f"{pair.upper()}_D1.json"
    cache_info: Dict[str, Any] = {"path": str(path), "age_h": None, "stale": False, "n_candles": 0}

    if not path.exists():
        out = _empty_result("cache_missing")
        out["cache"] = cache_info
        return out

    age_h = (now_utc.timestamp() - path.stat().st_mtime) / 3600.0
    cache_info["age_h"] = round(age_h, 2)
    if age_h > STALE_HOURS:
        cache_info["stale"] = True
        out = _empty_result("stale_d1_cache")
        out["cache"] = cache_info
        return out

    try:
        data = json.loads(path.read_text())
    except Exception as exc:
        logger.error("[d1_direction] %s cache read failed: %s", pair, exc)
        out = _empty_result("cache_read_error")
        out["cache"] = cache_info
        return out

    candles = sorted(
        data.get("candles", []) or [], key=lambda c: c.get("timestamp", "")
    )
    completed = [
        c for c in candles
        if datetime.fromisoformat(c["timestamp"]).date() < now_utc.date()
        and c.get("close") is not None
    ]
    cache_info["n_candles"] = len(completed)
    if len(completed) < MIN_CANDLES:
        out = _empty_result("insufficient_d1_history")
        out["cache"] = cache_info
        return out

    out = compute_d1_direction_from_candles(pair, completed, config)
    out["cache"] = cache_info
    return out


def map_direction_to_daily_bias(direction: str) -> str:
    """Convert direction string to the briefing's daily_bias vocabulary."""
    return {"BULL": "BULLISH", "BEAR": "BEARISH"}.get(direction, "NEUTRAL")


def would_veto(direction_in: str, computed_direction: str) -> bool:
    """True iff trade direction opposes the computed D1 direction.
    NEUTRAL never vetoes."""
    if computed_direction == "BULL" and direction_in == "SELL":
        return True
    if computed_direction == "BEAR" and direction_in == "BUY":
        return True
    return False
