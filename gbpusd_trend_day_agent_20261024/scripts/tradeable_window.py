#!/usr/bin/env python3
"""
For each weekday, compute two trend-day definitions:

  A) Full-day one-directional swing (as in census.py) — the "available
     opportunity".
  B) Max one-directional swing confined to 07:00-22:00 UK local — the
     "tradeable opportunity".

Also compute: pips remaining in the dominant direction at each hour from
07:00 to 15:00 UK local — i.e. the pips still available between hour H and
the swing peak, measured in the dominant direction.
"""
from __future__ import annotations
import datetime as dt
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.append(str(Path(__file__).parent))
from census import (  # noqa: E402
    CANDLES_26, CANDLES_EXT, _07_uk_in_utc, _load_day_file, _uk_offset_hours,
)

OUT = Path("<research_workspace>/outputs/tradeable_window.csv")


def _swing(df: pd.DataFrame) -> dict:
    high = df["high"].to_numpy(dtype=float)
    low = df["low"].to_numpy(dtype=float)
    n = len(df)
    if n < 2:
        return {}
    rl = low[0]; rl_i = 0; bl = 0.0; bl_lo = 0; bl_hi = 0
    for j in range(n):
        if low[j] < rl: rl = low[j]; rl_i = j
        if high[j] - rl > bl: bl = high[j] - rl; bl_lo = rl_i; bl_hi = j
    rh = high[0]; rh_i = 0; bs = 0.0; bs_hi = 0; bs_lo = 0
    for j in range(n):
        if high[j] > rh: rh = high[j]; rh_i = j
        if rh - low[j] > bs: bs = rh - low[j]; bs_hi = rh_i; bs_lo = j
    if bl >= bs:
        return {"dir": "LONG", "pips": bl, "s": bl_lo, "e": bl_hi,
                "anchor": low[bl_lo], "peak": high[bl_hi]}
    return {"dir": "SHORT", "pips": bs, "s": bs_hi, "e": bs_lo,
            "anchor": high[bs_hi], "peak": low[bs_lo]}


def _window_bounds(day_ts_utc: pd.Timestamp) -> tuple[pd.Timestamp, pd.Timestamp]:
    off = _uk_offset_hours(day_ts_utc)
    date = day_ts_utc.date()
    uk07 = pd.Timestamp(date, tz="UTC") + pd.Timedelta(hours=7 - off)
    uk22 = pd.Timestamp(date, tz="UTC") + pd.Timedelta(hours=22 - off)
    return uk07, uk22


def analyze(path: Path, basis: str) -> dict | None:
    df = _load_day_file(path, basis)
    if df is None or len(df) < 20:
        return None
    date = df["ts"].iloc[0].date()
    if date.weekday() >= 5:
        return None

    full = _swing(df)
    uk07, uk22 = _window_bounds(df["ts"].iloc[0])
    win_df = df[(df["ts"] >= uk07) & (df["ts"] <= uk22)].reset_index(drop=True)
    win = _swing(win_df) if not win_df.empty else {}

    # Remaining-direction opportunity at discrete hours
    remaining = {}
    hourly_prices = {}
    for h in range(7, 16):  # 07:00 … 15:00 UK
        off = _uk_offset_hours(df["ts"].iloc[0])
        tgt = pd.Timestamp(date, tz="UTC") + pd.Timedelta(hours=h - off)
        subset = df[df["ts"] >= tgt]
        if subset.empty or not full:
            remaining[f"rem_at_{h:02d}_uk"] = None
            hourly_prices[f"price_at_{h:02d}_uk"] = None
            continue
        p0 = float(subset["close"].iloc[0])
        hourly_prices[f"price_at_{h:02d}_uk"] = round(p0 / 10000, 5)
        if full["dir"] == "LONG":
            rem = float(subset["high"].max()) - p0
        else:
            rem = p0 - float(subset["low"].min())
        remaining[f"rem_at_{h:02d}_uk"] = round(rem, 2)

    out = {
        "date": date.isoformat(),
        "weekday": date.strftime("%a"),
        "basis": basis,
        "full_dir": full.get("dir") if full else None,
        "full_pips": round(full["pips"], 2) if full else None,
        "win_dir": win.get("dir") if win else None,
        "win_pips": round(win["pips"], 2) if win else None,
        "trend_full": bool(full and full["pips"] >= 80),
        "trend_win":  bool(win and win["pips"] >= 80),
    }
    out.update(hourly_prices)
    out.update(remaining)
    return out


def main():
    rows = []
    for p in sorted(CANDLES_EXT.glob("*.csv")):
        r = analyze(p, "BID")
        if r: rows.append(r)
    for p in sorted(CANDLES_26.glob("*.csv")):
        r = analyze(p, "MID")
        if r: rows.append(r)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(rows)
    df.to_csv(OUT, index=False)

    full_trend = df[df.trend_full]
    win_trend = df[df.trend_win]
    both = df[df.trend_full & df.trend_win]
    print(f"Days: {len(df)}")
    print(f"Full-day trend days (>=80 pips): {len(full_trend)} ({len(full_trend)/len(df)*100:.1f}%)")
    print(f"Within 07-22 UK trend days: {len(win_trend)} ({len(win_trend)/len(df)*100:.1f}%)")
    print(f"Both full and window-constrained: {len(both)}")

    # Remaining opportunity distributions
    for h in range(7, 16):
        c = f"rem_at_{h:02d}_uk"
        if c in full_trend.columns:
            v = full_trend[c].dropna()
            print(f"{h:02d}:00 UK — remaining pips (trend days): "
                  f"median {v.median():.1f}, mean {v.mean():.1f}, "
                  f">=50 share {(v>=50).mean()*100:.1f}%, "
                  f">=25 share {(v>=25).mean()*100:.1f}%")

    # Save condensed summary of trend-day dates
    full_trend[[c for c in full_trend.columns if c not in [f'price_at_{h:02d}_uk' for h in range(7,16)]]
    ].sort_values('date').to_csv(
        "<research_workspace>/outputs/trend_day_list.csv", index=False)


if __name__ == "__main__":
    main()
