"""
Combined evaluation: BB Bounce × S1/R1 permission × predicted-zone activation.

For each BB-bounce signal, we tag whether:
  - it is PERMITTED by the S1/R1 rule (Investigation A)
  - it fires WITHIN an active predicted BUY/SELL zone's "activation band"
    (configurable: 5, 10, 15, 20, 30 pips tolerance from the zone)

Then we compare four configurations as per spec § 9:
  A — baseline (no filter, no zone)
  B — S1/R1 only
  C — zone-gated only (BB_BOUNCE direction aligned with zone, price within
      the activation band of the zone's center)
  D — both filters combined

Zones used: whichever forecaster model is being studied. The spec implies
one model per combined analysis. We'll report D for each model separately.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

OUT = Path("/home/autobot/research/gbpusd_bb_bounce_20261027/data_out")

PRIMARY_SL = 20.0
PRIMARY_TP = 30.0
ACTIVATION_BANDS_PIPS = [5.0, 10.0, 15.0, 20.0, 30.0]


def metrics(trades: pd.DataFrame, pnl_col: str) -> dict:
    if len(trades) == 0:
        return dict(n=0, wins=0, losses=0, win_rate=float("nan"),
                    net_pips=0.0, profit_factor=float("nan"),
                    avg_pips=float("nan"), max_dd=float("nan"))
    oc_col = pnl_col.replace("pnl_pips_", "outcome_")
    pnl = trades[pnl_col].values
    wins = (trades[oc_col] == "WIN").sum()
    losses = (trades[oc_col] == "LOSS").sum()
    gross_p = pnl[pnl > 0].sum(); gross_l = -pnl[pnl < 0].sum()
    equity = np.cumsum(pnl)
    peak = np.maximum.accumulate(equity)
    dd = (equity - peak).min() if len(equity) else 0.0
    return dict(
        n=int(len(trades)), wins=int(wins), losses=int(losses),
        win_rate=float(wins / len(trades)),
        net_pips=float(pnl.sum()),
        profit_factor=float(gross_p / gross_l) if gross_l else float("inf"),
        avg_pips=float(np.mean(pnl)),
        max_dd=float(dd),
    )


def tag_zone_activation(sig: pd.DataFrame, forecasts: pd.DataFrame,
                        model: str, activation_pips: float) -> pd.Series:
    """Return a boolean series: did the BB-bounce fire within `activation_pips`
    of ANY same-direction forecast zone that was active for that fire time?

    A zone is "active" from prediction_time up to 288 bars (24 h) OR until a
    new prediction_time for the same model.
    """
    fcast = forecasts[forecasts["model"] == model].copy()
    fcast["prediction_time"] = pd.to_datetime(fcast["prediction_time"], utc=True)
    fcast["date"] = pd.to_datetime(fcast["date"]).dt.date
    # Direction alignment: BB-bounce LONG ↔ zone BUY; SHORT ↔ SELL
    buy_zones = fcast[fcast["direction"] == "BUY"][["prediction_time", "date", "zone_lo", "zone_hi", "zone_mid"]].rename(columns={"zone_mid": "mid"}).reset_index(drop=True)
    sell_zones = fcast[fcast["direction"] == "SELL"][["prediction_time", "date", "zone_lo", "zone_hi", "zone_mid"]].rename(columns={"zone_mid": "mid"}).reset_index(drop=True)
    buy_by_date = {d: g for d, g in buy_zones.groupby("date")}
    sell_by_date = {d: g for d, g in sell_zones.groupby("date")}

    out = []
    for _, s in sig.iterrows():
        d = s["fire_time"].date()
        px = s["fire_bar_close"]
        if s["direction"] == "LONG":
            g = buy_by_date.get(d)
        else:
            g = sell_by_date.get(d)
        if g is None:
            out.append(False); continue
        # Any zone whose mid is within activation_pips of px
        if (abs(g["mid"] - px) <= activation_pips).any():
            out.append(True)
        else:
            out.append(False)
    return pd.Series(out, index=sig.index)


def main():
    sig = pd.read_csv(OUT / "signals_with_outcomes.csv")
    sig["fire_time"] = pd.to_datetime(sig["fire_time"], utc=True)
    sig["setup_time"] = pd.to_datetime(sig["setup_time"], utc=True)
    fcast = pd.read_csv(OUT / "forecasts_with_outcomes.csv")
    print(f"BB signals: {len(sig):,}  forecasts: {len(fcast):,}")

    pnl_col = f"pnl_pips_sl{int(PRIMARY_SL)}_tp{int(PRIMARY_TP)}"
    rows = []
    for model in ("M1_pivots", "M2_swings", "M3_prev_hl", "M4_baseline"):
        for band in ACTIVATION_BANDS_PIPS:
            active = tag_zone_activation(sig, fcast, model, band)
            sig_m = sig.assign(zone_active=active)
            for split in ("TRAIN", "VAL", "TEST", "ALL"):
                df = sig_m if split == "ALL" else sig_m[sig_m["split"] == split]
                config_A = df
                config_B = df[df["s1r1_decision"] != "BLOCK"]
                config_C = df[df["zone_active"]]
                config_D = df[(df["s1r1_decision"] != "BLOCK") & (df["zone_active"])]
                for label, sub in [("A_baseline", config_A), ("B_s1r1", config_B),
                                   (f"C_zone_{model}_{int(band)}p", config_C),
                                   (f"D_both_{model}_{int(band)}p", config_D)]:
                    m = metrics(sub, pnl_col)
                    m.update(model=model, activation_band=band, split=split,
                             config=label)
                    rows.append(m)
    out = pd.DataFrame(rows)
    out.to_csv(OUT / "combined_metrics.csv", index=False)
    print(f"  wrote combined_metrics.csv ({len(out):,} rows)")

    # Print the headline table for ALL split
    pd.set_option('display.width', 220); pd.set_option('display.max_columns', 20); pd.set_option('display.precision', 2)
    headline = out[(out["split"] == "ALL") & (out["activation_band"] == 10.0) &
                   ((out["config"].str.startswith("C_zone_")) |
                    (out["config"].str.startswith("D_both_")) |
                    (out["config"].isin(["A_baseline", "B_s1r1"])))]
    headline = headline.drop_duplicates(subset=["config"])[["config", "n", "wins", "losses", "win_rate", "net_pips", "profit_factor", "max_dd"]]
    print("\n=== Combined (ALL split, band=10p where applicable) ===")
    print(headline.to_string(index=False))


if __name__ == "__main__":
    main()
