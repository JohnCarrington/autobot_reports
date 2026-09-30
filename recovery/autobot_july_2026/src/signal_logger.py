"""
signal_logger.py — append-only JSONL trade log with full open context and close outcome.

Each line is a self-contained JSON record. Records are written at open and updated in-place
at close (file is rewritten to patch the matching record).
"""

import json
import math
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import pandas as pd

_log = logging.getLogger(__name__)

# reversal_geometry loads at import time — self-registers its 5m-close
# callback for BB_BOUNCE post-fire reversal-geometry telemetry, and
# hydrates any pending fires from cache/reversal_geometry_pending.json.
# Soft-fail if import raises: no downstream effect on signal_logger.
try:
    import reversal_geometry as _reversal_geometry_module  # noqa: F401
except Exception as _rg_imp_exc:
    _log.debug("[signal_logger] reversal_geometry import failed: %s", _rg_imp_exc)

LOG_PATH = Path(os.getenv("SIGNAL_LOG_PATH", "/opt/tradingbot/logs/signal_log.jsonl"))


# ---------------------------------------------------------------------------
# Session
# ---------------------------------------------------------------------------

def _session_from_utc_hour(hour: int) -> str:
    if 0 <= hour < 6:
        return "Asian"
    if 6 <= hour < 11:
        return "London"
    if 11 <= hour < 16:
        return "NY"
    return "Late"


# ---------------------------------------------------------------------------
# Indicator helpers (computed from raw df columns)
# ---------------------------------------------------------------------------

def _ema_aligned(df: pd.DataFrame, direction: str) -> Optional[bool]:
    """True if EMA 8/13/21/50 are stacked in the correct order for direction."""
    try:
        row = df.iloc[-1]
        vals = {}
        for p in (8, 13, 21, 50):
            key = f"EMA_{p}"
            if key not in df.columns:
                return None
            v = float(row[key])
            if not math.isfinite(v):
                return None
            vals[p] = v
        if direction == "SELL":
            return vals[8] < vals[13] < vals[21] < vals[50]
        else:
            return vals[8] > vals[13] > vals[21] > vals[50]
    except Exception:
        return None


def _macd_direction(df: pd.DataFrame) -> Optional[str]:
    """'bullish' if MACD histogram > 0, 'bearish' if < 0, None if unavailable."""
    try:
        row = df.iloc[-1]
        for col in df.columns:
            if col.startswith("MACD_HIST"):
                v = float(row[col])
                if math.isfinite(v):
                    return "bearish" if v < 0 else "bullish"
        return None
    except Exception:
        return None


def _atr_pips(df: pd.DataFrame, pip_size: float, period: int = 14) -> Optional[float]:
    """14-period Wilder ATR in pips."""
    try:
        if len(df) < period + 1:
            return None
        highs = df["high"].astype(float)
        lows = df["low"].astype(float)
        closes = df["close"].astype(float)
        tr_list = [
            max(
                highs.iloc[i] - lows.iloc[i],
                abs(highs.iloc[i] - closes.iloc[i - 1]),
                abs(lows.iloc[i] - closes.iloc[i - 1]),
            )
            for i in range(1, len(df))
        ]
        atr = pd.Series(tr_list).ewm(span=period, adjust=False, min_periods=period).mean().iloc[-1]
        return round(atr / pip_size, 2) if math.isfinite(atr) else None
    except Exception:
        return None


def _bb_width_pips(df: pd.DataFrame, pip_size: float) -> Optional[float]:
    """Bollinger Band width (upper - lower) in pips."""
    try:
        row = df.iloc[-1]
        upper = lower = None
        for col in df.columns:
            if upper is None and col.startswith("BB_UPPER"):
                v = float(row[col])
                if math.isfinite(v):
                    upper = v
            if lower is None and col.startswith("BB_LOWER"):
                v = float(row[col])
                if math.isfinite(v):
                    lower = v
        if upper is None or lower is None:
            return None
        return round((upper - lower) / pip_size, 2)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# New open-context helpers
# ---------------------------------------------------------------------------

def _minutes_since_london_open(now_utc: datetime) -> int:
    """Minutes elapsed since 07:00 UTC today (negative if before open)."""
    london_open = now_utc.replace(hour=7, minute=0, second=0, microsecond=0)
    return int((now_utc - london_open).total_seconds() / 60)


def _minutes_since_briefing(briefing: Dict[str, Any], now_utc: datetime) -> Optional[int]:
    """Minutes since the last briefing was generated."""
    try:
        bt = briefing.get("briefing_time") if briefing else None
        if not bt:
            return None
        briefing_dt = datetime.fromisoformat(str(bt).replace("Z", "+00:00"))
        return max(0, int((now_utc - briefing_dt).total_seconds() / 60))
    except Exception:
        return None


def _today_candles(df: pd.DataFrame, now_utc: datetime) -> pd.DataFrame:
    """Filter df to candles whose timestamp falls on today's UTC date."""
    try:
        today = now_utc.date()
        time_col = "time" if "time" in df.columns else "timestamp"
        ts = pd.to_datetime(df[time_col], utc=True, errors="coerce")
        mask = ts.dt.date == today
        return df[mask].copy()
    except Exception:
        return pd.DataFrame()


def _price_vs_daily_open(
    df: pd.DataFrame, entry_price: float, pip_size: float, now_utc: datetime
) -> Optional[float]:
    """entry_price minus today's first candle open, in pips (+ = above daily open)."""
    try:
        today_df = _today_candles(df, now_utc)
        if today_df.empty:
            return None
        daily_open = float(today_df.iloc[0]["open"])
        return round((entry_price - daily_open) / pip_size, 2)
    except Exception:
        return None


def _vwap_distance_pips(
    df: pd.DataFrame, entry_price: float, pip_size: float, now_utc: datetime
) -> Optional[float]:
    """Distance from today's VWAP in pips (+ = entry above VWAP)."""
    try:
        today_df = _today_candles(df, now_utc)
        if today_df.empty:
            return None
        highs  = pd.to_numeric(today_df["high"],  errors="coerce")
        lows   = pd.to_numeric(today_df["low"],   errors="coerce")
        closes = pd.to_numeric(today_df["close"], errors="coerce")
        typical = (highs + lows + closes) / 3.0

        vwap: float
        if "volume" in today_df.columns:
            vol = pd.to_numeric(today_df["volume"], errors="coerce").fillna(0)
            total_vol = vol.sum()
            vwap = float((typical * vol).sum() / total_vol) if total_vol > 0 else float(typical.mean())
        else:
            vwap = float(typical.mean())

        if not math.isfinite(vwap):
            return None
        return round((entry_price - vwap) / pip_size, 2)
    except Exception:
        return None


def _candles_touched_today(
    briefing: Dict[str, Any], df: pd.DataFrame, pip_size: float, now_utc: datetime
) -> int:
    """Count how many briefing key levels price touched today (within 3-pip tolerance)."""
    try:
        if not briefing:
            return 0
        today_df = _today_candles(df, now_utc)
        if today_df.empty:
            return 0

        highs = pd.to_numeric(today_df["high"], errors="coerce")
        lows  = pd.to_numeric(today_df["low"],  errors="coerce")
        day_high = float(highs.max())
        day_low  = float(lows.min())

        tol = 3.0 * pip_size
        levels = []
        for section in ("key_levels", "major_levels"):
            sec = briefing.get(section) or {}
            for side in ("support", "resistance"):
                for lv in sec.get(side) or []:
                    try:
                        levels.append(float(lv))
                    except (TypeError, ValueError):
                        pass

        touched = 0
        for lv in levels:
            if (day_low - tol) <= lv <= (day_high + tol):
                touched += 1
        return touched
    except Exception:
        return 0


