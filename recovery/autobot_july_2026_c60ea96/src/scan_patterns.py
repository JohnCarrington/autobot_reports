#!/usr/bin/env python3
"""
scan_patterns.py — Count all valid V1/V3 BB patterns on GBPUSD,
regardless of whether they fired as trades.

Scans raw 5M candle data for:
  V1: Classic BB pierce (N-2) → rejection (N-1) → confirm (N)
  V3: Engulfing at BB proximity (within 15 pips) with body >= 60% of range

Also checks the 10-pip body filter (London) and logs which were
blocked by 60-min cooldown.
"""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Dict

import pandas as pd

DATES = [
    "2026-03-23",
    "2026-03-24",
    "2026-03-25",
    "2026-03-26",
    "2026-03-27",
    "2026-03-30",
    "2026-03-31",
]
PPP = 1.0
WARMUP = 22  # need 20 for BB + 2-3 candle lookback
COOLDOWN_MINS = 60
BB_PROX_PIPS = 15
MIN_BODY_PIPS = 10
SESSION_START = 7
SESSION_END = 17


def load_candles(date: str) -> pd.DataFrame:
    path = Path(f"/opt/tradingbot/cache/test_candles_GBPUSD_{date}.json")
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


def scan_day(date: str) -> List[Dict]:
    df = load_candles(date)
    if df.empty or len(df) < WARMUP + 3:
        return []

    closes = df["close"].astype(float)
    highs = df["high"].astype(float)
    lows = df["low"].astype(float)
    opens = df["open"].astype(float)

    sma = closes.rolling(20).mean()
    std = closes.rolling(20).std()
    upper = sma + 2 * std
    lower = sma - 2 * std

    patterns = []

    for i in range(WARMUP + 2, len(df)):
        ts = df["timestamp"].iloc[i]
        if not hasattr(ts, "hour"):
            ts = ts.to_pydatetime()
        h = ts.hour
        if h < SESSION_START or h >= SESSION_END:
            continue

        n = df.iloc[i]
        n_close, n_high, n_low, n_open = float(n["close"]), float(n["high"]), float(n["low"]), float(n["open"])
        n1 = df.iloc[i - 1]
        n1_close, n1_high, n1_low, n1_open = float(n1["close"]), float(n1["high"]), float(n1["low"]), float(n1["open"])

        upper_n1 = float(upper.iloc[i - 1])
        lower_n1 = float(lower.iloc[i - 1])

        n1_body = abs(n1_close - n1_open)
        n1_range = n1_high - n1_low
        n1_body_ratio = n1_body / n1_range if n1_range > 0 else 0
        n1_body_pips = n1_body / PPP

        # ===================== V1: Classic BB pierce =====================
        if i >= WARMUP + 3:
            n2 = df.iloc[i - 2]
            n2_close = float(n2["close"])
            upper_n2 = float(upper.iloc[i - 2])
            lower_n2 = float(lower.iloc[i - 2])

            # Upper pierce → SELL
            if n2_close > upper_n2 and n1_close <= upper_n1 and n_close < n1_low:
                patterns.append({
                    "date": date,
                    "time": ts.strftime("%H:%M"),
                    "hour": h,
                    "variant": "V1",
                    "direction": "SELL",
                    "detail": f"pierce={n2_close:.1f}>upper={upper_n2:.1f}, reject={n1_close:.1f}, confirm={n_close:.1f}<{n1_low:.1f}",
                    "n1_body_pips": n1_body_pips,
                    "entry": n_close,
                })

            # Lower pierce → BUY
            if n2_close < lower_n2 and n1_close >= lower_n1 and n_close > n1_high:
                patterns.append({
                    "date": date,
                    "time": ts.strftime("%H:%M"),
                    "hour": h,
                    "variant": "V1",
                    "direction": "BUY",
                    "detail": f"pierce={n2_close:.1f}<lower={lower_n2:.1f}, reject={n1_close:.1f}, confirm={n_close:.1f}>{n1_high:.1f}",
                    "n1_body_pips": n1_body_pips,
                    "entry": n_close,
                })

        # ===================== V3: Engulfing at BB proximity =====================
        if i >= WARMUP + 3:
            n2 = df.iloc[i - 2]
            n2_close, n2_high, n2_low = float(n2["close"]), float(n2["high"]), float(n2["low"])
            bb_prox = BB_PROX_PIPS * PPP

            # Near upper BB, bearish engulfing → SELL
            dist_upper = upper_n1 - n1_high
            if 0 <= dist_upper <= bb_prox:
                if n1_close < n1_open and n1_close < n2_low and n1_body_ratio >= 0.60:
                    if n_close < n1_low:
                        patterns.append({
                            "date": date,
                            "time": ts.strftime("%H:%M"),
                            "hour": h,
                            "variant": "V3",
                            "direction": "SELL",
                            "detail": f"engulf@upper prox={dist_upper/PPP:.1f}p body={n1_body_ratio*100:.0f}% confirm={n_close:.1f}<{n1_low:.1f}",
                            "n1_body_pips": n1_body_pips,
                            "entry": n_close,
                        })

            # Near lower BB, bullish engulfing → BUY
            dist_lower = n1_low - lower_n1
            if 0 <= dist_lower <= bb_prox:
                if n1_close > n1_open and n1_close > n2_high and n1_body_ratio >= 0.60:
                    if n_close > n1_high:
                        patterns.append({
                            "date": date,
                            "time": ts.strftime("%H:%M"),
                            "hour": h,
                            "variant": "V3",
                            "direction": "BUY",
                            "detail": f"engulf@lower prox={dist_lower/PPP:.1f}p body={n1_body_ratio*100:.0f}% confirm={n_close:.1f}>{n1_high:.1f}",
                            "n1_body_pips": n1_body_pips,
                            "entry": n_close,
                        })

    return patterns


