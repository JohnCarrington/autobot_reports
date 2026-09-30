#!/usr/bin/env python3
"""Run true_replay.py in parallel across many dates, aggregate results."""
import json, os, subprocess, sys, tempfile
from collections import defaultdict
from multiprocessing import Pool
from pathlib import Path

PAIR = "GBPUSD"
START = "2026-03-23"
END   = "2026-03-31"
CANDLES = Path(f"/opt/tradingbot/data/candles/{PAIR}")
OUT_DIR = Path("/tmp/replay_batch"); OUT_DIR.mkdir(exist_ok=True)

def run_one(date: str):
    out_path = OUT_DIR / f"{date}.json"
    env = {**os.environ, "TRADE_LOG_OUT": str(out_path)}
    log_path = OUT_DIR / f"{date}.log"
    with open(log_path, "w") as lf:
        r = subprocess.run(
            ["python3", "/opt/tradingbot/true_replay.py", PAIR, date],
            env=env, stdout=lf, stderr=subprocess.STDOUT, cwd="/opt/tradingbot",
        )
    if out_path.exists():
        trades = json.loads(out_path.read_text())
    else:
        trades = []
    return date, r.returncode, trades

def main():
    dates = sorted(f.stem for f in CANDLES.glob("*.csv")
                   if START <= f.stem <= END)
    print(f"Running {len(dates)} dates on {os.cpu_count()} CPUs…", flush=True)

    all_trades = []
    with Pool(processes=4) as pool:
        done = 0
        for date, rc, trades in pool.imap_unordered(run_one, dates):
            done += 1
            for t in trades:
                t["_date"] = date
            all_trades.extend(trades)
            print(f"  [{done}/{len(dates)}] {date} rc={rc} trades={len(trades)}", flush=True)

    # Save aggregate
    Path("/tmp/replay_batch_trades.json").write_text(json.dumps(all_trades))
    print(f"\nTotal trades: {len(all_trades)}")

    if not all_trades:
        return

    # Monthly breakdown
    by_month = defaultdict(list)
    for t in all_trades:
        by_month[t["_date"][:7]].append(t)

    print("\n" + "=" * 72)
    print("  MONTHLY BREAKDOWN")
    print("=" * 72)
    print(f"  {'Month':<10} {'N':>4} {'W':>4} {'L':>4} {'WR%':>6} {'Total':>9} {'Avg':>7}")
    print(f"  {'-'*10} {'-'*4} {'-'*4} {'-'*4} {'-'*6} {'-'*9} {'-'*7}")
    for m in sorted(by_month):
        ts = by_month[m]
        pnls = [t["pnl"] for t in ts]
        n = len(ts); w = sum(1 for p in pnls if p > 0); l = sum(1 for p in pnls if p < 0)
        tot = sum(pnls)
        print(f"  {m:<10} {n:>4} {w:>4} {l:>4} {w/n*100:>5.1f}% {tot:>+9.1f} {tot/n:>+7.1f}")

    # By strategy
    by_mode = defaultdict(list)
    for t in all_trades:
        by_mode[t["mode"]].append(t)

    print("\n" + "=" * 72)
    print("  STRATEGY PERFORMANCE")
    print("=" * 72)
    print(f"  {'Strategy':<28} {'N':>4} {'W':>4} {'L':>4} {'WR%':>6} {'Total':>9} {'Avg':>7}")
    print(f"  {'-'*28} {'-'*4} {'-'*4} {'-'*4} {'-'*6} {'-'*9} {'-'*7}")
    gt = gn = gw = 0
    for m in sorted(by_mode):
        ts = by_mode[m]
        pnls = [t["pnl"] for t in ts]
        n = len(ts); w = sum(1 for p in pnls if p > 0); l = sum(1 for p in pnls if p < 0)
        tot = sum(pnls)
        gt += tot; gn += n; gw += w
        print(f"  {m:<28} {n:>4} {w:>4} {l:>4} {w/n*100:>5.1f}% {tot:>+9.1f} {tot/n:>+7.1f}")
    print(f"  {'-'*28} {'-'*4} {'-'*4} {'-'*4} {'-'*6} {'-'*9} {'-'*7}")
    print(f"  {'TOTAL':<28} {gn:>4} {gw:>4} {gn-gw:>4} {gw/gn*100:>5.1f}% {gt:>+9.1f} {gt/gn:>+7.1f}")

if __name__ == "__main__":
    main()
