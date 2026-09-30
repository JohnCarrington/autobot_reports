#!/usr/bin/env python3
"""
backtest_replay.py — Strict time-ordered replay engine (production-config aligned).

Matches the deployed strategy stack as of 2026-04-08:
  - BRIEFING_SWEEP on GBPUSD only
  - WINDOW_SWEEP on all pairs (with MACD crossover gate)
  - 3CO on all pairs
  - NEWS_STRATEGY on all pairs
  - BRIEFING_LIQUIDITY disabled
  - One trade at a time across ALL epics
  - Exit logic:
    * BE stop at +12p (all strategies)
    * Trail after TP1 at 15p for BRIEFING_SWEEP / WINDOW_SWEEP
    * Momentum TP1/TP2/TP3 for 3CO
    * Fixed TP for NEWS
"""

import json, os, sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

sys.path.insert(0, "/opt/tradingbot")
os.chdir("/opt/tradingbot")
from dotenv import load_dotenv
load_dotenv()

from briefing_sweep import BriefingSweepStrategy
from indicators import add_indicators, IndicatorsConfig
from trade_manager import select_tp_levels

# ── Config ────────────────────────────────────────────────────────
PAIRS = {
    "GBPUSD": "CS.D.GBPUSD.TODAY.IP",
    "EURUSD": "CS.D.EURUSD.TODAY.IP",
    "USDJPY": "CS.D.USDJPY.TODAY.IP",
    "USDCAD": "CS.D.USDCAD.TODAY.IP",
    "GBPJPY": "CS.D.GBPJPY.TODAY.IP",
}
DATES = [
    "2026-03-23", "2026-03-24", "2026-03-25",
    "2026-03-26", "2026-03-27", "2026-03-28", "2026-03-29",
    "2026-03-30", "2026-03-31",
    "2026-04-01", "2026-04-02", "2026-04-03",
    "2026-04-04", "2026-04-05", "2026-04-06", "2026-04-07", "2026-04-08",
]
PPP = 1.0
WARMUP = 60
SESSION_START_H = 7
SESSION_END_H = 17
COOLDOWN = timedelta(minutes=60)

# BE stop
BE_TRIGGER_PIPS = 12.0
BE_OFFSET_PIPS = 1.0

# Trail after TP1 (BRIEFING_SWEEP + WINDOW_SWEEP)
TRAIL_AFTER_TP1_PIPS = 15.0

# 3CO momentum TP retrace
THREE_CO_PULLBACK_PIPS = 25.0  # matches BRIEFING_TP_PULLBACK_PIPS

# WINDOW_SWEEP config (single-phase: BB touch + hist reducing)
WS_MORNING_BST = (10, 30, 11, 30)
WS_AFTERNOON_BST = (13, 30, 14, 30)
WS_SL_PIPS = 20.0
MACD_FAST = 35
MACD_SLOW = 45
MACD_SIGNAL_P = 30

# BRIEFING_SWEEP pair filter
BRIEFING_SWEEP_PAIRS = {"GBPUSD"}

BRIEFING_SCHED = [
    (0, 0, "Asian"), (5, 30, "London"), (7, 0, "London_Open"),
    (9, 45, "Mid-session"), (12, 0, "NY"), (14, 0, "NY_Mid"),
]

# NEWS config
NEWS_SPIKE_MIN_PIPS = 15.0
NEWS_STALL_CANDLES = 2
NEWS_CONFIRM_PIPS = 5.0
NEWS_TIMEOUT_CANDLES = 12
NEWS_EVENTS = [
    ("2026-03-25", 7, 0, "GBP", ["GBPUSD"], "CPI y/y"),
    ("2026-03-27", 13, 30, "USD", ["GBPUSD", "EURUSD", "USDJPY", "USDCAD"], "US Final GDP q/q"),
    ("2026-04-01", 12, 15, "USD", ["GBPUSD", "EURUSD", "USDJPY"], "ADP Non-Farm Employ"),
    ("2026-04-01", 14, 0, "USD", ["GBPUSD", "EURUSD", "USDJPY"], "ISM Manufacturing PMI"),
    ("2026-04-03", 12, 30, "USD", ["GBPUSD", "EURUSD", "USDJPY"], "Core PCE / Final GDP"),
]

# 3CO config
THREE_CO_SL_PIPS = 20.0
THREE_CO_SL_PIPS_JPY = 25.0
THREE_CO_TP1_PIPS = 25.0
SESSION_OPENS = {
    "GBPUSD": [(7, 0)],
    "EURUSD": [(7, 0)],
    "USDJPY": [(6, 45)],
    "USDCAD": [(13, 30)],
    "GBPJPY": [(6, 45)],
}

IND_CFG = IndicatorsConfig(
    ema_period=50, bb_period=20, bb_std=2.0,
    macd_fast=MACD_FAST, macd_slow=MACD_SLOW, macd_signal=MACD_SIGNAL_P,
    aroon_period=14,
)


# ── Monkey-patch datetime for BriefingSweepStrategy ────────────────
import briefing_sweep as _bs_mod
_real_dt = datetime


class _SimDt(datetime):
    _now = None

    @classmethod
    def now(cls, tz=None):
        if cls._now is not None and tz is not None:
            return cls._now
        return _real_dt.now(tz)


_bs_mod.datetime = _SimDt


# ── Data types ────────────────────────────────────────────────────
@dataclass
class Candle:
    ts: datetime
    pair: str
    o: float
    h: float
    l: float
    c: float


