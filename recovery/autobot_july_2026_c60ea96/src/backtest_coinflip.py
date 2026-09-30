#!/usr/bin/env python3
"""
backtest_coinflip.py — Coin flip experiment on GBPUSD.

100 simulations × 7 days. Random BUY/SELL at 07:00, SL 15p, no TP,
hold to reversal (15p engulfing) or 17:00 session close.
"""

import json
import random
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
SL_PIPS = 15.0
REVERSAL_BODY_PIPS = 15.0
NUM_SIMS = 100


@dataclass
class Candle:
    ts: datetime
    o: float
    h: float
    l: float
    c: float


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


def find_candle(candles, hour, minute):
    for i, c in enumerate(candles):
        if c.ts.hour == hour and c.ts.minute == minute:
            return i
    return None


def simulate_day(candles: List[Candle], direction: str) -> Optional[float]:
    """Simulate one coin-flip trade. Returns pnl_pips or None if no entry."""
    i_entry = find_candle(candles, 7, 0)
    if i_entry is None:
        return None

    entry = candles[i_entry].o
    sl_price = entry - SL_PIPS * PPP if direction == "BUY" else entry + SL_PIPS * PPP

    for j in range(i_entry, len(candles)):
        c = candles[j]

        if c.ts.hour >= 17:
            return (c.c - entry) / PPP if direction == "BUY" else (entry - c.c) / PPP

        # SL check
        if direction == "BUY" and c.l <= sl_price:
            return -SL_PIPS
        if direction == "SELL" and c.h >= sl_price:
            return -SL_PIPS

        # Reversal candle: 15-pip body against direction
        body = abs(c.c - c.o) / PPP
        if body >= REVERSAL_BODY_PIPS:
            if direction == "BUY" and c.c < c.o:  # bearish candle against BUY
                return (c.c - entry) / PPP
            if direction == "SELL" and c.c > c.o:  # bullish candle against SELL
                return (entry - c.c) / PPP

    # End of data
    lc = candles[-1]
    return (lc.c - entry) / PPP if direction == "BUY" else (entry - lc.c) / PPP


def run_simulation(seed: int) -> dict:
    """Run one full simulation across all dates. Returns stats."""
    rng = random.Random(seed)
    day_results = []

    for date in DATES:
        candles = load_candles(date)
        if len(candles) < 50:
            continue
        direction = "BUY" if rng.random() < 0.5 else "SELL"
        pnl = simulate_day(candles, direction)
        if pnl is not None:
            day_results.append({"date": date, "dir": direction, "pnl": pnl})

    total = sum(d["pnl"] for d in day_results)
    wins = sum(1 for d in day_results if d["pnl"] > 0)
    days = len(day_results)
    return {
        "seed": seed,
        "total": total,
        "avg_daily": total / days if days > 0 else 0,
        "wins": wins,
        "losses": days - wins,
        "wr": wins / days * 100 if days > 0 else 0,
        "days": days,
        "results": day_results,
    }


