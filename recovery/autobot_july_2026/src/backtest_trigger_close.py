#!/usr/bin/env python3
"""
backtest_trigger_close.py — 7-day trigger_close replay for EURUSD and USDCAD.
Uses full briefing_liquidity strategy but ONLY counts trigger_close trades.
V1/V3 sweeps are filtered out of results (GBPUSD handles those separately).
"""

import json
import logging
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import pandas as pd

sys.path.insert(0, "/opt/tradingbot")
os.chdir("/opt/tradingbot")
from dotenv import load_dotenv
load_dotenv()

from briefing_liquidity import BriefingLiquidityStrategy

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
logger = logging.getLogger("TrigClose")
logger.setLevel(logging.INFO)

DATES = [
    "2026-03-23", "2026-03-24", "2026-03-25",
    "2026-03-26", "2026-03-27", "2026-03-30", "2026-03-31",
]

PAIRS = {
    "EURUSD": "CS.D.EURUSD.TODAY.IP",
    "USDCAD": "CS.D.USDCAD.TODAY.IP",
}

PPP = 1.0
SESSION_START = 7
SESSION_END = 17
WARMUP = 60
COOLDOWN_MINS = 60

POST_TP1_REVERSAL_BODY = 8.0
POST_TP1_MAX_RETRACE = 10.0
POST_TP1_BELOW_BUFFER = 5.0

BRIEFING_SESSIONS = [
    (0, 0, "Asian"), (6, 30, "London"),
    (10, 45, "Mid-session"), (13, 0, "NY"),
]


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
    trigger_source: str = ""
    post_tp1_active: bool = False
    post_tp1_peak: float = 0.0
    prev_close: float = 0.0
    exit_time: Optional[str] = None
    outcome: Optional[str] = None
    pnl_pips: Optional[float] = None
    closed: bool = False


