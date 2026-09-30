#!/usr/bin/env python3
"""
sweep_replay.py — Multi-day sweep detector replay using cached candle data.

Replays BriefingLiquidityStrategy _check_sweep_entry() across all available
cached candle dates. Reports per-variant stats, win rate, P&L, and GBPUSD detail.
"""

import json
import logging
import os
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from glob import glob
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd

sys.path.insert(0, "/opt/tradingbot")
os.chdir("/opt/tradingbot")
from dotenv import load_dotenv
load_dotenv()

# Force sweep variants and observation off for replay
os.environ["BRIEFING_LIQUIDITY_SWEEP_VARIANTS"] = "1,2,3,4"
os.environ["BRIEFING_LIQUIDITY_OBSERVE"] = "0"
os.environ["BRIEFING_LIQUIDITY_BB_PIERCE_ENABLED"] = "1"
os.environ["BRIEFING_LIQUIDITY_ENABLED"] = "1"

import importlib
import briefing_liquidity as bl_mod
importlib.reload(bl_mod)
from briefing_liquidity import BriefingLiquidityStrategy, _get_points_per_pip

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
logger = logging.getLogger("SweepReplay")
logger.setLevel(logging.INFO)

SYMBOLS = ["GBPUSD", "EURUSD", "USDJPY", "USDCAD"]
EPICS = {
    "GBPUSD": "CS.D.GBPUSD.TODAY.IP",
    "EURUSD": "CS.D.EURUSD.TODAY.IP",
    "USDJPY": "CS.D.USDJPY.TODAY.IP",
    "USDCAD": "CS.D.USDCAD.TODAY.IP",
}
PIP_SIZE = 1.0
WARMUP = 60

BRIEFING_SESSIONS = [
    ("Asian", 0, 0),
    ("London", 6, 30),
    ("Mid-session", 10, 45),
    ("NY", 13, 0),
]


@dataclass
class Trade:
    time: str
    date: str
    epic: str
    symbol: str
    direction: str
    entry: float
    sl_pips: float
    tp1_pips: float
    sl_price: float
    tp1_price: float
    variant: int = 0
    source: str = ""
    best_pnl: float = 0.0
    trail_armed: bool = False
    trail_floor: float = 0.0
    exit_time: Optional[str] = None
    exit_price: Optional[float] = None
    outcome: Optional[str] = None
    pnl_pips: Optional[float] = None
    closed: bool = False
    candles: int = 0
    mfe_pips: float = 0.0


def calculate_session_bias_from_candles(
    h1_closes: list, d1_candles_raw: list, current_price: float,
    prev_week_high: float | None, prev_week_low: float | None,
) -> str:
    """Calculate session_bias from market data — mirrors morning_briefing.calculate_session_bias().

    BEARISH if ANY TWO of:
      1. H1 price below H1 EMA 200
      2. H1 EMA 8 < EMA 21 < EMA 50
      3. Yesterday closed lower than it opened
      4. Price below last week's midpoint

    BULLISH if ANY TWO of the mirror conditions.
    NEUTRAL only if exactly 2 bearish and 2 bullish cancel out.
    """
    bullish = 0
    bearish = 0

    # Compute H1 EMAs from closes
    if len(h1_closes) >= 3:
        s = pd.Series(h1_closes, dtype="float64")
        ema8   = float(s.ewm(span=8,   adjust=False).mean().iloc[-1])
        ema21  = float(s.ewm(span=21,  adjust=False).mean().iloc[-1])
        ema50  = float(s.ewm(span=50,  adjust=False).mean().iloc[-1])
        ema200 = float(s.ewm(span=200, adjust=False).mean().iloc[-1]) if len(h1_closes) >= 50 else None

        # Signal 1: Price vs H1 EMA 200
        if ema200 is not None:
            if current_price > ema200:
                bullish += 1
            elif current_price < ema200:
                bearish += 1

        # Signal 2: EMA fan alignment
        if ema8 > ema21 > ema50:
            bullish += 1
        elif ema8 < ema21 < ema50:
            bearish += 1

    # Signal 3: Yesterday closed lower/higher than it opened
    if len(d1_candles_raw) >= 2:
        prev = d1_candles_raw[-2]
        y_open  = float(prev.get("open", prev.get("o", 0)))
        y_close = float(prev.get("close", prev.get("c", 0)))
        if y_close > y_open:
            bullish += 1
        elif y_close < y_open:
            bearish += 1

    # Signal 4: Price vs last week's midpoint
    if prev_week_high is not None and prev_week_low is not None:
        week_mid = (prev_week_high + prev_week_low) / 2.0
        if current_price > week_mid:
            bullish += 1
        elif current_price < week_mid:
            bearish += 1

    if bullish >= 2 and bearish >= 2:
        return "NEUTRAL"
    if bearish >= 2:
        return "BEARISH"
    if bullish >= 2:
        return "BULLISH"
    return "NEUTRAL"


