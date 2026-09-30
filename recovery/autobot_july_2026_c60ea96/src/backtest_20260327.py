#!/usr/bin/env python3
"""
backtest_20260327.py — Full-day backtest for 2026-03-27 London session.

Fetches 5M candles via IG REST API for GBPUSD, EURUSD, USDJPY, USDCAD
and replays through BRIEFING_LIQUIDITY, EMA_PULLBACK, BRIEFING_SWEEP.

Trade manager: arm/floor trailing stop simulation.
News blackout: 07:00 UTC ±5 min (GBP Retail Sales).
60-min cooldown per epic per strategy.
No session cutoff — trades run until TP1 or SL hit.
"""

import json
import logging
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd
import numpy as np

# -- Ensure project root is importable --
sys.path.insert(0, "/opt/tradingbot")
os.chdir("/opt/tradingbot")
from dotenv import load_dotenv
load_dotenv()

from ig_auth import get_ig_session
from briefing_liquidity import BriefingLiquidityStrategy

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
logger = logging.getLogger("Backtest")
logger.setLevel(logging.INFO)

# ============================================================
# CONFIG
# ============================================================
DATE = "2026-03-27"
SYMBOLS = ["GBPUSD", "EURUSD", "USDJPY", "USDCAD"]
EPICS = {
    "GBPUSD": "CS.D.GBPUSD.TODAY.IP",
    "EURUSD": "CS.D.EURUSD.TODAY.IP",
    "USDJPY": "CS.D.USDJPY.TODAY.IP",
    "USDCAD": "CS.D.USDCAD.TODAY.IP",
}
PIP_SIZE = 1.0  # All spread-bet pairs on IG

# Session window for simulation
SESSION_START = datetime(2026, 3, 27, 7, 0, tzinfo=timezone.utc)
SESSION_END = datetime(2026, 3, 27, 18, 0, tzinfo=timezone.utc)

# News blackout: GBP Retail Sales 07:00 UTC ±5 min
NEWS_START = datetime(2026, 3, 27, 6, 55, tzinfo=timezone.utc)
NEWS_END = datetime(2026, 3, 27, 7, 5, tzinfo=timezone.utc)

# Warmup: candles before session start needed for indicators
WARMUP_CANDLES = 60  # 5 hours of 5M candles

# Trade manager trailing stops
TRAIL_CONFIG = {
    "BRIEFING_LIQUIDITY": {"arm_pips": 5, "floor_pips": 2, "trail_ratio": 0.5},
    "EMA_PULLBACK":       {"arm_pips": 5, "floor_pips": 2, "trail_ratio": 0.5},
    "BRIEFING_SWEEP":     {"arm_pips": 20, "floor_pips": 10, "trail_ratio": 0.5},
}

COOLDOWN_MINS = 60

# Briefing session schedule (UTC times → which briefing file to load)
BRIEFING_SESSIONS = [
    (datetime(2026, 3, 27, 0, 0, tzinfo=timezone.utc), "Asian"),
    (datetime(2026, 3, 27, 6, 30, tzinfo=timezone.utc), "London"),
    (datetime(2026, 3, 27, 10, 45, tzinfo=timezone.utc), "Mid-session"),
    (datetime(2026, 3, 27, 13, 0, tzinfo=timezone.utc), "NY"),
]


# ============================================================
# DATA TYPES
# ============================================================
@dataclass
class Trade:
    time: str
    epic: str
    symbol: str
    strategy: str
    direction: str
    entry: float
    sl_pips: float
    tp1_pips: float
    sl_price: float
    tp1_price: float
    # Trade manager state
    best_pnl: float = 0.0
    trail_armed: bool = False
    trail_floor: float = 0.0
    # Outcome
    exit_time: Optional[str] = None
    exit_price: Optional[float] = None
    outcome: Optional[str] = None
    pnl_pips: Optional[float] = None
    closed: bool = False


# ============================================================
# HELPERS
# ============================================================
def get_briefing_for_time(symbol: str, ts: datetime) -> Optional[Dict]:
    """Load the most recent briefing file that was generated before ts."""
    best_session = None
    for gen_time, session_name in BRIEFING_SESSIONS:
        if ts >= gen_time:
            best_session = session_name
    if best_session is None:
        return None
    path = Path(f"/opt/tradingbot/logs/briefing_{symbol}_{DATE}_{best_session}.json")
    if not path.exists():
        return None
    with open(path) as f:
        return json.load(f)


