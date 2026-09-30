"""
gbpusd_raw_reversal.py — GBPUSD_RAW_REVERSAL strategy.

Catches reversals at the end of sustained directional moves on GBPUSD 5m.
Replaces BB_REVERSAL, EXHAUSTION_REVERSAL, BIG_REV, and the gbpusd_*
counter-trend variants for GBPUSD.

Three trigger setups (any one fires the strategy on a 5m close):

  Setup A  (pierce + recover): bar[-2].low <= BB_lower; bar[-1].close > BB_lower
  Setup B  (engulfing + hold): bar[-3] bearish, bar[-2] bullish engulfing, bar[-1].close >= bar[-2].open
  Setup C  (curve + rejection): 3-5 candle curve under support with strictly
                                shrinking bodies, no pierce, current bar
                                bullish with body >= 4 pips
SHORT mirrors all three.

Four context filters — ALL must pass at trigger time:

  1. Body slope:  numpy polyfit(deg=1) on abs(body) of prior 6 closed candles, slope < 0
  2. RSI lift:    RSI(14). LONG: min(rsi[-8:]) <= 30 AND rsi[-1] > min + 5. SHORT mirrors.
  3. MACD decay:  histogram peaked in [-12:-3] then decaying with allowed=1 non-decrease.
                  Required decay bars = max(3, floor(prior_move_pips / 10)).
                  prior_move_pips = abs(close[-1] - close[-13]).  (60min on 5m bars)
  4. Level prox:  trigger.low (LONG) or trigger.high (SHORT) within 3 pips of:
                    - briefing key_levels / major_levels / liquidity_pools
                    - yesterday's H or L (from H1 cache)
                    - today's morning extreme (06:00-12:00 UTC, from df)
                    - BB lower/upper (Setup A only)

Entry on trigger close.
SL = clamp(max(6p, distance_to_extreme + 1p), 6p, 25p) — reject above 25p.
TP = 50p (fixed; full reversal target).

Cooldown: standard 120s pair-dedup is bypassed for this mode (handled in autobot.py).
Session: 06:00-21:00 UTC. Max 3 entries per direction per session.
News blackout: subject to the universal autobot blackout gate.
"""
from __future__ import annotations

import json
import logging
import math
import os
import threading
from dataclasses import dataclass
from datetime import datetime, time as dtime, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple, TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from strategy_logic import StrategyDecision  # noqa: F401

logger = logging.getLogger("gbpusd_raw_reversal")

MODE_NAME_LONG  = "GBPUSD_RAW_REVERSAL_L"
MODE_NAME_SHORT = "GBPUSD_RAW_REVERSAL_S"
PIP_SIZE = 1.0  # GBPUSD on IG TODAY epic: 1 raw point = 1 pip


def _env_bool(name: str, default: str) -> bool:
    return os.getenv(name, default).strip().lower() in ("1", "true", "yes")


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(float(os.getenv(name, str(default))))
    except (TypeError, ValueError):
        return default


# ─── Configuration ────────────────────────────────────────────────────────
ENABLED = _env_bool("GBPUSD_RAW_REVERSAL_ENABLED", "1")

# Session window (UTC, weekdays only). Counter resets at WIN_START daily.
WIN_START = dtime(_env_int("GBPUSD_RAW_REVERSAL_WIN_START_H", 6), 0)
WIN_END   = dtime(_env_int("GBPUSD_RAW_REVERSAL_WIN_END_H", 21), 0)

# Per-direction session cap (BUY counter independent of SELL counter).
MAX_ENTRIES_PER_DIRECTION = _env_int("GBPUSD_RAW_REVERSAL_MAX_PER_DIR", 3)

# Trigger thresholds.
SETUP_C_MIN_CURVE_LEN = 3      # current + 2 prior candles
SETUP_C_MAX_CURVE_LEN = 5      # current + 4 prior candles
SETUP_C_MIN_BODY_PIPS = _env_float("GBPUSD_RAW_REVERSAL_SETUP_C_MIN_BODY_PIPS", 4.0)

# Context filters.
BODY_SLOPE_LOOKBACK = 6
RSI_PERIOD          = _env_int("GBPUSD_RAW_REVERSAL_RSI_PERIOD", 14)
RSI_LOW_THRESHOLD   = _env_float("GBPUSD_RAW_REVERSAL_RSI_LOW", 30.0)
RSI_HIGH_THRESHOLD  = _env_float("GBPUSD_RAW_REVERSAL_RSI_HIGH", 70.0)
RSI_LIFT_PIPS       = _env_float("GBPUSD_RAW_REVERSAL_RSI_LIFT", 5.0)
RSI_LOOKBACK_BARS   = 8