def main():
    print("=" * 100)
    print("  COIN FLIP EXPERIMENT — GBPUSD 07:00 entry, SL 15p, 15p reversal exit, 17:00 close")
    print(f"  {NUM_SIMS} simulations × {len(DATES)} days | Random seed per simulation")
    print("=" * 100)
    print()

    # First: show what a SELL-every-day and BUY-every-day looks like
    print("  BASELINE — Fixed direction every day:")
    for fixed_dir in ["BUY", "SELL"]:
        day_pnls = []
        for date in DATES:
            candles = load_candles(date)
            if len(candles) < 50:
                continue
            pnl = simulate_day(candles, fixed_dir)
            if pnl is not None:
                day_pnls.append(pnl)
        total = sum(day_pnls)
        wins = sum(1 for p in day_pnls if p > 0)
        print(f"    Always {fixed_dir}: {total:+.1f} pips over {len(day_pnls)} days "
              f"({wins}W/{len(day_pnls) - wins}L) | avg {total / len(day_pnls):+.1f}/day")
    print()

    # Run 100 simulations
    sims = [run_simulation(seed) for seed in range(NUM_SIMS)]

    totals = [s["total"] for s in sims]
    dailies = [s["avg_daily"] for s in sims]
    wrs = [s["wr"] for s in sims]

    best = max(sims, key=lambda s: s["total"])
    worst = min(sims, key=lambda s: s["total"])
    median_idx = sorted(range(len(totals)), key=lambda i: totals[i])[NUM_SIMS // 2]
    median_sim = sims[median_idx]

    print(f"  {NUM_SIMS} SIMULATIONS — Distribution:")
    print(f"    Mean total P&L:   {np.mean(totals):+.1f} pips ({np.mean(dailies):+.1f}/day)")
    print(f"    Median total:     {np.median(totals):+.1f} pips ({np.median(dailies):+.1f}/day)")
    print(f"    Std dev:          {np.std(totals):.1f} pips")
    print(f"    Mean WR:          {np.mean(wrs):.0f}%")
    print()

    # Distribution buckets
    brackets = [(-200, -100), (-100, -50), (-50, 0), (0, 50), (50, 100), (100, 200)]
    print(f"    P&L distribution:")
    for lo, hi in brackets:
        count = sum(1 for t in totals if lo <= t < hi)
        bar = "█" * count
        print(f"      {lo:>+5} to {hi:>+4}: {count:>3} sims  {bar}")
    profitable = sum(1 for t in totals if t > 0)
    print(f"    Profitable sims:  {profitable}/{NUM_SIMS} ({profitable / NUM_SIMS * 100:.0f}%)")
    print()

    # Best simulation detail
    print(f"  BEST (seed={best['seed']}): {best['total']:+.1f} pips | {best['wr']:.0f}% WR")
    for d in best["results"]:
        print(f"    {d['date']} {d['dir']:>4} → {d['pnl']:+.1f} pips")
    print()

    # Worst simulation detail
    print(f"  WORST (seed={worst['seed']}): {worst['total']:+.1f} pips | {worst['wr']:.0f}% WR")
    for d in worst["results"]:
        print(f"    {d['date']} {d['dir']:>4} → {d['pnl']:+.1f} pips")
    print()

    # Median simulation detail
    print(f"  MEDIAN (seed={median_sim['seed']}): {median_sim['total']:+.1f} pips | {median_sim['wr']:.0f}% WR")
    for d in median_sim["results"]:
        print(f"    {d['date']} {d['dir']:>4} → {d['pnl']:+.1f} pips")
    print()

    # Per-day analysis: what's the expected value of a random trade each day?
    print(f"  PER-DAY EXPECTED VALUE (averaged across {NUM_SIMS} sims):")
    for date in DATES:
        day_pnls = []
        for s in sims:
            for d in s["results"]:
                if d["date"] == date:
                    day_pnls.append(d["pnl"])
        if day_pnls:
            candles = load_candles(date)
            full_range = 0
            if candles:
                session = [c for c in candles if 7 <= c.ts.hour < 17]
                if session:
                    full_range = (max(c.h for c in session) - min(c.l for c in session)) / PPP
            print(f"    {date}: avg {np.mean(day_pnls):+.1f} pips | "
                  f"range {full_range:.0f}p | "
                  f"SL rate {sum(1 for p in day_pnls if p == -SL_PIPS) / len(day_pnls) * 100:.0f}%")

    # Compare to actual system
    print()
    print("=" * 100)
    print("  COMPARISON")
    print("=" * 100)
    print(f"    Coin flip average:     {np.mean(dailies):+.1f} pips/day")
    print(f"    Coin flip median:      {np.median(dailies):+.1f} pips/day")
    print(f"    Actual system:         +31.0 pips/day (clean backtest)")
    print(f"    System edge over coin: {31.0 - np.mean(dailies):+.1f} pips/day")
    print("=" * 100)


if __name__ == "__main__":
    main()
