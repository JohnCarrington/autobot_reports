"""
BB_MID_SLOPE_5_20 real-data sanity check (GBPUSD + USDJPY deep caches).

Expectations from the spec:
  1. Distribution ~symmetric around zero. Sharp long-run skew -> sign error
     or unit drift.
  2. Magnitude scale: USDJPY ~0.01/bar (IG points), GBPUSD ~0.0001/bar.
     Don't compare magnitudes cross-pair, only within pair.
  3. Trending-session sign-hold: within a clean directional run, sign should
     stay consistent over 5-10 bars. Frequent flips inside a clear trend
     mean the lookback is too noisy.
  4. Warmup: first 24 bars (19-bar BB mid warmup + 5-bar diff) must be NaN.
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


def run_pair(pair: str, path: str) -> pd.DataFrame:
    df = pd.read_csv(path, parse_dates=["timestamp"])
    df = df.set_index("timestamp").sort_index()

    enr = add_indicators(df.reset_index(), caller=f"bb_mid_slope_5_check_{pair}")
    enr["timestamp"] = df.index
    enr = enr.set_index("timestamp")

    col = "BB_MID_SLOPE_5_20"
    sibling = "BB_MID_SLOPE_20"
    assert col in enr.columns, f"{col} not emitted"
    assert sibling in enr.columns, f"{sibling} should still exist"

    print(f"\n=============== {pair} ===============")
    print(f"rows: {len(enr)}  range: {enr.index.min()} -> {enr.index.max()}")

    # --- Warmup cliff ----------------------------------------------------
    first_valid = enr[col].first_valid_index()
    first_valid_pos = enr.index.get_loc(first_valid)
    nan_head = enr[col].iloc[:first_valid_pos].isna().all()
    print(f"first_valid_idx: row {first_valid_pos} ({first_valid})  "
          f"head all-NaN: {nan_head}  (expected: 24 warmup bars)")

    valid = enr[col].dropna()

    # --- Distribution ----------------------------------------------------
    desc = valid.describe(percentiles=[0.01, 0.1, 0.5, 0.9, 0.99])
    print(f"\ndistribution (n={len(valid)}):")
    print(f"  min={desc['min']:+.6f}  max={desc['max']:+.6f}")
    print(f"  p01={desc['1%']:+.6f}  p99={desc['99%']:+.6f}")
    print(f"  p10={desc['10%']:+.6f}  p90={desc['90%']:+.6f}")
    print(f"  mean={valid.mean():+.6f}  median={valid.median():+.6f}")
    print(f"  std ={valid.std():.6f}")

    pos = (valid > 0).sum()
    neg = (valid < 0).sum()
    zero = (valid == 0).sum()
    total = len(valid)
    print(f"\nsign balance:")
    print(f"  positive: {pos:>5d} ({100*pos/total:.1f}%)")
    print(f"  negative: {neg:>5d} ({100*neg/total:.1f}%)")
    print(f"  zero    : {zero:>5d} ({100*zero/total:.1f}%)")
    skew_pct = abs(100*pos/total - 100*neg/total)
    if skew_pct > 15:
        print(f"  -> SUSPICIOUS: sign skew {skew_pct:.1f} pp > 15 pp threshold")
    else:
        print(f"  -> Symmetric-ish: sign skew {skew_pct:.1f} pp <= 15 pp")

    # --- Magnitude scale check -------------------------------------------
    median_abs = valid.abs().median()
    print(f"\nmedian |slope|: {median_abs:.6f} (pair-specific, do NOT "
          f"cross-compare magnitudes)")

    # --- Relation to the 1-bar sibling -----------------------------------
    sibling_series = enr[sibling].dropna()
    joint = pd.concat([valid, sibling_series], axis=1, join="inner")
    joint.columns = ["slope5", "slope1"]
    corr = joint["slope5"].corr(joint["slope1"])
    print(f"\ncorrelation with 1-bar BB_MID_SLOPE_20: {corr:+.3f}  "
          f"(expected strong positive, <1)")
    slope5_abs_std = joint["slope5"].std()
    slope1_abs_std = joint["slope1"].std()
    print(f"std ratio slope5/slope1: {slope5_abs_std/slope1_abs_std:.3f}  "
          f"(expected <1: 5-bar smoothing reduces noise)")

    # --- Sign-hold inside a clean trend ----------------------------------
    # Find the longest single-direction window in the raw close series and
    # check whether BB_MID_SLOPE_5_20 holds sign across it.
    close = enr["close"].astype(float)
    ret = close.diff()
    # Longest run of same-sign returns as a proxy for "clean trend".
    sign = np.sign(ret).fillna(0).astype(int)
    best_start, best_len, best_sign = 0, 0, 0
    cur_start, cur_len, cur_sign = 0, 0, 0
    for i, s in enumerate(sign.values):
        if s != 0 and s == cur_sign:
            cur_len += 1
        else:
            if cur_len > best_len and cur_sign != 0:
                best_start, best_len, best_sign = cur_start, cur_len, cur_sign
            cur_start, cur_len, cur_sign = i, 1, s
    if cur_len > best_len and cur_sign != 0:
        best_start, best_len, best_sign = cur_start, cur_len, cur_sign

    window = enr.iloc[best_start:best_start + best_len]
    slope_in_run = window[col].dropna()
    if len(slope_in_run) > 0:
        run_pos = (slope_in_run > 0).sum()
        run_neg = (slope_in_run < 0).sum()
        hold_pct = 100 * max(run_pos, run_neg) / len(slope_in_run)
        print(f"\nlongest clean-trend run: {best_len} bars, "
              f"close-return sign={best_sign:+d}")
        print(f"  BB_MID_SLOPE_5_20 sign inside run: "
              f"{run_pos} pos / {run_neg} neg ({hold_pct:.0f}% same-sign)")
        if hold_pct < 70:
            print(f"  -> NOISY: <70% same-sign hold inside a clean run")
        else:
            print(f"  -> Good sign-hold within trend")

    return valid


def main() -> None:
    for pair, path in PAIRS:
        if not Path(path).exists():
            print(f"SKIP {pair}: {path} missing")
            continue
        run_pair(pair, path)


if __name__ == "__main__":
    main()