MACD_PEAK_WINDOW_START = -12
MACD_PEAK_WINDOW_END   = -3      # python slice end → inclusive index -4
MACD_DECAY_BAR_FLOOR   = 3
MACD_DECAY_NON_DECREASE_BUDGET = 1
MACD_FAST   = _env_int("MACD_FAST", 35)
MACD_SLOW   = _env_int("MACD_SLOW", 45)
MACD_SIGNAL = _env_int("MACD_SIGNAL", 30)

LEVEL_TOLERANCE_PIPS = _env_float("GBPUSD_RAW_REVERSAL_LEVEL_TOL_PIPS", 3.0)
LEVEL_TOLERANCE_PIPS_SETUP_A = _env_float(
    "GBPUSD_RAW_REVERSAL_LEVEL_TOL_PIPS_SETUP_A", 5.0
)
MACD_SETUP_A_LOOKBACK = 6  # compare hist[-1] vs hist[-7]
MORNING_EXTREME_START_H = 6
MORNING_EXTREME_END_H   = 12

BB_PERIOD = 20
BB_STD    = 2.0

# Stop / target geometry.
SL_BUFFER_PIPS = 1.0
SL_FLOOR_PIPS  = 6.0
SL_CEILING_PIPS = 25.0
TP_PIPS        = _env_float("GBPUSD_RAW_REVERSAL_TP_PIPS", 50.0)

# Per-mode max-hold override is enforced in trade_manager.py — this constant
# documents the intent and makes the value greppable from this file.
MAX_HOLD_MINUTES = 120

_STATE_FILE = "/opt/tradingbot/cache/gbpusd_raw_reversal_state.json"


# ─── Bar dataclass ────────────────────────────────────────────────────────
@dataclass
class Bar:
    """A closed 5m candle. Times are tz-aware UTC."""
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float

    @property
    def body(self) -> float:
        return abs(self.close - self.open)

    @property
    def is_bull(self) -> bool:
        return self.close > self.open

    @property
    def is_bear(self) -> bool:
        return self.close < self.open


# ─── Indicators ───────────────────────────────────────────────────────────
def _bb_20_2(closes: Sequence[float]) -> Tuple[float, float, float]:
    """Return (lower, mid, upper). Need >=20 closes."""
    if len(closes) < BB_PERIOD:
        raise ValueError("need 20+ closes for BB(20,2)")
    window = list(closes[-BB_PERIOD:])
    mid = sum(window) / BB_PERIOD
    var = sum((c - mid) ** 2 for c in window) / BB_PERIOD
    std = math.sqrt(var)
    return mid - BB_STD * std, mid, mid + BB_STD * std


def _rsi(closes: Sequence[float], period: int = RSI_PERIOD) -> List[float]:
    """Wilder RSI. Returns list aligned to closes; first `period` values are NaN."""
    n = len(closes)
    if n <= period:
        return [float("nan")] * n
    deltas = [closes[i] - closes[i - 1] for i in range(1, n)]
    gains = [max(d, 0.0) for d in deltas]
    losses = [-min(d, 0.0) for d in deltas]
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    out: List[float] = [float("nan")] * (period + 1)
    if avg_loss == 0:
        out.append(100.0 if avg_gain > 0 else 50.0)
    else:
        rs = avg_gain / avg_loss
        out.append(100.0 - 100.0 / (1.0 + rs))
    for i in range(period + 1, n):
        avg_gain = (avg_gain * (period - 1) + gains[i - 1]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i - 1]) / period
        if avg_loss == 0:
            out.append(100.0 if avg_gain > 0 else 50.0)
        else:
            rs = avg_gain / avg_loss
            out.append(100.0 - 100.0 / (1.0 + rs))
    # `out` currently has length n; first (period + 1) entries are NaN/seed.
    return out


def _macd_hist(closes: Sequence[float],
               fast: int = MACD_FAST,
               slow: int = MACD_SLOW,
               signal: int = MACD_SIGNAL) -> List[float]:
    """Return MACD histogram as a list aligned with closes."""
    n = len(closes)
    if n == 0:
        return []

    def _ema(values: Sequence[float], span: int) -> List[float]:
        alpha = 2.0 / (span + 1.0)
        out: List[float] = []
        prev = float(values[0])
        out.append(prev)
        for v in values[1:]:
            prev = alpha * float(v) + (1 - alpha) * prev
            out.append(prev)
        return out

    fast_ema = _ema(closes, fast)
    slow_ema = _ema(closes, slow)
    macd_line = [f - s for f, s in zip(fast_ema, slow_ema)]
    sig = _ema(macd_line, signal)
    return [m - s for m, s in zip(macd_line, sig)]


