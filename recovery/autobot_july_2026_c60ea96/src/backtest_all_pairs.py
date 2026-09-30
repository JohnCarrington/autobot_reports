#!/usr/bin/env python3
"""
backtest_all_pairs.py — 7-day replay for EURUSD, USDJPY, USDCAD.
Same optimised settings as GBPUSD: V1/V3 sweeps, post-TP1 continuation,
10-pip body filter, 60-min cooldown, TP1-or-SL, no trigger_close.
"""

import json
import logging
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Optional

import pandas as pd
import numpy as np

sys.path.insert(0, "/opt/tradingbot")
os.chdir("/opt/tradingbot")
from dotenv import load_dotenv
load_dotenv()

from briefing_liquidity import BriefingLiquidityStrategy

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
logger = logging.getLogger("AllPairs")
logger.setLevel(logging.INFO)

# ============================================================
# CONFIG
# ============================================================
DATES = [
    "2026-03-23", "2026-03-24", "2026-03-25",
    "2026-03-26", "2026-03-27", "2026-03-30", "2026-03-31",
]

PAIRS = {
    "EURUSD": "CS.D.EURUSD.TODAY.IP",
    "USDJPY": "CS.D.USDJPY.TODAY.IP",
    "USDCAD": "CS.D.USDCAD.TODAY.IP",
}

PPP = 1.0
SESSION_START_HOUR = 7
SESSION_END_HOUR = 17
WARMUP_CANDLES = 60
COOLDOWN_MINS = 60

POST_TP1_REVERSAL_BODY_PIPS = 8.0
POST_TP1_MAX_RETRACE_PIPS = 10.0
POST_TP1_BELOW_BUFFER_PIPS = 5.0

BRIEFING_SESSIONS = [
    (0, 0, "Asian"), (6, 30, "London"),
    (10, 45, "Mid-session"), (13, 0, "NY"),
]

# ============================================================
# DATA TYPES
# ============================================================
@dataclass
class Trade:
    pair: str
    date: str
    time: str
    direction: str
    entry: float
    sl_pips: float
    tp1_pips: float
    sl_price: float
    tp1_price: float
    entry_source: str
    bias: str
    # Post-TP1
    post_tp1_active: bool = False
    post_tp1_peak_pips: float = 0.0
    prev_candle_close: float = 0.0
    # Outcome
    exit_time: Optional[str] = None
    outcome: Optional[str] = None
    pnl_pips: Optional[float] = None
    closed: bool = False