def _entry_candle_pattern(df: pd.DataFrame) -> str:
    """Classify the entry candle (last completed). Requires at least 2 rows."""
    try:
        if len(df) < 2:
            return "normal"
        curr = df.iloc[-1]
        prev = df.iloc[-2]

        c_open  = float(curr["open"])
        c_high  = float(curr["high"])
        c_low   = float(curr["low"])
        c_close = float(curr["close"])
        p_open  = float(prev["open"])
        p_close = float(prev["close"])

        c_range = c_high - c_low
        if c_range <= 0:
            return "doji"

        body     = abs(c_close - c_open)
        body_pct = body / c_range * 100.0

        # Doji: very small body
        if body_pct < 10.0:
            return "doji"

        # Inside bar: current range entirely within previous range
        p_range_high = max(p_open, p_close)
        p_range_low  = min(p_open, p_close)
        if c_high <= prev["high"] and c_low >= prev["low"]:
            return "inside_bar"

        # Engulfing: current body fully engulfs previous body
        c_body_high = max(c_open, c_close)
        c_body_low  = min(c_open, c_close)
        if c_body_high > p_range_high and c_body_low < p_range_low:
            return "engulfing"

        # Pin bar: one wick ≥ 2× the body and ≥ 60% of total range
        upper_wick = c_high - max(c_open, c_close)
        lower_wick = min(c_open, c_close) - c_low
        if upper_wick >= 2.0 * body and upper_wick / c_range >= 0.60:
            return "pin_bar"
        if lower_wick >= 2.0 * body and lower_wick / c_range >= 0.60:
            return "pin_bar"

        return "normal"
    except Exception:
        return "normal"


def _entry_candle_body_pct(df: pd.DataFrame) -> Optional[float]:
    """Body size as % of total candle range (0–100) for the last candle."""
    try:
        row = df.iloc[-1]
        c_range = float(row["high"]) - float(row["low"])
        if c_range <= 0:
            return 0.0
        body = abs(float(row["close"]) - float(row["open"]))
        return round(min(100.0, body / c_range * 100.0), 2)
    except Exception:
        return None


def _entry_candle_wick_ratio(df: pd.DataFrame) -> Optional[float]:
    """Upper wick / lower wick ratio for the last candle (None if lower wick is zero)."""
    try:
        row = df.iloc[-1]
        c_open  = float(row["open"])
        c_high  = float(row["high"])
        c_low   = float(row["low"])
        c_close = float(row["close"])
        upper_wick = c_high - max(c_open, c_close)
        lower_wick = min(c_open, c_close) - c_low
        upper_wick = max(upper_wick, 0.0)
        lower_wick = max(lower_wick, 0.0)
        if lower_wick < 1e-8:
            return None
        return round(upper_wick / lower_wick, 3)
    except Exception:
        return None


def _atr_vs_20day_avg(df: pd.DataFrame, pip_size: float, period: int = 14) -> Optional[float]:
    """
    Current 14-period ATR relative to the mean 14-period ATR over all available candles.
    Returns current/mean so >1 means higher-than-average volatility.
    Uses available candle window as proxy (ideally 20 days; typically 50 candles here).
    """
    try:
        if len(df) < period + 2:
            return None
        highs  = df["high"].astype(float).values
        lows   = df["low"].astype(float).values
        closes = df["close"].astype(float).values

        tr = [
            max(
                highs[i] - lows[i],
                abs(highs[i] - closes[i - 1]),
                abs(lows[i] - closes[i - 1]),
            )
            for i in range(1, len(df))
        ]
        tr_series = pd.Series(tr)
        atr_series = tr_series.ewm(span=period, adjust=False, min_periods=period).mean()
        atr_series = atr_series.dropna()

        if len(atr_series) < 2:
            return None

        current_atr = float(atr_series.iloc[-1])
        mean_atr    = float(atr_series.mean())
        if mean_atr <= 0 or not math.isfinite(mean_atr):
            return None
        return round(current_atr / mean_atr, 3)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Day-type telemetry helpers (Part D, 2026-07-16, OBSERVABLE-ONLY).
#
# All fail-safe: any exception returns None so a missing df / bad column /
# stale news cache never blocks a fire. Matches the FXi-block pattern in
# log_open — one warning, nulls preserved, no re-raise.
# ---------------------------------------------------------------------------

_DAY_SESSIONS = (
    ("Asia",   0,  7),
    ("London", 7, 13),
    ("NY",    13, 21),
)

_MARKET_ACTION_TH = {
    "trending_adx_min":                 25.0,
    "trending_er_min":                   0.40,
    "ranging_er_max":                    0.30,
    "ranging_adx_max":                  20.0,
    "chop_er_max":                       0.20,
    "chop_adx_max":                     15.0,
    "consolidation_bbw_slope_max_pips": -1.5,
}


def _day_session_name(now_utc: datetime) -> Optional[str]:
    try:
        h = int(now_utc.hour)
        for name, start, end in _DAY_SESSIONS:
            if start <= h < end:
                return name
        return None
    except Exception:
        return None


def _kaufman_er_from_closes(closes: pd.Series, period: int = 10) -> Optional[float]:
    try:
        s = pd.to_numeric(closes, errors="coerce").dropna()
        if len(s) < period + 1:
            return None
        net = abs(float(s.iloc[-1]) - float(s.iloc[-period - 1]))
        volatility = float(s.diff().abs().iloc[-period:].sum())
        if volatility <= 0:
            return None
        return round(net / volatility, 3)
    except Exception:
        return None


def _classify_market_action(
    adx: Optional[float], er: Optional[float], bbw_slope: Optional[float]
) -> str:
    """Same rules as daily_journal._classify_market_action (l.224-237)."""
    t = _MARKET_ACTION_TH
    if adx is None or er is None:
        return "unknown"
    if adx >= t["trending_adx_min"] and er >= t["trending_er_min"]:
        return "trending"
    if bbw_slope is not None and bbw_slope <= t["consolidation_bbw_slope_max_pips"]:
        return "consolidation"
    if adx <= t["chop_adx_max"] and er <= t["chop_er_max"]:
        return "chop"
    if adx < t["ranging_adx_max"] and er < t["ranging_er_max"]:
        return "ranging"
    return "mixed"


def _session_frame(df: pd.DataFrame, now_utc: datetime) -> Optional[pd.DataFrame]:
    """Slice df to bars from the current UTC session's start up to now."""
    try:
        sess = _day_session_name(now_utc)
        if sess is None:
            return None
        start_h = next(s for n, s, _ in _DAY_SESSIONS if n == sess)
        time_col = "time" if "time" in df.columns else "timestamp"
        ts = pd.to_datetime(df[time_col], utc=True, errors="coerce")
        day = now_utc.date()
        start_ts = pd.Timestamp(datetime(day.year, day.month, day.day, start_h,
                                         tzinfo=timezone.utc))
        mask = (ts.dt.date == day) & (ts >= start_ts) & (ts <= pd.Timestamp(now_utc))
        return df[mask]
    except Exception:
        return None


def _last_num(series: pd.Series) -> Optional[float]:
    try:
        s = pd.to_numeric(series, errors="coerce").dropna()
        if s.empty:
            return None
        v = float(s.iloc[-1])
        return v if math.isfinite(v) else None
    except Exception:
        return None


def _bbw_pips_slope_from_column(
    df: pd.DataFrame, pip_size: float, lookback: int = 6
) -> Optional[float]:
    """Slope of BB_WIDTH over last `lookback` bars, in pips."""
    try:
        col = next((c for c in df.columns if c.startswith("BB_WIDTH_20")), None)
        if col is None or pip_size in (None, 0):
            return None
        s = pd.to_numeric(df[col], errors="coerce").dropna()
        if len(s) < lookback + 1:
            return None
        now = float(s.iloc[-1]) / float(pip_size)
        then = float(s.iloc[-lookback - 1]) / float(pip_size)
        if not (math.isfinite(now) and math.isfinite(then)):
            return None
        return round(now - then, 2)
    except Exception:
        return None


