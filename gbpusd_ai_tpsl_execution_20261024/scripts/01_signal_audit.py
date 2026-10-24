#!/usr/bin/env python3
"""Stage 1-2 — build the AI signal audit CSV.

Rebuilds the Phase 7 signal register and augments every row with:
  * Entry price (= close_at_cutoff, when the signal would be entered)
  * MFE in predicted direction (max favourable travel from entry until 22:00 UK)
  * MAE in predicted direction (max adverse travel)
  * Time (minutes) of MFE from entry
  * Original "hold to 21:00 UK" realised net PnL

Primary population: all 4,182 (date, hour-cutoff) model evaluations.
Executable sub-population: those where p_trend ≥ 0.5 and dir_confidence ≥ 0.5.

Outputs:
  outputs/nextres/ai_signal_audit.csv  (full 4,182-row audit)
  outputs/nextres/accuracy_check.txt    (reproduction of the 85% claim)
"""
from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.append(str(Path(__file__).parent.parent))
from census import CANDLES_26, CANDLES_EXT, _load_day_file, _uk_offset_hours  # noqa: E402

ROOT = Path("<research_workspace>/outputs")
OUT = ROOT / "nextres"
OUT.mkdir(parents=True, exist_ok=True)
SPREAD = 0.8   # round-trip cost assumption

reg = pd.read_csv(ROOT / "phase7" / "signal_register.csv")
reg["date"] = reg["date"].astype(str)

candle_cache: dict[str, pd.DataFrame] = {}
def load(date_str):
    if date_str in candle_cache:
        return candle_cache[date_str]
    for p in CANDLES_EXT.glob(f"{date_str}.csv"):
        df = _load_day_file(p, "BID"); candle_cache[date_str] = df; return df
    for p in CANDLES_26.glob(f"{date_str}.csv"):
        df = _load_day_file(p, "MID"); candle_cache[date_str] = df; return df
    return None


def _uk_end_utc(date_str, hour_uk):
    d = dt.date.fromisoformat(date_str)
    off = _uk_offset_hours(pd.Timestamp(d, tz="UTC"))
    return pd.Timestamp(d, tz="UTC") + pd.Timedelta(hours=hour_uk - off)


print(f"Auditing {len(reg)} signals ...")
rows = []
for _, r in reg.iterrows():
    df = load(r.date)
    if df is None:
        continue
    cutoff_ts = pd.Timestamp(r.cutoff_utc)
    end_22_ut = _uk_end_utc(r.date, 22)
    end_21_ut = _uk_end_utc(r.date, 21)
    after_22 = df[(df.ts > cutoff_ts) & (df.ts <= end_22_ut)].reset_index(drop=True)
    after_21 = df[(df.ts > cutoff_ts) & (df.ts <= end_21_ut)].reset_index(drop=True)
    if after_22.empty:
        continue

    entry = float(r.close_at_cutoff)
    dir_pred = r.dir_pred

    # MFE / MAE in predicted direction (until 22:00 UK)
    if dir_pred == "LONG":
        mfe_pips = (after_22.high.max()/10000 - entry) * 10000
        mae_pips = (entry - after_22.low.min()/10000) * 10000
        # Time to MFE: first bar whose high equals the running max within tolerance
        running_max = -1e9
        mfe_bar_idx = 0
        for i, bar in enumerate(after_22.itertuples()):
            if bar.high/10000 > running_max:
                running_max = bar.high/10000
                mfe_bar_idx = i
    else:
        mfe_pips = (entry - after_22.low.min()/10000) * 10000
        mae_pips = (after_22.high.max()/10000 - entry) * 10000
        running_min = 1e9
        mfe_bar_idx = 0
        for i, bar in enumerate(after_22.itertuples()):
            if bar.low/10000 < running_min:
                running_min = bar.low/10000
                mfe_bar_idx = i

    mfe_ts = after_22.ts.iloc[mfe_bar_idx]
    minutes_to_mfe = int((mfe_ts - cutoff_ts).total_seconds() / 60)

    # Original hold-to-21:00 UK exit (as per Phase 6 strategy_backtest)
    if after_21.empty:
        orig_exit_px = float(after_22.close.iloc[-1])/10000
        orig_exit_ts = after_22.ts.iloc[-1]
    else:
        orig_exit_px = float(after_21.close.iloc[-1])/10000
        orig_exit_ts = after_21.ts.iloc[-1]
    if dir_pred == "LONG":
        orig_gross = (orig_exit_px - entry) * 10000
    else:
        orig_gross = (entry - orig_exit_px) * 10000
    orig_net = orig_gross - SPREAD

    # Signal timestamps (UTC + UK local)
    hr = int(r.hour_uk)
    rows.append({
        "date": r.date, "basis": r.basis, "partition": r.partition,
        "hour_uk": hr,
        "signal_ts_utc": r.cutoff_utc,
        "signal_ts_uk_local":
            (cutoff_ts + pd.Timedelta(hours=_uk_offset_hours(pd.Timestamp(dt.date.fromisoformat(r.date), tz="UTC")))).isoformat(),
        "dir_pred": r.dir_pred,
        "p_trend": float(r.p_trend),
        "p_long":  float(r.p_long),
        "dir_confidence": float(r.dir_confidence),
        "entry_price": round(entry, 5),
        "would_fire_at_0.5":
            bool(float(r.p_trend) >= 0.5 and float(r.dir_confidence) >= 0.5),
        "would_fire_at_0.6":
            bool(float(r.p_trend) >= 0.6 and float(r.dir_confidence) >= 0.6),
        "would_fire_at_0.7":
            bool(float(r.p_trend) >= 0.7 and float(r.dir_confidence) >= 0.7),
        "true_trend_day": bool(r.true_trend_day),
        "true_direction": r.true_direction if pd.notna(r.true_direction) else None,
        "true_pips": float(r.true_pips) if pd.notna(r.true_pips) else None,
        "is_direction_correct_on_true_trend":
            bool(r.is_direction_correct_on_true_trend),
        "mfe_in_pred_dir_pips": round(mfe_pips, 2),
        "mae_in_pred_dir_pips": round(mae_pips, 2),
        "minutes_to_mfe": minutes_to_mfe,
        "mfe_time_utc": mfe_ts.isoformat(),
        "orig_exit_ts_utc": orig_exit_ts.isoformat(),
        "orig_exit_price": round(orig_exit_px, 5),
        "orig_realised_net_pips": round(orig_net, 2),
        "pips_before_cutoff_in_true_dir":
            float(r.pips_before_cutoff_in_true_dir)
            if pd.notna(r.pips_before_cutoff_in_true_dir) else None,
        "pips_after_cutoff_in_true_dir":
            float(r.pips_after_cutoff_in_true_dir)
            if pd.notna(r.pips_after_cutoff_in_true_dir) else None,
    })

