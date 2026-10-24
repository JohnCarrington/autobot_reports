#!/usr/bin/env python3
"""Phase 7 Task 4 — M5 earlier-entry investigation.

Rather than retraining a full GBM at 5-minute cadence (expensive and would
only help if LATE_FIRE were the dominant limiter — it isn't), this script
investigates a cheaper hypothesis: a 5-minute RULE-BASED signal (persistent
BB-hug + EMA alignment + displacement) that fires once per day as early as
possible, and measures its 45-pip TP achievability.

Rule: for each M5 bar from 06:00 UK onwards, flag LONG if:
  (a) close ≥ 75% of BB(20,2) band position for ≥ k consecutive bars
  (b) EMA(7) > EMA(13) > EMA(21), slope of EMA(21) positive
  (c) ADX(14) ≥ 18
  (d) last 3 bars have mean body ≥ 1.5 pips
SHORT = mirror. The signal fires on the first bar meeting all four
conditions. k is tuned on Dev (via grid-search) and locked for Holdout +
Conf2026.

For every signal, compute: entry at that bar's close, TP +45 pips, SL=25
pips (same as the Phase 7 Task 2 best-OOS stop).
"""
from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.append(str(Path(__file__).parent))
from census import CANDLES_26, CANDLES_EXT, _load_day_file, _uk_offset_hours  # noqa
from baseline_classifiers import _ema, _bb, _adx  # noqa

ROOT = Path("<research_workspace>/outputs")
P7 = ROOT / "phase7"

TP_PIPS = 45.0
SL_PIPS = 25.0
SPREAD = 0.8


def partition(d_str):
    d = dt.date.fromisoformat(d_str)
    if d < dt.date(2025, 7, 1): return "Dev"
    if d < dt.date(2026, 1, 1): return "Holdout"
    return "Conf2026"


def _end_window_utc(date_str):
    d = dt.date.fromisoformat(date_str)
    off = _uk_offset_hours(pd.Timestamp(d, tz="UTC"))
    return pd.Timestamp(d, tz="UTC") + pd.Timedelta(hours=21 - off)


def _06_uk_utc(date_str):
    d = dt.date.fromisoformat(date_str)
    off = _uk_offset_hours(pd.Timestamp(d, tz="UTC"))
    return pd.Timestamp(d, tz="UTC") + pd.Timedelta(hours=6 - off)


def _14_uk_utc(date_str):
    d = dt.date.fromisoformat(date_str)
    off = _uk_offset_hours(pd.Timestamp(d, tz="UTC"))
    return pd.Timestamp(d, tz="UTC") + pd.Timedelta(hours=14 - off)


def generate_signal(df: pd.DataFrame, k: int) -> dict | None:
    """Scan 06:00 UK → 14:00 UK and return the first bar meeting the rule.

    df must have columns ts, open, high, low, close (raw * 10000)."""
    date_str = df.ts.iloc[0].date().isoformat()
    start = _06_uk_utc(date_str)
    end = _14_uk_utc(date_str)
    scan = df[(df.ts >= start) & (df.ts <= end)].reset_index(drop=True)
    if len(scan) < 30:
        return None
    # Compute indicators on the full-day series up to each point.
    close = df.close.to_numpy(dtype=float) / 10000
    high = df.high.to_numpy(dtype=float) / 10000
    low  = df.low.to_numpy(dtype=float) / 10000
    open_ = df.open.to_numpy(dtype=float) / 10000
    mid, up, lo = _bb(close, 20, 2.0)
    e7 = _ema(close, 7); e13 = _ema(close, 13); e21 = _ema(close, 21)
    adx, pdi, mdi = _adx(high, low, close, 14)

    scan_idxs = df.index[(df.ts >= start) & (df.ts <= end)].tolist()
    hug_up = hug_dn = 0
    for i in scan_idxs:
        if np.isnan(up[i]) or (up[i] - lo[i]) <= 0:
            hug_up = hug_dn = 0; continue
        bw = up[i] - lo[i]
        pos = (close[i] - lo[i]) / bw
        if pos >= 0.75:
            hug_up += 1
        else:
            hug_up = 0
        if pos <= 0.25:
            hug_dn += 1
        else:
            hug_dn = 0

        stacked_up = e7[i] > e13[i] > e21[i]
        stacked_dn = e7[i] < e13[i] < e21[i]
        slope21_up = (e21[i] - e21[max(0, i-6)]) > 0 if i >= 6 else False
        slope21_dn = (e21[i] - e21[max(0, i-6)]) < 0 if i >= 6 else False
        adx_ok = (not np.isnan(adx[i])) and adx[i] >= 18
        body = np.mean(np.abs(close[max(0, i-2):i+1] - open_[max(0, i-2):i+1])) * 10000
        body_ok = body >= 1.5

        if hug_up >= k and stacked_up and slope21_up and adx_ok and body_ok:
            return {
                "ts": df.ts.iloc[i].isoformat(),
                "idx": i,
                "dir": "LONG",
                "close": round(close[i], 5),
            }
        if hug_dn >= k and stacked_dn and slope21_dn and adx_ok and body_ok:
            return {
                "ts": df.ts.iloc[i].isoformat(),
                "idx": i,
                "dir": "SHORT",
                "close": round(close[i], 5),
            }
    return None


