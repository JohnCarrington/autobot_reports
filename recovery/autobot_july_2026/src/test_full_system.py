#!/usr/bin/env python3
"""
test_full_system.py — Full system replay test.

Stage 1: Data loaders (load_candles, load_briefings, list_available_dates)
Stage 2: Signal replay engine (replay_session, simulate_outcome, validate_signal)
"""

import os
import sys
import json
import glob
import re
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd
from dotenv import load_dotenv

sys.path.insert(0, "/opt/tradingbot")
os.chdir("/opt/tradingbot")

load_dotenv()

LOG_DIR = Path("/opt/tradingbot/logs")
CACHE_DIR = Path("/opt/tradingbot/cache")
PAIRS = ["GBPUSD", "EURUSD", "USDJPY", "USDCAD"]
SESSIONS = ["Asian", "London", "Mid-session", "NY"]

CANDLE_EPICS = json.loads(os.getenv("EPICS_JSON", '{}')) or {
    "GBPUSD": "CS.D.GBPUSD.TODAY.IP",
    "EURUSD": "CS.D.EURUSD.TODAY.IP",
    "USDJPY": "CS.D.USDJPY.TODAY.IP",
    "USDCAD": "CS.D.USDCAD.TODAY.IP",
}


def _get_ig_session():
    """Lazy-load and cache IG session."""
    if not hasattr(_get_ig_session, "_cached"):
        from ig_auth import get_ig_session
        _get_ig_session._cached = get_ig_session()
    return _get_ig_session._cached


def _cache_path(pair: str, date: str) -> Path:
    return CACHE_DIR / f"test_candles_{pair}_{date}.json"


def load_candles(pair: str, date: str) -> list[dict]:
    """Load 5m candles for a pair on a given date.

    Checks local cache first; if missing, fetches from IG REST API
    and caches to /opt/tradingbot/cache/test_candles_{pair}_{date}.json.

    Returns list of dicts with keys: timestamp, open, high, low, close.
    """
    cache_file = _cache_path(pair, date)

    # Return from cache if available
    if cache_file.exists():
        with open(cache_file) as f:
            return json.load(f)

    # Fetch from IG API
    ig, _headers, _acc = _get_ig_session()
    epic = CANDLE_EPICS.get(pair.upper())
    if not epic:
        raise ValueError(f"Unknown pair: {pair}")

    start = f"{date} 00:00:00"
    end = f"{date} 23:59:59"

    try:
        hist = ig.fetch_historical_prices_by_epic_and_date_range(
            epic, "MINUTE_5", start, end
        )
    except Exception as e:
        # No data for this date (weekend / holiday)
        candles = []
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        with open(cache_file, "w") as f:
            json.dump(candles, f)
        return candles

    # Normalise response to list of candle dicts
    candles = _normalize_hist(hist)

    # Cache result
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    with open(cache_file, "w") as f:
        json.dump(candles, f)

    return candles


def _normalize_hist(hist) -> list[dict]:
    """Extract candle rows from IG historical response (multiple formats)."""
    # Try DataFrame-style response first (trading_ig often returns allowance + prices)
    prices_df = None
    if isinstance(hist, tuple):
        for item in hist:
            if isinstance(item, pd.DataFrame) and not item.empty:
                prices_df = item
                break
    elif isinstance(hist, pd.DataFrame):
        prices_df = hist
    elif isinstance(hist, dict):
        if "prices" in hist:
            raw = hist["prices"]
            if isinstance(raw, pd.DataFrame):
                prices_df = raw
            elif isinstance(raw, list):
                return _normalize_price_list(raw)

    if prices_df is not None:
        return _df_to_candles(prices_df)

    # Last resort: look for list of price dicts
    if isinstance(hist, list):
        return _normalize_price_list(hist)

    return []


def _df_to_candles(df: pd.DataFrame) -> list[dict]:
    """Convert a prices DataFrame to list of candle dicts."""
    # Handle multi-level columns: (bid/ask/last, Open/High/Low/Close/Volume)
    # Compute mid = (bid + ask) / 2 for each OHLC field
    if isinstance(df.columns, pd.MultiIndex):
        mid_data = {}
        for ohlc in ["Open", "High", "Low", "Close"]:
            bid_val = df[("bid", ohlc)]
            ask_val = df[("ask", ohlc)]
            mid_data[ohlc.lower()] = (bid_val + ask_val) / 2.0
        df = pd.DataFrame(mid_data, index=df.index)
    else:
        # Normalise column names for flat columns
        col_map = {}
        for col in df.columns:
            cl = str(col).lower().replace(" ", "")
            if "open" in cl:
                col_map[col] = "open"
            elif "high" in cl:
                col_map[col] = "high"
            elif "low" in cl:
                col_map[col] = "low"
            elif "close" in cl:
                col_map[col] = "close"
        df = df.rename(columns=col_map)

    # Timestamp from index or column
    if "timestamp" not in df.columns and "DateTime" not in df.columns:
        df = df.reset_index()
    if "DateTime" in df.columns:
        df = df.rename(columns={"DateTime": "timestamp"})

    ts_col = "timestamp" if "timestamp" in df.columns else df.columns[0]

    rows = []
    for _, row in df.iterrows():
        try:
            ts = str(row[ts_col])
            rows.append({
                "timestamp": ts,
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
            })
        except (KeyError, ValueError, TypeError):
            continue
    return rows


def _normalize_price_list(prices: list) -> list[dict]:
    """Convert IG raw price list (list of dicts) to candle dicts."""
    rows = []
    for p in prices:
        if not isinstance(p, dict):
            continue
        ts = (p.get("snapshotTimeUTC") or p.get("snapshotTime")
              or p.get("timestamp") or p.get("time"))

        def _mid(x, fallback_key):
            if isinstance(x, dict):
                return x.get("mid")
            return p.get(fallback_key)

        o = _mid(p.get("openPrice"), "open")
        h = _mid(p.get("highPrice"), "high")
        l = _mid(p.get("lowPrice"), "low")
        c = _mid(p.get("closePrice"), "close")
        if c is None:
            continue
        rows.append({
            "timestamp": str(ts),
            "open": float(o),
            "high": float(h),
            "low": float(l),
            "close": float(c),
        })
    return rows


