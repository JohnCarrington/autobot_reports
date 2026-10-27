"""
Investigate whether 1.3320 could have been identified from the data available
at 2026-10-26 05:57 UK time (= 05:57 UTC, since UK switched off BST on
2026-10-25).

Only use bars completed strictly before the 06:00 UTC H1 bar.
That means:
  - M5: bars with timestamp < 2026-10-26T05:55:00Z are completed; the 05:55
        M5 bar closed at 05:59:59.999 → completed before 05:57? NO, 05:55
        bar is OPEN during 05:57. So "completed" M5 bars run up through
        2026-10-26T05:50:00Z inclusive.
  - H1: last completed H1 bar is 2026-10-26T04:00:00Z (closed at 05:00Z).
  - H4: last completed H4 bar is 2026-10-26T00:00:00Z (closed at 04:00Z).

We will:
  1. Enumerate ALL H1 and H4 swings confirmed by 05:57 UTC on 2026-10-26.
  2. Compute Fib levels (and controls) for each; check which land within
     ±5p and ±10p of 1.3320.
  3. Also report nearest technical levels: pivots, EMAs, prior session HL,
     recent swing extrema.
"""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd

from data_loader import load_m5, resample_ohlc
from swings import detect_swings
from fibs import FIB_PCTS, CONTROL_PCTS, compute_levels

TARGET_PRICE = 13320.0  # 1.3320 in pip-scale
AS_OF = pd.Timestamp("2026-10-26T05:57:00+00:00")  # 05:57 UTC on 2026-10-26

M5_CUTOFF_INCLUSIVE = pd.Timestamp("2026-10-26T05:50:00+00:00")  # last completed M5 bar
H1_CUTOFF_INCLUSIVE = pd.Timestamp("2026-10-26T04:00:00+00:00")  # last completed H1 bar
H4_CUTOFF_INCLUSIVE = pd.Timestamp("2026-10-26T00:00:00+00:00")  # last completed H4 bar


def truncate(df: pd.DataFrame, cutoff_inclusive: pd.Timestamp) -> pd.DataFrame:
    return df[df["timestamp"] <= cutoff_inclusive].reset_index(drop=True)