def in_news_blackout(ts: datetime) -> bool:
    return NEWS_START <= ts <= NEWS_END


def compute_pnl_pips(direction: str, entry: float, current: float) -> float:
    if direction == "BUY":
        return (current - entry) / PIP_SIZE
    else:
        return (entry - current) / PIP_SIZE


def apply_trade_manager(trade: Trade, candle_high: float, candle_low: float, cfg: dict) -> Optional[str]:
    """Simulate intra-candle trade management. Returns exit reason or None."""
    # Check SL/TP hit on this candle using high/low
    if trade.direction == "BUY":
        # SL hit if low <= sl_price
        if candle_low <= trade.sl_price:
            trade.exit_price = trade.sl_price
            trade.pnl_pips = -trade.sl_pips
            return "SL"
        # TP hit if high >= tp1_price
        if candle_high >= trade.tp1_price:
            trade.exit_price = trade.tp1_price
            trade.pnl_pips = trade.tp1_pips
            return "TP1"
        # Update best PnL (using high for BUY)
        current_pnl = compute_pnl_pips("BUY", trade.entry, candle_high)
    else:  # SELL
        # SL hit if high >= sl_price
        if candle_high >= trade.sl_price:
            trade.exit_price = trade.sl_price
            trade.pnl_pips = -trade.sl_pips
            return "SL"
        # TP hit if low <= tp1_price
        if candle_low <= trade.tp1_price:
            trade.exit_price = trade.tp1_price
            trade.pnl_pips = trade.tp1_pips
            return "TP1"
        # Update best PnL (using low for SELL)
        current_pnl = compute_pnl_pips("SELL", trade.entry, candle_low)

    # Track best PnL
    if current_pnl > trade.best_pnl:
        trade.best_pnl = current_pnl

    # Trailing stop logic
    arm_pips = cfg["arm_pips"]
    floor_pips = cfg["floor_pips"]
    trail_ratio = cfg["trail_ratio"]

    if not trade.trail_armed and trade.best_pnl >= arm_pips:
        trade.trail_armed = True
        trade.trail_floor = floor_pips
        logger.debug("  Trail armed for %s %s at %.1f pips profit", trade.symbol, trade.strategy, trade.best_pnl)

    if trade.trail_armed:
        # Floor rises with additional profit above arm threshold
        dynamic_floor = floor_pips + (trade.best_pnl - arm_pips) * trail_ratio
        trade.trail_floor = max(trade.trail_floor, dynamic_floor)

        # Check if current candle close would trigger trail stop
        # Use worst price in candle for the direction
        if trade.direction == "BUY":
            worst_pnl = compute_pnl_pips("BUY", trade.entry, candle_low)
        else:
            worst_pnl = compute_pnl_pips("SELL", trade.entry, candle_high)

        if worst_pnl <= trade.trail_floor and trade.best_pnl > arm_pips:
            # Trail stop hit — exit at floor level
            trade.pnl_pips = trade.trail_floor
            if trade.direction == "BUY":
                trade.exit_price = trade.entry + trade.trail_floor * PIP_SIZE
            else:
                trade.exit_price = trade.entry - trade.trail_floor * PIP_SIZE
            return "TRAIL"

    return None