@dataclass
class Trade:
    pair: str
    date: str
    strategy: str
    signal_time: str
    fill_time: str
    direction: str
    entry: float
    sl_price: float
    tp1_price: float
    sl_pips: float
    tp1_pips: float
    source: str
    # TP2/TP3 for 3CO momentum
    tp2_price: Optional[float] = None
    tp3_price: Optional[float] = None
    tp2_pips: Optional[float] = None
    tp3_pips: Optional[float] = None
    # State
    be_applied: bool = False
    tp1_hit: bool = False
    trail_best: float = 0.0
    phase: str = "OPEN"  # OPEN → TP1 → TP2 → TP3
    swing_extreme: float = 0.0
    exit_time: Optional[str] = None
    exit_price: Optional[float] = None
    outcome: Optional[str] = None
    pnl_pips: Optional[float] = None


@dataclass
class PairState:
    pair: str
    epic: str
    candle_history: List[Candle] = field(default_factory=list)
    strat: BriefingSweepStrategy = field(default_factory=BriefingSweepStrategy)
    open_trade: Optional[Trade] = None
    pending_signal: Optional[Dict] = None
    last_signal_ts: Optional[datetime] = None
    last_date: Optional[str] = None
    # NEWS state machine
    news_anchor_price: Optional[float] = None
    news_spike_detected: bool = False
    news_spike_dir: Optional[str] = None
    news_spike_extreme: Optional[float] = None
    news_stall_detected: bool = False
    news_stall_price: Optional[float] = None
    news_stall_count: int = 0
    news_confirm_pending: bool = False
    news_event_ts: Optional[datetime] = None
    news_candles_since: int = 0
    # 3CO state
    three_co_checked_today: bool = False
    # WINDOW_SWEEP one-per-window-per-day
    ws_fired: Dict[str, bool] = field(default_factory=dict)


# ── Helpers ───────────────────────────────────────────────────────
def load_day_candles(pair: str, date: str) -> List[Candle]:
    p = Path(f"/opt/tradingbot/cache/test_candles_{pair}_{date}.json")
    if p.exists():
        with open(p) as f:
            raw = json.load(f)
        if raw:
            candles = []
            for r in raw:
                ts = pd.to_datetime(r["timestamp"], utc=True)
                if hasattr(ts, "to_pydatetime"):
                    ts = ts.to_pydatetime()
                candles.append(Candle(ts=ts, pair=pair, o=float(r["open"]),
                                      h=float(r["high"]), l=float(r["low"]),
                                      c=float(r["close"])))
            return candles

    csv_path = Path(f"/opt/tradingbot/data/candles/{pair}/{date}.csv")
    if csv_path.exists():
        df = pd.read_csv(csv_path, parse_dates=["timestamp"])
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
        candles = []
        for _, r in df.iterrows():
            ts = r["timestamp"]
            if hasattr(ts, "to_pydatetime"):
                ts = ts.to_pydatetime()
            candles.append(Candle(ts=ts, pair=pair, o=float(r["open"]),
                                  h=float(r["high"]), l=float(r["low"]),
                                  c=float(r["close"])))
        return candles
    return []


def get_briefing(pair: str, date: str, ts: datetime) -> Optional[Dict]:
    """Load the historical briefing that was active at this timestamp."""
    best = None
    for h, m, name in BRIEFING_SCHED:
        gt = datetime(ts.year, ts.month, ts.day, h, m, tzinfo=timezone.utc)
        if ts >= gt:
            best = name
    if not best:
        return None
    # Try replay briefings first, then logs/ (production), then briefings_live/
    for base in ("/opt/tradingbot/data/briefings_replay", "/opt/tradingbot/logs", "/opt/tradingbot/data/briefings_live"):
        p = Path(f"{base}/briefing_{pair}_{date}_{best}.json")
        if p.exists():
            with open(p) as f:
                return json.load(f)
    return None


def build_df(candle_history: List[Candle], warmup: int = WARMUP) -> Optional[pd.DataFrame]:
    if len(candle_history) < 1:
        return None
    start = max(0, len(candle_history) - warmup)
    rows = [{"timestamp": c.ts, "open": c.o, "high": c.h, "low": c.l, "close": c.c}
            for c in candle_history[start:]]
    df = pd.DataFrame(rows)
    try:
        df = add_indicators(df, IND_CFG)
    except Exception:
        pass
    return df


def build_rc_all(candle_history: List[Candle], df_ind: pd.DataFrame) -> list:
    """Build recent_closed list in the format BriefingSweepStrategy expects."""
    rc = []
    n = min(len(candle_history), len(df_ind))
    tail = df_ind.tail(n)
    hist_tail = candle_history[-n:]
    macd_hist_key = f"MACD_HIST_{MACD_FAST}_{MACD_SLOW}_{MACD_SIGNAL_P}"
    for i, (_, row) in enumerate(tail.iterrows()):
        c = hist_tail[i]
        indicators = {}
        for k in (macd_hist_key, "MACD_HIST"):
            if k in row.index and row[k] == row[k]:
                indicators[k] = float(row[k])
        rc.append({
            "candle": {"open": c.o, "high": c.h, "low": c.l, "close": c.c},
            "indicators": indicators,
        })
    return rc


def pip_pnl(direction: str, entry: float, price: float) -> float:
    return (price - entry) / PPP if direction == "BUY" else (entry - price) / PPP