def load_candles(pair, date):
    p = Path(f"/opt/tradingbot/cache/test_candles_{pair}_{date}.json")
    if not p.exists():
        return pd.DataFrame()
    with open(p) as f:
        data = json.load(f)
    if not data:
        return pd.DataFrame()
    df = pd.DataFrame(data)
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
    for c in ["open", "high", "low", "close"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df.dropna(subset=["open", "high", "low", "close"]).reset_index(drop=True)


def get_briefing(pair, date, ts):
    best = None
    for h, m, name in BRIEFING_SESSIONS:
        if ts >= datetime(ts.year, ts.month, ts.day, h, m, tzinfo=timezone.utc):
            best = name
    if not best:
        return None
    p = Path(f"/opt/tradingbot/logs/briefing_{pair}_{date}_{best}.json")
    return json.load(open(p)) if p.exists() else None


def pnl(direction, entry, price):
    return (price - entry) / PPP if direction == "BUY" else (entry - price) / PPP


def manage(t, co, ch, cl, cc):
    buy = t.direction == "BUY"
    if not t.post_tp1_active:
        if buy:
            if cl <= t.sl_price:
                t.pnl_pips = -t.sl_pips; return "SL"
            if cc >= t.tp1_price:
                t.post_tp1_active = True
                t.post_tp1_peak = max((ch - t.entry) / PPP, t.tp1_pips)
                t.prev_close = cc; return None
        else:
            if ch >= t.sl_price:
                t.pnl_pips = -t.sl_pips; return "SL"
            if cc <= t.tp1_price:
                t.post_tp1_active = True
                t.post_tp1_peak = max((t.entry - cl) / PPP, t.tp1_pips)
                t.prev_close = cc; return None
    else:
        if buy:
            p = (cc - t.entry) / PPP
            pk = max(t.post_tp1_peak, (ch - t.entry) / PPP)
        else:
            p = (t.entry - cc) / PPP
            pk = max(t.post_tp1_peak, (t.entry - cl) / PPP)
        t.post_tp1_peak = pk
        if p < t.tp1_pips - POST_TP1_BELOW_BUFFER:
            t.pnl_pips = t.tp1_pips; return "TP1"
        ret = pk - p
        if ret >= POST_TP1_MAX_RETRACE:
            t.pnl_pips = max(pk - POST_TP1_MAX_RETRACE, t.tp1_pips); return "TP1+RET"
        body = abs(cc - co) / PPP
        pm = (t.prev_close + co) / 2
        if body >= POST_TP1_REVERSAL_BODY:
            if buy and cc < co and cc < pm:
                t.pnl_pips = max(p, t.tp1_pips); return "TP1+REV"
            elif not buy and cc > co and cc > pm:
                t.pnl_pips = max(p, t.tp1_pips); return "TP1+REV"
        t.prev_close = cc
    return None


def day_range(df, s, e):
    m = (df["timestamp"].dt.hour >= s) & (df["timestamp"].dt.hour < e)
    d = df[m]
    return (d["high"].max() - d["low"].min()) / PPP if not d.empty else 0


import briefing_liquidity as _bl
_rdt = datetime
class _SD(datetime):
    _sn = None
    @classmethod
    def now(cls, tz=None):
        return cls._sn if cls._sn and tz else _rdt.now(tz)
_bl.datetime = _SD


def replay(pair, epic, date):
    df = load_candles(pair, date)
    if df.empty or len(df) < WARMUP + 10:
        return []
    strat = BriefingLiquidityStrategy()
    trades, ot, lst = [], None, None

    for i in range(WARMUP, len(df)):
        ts = df["timestamp"].iloc[i]
        if not isinstance(ts, datetime): ts = ts.to_pydatetime()
        if ts.tzinfo is None: ts = ts.replace(tzinfo=timezone.utc)
        _SD._sn = ts
        h = ts.hour
        co, ch, cl, cc = float(df["open"].iloc[i]), float(df["high"].iloc[i]), float(df["low"].iloc[i]), float(df["close"].iloc[i])

        if ot and not ot.closed:
            if h >= SESSION_END:
                p = pnl(ot.direction, ot.entry, cc)
                if ot.post_tp1_active:
                    ot.pnl_pips = max(p, ot.tp1_pips); ot.outcome = "TP1+17:00"
                else:
                    ot.pnl_pips = p; ot.outcome = "17:00"
                ot.exit_time = ts.strftime("%H:%M"); ot.closed = True
                trades.append(ot); ot = None
            else:
                r = manage(ot, co, ch, cl, cc)
                if r:
                    ot.exit_time = ts.strftime("%H:%M"); ot.outcome = r; ot.closed = True
                    trades.append(ot); ot = None

        if h < SESSION_START or h >= SESSION_END: continue
        if ot is not None: continue
        if lst and (ts - lst) < timedelta(minutes=COOLDOWN_MINS): continue

        br = get_briefing(pair, date, ts)
        if not br: continue

        sl = df.iloc[max(0, i - WARMUP + 1):i + 1].copy()
        try:
            dec = strat.evaluate(pair, epic, sl, PPP, cc, br)
        except: continue

        sig = str(dec.signal or "").upper()
        if sig not in ("BUY", "SELL"): continue

        src = dec.debug.get("entry_source", "")
        lst = ts

        # Accept trigger_close, OR/PB, and sweep entries (all contribute to cooldown)
        # but only record trigger_close trades
        entry = float(dec.entry or cc)
        sl_p = float(dec.sl or 10)
        tp_p = float(dec.tp or 15)
        bias = dec.debug.get("bias", "?")
        tsrc = dec.debug.get("trigger_source", "")

        if sig == "BUY":
            slpr = entry - sl_p * PPP; tppr = entry + tp_p * PPP
        else:
            slpr = entry + sl_p * PPP; tppr = entry - tp_p * PPP

        ot = Trade(pair=pair, date=date, time=ts.strftime("%H:%M"), direction=sig,
                   entry=entry, sl_pips=sl_p, tp1_pips=tp_p, sl_price=slpr,
                   tp1_price=tppr, entry_source=src, bias=bias, trigger_source=tsrc)

        # If not trigger_close, mark as closed immediately (consumes cooldown only)
        if src != "trigger_close":
            ot.closed = True
            ot.outcome = "SKIP"
            ot = None

    if ot and not ot.closed:
        lc = float(df["close"].iloc[-1])
        p = pnl(ot.direction, ot.entry, lc)
        if ot.post_tp1_active:
            ot.pnl_pips = max(p, ot.tp1_pips); ot.outcome = "TP1+EOD"
        else:
            ot.pnl_pips = p; ot.outcome = "EOD"
        ot.exit_time = "EOD"; ot.closed = True; trades.append(ot)

    return [t for t in trades if t.entry_source == "trigger_close"]


def main():
    print("=" * 120)
    print("  TRIGGER_CLOSE REPLAY — EURUSD + USDCAD (7 days)")
    print("  Bias gate ON | TP1-or-SL + post-TP1 continuation | Min SL: 8 pips")
    print("=" * 120)

    gbp_pnl, gbp_trades, gbp_wins, gbp_days = 167.3, 10, 7, 6

    all_results = {}

    for pair, epic in PAIRS.items():
        pt, dr = [], []
        for date in DATES:
            t = replay(pair, epic, date)
            df = load_candles(pair, date)
            am = day_range(df, 7, 12) if not df.empty else 0
            pm = day_range(df, 13, 18) if not df.empty else 0
            full = day_range(df, 7, 18) if not df.empty else 0
            dp = sum(x.pnl_pips or 0 for x in t)
            dr.append({"date": date, "trades": len(t), "pnl": dp, "am": am, "pm": pm, "full": full})
            pt.extend(t)
        all_results[pair] = {"trades": pt, "days": dr}

    for pair in PAIRS:
        res = all_results[pair]
        trades = res["trades"]
        days = res["days"]

        print(f"\n{'='*110}")
        print(f"  {pair} — trigger_close")
        print(f"{'='*110}")

        if trades:
            wins = [t for t in trades if (t.pnl_pips or 0) > 0]
            losses = [t for t in trades if (t.pnl_pips or 0) <= 0]
            total = sum(t.pnl_pips or 0 for t in trades)
            wr = len(wins) / len(trades) * 100
            active = len([d for d in days if d["trades"] > 0])
            avg_d = total / active if active > 0 else 0

            print(f"  Trades: {len(trades)} | Wins: {len(wins)} | Losses: {len(losses)} | WR: {wr:.0f}%")
            print(f"  Total P&L: {total:+.1f} pips | Avg daily: {avg_d:+.1f} pips")
            print()
            print(f"  {'Date':>12} {'Time':>6} {'Dir':>5} {'Entry':>10} {'SL':>6} {'TP1':>6} {'Bias':>6} {'Out':>8} {'P&L':>8}  {'Source'}")
            print(f"  {'-'*100}")
            for t in trades:
                pstr = f"{t.pnl_pips:+.1f}" if t.pnl_pips is not None else "?"
                print(f"  {t.date:>12} {t.time:>6} {t.direction:>5} {t.entry:>10.1f} "
                      f"{t.sl_pips:>6.1f} {t.tp1_pips:>6.1f} {t.bias:>6} {t.outcome or '?':>8} {pstr:>8}  {t.trigger_source}")
        else:
            print("  No trigger_close trades.")

        print()
        print(f"  {'Date':>12} {'#Tr':>4} {'P&L':>8} {'AM':>7} {'PM':>7} {'Full':>7}")
        print(f"  {'-'*55}")
        for d in days:
            if d["full"] > 0:
                print(f"  {d['date']:>12} {d['trades']:>4} {d['pnl']:>+8.1f} {d['am']:>7.0f} {d['pm']:>7.0f} {d['full']:>7.0f}")

    # Combined
    print(f"\n{'='*120}")
    print(f"  COMBINED: GBPUSD sweeps + EURUSD/USDCAD trigger_close")
    print(f"{'='*120}")
    print(f"\n  {'Pair':>8} {'Strategy':>14} {'Trades':>7} {'Wins':>5} {'WR':>5} {'Total':>9} {'Avg/day':>8}")
    print(f"  {'-'*65}")

    gp, gt, gw = 0, 0, 0

    print(f"  {'GBPUSD':>8} {'V1/V3 sweep':>14} {gbp_trades:>7} {gbp_wins:>5} {gbp_pnl/gbp_trades*100/gbp_pnl*gbp_wins:>4.0f}% {gbp_pnl:>+9.1f} {gbp_pnl/gbp_days:>+8.1f}")
    gp += gbp_pnl; gt += gbp_trades; gw += gbp_wins

    for pair in PAIRS:
        tr = all_results[pair]["trades"]
        total = sum(t.pnl_pips or 0 for t in tr)
        wins = sum(1 for t in tr if (t.pnl_pips or 0) > 0)
        wr = wins / len(tr) * 100 if tr else 0
        active = len([d for d in all_results[pair]["days"] if d["trades"] > 0])
        avg = total / active if active > 0 else 0
        print(f"  {pair:>8} {'trigger_close':>14} {len(tr):>7} {wins:>5} {wr:>4.0f}% {total:>+9.1f} {avg:>+8.1f}")
        gp += total; gt += len(tr); gw += wins

    print(f"  {'-'*65}")
    gwr = gw / gt * 100 if gt > 0 else 0
    gdaily = gp / 6
    print(f"  {'TOTAL':>8} {'':>14} {gt:>7} {gw:>5} {gwr:>4.0f}% {gp:>+9.1f} {gdaily:>+8.1f}")
    print()
    print(f"  Combined pips/day:  {gdaily:+.1f}")
    print(f"  Target:             100.0")
    print(f"  Gap:                {100 - gdaily:.1f}")
    print(f"  @ £1/pip:  £{gp:+.2f} total | £{gdaily:+.2f}/day")
    print(f"  @ £10/pip: £{gp*10:+.2f} total | £{gdaily*10:+.2f}/day")
    print(f"{'='*120}")


if __name__ == "__main__":
    main()