# ============================================================
# CANDLE FETCH
# ============================================================
def fetch_candles(ig, epic: str, symbol: str) -> pd.DataFrame:
    """Fetch 5M candles for today + warmup via IG REST API.
    Falls back to cached test candle JSON files if API unavailable."""
    logger.info("Fetching 5M candles for %s (%s)...", symbol, epic)

    # Try cached data first if API has been exhausted
    cache_path = Path(f"/opt/tradingbot/cache/test_candles_{symbol}_{DATE}.json")
    def _load_cached() -> pd.DataFrame:
        if not cache_path.exists():
            return pd.DataFrame()
        logger.info("  Loading cached candles from %s", cache_path)
        with open(cache_path) as f:
            data = json.load(f)
        if not data:
            return pd.DataFrame()
        df = pd.DataFrame(data)
        for col in ["timestamp"]:
            if col in df.columns:
                df[col] = pd.to_datetime(df[col], utc=True, errors="coerce")
        for c in ["open", "high", "low", "close"]:
            if c in df.columns:
                df[c] = pd.to_numeric(df[c], errors="coerce")
        df = df.dropna(subset=["open", "high", "low", "close"]).reset_index(drop=True)
        logger.info("  %s: %d cached candles from %s to %s",
                    symbol, len(df),
                    df["timestamp"].iloc[0] if len(df) else "N/A",
                    df["timestamp"].iloc[-1] if len(df) else "N/A")
        return df

    # Fetch enough candles to cover warmup + full session
    # 07:00 - 18:00 UTC = 132 candles + 60 warmup = ~200
    num_points = 250

    try:
        fn = getattr(ig, "fetch_historical_prices_by_epic_and_num_points", None)
        if callable(fn):
            hist = fn(epic, "MINUTE_5", num_points)
        else:
            fn2 = getattr(ig, "fetch_historical_prices_by_epic", None)
            hist = fn2(epic=epic, resolution="MINUTE_5")
    except Exception as e:
        logger.error("Failed to fetch candles for %s: %s", symbol, e)
        logger.info("Falling back to cached candle data...")
        return _load_cached()

    # Extract prices DataFrame from IG response dict
    if isinstance(hist, dict):
        prices = hist.get("prices", hist)
    elif isinstance(hist, tuple):
        prices = hist[0]
    else:
        prices = hist

    if isinstance(prices, pd.DataFrame):
        df = prices.copy()
        # IG returns MultiIndex columns: (bid/ask/last, Open/High/Low/Close/Volume)
        # Use mid of bid/ask for OHLC
        if isinstance(df.columns, pd.MultiIndex):
            mid_data = {}
            for ohlc in ["Open", "High", "Low", "Close"]:
                bid_val = df[("bid", ohlc)]
                ask_val = df[("ask", ohlc)]
                mid_data[ohlc.lower()] = (bid_val + ask_val) / 2.0
            df = pd.DataFrame(mid_data, index=df.index)

        # DateTime index → timestamp column
        df = df.reset_index()
        if "DateTime" in df.columns:
            df = df.rename(columns={"DateTime": "timestamp"})
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
    else:
        raise RuntimeError(f"Unexpected IG response type: {type(prices)}")

    df = df.dropna(subset=["timestamp"]).sort_values("timestamp").reset_index(drop=True)

    for c in ["open", "high", "low", "close"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna(subset=["open", "high", "low", "close"]).reset_index(drop=True)

    logger.info("  %s: %d candles from %s to %s",
                symbol, len(df),
                df["timestamp"].iloc[0] if len(df) else "N/A",
                df["timestamp"].iloc[-1] if len(df) else "N/A")
    return df


def enrich_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Add EMA, MACD, BB, ATR indicators needed by strategies."""
    if len(df) < 5:
        return df

    closes = df["close"].astype(float)

    # EMAs
    for period in [8, 13, 21, 50, 200]:
        df[f"EMA_{period}"] = closes.ewm(span=period, adjust=False).mean()

    # MACD (35, 45, 30 — custom parameters used by strategies)
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


# ============================================================
# MAIN SIMULATION
# ============================================================
def run_backtest():
    print("=" * 80)
    print(f"  BACKTEST: {DATE} London Session (07:00–18:00 UTC)")
    print(f"  Epics: {', '.join(SYMBOLS)}")
    print(f"  News blackout: 06:55–07:05 UTC (GBP Retail Sales)")
    print("=" * 80)
    print()

    # --- Authenticate IG ---
    logger.info("Authenticating with IG Markets...")
    ig, headers, account_id = get_ig_session()
    logger.info("Authenticated. Account: %s", account_id)

    # --- Fetch candles for all epics ---
    candle_data: Dict[str, pd.DataFrame] = {}
    for sym in SYMBOLS:
        epic = EPICS[sym]
        df = fetch_candles(ig, epic, sym)
        if len(df) < 20:
            logger.warning("Insufficient candles for %s (%d) — skipping", sym, len(df))
            continue
        df = enrich_indicators(df)
        candle_data[sym] = df

    if not candle_data:
        print("ERROR: No candle data fetched. Check IG API credentials.")
        return

    # --- Initialize strategies ---
    bl_strat = BriefingLiquidityStrategy()
    ep_strat = EMAPullbackStrategy()
    bs_strat = BriefingSweepStrategy()

    # --- Simulation state ---
    all_trades: List[Trade] = []
    open_trades: Dict[str, Trade] = {}  # key = f"{sym}_{strategy}"
    cooldowns: Dict[str, datetime] = {}  # key = f"{sym}_{strategy}" → last signal time

    # --- Monkey-patch datetime.now in briefing_liquidity for backtest time simulation ---
    import briefing_liquidity as _bl_mod
    _real_datetime = datetime

    class _SimDatetime(datetime):
        _sim_now = None
        @classmethod
        def now(cls, tz=None):
            if cls._sim_now is not None and tz is not None:
                return cls._sim_now
            return _real_datetime.now(tz)

    _bl_mod.datetime = _SimDatetime

    # --- Replay candles ---
    for sym, df in candle_data.items():
        epic = EPICS[sym]
        logger.info("Replaying %s: %d candles", sym, len(df))

        for i in range(WARMUP_CANDLES, len(df)):
            ts = df["timestamp"].iloc[i]
            if not isinstance(ts, datetime):
                ts = ts.to_pydatetime()
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)

            # Set simulated time for strategy module
            _SimDatetime._sim_now = ts

            # Only process candles in session window
            if ts < SESSION_START or ts > SESSION_END:
                # But still manage open trades outside session
                for key, trade in list(open_trades.items()):
                    if trade.symbol != sym or trade.closed:
                        continue
                    cfg = TRAIL_CONFIG.get(trade.strategy, TRAIL_CONFIG["BRIEFING_SWEEP"])
                    result = apply_trade_manager(
                        trade, float(df["high"].iloc[i]), float(df["low"].iloc[i]), cfg
                    )
                    if result:
                        trade.exit_time = str(ts)
                        trade.outcome = result
                        trade.closed = True
                        del open_trades[key]
                continue

            candle_high = float(df["high"].iloc[i])
            candle_low = float(df["low"].iloc[i])
            candle_close = float(df["close"].iloc[i])

            # --- Manage open trades first ---
            for key, trade in list(open_trades.items()):
                if trade.symbol != sym or trade.closed:
                    continue
                cfg = TRAIL_CONFIG.get(trade.strategy, TRAIL_CONFIG["BRIEFING_SWEEP"])
                result = apply_trade_manager(trade, candle_high, candle_low, cfg)
                if result:
                    trade.exit_time = str(ts)
                    trade.outcome = result
                    trade.closed = True
                    del open_trades[key]

            # --- News blackout check ---
            if in_news_blackout(ts):
                continue

            # --- Load current briefing ---
            briefing = get_briefing_for_time(sym, ts)
            if not briefing:
                continue

            # --- Build the rolling DataFrame slice ---
            df_slice = df.iloc[max(0, i - WARMUP_CANDLES + 1):i + 1].copy()
            mid = candle_close  # use close as mid proxy

            # --- STRATEGY 1: BRIEFING_LIQUIDITY ---
            strat_key = f"{sym}_BRIEFING_LIQUIDITY"
            if strat_key not in open_trades:
                # Check cooldown
                last_cd = cooldowns.get(strat_key)
                if last_cd is None or (ts - last_cd) >= timedelta(minutes=COOLDOWN_MINS):
                    try:
                        dec = bl_strat.evaluate(sym, epic, df_slice, PIP_SIZE, mid, briefing)
                        if str(dec.signal or "").upper() in ("BUY", "SELL"):
                            direction = str(dec.signal).upper()
                            entry = float(dec.entry or mid)
                            sl_pips = float(dec.sl or 10)
                            tp_pips = float(dec.tp or 15)
                            if direction == "BUY":
                                sl_price = entry - sl_pips * PIP_SIZE
                                tp_price = entry + tp_pips * PIP_SIZE
                            else:
                                sl_price = entry + sl_pips * PIP_SIZE
                                tp_price = entry - tp_pips * PIP_SIZE

                            trade = Trade(
                                time=str(ts), epic=epic, symbol=sym,
                                strategy="BRIEFING_LIQUIDITY", direction=direction,
                                entry=entry, sl_pips=sl_pips, tp1_pips=tp_pips,
                                sl_price=sl_price, tp1_price=tp_price,
                            )
                            all_trades.append(trade)
                            open_trades[strat_key] = trade
                            cooldowns[strat_key] = ts
                            logger.info("  [BL] %s %s %s @ %.1f | SL=%.1f TP=%.1f",
                                       ts.strftime("%H:%M"), sym, direction, entry, sl_pips, tp_pips)
                    except Exception as e:
                        logger.debug("  [BL] %s error: %s", sym, e)

            # --- STRATEGY 2: EMA_PULLBACK ---
            strat_key = f"{sym}_EMA_PULLBACK"
            if strat_key not in open_trades:
                last_cd = cooldowns.get(strat_key)
                if last_cd is None or (ts - last_cd) >= timedelta(minutes=COOLDOWN_MINS):
                    try:
                        dec = ep_strat.evaluate(sym, epic, df_slice, PIP_SIZE, mid, briefing)
                        if str(dec.signal or "").upper() in ("BUY", "SELL"):
                            direction = str(dec.signal).upper()
                            entry = float(dec.entry or mid)
                            sl_pips = float(dec.sl or 10)
                            tp_pips = float(dec.tp or 15)
                            if direction == "BUY":
                                sl_price = entry - sl_pips * PIP_SIZE
                                tp_price = entry + tp_pips * PIP_SIZE
                            else:
                                sl_price = entry + sl_pips * PIP_SIZE
                                tp_price = entry - tp_pips * PIP_SIZE

                            trade = Trade(
                                time=str(ts), epic=epic, symbol=sym,
                                strategy="EMA_PULLBACK", direction=direction,
                                entry=entry, sl_pips=sl_pips, tp1_pips=tp_pips,
                                sl_price=sl_price, tp1_price=tp_price,
                            )
                            all_trades.append(trade)
                            open_trades[strat_key] = trade
                            cooldowns[strat_key] = ts
                            logger.info("  [EP] %s %s %s @ %.1f | SL=%.1f TP=%.1f",
                                       ts.strftime("%H:%M"), sym, direction, entry, sl_pips, tp_pips)
                    except Exception as e:
                        logger.debug("  [EP] %s error: %s", sym, e)

            # --- STRATEGY 3: BRIEFING_SWEEP ---
            strat_key = f"{sym}_BRIEFING_SWEEP"
            if strat_key not in open_trades:
                last_cd = cooldowns.get(strat_key)
                if last_cd is None or (ts - last_cd) >= timedelta(minutes=COOLDOWN_MINS):
                    try:
                        # Build recent_closed list for BriefingSweep
                        rc_start = max(0, i - 5)
                        recent_closed = []
                        for j in range(rc_start, i + 1):
                            recent_closed.append({
                                "open": float(df["open"].iloc[j]),
                                "high": float(df["high"].iloc[j]),
                                "low": float(df["low"].iloc[j]),
                                "close": float(df["close"].iloc[j]),
                                "timestamp": str(df["timestamp"].iloc[j]),
                            })

                        dec = bs_strat.evaluate(sym, epic, recent_closed, PIP_SIZE, mid, briefing)
                        if str(dec.signal or "").upper() in ("BUY", "SELL"):
                            direction = str(dec.signal).upper()
                            entry = float(dec.entry or mid)
                            sl_pips = float(dec.sl or 12)
                            tp_pips = float(dec.tp or 50)
                            if direction == "BUY":
                                sl_price = entry - sl_pips * PIP_SIZE
                                tp_price = entry + tp_pips * PIP_SIZE
                            else:
                                sl_price = entry + sl_pips * PIP_SIZE
                                tp_price = entry - tp_pips * PIP_SIZE

                            trade = Trade(
                                time=str(ts), epic=epic, symbol=sym,
                                strategy="BRIEFING_SWEEP", direction=direction,
                                entry=entry, sl_pips=sl_pips, tp1_pips=tp_pips,
                                sl_price=sl_price, tp1_price=tp_price,
                            )
                            all_trades.append(trade)
                            open_trades[strat_key] = trade
                            cooldowns[strat_key] = ts
                            logger.info("  [BS] %s %s %s @ %.1f | SL=%.1f TP=%.1f",
                                       ts.strftime("%H:%M"), sym, direction, entry, sl_pips, tp_pips)
                    except Exception as e:
                        logger.debug("  [BS] %s error: %s", sym, e)

    # --- Close any still-open trades at last candle ---
    for key, trade in open_trades.items():
        if not trade.closed:
            sym = trade.symbol
            if sym in candle_data:
                df = candle_data[sym]
                last_close = float(df["close"].iloc[-1])
                trade.exit_price = last_close
                trade.exit_time = str(df["timestamp"].iloc[-1])
                trade.pnl_pips = compute_pnl_pips(trade.direction, trade.entry, last_close)
                trade.outcome = "OPEN (EOD)"
                trade.closed = True

    # ============================================================
    # REPORT
    # ============================================================
    print()
    print("=" * 100)
    print("  TRADE LOG")
    print("=" * 100)
    print(f"{'Time':>20s}  {'Epic':>8s}  {'Strategy':>20s}  {'Dir':>4s}  {'Entry':>9s}  "
          f"{'SL pip':>6s}  {'TP1 pip':>7s}  {'Outcome':>8s}  {'P&L pip':>8s}")
    print("-" * 100)

    for t in all_trades:
        ts_short = t.time[11:16] if len(t.time) > 16 else t.time
        print(f"{ts_short:>20s}  {t.symbol:>8s}  {t.strategy:>20s}  {t.direction:>4s}  "
              f"{t.entry:>9.1f}  {t.sl_pips:>6.1f}  {t.tp1_pips:>7.1f}  "
              f"{t.outcome or 'OPEN':>8s}  {t.pnl_pips or 0:>+8.1f}")

    if not all_trades:
        print("  (no trades fired)")

    # --- Strategy summary ---
    print()
    print("=" * 80)
    print("  STRATEGY SUMMARY")
    print("=" * 80)

    strategies = ["BRIEFING_LIQUIDITY", "EMA_PULLBACK", "BRIEFING_SWEEP"]
    total_pips = 0.0

    for strat in strategies:
        strat_trades = [t for t in all_trades if t.strategy == strat]
        wins = [t for t in strat_trades if (t.pnl_pips or 0) > 0]
        losses = [t for t in strat_trades if (t.pnl_pips or 0) < 0]
        flat = [t for t in strat_trades if (t.pnl_pips or 0) == 0]
        pips = sum(t.pnl_pips or 0 for t in strat_trades)
        total_pips += pips

        print(f"\n  {strat}")
        print(f"    Trades: {len(strat_trades)}  |  Wins: {len(wins)}  |  Losses: {len(losses)}  |  Flat: {len(flat)}")
        print(f"    Total P&L: {pips:+.1f} pips")
        if strat_trades:
            for t in strat_trades:
                ts_short = t.time[11:16] if len(t.time) > 16 else t.time
                print(f"      {ts_short} {t.symbol} {t.direction} @ {t.entry:.1f} → {t.outcome or 'OPEN'} {t.pnl_pips or 0:+.1f} pips")

    # --- Day total ---
    print()
    print("=" * 80)
    print("  DAY TOTAL")
    print("=" * 80)
    print(f"  Total trades: {len(all_trades)}")
    print(f"  Total P&L:    {total_pips:+.1f} pips")
    print(f"  @ £1/pip:     £{total_pips * 1:+.2f}")
    print(f"  @ £10/pip:    £{total_pips * 10:+.2f}")
    print()

    # Per-epic breakdown
    print("  Per-epic breakdown:")
    for sym in SYMBOLS:
        sym_trades = [t for t in all_trades if t.symbol == sym]
        sym_pips = sum(t.pnl_pips or 0 for t in sym_trades)
        print(f"    {sym}: {len(sym_trades)} trades, {sym_pips:+.1f} pips (£{sym_pips:+.2f} @ £1/pip, £{sym_pips * 10:+.2f} @ £10/pip)")

    print()


if __name__ == "__main__":
    run_backtest()