def build_briefing_levels(briefing: Dict) -> list:
    levels = []
    for src in ("key_levels", "major_levels"):
        d = briefing.get(src, {})
        maj = src == "major_levels"
        for v in d.get("resistance", []):
            if v is not None:
                levels.append({"price": float(v), "level_type": "resistance", "source": src, "major": maj})
        for v in d.get("support", []):
            if v is not None:
                levels.append({"price": float(v), "level_type": "support", "source": src, "major": maj})
    lp = briefing.get("liquidity_pools", {})
    for v in lp.get("buy_side", []):
        if v is not None:
            levels.append({"price": float(v), "level_type": "resistance", "source": "liq", "major": False})
    for v in lp.get("sell_side", []):
        if v is not None:
            levels.append({"price": float(v), "level_type": "support", "source": "liq", "major": False})
    return levels


# ── Trade management ──────────────────────────────────────────────
def apply_be_stop(trade: Trade, candle: Candle) -> None:
    """Move SL to breakeven + offset once profit exceeds BE_TRIGGER_PIPS."""
    if trade.be_applied:
        return
    is_buy = trade.direction == "BUY"
    best = candle.h if is_buy else candle.l
    pnl = pip_pnl(trade.direction, trade.entry, best)
    if pnl >= BE_TRIGGER_PIPS:
        if is_buy:
            new_sl = trade.entry + BE_OFFSET_PIPS * PPP
            trade.sl_price = max(trade.sl_price, new_sl)
        else:
            new_sl = trade.entry - BE_OFFSET_PIPS * PPP
            trade.sl_price = min(trade.sl_price, new_sl)
        trade.be_applied = True


def manage_trade_trail(trade: Trade, candle: Candle) -> Optional[str]:
    """Manage BRIEFING_SWEEP / WINDOW_SWEEP: BE stop + trail after TP1."""
    is_buy = trade.direction == "BUY"
    apply_be_stop(trade, candle)

    if not trade.tp1_hit:
        # Check SL
        sl_hit = (candle.l <= trade.sl_price) if is_buy else (candle.h >= trade.sl_price)
        tp_hit = (candle.h >= trade.tp1_price) if is_buy else (candle.l <= trade.tp1_price)

        if sl_hit and tp_hit:
            trade.exit_price = trade.sl_price
            trade.pnl_pips = pip_pnl(trade.direction, trade.entry, trade.sl_price)
            return "SL"
        if sl_hit:
            trade.exit_price = trade.sl_price
            trade.pnl_pips = pip_pnl(trade.direction, trade.entry, trade.sl_price)
            return "SL"
        if tp_hit:
            trade.tp1_hit = True
            trade.phase = "TP1"
            # Move SL to breakeven
            trade.sl_price = trade.entry
            # Set trail best from this candle
            if is_buy:
                trade.trail_best = candle.h
            else:
                trade.trail_best = candle.l
            return None
    else:
        # Trail is active — update best, check SL (breakeven) and trail retrace
        if is_buy:
            trade.trail_best = max(trade.trail_best, candle.h)
            retrace = (trade.trail_best - candle.l) / PPP
            worst_price = candle.l
        else:
            trade.trail_best = min(trade.trail_best, candle.l)
            retrace = (candle.h - trade.trail_best) / PPP
            worst_price = candle.h

        # SL at breakeven still active
        sl_hit = (candle.l <= trade.sl_price) if is_buy else (candle.h >= trade.sl_price)
        if sl_hit:
            trade.exit_price = trade.sl_price
            trade.pnl_pips = pip_pnl(trade.direction, trade.entry, trade.sl_price)
            return "BE"

        if retrace >= TRAIL_AFTER_TP1_PIPS:
            exit_pnl = pip_pnl(trade.direction, trade.entry, worst_price)
            # Trail exit: at least TP1 pips minus trail distance
            trade.pnl_pips = max(exit_pnl, trade.tp1_pips - TRAIL_AFTER_TP1_PIPS)
            if is_buy:
                trade.exit_price = trade.trail_best - TRAIL_AFTER_TP1_PIPS * PPP
            else:
                trade.exit_price = trade.trail_best + TRAIL_AFTER_TP1_PIPS * PPP
            return "TRAIL"

    return None


def _simple_momentum(df_ind: pd.DataFrame, direction: str) -> bool:
    """Simplified momentum check: 2 of 3 candle bodies in direction + MACD expanding."""
    if df_ind is None or len(df_ind) < 3:
        return False
    try:
        tail = df_ind.tail(3)
        bodies_in_dir = 0
        for _, row in tail.iterrows():
            o, c = float(row["open"]), float(row["close"])
            if direction == "BUY" and c > o:
                bodies_in_dir += 1
            elif direction == "SELL" and c < o:
                bodies_in_dir += 1

        hist_key = f"MACD_HIST_{MACD_FAST}_{MACD_SLOW}_{MACD_SIGNAL_P}"
        if hist_key in df_ind.columns and len(df_ind) >= 2:
            curr = float(df_ind.iloc[-1][hist_key])
            prev = float(df_ind.iloc[-2][hist_key])
            if direction == "BUY":
                macd_ok = curr > prev
            else:
                macd_ok = curr < prev
        else:
            macd_ok = False

        return bodies_in_dir >= 2 and macd_ok
    except Exception:
        return False