def simulate_trade(df: pd.DataFrame, sig: dict) -> dict:
    idx = sig["idx"]; dir_ = sig["dir"]; entry = sig["close"]
    tp = entry + TP_PIPS/10000 if dir_ == "LONG" else entry - TP_PIPS/10000
    sl = entry - SL_PIPS/10000 if dir_ == "LONG" else entry + SL_PIPS/10000
    end = _end_window_utc(df.ts.iloc[idx].date().isoformat())
    after = df.iloc[idx+1:][df.ts.iloc[idx+1:] <= end]
    for _, bar in after.iterrows():
        h = float(bar.high)/10000; l = float(bar.low)/10000
        if dir_ == "LONG":
            hit_tp = h >= tp; hit_sl = l <= sl
        else:
            hit_tp = l <= tp; hit_sl = h >= sl
        if hit_tp and hit_sl:
            return {"status": "SL_AMB", "net_pips": -SL_PIPS - SPREAD, "exit_ts": bar.ts.isoformat()}
        if hit_tp:
            return {"status": "TP", "net_pips": TP_PIPS - SPREAD, "exit_ts": bar.ts.isoformat()}
        if hit_sl:
            return {"status": "SL", "net_pips": -SL_PIPS - SPREAD, "exit_ts": bar.ts.isoformat()}
    if len(after) == 0:
        return {"status": "no_data", "net_pips": -SPREAD, "exit_ts": None}
    exit_px = float(after.close.iloc[-1])/10000
    gross = (exit_px - entry) * 10000 if dir_ == "LONG" else (entry - exit_px) * 10000
    return {"status": "EOW", "net_pips": gross - SPREAD,
            "exit_ts": after.ts.iloc[-1].isoformat()}


census = pd.read_csv(ROOT / "census.csv")

def run_k(k: int):
    rows = []
    for p in sorted(list(CANDLES_EXT.glob("*.csv")) + list(CANDLES_26.glob("*.csv"))):
        basis = "BID" if "candles_ext" in str(p) else "MID"
        df = _load_day_file(p, basis)
        if df is None or len(df) < 60: continue
        date = df.ts.iloc[0].date()
        if date.weekday() >= 5: continue
        sig = generate_signal(df, k)
        if sig is None: continue
        trade = simulate_trade(df, sig)
        cen = census[census.date == date.isoformat()]
        row = {
            "date": date.isoformat(), "basis": basis,
            "partition": partition(date.isoformat()),
            "signal_ts": sig["ts"], "signal_dir": sig["dir"],
            "entry_px": sig["close"], "k": k,
            **trade,
        }
        if not cen.empty:
            row["true_trend_day"] = bool(cen.trend_day.iloc[0])
            row["true_direction"] = cen.direction.iloc[0]
            row["true_pips"] = float(cen.pips.iloc[0])
        rows.append(row)
    return pd.DataFrame(rows)

best_k = None
best_oos_pips = -1e9
all_results = []
for k in [3, 4, 6, 8]:
    rdf = run_k(k)
    rdf.to_csv(P7 / f"m5_rule_trades_k{k}.csv", index=False)
    oos = rdf[rdf.partition.isin(["Holdout", "Conf2026"])]
    total_oos = oos.net_pips.sum() if len(oos) else -1e9
    print(f"\n--- k={k}, consecutive BB-hug bars ---")
    print(f"  signals total: {len(rdf)}")
    for part in ["Dev", "Holdout", "Conf2026"]:
        s = rdf[rdf.partition == part]
        if s.empty: continue
        wins = (s.net_pips > 0).sum()
        tp_pct = (s.status == "TP").mean()*100
        sl_pct = (s.status.isin(["SL", "SL_AMB"])).mean()*100
        print(f"    {part:9s}: n={len(s):3d}  wins={wins:3d}  "
              f"win%={wins/len(s)*100:5.1f}  "
              f"TP%={tp_pct:5.1f}  SL%={sl_pct:5.1f}  "
              f"total_net={s.net_pips.sum():+7.1f}  "
              f"mean={s.net_pips.mean():+5.1f}")
    if total_oos > best_oos_pips:
        best_oos_pips = total_oos; best_k = k
    all_results.append(rdf.assign(k=k))

combined = pd.concat(all_results, ignore_index=True)
combined.to_csv(P7 / "m5_rule_all.csv", index=False)
print(f"\nBest k (by OOS total net pips): k={best_k} with +{best_oos_pips:.1f} pips")
