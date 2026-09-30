#!/usr/bin/env python3
"""
sl_analytics.py — Extract actual SL distances from IG trade history.

Queries the IG API for closed position history and computes real
stop-loss distances, spread at entry, and effective buffer per pair.
Saves sl_analytics.csv and prints a summary table.

Usage:
    python3 sl_analytics.py              # last 30 days
    python3 sl_analytics.py --days 7     # last 7 days
"""

import csv
import os
import sys
from collections import defaultdict

sys.path.insert(0, "/opt/tradingbot")
os.chdir("/opt/tradingbot")

from dotenv import load_dotenv
load_dotenv("/opt/tradingbot/.env")


PAIR_MAP = {
    "CS.D.GBPUSD.TODAY.IP": "GBPUSD",
    "CS.D.EURUSD.TODAY.IP": "EURUSD",
    "CS.D.USDJPY.TODAY.IP": "USDJPY",
    "CS.D.USDCAD.TODAY.IP": "USDCAD",
    "CS.D.GBPJPY.TODAY.IP": "GBPJPY",
}

# Average spreads measured from live tick data (2026-04-08)
AVG_SPREADS = {
    "EURUSD": 0.8,
    "GBPUSD": 1.6,
    "USDJPY": 1.4,
    "USDCAD": 2.1,
    "GBPJPY": 3.0,
}

CSV_PATH = "/opt/tradingbot/data/sl_analytics.csv"
CSV_FIELDS = [
    "timestamp", "pair", "direction", "entry_price", "sl_price",
    "sl_distance_pips", "spread_at_entry", "effective_buffer_pips",
]


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=30)
    args = parser.parse_args()

    from ig_auth import get_ig_session
    session = get_ig_session()
    ig = session[0] if isinstance(session, (tuple, list)) else session

    ms = args.days * 24 * 3600 * 1000
    activity = ig.fetch_account_activity_by_period(ms)

    # Filter to position opens with stop data
    opens = activity[
        (activity["activity"] == "Market Order") &
        (activity["result"].str.contains("Position opened", na=False)) &
        (activity["stop"].notna()) &
        (activity["stop"] != "") &
        (activity["level"].notna()) &
        (activity["level"] != "")
    ].copy()

    print(f"Found {len(opens)} position opens with stop data (last {args.days} days)")
    print()

    rows = []
    for _, row in opens.iterrows():
        epic = str(row["epic"])
        pair = PAIR_MAP.get(epic, epic)
        if pair not in AVG_SPREADS:
            continue

        entry = float(row["level"])
        sl = float(row["stop"])
        size = str(row.get("size", ""))

        if size.startswith("+"):
            direction = "BUY"
            sl_distance = entry - sl
        elif size.startswith("-"):
            direction = "SELL"
            sl_distance = sl - entry
        else:
            direction = "BUY" if sl < entry else "SELL"
            sl_distance = abs(entry - sl)

        spread = AVG_SPREADS.get(pair, 1.0)
        effective_buffer = sl_distance - spread

        date_str = str(row.get("date", ""))
        time_str = str(row.get("time", ""))
        # Convert DD/MM/YY to ISO
        try:
            d, m, y = date_str.split("/")
            ts = f"20{y}-{m}-{d}T{time_str}:00Z"
        except Exception:
            ts = f"{date_str} {time_str}"

        rows.append({
            "timestamp": ts,
            "pair": pair,
            "direction": direction,
            "entry_price": round(entry, 1),
            "sl_price": round(sl, 1),
            "sl_distance_pips": round(sl_distance, 1),
            "spread_at_entry": spread,
            "effective_buffer_pips": round(effective_buffer, 1),
        })

    # Sort chronologically
    rows.sort(key=lambda r: r["timestamp"])

    # Save CSV
    os.makedirs(os.path.dirname(CSV_PATH), exist_ok=True)
    with open(CSV_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    print(f"Saved {len(rows)} rows to {CSV_PATH}")
    print()

    # Summary statistics per pair
    by_pair = defaultdict(list)
    for r in rows:
        by_pair[r["pair"]].append(r)

    print("SL DISTANCE SUMMARY (all values in pips)")
    print("=" * 100)
    print(f"{'Pair':<8} {'Count':>6} {'Min':>6} {'p25':>6} {'Mean':>6} {'p75':>6} {'p95':>6} {'Max':>6}  {'Spread':>6} {'Eff p25':>7} {'Eff Mean':>8} {'Eff p75':>7}")
    print("-" * 100)

    for pair in ["GBPUSD", "EURUSD", "USDJPY", "USDCAD"]:
        trades = by_pair.get(pair, [])
        if not trades:
            print(f"{pair:<8} {'—':>6}")
            continue

        distances = sorted(r["sl_distance_pips"] for r in trades)
        buffers = sorted(r["effective_buffer_pips"] for r in trades)
        n = len(distances)
        spread = AVG_SPREADS[pair]

        def pct(arr, p):
            idx = min(int(len(arr) * p), len(arr) - 1)
            return arr[idx]

        print(
            f"{pair:<8} {n:>6} {distances[0]:>6.1f} {pct(distances, 0.25):>6.1f} "
            f"{sum(distances)/n:>6.1f} {pct(distances, 0.75):>6.1f} "
            f"{pct(distances, 0.95):>6.1f} {distances[-1]:>6.1f}  "
            f"{spread:>6.1f} {pct(buffers, 0.25):>7.1f} "
            f"{sum(buffers)/n:>8.1f} {pct(buffers, 0.75):>7.1f}"
        )

    print()

    # Flag pairs with tight effective buffers
    print("RISK ASSESSMENT")
    print("-" * 60)
    for pair in ["GBPUSD", "EURUSD", "USDJPY", "USDCAD"]:
        trades = by_pair.get(pair, [])
        if not trades:
            continue
        buffers = [r["effective_buffer_pips"] for r in trades]
        mean_buf = sum(buffers) / len(buffers)
        tight = [b for b in buffers if b < 5.0]
        tight_pct = len(tight) / len(buffers) * 100
        if tight_pct > 20:
            print(f"  ⚠  {pair}: {tight_pct:.0f}% of trades have <5p effective buffer (mean={mean_buf:.1f}p)")
        elif tight_pct > 0:
            print(f"  ·  {pair}: {tight_pct:.0f}% of trades have <5p effective buffer (mean={mean_buf:.1f}p)")
        else:
            print(f"  ✓  {pair}: all trades have ≥5p effective buffer (mean={mean_buf:.1f}p)")


if __name__ == "__main__":
    main()
