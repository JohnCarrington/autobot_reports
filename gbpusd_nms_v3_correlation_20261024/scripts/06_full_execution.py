#!/usr/bin/env python3
"""Full-corpus execution test: TP30/SL12 and TP40/SL12 on every first-of-day
V3 STRONG fire. Session-end 22:00 UK, 0.8-pip round-trip spread,
conservative intrabar ambiguity (SL first)."""
from __future__ import annotations
import csv
import datetime as dt
import sys
from pathlib import Path

import pandas as pd

sys.path.append(str(Path(__file__).parent.parent))
from census import CANDLES_26, CANDLES_EXT, _load_day_file, _uk_offset_hours  # noqa

OUT = Path("<research_workspace>/outputs/nms_corr")
LIVE_CANDLES_26 = Path("<autobot_prod_root>/data/candles/GBPUSD")

tr = pd.read_csv(OUT / "v3_transitions.csv")
tr["ts_utc"] = pd.to_datetime(tr["ts_utc"])

# First-of-day STRONG fire for each day (either direction)
strong = tr[tr.to_state.isin(["STRONG_UP", "STRONG_DOWN"])].copy()
strong = strong.sort_values("ts_utc").drop_duplicates(["date"], keep="first")
print(f"First-of-day STRONG fires: {len(strong)}")

candle_cache: dict[str, pd.DataFrame] = {}
def load(date_str, basis):
    key = f"{date_str}|{basis}"
    if key in candle_cache:
        return candle_cache[key]
    for p in CANDLES_EXT.glob(f"{date_str}.csv"):
        df = _load_day_file(p, "BID"); candle_cache[key] = df; return df
    for p in CANDLES_26.glob(f"{date_str}.csv"):
        df = _load_day_file(p, "MID"); candle_cache[key] = df; return df
    for p in LIVE_CANDLES_26.glob(f"{date_str}.csv"):
        df = _load_day_file(p, "MID"); candle_cache[key] = df; return df
    return None


def _uk22_utc(date_str):
    d = dt.date.fromisoformat(date_str)
    off = _uk_offset_hours(pd.Timestamp(d, tz="UTC"))
    return pd.Timestamp(d, tz="UTC") + pd.Timedelta(hours=22 - off)


SPREAD = 0.8

def simulate(df, fire_ts, direction, tp, sl, date_str):
    end22 = _uk22_utc(date_str)
    after = df[(df.ts > fire_ts) & (df.ts <= end22)].reset_index(drop=True)
    if after.empty:
        return None
    entry_px = float(after.open.iloc[0]) / 10000
    if direction == "LONG":
        tp_px = entry_px + tp/10000; sl_px = entry_px - sl/10000
    else:
        tp_px = entry_px - tp/10000; sl_px = entry_px + sl/10000
    status = None; exit_px = None; exit_ts = None; ambiguous = False
    for _, bar in after.iterrows():
        hi = float(bar.high)/10000; lo = float(bar.low)/10000
        if direction == "LONG":
            htp = hi >= tp_px; hsl = lo <= sl_px
        else:
            htp = lo <= tp_px; hsl = hi >= sl_px
        if htp and hsl:
            status = "SL_ambiguous"; exit_px = sl_px; exit_ts = bar.ts; ambiguous = True; break
        if htp:
            status = "TP"; exit_px = tp_px; exit_ts = bar.ts; break
        if hsl:
            status = "SL"; exit_px = sl_px; exit_ts = bar.ts; break
    if status is None:
        status = "SESSION_END"
        exit_px = float(after.close.iloc[-1]) / 10000
        exit_ts = after.ts.iloc[-1]
    gross = ((exit_px - entry_px) if direction == "LONG" else (entry_px - exit_px)) * 10000
    net = gross - SPREAD
    return {
        "entry_ts": fire_ts.isoformat(),
        "entry_price": round(entry_px, 5),
        "exit_ts": exit_ts.isoformat() if hasattr(exit_ts, "isoformat") else str(exit_ts),
        "exit_price": round(exit_px, 5),
        "exit_reason": status,
        "net_pips": round(net, 2),
        "gross_pips": round(gross, 2),
        "duration_min": int((pd.Timestamp(exit_ts) - fire_ts).total_seconds()/60),
        "ambiguous": ambiguous,
    }