# Cached H1/D1 candle data built from 5M frames, keyed by symbol
_h1_candle_cache: Dict[str, list] = {}
_d1_candle_cache: Dict[str, list] = {}


def build_htf_candle_caches(sym: str, df_5m: pd.DataFrame) -> None:
    """Build synthetic H1 and D1 candle lists from the continuous 5M DataFrame."""
    df = df_5m.copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    for col in ["open", "high", "low", "close"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    # H1 candles: resample 5M to 1H
    df = df.set_index("timestamp")
    h1 = df.resample("1h").agg({"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
    _h1_candle_cache[sym] = h1.reset_index().to_dict("records")

    # D1 candles: resample 5M to 1D
    d1 = df.resample("1D").agg({"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
    _d1_candle_cache[sym] = d1.reset_index().to_dict("records")


def get_briefing(symbol: str, date_str: str, ts: datetime) -> Optional[Dict]:
    best = None
    for sess_name, hh, mm in BRIEFING_SESSIONS:
        gen = datetime(ts.year, ts.month, ts.day, hh, mm, tzinfo=timezone.utc)
        if ts >= gen:
            best = sess_name
    if not best:
        return None
    p = Path(f"/opt/tradingbot/logs/briefing_{symbol}_{date_str}_{best}.json")
    if not p.exists():
        return None
    with open(p) as f:
        briefing = json.load(f)

    # --- Override session_bias with calculated bias from market data ---
    h1_candles = _h1_candle_cache.get(symbol, [])
    d1_candles = _d1_candle_cache.get(symbol, [])

    # Filter H1 candles up to current timestamp for point-in-time accuracy
    h1_up_to_now = [c for c in h1_candles if c["timestamp"] <= ts]
    h1_closes = [float(c["close"]) for c in h1_up_to_now]

    # Filter D1 candles up to yesterday (don't include today's incomplete candle)
    d1_up_to_now = [c for c in d1_candles if c["timestamp"].date() < ts.date()]
    # Add today's partial candle so d1[-1] = today, d1[-2] = yesterday
    d1_today = [c for c in d1_candles if c["timestamp"].date() == ts.date()]
    d1_for_calc = d1_up_to_now + d1_today

    current_price = h1_closes[-1] if h1_closes else None

    # Last week's midpoint: use D1 candles from the previous 5 trading days before this week
    prev_week_high = None
    prev_week_low = None
    if len(d1_up_to_now) >= 10:
        # Current week ~ last 5 days, prev week ~ 5 before that
        last_week = d1_up_to_now[-10:-5]
        if last_week:
            prev_week_high = max(float(c["high"]) for c in last_week)
            prev_week_low  = min(float(c["low"])  for c in last_week)

    # Keep the API session_bias as-is (matches live behaviour since 9f4739f).
    # Store calculated bias for audit only.
    if current_price is not None:
        calc_bias = calculate_session_bias_from_candles(
            h1_closes, d1_for_calc, current_price,
            prev_week_high, prev_week_low,
        )
        briefing["calc_session_bias"] = calc_bias  # audit trail only

    return briefing


def compute_pnl(direction, entry, current):
    return ((current - entry) if direction == "BUY" else (entry - current)) / PIP_SIZE


def manage_trade(trade, c_high, c_low):
    trade.candles += 1
    # Track MFE (max favorable excursion) before any exit
    if trade.direction == "BUY":
        mfe_candidate = compute_pnl("BUY", trade.entry, c_high)
    else:
        mfe_candidate = compute_pnl("SELL", trade.entry, c_low)
    if mfe_candidate > trade.mfe_pips:
        trade.mfe_pips = mfe_candidate
    if trade.direction == "BUY":
        if c_low <= trade.sl_price:
            trade.exit_price = trade.sl_price
            trade.pnl_pips = -trade.sl_pips
            return "SL"
        if c_high >= trade.tp1_price:
            trade.exit_price = trade.tp1_price
            trade.pnl_pips = trade.tp1_pips
            return "TP1"
        cur = compute_pnl("BUY", trade.entry, c_high)
    else:
        if c_high >= trade.sl_price:
            trade.exit_price = trade.sl_price
            trade.pnl_pips = -trade.sl_pips
            return "SL"
        if c_low <= trade.tp1_price:
            trade.exit_price = trade.tp1_price
            trade.pnl_pips = trade.tp1_pips
            return "TP1"
        cur = compute_pnl("SELL", trade.entry, c_low)
    if cur > trade.best_pnl:
        trade.best_pnl = cur
    # TP1-aware trail thresholds — GBPUSD: 60%/50%, others: 35%/25%
    if trade.symbol == "GBPUSD" and trade.tp1_pips >= 30:
        arm_pips = trade.tp1_pips * 0.60
        floor_pips = trade.tp1_pips * 0.50
    elif trade.tp1_pips >= 30:
        arm_pips = trade.tp1_pips * 0.35
        floor_pips = trade.tp1_pips * 0.25
    else:
        arm_pips = 20
        floor_pips = 10
    if not trade.trail_armed and trade.best_pnl >= arm_pips:
        trade.trail_armed = True
        trade.trail_floor = floor_pips
    if trade.trail_armed:
        trade.trail_floor = max(trade.trail_floor, floor_pips + (trade.best_pnl - arm_pips) * 0.5)
        worst = compute_pnl(trade.direction, trade.entry, c_low if trade.direction == "BUY" else c_high)
        if worst <= trade.trail_floor and trade.best_pnl > arm_pips:
            trade.pnl_pips = trade.trail_floor
            return "TRAIL"
    return None


def enrich(df):
    if len(df) < 5:
        return df
    c = df["close"].astype(float)
    for p in [8, 13, 21, 50, 200]:
        df[f"EMA_{p}"] = c.ewm(span=p, adjust=False).mean()
    bb_mid = c.rolling(20).mean()
    bb_std = c.rolling(20).std()
    df["BB_UPPER"] = bb_mid + 2 * bb_std
    df["BB_LOWER"] = bb_mid - 2 * bb_std
    return df


def load_cached_candles(sym: str) -> Dict[str, pd.DataFrame]:
    """Load cached 5M candle data per date from test_candles files, deep cache, and data/candles/."""
    date_dfs: Dict[str, pd.DataFrame] = {}

    # Test candle JSONs (per-day)
    for f in sorted(glob(f"/opt/tradingbot/cache/test_candles_{sym}_????-??-??.json")):
        date_str = f.split("_")[-1].replace(".json", "")
        try:
            with open(f) as fh:
                data = json.load(fh)
            df = pd.DataFrame(data)
            df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
            for col in ["open", "high", "low", "close"]:
                df[col] = pd.to_numeric(df[col], errors="coerce")
            df = df.dropna(subset=["timestamp", "open", "high", "low", "close"])
            df = df.sort_values("timestamp").reset_index(drop=True)
            if len(df) >= 30:
                date_dfs[date_str] = df
        except Exception:
            continue

    # Deep cache CSV (multi-day) — split by date
    deep_path = f"/opt/tradingbot/cache/{sym}_candles_deep.csv"
    if os.path.exists(deep_path):
        try:
            df = pd.read_csv(deep_path, parse_dates=["timestamp"])
            df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
            for col in ["open", "high", "low", "close"]:
                df[col] = pd.to_numeric(df[col], errors="coerce")
            df = df.dropna(subset=["timestamp", "open", "high", "low", "close"])
            df = df.sort_values("timestamp").reset_index(drop=True)
            for date_str, grp in df.groupby(df["timestamp"].dt.date.astype(str)):
                if date_str not in date_dfs and len(grp) >= 30:
                    date_dfs[date_str] = grp.reset_index(drop=True)
        except Exception:
            pass

    # data/candles/{sym}/{date}.csv — per-day CSV files
    candle_dir = f"/opt/tradingbot/data/candles/{sym}"
    if os.path.isdir(candle_dir):
        for f in sorted(glob(f"{candle_dir}/????-??-??.csv")):
            date_str = Path(f).stem  # e.g. "2026-04-01"
            if date_str in date_dfs:
                continue  # don't overwrite existing data
            try:
                df = pd.read_csv(f, parse_dates=["timestamp"])
                df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
                for col in ["open", "high", "low", "close"]:
                    df[col] = pd.to_numeric(df[col], errors="coerce")
                df = df.dropna(subset=["timestamp", "open", "high", "low", "close"])
                df = df.sort_values("timestamp").reset_index(drop=True)
                if len(df) >= 30:
                    date_dfs[date_str] = df
            except Exception:
                continue

    return date_dfs


def run():
    print("=" * 90)
    print("  SWEEP DETECTOR MULTI-DAY REPLAY")
    print(f"  Variants enabled: {sorted(bl_mod.BRIEFING_LIQUIDITY_SWEEP_VARIANTS)}")
    print("=" * 90)

    # Load all cached candle data
    all_candles: Dict[str, Dict[str, pd.DataFrame]] = {}  # sym -> {date -> df}
    for sym in SYMBOLS:
        cds = load_cached_candles(sym)
        if cds:
            all_candles[sym] = cds
            dates = sorted(cds.keys())
            total_rows = sum(len(df) for df in cds.values())
            print(f"  {sym}: {len(dates)} days, {total_rows} candles [{dates[0]} → {dates[-1]}]")

    if not all_candles:
        print("  No cached candle data found.")
        return

    # Also fetch today's live candles from IG
    try:
        from ig_auth import get_ig_session
        ig, _, _ = get_ig_session()
        for sym in SYMBOLS:
            epic = EPICS[sym]
            fn = getattr(ig, "fetch_historical_prices_by_epic_and_num_points", None)
            if not callable(fn):
                continue
            hist = fn(epic, "MINUTE_5", 250)
            if isinstance(hist, dict):
                prices = hist.get("prices", hist)
            elif isinstance(hist, tuple):
                prices = hist[0]
            else:
                prices = hist
            if isinstance(prices, pd.DataFrame):
                df = prices.copy()
                if isinstance(df.columns, pd.MultiIndex):
                    mid = {}
                    for ohlc in ["Open", "High", "Low", "Close"]:
                        mid[ohlc.lower()] = (df[("bid", ohlc)] + df[("ask", ohlc)]) / 2.0
                    df = pd.DataFrame(mid, index=df.index)
                df = df.reset_index()
                if "DateTime" in df.columns:
                    df = df.rename(columns={"DateTime": "timestamp"})
                df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
                for col in ["open", "high", "low", "close"]:
                    df[col] = pd.to_numeric(df[col], errors="coerce")
                df = df.dropna(subset=["timestamp", "open", "high", "low", "close"])
                df = df.sort_values("timestamp").reset_index(drop=True)
                # Split by date
                for date_str, grp in df.groupby(df["timestamp"].dt.date.astype(str)):
                    if sym not in all_candles:
                        all_candles[sym] = {}
                    if date_str not in all_candles[sym] and len(grp) >= 30:
                        all_candles[sym][date_str] = grp.reset_index(drop=True)
                        print(f"  {sym}: +{date_str} from IG ({len(grp)} candles)")
    except Exception as e:
        logger.info("IG fetch failed (non-fatal): %s", e)

    # Build continuous multi-day DataFrames per symbol (for indicator warmup)
    sym_frames: Dict[str, pd.DataFrame] = {}
    for sym in SYMBOLS:
        if sym not in all_candles:
            continue
        frames = [all_candles[sym][d] for d in sorted(all_candles[sym].keys())]
        full = pd.concat(frames, ignore_index=True).sort_values("timestamp").reset_index(drop=True)
        full = enrich(full)
        sym_frames[sym] = full
        # Build H1/D1 candle caches for calculated session_bias
        build_htf_candle_caches(sym, full)

    # --- SWEEP-ONLY detection pass (no cooldown, no limits) ---
    print("\n" + "=" * 90)
    print("  RAW SWEEP DETECTIONS (all variants, no cooldown)")
    print("=" * 90)

    raw_detections: List[Dict] = []

    for sym, df in sym_frames.items():
        epic = EPICS[sym]
        ppp = _get_points_per_pip(epic)
        strat = BriefingLiquidityStrategy()

        for i in range(WARMUP, len(df)):
            ts = df["timestamp"].iloc[i]
            if not isinstance(ts, datetime):
                ts = ts.to_pydatetime()
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            if not (7 <= ts.hour < 17):
                continue

            date_str = str(ts.date())
            briefing = get_briefing(sym, date_str, ts)
            if not briefing:
                continue

            bias = strat._get_bias(briefing)
            if bias == "NONE":
                continue

            levels = strat._ensure_levels(epic, briefing, float(df["close"].iloc[i]), bias)
            df_slice = df.iloc[max(0, i - WARMUP + 1):i + 1].copy()

            result = strat._check_sweep_entry(epic, df_slice, bias, ppp, levels or [])
            if result:
                raw_detections.append({
                    "time": str(ts),
                    "date": date_str,
                    "symbol": sym,
                    "direction": result["direction"],
                    "entry": result["entry"],
                    "variant": result.get("variant", 0),
                    "source": result["source"],
                })

    # Per-variant raw count
    v_counts = defaultdict(int)
    v_by_sym = defaultdict(lambda: defaultdict(int))
    for d in raw_detections:
        v_counts[d["variant"]] += 1
        v_by_sym[d["symbol"]][d["variant"]] += 1

    for v in sorted(v_counts.keys()):
        by_sym = ", ".join(f"{s}={v_by_sym[s][v]}" for s in SYMBOLS if v_by_sym[s][v])
        print(f"  V{v}: {v_counts[v]} detections  ({by_sym})")
    print(f"  TOTAL: {sum(v_counts.values())} raw sweep detections across {len(set(d['date'] for d in raw_detections))} days")

    # --- FULL REPLAY with trade management ---
    print("\n" + "=" * 90)
    print("  FULL REPLAY WITH TRADE MANAGEMENT")
    print("=" * 90)

    all_trades: List[Trade] = []
    # Track skipped detections per symbol/date for utilisation analysis
    skipped_detections: List[Dict] = []  # {time, date, symbol, direction, reason, variant}

    for sym, df in sym_frames.items():
        epic = EPICS[sym]
        ppp = _get_points_per_pip(epic)
        strat = BriefingLiquidityStrategy()
        open_trades: Dict[str, Trade] = {}

        for i in range(WARMUP, len(df)):
            ts = df["timestamp"].iloc[i]
            if not isinstance(ts, datetime):
                ts = ts.to_pydatetime()
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)

            c_high = float(df["high"].iloc[i])
            c_low = float(df["low"].iloc[i])
            c_close = float(df["close"].iloc[i])
            date_str = str(ts.date())

            # Manage open trades
            for key, trade in list(open_trades.items()):
                if trade.closed:
                    continue
                result = manage_trade(trade, c_high, c_low)
                if result:
                    trade.exit_time = str(ts)
                    trade.outcome = result
                    trade.closed = True
                    del open_trades[key]

            if not (7 <= ts.hour < 17):
                continue

            briefing = get_briefing(sym, date_str, ts)
            if not briefing:
                continue

            # Check for detection even when blocked, for utilisation tracking
            if open_trades:
                _skip_slice = df.iloc[max(0, i - WARMUP + 1):i + 1].copy()
                _skip_bias = strat._get_bias(briefing)
                if _skip_bias != "NONE":
                    _skip_levels = strat._ensure_levels(epic, briefing, c_close, _skip_bias)
                    _skip_result = strat._check_sweep_entry(epic, _skip_slice, _skip_bias, ppp, _skip_levels or [])
                    if _skip_result:
                        _sv = 0
                        _ss = _skip_result.get("source", "")
                        if "sweep_v" in _ss:
                            try: _sv = int(_ss.split("sweep_v")[1][0])
                            except: pass
                        _blocking = list(open_trades.values())[0]
                        skipped_detections.append({
                            "time": str(ts), "date": date_str, "symbol": sym,
                            "direction": _skip_result["direction"], "variant": _sv,
                            "source": _ss, "reason": "POSITION_OPEN",
                            "blocker": f"{_blocking.direction} @ {_blocking.entry:.0f} ({_blocking.source})",
                        })

            if open_trades:
                continue

            df_slice = df.iloc[max(0, i - WARMUP + 1):i + 1].copy()

            bias = strat._get_bias(briefing)
            if bias == "NONE":
                continue

            levels = strat._ensure_levels(epic, briefing, c_close, bias)
            result = strat._check_sweep_entry(epic, df_slice, bias, ppp, levels or [])
            if not result:
                continue

            direction = result["direction"]
            entry = float(result["entry"])
            sl_price_raw = float(result["sl_price"])
            source = result.get("source", "")
            variant = 0
            if "sweep_v" in source:
                try:
                    variant = int(source.split("sweep_v")[1][0])
                except (ValueError, IndexError):
                    pass

            # Compute SL pips from entry and sl_price (same as evaluate())
            if direction == "SELL":
                sl_pips = (sl_price_raw - entry) / PIP_SIZE
            else:
                sl_pips = (entry - sl_price_raw) / PIP_SIZE
            if sl_pips <= 0:
                continue

            # Compute TP from briefing levels (same as evaluate())
            tp_plan = strat._find_tp_plan(
                direction, entry, sl_pips, levels or [], ppp, briefing,
            )
            tp_pips = tp_plan[0]["pips"] if tp_plan else 15.0

            if direction == "BUY":
                sl_price = entry - sl_pips * PIP_SIZE
                tp_price = entry + tp_pips * PIP_SIZE
            else:
                sl_price = entry + sl_pips * PIP_SIZE
                tp_price = entry - tp_pips * PIP_SIZE

            trade_key = f"{sym}_sweep" if variant > 0 else f"{sym}_level"
            trade = Trade(
                time=str(ts), date=date_str, epic=epic, symbol=sym,
                direction=direction, entry=entry,
                sl_pips=sl_pips, tp1_pips=tp_pips,
                sl_price=sl_price, tp1_price=tp_price,
                variant=variant, source=source,
            )
            all_trades.append(trade)
            open_trades[trade_key] = trade

        # Close remaining
        for key, trade in open_trades.items():
            if not trade.closed:
                trade.pnl_pips = compute_pnl(trade.direction, trade.entry, float(df["close"].iloc[-1]))
                trade.outcome = "EOD"
                trade.closed = True

    # --- TRADE LOG ---
    print(f"\n{'Time':>20s}  {'Sym':>6s}  {'Dir':>4s}  {'Entry':>9s}  {'SL':>5s}  {'TP':>5s}  "
          f"{'Var':>3s}  {'Source':>25s}  {'Out':>5s}  {'P&L':>8s}")
    print("-" * 100)
    for t in all_trades:
        ts_short = t.time[11:16] if len(t.time) > 16 else t.time
        vl = f"V{t.variant}" if t.variant else "LVL"
        print(f"{t.date} {ts_short:>5s}  {t.symbol:>6s}  {t.direction:>4s}  {t.entry:>9.1f}  "
              f"{t.sl_pips:>5.1f}  {t.tp1_pips:>5.1f}  "
              f"{vl:>3s}  {t.source:>25s}  {t.outcome or 'OPEN':>5s}  {t.pnl_pips or 0:>+8.1f}")
    if not all_trades:
        print("  (no trades)")

    # --- PER-VARIANT SUMMARY ---
    print("\n" + "=" * 80)
    print("  PER-VARIANT SUMMARY")
    print("=" * 80)

    vt = defaultdict(list)
    for t in all_trades:
        vt[t.variant].append(t)

    total_pnl = 0.0
    sweep_pnl = 0.0
    sweep_count = 0
    for v in sorted(vt.keys()):
        trades = vt[v]
        wins = [t for t in trades if (t.pnl_pips or 0) > 0]
        losses = [t for t in trades if (t.pnl_pips or 0) < 0]
        pnl = sum(t.pnl_pips or 0 for t in trades)
        wr = len(wins) / len(trades) * 100 if trades else 0
        label = f"V{v}" if v > 0 else "Level trigger"
        total_pnl += pnl
        if v > 0:
            sweep_pnl += pnl
            sweep_count += len(trades)
        print(f"\n  {label}: {len(trades)} trades | W:{len(wins)} L:{len(losses)} | WR:{wr:.0f}% | P&L:{pnl:+.1f}")

    level_count = sum(1 for t in all_trades if t.variant == 0)
    level_pnl = sum(t.pnl_pips or 0 for t in all_trades if t.variant == 0)
    print(f"\n  {'—' * 50}")
    print(f"  Level triggers: {level_count} trades, {level_pnl:+.1f} pips")
    print(f"  Sweep variants: {sweep_count} trades, {sweep_pnl:+.1f} pips")
    print(f"  TOTAL:          {len(all_trades)} trades, {total_pnl:+.1f} pips")

    # --- PER-SYMBOL BREAKDOWN ---
    print("\n" + "=" * 80)
    print("  PER-SYMBOL BREAKDOWN")
    print("=" * 80)
    for sym in SYMBOLS:
        st = [t for t in all_trades if t.symbol == sym]
        sw = [t for t in st if t.variant > 0]
        sp = sum(t.pnl_pips or 0 for t in st)
        swp = sum(t.pnl_pips or 0 for t in sw)
        print(f"  {sym}: {len(st)} trades ({len(sw)} sweep) | Total:{sp:+.1f} | Sweep:{swp:+.1f}")

    # --- GBPUSD DETAIL ---
    print("\n" + "=" * 80)
    print("  GBPUSD SWEEP DETAIL")
    print("=" * 80)
    gbp = [t for t in all_trades if t.symbol == "GBPUSD"]
    gbp_sweeps = [t for t in gbp if t.variant > 0]
    gbp_raw = [d for d in raw_detections if d["symbol"] == "GBPUSD"]

    print(f"  GBPUSD total trades: {len(gbp)}")
    print(f"  GBPUSD sweep trades (executed): {len(gbp_sweeps)}")
    print(f"  GBPUSD raw sweep detections: {len(gbp_raw)}")

    dates_with_gbp = sorted(set(t.date for t in gbp))
    print(f"  Days with GBPUSD trades: {len(dates_with_gbp)}")

    for t in gbp:
        ts_short = t.time[11:16] if len(t.time) > 16 else t.time
        vl = f"V{t.variant}" if t.variant else "LVL"
        print(f"    {t.date} {ts_short} {t.direction} @ {t.entry:.1f} [{vl}] {t.source} → {t.outcome} {t.pnl_pips or 0:+.1f}")

    # --- GBPUSD SL DIAGNOSTIC ---
    gbp_sl = [t for t in gbp if t.outcome == "SL"]
    if gbp_sl:
        print(f"\n  GBPUSD SL DIAGNOSTIC ({len(gbp_sl)} trades)")
        print(f"  {'Date':>10s} {'Time':>5s} {'Dir':>4s}  {'SL':>5s}  {'TP1':>5s}  {'MFE':>5s}  {'Candles':>7s}  {'Verdict'}")
        print(f"  {'-'*70}")
        noise_count = 0
        for t in gbp_sl:
            ts_short = t.time[11:16] if len(t.time) > 16 else t.time
            if t.candles <= 3:
                verdict = "NOISE — immediate reversal"
                noise_count += 1
            elif t.mfe_pips >= t.sl_pips * 0.5:
                verdict = f"RUNNER REVERSED — ran {t.mfe_pips:.0f}/{t.tp1_pips:.0f} then failed"
            else:
                verdict = "GENUINE FAIL — never developed"
            print(f"  {t.date:>10s} {ts_short:>5s} {t.direction:>4s}  {t.sl_pips:>5.1f}  {t.tp1_pips:>5.1f}  "
                  f"{t.mfe_pips:>5.1f}  {t.candles:>5d}x5m  {verdict}")
        print(f"\n  Noise stops (<=3 candles): {noise_count}/{len(gbp_sl)}")
        avg_mfe = sum(t.mfe_pips for t in gbp_sl) / len(gbp_sl)
        avg_sl = sum(t.sl_pips for t in gbp_sl) / len(gbp_sl)
        print(f"  Avg MFE before SL: {avg_mfe:.1f} pips  |  Avg SL width: {avg_sl:.1f} pips")

    # --- GBPUSD HOURLY BREAKDOWN ---
    print(f"\n  GBPUSD HOURLY BREAKDOWN (entry hour UTC)")
    print(f"  {'Hour':>6s}  {'Trades':>6s}  {'W':>3s}  {'L':>3s}  {'WR':>5s}  {'Total':>7s}  {'Avg':>6s}  {'Verdict'}")
    print(f"  {'-'*62}")
    hourly: Dict[int, list] = defaultdict(list)
    for t in gbp:
        # Extract hour from time string (format: "YYYY-MM-DD HH:MM:...")
        h = int(t.time[11:13])
        hourly[h].append(t)
    for h in range(6, 18):
        trades = hourly.get(h, [])
        if not trades:
            print(f"  {h:02d}:00        —")
            continue
        wins = [t for t in trades if (t.pnl_pips or 0) > 0]
        losses = [t for t in trades if (t.pnl_pips or 0) <= 0]
        total = sum(t.pnl_pips or 0 for t in trades)
        avg = total / len(trades)
        wr = len(wins) / len(trades) * 100
        verdict = "PROFITABLE" if total > 0 else "LOSING"
        print(f"  {h:02d}:00  {len(trades):>6d}  {len(wins):>3d}  {len(losses):>3d}  {wr:>4.0f}%  {total:>+7.1f}  {avg:>+6.1f}  {verdict}")

    print(f"\n  Raw GBPUSD sweep detections by date:")
    gbp_raw_by_date = defaultdict(list)
    for d in gbp_raw:
        gbp_raw_by_date[d["date"]].append(d)
    for date_str in sorted(gbp_raw_by_date.keys()):
        dets = gbp_raw_by_date[date_str]
        print(f"    {date_str}: {len(dets)} sweeps")
        for d in dets:
            ts_short = d["time"][11:16] if len(d["time"]) > 16 else d["time"]
            print(f"      {ts_short} {d['direction']} @ {d['entry']:.1f} [V{d['variant']}] {d['source']}")

    # Per-day average
    all_dates = sorted(set(d["date"] for d in raw_detections))
    if all_dates:
        gbp_dates = sorted(set(d["date"] for d in gbp_raw))
        avg = len(gbp_raw) / len(gbp_dates) if gbp_dates else 0
        print(f"\n  GBPUSD: {len(gbp_raw)} sweeps over {len(gbp_dates)} days = {avg:.1f} sweeps/day avg")
        total_raw_per_day = len(raw_detections) / len(all_dates)
        print(f"  All pairs: {len(raw_detections)} sweeps over {len(all_dates)} days = {total_raw_per_day:.1f}/day avg")

    # --- GBPUSD UTILISATION ANALYSIS ---
    gbp_skipped = [s for s in skipped_detections if s["symbol"] == "GBPUSD"]
    if gbp or gbp_skipped:
        print("\n" + "=" * 80)
        print("  GBPUSD UTILISATION ANALYSIS — WHY PIPS ARE LEFT ON THE TABLE")
        print("=" * 80)

        gbp_dates = sorted(set(
            [t.date for t in gbp] + [s["date"] for s in gbp_skipped]
        ))
        for date_str in gbp_dates:
            day_trades = [t for t in gbp if t.date == date_str]
            day_skipped = [s for s in gbp_skipped if s["date"] == date_str]
            day_pnl = sum(t.pnl_pips or 0 for t in day_trades)

            print(f"\n  {date_str}  |  {len(day_trades)} trades executed, {len(day_skipped)} detections skipped  |  P&L: {day_pnl:+.1f}")

            # Build timeline: entries, exits, skips
            events = []
            for t in day_trades:
                entry_ts = t.time[11:16]
                exit_ts = (t.exit_time or t.time)[11:16]
                hold_mins = t.candles * 5
                events.append(("TRADE", entry_ts, exit_ts, t))
                print(f"    {entry_ts} ENTER {t.direction:>4s} [{t.source}] → {exit_ts} {t.outcome} {t.pnl_pips or 0:+.1f}  ({hold_mins}m hold, MFE {t.mfe_pips:.0f}/{t.tp1_pips:.0f})")

            for s in day_skipped:
                skip_ts = s["time"][11:16]
                print(f"    {skip_ts} SKIP  {s['direction']:>4s} [{s['source']}]  — blocked by: {s['blocker']}")

            # Calculate time utilisation
            session_mins = 10 * 60  # 07:00-17:00 = 600 mins
            in_trade_mins = sum(t.candles * 5 for t in day_trades)
            idle_mins = session_mins - in_trade_mins
            print(f"    ── Time: {in_trade_mins}m in trade, {idle_mins}m idle of {session_mins}m session ({in_trade_mins*100/session_mins:.0f}% utilised)")

    print()


if __name__ == "__main__":
    run()
