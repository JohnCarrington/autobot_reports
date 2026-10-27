"""
BB Bounce × alignment-context integration.

Reuse the BB Bounce signals + outcomes CSV from the prior study:
  /home/autobot/research/gbpusd_bb_bounce_20261027/data_out/signals_with_outcomes.csv

For each BB-bounce fire, attach the alignment state from the most recent
pre-fire UK-hour snapshot (05/06/07/08/10/12/13/14 UK).

Compare four configurations:
  CFG1 — baseline (no filter)
  CFG2 — alignment-aligned: allow LONG when expectation is BUY (H4 bull +
         correction setup); allow SHORT when expectation is SELL.
  CFG3 — H4-aligned: BB LONG only on H4 bullish days; BB SHORT only on H4 bearish days.
  CFG4 — alignment + half-rule S1 (block SHORT below S1, from prior study).
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

OUT = Path("/home/autobot/research/gbpusd_prelondon_20261027/data_out")
PRIOR = Path("/home/autobot/research/gbpusd_bb_bounce_20261027/data_out")

PRIMARY = ("sl20_tp30", 20.0, 30.0)


def _attach_alignment(signals: pd.DataFrame, features: pd.DataFrame) -> pd.DataFrame:
    """For each signal, find the latest feature snapshot BEFORE fire_time."""
    sig = signals.copy()
    sig["fire_time"] = pd.to_datetime(sig["fire_time"], utc=True)
    feats = features.copy()
    feats["snapshot_utc"] = pd.to_datetime(feats["snapshot_utc"], utc=True)
    feats = feats.sort_values("snapshot_utc").reset_index(drop=True)

    # merge_asof backward join
    sig = sig.sort_values("fire_time").reset_index(drop=True)
    out = pd.merge_asof(
        sig, feats[["snapshot_utc","alignment","h4_dir","h1_dir","m5_dir","spot"]],
        left_on="fire_time", right_on="snapshot_utc",
        direction="backward",
    )
    return out


def _metrics(df, pnl_col):
    if len(df) == 0:
        return dict(n=0, wins=0, losses=0, win_rate=float("nan"),
                     net_pips=0.0, pf=float("nan"), dd=float("nan"))
    pnl = df[pnl_col].values
    oc = df[pnl_col.replace("pnl_pips_","outcome_")]
    wins = int((oc == "WIN").sum()); losses = int((oc == "LOSS").sum())
    gp = pnl[pnl > 0].sum(); gl = -pnl[pnl < 0].sum()
    eq = np.cumsum(pnl); peak = np.maximum.accumulate(eq)
    dd = float((eq - peak).min()) if len(eq) else 0.0
    return dict(n=int(len(df)), wins=wins, losses=losses,
                 win_rate=float(wins/len(df)),
                 net_pips=float(pnl.sum()),
                 pf=float(gp/gl) if gl > 0 else float("inf"),
                 dd=dd)


# Alignment expected direction: when alignment implies a reversal direction
EXPECTED_DIR = {
    "H4H1BULL_M5BEAR": "LONG",   # bullish correction → next bounce is BUY (= BB LONG)
    "H4BULL_H1M5BEAR": "LONG",
    "H4BULL_H1BEAR_M5BULL": "LONG",
    "H4H1BEAR_M5BULL": "SHORT",  # bearish correction → next bounce is SELL
    "H4BEAR_H1M5BULL": "SHORT",
    "H4BEAR_H1BULL_M5BEAR": "SHORT",
    "ALL_BULL": "LONG",          # continuation (both directions ok but allow with-trend)
    "ALL_BEAR": "SHORT",
}


def main():
    sig = pd.read_csv(PRIOR / "signals_with_outcomes.csv")
    print(f"BB signals from prior study: {len(sig):,}")
    feats = pd.read_csv(OUT / "features.csv")
    sig = _attach_alignment(sig, feats)
    print(f"After alignment attach: {len(sig):,}")
    print(f"  alignment counts: {sig['alignment'].value_counts().to_dict()}")

    sig["split"] = sig["fire_time"].apply(
        lambda t: "TRAIN" if pd.Timestamp(t) < pd.Timestamp("2025-07-01", tz="UTC")
        else ("VAL" if pd.Timestamp(t) < pd.Timestamp("2026-03-01", tz="UTC") else "TEST")
    )

    pnl_col = "pnl_pips_sl20_tp30"
    rows = []
    for split in ("TRAIN", "VAL", "TEST", "ALL"):
        d = sig if split == "ALL" else sig[sig["split"] == split]
        # CFG1 baseline
        rows.append(dict(config="CFG1_baseline", split=split, **_metrics(d, pnl_col)))
        # CFG2 alignment-aligned
        def allowed_cfg2(row):
            exp = EXPECTED_DIR.get(row["alignment"])
            if exp is None: return True   # permit when alignment is unmapped (MIXED)
            return row["direction"] == exp
        cfg2 = d[d.apply(allowed_cfg2, axis=1)]
        rows.append(dict(config="CFG2_alignment", split=split, **_metrics(cfg2, pnl_col)))
        # CFG3 H4-aligned
        def allowed_cfg3(row):
            if row["h4_dir"] == "BULLISH" and row["direction"] == "LONG": return True
            if row["h4_dir"] == "BEARISH" and row["direction"] == "SHORT": return True
            return False
        cfg3 = d[d.apply(allowed_cfg3, axis=1)]
        rows.append(dict(config="CFG3_h4_aligned", split=split, **_metrics(cfg3, pnl_col)))
        # CFG4 alignment + half-rule S1
        def allowed_cfg4(row):
            if not allowed_cfg2(row): return False
            if pd.isna(row.get("S1")): return True
            if row["direction"] == "SHORT" and row["fire_bar_close"] < row["S1"]: return False
            return True
        cfg4 = d[d.apply(allowed_cfg4, axis=1)]
        rows.append(dict(config="CFG4_align_plus_half", split=split, **_metrics(cfg4, pnl_col)))
    out = pd.DataFrame(rows)
    out.to_csv(OUT / "bb_integration_metrics.csv", index=False)
    print(f"  wrote bb_integration_metrics.csv ({len(out)} rows)")
    pd.set_option("display.width", 220); pd.set_option("display.max_columns", 20); pd.set_option("display.precision", 2)
    print(out.to_string(index=False))


if __name__ == "__main__":
    main()