# ─── Setup detectors ──────────────────────────────────────────────────────
def _detect_setup_a(bars: Sequence[Bar],
                    bb_lower: float, bb_upper: float) -> Optional[str]:
    """Pierce + recover. Returns 'BUY' / 'SELL' / None.

    Accepts either a prior-bar pierce (prev.low <= BBL) or an intra-bar
    pierce-and-recover on the trigger candle itself (cur.low <= BBL),
    provided the trigger closes back inside the band.
    """
    if len(bars) < 2:
        return None
    prev = bars[-2]
    cur = bars[-1]
    prev_pierced_low = prev.low <= bb_lower
    cur_pierced_low = cur.low <= bb_lower
    if (prev_pierced_low or cur_pierced_low) and cur.close > bb_lower:
        return "BUY"
    prev_pierced_high = prev.high >= bb_upper
    cur_pierced_high = cur.high >= bb_upper
    if (prev_pierced_high or cur_pierced_high) and cur.close < bb_upper:
        return "SELL"
    return None


def _detect_setup_b(bars: Sequence[Bar]) -> Optional[str]:
    """Engulfing + hold. The current bar's close holds within the engulfing structure."""
    if len(bars) < 3:
        return None
    first = bars[-3]
    second = bars[-2]
    cur = bars[-1]
    # LONG: first bearish, second bullish engulfing, current closes >= second.open
    if (first.is_bear and second.is_bull
            and second.open <= first.close
            and second.close >= first.open
            and cur.close >= second.open):
        return "BUY"
    # SHORT: first bullish, second bearish engulfing, current closes <= second.open
    if (first.is_bull and second.is_bear
            and second.open >= first.close
            and second.close <= first.open
            and cur.close <= second.open):
        return "SELL"
    return None


def _detect_setup_c(bars: Sequence[Bar],
                    support_levels: Sequence[float],
                    resistance_levels: Sequence[float],
                    pip_size: float = PIP_SIZE,
                    ) -> Optional[Tuple[str, float]]:
    """Curve + rejection. 3-5 prior candles forming a tightening curve under
    a support level (LONG) or above a resistance level (SHORT). The trigger
    candle (current) must be bullish/bearish with body >= SETUP_C_MIN_BODY_PIPS.

    No part of the curve pierces the level (all lows above support / all highs
    below resistance). Bodies of the candles BEFORE the trigger must be
    strictly monotonically shrinking.

    Returns (direction, level_price) on match, else None.
    """
    if len(bars) < SETUP_C_MIN_CURVE_LEN:
        return None
    cur = bars[-1]
    cur_body = cur.body / pip_size

    # LONG: bullish trigger, body >= floor, curve under a support level
    if cur.is_bull and cur_body >= SETUP_C_MIN_BODY_PIPS and support_levels:
        for k in range(SETUP_C_MAX_CURVE_LEN, SETUP_C_MIN_CURVE_LEN - 1, -1):
            if len(bars) < k:
                continue
            curve = list(bars[-k:])
            # Strictly shrinking bodies on the candles BEFORE the trigger:
            # abs(body[i]) < abs(body[i-1]) for prior candles only.
            prior = curve[:-1]
            if len(prior) < 2:
                continue
            prior_bodies = [b.body for b in prior]
            shrinking = all(
                prior_bodies[i] < prior_bodies[i - 1]
                for i in range(1, len(prior_bodies))
            )
            if not shrinking:
                continue
            for lvl in support_levels:
                if all(b.low > lvl for b in curve):
                    return ("BUY", float(lvl))

    # SHORT: bearish trigger, body >= floor, curve over a resistance level
    if cur.is_bear and cur_body >= SETUP_C_MIN_BODY_PIPS and resistance_levels:
        for k in range(SETUP_C_MAX_CURVE_LEN, SETUP_C_MIN_CURVE_LEN - 1, -1):
            if len(bars) < k:
                continue
            curve = list(bars[-k:])
            prior = curve[:-1]
            if len(prior) < 2:
                continue
            prior_bodies = [b.body for b in prior]
            shrinking = all(
                prior_bodies[i] < prior_bodies[i - 1]
                for i in range(1, len(prior_bodies))
            )
            if not shrinking:
                continue
            for lvl in resistance_levels:
                if all(b.high < lvl for b in curve):
                    return ("SELL", float(lvl))

    return None


# ─── Context filters ──────────────────────────────────────────────────────
def _body_slope_ok(bars: Sequence[Bar]) -> Tuple[bool, float]:
    """Linear regression slope of abs(body) over the 6 closed candles
    BEFORE the trigger candle. Required: slope < 0."""
    if len(bars) < BODY_SLOPE_LOOKBACK + 1:
        return False, 0.0
    prior = bars[-(BODY_SLOPE_LOOKBACK + 1):-1]
    bodies = np.array([b.body for b in prior], dtype=float)
    x = np.arange(len(bodies), dtype=float)
    if np.allclose(bodies, bodies[0]):
        return False, 0.0
    slope, _ = np.polyfit(x, bodies, 1)
    return bool(slope < 0), float(slope)


