#!/usr/bin/env python3
"""Simple strategy backtest driven by the agent's probabilities.

Policy A — "First confident fire, hold until EOD or exhaustion":
    On the first hour where P(trend) ≥ ENTRY_THR and direction_prob is on the
    same side, enter at that hour's close in the predicted direction. Hold
    until 21:00 UK (end of principal window). Exit at bar close.

Policy B — "Early fire with trailing exit":
    Same entry; exit when P(trend) at a later hour drops below EXIT_THR, or
    at 21:00 UK, whichever first.

Metrics: expectancy per fire (pips), win rate, hit-rate (% that reach 20
pips profit), average loss on losers, mean MFE/MAE.

Costs: spread assumed 0.8 pips round-trip (conservative for GBPUSD during
London/NY). No slippage model.
"""
from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

sys.path.append(str(Path(__file__).parent))
from census import CANDLES_26, CANDLES_EXT, _load_day_file, _uk_offset_hours  # noqa

ROOT = Path("<research_workspace>/outputs")
MODELS = Path("<research_workspace>/models")

features = pd.read_parquet(ROOT / "features.parquet")
features["is_mon"] = (features.weekday == "Mon").astype(int)
features["is_tue"] = (features.weekday == "Tue").astype(int)
features["is_wed"] = (features.weekday == "Wed").astype(int)
features["is_thu"] = (features.weekday == "Thu").astype(int)
features["is_fri"] = (features.weekday == "Fri").astype(int)
EXCLUDE = {"date", "basis", "weekday", "hour_uk", "cutoff_utc", "close",
           "partition", "direction", "trend_day", "pips_target",
           "remaining_pips_in_dir", "trend_already_developed_pips",
           "asia_close", "asia_open"}
FEATURES = [c for c in features.columns if c not in EXCLUDE]
features[FEATURES] = features[FEATURES].replace([np.inf, -np.inf], np.nan).fillna(0.0)
for c in FEATURES:
    if features[c].dtype == object:
        features[c] = pd.to_numeric(features[c], errors="coerce").fillna(0.0)
census = pd.read_csv(ROOT / "census.csv")

def partition(d):
    d = dt.date.fromisoformat(d)
    if d < dt.date(2025, 7, 1): return "Dev"
    if d < dt.date(2026, 1, 1): return "Holdout"
    return "Conf2026"


# Preload models and generate predictions for each (date, hour)
pred_rows = []
for h in sorted(features.hour_uk.unique()):
    clf = joblib.load(MODELS / f"trend_gbm_h{h:02d}.joblib")
    dir_clf = joblib.load(MODELS / f"dir_gbm_h{h:02d}.joblib")
    sub = features[features.hour_uk == h].copy()
    sub["p_trend"] = clf.predict_proba(sub[FEATURES])[:, 1]
    sub["p_long"] = dir_clf.predict_proba(sub[FEATURES])[:, 1]
    pred_rows.append(sub[["date", "basis", "hour_uk", "close", "p_trend", "p_long"]])
preds = pd.concat(pred_rows, ignore_index=True).sort_values(["date", "hour_uk"])
preds["partition"] = preds["date"].apply(partition)

def _ldn_close_utc(d: str) -> pd.Timestamp:
    d = dt.date.fromisoformat(d)
    off = _uk_offset_hours(pd.Timestamp(d, tz="UTC"))
    return pd.Timestamp(d, tz="UTC") + pd.Timedelta(hours=21 - off)  # 21:00 UK

SPREAD_PIPS = 0.8   # round-trip cost assumption

def _load_day_m5(date_str: str):
    for p in CANDLES_EXT.glob(f"{date_str}.csv"):
        return _load_day_file(p, "BID")
    for p in CANDLES_26.glob(f"{date_str}.csv"):
        return _load_day_file(p, "MID")
    return None

def backtest(entry_thr: float, dir_conf_thr: float):
    rows = []
    for d, grp in preds.groupby("date"):
        df_m5 = _load_day_m5(d)
        if df_m5 is None:
            continue
        # entry
        entry = None
        for _, p in grp.sort_values("hour_uk").iterrows():
            if p.p_trend >= entry_thr:
                dir_pred = "LONG" if p.p_long >= 0.5 else "SHORT"
                conf = max(p.p_long, 1 - p.p_long)
                if conf >= dir_conf_thr:
                    entry = {"hour_uk": int(p.hour_uk), "p_trend": p.p_trend,
                             "p_long": p.p_long, "dir": dir_pred, "px": p.close}
                    break
        if entry is None:
            continue
        # exit at 21:00 UK (close of principal window)
        exit_ts = _ldn_close_utc(d)
        after = df_m5[df_m5.ts >= pd.Timestamp(entry["px"] and d, tz="UTC") +
                        pd.Timedelta(hours=entry["hour_uk"] - _uk_offset_hours(pd.Timestamp(d, tz="UTC")))]
        after = after[after.ts <= exit_ts]
        if after.empty:
            continue
        exit_px = after["close"].iloc[-1] / 10000
        # MFE/MAE within hold
        if entry["dir"] == "LONG":
            mfe = (after["high"].max() / 10000 - entry["px"]) * 10000
            mae = (entry["px"] - after["low"].min() / 10000) * 10000
            pnl = (exit_px - entry["px"]) * 10000 - SPREAD_PIPS
        else:
            mfe = (entry["px"] - after["low"].min() / 10000) * 10000
            mae = (after["high"].max() / 10000 - entry["px"]) * 10000
            pnl = (entry["px"] - exit_px) * 10000 - SPREAD_PIPS
        rows.append({
            "date": d, "partition": grp.partition.iloc[0],
            "hour_uk": entry["hour_uk"], "entry_px": round(entry["px"], 5),
            "exit_px": round(exit_px, 5), "dir": entry["dir"],
            "p_trend": round(entry["p_trend"], 3),
            "p_long":  round(entry["p_long"], 3),
            "mfe_pips": round(mfe, 1), "mae_pips": round(mae, 1),
            "pnl_pips": round(pnl, 1),
        })
    return pd.DataFrame(rows)

for et, dt_ in [(0.50, 0.50), (0.60, 0.60), (0.70, 0.70)]:
    df_r = backtest(et, dt_)
    df_r.to_csv(ROOT / f"strategy_entry_{et}_dir_{dt_}.csv", index=False)
    print(f"\n═══ Entry P(trend)>={et}, direction conf >= {dt_} ═══")
    for part in ["Dev", "Holdout", "Conf2026"]:
        sub = df_r[df_r.partition == part]
        if sub.empty:
            print(f"  {part}: no fires")
            continue
        wins = (sub.pnl_pips > 0).sum()
        hits = (sub.pnl_pips > 20).sum()
        print(f"  {part:9s}  fires={len(sub):4d}  "
              f"mean_pips={sub.pnl_pips.mean():+6.1f}  "
              f"median={sub.pnl_pips.median():+6.1f}  "
              f"win={wins/len(sub)*100:.1f}%  "
              f"hit20={hits/len(sub)*100:.1f}%  "
              f"MFE={sub.mfe_pips.mean():.1f}  "
              f"MAE={sub.mae_pips.mean():.1f}  "
              f"best={sub.pnl_pips.max():.1f}  "
              f"worst={sub.pnl_pips.min():.1f}  "
              f"total={sub.pnl_pips.sum():.1f}")