def manage_trade_3co(trade: Trade, candle: Candle, df_ind: Optional[pd.DataFrame]) -> Optional[str]:
    """Manage 3CO: BE stop + momentum TP1/TP2/TP3."""
    is_buy = trade.direction == "BUY"
    apply_be_stop(trade, candle)

    # SL check
    sl_hit = (candle.l <= trade.sl_price) if is_buy else (candle.h >= trade.sl_price)
    if sl_hit:
        trade.exit_price = trade.sl_price
        trade.pnl_pips = pip_pnl(trade.direction, trade.entry, trade.sl_price)
        return "SL"

    # TP3: always close
    if trade.tp3_price is not None:
        tp3_hit = (candle.h >= trade.tp3_price) if is_buy else (candle.l <= trade.tp3_price)
        if tp3_hit and trade.phase in ("OPEN", "TP1", "TP2"):
            trade.exit_price = trade.tp3_price
            trade.pnl_pips = pip_pnl(trade.direction, trade.entry, trade.tp3_price)
            return "TP3"

    # TP2: momentum check
    if trade.tp2_price is not None and trade.phase == "TP1":
        tp2_hit = (candle.h >= trade.tp2_price) if is_buy else (candle.l <= trade.tp2_price)
        if tp2_hit:
            if _simple_momentum(df_ind, trade.direction):
                trade.phase = "TP2"
                trade.sl_price = trade.tp1_price  # SL → TP1
                trade.swing_extreme = candle.h if is_buy else candle.l
                return None
            else:
                trade.exit_price = trade.tp2_price
                trade.pnl_pips = pip_pnl(trade.direction, trade.entry, trade.tp2_price)
                return "TP2"

    # TP1: momentum check
    tp1_hit = (candle.h >= trade.tp1_price) if is_buy else (candle.l <= trade.tp1_price)
    if tp1_hit and trade.phase == "OPEN":
        if _simple_momentum(df_ind, trade.direction):
            trade.phase = "TP1"
            trade.sl_price = trade.entry  # SL → breakeven
            trade.swing_extreme = candle.h if is_buy else candle.l
            return None
        else:
            trade.exit_price = trade.tp1_price
            trade.pnl_pips = pip_pnl(trade.direction, trade.entry, trade.tp1_price)
            return "TP1"

    # Pullback trail between TP levels (when in TP1 or TP2 phase)
    if trade.phase in ("TP1", "TP2"):
        if is_buy:
            trade.swing_extreme = max(trade.swing_extreme, candle.h)
            pullback = (trade.swing_extreme - candle.l) / PPP
        else:
            trade.swing_extreme = min(trade.swing_extreme, candle.l)
            pullback = (candle.h - trade.swing_extreme) / PPP
        if pullback >= THREE_CO_PULLBACK_PIPS:
            pnl = pip_pnl(trade.direction, trade.entry, candle.c)
            trade.exit_price = candle.c
            trade.pnl_pips = pnl
            return f"{trade.phase}+PB"

    return None


def manage_trade_news(trade: Trade, candle: Candle) -> Optional[str]:
    """Manage NEWS: BE stop + fixed TP."""
    is_buy = trade.direction == "BUY"
    apply_be_stop(trade, candle)

    sl_hit = (candle.l <= trade.sl_price) if is_buy else (candle.h >= trade.sl_price)
    tp_hit = (candle.h >= trade.tp1_price) if is_buy else (candle.l <= trade.tp1_price)

    if sl_hit and tp_hit:
        trade.exit_price = trade.sl_price
        trade.pnl_pips = pip_pnl(trade.direction, trade.entry, trade.sl_price)
        return "SL"
    if sl_hit:
        trade.exit_price = trade.sl_price
        trade.pnl_pips = pip_pnl(trade.direction, trade.entry, trade.sl_price)
        return "SL"
    if tp_hit:
        trade.exit_price = trade.tp1_price
        trade.pnl_pips = trade.tp1_pips
        return "TP"

    return None


def close_trade_at(trade: Trade, candle: Candle, reason: str):
    p = pip_pnl(trade.direction, trade.entry, candle.c)
    trade.pnl_pips = p
    trade.outcome = reason
    trade.exit_time = candle.ts.strftime("%H:%M")
    trade.exit_price = candle.c


# ── NEWS state machine ────────────────────────────────────────────
def get_news_event(pair: str, date: str) -> Optional[Tuple[int, int, str]]:
    for d, eh, em, ccy, pairs, label in NEWS_EVENTS:
        if d == date and pair in pairs:
            return (eh, em, label)
    return None


def reset_news_state(ps: PairState):
    ps.news_anchor_price = None
    ps.news_spike_detected = False
    ps.news_spike_dir = None
    ps.news_spike_extreme = None
    ps.news_stall_detected = False
    ps.news_stall_price = None
    ps.news_stall_count = 0
    ps.news_confirm_pending = False
    ps.news_event_ts = None
    ps.news_candles_since = 0