def _rsi_lift_ok(closes: Sequence[float], direction: str
                 ) -> Tuple[bool, float, float]:
    """LONG: min(rsi[-8:]) <= 30 and current > min + 5.  SHORT mirror."""
    rsi = _rsi(closes, RSI_PERIOD)
    if len(rsi) < RSI_LOOKBACK_BARS:
        return False, float("nan"), float("nan")
    window = rsi[-RSI_LOOKBACK_BARS:]
    if any(math.isnan(v) for v in window):
        return False, float("nan"), float("nan")
    cur = window[-1]
    if direction == "BUY":
        wmin = min(window)
        return (wmin <= RSI_LOW_THRESHOLD and cur > wmin + RSI_LIFT_PIPS, cur, wmin)
    elif direction == "SELL":
        wmax = max(window)
        return (wmax >= RSI_HIGH_THRESHOLD and cur < wmax - RSI_LIFT_PIPS, cur, wmax)
    return False, float("nan"), float("nan")


def _macd_decay_ok(closes: Sequence[float], direction: str,
                    pip_size: float = PIP_SIZE
                    ) -> Tuple[bool, Dict[str, Any]]:
    """Histogram must peak in [-12:-3] then decay to current with at most
    one non-decrease step. Required decay bar count is proportional to
    prior_move_pips = abs(close[-1] - close[-13])."""
    n = len(closes)
    # Need at least 13 closes (for the 60min look-back) and a peak window.
    if n < 13:
        return False, {"reason": "insufficient_closes", "n": n}

    hist = _macd_hist(closes)
    if len(hist) != n:
        return False, {"reason": "macd_hist_size_mismatch"}

    # Peak window: indices -12 through -4 inclusive (Python slice [-12:-3]).
    peak_window = hist[MACD_PEAK_WINDOW_START:MACD_PEAK_WINDOW_END]
    if len(peak_window) == 0:
        return False, {"reason": "peak_window_empty"}

    if direction == "BUY":
        # Bottom: most-negative hist bar in window.
        peak_local_idx = int(np.argmin(peak_window))
        peak_val = peak_window[peak_local_idx]
        if peak_val >= 0:
            return False, {"reason": "no_negative_peak", "peak_val": peak_val}
    elif direction == "SELL":
        peak_local_idx = int(np.argmax(peak_window))
        peak_val = peak_window[peak_local_idx]
        if peak_val <= 0:
            return False, {"reason": "no_positive_peak", "peak_val": peak_val}
    else:
        return False, {"reason": "bad_direction"}

    # Translate local index in peak_window → absolute index in hist.
    peak_abs_idx = (n + MACD_PEAK_WINDOW_START) + peak_local_idx

    # Decay bars = bars from peak (exclusive) to last bar (inclusive).
    decay_bars = (n - 1) - peak_abs_idx
    prior_move_pips = abs(closes[-1] - closes[-13]) / pip_size
    required_decay = max(MACD_DECAY_BAR_FLOOR, int(math.floor(prior_move_pips / 10.0)))
    if decay_bars < required_decay:
        return False, {
            "reason": "insufficient_decay_bars",
            "decay_bars": decay_bars,
            "required": required_decay,
            "prior_move_pips": prior_move_pips,
        }

    # Monotonic decrease of |hist| from peak forward, allow 1 non-decrease.
    decay_slice = [abs(h) for h in hist[peak_abs_idx:]]
    non_decrease_count = 0
    for i in range(1, len(decay_slice)):
        if decay_slice[i] >= decay_slice[i - 1]:
            non_decrease_count += 1
            if non_decrease_count > MACD_DECAY_NON_DECREASE_BUDGET:
                return False, {
                    "reason": "monotonic_violation",
                    "non_decrease_count": non_decrease_count,
                    "decay_bars": decay_bars,
                }

    return True, {
        "peak_idx_from_end": -(n - peak_abs_idx),  # negative offset (e.g. -8)
        "peak_val": peak_val,
        "decay_bars": decay_bars,
        "required_decay": required_decay,
        "prior_move_pips": prior_move_pips,
        "non_decrease_count": non_decrease_count,
    }


