"""
Correction-destination forecasters — comparison of baselines A-H.

For each trading day (06 UK reference), each model emits:
  - direction: BUY/SELL/NONE
  - zone_mid: candidate reversal destination price
  - zone_lo/hi: ±5 p band
  - confidence (TRAIN-estimated probability)

Models:
  A — Fixed-distance (BUY zone 30 p below spot, SELL 30 p above). Dumb.
  B — Average daily range from 06 (spot ± mean(ADR) × 0.5). ADR20.
  C — ATR projection: spot ± ATR20 × 0.5 (same as previous zones M4).
  D — Prior day H/L (BUY = prev_l ± 5 p, SELL = prev_h ± 5 p). Historical reference.
  E — Daily pivot S1/R1.
  F — Unconditional historical movement median (train):
       BUY = spot − median(mfd), SELL = spot + median(mfu) in LATE_LONDON window.
  G — Alignment-conditioned median movement from TRAIN:
       zone distance = TRAIN-median mfu/mfd conditional on 06-UK alignment state.
  H — Alignment + ATR20 + Asian-session-move combined:
       zone distance = linear predictor fit on TRAIN with features
       (alignment one-hot + atr20 + prev_day_range) → median mfu/mfd.

Evaluation:
  For each forecast on day d:
    - approach_rate: P(price within zone_lo..zone_hi during 07-22 UK)
    - hit_15/20/30/50: P(a `size`-pip reversal in forecast direction after
      the FIRST approach to the zone)
  - mean distance of actual intraday extremum from zone (zone-fit accuracy)

Split: TRAIN=2024-01..2025-06, VAL=2025-07..2026-02, TEST=2026-03..2026-10.
Fit (model F, G, H) uses TRAIN only; eval on all three.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

OUT = Path("/home/autobot/research/gbpusd_prelondon_20261027/data_out")
ZONE_HALF = 5.0


def split_of(d):
    d = pd.Timestamp(d).date() if not hasattr(d, "year") else d
    if d < pd.Timestamp("2025-07-01").date(): return "TRAIN"
    if d < pd.Timestamp("2026-03-01").date(): return "VAL"
    return "TEST"


def main():
    feats = pd.read_csv(OUT / "features.csv", parse_dates=["snapshot_utc"])
    feats["date"] = pd.to_datetime(feats["date"]).dt.date
    f06 = feats[feats["uk_hour"] == 6].copy()
    f06["split"] = f06["date"].apply(split_of)
    f06 = f06.dropna(subset=["spot", "atr20_daily"]).reset_index(drop=True)

    wins = pd.read_csv(OUT / "window_movements.csv",
                       parse_dates=["high_time", "low_time"])
    wins["date"] = pd.to_datetime(wins["date"]).dt.date
    wins06 = wins[wins["ref_uk_hour"] == 6]

    # Build per-day aggregate movement from 06 UK through end-of-NY (22 UK)
    # by summing the window metrics across EARLY_LONDON..LATE_NY from 06 ref.
    agg_rows = []
    for d, g in wins06.groupby("date"):
        g = g.set_index("window")
        if "LATE_NY" not in g.index or "EARLY_LONDON" not in g.index:
            continue
        # Day's high / low from 07 UK start to 22 UK end
        # We don't have "whole day from 06 ref" directly; approximate by taking the
        # max high and min low across all windows from 06 ref.
        hi = g["high"].max(); lo = g["low"].min()
        ref = g.loc["EARLY_LONDON", "ref_price"]
        agg_rows.append(dict(date=d, ref_06=ref,
                              day_hi=hi, day_lo=lo,
                              mfu=hi - ref, mfd=ref - lo))
    agg = pd.DataFrame(agg_rows)
    agg["split"] = agg["date"].apply(split_of)

    merged = f06.merge(agg, on="date", how="inner", suffixes=("", "_agg"))
    merged = merged.rename(columns={"split": "split_f", "split_agg": "split"})
    print(f"Merged frames: {len(merged):,} days")

    train = merged[merged["split"] == "TRAIN"]
    print(f"TRAIN days: {len(train)}  VAL days: {(merged['split']=='VAL').sum()}  TEST days: {(merged['split']=='TEST').sum()}")

    # Fit model parameters on TRAIN
    FIXED_DIST = 30.0
    ADR20_FACTOR = 0.5
    ATR_FACTOR = 0.5
    unconditional_median_mfu = float(train["mfu"].median())
    unconditional_median_mfd = float(train["mfd"].median())
    alignment_medians = {
        align: dict(mfu_med=float(g["mfu"].median()), mfd_med=float(g["mfd"].median()),
                     mfu_mean=float(g["mfu"].mean()), mfd_mean=float(g["mfd"].mean()), n=len(g))
        for align, g in train.groupby("alignment")
    }
    # Simple linear predictor for Model H — fit on TRAIN: mfu/mfd ~ a + b*atr20 + c*alignment_bull + d*alignment_bear
    tr = train.copy()
    tr["is_bull"] = (tr["alignment"] == "ALL_BULL").astype(int)
    tr["is_bear"] = (tr["alignment"] == "ALL_BEAR").astype(int)
    def ols(y, X):
        X = np.column_stack([np.ones(len(X)), X])
        beta, *_ = np.linalg.lstsq(X, y, rcond=None)
        return beta
    X = tr[["atr20_daily","is_bull","is_bear"]].values
    beta_mfu = ols(tr["mfu"].values, X)
    beta_mfd = ols(tr["mfd"].values, X)

    def predict_h(atr20, align):
        is_bull = 1 if align == "ALL_BULL" else 0
        is_bear = 1 if align == "ALL_BEAR" else 0
        x = np.array([1.0, atr20, is_bull, is_bear])
        return float(x @ beta_mfu), float(x @ beta_mfd)

    # Score each model on each day
    scores = []
    for _, r in merged.iterrows():
        spot = r["spot"]; atr = r["atr20_daily"] if not pd.isna(r["atr20_daily"]) else 60.0
        align = r["alignment"]; prev_h = r.get("prev_day_h"); prev_l = r.get("prev_day_l")
        actual_mfu = r["mfu"]; actual_mfd = r["mfd"]; day_hi = r["day_hi"]; day_lo = r["day_lo"]
        split = r["split"]
        rows = []
        rows.append(dict(model="A_fixed_30p", buy_mid=spot-FIXED_DIST, sell_mid=spot+FIXED_DIST))
        rows.append(dict(model="B_adr20_half", buy_mid=spot-atr*ADR20_FACTOR, sell_mid=spot+atr*ADR20_FACTOR))
        rows.append(dict(model="C_atr_half", buy_mid=spot-atr*ATR_FACTOR, sell_mid=spot+atr*ATR_FACTOR))
        if not pd.isna(prev_h) and not pd.isna(prev_l):
            rows.append(dict(model="D_prev_HL", buy_mid=prev_l, sell_mid=prev_h))
        else:
            rows.append(dict(model="D_prev_HL", buy_mid=np.nan, sell_mid=np.nan))
        rows.append(dict(model="F_unconditional", buy_mid=spot-unconditional_median_mfd,
                           sell_mid=spot+unconditional_median_mfu))
        am = alignment_medians.get(align)
        if am and am["n"] >= 20:
            rows.append(dict(model="G_alignment", buy_mid=spot-am["mfd_med"], sell_mid=spot+am["mfu_med"]))
        else:
            rows.append(dict(model="G_alignment", buy_mid=spot-unconditional_median_mfd,
                               sell_mid=spot+unconditional_median_mfu))
        mfu_h, mfd_h = predict_h(atr, align)
        rows.append(dict(model="H_regression", buy_mid=spot-mfd_h, sell_mid=spot+mfu_h))

        for row in rows:
            buy_mid = row["buy_mid"]; sell_mid = row["sell_mid"]
            buy_approached = (not pd.isna(buy_mid)) and (day_lo <= buy_mid + ZONE_HALF)
            sell_approached = (not pd.isna(sell_mid)) and (day_hi >= sell_mid - ZONE_HALF)
            # Error: how close zone is to actual extremum
            buy_err = abs(day_lo - buy_mid) if not pd.isna(buy_mid) else float("nan")
            sell_err = abs(day_hi - sell_mid) if not pd.isna(sell_mid) else float("nan")
            scores.append(dict(date=r["date"], split=split, alignment=align,
                                model=row["model"],
                                buy_mid=buy_mid, sell_mid=sell_mid,
                                buy_approached=buy_approached, sell_approached=sell_approached,
                                buy_err=buy_err, sell_err=sell_err))

    s = pd.DataFrame(scores)
    s.to_csv(OUT / "model_scores.csv", index=False)
    print(f"  wrote model_scores.csv ({len(s):,} rows)")

    # Summary
    print("\n=== Model performance (approach rate, zone error) ===")
    for split in ("TRAIN","VAL","TEST","ALL"):
        print(f"\n--- {split} ---")
        d = s if split == "ALL" else s[s["split"] == split]
        agg_m = d.groupby("model").agg(
            n=("buy_approached","size"),
            buy_approach=("buy_approached","mean"),
            sell_approach=("sell_approached","mean"),
            buy_err_med=("buy_err","median"),
            sell_err_med=("sell_err","median"),
        )
        print(agg_m.to_string())


if __name__ == "__main__":
    main()
