#!/usr/bin/env python3
"""
backtest_combined.py — Four-strategy combined backtest over 10-day dataset.

Strategies:
  WINDOW_SWEEP  — BB sweep entries (sweep_v1, sweep_v3) from briefing_liquidity
  BRIEFING_LIQ  — Trigger-close entries from briefing_liquidity
  NEWS          — Stall-and-confirm on high-impact news events (5M candle simulation)
  3CO           — Three consecutive directional candles from session open (candles 4-8)

Fill at next candle open | SL wins if ambiguous | Post-TP1 10p retrace | 17:00 close
"""

import json, os, sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd

sys.path.insert(0, "/opt/tradingbot")
os.chdir("/opt/tradingbot")
from dotenv import load_dotenv
load_dotenv()

from briefing_liquidity import BriefingLiquidityStrategy

# ── Config ────────────────────────────────────────────────────────
PAIRS = {
    "GBPUSD": "CS.D.GBPUSD.TODAY.IP",
    "EURUSD": "CS.D.EURUSD.TODAY.IP",
    "USDJPY": "CS.D.USDJPY.TODAY.IP",
    "USDCAD": "CS.D.USDCAD.TODAY.IP",
}
DATES = [
    "2026-03-23", "2026-03-24", "2026-03-25",
    "2026-03-26", "2026-03-27", "2026-03-30", "2026-03-31",
    "2026-04-01", "2026-04-02", "2026-04-03",
]
PPP = 1.0
WARMUP = 60
SESSION_START_H = 7
SESSION_END_H = 17
COOLDOWN = timedelta(minutes=60)
POST_TP1_MAX_RETRACE = 10.0
POST_TP1_BELOW_BUFFER = 5.0

BRIEFING_SCHED = [(0, 0, "Asian"), (6, 30, "London"), (10, 45, "Mid-session"), (13, 0, "NY")]

# NEWS config
NEWS_SPIKE_MIN_PIPS = 15.0
NEWS_STALL_CANDLES = 2        # 2 consecutive candles with no new extreme ≈ 10 ticks
NEWS_CONFIRM_PIPS = 5.0
NEWS_SL_PIPS = 20.0
NEWS_TP_PIPS = 40.0           # realistic TP for news moves (not 80)
NEWS_TIMEOUT_CANDLES = 12     # 1 hour of 5M candles

# News events during 10-day window (from news_windows.json + sweep journal event labels)
# Pre-DST (before Mar 29): BST = UTC (clocks haven't changed)
# Post-DST (Mar 29+): BST = UTC+1, subtract 1h
NEWS_EVENTS = [
    # (date, utc_h, utc_m, currency, affected_pairs, label)
    ("2026-03-25", 7, 0, "GBP", ["GBPUSD"], "CPI y/y"),
    ("2026-03-27", 13, 30, "USD", ["GBPUSD", "EURUSD", "USDJPY", "USDCAD"], "US Final GDP q/q"),
    ("2026-04-01", 12, 15, "USD", ["GBPUSD", "EURUSD", "USDJPY"], "ADP Non-Farm Employ"),
    ("2026-04-01", 14, 0, "USD", ["GBPUSD", "EURUSD", "USDJPY"], "ISM Manufacturing PMI"),
    ("2026-04-03", 12, 30, "USD", ["GBPUSD", "EURUSD", "USDJPY"], "Core PCE / Final GDP"),
]

# 3CO config
THREE_CO_SL_PIPS = 20.0
THREE_CO_SL_PIPS_JPY = 25.0
THREE_CO_TP1_PIPS = 25.0     # early momentum play → 25p TP1 then post-TP1

# Session open times (UTC) for 3CO
SESSION_OPENS = {
    "GBPUSD": [(7, 0)],
    "EURUSD": [(7, 0)],
    "USDJPY": [(7, 0)],
    "USDCAD": [(13, 30)],
}


# ── Monkey-patch ──────────────────────────────────────────────────
import briefing_liquidity as _bl_mod
_real_dt = datetime


class _SimDt(datetime):
    _now = None

    @classmethod
    def now(cls, tz=None):
        if cls._now is not None and tz is not None:
            return cls._now
        return _real_dt.now(tz)


_bl_mod.datetime = _SimDt