results_30 = []
results_40 = []
for _, s in strong.iterrows():
    date = s.date
    direction = "LONG" if s.to_state == "STRONG_UP" else "SHORT"
    df = load(date, s.basis)
    if df is None: continue
    for tp, bucket in [(30, results_30), (40, results_40)]:
        res = simulate(df, s.ts_utc, direction, tp, 12, date)
        if res is None: continue
        row = {
            "date": date, "partition": s.partition, "basis": s.basis,
            "v3_fire_state": s.to_state,
            "v3_pred_dir": direction,
            "tp_pips": tp, "sl_pips": 12,
            **res,
        }
        bucket.append(row)

pd.DataFrame(results_30).to_csv(OUT / "nms_tp30_sl12.csv", index=False)
pd.DataFrame(results_40).to_csv(OUT / "nms_tp40_sl12.csv", index=False)

# Partition + monthly summaries
summary_rows = []
monthly_rows = []
for tag, data in [("tp30_sl12", results_30), ("tp40_sl12", results_40)]:
    df_r = pd.DataFrame(data)
    df_r["year"] = df_r.date.str[:4]
    df_r["ym"] = df_r.date.str[:7]
    for part in ["Dev", "Holdout", "Conf2026", "ALL"]:
        sub = df_r if part == "ALL" else df_r[df_r.partition == part]
        if sub.empty: continue
        n = len(sub)
        tp_n = (sub.exit_reason == "TP").sum()
        sl_n = (sub.exit_reason.isin(["SL","SL_ambiguous"])).sum()
        se_n = (sub.exit_reason == "SESSION_END").sum()
        wins = (sub.net_pips > 0).sum()
        summary_rows.append({
            "scenario": tag, "partition": part,
            "trades": n,
            "tp_hit": int(tp_n), "sl_hit": int(sl_n), "se": int(se_n),
            "wins": int(wins),
            "win_rate_%": round(wins/n*100, 1),
            "tp_hit_%": round(tp_n/n*100, 1),
            "sl_hit_%": round(sl_n/n*100, 1),
            "total_net_pips": round(sub.net_pips.sum(), 1),
            "avg_net_per_trade": round(sub.net_pips.mean(), 2),
            "profit_factor": round(
                -sub[sub.net_pips>0].net_pips.sum()/sub[sub.net_pips<=0].net_pips.sum(), 2
                ) if (sub.net_pips<=0).sum() else None,
            "max_drawdown":
                round((sub.sort_values("date").net_pips.cumsum() -
                       sub.sort_values("date").net_pips.cumsum().cummax()).min(), 1),
            "median_duration_min": int(sub.duration_min.median()),
        })
    # Per-year
    for year, grp_y in df_r.groupby("year"):
        for part in ["Dev", "Holdout", "Conf2026"]:
            s = grp_y[grp_y.partition == part]
            if s.empty: continue
            summary_rows.append({
                "scenario": tag, "partition": f"{part}_{year}",
                "trades": len(s),
                "tp_hit": int((s.exit_reason == "TP").sum()),
                "sl_hit": int((s.exit_reason.isin(["SL","SL_ambiguous"])).sum()),
                "se": int((s.exit_reason == "SESSION_END").sum()),
                "wins": int((s.net_pips > 0).sum()),
                "win_rate_%": round((s.net_pips > 0).mean()*100, 1),
                "tp_hit_%": round((s.exit_reason == "TP").mean()*100, 1),
                "sl_hit_%": round(s.exit_reason.isin(["SL","SL_ambiguous"]).mean()*100, 1),
                "total_net_pips": round(s.net_pips.sum(), 1),
                "avg_net_per_trade": round(s.net_pips.mean(), 2),
                "profit_factor": None,
                "max_drawdown": None,
                "median_duration_min": int(s.duration_min.median()),
            })
    # Monthly
    for ym, grp in df_r.groupby("ym"):
        monthly_rows.append({
            "scenario": tag, "ym": ym, "trades": len(grp),
            "wins": int((grp.net_pips > 0).sum()),
            "tp_hit": int((grp.exit_reason == "TP").sum()),
            "sl_hit": int(grp.exit_reason.isin(["SL","SL_ambiguous"]).sum()),
            "net_pips": round(grp.net_pips.sum(), 1),
        })

sdf = pd.DataFrame(summary_rows)
sdf.to_csv(OUT / "nms_scenario_summary.csv", index=False)
pd.DataFrame(monthly_rows).to_csv(OUT / "nms_monthly_pnl.csv", index=False)

print("\n═══ TP30/SL12 — full corpus ═══")
print(sdf[(sdf.scenario == "tp30_sl12")].to_string(index=False))
print("\n═══ TP40/SL12 — full corpus ═══")
print(sdf[(sdf.scenario == "tp40_sl12")].to_string(index=False))
