#!/usr/bin/env python3
import argparse
import numpy as np
import pandas as pd

def load_base(csv_path: str) -> pd.DataFrame:
    df = pd.read_csv(csv_path)
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    df = df.sort_values("timestamp").reset_index(drop=True)
    for c in ["open", "high", "low", "close"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna(subset=["timestamp","open","high","low","close"]).reset_index(drop=True)
    return df

def gen_walk(last_close: float, n: int, step_std_points: float, wick_scale: float, seed: int):
    rng = np.random.default_rng(seed)
    # random walk in *points* (your cache is already in IG points)
    steps = rng.normal(0, step_std_points, size=n)
    closes = last_close + np.cumsum(steps)

    opens = np.empty(n)
    highs = np.empty(n)
    lows  = np.empty(n)

    prev = last_close
    for i in range(n):
        o = prev
        c = closes[i]
        # wick sizes proportional to abs move + some noise
        body = abs(c - o)
        wick = (body * wick_scale) + abs(rng.normal(0, step_std_points * 0.5))
        h = max(o, c) + wick
        l = min(o, c) - wick
        opens[i], highs[i], lows[i] = o, h, l
        prev = c

    return opens, highs, lows, closes

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", required=True)
    ap.add_argument("--out", dest="outp", required=True)
    ap.add_argument("--add", type=int, default=500, help="how many extra 5m candles to generate")
    ap.add_argument("--step-std", type=float, default=3.0, help="random walk std in POINTS per candle")
    ap.add_argument("--wick-scale", type=float, default=0.8, help="wick size multiplier")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    base = load_base(args.inp)
    if base.empty:
        raise SystemExit("Base CSV has no rows")

    last_ts = base["timestamp"].iloc[-1]
    last_close = float(base["close"].iloc[-1])

    opens, highs, lows, closes = gen_walk(last_close, args.add, args.step_std, args.wick_scale, args.seed)

    # continue timestamps every 5 minutes
    new_ts = pd.date_range(last_ts + pd.Timedelta(minutes=5), periods=args.add, freq="5min", tz="UTC")

    ext = pd.DataFrame({
        "timestamp": new_ts,
        "open": opens,
        "high": highs,
        "low": lows,
        "close": closes,
    })

    out = pd.concat([base, ext], ignore_index=True)
    out.to_csv(args.outp, index=False)
    print(f"Wrote {len(out)} candles -> {args.outp}")

if __name__ == "__main__":
    main()
