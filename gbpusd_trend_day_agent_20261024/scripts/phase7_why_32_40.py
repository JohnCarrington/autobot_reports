#!/usr/bin/env python3
"""Phase 7 Task 3 — Diagnose why mean MFE is only 32–40 pips after fire.

For every FIRST-FIRE-PER-DAY signal, compute:
  * When did the swing START (anchor_time_utc from census)
  * When did the agent first fire (hour_uk × cutoff_utc)
  * delta_minutes_signal_to_anchor (negative = anchored BEFORE fire → late)
  * pips_before_signal_in_true_dir (pips of the true swing already done)
  * pips_remaining_after_signal_in_true_dir (pips still available)
  * MFE_in_predicted_direction / MAE_in_predicted_direction after fire
  * Classify limiter: LATE / WRONG_DIR / INSUFFICIENT_MOVE / FALSE_POSITIVE /
    GOOD_FIRE (any 45-pip achievable in true direction)

Output: outputs/phase7/why_limiter.csv and summary.
"""
from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.append(str(Path(__file__).parent))
from census import CANDLES_26, CANDLES_EXT, _load_day_file, _uk_offset_hours  # noqa

ROOT = Path("<research_workspace>/outputs")
P7 = ROOT / "phase7"

reg = pd.read_csv(P7 / "signal_register.csv")
reg["date"] = reg["date"].astype(str)
fires = pd.read_csv(P7 / "fires_first_per_day.csv")
fires["date"] = fires["date"].astype(str)

census = pd.read_csv(ROOT / "census.csv")
census["date"] = census["date"].astype(str)
m = fires.merge(census[["date", "basis", "trend_day", "direction", "pips",
                         "anchor_time_utc", "peak_time_utc",
                         "anchor_price", "peak_price"]],
                on=["date", "basis"], how="left",
                suffixes=("", "_census"))

# Load candles lazily
candle_cache: dict[str, pd.DataFrame] = {}
def load(date_str):
    if date_str in candle_cache:
        return candle_cache[date_str]
    for p in CANDLES_EXT.glob(f"{date_str}.csv"):
        df = _load_day_file(p, "BID"); candle_cache[date_str] = df; return df
    for p in CANDLES_26.glob(f"{date_str}.csv"):
        df = _load_day_file(p, "MID"); candle_cache[date_str] = df; return df
    return None


def _end_window(date_str):
    d = dt.date.fromisoformat(date_str)
    off = _uk_offset_hours(pd.Timestamp(d, tz="UTC"))
    return pd.Timestamp(d, tz="UTC") + pd.Timedelta(hours=21 - off)


rows = []
for _, r in m.iterrows():
    df_m5 = load(r.date)
    if df_m5 is None:
        continue
    cutoff = pd.Timestamp(r.cutoff_utc)
    entry_px = float(r.close_at_cutoff)
    after = df_m5[(df_m5.ts > cutoff) & (df_m5.ts <= _end_window(r.date))]
    before = df_m5[df_m5.ts <= cutoff]

    if r.dir_pred == "LONG":
        mfe_pred_dir = (after.high.max()/10000 - entry_px) * 10000 if len(after) else 0.0
        mae_pred_dir = (entry_px - after.low.min()/10000) * 10000 if len(after) else 0.0
    else:
        mfe_pred_dir = (entry_px - after.low.min()/10000) * 10000 if len(after) else 0.0
        mae_pred_dir = (after.high.max()/10000 - entry_px) * 10000 if len(after) else 0.0

    # true-direction MFE (if trend day)
    if pd.notna(r.direction) and len(after):
        if r.direction == "LONG":
            mfe_true_dir = (after.high.max()/10000 - entry_px) * 10000
        else:
            mfe_true_dir = (entry_px - after.low.min()/10000) * 10000
    else:
        mfe_true_dir = None

    # pips_before_signal (in true direction)
    pips_before_true = None
    if pd.notna(r.anchor_price) and pd.notna(r.direction):
        if r.direction == "LONG":
            pips_before_true = max(0.0, (before.high.max()/10000 - r.anchor_price) * 10000) \
                               if len(before) else 0.0
        else:
            pips_before_true = max(0.0, (r.anchor_price - before.low.min()/10000) * 10000) \
                               if len(before) else 0.0

    # Classify limiter
    limiter = None
    tp_true_dir = (mfe_true_dir or 0.0) >= 45  # 45 pips achievable in true dir
    tp_pred_dir = mfe_pred_dir >= 45

    if not r.trend_day:
        limiter = "FALSE_POSITIVE"
    elif r.dir_pred != r.direction:
        limiter = "WRONG_DIR"
    elif tp_pred_dir and tp_true_dir:
        limiter = "GOOD_FIRE"
    elif not tp_true_dir:
        # trend day with correct direction prediction but <45 remaining
        if pips_before_true is not None and pips_before_true > 0.5 * (r.pips or 0.0):
            limiter = "LATE_FIRE_INSUFFICIENT_REMAIN"
        else:
            limiter = "INSUFFICIENT_MOVE_ALL_DIRECTIONS"
    else:
        limiter = "UNDETERMINED"

    # Delta minutes signal-to-anchor
    delta_min = None
    if pd.notna(r.anchor_time_utc):
        anchor = pd.Timestamp(r.anchor_time_utc)
        delta_min = int((cutoff - anchor).total_seconds() / 60)  # positive = fire AFTER anchor

    rows.append({
        "date": r.date, "basis": r.basis, "partition": r.partition,
        "hour_uk": int(r.hour_uk),
        "p_trend": float(r.p_trend), "p_long": float(r.p_long),
        "dir_pred": r.dir_pred, "true_direction": r.direction,
        "true_trend_day": bool(r.trend_day),
        "true_pips": float(r.pips) if pd.notna(r.pips) else None,
        "entry_px": round(entry_px, 5),
        "mfe_pred_dir_pips": round(mfe_pred_dir, 2),
        "mae_pred_dir_pips": round(mae_pred_dir, 2),
        "mfe_true_dir_pips": round(mfe_true_dir, 2) if mfe_true_dir is not None else None,
        "pips_before_signal_in_true_dir":
            round(pips_before_true, 2) if pips_before_true is not None else None,
        "minutes_signal_minus_anchor": delta_min,
        "tp45_reachable_pred_dir": bool(tp_pred_dir),
        "tp45_reachable_true_dir": bool(tp_true_dir),
        "limiter": limiter,
    })
