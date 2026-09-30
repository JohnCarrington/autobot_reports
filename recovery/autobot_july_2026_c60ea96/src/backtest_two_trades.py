#!/usr/bin/env python3
"""
backtest_two_trades.py — Two-trade-per-day strategy on GBPUSD.

Trade 1 (Runner): 07:00-07:10 opening assessment → enter 07:15 open
Trade 2 (Afternoon): 12:00-15:00 engulfing/hammer at session extreme
Real OHLC 5M candles from cache. No strategy imports — pure price action.
"""

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Optional

import pandas as pd
import numpy as np

DATES = [
    "2026-03-23", "2026-03-24", "2026-03-25",
    "2026-03-26", "2026-03-27", "2026-03-30", "2026-03-31",
]
PPP = 1.0
REVERSAL_BODY_PIPS = 15.0
AFTERNOON_TP_PIPS = 60.0
SL_BUFFER_PIPS = 5.0


@dataclass
class Candle:
    ts: datetime
    o: float
    h: float
    l: float
    c: float

    @property
    def body(self) -> float:
        return abs(self.c - self.o)

    @property
    def bullish(self) -> bool:
        return self.c > self.o

    @property
    def bearish(self) -> bool:
        return self.c < self.o


@dataclass
class Trade:
    date: str
    trade_type: str       # "RUNNER" or "AFTERNOON"
    signal_time: str
    fill_time: str
    direction: str
    entry: float
    sl_price: float
    sl_pips: float
    tp_price: Optional[float]  # None for runner (no fixed TP)
    tp_pips: Optional[float]
    exit_time: Optional[str] = None
    exit_price: Optional[float] = None
    outcome: Optional[str] = None
    pnl_pips: Optional[float] = None
    best_pnl: float = 0.0


def load_candles(date: str) -> List[Candle]:
    p = Path(f"/opt/tradingbot/cache/test_candles_GBPUSD_{date}.json")
    if not p.exists():
        return []
    with open(p) as f:
        raw = json.load(f)
    if not raw:
        return []
    out = []
    for r in raw:
        ts = pd.to_datetime(r["timestamp"], utc=True)
        if hasattr(ts, "to_pydatetime"):
            ts = ts.to_pydatetime()
        out.append(Candle(ts=ts, o=float(r["open"]), h=float(r["high"]),
                          l=float(r["low"]), c=float(r["close"])))
    return out


def candle_at(candles: List[Candle], hour: int, minute: int) -> Optional[int]:
    """Find index of candle at exact hour:minute."""
    for i, c in enumerate(candles):
        if c.ts.hour == hour and c.ts.minute == minute:
            return i
    return None


def pnl(direction: str, entry: float, price: float) -> float:
    return (price - entry) / PPP if direction == "BUY" else (entry - price) / PPP


def day_range(candles: List[Candle], start_h: int, end_h: int) -> float:
    session = [c for c in candles if start_h <= c.ts.hour < end_h]
    if not session:
        return 0
    return (max(c.h for c in session) - min(c.l for c in session)) / PPP