def load_briefings(date: str) -> dict:
    """Load all briefing JSONs for a given date across all pairs and sessions.

    Returns dict keyed by "{pair}_{session}" with the parsed JSON as value.
    """
    result = {}
    for pair in PAIRS:
        for session in SESSIONS:
            path = LOG_DIR / f"briefing_{pair}_{date}_{session}.json"
            if path.exists():
                with open(path) as f:
                    result[f"{pair}_{session}"] = json.load(f)
    return result


def list_available_dates() -> list[str]:
    """Scan briefing logs for dates that have at least one GBPUSD London briefing.

    Returns sorted list of date strings (YYYY-MM-DD).
    """
    pattern = str(LOG_DIR / "briefing_GBPUSD_*_London.json")
    files = glob.glob(pattern)
    dates = set()
    for f in files:
        m = re.search(r"briefing_GBPUSD_(\d{4}-\d{2}-\d{2})_London\.json", f)
        if m:
            dates.add(m.group(1))
    return sorted(dates)


# ============================================================
# STAGE 2 — Signal replay engine
# ============================================================

PIP_SIZE = 1.0  # All spread-bet pairs on IG

SPREAD_EPICS = {
    "GBPUSD": "CS.D.GBPUSD.TODAY.IP",
    "EURUSD": "CS.D.EURUSD.TODAY.IP",
    "USDJPY": "CS.D.USDJPY.TODAY.IP",
    "USDCAD": "CS.D.USDCAD.TODAY.IP",
}

# Session time windows (UTC) — BST-aware
SESSION_WINDOWS = {
    "Asian":       (0, 0, 6, 30),    # 00:00 – 06:30
    "London":      (6, 30, 10, 45),  # 06:30 – 10:45 (GMT); 05:30 – 09:45 (BST)
    "Mid-session": (10, 45, 13, 0),  # 10:45 – 13:00 (GMT); 09:45 – 12:00 (BST)
    "NY":          (13, 0, 18, 0),   # 13:00 – 18:00 (GMT); 12:00 – 17:00 (BST)
}

TRAIL_CONFIG = {
    "BRIEFING_LIQUIDITY": {"arm_pips": 5, "floor_pips": 2, "trail_ratio": 0.5},
    "BRIEFING_SWEEP":     {"arm_pips": 20, "floor_pips": 10, "trail_ratio": 0.5},
}

# Trend-hold mode config — disabled after replay showed -112p regression.
# Briefing-level trades are short bounces (5-15 pip MFE), not trending runs.
# The tight trail (arm 5, floor 2) correctly captures these.
TREND_HOLD_ENABLED = False
TREND_HOLD_MIN_CONFIDENCE = 0.68
TREND_HOLD_TP1_ARM_PCT = 0.40
TREND_HOLD_OFFSET_PIPS = 10.0
TREND_HOLD_TRAIL_RATIO = 0.5

# Wide-TP trail: TP1 distance determines trail behaviour
WIDE_TP_THRESHOLD_PIPS = 999.0  # disabled — tight trail outperforms at all thresholds tested
WIDE_ARM_PCT = 0.30
WIDE_FLOOR_PCT = 0.15
WIDE_TRAIL_PCT = 0.20

WARMUP_CANDLES = 60

logger = logging.getLogger("ReplayTest")


def _is_bst(dt: datetime) -> bool:
    """Check if a date falls in BST (last Sunday in March to last Sunday in October)."""
    year = dt.year
    # Last Sunday in March
    mar31 = datetime(year, 3, 31, tzinfo=timezone.utc)
    bst_start = mar31 - timedelta(days=mar31.weekday() + 1) if mar31.weekday() != 6 else mar31
    bst_start = bst_start.replace(hour=1)
    # Last Sunday in October
    oct31 = datetime(year, 10, 31, tzinfo=timezone.utc)
    bst_end = oct31 - timedelta(days=oct31.weekday() + 1) if oct31.weekday() != 6 else oct31
    bst_end = bst_end.replace(hour=1)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return bst_start <= dt < bst_end


def _session_time_range(date_str: str, session_name: str) -> tuple:
    """Return (start_dt, end_dt) in UTC for a session on a given date."""
    y, m, d = map(int, date_str.split("-"))
    base = datetime(y, m, d, tzinfo=timezone.utc)
    bst = _is_bst(base)
    bst_shift = -1 if bst else 0  # BST sessions start 1hr earlier in UTC

    sh, sm, eh, em = SESSION_WINDOWS[session_name]
    if session_name != "Asian":
        sh += bst_shift
        eh += bst_shift
    start = base.replace(hour=sh, minute=sm)
    end = base.replace(hour=eh, minute=em)
    return start, end