df = pd.DataFrame(rows)
df.to_csv(P7 / "why_limiter.csv", index=False)
print(f"n={len(df)}")

print("\n═══ Limiter classification by partition ═══")
pt = df.groupby(["partition", "limiter"]).size().unstack("limiter").fillna(0).astype(int)
print(pt.to_string())
print("\nPercentages:")
print((pt.div(pt.sum(axis=1), axis=0) * 100).round(1).to_string())

print("\n═══ MFE distribution by limiter class (Conf2026 + Holdout) ═══")
oos = df[df.partition.isin(["Conf2026", "Holdout"])]
print(oos.groupby("limiter").mfe_pred_dir_pips.describe()[
    ["count", "mean", "50%", "75%", "max"]].round(1).to_string())

print("\n═══ Late-fire magnitude on true trend days (Conf2026 + Holdout) ═══")
trnd = oos[oos.true_trend_day]
print(f"Mean pips_before_signal (in true dir): "
      f"{trnd.pips_before_signal_in_true_dir.mean():.1f}")
print(f"Mean true_pips: {trnd.true_pips.mean():.1f}")
print(f"% of trend-day fires with >50% move already done: "
      f"{(trnd.pips_before_signal_in_true_dir / trnd.true_pips > 0.5).mean() * 100:.1f}%")
print(f"% with >75% move already done: "
      f"{(trnd.pips_before_signal_in_true_dir / trnd.true_pips > 0.75).mean() * 100:.1f}%")
print(f"% with >=45 pips remaining in TRUE direction: "
      f"{(trnd.mfe_true_dir_pips >= 45).mean() * 100:.1f}%")
print(f"% with >=45 pips remaining in PREDICTED direction: "
      f"{(trnd.mfe_pred_dir_pips >= 45).mean() * 100:.1f}%")

# Deliverable: aggregate numbers for the final report
cause_summary = []
for part in ["Dev", "Holdout", "Conf2026"]:
    sub = df[df.partition == part]
    tot = len(sub)
    cause_summary.append({
        "partition": part,
        "n_fires": tot,
        "GOOD_FIRE_%": round((sub.limiter == "GOOD_FIRE").mean() * 100, 1),
        "FALSE_POSITIVE_%": round((sub.limiter == "FALSE_POSITIVE").mean() * 100, 1),
        "WRONG_DIR_%": round((sub.limiter == "WRONG_DIR").mean() * 100, 1),
        "LATE_INSUFFICIENT_%":
            round((sub.limiter == "LATE_FIRE_INSUFFICIENT_REMAIN").mean() * 100, 1),
        "SMALL_TRUE_MOVE_%":
            round((sub.limiter == "INSUFFICIENT_MOVE_ALL_DIRECTIONS").mean() * 100, 1),
        "undetermined_%":
            round((sub.limiter == "UNDETERMINED").mean() * 100, 1),
    })
sum_df = pd.DataFrame(cause_summary)
sum_df.to_csv(P7 / "limiter_summary.csv", index=False)
print("\n═══ Headline limiter summary ═══")
print(sum_df.to_string(index=False))