def replay_day(date: str) -> List[Trade]:
    candles = load_candles(date)
    if len(candles) < 50:
        return []

    trades: List[Trade] = []
    runner_done = False

    # ══════════════════════════════════════════════════════════
    # TRADE 1: MORNING RUNNER (07:00-07:10 assessment → 07:15 entry)
    # ══════════════════════════════════════════════════════════
    i0 = candle_at(candles, 7, 0)
    i1 = candle_at(candles, 7, 5)
    i2 = candle_at(candles, 7, 10)
    i_fill = candle_at(candles, 7, 15)

    if i0 is not None and i1 is not None and i2 is not None and i_fill is not None:
        c0, c1, c2 = candles[i0], candles[i1], candles[i2]
        fill_candle = candles[i_fill]

        all_bearish = c0.bearish and c1.bearish and c2.bearish
        all_bullish = c0.bullish and c1.bullish and c2.bullish

        if all_bearish or all_bullish:
            direction = "SELL" if all_bearish else "BUY"
            entry = fill_candle.o

            # SL: extreme of the 3 opening candles + 5 pips buffer
            if direction == "SELL":
                extreme = max(c0.h, c1.h, c2.h)
                sl_price = extreme + SL_BUFFER_PIPS * PPP
            else:
                extreme = min(c0.l, c1.l, c2.l)
                sl_price = extreme - SL_BUFFER_PIPS * PPP

            sl_pips = abs(entry - sl_price) / PPP

            runner = Trade(
                date=date, trade_type="RUNNER",
                signal_time="07:10", fill_time="07:15",
                direction=direction, entry=entry,
                sl_price=sl_price, sl_pips=sl_pips,
                tp_price=None, tp_pips=None,
            )

            # Run candle by candle from fill to 17:00
            for j in range(i_fill, len(candles)):
                c = candles[j]

                if c.ts.hour >= 17:
                    # Session close
                    runner.exit_time = c.ts.strftime("%H:%M")
                    runner.exit_price = c.c
                    runner.pnl_pips = pnl(direction, entry, c.c)
                    runner.outcome = "17:00"
                    break

                # Track best P&L
                if direction == "BUY":
                    cur_best = (c.h - entry) / PPP
                else:
                    cur_best = (entry - c.l) / PPP
                runner.best_pnl = max(runner.best_pnl, cur_best)

                # Check SL
                if direction == "BUY" and c.l <= sl_price:
                    runner.exit_time = c.ts.strftime("%H:%M")
                    runner.exit_price = sl_price
                    runner.pnl_pips = -sl_pips
                    runner.outcome = "SL"
                    break
                if direction == "SELL" and c.h >= sl_price:
                    runner.exit_time = c.ts.strftime("%H:%M")
                    runner.exit_price = sl_price
                    runner.pnl_pips = -sl_pips
                    runner.outcome = "SL"
                    break

                # Check reversal: engulfing candle body >= 15 pips against direction
                body_pips = c.body / PPP
                if body_pips >= REVERSAL_BODY_PIPS:
                    if direction == "SELL" and c.bullish:
                        runner.exit_time = c.ts.strftime("%H:%M")
                        runner.exit_price = c.c
                        runner.pnl_pips = pnl(direction, entry, c.c)
                        runner.outcome = f"REV({body_pips:.0f}p)"
                        break
                    if direction == "BUY" and c.bearish:
                        runner.exit_time = c.ts.strftime("%H:%M")
                        runner.exit_price = c.c
                        runner.pnl_pips = pnl(direction, entry, c.c)
                        runner.outcome = f"REV({body_pips:.0f}p)"
                        break
            else:
                # Ran out of candles
                lc = candles[-1]
                runner.exit_time = "EOD"
                runner.exit_price = lc.c
                runner.pnl_pips = pnl(direction, entry, lc.c)
                runner.outcome = "EOD"

            trades.append(runner)
            runner_done = True
            # Check if runner is still open at noon (for afternoon trade eligibility)
            if runner.exit_time and runner.exit_time not in ("EOD",):
                exit_h = int(runner.exit_time.split(":")[0])
                if exit_h >= 12:
                    runner_done = True  # runner ran into afternoon — no afternoon trade
                else:
                    runner_done = False  # runner closed early — afternoon eligible

    # ══════════════════════════════════════════════════════════
    # TRADE 2: AFTERNOON (12:00-15:00 engulfing/hammer at new extreme)
    # ══════════════════════════════════════════════════════════
    # Only if no runner is open, or runner closed before noon
    if not runner_done or (trades and trades[-1].outcome != "17:00"):
        # Find session high/low up to noon
        morning = [c for c in candles if 7 <= c.ts.hour < 12]
        if morning:
            session_high = max(c.h for c in morning)
            session_low = min(c.l for c in morning)

            afternoon_candles = [(i, c) for i, c in enumerate(candles)
                                 if 12 <= c.ts.hour < 15]

            for idx, (ci, c) in enumerate(afternoon_candles):
                if ci < 1:
                    continue
                prev = candles[ci - 1]

                body_pips = c.body / PPP
                if body_pips < 5:  # minimum body for pattern
                    continue

                direction = None
                pattern = None

                # Bearish engulfing at new high → SELL
                if c.h >= session_high and c.bearish and c.c < prev.l:
                    direction = "SELL"
                    pattern = "engulf@high"
                    session_high = c.h  # update extreme

                # Bullish engulfing at new low → BUY
                elif c.l <= session_low and c.bullish and c.c > prev.h:
                    direction = "BUY"
                    pattern = "engulf@low"
                    session_low = c.l

                # Hammer at new low → BUY (lower wick >= 2x body, close in upper half)
                elif c.l <= session_low and c.bullish:
                    lower_wick = min(c.o, c.c) - c.l
                    if lower_wick >= 2 * c.body and c.body >= 3 * PPP:
                        direction = "BUY"
                        pattern = "hammer@low"
                        session_low = c.l

                # Shooting star at new high → SELL
                elif c.h >= session_high and c.bearish:
                    upper_wick = c.h - max(c.o, c.c)
                    if upper_wick >= 2 * c.body and c.body >= 3 * PPP:
                        direction = "SELL"
                        pattern = "star@high"
                        session_high = c.h

                if direction is None:
                    continue

                # Check there's a next candle for fill
                if ci + 1 >= len(candles):
                    continue
                fill_c = candles[ci + 1]
                if fill_c.ts.hour >= 17:
                    continue

                fill_price = fill_c.o
                if direction == "SELL":
                    sl_price = c.h + SL_BUFFER_PIPS * PPP
                    tp_price = fill_price - AFTERNOON_TP_PIPS * PPP
                else:
                    sl_price = c.l - SL_BUFFER_PIPS * PPP
                    tp_price = fill_price + AFTERNOON_TP_PIPS * PPP

                sl_pips = abs(fill_price - sl_price) / PPP

                pm_trade = Trade(
                    date=date, trade_type="AFTERNOON",
                    signal_time=c.ts.strftime("%H:%M"),
                    fill_time=fill_c.ts.strftime("%H:%M"),
                    direction=direction, entry=fill_price,
                    sl_price=sl_price, sl_pips=sl_pips,
                    tp_price=tp_price, tp_pips=AFTERNOON_TP_PIPS,
                )

                # Run from fill to 17:00
                for j in range(ci + 1, len(candles)):
                    cc = candles[j]
                    if cc.ts.hour >= 17:
                        pm_trade.exit_time = cc.ts.strftime("%H:%M")
                        pm_trade.exit_price = cc.c
                        pm_trade.pnl_pips = pnl(direction, fill_price, cc.c)
                        pm_trade.outcome = "17:00"
                        break

                    if direction == "BUY":
                        cur = (cc.h - fill_price) / PPP
                    else:
                        cur = (fill_price - cc.l) / PPP
                    pm_trade.best_pnl = max(pm_trade.best_pnl, cur)

                    # SL
                    if direction == "BUY" and cc.l <= sl_price:
                        pm_trade.exit_time = cc.ts.strftime("%H:%M")
                        pm_trade.exit_price = sl_price
                        pm_trade.pnl_pips = -sl_pips
                        pm_trade.outcome = "SL"
                        break
                    if direction == "SELL" and cc.h >= sl_price:
                        pm_trade.exit_time = cc.ts.strftime("%H:%M")
                        pm_trade.exit_price = sl_price
                        pm_trade.pnl_pips = -sl_pips
                        pm_trade.outcome = "SL"
                        break

                    # TP
                    if direction == "BUY" and cc.h >= tp_price:
                        pm_trade.exit_time = cc.ts.strftime("%H:%M")
                        pm_trade.exit_price = tp_price
                        pm_trade.pnl_pips = AFTERNOON_TP_PIPS
                        pm_trade.outcome = "TP"
                        break
                    if direction == "SELL" and cc.l <= tp_price:
                        pm_trade.exit_time = cc.ts.strftime("%H:%M")
                        pm_trade.exit_price = tp_price
                        pm_trade.pnl_pips = AFTERNOON_TP_PIPS
                        pm_trade.outcome = "TP"
                        break
                else:
                    lc = candles[-1]
                    pm_trade.exit_time = "EOD"
                    pm_trade.exit_price = lc.c
                    pm_trade.pnl_pips = pnl(direction, fill_price, lc.c)
                    pm_trade.outcome = "EOD"

                trades.append(pm_trade)
                break  # only one afternoon trade

    return trades