def main():
    # Load last 60 days to give the detector enough history for all thresholds
    start = (AS_OF - pd.Timedelta(days=60)).date()
    end = AS_OF.date()
    m5 = load_m5(start, end)
    m5 = truncate(m5, M5_CUTOFF_INCLUSIVE)
    h1 = truncate(resample_ohlc(m5, "1h"), H1_CUTOFF_INCLUSIVE)
    h4 = truncate(resample_ohlc(m5, "4h"), H4_CUTOFF_INCLUSIVE)

    print(f"Data as of {AS_OF.isoformat()} (truncated to completed bars only)")
    print(f"  M5 bars loaded:   {len(m5):,}  last ts: {m5['timestamp'].max()}")
    print(f"  H1 bars:          {len(h1):,}  last ts: {h1['timestamp'].max()}")
    print(f"  H4 bars:          {len(h4):,}  last ts: {h4['timestamp'].max()}")
    print()

    # Current spot (last completed M5 close)
    last_close = float(m5["close"].iloc[-1])
    print(f"Spot (last completed M5 close): {last_close:.2f}  ({last_close/10000:.5f})")
    print(f"TARGET: 1.3320 (pip-scale {TARGET_PRICE:.2f})")
    print(f"  distance: {TARGET_PRICE - last_close:.1f} pips from spot")
    print()

    # Enumerate swings at a range of thresholds; keep only those CONFIRMED by AS_OF
    hits = []
    for tf, bars, cutoff, thresholds in [
        ("H1", h1, H1_CUTOFF_INCLUSIVE, [20.0, 40.0, 80.0, 150.0]),
        ("H4", h4, H4_CUTOFF_INCLUSIVE, [40.0, 80.0, 150.0, 300.0]),
    ]:
        print(f"=== {tf} swings (thresholds {thresholds}) ===")
        for th in thresholds:
            sw = detect_swings(bars, th)
            if len(sw) == 0:
                continue
            # Only swings confirmed by cutoff
            sw = sw[sw["conf_time"] <= cutoff].reset_index(drop=True)
            if len(sw) == 0:
                continue
            # The most recent 10 swings for context
            print(f"  --- threshold {th}p: {len(sw)} swings total; last 6 ---")
            tail = sw.tail(6)[["swing_id", "direction", "start_time", "end_time", "pips", "conf_time", "start_price", "end_price"]]
            print(tail.to_string())

            # Compute levels on all swings and look for 1.3320 proximity
            lv = compute_levels(sw)
            lv["abs_dist_from_target"] = (lv["level_price"] - TARGET_PRICE).abs()
            near5 = lv[lv["abs_dist_from_target"] <= 5.0].copy()
            near10 = lv[lv["abs_dist_from_target"] <= 10.0].copy()
            if len(near10):
                print(f"\n  >>> Levels within ±10p of 1.3320 ({len(near10)} matches, {len(near5)} within ±5p):")
                near10 = near10.sort_values("abs_dist_from_target")
                for _, r in near10.iterrows():
                    hits.append({
                        "tf": tf, "threshold_pips": th,
                        "level_name": r["level_name"], "pct": r["pct"],
                        "level_price": r["level_price"],
                        "dist_from_target": float(r["level_price"] - TARGET_PRICE),
                        "swing_direction": r["swing_direction"],
                        "swing_pips": r["swing_pips"],
                        "swing_start_time": r["swing_start_time"],
                        "swing_end_time": r["swing_end_time"],
                        "swing_start_price": r["swing_start_price"],
                        "swing_end_price": r["swing_end_price"],
                        "live_from": r["live_from"],
                    })
                    print(f"     {r['level_name']:>10s} @ {r['level_price']:.2f}  (dist {r['level_price']-TARGET_PRICE:+.1f}p)  "
                          f"from {r['swing_direction']}-swing {r['swing_start_price']:.2f}->{r['swing_end_price']:.2f} "
                          f"({r['swing_pips']:.1f}p)  live_from {r['live_from']}")
            else:
                print(f"  (no levels within ±10p of 1.3320 for {tf}@{th}p)")
            print()

    # Also compute non-Fib technical levels at AS_OF
    print("=== Non-Fib technical references near 1.3320 ===")
    from confluence import daily_pivots_from, build_daily_hlc, build_h1_emas, build_h4_emas, _session_extrema

    daily = build_daily_hlc(m5)
    # Prior day = 2026-10-23 (Friday); 10-25 is Sunday with likely minimal data; 10-26 is Monday
    daily = daily.sort_values("date")
    prev_rows = daily[daily["date"] < AS_OF.date()]
    print(f"  Daily history has {len(prev_rows)} completed days up to {prev_rows['date'].iloc[-1]}")
    if len(prev_rows) >= 1:
        pd_row = prev_rows.iloc[-1]
        pivots = daily_pivots_from(pd_row["h"], pd_row["l"], pd_row["c"])
        print(f"  Prior-day ({pd_row['date']}) H/L/C: {pd_row['h']:.2f} / {pd_row['l']:.2f} / {pd_row['c']:.2f}")
        for name, v in pivots.items():
            dist = v - TARGET_PRICE
            print(f"     {name}: {v:.2f}  (dist {dist:+.1f}p from 1.3320)")

    h1e = build_h1_emas(h1)
    h4e = build_h4_emas(h4)
    last_h1 = h1e.iloc[-1]
    last_h4 = h4e.iloc[-1]
    print(f"\n  H1 EMA20: {last_h1['ema20']:.2f}  dist from 1.3320: {last_h1['ema20']-TARGET_PRICE:+.1f}p")
    print(f"  H1 EMA50: {last_h1['ema50']:.2f}  dist from 1.3320: {last_h1['ema50']-TARGET_PRICE:+.1f}p")
    print(f"  H4 EMA20: {last_h4['ema20']:.2f}  dist from 1.3320: {last_h4['ema20']-TARGET_PRICE:+.1f}p")
    print(f"  H4 EMA50: {last_h4['ema50']:.2f}  dist from 1.3320: {last_h4['ema50']-TARGET_PRICE:+.1f}p")

    sess = _session_extrema(m5)
    # Prior session dates: pre-weekend Friday 2026-10-23
    prev_sess_date = pd.Timestamp("2026-10-23").date()
    for name, src in sess.items():
        try:
            r = src.loc[prev_sess_date]
            print(f"  Prev {name} session {prev_sess_date}: H={r['h']:.2f} ({r['h']-TARGET_PRICE:+.1f}p from 1.3320)  "
                  f"L={r['l']:.2f} ({r['l']-TARGET_PRICE:+.1f}p from 1.3320)")
        except (KeyError, IndexError):
            pass

    # Recent swing extrema
    print("\n=== Recent H1 swing extrema (last 10 confirmed swings @ 40p) ===")
    sw_h1_40 = detect_swings(h1, 40.0)
    sw_h1_40 = sw_h1_40[sw_h1_40["conf_time"] <= H1_CUTOFF_INCLUSIVE].tail(10)
    for _, r in sw_h1_40.iterrows():
        extrema_price = r["end_price"]
        extrema_time = r["end_time"]
        dist = extrema_price - TARGET_PRICE
        tag = "swing_HIGH" if r["direction"] == "UP" else "swing_LOW "
        print(f"  {tag} @ {extrema_price:.2f}  ({extrema_time})  dist {dist:+.1f}p from 1.3320")

    # Save hits as a CSV for the report
    hits_df = pd.DataFrame(hits)
    out = "/home/autobot/research/gbpusd_fib_reversal_20261027/data_out/pia_1_3320_fib_matches.csv"
    hits_df.to_csv(out, index=False)
    print(f"\nWrote: {out}  ({len(hits_df)} Fib/control levels within ±10p of 1.3320)")


if __name__ == "__main__":
    main()