def _macd_setup_a_decay_ok(closes: Sequence[float], direction: str,
                            ) -> Tuple[bool, Dict[str, Any]]:
    """Loosened MACD check used by Setup A only.

    "Any decay" — the histogram magnitude has shrunk over the last 6 bars
    (|hist[-1]| < |hist[-7]|), regardless of sign. Setup A's primary signal
    is the BB pierce + recover geometry; the original deep-negative-peak
    requirement was too strict for clean single-bar liquidity sweeps in
    sideways markets. Setups B and C still use the strict _macd_decay_ok.
    """
    n = len(closes)
    if n < MACD_SETUP_A_LOOKBACK + 1:
        return False, {"reason": "insufficient_closes", "n": n}
    hist = _macd_hist(closes)
    if len(hist) != n:
        return False, {"reason": "macd_hist_size_mismatch"}
    cur = hist[-1]
    ref = hist[-(MACD_SETUP_A_LOOKBACK + 1)]
    decayed = abs(cur) < abs(ref)
    meta = {
        "rule": "setup_a_any_decay",
        "hist_cur": float(cur),
        "hist_ref": float(ref),
        "lookback": MACD_SETUP_A_LOOKBACK,
        "magnitude_decayed": decayed,
        "direction": direction,
    }
    if not decayed:
        meta["reason"] = "no_magnitude_decay"
    return decayed, meta


def _level_proximity_ok(trigger: Bar,
                         direction: str,
                         support_levels: Sequence[float],
                         resistance_levels: Sequence[float],
                         pip_size: float = PIP_SIZE,
                         tol_pips: Optional[float] = None,
                         ) -> Tuple[bool, Optional[float], Optional[str]]:
    """Returns (passes, matched_level_price, level_label).

    tol_pips overrides LEVEL_TOLERANCE_PIPS when provided (used by Setup A
    to widen tolerance to 5p without affecting Setups B/C).
    """
    tol = (tol_pips if tol_pips is not None else LEVEL_TOLERANCE_PIPS) * pip_size
    if direction == "BUY":
        ref = trigger.low
        for lvl in support_levels:
            if abs(ref - lvl) <= tol:
                return True, float(lvl), "support"
        return False, None, None
    if direction == "SELL":
        ref = trigger.high
        for lvl in resistance_levels:
            if abs(ref - lvl) <= tol:
                return True, float(lvl), "resistance"
        return False, None, None
    return False, None, None


# ─── Level extraction ─────────────────────────────────────────────────────
def _extract_briefing_levels(briefing: Optional[Dict[str, Any]]
                              ) -> Tuple[List[float], List[float]]:
    """Return (support_levels, resistance_levels) from a briefing dict.
    Mirrors the bb_reversal._extract_tp_levels approach."""
    sup: List[float] = []
    res: List[float] = []
    if not briefing or not isinstance(briefing, dict):
        return sup, res
    for src in ("key_levels", "major_levels"):
        d = briefing.get(src, {}) or {}
        for v in d.get("support", []) or []:
            if v is not None:
                try:
                    sup.append(float(v))
                except (TypeError, ValueError):
                    pass
        for v in d.get("resistance", []) or []:
            if v is not None:
                try:
                    res.append(float(v))
                except (TypeError, ValueError):
                    pass
    lp = briefing.get("liquidity_pools", {}) or {}
    for v in lp.get("sell_side", []) or []:
        if v is not None:
            try:
                sup.append(float(v))
            except (TypeError, ValueError):
                pass
    for v in lp.get("buy_side", []) or []:
        if v is not None:
            try:
                res.append(float(v))
            except (TypeError, ValueError):
                pass
    return sup, res


def _yesterday_extremes_from_h1(h1_candles: Optional[Sequence[Dict[str, Any]]],
                                 today_utc: datetime,
                                 ) -> Tuple[Optional[float], Optional[float]]:
    """Return (yesterday_low, yesterday_high) by aggregating H1 candles
    whose timestamp falls on the previous UTC date. Returns (None, None)
    if cache absent or no matching bars."""
    if not h1_candles:
        return None, None
    yest = (today_utc.astimezone(timezone.utc).date() - timedelta(days=1))
    lows: List[float] = []
    highs: List[float] = []
    for c in h1_candles:
        ts_raw = c.get("time") or c.get("timestamp") or c.get("snapshotTime")
        if ts_raw is None:
            continue
        try:
            if isinstance(ts_raw, datetime):
                ts = ts_raw if ts_raw.tzinfo else ts_raw.replace(tzinfo=timezone.utc)
            else:
                ts_str = str(ts_raw).replace("/", "-").replace(" ", "T")
                ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
        except Exception:
            continue
        if ts.astimezone(timezone.utc).date() != yest:
            continue
        try:
            lows.append(float(c.get("low", c.get("lowPrice", 0.0))))
            highs.append(float(c.get("high", c.get("highPrice", 0.0))))
        except (TypeError, ValueError):
            continue
    if not lows or not highs:
        return None, None
    return min(lows), max(highs)