def _day_news_tier_for(now_utc: datetime) -> Optional[str]:
    """Read the loaded finnhub calendar for today and return the max tier
    among HIGH-impact GBP/USD events: BIG > MIDDLE > SMALL > none.
    Returns None only on unexpected error; "none" when no HIGH events."""
    try:
        day = now_utc.date().isoformat()
        p = Path("/opt/tradingbot/cache") / f"news_state_finnhub_{day}.json"
        if not p.exists():
            return "none"
        blob = json.loads(p.read_text(encoding="utf-8"))
        events = blob.get("events") or []
        max_tier = "none"
        rank = {"none": 0, "SMALL": 1, "MIDDLE": 2, "BIG": 3}
        try:
            from news_tier_classifier import classify_news_tier as _classify
        except Exception:
            _classify = None
        for e in events:
            if str(e.get("impact", "")).upper() != "HIGH":
                continue
            if str(e.get("currency", "")).upper() not in ("GBP", "USD"):
                continue
            tier = "SMALL"
            if _classify is not None:
                try:
                    ev = {"event_name": e.get("event"), "currency": e.get("currency")}
                    r = _classify(ev)
                    tier = str(r.get("tier") or "SMALL")
                except Exception:
                    pass
            if rank.get(tier, 0) > rank.get(max_tier, 0):
                max_tier = tier
        return max_tier
    except Exception:
        return None


def _bb_squeeze(df: pd.DataFrame) -> Optional[bool]:
    """
    True if the current BB width is below the average BB width across available candles.
    Uses BB_UPPER / BB_LOWER columns produced by indicators.add_indicators().
    """
    try:
        upper_col = next((c for c in df.columns if c.startswith("BB_UPPER")), None)
        lower_col = next((c for c in df.columns if c.startswith("BB_LOWER")), None)
        if upper_col is None or lower_col is None:
            return None

        widths = (
            pd.to_numeric(df[upper_col], errors="coerce")
            - pd.to_numeric(df[lower_col], errors="coerce")
        ).dropna()

        if widths.empty:
            return None

        current_width = float(widths.iloc[-1])
        avg_width     = float(widths.mean())
        if not math.isfinite(current_width) or not math.isfinite(avg_width) or avg_width <= 0:
            return None
        return current_width < avg_width
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Close-context helpers
# ---------------------------------------------------------------------------

def _close_type(reason: str) -> str:
    """Map a close reason string to a canonical close type label."""
    r = (reason or "").upper()
    if "TP3" in r:
        return "TP3"
    if "TP2" in r:
        return "TP2"
    if "TP1" in r or ("TP" in r and "TP2" not in r and "TP3" not in r):
        return "TP1"
    if "SL" in r:
        return "SL"
    if any(w in r for w in ("MANUAL", "FORCED", "BLACKOUT", "PRE_NEWS")):
        return "MANUAL"
    if any(w in r for w in ("TRAIL", "PROFIT_PROTECT", "SWEEP_EXTREME", "SWEEP_STALL")):
        return "TRAIL"
    return reason or "UNKNOWN"


def _mae_mfe(
    df: pd.DataFrame,
    direction: str,
    entry_price: float,
    pip_size: float,
    open_ts: Optional[datetime],
) -> Tuple[Optional[float], Optional[float]]:
    """
    Compute Max Adverse Excursion and Max Favourable Excursion from entry_price
    using 5m candles from open_ts onwards.

    BUY:  adverse = entry - candle_low,  favourable = candle_high - entry
    SELL: adverse = candle_high - entry, favourable = entry - candle_low

    Returns (mae_pips, mfe_pips).
    """
    try:
        if df is None or df.empty or not entry_price:
            return None, None

        work = df.copy()
        if open_ts is not None:
            time_col = "time" if "time" in work.columns else "timestamp"
            ts = pd.to_datetime(work[time_col], utc=True, errors="coerce")
            open_ts_utc = open_ts.astimezone(timezone.utc) if open_ts.tzinfo else open_ts.replace(tzinfo=timezone.utc)
            work = work[ts >= open_ts_utc]

        if work.empty:
            return None, None

        highs = pd.to_numeric(work["high"], errors="coerce")
        lows  = pd.to_numeric(work["low"],  errors="coerce")

        if direction == "BUY":
            adverse_series    = (entry_price - lows).clip(lower=0)
            favourable_series = (highs - entry_price).clip(lower=0)
        else:  # SELL
            adverse_series    = (highs - entry_price).clip(lower=0)
            favourable_series = (entry_price - lows).clip(lower=0)

        mae = float(adverse_series.max())
        mfe = float(favourable_series.max())

        if not math.isfinite(mae) or not math.isfinite(mfe):
            return None, None

        return round(mae / pip_size, 2), round(mfe / pip_size, 2)
    except Exception:
        return None, None


# ---------------------------------------------------------------------------
# Level source / major
# ---------------------------------------------------------------------------

def _coerce_level_price(raw: Any) -> Optional[float]:
    """Coerce a `briefing_level` debug value into a float price.

    Strategies pass different shapes for `debug["briefing_level"]`:
      - dict (the common case from _match_levels_array): {"price": 13520.0, ...}
      - float / int: a bare price
      - str: a stringified number
      - None: not matched

    Anything else logs a one-liner warning and returns None — the open
    record is still written without a level_price field, instead of
    crashing the whole log_open call (which orphans the audit trail).
    """
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        try:
            return float(raw)
        except (TypeError, ValueError):
            return None
    if isinstance(raw, dict):
        # Try the canonical "price" key first; fall back to other common names.
        for key in ("price", "level_price", "value"):
            v = raw.get(key)
            if v is not None:
                try:
                    return float(v)
                except (TypeError, ValueError):
                    continue
        return None
    if isinstance(raw, str):
        try:
            return float(raw.strip())
        except (TypeError, ValueError):
            return None
    _log.warning(
        "[signal_logger] log_open: level_price_raw type=%s unexpected, storing as null",
        type(raw).__name__,
    )
    return None


def _level_meta(briefing: Dict[str, Any], level_price: Optional[float]) -> Tuple[Optional[str], Optional[bool]]:
    """Return (level_source, level_major) for a matched briefing level."""
    if not briefing or level_price is None:
        return None, None
    tol = abs(level_price) * 1e-6 + 1e-5
    kl = briefing.get("key_levels") or {}
    for side in ("resistance", "support"):
        for lv in kl.get(side) or []:
            try:
                if abs(float(lv) - level_price) <= tol:
                    return f"briefing_{side}", True
            except (TypeError, ValueError):
                pass
    lp = briefing.get("liquidity_pools") or {}
    for side in ("buy_side", "sell_side"):
        for lv in lp.get(side) or []:
            try:
                if abs(float(lv) - level_price) <= tol:
                    return f"briefing_{side}_liquidity", False
            except (TypeError, ValueError):
                pass
    return "briefing_unknown", None


# ---------------------------------------------------------------------------
# Outcome label
# ---------------------------------------------------------------------------