# ── Data types ───────────────────────────────────────────────────
@dataclass
class Candle:
    ts: datetime
    o: float
    h: float
    l: float
    c: float


@dataclass
class Trade:
    pair: str
    date: str
    strategy: str           # WINDOW_SWEEP, BRIEFING_LIQ, NEWS, 3CO
    signal_time: str
    fill_time: str
    direction: str
    entry: float
    sl_price: float
    tp1_price: float
    sl_pips: float
    tp1_pips: float
    source: str             # detailed source tag
    tp1_hit: bool = False
    post_tp1_peak: float = 0.0
    exit_time: Optional[str] = None
    exit_price: Optional[float] = None
    outcome: Optional[str] = None
    pnl_pips: Optional[float] = None


# ── Helpers ──────────────────────────────────────────────────────
def load_candles(pair: str, date: str) -> List[Candle]:
    # JSON cache first
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
                candles.append(Candle(ts=ts, o=float(r["open"]), h=float(r["high"]),
                                      l=float(r["low"]), c=float(r["close"])))
            return candles

    # CSV fallback
    csv_path = Path(f"/opt/tradingbot/data/candles/{pair}/{date}.csv")
    if csv_path.exists():
        df = pd.read_csv(csv_path, parse_dates=["timestamp"])
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
        candles = []
        for _, r in df.iterrows():
            ts = r["timestamp"]
            if hasattr(ts, "to_pydatetime"):
                ts = ts.to_pydatetime()
            candles.append(Candle(ts=ts, o=float(r["open"]), h=float(r["high"]),
                                  l=float(r["low"]), c=float(r["close"])))
        return candles

    return []