audit = pd.DataFrame(rows)
audit.to_csv(OUT / "ai_signal_audit.csv", index=False)
print(f"Wrote {len(audit)} rows → {OUT/'ai_signal_audit.csv'}")

# ─── Stage 2 — reproduce the 85% figure ────────────────────────────
lines = ["Stage 2 — reproduce the 85% directional-accuracy claim",
         "=" * 72]
# Interpretation A: direction correct on true trend days, unconditional
for part in ["Dev", "Holdout", "Conf2026"]:
    sub = audit[audit.partition == part]
    for h in [7, 8, 9, 10, 11, 12]:
        s = sub[(sub.hour_uk == h) & sub.true_trend_day]
        if s.empty: continue
        acc = s.is_direction_correct_on_true_trend.mean()*100
        lines.append(f"  {part:9s} h={h:02d}  n_true_trend={len(s):4d}  "
                     f"direction_correct_%={acc:5.1f}")
lines.append("")
lines.append("Interpretation B: direction accuracy among MODEL FIRES on true trend days")
for part in ["Dev", "Holdout", "Conf2026"]:
    sub = audit[(audit.partition == part) & audit["would_fire_at_0.5"]]
    for h in [7, 8, 9, 10, 11, 12]:
        s = sub[(sub.hour_uk == h) & sub.true_trend_day]
        if s.empty: continue
        acc = (s.dir_pred == s.true_direction).mean()*100
        lines.append(f"  {part:9s} h={h:02d}  fires_on_trend={len(s):4d}  "
                     f"direction_correct_%={acc:5.1f}")
lines.append("")
lines.append("Interpretation C: direction accuracy among ALL FIRES (incl. non-trend-day)")
for part in ["Dev", "Holdout", "Conf2026"]:
    sub = audit[(audit.partition == part) & audit["would_fire_at_0.5"]]
    for h in [7, 8, 9, 10, 11, 12]:
        s = sub[sub.hour_uk == h]
        if s.empty: continue
        # On non-trend days there is no true direction — count as "not correct"
        # for this interpretation.
        correct = (s.true_trend_day & (s.dir_pred == s.true_direction)).sum()
        acc = correct / len(s) * 100
        lines.append(f"  {part:9s} h={h:02d}  all_fires={len(s):4d}  "
                     f"correct_%_(trend+right_dir)={acc:5.1f}")

acc_text = "\n".join(lines)
(OUT / "accuracy_check.txt").write_text(acc_text + "\n")
print("\n" + acc_text)