# ── 3CO check ────────────────────────────────────────────────────
def check_3co(ps: PairState, candle: Candle, date: str, briefing: Optional[Dict]) -> Optional[Dict]:
    """Check 3CO pattern. Requires session_bias alignment."""
    if briefing is None:
        return None
    session_bias = str(briefing.get("session_bias", "")).upper()

    opens = SESSION_OPENS.get(ps.pair, [(7, 0)])
    for oh, om in opens:
        open_ts = datetime(candle.ts.year, candle.ts.month, candle.ts.day,
                           oh, om, tzinfo=timezone.utc)
        open_candles = [c for c in ps.candle_history if c.ts >= open_ts]
        if len(open_candles) != 4:
            continue
        if open_candles[-1].ts != candle.ts:
            continue

        c1, c2, c3 = open_candles[0], open_candles[1], open_candles[2]
        b1 = (c1.c - c1.o) / PPP
        b2 = (c2.c - c2.o) / PPP
        b3 = (c3.c - c3.o) / PPP

        if b1 > 0 and b2 > 0 and b3 > 0:
            direction = "BUY"
        elif b1 < 0 and b2 < 0 and b3 < 0:
            direction = "SELL"
        else:
            continue

        # Bias alignment
        if direction == "BUY" and session_bias != "BULLISH":
            continue
        if direction == "SELL" and session_bias != "BEARISH":
            continue

        c4 = open_candles[3]
        c4_body = (c4.c - c4.o) / PPP
        if (direction == "BUY" and c4_body < 0) or (direction == "SELL" and c4_body > 0):
            continue

        ab1, ab2, ab3 = abs(b1), abs(b2), abs(b3)
        if not (ab3 > ab2 > ab1):
            continue

        sl_pips = THREE_CO_SL_PIPS_JPY if "JPY" in ps.pair else THREE_CO_SL_PIPS

        # Build TP levels from briefing
        levels = build_briefing_levels(briefing)
        tp = select_tp_levels(candle.c, direction, levels, ps.pair)

        return {
            "direction": direction,
            "sl_pips": sl_pips,
            "tp1_pips": tp["tp1_pips"],
            "tp2_pips": tp["tp2_pips"],
            "tp3_pips": tp["tp3_pips"],
            "source": "3co_momentum",
            "time": candle.ts.strftime("%H:%M"),
        }
    return None


# ── WINDOW_SWEEP check ───────────────────────────────────────────
def check_window_sweep(
    ps: PairState,
    candle: Candle,
    df_ind: pd.DataFrame,
    briefing: Optional[Dict],
    date: str,
) -> Optional[Dict]:
    """Single-phase WINDOW_SWEEP detector for backtesting.

    Entry fires immediately when both conditions met on the same 5M candle:
      BUY: low <= lower BB AND prior 3 candles hist positive & reducing
      SELL: high >= upper BB AND prior 3 candles hist negative & reducing
    """
    if df_ind is None or len(df_ind) < 20:
        return None

    # Time window (BST)
    utc_h, utc_m = candle.ts.hour, candle.ts.minute
    month = candle.ts.month
    is_bst = month >= 4 or (month == 3 and candle.ts.day >= 29)
    bst_h = utc_h + (1 if is_bst else 0)
    bst_min = bst_h * 60 + utc_m

    morn_s = WS_MORNING_BST[0] * 60 + WS_MORNING_BST[1]
    morn_e = WS_MORNING_BST[2] * 60 + WS_MORNING_BST[3]
    aftn_s = WS_AFTERNOON_BST[0] * 60 + WS_AFTERNOON_BST[1]
    aftn_e = WS_AFTERNOON_BST[2] * 60 + WS_AFTERNOON_BST[3]

    if morn_s <= bst_min < morn_e:
        window = "MORNING"
    elif aftn_s <= bst_min < aftn_e:
        window = "AFTERNOON"
    else:
        return None

    # BB bands
    last = df_ind.iloc[-1]
    bb_upper = bb_lower = None
    for k in ("BB_UPPER_20_2", "BB_UPPER"):
        if k in last.index and last[k] == last[k]:
            bb_upper = float(last[k]); break
    for k in ("BB_LOWER_20_2", "BB_LOWER"):
        if k in last.index and last[k] == last[k]:
            bb_lower = float(last[k]); break
    if bb_upper is None or bb_lower is None:
        return None

    # BB touch check
    lower_touch = candle.l <= bb_lower
    upper_touch = candle.h >= bb_upper
    if not lower_touch and not upper_touch:
        return None

    direction = "BUY" if lower_touch else "SELL"

    # No briefing bias filter — WINDOW_SWEEP fires on price action only

    # MACD histogram: 3 candles BEFORE pierce must be correct sign & reducing
    #   BUY:  hist positive (green) and reducing — bullish momentum exhausting
    #   SELL: hist negative (red) and reducing — bearish momentum exhausting
    hist_key = f"MACD_HIST_{MACD_FAST}_{MACD_SLOW}_{MACD_SIGNAL_P}"
    if hist_key not in df_ind.columns or len(df_ind) < 4:
        return None
    try:
        raw3 = [float(df_ind.iloc[i][hist_key]) for i in range(-4, -1)]
    except Exception:
        return None
    if direction == "BUY":
        if not all(v > 0 for v in raw3):
            return None
    else:
        if not all(v < 0 for v in raw3):
            return None
    h3 = [abs(v) for v in raw3]
    if not (h3[2] < h3[1] < h3[0]):
        return None

    # One per window per day
    ws_key = f"{ps.pair}_{date}_{window}"
    if ws_key in ps.ws_fired:
        return None
    ps.ws_fired[ws_key] = True

    levels = build_briefing_levels(briefing) if briefing else []
    tp = select_tp_levels(candle.c, direction, levels, ps.pair)

    return {
        "direction": direction,
        "sl_pips": WS_SL_PIPS,
        "tp1_pips": tp["tp1_pips"],
        "source": f"window_sweep_{window.lower()}",
        "time": candle.ts.strftime("%H:%M"),
        "strategy": "WINDOW_SWEEP",
    }


# ══════════════════════════════════════════════════════════════════
#  MAIN REPLAY ENGINE
# ══════════════════════════════════════════════════════════════════
def any_open_trade(pair_states: Dict[str, PairState]) -> bool:
    """One-trade-at-a-time: check if any pair has an open position."""
    return any(ps.open_trade is not None for ps in pair_states.values())