def _outcome_label(reason: str) -> str:
    r = (reason or "").upper()
    if "TP" in r:
        return "TP1"
    if "SL" in r:
        return "SL"
    if any(w in r for w in ("MANUAL", "FORCED", "BLACKOUT", "PRE_NEWS")):
        return "MANUAL"
    return reason or "UNKNOWN"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def log_open(
    trade_id: str,
    epic: str,
    decision: Any,
    briefing: Dict[str, Any],
    df_5m: pd.DataFrame,
    entry_price: float,
    deal_id: Optional[str] = None,
    latency: Optional[Dict[str, Any]] = None,
    entry_price_source: str = "decision_fallback",
) -> None:
    """Append a new open record to the signal log.

    deal_id is the IG broker deal_id, persisted so startup reconciliation
    can recover the original strategy tag after a service restart.

    latency, if provided, is a dict produced by
    execution_latency_metrics.build_fire_latency_record(...) — its keys
    are merged into the open record verbatim.  All fields are optional
    and default to None so old readers keep working and old records
    stay valid.

    entry_price_source labels the provenance of `entry_price`:
      - "ig_fill"           — IG broker confirmed fill from
                              fetch_deal_by_deal_reference (preferred).
      - "decision_fallback" — M5 decision price; ENTRY_FILL_READBACK_ENABLED
                              was off, no fill was captured, or the fill
                              was outside the sanity bound (>5p from
                              decision).
    Default "decision_fallback" preserves back-compat for any call site
    that hasn't been ported (matches pre-2026-06-15 behaviour).
    """
    try:
        dbg: Dict[str, Any] = getattr(decision, "debug", None) or {}
        pip_size = float(dbg.get("pip_size") or 1.0)
        direction = str(getattr(decision, "signal", "") or "")
        pair = str(getattr(decision, "symbol", "") or "")

        sl_pips_raw = getattr(decision, "sl", None)
        tp_pips_raw = getattr(decision, "tp", None)
        sl_pips = float(sl_pips_raw) if sl_pips_raw is not None else None
        tp_pips = float(tp_pips_raw) if tp_pips_raw is not None else None

        # Convert pip distances → price levels
        sl_price = tp_price = None
        if sl_pips is not None:
            dist = sl_pips * pip_size
            sl_price = round(entry_price + dist if direction == "SELL" else entry_price - dist, 5)
        if tp_pips is not None:
            dist = tp_pips * pip_size
            tp_price = round(entry_price - dist if direction == "SELL" else entry_price + dist, 5)

        now_utc = datetime.now(timezone.utc)
        level_price_raw = dbg.get("briefing_level")
        # Coerce defensively — strategies pass dict / float / None for this
        # field. Bare float() crashed log_open and orphaned the audit trail.
        level_price = _coerce_level_price(level_price_raw)
        level_source, level_major = _level_meta(briefing, level_price)

        dist_pips = None
        if level_price is not None:
            try:
                dist_pips = round(abs(entry_price - level_price) / pip_size, 2)
            except Exception:
                pass

        # ── New open-context fields ────────────────────────────────────────
        has_df = df_5m is not None and not df_5m.empty

        # Regime state at fire-time. Primary path: strategy threaded the
        # five-field dict through decision.debug["regime_state"] (built
        # via regime_classifier.build_regime_state_for_debug). Fallback:
        # strategy_logic.get_latest_regime_state(pair) — slightly stale
        # but bar-aligned. Final fallback: all five fields are null.
        # Per-pair migration is incremental — fields default to null for
        # strategies that haven't been wired yet rather than crashing.
        _rs: Dict[str, Any] = {}
        try:
            _rs_from_debug = (dbg.get("regime_state") if isinstance(dbg, dict) else None)
            if isinstance(_rs_from_debug, dict):
                _rs = _rs_from_debug
            else:
                from strategy_logic import get_latest_regime_state as _gls
                _rs_cached = _gls(pair)
                if isinstance(_rs_cached, dict):
                    _rs = _rs_cached
        except Exception:
            _rs = {}

        # fire_path: caller-supplied tag identifying which dispatch path
        # within a multi-path strategy produced this decision (e.g.
        # BRIEFING_EXECUTION's "phase2_sweep_reclaim" vs
        # "trend_entry_fallback"). Additive — strategies that don't set
        # debug["fire_path"] leave this null, matching pre-existing records.
        _fire_path = dbg.get("fire_path") if isinstance(dbg, dict) else None
        if _fire_path is not None and not isinstance(_fire_path, str):
            _fire_path = None

        # Rich engine-regime capture (additive, 2026-06-23). The existing
        # regime_at_fire above is the strategy-side gbpusd_regime detector
        # (NEUTRAL/TRENDING/RANGE vocabulary). regime_engine emits a 6+-way
        # label (TREND_FORMING_UP/DOWN, STRONG_TREND_*, RANGE_ROTATION,
        # COMPRESSION, CHOP, BREAKOUT_*) on every 5M close and caches the
        # result module-level — read here without recomputation. engine_*
        # fields are capture-only; no gate, router, or exit reads them.
        _eng: Dict[str, Any] = {}
        try:
            import regime_engine as _regime_engine
            _eng_raw = _regime_engine.latest_result(pair)
            if isinstance(_eng_raw, dict):
                _eng = _eng_raw
        except Exception:
            _eng = {}

        # Regime-field resolution (telemetry-only, added 2026-07-11).
        # Prior state: signal_logger read strategy-stamped keys straight
        # from decision.debug; strategies that used the wrong key
        # (structure_break, confirmation_fallback stamp "regime_at_fire"
        # instead of "regime") or did not stamp at all (armed EMA_PULLBACK,
        # trend_v3 partial, all rows for regime_instance_id since the
        # router is dormant) wrote nulls. This block:
        #   (a) accepts either dbg["regime"] or dbg["regime_at_fire"] as
        #       the strategy stamp for regime_at_fire,
        #   (b) falls back to the same _eng cache used by
        #       engine_regime_at_fire below, and
        #   (c) tags enriched rows with regime_source="engine_enriched_at_log"
        #       so a downstream reader can distinguish strategy vs engine
        #       provenance. NO gate, router, or exit reads these fields —
        #       purely capture. Wrapped so any failure logs and falls back
        #       to the pre-existing null behaviour; never delays a fire.
        _regime_iid_final = dbg.get("regime_instance_id") if isinstance(dbg, dict) else None
        _regime_at_fire_final = None
        _regime_conf_final = None
        _regime_signals_final = None
        _regime_source_final = None
        if isinstance(dbg, dict):
            _regime_at_fire_final = dbg.get("regime") or dbg.get("regime_at_fire")
            _regime_conf_final = dbg.get("regime_confidence_final")
            _regime_signals_final = dbg.get("regime_signals")
            _regime_source_final = dbg.get("regime_source")
        try:
            _enriched_any = False
            if _regime_iid_final is None and _eng.get("regime_instance_id"):
                _regime_iid_final = _eng.get("regime_instance_id")
                _enriched_any = True
            if _regime_at_fire_final is None and _eng.get("winning_regime"):
                _regime_at_fire_final = _eng.get("winning_regime")
                _enriched_any = True
            if _regime_conf_final is None and _eng.get("confidence_final") is not None:
                _regime_conf_final = _eng.get("confidence_final")
                _enriched_any = True
            if _regime_signals_final is None and _eng:
                _regime_signals_final = {
                    "ADX":              _eng.get("ADX"),
                    "adx_slope":        _eng.get("adx_slope"),
                    "plus_di":          _eng.get("plus_di"),
                    "minus_di":         _eng.get("minus_di"),
                    "EMA_state":        _eng.get("EMA_state"),
                    "winning_score":    _eng.get("winning_score"),
                    "score_margin":     _eng.get("score_margin"),
                    "runner_up_regime": _eng.get("runner_up_regime"),
                }
                _enriched_any = True
            if _enriched_any and _regime_source_final is None:
                _regime_source_final = "engine_enriched_at_log"
        except Exception as _enrich_exc:
            _log.warning(
                "[signal_logger] regime enrichment failed (writing pre-enrichment values): %s",
                _enrich_exc,
            )

        # ── FXi + grid telemetry stamp (OBSERVABLE-ONLY, added 2026-07-14) ──
        # Cache-first per-pair read of today's FXi plan (fxi_briefing_reader)
        # plus pair-independent grid distances from entry. No gate, no veto,
        # no sizing input — every field is capture-only. Failure => nulls, one
        # warning, never blocks a fire.
        _fxi_direction_agree: Optional[bool] = None
        _fxi_dist_to_level_pips: Optional[float] = None
        _fxi_confidence = None
        _fxi_state = None
        _fxi_levels_source = None
        _dist_to_00_pips: Optional[float] = None
        _dist_to_0050_pips: Optional[float] = None
        _fxi_plan_entry: Optional[float] = None
        _fxi_plan_stop: Optional[float] = None
        _fxi_plan_target: Optional[float] = None
        _fxi_plan_state: Optional[str] = None
        _fxi_plan_rr: Optional[float] = None
        _fxi_dist_from_entry_pips: Optional[float] = None
        try:
            if entry_price is not None:
                _ep = float(entry_price)
                _mod100 = _ep % 100.0
                _mod050 = _ep % 50.0
                _dist_to_00_pips = round(min(_mod100, 100.0 - _mod100), 2)
                _dist_to_0050_pips = round(min(_mod050, 50.0 - _mod050), 2)

            import fxi_briefing_reader as _fxi_reader
            _plan = _fxi_reader.get_today_plan(pair)
            if isinstance(_plan, dict):
                _plan_dir = str(_plan.get("direction") or "").upper()
                if direction in ("BUY", "SELL") and _plan_dir in ("BUY", "SELL"):
                    _fxi_direction_agree = (direction == _plan_dir)
                _fxi_confidence = _plan.get("confidence")
                _fxi_state = _plan.get("state")
                _fxi_levels_source = _plan.get("levels_source")

                _all_levels: List[float] = []
                for _lvl in (_plan.get("support_levels") or []):
                    try:
                        _all_levels.append(float(_lvl))
                    except (TypeError, ValueError):
                        pass
                for _lvl in (_plan.get("resistance_levels") or []):
                    try:
                        _all_levels.append(float(_lvl))
                    except (TypeError, ValueError):
                        pass
                if _all_levels and pip_size and entry_price is not None:
                    _fxi_dist_to_level_pips = round(
                        min(abs(float(entry_price) - lp) for lp in _all_levels) / float(pip_size),
                        2,
                    )

                # Plan verbatim (v5_fxi jsonb → reader → here). STAND_ASIDE
                # plans usually carry None for entry/stop/target — leave the
                # tag stamped so the row is still explainable.
                _pv = _plan.get("plan_entry")
                _fxi_plan_entry = float(_pv) if isinstance(_pv, (int, float)) else None
                _pv = _plan.get("plan_stop")
                _fxi_plan_stop = float(_pv) if isinstance(_pv, (int, float)) else None
                _pv = _plan.get("plan_target")
                _fxi_plan_target = float(_pv) if isinstance(_pv, (int, float)) else None
                _pv = _plan.get("plan_rr")
                _fxi_plan_rr = float(_pv) if isinstance(_pv, (int, float)) else None
                _fxi_plan_state = _fxi_state

                # Signed distance: positive => fire entry is FURTHER in the
                # plan's direction than plan entry (chasing); negative =>
                # better price than plan. Direction of the FIRE governs sign.
                if (
                    _fxi_plan_entry is not None
                    and pip_size
                    and entry_price is not None
                    and direction in ("BUY", "SELL")
                ):
                    _raw = (float(entry_price) - float(_fxi_plan_entry)) / float(pip_size)
                    _fxi_dist_from_entry_pips = round(_raw if direction == "BUY" else -_raw, 2)
        except Exception as _fxi_exc:
            _log.warning(
                "[signal_logger] fxi/grid stamp failed (nulls preserved): %s",
                _fxi_exc,
            )

        # ── Stretch-from-EMA_21 stamp (OBSERVABLE-ONLY, added 2026-07-15) ──
        # Independent guard: a df_5m read failure must not null the fxi/grid
        # fields above. Reads the same EMA_21 / ATR_14 columns strategies
        # already consume; guarded for missing cols / short df / NaN tail.
        _ema21_at_fire: Optional[float] = None
        _atr_at_fire: Optional[float] = None
        _stretch_atr_at_fire: Optional[float] = None
        try:
            if df_5m is not None and not df_5m.empty:
                if "EMA_21" in df_5m.columns:
                    _v = df_5m["EMA_21"].iloc[-1]
                    if pd.notna(_v):
                        _ema21_at_fire = float(_v)
                if "ATR_14" in df_5m.columns:
                    _v = df_5m["ATR_14"].iloc[-1]
                    if pd.notna(_v):
                        _atr_at_fire = float(_v)
                if (
                    _ema21_at_fire is not None
                    and _atr_at_fire is not None
                    and _atr_at_fire > 0
                    and entry_price is not None
                ):
                    _stretch_atr_at_fire = round(
                        abs(float(entry_price) - _ema21_at_fire) / _atr_at_fire, 3
                    )
        except Exception as _stretch_exc:
            _log.warning(
                "[signal_logger] stretch/ema/atr stamp failed (nulls preserved): %s",
                _stretch_exc,
            )

        # ── Day-type telemetry stamp (2026-07-16, OBSERVABLE-ONLY, Part D) ──
        # Session/day context computed live from df_5m and the news calendar
        # so post-hoc analysis can bucket fires by day-type without joining
        # to the journal's EOD summary. Same fail-safe pattern as the FXi
        # block above: each field nulls independently, one warning on
        # unexpected failure, no re-raise into the fire path.
        _session_name: Optional[str] = None
        _session_action_so_far: Optional[str] = None
        _session_adx: Optional[float] = None
        _session_er: Optional[float] = None
        _session_bbw_pips: Optional[float] = None
        _day_range_so_far_pips: Optional[float] = None
        _day_net_so_far_pips: Optional[float] = None
        _day_news_tier: Optional[str] = None
        try:
            _session_name = _day_session_name(now_utc)
            if df_5m is not None and not df_5m.empty and pip_size:
                sess_df = _session_frame(df_5m, now_utc)
                if sess_df is not None and not sess_df.empty:
                    if "ADX_14" in sess_df.columns:
                        _session_adx = _last_num(sess_df["ADX_14"])
                    if "close" in sess_df.columns:
                        _session_er = _kaufman_er_from_closes(sess_df["close"], 10)
                    _bbw_col = next(
                        (c for c in sess_df.columns if c.startswith("BB_WIDTH_20")),
                        None,
                    )
                    if _bbw_col is not None:
                        _v = _last_num(sess_df[_bbw_col])
                        _session_bbw_pips = round(_v / float(pip_size), 2) \
                            if _v is not None else None
                    _bbw_slope = _bbw_pips_slope_from_column(sess_df, pip_size, 6)
                    _session_action_so_far = _classify_market_action(
                        _session_adx, _session_er, _bbw_slope,
                    )

                today_df = _today_candles(df_5m, now_utc)
                if not today_df.empty and "open" in today_df.columns \
                        and "high" in today_df.columns and "low" in today_df.columns \
                        and "close" in today_df.columns:
                    try:
                        _day_open = float(today_df.iloc[0]["open"])
                        _day_high = float(
                            pd.to_numeric(today_df["high"], errors="coerce").max()
                        )
                        _day_low = float(
                            pd.to_numeric(today_df["low"], errors="coerce").min()
                        )
                        _day_close = float(today_df.iloc[-1]["close"])
                        _day_range_so_far_pips = round(
                            (_day_high - _day_low) / float(pip_size), 2,
                        )
                        _day_net_so_far_pips = round(
                            (_day_close - _day_open) / float(pip_size), 2,
                        )
                    except Exception:
                        pass
        except Exception as _dtype_exc:
            _log.warning(
                "[signal_logger] day-type stamp failed (nulls preserved): %s",
                _dtype_exc,
            )
        # News tier is an independent read — guard separately so a df_5m
        # failure above doesn't null the news read (or vice-versa).
        try:
            _day_news_tier = _day_news_tier_for(now_utc)
        except Exception as _news_exc:
            _log.warning(
                "[signal_logger] day_news_tier read failed (null preserved): %s",
                _news_exc,
            )

        _eng_unstable = (
            bool(_eng.get("tiebreak_fired") or _eng.get("vol_override_fired"))
            if _eng else None
        )
        # Phase 3 profile stamp — read from EPIC_STATE keyed by
        # pos_key "{epic}|{MODE}" populated by trade_executor.
        # _stamp_profile_at_fire on ACCEPTED. Bare-epic lookup misses:
        # EPIC_STATE is keyed by pos_key (trade_executor._pos_key),
        # so profile_id was stamped null in signal_log 07-15 despite
        # STRONG manager actually running (07-16 audit).
        _profile_id = None
        _regime_at_fire_effective = None
        try:
            import trade_executor as _te
            _mode_for_pk = str(getattr(decision, "mode", "") or "DEFAULT").strip().upper() or "DEFAULT"
            _pk_for_state = f"{epic}|{_mode_for_pk}"
            _st = _te.EPIC_STATE.get(_pk_for_state) or {}
            if not _st:
                # Fallback: scan any active position on this epic. Covers
                # BB_REVERSAL pyramid pos_keys ("{MODE}_{ts}") whose exact
                # suffix isn't reconstructable from decision.mode alone.
                _prefix = f"{epic}|"
                for _k, _v in _te.EPIC_STATE.items():
                    if _k.startswith(_prefix) and (_v.get("active") or _v.get("pending_open")):
                        _st = _v
                        break
            _profile_id = _st.get("profile_id")
            _regime_at_fire_effective = _st.get("regime_at_fire_effective")
        except Exception:
            pass

        record: Dict[str, Any] = {
            "id": trade_id,
            "deal_id": str(deal_id) if deal_id else None,
            "timestamp_open": now_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "epic": epic,
            "pair": pair,
            "direction": direction,
            "strategy": str(getattr(decision, "mode", "") or ""),
            "fire_path": _fire_path,
            "entry": round(entry_price, 5),
            "entry_price_source": str(entry_price_source),
            "sl": sl_price,
            "sl_pips": sl_pips,
            "tp1": tp_price,
            "tp1_pips": tp_pips,
            "cascade_stable_at_fire": _rs.get("cascade_stable_at_fire"),
            "shadow_vote_label_at_fire": _rs.get("shadow_vote_label_at_fire"),
            "shadow_vote_confidence_at_fire": _rs.get("shadow_vote_confidence_at_fire"),
            "axis_confidence_direction": _rs.get("axis_confidence_direction"),
            "axis_confidence_structure": _rs.get("axis_confidence_structure"),
            # Regime router stamp — populated when regime_router_engine.dispatch
            # opened this trade. Strategies that don't route via the router
            # leave these null (backwards compatible).
            "regime_instance_id":         _regime_iid_final,
            "regime_at_fire":             _regime_at_fire_final,
            "regime_confidence_at_fire":  _regime_conf_final,
            # Regime-tag instrumentation (added 2026-06-01) — populated by
            # strategies that capture gbpusd_regime_detector verdict into
            # decision.debug. Null for strategies not yet wired.
            "regime_signals":              _regime_signals_final,
            "regime_source":               _regime_source_final,
            "regime_classified_at_bar_ts": dbg.get("regime_classified_at_bar_ts") if isinstance(dbg, dict) else None,
            # Engine-regime capture (additive, 2026-06-23). Reads
            # regime_engine.latest_result(pair) — the same module cache
            # gbpusd_structure_break and gbpusd_ema_pullback already use.
            # engine_regime_bar_ts records the bar the label was computed
            # on so staleness (up to ~5m between closes) is visible to
            # analysis. GATES NOTHING.
            "engine_regime_at_fire":             _eng.get("winning_regime"),
            "engine_regime_confidence_at_fire":  _eng.get("confidence_final"),
            "engine_regime_bias_at_fire":        _eng.get("directional_bias"),
            # Phase 3 profile stamp (regime_matrix.effective_regime →
            # profile_id) — populated by trade_executor at fire when
            # REGIME_MGMT_ENABLED=1; null otherwise.
            "profile_id":                        _profile_id,
            "regime_at_fire_effective":          _regime_at_fire_effective,
            "engine_regime_margin_at_fire":      _eng.get("score_margin"),
            "engine_regime_unstable_at_fire":    _eng_unstable,
            "engine_regime_bar_ts":              _eng.get("timestamp"),
            "regime_label_path":                 _eng.get("regime_label_path"),
            "hist_freshness_downgraded":         _eng.get("hist_freshness_downgraded"),
            # EMA_PULLBACK fan-gate instrumentation (added 2026-06-01).
            # Captures the gated values so post-fire analysis can
            # correlate fan/squeeze with outcome. Null for strategies not
            # using the fan gate.
            "fan_width_pips_at_fire":      dbg.get("fan_width_pips_at_fire") if isinstance(dbg, dict) else None,
            "bb_squeeze_at_fire":          dbg.get("bb_squeeze_at_fire") if isinstance(dbg, dict) else None,
            "router_direction":           dbg.get("router_direction") if isinstance(dbg, dict) else None,
            "level_price": level_price,
            "level_source": level_source,
            "level_major": level_major,
            # FXi + grid telemetry (added 2026-07-14, OBSERVABLE-ONLY).
            "fxi_direction_agree":     _fxi_direction_agree,
            "fxi_dist_to_level_pips":  _fxi_dist_to_level_pips,
            "fxi_confidence":          _fxi_confidence,
            "fxi_state":               _fxi_state,
            "fxi_levels_source":       _fxi_levels_source,
            "dist_to_00_pips":         _dist_to_00_pips,
            "dist_to_0050_pips":       _dist_to_0050_pips,
            # Level-distance telemetry (2026-07-18, OBSERVABLE-ONLY).
            # Raw floats are the primary record; `at_level` is derived from
            # `dist_to_nearest_level_pips <= at_level_threshold_pips` and can
            # be re-derived at analysis time with a different threshold.
            # Originally BB_BOUNCE-only; extended to STRUCTURE_BREAK on
            # 2026-07-24 via the shared level_telemetry module (called from
            # both CHASE and RETEST-fill build sites). Null for strategies
            # that don't populate the debug keys.
            "dist_to_pdh_pips":            dbg.get("dist_to_pdh_pips") if isinstance(dbg, dict) else None,
            "dist_to_pdl_pips":            dbg.get("dist_to_pdl_pips") if isinstance(dbg, dict) else None,
            "dist_to_nearest_level_pips":  dbg.get("dist_to_nearest_level_pips") if isinstance(dbg, dict) else None,
            "nearest_level_type":          dbg.get("nearest_level_type") if isinstance(dbg, dict) else None,
            "at_level":                    dbg.get("at_level") if isinstance(dbg, dict) else None,
            "at_level_threshold_pips":     dbg.get("at_level_threshold_pips") if isinstance(dbg, dict) else None,
            # STRUCTURE_BREAK break-level fields (2026-07-24, OBSERVABLE-ONLY).
            # Persist the raw flip-bar values so the "entry path predicts
            # outcome" and "distance from break level predicts failure"
            # questions become answerable from signal_log directly. Names
            # `sb_break_pips` / `sb_atr_pips` / `sb_entry_path` are prefixed
            # to avoid colliding with row-level `atr_pips` (`:1200`, from
            # df_5m at fire time) and any future strategy-agnostic
            # entry_path. `prior_swing` / `close_at_flip` / `flip_bar_ts`
            # are unprefixed — the debug source keys already existed on SB
            # debug and no other strategy writes them. Null for
            # non-STRUCTURE_BREAK emitters.
            "prior_swing":                 dbg.get("prior_swing") if isinstance(dbg, dict) else None,
            "close_at_flip":               dbg.get("close_at_flip") if isinstance(dbg, dict) else None,
            "flip_bar_ts":                 dbg.get("flip_bar_ts") if isinstance(dbg, dict) else None,
            "sb_break_pips":               dbg.get("sb_break_pips") if isinstance(dbg, dict) else None,
            "sb_atr_pips":                 dbg.get("sb_atr_pips") if isinstance(dbg, dict) else None,
            "sb_entry_path":               dbg.get("sb_entry_path") if isinstance(dbg, dict) else None,
            # BB_BOUNCE H1 EMA-stack snapshot AT ARM TIME (2026-07-24, OBSERVABLE-ONLY).
            # gbpusd_bb_bounce.py captures h1_dir / h1_strength on each armed
            # setup (:1316-1317) but they never reached the fill row — closing
            # the WITH-H1 vs COUNTER-H1 outcome question required log-only
            # persistence. Prefixed `bb_` (same collision policy as `sb_`).
            # Null for non-BB emitters.
            "bb_h1_dir_at_arm":            dbg.get("bb_h1_dir_at_arm") if isinstance(dbg, dict) else None,
            "bb_h1_strength_at_arm":       dbg.get("bb_h1_strength_at_arm") if isinstance(dbg, dict) else None,
            # NEWS_STRATEGY telemetry (2026-07-25). Stamped by
            # news_strategy._snapshot_news_telemetry on FIRE / WOULD_FIRE /
            # REVERSAL_FIRE paths. Null for non-NEWS_STRATEGY emitters.
            "news_telemetry":              dbg.get("news_telemetry") if isinstance(dbg, dict) else None,
            # FXi plan verbatim + signed distance from plan entry (2026-07-15).
            "fxi_plan_entry":          _fxi_plan_entry,
            "fxi_plan_stop":           _fxi_plan_stop,
            "fxi_plan_target":         _fxi_plan_target,
            "fxi_plan_state":          _fxi_plan_state,
            "fxi_plan_rr":             _fxi_plan_rr,
            "fxi_dist_from_entry_pips": _fxi_dist_from_entry_pips,
            # Stretch from EMA_21, and the underlying reads (2026-07-15).
            "ema21_at_fire":           _ema21_at_fire,
            "atr_at_fire":             _atr_at_fire,
            "stretch_atr_at_fire":     _stretch_atr_at_fire,
            # Day-type telemetry (2026-07-16, Part D, OBSERVABLE-ONLY).
            "session_name":            _session_name,
            "session_action_so_far":   _session_action_so_far,
            "session_adx":             _session_adx,
            "session_er":              _session_er,
            "session_bbw_pips":        _session_bbw_pips,
            "day_range_so_far_pips":   _day_range_so_far_pips,
            "day_net_so_far_pips":     _day_net_so_far_pips,
            "day_news_tier":           _day_news_tier,
            "session": _session_from_utc_hour(now_utc.hour),
            "session_bias": briefing.get("session_expectation") if briefing else None,
            "daily_bias": briefing.get("daily_bias") if briefing else None,
            "bias_confidence": briefing.get("bias_confidence") if briefing else None,
            "ema_aligned": _ema_aligned(df_5m, direction) if has_df else None,
            "macd_direction": _macd_direction(df_5m) if has_df else None,
            "atr_pips": _atr_pips(df_5m, pip_size) if has_df else None,
            "bb_width_pips": _bb_width_pips(df_5m, pip_size) if has_df else None,
            "distance_from_level_pips": dist_pips,
            # Time context
            "minutes_since_london_open": _minutes_since_london_open(now_utc),
            "minutes_since_briefing": _minutes_since_briefing(briefing, now_utc) if briefing else None,
            # Price structure
            "price_vs_daily_open": _price_vs_daily_open(df_5m, entry_price, pip_size, now_utc) if has_df else None,
            "vwap_distance_pips": _vwap_distance_pips(df_5m, entry_price, pip_size, now_utc) if has_df else None,
            "candles_touched_today": _candles_touched_today(briefing, df_5m, pip_size, now_utc) if (has_df and briefing) else 0,
            # Candle pattern at entry
            "entry_candle_pattern": _entry_candle_pattern(df_5m) if has_df else None,
            "entry_candle_body_pct": _entry_candle_body_pct(df_5m) if has_df else None,
            "entry_candle_wick_ratio": _entry_candle_wick_ratio(df_5m) if has_df else None,
            # Volatility context
            "atr_vs_20day_avg": _atr_vs_20day_avg(df_5m, pip_size) if has_df else None,
            "bb_squeeze": _bb_squeeze(df_5m) if has_df else None,
            # Outcome (populated at close)
            "outcome": None,
        }

        # ── Execution-latency fields (optional; merged in verbatim) ───────
        # See execution_latency_metrics.FIRE_LATENCY_FIELDS for the schema.
        # Old records / callsites that don't pass `latency=` simply have
        # these fields absent → readers must treat missing as null.
        if latency:
            try:
                for _k, _v in latency.items():
                    # Only persist whitelisted latency keys to avoid
                    # accidentally widening the schema with arbitrary debug.
                    if _k in (
                        "t_decision_epoch_ms",
                        "t_dispatch_epoch_ms",
                        "t_ig_request_epoch_ms",
                        "t_ig_ack_epoch_ms",
                        "t_ig_confirm_epoch_ms",
                        "decision_to_dispatch_ms",
                        "dispatch_to_ig_request_ms",
                        "ig_request_to_ack_ms",
                        "ack_to_confirm_ms",
                        "total_decision_to_confirm_ms",
                        "ls_async_dispatch",
                    ):
                        record[_k] = _v
            except Exception:
                _log.warning("[signal_logger] log_open: latency merge failed", exc_info=True)

        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_PATH, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")

        _log.info(f"[signal_logger] open logged id={trade_id} pair={pair} dir={direction} entry={entry_price}")

    except Exception:
        _log.warning("[signal_logger] log_open failed", exc_info=True)

    # ── Confirmation-engine Phase-1 hook (telemetry-only, 2026-05-23) ─
    # Fires once per opened trade. ⚠️ FAIL-SAFE: any exception is
    # swallowed here — confirmation logging cannot affect the trade path.
    # The engine itself never calls close_position / SL-amend / sizing.
    try:
        import confirmation_engine as _conf
        _conf.record_at_entry(
            trade_id=trade_id,
            pair=pair,
            direction=direction,
            entry_price=entry_price,
            df_5m=df_5m,
            deal_id=deal_id,
            strategy=str(getattr(decision, "mode", "") or ""),
        )
    except Exception:
        _log.debug("[signal_logger] confirmation_engine Phase-1 hook failed",
                   exc_info=True)

    # ── reversal_geometry Phase-1 hook (BB_BOUNCE only, telemetry-only) ─
    # Post-fire N-bar reversal-geometry capture. record_at_entry itself
    # short-circuits for any non-BB_BOUNCE strategy. Same fail-safe wrap
    # as the confirmation_engine hook above — cannot affect trade path.
    try:
        import reversal_geometry as _rg
        _rg_entry_bar_ts = None
        try:
            if df_5m is not None and len(df_5m) > 0:
                # Mirror reversal_geometry.py:211 ts_col precedence — the
                # candle_builder payload frame uses "time" (rebuilt at
                # candle_builder.py:425), while some other df_5m sources
                # still carry "timestamp". Prefer "timestamp" when present
                # for parity with the evaluator; fall back to "time".
                _ts_col = (
                    "timestamp" if "timestamp" in df_5m.columns
                    else ("time" if "time" in df_5m.columns else None)
                )
                if _ts_col is not None:
                    _v = df_5m[_ts_col].iloc[-1]
                    _rg_entry_bar_ts = (
                        _v.isoformat() if hasattr(_v, "isoformat") else str(_v)
                    )
        except Exception:
            _rg_entry_bar_ts = None
        _rg.record_at_entry(
            trade_id=trade_id,
            pair=pair,
            direction=direction,
            entry_price=entry_price,
            entry_bar_ts=_rg_entry_bar_ts,
            debug_dict=dbg,
            deal_id=deal_id,
            strategy=str(getattr(decision, "mode", "") or ""),
        )
    except Exception:
        _log.debug("[signal_logger] reversal_geometry Phase-1 hook failed",
                   exc_info=True)


