"""
ATR_PCTL_14 real-data sanity check (GBPUSD + USDJPY deep caches).

Same structure as check_bb_width_pctl_usdjpy_sessions.py but for the
576-bar ATR percentile.

Expectations from the spec:
  1. Warmup cliff: first valid at row 575 (ATR finite from row 0 via
     Wilder RMA min_periods=1; then rolling(576, min_periods=576) needs
     576 non-NaN inputs).
  2. Distribution: rolling-percentile-on-autocorrelated-series produces
     the same mild U-shape as BB_WIDTH_PCTL. Fail threshold: tails
     (<20 or >80) >60% of values. Expect pass but with slightly more
     tail concentration than BB_WIDTH_PCTL because the 576-bar window
     spans all three sessions (session-mixing effect).
  3. Session means: GBPUSD Asian should be LOWER than London/NY (quieter
     session → lower ATR → lower percentile). USDJPY may show
     Tokyo-session ATR elevation mirroring BB_WIDTH_PCTL finding.
  4. Cross-pair isolation: per-pair rolling windows — |GBPUSD - USDJPY|
     should not be trivially close (no shared-window leakage).
  5. Known-dead window: 21:00-23:00 UTC should be at the low end.
"""
from pathlib import Path
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from indicators import add_indicators  # noqa: E402

PAIRS = [
    ("GBPUSD", "/opt/tradingbot/cache/GBPUSD_candles_deep.csv"),
    ("USDJPY", "/opt/tradingbot/cache/USDJPY_candles_deep.csv"),
]
COL = "ATR_PCTL_14"


def load_enriched(path: str, caller: str) -> pd.DataFrame:
    df = pd.read_csv(path, parse_dates=["timestamp"]).sort_values("timestamp")
    enr = add_indicators(df.reset_index(drop=True), caller=caller)
    enr.index = df["timestamp"].values
    return enr


def run_pair(pair: str, path: str) -> pd.DataFrame:
    enr = load_enriched(path, f"atr_pctl_check_{pair}")
    assert COL in enr.columns, f"{COL} not emitted for {pair}"

    print(f"\n=============== {pair} ===============")
    print(f"rows: {len(enr)}  range: {enr.index.min()} -> {enr.index.max()}")

    first_valid_idx = enr[COL].first_valid_index()
    first_valid_pos = list(enr.index).index(first_valid_idx)
    nan_head_ok = enr[COL].iloc[:first_valid_pos].isna().all()
    print(f"first_valid: row {first_valid_pos} ({first_valid_idx})  "
          f"head all-NaN: {nan_head_ok}  (expected: row 575)")

    valid = enr[COL].dropna()
    print(f"valid rows: {len(valid)}")
    print(f"min={valid.min():.2f}  median={valid.median():.2f}  max={valid.max():.2f}")

    lo = (valid < 20).sum() / len(valid) * 100.0
    hi = (valid > 80).sum() / len(valid) * 100.0
    tails = lo + hi
    verdict = "pass" if tails <= 60 else "FAIL"
    print(f"tail concentration:  <20 = {lo:.1f}%  >80 = {hi:.1f}%  "
          f"total = {tails:.1f}%  → {verdict} (threshold 60%)")

    hour = pd.Series(enr.index).dt.hour.values
    enr = enr.assign(_hour=hour)
    session_windows = [
        ("Asian       00:00-06:00", list(range(0, 7))),
        ("London      07:00-12:00", list(range(7, 13))),
        ("NY          13:00-17:00", list(range(13, 18))),
        ("Dead        21:00-23:00", [21, 22]),
    ]
    print(f"\nSession means ({COL}):")
    for label, hours in session_windows:
        sub = enr.loc[enr["_hour"].isin(hours), COL].dropna()
        if len(sub) == 0:
            print(f"  {label:<26} (empty)")
            continue
        print(f"  {label:<26} n={len(sub):>5d} mean={sub.mean():.2f} "
              f"median={sub.median():.2f}")

    return enr[[COL]].rename(columns={COL: pair})


def main() -> None:
    by_pair = {}
    for pair, path in PAIRS:
        if not Path(path).exists():
            print(f"SKIP {pair}: {path} missing")
            continue
        by_pair[pair] = run_pair(pair, path)

    if len(by_pair) == 2:
        joined = pd.concat(by_pair.values(), axis=1, join="inner").dropna()
        diff = (joined["GBPUSD"] - joined["USDJPY"]).abs()
        print(f"\n=============== cross-pair isolation ===============")
        print(f"overlap rows: {len(joined)}")
        print(f"|GBPUSD - USDJPY| ATR_PCTL: "
              f"mean={diff.mean():.2f}  median={diff.median():.2f}  "
              f"max={diff.max():.2f}")
        if diff.mean() > 10:
            print("  -> Per-pair rolling windows are isolated — no leakage.")
        else:
            print("  -> SUSPICIOUS: pairs track too closely, investigate.")


if __name__ == "__main__":
    main()