def replay_day(date: str, pair_states: Dict[str, PairState]) -> List[Trade]:
    completed: List[Trade] = []

    all_candles: List[Candle] = []
    for pair in PAIRS:
        all_candles.extend(load_day_candles(pair, date))
    if not all_candles:
        return []

    all_candles.sort(key=lambda c: (c.ts, c.pair))

    for candle in all_candles:
        pair = candle.pair
        ps = pair_states[pair]
        h = candle.ts.hour

        if ps.last_date != date:
            ps.strat = BriefingSweepStrategy()
            ps.last_date = date
            ps.pending_signal = None
            ps.three_co_checked_today = False
            ps.ws_fired = {}
            reset_news_state(ps)

        _SimDt._now = candle.ts

        ps.candle_history.append(candle)
        if len(ps.candle_history) > WARMUP + 20:
            ps.candle_history = ps.candle_history[-(WARMUP + 10):]

        # ── Fill pending signal ──
        if ps.pending_signal is not None and ps.open_trade is None and not any_open_trade(pair_states):
            sig = ps.pending_signal
            ps.pending_signal = None
            d = sig["direction"]
            fill = candle.o
            if d == "BUY":
                sl_p = fill - sig["sl_pips"] * PPP
                tp_p = fill + sig["tp1_pips"] * PPP
            else:
                sl_p = fill + sig["sl_pips"] * PPP
                tp_p = fill - sig["tp1_pips"] * PPP

            trade = Trade(
                pair=pair, date=date, strategy=sig["strategy"],
                signal_time=sig["time"], fill_time=candle.ts.strftime("%H:%M"),
                direction=d, entry=fill,
                sl_price=sl_p, tp1_price=tp_p,
                sl_pips=sig["sl_pips"], tp1_pips=sig["tp1_pips"],
                source=sig["source"],
            )

            # 3CO: set TP2/TP3
            if sig["strategy"] == "3CO" and sig.get("tp2_pips"):
                if d == "BUY":
                    trade.tp2_price = fill + sig["tp2_pips"] * PPP
                    trade.tp3_price = fill + sig["tp3_pips"] * PPP
                else:
                    trade.tp2_price = fill - sig["tp2_pips"] * PPP
                    trade.tp3_price = fill - sig["tp3_pips"] * PPP
                trade.tp2_pips = sig["tp2_pips"]
                trade.tp3_pips = sig["tp3_pips"]

            ps.open_trade = trade
        elif ps.pending_signal is not None and any_open_trade(pair_states):
            ps.pending_signal = None  # Drop signal — one trade at a time

        # ── Manage open trade ──
        if ps.open_trade is not None:
            if h >= SESSION_END_H:
                close_trade_at(ps.open_trade, candle, "17:00")
                completed.append(ps.open_trade)
                ps.open_trade = None
            else:
                df_ind = build_df(ps.candle_history) if ps.open_trade.strategy == "3CO" else None
                if ps.open_trade.strategy in ("BRIEFING_SWEEP", "WINDOW_SWEEP"):
                    result = manage_trade_trail(ps.open_trade, candle)
                elif ps.open_trade.strategy == "3CO":
                    result = manage_trade_3co(ps.open_trade, candle, df_ind)
                else:  # NEWS
                    result = manage_trade_news(ps.open_trade, candle)

                if result:
                    ps.open_trade.exit_time = candle.ts.strftime("%H:%M")
                    ps.open_trade.outcome = result
                    completed.append(ps.open_trade)
                    ps.open_trade = None

        # ── Skip signal eval if outside session, position open anywhere, pending ──
        if h < SESSION_START_H or h >= SESSION_END_H:
            continue
        if any_open_trade(pair_states):
            continue
        if any(p.pending_signal is not None for p in pair_states.values()):
            continue

        # ── Cooldown check ──
        cooldown_active = ps.last_signal_ts and (candle.ts - ps.last_signal_ts) < COOLDOWN

        # ── NEWS strategy ──
        news_event = get_news_event(pair, date)
        if news_event is not None:
            eh, em, label = news_event
            event_ts = datetime(candle.ts.year, candle.ts.month, candle.ts.day,
                                eh, em, tzinfo=timezone.utc)

            if candle.ts >= event_ts and ps.news_event_ts is None:
                prev_candles = [c for c in ps.candle_history if c.ts < event_ts]
                if prev_candles:
                    ps.news_anchor_price = prev_candles[-1].c
                    ps.news_event_ts = event_ts

            if ps.news_anchor_price is not None and candle.ts >= event_ts:
                ps.news_candles_since += 1

                if ps.news_candles_since <= NEWS_TIMEOUT_CANDLES:
                    if not ps.news_spike_detected:
                        up = (candle.h - ps.news_anchor_price) / PPP
                        dn = (ps.news_anchor_price - candle.l) / PPP
                        if up >= NEWS_SPIKE_MIN_PIPS:
                            ps.news_spike_detected = True
                            ps.news_spike_dir = "UP"
                            ps.news_spike_extreme = candle.h
                        elif dn >= NEWS_SPIKE_MIN_PIPS:
                            ps.news_spike_detected = True
                            ps.news_spike_dir = "DOWN"
                            ps.news_spike_extreme = candle.l

                    elif not ps.news_stall_detected:
                        new_extreme = False
                        if ps.news_spike_dir == "UP" and candle.h > ps.news_spike_extreme:
                            ps.news_spike_extreme = candle.h
                            new_extreme = True
                            ps.news_stall_count = 0
                        elif ps.news_spike_dir == "DOWN" and candle.l < ps.news_spike_extreme:
                            ps.news_spike_extreme = candle.l
                            new_extreme = True
                            ps.news_stall_count = 0
                        if not new_extreme:
                            ps.news_stall_count += 1
                        if ps.news_stall_count >= NEWS_STALL_CANDLES:
                            ps.news_stall_detected = True
                            ps.news_stall_price = candle.c
                            ps.news_confirm_pending = True

                    elif ps.news_confirm_pending:
                        move = (candle.c - ps.news_stall_price) / PPP
                        signal = None
                        reason_tag = None
                        if ps.news_spike_dir == "UP":
                            if move >= NEWS_CONFIRM_PIPS:
                                signal = "BUY"; reason_tag = "continuation"
                            elif move <= -NEWS_CONFIRM_PIPS:
                                signal = "SELL"; reason_tag = "reversal"
                        else:
                            if move <= -NEWS_CONFIRM_PIPS:
                                signal = "SELL"; reason_tag = "continuation"
                            elif move >= NEWS_CONFIRM_PIPS:
                                signal = "BUY"; reason_tag = "reversal"

                        if signal is not None:
                            _mins = (candle.ts - ps.news_event_ts).total_seconds() / 60
                            if _mins > 30:
                                ps.news_confirm_pending = False
                            else:
                                _spike_pips = abs(ps.news_spike_extreme - ps.news_anchor_price) / PPP
                                _news_sl = max(15.0, min(25.0, _spike_pips * 0.5))
                                _news_tp = max(30.0, min(120.0, _spike_pips * 1.5))
                                ps.pending_signal = {
                                    "direction": signal,
                                    "sl_pips": _news_sl,
                                    "tp1_pips": _news_tp,
                                    "source": f"news_{reason_tag}",
                                    "time": candle.ts.strftime("%H:%M"),
                                    "strategy": "NEWS",
                                }
                                ps.news_confirm_pending = False
                                continue

        # ── 3CO strategy ──
        if not ps.three_co_checked_today:
            briefing = get_briefing(pair, date, candle.ts)
            co_sig = check_3co(ps, candle, date, briefing)
            if co_sig is not None:
                ps.three_co_checked_today = True
                ps.pending_signal = {
                    "direction": co_sig["direction"],
                    "sl_pips": co_sig["sl_pips"],
                    "tp1_pips": co_sig["tp1_pips"],
                    "tp2_pips": co_sig.get("tp2_pips"),
                    "tp3_pips": co_sig.get("tp3_pips"),
                    "source": co_sig["source"],
                    "time": co_sig["time"],
                    "strategy": "3CO",
                }
                continue

        # ── Strategies with cooldown ──
        if cooldown_active:
            continue
        if len(ps.candle_history) < WARMUP:
            continue

        briefing = get_briefing(pair, date, candle.ts)
        if not briefing:
            continue

        df_ind = build_df(ps.candle_history)
        if df_ind is None:
            continue

        # ── WINDOW_SWEEP (all pairs) ──
        ws_sig = check_window_sweep(ps, candle, df_ind, briefing, date)
        if ws_sig is not None:
            ps.last_signal_ts = candle.ts
            ps.pending_signal = ws_sig
            continue

        # ── BRIEFING_SWEEP (GBPUSD only) ──
        if pair in BRIEFING_SWEEP_PAIRS:
            rc_all = build_rc_all(ps.candle_history, df_ind)
            try:
                dec = ps.strat.evaluate(pair, PAIRS[pair], rc_all, PPP, candle.c, briefing)
            except Exception:
                continue

            sig = str(dec.signal or "").upper()
            if sig in ("BUY", "SELL"):
                # Get TP1 from briefing levels
                levels = build_briefing_levels(briefing)
                tp = select_tp_levels(candle.c, sig, levels, pair)
                ps.last_signal_ts = candle.ts
                ps.pending_signal = {
                    "direction": sig,
                    "sl_pips": float(dec.sl or 20),
                    "tp1_pips": tp["tp1_pips"],
                    "source": (dec.debug or {}).get("entry_source", "briefing_sweep"),
                    "time": candle.ts.strftime("%H:%M"),
                    "strategy": "BRIEFING_SWEEP",
                }

    # ── End of day ──
    for pair, ps in pair_states.items():
        if ps.open_trade is not None:
            last_candles = [c for c in all_candles if c.pair == pair]
            if last_candles:
                close_trade_at(ps.open_trade, last_candles[-1], "EOD")
                completed.append(ps.open_trade)
            ps.open_trade = None
        ps.pending_signal = None

    return completed