def log_partial(
    trade_id: str,
    partial_pnl_pips: float,
    partial_exit_price: Optional[float],
    partial_ts: str,
    runner_size: float,
    runner_sl_price: float,
    partial_fill_estimated: bool = False,
) -> None:
    """Patch an open record with scale-out / partial-bank fields.

    Does NOT set `outcome` — the record stays open and log_close patches
    the runner's eventual close later. Together they give a complete
    OUTCOME JOIN: partial_bank_pips (this call) + runner pnl (log_close)
    = total_pnl_pips (computed by log_close).

    `partial_fill_estimated` flags the case where IG's confirm response
    lacked a "level" and partial_exit_price was sourced from last_mid
    (stale-mid fallback). When True, total_pnl_pips on the eventual
    closed record is APPROXIMATE — clean-run analysis should filter on
    this flag (exclude or treat-as-estimate).

    Idempotent within a single open record (re-firing would just overwrite
    with the same values; the trade_manager guard prevents double-fire
    upstream anyway).
    """
    try:
        if not LOG_PATH.exists():
            _log.warning(f"[signal_logger] log_partial: {LOG_PATH} does not exist, id={trade_id}")
            return
        raw = LOG_PATH.read_text(encoding="utf-8")
        lines = raw.splitlines()
        updated = False
        out_lines = []
        for line in lines:
            stripped = line.strip()
            if not stripped:
                out_lines.append(stripped)
                continue
            try:
                rec = json.loads(stripped)
            except json.JSONDecodeError:
                out_lines.append(stripped)
                continue
            if rec.get("id") == trade_id and rec.get("outcome") is None:
                rec.update({
                    "scaled_out":               True,
                    "partial_bank_pips":        round(float(partial_pnl_pips), 2),
                    "partial_bank_ts":          str(partial_ts),
                    "partial_exit_price":       round(float(partial_exit_price), 5) if partial_exit_price is not None else None,
                    "runner_size":              round(float(runner_size), 2),
                    "runner_sl_price":          round(float(runner_sl_price), 5),
                    # Honesty flag: True ⇒ partial_exit_price came from
                    # last_mid (no broker level in IG confirm), so
                    # partial_bank_pips — and the downstream
                    # total_pnl_pips on log_close — is APPROXIMATE.
                    "partial_fill_estimated":   bool(partial_fill_estimated),
                })
                updated = True
            out_lines.append(json.dumps(rec))
        if updated:
            LOG_PATH.write_text("\n".join(out_lines) + "\n", encoding="utf-8")
            _log.info(f"[signal_logger] partial logged id={trade_id} bank={partial_pnl_pips:+.2f}p runner_size={runner_size}")
        else:
            _log.warning(f"[signal_logger] log_partial: no open record found for id={trade_id}")
    except Exception:
        _log.warning("[signal_logger] log_partial failed", exc_info=True)