def verify_candles(candles: List[Candle]) -> bool:
    if len(candles) < 10:
        return False
    gaps = [(candles[i + 1].ts - candles[i].ts).total_seconds()
            for i in range(min(20, len(candles) - 1))]
    median_gap = sorted(gaps)[len(gaps) // 2]
    return abs(median_gap - 300) < 60


def get_briefing(pair: str, date: str, ts: datetime) -> Optional[Dict]:
    best = None
    for h, m, name in BRIEFING_SCHED:
        gt = datetime(ts.year, ts.month, ts.day, h, m, tzinfo=timezone.utc)
        if ts >= gt:
            best = name
    if not best:
        return None
    p = Path(f"/opt/tradingbot/logs/briefing_{pair}_{date}_{best}.json")
    if not p.exists():
        return None
    with open(p) as f:
        return json.load(f)


def build_df(candles: List[Candle], end_idx: int) -> pd.DataFrame:
    start = max(0, end_idx - WARMUP + 1)
    rows = [{"timestamp": c.ts, "open": c.o, "high": c.h, "low": c.l, "close": c.c}
            for c in candles[start:end_idx + 1]]
    return pd.DataFrame(rows)


def pip_pnl(direction: str, entry: float, price: float) -> float:
    return (price - entry) / PPP if direction == "BUY" else (entry - price) / PPP


# ── Trade management (shared) ───────────────────────────────────
def manage_trade(trade: Trade, candle: Candle, use_post_tp1: bool = True) -> Optional[str]:
    """Check candle against open trade. Returns outcome or None."""
    is_buy = trade.direction == "BUY"

    if not trade.tp1_hit:
        sl_hit = (candle.l <= trade.sl_price) if is_buy else (candle.h >= trade.sl_price)
        tp_hit = (candle.h >= trade.tp1_price) if is_buy else (candle.l <= trade.tp1_price)

        if sl_hit and tp_hit:
            trade.exit_price = trade.sl_price
            trade.pnl_pips = -trade.sl_pips
            return "SL"
        if sl_hit:
            trade.exit_price = trade.sl_price
            trade.pnl_pips = -trade.sl_pips
            return "SL"
        if tp_hit:
            if not use_post_tp1:
                trade.exit_price = trade.tp1_price
                trade.pnl_pips = trade.tp1_pips
                return "TP"
            trade.tp1_hit = True
            if is_buy:
                trade.post_tp1_peak = max((candle.h - trade.entry) / PPP, trade.tp1_pips)
            else:
                trade.post_tp1_peak = max((trade.entry - candle.l) / PPP, trade.tp1_pips)
            return None
    else:
        if is_buy:
            candle_best = (candle.h - trade.entry) / PPP
            candle_worst = (candle.l - trade.entry) / PPP
        else:
            candle_best = (trade.entry - candle.l) / PPP
            candle_worst = (trade.entry - candle.h) / PPP

        peak = max(trade.post_tp1_peak, candle_best)
        trade.post_tp1_peak = peak

        if candle_worst < trade.tp1_pips - POST_TP1_BELOW_BUFFER:
            trade.exit_price = trade.tp1_price
            trade.pnl_pips = trade.tp1_pips
            return "TP1"

        retrace = peak - candle_worst
        if retrace >= POST_TP1_MAX_RETRACE:
            exit_pips = max(peak - POST_TP1_MAX_RETRACE, trade.tp1_pips)
            trade.pnl_pips = exit_pips
            if is_buy:
                trade.exit_price = trade.entry + exit_pips * PPP
            else:
                trade.exit_price = trade.entry - exit_pips * PPP
            return "TP1+RET"

    return None


def close_trade_at(trade: Trade, candle: Candle, reason: str):
    """Close trade at candle close price."""
    p = pip_pnl(trade.direction, trade.entry, candle.c)
    if trade.tp1_hit:
        trade.pnl_pips = max(p, trade.tp1_pips)
        trade.outcome = f"TP1+{reason}"
    else:
        trade.pnl_pips = p
        trade.outcome = reason
    trade.exit_time = candle.ts.strftime("%H:%M")
    trade.exit_price = candle.c


# ══════════════════════════════════════════════════════════════════
#  PHASE 1: WINDOW_SWEEP + BRIEFING_LIQ (from backtest_clean logic)
# ══════════════════════════════════════════════════════════════════
def replay_sweep_briefing(pair: str, epic: str, date: str) -> List[Trade]:
    candles = load_candles(pair, date)
    if not candles or not verify_candles(candles):
        return []

    strat = BriefingLiquidityStrategy()
    completed: List[Trade] = []
    trade: Optional[Trade] = None
    pending = None
    last_signal_ts = None

    for i in range(WARMUP, len(candles)):
        c = candles[i]
        _SimDt._now = c.ts
        h = c.ts.hour

        # Fill pending signal
        if pending is not None:
            ps = pending
            pending = None
            d = ps["direction"]
            fill = c.o
            if d == "BUY":
                sl_p = fill - ps["sl_pips"] * PPP
                tp_p = fill + ps["tp1_pips"] * PPP
            else:
                sl_p = fill + ps["sl_pips"] * PPP
                tp_p = fill - ps["tp1_pips"] * PPP

            src = ps["source"]
            strat_name = "BRIEFING_LIQ" if "trigger" in src else "WINDOW_SWEEP"
            trade = Trade(
                pair=pair, date=date, strategy=strat_name,
                signal_time=ps["time"], fill_time=c.ts.strftime("%H:%M"),
                direction=d, entry=fill,
                sl_price=sl_p, tp1_price=tp_p,
                sl_pips=ps["sl_pips"], tp1_pips=ps["tp1_pips"],
                source=src,
            )

        # Manage open trade
        if trade is not None:
            if h >= SESSION_END_H:
                close_trade_at(trade, c, "17:00")
                completed.append(trade)
                trade = None
            else:
                result = manage_trade(trade, c)
                if result:
                    trade.exit_time = c.ts.strftime("%H:%M")
                    trade.outcome = result
                    completed.append(trade)
                    trade = None

        # Evaluate for new signal
        if h < SESSION_START_H or h >= SESSION_END_H:
            continue
        if trade is not None or pending is not None:
            continue
        if last_signal_ts and (c.ts - last_signal_ts) < COOLDOWN:
            continue

        briefing = get_briefing(pair, date, c.ts)
        if not briefing:
            continue

        df = build_df(candles, i)
        try:
            dec = strat.evaluate(pair, epic, df, PPP, c.c, briefing)
        except Exception:
            continue

        sig = str(dec.signal or "").upper()
        if sig not in ("BUY", "SELL"):
            continue

        last_signal_ts = c.ts
        pending = {
            "time": c.ts.strftime("%H:%M"), "direction": sig,
            "signal_entry": float(dec.entry or c.c),
            "sl_pips": float(dec.sl or 10), "tp1_pips": float(dec.tp or 15),
            "source": dec.debug.get("entry_source", "?"),
        }

    if trade is not None:
        lc = candles[-1]
        close_trade_at(trade, lc, "EOD")
        completed.append(trade)

    return completed


# ══════════════════════════════════════════════════════════════════
#  PHASE 2: NEWS — Stall-and-confirm simulation on 5M candles
# ══════════════════════════════════════════════════════════════════
def simulate_news_event(pair: str, date: str, event_h: int, event_m: int,
                        label: str) -> Tuple[Optional[Trade], Dict]:
    """Simulate stall-and-confirm news strategy on 5M candles.

    Returns (trade_or_None, detail_dict) for detailed event reporting.
    """
    detail = {"pair": pair, "spike": False, "stall": False, "entry": False,
              "max_up": 0, "max_dn": 0, "spike_dir": None, "spike_pips": 0,
              "spike_time": None, "stall_time": None, "stall_price": 0}

    candles = load_candles(pair, date)
    if not candles:
        detail["reason"] = "no data"
        return None, detail

    event_ts = datetime(int(date[:4]), int(date[5:7]), int(date[8:10]),
                        event_h, event_m, tzinfo=timezone.utc)

    # Find anchor candle (last close before event)
    anchor_idx = None
    for i, c in enumerate(candles):
        if c.ts >= event_ts:
            anchor_idx = i - 1
            break
    if anchor_idx is None or anchor_idx < 0:
        detail["reason"] = "no anchor"
        return None, detail

    anchor_price = candles[anchor_idx].c
    detail["anchor"] = anchor_price

    # State machine
    spike_detected = False
    spike_dir = None
    spike_extreme = None
    stall_detected = False
    stall_price = None
    stall_candles_count = 0

    start = anchor_idx + 1
    end = min(start + NEWS_TIMEOUT_CANDLES, len(candles))

    # Track max moves for reporting
    for c in candles[start:end]:
        detail["max_up"] = max(detail["max_up"], (c.h - anchor_price) / PPP)
        detail["max_dn"] = max(detail["max_dn"], (anchor_price - c.l) / PPP)

    for i in range(start, end):
        c = candles[i]

        if not spike_detected:
            up_move = (c.h - anchor_price) / PPP
            dn_move = (anchor_price - c.l) / PPP
            if up_move >= NEWS_SPIKE_MIN_PIPS:
                spike_detected = True
                spike_dir = "UP"
                spike_extreme = c.h
                detail["spike"] = True
                detail["spike_dir"] = "UP"
                detail["spike_pips"] = up_move
                detail["spike_time"] = c.ts.strftime("%H:%M")
            elif dn_move >= NEWS_SPIKE_MIN_PIPS:
                spike_detected = True
                spike_dir = "DOWN"
                spike_extreme = c.l
                detail["spike"] = True
                detail["spike_dir"] = "DOWN"
                detail["spike_pips"] = dn_move
                detail["spike_time"] = c.ts.strftime("%H:%M")
            else:
                continue
            # Don't skip — same candle could also start stall detection
            # but for 5M we move on
            continue

        if not stall_detected:
            new_extreme = False
            if spike_dir == "UP" and c.h > spike_extreme:
                spike_extreme = c.h
                new_extreme = True
                stall_candles_count = 0
                detail["spike_pips"] = (spike_extreme - anchor_price) / PPP
            elif spike_dir == "DOWN" and c.l < spike_extreme:
                spike_extreme = c.l
                new_extreme = True
                stall_candles_count = 0
                detail["spike_pips"] = (anchor_price - spike_extreme) / PPP

            if not new_extreme:
                stall_candles_count += 1

            if stall_candles_count >= NEWS_STALL_CANDLES:
                stall_detected = True
                stall_price = c.c
                detail["stall"] = True
                detail["stall_price"] = stall_price
                detail["stall_time"] = c.ts.strftime("%H:%M")
            continue

        # Confirmation
        move_from_stall = (c.c - stall_price) / PPP

        signal = None
        reason_tag = None
        if spike_dir == "UP":
            if move_from_stall >= NEWS_CONFIRM_PIPS:
                signal = "BUY"; reason_tag = "continuation"
            elif move_from_stall <= -NEWS_CONFIRM_PIPS:
                signal = "SELL"; reason_tag = "reversal"
        else:
            if move_from_stall <= -NEWS_CONFIRM_PIPS:
                signal = "SELL"; reason_tag = "continuation"
            elif move_from_stall >= NEWS_CONFIRM_PIPS:
                signal = "BUY"; reason_tag = "reversal"

        if signal is None:
            continue

        detail["entry"] = True
        detail["confirm_move"] = move_from_stall

        # Fill at next candle open
        if i + 1 >= len(candles):
            break
        fill_candle = candles[i + 1]
        fill_price = fill_candle.o

        if signal == "BUY":
            sl_p = fill_price - NEWS_SL_PIPS * PPP
            tp_p = fill_price + NEWS_TP_PIPS * PPP
        else:
            sl_p = fill_price + NEWS_SL_PIPS * PPP
            tp_p = fill_price - NEWS_TP_PIPS * PPP

        trade = Trade(
            pair=pair, date=date, strategy="NEWS",
            signal_time=c.ts.strftime("%H:%M"),
            fill_time=fill_candle.ts.strftime("%H:%M"),
            direction=signal, entry=fill_price,
            sl_price=sl_p, tp1_price=tp_p,
            sl_pips=NEWS_SL_PIPS, tp1_pips=NEWS_TP_PIPS,
            source=f"news_{reason_tag}",
        )

        for j in range(i + 1, len(candles)):
            mc = candles[j]
            if mc.ts.hour >= SESSION_END_H:
                close_trade_at(trade, mc, "17:00")
                return trade, detail
            result = manage_trade(trade, mc, use_post_tp1=True)
            if result:
                trade.exit_time = mc.ts.strftime("%H:%M")
                trade.outcome = result
                return trade, detail

        close_trade_at(trade, candles[-1], "EOD")
        return trade, detail

    if not spike_detected:
        detail["reason"] = f"no spike (max +{detail['max_up']:.1f}p / -{detail['max_dn']:.1f}p)"
    elif not stall_detected:
        detail["reason"] = f"spike {spike_dir} {detail['spike_pips']:.0f}p but no stall"
    else:
        detail["reason"] = f"stall but no confirm (stayed within ±{NEWS_CONFIRM_PIPS:.0f}p)"
    return None, detail


def run_news_strategy() -> List[Trade]:
    """Run NEWS strategy — detailed per-event breakdown."""
    trades = []
    print("\n  NEWS STRATEGY — Stall-and-confirm on 5M OHLC reconstruction")
    print(f"  Spike ≥{NEWS_SPIKE_MIN_PIPS:.0f}p → stall ({NEWS_STALL_CANDLES} candles no new extreme) → "
          f"confirm ±{NEWS_CONFIRM_PIPS:.0f}p")
    print(f"  SL={NEWS_SL_PIPS:.0f}p | TP={NEWS_TP_PIPS:.0f}p | post-TP1 continuation enabled")
    print(f"  NOTE: No raw tick data stored to disk. Using 5M candle OHLC as approximation.")
    print()

    for date, eh, em, ccy, pairs, label in NEWS_EVENTS:
        print(f"  ┌─ {date} {eh:02d}:{em:02d} UTC — {label} ({ccy})")
        any_traded = False

        for pair in pairs:
            t, d = simulate_news_event(pair, date, eh, em, label)

            if d.get("spike"):
                spike_str = f"spike {d['spike_dir']} {d['spike_pips']:.0f}p @ {d['spike_time']}"
            else:
                spike_str = f"no spike ({d.get('reason', '?')})"

            if t:
                any_traded = True
                stall_str = f"stall @ {d['stall_price']:.1f} ({d['stall_time']})"
                confirm_str = f"confirm {d['confirm_move']:+.1f}p → {t.source}"
                print(f"  │  {pair}: {spike_str} → {stall_str} → {confirm_str}")
                print(f"  │         {t.direction} fill {t.fill_time} @ {t.entry:.1f} "
                      f"→ {t.outcome} {t.pnl_pips:+.1f}p")
                trades.append(t)
            else:
                if d.get("spike") and d.get("stall"):
                    print(f"  │  {pair}: {spike_str} → stall @ {d['stall_price']:.1f} → {d.get('reason','?')}")
                elif d.get("spike"):
                    print(f"  │  {pair}: {spike_str} → {d.get('reason','?')}")
                else:
                    print(f"  │  {pair}: {d.get('reason', 'no data')}")

        if not any_traded:
            print(f"  │  → No valid entry for this event")
        print(f"  └{'─'*70}")
        print()

    return trades


# ══════════════════════════════════════════════════════════════════
#  PHASE 3: 3CO — Three Consecutive Opener
# ══════════════════════════════════════════════════════════════════
def run_3co_day(pair: str, date: str, open_h: int, open_m: int) -> Optional[Trade]:
    """Check for 3CO setup from session open."""
    candles = load_candles(pair, date)
    if not candles:
        return None

    open_ts = datetime(int(date[:4]), int(date[5:7]), int(date[8:10]),
                       open_h, open_m, tzinfo=timezone.utc)

    # Find candle at or after session open
    open_idx = None
    for i, c in enumerate(candles):
        if c.ts >= open_ts:
            open_idx = i
            break
    if open_idx is None:
        return None

    # Need at least 5 candles from open (3 pattern + trigger + 1 for fill)
    if open_idx + 5 >= len(candles):
        return None

    # First 3 candles
    c1 = candles[open_idx]
    c2 = candles[open_idx + 1]
    c3 = candles[open_idx + 2]

    # Body sizes (absolute pips)
    MIN_BODY_PIPS = 5.0
    b1 = (c1.c - c1.o) / PPP
    b2 = (c2.c - c2.o) / PPP
    b3 = (c3.c - c3.o) / PPP

    # All 3 bullish with minimum body size
    if b1 >= MIN_BODY_PIPS and b2 >= MIN_BODY_PIPS and b3 >= MIN_BODY_PIPS:
        direction = "BUY"
    elif b1 <= -MIN_BODY_PIPS and b2 <= -MIN_BODY_PIPS and b3 <= -MIN_BODY_PIPS:
        direction = "SELL"
    else:
        return None

    # Entry on candle 4 close, fill at candle 5 open
    trigger_candle = candles[open_idx + 3]
    fill_candle = candles[open_idx + 4]
    fill_price = fill_candle.o

    sl_pips = THREE_CO_SL_PIPS_JPY if pair == "USDJPY" else THREE_CO_SL_PIPS
    tp1_pips = THREE_CO_TP1_PIPS

    if direction == "BUY":
        sl_p = fill_price - sl_pips * PPP
        tp_p = fill_price + tp1_pips * PPP
    else:
        sl_p = fill_price + sl_pips * PPP
        tp_p = fill_price - tp1_pips * PPP

    trade = Trade(
        pair=pair, date=date, strategy="3CO",
        signal_time=trigger_candle.ts.strftime("%H:%M"),
        fill_time=fill_candle.ts.strftime("%H:%M"),
        direction=direction, entry=fill_price,
        sl_price=sl_p, tp1_price=tp_p,
        sl_pips=sl_pips, tp1_pips=tp1_pips,
        source="3co_momentum",
    )

    # Manage trade
    for j in range(open_idx + 4, len(candles)):
        mc = candles[j]
        if mc.ts.hour >= SESSION_END_H:
            close_trade_at(trade, mc, "17:00")
            return trade
        result = manage_trade(trade, mc, use_post_tp1=True)
        if result:
            trade.exit_time = mc.ts.strftime("%H:%M")
            trade.outcome = result
            return trade

    close_trade_at(trade, candles[-1], "EOD")
    return trade


def run_3co_strategy() -> List[Trade]:
    """Run 3CO strategy across all days/pairs."""
    trades = []
    setups_checked = 0
    print("\n  3CO STRATEGY — Three Consecutive Opener:")
    print(f"  3 same-direction candles from session open → entry on candle 4 | "
          f"SL={THREE_CO_SL_PIPS:.0f} TP1={THREE_CO_TP1_PIPS:.0f}")
    print()

    for date in DATES:
        for pair in PAIRS:
            opens = SESSION_OPENS.get(pair, [(7, 0)])
            for oh, om in opens:
                candles = load_candles(pair, date)
                if not candles:
                    continue
                setups_checked += 1
                t = run_3co_day(pair, date, oh, om)
                if t:
                    # Show the 3 candles
                    open_ts = datetime(int(date[:4]), int(date[5:7]), int(date[8:10]),
                                       oh, om, tzinfo=timezone.utc)
                    open_idx = next((i for i, c in enumerate(candles) if c.ts >= open_ts), None)
                    if open_idx is not None:
                        c1, c2, c3 = candles[open_idx], candles[open_idx+1], candles[open_idx+2]
                        body1 = (c1.c - c1.o) / PPP
                        body2 = (c2.c - c2.o) / PPP
                        body3 = (c3.c - c3.o) / PPP
                        print(f"  {date} {pair} {oh:02d}:{om:02d} | "
                              f"bodies: {body1:+.1f} {body2:+.1f} {body3:+.1f} | "
                              f"{t.direction} fill {t.fill_time} @ {t.entry:.1f} | "
                              f"{t.outcome} {t.pnl_pips:+.1f}p")
                    trades.append(t)

    print(f"\n  {setups_checked} session opens checked, {len(trades)} valid 3CO setups found")
    return trades


# ══════════════════════════════════════════════════════════════════
#  MAIN — Combine all four strategies
# ══════════════════════════════════════════════════════════════════
def main():
    print("=" * 100)
    print("  COMBINED 4-STRATEGY BACKTEST — 10-day dataset (2026-03-23 to 2026-04-03)")
    print("  Fill at next candle open | SL wins if ambiguous | Post-TP1 10p retrace | 17:00 close")
    print("=" * 100)

    # ── Phase 1: WINDOW_SWEEP + BRIEFING_LIQ ──
    print("\n  PHASE 1: WINDOW_SWEEP + BRIEFING_LIQ (from briefing_liquidity strategy)")
    print("  " + "-" * 70)
    sweep_liq_trades = []
    for pair, epic in PAIRS.items():
        for date in DATES:
            trades = replay_sweep_briefing(pair, epic, date)
            sweep_liq_trades.extend(trades)

    ws_trades = [t for t in sweep_liq_trades if t.strategy == "WINDOW_SWEEP"]
    bl_trades = [t for t in sweep_liq_trades if t.strategy == "BRIEFING_LIQ"]

    ws_pnl = sum(t.pnl_pips or 0 for t in ws_trades)
    bl_pnl = sum(t.pnl_pips or 0 for t in bl_trades)
    ws_wins = sum(1 for t in ws_trades if (t.pnl_pips or 0) > 0)
    bl_wins = sum(1 for t in bl_trades if (t.pnl_pips or 0) > 0)
    print(f"  WINDOW_SWEEP: {len(ws_trades)} trades, {ws_pnl:+.1f} pips, "
          f"WR {ws_wins/max(1,len(ws_trades))*100:.0f}%")
    print(f"  BRIEFING_LIQ: {len(bl_trades)} trades, {bl_pnl:+.1f} pips, "
          f"WR {bl_wins/max(1,len(bl_trades))*100:.0f}%")
    print(f"  Subtotal:     {len(sweep_liq_trades)} trades, {ws_pnl+bl_pnl:+.1f} pips")

    # ── Phase 2: NEWS ──
    print("\n  " + "=" * 70)
    print("  PHASE 2: NEWS STRATEGY")
    print("  " + "=" * 70)
    news_trades = run_news_strategy()

    # ── Phase 3: 3CO ──
    print("\n  " + "=" * 70)
    print("  PHASE 3: 3CO STRATEGY")
    print("  " + "=" * 70)
    three_co_trades = run_3co_strategy()

    # ══════════════════════════════════════════════════════════════
    #  COMBINED RESULTS TABLE
    # ══════════════════════════════════════════════════════════════
    all_trades = sweep_liq_trades + news_trades + three_co_trades

    strats = {
        "WINDOW_SWEEP": ws_trades,
        "BRIEFING_LIQ": bl_trades,
        "NEWS": news_trades,
        "3CO": three_co_trades,
    }

    print("\n")
    print("=" * 100)
    print("  COMBINED STRATEGY RESULTS")
    print("=" * 100)
    print()
    print("  ┌──────────────┬────────┬───────────┬──────┐")
    print("  │   Strategy   │ Trades │ Total Pip │  WR  │")
    print("  ├──────────────┼────────┼───────────┼──────┤")

    grand_trades = 0
    grand_pnl = 0.0
    grand_wins = 0

    for name, tlist in strats.items():
        n = len(tlist)
        pnl = sum(t.pnl_pips or 0 for t in tlist)
        w = sum(1 for t in tlist if (t.pnl_pips or 0) > 0)
        wr = w / n * 100 if n else 0
        print(f"  │ {name:<12} │ {n:>6} │ {pnl:>+9.1f} │ {wr:>3.0f}% │")
        grand_trades += n
        grand_pnl += pnl
        grand_wins += w

    gwr = grand_wins / grand_trades * 100 if grand_trades else 0
    print("  ├──────────────┼────────┼───────────┼──────┤")
    print(f"  │ {'COMBINED':<12} │ {grand_trades:>6} │ {grand_pnl:>+9.1f} │ {gwr:>3.0f}% │")
    print("  └──────────────┴────────┴───────────┴──────┘")

    # ── Per-pair breakdown ──
    print("\n  Per-pair breakdown:")
    print(f"  {'Pair':>8} {'WS':>8} {'BL':>8} {'NEWS':>8} {'3CO':>8} {'Total':>8}")
    print(f"  {'-'*52}")
    for pair in PAIRS:
        vals = {}
        for sn, tl in strats.items():
            vals[sn] = sum(t.pnl_pips or 0 for t in tl if t.pair == pair)
        total = sum(vals.values())
        print(f"  {pair:>8} {vals['WINDOW_SWEEP']:>+8.1f} {vals['BRIEFING_LIQ']:>+8.1f} "
              f"{vals['NEWS']:>+8.1f} {vals['3CO']:>+8.1f} {total:>+8.1f}")

    # ── Per-day with all four strategies ──
    print("\n  PIPS PER DAY — All four strategies active:")
    print(f"  {'Date':>12} {'WS':>8} {'BL':>8} {'NEWS':>8} {'3CO':>8} {'TOTAL':>8} {'#Trds':>6}  {'Note':>10}")
    print(f"  {'-'*74}")
    active_days = 0
    for date in DATES:
        day_trades = [t for t in all_trades if t.date == date]
        if not day_trades:
            continue
        active_days += 1

        vals = {}
        for sn, tl in strats.items():
            vals[sn] = sum(t.pnl_pips or 0 for t in tl if t.date == date)
        total = sum(vals.values())
        note = "🔥 100+" if total >= 100 else ""
        print(f"  {date:>12} {vals['WINDOW_SWEEP']:>+8.1f} {vals['BRIEFING_LIQ']:>+8.1f} "
              f"{vals['NEWS']:>+8.1f} {vals['3CO']:>+8.1f} {total:>+8.1f} {len(day_trades):>6}  {note}")

    daily_avg = grand_pnl / active_days if active_days > 0 else 0

    # ── Trade log (condensed) ──
    print(f"\n  FULL TRADE LOG:")
    print(f"  {'Date':>10} {'Time':>5} {'Pair':>7} {'Strat':>12} {'Dir':>4} {'Entry':>9} "
          f"{'SL':>4} {'TP':>4} {'Out':>8} {'P&L':>7}")
    print(f"  {'-'*80}")
    for t in sorted(all_trades, key=lambda x: (x.date, x.fill_time)):
        print(f"  {t.date:>10} {t.fill_time:>5} {t.pair:>7} {t.strategy:>12} {t.direction:>4} "
              f"{t.entry:>9.1f} {t.sl_pips:>4.0f} {t.tp1_pips:>4.0f} {t.outcome:>8} "
              f"{t.pnl_pips:>+7.1f}")

    # ── Grand total ──
    print(f"\n{'='*100}")
    print(f"  GRAND TOTAL")
    print(f"{'='*100}")
    print(f"  Trades:        {grand_trades}")
    print(f"  Win rate:      {gwr:.0f}% ({grand_wins}W / {grand_trades - grand_wins}L)")
    print(f"  Total P&L:     {grand_pnl:+.1f} pips")
    print(f"  Active days:   {active_days}")
    print(f"  Avg pips/day:  {daily_avg:+.1f}")
    print(f"  @ £1/pip:      £{grand_pnl:+.2f} total | £{daily_avg:+.2f}/day")
    print(f"  @ £10/pip:     £{grand_pnl * 10:+.2f} total | £{daily_avg * 10:+.2f}/day")
    print(f"{'='*100}")


if __name__ == "__main__":
    main()