# ============================================================
# HELPERS
# ============================================================
def load_candles(pair: str, date: str) -> pd.DataFrame:
    path = Path(f"/opt/tradingbot/cache/test_candles_{pair}_{date}.json")
    if not path.exists():
        return pd.DataFrame()
    with open(path) as f:
        data = json.load(f)
    if not data:
        return pd.DataFrame()
    df = pd.DataFrame(data)
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
    for c in ["open", "high", "low", "close"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df.dropna(subset=["open", "high", "low", "close"]).reset_index(drop=True)


def get_briefing(pair: str, date: str, ts: datetime) -> Optional[Dict]:
    best = None
    for h, m, name in BRIEFING_SESSIONS:
        gt = datetime(ts.year, ts.month, ts.day, h, m, tzinfo=timezone.utc)
        if ts >= gt:
            best = name
    if not best:
        return None
    path = Path(f"/opt/tradingbot/logs/briefing_{pair}_{date}_{best}.json")
    if not path.exists():
        return None
    with open(path) as f:
        return json.load(f)


def compute_pnl(direction, entry, current):
    return (current - entry) / PPP if direction == "BUY" else (entry - current) / PPP


def manage_trade(trade, candle_open, candle_high, candle_low, candle_close):
    is_buy = trade.direction == "BUY"

    if not trade.post_tp1_active:
        if is_buy:
            if candle_low <= trade.sl_price:
                trade.pnl_pips = -trade.sl_pips
                return "SL"
            if candle_close >= trade.tp1_price:
                trade.post_tp1_active = True
                trade.post_tp1_peak_pips = max((candle_high - trade.entry) / PPP, trade.tp1_pips)
                trade.prev_candle_close = candle_close
                return None
        else:
            if candle_high >= trade.sl_price:
                trade.pnl_pips = -trade.sl_pips
                return "SL"
            if candle_close <= trade.tp1_price:
                trade.post_tp1_active = True
                trade.post_tp1_peak_pips = max((trade.entry - candle_low) / PPP, trade.tp1_pips)
                trade.prev_candle_close = candle_close
                return None
    else:
        if is_buy:
            pnl = (candle_close - trade.entry) / PPP
            peak = max(trade.post_tp1_peak_pips, (candle_high - trade.entry) / PPP)
        else:
            pnl = (trade.entry - candle_close) / PPP
            peak = max(trade.post_tp1_peak_pips, (trade.entry - candle_low) / PPP)
        trade.post_tp1_peak_pips = peak

        if pnl < trade.tp1_pips - POST_TP1_BELOW_BUFFER_PIPS:
            trade.pnl_pips = trade.tp1_pips
            return "TP1"

        retrace = peak - pnl
        if retrace >= POST_TP1_MAX_RETRACE_PIPS:
            trade.pnl_pips = max(peak - POST_TP1_MAX_RETRACE_PIPS, trade.tp1_pips)
            return "TP1+RET"

        body = abs(candle_close - candle_open) / PPP
        prev_mid = (trade.prev_candle_close + candle_open) / 2
        if body >= POST_TP1_REVERSAL_BODY_PIPS:
            if is_buy and candle_close < candle_open and candle_close < prev_mid:
                trade.pnl_pips = max(pnl, trade.tp1_pips)
                return "TP1+REV"
            elif not is_buy and candle_close > candle_open and candle_close > prev_mid:
                trade.pnl_pips = max(pnl, trade.tp1_pips)
                return "TP1+REV"

        trade.prev_candle_close = candle_close
    return None


def day_range(df, start, end):
    mask = (df["timestamp"].dt.hour >= start) & (df["timestamp"].dt.hour < end)
    s = df[mask]
    if s.empty:
        return 0.0
    return (s["high"].max() - s["low"].min()) / PPP


# Monkey-patch
import briefing_liquidity as _bl_mod
_real_dt = datetime

class _SimDt(datetime):
    _sim_now = None
    @classmethod
    def now(cls, tz=None):
        if cls._sim_now is not None and tz is not None:
            return cls._sim_now
        return _real_dt.now(tz)

_bl_mod.datetime = _SimDt


# ============================================================
# REPLAY
# ============================================================
def replay_pair_day(pair, epic, date):
    df = load_candles(pair, date)
    if df.empty or len(df) < WARMUP_CANDLES + 10:
        return []

    strat = BriefingLiquidityStrategy()
    trades = []
    open_trade = None
    last_sig_time = None

    for i in range(WARMUP_CANDLES, len(df)):
        ts = df["timestamp"].iloc[i]
        if not isinstance(ts, datetime):
            ts = ts.to_pydatetime()
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        _SimDt._sim_now = ts

        h = ts.hour
        co = float(df["open"].iloc[i])
        ch = float(df["high"].iloc[i])
        cl = float(df["low"].iloc[i])
        cc = float(df["close"].iloc[i])

        if open_trade and not open_trade.closed:
            if h >= SESSION_END_HOUR:
                pnl = compute_pnl(open_trade.direction, open_trade.entry, cc)
                if open_trade.post_tp1_active:
                    open_trade.pnl_pips = max(pnl, open_trade.tp1_pips)
                    open_trade.outcome = "TP1+17:00"
                else:
                    open_trade.pnl_pips = pnl
                    open_trade.outcome = "17:00"
                open_trade.exit_time = ts.strftime("%H:%M")
                open_trade.closed = True
                trades.append(open_trade)
                open_trade = None
            else:
                result = manage_trade(open_trade, co, ch, cl, cc)
                if result:
                    open_trade.exit_time = ts.strftime("%H:%M")
                    open_trade.outcome = result
                    open_trade.closed = True
                    trades.append(open_trade)
                    open_trade = None

        if h < SESSION_START_HOUR or h >= SESSION_END_HOUR:
            continue
        if open_trade is not None:
            continue
        if last_sig_time and (ts - last_sig_time) < timedelta(minutes=COOLDOWN_MINS):
            continue

        briefing = get_briefing(pair, date, ts)
        if not briefing:
            continue

        df_slice = df.iloc[max(0, i - WARMUP_CANDLES + 1):i + 1].copy()
        try:
            dec = strat.evaluate(pair, epic, df_slice, PPP, cc, briefing)
        except Exception:
            continue

        sig = str(dec.signal or "").upper()
        if sig not in ("BUY", "SELL"):
            continue

        src = dec.debug.get("entry_source", "")
        # Only V1/V3 sweeps (no trigger_close)
        if src not in ("sweep_v1", "sweep_v3"):
            last_sig_time = ts
            open_trade = Trade(pair=pair, date=date, time="", direction=sig,
                               entry=0, sl_pips=0, tp1_pips=0, sl_price=0,
                               tp1_price=0, entry_source=src, bias="", closed=True)
            continue

        entry = float(dec.entry or cc)
        sl_pips = float(dec.sl or 10)
        tp_pips = float(dec.tp or 15)
        bias = dec.debug.get("bias", "?")

        if sig == "BUY":
            sl_price = entry - sl_pips * PPP
            tp_price = entry + tp_pips * PPP
        else:
            sl_price = entry + sl_pips * PPP
            tp_price = entry - tp_pips * PPP

        open_trade = Trade(
            pair=pair, date=date, time=ts.strftime("%H:%M"), direction=sig,
            entry=entry, sl_pips=sl_pips, tp1_pips=tp_pips,
            sl_price=sl_price, tp1_price=tp_price,
            entry_source=src, bias=bias,
        )
        last_sig_time = ts

    if open_trade and not open_trade.closed:
        lc = float(df["close"].iloc[-1])
        pnl = compute_pnl(open_trade.direction, open_trade.entry, lc)
        if open_trade.post_tp1_active:
            open_trade.pnl_pips = max(pnl, open_trade.tp1_pips)
            open_trade.outcome = "TP1+EOD"
        else:
            open_trade.pnl_pips = pnl
            open_trade.outcome = "EOD"
        open_trade.exit_time = "EOD"
        open_trade.closed = True
        trades.append(open_trade)

    return [t for t in trades if t.entry_source in ("sweep_v1", "sweep_v3")]


# ============================================================
# MAIN
# ============================================================
def main():
    print("=" * 120)
    print("  MULTI-PAIR V1/V3 SWEEP REPLAY — EURUSD, USDJPY, USDCAD (7 days)")
    print("  Same settings as GBPUSD: 10p body, 60m cooldown, TP1+post-TP1, no trigger_close")
    print("=" * 120)

    # GBPUSD baseline from previous replay
    gbp_total_pnl = 167.3
    gbp_trades = 10
    gbp_wr = 70
    gbp_days = 6

    all_pair_results = {}

    for pair, epic in PAIRS.items():
        pair_trades = []
        day_rows = []

        for date in DATES:
            trades = replay_pair_day(pair, epic, date)
            df = load_candles(pair, date)
            am = day_range(df, 7, 12) if not df.empty else 0
            pm = day_range(df, 13, 18) if not df.empty else 0
            full = day_range(df, 7, 18) if not df.empty else 0
            dpnl = sum(t.pnl_pips or 0 for t in trades)

            day_rows.append({
                "date": date, "trades": len(trades), "pnl": dpnl,
                "am": am, "pm": pm, "full": full,
            })
            pair_trades.extend(trades)

        all_pair_results[pair] = {"trades": pair_trades, "days": day_rows}

    # ================================================================
    # Per-pair output
    # ================================================================
    for pair in PAIRS:
        res = all_pair_results[pair]
        trades = res["trades"]
        days = res["days"]

        print(f"\n{'='*100}")
        print(f"  {pair}")
        print(f"{'='*100}")

        if trades:
            wins = [t for t in trades if (t.pnl_pips or 0) > 0]
            losses = [t for t in trades if (t.pnl_pips or 0) <= 0]
            total = sum(t.pnl_pips or 0 for t in trades)
            wr = len(wins) / len(trades) * 100
            active_days = len([d for d in days if d["trades"] > 0])
            avg_daily = total / active_days if active_days > 0 else 0
            avg_am = np.mean([d["am"] for d in days if d["full"] > 0])
            avg_pm = np.mean([d["pm"] for d in days if d["full"] > 0])

            print(f"  Trades: {len(trades)} | Wins: {len(wins)} | Losses: {len(losses)} | WR: {wr:.0f}%")
            print(f"  Total P&L: {total:+.1f} pips | Avg daily: {avg_daily:+.1f} pips")
            print(f"  Avg AM range: {avg_am:.0f} pips | Avg PM range: {avg_pm:.0f} pips")
            print()

            # Trade log
            print(f"  {'Date':>12} {'Time':>6} {'Src':>9} {'Dir':>5} {'Entry':>10} {'SL':>6} {'TP1':>6} {'Out':>8} {'P&L':>8}")
            print(f"  {'-'*90}")
            for t in trades:
                pnl = f"{t.pnl_pips:+.1f}" if t.pnl_pips is not None else "?"
                print(f"  {t.date:>12} {t.time:>6} {t.entry_source:>9} {t.direction:>5} {t.entry:>10.1f} "
                      f"{t.sl_pips:>6.1f} {t.tp1_pips:>6.1f} {t.outcome or '?':>8} {pnl:>8}")
        else:
            print("  No V1/V3 sweeps triggered.")

        # Day table
        print()
        print(f"  {'Date':>12} {'#Tr':>4} {'P&L':>8} {'AM Rng':>7} {'PM Rng':>7} {'Full':>7}")
        print(f"  {'-'*55}")
        for d in days:
            if d["full"] > 0:
                print(f"  {d['date']:>12} {d['trades']:>4} {d['pnl']:>+8.1f} {d['am']:>7.0f} {d['pm']:>7.0f} {d['full']:>7.0f}")

    # ================================================================
    # Combined 4-pair summary
    # ================================================================
    print(f"\n{'='*120}")
    print(f"  COMBINED 4-PAIR SUMMARY")
    print(f"{'='*120}")

    print(f"\n  {'Pair':>8} {'Trades':>7} {'Wins':>5} {'WR':>5} {'Total P&L':>10} {'Avg/day':>8} {'Avg AM':>7} {'Avg PM':>7}")
    print(f"  {'-'*70}")

    grand_pnl = 0
    grand_trades = 0
    grand_wins = 0

    # GBPUSD row (from known results)
    print(f"  {'GBPUSD':>8} {gbp_trades:>7} {7:>5} {gbp_wr:>4.0f}% {gbp_total_pnl:>+10.1f} {gbp_total_pnl/gbp_days:>+8.1f} {'69':>7} {'62':>7}")
    grand_pnl += gbp_total_pnl
    grand_trades += gbp_trades
    grand_wins += 7

    for pair in PAIRS:
        res = all_pair_results[pair]
        trades = res["trades"]
        days = res["days"]
        total = sum(t.pnl_pips or 0 for t in trades)
        wins = sum(1 for t in trades if (t.pnl_pips or 0) > 0)
        wr = wins / len(trades) * 100 if trades else 0
        active = len([d for d in days if d["trades"] > 0])
        avg_d = total / active if active > 0 else 0
        avg_am = np.mean([d["am"] for d in days if d["full"] > 0]) if days else 0
        avg_pm = np.mean([d["pm"] for d in days if d["full"] > 0]) if days else 0

        print(f"  {pair:>8} {len(trades):>7} {wins:>5} {wr:>4.0f}% {total:>+10.1f} {avg_d:>+8.1f} {avg_am:>7.0f} {avg_pm:>7.0f}")
        grand_pnl += total
        grand_trades += len(trades)
        grand_wins += wins

    print(f"  {'-'*70}")
    grand_wr = grand_wins / grand_trades * 100 if grand_trades > 0 else 0
    # Use 6 active days (Mar 31 has no data for most pairs)
    grand_daily = grand_pnl / 6
    print(f"  {'TOTAL':>8} {grand_trades:>7} {grand_wins:>5} {grand_wr:>4.0f}% {grand_pnl:>+10.1f} {grand_daily:>+8.1f}")
    print()
    print(f"  Combined avg pips/day:  {grand_daily:+.1f}")
    print(f"  Target:                 100.0")
    print(f"  Gap:                    {100.0 - grand_daily:.1f} pips/day")
    print()
    print(f"  @ £1/pip:  £{grand_pnl:+.2f} total | £{grand_daily:+.2f}/day")
    print(f"  @ £10/pip: £{grand_pnl * 10:+.2f} total | £{grand_daily * 10:+.2f}/day")
    print(f"{'='*120}")


if __name__ == "__main__":
    main()