def log_close(
    trade_id: str,
    close_price: Optional[float],
    pnl_pips: Optional[float],
    reason: str,
    df_5m: Optional[pd.DataFrame] = None,
    latency: Optional[Dict[str, Any]] = None,
) -> None:
    """Find the open record by id and patch it with outcome fields.

    latency, if provided, is a dict produced by
    execution_latency_metrics.build_exit_latency_record(...) — its keys
    are merged into the patched record.  All fields are optional and
    default to None so callers that haven't been updated yet still work.
    """
    try:
        if not LOG_PATH.exists():
            _log.warning(f"[signal_logger] log_close: {LOG_PATH} does not exist, id={trade_id}")
            return

        now_utc = datetime.now(timezone.utc)
        ts_close = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")

        raw = LOG_PATH.read_text(encoding="utf-8")
        lines = raw.splitlines()

        updated = False
        out_lines = []
        for line in lines:
            stripped = line.strip()
            if not stripped:
                out_lines.append(stripped)
                continue
            try:
                rec = json.loads(stripped)
            except json.JSONDecodeError:
                out_lines.append(stripped)
                continue

            if rec.get("id") == trade_id and rec.get("outcome") is None:
                # Duration
                duration_minutes = None
                open_ts: Optional[datetime] = None
                try:
                    ts_open_str = rec["timestamp_open"]
                    open_ts = datetime.fromisoformat(ts_open_str.replace("Z", "+00:00"))
                    ts_c = datetime.fromisoformat(ts_close.replace("Z", "+00:00"))
                    duration_minutes = int((ts_c - open_ts).total_seconds() / 60)
                except Exception:
                    pass

                # MAE / MFE
                mae_pips = mfe_pips = mfe_vs_tp1_pct = None
                if df_5m is not None and not df_5m.empty:
                    try:
                        direction  = rec.get("direction", "BUY")
                        entry      = float(rec.get("entry") or close_price or 0)
                        pip_size   = 1.0
                        # Infer pip_size from sl_pips / sl prices if available
                        _sl        = rec.get("sl")
                        _sl_pips   = rec.get("sl_pips")
                        if _sl and _sl_pips and float(_sl_pips) > 0:
                            pip_size = abs(float(_sl) - entry) / float(_sl_pips)
                        if pip_size <= 0 or not math.isfinite(pip_size):
                            pip_size = 1.0

                        mae_pips, mfe_pips = _mae_mfe(df_5m, direction, entry, pip_size, open_ts)

                        tp1_pips = rec.get("tp1_pips")
                        if mfe_pips is not None and tp1_pips and float(tp1_pips) > 0:
                            mfe_vs_tp1_pct = round(mfe_pips / float(tp1_pips) * 100.0, 1)
                    except Exception:
                        pass

                # Scale-out OUTCOME JOIN integrity: if log_partial previously
                # patched this record with partial_bank_pips, this close
                # represents the runner only. Compute total_pnl_pips =
                # partial_bank + runner_pnl so per-regime expectancy in the
                # learning loop reflects the FULL trade, not half.
                _partial_bank = rec.get("partial_bank_pips")
                _runner_pnl = float(pnl_pips) if pnl_pips is not None else 0.0
                _total_pnl = _runner_pnl + (float(_partial_bank) if _partial_bank is not None else 0.0)
                # Honesty flag: when partial_fill_estimated is True the
                # partial_bank_pips (and therefore total_pnl_pips) was
                # computed from last_mid as a fallback, not a real broker
                # fill. Clean-run / per-regime expectancy analysis on
                # total_pnl_pips should filter on this flag (exclude or
                # treat-as-estimate). The total_pnl_pips computation itself
                # is unchanged — the flag is additive.
                _partial_fill_estimated = bool(rec.get("partial_fill_estimated", False))

                rec.update({
                    "outcome": _outcome_label(reason),
                    "timestamp_close": ts_close,
                    "close_price": round(float(close_price), 5) if close_price is not None else None,
                    "pnl_pips": round(float(pnl_pips), 2) if pnl_pips is not None else None,
                    # Diagnostic split (null when not scaled).
                    "runner_pnl_pips": round(_runner_pnl, 2) if _partial_bank is not None else None,
                    # Combined trade outcome — THE field per-regime expectancy
                    # should be computed on. Equal to pnl_pips when not scaled.
                    # APPROXIMATE when partial_fill_estimated=True (filter
                    # downstream on that flag).
                    "total_pnl_pips": round(_total_pnl, 2),
                    "partial_fill_estimated": _partial_fill_estimated,
                    "duration_minutes": duration_minutes,
                    "close_reason": reason,
                    "close_type": _close_type(reason),
                    "mae_pips": mae_pips,
                    "mfe_pips": mfe_pips,
                    "mfe_vs_tp1_pct": mfe_vs_tp1_pct,
                    "time_in_trade_minutes": duration_minutes,
                })

                # Exit-path latency fields (optional; merged in verbatim).
                # Whitelisted to keep the schema disciplined.
                if latency:
                    try:
                        for _k, _v in latency.items():
                            if _k in (
                                "t_exit_trigger_epoch_ms",
                                "t_exit_dispatch_epoch_ms",
                                "t_exit_confirm_epoch_ms",
                                "trigger_to_dispatch_ms",
                                "dispatch_to_confirm_ms",
                                "total_trigger_to_confirm_ms",
                                "ls_async_dispatch",
                            ):
                                rec[_k] = _v
                    except Exception:
                        _log.warning(
                            "[signal_logger] log_close: latency merge failed",
                            exc_info=True,
                        )

                updated = True

            out_lines.append(json.dumps(rec))

        if updated:
            LOG_PATH.write_text("\n".join(out_lines) + "\n", encoding="utf-8")
            _log.info(f"[signal_logger] close logged id={trade_id} reason={reason} pnl={pnl_pips}")
        else:
            _log.warning(f"[signal_logger] log_close: no open record found for id={trade_id}")

    except Exception:
        _log.warning("[signal_logger] log_close failed", exc_info=True)
