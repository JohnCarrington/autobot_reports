"""
USDJPY BB_WIDTH_PCTL_20_2 session-decomposition sanity check.

Two questions:
  1. Is the elevated Asian-session mean (56.3 vs London 50.1) real Tokyo
     microstructure or a metric artefact? Real microstructure should show
     a visible dip during Tokyo lunch (03:00-04:00 UTC) and thinner
     Tokyo afternoon (04:00-06:00 UTC) vs Tokyo morning (00:00-03:00 UTC).
  2. Does the truly dead window (21:00-23:00 UTC, post-NY-close,
     pre-Tokyo-open) sit *below* the Asian average? If yes, metric is
     correctly tracking volatility regimes. If similar or higher, the
     metric isn't picking up quiet periods on USDJPY.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from indicators import add_indicators  # noqa: E402


def main() -> None:
    cache = Path("/opt/tradingbot/cache/USDJPY_candles_deep.csv")
    df = pd.read_csv(cache, parse_dates=["timestamp"])
    df = df.set_index("timestamp").sort_index()

    enr = add_indicators(df.reset_index(), caller="bb_width_pctl_session_check")
    enr["timestamp"] = df.index
    enr = enr.set_index("timestamp")

    col = "BB_WIDTH_PCTL_20_2"
    if col not in enr.columns:
        print(f"FATAL: {col} not emitted. Columns: {list(enr.columns)}")
        sys.exit(1)

    valid = enr[col].dropna()
    print(f"rows={len(enr)}  valid={len(valid)}  first_valid_idx={enr[col].first_valid_index()}")
    print(f"range: {enr.index.min()} -> {enr.index.max()}\n")

    hour = enr.index.hour
    enr = enr.assign(_hour=hour)

    # --- Check 1: Tokyo decomposition -------------------------------------
    windows = [
        ("Tokyo morning  00:00-03:00", (0, 1, 2)),
        ("Tokyo lunch    03:00-04:00", (3,)),
        ("Tokyo afternoon 04:00-06:00", (4, 5)),
        ("London         07:00-12:00", (7, 8, 9, 10, 11)),
        ("NY             13:00-17:00", (13, 14, 15, 16)),
        ("Dead window    21:00-23:00", (21, 22)),
    ]

    print("=" * 70)
    print(f"{col} mean by window (USDJPY, UTC hours):")
    print("=" * 70)
    print(f"{'window':<32} {'n':>6} {'mean':>7} {'median':>7} {'std':>7}")
    means = {}
    for label, hours in windows:
        sub = enr.loc[enr["_hour"].isin(hours), col].dropna()
        if len(sub) == 0:
            print(f"{label:<32} {'(empty)':>6}")
            continue
        means[label] = sub.mean()
        print(
            f"{label:<32} {len(sub):>6d} "
            f"{sub.mean():>7.2f} {sub.median():>7.2f} {sub.std():>7.2f}"
        )
    print()

    # --- Check 1a: hour-by-hour through Asian window ----------------------
    print("=" * 70)
    print("Asian block hour-by-hour (watch for lunch-lull dip):")
    print("=" * 70)
    print(f"{'hour (UTC)':<12} {'n':>6} {'mean':>7} {'median':>7}")
    for h in range(0, 7):
        sub = enr.loc[enr["_hour"] == h, col].dropna()
        if len(sub) == 0:
            continue
        print(f"{h:02d}:00-{h:02d}:59   {len(sub):>6d} {sub.mean():>7.2f} {sub.median():>7.2f}")
    print()

    # --- Check 2: quiet-window comparison ---------------------------------
    asian_mean = means.get("Tokyo morning  00:00-03:00", float("nan"))
    dead_mean = means.get("Dead window    21:00-23:00", float("nan"))
    print("=" * 70)
    print("Interpretation")
    print("=" * 70)
    print(f"Tokyo morning mean:  {asian_mean:.2f}")
    print(f"Dead window mean:    {dead_mean:.2f}")
    delta = asian_mean - dead_mean
    print(f"Delta (morning - dead): {delta:+.2f}")
    if delta > 5:
        print("  -> Tokyo morning clearly above dead window: metric IS tracking quiet periods.")
    elif delta < -5:
        print("  -> Tokyo morning BELOW dead window: unexpected, investigate.")
    else:
        print("  -> Tokyo morning ~= dead window: metric may not be picking up volatility regimes.")

    tm = means.get("Tokyo morning  00:00-03:00", float("nan"))
    tl = means.get("Tokyo lunch    03:00-04:00", float("nan"))
    ta = means.get("Tokyo afternoon 04:00-06:00", float("nan"))
    print(f"\nTokyo morning -> lunch -> afternoon: {tm:.2f} -> {tl:.2f} -> {ta:.2f}")
    if tl < tm and tl < ta:
        print("  -> Clear lunch-lull dip: metric IS capturing real Tokyo microstructure.")
    elif tm > tl > ta:
        print("  -> Monotonic decline (fine with Tokyo winding down, no lunch lull visible).")
    else:
        print("  -> No visible lunch lull. Metric may be flat across Asian window.")


if __name__ == "__main__":
    main()