def enrich_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Add EMA, MACD, BB, ATR indicators needed by strategies."""
    if len(df) < 5:
        return df

    closes = df["close"].astype(float)

    # EMAs
    for period in [8, 13, 21, 50, 200]:
        df[f"EMA_{period}"] = closes.ewm(span=period, adjust=False).mean()

    # MACD (35, 45, 30)
    ema35 = closes.ewm(span=35, adjust=False).mean()
    ema45 = closes.ewm(span=45, adjust=False).mean()
    macd_line = ema35 - ema45
    signal_line = macd_line.ewm(span=30, adjust=False).mean()
    macd_hist = macd_line - signal_line
    df["MACD_35_45"] = macd_line
    df["MACD_SIGNAL_35_45_30"] = signal_line
    df["MACD_HIST_35_45_30"] = macd_hist
    df["MACD_35_45_DELTA"] = macd_line.diff()
    df["MACD_HIST_35_45_30_DELTA"] = macd_hist.diff()
    df["MACD_HIST_35_45_30_DECEL2"] = macd_hist.diff().diff()
    df["MACD_HIST_35_45_30_DECREASING2"] = (macd_hist.diff() < 0) & (macd_hist.diff().shift(1) < 0)

    # EMA slopes
    df["EMA_50_SLOPE"] = df["EMA_50"].diff()

    # Bollinger Bands (20, 2)
    bb_mid = closes.rolling(20).mean()
    bb_std = closes.rolling(20).std()
    df["BB_MID_20"] = bb_mid
    df["BB_UPPER_20_2"] = bb_mid + 2 * bb_std
    df["BB_LOWER_20_2"] = bb_mid - 2 * bb_std
    bb_width = (df["BB_UPPER_20_2"] - df["BB_LOWER_20_2"]) / bb_mid
    df["BB_WIDTH_20_2"] = bb_width
    df["BB_WIDTH_DELTA_20_2"] = bb_width.diff()
    df["BB_WIDTH_EXPANDING_20_2"] = bb_width.diff() > 0
    df["BB_WIDTH_CONTRACTING_20_2"] = bb_width.diff() < 0
    df["BB_WIDTH_FLAT_20_2"] = bb_width.diff().abs() < 0.00001
    df["BB_UPPER_SLOPE_20_2"] = df["BB_UPPER_20_2"].diff()
    df["BB_LOWER_SLOPE_20_2"] = df["BB_LOWER_20_2"].diff()
    df["BB_MID_SLOPE_20"] = bb_mid.diff()
    df["BB_UPPER_SLOPE_20_2_DELTA"] = df["BB_UPPER_SLOPE_20_2"].diff()
    df["BB_LOWER_SLOPE_20_2_DELTA"] = df["BB_LOWER_SLOPE_20_2"].diff()

    # RSI (3)
    delta = closes.diff()
    gain = delta.clip(lower=0).ewm(span=3, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(span=3, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    df["RSI_3"] = 100 - (100 / (1 + rs))
    df["RSI_3_DELTA"] = df["RSI_3"].diff()

    # ATR (14)
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    prev_close = closes.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    df["ATR_14"] = tr.ewm(span=14, adjust=False).mean()

    # Aroon (14)
    window = 14
    df["AROON_UP_14"] = high.rolling(window + 1).apply(lambda x: x.argmax() / window * 100, raw=True)
    df["AROON_DOWN_14"] = low.rolling(window + 1).apply(lambda x: x.argmin() / window * 100, raw=True)

    return df


def _build_rc_all(df: pd.DataFrame, idx: int) -> list:
    """Build rc_all (rich candle list) for BriefingSweep from DataFrame slice."""
    rc_start = max(0, idx - 5)
    rc = []
    for j in range(rc_start, idx + 1):
        row = df.iloc[j]
        candle = {
            "open": float(row["open"]),
            "high": float(row["high"]),
            "low": float(row["low"]),
            "close": float(row["close"]),
        }
        indicators = {}
        for col in df.columns:
            if col in ("open", "high", "low", "close", "timestamp"):
                continue
            val = row[col]
            try:
                fv = float(val)
                if np.isfinite(fv):
                    indicators[col] = fv
            except (TypeError, ValueError):
                pass
        rc.append({"candle": candle, "indicators": indicators})
    return rc


@dataclass
class Signal:
    time: str
    strategy: str
    direction: str
    entry: float
    entry_type: str
    level: Optional[float]
    sl_pips: float
    sl_price: float
    tp1_pips: float
    tp1_price: float
    tp2_pips: Optional[float] = None
    tp2_price: Optional[float] = None
    tp3_pips: Optional[float] = None
    tp3_price: Optional[float] = None
    trend_hold: bool = False
    debug: Dict[str, Any] = field(default_factory=dict)


def _ema_stack_aligned(df_slice: pd.DataFrame, direction: str) -> bool:
    """Check if EMA 8/13/21/50 are fully aligned in trade direction."""
    if len(df_slice) < 1:
        return False
    last = df_slice.iloc[-1]
    try:
        e8 = float(last.get("EMA_8", float("nan")))
        e13 = float(last.get("EMA_13", float("nan")))
        e21 = float(last.get("EMA_21", float("nan")))
        e50 = float(last.get("EMA_50", float("nan")))
    except (TypeError, ValueError):
        return False
    if any(np.isnan(v) for v in (e8, e13, e21, e50)):
        return False
    if direction == "BUY":
        return e8 > e13 > e21 > e50
    else:
        return e8 < e13 < e21 < e50


def replay_session(pair: str, date: str, session_name: str,
                   candles_df: pd.DataFrame, briefing: dict) -> List[Signal]:
    """Replay a single session through both strategies, returning all signals."""
    from briefing_liquidity import BriefingLiquidityStrategy
    from briefing_sweep import BriefingSweepStrategy

    epic = SPREAD_EPICS[pair.upper()]
    session_start, session_end = _session_time_range(date, session_name)
    signals = []

    # Fresh strategy instances per session
    bl_strat = BriefingLiquidityStrategy()
    bs_strat = BriefingSweepStrategy()

    for i in range(WARMUP_CANDLES, len(candles_df)):
        ts = candles_df["timestamp"].iloc[i]
        if not isinstance(ts, datetime):
            ts = pd.to_datetime(ts, utc=True).to_pydatetime()
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)

        if ts < session_start or ts >= session_end:
            continue

        df_slice = candles_df.iloc[max(0, i - WARMUP_CANDLES + 1):i + 1].copy()
        mid = float(candles_df["close"].iloc[i])

        # --- Monkey-patch datetime.now so time gates use candle time ---
        import briefing_liquidity as _bl_mod
        import briefing_sweep as _bs_mod
        _orig_bl_dt = _bl_mod.datetime
        _orig_bs_dt = _bs_mod.datetime

        class _FakeDatetime(_orig_bl_dt):
            @classmethod
            def now(cls, tz=None):
                return ts

        try:
            _bl_mod.datetime = _FakeDatetime
            _bs_mod.datetime = _FakeDatetime

            # --- BRIEFING_LIQUIDITY ---
            dec = bl_strat.evaluate(pair, epic, df_slice, PIP_SIZE, mid, briefing)

            if str(dec.signal or "").upper() in ("BUY", "SELL"):
                direction = str(dec.signal).upper()
                entry = float(dec.entry or mid)
                sl_pips = float(dec.sl or 10)
                tp_pips = float(dec.tp or 15)
                dbg = dec.debug or {}
                if direction == "BUY":
                    sl_price = entry - sl_pips * PIP_SIZE
                    tp1_price = entry + tp_pips * PIP_SIZE
                else:
                    sl_price = entry + sl_pips * PIP_SIZE
                    tp1_price = entry - tp_pips * PIP_SIZE
                # Trend-hold: high confidence + fully aligned EMA stack
                _conf = float(briefing.get("bias_confidence", 0))
                _th = (TREND_HOLD_ENABLED
                       and _conf >= TREND_HOLD_MIN_CONFIDENCE
                       and _ema_stack_aligned(df_slice, direction))
                signals.append(Signal(
                    time=str(ts),
                    strategy="BRIEFING_LIQUIDITY",
                    direction=direction,
                    entry=entry,
                    entry_type=dbg.get("entry_source", "unknown"),
                    level=dbg.get("level_price"),
                    sl_pips=sl_pips,
                    sl_price=sl_price,
                    tp1_pips=tp_pips,
                    tp1_price=tp1_price,
                    tp2_pips=dbg.get("tp2_pips"),
                    tp2_price=dbg.get("tp2_price"),
                    tp3_pips=dbg.get("tp3_pips"),
                    tp3_price=dbg.get("tp3_price"),
                    trend_hold=_th,
                    debug=dbg,
                ))

            # --- BRIEFING_SWEEP ---
            rc_all = _build_rc_all(candles_df, i)
            try:
                dec = bs_strat.evaluate(pair, epic, rc_all, PIP_SIZE, mid, briefing)
            except Exception:
                dec = None
        finally:
            _bl_mod.datetime = _orig_bl_dt
            _bs_mod.datetime = _orig_bs_dt

        if dec and str(dec.signal or "").upper() in ("BUY", "SELL"):
            direction = str(dec.signal).upper()
            entry = float(dec.entry or mid)
            sl_pips = float(dec.sl or 12)
            tp_pips = float(dec.tp or 50)
            dbg = dec.debug or {}
            if direction == "BUY":
                sl_price = entry - sl_pips * PIP_SIZE
                tp1_price = entry + tp_pips * PIP_SIZE
            else:
                sl_price = entry + sl_pips * PIP_SIZE
                tp1_price = entry - tp_pips * PIP_SIZE
            _conf = float(briefing.get("bias_confidence", 0))
            _th = (TREND_HOLD_ENABLED
                   and _conf >= TREND_HOLD_MIN_CONFIDENCE
                   and _ema_stack_aligned(df_slice, direction))
            signals.append(Signal(
                time=str(ts),
                strategy="BRIEFING_SWEEP",
                direction=direction,
                entry=entry,
                entry_type="sweep_rejection",
                level=dbg.get("matched_level"),
                sl_pips=sl_pips,
                sl_price=sl_price,
                tp1_pips=tp_pips,
                tp1_price=tp1_price,
                trend_hold=_th,
                debug=dbg,
            ))

    return signals


def simulate_outcome(signal: Signal, remaining_candles: List[dict]) -> dict:
    """Step through candles after signal fires and simulate trade outcome.

    Applies trade manager: arm at pair minimum, floor at pair minimum, trail.
    In trend_hold mode: arm at 50% of TP1, floor at same, 20-pip offset.
    Returns dict with: outcome, close_price, pnl_pips, mfe, mae, trend_hold.
    """
    # Wide-TP mode: TP1 >= 20 pips on BL/BS → proportional trail from TP1 distance
    is_wide = (signal.tp1_pips >= WIDE_TP_THRESHOLD_PIPS
               and signal.strategy in ("BRIEFING_LIQUIDITY", "BRIEFING_SWEEP"))
    if is_wide:
        arm_pips = signal.tp1_pips * WIDE_ARM_PCT
        floor_pips = signal.tp1_pips * WIDE_FLOOR_PCT
        trail_ratio = 0.5
    elif signal.trend_hold:
        arm_pips = signal.tp1_pips * TREND_HOLD_TP1_ARM_PCT
        floor_pips = max(0, arm_pips - TREND_HOLD_OFFSET_PIPS)
        trail_ratio = TREND_HOLD_TRAIL_RATIO
    else:
        cfg = TRAIL_CONFIG.get(signal.strategy, TRAIL_CONFIG["BRIEFING_SWEEP"])
        arm_pips = cfg["arm_pips"]
        floor_pips = cfg["floor_pips"]
        trail_ratio = cfg["trail_ratio"]

    entry = signal.entry
    direction = signal.direction
    sl_price = signal.sl_price
    tp1_price = signal.tp1_price

    best_pnl = 0.0
    worst_pnl = 0.0
    trail_armed = False
    trail_floor = 0.0

    for c in remaining_candles:
        h = float(c["high"])
        l = float(c["low"])

        # Check SL / TP1
        if direction == "BUY":
            if l <= sl_price:
                pnl = -signal.sl_pips
                return {"outcome": "SL", "close_price": sl_price, "pnl_pips": pnl,
                        "mfe": best_pnl, "mae": worst_pnl}
            if h >= tp1_price:
                pnl = signal.tp1_pips
                return {"outcome": "TP1", "close_price": tp1_price, "pnl_pips": pnl,
                        "mfe": max(best_pnl, pnl), "mae": worst_pnl}
            current_best = (h - entry) / PIP_SIZE
            current_worst = (l - entry) / PIP_SIZE
        else:
            if h >= sl_price:
                pnl = -signal.sl_pips
                return {"outcome": "SL", "close_price": sl_price, "pnl_pips": pnl,
                        "mfe": best_pnl, "mae": worst_pnl}
            if l <= tp1_price:
                pnl = signal.tp1_pips
                return {"outcome": "TP1", "close_price": tp1_price, "pnl_pips": pnl,
                        "mfe": max(best_pnl, pnl), "mae": worst_pnl}
            current_best = (entry - l) / PIP_SIZE
            current_worst = (entry - h) / PIP_SIZE

        best_pnl = max(best_pnl, current_best)
        worst_pnl = min(worst_pnl, current_worst)

        # Trail logic
        if not trail_armed and best_pnl >= arm_pips:
            trail_armed = True
            trail_floor = floor_pips

        if trail_armed:
            dynamic_floor = floor_pips + (best_pnl - arm_pips) * trail_ratio
            trail_floor = max(trail_floor, dynamic_floor)

            # Check trail stop
            if direction == "BUY":
                candle_worst_pnl = (l - entry) / PIP_SIZE
            else:
                candle_worst_pnl = (entry - h) / PIP_SIZE

            if candle_worst_pnl <= trail_floor and best_pnl > arm_pips:
                if direction == "BUY":
                    close_price = entry + trail_floor * PIP_SIZE
                else:
                    close_price = entry - trail_floor * PIP_SIZE
                return {"outcome": "TRAIL", "close_price": close_price,
                        "pnl_pips": trail_floor, "mfe": best_pnl, "mae": worst_pnl}

    # End of candles — still open
    last = remaining_candles[-1] if remaining_candles else {"close": entry}
    close_price = float(last["close"])
    if direction == "BUY":
        pnl = (close_price - entry) / PIP_SIZE
    else:
        pnl = (entry - close_price) / PIP_SIZE
    return {"outcome": "OPEN", "close_price": close_price, "pnl_pips": pnl,
            "mfe": best_pnl, "mae": worst_pnl}


def validate_signal(signal: Signal, briefing: dict) -> dict:
    """Check signal quality against briefing.

    Returns dict with: verdict (GOOD/QUESTIONABLE), reasons list.
    """
    reasons = []

    # 1. Was entry within 15 pips of a briefing level?
    all_levels = []
    for src in ("key_levels", "major_levels"):
        kl = briefing.get(src) or {}
        for side in ("resistance", "support"):
            for lv in kl.get(side) or []:
                try:
                    all_levels.append(float(lv))
                except (TypeError, ValueError):
                    pass
    lp = briefing.get("liquidity_pools") or {}
    for side in ("buy_side", "sell_side"):
        for lv in lp.get(side) or []:
            try:
                all_levels.append(float(lv))
            except (TypeError, ValueError):
                pass

    if all_levels:
        min_dist = min(abs(signal.entry - lv) / PIP_SIZE for lv in all_levels)
        if min_dist > 15:
            reasons.append(f"entry {min_dist:.1f} pips from nearest briefing level (>15)")
    else:
        reasons.append("no briefing levels found")

    # 2. Was direction aligned with session bias?
    session_bias = str(briefing.get("session_bias", "")).upper()
    daily_bias = str(briefing.get("daily_bias", "")).upper()
    bias_aligned = False
    if session_bias in ("BULLISH", "BEARISH"):
        expected = "BUY" if session_bias == "BULLISH" else "SELL"
        if signal.direction == expected:
            bias_aligned = True
        else:
            reasons.append(f"direction {signal.direction} opposes session bias {session_bias}")
    elif daily_bias in ("BULLISH", "BEARISH"):
        expected = "BUY" if daily_bias == "BULLISH" else "SELL"
        if signal.direction == expected:
            bias_aligned = True
        else:
            reasons.append(f"direction {signal.direction} opposes daily bias {daily_bias}")
    else:
        reasons.append("no directional bias in briefing")

    # 3. Was SL structural (at a briefing level)?
    if all_levels:
        sl_dist = min(abs(signal.sl_price - lv) / PIP_SIZE for lv in all_levels)
        if sl_dist > 10:
            reasons.append(f"SL {sl_dist:.1f} pips from nearest level (not structural)")

    verdict = "GOOD" if not reasons else "QUESTIONABLE"
    return {"verdict": verdict, "reasons": reasons}


# ============================================================
# STAGE 3 — Full week replay
# ============================================================

@dataclass
class ReplayResult:
    date: str
    pair: str
    session: str
    signal: Signal
    outcome: dict
    quality: dict
    briefing_bias: str
    actual_direction: str


def _actual_session_direction(candles_df: pd.DataFrame,
                              session_start: datetime,
                              session_end: datetime) -> str:
    """Determine actual price direction during a session window."""
    mask = (candles_df["timestamp"] >= session_start) & (candles_df["timestamp"] < session_end)
    session_candles = candles_df[mask]
    if len(session_candles) < 2:
        return "FLAT"
    open_price = float(session_candles.iloc[0]["open"])
    close_price = float(session_candles.iloc[-1]["close"])
    move = close_price - open_price
    if abs(move) < 3 * PIP_SIZE:
        return "FLAT"
    return "UP" if move > 0 else "DOWN"


def run_full_replay() -> List[ReplayResult]:
    """Run replay across all dates, pairs, and sessions."""
    dates = list_available_dates()
    replay_sessions = ["London", "Mid-session", "NY"]
    results = []

    for date in dates:
        all_briefings = load_briefings(date)

        for pair in PAIRS:
            # Load and prepare candles once per pair/date
            raw_candles = load_candles(pair, date)
            if len(raw_candles) < WARMUP_CANDLES + 10:
                print(f"  SKIP {pair} {date}: only {len(raw_candles)} candles")
                continue

            df = pd.DataFrame(raw_candles)
            df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
            df = df.sort_values("timestamp").reset_index(drop=True)
            df = enrich_indicators(df)

            for session_name in replay_sessions:
                briefing_key = f"{pair}_{session_name}"
                briefing = all_briefings.get(briefing_key)
                if not briefing:
                    continue

                session_start, session_end = _session_time_range(date, session_name)
                actual_dir = _actual_session_direction(df, session_start, session_end)
                session_bias = str(briefing.get("session_bias", "")).upper()

                try:
                    signals = replay_session(pair, date, session_name, df, briefing)
                except Exception as e:
                    print(f"  ERROR {pair} {session_name} {date}: {e}")
                    continue

                for sig in signals:
                    sig_ts = pd.to_datetime(sig.time, utc=True)
                    remaining = [c for c in raw_candles
                                 if pd.to_datetime(c["timestamp"], utc=True) > sig_ts]
                    outcome = simulate_outcome(sig, remaining)
                    quality = validate_signal(sig, briefing)

                    results.append(ReplayResult(
                        date=date, pair=pair, session=session_name,
                        signal=sig, outcome=outcome, quality=quality,
                        briefing_bias=session_bias,
                        actual_direction=actual_dir,
                    ))

        print(f"  {date} done — {sum(1 for r in results if r.date == date)} signals")

    return results


def _bias_correct(bias: str, actual: str) -> bool:
    """Check if briefing bias matched actual direction."""
    if bias == "BULLISH" and actual == "UP":
        return True
    if bias == "BEARISH" and actual == "DOWN":
        return True
    return False


def _win(outcome: dict) -> bool:
    return outcome["pnl_pips"] > 0


def _pct(n: int, total: int) -> str:
    return f"{n/total*100:.0f}%" if total > 0 else "0%"


def print_report(results: List[ReplayResult], dates: List[str]):
    """Print the full summary report."""
    total = len(results)
    if total == 0:
        print("No signals found.")
        return

    good = [r for r in results if r.quality["verdict"] == "GOOD"]
    questionable = [r for r in results if r.quality["verdict"] == "QUESTIONABLE"]

    tp1 = [r for r in results if r.outcome["outcome"] == "TP1"]
    sl = [r for r in results if r.outcome["outcome"] == "SL"]
    trail = [r for r in results if r.outcome["outcome"] == "TRAIL"]
    still_open = [r for r in results if r.outcome["outcome"] == "OPEN"]
    total_pnl = sum(r.outcome["pnl_pips"] for r in results)
    avg_pnl = total_pnl / total

    print()
    print(f"FULL SYSTEM REPLAY — {dates[0]} to {dates[-1]}")
    print("═" * 50)

    print(f"\nSIGNAL QUALITY")
    print(f"  Total signals:  {total}")
    print(f"  Good:           {len(good)} ({_pct(len(good), total)})")
    print(f"  Questionable:   {len(questionable)} ({_pct(len(questionable), total)})")

    print(f"\nOUTCOMES")
    print(f"  TP1 hit:        {len(tp1)} ({_pct(len(tp1), total)})")
    print(f"  SL hit:         {len(sl)} ({_pct(len(sl), total)})")
    print(f"  Trail exit:     {len(trail)} ({_pct(len(trail), total)})")
    if still_open:
        print(f"  Still open:     {len(still_open)} ({_pct(len(still_open), total)})")
    print(f"  Total P&L:      {total_pnl:+.1f} pips")
    print(f"  Avg per signal: {avg_pnl:+.1f} pips")

    # BY PAIR
    print(f"\nBY PAIR")
    for pair in PAIRS:
        pr = [r for r in results if r.pair == pair]
        if not pr:
            print(f"  {pair}: 0 signals")
            continue
        wins = sum(1 for r in pr if _win(r.outcome))
        pnl = sum(r.outcome["pnl_pips"] for r in pr)
        print(f"  {pair}: {len(pr)} signals, {_pct(wins, len(pr))} win rate, {pnl:+.1f} pips")

    # BY SESSION
    print(f"\nBY SESSION")
    for sess in ["London", "Mid-session", "NY"]:
        sr = [r for r in results if r.session == sess]
        if not sr:
            print(f"  {sess}: 0 signals")
            continue
        wins = sum(1 for r in sr if _win(r.outcome))
        pnl = sum(r.outcome["pnl_pips"] for r in sr)
        print(f"  {sess}: {len(sr)} signals, {_pct(wins, len(sr))} win rate, {pnl:+.1f} pips")

    # BY ENTRY TYPE
    print(f"\nBY ENTRY TYPE")
    entry_types = sorted(set(r.signal.entry_type for r in results))
    for et in entry_types:
        er = [r for r in results if r.signal.entry_type == et]
        wins = sum(1 for r in er if _win(r.outcome))
        pnl = sum(r.outcome["pnl_pips"] for r in er)
        print(f"  {et}: {len(er)} signals, {_pct(wins, len(er))} win rate, {pnl:+.1f} pips")

    # WIDE TP MODE
    wide_signals = [r for r in results
                    if r.signal.tp1_pips >= WIDE_TP_THRESHOLD_PIPS
                    and r.signal.strategy in ("BRIEFING_LIQUIDITY", "BRIEFING_SWEEP")]
    tight_signals = [r for r in results if r not in wide_signals]
    print(f"\nWIDE TP MODE (TP1 >= {WIDE_TP_THRESHOLD_PIPS:.0f}p)")
    for label, grp in [("Wide TP (proportional trail)", wide_signals),
                        ("Tight TP (5/2 trail)", tight_signals)]:
        if grp:
            gw = sum(1 for r in grp if _win(r.outcome))
            gpnl = sum(r.outcome["pnl_pips"] for r in grp)
            print(f"  {label:<30s} {len(grp):>3d} sig, "
                  f"{_pct(gw, len(grp))} WR, "
                  f"{gpnl:>+7.1f}p total, "
                  f"{gpnl/len(grp):>+5.1f}p avg")

    # TREND HOLD MODE
    th_signals = [r for r in results if r.signal.trend_hold]
    normal_signals = [r for r in results if not r.signal.trend_hold]
    if th_signals or TREND_HOLD_ENABLED:
        print(f"\nTREND HOLD MODE")
        th_w = sum(1 for r in th_signals if _win(r.outcome))
        th_pnl = sum(r.outcome["pnl_pips"] for r in th_signals)
        n_w = sum(1 for r in normal_signals if _win(r.outcome))
        n_pnl = sum(r.outcome["pnl_pips"] for r in normal_signals)
        print(f"  Trend-hold:  {len(th_signals):>3d} signals, "
              f"{_pct(th_w, len(th_signals))} WR, "
              f"{th_pnl:>+7.1f}p total, "
              f"{th_pnl/len(th_signals):>+5.1f}p avg" if th_signals else
              f"  Trend-hold:    0 signals")
        print(f"  Normal:      {len(normal_signals):>3d} signals, "
              f"{_pct(n_w, len(normal_signals))} WR, "
              f"{n_pnl:>+7.1f}p total, "
              f"{n_pnl/len(normal_signals):>+5.1f}p avg" if normal_signals else
              f"  Normal:        0 signals")

    # BRIEFING ACCURACY — one row per (date, pair, session) that had a briefing
    print(f"\nBRIEFING ACCURACY")
    # Collect all unique sessions that were replayed (not just those with signals)
    all_session_biases = []
    all_briefings_loaded = load_briefings(dates[0])  # just to init structure
    for date in dates:
        all_b = load_briefings(date)
        for pair in PAIRS:
            for sess in ["London", "Mid-session", "NY"]:
                bk = f"{pair}_{sess}"
                b = all_b.get(bk)
                if not b:
                    continue
                bias = str(b.get("session_bias", "")).upper()
                # Need actual direction — check if we have candle data cached
                cache_file = _cache_path(pair, date)
                if not cache_file.exists():
                    continue
                raw = json.load(open(cache_file))
                if len(raw) < 20:
                    continue
                tdf = pd.DataFrame(raw)
                tdf["timestamp"] = pd.to_datetime(tdf["timestamp"], utc=True)
                tdf = tdf.sort_values("timestamp").reset_index(drop=True)
                ss, se = _session_time_range(date, sess)
                actual = _actual_session_direction(tdf, ss, se)
                all_session_biases.append({
                    "date": date, "pair": pair, "session": sess,
                    "bias": bias, "actual": actual,
                })

    directional = [s for s in all_session_biases if s["bias"] in ("BULLISH", "BEARISH")]
    correct = [s for s in directional if _bias_correct(s["bias"], s["actual"])]
    print(f"  Correct direction: {len(correct)}/{len(directional)} sessions ({_pct(len(correct), len(directional))})")

    print(f"  By pair:")
    for pair in PAIRS:
        pd_ = [s for s in directional if s["pair"] == pair]
        pc = [s for s in pd_ if _bias_correct(s["bias"], s["actual"])]
        print(f"    {pair}: {_pct(len(pc), len(pd_))} ({len(pc)}/{len(pd_)})")

    # QUESTIONABLE SIGNALS
    if questionable:
        print(f"\nQUESTIONABLE SIGNALS")
        for r in questionable:
            sig = r.signal
            oc = r.outcome
            print(f"  {r.date} {r.pair} {r.session} {sig.time[-14:-6]} "
                  f"{sig.strategy} {sig.direction} @ {sig.entry:.1f} "
                  f"-> {oc['outcome']} {oc['pnl_pips']:+.1f}p")
            for reason in r.quality["reasons"]:
                print(f"    - {reason}")

    print()


# ---------------------------------------------------------------------------
# Comparison report
# ---------------------------------------------------------------------------

# Baseline from original run (before confidence gate / prompt enhancements)
BASELINE = {
    "total": 56,
    "good_pct": 93,
    "win_rate": 66,
    "total_pnl": 207.0,
    "pair_pnl":    {"GBPUSD": -40.0, "EURUSD": +54.3, "USDJPY": +45.9, "USDCAD": +146.8},
    "pair_signals": {"GBPUSD": 18, "EURUSD": 12, "USDJPY": 12, "USDCAD": 14},
    "pair_wr":     {"GBPUSD": 39, "EURUSD": 58, "USDJPY": 75, "USDCAD": 100},
    "session_pnl":    {"London": -24.3, "Mid-session": +58.1, "NY": +173.2},
    "session_signals": {"London": 22, "Mid-session": 11, "NY": 23},
    "session_wr":     {"London": 50, "Mid-session": 64, "NY": 83},
    "entry_wr":    {"sweep_rejection": 59, "bb_pierce": 100, "trigger_close": 100},
    "entry_pnl":   {"sweep_rejection": +176.0, "bb_pierce": +23.5, "trigger_close": +7.4},
    "entry_signals": {"sweep_rejection": 46, "bb_pierce": 7, "trigger_close": 3},
    "briefing_accuracy": 74,
}


def _delta(after: float, before: float) -> str:
    d = after - before
    return f"{d:+.1f}" if isinstance(before, float) else f"{d:+.0f}"


def _delta_pct(after: float, before: float) -> str:
    d = after - before
    return f"{d:+.0f}%"


def print_comparison_report(results: List[ReplayResult], dates: List[str]):
    """Print the full report with before/after comparison."""
    total = len(results)
    if total == 0:
        print("No signals found.")
        return

    B = BASELINE
    good = [r for r in results if r.quality["verdict"] == "GOOD"]
    questionable = [r for r in results if r.quality["verdict"] == "QUESTIONABLE"]
    wins = sum(1 for r in results if _win(r.outcome))
    win_rate = wins / total * 100 if total else 0
    good_pct = len(good) / total * 100 if total else 0

    tp1 = [r for r in results if r.outcome["outcome"] == "TP1"]
    sl = [r for r in results if r.outcome["outcome"] == "SL"]
    trail = [r for r in results if r.outcome["outcome"] == "TRAIL"]
    still_open = [r for r in results if r.outcome["outcome"] == "OPEN"]
    total_pnl = sum(r.outcome["pnl_pips"] for r in results)
    avg_pnl = total_pnl / total

    print()
    print(f"FULL SYSTEM REPLAY — {dates[0]} to {dates[-1]}")
    print("═" * 70)
    print(f"{'':30s} {'BEFORE':>10s}  {'AFTER':>10s}  {'CHANGE':>10s}")
    print(f"{'─'*30} {'─'*10:>10s}  {'─'*10:>10s}  {'─'*10:>10s}")

    print(f"\nSIGNAL QUALITY")
    print(f"  {'Total signals:':<28s} {B['total']:>10d}  {total:>10d}  {total - B['total']:>+10d}")
    print(f"  {'Good quality:':<28s} {B['good_pct']:>9.0f}%  {good_pct:>9.0f}%  {good_pct - B['good_pct']:>+9.0f}%")
    print(f"  {'Win rate:':<28s} {B['win_rate']:>9.0f}%  {win_rate:>9.0f}%  {win_rate - B['win_rate']:>+9.0f}%")

    print(f"\nOUTCOMES")
    print(f"  TP1 hit:        {len(tp1)} ({_pct(len(tp1), total)})")
    print(f"  SL hit:         {len(sl)} ({_pct(len(sl), total)})")
    print(f"  Trail exit:     {len(trail)} ({_pct(len(trail), total)})")
    if still_open:
        print(f"  Still open:     {len(still_open)} ({_pct(len(still_open), total)})")
    print(f"  {'Total P&L:':<28s} {B['total_pnl']:>+9.1f}p  {total_pnl:>+9.1f}p  {total_pnl - B['total_pnl']:>+9.1f}p")
    print(f"  {'Avg per signal:':<28s} {B['total_pnl']/B['total']:>+9.1f}p  {avg_pnl:>+9.1f}p  {avg_pnl - B['total_pnl']/B['total']:>+9.1f}p")

    # BY PAIR
    print(f"\nBY PAIR")
    for pair in PAIRS:
        pr = [r for r in results if r.pair == pair]
        if not pr:
            continue
        pw = sum(1 for r in pr if _win(r.outcome))
        pnl = sum(r.outcome["pnl_pips"] for r in pr)
        wr = pw / len(pr) * 100 if pr else 0
        b_pnl = B["pair_pnl"].get(pair, 0)
        b_sig = B["pair_signals"].get(pair, 0)
        b_wr = B["pair_wr"].get(pair, 0)
        print(f"  {pair + ':':<10s} {b_sig:>2d} sig {b_wr:>3.0f}% WR {b_pnl:>+7.1f}p"
              f"  →  {len(pr):>2d} sig {wr:>3.0f}% WR {pnl:>+7.1f}p"
              f"  ({pnl - b_pnl:>+7.1f}p)")

    # BY SESSION
    print(f"\nBY SESSION")
    for sess in ["London", "Mid-session", "NY"]:
        sr = [r for r in results if r.session == sess]
        if not sr:
            continue
        sw = sum(1 for r in sr if _win(r.outcome))
        pnl = sum(r.outcome["pnl_pips"] for r in sr)
        wr = sw / len(sr) * 100 if sr else 0
        b_pnl = B["session_pnl"].get(sess, 0)
        b_sig = B["session_signals"].get(sess, 0)
        b_wr = B["session_wr"].get(sess, 0)
        print(f"  {sess + ':':<14s} {b_sig:>2d} sig {b_wr:>3.0f}% WR {b_pnl:>+7.1f}p"
              f"  →  {len(sr):>2d} sig {wr:>3.0f}% WR {pnl:>+7.1f}p"
              f"  ({pnl - b_pnl:>+7.1f}p)")

    # BY ENTRY TYPE
    print(f"\nBY ENTRY TYPE")
    entry_types = sorted(set(r.signal.entry_type for r in results))
    for et in entry_types:
        er = [r for r in results if r.signal.entry_type == et]
        ew = sum(1 for r in er if _win(r.outcome))
        pnl = sum(r.outcome["pnl_pips"] for r in er)
        wr = ew / len(er) * 100 if er else 0
        b_wr = B["entry_wr"].get(et, 0)
        b_pnl = B["entry_pnl"].get(et, 0)
        b_sig = B["entry_signals"].get(et, 0)
        print(f"  {et + ':':<18s} {b_sig:>2d} sig {b_wr:>3.0f}% WR {b_pnl:>+7.1f}p"
              f"  →  {len(er):>2d} sig {wr:>3.0f}% WR {pnl:>+7.1f}p"
              f"  ({pnl - b_pnl:>+7.1f}p)")

    # WIDE TP MODE
    wide_signals = [r for r in results
                    if r.signal.tp1_pips >= WIDE_TP_THRESHOLD_PIPS
                    and r.signal.strategy in ("BRIEFING_LIQUIDITY", "BRIEFING_SWEEP")]
    tight_signals = [r for r in results if r not in wide_signals]
    print(f"\nWIDE TP MODE (TP1 >= {WIDE_TP_THRESHOLD_PIPS:.0f}p → arm {WIDE_ARM_PCT:.0%}, floor {WIDE_FLOOR_PCT:.0%}, trail {WIDE_TRAIL_PCT:.0%})")
    for label, grp in [("Wide TP (proportional)", wide_signals),
                        ("Tight TP (5/2 trail)", tight_signals)]:
        if grp:
            gw = sum(1 for r in grp if _win(r.outcome))
            gpnl = sum(r.outcome["pnl_pips"] for r in grp)
            print(f"  {label:<28s} {len(grp):>3d} sig, "
                  f"{_pct(gw, len(grp))} WR, "
                  f"{gpnl:>+7.1f}p total, "
                  f"{gpnl/len(grp):>+5.1f}p avg")

    # BRIEFING ACCURACY
    print(f"\nBRIEFING ACCURACY")
    all_session_biases = []
    for date in dates:
        all_b = load_briefings(date)
        for pair in PAIRS:
            for sess in ["London", "Mid-session", "NY"]:
                bk = f"{pair}_{sess}"
                b = all_b.get(bk)
                if not b:
                    continue
                bias = str(b.get("session_bias", "")).upper()
                cache_file = _cache_path(pair, date)
                if not cache_file.exists():
                    continue
                raw = json.load(open(cache_file))
                if len(raw) < 20:
                    continue
                tdf = pd.DataFrame(raw)
                tdf["timestamp"] = pd.to_datetime(tdf["timestamp"], utc=True)
                tdf = tdf.sort_values("timestamp").reset_index(drop=True)
                ss, se = _session_time_range(date, sess)
                actual = _actual_session_direction(tdf, ss, se)
                all_session_biases.append({
                    "date": date, "pair": pair, "session": sess,
                    "bias": bias, "actual": actual,
                })

    directional = [s for s in all_session_biases if s["bias"] in ("BULLISH", "BEARISH")]
    correct = [s for s in directional if _bias_correct(s["bias"], s["actual"])]
    acc_pct = len(correct) / len(directional) * 100 if directional else 0
    print(f"  Correct direction: {len(correct)}/{len(directional)} sessions "
          f"({acc_pct:.0f}%, was {B['briefing_accuracy']}%)")

    # QUESTIONABLE SIGNALS
    if questionable:
        print(f"\nQUESTIONABLE SIGNALS ({len(questionable)})")
        for r in questionable:
            sig = r.signal
            oc = r.outcome
            print(f"  {r.date} {r.pair} {r.session} {sig.time[-14:-6]} "
                  f"{sig.strategy} {sig.direction} @ {sig.entry:.1f} "
                  f"-> {oc['outcome']} {oc['pnl_pips']:+.1f}p")
            for reason in r.quality["reasons"]:
                print(f"    - {reason}")

    # SIGNALS REMOVED BY CONFIDENCE GATE
    # Compare signal count per pair to baseline
    print(f"\nSIGNALS FILTERED BY CONFIDENCE GATE")
    for pair in PAIRS:
        b_sig = B["pair_signals"].get(pair, 0)
        a_sig = sum(1 for r in results if r.pair == pair)
        diff = a_sig - b_sig
        if diff != 0:
            print(f"  {pair}: {b_sig} → {a_sig} ({diff:+d} signals)")

    print()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING,
                        format="%(levelname)s %(message)s")

    dates = list_available_dates()
    print(f"Available dates: {dates}")
    print(f"Pairs: {PAIRS}")
    print(f"Sessions: London, Mid-session, NY")
    print(f"Running full week replay...\n")

    results = run_full_replay()
    print_comparison_report(results, dates)