# ══════════════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════════════
def main():
    print("=" * 100)
    print("  REPLAY ENGINE — Production config aligned (2026-04-08)")
    print("  BRIEFING_SWEEP (GBPUSD) | WINDOW_SWEEP (all, MACD cross) | 3CO (all) | NEWS (all)")
    print("  One trade at a time | BE +12p | Trail 15p after TP1 (BS/WS) | Momentum TP (3CO)")
    print("=" * 100)

    pair_states: Dict[str, PairState] = {}
    for pair, epic in PAIRS.items():
        pair_states[pair] = PairState(pair=pair, epic=epic)

    all_trades: List[Trade] = []

    for date in DATES:
        day_trades = replay_day(date, pair_states)
        all_trades.extend(day_trades)

    # ── Verify briefing source ──
    briefing_count = 0
    for date in DATES:
        for pair in PAIRS:
            for h, m, name in BRIEFING_SCHED:
                p = Path(f"/opt/tradingbot/logs/briefing_{pair}_{date}_{name}.json")
                if p.exists():
                    briefing_count += 1
    print(f"\n  Briefings loaded from: /opt/tradingbot/logs/ (historical, {briefing_count} files)")

    # ── Results ──
    STRAT_NAMES = ["WINDOW_SWEEP", "BRIEFING_SWEEP", "NEWS", "3CO"]
    strats: Dict[str, List[Trade]] = {s: [] for s in STRAT_NAMES}
    for t in all_trades:
        strats.setdefault(t.strategy, []).append(t)

    print("\n  ┌────────────────┬────────┬───────────┬──────┐")
    print("  │   Strategy     │ Trades │ Total Pip │  WR  │")
    print("  ├────────────────┼────────┼───────────┼──────┤")

    grand_trades = 0
    grand_pnl = 0.0
    grand_wins = 0

    for name in STRAT_NAMES:
        tlist = strats.get(name, [])
        n = len(tlist)
        pnl = sum(t.pnl_pips or 0 for t in tlist)
        w = sum(1 for t in tlist if (t.pnl_pips or 0) > 0)
        wr = w / n * 100 if n else 0
        print(f"  │ {name:<14} │ {n:>6} │ {pnl:>+9.1f} │ {wr:>3.0f}% │")
        grand_trades += n
        grand_pnl += pnl
        grand_wins += w

    gwr = grand_wins / grand_trades * 100 if grand_trades else 0
    print("  ├────────────────┼────────┼───────────┼──────┤")
    print(f"  │ {'COMBINED':<14} │ {grand_trades:>6} │ {grand_pnl:>+9.1f} │ {gwr:>3.0f}% │")
    print("  └────────────────┴────────┴───────────┴──────┘")

    # Per-pair
    print("\n  Per-pair breakdown:")
    print(f"  {'Pair':>8} {'WS':>8} {'BS':>8} {'NEWS':>8} {'3CO':>8} {'Total':>8}")
    print(f"  {'-'*52}")
    for pair in PAIRS:
        vals = {}
        for sn, tl in strats.items():
            vals[sn] = sum(t.pnl_pips or 0 for t in tl if t.pair == pair)
        total = sum(vals.values())
        print(f"  {pair:>8} {vals.get('WINDOW_SWEEP',0):>+8.1f} {vals.get('BRIEFING_SWEEP',0):>+8.1f} "
              f"{vals.get('NEWS',0):>+8.1f} {vals.get('3CO',0):>+8.1f} {total:>+8.1f}")

    # Per-day with equity curve
    print("\n  Per-day breakdown (equity curve):")
    print(f"  {'Date':>12} {'WS':>8} {'BS':>8} {'NEWS':>8} {'3CO':>8} {'TOTAL':>8} {'#':>4} {'Equity':>9}")
    print(f"  {'-'*72}")
    active_days = 0
    running_equity = 0.0
    for date in DATES:
        day_trades = [t for t in all_trades if t.date == date]
        if not day_trades:
            continue
        active_days += 1
        vals = {}
        for sn in strats:
            vals[sn] = sum(t.pnl_pips or 0 for t in strats[sn] if t.date == date)
        total = sum(vals.values())
        running_equity += total
        print(f"  {date:>12} {vals.get('WINDOW_SWEEP',0):>+8.1f} {vals.get('BRIEFING_SWEEP',0):>+8.1f} "
              f"{vals.get('NEWS',0):>+8.1f} {vals.get('3CO',0):>+8.1f} {total:>+8.1f} {len(day_trades):>4} {running_equity:>+9.1f}")

    daily_avg = grand_pnl / active_days if active_days > 0 else 0

    # Trade log
    print(f"\n  FULL TRADE LOG:")
    print(f"  {'Date':>10} {'Time':>5} {'Pair':>7} {'Strat':>14} {'Dir':>4} {'Entry':>9} "
          f"{'SL':>4} {'TP':>4} {'Out':>8} {'P&L':>7}")
    print(f"  {'-'*84}")
    for t in sorted(all_trades, key=lambda x: (x.date, x.fill_time)):
        print(f"  {t.date:>10} {t.fill_time:>5} {t.pair:>7} {t.strategy:>14} {t.direction:>4} "
              f"{t.entry:>9.1f} {t.sl_pips:>4.0f} {t.tp1_pips:>4.0f} {str(t.outcome):>8} "
              f"{(t.pnl_pips or 0):>+7.1f}")

    # Grand total
    print(f"\n{'='*100}")
    print(f"  GRAND TOTAL (REPLAY ENGINE)")
    print(f"{'='*100}")
    print(f"  Trades:        {grand_trades}")
    print(f"  Win rate:      {gwr:.0f}% ({grand_wins}W / {grand_trades - grand_wins}L)")
    print(f"  Total P&L:     {grand_pnl:+.1f} pips")
    print(f"  Active days:   {active_days}")
    print(f"  Avg pips/day:  {daily_avg:+.1f}")
    print(f"  @ £1/pip:      £{grand_pnl:+.2f} total | £{daily_avg:+.2f}/day")
    print(f"  @ £10/pip:     £{grand_pnl * 10:+.2f} total | £{daily_avg * 10:+.2f}/day")
    print(f"{'='*100}")

    return grand_trades, grand_pnl, grand_wins


if __name__ == "__main__":
    main()
