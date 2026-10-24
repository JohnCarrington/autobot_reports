#!/usr/bin/env python3
"""Compute daily market-structure features for each weekday:
  * Previous-day H / L / Close (PDH, PDL, PDC)
  * Classical pivots: PP, R1, R2, R3, S1, S2, S3
  * Prior-day range (used as ATR proxy on D1)
  * 14-day ATR of the daily range
  * 7-day realised volatility (close-close)
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.append(str(Path(__file__).parent))
from census import CANDLES_26, CANDLES_EXT, _load_day_file  # noqa: E402

OUT = Path("<research_workspace>/outputs/daily_structure.csv")


def _daily_from_m5():
    rows = []
    for p in sorted(CANDLES_EXT.glob("*.csv")):
        d = _load_day_file(p, "BID")
        if d is None or len(d) < 20:
            continue
        date = d["ts"].iloc[0].date()
        if date.weekday() >= 5:
            continue
        rows.append({
            "date": date.isoformat(), "basis": "BID",
            "open": d["open"].iloc[0] / 10000,
            "high": d["high"].max() / 10000,
            "low": d["low"].min() / 10000,
            "close": d["close"].iloc[-1] / 10000,
        })
    for p in sorted(CANDLES_26.glob("*.csv")):
        d = _load_day_file(p, "MID")
        if d is None or len(d) < 20:
            continue
        date = d["ts"].iloc[0].date()
        if date.weekday() >= 5:
            continue
        rows.append({
            "date": date.isoformat(), "basis": "MID",
            "open": d["open"].iloc[0] / 10000,
            "high": d["high"].max() / 10000,
            "low": d["low"].min() / 10000,
            "close": d["close"].iloc[-1] / 10000,
        })
    return pd.DataFrame(rows).sort_values("date").reset_index(drop=True)


def main():
    daily = _daily_from_m5()

    # Pivots & previous-day context
    daily["PDH"] = daily["high"].shift(1)
    daily["PDL"] = daily["low"].shift(1)
    daily["PDC"] = daily["close"].shift(1)
    daily["prev_range"] = daily["PDH"] - daily["PDL"]
    pp = (daily["PDH"] + daily["PDL"] + daily["PDC"]) / 3
    rng = daily["PDH"] - daily["PDL"]
    daily["PP"] = pp
    daily["R1"] = 2 * pp - daily["PDL"]
    daily["S1"] = 2 * pp - daily["PDH"]
    daily["R2"] = pp + rng
    daily["S2"] = pp - rng
    daily["R3"] = daily["PDH"] + 2 * (pp - daily["PDL"])
    daily["S3"] = daily["PDL"] - 2 * (daily["PDH"] - pp)

    # ATR14 of daily range + 7-day realized vol
    daily["atr14"] = daily["prev_range"].rolling(14, min_periods=5).mean()
    log_ret = np.log(daily["close"] / daily["close"].shift(1))
    daily["rv7"] = log_ret.rolling(7, min_periods=5).std()

    # Pip-scaled columns
    for c in ["PDH", "PDL", "PDC", "PP", "R1", "R2", "R3", "S1", "S2", "S3",
              "prev_range", "atr14"]:
        daily[c + "_pips"] = (daily[c] * 10000).round(2) if c != "prev_range" and c != "atr14" \
            else (daily[c] * 10000).round(1)
    daily.to_csv(OUT, index=False)
    print(f"Daily rows: {len(daily)}")
    print(daily.tail(5)[["date", "high", "low", "close", "atr14"]].to_string(index=False))


if __name__ == "__main__":
    main()
