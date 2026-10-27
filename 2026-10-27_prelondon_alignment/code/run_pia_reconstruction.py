"""
PIA-First 2026-10-26 reconstruction.

At 05:57 UK (= 05:57 UTC since UK is on GMT after 2026-10-25), compute the
alignment state and run every forecaster model. Compare predicted zones to
the PIA 1.3320 target. Verify intraday low from source candles.
"""
from __future__ import annotations

from datetime import date
import pandas as pd
import numpy as np

from data_loader import load_m5, resample_ohlc
from direction import (
    classify_ema_direction, classify_macd_m5, alignment_state,
)
from features import uk_to_utc

AS_OF_UTC = pd.Timestamp("2026-10-26T05:57:00+00:00")
TARGET_PRICE = 13320.0   # 1.3320 pip-scale
PIA_SL = 13295.0; PIA_TP = 13420.0


def _last_bar_before(df, as_of):
    ts = df["timestamp"].values.astype("datetime64[ns]")
    i = int(np.searchsorted(ts, as_of.to_datetime64(), side="left")) - 1
    return i


def main():
    # Load last 60 days + today
    m5 = load_m5(date(2026, 9, 1), date(2026, 10, 27))
    # Truncate m5 to the last completed bar at 05:50 UTC (bar closed at 05:55, so last completed 05:50-05:55 bar)
    cutoff_m5 = pd.Timestamp("2026-10-26T05:50:00+00:00")
    m5_pit = m5[m5["timestamp"] <= cutoff_m5].reset_index(drop=True)
    print(f"M5 bars (pre-truncation): {len(m5):,}  pit cutoff: {cutoff_m5}  M5 bars for PIT: {len(m5_pit):,}")

    h1 = resample_ohlc(m5_pit, "1h")
    h4 = resample_ohlc(m5_pit, "4h")

    # Classify
    m5_cls = classify_macd_m5(m5_pit)
    h1_cls = classify_ema_direction(h1, ema_fast=20, ema_slow=50)
    h4_cls = classify_ema_direction(h4, ema_fast=20, ema_slow=50)

    i_m5 = _last_bar_before(m5_cls, AS_OF_UTC)
    i_h1 = _last_bar_before(h1_cls, AS_OF_UTC)
    i_h4 = _last_bar_before(h4_cls, AS_OF_UTC)

    spot = float(m5_pit.at[i_m5, "close"])
    m5_dir = m5_cls.at[i_m5, "direction"]
    m5_str = float(m5_cls.at[i_m5, "strength"])
    h1_dir = h1_cls.at[i_h1, "direction"]
    h1_str = float(h1_cls.at[i_h1, "strength"])
    h4_dir = h4_cls.at[i_h4, "direction"]
    h4_str = float(h4_cls.at[i_h4, "strength"])
    align = alignment_state(h4_dir, h1_dir, m5_dir)

    print(f"\nAt {AS_OF_UTC} (= 05:57 UK on 2026-10-26):")
    print(f"  Spot:         {spot:.2f}  ({spot/10000:.5f})")
    print(f"  H4 direction: {h4_dir}  (EMA sep {h4_str:.1f} p)")
    print(f"  H1 direction: {h1_dir}  (EMA sep {h1_str:.1f} p)")
    print(f"  M5 direction: {m5_dir}  (close-EMA20 {m5_str:.2f})")
    print(f"  Alignment:    {align}")
    print(f"  PIA target:   1.3320 = {TARGET_PRICE:.2f}  ({TARGET_PRICE - spot:+.1f} p from spot)")
    print(f"  PIA SL:       1.3295 = {PIA_SL:.2f}  ({PIA_SL - spot:+.1f} p from spot)")
    print(f"  PIA TP:       1.3420 = {PIA_TP:.2f}  ({PIA_TP - spot:+.1f} p from spot)")

    # Verify actual intraday low on 2026-10-26 from source candles
    today_m5 = m5[(m5["timestamp"] >= pd.Timestamp("2026-10-26T05:50:00+00:00")) &
                  (m5["timestamp"] < pd.Timestamp("2026-10-27T00:00:00+00:00"))]
    actual_low = float(today_m5["low"].min())
    actual_low_time = today_m5.loc[today_m5["low"].idxmin(), "timestamp"]
    actual_high = float(today_m5["high"].max())
    actual_high_time = today_m5.loc[today_m5["high"].idxmax(), "timestamp"]
    print(f"\n2026-10-26 intraday range (05:55 UTC onwards):")
    print(f"  LOW:  {actual_low:.2f} at {actual_low_time}  (dist from 1.3320: {actual_low - TARGET_PRICE:+.1f} p)")
    print(f"  HIGH: {actual_high:.2f} at {actual_high_time}")

    # Load prior-day ATR, prev-day H/L
    hlc = m5.copy()
    hlc["date"] = hlc["timestamp"].dt.date
    daily = hlc.groupby("date").agg(h=("high","max"), l=("low","min"),
                                     c=("close","last"), o=("open","first")).reset_index()
    daily = daily.sort_values("date").reset_index(drop=True)
    # Prior UTC day = 2026-10-23 (Friday); 10-25 and 10-26 may have Sun data but Sunday is thin
    today = date(2026, 10, 26)
    prev_date = None
    for i in range(1, 5):
        pd_ = pd.Timestamp(today) - pd.Timedelta(days=i)
        pd_d = pd_.date()
        if pd_d in daily["date"].values:
            prev_date = pd_d
            break
    prev_row = daily[daily["date"] == prev_date].iloc[0] if prev_date else None
    print(f"\nPrev day for pivots: {prev_date} (H={prev_row['h']:.2f}, L={prev_row['l']:.2f}, C={prev_row['c']:.2f})")
    H, L, C = prev_row["h"], prev_row["l"], prev_row["c"]
    P = (H + L + C) / 3.0
    S1 = 2 * P - H; R1 = 2 * P - L
    print(f"  PP={P:.2f}  S1={S1:.2f}  R1={R1:.2f}  (S1 dist from 1.3320 = {S1-TARGET_PRICE:+.1f} p)")

    # ATR20 (prior 20 days)
    prior = daily[daily["date"] < today].tail(20)
    atr20 = float((prior["h"] - prior["l"]).mean())
    print(f"  ATR20: {atr20:.1f} p")

    # Run model forecasts
    FIXED = 30.0
    ADR_HALF = atr20 * 0.5
    ATR_HALF = atr20 * 0.5
    # G alignment uses TRAIN medians — load from model_scores.csv groupby alignment
    scores = pd.read_csv("/home/autobot/research/gbpusd_prelondon_20261027/data_out/model_scores.csv")
    # Train subset
    tr_feats = pd.read_csv("/home/autobot/research/gbpusd_prelondon_20261027/data_out/features.csv")
    tr_wins = pd.read_csv("/home/autobot/research/gbpusd_prelondon_20261027/data_out/window_movements.csv")
    tr_feats["date"] = pd.to_datetime(tr_feats["date"]).dt.date
    tr_wins["date"] = pd.to_datetime(tr_wins["date"]).dt.date
    tr_feats = tr_feats[tr_feats["uk_hour"] == 6]
    train_dates = tr_feats[tr_feats["date"] < date(2025, 7, 1)]["date"].values
    # Build mfu/mfd aggregates
    agg_rows = []
    for d, g in tr_wins[tr_wins["ref_uk_hour"] == 6].groupby("date"):
        hi = g["high"].max(); lo = g["low"].min()
        ref = g.loc[g["window"] == "EARLY_LONDON", "ref_price"].iloc[0] if (g["window"] == "EARLY_LONDON").any() else None
        if ref: agg_rows.append(dict(date=d, mfu=hi-ref, mfd=ref-lo))
    agg = pd.DataFrame(agg_rows)
    agg = agg[agg["date"].isin(train_dates)]
    f = tr_feats[tr_feats["date"].isin(train_dates)][["date","alignment"]]
    j = agg.merge(f, on="date")
    align_meds = j.groupby("alignment").agg(mfu_med=("mfu","median"), mfd_med=("mfd","median"), n=("date","size"))
    unconditional_mfu = float(j["mfu"].median())
    unconditional_mfd = float(j["mfd"].median())
    print(f"\nTRAIN medians: unconditional mfu={unconditional_mfu:.1f}, mfd={unconditional_mfd:.1f}")
    if align in align_meds.index:
        g_mfu = float(align_meds.loc[align, "mfu_med"])
        g_mfd = float(align_meds.loc[align, "mfd_med"])
    else:
        g_mfu, g_mfd = unconditional_mfu, unconditional_mfd
    print(f"  TRAIN medians for alignment {align}: mfu={g_mfu:.1f}, mfd={g_mfd:.1f}")

    print("\n--- Forecaster predictions at 05:57 UK ---")
    predictions = [
        ("A_fixed_30p",     spot - FIXED,     spot + FIXED),
        ("B_adr20_half",    spot - ADR_HALF,  spot + ADR_HALF),
        ("C_atr_half",      spot - ATR_HALF,  spot + ATR_HALF),
        ("D_prev_HL",       L,                H),
        ("E_pivot_S1R1",    S1,               R1),
        ("F_unconditional", spot - unconditional_mfd, spot + unconditional_mfu),
        ("G_alignment",     spot - g_mfd,     spot + g_mfu),
    ]
    rows_out = []
    for name, buy_mid, sell_mid in predictions:
        dist_from_target_buy = buy_mid - TARGET_PRICE
        print(f"  {name:>18s}  BUY zone {buy_mid-5:.2f}-{buy_mid+5:.2f}  mid {buy_mid:.2f}  "
              f"(dist from 1.3320: {dist_from_target_buy:+.1f} p)  "
              f"SELL zone {sell_mid-5:.2f}-{sell_mid+5:.2f}")
        rows_out.append(dict(model=name, buy_mid=buy_mid, sell_mid=sell_mid,
                              buy_dist_from_pia=dist_from_target_buy,
                              buy_approached=actual_low <= buy_mid + 5,
                              buy_bounce=max(0.0, actual_high - buy_mid) if actual_low <= buy_mid + 5 else float("nan")))
    pd.DataFrame(rows_out).to_csv("/home/autobot/research/gbpusd_prelondon_20261027/data_out/pia_reconstruction.csv", index=False)
    print("\n  wrote pia_reconstruction.csv")


if __name__ == "__main__":
    main()