def main():
    print("=" * 110)
    print("  TWO-TRADE STRATEGY — GBPUSD 5M OHLC")
    print("  Runner: 07:00-07:10 assessment → 07:15 fill | No fixed TP | 15p reversal exit")
    print("  Afternoon: 12:00-15:00 engulfing/hammer at extreme | TP 60p | SL pattern+5p")
    print("=" * 110)
    print()

    all_trades: List[Trade] = []
    total_available = 0

    for date in DATES:
        candles = load_candles(date)
        if len(candles) < 50:
            continue

        trades = replay_day(date)
        am_range = day_range(candles, 7, 12)
        pm_range = day_range(candles, 12, 17)
        full_range = day_range(candles, 7, 17)
        total_available += full_range

        day_pnl = sum(t.pnl_pips or 0 for t in trades)

        # Opening candles
        i0 = candle_at(candles, 7, 0)
        i1 = candle_at(candles, 7, 5)
        i2 = candle_at(candles, 7, 10)
        opening = ""
        if i0 is not None and i1 is not None and i2 is not None:
            c0, c1, c2 = candles[i0], candles[i1], candles[i2]
            dirs = ["▼" if c.bearish else "▲" if c.bullish else "—" for c in [c0, c1, c2]]
            opening = f"Opening: {dirs[0]}{dirs[1]}{dirs[2]}"
            if all(c.bearish for c in [c0, c1, c2]):
                opening += " → BEARISH runner"
            elif all(c.bullish for c in [c0, c1, c2]):
                opening += " → BULLISH runner"
            else:
                opening += " → Mixed (no runner)"

        capture = (day_pnl / full_range * 100) if full_range > 0 else 0

        print(f"  {date}  |  {opening}")
        print(f"  Range: AM={am_range:.0f}p  PM={pm_range:.0f}p  Full={full_range:.0f}p  "
              f"| Captured: {day_pnl:+.1f}p ({capture:.0f}%)")

        for t in trades:
            tp_str = f"TP {t.tp_price:.1f} ({t.tp_pips:.0f}p)" if t.tp_price else "no TP (runner)"
            print(f"    [{t.trade_type:>9}] {t.signal_time}→{t.fill_time} {t.direction} @ {t.entry:.1f} | "
                  f"SL {t.sl_price:.1f} ({t.sl_pips:.0f}p) | {tp_str}")
            print(f"               → {t.outcome} @ {t.exit_time} | {t.pnl_pips:+.1f} pips "
                  f"(best: +{t.best_pnl:.1f}p)")
        if not trades:
            print(f"    No trades")
        print()

        all_trades.extend(trades)

    # ── Summary ──
    runners = [t for t in all_trades if t.trade_type == "RUNNER"]
    afternoons = [t for t in all_trades if t.trade_type == "AFTERNOON"]
    total_pnl = sum(t.pnl_pips or 0 for t in all_trades)
    active_days = len(set(t.date for t in all_trades)) if all_trades else 1

    print("=" * 110)
    print("  SUMMARY")
    print("=" * 110)

    for label, group in [("RUNNER", runners), ("AFTERNOON", afternoons), ("COMBINED", all_trades)]:
        if not group:
            print(f"  {label:>12}: 0 trades")
            continue
        wins = sum(1 for t in group if (t.pnl_pips or 0) > 0)
        losses = len(group) - wins
        wr = wins / len(group) * 100
        tot = sum(t.pnl_pips or 0 for t in group)
        avg_w = np.mean([t.pnl_pips for t in group if (t.pnl_pips or 0) > 0]) if wins else 0
        avg_l = np.mean([t.pnl_pips for t in group if (t.pnl_pips or 0) <= 0]) if losses else 0
        avg_best = np.mean([t.best_pnl for t in group])
        print(f"  {label:>12}: {len(group)} trades | {wins}W/{losses}L ({wr:.0f}%) | "
              f"{tot:+.1f} pips | avg win: {avg_w:+.1f} | avg loss: {avg_l:+.1f} | "
              f"avg best run: +{avg_best:.1f}")

    print()
    daily_avg = total_pnl / active_days if active_days > 0 else 0
    avg_available = total_available / len([d for d in DATES if load_candles(d)])
    print(f"  Avg pips/day:      {daily_avg:+.1f} (target: 100)")
    print(f"  Avg available/day: {avg_available:.0f} pips")
    print(f"  Capture rate:      {total_pnl / total_available * 100:.0f}%" if total_available > 0 else "")
    print(f"  @ £10/pip:         £{daily_avg * 10:+.2f}/day | £{total_pnl * 10:+.2f} total")
    print("=" * 110)


if __name__ == "__main__":
    main()