def main():
    print("=" * 130)
    print("  GBPUSD V1/V3 PATTERN SCAN — All valid patterns in 07:00–17:00 UTC")
    print("  Cooldown: 60 min | London body filter: 10 pips | BB proximity: 15 pips")
    print("=" * 130)
    print()

    grand_total = 0
    grand_fireable = 0
    grand_blocked = 0

    for date in DATES:
        patterns = scan_day(date)

        # Simulate cooldown blocking
        last_fire_time = None
        for p in patterns:
            ts = datetime.strptime(f"{p['date']} {p['time']}", "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)
            h = p["hour"]
            is_london = 7 <= h < 11
            is_ny = 13 <= h < 17

            # Body filter for London
            if is_london and p["n1_body_pips"] < MIN_BODY_PIPS:
                p["status"] = "FILTERED (body<10p)"
            elif last_fire_time and (ts - last_fire_time).total_seconds() < COOLDOWN_MINS * 60:
                p["status"] = "BLOCKED (cooldown)"
            else:
                p["status"] = "FIREABLE"
                last_fire_time = ts

        total = len(patterns)
        fireable = sum(1 for p in patterns if p["status"] == "FIREABLE")
        blocked = sum(1 for p in patterns if p["status"] == "BLOCKED (cooldown)")
        filtered = sum(1 for p in patterns if "FILTERED" in p["status"])

        grand_total += total
        grand_fireable += fireable
        grand_blocked += blocked

        print(f"  {date}  |  Patterns: {total}  |  Fireable: {fireable}  |  Cooldown-blocked: {blocked}  |  Body-filtered: {filtered}")
        if patterns:
            for p in patterns:
                session = "London" if 7 <= p["hour"] < 11 else ("NY" if 13 <= p["hour"] < 17 else "Gap")
                body_str = f"body={p['n1_body_pips']:.0f}p"
                print(f"    {p['time']}  {p['variant']} {p['direction']:>4}  {body_str:>9}  [{session:>6}]  {p['status']:<22}  {p['detail']}")
        else:
            print("    (no patterns)")
        print()

    print("=" * 130)
    print(f"  TOTALS across {len(DATES)} days:")
    print(f"    Patterns formed:     {grand_total}")
    print(f"    Fireable (tradeable): {grand_fireable}")
    print(f"    Blocked by cooldown: {grand_blocked}")
    print(f"    Avg patterns/day:    {grand_total / len(DATES):.1f}")
    print(f"    Avg fireable/day:    {grand_fireable / len(DATES):.1f}")
    print("=" * 130)


if __name__ == "__main__":
    main()