def _morning_extremes_from_bars(bars: Sequence[Bar],
                                 today_utc: datetime,
                                 ) -> Tuple[Optional[float], Optional[float]]:
    """Highest high and lowest low between 06:00-12:00 UTC of `today_utc`'s
    date in the bars list. Returns (low, high)."""
    today = today_utc.astimezone(timezone.utc).date()
    lows: List[float] = []
    highs: List[float] = []
    for b in bars:
        ts = b.timestamp.astimezone(timezone.utc)
        if ts.date() != today:
            continue
        h = ts.hour
        if MORNING_EXTREME_START_H <= h < MORNING_EXTREME_END_H:
            lows.append(b.low)
            highs.append(b.high)
    if not lows or not highs:
        return None, None
    return min(lows), max(highs)


# ─── Strategy class ───────────────────────────────────────────────────────
class GbpUsdRawReversalStrategy:
    """Singleton. Stateful only on the per-direction session counter."""

    _instance: Optional["GbpUsdRawReversalStrategy"] = None

    def __init__(self) -> None:
        self._lock = threading.Lock()
        # session_date_str -> {"BUY": int, "SELL": int}
        self._counts: Dict[str, Dict[str, int]] = {}
        # Dedup eval per (epic, bar_ts).
        self._last_eval_bar: Dict[str, datetime] = {}
        self._load_state()

    # --- Singleton ---
    @classmethod
    def instance(cls) -> "GbpUsdRawReversalStrategy":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    # --- State persistence ---
    def _load_state(self) -> None:
        try:
            if not os.path.exists(_STATE_FILE):
                return
            with open(_STATE_FILE) as f:
                raw = json.load(f)
            if isinstance(raw, dict) and isinstance(raw.get("counts"), dict):
                # Sanitize.
                clean: Dict[str, Dict[str, int]] = {}
                for k, v in raw["counts"].items():
                    if isinstance(v, dict):
                        clean[str(k)] = {
                            "BUY": int(v.get("BUY", 0) or 0),
                            "SELL": int(v.get("SELL", 0) or 0),
                        }
                self._counts = clean
        except Exception as exc:
            logger.warning("[RAW_REVERSAL] state load failed: %s", exc)

    def _save_state(self) -> None:
        try:
            os.makedirs(os.path.dirname(_STATE_FILE), exist_ok=True)
            tmp = _STATE_FILE + ".tmp"
            with open(tmp, "w") as f:
                json.dump({"counts": self._counts}, f)
            os.replace(tmp, _STATE_FILE)
        except Exception as exc:
            logger.warning("[RAW_REVERSAL] state save failed: %s", exc)

    # --- Session helpers ---
    @staticmethod
    def _session_date(ts_utc: datetime) -> str:
        """Return YYYY-MM-DD for the session containing `ts_utc`. Sessions
        run from WIN_START UTC to WIN_END UTC the same calendar day; if the
        timestamp is before WIN_START, count it under the prior date."""
        ts = ts_utc.astimezone(timezone.utc)
        if ts.time() < WIN_START:
            ts = ts - timedelta(days=1)
        return ts.date().isoformat()

    def _in_window(self, ts_utc: datetime) -> bool:
        ts = ts_utc.astimezone(timezone.utc)
        if ts.weekday() >= 5:
            return False
        t = ts.time()
        return WIN_START <= t < WIN_END

    def _can_enter(self, session_date: str, direction: str) -> bool:
        bucket = self._counts.get(session_date) or {"BUY": 0, "SELL": 0}
        return bucket.get(direction, 0) < MAX_ENTRIES_PER_DIRECTION

    def _record_entry(self, session_date: str, direction: str) -> None:
        with self._lock:
            bucket = self._counts.setdefault(session_date, {"BUY": 0, "SELL": 0})
            bucket[direction] = bucket.get(direction, 0) + 1
            # Keep only last 14 sessions.
            if len(self._counts) > 14:
                for k in sorted(self._counts.keys())[:-14]:
                    self._counts.pop(k, None)
            self._save_state()

    # --- Main entry point ---
    def evaluate(self,
                 symbol: str,
                 epic: str,
                 ts: datetime,
                 bars: Sequence[Bar],
                 closes_ind: Sequence[float],
                 briefing: Optional[Dict[str, Any]] = None,
                 h1_candles: Optional[Sequence[Dict[str, Any]]] = None,
                 pip_size: float = PIP_SIZE,
                 has_open_long: bool = False,
                 has_open_short: bool = False,
                 ) -> Optional["StrategyDecision"]:
        """Called on each new 5m close for GBPUSD.

        Args:
            bars: list of recent closed 5m Bars; bars[-1] is the trigger candle.
                  Need at least max(13, BB_PERIOD+1) bars.
            closes_ind: full closes list for indicator computation (same source
                  as bars but may be longer; at minimum 13 closes for MACD).
        """
        if not ENABLED or str(symbol).upper() != "GBPUSD":
            return None
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        else:
            ts = ts.astimezone(timezone.utc)

        if not self._in_window(ts):
            return None

        if not bars or len(bars) < 13:
            return None

        # Dedup — only evaluate each closed bar once per epic.
        last_seen = self._last_eval_bar.get(epic)
        if last_seen is not None and bars[-1].timestamp <= last_seen:
            return None
        self._last_eval_bar[epic] = bars[-1].timestamp

        trigger = bars[-1]

        # Indicators on the closes-for-indicators series.
        if len(closes_ind) < BB_PERIOD:
            return None
        try:
            bb_lower, bb_mid, bb_upper = _bb_20_2(closes_ind)
        except ValueError:
            return None

        # Briefing levels.
        b_sup, b_res = _extract_briefing_levels(briefing)

        # Yesterday's extremes (from H1 cache; fall back to None if absent).
        if h1_candles is None:
            try:
                from htf_cache import load_cached_candles  # type: ignore
                cached = load_cached_candles("GBPUSD", "H1") or {}
                h1_candles = cached.get("candles") or []
            except Exception:
                h1_candles = []
        yest_low, yest_high = _yesterday_extremes_from_h1(h1_candles, ts)

        # Today's morning extremes from the bar list.
        morn_low, morn_high = _morning_extremes_from_bars(bars, ts)

        # Aggregate level lists for proximity & Setup-C use.
        # BB lower/upper count only for Setup A's proximity check.
        sup_no_bb: List[float] = list(b_sup)
        res_no_bb: List[float] = list(b_res)
        if yest_low is not None:
            sup_no_bb.append(yest_low)
        if yest_high is not None:
            res_no_bb.append(yest_high)
        if morn_low is not None:
            sup_no_bb.append(morn_low)
        if morn_high is not None:
            res_no_bb.append(morn_high)

        # Try setups in order: A → B → C. First match wins; setups are
        # mutually exclusive in practice (different geometric pre-conditions).
        direction: Optional[str] = None
        setup: str = ""
        setup_level: Optional[float] = None

        a = _detect_setup_a(bars, bb_lower, bb_upper)
        if a is not None:
            direction = a
            setup = "A"
            setup_level = bb_lower if a == "BUY" else bb_upper
        else:
            b = _detect_setup_b(bars)
            if b is not None:
                direction = b
                setup = "B"
            else:
                c = _detect_setup_c(bars, sup_no_bb, res_no_bb, pip_size)
                if c is not None:
                    direction, setup_level = c
                    setup = "C"

        if direction is None:
            return None

        # Per-direction open-position gate (defensive — autobot also enforces
        # GBPUSD_MAX_PER_DIRECTION; keeping it here makes the strategy
        # self-contained).
        if direction == "BUY" and has_open_long:
            return None
        if direction == "SELL" and has_open_short:
            return None

        # Per-direction session cap.
        sess = self._session_date(ts)
        if not self._can_enter(sess, direction):
            logger.info(
                "[RAW_REVERSAL] %s %s blocked: session cap reached "
                "(%d/%d) for date=%s",
                symbol, direction,
                (self._counts.get(sess) or {}).get(direction, 0),
                MAX_ENTRIES_PER_DIRECTION, sess,
            )
            return None

        # Context filter 1 — body slope.
        slope_ok, body_slope = _body_slope_ok(bars)
        if not slope_ok:
            logger.debug(
                "[RAW_REVERSAL] %s %s setup=%s rejected: body_slope=%.4f (need <0)",
                symbol, direction, setup, body_slope,
            )
            return None

        # Context filter 2 — RSI lift. Setup A relies on the BB pierce +
        # recover geometry as its primary signal; RSI lift is informational
        # only for Setup A. Setups B and C still gate on it.
        rsi_ok, rsi_cur, rsi_extreme = _rsi_lift_ok(closes_ind, direction)
        if setup != "A" and not rsi_ok:
            logger.debug(
                "[RAW_REVERSAL] %s %s setup=%s rejected: RSI cur=%.2f extreme=%.2f",
                symbol, direction, setup, rsi_cur, rsi_extreme,
            )
            return None

        # Context filter 3 — MACD decay. Setup A uses a loosened "any decay"
        # rule (|hist[-1]| < |hist[-7]|) since its BB pierce + recover geometry
        # is itself a sweep/exhaustion signal. Setups B and C still require
        # the strict negative-peak-then-decay pattern.
        if setup == "A":
            macd_ok, macd_meta = _macd_setup_a_decay_ok(closes_ind, direction)
        else:
            macd_ok, macd_meta = _macd_decay_ok(closes_ind, direction, pip_size)
        if not macd_ok:
            logger.debug(
                "[RAW_REVERSAL] %s %s setup=%s rejected: MACD decay %s",
                symbol, direction, setup, macd_meta,
            )
            return None

        # Context filter 4 — level proximity. Setup A uses a 5p tolerance
        # (vs 3p default) since BB-pierce trigger lows often sit just outside
        # the closest cached level.
        if setup == "A":
            sup_for_prox = list(sup_no_bb) + [bb_lower]
            res_for_prox = list(res_no_bb) + [bb_upper]
            prox_tol = LEVEL_TOLERANCE_PIPS_SETUP_A
        else:
            sup_for_prox = list(sup_no_bb)
            res_for_prox = list(res_no_bb)
            prox_tol = LEVEL_TOLERANCE_PIPS
        prox_ok, lvl_price, lvl_label = _level_proximity_ok(
            trigger, direction, sup_for_prox, res_for_prox, pip_size,
            tol_pips=prox_tol,
        )
        if not prox_ok:
            logger.debug(
                "[RAW_REVERSAL] %s %s setup=%s rejected: level_proximity. "
                "trigger.low=%.2f trigger.high=%.2f sup=%s res=%s tol=%.1fp",
                symbol, direction, setup,
                trigger.low, trigger.high,
                sup_for_prox[:8], res_for_prox[:8], prox_tol,
            )
            return None

        # SL / TP.
        entry = float(trigger.close)
        if direction == "BUY":
            raw_sl_pips = (entry - trigger.low) / pip_size + SL_BUFFER_PIPS
        else:
            raw_sl_pips = (trigger.high - entry) / pip_size + SL_BUFFER_PIPS

        sl_pips = max(SL_FLOOR_PIPS, raw_sl_pips)
        if sl_pips > SL_CEILING_PIPS:
            logger.info(
                "[RAW_REVERSAL] %s %s setup=%s rejected: sl_exceeds_25p "
                "(raw=%.1fp clamped=%.1fp ceiling=%.1fp)",
                symbol, direction, setup, raw_sl_pips, sl_pips, SL_CEILING_PIPS,
            )
            return None

        tp_pips = TP_PIPS

        mode = MODE_NAME_LONG if direction == "BUY" else MODE_NAME_SHORT
        reason = (
            f"raw_reversal_{direction.lower()}_setup_{setup.lower()}: "
            f"slope={body_slope:.4f} rsi_cur={rsi_cur:.1f} rsi_extreme={rsi_extreme:.1f} "
            f"decay_bars={macd_meta.get('decay_bars')} "
            f"level={lvl_label}={lvl_price:.2f} sl={sl_pips:.1f}p tp={tp_pips:.1f}p"
        )

        try:
            from strategy_logic import StrategyDecision
        except Exception as exc:
            logger.error("[RAW_REVERSAL] StrategyDecision import failed: %s", exc)
            return None

        decision = StrategyDecision(
            symbol="GBPUSD",
            regime="RAW_REVERSAL",
            signal=direction,
            mode=mode,
            entry=entry,
            sl=round(float(sl_pips), 2),
            tp=round(float(tp_pips), 2),
            use_trailing_stop=False,
            reason=reason,
            debug={
                "setup": setup,
                "setup_level": setup_level,
                "matched_level": lvl_price,
                "matched_level_label": lvl_label,
                "body_slope": round(body_slope, 6),
                "rsi_current": round(rsi_cur, 2),
                "rsi_extreme": round(rsi_extreme, 2),
                "macd": macd_meta,
                "bb_lower": round(bb_lower, 4),
                "bb_mid": round(bb_mid, 4),
                "bb_upper": round(bb_upper, 4),
                "trigger_high": trigger.high,
                "trigger_low": trigger.low,
                "trigger_close": trigger.close,
                "session_date": sess,
                "session_count_after": (
                    (self._counts.get(sess) or {}).get(direction, 0) + 1
                ),
            },
            pip_size=pip_size,
        )

        logger.info(
            "[RAW_REVERSAL] %s ENTRY @ %.2f setup=%s | SL=%.1fp TP=%.1fp | %s",
            direction, entry, setup, sl_pips, tp_pips, reason,
        )
        self._record_entry(sess, direction)
        return decision


# Module-level singleton + dispatch helpers.
strategy = GbpUsdRawReversalStrategy.instance()


def evaluate(*args, **kwargs):
    return strategy.evaluate(*args, **kwargs)
